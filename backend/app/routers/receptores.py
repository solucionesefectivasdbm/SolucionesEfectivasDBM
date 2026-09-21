"""routers/receptores.py — CRUD de receptores y sus cuentas bancarias."""
import math
import uuid
from datetime import datetime, timezone
from typing import Any
from app.utils.fechas import ahora_bogota

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import Boolean, Enum, Integer, UUID as SA_UUID, cast, exists, func, select, table, column, update, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_client_ip, require_role
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.usuario import Usuario
from app.schemas.common import PaginatedResponse
from app.schemas.receptor import (
    CuentaBancariaCreate,
    CuentaBancariaResponse,
    ReceptorCreate,
    ReceptorResponse,
    ReceptorUpdate,
)
from app.services import audit_service, cuenta_bancaria_service

router = APIRouter(prefix="/receptores", tags=["Receptores"])


# ---------------------------------------------------------------------------
# Backfill (PR1b, decision 8) — construcciones Core ligeras, nunca los modelos
# ORM: deben seguir funcionando después de que PR2a quite las relaciones y
# PR4 elimine `receptor_id`. `tipo_cuenta` se tipa con el mismo Enum que el
# modelo para que el valor almacenado sea el NOMBRE del enum ("ahorros"), no
# un literal de texto arbitrario.
# ---------------------------------------------------------------------------
_t_receptores = table("receptores", column("id", SA_UUID(as_uuid=True)), column("deleted_at"))
_t_cuentas = table(
    "cuentas_bancarias",
    column("id", SA_UUID(as_uuid=True)), column("receptor_id", SA_UUID(as_uuid=True)),
    column("entidad_bancaria"),
    column("tipo_cuenta", Enum(TipoCuenta, name="tipo_cuenta_enum")),
    column("numero_cuenta"), column("es_predeterminada", Boolean),
)
_t_gestores = table(
    "gestores", column("id", SA_UUID(as_uuid=True)), column("receptor_id", SA_UUID(as_uuid=True)),
    column("cuenta_bancaria_id", SA_UUID(as_uuid=True)), column("deleted_at"),
)
_t_pagos = table(
    "pagos", column("id", SA_UUID(as_uuid=True)), column("credito_id", SA_UUID(as_uuid=True)),
    column("receptor_id", SA_UUID(as_uuid=True)), column("cuenta_bancaria_id", SA_UUID(as_uuid=True)),
    column("pagado", Boolean), column("deleted_at"),
)
_t_creditos = table(
    "creditos", column("id", SA_UUID(as_uuid=True)), column("cliente_id", SA_UUID(as_uuid=True)),
    column("deleted_at"),
)
_t_clientes = table(
    "clientes", column("id", SA_UUID(as_uuid=True)), column("gestor_id", SA_UUID(as_uuid=True)),
    column("deleted_at"),
)


def _cuentas_sin_default_elegidas():
    """Step 1 selection: the lowest `id` per receptor that has accounts but
    none marked as default. Uses `row_number() OVER (PARTITION BY receptor_id
    ORDER BY id)` instead of `MIN(id)` because PostgreSQL has no min/max
    aggregate for `uuid`; the choice stays deterministic (lowest id)."""
    receptores_sin_default = (
        select(_t_cuentas.c.receptor_id)
        .group_by(_t_cuentas.c.receptor_id)
        .having(func.sum(cast(_t_cuentas.c.es_predeterminada, Integer)) == 0)
    )
    ranked = (
        select(
            _t_cuentas.c.id.label("id"),
            func.row_number()
            .over(partition_by=_t_cuentas.c.receptor_id, order_by=_t_cuentas.c.id)
            .label("rn"),
        )
        .where(_t_cuentas.c.receptor_id.in_(receptores_sin_default))
        .subquery("cuentas_rankeadas")
    )
    return select(ranked.c.id).where(ranked.c.rn == 1)


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


# ---------------------------------------------------------------------------
# ENDPOINT TEMPORAL — eliminar en PR4 (chore/cuenta-bancaria-cleanup) tras un
# ciclo limpio en producción. Declarado antes de las rutas paramétricas
# "/{receptor_id}" para que no compita con ellas.
# ---------------------------------------------------------------------------
@router.post("/admin/backfill-cuentas-bancarias")
async def backfill_cuentas_bancarias(
    dry_run: bool = Query(True),
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Rellena `cuenta_bancaria_id` en gestores/pagos y elige/crea la cuenta
    predeterminada de cada receptor. Idempotente: cada paso está guardado
    por `IS NULL` / `NOT EXISTS default`, así que una segunda corrida no
    escribe nada. `dry_run=true` (default) ejecuta los mismos predicados con
    `COUNT` y no escribe. Nunca sobrescribe un `cuenta_bancaria_id` existente.
    Las filas cuyo default no se puede resolver no se cuentan ni se escriben
    en los pasos 3/4a/4b; solo aparecen en `pendientes` (ver desglose abajo).

    Nota sobre `dry_run`: los pasos 3/4a/4b dependen de que los pasos 1/2/3
    ya hayan escrito. En una base sin predeterminadas ni cuentas genéricas,
    el dry_run reporta 0 en `gestores_actualizados`, `pagos_por_receptor` y
    `pagos_por_gestor`; la corrida real sí los rellena. Los contadores de
    los pasos 1 y 2 sí son un preview fiel.

    ENDPOINT TEMPORAL — eliminar tras ejecutar en producción (PR4).
    """
    # --- Paso 1: elegir predeterminada (menor id via row_number, ver
    # _cuentas_sin_default_elegidas) donde el receptor tiene cuentas pero
    # ninguna marcada como predeterminada ---
    sin_default_min_ids = _cuentas_sin_default_elegidas()
    predeterminadas_elegidas = (await db.execute(
        select(func.count()).select_from(sin_default_min_ids.subquery())
    )).scalar()
    if not dry_run and predeterminadas_elegidas:
        await db.execute(
            update(_t_cuentas)
            .where(_t_cuentas.c.id.in_(sin_default_min_ids))
            .values(es_predeterminada=True)
        )

    # --- Paso 2: crear cuenta genérica predeterminada para receptores activos
    # sin ninguna cuenta ---
    receptores_sin_cuentas = select(_t_receptores.c.id).where(
        _t_receptores.c.deleted_at.is_(None),
        ~exists().where(_t_cuentas.c.receptor_id == _t_receptores.c.id),
    )
    ids_sin_cuentas = [
        row[0] for row in (await db.execute(receptores_sin_cuentas)).all()
    ]
    cuentas_genericas_creadas = len(ids_sin_cuentas)
    if not dry_run and ids_sin_cuentas:
        await db.execute(
            insert(_t_cuentas),
            [
                {
                    "id": uuid.uuid4(), "receptor_id": receptor_id,
                    "entidad_bancaria": "Por definir", "tipo_cuenta": TipoCuenta.ahorros,
                    "numero_cuenta": "0", "es_predeterminada": True,
                }
                for receptor_id in ids_sin_cuentas
            ],
        )

    # --- Paso 3: gestores.cuenta_bancaria_id <- default de gestores.receptor_id ---
    default_por_receptor = (
        select(_t_cuentas.c.id)
        .where(
            _t_cuentas.c.receptor_id == _t_gestores.c.receptor_id,
            _t_cuentas.c.es_predeterminada == True,  # noqa: E712
        )
        .correlate(_t_gestores)
        .scalar_subquery()
    )
    # `isnot(None)` on the scalar subquery keeps rows whose default cannot be
    # resolved (receptor soft-deleted without accounts) out of both the count
    # and the update, so they never write NULL -> NULL and counters reach 0.
    gestores_pred = (
        _t_gestores.c.cuenta_bancaria_id.is_(None)
        & _t_gestores.c.receptor_id.isnot(None)
        & default_por_receptor.isnot(None)
    )
    gestores_actualizados = (await db.execute(
        select(func.count()).select_from(_t_gestores).where(gestores_pred)
    )).scalar()
    if not dry_run and gestores_actualizados:
        await db.execute(
            update(_t_gestores).where(gestores_pred).values(cuenta_bancaria_id=default_por_receptor)
        )

    # --- Paso 4a: pagos.cuenta_bancaria_id <- default de pagos.receptor_id ---
    default_por_receptor_pago = (
        select(_t_cuentas.c.id)
        .where(
            _t_cuentas.c.receptor_id == _t_pagos.c.receptor_id,
            _t_cuentas.c.es_predeterminada == True,  # noqa: E712
        )
        .correlate(_t_pagos)
        .scalar_subquery()
    )
    pagos_receptor_pred = (
        _t_pagos.c.cuenta_bancaria_id.is_(None)
        & _t_pagos.c.receptor_id.isnot(None)
        & default_por_receptor_pago.isnot(None)
    )
    pagos_por_receptor = (await db.execute(
        select(func.count()).select_from(_t_pagos).where(pagos_receptor_pred)
    )).scalar()
    if not dry_run and pagos_por_receptor:
        await db.execute(
            update(_t_pagos).where(pagos_receptor_pred).values(cuenta_bancaria_id=default_por_receptor_pago)
        )

    # --- Paso 4b: pagos no pagados que siguen sin cuenta heredan de
    # credito -> cliente -> gestor.cuenta_bancaria_id ---
    cuenta_via_gestor = (
        select(_t_gestores.c.cuenta_bancaria_id)
        .select_from(
            _t_creditos.join(_t_clientes, _t_clientes.c.id == _t_creditos.c.cliente_id)
            .join(_t_gestores, _t_gestores.c.id == _t_clientes.c.gestor_id)
        )
        .where(
            _t_creditos.c.id == _t_pagos.c.credito_id,
            _t_creditos.c.deleted_at.is_(None),
            _t_clientes.c.deleted_at.is_(None),
            _t_gestores.c.deleted_at.is_(None),
        )
        .correlate(_t_pagos)
        .scalar_subquery()
    )
    pagos_gestor_base = (
        (_t_pagos.c.pagado == False)  # noqa: E712
        & _t_pagos.c.deleted_at.is_(None)
        & _t_pagos.c.cuenta_bancaria_id.is_(None)
        & _t_pagos.c.receptor_id.is_(None)
    )
    pagos_gestor_pred = pagos_gestor_base & cuenta_via_gestor.isnot(None)
    pagos_por_gestor = (await db.execute(
        select(func.count()).select_from(_t_pagos).where(pagos_gestor_pred)
    )).scalar()
    if not dry_run and pagos_por_gestor:
        await db.execute(
            update(_t_pagos).where(pagos_gestor_pred).values(cuenta_bancaria_id=cuenta_via_gestor)
        )

    if not dry_run:
        await db.flush()

    # --- Pendientes: filas que siguen sin cuenta tras esta corrida (en
    # dry_run reflejan el estado sin cambios). Incluyen las filas que ningún
    # paso pudo resolver (gestor sin receptor, receptor soft-deleted sin
    # cuentas, cadena credito -> cliente -> gestor sin cuenta o soft-deleted).
    #   gestores_sin_cuenta: gestores con cuenta_bancaria_id NULL.
    #   pagos_sin_cuenta_rellenables: pagos en alcance de los pasos 4a/4b
    #     (receptor_id no nulo, o no pagados y no borrados) aún sin cuenta;
    #     requieren corrección de datos.
    #   pagos_sin_cuenta_no_rellenables: pagos pagados o soft-deleted sin
    #     receptor_id; ningún paso los llena por diseño.
    pendientes_gestores = (await db.execute(
        select(func.count()).select_from(_t_gestores).where(_t_gestores.c.cuenta_bancaria_id.is_(None))
    )).scalar()
    pagos_no_rellenables_pred = (
        _t_pagos.c.cuenta_bancaria_id.is_(None)
        & _t_pagos.c.receptor_id.is_(None)
        & ((_t_pagos.c.pagado == True) | _t_pagos.c.deleted_at.isnot(None))  # noqa: E712
    )
    pendientes_pagos_rellenables = (await db.execute(
        select(func.count()).select_from(_t_pagos).where(
            _t_pagos.c.cuenta_bancaria_id.is_(None), ~pagos_no_rellenables_pred,
        )
    )).scalar()
    pendientes_pagos_no_rellenables = (await db.execute(
        select(func.count()).select_from(_t_pagos).where(pagos_no_rellenables_pred)
    )).scalar()

    return {
        "dry_run": dry_run,
        "predeterminadas_elegidas": predeterminadas_elegidas,
        "cuentas_genericas_creadas": cuentas_genericas_creadas,
        "gestores_actualizados": gestores_actualizados,
        "pagos_por_receptor": pagos_por_receptor,
        "pagos_por_gestor": pagos_por_gestor,
        "pendientes": {
            "gestores_sin_cuenta": pendientes_gestores,
            "pagos_sin_cuenta_rellenables": pendientes_pagos_rellenables,
            "pagos_sin_cuenta_no_rellenables": pendientes_pagos_no_rellenables,
        },
    }


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
