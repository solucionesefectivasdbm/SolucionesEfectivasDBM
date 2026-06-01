"""
routers/admin.py — Endpoints de administración.

ENDPOINT TEMPORAL — eliminar tras ejecutar en producción.
Este router contiene el endpoint de migración one-shot para recalcular
saldos desincronizados por los bugs corregidos en fix-reduccion-saldos
(Batch A/B/C). Debe eliminarse en un commit posterior al deploy exitoso.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_client_ip, require_role
from app.models.credito import Credito, TipoCredito
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.services import audit_service

router = APIRouter(prefix="/admin", tags=["Admin"])


# ---------------------------------------------------------------------------
# ENDPOINT TEMPORAL — eliminar tras ejecutar en producción
# ---------------------------------------------------------------------------
@router.post("/migracion/recalcular-saldos")
async def recalcular_saldos_migracion(
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(get_client_ip),
) -> dict[str, Any]:
    """
    Recalcula saldo_capital y saldo_intereses de todos los créditos activos
    a partir de los pagos reales confirmados (no-deleted).

    Algoritmo:
    - saldo_capital = max(0, capital_prestado − Σ capital_pagado)
    - saldo_intereses (cuota_fija) = capital*tasa*(n/ppm) − Σ interes_pagado
    - saldo_intereses (abono_capital) = calcular_interes_periodo(saldo_capital_nuevo, tasa)

    Registra cada cambio en audit_log. Retorna resumen completo.

    ENDPOINT TEMPORAL — eliminar tras ejecutar en producción.
    """
    # Importar helpers aquí para evitar circular dependency
    from app.services.credito_service import calcular_interes_periodo, _periodos_por_mes

    # Traer créditos activos con sus pagos no eliminados en una sola query
    creditos_result = await db.execute(
        select(Credito).where(
            Credito.deleted_at == None,  # noqa: E711
            Credito.activo == True,  # noqa: E712
        )
    )
    creditos = creditos_result.scalars().all()

    total_revisados = 0
    total_corregidos = 0
    detalles: list[dict[str, Any]] = []

    for credito in creditos:
        total_revisados += 1

        # --- Calcular saldo_capital correcto ---
        capital_pagado_total = (await db.execute(
            select(func.coalesce(func.sum(Pago.capital_pagado), Decimal("0.00"))).where(
                Pago.credito_id == credito.id,
                Pago.deleted_at == None,  # noqa: E711
            )
        )).scalar() or Decimal("0.00")

        capital_pagado_total = Decimal(str(capital_pagado_total))

        nuevo_saldo_capital = (
            credito.capital_prestado - capital_pagado_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if nuevo_saldo_capital < Decimal("0.00"):
            nuevo_saldo_capital = Decimal("0.00")

        # --- Calcular saldo_intereses correcto según tipo ---
        if credito.tipo_credito == TipoCredito.cuota_fija and credito.numero_cuotas:
            ppm = Decimal(_periodos_por_mes(credito.periodicidad))
            num_meses = Decimal(credito.numero_cuotas) / ppm
            interes_total = credito.capital_prestado * credito.tasa_interes_mensual * num_meses

            interes_pagado_total = (await db.execute(
                select(func.coalesce(func.sum(Pago.interes_pagado), Decimal("0.00"))).where(
                    Pago.credito_id == credito.id,
                    Pago.deleted_at == None,  # noqa: E711
                )
            )).scalar() or Decimal("0.00")
            interes_pagado_total = Decimal(str(interes_pagado_total))

            nuevo_saldo_intereses = (interes_total - interes_pagado_total).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if nuevo_saldo_intereses < Decimal("0.00"):
                nuevo_saldo_intereses = Decimal("0.00")
        else:
            # abono_capital: próximo período calculado sobre el saldo_capital recalculado
            nuevo_saldo_intereses = calcular_interes_periodo(
                nuevo_saldo_capital, credito.tasa_interes_mensual
            )

        # --- Detectar si cambió algo ---
        saldo_capital_anterior = Decimal(str(credito.saldo_capital))
        saldo_intereses_anterior = Decimal(str(credito.saldo_intereses))

        cambio_capital = saldo_capital_anterior != nuevo_saldo_capital
        cambio_intereses = saldo_intereses_anterior != nuevo_saldo_intereses

        if not (cambio_capital or cambio_intereses):
            continue

        # --- Aplicar cambios ---
        cambios: dict[str, tuple[str, str]] = {}
        if cambio_capital:
            cambios["saldo_capital"] = (
                str(saldo_capital_anterior),
                str(nuevo_saldo_capital),
            )
            credito.saldo_capital = nuevo_saldo_capital
        if cambio_intereses:
            cambios["saldo_intereses"] = (
                str(saldo_intereses_anterior),
                str(nuevo_saldo_intereses),
            )
            credito.saldo_intereses = nuevo_saldo_intereses

        # --- Registrar en audit_log ---
        await audit_service.registrar_actualizacion_campos(
            db=db,
            entidad="creditos",
            entidad_id=credito.id,
            usuario_id=current_user.id,
            ip_origen=client_ip,
            cambios=cambios,
        )

        total_corregidos += 1
        detalles.append({
            "credito_id": str(credito.id),
            "numero_credito": credito.numero_credito_cliente,
            "saldo_capital": [str(saldo_capital_anterior), str(nuevo_saldo_capital)],
            "saldo_intereses": [str(saldo_intereses_anterior), str(nuevo_saldo_intereses)],
        })

    return {
        "total_revisados": total_revisados,
        "total_corregidos": total_corregidos,
        "corregidos": detalles,
    }
