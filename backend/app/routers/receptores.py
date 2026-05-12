"""routers/receptores.py — CRUD de receptores y sus cuentas bancarias."""
import math
import uuid
from datetime import datetime, timezone
from app.utils.fechas import ahora_bogota

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_client_ip, require_role
from app.models.receptor import CuentaBancaria, Receptor
from app.models.usuario import Usuario
from app.schemas.common import PaginatedResponse
from app.schemas.receptor import (
    CuentaBancariaCreate,
    CuentaBancariaResponse,
    ReceptorCreate,
    ReceptorResponse,
    ReceptorUpdate,
)
from app.services import audit_service

router = APIRouter(prefix="/receptores", tags=["Receptores"])


@router.get("", response_model=PaginatedResponse[ReceptorResponse])
async def listar_receptores(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    busqueda: str = Query(""),
    current_user: Usuario = Depends(require_role("admin", "recaudador")),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Receptor)
        .where(Receptor.deleted_at == None)  # noqa: E711
        .options(selectinload(Receptor.cuentas_bancarias))
    )
    if busqueda:
        query = query.where(Receptor.nombre.ilike(f"%{busqueda}%"))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    items = (await db.execute(
        query.order_by(Receptor.nombre, Receptor.id).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return PaginatedResponse(
        items=[ReceptorResponse.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=ReceptorResponse, status_code=status.HTTP_201_CREATED)
async def crear_receptor(
    body: ReceptorCreate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(Receptor).where(Receptor.cedula == body.cedula, Receptor.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cédula ya registrada")

    receptor = Receptor(**body.model_dump())
    db.add(receptor)
    await db.flush()

    await audit_service.registrar_creacion(
        db=db, entidad="receptores", entidad_id=receptor.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )
    await db.refresh(receptor, ["cuentas_bancarias"])
    return ReceptorResponse.model_validate(receptor)


@router.get("/{receptor_id}", response_model=ReceptorResponse)
async def obtener_receptor(
    receptor_id: uuid.UUID,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Receptor)
        .where(Receptor.id == receptor_id, Receptor.deleted_at == None)  # noqa: E711
        .options(selectinload(Receptor.cuentas_bancarias))
    )
    receptor = result.scalar_one_or_none()
    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")
    return ReceptorResponse.model_validate(receptor)


@router.patch("/{receptor_id}", response_model=ReceptorResponse)
async def actualizar_receptor(
    receptor_id: uuid.UUID,
    body: ReceptorUpdate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Receptor)
        .where(Receptor.id == receptor_id, Receptor.deleted_at == None)  # noqa: E711
        .options(selectinload(Receptor.cuentas_bancarias))
    )
    receptor = result.scalar_one_or_none()
    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    cambios = {}
    for field, value in body.model_dump(exclude_none=True).items():
        cambios[field] = (str(getattr(receptor, field)), str(value))
        setattr(receptor, field, value)

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="receptores", entidad_id=receptor.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request), cambios=cambios,
    )
    return ReceptorResponse.model_validate(receptor)


@router.delete("/{receptor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_receptor(
    receptor_id: uuid.UUID,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Receptor).where(Receptor.id == receptor_id, Receptor.deleted_at == None)  # noqa: E711
    )
    receptor = result.scalar_one_or_none()
    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    receptor.deleted_at = ahora_bogota()
    await audit_service.registrar_eliminacion(
        db=db, entidad="receptores", entidad_id=receptor.id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
    )


# --- Cuentas bancarias ---

@router.post("/{receptor_id}/cuentas", response_model=CuentaBancariaResponse, status_code=201)
async def agregar_cuenta(
    receptor_id: uuid.UUID,
    body: CuentaBancariaCreate,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    receptor = (await db.execute(
        select(Receptor).where(Receptor.id == receptor_id, Receptor.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    cuenta = CuentaBancaria(receptor_id=receptor_id, **body.model_dump())
    db.add(cuenta)
    await db.flush()
    return CuentaBancariaResponse.model_validate(cuenta)


@router.patch("/{receptor_id}/cuentas/{cuenta_id}", response_model=CuentaBancariaResponse)
async def actualizar_cuenta(
    receptor_id: uuid.UUID,
    cuenta_id: uuid.UUID,
    body: CuentaBancariaCreate,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    cuenta = (await db.execute(
        select(CuentaBancaria).where(
            CuentaBancaria.id == cuenta_id,
            CuentaBancaria.receptor_id == receptor_id,
        )
    )).scalar_one_or_none()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    for field, value in body.model_dump().items():
        setattr(cuenta, field, value)
    return CuentaBancariaResponse.model_validate(cuenta)
