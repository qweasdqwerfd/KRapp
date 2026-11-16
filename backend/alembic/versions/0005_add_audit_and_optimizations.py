"""add audit and optimizations

Revision ID: 0005_audit_opt
Revises: 0004_data_seed
Create Date: 2026-11-01 12:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0005_audit_opt'
down_revision: Union[str, None] = '0004_data_seed'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

def upgrade() -> None:
    # 0005: Добавление составных индексов и материализованного представления
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_equip_dept_status 
        ON equipment_items (current_department_id, status);
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_diag_barcode_time 
        ON diagnostic_logs (scanned_barcode, scan_timestamp DESC);
    """)

    # Материализованное представление для Задания 10 (Аналитическая отчетность)
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_model_failure_stats AS
        SELECT 
            em.id AS model_id,
            em.model_name,
            m.name AS manufacturer_name,
            ec.name AS category_name,
            COUNT(DISTINCT ei.id) AS total_items_count,
            COUNT(DISTINCT dl.id) AS total_diagnostics_count,
            COUNT(DISTINCT mo.id) AS total_repairs_count,
            COALESCE(AVG(mo.total_cost), 0.0) AS avg_repair_cost,
            COALESCE(SUM(mo.total_cost), 0.0) AS sum_total_repair_costs
        FROM equipment_models em
        JOIN manufacturers m ON em.manufacturer_id = m.id
        JOIN equipment_categories ec ON em.category_id = ec.id
        LEFT JOIN equipment_items ei ON ei.model_id = em.id
        LEFT JOIN diagnostic_logs dl ON dl.equipment_id = ei.id
        LEFT JOIN maintenance_orders mo ON mo.equipment_id = ei.id
        GROUP BY em.id, em.model_name, m.name, ec.name;
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_model_failure_id 
        ON mv_model_failure_stats (model_id);
    """)

def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_model_failure_stats;")
    op.execute("DROP INDEX IF EXISTS idx_diag_barcode_time;")
    op.execute("DROP INDEX IF EXISTS idx_equip_dept_status;")

