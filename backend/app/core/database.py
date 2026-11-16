import os
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://diag_admin:secure_diag_pass_2026@localhost:5434/equipment_diag_db"
)

SYNC_DATABASE_URL = os.getenv(
    "SYNC_DATABASE_URL",
    "postgresql+psycopg2://diag_admin:secure_diag_pass_2026@localhost:5434/equipment_diag_db"
)

from sqlalchemy.pool import NullPool

# Async engine for FastAPI endpoints
async_engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for Alembic, seed scripts, and benchmark utilities
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False, pool_size=10, max_overflow=20, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

def get_sync_db():
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()
