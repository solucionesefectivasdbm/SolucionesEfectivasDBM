"""
alembic/env.py — Configuración de migraciones async con Alembic.

DECISIÓN TÉCNICA: Usamos Alembic en modo async porque SQLAlchemy
está configurado con asyncpg. El patrón run_async_migrations() es
el estándar para migraciones async con FastAPI.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importar todos los modelos para que Alembic los detecte
from app.database import Base
import app.models  # noqa: F401 — carga todos los modelos

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    """URL de la DB para migraciones async.

    Reutiliza la MISMA normalizacion que la app (Settings.database_url_async),
    que reescribe el prefijo 'postgresql://' / 'postgres://' que provee Railway
    a 'postgresql+asyncpg://'. Sin esto, async_engine_from_config carga psycopg2
    (driver sync) y falla con 'The asyncio extension requires an async driver'.
    """
    from app.config import get_settings
    return get_settings().database_url_async


def run_migrations_offline() -> None:
    """Modo offline: genera SQL sin conectarse a la DB."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Modo online async: conecta y ejecuta migraciones."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
