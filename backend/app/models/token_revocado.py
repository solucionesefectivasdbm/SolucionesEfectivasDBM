"""
Modelo TokenRevocado — blocklist de refresh tokens invalidados en logout.

DECISIÓN TÉCNICA: la revocación vive en la base de datos, no en memoria, para
que sobreviva reinicios del servidor y funcione con múltiples instancias. Antes
era un set en memoria: cada restart "resucitaba" los tokens revocados hasta su
expiración y la revocación no se compartía entre instancias.

Se guarda el SHA-256 del token, nunca el token crudo — mismo criterio que con
password_hash: si la tabla se filtra, no debe contener secretos reutilizables.

Los registros se purgan cuando el token expira (expires_at <= ahora): a partir
de ahí el JWT ya es inválido por su propia claim `exp`, así que no hace falta
seguir bloqueándolo.
"""
import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.tz import ahora_bogota


class TokenRevocado(Base):
    __tablename__ = "tokens_revocados"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False,
        comment="SHA-256 hex del refresh token revocado",
    )
    expires_at: Mapped[datetime] = mapped_column(
        nullable=False,
        comment="Expiración (UTC) original del token; pasada esta fecha el registro se purga",
    )
    created_at: Mapped[datetime] = mapped_column(
        default=ahora_bogota, nullable=False,
    )
