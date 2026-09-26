"""routers/reportes.py — Reportes financieros por período."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import require_role
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.gestor import Gestor
from app.models.pago import Pago
from app.models.pago_reparto import PagoReparto, TipoDestinatario
from app.models.receptor import CuentaBancaria, Receptor
from app.models.usuario import Usuario
from app.services.credito_service import credito_operativamente_abierto
from app.services.cuenta_bancaria_service import etiqueta_cuenta
from app.utils.fechas import hoy_bogota
from app.utils.momentos import bounds_entrada_mora, get_periodo_momento

_Q2 = Decimal("0.01")


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
    # anio/mes/momento son None en modo por intervalo (D9). fecha_inicio/
    # fecha_fin son aditivos y siempre vienen llenos, en ambos modos.
    anio: int | None = None
    mes: int | None = None
    momento: str | None = None
    fecha_inicio: date
    fecha_fin: date
    total_recaudado: float
    total_intereses_recaudados: float
    total_capital_recaudado: float
    total_pendiente: float
    total_intereses_pendientes: float
    total_capital_pendiente: float
    total_esperado: float
    por_gestor: list[ReporteDetalleGestorExtendido]
    por_receptor: list[ReporteDetalleReceptorExtendido]


class CarteraVencidaGestor(BaseModel):
    gestor_id: str
    gestor_nombre: str
    cantidad_cuotas: int
    total_vencido: float
    total_capital_vencido: float
    total_intereses_vencidos: float


class CarteraVencidaResponse(BaseModel):
    # fecha_fin ya viene recortada a hoy cuando la ventana solicitada se
    # extiende al futuro (design D5) — nunca es la fecha_fin cruda que
    # devuelve resolver_ventana.
    fecha_inicio: date
    fecha_fin: date
    anio: int | None = None
    mes: int | None = None
    momento: str | None = None
    cantidad_cuotas: int
    total_vencido: float
    total_capital_vencido: float
    total_intereses_vencidos: float
    por_gestor: list[CarteraVencidaGestor]  # sin por_receptor (Req: cuotas no recibidas)


# ─── Ventana (por momento o por intervalo) ────────────────────────────────────

def resolver_ventana(
    anio: int | None,
    mes: int | None,
    momento: str | None,
    fecha_desde: date | None,
    fecha_hasta: date | None,
) -> tuple[date, date]:
    """
    reportes-cartera-vencida-y-rango-fechas, design D2 (Requirement: Two
    Mutually Exclusive Filter Modes). Resuelve la ventana (fecha_inicio,
    fecha_fin) de un reporte a partir de los query params, en uno de dos
    modos mutuamente excluyentes:

    - "por momento": `anio` + `mes` + `momento`, los tres juntos.
    - "por intervalo": `fecha_desde` + `fecha_hasta`, los dos juntos.

    Valida ANTES de tocar la base de datos: ambos modos completos, ambos
    modos parciales, o ningún modo -> HTTPException(422) y no se ejecuta
    ninguna consulta. Un `momento` inválido también es 422 (antes de este
    cambio causaba un `ValueError` sin capturar -> 500).

    Vive en el router (no en utils/momentos.py) porque valida entrada HTTP;
    momentos.py se mantiene como lógica de fechas pura.
    """
    momento_campos = (anio, mes, momento)
    intervalo_campos = (fecha_desde, fecha_hasta)
    momento_dado = any(c is not None for c in momento_campos)
    intervalo_dado = any(c is not None for c in intervalo_campos)
    momento_completo = all(c is not None for c in momento_campos)
    intervalo_completo = all(c is not None for c in intervalo_campos)

    if momento_dado and not momento_completo:
        raise HTTPException(
            status_code=422, detail="anio, mes y momento deben enviarse juntos"
        )
    if intervalo_dado and not intervalo_completo:
        raise HTTPException(
            status_code=422, detail="fecha_desde y fecha_hasta deben enviarse juntos"
        )
    if momento_completo and intervalo_completo:
        raise HTTPException(
            status_code=422,
            detail="Use un solo modo de filtro: por momento o por intervalo, no ambos",
        )
    if momento_completo:
        try:
            return get_periodo_momento(anio, mes, momento)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if intervalo_completo:
        if fecha_desde > fecha_hasta:
            raise HTTPException(
                status_code=422,
                detail="fecha_desde no puede ser posterior a fecha_hasta",
            )
        return fecha_desde, fecha_hasta

    raise HTTPException(
        status_code=422,
        detail="Debe especificar anio+mes+momento o fecha_desde+fecha_hasta",
    )


# ─── Router ───────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/reportes", tags=["Reportes"])


@router.get("/ingresos", response_model=ReporteResponseExtendido)
@router.get("", response_model=ReporteResponseExtendido, include_in_schema=False)
async def generar_reporte_ingresos(
    anio: int | None = Query(None),
    mes: int | None = Query(None, ge=1, le=12),
    momento: str | None = Query(None),
    fecha_desde: date | None = Query(None),
    fecha_hasta: date | None = Query(None),
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Reporte de ingresos por ventana de fechas, por momento (m1..m5) o por
    intervalo (`fecha_desde`/`fecha_hasta`) — ver `resolver_ventana`.

    `GET /reportes` (sin sufijo) es un alias oculto de este mismo handler
    (design D1): mismo comportamiento en modo por momento, para que los
    clientes existentes seguir funcionando sin cambios mientras se despliega
    el frontend que consume `/reportes/ingresos`.
    """
    fecha_inicio, fecha_fin = resolver_ventana(anio, mes, momento, fecha_desde, fecha_hasta)

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
    # está deprecado desde PR2a y nunca se lee. payment-multi-recipient
    # (item 10, PR2): para el lado RECAUDADO, la cuenta ya no viene de
    # `Pago.cuenta_bancaria_id` directo (un pago repartido puede tener esa
    # columna en None, ver `pago_reparto_service.aplicar_herencia`) — viene
    # de `pago_repartos` activos tipo cuenta_bancaria. El lado PENDIENTE
    # sigue leyendo la columna legacy: un pago pendiente todavía no tiene
    # repartos (invariante I1).
    pago_por_id = {p.id: p for p in pagados}
    filas_repartos: list[PagoReparto] = []
    if pago_por_id:
        filas_repartos = (await db.execute(
            select(PagoReparto).where(
                PagoReparto.pago_id.in_(pago_por_id.keys()),
                PagoReparto.deleted_at == None,  # noqa: E711
                PagoReparto.tipo_destinatario == TipoDestinatario.cuenta_bancaria,
            )
        )).scalars().all()

    cuenta_ids = {p.cuenta_bancaria_id for p in pendientes if p.cuenta_bancaria_id}
    cuenta_ids |= {r.cuenta_bancaria_id for r in filas_repartos}
    cuentas_map: dict = {}
    if cuenta_ids:
        filas_cuentas = (await db.execute(
            select(CuentaBancaria, Receptor)
            .join(Receptor, CuentaBancaria.receptor_id == Receptor.id)
            .where(CuentaBancaria.id.in_(cuenta_ids))
        )).all()
        cuentas_map = {cuenta.id: (cuenta, receptor) for cuenta, receptor in filas_cuentas}

    por_receptor_map: dict = {}
    por_cuenta_map: dict = {}

    def _fila(cuenta: CuentaBancaria, receptor: Receptor) -> tuple[str, str]:
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
        return rkey, key

    # Pendiente: sigue viniendo de Pago.cuenta_bancaria_id directo (un pago
    # pendiente no tiene repartos todavía). Misma fórmula que antes de PR2.
    for pago in pendientes:
        if not pago.cuenta_bancaria_id:
            continue
        cuenta_receptor = cuentas_map.get(pago.cuenta_bancaria_id)
        if not cuenta_receptor:
            continue
        cuenta, receptor = cuenta_receptor
        rkey, key = _fila(cuenta, receptor)
        capital = float(pago.capital_a_pagar - pago.capital_pagado)
        intereses = float(pago.interes_a_pagar - pago.interes_pagado)
        por_receptor_map[rkey]["capital_pend"] += capital
        por_receptor_map[rkey]["intereses_pend"] += intereses
        por_cuenta_map[key]["capital_pend"] += capital
        por_cuenta_map[key]["intereses_pend"] += intereses

    # Recaudado: viene de pago_repartos (item 10) — cada cuenta recibe la
    # porción de capital/interés proporcional a su parte del monto total del
    # pago. Para el caso común (1 solo reparto, sin split), la proporción es
    # EXACTAMENTE 1 por invariante I1 — capital/interés byte-idénticos al
    # pago, cero cambio de comportamiento. Un split real prorratea; el
    # redondeo de ±0.01 por cuenta se tolera igual que la acumulación float
    # ya existente (ver test_totales_receptor_se_acumulan_por_pago_no_por_cuenta).
    for reparto in filas_repartos:
        cuenta_receptor = cuentas_map.get(reparto.cuenta_bancaria_id)
        if not cuenta_receptor:
            continue
        pago = pago_por_id[reparto.pago_id]
        total_pago = pago.capital_pagado + pago.interes_pagado
        if total_pago <= Decimal("0.00"):
            continue
        proporcion = reparto.monto / total_pago
        capital_compartido = (pago.capital_pagado * proporcion).quantize(_Q2, rounding=ROUND_HALF_UP)
        interes_compartido = (pago.interes_pagado * proporcion).quantize(_Q2, rounding=ROUND_HALF_UP)

        cuenta, receptor = cuenta_receptor
        rkey, key = _fila(cuenta, receptor)
        capital = float(capital_compartido)
        intereses = float(interes_compartido)
        por_receptor_map[rkey]["capital_rec"] += capital
        por_receptor_map[rkey]["intereses_rec"] += intereses
        por_cuenta_map[key]["capital_rec"] += capital
        por_cuenta_map[key]["intereses_rec"] += intereses

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
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
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


@router.get("/cartera-vencida", response_model=CarteraVencidaResponse)
async def generar_reporte_cartera_vencida(
    anio: int | None = Query(None),
    mes: int | None = Query(None, ge=1, le=12),
    momento: str | None = Query(None),
    fecha_desde: date | None = Query(None),
    fecha_hasta: date | None = Query(None),
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    reportes-cartera-vencida-y-rango-fechas: cartera vencida es event-based
    sobre `fecha_entrada_mora` (design D4), no sobre `hoy_bogota()` como
    corte de inclusión — salvo el recorte de ventana futura (D5, ver abajo).
    Reutiliza `resolver_ventana` (mismo modo por momento/por intervalo que
    Ingresos) y los mismos guards que `/pagos/alertas/vencidos`:
    `pagado == False`, `deleted_at IS NULL`, `credito_operativamente_abierto()`
    (D6).

    D5: la ventana efectiva se recorta a `min(fecha_fin, hoy)`. Como
    `bounds_entrada_mora` traduce esa ventana a un rango `[lo, hi)` sobre
    `fecha_maxima` y `fecha_limite_mora` es monótona no decreciente, una
    `fecha_inicio` posterior a `fin_efectivo` produce `lo >= hi` — el rango
    queda vacío sin necesitar un caso especial para "ventana totalmente
    futura".
    """
    fecha_inicio, fecha_fin = resolver_ventana(anio, mes, momento, fecha_desde, fecha_hasta)
    fin_efectivo = min(fecha_fin, hoy_bogota())
    lo, hi = bounds_entrada_mora(fecha_inicio, fin_efectivo)

    query = (
        select(Pago, Gestor)
        .join(Credito, Pago.credito_id == Credito.id)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .outerjoin(Gestor, Cliente.gestor_id == Gestor.id)
        .where(
            Pago.pagado == False,  # noqa: E712
            Pago.deleted_at == None,  # noqa: E711
            # atraso-pago-aplazado-corte-original (design D8): corte
            # inmutable del momento original, no la fecha_maxima vigente
            # (que un aplazamiento puntual movería fuera de esta ventana).
            Pago.fecha_maxima_original >= lo,
            Pago.fecha_maxima_original < hi,
            credito_operativamente_abierto(),
        )
    )
    filas = (await db.execute(query)).all()

    total_capital = Decimal("0.00")
    total_intereses = Decimal("0.00")
    por_gestor_map: dict = {}

    for pago, gestor in filas:
        pendiente_capital = pago.capital_a_pagar - pago.capital_pagado
        pendiente_intereses = pago.interes_a_pagar - pago.interes_pagado
        total_capital += pendiente_capital
        total_intereses += pendiente_intereses

        if gestor is not None:
            key = str(gestor.id)
            if key not in por_gestor_map:
                por_gestor_map[key] = {
                    "gestor_id": key,
                    "gestor_nombre": f"{gestor.nombre} {gestor.apellidos}",
                    "cantidad": 0,
                    "capital": Decimal("0.00"),
                    "intereses": Decimal("0.00"),
                }
            por_gestor_map[key]["cantidad"] += 1
            por_gestor_map[key]["capital"] += pendiente_capital
            por_gestor_map[key]["intereses"] += pendiente_intereses

    por_gestor = sorted(
        (
            CarteraVencidaGestor(
                gestor_id=v["gestor_id"],
                gestor_nombre=v["gestor_nombre"],
                cantidad_cuotas=v["cantidad"],
                total_vencido=float(v["capital"] + v["intereses"]),
                total_capital_vencido=float(v["capital"]),
                total_intereses_vencidos=float(v["intereses"]),
            )
            for v in por_gestor_map.values()
        ),
        key=lambda g: (g.gestor_nombre, g.gestor_id),
    )

    return CarteraVencidaResponse(
        fecha_inicio=fecha_inicio,
        fecha_fin=fin_efectivo,
        anio=anio,
        mes=mes,
        momento=momento,
        cantidad_cuotas=len(filas),
        total_vencido=float(total_capital + total_intereses),
        total_capital_vencido=float(total_capital),
        total_intereses_vencidos=float(total_intereses),
        por_gestor=por_gestor,
    )