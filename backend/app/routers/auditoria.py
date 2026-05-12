"""routers/auditoria.py — Consulta del historial de auditoría (solo Admin, solo lectura)."""
import math
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.usuario import Usuario
from app.schemas.common import AuditLogResponse, PaginatedResponse

router = APIRouter(prefix="/auditoria", tags=["Auditoría"])


@router.get("", response_model=PaginatedResponse[AuditLogResponse])
async def listar_auditoria(
    entidad: Optional[str] = Query(None, description="Filtrar por tabla (clientes, creditos, etc.)"),
    entidad_id: Optional[uuid.UUID] = Query(None, description="Filtrar por ID de registro"),
    usuario_id: Optional[uuid.UUID] = Query(None, description="Filtrar por usuario que hizo el cambio"),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Historial de auditoría. Solo Admin puede consultarlo.
    De solo lectura — no hay endpoints de UPDATE ni DELETE sobre audit_log.
    """
    query = select(AuditLog)

    if entidad:
        query = query.where(AuditLog.entidad == entidad)
    if entidad_id:
        query = query.where(AuditLog.entidad_id == entidad_id)
    if usuario_id:
        query = query.where(AuditLog.usuario_id == usuario_id)
    if fecha_desde:
        query = query.where(AuditLog.fecha_accion >= fecha_desde)
    if fecha_hasta:
        query = query.where(AuditLog.fecha_accion <= fecha_hasta)

    query = query.order_by(AuditLog.fecha_accion.desc(), AuditLog.id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()

    # Traer en paralelo el username del usuario que hizo cada cambio
    rows = (await db.execute(
        query.add_columns(Usuario.username.label("usuario_username"))
        .join(Usuario, AuditLog.usuario_id == Usuario.id, isouter=True)
        .offset((page - 1) * page_size).limit(page_size)
    )).all()

    items = []
    for row in rows:
        log = row[0]
        data = AuditLogResponse.model_validate(log).model_dump()
        data["usuario_username"] = row.usuario_username
        items.append(AuditLogResponse.model_validate(data))

    return PaginatedResponse(
        items=items,
        total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )
