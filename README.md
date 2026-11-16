# Система сервисного учёта, технической диагностики и предиктивного обслуживания оборудования по штрихкодам

Курсовой проект по дисциплине **«Базы данных»**  
**Студент:** Степанов С. А. (гр. ПИ-231, БГТУ им. В.Г. Шухова, 2026 г.)  
**Преподаватель:** ст. преп. кафедры ПО ВТ и АС Панченко М. В.

---

## 1. Стек технологий
- **СУБД:** PostgreSQL 16 (контейнеризация в Docker Compose, порт хоста 5434:5432)
- **Бэкенд:** Python 3.11+, FastAPI (REST API), SQLAlchemy 2.0 (декларативные модели, asyncpg), Pydantic v2
- **Миграции БД:** Alembic (5 версионных миграций)
- **Генерация данных:** Faker (1 200+ единиц техники, 1 500+ записей журнала диагностики, 1 100+ нарядов)
- **Экспорт отчетов:** OpenPyXL (XLSX), ReportLab (PDF), JSON
- **Мобильный клиент:** Android (Kotlin, Jetpack CameraX, Google ML Kit Barcode Scanning)

---

## 2. Структура проекта
```text
stepan_project/
├── docker-compose.yml          # Спецификация сервисов db (PostgreSQL 16) и backend
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/                # 5 миграций схемы и данных
│   ├── app/
│   │   ├── main.py             # Точка входа FastAPI
│   │   ├── core/               # Конфигурация и подключение к БД
│   │   ├── models/             # 15 реляционных моделей SQLAlchemy 2.0 в 3НФ
│   │   ├── schemas/            # Схемы валидации Pydantic
│   │   ├── services/           # Сервисы: экспорт отчетов, web_scraper, product_ingestion
│   │   └── api/                # Эндпоинты (auth, diagnostics, reports, parser, backup, analytics)
│   └── scripts/
│       ├── scrape_to_db.py     # Парсинг товаров и EAN-13 штрихкодов из любых URL в БД
│       ├── seed_data.py        # Генератор 1000+ записей
│       ├── test_backup_restore.sh # Автобэкап pg_dump и верификация на чистой БД
│       └── benchmark_explain.py   # Замеры планов EXPLAIN ANALYZE и N+1
├── android_client/             # Исходный код Android-приложения сканирования
└── tests/
    ├── test_api_integration.py # Интеграционные тесты pytest
    └── test_parser_scraper.py  # Тесты парсера, EAN-13 контрольной суммы и сканирования
```

---

## 3. Быстрый старт

### 3.1 Запуск базы данных
```bash
docker compose up -d db
```

### 3.2 Установка зависимостей бэкенда
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3.3 Применение миграций и наполнение базы
```bash
alembic upgrade head
python scripts/seed_data.py
```

### 3.4 Запуск сервера FastAPI
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Документация Swagger UI доступна по адресу: `http://localhost:8000/docs`

### 3.5 Запуск интеграционных тестов
```bash
pytest ../tests/ -v
```

### 3.6 Верификация резервной копии
```bash
bash scripts/test_backup_restore.sh
```

### 3.7 Веб-парсинг внешних каталогов в БД (EAN-13)
```bash
python scripts/scrape_to_db.py --url "https://tehnoformula.ru/product/usb/?PAGEN_1=2&view_mode=list" --limit 10
```

