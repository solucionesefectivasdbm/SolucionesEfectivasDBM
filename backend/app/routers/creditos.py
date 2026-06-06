"""routers/creditos.py — Gestión de créditos (cuota fija y abono a capital)."""
import math
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_role
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito
from app.models.gestor import Gestor
from app.models.pago import Pago
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.common import PaginatedResponse
from app.schemas.credito import CreditoCreate, CreditoResponse, CreditoUpdate, DiasPagoUpdate
from app.schemas.pago import PagoResponse
from app.services.credito_service import _periodos_por_mes
from app.services import audit_service
from app.services.credito_service import (
    crear_primera_cuota,
    generar_numero_credito,
    generar_prefijo_cliente,
    recalcular_cuota_actual_si_no_pagada,
    recalcular_cuotas_futuras,
    recalcular_saldo_intereses,
)
from app.utils.tz import ahora_bogota

router = APIRouter(prefix="/creditos", tags=["Créditos"])


@router.get("", response_model=PaginatedResponse[CreditoResponse])
async def listar_creditos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    busqueda: str = Query("", description="Buscar por nombre o cédula de cliente"),
    solo_activos: bool = Query(True),
    cliente_id: uuid.UUID | None = Query(None, description="Filtrar por cliente"),
    gestor_id: uuid.UUID | None = Query(None, description="Filtrar por gestor"),
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Credito)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .where(Credito.deleted_at == None, Cliente.deleted_at == None)  # noqa: E711
    )

    if cliente_id:
        query = query.where(Credito.cliente_id == cliente_id)

    if solo_activos:
        query = query.where(Credito.activo == True)  # noqa: E712

    # Gestor: solo sus clientes
    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = query.where(Cliente.gestor_id == gestor.id)
    elif gestor_id:
        query = query.where(Cliente.gestor_id == gestor_id)

    if busqueda:
        # Búsqueda por palabras: cada token debe aparecer en algún campo.
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

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    items = (await db.execute(
        query.order_by(Credito.numero_credito_cliente, Credito.id).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return PaginatedResponse(
        items=[CreditoResponse.model_validate(c) for c in items],
        total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/resumen-cartera")
async def resumen_cartera(
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Saldo total de la cartera: suma de saldo_capital + saldo_intereses de créditos activos."""
    query = select(
        func.coalesce(func.sum(Credito.saldo_capital), 0),
        func.coalesce(func.sum(Credito.saldo_intereses), 0),
    ).where(
        Credito.activo == True,  # noqa: E712
        Credito.deleted_at == None,  # noqa: E711
    )

    # Gestor: solo sus clientes
    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = query.join(Cliente, Credito.cliente_id == Cliente.id).where(
                Cliente.gestor_id == gestor.id
            )

    row = (await db.execute(query)).one()
    total_capital = row[0]
    total_intereses = row[1]

    return {
        "saldo_capital": float(total_capital),
        "saldo_intereses": float(total_intereses),
        "saldo_total": float(total_capital + total_intereses),
    }


@router.post("", response_model=CreditoResponse, status_code=status.HTTP_201_CREATED)
async def crear_credito(
    body: CreditoCreate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "registrador")),
    db: AsyncSession = Depends(get_db),
):
    # Verificar cliente existente
    cliente = (await db.execute(
        select(Cliente).where(Cliente.id == body.cliente_id, Cliente.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Generar número de crédito con prefijo basado en el nombre del cliente
    prefijo = await generar_prefijo_cliente(db, cliente)
    numero = await generar_numero_credito(db, prefijo)

    credito = Credito(
        cliente_id=body.cliente_id,
        numero_credito_cliente=numero,
        tipo_credito=body.tipo_credito,
        capital_prestado=body.capital_prestado,
        tasa_interes_mensual=body.tasa_interes_mensual,
        fecha_apertura=body.fecha_apertura,
        fecha_inicial_pago=body.fecha_inicial_pago,
        periodicidad=body.periodicidad,
        anchor_dia_1=body.anchor_dia_1,
        anchor_dia_2=body.anchor_dia_2,
        saldo_capital=body.capital_prestado,
        # cuota_fija: el interés total se conoce desde el inicio → se lleva saldo.
        # abono_capital: el interés total es indeterminado → NO lleva saldo (0).
        # En ambos casos el interés de cada período se cobra en la cuota.
        saldo_intereses=(
            body.capital_prestado * body.tasa_interes_mensual
            * (Decimal(body.numero_cuotas) / Decimal(_periodos_por_mes(body.periodicidad)))
        ) if body.numero_cuotas else Decimal("0.00"),
        abono_minimo=body.abono_minimo,
        numero_cuotas=body.numero_cuotas,
        calcular_interes_dias_corridos=body.calcular_interes_dias_corridos,
    )
    db.add(credito)
    await db.flush()  # Obtener el ID

    # Obtener receptor del gestor del cliente
    gestor = (await db.execute(
        select(Gestor).where(Gestor.id == cliente.gestor_id)
    )).scalar_one_or_none()
    receptor_id = gestor.receptor_id if gestor else None

    # Crear primera cuota
    primera_cuota = await crear_primera_cuota(credito, receptor_id)
    db.add(primera_cuota)

    await audit_service.registrar_creacion(
        db=db, entidad="creditos", entidad_id=credito.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )
    return CreditoResponse.model_validate(credito)


@router.get("/{credito_id}", response_model=CreditoResponse)
async def obtener_credito(
    credito_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Credito).where(Credito.id == credito_id, Credito.deleted_at == None)  # noqa: E711

    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = (
                query.join(Cliente, Credito.cliente_id == Cliente.id)
                .where(Cliente.gestor_id == gestor.id)
            )

    credito = (await db.execute(query)).scalar_one_or_none()
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")
    return CreditoResponse.model_validate(credito)


@router.patch("/{credito_id}", response_model=CreditoResponse)
async def actualizar_credito(
    credito_id: uuid.UUID,
    body: CreditoUpdate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Solo Admin. Permite modificar capital, tasa y abono mínimo.
    Para re-anclar fechas de pago usar PATCH /creditos/{id}/dias-pago.
    """
    credito = (await db.execute(
        select(Credito).where(Credito.id == credito_id, Credito.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    if not credito.activo:
        raise HTTPException(
            status_code=422,
            detail="No se puede modificar un crédito cerrado"
        )

    cambios = {}
    requiere_recalculo = False

    # Solo recomputar si el capital REALMENTE cambió. El formulario de edición
    # reenvía capital_prestado (pre-cargado) aunque el admin solo cambie la
    # fecha; sin este guard, eso reseteaba saldo_capital al capital completo.
    if body.capital_prestado is not None and body.capital_prestado != credito.capital_prestado:
        cambios["capital_prestado"] = (str(credito.capital_prestado), str(body.capital_prestado))
        credito.capital_prestado = body.capital_prestado

        # saldo_capital debe descontar el capital YA pagado, no resetearse al
        # capital completo (si no, "resucita" el capital de las cuotas ya pagadas).
        capital_pagado_total = (await db.execute(
            select(func.coalesce(func.sum(Pago.capital_pagado), Decimal("0.00"))).where(
                Pago.credito_id == credito.id,
                Pago.deleted_at == None,  # noqa: E711
            )
        )).scalar() or Decimal("0.00")
        saldo_capital_anterior = str(credito.saldo_capital)
        nuevo_saldo = (body.capital_prestado - Decimal(str(capital_pagado_total))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        credito.saldo_capital = max(Decimal("0.00"), nuevo_saldo)
        cambios["saldo_capital"] = (saldo_capital_anterior, str(credito.saldo_capital))
        requiere_recalculo = True

    if body.tasa_interes_mensual is not None:
        cambios["tasa_interes_mensual"] = (str(credito.tasa_interes_mensual), str(body.tasa_interes_mensual))
        credito.tasa_interes_mensual = body.tasa_interes_mensual
        requiere_recalculo = True

    if body.abono_minimo is not None:
        cambios["abono_minimo"] = (str(credito.abono_minimo), str(body.abono_minimo))
        credito.abono_minimo = body.abono_minimo
        requiere_recalculo = True

    # Si cambió capital, tasa o abono mínimo, hay que actualizar:
    # 1) saldo_intereses (que se calculó al crear y nunca se ajusta solo)
    # 2) la cuota ACTUAL (primera sin pagar) — el cambio se refleja desde la
    #    cuota actual, no solo en las posteriores que se generen luego.
    if requiere_recalculo:
        saldo_intereses_anterior = str(credito.saldo_intereses)
        await recalcular_saldo_intereses(db, credito)
        cambios["saldo_intereses"] = (saldo_intereses_anterior, str(credito.saldo_intereses))

        await db.flush()
        recalculada = await recalcular_cuota_actual_si_no_pagada(db, credito)
        if recalculada:
            cambios["cuota_actual_recalculada"] = ("no", "si")

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="creditos", entidad_id=credito.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request), cambios=cambios,
    )
    return CreditoResponse.model_validate(credito)


@router.patch("/{credito_id}/dias-pago", response_model=CreditoResponse)
async def actualizar_dias_pago(
    credito_id: uuid.UUID,
    body: DiasPagoUpdate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "registrador", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin / Registrador / Recaudador. Re-anchors pending cuota dates to new anchor days.
    Only fecha_maxima/momento of PENDING cuotas change — paid cuotas and all amounts
    remain untouched.
    """
    from app.models.credito import Periodicidad as Per
    from app.utils.fechas import siguiente_fecha_maxima

    credito = (await db.execute(
        select(Credito).where(Credito.id == credito_id, Credito.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    if not credito.activo:
        raise HTTPException(
            status_code=422,
            detail="No se puede modificar un crédito cerrado",
        )

    p = credito.periodicidad
    if p in (Per.semanal, Per.diario):
        raise HTTPException(
            status_code=422,
            detail="Editar días no aplica para esta periodicidad",
        )

    if p == Per.mensual:
        if body.anchor_dia_2 is not None:
            raise HTTPException(
                status_code=422,
                detail="mensual no admite segundo día",
            )
        d1, d2 = body.anchor_dia_1, None
    else:  # quincenal
        if body.anchor_dia_2 is None:
            raise HTTPException(
                status_code=422,
                detail="quincenal requiere segundo día",
            )
        if body.anchor_dia_1 == body.anchor_dia_2:
            raise HTTPException(
                status_code=422,
                detail="los días deben ser distintos",
            )
        d1, d2 = sorted([body.anchor_dia_1, body.anchor_dia_2])

    old1, old2 = credito.anchor_dia_1, credito.anchor_dia_2
    credito.anchor_dia_1 = d1
    credito.anchor_dia_2 = d2

    # desde_fecha — mirror admin.py:258-277
    ultima_pagada: date | None = (await db.execute(
        select(func.max(Pago.fecha_maxima)).where(
            Pago.credito_id == credito.id,
            Pago.pagado == True,  # noqa: E712
            Pago.deleted_at == None,  # noqa: E711
        )
    )).scalar()

    if ultima_pagada is None:
        desde_fecha = credito.fecha_inicial_pago
    else:
        desde_fecha = siguiente_fecha_maxima(ultima_pagada, credito)

    await recalcular_cuotas_futuras(db, credito, desde_fecha)

    await audit_service.registrar_actualizacion_campos(
        db=db,
        entidad="creditos",
        entidad_id=credito.id,
        usuario_id=current_user.id,
        ip_origen=get_client_ip(request),
        cambios={
            "anchor_fechas": (
                f"d1={old1},d2={old2}",
                f"d1={d1},d2={d2}",
            )
        },
    )

    return CreditoResponse.model_validate(credito)


@router.delete("/{credito_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_credito(
    credito_id: uuid.UUID,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Elimina (soft delete) un crédito si no tiene pagos validados
    ni pagos con montos registrados (capital_pagado o interes_pagado > 0).
    """
    credito = (await db.execute(
        select(Credito).where(Credito.id == credito_id, Credito.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    # Verificar que no haya pagos con montos registrados o validados
    pagos_con_actividad = (await db.execute(
        select(func.count(Pago.id)).where(
            Pago.credito_id == credito_id,
            Pago.deleted_at == None,  # noqa: E711
            (
                (Pago.pagado == True) |  # noqa: E712
                (Pago.validado_recaudador == True) |  # noqa: E712
                (Pago.capital_pagado > 0) |
                (Pago.interes_pagado > 0)
            ),
        )
    )).scalar()

    if pagos_con_actividad > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se puede eliminar el crédito porque tiene pagos validados "
                   "o con montos registrados.",
        )

    # Soft delete del crédito y sus cuotas pendientes
    ahora = ahora_bogota()
    credito.deleted_at = ahora
    credito.activo = False

    # Eliminar cuotas pendientes asociadas
    cuotas_pendientes = (await db.execute(
        select(Pago).where(
            Pago.credito_id == credito_id,
            Pago.deleted_at == None,  # noqa: E711
        )
    )).scalars().all()
    for cuota in cuotas_pendientes:
        cuota.deleted_at = ahora

    await audit_service.registrar_eliminacion(
        db=db, entidad="creditos", entidad_id=credito.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )


@router.get("/{credito_id}/cuotas", response_model=list[PagoResponse])
async def historial_cuotas(
    credito_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Historial completo de cuotas de un crédito."""
    result = await db.execute(
        select(Pago)
        .where(Pago.credito_id == credito_id, Pago.deleted_at == None)  # noqa: E711
        .order_by(Pago.numero_cuota)
    )
    pagos = result.scalars().all()
    return [PagoResponse.model_validate(p) for p in pagos]


