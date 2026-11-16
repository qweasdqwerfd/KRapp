from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, date
import json
import csv
import io

from app.core.database import get_db
from app.api.deps import require_roles
from app.models.entities import (
    User, EquipmentModel, EquipmentItem, Manufacturer,
    EquipmentCategory, ServiceDepartment, TechnicalSpecification
)
from app.schemas.schemas import ScrapeUrlRequest, ScrapeUrlResponse
from app.services.web_scraper import UniversalProductScraper, validate_ean13
from app.services.product_ingestion import ingest_scraped_products

router = APIRouter(prefix="/parser", tags=["Импорт данных из внешних источников / DNS (Задание 4)"])

@router.post("/import-dns-json")
async def import_dns_catalog_json(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    """
    Задание 4: Загрузка каталога техники (DNS / маркетплейс) в формате JSON.
    - Проверка схемы и валидность входных данных
    - Сопоставление со справочниками производителей и категорий
    - Транзакционное выполнение с формированием протокола
    """
    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Некорректный JSON файл: {str(e)}")

    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Корневой элемент JSON должен быть массивом объектов")

    protocol = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_records_processed": len(data),
        "imported_count": 0,
        "rejected_count": 0,
        "rejected_items": []
    }

    # Кэшируем существующие справочники
    mfg_res = await db.execute(select(Manufacturer))
    mfg_map = {m.name.lower(): m.id for m in mfg_res.scalars().all()}

    cat_res = await db.execute(select(EquipmentCategory))
    cat_map = {c.code.upper(): c.id for c in cat_res.scalars().all()}

    dept_res = await db.execute(select(ServiceDepartment))
    dept_first = dept_res.scalars().first()
    default_dept_id = dept_first.id if dept_first else 1

    try:
        async with db.begin_nested(): # Создаем точку сохранения Savepoint
            for idx, item in enumerate(data):
                # 1. Валидация обязательных полей
                vendor_code = item.get("vendor_code")
                barcode = item.get("barcode")
                model_name = item.get("model_name")
                manufacturer_name = item.get("manufacturer")
                category_code = item.get("category_code")

                if not all([vendor_code, barcode, model_name, manufacturer_name, category_code]):
                    protocol["rejected_count"] += 1
                    protocol["rejected_items"].append({
                        "index": idx,
                        "data": item,
                        "reason": "Пропущены обязательные поля (vendor_code, barcode, model_name, manufacturer, category_code)"
                    })
                    continue

                # 2. Сопоставление производителя
                mfg_id = mfg_map.get(manufacturer_name.lower())
                if not mfg_id:
                    # Создаем нового производителя на лету
                    new_mfg = Manufacturer(name=manufacturer_name, country="Не указана")
                    db.add(new_mfg)
                    await db.flush()
                    mfg_id = new_mfg.id
                    mfg_map[manufacturer_name.lower()] = mfg_id

                # 3. Сопоставление категории
                cat_id = cat_map.get(category_code.upper())
                if not cat_id:
                    protocol["rejected_count"] += 1
                    protocol["rejected_items"].append({
                        "index": idx,
                        "data": item,
                        "reason": f"Категория с кодом '{category_code}' не найдена в справочнике категорий"
                    })
                    continue

                # 4. Проверяем наличие модели в БД
                model_stmt = select(EquipmentModel).where(EquipmentModel.vendor_code == vendor_code)
                m_res = await db.execute(model_stmt)
                model = m_res.scalars().first()

                if not model:
                    model = EquipmentModel(
                        category_id=cat_id,
                        manufacturer_id=mfg_id,
                        model_name=model_name,
                        vendor_code=vendor_code,
                        release_year=int(item.get("release_year", 2023)),
                        warranty_period_months=int(item.get("warranty_period_months", 12))
                    )
                    db.add(model)
                    await db.flush()

                    # Характеристики 1:1
                    spec = TechnicalSpecification(
                        model_id=model.id,
                        power_consumption_watts=item.get("power_watts"),
                        operating_voltage_volts=item.get("voltage"),
                        dimensions_mm=item.get("dimensions"),
                        weight_kg=item.get("weight_kg"),
                        color=item.get("color"),
                        additional_specs=item.get("specs_json", "{}")
                    )
                    db.add(spec)
                    await db.flush()

                # 5. Проверяем уникальность штрихкода оборудования
                barcode_stmt = select(EquipmentItem).where(EquipmentItem.barcode == barcode)
                b_res = await db.execute(barcode_stmt)
                existing_item = b_res.scalars().first()

                if existing_item:
                    protocol["rejected_count"] += 1
                    protocol["rejected_items"].append({
                        "index": idx,
                        "barcode": barcode,
                        "reason": f"Оборудование со штрихкодом {barcode} уже существует в базе (id={existing_item.id})"
                    })
                    continue

                # 6. Добавляем единицу техники
                new_item = EquipmentItem(
                    model_id=model.id,
                    current_department_id=default_dept_id,
                    serial_number=item.get("serial_number", f"SN-IMP-{barcode}"),
                    barcode=barcode,
                    manufacture_date=datetime.strptime(item.get("manufacture_date", "2023-01-01"), "%Y-%m-%d").date(),
                    status="IN_OPERATION",
                    initial_cost=float(item.get("price", 10000.0)),
                    created_at=datetime.utcnow()
                )
                db.add(new_item)
                protocol["imported_count"] += 1

        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка транзакции импорта данных: {str(e)}")

    return protocol


@router.post("/scrape-url", response_model=ScrapeUrlResponse, summary="Парсинг каталога/товара по живому URL в БД")
async def scrape_and_ingest_url(
    req: ScrapeUrlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    """
    Универсальный парсинг и импорт данных о товарах из любого сайта (Tehnoformula, Spectrasoft и др.).
    - Получает HTML страницы каталога или товара по URL
    - Извлекает метаданные: бренд, категорию, артикул, цену, ТТХ и штрихкод EAN-13
    - Проверяет валидность EAN-13 контрольной суммы
    - Сохраняет данные в базу PostgreSQL с соблюдением 3НФ (производители, категории, модели, ТТХ, экземпляры)
    """
    scraper = UniversalProductScraper()
    try:
        products = scraper.scrape(req.url, max_items=req.max_items)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка парсинга веб-страницы {req.url}: {str(e)}"
        )

    if not products:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Не удалось извлечь товары по указанному URL ({req.url}). Проверьте доступность сайта или разметку."
        )

    protocol = await ingest_scraped_products(
        db=db,
        products=products,
        user_id=current_user.id,
        department_id=req.department_id
    )

    return protocol


@router.get("/preview-url", summary="Предпросмотр данных парсера без записи в БД")
async def preview_scrape_url(
    url: str,
    max_items: int = 10,
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    """
    Быстрый предпросмотр: парсит URL и возвращает извлеченные сущности с валидацией EAN-13 без коммита в БД.
    """
    scraper = UniversalProductScraper()
    try:
        products = scraper.scrape(url, max_items=max_items)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка загрузки URL {url}: {str(e)}"
        )

    return {
        "url": url,
        "total_extracted": len(products),
        "products": [
            {
                "title": p.title,
                "vendor_code": p.vendor_code,
                "barcode": p.barcode,
                "is_ean13_valid": validate_ean13(p.barcode),
                "price": p.price,
                "manufacturer": p.manufacturer,
                "category": p.category,
                "warranty_months": p.warranty_months,
                "release_year": p.release_year,
                "dimensions_mm": p.dimensions_mm,
                "weight_kg": p.weight_kg,
                "color": p.color,
                "specs": p.specs
            }
            for p in products
        ]
    }


