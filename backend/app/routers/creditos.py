"""routers/creditos.py — Gestión de créditos (cuota fija y abono a capital)."""
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
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
from app.schemas.credito import CreditoCreate, CreditoResponse, CreditoUpdate
from app.schemas.pago import PagoResponse
from app.services.credito_service import _periodos_por_mes
from app.services import audit_service
from app.services.credito_service import (
    crear_primera_cuota,
    generar_numero_credito,
    generar_prefijo_cliente,
    recalcular_cuotas_futuras,
    sincronizar_prefijos_por_nombre,
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

    if busqueda:
        query = query.where(
            (Cliente.nombre.ilike(f"%{busqueda}%"))
            | (Cliente.apellidos.ilike(f"%{busqueda}%"))
            | (Cliente.cedula.ilike(f"%{busqueda}%"))
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    items = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()

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
        saldo_capital=body.capital_prestado,
        saldo_intereses=body.capital_prestado * body.tasa_interes_mensual * (Decimal(body.numero_cuotas) / Decimal(_periodos_por_mes(body.periodicidad))) if body.numero_cuotas else body.capital_prestado * body.tasa_interes_mensual,
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
    Solo Admin. Permite modificar capital, tasa y fecha del pago activo.
    La modificación de fecha del pago activo recalcula todos los momentos/fechas futuros.
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

    if body.capital_prestado is not None:
        cambios["capital_prestado"] = (str(credito.capital_prestado), str(body.capital_prestado))
        credito.capital_prestado = body.capital_prestado
        credito.saldo_capital = body.capital_prestado

    if body.tasa_interes_mensual is not None:
        cambios["tasa_interes_mensual"] = (str(credito.tasa_interes_mensual), str(body.tasa_interes_mensual))
        credito.tasa_interes_mensual = body.tasa_interes_mensual

    if body.fecha_pago_activo is not None:
        # Esta modificación recalcula TODOS los pagos futuros
        await recalcular_cuotas_futuras(db, credito, body.fecha_pago_activo)
        cambios["fecha_pago_activo"] = (str(credito.fecha_inicial_pago), str(body.fecha_pago_activo))

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="creditos", entidad_id=credito.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request), cambios=cambios,
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


@router.post("/fix-prefijos-nombre")
async def fix_prefijos_nombre(
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    ENDPOINT TEMPORAL — Migración del formato de numero_credito_cliente.

    Convierte TODOS los créditos del formato anterior (p. ej. cédula-based)
    al formato basado en nombre: "{nombre} {apellidos}[(N)]-CR-NNN".
    Idempotente. Auditado. Ejecutar una sola vez tras el deploy.
    """
    ip = get_client_ip(request)

    # Obtener los pares únicos (nombre, apellidos) de clientes ACTIVOS que tengan créditos
    pares = (await db.execute(
        select(Cliente.nombre, Cliente.apellidos)
        .where(Cliente.deleted_at == None)  # noqa: E711
        .distinct()
    )).all()

    total_cambios = 0
    detalles: list[dict] = []

    for nombre, apellidos in pares:
        cambios = await sincronizar_prefijos_por_nombre(db, nombre, apellidos)
        if not cambios:
            continue

        total_cambios += len(cambios)
        detalles.append({
            "nombre": nombre,
            "apellidos": apellidos,
            "cambios": [
                {"credito_id": str(cid), "anterior": ant, "nuevo": nue}
                for cid, ant, nue in cambios
            ],
        })

        for credito_id, anterior, nuevo in cambios:
            await audit_service.registrar_actualizacion_campos(
                db=db, entidad="creditos", entidad_id=credito_id,
                usuario_id=current_user.id, ip_origen=ip,
                cambios={"numero_credito_cliente": (anterior, nuevo)},
            )

    return {
        "grupos_procesados": len(detalles),
        "creditos_renumerados": total_cambios,
        "detalles": detalles,
    }
