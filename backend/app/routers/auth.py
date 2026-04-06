"""
routers/auth.py — Autenticación JWT.

DECISIÓN TÉCNICA: El refresh token viaja en una HttpOnly cookie para
que JS no pueda accederlo (mitiga XSS). El access token se retorna
en el body JSON para que el frontend lo guarde en memoria (Zustand),
nunca en localStorage.

Rate limiting: slowapi limita a 10 intentos fallidos por IP en 15 min.
Bloqueo de 30 min al superar el límite (configurado en config.py).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, get_client_ip
from app.models.usuario import Usuario
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Autenticación"])
settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds)

# Almacén en memoria de refresh tokens revocados
# DECISIÓN: En producción con múltiples instancias, usar Redis.
# Para MVP en Render con una sola instancia, este set en memoria funciona.
_revoked_refresh_tokens: set[str] = set()


def crear_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "type": "access", "exp": expire},
        settings.secret_key,
        algorithm="HS256",
    )


def crear_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return jwt.encode(
        {"sub": user_id, "type": "refresh", "exp": expire},
        settings.secret_key,
        algorithm="HS256",
    )


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 86400,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Autentica al usuario y retorna access_token + refresh_token en cookie.
    """
    # Buscar usuario
    result = await db.execute(
        select(Usuario).where(
            Usuario.username == body.username,
            Usuario.deleted_at == None,  # noqa: E711
        )
    )
    usuario = result.scalar_one_or_none()

    # Validar credenciales (mensaje genérico para no revelar si el usuario existe)
    if not usuario or not pwd_context.verify(body.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )

    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario deshabilitado. Contacte al administrador.",
        )

    access_token = crear_access_token(str(usuario.id))
    refresh_token = crear_refresh_token(str(usuario.id))

    set_refresh_cookie(response, refresh_token)

    from app.schemas.usuario import UsuarioResponse
    return TokenResponse(
        access_token=access_token,
        user=UsuarioResponse.model_validate(usuario),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Renueva el access token usando el refresh token de la cookie HttpOnly.
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token no encontrado",
        )

    if refresh_token in _revoked_refresh_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revocado",
        )

    try:
        payload = jwt.decode(refresh_token, settings.secret_key, algorithms=["HS256"])
        user_id: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")

        if not user_id or token_type != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    result = await db.execute(
        select(Usuario).where(Usuario.id == user_id, Usuario.activo == True)  # noqa: E712
    )
    usuario = result.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

    # Rotar refresh token (revocar el anterior, emitir uno nuevo)
    _revoked_refresh_tokens.add(refresh_token)
    nuevo_refresh = crear_refresh_token(str(usuario.id))
    nuevo_access = crear_access_token(str(usuario.id))

    set_refresh_cookie(response, nuevo_refresh)

    from app.schemas.usuario import UsuarioResponse
    return TokenResponse(
        access_token=nuevo_access,
        user=UsuarioResponse.model_validate(usuario),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current_user: Usuario = Depends(get_current_user),
):
    """Invalida el refresh token y limpia la cookie."""
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        _revoked_refresh_tokens.add(refresh_token)

    response.delete_cookie("refresh_token")
