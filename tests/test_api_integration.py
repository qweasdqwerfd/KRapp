import pytest
import sys
import os
from httpx import AsyncClient, ASGITransport

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from app.main import app

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "HEALTHY"

@pytest.mark.asyncio
async def test_auth_login_admin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/auth/login", data={"username": "admin_stepan", "password": "AdminPass2026!"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "ADMIN"
        assert data["username"] == "admin_stepan"

@pytest.mark.asyncio
async def test_auth_login_technician():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/auth/login", data={"username": "engineer_1", "password": "TechPass2026!"})
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "TECHNICIAN"

@pytest.mark.asyncio
async def test_barcode_diagnostic_scan():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Авторизуемся инженером
        login_res = await ac.post("/api/auth/login", data={"username": "engineer_1", "password": "TechPass2026!"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Получаем штрихкод из базы через аналитику
        dash_res = await ac.get("/api/analytics/dashboard-stats", headers=headers)
        assert dash_res.status_code == 200

        # Выполняем тестовое сканирование существующего штрихкода (или тестового)
        # Получим любой валидный штрихкод через прямой SQL запрос
        from app.core.database import SyncSessionLocal
        from app.models.entities import EquipmentItem
        s = SyncSessionLocal()
        item = s.query(EquipmentItem).first()
        test_barcode = item.barcode
        s.close()

        scan_payload = {
            "barcode": test_barcode,
            "department_id": 1,
            "observed_symptoms": "Интеграционный тест: повышенный нагрев и шум вентилятора"
        }
        scan_res = await ac.post("/api/diagnostics/scan", json=scan_payload, headers=headers)
        assert scan_res.status_code == 200
        result = scan_res.json()
        assert result["scanned_barcode"] == test_barcode
        assert "diagnostic_conclusion" in result
        assert "matched_malfunctions" in result

@pytest.mark.asyncio
async def test_reports_generation_and_export():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login_res = await ac.post("/api/auth/login", data={"username": "admin_stepan", "password": "AdminPass2026!"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. JSON Report
        rep_json = await ac.get("/api/reports/model-reliability?export_format=json", headers=headers)
        assert rep_json.status_code == 200
        assert "data" in rep_json.json()

        # 2. XLSX Report (OpenPyXL)
        rep_xlsx = await ac.get("/api/reports/model-reliability?export_format=xlsx", headers=headers)
        assert rep_xlsx.status_code == 200
        assert rep_xlsx.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert len(rep_xlsx.content) > 1000

        # 3. PDF Report (ReportLab)
        rep_pdf = await ac.get("/api/reports/model-reliability?export_format=pdf", headers=headers)
        assert rep_pdf.status_code == 200
        assert rep_pdf.headers["content-type"] == "application/pdf"
        assert rep_pdf.content.startswith(b"%PDF")

