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

from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import DestinoExcedente, Pago, TipoCuota
from app.services import credito_service


def _credito(
    tipo=TipoCredito.cuota_fija, capital="1000000", cuotas=10,
    saldo_capital="0", saldo_intereses="0", activo=True,
) -> Credito:
    """Monthly credit at 3%: cuota_fija interest base = capital * 0.03 * cuotas."""
    return Credito(
        id=uuid.uuid4(), tipo_credito=tipo, capital_prestado=Decimal(capital),
        tasa_interes_mensual=Decimal("0.0300"), periodicidad=Periodicidad.mensual,
        numero_cuotas=cuotas if tipo == TipoCredito.cuota_fija else None,
        saldo_capital=Decimal(saldo_capital), saldo_intereses=Decimal(saldo_intereses),
        activo=activo,
    )


def _exacto() -> Pago:
    return _pago("100000", "30000", "100000", "30000")


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


class TestSaldosPorCronograma:
    """R(paid): balances rebuilt as base - sum(reduccion_efectiva), floored at 0."""

    def test_cuota_fija_sin_pagos_es_la_base(self):
        # 1000000 capital; interest 1000000 * 0.03 * 10 cuotas
        assert credito_service.saldos_por_cronograma(_credito(), []) == (
            Decimal("1000000.00"), Decimal("300000.00"),
        )

    def test_cuota_fija_descuenta_la_reduccion_efectiva_de_cada_pago(self):
        pagados = [
            _exacto(),
            _exacto(),
            # Reported 100000/50000 (exc 20000) with destino intereses reduces 100000/50000.
            _pago("100000", "30000", "100000", "50000", destino=DestinoExcedente.intereses),
        ]
        assert credito_service.saldos_por_cronograma(_credito(), pagados) == (
            Decimal("700000.00"), Decimal("190000.00"),
        )

    def test_abono_capital_nunca_lleva_saldo_de_intereses(self):
        credito = _credito(tipo=TipoCredito.abono_capital, capital="2000000")
        pagado = _pago("200000", "60000", "200000", "60000")
        assert credito_service.saldos_por_cronograma(credito, [pagado]) == (
            Decimal("1800000.00"), Decimal("0.00"),
        )

    def test_piso_en_cero_cuando_lo_pagado_supera_la_base(self):
        credito = _credito(capital="100000", cuotas=1)  # interest base 3000
        pagados = [_pago("100000", "3000", "80000", "0"), _pago("100000", "3000", "60000", "4000")]
        assert credito_service.saldos_por_cronograma(credito, pagados) == (
            Decimal("0.00"), Decimal("0.00"),
        )


class TestReabrirCredito:
    """Design D7: the only writer of activo False -> True; never touches balances."""

    def test_credito_cerrado_se_reabre_sin_tocar_saldos(self):
        credito = _credito(saldo_capital="500", saldo_intereses="20", activo=False)

        assert credito_service.reabrir_credito(credito) is True
        assert credito.activo is True
        assert (credito.saldo_capital, credito.saldo_intereses) == (Decimal("500"), Decimal("20"))

    def test_credito_abierto_no_cambia(self):
        credito = _credito(saldo_capital="500", saldo_intereses="20", activo=True)

        assert credito_service.reabrir_credito(credito) is False
        assert credito.activo is True


class TestSaldosTrasReversion:
    """Design D2/D3: new = stored + (R(paid - {P}) - R(paid)); closed credit replays interest."""

    def test_sin_drift_devuelve_los_saldos_previos_al_pago(self):
        p1, p2 = _exacto(), _exacto()
        credito = _credito(saldo_capital="800000", saldo_intereses="240000")
        assert credito_service.saldos_tras_reversion(credito, [p1, p2], p2) == (
            Decimal("900000.00"), Decimal("270000.00"),
        )

    def test_preserva_el_drift_almacenado(self):
        # Stored balances carry +7777 capital / +500 interest of legacy drift: kept, not overwritten.
        p1, p2 = _exacto(), _exacto()
        credito = _credito(saldo_capital="807777", saldo_intereses="240500")
        assert credito_service.saldos_tras_reversion(credito, [p1, p2], p2) == (
            Decimal("907777.00"), Decimal("270500.00"),
        )

    def test_el_piso_absorbido_al_registrar_no_se_devuelve(self):
        # P2 paid 40000 capital but only 20000 was left: reverting gives back 20000, not 40000.
        credito = _credito(capital="100000", cuotas=1, saldo_capital="0", saldo_intereses="3000")
        p1 = _pago("100000", "3000", "80000", "0")
        p2 = _pago("100000", "3000", "40000", "0")
        assert credito_service.saldos_tras_reversion(credito, [p1, p2], p2) == (
            Decimal("20000.00"), Decimal("3000.00"),
        )

    def test_credito_cerrado_recompone_el_interes_por_replay_completo(self):
        # Regla 14: closure zeroed saldo_intereses, so anchoring would give 0 + (6000 - 6000).
        credito = _credito(capital="200000", cuotas=2, saldo_capital="0", saldo_intereses="0", activo=False)
        p1 = _pago("100000", "6000", "100000", "6000")
        p2 = _pago("100000", "6000", "100000", "0")  # partial: capital only
        assert credito_service.saldos_tras_reversion(credito, [p1, p2], p2) == (
            Decimal("100000.00"), Decimal("6000.00"),
        )
