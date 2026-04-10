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
from app.models.receptor import Receptor
from app.models.usuario import Usuario
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


class ReporteDetalleReceptorExtendido(BaseModel):
    receptor_id: str
    receptor_nombre: str
    total_recaudado: float
    total_intereses_recaudados: float
    total_capital_recaudado: float
    total_pendiente: float
    total_intereses_pendientes: float
    total_capital_pendiente: float


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

    por_receptor_map: dict = {}
    for pago in todos:
        if pago.receptor_id:
            receptor = (await db.execute(select(Receptor).where(Receptor.id == pago.receptor_id))).scalar_one_or_none()
            if receptor:
                key = str(receptor.id)
                if key not in por_receptor_map:
                    por_receptor_map[key] = {
                        "receptor_id": str(receptor.id),
                        "receptor_nombre": receptor.nombre,
                        "capital_rec": 0.0, "intereses_rec": 0.0,
                        "capital_pend": 0.0, "intereses_pend": 0.0,
                    }
                if pago.pagado:
                    por_receptor_map[key]["capital_rec"] += float(pago.capital_pagado)
                    por_receptor_map[key]["intereses_rec"] += float(pago.interes_pagado)
                else:
                    por_receptor_map[key]["capital_pend"] += float(pago.capital_a_pagar - pago.capital_pagado)
                    por_receptor_map[key]["intereses_pend"] += float(pago.interes_a_pagar - pago.interes_pagado)

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
        )
        for v in por_receptor_map.values()
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