"""
tests/test_pago_service_arrastre.py — Unmocked chained-partial payment tests.

Root cause of the shipped defect: every existing test in `test_pago_service.py`
mocks `generar_siguiente_cuota` with `return_value=None`, so the arrastre
disaggregation was never exercised end to end through `PagoService`. These
tests call `PagoService.registrar_pago` and `confirmar_excedente` with the
REAL `generar_siguiente_cuota` (no mock/patch), proving the fix works through
the actual payment-registration path. `TestExcedenteConArrastre` below is the
only class that exercises `confirmar_excedente`; the other classes only call
`registrar_pago`.

`generar_siguiente_cuota` performs no DB I/O itself (it only builds a `Pago`
in memory), so `db=AsyncMock(spec=AsyncSession)` is sufficient here —
"unmocked" refers to NOT patching `generar_siguiente_cuota`/
`_siguiente_cuota_fija`, not to using a real database.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota, DestinoExcedente
from app.schemas.pago import RegistrarPagoRequest
from app.services.pago_service import PagoService


def make_db() -> AsyncMock:
    """`spec=AsyncSession` makes `db.add()` a plain (sync) mock, matching the
    real (sync) `AsyncSession.add` signature — eliminates the cosmetic
    'coroutine was never awaited' RuntimeWarning from an unconstrained
    AsyncMock without weakening any assertion (`db.add.call_args_list` still
    works identically)."""
    return AsyncMock(spec=AsyncSession)


def make_credito_cuota_fija(
    capital_prestado=Decimal("1000.00"),
    tasa=Decimal("0.0200"),
    numero_cuotas=10,
    saldo_capital=Decimal("1000.00"),
) -> Credito:
    """Base cuota this produces: capital 100.00 + interest 20.00 = 120.00."""
    c = Credito()
    c.id = uuid.uuid4()
    c.tipo_credito = TipoCredito.cuota_fija
    c.capital_prestado = capital_prestado
    c.saldo_capital = saldo_capital
    c.saldo_intereses = Decimal("0.00")
    c.tasa_interes_mensual = tasa
    c.numero_cuotas = numero_cuotas
    c.periodicidad = Periodicidad.mensual
    c.activo = True
    return c


def make_cuota(
    numero_cuota=1,
    monto_a_pagar=Decimal("120.00"),
    capital=Decimal("100.00"),
    interes=Decimal("20.00"),
    fecha_maxima=date(2026, 1, 10),
) -> Pago:
    p = Pago()
    p.id = uuid.uuid4()
    p.credito_id = uuid.uuid4()
    p.numero_cuota = numero_cuota
    p.tipo_cuota = TipoCuota.programada
    p.monto_a_pagar = monto_a_pagar
    p.capital_a_pagar = capital
    p.interes_a_pagar = interes
    p.capital_pagado = Decimal("0")
    p.interes_pagado = Decimal("0")
    p.momento = "m3"
    p.fecha_maxima = fecha_maxima
    p.receptor_id = None
    p.pagado = False
    p.validado_recaudador = True
    p.fecha_pago_real = None
    p.es_excedente_a = None
    p.es_ultimo_pago = False
    return p


def _ultima_cuota_agregada(db: AsyncMock) -> Pago:
    """
    Retrieves the Pago passed to the last db.add(...) call.

    `id` stays None until an actual flush assigns the mapped_column default —
    which never happens here since `db` is an AsyncMock. Assign one so the
    Pago can round-trip through PagoResponse when chained into a further
    `registrar_pago` call, mirroring what a real flush would produce.
    """
    pago = db.add.call_args_list[-1][0][0]
    if pago.id is None:
        pago.id = uuid.uuid4()
    return pago


class TestCadenaArrastreTresPasos:
    """
    Verifies the design's 3-step chained-partial table end to end, through
    the real (unmocked) generation path:

    | Step | Cuota (cap/int/monto) | Paid (cap/int) | arrastre (cap/int) | Next cuota |
    |---|---|---|---|---|
    | 1 | 100/20/120  | 50/10  | 50/10 | 150/30/180 |
    | 2 | 150/30/180  | 90/10  | 60/20 | 160/40/200 |
    | 3 | 160/40/200  | 160/40 | 0/0   | 100/20/120 |
    """

    @pytest.mark.asyncio
    async def test_cadena_sin_doble_conteo(self):
        credito = make_credito_cuota_fija()
        db = make_db()

        cuota1 = make_cuota(numero_cuota=1)
        req1 = RegistrarPagoRequest(capital_pagado=Decimal("50.00"), interes_pagado=Decimal("10.00"))
        await PagoService.registrar_pago(db, cuota1, credito, req1, date(2026, 1, 10))

        cuota2 = _ultima_cuota_agregada(db)
        assert cuota2.capital_a_pagar == Decimal("150.00")
        assert cuota2.interes_a_pagar == Decimal("30.00")
        assert cuota2.monto_a_pagar == Decimal("180.00")
        assert cuota2.capital_a_pagar + cuota2.interes_a_pagar == cuota2.monto_a_pagar

        cuota2.validado_recaudador = True
        req2 = RegistrarPagoRequest(capital_pagado=Decimal("90.00"), interes_pagado=Decimal("10.00"))
        await PagoService.registrar_pago(db, cuota2, credito, req2, date(2026, 2, 10))

        cuota3 = _ultima_cuota_agregada(db)
        assert cuota3.capital_a_pagar == Decimal("160.00")
        assert cuota3.interes_a_pagar == Decimal("40.00")
        assert cuota3.monto_a_pagar == Decimal("200.00")
        assert cuota3.capital_a_pagar + cuota3.interes_a_pagar == cuota3.monto_a_pagar

        cuota3.validado_recaudador = True
        req3 = RegistrarPagoRequest(capital_pagado=Decimal("160.00"), interes_pagado=Decimal("40.00"))
        result3 = await PagoService.registrar_pago(db, cuota3, credito, req3, date(2026, 3, 10))

        # Exact payment of base + full arrastre: accepted, no HTTP-422-worthy ValueError.
        assert result3.requiere_decision is False
        assert cuota3.pagado is True

        cuota4 = _ultima_cuota_agregada(db)
        assert cuota4.capital_a_pagar == Decimal("100.00")
        assert cuota4.interes_a_pagar == Decimal("20.00")
        assert cuota4.monto_a_pagar == Decimal("120.00")

    @pytest.mark.asyncio
    async def test_saldo_capital_final_refleja_solo_lo_pagado(self):
        """Saldo tracking is independent from the arrastre bookkeeping: it only
        ever decreases by what was actually paid, each step."""
        credito = make_credito_cuota_fija(saldo_capital=Decimal("1000.00"))
        db = make_db()

        cuota1 = make_cuota(numero_cuota=1)
        req1 = RegistrarPagoRequest(capital_pagado=Decimal("50.00"), interes_pagado=Decimal("10.00"))
        await PagoService.registrar_pago(db, cuota1, credito, req1, date(2026, 1, 10))
        assert credito.saldo_capital == Decimal("950.00")

        cuota2 = _ultima_cuota_agregada(db)
        cuota2.validado_recaudador = True
        req2 = RegistrarPagoRequest(capital_pagado=Decimal("90.00"), interes_pagado=Decimal("10.00"))
        await PagoService.registrar_pago(db, cuota2, credito, req2, date(2026, 2, 10))
        assert credito.saldo_capital == Decimal("860.00")


class TestComponentOverpayClamp:
    """
    Component-overpay edge (free split within a partial payment): capital
    paid beyond target → clamp to 0, arrastre becomes 100% interest.
    Cuota 150/30/180 paid 160/0 → next cuota 100/40/140.
    """

    @pytest.mark.asyncio
    async def test_clamp_produce_arrastre_solo_interes(self):
        credito = make_credito_cuota_fija()
        db = make_db()

        cuota = make_cuota(
            numero_cuota=2, monto_a_pagar=Decimal("180.00"),
            capital=Decimal("150.00"), interes=Decimal("30.00"),
        )
        req = RegistrarPagoRequest(capital_pagado=Decimal("160.00"), interes_pagado=Decimal("0.00"))
        await PagoService.registrar_pago(db, cuota, credito, req, date(2026, 2, 10))

        siguiente = _ultima_cuota_agregada(db)
        assert siguiente.capital_a_pagar == Decimal("100.00")
        assert siguiente.interes_a_pagar == Decimal("40.00")
        assert siguiente.monto_a_pagar == Decimal("140.00")


class TestGuardrails:
    """Guardrails around `_validar_split` must stay intact — the ceiling
    MOVES to arrastre-inclusive targets, but is never removed."""

    @pytest.mark.asyncio
    async def test_pago_exacto_base_mas_arrastre_no_lanza_error(self):
        """Exact payment matching arrastre-inclusive components is accepted."""
        credito = make_credito_cuota_fija()
        db = make_db()

        cuota_arrastre = make_cuota(
            numero_cuota=2, monto_a_pagar=Decimal("180.00"),
            capital=Decimal("150.00"), interes=Decimal("30.00"),
        )
        req = RegistrarPagoRequest(capital_pagado=Decimal("150.00"), interes_pagado=Decimal("30.00"))

        result = await PagoService.registrar_pago(db, cuota_arrastre, credito, req, date(2026, 2, 10))

        assert result.requiere_decision is False
        assert cuota_arrastre.pagado is True

    @pytest.mark.asyncio
    async def test_sobrepago_de_componente_sin_arrastre_sigue_siendo_rechazado(self):
        """A cuota with ZERO arrastre still rejects a component overpay in
        `exacto` — the pre-existing guardrail is untouched."""
        credito = make_credito_cuota_fija()
        db = make_db()

        cuota_base = make_cuota(numero_cuota=1)  # 100/20/120, no arrastre

        # Total matches monto_a_pagar (120) but capital component (110) exceeds
        # capital_a_pagar (100) + TOL — must still raise ValueError.
        req = RegistrarPagoRequest(capital_pagado=Decimal("110.00"), interes_pagado=Decimal("10.00"))

        with pytest.raises(ValueError):
            await PagoService.registrar_pago(db, cuota_base, credito, req, date(2026, 1, 10))


class TestExcedenteConArrastre:
    """
    Spec Requirement 3, scenario "Payment above base plus arrastre": a payment
    exceeding (base + full arrastre) MUST go through the existing 2-step
    `confirmar_excedente` flow unchanged, even when the cuota's components
    already carry an arrastre. This is the only class in this file that
    calls `confirmar_excedente`.
    """

    @pytest.mark.asyncio
    async def test_pago_supera_base_mas_arrastre_via_confirmar_excedente(self):
        credito = make_credito_cuota_fija(saldo_capital=Decimal("850.00"))
        db = make_db()

        # Base 100/20/120 + full arrastre 50/10 = 150/30/180.
        cuota_arrastre = make_cuota(
            numero_cuota=2, monto_a_pagar=Decimal("180.00"),
            capital=Decimal("150.00"), interes=Decimal("30.00"),
        )

        # Step 1: registrar_pago detects the excedente and does NOT modify
        # the credit or the cuota yet.
        req_excedente = RegistrarPagoRequest(
            capital_pagado=Decimal("200.00"), interes_pagado=Decimal("30.00")
        )
        result1 = await PagoService.registrar_pago(
            db, cuota_arrastre, credito, req_excedente, date(2026, 2, 10)
        )

        assert result1.requiere_decision is True
        assert result1.excedente == Decimal("50.00")
        assert cuota_arrastre.pagado is False
        assert credito.saldo_capital == Decimal("850.00")

        # Step 2: confirmar_excedente applies the user's decision (surplus to
        # capital) and completes the payment through the real (unmocked)
        # generation path.
        result2 = await PagoService.confirmar_excedente(
            db, cuota_arrastre, credito, req_excedente,
            DestinoExcedente.capital, date(2026, 2, 10),
        )

        assert cuota_arrastre.pagado is True
        assert cuota_arrastre.capital_pagado == Decimal("200.00")
        assert cuota_arrastre.interes_pagado == Decimal("30.00")
        assert cuota_arrastre.es_excedente_a == DestinoExcedente.capital

        # Reduction is authoritative from destino: capital_a_pagar (150) +
        # excedente (50) = 200 off capital; interes_a_pagar (30) off interest.
        assert credito.saldo_capital == Decimal("650.00")
        assert credito.saldo_intereses == Decimal("0.00")

        # No shortfall remains after this exact-plus-surplus payment, so the
        # next cuota is generated at base values — the arrastre chain resets.
        siguiente = _ultima_cuota_agregada(db)
        assert siguiente.capital_a_pagar == Decimal("100.00")
        assert siguiente.interes_a_pagar == Decimal("20.00")
        assert siguiente.monto_a_pagar == Decimal("120.00")
