from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, Date, DateTime,
    ForeignKey, CheckConstraint, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.core.database import Base

# ==========================================================
# 1. СЛУЖЕБНЫЕ СУЩНОСТИ АВТОРИЗАЦИИ И АУДИТА
# ==========================================================

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False) # ADMIN, TECHNICIAN, CLIENT
    description = Column(String(200), nullable=True)

    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    role = relationship("Role", back_populates="users")
    diagnostic_logs = relationship("DiagnosticLog", back_populates="diagnostician")
    assigned_orders = relationship("MaintenanceOrder", back_populates="assigned_engineer")


# ==========================================================
# 2. ОСНОВНЫЕ СУЩНОСТИ ПРЕДМЕТНОЙ ОБЛАСТИ (11 СУЩНОСТЕЙ В 3НФ)
# ==========================================================

# Сущность 1: Производители / Бренды
class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    country = Column(String(100), nullable=False)
    support_phone = Column(String(50), nullable=True)
    support_email = Column(String(100), nullable=True)
    official_website = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    models = relationship("EquipmentModel", back_populates="manufacturer")
    spare_parts = relationship("SparePart", back_populates="manufacturer")


# Сущность 2: Категории техники (Иерархический рубрикатор)
class EquipmentCategory(Base):
    __tablename__ = "equipment_categories"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("equipment_categories.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    avg_service_lifetime_months = Column(Integer, default=36, nullable=False)

    __table_args__ = (
        CheckConstraint("avg_service_lifetime_months > 0", name="chk_category_lifetime_positive"),
    )

    parent = relationship("EquipmentCategory", remote_side=[id], backref="subcategories")
    models = relationship("EquipmentModel", back_populates="category")
    malfunctions = relationship("MalfunctionPattern", back_populates="category")


# Сущность 3: Модели оборудования
class EquipmentModel(Base):
    __tablename__ = "equipment_models"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("equipment_categories.id", ondelete="RESTRICT"), nullable=False, index=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id", ondelete="RESTRICT"), nullable=False, index=True)
    model_name = Column(String(150), nullable=False, index=True)
    vendor_code = Column(String(100), unique=True, nullable=False, index=True) # Артикул производителя / DNS
    release_year = Column(Integer, nullable=False)
    warranty_period_months = Column(Integer, default=12, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("release_year >= 2000 AND release_year <= 2030", name="chk_model_release_year"),
        CheckConstraint("warranty_period_months >= 0", name="chk_model_warranty_positive"),
    )

    category = relationship("EquipmentCategory", back_populates="models")
    manufacturer = relationship("Manufacturer", back_populates="models")
    specifications = relationship("TechnicalSpecification", uselist=False, back_populates="model", cascade="all, delete-orphan")
    items = relationship("EquipmentItem", back_populates="model")
    model_malfunctions = relationship("ModelMalfunction", back_populates="model", cascade="all, delete-orphan")


# Сущность 4: Технические характеристики (Связь 1:1 с моделью)
class TechnicalSpecification(Base):
    __tablename__ = "technical_specifications"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("equipment_models.id", ondelete="CASCADE"), unique=True, nullable=False)
    power_consumption_watts = Column(Float, nullable=True)
    operating_voltage_volts = Column(String(50), nullable=True) # e.g. "220-240V"
    dimensions_mm = Column(String(100), nullable=True) # e.g. "360x240x19"
    weight_kg = Column(Float, nullable=True)
    color = Column(String(50), nullable=True)
    additional_specs = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("power_consumption_watts IS NULL OR power_consumption_watts >= 0", name="chk_power_positive"),
        CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="chk_weight_positive"),
    )

    model = relationship("EquipmentModel", back_populates="specifications")


# Сущность 5: Каталог типовых дефектов и неисправностей (База знаний / DNS)
class MalfunctionPattern(Base):
    __tablename__ = "malfunction_patterns"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("equipment_categories.id", ondelete="RESTRICT"), nullable=False, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    symptom_description = Column(Text, nullable=False)
    possible_root_cause = Column(Text, nullable=False)
    criticality_level = Column(String(20), default="MEDIUM", nullable=False) # LOW, MEDIUM, HIGH, CRITICAL
    recommended_remedy = Column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("criticality_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="chk_malfunction_criticality"),
    )

    category = relationship("EquipmentCategory", back_populates="malfunctions")
    model_links = relationship("ModelMalfunction", back_populates="malfunction")
    diagnostic_logs = relationship("DiagnosticLog", back_populates="matched_malfunction")


# Сущность 6: Модели и их дефекты (M:N с дополнительными атрибутами вероятности)
class ModelMalfunction(Base):
    __tablename__ = "model_malfunctions"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("equipment_models.id", ondelete="CASCADE"), nullable=False, index=True)
    malfunction_id = Column(Integer, ForeignKey("malfunction_patterns.id", ondelete="CASCADE"), nullable=False, index=True)
    occurrence_frequency_pct = Column(Float, default=5.0, nullable=False)
    typical_operating_hours = Column(Integer, default=2000, nullable=False)

    __table_args__ = (
        UniqueConstraint("model_id", "malfunction_id", name="uq_model_malfunction"),
        CheckConstraint("occurrence_frequency_pct >= 0 AND occurrence_frequency_pct <= 100", name="chk_frequency_range"),
        CheckConstraint("typical_operating_hours >= 0", name="chk_operating_hours_positive"),
    )

    model = relationship("EquipmentModel", back_populates="model_malfunctions")
    malfunction = relationship("MalfunctionPattern", back_populates="model_links")


# Сущность 7: Сервисные подразделения / Склады
class ServiceDepartment(Base):
    __tablename__ = "service_departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    city = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)
    max_simultaneous_repairs = Column(Integer, default=50, nullable=False)

    __table_args__ = (
        CheckConstraint("max_simultaneous_repairs > 0", name="chk_dept_max_repairs_positive"),
    )

    equipment_items = relationship("EquipmentItem", back_populates="department")
    orders = relationship("MaintenanceOrder", back_populates="department")
    diagnostic_logs = relationship("DiagnosticLog", back_populates="department")


# Сущность 8: Физические единицы оборудования (Экземпляры со штрихкодами)
class EquipmentItem(Base):
    __tablename__ = "equipment_items"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("equipment_models.id", ondelete="RESTRICT"), nullable=False, index=True)
    current_department_id = Column(Integer, ForeignKey("service_departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    serial_number = Column(String(100), unique=True, nullable=False, index=True)
    barcode = Column(String(100), unique=True, nullable=False, index=True) # QR / Code128 / EAN13
    manufacture_date = Column(Date, nullable=False)
    status = Column(String(30), default="IN_OPERATION", nullable=False, index=True)
    initial_cost = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('IN_OPERATION', 'IN_DIAGNOSTICS', 'IN_REPAIR', 'REPAIRED', 'DECOMMISSIONED')",
            name="chk_item_status"
        ),
        CheckConstraint("initial_cost >= 0", name="chk_item_cost_positive"),
    )

    model = relationship("EquipmentModel", back_populates="items")
    department = relationship("ServiceDepartment", back_populates="equipment_items")
    diagnostic_logs = relationship("DiagnosticLog", back_populates="equipment", cascade="all, delete-orphan")
    maintenance_orders = relationship("MaintenanceOrder", back_populates="equipment")


# Сущность 9: Журнал сканирования и диагностики оборудования (Мобильный сканер)
class DiagnosticLog(Base):
    __tablename__ = "diagnostic_logs"

    id = Column(Integer, primary_key=True, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment_items.id", ondelete="CASCADE"), nullable=False, index=True)
    diagnostician_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("service_departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    scanned_barcode = Column(String(100), nullable=False)
    scan_timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    dns_source_url = Column(String(255), nullable=True)
    observed_symptoms = Column(Text, nullable=False)
    matched_malfunction_id = Column(Integer, ForeignKey("malfunction_patterns.id", ondelete="SET NULL"), nullable=True)
    diagnostic_conclusion = Column(Text, nullable=False)
    recommended_action = Column(String(50), default="NO_ACTION", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "recommended_action IN ('NO_ACTION', 'PREVENTIVE_MAINTENANCE', 'URGENT_REPAIR', 'WRITE_OFF')",
            name="chk_diag_action"
        ),
    )

    equipment = relationship("EquipmentItem", back_populates="diagnostic_logs")
    diagnostician = relationship("User", back_populates="diagnostic_logs")
    department = relationship("ServiceDepartment", back_populates="diagnostic_logs")
    matched_malfunction = relationship("MalfunctionPattern", back_populates="diagnostic_logs")
    maintenance_orders = relationship("MaintenanceOrder", back_populates="diagnostic_log")


# Сущность 10: Заказы на техническое обслуживание и ремонт
class MaintenanceOrder(Base):
    __tablename__ = "maintenance_orders"

    id = Column(Integer, primary_key=True, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("service_departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_engineer_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    diagnostic_log_id = Column(Integer, ForeignKey("diagnostic_logs.id", ondelete="SET NULL"), nullable=True)
    order_number = Column(String(50), unique=True, nullable=False, index=True)
    order_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completion_date = Column(DateTime, nullable=True)
    status = Column(String(30), default="NEW", nullable=False, index=True)
    total_cost = Column(Float, default=0.0, nullable=False)
    work_summary = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('NEW', 'IN_PROGRESS', 'WAITING_PARTS', 'COMPLETED', 'CANCELLED')",
            name="chk_order_status"
        ),
        CheckConstraint("total_cost >= 0", name="chk_order_cost_positive"),
    )

    equipment = relationship("EquipmentItem", back_populates="maintenance_orders")
    department = relationship("ServiceDepartment", back_populates="orders")
    assigned_engineer = relationship("User", back_populates="assigned_orders")
    diagnostic_log = relationship("DiagnosticLog", back_populates="maintenance_orders")
    used_parts = relationship("OrderSparePart", back_populates="order", cascade="all, delete-orphan")


# Сущность 11: Запасные части и компоненты
class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(Integer, primary_key=True, index=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id", ondelete="RESTRICT"), nullable=False, index=True)
    compatible_category_id = Column(Integer, ForeignKey("equipment_categories.id", ondelete="SET NULL"), nullable=True)
    part_number = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    unit_price = Column(Float, nullable=False)
    stock_quantity = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="chk_part_price_positive"),
        CheckConstraint("stock_quantity >= 0", name="chk_part_stock_positive"),
    )

    manufacturer = relationship("Manufacturer", back_populates="spare_parts")
    order_links = relationship("OrderSparePart", back_populates="spare_part")


# Связующая сущность: Детали в заказе (M:N между MaintenanceOrder и SparePart)
class OrderSparePart(Base):
    __tablename__ = "order_spare_parts"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("maintenance_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    spare_part_id = Column(Integer, ForeignKey("spare_parts.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    applied_price = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("order_id", "spare_part_id", name="uq_order_part"),
        CheckConstraint("quantity > 0", name="chk_order_part_qty_positive"),
        CheckConstraint("applied_price >= 0", name="chk_applied_price_positive"),
    )

    order = relationship("MaintenanceOrder", back_populates="used_parts")
    spare_part = relationship("SparePart", back_populates="order_links")


# Аудит изменений (Задание 5)
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    table_name = Column(String(100), nullable=False, index=True)
    record_id = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False) # INSERT, UPDATE, DELETE
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)

