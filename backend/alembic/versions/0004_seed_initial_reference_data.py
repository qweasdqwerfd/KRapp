"""seed initial reference data

Revision ID: 0004_data_seed
Revises: 0003_orders_parts
Create Date: 2026-11-01 12:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0004_data_seed'
down_revision: Union[str, None] = '0003_orders_parts'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

def upgrade() -> None:
    # 0004: Миграция данных (Data Migration) - заполнение базовых ролей и категорий
    op.execute("""
        INSERT INTO roles (name, description) VALUES
        ('ADMIN', 'Администратор системы с полным доступом к конфигурации и СУБД'),
        ('TECHNICIAN', 'Сервисный инженер / диагност (сканирование, дефектовка, ремонты)'),
        ('CLIENT', 'Клиент / Заявитель (просмотр статуса своего оборудования)')
        ON CONFLICT (name) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO equipment_categories (name, code, description, avg_service_lifetime_months) VALUES
        ('Ноутбуки и ультрабуки', 'CAT-LAPTOP', 'Портативные персональные компьютеры', 48),
        ('Смартфоны и планшеты', 'CAT-MOBILE', 'Мобильные устройства связи', 36),
        ('Крупная бытовая техника', 'CAT-MAJOR-APPLIANCE', 'Холодильники, стиральные машины', 84),
        ('Оргтехника и МФУ', 'CAT-OFFICE-PRINT', 'Лазерные и струйные печатные устройства', 60)
        ON CONFLICT (code) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO manufacturers (name, country, support_phone, support_email, official_website, created_at) VALUES
        ('ASUS', 'Тайвань', '+7-800-100-2787', 'support@asus.ru', 'https://asus.com', NOW()),
        ('Samsung', 'Южная Корея', '+7-800-555-5555', 'support@samsung.com', 'https://samsung.com', NOW()),
        ('DNS / DEXP', 'Россия', '+7-800-770-7999', 'service@dns-shop.ru', 'https://dns-shop.ru', NOW()),
        ('Xiaomi', 'Китай', '+7-800-775-6615', 'service.ru@xiaomi.com', 'https://mi.com', NOW())
        ON CONFLICT (name) DO NOTHING;
    """)

def downgrade() -> None:
    op.execute("DELETE FROM equipment_categories WHERE code IN ('CAT-LAPTOP', 'CAT-MOBILE', 'CAT-MAJOR-APPLIANCE', 'CAT-OFFICE-PRINT');")
    op.execute("DELETE FROM manufacturers WHERE name IN ('ASUS', 'Samsung', 'DNS / DEXP', 'Xiaomi');")
    op.execute("DELETE FROM roles WHERE name IN ('ADMIN', 'TECHNICIAN', 'CLIENT');")
