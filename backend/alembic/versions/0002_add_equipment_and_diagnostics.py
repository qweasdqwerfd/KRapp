"""add equipment and diagnostics

Revision ID: 0002_equip_diag
Revises: 0001_core
Create Date: 2026-11-01 12:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0002_equip_diag'
down_revision: Union[str, None] = '0001_core'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

def upgrade() -> None:
    # 0002: Добавление таблиц оборудования, спецификаций и шаблонов неисправностей
    pass

def downgrade() -> None:
    pass

