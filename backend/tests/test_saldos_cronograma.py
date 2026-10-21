"""
tests/test_saldos_cronograma.py — Pure helpers that rebuild credit balances from
the schedule (recaudo-registra-montos-registrador-supervisa, PR2a, design D2-D4).

`reduccion_efectiva` mirrors what registering a payment subtracted from the
balances (destino authoritative on excedente); the helpers below it compose
that into R(paid) and the schedule-anchored delta used by amount reversal.
No DB: plain model instances, `Decimal` only.
"""
import uuid
from decimal import Decimal

import pytest

from app.models.pago import DestinoExcedente, Pago, TipoCuota
from app.services import credito_service


def _pago(
    capital_a_pagar, interes_a_pagar, capital_pagado, interes_pagado,
    tipo=TipoCuota.programada, destino=None,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), numero_cuota=1, tipo_cuota=tipo,
        monto_a_pagar=Decimal(capital_a_pagar) + Decimal(interes_a_pagar),
        capital_a_pagar=Decimal(capital_a_pagar), interes_a_pagar=Decimal(interes_a_pagar),
        capital_pagado=Decimal(capital_pagado), interes_pagado=Decimal(interes_pagado),
        pagado=True, es_excedente_a=destino, deleted_at=None,
    )


class TestReduccionEfectiva:
    """What `registrar_pago` / `confirmar_excedente` / `registrar_pago_no_programado`
    actually subtracted from (saldo_capital, saldo_intereses)."""

    @pytest.mark.parametrize(
        "pago, esperado",
        [
            pytest.param(
                _pago("70000", "30000", "70000", "30000"),
                (Decimal("70000"), Decimal("30000")), id="exacto",
            ),
            pytest.param(
                # Partial: free split, the reduction is exactly what was paid.
                _pago("70000", "30000", "30000", "20000"),
                (Decimal("30000"), Decimal("20000")), id="parcial",
            ),
            pytest.param(
                # Reported 100000/50000 (exc 50000) but destino capital is authoritative:
                # capital_a_pagar + exc = 120000, interes_a_pagar untouched = 30000.
                _pago("70000", "30000", "100000", "50000", destino=DestinoExcedente.capital),
                (Decimal("120000"), Decimal("30000")), id="excedente-capital",
            ),
            pytest.param(
                # Reported 90000/30000 (exc 20000) but destino intereses is authoritative:
                # capital_a_pagar untouched = 70000, interes_a_pagar + exc = 50000.
                _pago("70000", "30000", "90000", "30000", destino=DestinoExcedente.intereses),
                (Decimal("70000"), Decimal("50000")), id="excedente-intereses",
            ),
            pytest.param(
                _pago("50000", "0", "50000", "0", tipo=TipoCuota.no_programada),
                (Decimal("50000"), Decimal("0")), id="no-programada-capital",
            ),
            pytest.param(
                _pago("0", "40000", "0", "40000", tipo=TipoCuota.no_programada),
                (Decimal("0"), Decimal("40000")), id="no-programada-intereses",
            ),
        ],
    )
    def test_reduccion_efectiva(self, pago, esperado):
        assert credito_service.reduccion_efectiva(pago) == esperado
