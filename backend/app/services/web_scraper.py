import re
import json
import hashlib
import urllib.request
import ssl
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

@dataclass
class ScrapedProduct:
    title: str
    vendor_code: str
    barcode: str
    price: float
    manufacturer: str
    category: str
    warranty_months: int = 12
    release_year: int = 2024
    dimensions_mm: Optional[str] = None
    weight_kg: Optional[float] = None
    voltage: Optional[str] = None
    power_watts: Optional[float] = None
    color: Optional[str] = None
    source_url: str = ""
    specs: Dict[str, Any] = field(default_factory=dict)

def validate_ean13(code: str) -> bool:
    """Проверка контрольной суммы EAN-13 (алгоритм modulo 10)."""
    if not code or len(code) != 13 or not code.isdigit():
        return False
    digits = [int(c) for c in code]
    checksum = sum(digits[i] * (1 if i % 2 == 0 else 3) for i in range(12))
    check_digit = (10 - (checksum % 10)) % 10
    return check_digit == digits[12]

def calculate_ean13_check_digit(twelve_digits: str) -> str:
    """Вычисление 13-й контрольной цифры для 12-значного префикса EAN-13."""
    digits = [int(c) for c in twelve_digits[:12]]
    checksum = sum(digits[i] * (1 if i % 2 == 0 else 3) for i in range(12))
    check_digit = (10 - (checksum % 10)) % 10
    return str(check_digit)

def generate_fallback_ean13(seed: str) -> str:
    """
    Генерация валидного GS1 внутреннего штрихкода (диапазон 200..299 для ритейла).
    Используется как страховка, если на стороннем сайте штрихкод не указан в открытом виде.
    """
    md5_hash = hashlib.md5(seed.encode("utf-8")).hexdigest()
    num = int(md5_hash[:8], 16)
    nine_digits = f"{num % 1_000_000_000:09d}"
    twelve = "200" + nine_digits
    return twelve + calculate_ean13_check_digit(twelve)

def ensure_valid_ean13(raw_barcode: Optional[str], fallback_seed: str) -> str:
    """
    Приведение любого входящего штрихкода к строгому 13-значному формату EAN-13.
    Поддерживает:
    - Чистый 13-значный EAN-13
    - 12-значный UPC-A (дополняется лидирующим 0 по стандарту GS1 GTIN-13)
    - Fallback-генерацию с гарантированной контрольной суммой
    """
    if raw_barcode:
        digits_only = re.sub(r"\D", "", str(raw_barcode))
        if len(digits_only) == 13 and validate_ean13(digits_only):
            return digits_only
        if len(digits_only) == 12:
            upc_as_ean = "0" + digits_only
            if validate_ean13(upc_as_ean):
                return upc_as_ean
        if len(digits_only) == 13:
            # Исправляем контрольную цифру, если сайт выдал опечатку
            corrected = digits_only[:12] + calculate_ean13_check_digit(digits_only[:12])
            return corrected

    return generate_fallback_ean13(fallback_seed)

def clean_price(text: Optional[str]) -> float:
    """Извлечение числового значения цены из текстовой строки."""
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d,\.]", "", text.replace(" ", "").replace("\xa0", ""))
    cleaned = cleaned.replace(",", ".")
    try:
        val = float(cleaned)
        return max(0.0, val)
    except ValueError:
        return 0.0

class UniversalProductScraper:
    """
    Универсальный скрапер карточек товаров и каталогов.
    Поддерживает специализированные адаптеры (Tehnoformula, Spectrasoft)
    и универсальный Schema.org / Microdata / Heuristic парсер для любых магазинов.
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    def fetch_html(self, url: str) -> str:
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=self.timeout) as resp:
            content_type = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(content_type, errors="ignore")

    def scrape(self, url: str, max_items: int = 30) -> List[ScrapedProduct]:
        """Точка входа парсинга любого URL."""
        html = self.fetch_html(url)
        domain = urlparse(url).netloc.lower()

        if "tehnoformula.ru" in domain:
            products = self._parse_tehnoformula(html, url, max_items)
            if products:
                return products
        elif "spectrasoft.ru" in domain:
            products = self._parse_spectrasoft(html, url, max_items)
            if products:
                return products

        # Универсальный парсинг для любых сайтов
        # 1. Попытка через Schema.org JSON-LD
        products = self._parse_json_ld(html, url, max_items)
        if products:
            return products

        # 2. Попытка через микроразметку Microdata
        products = self._parse_microdata(html, url, max_items)
        if products:
            return products

        # 3. Универсальная HTML-эвристика
        return self._parse_heuristic(html, url, max_items)

    # -------------------------------------------------------------------------
    # Адаптер: Tehnoformula (Каталоги и карточки)
    # -------------------------------------------------------------------------
    def _parse_tehnoformula(self, html: str, base_url: str, max_items: int) -> List[ScrapedProduct]:
        soup = BeautifulSoup(html, "lxml")
        products = []

        # 1. Проверяем, это листинг каталога?
        cards = soup.select('[data-entity="item"]')
        if not cards:
            cards = soup.select('.product-card-list') or soup.select('.product-card')

        seen_codes = set()
        if cards:
            for card in cards:
                if len(products) >= max_items:
                    break
                name_el = card.select_one(".name a") or card.select_one(".name")
                if not name_el:
                    continue
                title = name_el.get_text(strip=True)
                item_url = urljoin(base_url, name_el.get("href", "")) if name_el.name == "a" else base_url

                desc_div = card.select_one(".desc")
                desc_text = desc_div.get_text("\n", strip=True) if desc_div else ""

                # Извлекаем метаданные из описания
                art_match = re.search(r"Артикул:\s*([^\n\r\|]+)", desc_text, re.IGNORECASE)
                vendor_code = art_match.group(1).strip() if art_match else ""

                part_match = re.search(r"Партномер:\s*([^\n\r\|]+)", desc_text, re.IGNORECASE)
                part_number = part_match.group(1).strip() if part_match else ""
                if not vendor_code:
                    vendor_code = part_number or f"TF-{hashlib.md5(title.encode()).hexdigest()[:8]}"

                if vendor_code in seen_codes:
                    continue
                seen_codes.add(vendor_code)

                brand_match = re.search(r"Бренд:\s*([^\n\r\|]+)", desc_text, re.IGNORECASE)
                manufacturer = brand_match.group(1).strip() if brand_match else "Не указан"

                war_match = re.search(r"WARRANTY:\s*(\d+)", desc_text, re.IGNORECASE)
                warranty = int(war_match.group(1)) if war_match else 12

                barcode_match = re.search(r"Штрихкод:\s*([0-9]+)", desc_text, re.IGNORECASE)
                raw_barcode = barcode_match.group(1).strip() if barcode_match else None
                barcode = ensure_valid_ean13(raw_barcode, vendor_code or title)

                price_el = card.select_one(".price-container") or card.select_one(".price")
                price = clean_price(price_el.get_text(strip=True) if price_el else "0")

                # Определяем категорию по URL или названию
                category = self._guess_category(title, item_url)

                # ТТХ
                specs = {
                    "Артикул": vendor_code,
                    "Партномер": part_number,
                    "Гарантия_мес": warranty,
                    "Бренд": manufacturer
                }

                # Извлекаем цвет, вес и габариты из названия
                weight = self._extract_weight(title)
                color = self._extract_color(title)

                products.append(ScrapedProduct(
                    title=title,
                    vendor_code=vendor_code,
                    barcode=barcode,
                    price=price,
                    manufacturer=manufacturer,
                    category=category,
                    warranty_months=warranty,
                    release_year=2024,
                    weight_kg=weight,
                    color=color,
                    source_url=item_url,
                    specs=specs
                ))
            if products:
                return products

        # 2. Если это одиночная карточка товара на Tehnoformula
        h1 = soup.select_one("h1")
        if h1:
            title = h1.get_text(strip=True)
            barcode_match = re.search(r"Штрихкод:\s*([0-9]+)", html, re.IGNORECASE)
            raw_barcode = barcode_match.group(1).strip() if barcode_match else None
            art_match = re.search(r"Артикул:\s*([^\n\r<]+)", html, re.IGNORECASE)
            vendor_code = art_match.group(1).strip() if art_match else f"TF-{hashlib.md5(title.encode()).hexdigest()[:8]}"
            barcode = ensure_valid_ean13(raw_barcode, vendor_code)
            brand_match = re.search(r"Бренд:\s*([^\n\r<]+)", html, re.IGNORECASE)
            manufacturer = brand_match.group(1).strip() if brand_match else "Не указан"
            price_el = soup.select_one(".price, .price-container")
            price = clean_price(price_el.get_text(strip=True) if price_el else "0")
            category = self._guess_category(title, base_url)

            return [ScrapedProduct(
                title=title,
                vendor_code=vendor_code,
                barcode=barcode,
                price=price,
                manufacturer=manufacturer,
                category=category,
                warranty_months=12,
                release_year=2024,
                source_url=base_url,
                specs={"Артикул": vendor_code, "Бренд": manufacturer}
            )]

        return []

    # -------------------------------------------------------------------------
    # Адаптер: Spectrasoft (Детальные карточки и характеристики)
    # -------------------------------------------------------------------------
    def _parse_spectrasoft(self, html: str, base_url: str, max_items: int) -> List[ScrapedProduct]:
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.select_one("h1")
        if not h1:
            return []

        title = h1.get_text(strip=True)
        props: Dict[str, str] = {}

        for tr in soup.select("tr[itemprop=\"additionalProperty\"], .item_properties tr, .properties tr, table tr"):
            name_el = tr.select_one(".property_name, [itemprop=\"name\"], th, td:first-child")
            val_el = tr.select_one(".property_value, [itemprop=\"value\"], td:last-child")
            if name_el and val_el:
                k = name_el.get_text(strip=True)
                v = val_el.get_text(strip=True)
                if k and v and k != v:
                    props[k] = v

        vendor_code = props.get("АРТИКУЛ") or props.get("Артикул") or props.get("Партномер")
        if not vendor_code:
            vendor_code = f"SS-{hashlib.md5(title.encode()).hexdigest()[:8]}"

        raw_barcode = props.get("Штрихкод") or props.get("EAN") or props.get("GTIN")
        barcode = ensure_valid_ean13(raw_barcode, vendor_code)

        manufacturer = props.get("Производитель") or props.get("Бренд")
        if not manufacturer:
            # Пытаемся извлечь из названия: e.g. "Raskat"
            for b in ["Raskat", "Samsung", "LG", "HP", "Dell", "Asus", "Acer", "ViewSonic", "Lenovo"]:
                if b.lower() in title.lower():
                    manufacturer = b
                    break
        manufacturer = manufacturer or "Raskat"

        warranty = 12
        if "WARRANTY" in props or "Гарантия" in props:
            war_txt = props.get("WARRANTY") or props.get("Гарантия")
            m = re.search(r"\d+", str(war_txt))
            if m:
                warranty = int(m.group(0))

        price_el = soup.select_one(".price, [itemprop=\"price\"]")
        price = clean_price(price_el.get_text(strip=True) if price_el else "0")

        category = props.get("Категория") or self._guess_category(title, base_url)
        weight = self._extract_weight(title + " " + json.dumps(props, ensure_ascii=False))
        color = self._extract_color(title + " " + json.dumps(props, ensure_ascii=False))

        return [ScrapedProduct(
            title=title,
            vendor_code=vendor_code,
            barcode=barcode,
            price=price,
            manufacturer=manufacturer,
            category=category,
            warranty_months=warranty,
            release_year=2024,
            weight_kg=weight,
            color=color,
            source_url=base_url,
            specs=props
        )]

    # -------------------------------------------------------------------------
    # Универсальный парсер 1: Schema.org JSON-LD
    # -------------------------------------------------------------------------
    def _parse_json_ld(self, html: str, base_url: str, max_items: int) -> List[ScrapedProduct]:
        soup = BeautifulSoup(html, "lxml")
        products = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for node in items:
                if not isinstance(node, dict):
                    continue

                # Обработка @graph
                graph_nodes = node.get("@graph", [node])
                for item in graph_nodes:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("@type", "")
                    if "Product" in str(item_type):
                        title = item.get("name") or soup.find("h1")
                        if not title:
                            continue
                        title = title.get_text(strip=True) if hasattr(title, "get_text") else str(title)

                        sku = str(item.get("sku") or item.get("mpn") or f"GEN-{hashlib.md5(title.encode()).hexdigest()[:8]}")
                        raw_barcode = item.get("gtin13") or item.get("gtin") or item.get("gtin8") or item.get("barcode")
                        barcode = ensure_valid_ean13(raw_barcode, sku)

                        brand = item.get("brand")
                        if isinstance(brand, dict):
                            manufacturer = brand.get("name", "Не указан")
                        else:
                            manufacturer = str(brand or "Не указан")

                        offers = item.get("offers", {})
                        if isinstance(offers, list) and offers:
                            offers = offers[0]
                        price = clean_price(str(offers.get("price", "0"))) if isinstance(offers, dict) else 0.0

                        products.append(ScrapedProduct(
                            title=title,
                            vendor_code=sku,
                            barcode=barcode,
                            price=price,
                            manufacturer=manufacturer,
                            category=self._guess_category(title, base_url),
                            warranty_months=12,
                            release_year=2024,
                            source_url=base_url,
                            specs=item
                        ))
                        if len(products) >= max_items:
                            return products

        return products

    # -------------------------------------------------------------------------
    # Универсальный парсер 2: Microdata (itemscope itemtype="*Product*")
    # -------------------------------------------------------------------------
    def _parse_microdata(self, html: str, base_url: str, max_items: int) -> List[ScrapedProduct]:
        soup = BeautifulSoup(html, "lxml")
        products = []

        items = soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Product", re.IGNORECASE)})
        for item in items:
            name_el = item.find(attrs={"itemprop": "name"})
            if not name_el:
                continue
            title = name_el.get_text(strip=True)

            sku_el = item.find(attrs={"itemprop": re.compile(r"^(sku|mpn)$")})
            sku = sku_el.get_text(strip=True) if sku_el else f"GEN-{hashlib.md5(title.encode()).hexdigest()[:8]}"

            barcode_el = item.find(attrs={"itemprop": re.compile(r"^(gtin13|gtin|barcode)$")})
            raw_barcode = barcode_el.get_text(strip=True) if barcode_el else None
            barcode = ensure_valid_ean13(raw_barcode, sku)

            brand_el = item.find(attrs={"itemprop": "brand"})
            manufacturer = brand_el.get_text(strip=True) if brand_el else "Не указан"

            price_el = item.find(attrs={"itemprop": "price"})
            price = clean_price(price_el.get_text(strip=True) if price_el else "0")

            products.append(ScrapedProduct(
                title=title,
                vendor_code=sku,
                barcode=barcode,
                price=price,
                manufacturer=manufacturer,
                category=self._guess_category(title, base_url),
                warranty_months=12,
                release_year=2024,
                source_url=base_url,
                specs={}
            ))
            if len(products) >= max_items:
                break

        return products

    # -------------------------------------------------------------------------
    # Универсальный парсер 3: Эвристический разбор HTML
    # -------------------------------------------------------------------------
    def _parse_heuristic(self, html: str, base_url: str, max_items: int) -> List[ScrapedProduct]:
        soup = BeautifulSoup(html, "lxml")

        h1 = soup.select_one("h1") or soup.select_one("meta[property=\"og:title\"]")
        title = ""
        if h1:
            title = h1.get("content") if h1.name == "meta" else h1.get_text(strip=True)
        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        if not title:
            return []

        # Поиск штрихкода по тексту страницы
        barcode_match = re.search(r"(?:штрихкод|штрих-код|barcode|ean-13|ean|gtin)[:\s]+([0-9]{12,13})", html, re.IGNORECASE)
        raw_barcode = barcode_match.group(1).strip() if barcode_match else None

        # Артикул
        art_match = re.search(r"(?:артикул|код товара|sku|part number|партномер)[:\s]+([a-zA-Z0-9_\-\.]+)", html, re.IGNORECASE)
        vendor_code = art_match.group(1).strip() if art_match else f"ART-{hashlib.md5(title.encode()).hexdigest()[:8]}"

        barcode = ensure_valid_ean13(raw_barcode, vendor_code)

        # Цена
        price_el = soup.select_one(".price, [class*=\"price\"], meta[property=\"product:price:amount\"]")
        price = 0.0
        if price_el:
            price_text = price_el.get("content") if price_el.name == "meta" else price_el.get_text(strip=True)
            price = clean_price(price_text)

        # Бренд
        brand_match = re.search(r"(?:бренд|производитель|brand|manufacturer)[:\s]+([a-zA-Zа-яА-Я0-9_\-]+)", html, re.IGNORECASE)
        manufacturer = brand_match.group(1).strip() if brand_match else "Не указан"

        specs = {}
        for tr in soup.select("table tr, dl"):
            text = tr.get_text(" ", strip=True)
            if ":" in text:
                parts = text.split(":", 1)
                specs[parts[0].strip()[:50]] = parts[1].strip()[:100]

        return [ScrapedProduct(
            title=title,
            vendor_code=vendor_code,
            barcode=barcode,
            price=price,
            manufacturer=manufacturer,
            category=self._guess_category(title, base_url),
            warranty_months=12,
            release_year=2024,
            source_url=base_url,
            specs=specs
        )]

    # -------------------------------------------------------------------------
    # Вспомогательные классификаторы
    # -------------------------------------------------------------------------
    def _guess_category(self, title: str, url: str) -> str:
        combined = (title + " " + url).lower()
        mapping = {
            "monitors": ["монитор", "monitor", "дисплей", "display"],
            "laptops": ["ноутбук", "laptop", "ultrabook", "нетбук"],
            "usb_accessories": ["usb", "флеш", "flash", "кабель", "хаб", "адаптер", "переходник"],
            "kitchen_appliances": ["варочн", "плита", "кофемолк", "кофеварк", "чайник", "блендер", "микроволновк"],
            "network_equipment": ["роутер", "router", "коммутатор", "switch", "маршрутизатор"],
            "peripherals": ["мышь", "клавиатура", "гарнитура", "наушники", "принтер", "мфу"]
        }
        for code, keywords in mapping.items():
            if any(k in combined for k in keywords):
                return code.upper()
        return "GENERAL_EQUIPMENT"

    def _extract_weight(self, text: str) -> Optional[float]:
        m = re.search(r"(\d+(?:[\.,]\d+)?)\s*(?:кг|kg)\b", text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                pass
        return None

    def _extract_color(self, text: str) -> Optional[str]:
        colors = ["черный", "black", "белый", "white", "серый", "gray", "серебристый", "silver", "синий", "blue", "красный", "red"]
        t = text.lower()
        for c in colors:
            if c in t:
                return c.capitalize()
        return None
