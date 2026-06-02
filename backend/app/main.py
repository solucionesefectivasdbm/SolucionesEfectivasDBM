"""
main.py — Punto de entrada de la aplicación FastAPI.

DECISIÓN TÉCNICA: Registramos todos los routers con prefix /api/v1
para facilitar el versionado futuro. El endpoint /health está en la
raíz (sin prefijo) porque Render lo necesita así para health checks.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    admin,
    auth,
    auditoria,
    clientes,
    creditos,
    gestores,
    pagos,
    receptores,
    reportes,
    usuarios,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida de la app. Al arrancar crea las tablas que falten y aplica
    migraciones mínimas de esquema. Reemplaza el hook @app.on_event("startup"),
    deprecado en FastAPI.
    """
    from app.database import engine, Base
    from app.models import cliente, credito, pago, gestor, receptor, audit_log, usuario, token_revocado  # noqa: F401
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Migración manual: ampliar numero_credito_cliente si la columna es menor a 100.
        # Es necesario porque create_all no altera columnas existentes.
        result = await conn.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'creditos' AND column_name = 'numero_credito_cliente'"
        ))
        current_length = result.scalar()
        if current_length and current_length < 100:
            await conn.execute(text(
                "ALTER TABLE creditos ALTER COLUMN numero_credito_cliente TYPE VARCHAR(100)"
            ))

        # Migración: reemplazar UNIQUE total en cedula por índice parcial
        # (solo clientes activos) para permitir recrear clientes soft-deleted.
        has_full_unique = (await conn.execute(text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'clientes_cedula_key' AND contype = 'u'"
        ))).scalar()
        if has_full_unique:
            await conn.execute(text(
                "ALTER TABLE clientes DROP CONSTRAINT clientes_cedula_key"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_clientes_cedula_active "
                "ON clientes (cedula) WHERE deleted_at IS NULL"
            ))

        # Migración: agregar columna tipo_validacion a pagos si no existe.
        has_tipo_validacion = (await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'pagos' AND column_name = 'tipo_validacion'"
        ))).scalar()
        if not has_tipo_validacion:
            await conn.execute(text(
                "ALTER TABLE pagos ADD COLUMN tipo_validacion VARCHAR(20)"
            ))

    yield
    # Shutdown: sin tareas de limpieza por ahora.


app = FastAPI(
    title="Soluciones Efectivas — API",
    description="Herramienta de Gestión de Préstamos",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# CORS — solo permite el dominio del frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,  # Necesario para las cookies HttpOnly del refresh token
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Agrega cabeceras de seguridad a todas las respuestas."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.is_production:
        # HSTS: forzar HTTPS por un año (solo en producción, detrás de TLS).
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Registrar routers
API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(usuarios.router, prefix=API_PREFIX)
app.include_router(gestores.router, prefix=API_PREFIX)
app.include_router(receptores.router, prefix=API_PREFIX)
app.include_router(clientes.router, prefix=API_PREFIX)
app.include_router(creditos.router, prefix=API_PREFIX)
app.include_router(pagos.router, prefix=API_PREFIX)
app.include_router(reportes.router, prefix=API_PREFIX)
app.include_router(auditoria.router, prefix=API_PREFIX)
# TEMPORAL — eliminar tras ejecutar migración en producción
app.include_router(admin.router, prefix=API_PREFIX)


@app.get("/health", tags=["Sistema"])
async def health_check():
    """
    Endpoint de salud requerido por Render para verificar disponibilidad.
    No requiere autenticación.
    """
    return {"status": "ok"}


@app.get("/", tags=["Sistema"])
async def root():
    return {"message": "Soluciones Efectivas API v1.0", "docs": "/docs"}

