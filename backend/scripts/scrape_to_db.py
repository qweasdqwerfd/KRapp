#!/usr/bin/env python3
"""
Автономный скрипт веб-парсинга каталогов и карточек товаров в базу данных PostgreSQL.
Использование:
    python scripts/scrape_to_db.py --url "https://tehnoformula.ru/product/televizory/" --limit 200
    python scripts/scrape_to_db.py --url "https://tehnoformula.ru/product/televizory/" --limit 5 --dry-run --show-specs
    python scripts/scrape_to_db.py --url "https://spectrasoft.ru/items/monitor_bad_pack_31_5_raskat_i32q16d_32_ips_2560x1440_hdmi_dp_5ms_178_178_1000_1_165hz_black.html"
"""

import sys
import os
import argparse
import asyncio
import json
import logging

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

# Добавляем директорию backend в sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(BASE_DIR)

from app.services.web_scraper import UniversalProductScraper, validate_ean13
from app.services.product_ingestion import ingest_scraped_products
from app.core.database import AsyncSessionLocal

async def main():
    parser = argparse.ArgumentParser(description="Парсер товаров и EAN-13 штрихкодов в БД курсовой работы")
    parser.add_argument("--url", required=True, help="URL каталога или карточки товара")
    parser.add_argument("--limit", type=int, default=15, help="Максимальное количество позиций для парсинга")
    parser.add_argument("--dept", type=int, default=None, help="ID сервисного отдела (по умолчанию 1)")
    parser.add_argument("--max-pages", type=int, default=50, help="Максимум страниц пагинации каталога")
    parser.add_argument("--no-details", action="store_true", help="Не заходить в карточки товаров (быстро, но без ТТХ/штрихкодов)")
    parser.add_argument("--delay", type=float, default=0.3, help="Пауза между HTTP-запросами, сек")
    parser.add_argument("--no-proxy", action="store_true", help="Игнорировать HTTP(S)_PROXY из окружения")
    parser.add_argument("--show-specs", action="store_true", help="Вывести все извлечённые характеристики (JSON)")
    parser.add_argument("--dry-run", action="store_true", help="Только спарсить без записи в базу данных")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    print(f"\n=======================================================")
    print(f"🚀 ЗАПУСК ВЕБ-ПАРСЕРА ТОВАРОВ И ШТРИХКОДОВ EAN-13")
    print(f"=======================================================")
    print(f"Целевой URL: {args.url}")
    print(f"Лимит позиций: {args.limit}")
    print(f"Режим dry-run: {args.dry_run}\n")

    try:
        with UniversalProductScraper(delay=args.delay, trust_env=not args.no_proxy) as scraper:
            products = scraper.scrape(
                args.url, max_items=args.limit, max_pages=args.max_pages,
                follow_details=not args.no_details,
            )
    except Exception as e:
        print(f"❌ Ошибка сетевого запроса или парсинга: {e}")
        sys.exit(1)

    if not products:
        print("⚠️ Не найдено ни одного товара на странице!")
        sys.exit(0)

    print(f"✅ Успешно извлечено {len(products)} позиций из внешнего источника:")

    table_data = []
    for i, p in enumerate(products, 1):
        is_valid = validate_ean13(p.barcode)
        if not is_valid:
            status_icon = "🔴 Невалидный"
        elif p.barcode_source == "site":
            status_icon = "🟢 с сайта"
        else:
            status_icon = "🟡 сгенерирован"
        table_data.append([
            i,
            p.barcode,
            status_icon,
            p.manufacturer[:15],
            p.title[:35] + ("..." if len(p.title) > 35 else ""),
            f"{p.price:,.2f} ₽",
            p.category_name or p.category
        ])

    headers = ["#", "Штрихкод", "Статус EAN-13", "Бренд", "Наименование", "Цена", "Категория"]
    try:
        print(tabulate(table_data, headers=headers, tablefmt="rounded_grid"))
    except Exception:
        # Если tabulate не установлен
        for row in table_data:
            print(f"[{row[0]}] {row[1]} ({row[2]}) | {row[3]} | {row[4]} | {row[5]} | {row[6]}")

    if args.show_specs:
        for p in products:
            print(f"\n--- {p.title}")
            print(json.dumps({**{k: v for k, v in p.__dict__.items() if k != "specs"}, "specs": p.specs},
                             ensure_ascii=False, indent=2, default=str))

    if args.dry_run:
        print("\n🔍 Режим предпросмотра: запись в базу данных пропущена.")
        return

    print("\n💾 Сохранение данных в PostgreSQL (3НФ)...")
    async with AsyncSessionLocal() as session:
        protocol = await ingest_scraped_products(
            db=session,
            products=products,
            department_id=args.dept
        )

    print(f"\n📊 ИТОГОВЫЙ ПРОТОКОЛ ТРАНЗАКЦИИ:")
    print(f"  • Всего обработано: {protocol['total_scraped']}")
    print(f"  • Успешно добавлено новых: {protocol['imported_count']}")
    print(f"  • Уже существовало в базе: {protocol['already_exists_count']}")
    print(f"  • Ошибок импорта: {protocol['failed_count']}")
    print(f"=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
