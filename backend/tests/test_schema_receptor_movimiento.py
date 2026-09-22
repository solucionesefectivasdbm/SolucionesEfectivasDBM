"""
tests/test_schema_receptor_movimiento.py — Pydantic schema tests for the
receiver-cash-balance ledger (item 9).

RED phase: `MovimientoCreate.monto` must be strictly positive (`gt=0`) —
the overdraft rejection itself happens in the service layer, not here.
`CorreccionCreate.monto` allows any sign but rejects exactly zero via a
custom validator (a zero correction has no effect and would pollute the
ledger history).
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.receptor_movimiento import CorreccionCreate, MovimientoCreate


class TestMovimientoCreate:
    """salida payload: monto must be > 0."""

    def test_monto_positivo_aceptado(self):
        m = MovimientoCreate(monto=Decimal("100.00"))
        assert m.monto == Decimal("100.00")
        assert m.nota is None

    def test_monto_cero_rechazado(self):
        with pytest.raises(ValidationError):
            MovimientoCreate(monto=Decimal("0.00"))

    def test_monto_negativo_rechazado(self):
        with pytest.raises(ValidationError):
            MovimientoCreate(monto=Decimal("-10.00"))

    def test_nota_opcional_se_acepta(self):
        m = MovimientoCreate(monto=Decimal("50.00"), nota="retiro parcial")
        assert m.nota == "retiro parcial"


class TestCorreccionCreate:
    """correccion payload: monto can be positive or negative, but never zero."""

    def test_monto_positivo_aceptado(self):
        c = CorreccionCreate(monto=Decimal("20.00"))
        assert c.monto == Decimal("20.00")

    def test_monto_negativo_aceptado(self):
        c = CorreccionCreate(monto=Decimal("-15.00"), nota="ajuste conteo físico")
        assert c.monto == Decimal("-15.00")
        assert c.nota == "ajuste conteo físico"

    def test_monto_cero_rechazado(self):
        with pytest.raises(ValidationError):
            CorreccionCreate(monto=Decimal("0.00"))
