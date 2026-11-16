"""
Универсальный парсер товаров интернет-магазинов.

Схема работы:
    URL (категория или карточка)
      ├─ карточка товара  -> разбор карточки
      └─ страница каталога -> сбор ссылок на товары + обход пагинации
                              -> загрузка и разбор каждой карточки

Разбор карточки не привязан к конкретному сайту и объединяет все доступные источники:
    1. Schema.org JSON-LD (Product, BreadcrumbList)
    2. Microdata (itemprop=...)
    3. Таблицы / списки характеристик (tr th|td, dl dt/dd, "Имя: значение")
    4. OpenGraph / meta-теги
Штрихкод приводится к формату EAN-13 с проверкой контрольной суммы.
"""

import re
import json
import time
import hashlib
import logging
from datetime import date
from typing import List, Dict, Any, Optional, Iterable, Tuple
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass
class ScrapedProduct:
    title: str
    vendor_code: str
    barcode: str
    price: float
    manufacturer: str
    category: str                       # Код категории (латиница, UPPER_SNAKE)
    category_name: Optional[str] = None  # Человекочитаемое название категории
    warranty_months: int = 12
    release_year: Optional[int] = None
    dimensions_mm: Optional[str] = None
    weight_kg: Optional[float] = None
    voltage: Optional[str] = None
    power_watts: Optional[float] = None
    color: Optional[str] = None
    source_url: str = ""
    barcode_source: str = "site"        # site | generated
    specs: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# EAN-13
# =============================================================================

def validate_ean13(code: str) -> bool:
    """Проверка контрольной суммы EAN-13 (алгоритм modulo 10)."""
    if not code or len(code) != 13 or not code.isdigit():
        return False
    digits = [int(c) for c in code]
    checksum = sum(digits[i] * (1 if i % 2 == 0 else 3) for i in range(12))
    return (10 - (checksum % 10)) % 10 == digits[12]


def calculate_ean13_check_digit(twelve_digits: str) -> str:
    """Вычисление 13-й контрольной цифры для 12-значного префикса EAN-13."""
    digits = [int(c) for c in twelve_digits[:12]]
    checksum = sum(digits[i] * (1 if i % 2 == 0 else 3) for i in range(12))
    return str((10 - (checksum % 10)) % 10)


def generate_fallback_ean13(seed: str) -> str:
    """
    Генерация валидного внутреннего штрихкода GS1 (префикс 200 — "in-store" диапазон).
    Используется, только если на сайте нет корректного штрихкода.
    """
    num = int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16)
    twelve = "200" + f"{num % 1_000_000_000:09d}"
    return twelve + calculate_ean13_check_digit(twelve)


def normalize_ean13(raw: Any) -> Optional[str]:
    """
    Приводит штрихкод с сайта к EAN-13. Возвращает None, если код невалиден.
    - 13 цифр с корректной контрольной суммой — как есть
    - 12 цифр (UPC-A) — дополняется лидирующим 0 (GTIN-13)
    - 14 цифр (GTIN-14) с лидирующим 0 — отбрасывается 0
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 14 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12:
        digits = "0" + digits
    return digits if validate_ean13(digits) else None


def ensure_valid_ean13(raw_barcode: Optional[str], fallback_seed: str) -> str:
    """Валидный EAN-13 с сайта, иначе — сгенерированный внутренний код."""
    return normalize_ean13(raw_barcode) or generate_fallback_ean13(fallback_seed)


def find_ean13_candidates(text: str) -> List[str]:
    """Все валидные EAN-13 в произвольной строке (в ячейке может быть несколько кодов)."""
    found = []
    for chunk in re.findall(r"\d[\d\s\-]{10,16}\d", text or ""):
        code = normalize_ean13(chunk)
        if code and code not in found:
            found.append(code)
    return found


# =============================================================================
# Вспомогательные функции
# =============================================================================

def clean_price(text: Optional[str]) -> float:
    """Извлечение числового значения цены из текстовой строки."""
    if text is None:
        return 0.0
    text = str(text).replace("\xa0", "").replace(" ", "").replace(" ", "")
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    if not m:
        return 0.0
    try:
        return max(0.0, float(m.group(0).replace(",", ".")))
    except ValueError:
        return 0.0


def _norm_space(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def category_code_from_name(name: str) -> str:
    """'Телевизоры' -> 'TELEVIZORY' (код категории для справочника)."""
    latin = "".join(_TRANSLIT.get(ch, ch) for ch in name.lower())
    code = re.sub(r"[^a-z0-9]+", "_", latin).strip("_").upper()
    return (code or "GENERAL_EQUIPMENT")[:50]


def _first(props: Dict[str, str], patterns: Iterable[str]) -> Optional[str]:
    """Первое значение характеристики, имя которой совпадает с одним из regex-шаблонов."""
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for k, v in props.items():
            if rx.search(k) and v not in (None, ""):
                return str(v)
    return None


# Шаблоны имён характеристик (рус./англ.)
KEY_BARCODE = [r"штрих.?код", r"\bean\b", r"ean.?13", r"\bgtin", r"barcode", r"\bupc\b"]
KEY_VENDOR_CODE = [r"^артикул", r"^код товара", r"^sku$", r"^арт\.?$", r"^код$", r"vendor.?code"]
KEY_PART_NUMBER = [r"партномер", r"part.?number", r"^mpn$", r"модель производителя", r"^p/?n$"]
KEY_BRAND = [r"^бренд", r"^производитель", r"^brand", r"^manufacturer", r"^марка", r"^торговая марка"]
KEY_WARRANTY = [r"гаранти", r"warranty"]
KEY_WEIGHT = [r"^вес", r"масса", r"weight"]
KEY_DIMENSIONS = [r"габарит", r"размер.*\(.*\)", r"^размеры", r"dimensions", r"ш\s*[xх×]\s*в\s*[xх×]\s*г"]
KEY_COLOR = [r"^цвет", r"colou?r"]
KEY_POWER = [r"потребляемая мощность", r"^мощность", r"power"]
KEY_VOLTAGE = [r"напряжение", r"voltage"]
KEY_YEAR = [r"год (выпуска|релиза|анонса)", r"release"]


# =============================================================================
# Парсер
# =============================================================================

class UniversalProductScraper:
    """
    Универсальный скрапер каталогов и карточек товаров любых интернет-магазинов.
    """

    def __init__(self, timeout: int = 20, delay: float = 0.3, verify_ssl: bool = True,
                 trust_env: bool = True, retries: int = 2):
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=verify_ssl,
            trust_env=trust_env,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        self._last_request = 0.0

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -------------------------------------------------------------------------
    # HTTP
    # -------------------------------------------------------------------------
    def fetch_html(self, url: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.client.get(url)
                self._last_request = time.monotonic()
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.text
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                self._last_request = time.monotonic()
                last_exc = e
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    # -------------------------------------------------------------------------
    # Точка входа
    # -------------------------------------------------------------------------
    def scrape(self, url: str, max_items: int = 30, max_pages: int = 50,
               follow_details: bool = True) -> List[ScrapedProduct]:
        """
        Парсинг любого URL: карточки товара или страницы категории (с пагинацией).
        :param max_items: максимальное число товаров
        :param max_pages: максимальное число страниц пагинации каталога
        :param follow_details: заходить в карточку каждого товара (полные данные + штрихкод)
        """
        html = self.fetch_html(url)
        soup = BeautifulSoup(html, "lxml")

        # Карточка товара (блоки "похожие товары" на ней не должны превращать её в каталог)
        if self._is_product_page(soup):
            product = self.parse_product_page(html, url)
            return [product] if product else []

        links = self._extract_product_links(soup, url)

        if not links:
            # Неизвестная разметка каталога: пробуем вытащить хотя бы карточку
            product = self.parse_product_page(html, url)
            return [product] if product else []

        # Обход пагинации до набора нужного количества ссылок
        visited_pages = {self._canon(url)}
        page_url, page_soup, page_no = url, soup, 1
        while len(links) < max_items and page_no < max_pages:
            next_url = self._find_next_page(page_soup, page_url)
            if not next_url or self._canon(next_url) in visited_pages:
                break
            visited_pages.add(self._canon(next_url))
            try:
                page_soup = BeautifulSoup(self.fetch_html(next_url), "lxml")
            except Exception as e:
                logger.warning("Не удалось загрузить страницу %s: %s", next_url, e)
                break
            page_url, page_no = next_url, page_no + 1
            new_links = [l for l in self._extract_product_links(page_soup, page_url) if l not in links]
            if not new_links:
                break
            links.extend(new_links)
            logger.info("Страница %d: +%d товаров (всего %d)", page_no, len(new_links), len(links))

        links = links[:max_items]
        if not follow_details:
            return [p for p in (self._product_from_link_only(l) for l in links) if p]

        products: List[ScrapedProduct] = []
        for i, link in enumerate(links, 1):
            try:
                product = self.parse_product_page(self.fetch_html(link), link)
                if product:
                    products.append(product)
                    logger.info("[%d/%d] %s | %s", i, len(links), product.barcode, product.title[:60])
            except Exception as e:
                logger.warning("[%d/%d] Ошибка карточки %s: %s", i, len(links), link, e)
        return products

    # -------------------------------------------------------------------------
    # Каталог: ссылки на товары
    # -------------------------------------------------------------------------
    def _extract_product_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        host = urlparse(base_url).netloc
        base_canon = self._canon(base_url)
        result: List[str] = []

        def add(href: Optional[str]):
            if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
                return
            full = urljoin(base_url, href).split("#")[0]
            if urlparse(full).netloc != host or self._canon(full) == base_canon:
                return
            if full not in result:
                result.append(full)

        # 1. JSON-LD ItemList / OfferCatalog
        for data in self._iter_json_ld(soup):
            if self._type_is(data, "ItemList", "OfferCatalog"):
                for el in data.get("itemListElement") or []:
                    if isinstance(el, dict):
                        item = el.get("item") if isinstance(el.get("item"), dict) else el
                        add(item.get("url") or el.get("url"))
        if len(result) >= 2:
            return result

        # 2. Bitrix (стандартный шаблон каталога: data-entity="item")
        for card in soup.select('[data-entity="item"]'):
            a = (card.select_one("a.name[href], .name a[href], .product-item-title a[href], a[itemprop=url]")
                 or card.select_one("a[href]:not([href^='javascript'])"))
            if a:
                add(a.get("href"))
        if len(result) >= 2:
            return result

        # 3. Microdata: несколько itemscope Product на странице
        md = soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)})
        if len(md) >= 2:
            for item in md:
                u = item.find(attrs={"itemprop": "url"})
                a = u if u is not None else item.find("a", href=True)
                if a is not None:
                    add(a.get("href") or a.get("content"))
            if len(result) >= 2:
                return result

        # 4. Эвристика: ссылки с названием, рядом с которыми есть цена
        price_rx = re.compile(r"\d[\d\s ]{2,}\s*(?:₽|руб|р\.|RUB|\$|€)", re.I)
        groups: Dict[str, List[str]] = {}
        for a in soup.find_all("a", href=True):
            text = _norm_space(a.get_text(" ")) or a.get("title", "")
            if len(text) < 12:
                continue
            node, has_price = a.parent, False
            for _ in range(5):
                if node is None or node.name in ("body", "html"):
                    break
                if price_rx.search(node.get_text(" ")) and len(node.get_text(" ")) < 3000:
                    has_price = True
                    break
                node = node.parent
            if not has_price or node is None:
                continue
            sig = f"{node.name}.{'.'.join(sorted(node.get('class') or []))}"
            full = urljoin(base_url, a["href"]).split("#")[0]
            if urlparse(full).netloc == host and self._canon(full) != base_canon:
                groups.setdefault(sig, [])
                if full not in groups[sig]:
                    groups[sig].append(full)
        if groups:
            best = max(groups.values(), key=len)
            if len(best) >= 2:
                for u in best:
                    add(u)
        return result

    def _find_next_page(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        # rel=next
        el = soup.select_one('link[rel="next"][href], a[rel="next"][href]')
        if el:
            return urljoin(current_url, el["href"])
        # Явная кнопка "следующая"
        for sel in [".pagination a.next", ".pagination .next a", "a.next", "a.pagination-next",
                    "[class*=pagin] a[class*=next]", "[class*=pager] a[class*=next]",
                    "li.next a", ".modern-page-next"]:
            el = soup.select_one(sel)
            if el and el.get("href") and not el["href"].startswith(("javascript", "#")):
                return urljoin(current_url, el["href"])
        # Ссылка с номером текущей страницы + 1
        page_rx = re.compile(r"(?:[?&](?:PAGEN_\d+|page|p|pg|pagenum)=(\d+))|(?:/page[/-]?(\d+))", re.I)
        m = page_rx.search(current_url)
        current = int(m.group(1) or m.group(2)) if m else 1
        for a in soup.find_all("a", href=True):
            m = page_rx.search(a["href"])
            if m and int(m.group(1) or m.group(2)) == current + 1:
                return urljoin(current_url, a["href"])
        return None

    @staticmethod
    def _canon(url: str) -> str:
        p = urlparse(url)
        query = urlencode(sorted(parse_qsl(p.query)))
        return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", query, ""))

    def _is_product_page(self, soup: BeautifulSoup) -> bool:
        """Страница одного товара, а не каталог."""
        ld_products = [n for n in self._iter_json_ld(soup) if self._type_is(n, "Product", "ProductModel")]
        if any(self._type_is(n, "ItemList", "OfferCatalog") for n in self._iter_json_ld(soup)):
            return False
        if len(ld_products) == 1:
            return True
        og = self._meta(soup, "og:type")
        if og and "product" in og.lower():
            return True
        md_products = soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)})
        top_level_md = [m for m in md_products
                        if not m.find_parent(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)})]
        if len(top_level_md) == 1 and top_level_md[0].find(attrs={"itemprop": "price"}):
            return True
        # Таблица характеристик с артикулом/штрихкодом
        props = self._spec_tables(soup)
        keys = " | ".join(props.keys())
        if len(props) >= 3 and re.search(r"штрих.?код|артикул|\bean\b|gtin|\bsku\b|партномер", keys, re.I):
            return True
        return False

    def _product_from_link_only(self, url: str) -> Optional[ScrapedProduct]:
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        title = slug.replace("_", " ").replace("-", " ")
        code = f"GEN-{hashlib.md5(url.encode()).hexdigest()[:10]}"
        return ScrapedProduct(title=title, vendor_code=code, barcode=generate_fallback_ean13(code),
                              price=0.0, manufacturer="Не указан", category="GENERAL_EQUIPMENT",
                              source_url=url, barcode_source="generated")

    # -------------------------------------------------------------------------
    # Карточка товара
    # -------------------------------------------------------------------------
    def parse_product_page(self, html: str, url: str) -> Optional[ScrapedProduct]:
        soup = BeautifulSoup(html, "lxml")

        ld = self._json_ld_product(soup)
        md = self._microdata(soup)
        props = self._spec_tables(soup)

        # additionalProperty из JSON-LD — это тоже характеристики
        for ap in self._as_list(ld.get("additionalProperty")):
            if isinstance(ap, dict) and ap.get("name") and ap.get("value") not in (None, ""):
                props.setdefault(str(ap["name"]), str(ap["value"]))

        # --- Название
        title = _norm_space(
            self._str(ld.get("name")) or md.get("name")
            or (soup.h1.get_text(" ") if soup.h1 else "")
            or self._meta(soup, "og:title")
            or (soup.title.get_text() if soup.title else "")
        )
        if not title:
            return None

        # --- Штрихкод
        raw_barcode_values: List[str] = []
        for key in ("gtin13", "gtin", "gtin12", "gtin14", "ean", "barcode"):
            if ld.get(key):
                raw_barcode_values.append(str(ld[key]))
            if md.get(key):
                raw_barcode_values.append(md[key])
        for k, v in props.items():
            if any(re.search(p, k, re.I) for p in KEY_BARCODE):
                raw_barcode_values.append(v)

        all_codes: List[str] = []
        for v in raw_barcode_values:
            for c in find_ean13_candidates(v):
                if c not in all_codes:
                    all_codes.append(c)
        if not all_codes:
            # Последний шанс: текст страницы рядом со словом "штрихкод"/"EAN"
            text = soup.get_text(" ")
            for m in re.finditer(r"(?:штрих.?код|ean.?13|\bean\b|gtin|barcode)\D{0,30}([\d\s\-]{12,18})", text, re.I):
                all_codes.extend(c for c in find_ean13_candidates(m.group(1)) if c not in all_codes)

        # --- Артикул / партномер
        part_number = _first(props, KEY_PART_NUMBER) or self._str(ld.get("mpn")) or md.get("mpn")
        vendor_code = (_first(props, KEY_VENDOR_CODE) or self._str(ld.get("sku")) or md.get("sku")
                       or part_number)
        if not vendor_code:
            vendor_code = f"GEN-{hashlib.md5(url.encode()).hexdigest()[:10]}"
        vendor_code = _norm_space(vendor_code)

        if all_codes:
            barcode, barcode_source = all_codes[0], "site"
        else:
            barcode, barcode_source = generate_fallback_ean13(f"{urlparse(url).netloc}:{vendor_code}"), "generated"

        # --- Бренд
        brand = ld.get("brand") or ld.get("manufacturer")
        if isinstance(brand, list):
            brand = brand[0] if brand else None
        if isinstance(brand, dict):
            brand = brand.get("name")
        manufacturer = _norm_space(_first(props, KEY_BRAND) or self._str(brand) or md.get("brand") or "")
        if not manufacturer:
            manufacturer = self._brand_from_title(title) or "Не указан"

        # --- Цена
        offers = ld.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        offers = offers if isinstance(offers, dict) else {}
        price_raw = (offers.get("price") or offers.get("lowPrice") or md.get("price")
                     or self._meta(soup, "product:price:amount"))
        if price_raw is None:
            el = soup.select_one('[itemprop="price"], .product-price, .price .value, .price, [class*="price"]')
            price_raw = el.get("content") if el is not None and el.get("content") else (el.get_text(" ") if el else None)
        price = clean_price(price_raw)
        currency = offers.get("priceCurrency") or md.get("priceCurrency") or self._meta(soup, "product:price:currency")
        availability = offers.get("availability") or md.get("availability")

        # --- Категория (хлебные крошки)
        breadcrumbs = self._breadcrumbs(soup, title)
        category_name = (breadcrumbs[-1] if breadcrumbs else None) or self._str(ld.get("category"))
        if category_name and ">" in category_name:
            category_name = category_name.split(">")[-1].strip()
        if category_name:
            category_code = category_code_from_name(category_name)
        else:
            category_code = self._guess_category(title, url)
            category_name = category_code.replace("_", " ").title()

        # --- Описание и изображения
        description = _norm_space(
            self._str(ld.get("description")) or md.get("description")
            or self._meta(soup, "og:description") or self._meta(soup, "description", attr="name") or ""
        )
        images = self._images(soup, ld, url)

        # --- Физические характеристики
        warranty = self._parse_warranty(_first(props, KEY_WARRANTY))
        weight = self._parse_weight(_first(props, KEY_WEIGHT)) or self._parse_weight(title)
        dimensions = _first(props, KEY_DIMENSIONS)
        color = _first(props, KEY_COLOR) or self._str(ld.get("color")) or self._extract_color(title)
        power = self._parse_number(_first(props, KEY_POWER))
        voltage = _first(props, KEY_VOLTAGE)
        year_raw = _first(props, KEY_YEAR)
        year_m = re.search(r"(19|20)\d{2}", year_raw or "")
        release_year = int(year_m.group(0)) if year_m else None

        specs: Dict[str, Any] = dict(props)
        specs.update({
            "_source_url": url,
            "_source_site": urlparse(url).netloc,
            "_scraped_at": date.today().isoformat(),
            "_part_number": part_number,
            "_price": price,
            "_currency": currency,
            "_availability": availability,
            "_breadcrumbs": breadcrumbs,
            "_description": description[:5000] if description else None,
            "_images": images,
            "_barcode_source": barcode_source,
            "_all_barcodes": all_codes,
            "_raw_barcode_values": raw_barcode_values or None,
        })
        specs = {k: v for k, v in specs.items() if v not in (None, "", [], {})}

        return ScrapedProduct(
            title=title,
            vendor_code=vendor_code,
            barcode=barcode,
            price=price,
            manufacturer=manufacturer,
            category=category_code,
            category_name=category_name,
            warranty_months=warranty if warranty is not None else 12,
            release_year=release_year,
            dimensions_mm=dimensions[:100] if dimensions else None,
            weight_kg=weight,
            voltage=voltage[:50] if voltage else None,
            power_watts=power,
            color=color[:50] if color else None,
            source_url=url,
            barcode_source=barcode_source,
            specs=specs,
        )

    # -------------------------------------------------------------------------
    # Источники данных карточки
    # -------------------------------------------------------------------------
    @staticmethod
    def _as_list(x) -> list:
        if x is None:
            return []
        return x if isinstance(x, list) else [x]

    @staticmethod
    def _str(x) -> Optional[str]:
        if x is None or isinstance(x, (dict, list)):
            return None
        s = str(x).strip()
        return s or None

    @staticmethod
    def _type_is(node: dict, *types: str) -> bool:
        t = node.get("@type")
        ts = t if isinstance(t, list) else [t]
        return any(str(x) in types for x in ts if x)

    def _iter_json_ld(self, soup: BeautifulSoup):
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text() or "")
            except Exception:
                continue
            stack = self._as_list(data)
            while stack:
                node = stack.pop(0)
                if not isinstance(node, dict):
                    continue
                yield node
                if "@graph" in node:
                    stack.extend(self._as_list(node["@graph"]))

    def _json_ld_product(self, soup: BeautifulSoup) -> Dict[str, Any]:
        for node in self._iter_json_ld(soup):
            if self._type_is(node, "Product", "ProductModel", "IndividualProduct"):
                return node
        return {}

    @staticmethod
    def _microdata(soup: BeautifulSoup) -> Dict[str, str]:
        """itemprop-свойства внутри (первого) itemscope Product, либо по всей странице."""
        root = soup.find(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)}) or soup
        allowed_nested = re.compile(r"schema\.org/(Offer|AggregateOffer)", re.I)
        result: Dict[str, str] = {}
        for el in root.find_all(attrs={"itemprop": True}):
            key = el["itemprop"]
            if key in result:
                continue
            # Свойства вложенных сущностей (PropertyValue, Brand, Review...) не относятся к товару
            scope = el.find_parent(attrs={"itemscope": True})
            if scope is not None and scope is not root and not allowed_nested.search(scope.get("itemtype", "")):
                continue
            val = el.get("content") or el.get("href") or el.get("src") or el.get_text(" ")
            val = _norm_space(val)
            if val:
                result[key] = val
        return result

    @staticmethod
    def _spec_tables(soup: BeautifulSoup) -> Dict[str, str]:
        """Таблицы/списки характеристик: tr(th|td, td), dl(dt, dd), li 'Имя: значение'."""
        props: Dict[str, str] = {}

        def put(k: str, v: str):
            k, v = _norm_space(k).rstrip(":").strip(), _norm_space(v)
            if k and v and k != v and len(k) <= 120 and len(v) <= 2000 and k not in props:
                props[k] = v

        for tr in soup.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) == 2:
                put(cells[0].get_text(" "), cells[1].get_text(" "))

        for dl in soup.find_all("dl"):
            for dt in dl.find_all("dt"):
                dd = dt.find_next_sibling("dd")
                if dd:
                    put(dt.get_text(" "), dd.get_text(" "))

        # Контейнеры с характеристиками в div/li-вёрстке
        name_rx = re.compile(r"(prop|char|spec|param|feature|attr).*(name|title|label|key)|^(name|label)$", re.I)
        value_rx = re.compile(r"(prop|char|spec|param|feature|attr).*(val|value)|^value$", re.I)
        for name_el in soup.find_all(class_=name_rx):
            parent = name_el.parent
            if not isinstance(parent, Tag):
                continue
            val_el = parent.find(class_=value_rx)
            if val_el and val_el is not name_el:
                put(name_el.get_text(" "), val_el.get_text(" "))

        container_rx = re.compile(r"char|spec|propert|param|feature|attribute|характ", re.I)
        for cont in soup.find_all(class_=container_rx):
            for li in cont.find_all("li"):
                text = _norm_space(li.get_text(" "))
                if ":" in text and len(text) < 300:
                    k, v = text.split(":", 1)
                    put(k, v)
        return props

    def _breadcrumbs(self, soup: BeautifulSoup, title: str) -> List[str]:
        crumbs: List[str] = []
        for node in self._iter_json_ld(soup):
            if self._type_is(node, "BreadcrumbList"):
                for el in sorted(self._as_list(node.get("itemListElement")),
                                 key=lambda e: int(e.get("position", 0)) if isinstance(e, dict) else 0):
                    if isinstance(el, dict):
                        name = el.get("name")
                        if not name and isinstance(el.get("item"), dict):
                            name = el["item"].get("name")
                        if name:
                            crumbs.append(_norm_space(str(name)))
                break
        if not crumbs:
            bc = soup.select_one('[itemtype*="BreadcrumbList"], .breadcrumbs, .breadcrumb, '
                                 '[class*="breadcrumb"], nav[aria-label*="crumb" i]')
            if bc:
                items = bc.select('[itemprop="name"]') or bc.select("a, span:not(:has(*))")
                for el in items:
                    t = _norm_space(el.get_text(" "))
                    if t and t not in crumbs and t not in ("/", "»", ">", "→"):
                        crumbs.append(t)
        skip = {"главная", "home", "каталог", "каталог товаров", "catalog", "магазин", "товары"}
        crumbs = [c for c in crumbs if c.lower() not in skip and c != title and len(c) < 100]
        return crumbs

    def _images(self, soup: BeautifulSoup, ld: Dict[str, Any], url: str) -> List[str]:
        imgs: List[str] = []
        for x in self._as_list(ld.get("image")):
            if isinstance(x, dict):
                x = x.get("url") or x.get("contentUrl")
            if x:
                imgs.append(urljoin(url, str(x)))
        og = self._meta(soup, "og:image")
        if og:
            imgs.append(urljoin(url, og))
        for el in soup.select('[itemprop="image"]'):
            src = el.get("content") or el.get("src") or el.get("href")
            if src:
                imgs.append(urljoin(url, src))
        seen, result = set(), []
        for i in imgs:
            if i not in seen and not re.search(r"no-?photo|placeholder|nophoto", i, re.I):
                seen.add(i)
                result.append(i)
        return result[:20]

    @staticmethod
    def _meta(soup: BeautifulSoup, name: str, attr: str = "property") -> Optional[str]:
        el = soup.find("meta", attrs={attr: name}) or soup.find("meta", attrs={"name": name})
        return el.get("content") if el and el.get("content") else None

    # -------------------------------------------------------------------------
    # Разбор значений
    # -------------------------------------------------------------------------
    @staticmethod
    def _parse_number(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        m = re.search(r"\d+(?:[.,]\d+)?", text.replace("\xa0", "").replace(" ", ""))
        return float(m.group(0).replace(",", ".")) if m else None

    @staticmethod
    def _parse_warranty(text: Optional[str]) -> Optional[int]:
        if not text:
            return None
        m = re.search(r"\d+", text)
        if not m:
            return None
        n = int(m.group(0))
        if re.search(r"год|лет|year", text, re.I):
            n *= 12
        return n

    @staticmethod
    def _parse_weight(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(кг|kg|г|g)\b", text, re.I)
        if m:
            v = float(m.group(1).replace(",", "."))
            return round(v / 1000, 3) if m.group(2).lower() in ("г", "g") else v
        return None

    @staticmethod
    def _extract_color(text: str) -> Optional[str]:
        colors = ["черный", "чёрный", "белый", "серый", "серебристый", "синий", "красный", "золотой",
                  "black", "white", "gray", "grey", "silver", "blue", "red", "gold"]
        t = text.lower()
        for c in colors:
            if re.search(rf"\b{c}\b", t):
                return c.capitalize()
        return None

    KNOWN_BRANDS = [
        "Samsung", "LG", "Sony", "Philips", "Xiaomi", "Haier", "Hisense", "TCL", "BBK", "Hyundai", "Skyworth",
        "Toshiba", "Panasonic", "Sharp", "Thomson", "Telefunken", "Polarline", "Harper", "Starwind", "Supra",
        "HP", "Dell", "Lenovo", "Asus", "Acer", "MSI", "Apple", "Huawei", "Honor", "Gigabyte", "AOC", "BenQ",
        "ViewSonic", "Iiyama", "Raskat", "Digma", "Dexp", "Vitek", "Bosch", "Beko", "Indesit", "Gorenje",
        "Electrolux", "Redmond", "Polaris", "Scarlett", "Kingston", "Transcend", "SanDisk", "Defender",
        "Logitech", "A4Tech", "Canon", "Epson", "Brother", "Kyocera", "Pantum", "TP-Link", "D-Link",
        "Keenetic", "Mikrotik", "Tenda", "Zyxel",
    ]

    @classmethod
    def _brand_from_title(cls, title: str) -> Optional[str]:
        """Запасное определение бренда по названию, если на сайте нет поля "Бренд/Производитель"."""
        for b in cls.KNOWN_BRANDS:
            if re.search(rf"(?<![\w-]){re.escape(b)}(?![\w-])", title, re.I):
                return b
        return None

    @staticmethod
    def _guess_category(title: str, url: str) -> str:
        """Запасной классификатор, если на странице нет хлебных крошек."""
        combined = (title + " " + url).lower()
        mapping = {
            "TELEVIZORY": ["телевизор", "tv "],
            "MONITORS": ["монитор", "monitor"],
            "LAPTOPS": ["ноутбук", "laptop", "ultrabook"],
            "USB_ACCESSORIES": ["usb", "флеш", "flash", "кабель", "хаб", "адаптер", "переходник"],
            "KITCHEN_APPLIANCES": ["варочн", "плита", "кофемолк", "кофеварк", "чайник", "блендер", "микроволновк"],
            "NETWORK_EQUIPMENT": ["роутер", "router", "коммутатор", "маршрутизатор"],
            "PERIPHERALS": ["мышь", "клавиатура", "гарнитура", "наушники", "принтер", "мфу"],
        }
        for code, keywords in mapping.items():
            if any(k in combined for k in keywords):
                return code
        return "GENERAL_EQUIPMENT"
