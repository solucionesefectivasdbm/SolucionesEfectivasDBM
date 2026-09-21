import uuid
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.receptor import CuentaBancariaResumen


class GestorBase(BaseModel):
    cedula: str
    nombre: str
    apellidos: str
    telefono: str
    direccion: str
    correo_electronico: str

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


class GestorCreate(GestorBase):
    user_id: uuid.UUID
    cuenta_bancaria_id: Optional[uuid.UUID] = None


class GestorUpdate(BaseModel):
    cedula: Optional[str] = None
    nombre: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    correo_electronico: Optional[str] = None
    cuenta_bancaria_id: Optional[uuid.UUID] = None


class GestorResponse(GestorBase):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    cuenta_bancaria_id: Optional[uuid.UUID] = None
    cuenta_bancaria: Optional[CuentaBancariaResumen] = None
