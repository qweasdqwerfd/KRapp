from datetime import datetime, date
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.models.entities import (
    Manufacturer, EquipmentCategory, EquipmentModel,
    TechnicalSpecification, EquipmentItem, ServiceDepartment, AuditLog
)
from app.services.web_scraper import ScrapedProduct

async def get_or_create_default_department(db: AsyncSession, department_id: Optional[int] = None) -> int:
    """Гарантирует наличие сервисного отдела в БД."""
    if department_id:
        stmt = select(ServiceDepartment).where(ServiceDepartment.id == department_id)
        res = await db.execute(stmt)
        dept = res.scalars().first()
        if dept:
            return dept.id

    stmt = select(ServiceDepartment)
    res = await db.execute(stmt)
    dept = res.scalars().first()
    if dept:
        return dept.id

    new_dept = ServiceDepartment(
        name="Центральный сервисный отдел БГТУ",
        city="Белгород",
        address="ул. Костюкова, 46",
        phone="+7 (4722) 55-41-41",
        max_simultaneous_repairs=50
    )
    db.add(new_dept)
    await db.flush()
    return new_dept.id

async def ingest_scraped_products(
    db: AsyncSession,
    products: List[ScrapedProduct],
    user_id: Optional[int] = None,
    department_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Транзакционное сохранение распарсенных товаров в PostgreSQL (3НФ).
    Использует вложенные точки сохранения (SAVEPOINT) для изоляции ошибок отдельных позиций.
    """
    protocol = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_scraped": len(products),
        "imported_count": 0,
        "already_exists_count": 0,
        "failed_count": 0,
        "items": []
    }

    if not products:
        return protocol

    dept_id = await get_or_create_default_department(db, department_id)

    # Кэшируем справочники брендов и категорий для скорости
    mfg_res = await db.execute(select(Manufacturer))
    mfg_map = {m.name.lower(): m for m in mfg_res.scalars().all()}

    cat_res = await db.execute(select(EquipmentCategory))
    cat_map = {c.code.upper(): c for c in cat_res.scalars().all()}

    for idx, prod in enumerate(products):
        try:
            async with db.begin_nested():
                # 1. Производитель (Manufacturer)
                mfg_name = prod.manufacturer.strip() or "Не указан"
                mfg = mfg_map.get(mfg_name.lower())
                if not mfg:
                    mfg = Manufacturer(
                        name=mfg_name,
                        country="Россия" if any(r in mfg_name.lower() for r in ["raskat", "dexp", "vitek"]) else "Не указана",
                        created_at=datetime.utcnow()
                    )
                    db.add(mfg)
                    await db.flush()
                    mfg_map[mfg_name.lower()] = mfg

                # 2. Категория (EquipmentCategory)
                cat_code = prod.category.upper()
                cat = cat_map.get(cat_code)
                if not cat:
                    readable_name = (getattr(prod, "category_name", None) or cat_code.replace("_", " ").title())[:100]
                    cat = EquipmentCategory(
                        name=readable_name,
                        code=cat_code,
                        description=f"Категория {readable_name}, создана автоматически парсером",
                        avg_service_lifetime_months=36
                    )
                    db.add(cat)
                    await db.flush()
                    cat_map[cat_code] = cat

                # 3. Модель оборудования (EquipmentModel)
                vendor_code = prod.vendor_code[:100]
                model_stmt = select(EquipmentModel).where(EquipmentModel.vendor_code == vendor_code)
                m_res = await db.execute(model_stmt)
                model = m_res.scalars().first()

                specs_payload = dict(prod.specs or {})
                if prod.source_url:
                    specs_payload["source_url"] = prod.source_url
                specs_payload["barcode_ean13"] = prod.barcode
                specs_json = json.dumps(specs_payload, ensure_ascii=False, default=str)

                if not model:
                    release_year = max(2000, min(2030, prod.release_year or date.today().year))
                    warranty = max(0, prod.warranty_months)
                    model = EquipmentModel(
                        category_id=cat.id,
                        manufacturer_id=mfg.id,
                        model_name=prod.title[:150],
                        vendor_code=vendor_code,
                        release_year=release_year,
                        warranty_period_months=warranty,
                        created_at=datetime.utcnow()
                    )
                    db.add(model)
                    await db.flush()

                # 4. Технические характеристики (TechnicalSpecification 1:1) — создаём или обновляем
                spec_res = await db.execute(
                    select(TechnicalSpecification).where(TechnicalSpecification.model_id == model.id)
                )
                spec = spec_res.scalars().first()
                if not spec:
                    spec = TechnicalSpecification(model_id=model.id)
                    db.add(spec)
                spec.power_consumption_watts = prod.power_watts or spec.power_consumption_watts
                spec.operating_voltage_volts = prod.voltage or spec.operating_voltage_volts
                spec.dimensions_mm = prod.dimensions_mm or spec.dimensions_mm
                spec.weight_kg = prod.weight_kg or spec.weight_kg
                spec.color = prod.color or spec.color
                spec.additional_specs = specs_json
                await db.flush()

                # 5. Экземпляр оборудования (EquipmentItem со штрихкодом EAN-13)
                barcode_stmt = select(EquipmentItem).where(EquipmentItem.barcode == prod.barcode)
                b_res = await db.execute(barcode_stmt)
                existing_item = b_res.scalars().first()

                if existing_item:
                    if prod.price:
                        existing_item.initial_cost = prod.price
                    protocol["already_exists_count"] += 1
                    protocol["items"].append({
                        "barcode": prod.barcode,
                        "title": prod.title,
                        "status": "ALREADY_EXISTS",
                        "item_id": existing_item.id
                    })
                    continue

                serial = f"SN-{prod.barcode}-{datetime.utcnow().strftime('%M%S%f')[:6]}"
                new_item = EquipmentItem(
                    model_id=model.id,
                    current_department_id=dept_id,
                    serial_number=serial[:100],
                    barcode=prod.barcode[:100],
                    manufacture_date=date(model.release_year, 1, 1),
                    status="IN_OPERATION",
                    initial_cost=prod.price,
                    created_at=datetime.utcnow()
                )
                db.add(new_item)
                await db.flush()

                # 6. Аудит (AuditLog)
                if user_id:
                    audit = AuditLog(
                        user_id=user_id,
                        table_name="equipment_items",
                        record_id=new_item.id,
                        action="INSERT",
                        timestamp=datetime.utcnow(),
                        new_values=json.dumps({
                            "barcode": new_item.barcode,
                            "serial_number": new_item.serial_number,
                            "model_id": new_item.model_id,
                            "initial_cost": new_item.initial_cost
                        }, ensure_ascii=False)
                    )
                    db.add(audit)

                protocol["imported_count"] += 1
                protocol["items"].append({
                    "item_id": new_item.id,
                    "barcode": new_item.barcode,
                    "title": prod.title,
                    "model_name": model.model_name,
                    "vendor_code": model.vendor_code,
                    "manufacturer": mfg.name,
                    "category": cat.code,
                    "price": new_item.initial_cost,
                    "barcode_source": getattr(prod, "barcode_source", None),
                    "status": "IMPORTED"
                })

        except Exception as e:
            protocol["failed_count"] += 1
            protocol["items"].append({
                "index": idx,
                "barcode": getattr(prod, "barcode", "UNKNOWN"),
                "status": "FAILED",
                "error": str(e)
            })

    await db.commit()
    return protocol
