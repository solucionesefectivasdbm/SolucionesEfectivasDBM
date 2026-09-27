"""
services/fecha_original_backfill.py — Backfill de `Pago.fecha_maxima_original`
para pagos existentes creados antes de que la columna existiera.

atraso-pago-aplazado-corte-original (Fase 4, design.md "Backfill Algorithm" /
decisión D9): la migración de Fase 1 (`a7b8c9d0e1f2`) llenó la columna nueva
con `fecha_maxima_original = fecha_maxima` para toda fila existente, lo cual
es incorrecto para cualquier pago que ya hubiera sido aplazado antes del
despliegue (su "original" real quedó sobreescrito por el valor aplazado).
Este servicio reconstruye el valor real caminando el historial de cambios de
`fecha_maxima` en `audit_log`.

`resolver_fecha_original` es puro y se prueba en aislamiento
(test_fecha_original_backfill.py). `ejecutar` hace la orquestación en 3
queries batched (sin N+1: nunca una query por pago) y aplica la función pura
en memoria.

El resultado se calcula SOLO a partir de `audit_log` y `fecha_maxima` — nunca
de `fecha_maxima_original` misma — así que correr `ejecutar` dos veces con
`dry_run=False` es idempotente (la segunda corrida da `a_modificar=0`).

TEMPORAL: este servicio y el endpoint admin que lo invoca
(`POST /pagos/admin/backfill-fecha-maxima-original` en routers/pagos.py) se
eliminan en un commit posterior una vez ejecutado el backfill en producción
(convención "Migraciones" de AGENTS.md; mismo patrón que dfb0cf2 /
abono-capital-carryover-fix, aplicado aquí dentro de pagos.py en vez de un
admin.py nuevo — ver nota de Fase 4 en tasks.md sobre por qué).
"""
import uuid
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.pago import Pago
from app.services import audit_service

MOTIVO_AUDITORIA = "auditoria"
MOTIVO_SIN_AUDITORIA = "sin_auditoria"
MOTIVO_REANCLADO = "reanclado"
MOTIVO_VALOR_INVALIDO = "valor_invalido"


def resolver_fecha_original(
    fecha_actual: date,
    fecha_pago_real: date | None,
    eventos: list[tuple[datetime, str | None]],
    ultimo_reanclaje: datetime | None,
) -> tuple[date, str]:
    """
    Pura. Reconstruye la `fecha_maxima_original` de UN pago a partir de su
    historial de cambios de `fecha_maxima` en `audit_log`.

    Args:
        fecha_actual: `fecha_maxima` vigente del pago (valor de fallback).
        fecha_pago_real: fecha en que el pago fue pagado, si ya lo está.
        eventos: tuplas (fecha_accion, valor_anterior) de las filas de
            audit_log de este pago para el campo `fecha_maxima`, ya
            ordenadas cronológicamente ascendente.
        ultimo_reanclaje: `MAX(fecha_accion)` de las filas de audit_log
            `anchor_fechas` del crédito de este pago, o None si el crédito
            nunca fue re-anclado.

    Returns:
        (fecha_original, motivo). motivo es uno de:
        "auditoria", "sin_auditoria", "reanclado", "valor_invalido".
    """
    if not eventos:
        return fecha_actual, MOTIVO_SIN_AUDITORIA

    eventos_vigentes = eventos
    if ultimo_reanclaje is not None:
        pagado_antes_del_reanclaje = (
            fecha_pago_real is not None and fecha_pago_real < ultimo_reanclaje.date()
        )
        if not pagado_antes_del_reanclaje:
            # El re-anclaje ya reseteó fecha_maxima_original de este pago
            # (recalcular_cuotas_futuras, design D5) — los eventos previos a
            # ese momento ya no describen el "original" vigente.
            eventos_vigentes = [
                evento for evento in eventos if evento[0] >= ultimo_reanclaje
            ]

    if not eventos_vigentes:
        return fecha_actual, MOTIVO_REANCLADO

    _, valor_anterior = eventos_vigentes[0]
    if valor_anterior is None:
        return fecha_actual, MOTIVO_VALOR_INVALIDO
    try:
        return date.fromisoformat(valor_anterior), MOTIVO_AUDITORIA
    except ValueError:
        return fecha_actual, MOTIVO_VALOR_INVALIDO


async def ejecutar(
    db: AsyncSession,
    usuario_id: uuid.UUID,
    ip: str,
    dry_run: bool,
) -> dict:
    """
    Orquesta el backfill en 3 queries batched (sin N+1) y aplica
    `resolver_fecha_original` por pago en memoria.

    En modo aplicado (`dry_run=False`), cada fila que cambia pasa por
    `audit_service.registrar_actualizacion_campos` en la misma transacción
    del request (AGENTS.md: "Toda mutación pasa por los helpers de
    audit_service.registrar_*").
    """
    pagos_result = await db.execute(
        select(Pago).where(Pago.deleted_at == None).order_by(Pago.id)  # noqa: E711
    )
    pagos = pagos_result.scalars().all()

    eventos_result = await db.execute(
        select(AuditLog.entidad_id, AuditLog.fecha_accion, AuditLog.valor_anterior)
        .where(
            AuditLog.entidad == "pagos",
            AuditLog.campo_modificado == "fecha_maxima",
        )
        .order_by(AuditLog.entidad_id, AuditLog.fecha_accion, AuditLog.id)
    )
    eventos_por_pago: dict[uuid.UUID, list[tuple[datetime, str | None]]] = defaultdict(list)
    for pago_id, fecha_accion, valor_anterior in eventos_result.all():
        eventos_por_pago[pago_id].append((fecha_accion, valor_anterior))

    reanclaje_result = await db.execute(
        select(AuditLog.entidad_id, func.max(AuditLog.fecha_accion))
        .where(
            AuditLog.entidad == "creditos",
            AuditLog.campo_modificado == "anchor_fechas",
        )
        .group_by(AuditLog.entidad_id)
    )
    ultimo_reanclaje_por_credito: dict[uuid.UUID, datetime] = dict(reanclaje_result.all())

    total_pagos = len(pagos)
    con_auditoria = 0
    a_modificar = 0
    aplazados_sin_auditoria = 0
    reanclados = 0
    valores_invalidos = 0
    ids_a_modificar: list[uuid.UUID] = []

    for pago in pagos:
        eventos = eventos_por_pago.get(pago.id, [])
        ultimo_reanclaje = ultimo_reanclaje_por_credito.get(pago.credito_id)
        nueva_fecha, motivo = resolver_fecha_original(
            pago.fecha_maxima, pago.fecha_pago_real, eventos, ultimo_reanclaje,
        )

        if motivo == MOTIVO_AUDITORIA:
            con_auditoria += 1
        elif motivo == MOTIVO_SIN_AUDITORIA:
            if pago.veces_aplazado > 0:
                aplazados_sin_auditoria += 1
        elif motivo == MOTIVO_REANCLADO:
            reanclados += 1
        elif motivo == MOTIVO_VALOR_INVALIDO:
            valores_invalidos += 1

        anterior = pago.fecha_maxima_original
        if nueva_fecha != anterior:
            a_modificar += 1
            ids_a_modificar.append(pago.id)

            if not dry_run:
                pago.fecha_maxima_original = nueva_fecha
                await audit_service.registrar_actualizacion_campos(
                    db=db,
                    entidad="pagos",
                    entidad_id=pago.id,
                    usuario_id=usuario_id,
                    ip_origen=ip,
                    cambios={
                        "fecha_maxima_original": (
                            anterior.isoformat() if anterior else None,
                            nueva_fecha.isoformat(),
                        )
                    },
                )

    if not dry_run and a_modificar:
        await db.flush()

    return {
        "dry_run": dry_run,
        "total_pagos": total_pagos,
        "con_auditoria": con_auditoria,
        "a_modificar": a_modificar,
        "aplazados_sin_auditoria": aplazados_sin_auditoria,
        "reanclados": reanclados,
        "valores_invalidos": valores_invalidos,
        "muestra_ids": [str(pid) for pid in ids_a_modificar[:20]],
    }
