"""routers/reportes.py — Reportes financieros por período."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import require_role
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.gestor import Gestor
from app.models.pago import Pago
from app.models.receptor import CuentaBancaria, Receptor
from app.models.usuario import Usuario
from app.services.cuenta_bancaria_service import etiqueta_cuenta
from app.utils.momentos import get_periodo_momento


# ─── Schemas del reporte ─────────────────────────────────────────────────────

class ReporteDetalleGestorExtendido(BaseModel):
    gestor_id: str
    gestor_nombre: str
    total_recaudado: float
    total_intereses_recaudados: float
    total_capital_recaudado: float
    total_pendiente: float
    total_intereses_pendientes: float
    total_capital_pendiente: float


class ReporteDetalleCuentaExtendido(BaseModel):
    """Sub-desglose por cuenta bancaria dentro de un receptor (PR2b, Req:
    Report Per-Account Sub-Breakdown)."""
    cuenta_bancaria_id: str
    etiqueta: str
    es_predeterminada: bool
    total_recaudado: float
    total_intereses_recaudados: float
    total_capital_recaudado: float
    total_pendiente: float
    total_intereses_pendientes: float
    total_capital_pendiente: float


class ReporteDetalleReceptorExtendido(BaseModel):
    receptor_id: str
    receptor_nombre: str
    total_recaudado: float
    total_intereses_recaudados: float
    total_capital_recaudado: float
    total_pendiente: float
    total_intereses_pendientes: float
    total_capital_pendiente: float
    por_cuenta: list[ReporteDetalleCuentaExtendido] = []


class ReporteResponseExtendido(BaseModel):
    anio: int
    mes: int
    momento: str
    total_recaudado: float
    total_intereses_recaudados: float
    total_capital_recaudado: float
    total_pendiente: float
    total_intereses_pendientes: float
    total_capital_pendiente: float
    total_esperado: float
    por_gestor: list[ReporteDetalleGestorExtendido]
    por_receptor: list[ReporteDetalleReceptorExtendido]


# ─── Router ───────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/reportes", tags=["Reportes"])


@router.get("", response_model=ReporteResponseExtendido)
async def generar_reporte(
    anio: int = Query(...),
    mes: int = Query(..., ge=1, le=12),
    momento: str = Query(...),
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    fecha_inicio, fecha_fin = get_periodo_momento(anio, mes, momento)

    todos_query = (
        select(Pago)
        .join(Credito, Pago.credito_id == Credito.id)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .where(
            Pago.deleted_at == None,
            Pago.fecha_maxima >= fecha_inicio,
            Pago.fecha_maxima <= fecha_fin,
        )
    )

    todos = (await db.execute(todos_query)).scalars().all()
    pagados = [p for p in todos if p.pagado]
    pendientes = [p for p in todos if not p.pagado]

    total_capital_rec = round(sum(float(p.capital_pagado) for p in pagados), 2)
    total_intereses_rec = round(sum(float(p.interes_pagado) for p in pagados), 2)
    total_recaudado = round(total_capital_rec + total_intereses_rec, 2)

    total_capital_pend = round(sum(float(p.capital_a_pagar - p.capital_pagado) for p in pendientes), 2)
    total_intereses_pend = round(sum(float(p.interes_a_pagar - p.interes_pagado) for p in pendientes), 2)
    total_pendiente = round(total_capital_pend + total_intereses_pend, 2)

    por_gestor_map: dict = {}
    for pago in todos:
        credito = (await db.execute(select(Credito).where(Credito.id == pago.credito_id))).scalar_one()
        cliente = (await db.execute(select(Cliente).where(Cliente.id == credito.cliente_id))).scalar_one()
        gestor = (await db.execute(select(Gestor).where(Gestor.id == cliente.gestor_id))).scalar_one_or_none()
        if gestor:
            key = str(gestor.id)
            if key not in por_gestor_map:
                por_gestor_map[key] = {
                    "gestor_id": str(gestor.id),
                    "gestor_nombre": f"{gestor.nombre} {gestor.apellidos}",
                    "capital_rec": 0.0, "intereses_rec": 0.0,
                    "capital_pend": 0.0, "intereses_pend": 0.0,
                }
            if pago.pagado:
                por_gestor_map[key]["capital_rec"] += float(pago.capital_pagado)
                por_gestor_map[key]["intereses_rec"] += float(pago.interes_pagado)
            else:
                por_gestor_map[key]["capital_pend"] += float(pago.capital_a_pagar - pago.capital_pagado)
                por_gestor_map[key]["intereses_pend"] += float(pago.interes_a_pagar - pago.interes_pagado)

    # Receptor.derivado.vía.cuenta_bancaria (decision 9/10): `Pago.receptor_id`
    # está deprecado desde PR2a y nunca se lee. Se agrega primero por
    # `cuenta_bancaria_id` y luego se agrupa por el receptor de cada cuenta —
    # una sola query precarga cuenta+receptor de todas las cuentas en juego.
    cuenta_ids = {p.cuenta_bancaria_id for p in todos if p.cuenta_bancaria_id}
    cuentas_map: dict = {}
    if cuenta_ids:
        filas_cuentas = (await db.execute(
            select(CuentaBancaria, Receptor)
            .join(Receptor, CuentaBancaria.receptor_id == Receptor.id)
            .where(CuentaBancaria.id.in_(cuenta_ids))
        )).all()
        cuentas_map = {cuenta.id: (cuenta, receptor) for cuenta, receptor in filas_cuentas}

    # Los totales del receptor se acumulan pago a pago (misma fórmula y orden
    # que antes de PR2b: byte-idénticos en float); los subtotales por cuenta
    # se acumulan aparte en el mismo recorrido.
    por_receptor_map: dict = {}
    por_cuenta_map: dict = {}
    for pago in todos:
        if not pago.cuenta_bancaria_id:
            continue
        cuenta_receptor = cuentas_map.get(pago.cuenta_bancaria_id)
        if not cuenta_receptor:
            continue
        cuenta, receptor = cuenta_receptor
        rkey = str(receptor.id)
        if rkey not in por_receptor_map:
            por_receptor_map[rkey] = {
                "receptor_id": rkey,
                "receptor_nombre": receptor.nombre,
                "capital_rec": 0.0, "intereses_rec": 0.0,
                "capital_pend": 0.0, "intereses_pend": 0.0,
                "cuentas": [],
            }
        key = str(cuenta.id)
        if key not in por_cuenta_map:
            por_cuenta_map[key] = {
                "cuenta_bancaria_id": key,
                "etiqueta": etiqueta_cuenta(cuenta),
                "es_predeterminada": cuenta.es_predeterminada,
                "capital_rec": 0.0, "intereses_rec": 0.0,
                "capital_pend": 0.0, "intereses_pend": 0.0,
            }
            por_receptor_map[rkey]["cuentas"].append(por_cuenta_map[key])
        if pago.pagado:
            capital = float(pago.capital_pagado)
            intereses = float(pago.interes_pagado)
            por_receptor_map[rkey]["capital_rec"] += capital
            por_receptor_map[rkey]["intereses_rec"] += intereses
            por_cuenta_map[key]["capital_rec"] += capital
            por_cuenta_map[key]["intereses_rec"] += intereses
        else:
            capital = float(pago.capital_a_pagar - pago.capital_pagado)
            intereses = float(pago.interes_a_pagar - pago.interes_pagado)
            por_receptor_map[rkey]["capital_pend"] += capital
            por_receptor_map[rkey]["intereses_pend"] += intereses
            por_cuenta_map[key]["capital_pend"] += capital
            por_cuenta_map[key]["intereses_pend"] += intereses

    # Orden determinista (el SELECT no lleva ORDER BY): receptores por nombre
    # y luego id; cuentas por etiqueta y luego id. `por_gestor` no cambia.
    receptores_ordenados = sorted(
        por_receptor_map.values(), key=lambda v: (v["receptor_nombre"], v["receptor_id"]),
    )
    for v in receptores_ordenados:
        v["cuentas"].sort(key=lambda c: (c["etiqueta"], c["cuenta_bancaria_id"]))

    por_gestor = [
        ReporteDetalleGestorExtendido(
            gestor_id=v["gestor_id"],
            gestor_nombre=v["gestor_nombre"],
            total_recaudado=v["capital_rec"] + v["intereses_rec"],
            total_intereses_recaudados=v["intereses_rec"],
            total_capital_recaudado=v["capital_rec"],
            total_pendiente=v["capital_pend"] + v["intereses_pend"],
            total_intereses_pendientes=v["intereses_pend"],
            total_capital_pendiente=v["capital_pend"],
        )
        for v in por_gestor_map.values()
    ]

    por_receptor = [
        ReporteDetalleReceptorExtendido(
            receptor_id=v["receptor_id"],
            receptor_nombre=v["receptor_nombre"],
            total_recaudado=v["capital_rec"] + v["intereses_rec"],
            total_intereses_recaudados=v["intereses_rec"],
            total_capital_recaudado=v["capital_rec"],
            total_pendiente=v["capital_pend"] + v["intereses_pend"],
            total_intereses_pendientes=v["intereses_pend"],
            total_capital_pendiente=v["capital_pend"],
            por_cuenta=[
                ReporteDetalleCuentaExtendido(
                    cuenta_bancaria_id=c["cuenta_bancaria_id"],
                    etiqueta=c["etiqueta"],
                    es_predeterminada=c["es_predeterminada"],
                    total_recaudado=c["capital_rec"] + c["intereses_rec"],
                    total_intereses_recaudados=c["intereses_rec"],
                    total_capital_recaudado=c["capital_rec"],
                    total_pendiente=c["capital_pend"] + c["intereses_pend"],
                    total_intereses_pendientes=c["intereses_pend"],
                    total_capital_pendiente=c["capital_pend"],
                )
                for c in v["cuentas"]
            ],
        )
        for v in receptores_ordenados
    ]

    return ReporteResponseExtendido(
        anio=anio,
        mes=mes,
        momento=momento,
        total_recaudado=total_recaudado,
        total_intereses_recaudados=total_intereses_rec,
        total_capital_recaudado=total_capital_rec,
        total_pendiente=total_pendiente,
        total_intereses_pendientes=total_intereses_pend,
        total_capital_pendiente=total_capital_pend,
        total_esperado=total_recaudado + total_pendiente,
        por_gestor=por_gestor,
        por_receptor=por_receptor,
    )