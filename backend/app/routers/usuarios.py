"""
routers/usuarios.py — CRUD de usuarios del sistema.
Solo accesible para Admin en operaciones de gestión.
Cualquier usuario puede cambiar su propia contraseña.
"""
import logging
import math
import uuid
from datetime import datetime, timezone
from app.utils.fechas import ahora_bogota

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from passlib.context import CryptContext
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_role
from app.models.audit_log import AccionAudit
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.common import PaginatedResponse
from app.schemas.usuario import (
    CambiarPasswordRequest,
    RestablecerPasswordRequest,
    UsuarioCreate,
    UsuarioResponse,
    UsuarioUpdate,
)
from app.services import audit_service

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])
settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds)


@router.get("", response_model=PaginatedResponse[UsuarioResponse])
async def listar_usuarios(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    busqueda: str = Query("", description="Buscar por username"),
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Usuario).where(Usuario.deleted_at == None)  # noqa: E711
    if busqueda:
        query = query.where(Usuario.username.ilike(f"%{busqueda}%"))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    items_result = await db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )
    items = items_result.scalars().all()

    return PaginatedResponse(
        items=[UsuarioResponse.model_validate(u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
async def crear_usuario(
    body: UsuarioCreate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    # Verificar username único
    existing = await db.execute(
        select(Usuario).where(Usuario.username == body.username, Usuario.deleted_at == None)  # noqa: E711
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El username ya existe")

    usuario = Usuario(
        username=body.username,
        password_hash=pwd_context.hash(body.password),
        telefono=body.telefono,
        tipo_usuario=body.tipo_usuario,
        must_change_password=True,  # Contraseña temporal
    )
    db.add(usuario)
    await db.flush()  # Para obtener el ID antes del commit

    await audit_service.registrar_creacion(
        db=db,
        entidad="users",
        entidad_id=usuario.id,
        usuario_id=current_user.id,
        ip_origen=get_client_ip(request),
    )
    return UsuarioResponse.model_validate(usuario)


@router.get("/{usuario_id}", response_model=UsuarioResponse)
async def obtener_usuario(
    usuario_id: uuid.UUID,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Usuario).where(Usuario.id == usuario_id, Usuario.deleted_at == None)  # noqa: E711
    )
    usuario = result.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return UsuarioResponse.model_validate(usuario)


@router.patch("/{usuario_id}", response_model=UsuarioResponse)
async def actualizar_usuario(
    usuario_id: uuid.UUID,
    body: UsuarioUpdate,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Usuario).where(Usuario.id == usuario_id, Usuario.deleted_at == None)  # noqa: E711
    )
    usuario = result.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    cambios = {}
    if body.telefono is not None:
        cambios["telefono"] = (usuario.telefono, body.telefono)
        usuario.telefono = body.telefono
    if body.tipo_usuario is not None:
        cambios["tipo_usuario"] = (usuario.tipo_usuario.value, body.tipo_usuario.value)
        usuario.tipo_usuario = body.tipo_usuario
    if body.activo is not None:
        cambios["activo"] = (str(usuario.activo), str(body.activo))
        usuario.activo = body.activo

    await audit_service.registrar_actualizacion_campos(
        db=db,
        entidad="users",
        entidad_id=usuario.id,
        usuario_id=current_user.id,
        ip_origen=get_client_ip(request),
        cambios=cambios,
    )
    return UsuarioResponse.model_validate(usuario)


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_usuario(
    usuario_id: uuid.UUID,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if usuario_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No puedes eliminar tu propia cuenta",
        )

    result = await db.execute(
        select(Usuario).where(Usuario.id == usuario_id, Usuario.deleted_at == None)  # noqa: E711
    )
    usuario = result.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    usuario.deleted_at = ahora_bogota()
    usuario.activo = False

    await audit_service.registrar_eliminacion(
        db=db,
        entidad="users",
        entidad_id=usuario.id,
        usuario_id=current_user.id,
        ip_origen=get_client_ip(request),
    )


@router.post("/{usuario_id}/restablecer-password", status_code=status.HTTP_204_NO_CONTENT)
async def restablecer_password(
    usuario_id: uuid.UUID,
    body: RestablecerPasswordRequest,
    request: Request,
    current_user: Usuario = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin asigna contraseña temporal. El usuario debe cambiarla en el primer login."""
    result = await db.execute(
        select(Usuario).where(Usuario.id == usuario_id, Usuario.deleted_at == None)  # noqa: E711
    )
    usuario = result.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    usuario.password_hash = pwd_context.hash(body.password_nuevo)
    usuario.must_change_password = True

    await audit_service.registrar_cambio(
        db=db,
        entidad="users",
        entidad_id=usuario.id,
        accion=AccionAudit.UPDATE,
        usuario_id=current_user.id,
        ip_origen=get_client_ip(request),
        campo="password_hash",
        valor_anterior="[HASH ANTERIOR]",
        valor_nuevo="[CAMBIO DE CONTRASEÑA]",
    )


@router.post("/me/cambiar-password", status_code=status.HTTP_204_NO_CONTENT)
async def cambiar_mi_password(
    body: CambiarPasswordRequest,
    request: Request,
    current_user: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cualquier usuario puede cambiar su propia contraseña."""
    try:
        password_ok = pwd_context.verify(body.password_actual, current_user.password_hash)
    except Exception as e:
        logger.exception(
            "CAMBIAR PASSWORD FAIL — error verificando hash de %s: %s",
            current_user.username, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error verificando la contraseña actual",
        )

    if not password_ok:
        logger.warning(
            "CAMBIAR PASSWORD FAIL — contraseña actual incorrecta para %s (must_change=%s)",
            current_user.username, current_user.must_change_password,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual es incorrecta",
        )

    current_user.password_hash = pwd_context.hash(body.password_nuevo)
    current_user.must_change_password = False
    logger.info("CAMBIAR PASSWORD OK — %s", current_user.username)

    await audit_service.registrar_cambio(
        db=db,
        entidad="users",
        entidad_id=current_user.id,
        accion=AccionAudit.UPDATE,
        usuario_id=current_user.id,
        ip_origen=get_client_ip(request),
        campo="password_hash",
        valor_anterior="[HASH ANTERIOR]",
        valor_nuevo="[CAMBIO DE CONTRASEÑA]",
    )
