import uuid
from typing import Optional
from pydantic import BaseModel, field_validator

from app.models.receptor import TipoCuenta


class CuentaBancariaBase(BaseModel):
    entidad_bancaria: str
    tipo_cuenta: TipoCuenta
    numero_cuenta: str


class CuentaBancariaCreate(CuentaBancariaBase):
    pass


class CuentaBancariaResponse(CuentaBancariaBase):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    receptor_id: uuid.UUID


class ReceptorBase(BaseModel):
    nombre: str
    cedula: str
    telefono: str

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


class ReceptorCreate(ReceptorBase):
    pass


class ReceptorUpdate(BaseModel):
    nombre: Optional[str] = None
    cedula: Optional[str] = None
    telefono: Optional[str] = None


class ReceptorResponse(ReceptorBase):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    cuentas_bancarias: list[CuentaBancariaResponse] = []
