"""routers/clientes.py — CRUD de clientes con control de acceso por rol."""
import math
import uuid
from datetime import datetime, timezone
from app.utils.fechas import ahora_bogota

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_role
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.gestor import Gestor
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.cliente import ClienteCreate, ClienteResponse, ClienteUpdate
from app.schemas.common import PaginatedResponse
from app.services import audit_service

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
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Cliente).where(Cliente.deleted_at == None)  # noqa: E711

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
        query = query.where(
            (Cliente.nombre.ilike(f"%{busqueda}%")) | (Cliente.apellidos.ilike(f"%{busqueda}%"))
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    items = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return PaginatedResponse(
        items=[ClienteResponse.model_validate(c) for c in items],
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

    # Solo Admin puede cambiar gestor
    update_data = body.model_dump(exclude_none=True)
    if "gestor_id" in update_data and current_user.tipo_usuario != TipoUsuario.admin:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede cambiar el gestor")

    cambios = {}
    for field, value in update_data.items():
        cambios[field] = (str(getattr(cliente, field)), str(value))
        setattr(cliente, field, value)

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
    await audit_service.registrar_eliminacion(
        db=db, entidad="clientes", entidad_id=cliente.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )
