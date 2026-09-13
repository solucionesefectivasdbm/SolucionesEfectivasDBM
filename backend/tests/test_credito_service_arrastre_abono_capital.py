"""
tests/test_credito_service_arrastre_abono_capital.py — Interest-only carry-over
for `abono_capital` credits.

Covers:
- `arrastre_interes_abono_capital`: pure Decimal helper, single source of
  truth for the pending INTEREST shortfall (never capital) of an
  `abono_capital` credit.
- `_ultima_cuota_interes_pagada`: walk-back query, source-row selection.
- `_siguiente_cuota_abono_capital`: folds the shortfall into `interes_a_pagar`
  for mensual/interés successors; abono successors ignore it.
- `generar_siguiente_cuota`: walk-back wiring across an intervening abono row
  (Shortfall Survives an Intervening Abono Cuota).
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.services.credito_service import (
    _siguiente_cuota_abono_capital,
    _ultima_cuota_interes_pagada,
    arrastre_interes_abono_capital,
    generar_siguiente_cuota,
    recalcular_cuota_actual_si_no_pagada,
)


def _mk_pago(
    numero_cuota: int,
    tipo_cuota: TipoCuota,
    interes_a_pagar: Decimal,
    interes_pagado: Decimal,
    pagado: bool = True,
    deleted_at=None,
) -> Pago:
    p = Pago()
    p.id = uuid.uuid4()
    p.credito_id = uuid.uuid4()
    p.numero_cuota = numero_cuota
    p.tipo_cuota = tipo_cuota
    p.capital_a_pagar = Decimal("0.00")
    p.interes_a_pagar = interes_a_pagar
    p.capital_pagado = Decimal("0.00")
    p.interes_pagado = interes_pagado
    p.monto_a_pagar = interes_a_pagar
    p.pagado = pagado
    p.deleted_at = deleted_at
    return p


class TestArrastreInteresAbonoCapital:
    """Unit tests for the pure helper — no DB required."""

    def test_faltante_de_interes(self):
        cuota = _mk_pago(1, TipoCuota.interes, Decimal("50000.00"), Decimal("30000.00"))
        assert arrastre_interes_abono_capital(cuota) == Decimal("20000.00")

    def test_sobrepago_clampa_a_cero(self):
        cuota = _mk_pago(1, TipoCuota.interes, Decimal("50000.00"), Decimal("60000.00"))
        assert arrastre_interes_abono_capital(cuota) == Decimal("0.00")

    def test_cuota_pagada_none_retorna_cero(self):
        assert arrastre_interes_abono_capital(None) == Decimal("0.00")

    def test_cuota_tipo_abono_retorna_cero(self):
        """Las cuotas de abono nunca cargan ni transmiten interés."""
        cuota = _mk_pago(1, TipoCuota.abono, Decimal("0.00"), Decimal("0.00"))
        assert arrastre_interes_abono_capital(cuota) == Decimal("0.00")


def _credito_abono_capital(
    periodicidad: Periodicidad,
    saldo_capital=Decimal("1000000.00"),
    tasa=Decimal("0.05"),
    abono_minimo=Decimal("100000.00"),
) -> Credito:
    return Credito(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente="TEST-ARR-AC-001",
        tipo_credito=TipoCredito.abono_capital,
        capital_prestado=saldo_capital,
        tasa_interes_mensual=tasa,
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 10),
        periodicidad=periodicidad,
        saldo_capital=saldo_capital,
        saldo_intereses=Decimal("0.00"),
        abono_minimo=abono_minimo,
        numero_cuotas=None,
        calcular_interes_dias_corridos=False,
        activo=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


class TestUltimaCuotaInteresPagada:
    """Walk-back query — `db_session` (aiosqlite), unmocked."""

    @pytest.mark.asyncio
    async def test_ignora_no_pagada_soft_deleted_abono_y_no_programada(self, db_session):
        credito = _credito_abono_capital(Periodicidad.quincenal)
        db_session.add(credito)
        await db_session.flush()

        no_pagada = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("50000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 1, 10), pagado=False,
        )
        soft_deleted = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("50000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("30000.00"),
            momento="m3", fecha_maxima=date(2026, 1, 25), pagado=True,
            deleted_at=datetime(2026, 2, 1),
        )
        abono_pagada = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=3,
            tipo_cuota=TipoCuota.abono, monto_a_pagar=Decimal("100000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("0.00"),
            capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 2, 10), pagado=True,
        )
        no_programada = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=4,
            tipo_cuota=TipoCuota.no_programada, monto_a_pagar=Decimal("10000.00"),
            capital_a_pagar=Decimal("10000.00"), interes_a_pagar=Decimal("0.00"),
            capital_pagado=Decimal("10000.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 2, 15), pagado=True,
        )
        valida = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=5,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("50000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("40000.00"),
            momento="m3", fecha_maxima=date(2026, 2, 25), pagado=True,
        )
        db_session.add_all([no_pagada, soft_deleted, abono_pagada, no_programada, valida])
        await db_session.flush()

        resultado = await _ultima_cuota_interes_pagada(db_session, credito.id, antes_de=6)
        assert resultado is not None
        assert resultado.numero_cuota == 5

    @pytest.mark.asyncio
    async def test_sin_fila_previa_retorna_none(self, db_session):
        credito = _credito_abono_capital(Periodicidad.quincenal)
        db_session.add(credito)
        await db_session.flush()

        resultado = await _ultima_cuota_interes_pagada(db_session, credito.id, antes_de=1)
        assert resultado is None


class TestSiguienteCuotaAbonoCapitalArrastre:
    """`_siguiente_cuota_abono_capital` folds saldo_pendiente into interés."""

    def test_mensual_combinada_pliega_arrastre_en_interes(self):
        credito = _credito_abono_capital(Periodicidad.mensual, tasa=Decimal("0.05"))
        anterior = _mk_pago(1, TipoCuota.programada, Decimal("50000.00"), Decimal("30000.00"))
        nueva = _siguiente_cuota_abono_capital(
            credito, anterior, 2, date(2026, 2, 10), "m3", None, Decimal("20000.00"),
        )
        assert nueva.capital_a_pagar == Decimal("100000.00")
        assert nueva.interes_a_pagar == Decimal("70000.00")
        assert nueva.monto_a_pagar == Decimal("170000.00")
        assert nueva.capital_a_pagar + nueva.interes_a_pagar == nueva.monto_a_pagar

    def test_sucesor_interes_pliega_arrastre(self):
        credito = _credito_abono_capital(Periodicidad.quincenal, tasa=Decimal("0.05"))
        anterior = _mk_pago(2, TipoCuota.abono, Decimal("0.00"), Decimal("0.00"))
        nueva = _siguiente_cuota_abono_capital(
            credito, anterior, 3, date(2026, 2, 10), "m3", None, Decimal("20000.00"),
        )
        assert nueva.tipo_cuota == TipoCuota.interes
        assert nueva.capital_a_pagar == Decimal("0.00")
        assert nueva.interes_a_pagar == Decimal("70000.00")
        assert nueva.monto_a_pagar == Decimal("70000.00")
        assert nueva.capital_a_pagar + nueva.interes_a_pagar == nueva.monto_a_pagar

    def test_sucesor_abono_ignora_saldo_pendiente(self):
        """El saldo_pendiente explícitamente NUNCA infla una cuota de abono."""
        credito = _credito_abono_capital(Periodicidad.quincenal, tasa=Decimal("0.05"))
        anterior = _mk_pago(1, TipoCuota.interes, Decimal("50000.00"), Decimal("30000.00"))
        nueva = _siguiente_cuota_abono_capital(
            credito, anterior, 2, date(2026, 2, 10), "m3", None, Decimal("20000.00"),
        )
        assert nueva.tipo_cuota == TipoCuota.abono
        assert nueva.interes_a_pagar == Decimal("0.00")
        assert nueva.monto_a_pagar == credito.abono_minimo
        assert nueva.capital_a_pagar == credito.abono_minimo


class TestGenerarSiguienteCuotaWalkBack:
    """Requirement: Shortfall Survives an Intervening Abono Cuota — via
    `db_session` (aiosqlite), unmocked; exercises the real walk-back query."""

    @pytest.mark.asyncio
    async def test_parcial_interes_abono_luego_interes(self, db_session):
        credito = _credito_abono_capital(
            Periodicidad.quincenal, saldo_capital=Decimal("1000000.00"), tasa=Decimal("0.05"),
        )
        db_session.add(credito)
        await db_session.flush()

        cuota_n = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("50000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("30000.00"),
            momento="m3", fecha_maxima=date(2026, 1, 10), pagado=True,
        )
        cuota_n_mas_1 = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
            tipo_cuota=TipoCuota.abono, monto_a_pagar=Decimal("100000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("0.00"),
            capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 1, 25), pagado=True,
        )
        db_session.add_all([cuota_n, cuota_n_mas_1])
        await db_session.flush()

        cuota_n_mas_2 = await generar_siguiente_cuota(
            db=db_session, credito=credito, cuota_anterior=cuota_n_mas_1,
            receptor_id=None, saldo_pendiente=Decimal("0.00"),
        )
        assert cuota_n_mas_2.tipo_cuota == TipoCuota.interes
        assert cuota_n_mas_2.interes_a_pagar == Decimal("70000.00")

    @pytest.mark.asyncio
    async def test_cadena_no_dobla_conteo(self, db_session):
        credito = _credito_abono_capital(
            Periodicidad.quincenal, saldo_capital=Decimal("1000000.00"), tasa=Decimal("0.05"),
        )
        db_session.add(credito)
        await db_session.flush()

        cuota_n_mas_2 = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=3,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("70000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("70000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("60000.00"),
            momento="m3", fecha_maxima=date(2026, 2, 10), pagado=True,
        )
        cuota_n_mas_3 = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=4,
            tipo_cuota=TipoCuota.abono, monto_a_pagar=Decimal("100000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("0.00"),
            capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 2, 25), pagado=True,
        )
        db_session.add_all([cuota_n_mas_2, cuota_n_mas_3])
        await db_session.flush()

        cuota_n_mas_4 = await generar_siguiente_cuota(
            db=db_session, credito=credito, cuota_anterior=cuota_n_mas_3,
            receptor_id=None, saldo_pendiente=Decimal("0.00"),
        )
        base_interes = credito.saldo_capital * credito.tasa_interes_mensual
        assert cuota_n_mas_4.interes_a_pagar == base_interes + Decimal("10000.00")


class TestRecalcularCuotaActualPreservaArrastreAbonoCapital:
    """Requirement: Recalculation Preserves Pending Arrastre — abono_capital
    mensual y alternado."""

    @pytest.mark.asyncio
    async def test_mensual_preserva_arrastre_tras_pago_no_programado(self, db_session):
        credito = _credito_abono_capital(
            Periodicidad.mensual, saldo_capital=Decimal("900000.00"), tasa=Decimal("0.05"),
        )
        db_session.add(credito)
        await db_session.flush()

        cuota_pagada = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("150000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("30000.00"),
            momento="m3", fecha_maxima=date(2026, 1, 10), pagado=True,
        )
        cuota_actual = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
            tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("165000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("65000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 2, 10), pagado=False,
        )
        db_session.add_all([cuota_pagada, cuota_actual])
        await db_session.flush()

        ok = await recalcular_cuota_actual_si_no_pagada(db_session, credito)

        assert ok is True
        # Base sobre saldo_capital 900000*0.05=45000 + arrastre 20000 = 65000.
        assert cuota_actual.interes_a_pagar == Decimal("65000.00")
        assert cuota_actual.capital_a_pagar == credito.abono_minimo
        assert cuota_actual.monto_a_pagar == Decimal("165000.00")
        assert cuota_actual.capital_a_pagar + cuota_actual.interes_a_pagar == cuota_actual.monto_a_pagar

    @pytest.mark.asyncio
    async def test_alternado_interes_preserva_arrastre_tras_edicion_admin(self, db_session):
        credito = _credito_abono_capital(
            Periodicidad.quincenal, saldo_capital=Decimal("900000.00"), tasa=Decimal("0.05"),
        )
        db_session.add(credito)
        await db_session.flush()

        cuota_pagada = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("50000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("30000.00"),
            momento="m3", fecha_maxima=date(2026, 1, 10), pagado=True,
        )
        cuota_actual = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("65000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("65000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 1, 25), pagado=False,
        )
        db_session.add_all([cuota_pagada, cuota_actual])
        await db_session.flush()

        ok = await recalcular_cuota_actual_si_no_pagada(db_session, credito)

        assert ok is True
        assert cuota_actual.interes_a_pagar == Decimal("65000.00")
        assert cuota_actual.capital_a_pagar == Decimal("0.00")
        assert cuota_actual.monto_a_pagar == Decimal("65000.00")

    @pytest.mark.asyncio
    async def test_alternado_abono_recalculado_se_mantiene_sin_interes(self, db_session):
        credito = _credito_abono_capital(
            Periodicidad.quincenal, saldo_capital=Decimal("900000.00"), tasa=Decimal("0.05"),
        )
        db_session.add(credito)
        await db_session.flush()

        cuota_pagada = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.interes, monto_a_pagar=Decimal("50000.00"),
            capital_a_pagar=Decimal("0.00"), interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("30000.00"),
            momento="m3", fecha_maxima=date(2026, 1, 10), pagado=True,
        )
        cuota_actual = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
            tipo_cuota=TipoCuota.abono, monto_a_pagar=Decimal("100000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("0.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 1, 25), pagado=False,
        )
        db_session.add_all([cuota_pagada, cuota_actual])
        await db_session.flush()

        ok = await recalcular_cuota_actual_si_no_pagada(db_session, credito)

        assert ok is True
        assert cuota_actual.interes_a_pagar == Decimal("0.00")
        assert cuota_actual.monto_a_pagar == credito.abono_minimo
        assert cuota_actual.capital_a_pagar == credito.abono_minimo
