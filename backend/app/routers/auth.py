"""
routers/auth.py — Autenticación JWT.

DECISIÓN TÉCNICA: El refresh token viaja en una HttpOnly cookie para
que JS no pueda accederlo (mitiga XSS). El access token se retorna
en el body JSON para que el frontend lo guarde en memoria (Zustand),
nunca en localStorage.

Rate limiting de login: se rastrean los intentos FALLIDOS por IP en un
almacén en memoria. Al acumular `login_max_attempts` fallos dentro de una
ventana de `login_block_minutes` (config.py), la IP recibe 429 hasta que
los fallos envejezcan fuera de la ventana. Un login exitoso limpia el
contador de esa IP.

DECISIÓN: el almacén es en memoria, consistente con _revoked_refresh_tokens.
Funciona para un despliegue de una sola instancia (MVP). Con múltiples
instancias, migrar este estado a Redis.
"""
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, get_client_ip
from app.models.token_revocado import TokenRevocado
from app.models.usuario import Usuario
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Autenticación"])
settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds)

# Blocklist de refresh tokens revocados — persistida en DB (tabla
# tokens_revocados). Sobrevive reinicios y funciona con múltiples instancias.
# Ver app/models/token_revocado.py para la decisión técnica completa.


def _hash_token(token: str) -> str:
    """SHA-256 hex de un token. No guardamos el token crudo en la blocklist."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _revocar_refresh_token(db: AsyncSession, token: str) -> None:
    """
    Agrega el refresh token a la blocklist (idempotente) y purga de paso los
    registros cuyo token ya expiró. El commit lo hace get_db al cerrar el request.
    """
    token_hash = _hash_token(token)

    ya_revocado = (await db.execute(
        select(TokenRevocado.id).where(TokenRevocado.token_hash == token_hash)
    )).scalar_one_or_none()

    if ya_revocado is None:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        except JWTError:
            payload = None
        # Solo registramos tokens válidos y con exp: un token inválido o expirado
        # ya lo rechaza el propio /refresh, no hace falta bloquearlo.
        if payload is not None and "exp" in payload:
            expires_at = datetime.fromtimestamp(payload["exp"], timezone.utc).replace(tzinfo=None)
            db.add(TokenRevocado(token_hash=token_hash, expires_at=expires_at))

    # Housekeeping: borrar registros cuyo token ya expiró (el JWT ya es inválido solo).
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.execute(delete(TokenRevocado).where(TokenRevocado.expires_at <= ahora_utc))


async def _refresh_token_revocado(db: AsyncSession, token: str) -> bool:
    """True si el refresh token está en la blocklist persistida."""
    existe = (await db.execute(
        select(TokenRevocado.id).where(TokenRevocado.token_hash == _hash_token(token))
    )).scalar_one_or_none()
    return existe is not None

# Rate limiting de login: timestamps (UTC) de intentos fallidos por IP.
_failed_login_attempts: dict[str, list[datetime]] = defaultdict(list)


def _login_bloqueado(ip: str) -> bool:
    """
    True si `ip` acumuló al menos `login_max_attempts` fallos dentro de la
    ventana de `login_block_minutes`. Poda los fallos vencidos al consultar.
    """
    ahora = datetime.now(timezone.utc)
    ventana = timedelta(minutes=settings.login_block_minutes)
    recientes = [t for t in _failed_login_attempts.get(ip, []) if ahora - t < ventana]
    if recientes:
        _failed_login_attempts[ip] = recientes
    else:
        _failed_login_attempts.pop(ip, None)
    return len(recientes) >= settings.login_max_attempts


def _registrar_fallo_login(ip: str) -> None:
    """Registra un intento de login fallido para `ip`."""
    _failed_login_attempts[ip].append(datetime.now(timezone.utc))


def _limpiar_fallos_login(ip: str) -> None:
    """Limpia el contador de fallos de `ip` (tras un login exitoso)."""
    _failed_login_attempts.pop(ip, None)


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
        samesite="none" if settings.is_production else "lax",
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
    ip = get_client_ip(request)

    # Rate limiting: rechazar si la IP superó el máximo de intentos fallidos.
    if _login_bloqueado(ip):
        logger.warning("LOGIN BLOCKED — demasiados intentos fallidos (ip=%s)", ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Demasiados intentos fallidos. Intente nuevamente en "
                f"{settings.login_block_minutes} minutos."
            ),
        )

    # Buscar usuario
    result = await db.execute(
        select(Usuario).where(
            Usuario.username == body.username,
            Usuario.deleted_at == None,  # noqa: E711
        )
    )
    usuario = result.scalar_one_or_none()

    # Logs detallados para diagnosticar problemas de login en producción.
    # No exponen información sensible al cliente — solo a Railway logs.
    if not usuario:
        _registrar_fallo_login(ip)
        logger.warning("LOGIN FAIL — usuario no encontrado: %r (ip=%s)", body.username, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )

    try:
        password_ok = pwd_context.verify(body.password, usuario.password_hash)
    except Exception as e:
        logger.exception("LOGIN FAIL — error verificando password para %s: %s", body.username, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error verificando credenciales",
        )

    if not password_ok:
        _registrar_fallo_login(ip)
        logger.warning(
            "LOGIN FAIL — password no coincide para %s (must_change=%s, activo=%s)",
            body.username, usuario.must_change_password, usuario.activo,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )

    if not usuario.activo:
        logger.warning("LOGIN FAIL — usuario inactivo: %s", body.username)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario deshabilitado. Contacte al administrador.",
        )

    # Login exitoso: limpiar el contador de fallos de esta IP.
    _limpiar_fallos_login(ip)
    logger.info("LOGIN OK — %s (must_change=%s)", body.username, usuario.must_change_password)

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

    if await _refresh_token_revocado(db, refresh_token):
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

    # DECISIÓN TÉCNICA: NO rotamos el refresh token en cada refresh.
    #
    # Rotar (revocar el anterior + emitir uno nuevo) causaba una condición de
    # carrera: dos requests que refrescaban casi simultáneamente — el polling
    # del Header + una acción del usuario, o dos pestañas abiertas — enviaban
    # el MISMO refresh token. El primero lo revocaba; el segundo llegaba con un
    # token recién revocado → 401 → el frontend cerraba sesión a un usuario que
    # estaba usando el sistema activamente.
    #
    # En su lugar: el refresh token se mantiene estable durante sus 7 días y
    # solo se emite un nuevo access token. La cookie se re-emite con el MISMO
    # valor para extender su expiración (sliding window) sin invalidar nada.
    # El refresh token solo se invalida en logout (se agrega a
    # _revoked_refresh_tokens y se borra la cookie).
    nuevo_access = crear_access_token(str(usuario.id))

    set_refresh_cookie(response, refresh_token)

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
    db: AsyncSession = Depends(get_db),
):
    """Invalida el refresh token y limpia la cookie."""
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await _revocar_refresh_token(db, refresh_token)

    response.delete_cookie(
        "refresh_token",
        samesite="none" if settings.is_production else "lax",
        secure=settings.is_production,
    )
