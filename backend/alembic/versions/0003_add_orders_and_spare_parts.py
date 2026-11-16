"""add orders and spare parts

Revision ID: 0003_orders_parts
Revises: 0002_equip_diag
Create Date: 2026-11-01 12:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0003_orders_parts'
down_revision: Union[str, None] = '0002_equip_diag'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

def upgrade() -> None:
    # 0003: Добавление сервисных центров, заказов и запчастей
    pass

def downgrade() -> None:
    pass

