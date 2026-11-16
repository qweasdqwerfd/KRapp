from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date

# 1. Auth & Users
class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str

class LoginRequest(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role_name: str
    is_active: bool

# 2. Equipment & Specs
class SpecificationOut(BaseModel):
    power_consumption_watts: Optional[float] = None
    operating_voltage_volts: Optional[str] = None
    dimensions_mm: Optional[str] = None
    weight_kg: Optional[float] = None
    color: Optional[str] = None
    additional_specs: Optional[str] = None

class EquipmentDetailOut(BaseModel):
    id: int
    serial_number: str
    barcode: str
    model_name: str
    vendor_code: str
    category_name: str
    manufacturer_name: str
    status: str
    initial_cost: float
    manufacture_date: date
    department_name: str
    specifications: Optional[SpecificationOut] = None

# 3. Barcode Diagnostics (Степан: Сканирование и парсинг проблем)
class BarcodeScanRequest(BaseModel):
    barcode: str
    department_id: int
    observed_symptoms: Optional[str] = None
    external_marketplace_url: Optional[str] = None

class MalfunctionPatternOut(BaseModel):
    id: int
    code: str
    title: str
    symptom_description: str
    possible_root_cause: str
    criticality_level: str
    recommended_remedy: str
    occurrence_frequency_pct: Optional[float] = None

class DiagnosticResultOut(BaseModel):
    log_id: int
    equipment_id: int
    scanned_barcode: str
    model_name: str
    manufacturer: str
    category: str
    observed_symptoms: str
    matched_malfunctions: List[MalfunctionPatternOut]
    diagnostic_conclusion: str
    recommended_action: str
    auto_created_order_number: Optional[str] = None

# 4. Reports & Analytics (Задание 2 и 10)
class ReportFilterParams(BaseModel):
    category_id: Optional[int] = None
    department_id: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_cost: Optional[float] = None

class ReliabilityReportItem(BaseModel):
    model_name: str
    manufacturer: str
    category: str
    total_equipment_count: int
    total_failures_count: int
    avg_repair_cost: float
    failure_rate_percent: float
    reliability_rank: int

class DepartmentLoadReportItem(BaseModel):
    department_name: str
    city: str
    active_repairs_count: int
    completed_orders_count: int
    total_revenue: float
    capacity_utilization_pct: float

# 5. Live Web Scraping & Ingestion
class ScrapeUrlRequest(BaseModel):
    url: str = Field(..., description="Ссылка на товар или страницу каталога (Tehnoformula, Spectrasoft или любой сайт)")
    max_items: int = Field(default=15, ge=1, le=1000, description="Максимальное количество товаров для парсинга")
    max_pages: int = Field(default=50, ge=1, le=500, description="Максимальное число страниц пагинации каталога")
    follow_details: bool = Field(default=True, description="Заходить в карточку каждого товара (полные ТТХ и штрихкод)")
    department_id: Optional[int] = Field(default=None, description="ID сервисного отдела (если None, берётся дефолтный)")

class ScrapedItemProtocol(BaseModel):
    item_id: Optional[int] = None
    barcode: str
    title: Optional[str] = None
    model_name: Optional[str] = None
    vendor_code: Optional[str] = None
    manufacturer: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    status: str
    error: Optional[str] = None

class ScrapeUrlResponse(BaseModel):
    timestamp: str
    total_scraped: int
    imported_count: int
    already_exists_count: int
    failed_count: int
    items: List[Dict[str, Any]]

