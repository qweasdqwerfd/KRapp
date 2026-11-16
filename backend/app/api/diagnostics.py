from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime
import random

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.entities import (
    User, EquipmentItem, EquipmentModel, DiagnosticLog,
    MaintenanceOrder, MalfunctionPattern, ModelMalfunction
)
from app.schemas.schemas import BarcodeScanRequest, DiagnosticResultOut, MalfunctionPatternOut

router = APIRouter(prefix="/diagnostics", tags=["Мобильная диагностика и сканирование штрихкодов"])

@router.post("/scan", response_model=DiagnosticResultOut)
async def scan_barcode_diagnostic(
    req: BarcodeScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    """
    Основной эндпоинт мобильного сканирования штрихкода (Android клиент).
    1. Находит оборудование по штрихкоду (или парсит внешний штрихкод).
    2. Извлекает характеристики и список типичных поломок модели (база DNS).
    3. Создает запись журнала диагностики и при необходимости заказ на ремонт.
    """
    stmt = (
        select(EquipmentItem)
        .options(
            selectinload(EquipmentItem.model).selectinload(EquipmentModel.manufacturer),
            selectinload(EquipmentItem.model).selectinload(EquipmentModel.category),
            selectinload(EquipmentItem.model).selectinload(EquipmentModel.specifications)
        )
        .where(EquipmentItem.barcode == req.barcode)
    )
    res = await db.execute(stmt)
    item = res.scalars().first()

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Оборудование со штрихкодом {req.barcode} не найдено в локальной БД. Выполните предварительный импорт через DNS-парсер."
        )

    # Загружаем типовые неисправности для модели из базы знаний (DNS catalog)
    malfunc_stmt = (
        select(MalfunctionPattern, ModelMalfunction.occurrence_frequency_pct)
        .join(ModelMalfunction, ModelMalfunction.malfunction_id == MalfunctionPattern.id)
        .where(ModelMalfunction.model_id == item.model_id)
    )
    mf_res = await db.execute(malfunc_stmt)
    malfunctions_with_freq = mf_res.all()

    matched_list = []
    top_critical_malfunc = None
    for mf, freq in malfunctions_with_freq:
        matched_list.append(
            MalfunctionPatternOut(
                id=mf.id,
                code=mf.code,
                title=mf.title,
                symptom_description=mf.symptom_description,
                possible_root_cause=mf.possible_root_cause,
                criticality_level=mf.criticality_level,
                recommended_remedy=mf.recommended_remedy,
                occurrence_frequency_pct=freq
            )
        )
        if mf.criticality_level in ["HIGH", "CRITICAL"] and not top_critical_malfunc:
            top_critical_malfunc = mf

    # Формируем заключение диагностики
    action = "NO_ACTION"
    if top_critical_malfunc:
        action = "URGENT_REPAIR"
        conclusion = f"Выявлена характерная критическая неисправность: {top_critical_malfunc.title}. Рекомендовано: {top_critical_malfunc.recommended_remedy}"
    elif matched_list:
        action = "PREVENTIVE_MAINTENANCE"
        conclusion = f"Обнаружены риски типового износа ({matched_list[0].title}). Требуется плановое обслуживание."
    else:
        conclusion = "Техническое состояние оборудования в пределах заводской нормы."

    # Сохраняем в журнал диагностики (DiagnosticLog)
    diag_log = DiagnosticLog(
        equipment_id=item.id,
        diagnostician_id=current_user.id,
        department_id=req.department_id,
        scanned_barcode=req.barcode,
        scan_timestamp=datetime.utcnow(),
        dns_source_url=req.external_marketplace_url or f"https://dns-shop.ru/product/{item.model.vendor_code.lower()}",
        observed_symptoms=req.observed_symptoms or "Плановое сканирование штрихкода мобильным терминалом",
        matched_malfunction_id=top_critical_malfunc.id if top_critical_malfunc else (matched_list[0].id if matched_list else None),
        diagnostic_conclusion=conclusion,
        recommended_action=action
    )
    db.add(diag_log)
    await db.flush()

    # Если требуется ремонт, автоматически создаем заказ на ремонт
    order_num = None
    if action in ["URGENT_REPAIR", "PREVENTIVE_MAINTENANCE"]:
        order_num = f"ORD-AUTO-{datetime.utcnow().strftime('%y%m%d')}-{random.randint(1000, 9999)}"
        new_order = MaintenanceOrder(
            equipment_id=item.id,
            department_id=req.department_id,
            assigned_engineer_id=current_user.id,
            diagnostic_log_id=diag_log.id,
            order_number=order_num,
            order_date=datetime.utcnow(),
            status="NEW",
            total_cost=0.0,
            work_summary=f"Автоматически сформированный заказ по результатам мобильной диагностики {diag_log.id}: {conclusion}"
        )
        item.status = "IN_DIAGNOSTICS" if action == "PREVENTIVE_MAINTENANCE" else "IN_REPAIR"
        db.add(new_order)

    await db.commit()

    return DiagnosticResultOut(
        log_id=diag_log.id,
        equipment_id=item.id,
        scanned_barcode=req.barcode,
        model_name=item.model.model_name,
        manufacturer=item.model.manufacturer.name,
        category=item.model.category.name,
        observed_symptoms=diag_log.observed_symptoms,
        matched_malfunctions=matched_list,
        diagnostic_conclusion=conclusion,
        recommended_action=action,
        auto_created_order_number=order_num
    )

