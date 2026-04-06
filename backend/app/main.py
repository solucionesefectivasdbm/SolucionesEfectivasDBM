"""
main.py — Punto de entrada de la aplicación FastAPI.

DECISIÓN TÉCNICA: Registramos todos los routers con prefix /api/v1
para facilitar el versionado futuro. El endpoint /health está en la
raíz (sin prefijo) porque Render lo necesita así para health checks.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
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

app = FastAPI(
    title="Soluciones Efectivas — API",
    description="Herramienta de Gestión de Préstamos",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# CORS — solo permite el dominio del frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,  # Necesario para las cookies HttpOnly del refresh token
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.on_event("startup")
async def startup_create_tables():
    """Crea las tablas de la BD si no existen (primer despliegue)."""
    from app.database import engine, Base
    from app.models import cliente, credito, pago, gestor, receptor, audit_log, usuario
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


