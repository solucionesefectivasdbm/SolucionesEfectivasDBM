"""
database.py — Motor async de SQLAlchemy y sesión de base de datos.

DECISIÓN TÉCNICA: Usamos SQLAlchemy async (asyncpg driver) porque FastAPI
es async por naturaleza. Mezclar sync/async en I/O de base de datos
generaría bloqueos en el event loop. asyncpg es el driver más rápido
para PostgreSQL en Python async.
"""
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# pool_pre_ping=True evita conexiones muertas (Railway puede reciclar la DB)
engine = create_async_engine(
    settings.database_url_async,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=not settings.is_production,  # Log SQL solo en desarrollo
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Evita lazy-load después del commit
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos SQLAlchemy."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependencia FastAPI para inyectar la sesión de DB.
    El 'async with' garantiza rollback automático si hay excepción.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
