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


@app.get("/fix-intereses", tags=["Sistema"])
async def fix_intereses():
    """
    Corrige créditos cuota_fija que se crearon con interés mal calculado.
    Solo afecta créditos activos sin pagos registrados.
    ELIMINAR este endpoint después del primer uso.
    """
    from decimal import Decimal, ROUND_HALF_UP
    from sqlalchemy import select, func
    from app.database import AsyncSessionLocal
    from app.models.credito import Credito, TipoCredito, Periodicidad
    from app.models.pago import Pago
    from app.services.credito_service import (
        calcular_interes_cuota_fija,
        calcular_capital_cuota_fija,
        _periodos_por_mes,
    )

    resultados = []

    async with AsyncSessionLocal() as db:
        # Buscar créditos cuota_fija activos
        creditos = (await db.execute(
            select(Credito).where(
                Credito.tipo_credito == TipoCredito.cuota_fija,
                Credito.activo == True,
                Credito.deleted_at == None,
            )
        )).scalars().all()

        for credito in creditos:
            # Verificar que no tenga pagos realizados
            pagos_hechos = (await db.execute(
                select(func.count(Pago.id)).where(
                    Pago.credito_id == credito.id,
                    Pago.pagado == True,
                    Pago.deleted_at == None,
                )
            )).scalar()

            if pagos_hechos > 0:
                resultados.append({
                    "credito": credito.numero_credito_cliente,
                    "estado": "OMITIDO - tiene pagos registrados",
                })
                continue

            # Calcular valores correctos
            ppm = Decimal(_periodos_por_mes(credito.periodicidad))
            num_meses = Decimal(credito.numero_cuotas) / ppm
            saldo_intereses_correcto = (
                credito.capital_prestado * credito.tasa_interes_mensual * num_meses
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            interes_por_cuota = calcular_interes_cuota_fija(
                credito.capital_prestado,
                credito.tasa_interes_mensual,
                credito.periodicidad,
            )
            capital_por_cuota = calcular_capital_cuota_fija(
                credito.capital_prestado, credito.numero_cuotas,
            )
            monto_cuota_correcto = (capital_por_cuota + interes_por_cuota).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Guardar valores anteriores para el log
            saldo_anterior = credito.saldo_intereses

            # Actualizar crédito
            credito.saldo_intereses = saldo_intereses_correcto

            # Actualizar la cuota pendiente
            cuota_pendiente = (await db.execute(
                select(Pago).where(
                    Pago.credito_id == credito.id,
                    Pago.pagado == False,
                    Pago.deleted_at == None,
                )
            )).scalar_one_or_none()

            if cuota_pendiente:
                interes_anterior = cuota_pendiente.interes_a_pagar
                cuota_pendiente.interes_a_pagar = interes_por_cuota
                cuota_pendiente.monto_a_pagar = monto_cuota_correcto

                resultados.append({
                    "credito": credito.numero_credito_cliente,
                    "estado": "CORREGIDO",
                    "saldo_intereses_antes": str(saldo_anterior),
                    "saldo_intereses_despues": str(saldo_intereses_correcto),
                    "interes_cuota_antes": str(interes_anterior),
                    "interes_cuota_despues": str(interes_por_cuota),
                    "monto_cuota_correcto": str(monto_cuota_correcto),
                })

        await db.commit()

    return {
        "message": f"Proceso completado. {len(resultados)} crédito(s) procesado(s).",
        "detalle": resultados,
    }


