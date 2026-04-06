"""
tests/test_pago_service.py — Tests de los 3 escenarios de pago.

Los tests más críticos del sistema: verifican que la lógica de
pago exacto, parcial y con excedente funciona correctamente
para ambos tipos de crédito.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import DestinoExcedente, Pago, TipoCuota
from app.schemas.pago import RegistrarPagoRequest
from app.services.pago_service import PagoService


def make_credito(
    tipo=TipoCredito.cuota_fija,
    saldo_capital=Decimal("1000000"),
    saldo_intereses=Decimal("30000"),
    numero_cuotas=12,
    tasa=Decimal("0.0300"),
) -> Credito:
    c = Credito()
    c.id = uuid.uuid4()
    c.tipo_credito = tipo
    c.capital_prestado = saldo_capital
    c.saldo_capital = saldo_capital
    c.saldo_intereses = saldo_intereses
    c.tasa_interes_mensual = tasa
    c.numero_cuotas = numero_cuotas
    c.periodicidad = Periodicidad.mensual
    c.activo = True
    return c


def make_pago(
    numero_cuota=1,
    monto_a_pagar=Decimal("100462"),
    capital=Decimal("70462"),
    interes=Decimal("30000"),
    tipo=TipoCuota.programada,
) -> Pago:
    p = Pago()
    p.id = uuid.uuid4()
    p.credito_id = uuid.uuid4()
    p.numero_cuota = numero_cuota
    p.tipo_cuota = tipo
    p.monto_a_pagar = monto_a_pagar
    p.capital_a_pagar = capital
    p.interes_a_pagar = interes
    p.capital_pagado = Decimal("0")
    p.interes_pagado = Decimal("0")
    p.momento = "m3"
    p.fecha_maxima = date(2026, 3, 10)
    p.receptor_id = None
    p.pagado = False
    p.validado_recaudador = False
    p.fecha_pago_real = None
    p.es_excedente_a = None
    p.es_ultimo_pago = False
    return p


class TestPagoExacto:

    @pytest.mark.asyncio
    async def test_pago_exacto_marca_pagado(self):
        credito = make_credito()
        pago = make_pago()
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("70462"),
            interes_pagado=Decimal("30000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            result = await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        assert pago.pagado is True
        assert result.requiere_decision is False
        assert pago.capital_pagado == Decimal("70462")
        assert pago.interes_pagado == Decimal("30000")

    @pytest.mark.asyncio
    async def test_pago_exacto_reduce_saldo_capital(self):
        credito = make_credito(saldo_capital=Decimal("1000000"))
        pago = make_pago(capital=Decimal("70462"), interes=Decimal("30000"))
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("70462"),
            interes_pagado=Decimal("30000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        assert credito.saldo_capital == Decimal("929538.00")

    @pytest.mark.asyncio
    async def test_pago_exacto_registra_fecha_real(self):
        credito = make_credito()
        pago = make_pago()
        db = AsyncMock()
        hoy = date(2026, 3, 10)

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("70462"),
            interes_pagado=Decimal("30000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            await PagoService.registrar_pago(db, pago, credito, request, hoy)

        assert pago.fecha_pago_real == hoy


class TestPagoParcial:

    @pytest.mark.asyncio
    async def test_pago_parcial_marca_pagado(self):
        """Pago parcial sigue marcando la cuota como pagada."""
        credito = make_credito()
        pago = make_pago(monto_a_pagar=Decimal("100462"))
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("30000"),
            interes_pagado=Decimal("20000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            result = await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        assert pago.pagado is True
        assert result.requiere_decision is False

    @pytest.mark.asyncio
    async def test_pago_parcial_faltante_en_mensaje(self):
        credito = make_credito()
        pago = make_pago(monto_a_pagar=Decimal("100000"))
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("40000"),
            interes_pagado=Decimal("20000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            result = await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        # Faltante: 100000 - 60000 = 40000
        assert "40000" in result.mensaje


class TestPagoExcedente:

    @pytest.mark.asyncio
    async def test_excedente_retorna_requiere_decision(self):
        """Si paga más, debe retornar requiere_decision=True."""
        credito = make_credito()
        pago = make_pago(monto_a_pagar=Decimal("100000"))
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("100000"),
            interes_pagado=Decimal("50000"),  # Total: 150000 > 100000
        )

        result = await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        assert result.requiere_decision is True
        assert result.excedente == Decimal("50000")

    @pytest.mark.asyncio
    async def test_excedente_no_modifica_credito_hasta_decision(self):
        """El saldo no cambia mientras requiere_decision=True."""
        credito = make_credito(saldo_capital=Decimal("1000000"))
        pago = make_pago(monto_a_pagar=Decimal("100000"))
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("100000"),
            interes_pagado=Decimal("50000"),
        )

        await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        # El saldo NO debe haber cambiado
        assert credito.saldo_capital == Decimal("1000000")
        assert pago.pagado is False

    @pytest.mark.asyncio
    async def test_confirmar_excedente_a_capital(self):
        """Al confirmar con destino=capital, reduce el saldo_capital."""
        credito = make_credito(saldo_capital=Decimal("1000000"))
        pago = make_pago(
            monto_a_pagar=Decimal("100000"),
            capital=Decimal("70000"),
            interes=Decimal("30000"),
        )
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("120000"),
            interes_pagado=Decimal("30000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            result = await PagoService.confirmar_excedente(
                db, pago, credito, request, DestinoExcedente.capital, date(2026, 3, 10)
            )

        # Excedente: 150000 - 100000 = 50000 va a capital
        # Capital reducido: 1000000 - 70000 (capital cuota) - 50000 (excedente) = 880000
        assert credito.saldo_capital == Decimal("880000.00")
        assert pago.pagado is True
        assert pago.es_excedente_a == DestinoExcedente.capital

    @pytest.mark.asyncio
    async def test_confirmar_excedente_a_intereses(self):
        """Al confirmar con destino=intereses, reduce saldo_intereses."""
        credito = make_credito(
            saldo_capital=Decimal("1000000"),
            saldo_intereses=Decimal("30000"),
        )
        pago = make_pago(
            monto_a_pagar=Decimal("100000"),
            capital=Decimal("70000"),
            interes=Decimal("30000"),
        )
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("70000"),
            interes_pagado=Decimal("50000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            await PagoService.confirmar_excedente(
                db, pago, credito, request, DestinoExcedente.intereses, date(2026, 3, 10)
            )

        # Excedente: 120000 - 100000 = 20000 va a intereses
        # saldo_intereses: 30000 - 30000 (interes cuota) - 20000 (excedente) = -20000 → 0
        assert credito.saldo_intereses == Decimal("0.00")
        assert pago.es_excedente_a == DestinoExcedente.intereses


class TestCierreCreditoAutomatico:

    @pytest.mark.asyncio
    async def test_cierre_al_llegar_saldo_cero(self):
        """Cuando saldo_capital llega a 0, el crédito se cierra."""
        credito = make_credito(saldo_capital=Decimal("70462"), numero_cuotas=12)
        # Última cuota: capital es exactamente el saldo restante
        pago = make_pago(
            numero_cuota=1,
            monto_a_pagar=Decimal("100462"),
            capital=Decimal("70462"),
            interes=Decimal("30000"),
        )
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("70462"),
            interes_pagado=Decimal("30000"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        assert credito.activo is False
        assert credito.saldo_capital == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_cierre_al_alcanzar_ultima_cuota(self):
        """Para cuota_fija: se cierra al pagar la cuota número numero_cuotas."""
        credito = make_credito(numero_cuotas=3)
        pago = make_pago(
            numero_cuota=3,
            monto_a_pagar=Decimal("100000"),
            capital=Decimal("1000000"),  # Todo el saldo
            interes=Decimal("0"),
        )
        pago.es_ultimo_pago = True
        credito.saldo_capital = Decimal("100000")
        db = AsyncMock()

        request = RegistrarPagoRequest(
            capital_pagado=Decimal("100000"),
            interes_pagado=Decimal("0"),
        )

        with patch("app.services.pago_service.generar_siguiente_cuota", return_value=None):
            await PagoService.registrar_pago(db, pago, credito, request, date(2026, 3, 10))

        assert credito.activo is False


class TestPropagacionReceptor:
    """Tests del router de gestores para propagación de receptor."""

    @pytest.mark.asyncio
    async def test_propagacion_se_llama_al_cambiar_receptor(self):
        """Verificar que _propagar_receptor_a_pagos se invoca al cambiar receptor."""
        from app.routers.gestores import _propagar_receptor_a_pagos

        db = AsyncMock()
        db.execute = AsyncMock()

        nuevo_receptor = uuid.uuid4()
        gestor_id = uuid.uuid4()

        # No debería lanzar excepción
        await _propagar_receptor_a_pagos(db, gestor_id, nuevo_receptor)
        assert db.execute.called
