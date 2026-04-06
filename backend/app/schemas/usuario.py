"""
Schemas Pydantic para Usuario.

DECISIÓN TÉCNICA: Separamos los schemas en Base/Create/Update/Response
para controlar exactamente qué campos entran y salen en cada operación.
password_hash NUNCA aparece en ningún schema de respuesta.
"""
import uuid
from typing import Optional
from pydantic import BaseModel, field_validator
import re

from app.models.usuario import TipoUsuario


class UsuarioBase(BaseModel):
    username: str
    telefono: str
    tipo_usuario: TipoUsuario


class UsuarioCreate(UsuarioBase):
    password: str

    @field_validator("password")
    @classmethod
    def validar_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        if not re.search(r"[A-Z]", v):
            raise ValueError("La contraseña debe tener al menos una mayúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("La contraseña debe tener al menos una minúscula")
        if not re.search(r"\d", v):
            raise ValueError("La contraseña debe tener al menos un número")
        return v

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, v: str) -> str:
        if not v.isdigit() or not (7 <= len(v) <= 10):
            raise ValueError("El teléfono debe tener entre 7 y 10 dígitos")
        return v


class UsuarioUpdate(BaseModel):
    telefono: Optional[str] = None
    tipo_usuario: Optional[TipoUsuario] = None
    activo: Optional[bool] = None


class UsuarioResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    username: str
    telefono: str
    tipo_usuario: TipoUsuario
    activo: bool
    must_change_password: bool


class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nuevo: str

    @field_validator("password_nuevo")
    @classmethod
    def validar_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        if not re.search(r"[A-Z]", v):
            raise ValueError("La contraseña debe tener al menos una mayúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("La contraseña debe tener al menos una minúscula")
        if not re.search(r"\d", v):
            raise ValueError("La contraseña debe tener al menos un número")
        return v


class RestablecerPasswordRequest(BaseModel):
    """Solo Admin: asigna contraseña temporal a otro usuario."""
    password_nuevo: str

    @field_validator("password_nuevo")
    @classmethod
    def validar_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        if not re.search(r"[A-Z]", v):
            raise ValueError("La contraseña debe tener al menos una mayúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("La contraseña debe tener al menos una minúscula")
        if not re.search(r"\d", v):
            raise ValueError("La contraseña debe tener al menos un número")
        return v
