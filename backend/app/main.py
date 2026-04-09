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
    import asyncio
    import logging
    logger = logging.getLogger("uvicorn")

    import os
    # Listar TODAS las env vars para diagnóstico
    env_keys = sorted(os.environ.keys())
    logger.info(f"ENV VARS disponibles: {env_keys}")
    raw_env = os.environ.get("DATABASE_URL", "NO DEFINIDA")
    logger.info(f"ENV DATABASE_URL raw: {raw_env[:30]}..." if len(raw_env) > 30 else f"ENV DATABASE_URL raw: {raw_env}")

    from app.config import get_settings
    s = get_settings()
    # Log para diagnóstico (oculta password)
    db_url = s.database_url
    masked = db_url[:20] + "***" + db_url[-30:] if len(db_url) > 50 else "URL corta"
    logger.info(f"Settings database_url: {masked}")
    logger.info(f"Settings database_url_async: {s.database_url_async[:30]}...")

    from app.database import engine, Base
    from app.models import cliente, credito, pago, gestor, receptor, audit_log, usuario

    for intento in range(5):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Tablas creadas/verificadas exitosamente")
            return
        except Exception as e:
            logger.error(f"Intento {intento+1}/5 falló: {e}")
            if intento < 4:
                await asyncio.sleep(3)
    logger.error("No se pudo conectar a la BD después de 5 intentos")


@app.get("/setup-admin", tags=["Sistema"])
async def setup_admin():
    """
    Crea el usuario admin inicial. Solo funciona si no existe.
    ELIMINAR este endpoint después del primer uso.
    """
    import uuid
    from sqlalchemy import select
    from passlib.context import CryptContext
    from app.database import AsyncSessionLocal
    from app.models.usuario import Usuario, TipoUsuario

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async with AsyncSessionLocal() as db:
        existe = (await db.execute(
            select(Usuario).where(Usuario.username == "admin")
        )).scalar_one_or_none()

        if existe:
            return {"message": "El usuario admin ya existe"}

        admin = Usuario(
            id=uuid.uuid4(),
            username="admin",
            password_hash=pwd_context.hash("Admin123"),
            telefono="3000000000",
            tipo_usuario=TipoUsuario.admin,
            activo=True,
            must_change_password=True,
        )
        db.add(admin)
        await db.commit()
        return {
            "message": "Admin creado exitosamente",
            "username": "admin",
            "password": "Admin123",
            "nota": "Cambie la contrasena en el primer ingreso. ELIMINE este endpoint."
        }


