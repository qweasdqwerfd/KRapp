from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, diagnostics, parser, reports, backup, analytics

app = FastAPI(
    title="BSTU Equipment Diagnostics & Service Database API",
    description="""
    Клиент-серверное программное приложение и реляционная база данных сервисного учета, 
    технической диагностики и предиктивного обслуживания оборудования по штрихкодам.
    Выполнено для БГТУ им. В.Г. Шухова, направление 09.03.04 «Программная инженерия» (кафедра ПО ВТ и АС).
    Преподаватель: Панченко М.В.
    """,
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(diagnostics.router, prefix="/api")
app.include_router(parser.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")

@app.get("/health", tags=["Мониторинг"])
async def health_check():
    return {"status": "HEALTHY", "service": "bstu_equipment_backend", "timestamp": "2026-11-01"}

@app.get("/", tags=["Корень"])
async def root():
    return {
        "project": "Курсовая работа: Базы данных (БГТУ им. В.Г. Шухова)",
        "author": "Степанов Степан (09.03.04)",
        "docs_url": "/docs",
        "redoc_url": "/redoc"
    }

