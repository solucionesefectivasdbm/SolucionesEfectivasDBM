"""routers/clientes.py — CRUD de clientes con control de acceso por rol."""
import math
import uuid
from datetime import datetime, timezone
from app.utils.fechas import ahora_bogota

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_role
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.gestor import Gestor
from app.models.pago import Pago
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.cliente import ClienteCreate, ClienteResponse, ClienteUpdate
from app.schemas.common import PaginatedResponse
from app.services import audit_service
from app.services.credito_service import sincronizar_prefijos_por_nombre
from app.utils.fechas import hoy_bogota

router = APIRouter(prefix="/clientes", tags=["Clientes"])


def _base_query(current_user: Usuario):
    """Query base filtrada por rol. Gestor solo ve sus propios clientes."""
    query = select(Cliente).where(Cliente.deleted_at == None)  # noqa: E711
    return query


@router.get("", response_model=PaginatedResponse[ClienteResponse])
async def listar_clientes(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    busqueda: str = Query(""),
    gestor_id: uuid.UUID | None = Query(None),
    al_dia: bool | None = Query(None, description="True solo al día, False solo no al día, None todos"),
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Cliente).where(Cliente.deleted_at == None)  # noqa: E711

    # "Al día" se computa automáticamente: cliente está al día si NO tiene
    # ningún pago vencido y sin pagar. El campo persistido en BD ya no se
    # usa para filtrar — se sobrescribe en el response con el valor real.
    hoy = hoy_bogota()
    atrasados_subq = (
        select(Credito.cliente_id)
        .join(Pago, Pago.credito_id == Credito.id)
        .where(
            Credito.deleted_at == None,  # noqa: E711
            Pago.deleted_at == None,  # noqa: E711
            Pago.pagado == False,  # noqa: E712
            Pago.fecha_maxima < hoy,
        )
        .distinct()
    )
    if al_dia is True:
        query = query.where(~Cliente.id.in_(atrasados_subq))
    elif al_dia is False:
        query = query.where(Cliente.id.in_(atrasados_subq))

    # Gestor solo ve sus clientes
    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = query.where(Cliente.gestor_id == gestor.id)
        else:
            return PaginatedResponse(items=[], total=0, page=page, page_size=page_size, pages=0)
    elif gestor_id:
        query = query.where(Cliente.gestor_id == gestor_id)

    if busqueda:
        # Búsqueda por palabras: "Juan Pérez" requiere que cada token aparezca
        # en algún campo (nombre, apellidos o cédula). Permite buscar nombre
        # completo aunque cada palabra esté en columnas distintas.
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
        query.order_by(Cliente.nombre, Cliente.apellidos, Cliente.id).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    # Computar al_dia real para los clientes de la página actual.
    ids_pagina = [c.id for c in items]
    atrasados_set: set = set()
    if ids_pagina:
        atrasados_rows = await db.execute(
            select(Credito.cliente_id)
            .join(Pago, Pago.credito_id == Credito.id)
            .where(
                Credito.cliente_id.in_(ids_pagina),
                Credito.deleted_at == None,  # noqa: E711
                Pago.deleted_at == None,  # noqa: E711
                Pago.pagado == False,  # noqa: E712
                Pago.fecha_maxima < hoy,
            )
            .distinct()
        )
        atrasados_set = set(atrasados_rows.scalars().all())

    response_items = []
    for c in items:
        c.al_dia = c.id not in atrasados_set
        response_items.append(ClienteResponse.model_validate(c))

    return PaginatedResponse(
        items=response_items,
        total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=ClienteResponse, status_code=status.HTTP_201_CREATED)
async def crear_cliente(
    body: ClienteCreate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "registrador")),
    db: AsyncSession = Depends(get_db),
):
    if (await db.execute(
        select(Cliente).where(Cliente.cedula == body.cedula, Cliente.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cédula ya registrada")

    # Verificar que el gestor existe
    gestor = (await db.execute(
        select(Gestor).where(Gestor.id == body.gestor_id, Gestor.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not gestor:
        raise HTTPException(status_code=404, detail="Gestor no encontrado")

    cliente = Cliente(**body.model_dump())
    db.add(cliente)
    await db.flush()

    # Si ya existían clientes con el mismo nombre+apellidos, sus créditos necesitan
    # que se les agregue disambig "(N)". Este cliente recién creado aún no tiene
    # créditos, pero sus hermanos sí podrían.
    renumerados = await sincronizar_prefijos_por_nombre(db, cliente.nombre, cliente.apellidos)
    for credito_id, anterior, nuevo in renumerados:
        await audit_service.registrar_actualizacion_campos(
            db=db, entidad="creditos", entidad_id=credito_id,
            usuario_id=current_user.id, ip_origen=get_client_ip(request),
            cambios={"numero_credito_cliente": (anterior, nuevo)},
        )

    await audit_service.registrar_creacion(
        db=db, entidad="clientes", entidad_id=cliente.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )
    return ClienteResponse.model_validate(cliente)


@router.get("/{cliente_id}", response_model=ClienteResponse)
async def obtener_cliente(
    cliente_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Cliente).where(Cliente.id == cliente_id, Cliente.deleted_at == None)  # noqa: E711

    # Gestor solo puede ver sus propios clientes
    if current_user.tipo_usuario == TipoUsuario.gestor:
        gestor = (await db.execute(
            select(Gestor).where(Gestor.user_id == current_user.id)
        )).scalar_one_or_none()
        if gestor:
            query = query.where(Cliente.gestor_id == gestor.id)

    cliente = (await db.execute(query)).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Computar al_dia
    hoy = hoy_bogota()
    tiene_atraso = (await db.execute(
        select(Pago.id)
        .join(Credito, Pago.credito_id == Credito.id)
        .where(
            Credito.cliente_id == cliente.id,
            Credito.deleted_at == None,  # noqa: E711
            Pago.deleted_at == None,  # noqa: E711
            Pago.pagado == False,  # noqa: E712
            Pago.fecha_maxima < hoy,
        )
        .limit(1)
    )).scalar_one_or_none()
    cliente.al_dia = tiene_atraso is None
    return ClienteResponse.model_validate(cliente)


@router.patch("/{cliente_id}", response_model=ClienteResponse)
async def actualizar_cliente(
    cliente_id: uuid.UUID,
    body: ClienteUpdate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin", "registrador")),
    db: AsyncSession = Depends(get_db),
):
    cliente = (await db.execute(
        select(Cliente).where(Cliente.id == cliente_id, Cliente.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    update_data = body.model_dump(exclude_none=True)

    # Si se está cambiando la cédula, validar unicidad frente a otros clientes activos
    nueva_cedula = update_data.get("cedula")
    if nueva_cedula is not None and nueva_cedula != cliente.cedula:
        duplicado = (await db.execute(
            select(Cliente.id).where(
                Cliente.cedula == nueva_cedula,
                Cliente.id != cliente_id,
                Cliente.deleted_at == None,  # noqa: E711
            )
        )).scalar_one_or_none()
        if duplicado:
            raise HTTPException(
                status_code=409,
                detail="La cédula ya está registrada para otro cliente",
            )

    # Capturar nombre anterior antes de aplicar cambios para detectar si hay que re-sincronizar
    nombre_anterior = cliente.nombre
    apellidos_anterior = cliente.apellidos

    cambios = {}
    for field, value in update_data.items():
        cambios[field] = (str(getattr(cliente, field)), str(value))
        setattr(cliente, field, value)

    # Si cambió nombre o apellidos, renumerar créditos de este cliente y de sus hermanos
    # (los del grupo del nombre viejo pueden perder disambig; los del nombre nuevo pueden ganarlo).
    nombre_cambio = (cliente.nombre, cliente.apellidos) != (nombre_anterior, apellidos_anterior)
    if nombre_cambio:
        ip = get_client_ip(request)
        renumerados: list = []
        renumerados.extend(
            await sincronizar_prefijos_por_nombre(db, nombre_anterior, apellidos_anterior)
        )
        renumerados.extend(
            await sincronizar_prefijos_por_nombre(db, cliente.nombre, cliente.apellidos)
        )
        for credito_id, numero_anterior, numero_nuevo in renumerados:
            await audit_service.registrar_actualizacion_campos(
                db=db, entidad="creditos", entidad_id=credito_id,
                usuario_id=current_user.id, ip_origen=ip,
                cambios={"numero_credito_cliente": (numero_anterior, numero_nuevo)},
            )

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="clientes", entidad_id=cliente.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request), cambios=cambios,
    )
    return ClienteResponse.model_validate(cliente)


@router.delete("/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_cliente(
    cliente_id: uuid.UUID,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    cliente = (await db.execute(
        select(Cliente).where(Cliente.id == cliente_id, Cliente.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Verificar que no tenga créditos activos
    creditos_activos = (await db.execute(
        select(func.count(Credito.id)).where(
            Credito.cliente_id == cliente_id,
            Credito.activo == True,  # noqa: E712
            Credito.deleted_at == None,  # noqa: E711
        )
    )).scalar()

    if creditos_activos > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se puede eliminar el cliente porque tiene créditos activos. "
                   "Primero cierre o liquide todos los créditos.",
        )

    cliente.deleted_at = ahora_bogota()

    # Re-sincronizar prefijos de hermanos: al quedar uno solo activo puede perder el disambig.
    nombre = cliente.nombre
    apellidos = cliente.apellidos
    renumerados = await sincronizar_prefijos_por_nombre(db, nombre, apellidos)
    ip = get_client_ip(request)
    for credito_id, anterior, nuevo in renumerados:
        await audit_service.registrar_actualizacion_campos(
            db=db, entidad="creditos", entidad_id=credito_id,
            usuario_id=current_user.id, ip_origen=ip,
            cambios={"numero_credito_cliente": (anterior, nuevo)},
        )

    await audit_service.registrar_eliminacion(
        db=db, entidad="clientes", entidad_id=cliente.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )
