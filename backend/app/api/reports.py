from fastapi import APIRouter, Depends, Query, Response, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.entities import User
from app.services.report_exporter import export_to_xlsx, export_to_pdf

router = APIRouter(prefix="/reports", tags=["Формирование отчётов и выгрузка (Задание 2)"])

# -------------------------------------------------------------
# ЗАПРОС 1: Анализ надежности и отказов моделей оборудования
# (Соединение 4 таблиц: models, manufacturers, categories, diagnostic_logs)
# -------------------------------------------------------------
@router.get("/model-reliability")
async def get_model_reliability_report(
    category_id: Optional[int] = Query(None, description="ID категории оборудования"),
    min_diagnostics: int = Query(5, description="Минимальное число диагностик (HAVING)"),
    export_format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    query = """
        SELECT 
            em.model_name AS "Модель",
            m.name AS "Производитель",
            ec.name AS "Категория",
            COUNT(DISTINCT ei.id) AS "Всего единиц",
            COUNT(dl.id) AS "Число диагностик",
            COUNT(mo.id) AS "Число ремонтов",
            ROUND(AVG(COALESCE(mo.total_cost, 0.0))::numeric, 2) AS "Средняя стоимость ремонта, руб.",
            ROUND((COUNT(dl.id)::numeric / NULLIF(COUNT(DISTINCT ei.id), 0) * 100)::numeric, 1) AS "Интенсивность отказов, %"
        FROM equipment_models em
        JOIN manufacturers m ON em.manufacturer_id = m.id
        JOIN equipment_categories ec ON em.category_id = ec.id
        JOIN equipment_items ei ON ei.model_id = em.id
        LEFT JOIN diagnostic_logs dl ON dl.equipment_id = ei.id
        LEFT JOIN maintenance_orders mo ON mo.equipment_id = ei.id
        WHERE (CAST(:cat_id AS INTEGER) IS NULL OR em.category_id = CAST(:cat_id AS INTEGER))
        GROUP BY em.id, em.model_name, m.name, ec.name
        HAVING COUNT(dl.id) >= :min_diag
        ORDER BY "Интенсивность отказов, %" DESC;
    """
    params = {"cat_id": category_id, "min_diag": min_diagnostics}
    res = await db.execute(text(query), params)
    rows = [list(r) for r in res.fetchall()]
    headers = [
        "Модель", "Производитель", "Категория", "Всего единиц",
        "Число диагностик", "Число ремонтов", "Средняя стоимость ремонта, руб.",
        "Интенсивность отказов, %"
    ]

    title = "Отчёт по надежности и статистике отказов моделей техники"
    if export_format == "xlsx":
        content = export_to_xlsx(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=model_reliability.xlsx"})
    elif export_format == "pdf":
        content = export_to_pdf(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=model_reliability.pdf"})
    else:
        return {"title": title, "params": params, "total_records": len(rows), "data": [dict(zip(headers, r)) for r in rows]}


# -------------------------------------------------------------
# ЗАПРОС 2: Загрузка сервисных отделений и финансовые показатели
# (Соединение 4 таблиц: departments, orders, equipment_items, users)
# -------------------------------------------------------------
@router.get("/department-workload")
async def get_department_workload_report(
    city: Optional[str] = Query(None, description="Город подразделения"),
    export_format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    query = """
        SELECT 
            sd.name AS "Подразделение",
            sd.city AS "Город",
            sd.max_simultaneous_repairs AS "Лимит мест",
            COUNT(CASE WHEN mo.status IN ('NEW', 'IN_PROGRESS', 'WAITING_PARTS') THEN 1 END) AS "Активные ремонты",
            COUNT(CASE WHEN mo.status = 'COMPLETED' THEN 1 END) AS "Завершенные ремонты",
            ROUND(COALESCE(SUM(mo.total_cost), 0.0)::numeric, 2) AS "Суммарная выручка, руб.",
            ROUND((COUNT(CASE WHEN mo.status IN ('NEW', 'IN_PROGRESS') THEN 1 END)::numeric / sd.max_simultaneous_repairs * 100)::numeric, 1) AS "Загрузка мощностей, %"
        FROM service_departments sd
        LEFT JOIN maintenance_orders mo ON mo.department_id = sd.id
        WHERE (CAST(:city AS VARCHAR) IS NULL OR sd.city ILIKE CAST(:city AS VARCHAR))
        GROUP BY sd.id, sd.name, sd.city, sd.max_simultaneous_repairs
        ORDER BY "Загрузка мощностей, %" DESC;
    """
    params = {"city": city}
    res = await db.execute(text(query), params)
    rows = [list(r) for r in res.fetchall()]
    headers = ["Подразделение", "Город", "Лимит мест", "Активные ремонты", "Завершенные ремонты", "Суммарная выручка, руб.", "Загрузка мощностей, %"]

    title = "Аналитический отчёт загрузки сервисных отделений"
    if export_format == "xlsx":
        content = export_to_xlsx(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=department_workload.xlsx"})
    elif export_format == "pdf":
        content = export_to_pdf(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=department_workload.pdf"})
    else:
        return {"title": title, "params": params, "data": [dict(zip(headers, r)) for r in rows]}


# -------------------------------------------------------------
# ЗАПРОС 3: Расход и себестоимость запчастей при ремонтах
# (Соединение 4 таблиц: spare_parts, order_spare_parts, orders, manufacturers)
# -------------------------------------------------------------
@router.get("/parts-consumption")
async def get_parts_consumption_report(
    min_units: int = Query(1, description="Минимальное количество израсходованных единиц"),
    export_format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    query = """
        SELECT 
            sp.part_number AS "Артикул",
            sp.name AS "Наименование детали",
            m.name AS "Производитель",
            sp.unit_price AS "Базовая цена, руб.",
            SUM(osp.quantity) AS "Израсходовано, шт.",
            ROUND(SUM(osp.quantity * osp.applied_price)::numeric, 2) AS "Общая стоимость, руб.",
            sp.stock_quantity AS "Остаток на складе"
        FROM spare_parts sp
        JOIN manufacturers m ON sp.manufacturer_id = m.id
        JOIN order_spare_parts osp ON osp.spare_part_id = sp.id
        JOIN maintenance_orders mo ON osp.order_id = mo.id
        GROUP BY sp.id, sp.part_number, sp.name, m.name, sp.unit_price, sp.stock_quantity
        HAVING SUM(osp.quantity) >= :min_u
        ORDER BY "Общая стоимость, руб." DESC;
    """
    params = {"min_u": min_units}
    res = await db.execute(text(query), params)
    rows = [list(r) for r in res.fetchall()]
    headers = ["Артикул", "Наименование детали", "Производитель", "Базовая цена, руб.", "Израсходовано, шт.", "Общая стоимость, руб.", "Остаток на складе"]

    title = "Отчёт по расходу и себестоимости комплектующих"
    if export_format == "xlsx":
        content = export_to_xlsx(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=parts_consumption.xlsx"})
    elif export_format == "pdf":
        content = export_to_pdf(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=parts_consumption.pdf"})
    else:
        return {"title": title, "params": params, "data": [dict(zip(headers, r)) for r in rows]}


# -------------------------------------------------------------
# ЗАПРОС 4: Каталог критических дефектов и частота их проявления
# (Соединение 3 таблиц: categories, malfunction_patterns, diagnostic_logs)
# -------------------------------------------------------------
@router.get("/critical-malfunctions")
async def get_critical_malfunctions_report(
    criticality: Optional[str] = Query(None, description="Уровень критичности (LOW, MEDIUM, HIGH, CRITICAL)"),
    export_format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    query = """
        SELECT 
            mp.code AS "Код дефекта",
            mp.title AS "Наименование неисправности",
            ec.name AS "Категория оборудования",
            mp.criticality_level AS "Критичность",
            COUNT(dl.id) AS "Число регистраций",
            mp.recommended_remedy AS "Рекомендуемое действие"
        FROM malfunction_patterns mp
        JOIN equipment_categories ec ON mp.category_id = ec.id
        LEFT JOIN diagnostic_logs dl ON dl.matched_malfunction_id = mp.id
        WHERE (CAST(:crit AS VARCHAR) IS NULL OR mp.criticality_level = CAST(:crit AS VARCHAR))
        GROUP BY mp.id, mp.code, mp.title, ec.name, mp.criticality_level, mp.recommended_remedy
        ORDER BY "Число регистраций" DESC;
    """
    params = {"crit": criticality}
    res = await db.execute(text(query), params)
    rows = [list(r) for r in res.fetchall()]
    headers = ["Код дефекта", "Наименование неисправности", "Категория оборудования", "Критичность", "Число регистраций", "Рекомендуемое действие"]

    title = "Отчёт по типовым дефектам и частоте их выявления"
    if export_format == "xlsx":
        content = export_to_xlsx(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=critical_malfunctions.xlsx"})
    elif export_format == "pdf":
        content = export_to_pdf(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=critical_malfunctions.pdf"})
    else:
        return {"title": title, "params": params, "data": [dict(zip(headers, r)) for r in rows]}


# -------------------------------------------------------------
# ЗАПРОС 5: Выработка и производительность сервисных инженеров
# (Соединение 3 таблиц: users, maintenance_orders, departments)
# -------------------------------------------------------------
@router.get("/engineer-performance")
async def get_engineer_performance_report(
    department_id: Optional[int] = Query(None, description="ID сервисного подразделения"),
    export_format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"]))
):
    query = """
        SELECT 
            u.full_name AS "Инженер",
            u.email AS "Email",
            sd.name AS "Подразделение",
            COUNT(mo.id) AS "Всего заказов",
            COUNT(CASE WHEN mo.status = 'COMPLETED' THEN 1 END) AS "Успешно завершено",
            ROUND(COALESCE(SUM(mo.total_cost), 0.0)::numeric, 2) AS "Сумма выполненных работ, руб.",
            ROUND(AVG(COALESCE(mo.total_cost, 0.0))::numeric, 2) AS "Средний чек ремонта, руб."
        FROM users u
        JOIN roles r ON u.role_id = r.id
        LEFT JOIN maintenance_orders mo ON mo.assigned_engineer_id = u.id
        LEFT JOIN service_departments sd ON mo.department_id = sd.id
        WHERE r.name = 'TECHNICIAN' AND (CAST(:dept_id AS INTEGER) IS NULL OR mo.department_id = CAST(:dept_id AS INTEGER))
        GROUP BY u.id, u.full_name, u.email, sd.name
        ORDER BY "Сумма выполненных работ, руб." DESC;
    """
    params = {"dept_id": department_id}
    res = await db.execute(text(query), params)
    rows = [list(r) for r in res.fetchall()]
    headers = ["Инженер", "Email", "Подразделение", "Всего заказов", "Успешно завершено", "Сумма выполненных работ, руб.", "Средний чек ремонта, руб."]

    title = "Отчёт по выработке и результативности сервисных специалистов"
    if export_format == "xlsx":
        content = export_to_xlsx(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=engineer_performance.xlsx"})
    elif export_format == "pdf":
        content = export_to_pdf(title, current_user.full_name, params, headers, rows)
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=engineer_performance.pdf"})
    else:
        return {"title": title, "params": params, "data": [dict(zip(headers, r)) for r in rows]}
