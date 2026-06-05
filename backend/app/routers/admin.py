"""
routers/admin.py — Endpoints de administración.

ENDPOINTS TEMPORALES — eliminar tras ejecutar en producción.
Este router contiene endpoints de migración one-shot:
  - recalcular-saldos: corrige saldos desincronizados (fix-reduccion-saldos, Batch A/B/C).
  - anclar-fechas: backfill de anchor_dia_1/2 y re-anclaje de cuotas pendientes.
Deben eliminarse en commits posteriores a sus respectivos deploys exitosos.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_client_ip, require_role
from app.models.credito import Credito, Periodicidad, TipoCredito
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
    - saldo_intereses (abono_capital) = 0 (no lleva saldo acumulado; el interés
      total es indeterminado y se cobra por cuota)

    Registra cada cambio en audit_log. Retorna resumen completo.

    ENDPOINT TEMPORAL — eliminar tras ejecutar en producción.
    """
    # Importar helpers aquí para evitar circular dependency
    from app.services.credito_service import _periodos_por_mes

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
            # abono_capital: NO lleva saldo de intereses acumulado (el total es
            # indeterminado). El interés se cobra por cuota, no a nivel crédito.
            nuevo_saldo_intereses = Decimal("0.00")

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


# ---------------------------------------------------------------------------
# ENDPOINT TEMPORAL — eliminar tras ejecutar en producción
# ---------------------------------------------------------------------------
@router.post("/migracion/anclar-fechas")
async def anclar_fechas_migracion(
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(get_client_ip),
) -> dict[str, Any]:
    """
    Backfill idempotente: deriva anchor_dia_1/anchor_dia_2 para créditos
    ACTIVOS mensual/quincenal y re-ancla sus cuotas pendientes.

    Algoritmo por crédito activo (deleted_at IS NULL, activo=True):
    - semanal/diario: ignorados (anchors permanecen NULL).
    - mensual: anchor_dia_1 = fecha_inicial_pago.day; anchor_dia_2 = NULL.
    - quincenal: deriva la pareja desde los primeros 2 días DISTINTOS de
      Pago.fecha_maxima (deleted_at IS NULL). Si <2 días → flagged como
      requiere_revision_manual, no se recalcula.
    - Idempotencia: crédito con anchor_dia_1 ya establecido → saltado
      (se cuenta en total_saltados, no se re-aplica).
    - Después de anclar, recalcula cuotas pendientes via recalcular_cuotas_futuras
      usando desde_fecha = siguiente fecha ancla desde la última cuota PAGADA,
      o fecha_inicial_pago si ninguna pagada.
    - Solo cambian fecha_maxima/momento; capital/interes/monto NO se tocan.

    Retorna resumen: total_revisados, total_anclados, total_saltados,
    requiere_revision_manual (lista de credito_id como str).

    ENDPOINT TEMPORAL — eliminar tras ejecutar en producción.
    """
    from app.services.credito_service import recalcular_cuotas_futuras
    from app.utils.fechas import siguiente_fecha_maxima

    creditos_result = await db.execute(
        select(Credito).where(
            Credito.deleted_at == None,  # noqa: E711
            Credito.activo == True,  # noqa: E712
        )
    )
    creditos = creditos_result.scalars().all()

    total_revisados = 0
    total_anclados = 0
    total_saltados = 0
    requiere_revision_manual: list[str] = []

    for credito in creditos:
        total_revisados += 1

        # semanal/diario: leave untouched
        if credito.periodicidad in (Periodicidad.semanal, Periodicidad.diario):
            total_saltados += 1
            continue

        # Idempotency gate: skip if anchor already set
        if credito.anchor_dia_1 is not None:
            total_saltados += 1
            continue

        # --- Derive anchors ---
        if credito.periodicidad == Periodicidad.mensual:
            credito.anchor_dia_1 = credito.fecha_inicial_pago.day
            credito.anchor_dia_2 = None

        elif credito.periodicidad == Periodicidad.quincenal:
            # Walk cuotas in chronological order and collect the first 2 distinct days.
            # Using chronological order avoids picking up drifted-date days from
            # later pending cuotas before we have seen the original cadence days.
            pagos_result = await db.execute(
                select(Pago.fecha_maxima)
                .where(
                    Pago.credito_id == credito.id,
                    Pago.deleted_at == None,  # noqa: E711
                )
                .order_by(Pago.fecha_maxima)
            )
            fechas_maxima = pagos_result.scalars().all()
            seen_days: list[int] = []
            for f in fechas_maxima:
                if f.day not in seen_days:
                    seen_days.append(f.day)
                if len(seen_days) == 2:
                    break
            distinct_days = sorted(seen_days)

            if len(distinct_days) < 2:
                # Cannot derive pair — seed anchor_dia_1 from fecha_inicial_pago so
                # that a re-run recognises this credit as already-seen (idempotency gate).
                # anchor_dia_2 stays None; still flagged; recalc is skipped.
                credito.anchor_dia_1 = credito.fecha_inicial_pago.day
                requiere_revision_manual.append(str(credito.id))
                continue

            credito.anchor_dia_1 = distinct_days[0]
            credito.anchor_dia_2 = distinct_days[1]

        # --- Compute desde_fecha for recalc ---
        # Last PAID cuota's fecha_maxima (deleted_at IS NULL)
        ultima_pagada_result = await db.execute(
            select(func.max(Pago.fecha_maxima)).where(
                Pago.credito_id == credito.id,
                Pago.pagado == True,  # noqa: E712
                Pago.deleted_at == None,  # noqa: E711
            )
        )
        ultima_pagada: Any = ultima_pagada_result.scalar()

        if ultima_pagada is None:
            # No paid cuotas: start from fecha_inicial_pago (first cuota keeps its date)
            desde_fecha = credito.fecha_inicial_pago
        else:
            # Advance one anchor step from last paid cuota
            desde_fecha = siguiente_fecha_maxima(ultima_pagada, credito)

        # --- Re-anchor pending cuotas ---
        await recalcular_cuotas_futuras(db, credito, desde_fecha)

        # --- Audit log ---
        await audit_service.registrar_actualizacion_campos(
            db=db,
            entidad="creditos",
            entidad_id=credito.id,
            usuario_id=current_user.id,
            ip_origen=client_ip,
            cambios={
                "anchor_fechas": (
                    "null",
                    f"anchor_dia_1={credito.anchor_dia_1}, anchor_dia_2={credito.anchor_dia_2}",
                )
            },
        )

        total_anclados += 1

    return {
        "total_revisados": total_revisados,
        "total_anclados": total_anclados,
        "total_saltados": total_saltados,
        "requiere_revision_manual": requiere_revision_manual,
    }
