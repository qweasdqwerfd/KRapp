from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.api.deps import require_roles
from app.models.entities import User

router = APIRouter(prefix="/analytics", tags=["Аналитика и оконные функции (Задание 10)"])

@router.get("/dashboard-stats")
async def get_dashboard_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "TECHNICIAN"]))
):
    """
    Задание 10: Информационная панель (Дашборд).
    Использует:
    1. Оконные функции DENSE_RANK() и ROW_NUMBER() для ранжирования моделей по частоте сбоев.
    2. Оконную функцию AVG() OVER (PARTITION BY category) для сравнения стоимости ремонта со средней по категории.
    3. Материализованное представление mv_model_failure_stats.
    """
    # Запрос с оконными функциями: рейтинг надежности и отклонение стоимости ремонта
    window_query = """
        SELECT 
            em.model_name,
            ec.name AS category_name,
            COUNT(dl.id) AS failures_count,
            DENSE_RANK() OVER (PARTITION BY ec.id ORDER BY COUNT(dl.id) DESC) as rank_in_category,
            ROUND(AVG(COALESCE(mo.total_cost, 0.0))::numeric, 2) AS model_avg_cost,
            ROUND(AVG(AVG(COALESCE(mo.total_cost, 0.0))) OVER (PARTITION BY ec.id)::numeric, 2) AS category_avg_cost,
            ROUND((AVG(COALESCE(mo.total_cost, 0.0)) - AVG(AVG(COALESCE(mo.total_cost, 0.0))) OVER (PARTITION BY ec.id))::numeric, 2) AS cost_deviation
        FROM equipment_models em
        JOIN equipment_categories ec ON em.category_id = ec.id
        LEFT JOIN equipment_items ei ON ei.model_id = em.id
        LEFT JOIN diagnostic_logs dl ON dl.equipment_id = ei.id
        LEFT JOIN maintenance_orders mo ON mo.equipment_id = ei.id
        GROUP BY em.id, em.model_name, ec.id, ec.name
        ORDER BY ec.name, rank_in_category ASC;
    """
    res = await db.execute(text(window_query))
    ranked_models = [dict(r._mapping) for r in res.fetchall()]

    # Данные из материализованного представления
    mv_query = "SELECT * FROM mv_model_failure_stats ORDER BY total_repairs_count DESC;"
    mv_res = await db.execute(text(mv_query))
    mat_view_data = [dict(r._mapping) for r in mv_res.fetchall()]

    return {
        "status": "SUCCESS",
        "description": "Аналитические показатели надежности с оконными функциями (DENSE_RANK, AVG OVER PARTITION)",
        "ranked_models_by_category": ranked_models,
        "materialized_view_summary": mat_view_data
    }

@router.post("/refresh-materialized-view")
async def refresh_materialized_view(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"]))
):
    """Обновление материализованного представления витрины данных"""
    await db.execute(text("REFRESH MATERIALIZED VIEW mv_model_failure_stats;"))
    await db.commit()
    return {"status": "SUCCESS", "message": "Материализованное представление mv_model_failure_stats успешно обновлено."}

