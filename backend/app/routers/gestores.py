"""routers/gestores.py — CRUD de gestores y asignación de receptores."""
import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_role
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.gestor import Gestor
from app.models.pago import Pago
from app.models.receptor import Receptor
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.common import PaginatedResponse
from app.schemas.gestor import GestorCreate, GestorResponse, GestorUpdate
from app.services import audit_service

router = APIRouter(prefix="/gestores", tags=["Gestores"])


def _query_con_relaciones():
    """Query base que carga receptor y sus cuentas_bancarias en un solo viaje."""
    return (
        select(Gestor)
        .where(Gestor.deleted_at == None)  # noqa: E711
        .options(
            selectinload(Gestor.receptor).selectinload(Receptor.cuentas_bancarias)
        )
    )


@router.get("", response_model=PaginatedResponse[GestorResponse])
async def listar_gestores(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    busqueda: str = Query(""),
    current_user: Usuario = Depends(require_role("admin", "registrador", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    query = _query_con_relaciones()

    if busqueda:
        query = query.where(
            (Gestor.nombre.ilike(f"%{busqueda}%")) | (Gestor.apellidos.ilike(f"%{busqueda}%"))
        )

    # Contar sin el selectinload para eficiencia
    count_query = select(func.count(Gestor.id)).where(Gestor.deleted_at == None)  # noqa: E711
    if busqueda:
        count_query = count_query.where(
            (Gestor.nombre.ilike(f"%{busqueda}%")) | (Gestor.apellidos.ilike(f"%{busqueda}%"))
        )

    total = (await db.execute(count_query)).scalar()
    items = (await db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return PaginatedResponse(
        items=[GestorResponse.model_validate(g) for g in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=GestorResponse, status_code=status.HTTP_201_CREATED)
async def crear_gestor(
    body: GestorCreate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    # Verificar cédula única
    if (await db.execute(
        select(Gestor).where(Gestor.cedula == body.cedula, Gestor.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cédula ya registrada")

    # Verificar que el user_id existe y tiene rol gestor
    usuario = (await db.execute(
        select(Usuario).where(Usuario.id == body.user_id, Usuario.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.tipo_usuario != TipoUsuario.gestor:
        raise HTTPException(status_code=422, detail="El usuario debe tener rol 'gestor'")

    gestor = Gestor(**body.model_dump())
    db.add(gestor)
    await db.flush()

    await audit_service.registrar_creacion(
        db=db, entidad="gestores", entidad_id=gestor.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )

    # Recargar con relaciones completas
    result = await db.execute(
        _query_con_relaciones().where(Gestor.id == gestor.id)
    )
    gestor = result.scalar_one()
    return GestorResponse.model_validate(gestor)


@router.get("/me", response_model=GestorResponse)
async def obtener_mi_perfil_gestor(
    current_user: Usuario = Depends(require_role("gestor")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        _query_con_relaciones().where(Gestor.user_id == current_user.id)
    )
    gestor = result.scalar_one_or_none()
    if not gestor:
        raise HTTPException(status_code=404, detail="Perfil de gestor no encontrado")
    return GestorResponse.model_validate(gestor)


@router.get("/{gestor_id}", response_model=GestorResponse)
async def obtener_gestor(
    gestor_id: uuid.UUID,
    current_user: Usuario = Depends(require_role("admin", "registrador", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        _query_con_relaciones().where(Gestor.id == gestor_id)
    )
    gestor = result.scalar_one_or_none()
    if not gestor:
        raise HTTPException(status_code=404, detail="Gestor no encontrado")
    return GestorResponse.model_validate(gestor)


@router.patch("/{gestor_id}", response_model=GestorResponse)
async def actualizar_gestor(
    gestor_id: uuid.UUID,
    body: GestorUpdate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        _query_con_relaciones().where(Gestor.id == gestor_id)
    )
    gestor = result.scalar_one_or_none()
    if not gestor:
        raise HTTPException(status_code=404, detail="Gestor no encontrado")

    cambios = {}
    receptor_cambiado = False

    for field, value in body.model_dump(exclude_none=True).items():
        if field == "receptor_id":
            receptor_cambiado = True
        cambios[field] = (str(getattr(gestor, field)), str(value))
        setattr(gestor, field, value)

    if receptor_cambiado and body.receptor_id is not None:
        await _propagar_receptor_a_pagos(db, gestor_id, body.receptor_id)

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="gestores", entidad_id=gestor.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request), cambios=cambios,
    )

    await db.flush()

    # Recargar con relaciones
    result = await db.execute(
        _query_con_relaciones().where(Gestor.id == gestor_id)
    )
    gestor = result.scalar_one()
    return GestorResponse.model_validate(gestor)


async def _propagar_receptor_a_pagos(
    db: AsyncSession,
    gestor_id: uuid.UUID,
    nuevo_receptor_id: uuid.UUID,
) -> None:
    subq = (
        select(Credito.id)
        .join(Cliente, Credito.cliente_id == Cliente.id)
        .where(
            Cliente.gestor_id == gestor_id,
            Cliente.deleted_at == None,  # noqa: E711
            Credito.deleted_at == None,  # noqa: E711
        )
    ).scalar_subquery()

    await db.execute(
        update(Pago)
        .where(
            Pago.pagado == False,  # noqa: E712
            Pago.credito_id.in_(subq),
        )
        .values(receptor_id=nuevo_receptor_id)
    )