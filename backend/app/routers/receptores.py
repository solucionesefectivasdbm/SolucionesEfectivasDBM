"""routers/receptores.py — CRUD de receptores y sus cuentas bancarias."""
import math
import uuid
from typing import Optional
from app.utils.fechas import ahora_bogota

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
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
from app.schemas.receptor_movimiento import MovimientoResponse, SaldoReceptorResponse
from app.services import audit_service, cuenta_bancaria_service, receptor_ledger_service

router = APIRouter(prefix="/receptores", tags=["Receptores"])

# item 9 (receiver-cash-balance): tupla a nivel de módulo para que sumar un
# rol futuro (p.ej. "registrador") sea un diff de una línea (decision 3).
ROLES_LECTURA_SALDO = ("admin", "recaudador")  # coincide con listar_receptores


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
        # Búsqueda por palabras: cada token debe aparecer en nombre o cédula,
        # igual que en clientes. Permite buscar nombre completo o documento.
        terminos = [t for t in busqueda.strip().split() if t]
        if terminos:
            condiciones = [
                or_(
                    Receptor.nombre.ilike(f"%{t}%"),
                    Receptor.cedula.ilike(f"%{t}%"),
                )
                for t in terminos
            ]
            query = query.where(and_(*condiciones))

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


@router.get("/saldos", response_model=list[SaldoReceptorResponse])
async def saldos_receptores(
    receptor_ids: str = Query(..., description="UUIDs de receptores separados por coma"),
    current_user: Usuario = Depends(require_role(*ROLES_LECTURA_SALDO)),
    db: AsyncSession = Depends(get_db),
):
    """
    Saldo agregado por receptor, para varios receptores a la vez (usado por
    la columna "Saldo" del listado). Es un bulk lookup, no un chequeo de
    existencia: un receptor_id desconocido simplemente no tiene cuentas y
    su saldo_total es 0 — la verificación 404 vive en el endpoint singular
    GET /{receptor_id}/saldo, más abajo.

    CRÍTICO: esta ruta debe registrarse ANTES de GET /{receptor_id} — si no,
    el path param UUID de esa ruta la eclipsa e intenta parsear "saldos"
    como UUID, devolviendo 422 en vez de despachar aquí.
    """
    ids: list[uuid.UUID] = []
    for token in receptor_ids.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(uuid.UUID(token))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"receptor_id inválido: {token}")

    resultado = await receptor_ledger_service.saldos_por_receptor(db, ids)
    return [resultado[rid] for rid in ids]


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

    es_predeterminada = await cuenta_bancaria_service.sin_predeterminada(db, receptor_id)
    cuenta = CuentaBancaria(
        receptor_id=receptor_id, es_predeterminada=es_predeterminada, **body.model_dump()
    )
    db.add(cuenta)
    try:
        await db.flush()
    except IntegrityError:
        # Carrera: otra transacción ya dejó una predeterminada (índice único parcial).
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El receptor ya tiene una cuenta predeterminada",
        )
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


@router.put("/{receptor_id}/cuentas/{cuenta_id}/predeterminada", response_model=CuentaBancariaResponse)
async def marcar_cuenta_predeterminada(
    receptor_id: uuid.UUID,
    cuenta_id: uuid.UUID,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    receptor = (await db.execute(
        select(Receptor).where(Receptor.id == receptor_id, Receptor.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    cuenta_anterior = (await db.execute(
        select(CuentaBancaria).where(
            CuentaBancaria.receptor_id == receptor_id,
            CuentaBancaria.es_predeterminada == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    cuenta_anterior_id = cuenta_anterior.id if cuenta_anterior else None

    try:
        cuenta = await cuenta_bancaria_service.marcar_predeterminada(db, receptor_id, cuenta_id)
    except IntegrityError:
        # Carrera con otro cambio de predeterminada: el índice único parcial rechazó el UPDATE.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto al cambiar la cuenta predeterminada, reintente",
        )

    await audit_service.registrar_actualizacion_campos(
        db=db, entidad="receptores", entidad_id=receptor_id,
        usuario_id=current_user.id, ip_origen=get_client_ip(request),
        cambios={"es_predeterminada": (str(cuenta_anterior_id), str(cuenta.id))},
    )
    return CuentaBancariaResponse.model_validate(cuenta)


# --- Ledger de movimientos (item 9, receiver-cash-balance) ---

@router.get("/{receptor_id}/saldo", response_model=SaldoReceptorResponse)
async def saldo_receptor(
    receptor_id: uuid.UUID,
    current_user: Usuario = Depends(require_role(*ROLES_LECTURA_SALDO)),
    db: AsyncSession = Depends(get_db),
):
    """Saldo total del receptor y desglose por cuenta bancaria. A diferencia
    de GET /saldos (bulk), aquí sí se exige que el receptor exista y no
    esté borrado lógicamente."""
    receptor = (await db.execute(
        select(Receptor).where(Receptor.id == receptor_id, Receptor.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    resultado = await receptor_ledger_service.saldos_por_receptor(db, [receptor_id])
    return resultado[receptor_id]


@router.get("/{receptor_id}/movimientos", response_model=PaginatedResponse[MovimientoResponse])
async def movimientos_receptor(
    receptor_id: uuid.UUID,
    cuenta_bancaria_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    current_user: Usuario = Depends(require_role(*ROLES_LECTURA_SALDO)),
    db: AsyncSession = Depends(get_db),
):
    """Historial paginado de salidas/correcciones del receptor, opcionalmente
    acotado a una sola cuenta bancaria."""
    receptor = (await db.execute(
        select(Receptor).where(Receptor.id == receptor_id, Receptor.deleted_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    items, total = await receptor_ledger_service.listar_movimientos(
        db, receptor_id, cuenta_bancaria_id=cuenta_bancaria_id, page=page, page_size=page_size,
    )
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )
