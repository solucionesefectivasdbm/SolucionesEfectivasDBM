"""
routers/pagos.py — Módulo de pagos: registro, validación y alertas.

Este es el router más complejo. Maneja:
- Listado con filtros obligatorios (año, mes, momento)
- Registro de montos pagados (Registrador/Admin)
- Confirmación de excedente (modal del frontend)
- Validación por Recaudador
- Modificación de fecha y receptor por Recaudador
- Pagos no programados
- Alertas (próximos a vencer, vencidos)
"""
import math
import uuid
from datetime import date, datetime, timezone
from app.utils.fechas import hoy_bogota
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_role
from app.models.cliente import Cliente
from app.models.credito import Credito, Periodicidad
from app.models.gestor import Gestor
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.common import PaginatedResponse
from app.schemas.pago import (
    ConfirmarExcedenteRequest,
    ModificarFechaPagoRequest,
    ModificarReceptorPagoRequest,
    PagoFiltros,
    PagoNoProgramadoRequest,
    PagoResponse,
    RegistrarPagoRequest,
    RegistrarPagoResponse,
    ValidarPagoRequest,
)
from app.services import audit_service
from app.services.pago_service import PagoService
from app.utils.momentos import get_momento, get_periodo_momento

router = APIRouter(prefix="/pagos", tags=["Pagos"])


@router.get("", response_model=PaginatedResponse[PagoResponse])
async def listar_pagos(
    anio: int = Query(..., description="Año (obligatorio)"),
    mes: int = Query(..., ge=1, le=12, description="Mes (obligatorio)"),
    momento: str | None = Query(None, description="m1..m5 (opcional). Si se omite, se filtra por todo el mes calendario."),
    gestor_id: uuid.UUID | None = Query(None),
    cliente_id: uuid.UUID | None = Query(None),
    receptor_id: uuid.UUID | None = Query(None),
    solo_periodicidad: Periodicidad | None = Query(None, description="Filtrar solo créditos con esta periodicidad"),
    excluir_periodicidad: Periodicidad | None = Query(None, description="Excluir créditos con esta periodicidad"),
    busqueda: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Listado de pagos. Año y mes son obligatorios. El momento es opcional
    (cuando no se especifica se incluyen todos los pagos del mes calendario).
    Filtros adicionales por periodicidad permiten separar la vista de pagos
    semanales del resto.
    """
    if momento is not None and momento not in ("m1", "m2", "m3", "m4", "m5"):
        raise HTTPException(status_code=400, detail="Momento inválido. Use m1..m5")

    # Calcular rango de fechas del período
    if momento:
        fecha_inicio, fecha_fin = get_periodo_momento(anio, mes, momento)
    else:
        # Mes calendario completo
        import calendar
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

    query = (
        select(Pago)
        .join(Credito, Pago.credito_id == Credito.id)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .where(
            Pago.deleted_at == None,  # noqa: E711
            Pago.fecha_maxima >= fecha_inicio,
            Pago.fecha_maxima <= fecha_fin,
        )
    )

    # Gestor solo ve sus clientes
    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = query.where(Cliente.gestor_id == gestor.id)

    if gestor_id:
        query = query.where(Cliente.gestor_id == gestor_id)
    if cliente_id:
        query = query.where(Credito.cliente_id == cliente_id)
    if receptor_id:
        query = query.where(Pago.receptor_id == receptor_id)
    if solo_periodicidad:
        query = query.where(Credito.periodicidad == solo_periodicidad)
    if excluir_periodicidad:
        query = query.where(Credito.periodicidad != excluir_periodicidad)
    if busqueda:
        # Búsqueda por palabras: cada token debe aparecer en algún campo
        # (nombre, apellidos o cédula). Permite buscar por nombre completo.
        terminos = [t for t in busqueda.strip().split() if t]
        if terminos:
            condiciones = [
                or_(
                    Cliente.nombre.ilike(f"%{t}%"),
                    Cliente.apellidos.ilike(f"%{t}%"),
                    Cliente.cedula.ilike(f"%{t}%"),
                )
                for t in terminos
            ]
            query = query.where(and_(*condiciones))

    # Traer TODAS las cuotas reales (sin paginar), con datos del cliente y crédito.
    # Necesitamos todas para mergearlas con las virtuales y paginar en memoria.
    query_ext = (
        query.add_columns(
            Cliente.nombre.label("cliente_nombre"),
            Cliente.apellidos.label("cliente_apellidos"),
            Credito.numero_credito_cliente,
        )
        .order_by(Cliente.nombre, Cliente.apellidos, Pago.numero_cuota, Pago.id)
    )
    rows = (await db.execute(query_ext)).all()

    reales: list[dict] = []
    for row in rows:
        pago = row[0]
        data = PagoResponse.model_validate(pago).model_dump()
        data["cliente_nombre"] = f"{row.cliente_nombre} {row.cliente_apellidos}"
        data["numero_credito_cliente"] = row.numero_credito_cliente
        reales.append(data)

    # ── Filas virtuales (cuotas proyectadas que deberían existir pero no se
    #    han generado por estar bloqueadas detrás de una cuota pendiente) ──
    # No proyectamos cuando hay filtro de receptor (las virtuales no tienen
    # receptor asignado todavía, así que no aplicarían al filtro).
    virtuales = await _calcular_virtuales(
        db=db,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        current_user=current_user,
        gestor_id_filtro=gestor_id,
        cliente_id_filtro=cliente_id,
        receptor_id_filtro=receptor_id,
        solo_periodicidad=solo_periodicidad,
        excluir_periodicidad=excluir_periodicidad,
        busqueda=busqueda,
    )

    # Merge + sort + paginar en memoria. Orden alfabético por nombre de cliente.
    todos = reales + virtuales
    todos.sort(key=lambda x: ((x["cliente_nombre"] or "").lower(), x["numero_cuota"], str(x["id"])))

    total = len(todos)
    inicio = (page - 1) * page_size
    page_items = todos[inicio : inicio + page_size]

    items = [PagoResponse.model_validate(x) for x in page_items]

    return PaginatedResponse(
        items=items,
        total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


async def _calcular_virtuales(
    db: AsyncSession,
    fecha_inicio: date,
    fecha_fin: date,
    current_user: Usuario,
    gestor_id_filtro,
    cliente_id_filtro,
    receptor_id_filtro,
    solo_periodicidad,
    excluir_periodicidad,
    busqueda: str,
) -> list[dict]:
    """
    Computa filas "virtuales" para cada crédito activo que debería tener una
    cuota en el período pero no la tiene generada (porque la cuota anterior
    está pendiente). Respeta los mismos filtros que el listado regular.

    Si hay filtro de receptor activo, no se generan virtuales (las virtuales
    no tienen receptor asignado todavía).
    """
    from datetime import timedelta
    from decimal import Decimal, ROUND_HALF_UP
    from app.models.credito import Periodicidad, TipoCredito
    from app.services.credito_service import _periodos_por_mes

    if receptor_id_filtro is not None:
        return []

    # Créditos activos que matchean los filtros del listado.
    cq = (
        select(Credito)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .where(
            Credito.activo == True,  # noqa: E712
            Credito.deleted_at == None,  # noqa: E711
            Cliente.deleted_at == None,  # noqa: E711
        )
    )

    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            cq = cq.where(Cliente.gestor_id == gestor.id)

    if gestor_id_filtro:
        cq = cq.where(Cliente.gestor_id == gestor_id_filtro)
    if cliente_id_filtro:
        cq = cq.where(Credito.cliente_id == cliente_id_filtro)
    if solo_periodicidad:
        cq = cq.where(Credito.periodicidad == solo_periodicidad)
    if excluir_periodicidad:
        cq = cq.where(Credito.periodicidad != excluir_periodicidad)
    if busqueda:
        terminos = [t for t in busqueda.strip().split() if t]
        if terminos:
            condiciones = [
                or_(
                    Cliente.nombre.ilike(f"%{t}%"),
                    Cliente.apellidos.ilike(f"%{t}%"),
                    Cliente.cedula.ilike(f"%{t}%"),
                )
                for t in terminos
            ]
            cq = cq.where(and_(*condiciones))

    creditos_rows = (await db.execute(
        cq.add_columns(
            Cliente.nombre.label("cliente_nombre"),
            Cliente.apellidos.label("cliente_apellidos"),
        )
    )).all()

    if not creditos_rows:
        return []

    credito_ids = [row[0].id for row in creditos_rows]

    # Cuotas existentes por crédito (numero_cuota + estado pagado)
    existentes_rows = (await db.execute(
        select(Pago.credito_id, Pago.numero_cuota, Pago.pagado).where(
            Pago.deleted_at == None,  # noqa: E711
            Pago.credito_id.in_(credito_ids),
        )
    )).all()
    existentes_map: dict = {}
    bloqueador_map: dict = {}  # credito_id -> (numero_cuota más alto pendiente)
    for cid, nc, pagado in existentes_rows:
        existentes_map.setdefault(cid, set()).add(nc)
        if not pagado:
            actual = bloqueador_map.get(cid)
            if actual is None or nc > actual:
                bloqueador_map[cid] = nc

    delta_dias = {
        Periodicidad.mensual: 30,
        Periodicidad.quincenal: 14,
        Periodicidad.semanal: 7,
        Periodicidad.diario: 1,
    }

    virtuales: list[dict] = []

    for row in creditos_rows:
        credito = row[0]
        cliente_nombre = f"{row.cliente_nombre} {row.cliente_apellidos}"
        delta = delta_dias[credito.periodicidad]
        ppm = Decimal(_periodos_por_mes(credito.periodicidad))

        existentes = existentes_map.get(credito.id, set())
        bloqueador = bloqueador_map.get(credito.id)

        # Si no hay bloqueador (todas las cuotas existentes están pagadas) y la
        # próxima ya está por generarse, no proyectamos — el sistema la creará
        # cuando corresponda.
        if bloqueador is None:
            continue

        # Proyectar cuota por cuota hasta exceder fecha_fin.
        n = 1
        # Safety cap
        max_iter = 2000
        while max_iter > 0:
            max_iter -= 1
            fecha_proy = credito.fecha_inicial_pago + timedelta(days=(n - 1) * delta)
            if fecha_proy > fecha_fin:
                break
            if (
                credito.tipo_credito == TipoCredito.cuota_fija
                and credito.numero_cuotas is not None
                and n > credito.numero_cuotas
            ):
                break

            if fecha_proy >= fecha_inicio and n not in existentes:
                # Computar valores estimados según tipo y periodicidad
                if credito.tipo_credito == TipoCredito.cuota_fija and credito.numero_cuotas:
                    capital_x = (credito.capital_prestado / Decimal(credito.numero_cuotas)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    interes_x = (credito.capital_prestado * credito.tasa_interes_mensual / ppm).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    monto = (capital_x + interes_x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    tipo_cuota_str = "programada"
                    capital_a_pagar = capital_x
                    interes_a_pagar = interes_x
                else:
                    # abono_capital
                    interes_est = (credito.saldo_capital * credito.tasa_interes_mensual / ppm).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    abono = credito.abono_minimo if credito.abono_minimo else Decimal("0.00")
                    if credito.periodicidad == Periodicidad.mensual:
                        monto = (interes_est + abono).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        tipo_cuota_str = "programada"
                        capital_a_pagar = abono
                        interes_a_pagar = interes_est
                    else:
                        if n % 2 == 1:
                            tipo_cuota_str = "interes"
                            monto = interes_est
                            capital_a_pagar = Decimal("0.00")
                            interes_a_pagar = interes_est
                        else:
                            tipo_cuota_str = "abono"
                            monto = abono
                            capital_a_pagar = abono
                            interes_a_pagar = Decimal("0.00")

                # UUID determinista para esta combinación (credito_id, numero_cuota).
                # Permite que React lo use como key consistente entre requests.
                virtual_id = uuid.uuid5(uuid.NAMESPACE_OID, f"{credito.id}-{n}")

                virtuales.append({
                    "id": virtual_id,
                    "credito_id": credito.id,
                    "numero_cuota": n,
                    "tipo_cuota": tipo_cuota_str,
                    "monto_a_pagar": monto,
                    "capital_a_pagar": capital_a_pagar,
                    "interes_a_pagar": interes_a_pagar,
                    "capital_pagado": Decimal("0.00"),
                    "interes_pagado": Decimal("0.00"),
                    "momento": get_momento(fecha_proy),
                    "fecha_maxima": fecha_proy,
                    "receptor_id": None,
                    "pagado": False,
                    "validado_recaudador": False,
                    "fecha_pago_real": None,
                    "es_excedente_a": None,
                    "es_ultimo_pago": False,
                    "tipo_validacion": None,
                    "cliente_nombre": cliente_nombre,
                    "numero_credito_cliente": credito.numero_credito_cliente,
                    "es_proyectada": True,
                    "razon_bloqueo": f"Cuota #{bloqueador} pendiente",
                })

            n += 1

    return virtuales


@router.post("/{pago_id}/registrar", response_model=RegistrarPagoResponse)
async def registrar_pago(
    pago_id: uuid.UUID,
    body: RegistrarPagoRequest,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "registrador")),
    db: AsyncSession = Depends(get_db),
):
    """
    Registra el monto pagado de una cuota.
    FLUJO: primero el recaudador valida (check), luego el registrador registra montos.
    Si hay excedente, retorna requiere_decision=True para que el
    frontend muestre el modal de decisión.
    """
    pago, credito = await _get_pago_con_credito(db, pago_id)

    if pago.pagado:
        raise HTTPException(status_code=422, detail="Esta cuota ya fue pagada")

    if not credito.activo:
        raise HTTPException(status_code=422, detail="El crédito está cerrado")

    if not pago.validado_recaudador:
        raise HTTPException(
            status_code=422,
            detail="El pago debe ser validado por el recaudador antes de registrar montos"
        )

    result = await PagoService.registrar_pago(
        db=db,
        pago=pago,
        credito=credito,
        request=body,
        fecha_hoy=hoy_bogota(),
    )

    if not result.requiere_decision:
        await audit_service.registrar_actualizacion_campos(
            db=db, entidad="pagos", entidad_id=pago.id,
            usuario_id=current_user.id, ip_origen=get_client_ip(request),
            cambios={
                "capital_pagado": ("0", str(body.capital_pagado)),
                "interes_pagado": ("0", str(body.interes_pagado)),
                "pagado": ("False", "True"),
            },
        )

    return result


class ConfirmarExcedenteBody(BaseModel):
    capital_pagado: float
    interes_pagado: float
    destino_excedente: str

@router.post("/{pago_id}/confirmar-excedente", response_model=RegistrarPagoResponse)
async def confirmar_excedente(
    pago_id: uuid.UUID,
    body: ConfirmarExcedenteBody,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "registrador")),
    db: AsyncSession = Depends(get_db),
):
    pago, credito = await _get_pago_con_credito(db, pago_id)

    if pago.pagado:
        raise HTTPException(status_code=422, detail="Esta cuota ya fue pagada")

    from app.schemas.pago import RegistrarPagoRequest
    from app.models.pago import DestinoExcedente

    montos = RegistrarPagoRequest(
        capital_pagado=body.capital_pagado,
        interes_pagado=body.interes_pagado,
    )

    result = await PagoService.confirmar_excedente(
        db=db,
        pago=pago,
        credito=credito,
        request=montos,
        destino=DestinoExcedente(body.destino_excedente),
        fecha_hoy=hoy_bogota(),
    )

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="pagos", entidad_id=pago.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
        cambios={
            "capital_pagado": ("0", str(body.capital_pagado)),
            "interes_pagado": ("0", str(body.interes_pagado)),
            "pagado": ("False", "True"),
            "es_excedente_a": ("None", body.destino_excedente),
        },
    )
    return result


@router.post("/{pago_id}/desvalidar", response_model=PagoResponse)
async def desvalidar_pago(
    pago_id: uuid.UUID,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    """
    Revierte la validación (check) de un pago.
    Solo permitido si el pago no ha sido pagado y no tiene montos registrados.
    """
    pago, _ = await _get_pago_con_credito(db, pago_id)

    if pago.pagado:
        raise HTTPException(
            status_code=422,
            detail="No se puede revertir: el pago ya fue registrado con montos.",
        )
    if pago.capital_pagado > 0 or pago.interes_pagado > 0:
        raise HTTPException(
            status_code=422,
            detail="No se puede revertir: el pago tiene montos registrados.",
        )
    if not pago.validado_recaudador:
        raise HTTPException(status_code=422, detail="Este pago no estaba validado.")

    tipo_anterior = pago.tipo_validacion
    pago.validado_recaudador = False
    pago.tipo_validacion = None

    cambios = {"validado_recaudador": ("True", "False")}
    if tipo_anterior is not None:
        cambios["tipo_validacion"] = (str(tipo_anterior), "None")

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="pagos", entidad_id=pago.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
        cambios=cambios,
    )
    return PagoResponse.model_validate(pago)


@router.post("/revertir-validaciones-bulk")
async def revertir_validaciones_bulk(
    request: Request,
    anio: int,
    mes: int,
    momento: str,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    ENDPOINT TEMPORAL — Revierte validado_recaudador para todos los pagos del
    período sin montos registrados.
    """
    if momento not in ("m1", "m2", "m3", "m4", "m5"):
        raise HTTPException(status_code=400, detail="Momento inválido")

    fecha_inicio, fecha_fin = get_periodo_momento(anio, mes, momento)
    pagos = (await db.execute(
        select(Pago).where(
            Pago.deleted_at == None,  # noqa: E711
            Pago.fecha_maxima >= fecha_inicio,
            Pago.fecha_maxima <= fecha_fin,
            Pago.validado_recaudador == True,  # noqa: E712
            Pago.pagado == False,  # noqa: E712
            Pago.capital_pagado == 0,
            Pago.interes_pagado == 0,
        )
    )).scalars().all()

    ip = get_client_ip(request)
    revertidos = 0
    for pago in pagos:
        antes_tipo = pago.tipo_validacion
        pago.validado_recaudador = False
        pago.tipo_validacion = None
        cambios = {"validado_recaudador": ("True", "False")}
        if antes_tipo is not None:
            cambios["tipo_validacion"] = (str(antes_tipo), "None")
        await audit_service.registrar_actualizacion_campos(
            db=db, entidad="pagos", entidad_id=pago.id,
            usuario_id=current_user.id, ip_origen=ip, cambios=cambios,
        )
        revertidos += 1

    return {"periodo": f"{anio}-{mes:02d} {momento}", "revertidos": revertidos}


@router.post("/{pago_id}/validar", response_model=PagoResponse)
async def validar_pago(
    pago_id: uuid.UUID,
    request: Request,
    body: Optional[ValidarPagoRequest] = Body(default=None),
    current_user: Usuario = Depends(require_role("admin", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    """
    Recaudador/Admin marca el pago como validado (check) y declara el tipo
    de pago observado: completo, incompleto o con_excedente. Esa información
    sirve de hint para el registrador.
    """
    pago, _ = await _get_pago_con_credito(db, pago_id)

    if pago.validado_recaudador:
        raise HTTPException(status_code=422, detail="Este pago ya fue validado")

    pago.validado_recaudador = True
    cambios = {"validado_recaudador": ("False", "True")}
    if body and body.tipo_validacion is not None:
        cambios["tipo_validacion"] = (str(pago.tipo_validacion), body.tipo_validacion)
        pago.tipo_validacion = body.tipo_validacion

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="pagos", entidad_id=pago.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
        cambios=cambios,
    )
    return PagoResponse.model_validate(pago)


@router.patch("/{pago_id}/fecha", response_model=PagoResponse)
async def modificar_fecha_pago(
    pago_id: uuid.UUID,
    body: ModificarFechaPagoRequest,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    """
    Recaudador/Admin modifica la fecha_maxima de UN pago individual.
    NO afecta el ciclo de pagos siguientes (a diferencia del Admin
    que modifica desde la ventana de créditos).
    """
    pago, _ = await _get_pago_con_credito(db, pago_id)

    fecha_anterior = pago.fecha_maxima
    pago.fecha_maxima = body.fecha_maxima
    # NOTA: NO se recalcula el momento ni las fechas siguientes
    # (eso es exclusivo del Admin desde ventana de créditos)

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="pagos", entidad_id=pago.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
        cambios={"fecha_maxima": (str(fecha_anterior), str(body.fecha_maxima))},
    )
    return PagoResponse.model_validate(pago)


@router.patch("/{pago_id}/receptor", response_model=PagoResponse)
async def modificar_receptor_pago(
    pago_id: uuid.UUID,
    body: ModificarReceptorPagoRequest,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    """
    Recaudador/Admin modifica el receptor de un pago individual.
    Esta modificación NO propaga a siguientes pagos.
    """
    pago, _ = await _get_pago_con_credito(db, pago_id)

    receptor_anterior = pago.receptor_id
    pago.receptor_id = body.receptor_id

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="pagos", entidad_id=pago.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
        cambios={"receptor_id": (str(receptor_anterior), str(body.receptor_id))},
    )
    return PagoResponse.model_validate(pago)


@router.post("/no-programado/{credito_id}", response_model=PagoResponse, status_code=201)
async def registrar_pago_no_programado(
    credito_id: uuid.UUID,
    body: PagoNoProgramadoRequest,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "registrador")),
    db: AsyncSession = Depends(get_db),
):
    """
    Registra un pago no programado sobre un crédito.
    No afecta las cuotas programadas existentes.
    """
    credito = (await db.execute(
        select(Credito).where(Credito.id == credito_id, Credito.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    # Obtener receptor por defecto del gestor
    cliente = (await db.execute(select(Cliente).where(Cliente.id == credito.cliente_id))).scalar_one()
    gestor = (await db.execute(select(Gestor).where(Gestor.id == cliente.gestor_id))).scalar_one_or_none()
    receptor_id = gestor.receptor_id if gestor else None

    pago = await PagoService.registrar_pago_no_programado(
        db=db,
        credito=credito,
        monto=body.monto,
        destino=body.destino,
        fecha_pago=body.fecha_pago,
        receptor_id=receptor_id,
    )

    await audit_service.registrar_creacion(
        db=db, entidad="pagos", entidad_id=pago.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )
    return PagoResponse.model_validate(pago)


# --- Alertas ---

@router.get("/alertas/proximos-vencer")
async def alertas_proximos_vencer(
    dias: int = Query(3, ge=1, le=30),
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pagos cuya fecha_maxima está dentro de los próximos N días."""
    hoy = hoy_bogota()
    from datetime import timedelta
    limite = hoy + timedelta(days=dias)

    query = (
        select(Pago)
        .join(Credito, Pago.credito_id == Credito.id)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .where(
            Pago.pagado == False,  # noqa: E712
            Pago.deleted_at == None,  # noqa: E711
            Pago.fecha_maxima >= hoy,
            Pago.fecha_maxima <= limite,
        )
    )

    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = query.where(Cliente.gestor_id == gestor.id)

    pagos = (await db.execute(query.order_by(Pago.fecha_maxima))).scalars().all()
    return [PagoResponse.model_validate(p) for p in pagos]


@router.get("/alertas/vencidos")
async def alertas_vencidos(
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pagos vencidos (fecha_maxima < hoy y pagado=False)."""
    hoy = hoy_bogota()

    query = (
        select(Pago)
        .join(Credito, Pago.credito_id == Credito.id)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .where(
            Pago.pagado == False,  # noqa: E712
            Pago.deleted_at == None,  # noqa: E711
            Pago.fecha_maxima < hoy,
        )
    )

    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = query.where(Cliente.gestor_id == gestor.id)

    pagos = (await db.execute(query.order_by(Pago.fecha_maxima))).scalars().all()
    total_mora = sum(p.monto_a_pagar - p.capital_pagado - p.interes_pagado for p in pagos)

    return {
        "total_pagos_vencidos": len(pagos),
        "total_monto_mora": float(total_mora),
        "pagos": [PagoResponse.model_validate(p) for p in pagos],
    }


# --- Helper ---

async def _get_pago_con_credito(
    db: AsyncSession,
    pago_id: uuid.UUID,
) -> tuple[Pago, Credito]:
    pago = (await db.execute(
        select(Pago).where(Pago.id == pago_id, Pago.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    credito = (await db.execute(
        select(Credito).where(Credito.id == pago.credito_id)
    )).scalar_one_or_none()
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito asociado no encontrado")

    return pago, credito
