import pytest
import sys
import os
from httpx import AsyncClient, ASGITransport

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from app.main import app
from app.services.web_scraper import (
    UniversalProductScraper, validate_ean13, ensure_valid_ean13, generate_fallback_ean13
)

def test_ean13_algorithms():
    """Проверка математики контрольной суммы EAN-13 и UPC-конвертера."""
    # Известные валидные штрихкоды
    assert validate_ean13("8690842695162") is True  # Beko с Техноформулы
    assert validate_ean13("2000011929374") is True  # Спектрасофт
    assert validate_ean13("4630143181081") is True  # Vitek

    # Невалидные штрихкоды
    assert validate_ean13("8690842695163") is False
    assert validate_ean13("12345") is False
    assert validate_ean13("abcdefghijklm") is False

    # UPC-12 конвертация в EAN-13
    upc_12 = "766907035070"
    converted = ensure_valid_ean13(upc_12, "test_seed")
    assert len(converted) == 13
    assert converted == "0766907035070"
    assert validate_ean13(converted) is True

    # Fallback генератор (диапазон 200..299)
    fallback = generate_fallback_ean13("arbitrary_item_without_barcode")
    assert len(fallback) == 13
    assert fallback.startswith("200")
    assert validate_ean13(fallback) is True

def test_scraper_live_extraction():
    """Проверка живого извлечения данных с сайтов-образцов."""
    scraper = UniversalProductScraper(timeout=10)

    # 1. Tehnoformula каталог
    tf_items = scraper.scrape("https://tehnoformula.ru/product/usb/?PAGEN_1=2&view_mode=list", max_items=2)
    assert len(tf_items) >= 1
    first_tf = tf_items[0]
    assert len(first_tf.barcode) == 13
    assert validate_ean13(first_tf.barcode) is True
    assert first_tf.manufacturer != ""
    assert first_tf.category != ""

    # 2. Spectrasoft карточка монитора
    ss_items = scraper.scrape(
        "https://spectrasoft.ru/items/monitor_bad_pack_31_5_raskat_i32q16d_32_ips_2560x1440_hdmi_dp_5ms_178_178_1000_1_165hz_black.html",
        max_items=1
    )
    assert len(ss_items) == 1
    mon = ss_items[0]
    assert mon.barcode == "2000011929374"
    assert validate_ean13(mon.barcode) is True
    assert "Raskat" in mon.title or "Raskat" in mon.manufacturer

@pytest.mark.asyncio
async def test_api_parser_preview_endpoint():
    """Тест эндпоинта предпросмотра без записи в базу /api/parser/preview-url."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login_res = await ac.post("/api/auth/login", data={"username": "engineer_1", "password": "TechPass2026!"})
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        target_url = "https://spectrasoft.ru/items/monitor_bad_pack_31_5_raskat_i32q16d_32_ips_2560x1440_hdmi_dp_5ms_178_178_1000_1_165hz_black.html"
        prev_res = await ac.get(f"/api/parser/preview-url?url={target_url}&max_items=1", headers=headers)
        assert prev_res.status_code == 200
        data = prev_res.json()
        assert data["total_extracted"] == 1
        assert data["products"][0]["barcode"] == "2000011929374"
        assert data["products"][0]["is_ean13_valid"] is True

@pytest.mark.asyncio
async def test_api_scrape_and_immediate_scan():
    """
    Сквозной интеграционный сценарий:
    1. Парсим товар по живому URL через API -> сохраняем в БД с EAN-13.
    2. Мгновенно выполняем диагностику по новому штрихкоду через сканер (/api/diagnostics/scan).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login_res = await ac.post("/api/auth/login", data={"username": "admin_stepan", "password": "AdminPass2026!"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Загрузка товара из внешнего URL
        scrape_payload = {
            "url": "https://tehnoformula.ru/product/usb/?PAGEN_1=2&view_mode=list",
            "max_items": 3,
            "department_id": 1
        }
        res = await ac.post("/api/parser/scrape-url", json=scrape_payload, headers=headers)
        assert res.status_code == 200
        protocol = res.json()
        assert protocol["total_scraped"] >= 1
        imported_or_existing = protocol["imported_count"] + protocol["already_exists_count"]
        assert imported_or_existing >= 1

        first_barcode = protocol["items"][0]["barcode"]
        assert len(first_barcode) == 13

        # 2. Сканирование мобильным клиентом
        scan_payload = {
            "barcode": first_barcode,
            "department_id": 1,
            "observed_symptoms": "Плановая приёмка оборудования из внешнего каталога"
        }
        scan_res = await ac.post("/api/diagnostics/scan", json=scan_payload, headers=headers)
        assert scan_res.status_code == 200
        scan_data = scan_res.json()
        assert scan_data["scanned_barcode"] == first_barcode
        assert "diagnostic_conclusion" in scan_data
        assert "equipment_id" in scan_data
