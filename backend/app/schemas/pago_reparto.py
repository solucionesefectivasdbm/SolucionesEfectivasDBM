"""
schemas/pago_reparto.py — Split de un Pago entre N destinatarios
(payment-multi-recipient, item 10, PR2).

DECISIÓN TÉCNICA: `RepartoItem` valida en la capa Pydantic (422 antes de
tocar la DB) exactamente la misma regla que el CHECK constraint
`ck_pago_repartos_destinatario` de la tabla — defensa en profundidad, no
duplicación accidental: si algún día cambia una regla, cambia en los dos
lugares a propósito.
"""
import uuid
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.pago_reparto import TipoDestinatario


class RepartoItem(BaseModel):
    """Item de entrada para `PUT /pagos/{id}/repartos`. Exactamente uno de
    `cuenta_bancaria_id`/`cliente_id` debe estar presente, coincidiendo con
    `tipo_destinatario`."""

    tipo_destinatario: TipoDestinatario
    cuenta_bancaria_id: Optional[uuid.UUID] = None
    cliente_id: Optional[uuid.UUID] = None
    monto: Decimal = Field(gt=0, decimal_places=2)

    @model_validator(mode="after")
    def _validar_destinatario(self) -> "RepartoItem":
        if self.tipo_destinatario == TipoDestinatario.cuenta_bancaria:
            if self.cuenta_bancaria_id is None or self.cliente_id is not None:
                raise ValueError(
                    "tipo_destinatario=cuenta_bancaria requiere cuenta_bancaria_id "
                    "y cliente_id debe quedar vacío"
                )
        else:
            if self.cliente_id is None or self.cuenta_bancaria_id is not None:
                raise ValueError(
                    "tipo_destinatario=cliente requiere cliente_id "
                    "y cuenta_bancaria_id debe quedar vacío"
                )
        return self


class RepartoResponse(RepartoItem):
    """Respuesta de GET/PUT `/pagos/{id}/repartos` y del campo `repartos`
    embebido en `PagoResponse`. `etiqueta` es `etiqueta_cuenta(...)` para
    destinatarios tipo cuenta, o el nombre completo del cliente para tipo
    cliente — la arma `pago_reparto_service.repartos_por_pago` (batched)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    etiqueta: str


class ReemplazarRepartosRequest(BaseModel):
    """Body de `PUT /pagos/{id}/repartos`."""

    repartos: list[RepartoItem]
