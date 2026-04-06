"""
dependencies.py — Dependencias reutilizables de FastAPI.

DECISIÓN TÉCNICA: require_role() devuelve una dependencia que valida
el rol en cada request. Esto garantiza que la autorización ocurra en
el backend independientemente del frontend. El principio es:
"El frontend oculta, el backend valida."

get_current_user() extrae el usuario del JWT y lo hace disponible
en todos los endpoints con una sola línea.
"""
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.usuario import TipoUsuario, Usuario

settings = get_settings()
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """
    Extrae y valida el access token JWT del header Authorization.
    Retorna el Usuario autenticado o lanza 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=["HS256"],
        )
        user_id: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")

        if user_id is None or token_type != "access":
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    result = await db.execute(
        select(Usuario).where(
            Usuario.id == uuid.UUID(user_id),
            Usuario.activo == True,  # noqa: E712
            Usuario.deleted_at == None,  # noqa: E711
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


def require_role(*roles: str):
    """
    Factory que retorna una dependencia FastAPI que valida el rol del usuario.

    Uso en router:
        @router.post("/clientes", dependencies=[Depends(require_role("admin", "registrador"))])

    O como parámetro para acceder al usuario:
        async def endpoint(current_user: Usuario = Depends(require_role("admin"))):
    """
    async def role_checker(
        current_user: Usuario = Depends(get_current_user),
    ) -> Usuario:
        if current_user.tipo_usuario.value not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para realizar esta acción",
            )
        return current_user

    return role_checker


def get_client_ip(request: Request) -> str:
    """
    Extrae la IP real del cliente, considerando proxies (Render usa proxy).
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
