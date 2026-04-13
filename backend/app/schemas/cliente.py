import uuid
from typing import Optional
from pydantic import BaseModel, field_validator


class ClienteBase(BaseModel):
    nombre: str
    apellidos: str
    cedula: str
    telefono: str
    direccion: str
    correo_electronico: Optional[str] = None
    afiliacion_militar: bool = False

    @field_validator("cedula")
    @classmethod
    def validar_cedula(cls, v: str) -> str:
        if not v.isdigit() or not (6 <= len(v) <= 10):
            raise ValueError("La cédula debe tener entre 6 y 10 dígitos")
        return v

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, v: str) -> str:
        if not v.isdigit() or not (7 <= len(v) <= 10):
            raise ValueError("El teléfono debe tener entre 7 y 10 dígitos")
        return v


class ClienteCreate(ClienteBase):
    gestor_id: uuid.UUID


class ClienteUpdate(BaseModel):
    nombre: Optional[str] = None
    apellidos: Optional[str] = None
    cedula: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    correo_electronico: Optional[str] = None
    afiliacion_militar: Optional[bool] = None
    al_dia: Optional[bool] = None
    gestor_id: Optional[uuid.UUID] = None  # Solo Admin


class ClienteResponse(ClienteBase):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    gestor_id: uuid.UUID
    al_dia: bool
