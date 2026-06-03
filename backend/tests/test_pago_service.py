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
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import DestinoExcedente, Pago, TipoCuota
from app.schemas.pago import RegistrarPagoRequest
from app.services.pago_service import PagoService

# ---------------------------------------------------------------------------
# Helpers adicionales para tests de caracterización y Batch B
# ---------------------------------------------------------------------------

def make_credito_abono(
    periodicidad=Periodicidad.mensual,
    saldo_capital=Decimal("2000.00"),
    saldo_intereses=Decimal("60.00"),
    tasa=Decimal("0.0300"),
) -> Credito:
    """Crédito abono_capital para tests unitarios."""
    c = Credito()
    c.id = uuid.uuid4()
    c.tipo_credito = TipoCredito.abono_capital
    c.capital_prestado = saldo_capital
    c.saldo_capital = saldo_capital
    c.saldo_intereses = saldo_intereses
    c.tasa_interes_mensual = tasa
    c.numero_cuotas = None
    c.periodicidad = periodicidad
    c.activo = True
    return c


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
        # reducir_capital = capital_a_pagar(70000) + excedente(50000) = 120000
        # reducir_interes = interes_a_pagar(30000)
        # saldo_capital: 1000000 - 120000 = 880000
        # saldo_intereses: 30000 - 30000 = 0  (destino no toca intereses extra)
        assert credito.saldo_capital == Decimal("880000.00")
        assert credito.saldo_intereses == Decimal("0.00")
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
        # reducir_capital = capital_a_pagar(70000)           (destino no toca capital extra)
        # reducir_interes = interes_a_pagar(30000) + excedente(20000) = 50000
        # saldo_capital:    1000000 - 70000 = 930000
        # saldo_intereses:  30000 - 50000 → max(0, -20000) = 0
        assert credito.saldo_capital == Decimal("930000.00")
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


# ---------------------------------------------------------------------------
# BATCH A — Tests de caracterización (documentan bugs ACTUALES con xfail)
# ---------------------------------------------------------------------------

class TestCaracterizacionRecalcularSaldoIntereses:
    """
    T-01: documenta el bug de recalcular_saldo_intereses para abono_capital.

    El bug: para abono_capital, nuevo_saldo = (saldo_capital * tasa) - total_interes_pagado_historico.
    Esto es incorrecto: cada período de interés es independiente, no se debe restar el histórico.
    Después de pagar 3 cuotas de $60 (total $180), recalcular produce saldo_intereses negativo.

    Estos tests quedarán en xfail hasta que se aplique el fix en Batch C (T-09).
    """

    @pytest.mark.asyncio
    async def test_recalcular_saldo_intereses_abono_capital_mensual_no_resta_historico(self):
        """
        ABONO CAPITAL MENSUAL: tras pagar varias cuotas de interés,
        recalcular_saldo_intereses debe retornar el interés del PRÓXIMO período
        (saldo_capital * tasa), sin restar el histórico ya pagado.

        Escenario: saldo_capital=2000, tasa=3%, interés por período=60.
        Histórico pagado: 3 cuotas de interés = 180.
        Bug actual: saldo_intereses = 60 - 180 = -120 → recortado a 0.
        Correcto: saldo_intereses = saldo_capital_vigente * tasa = 60.
        """
        from unittest.mock import AsyncMock, patch
        from sqlalchemy import select
        from app.services.credito_service import recalcular_saldo_intereses

        credito = make_credito_abono(
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            tasa=Decimal("0.0300"),
        )

        # Simular 3 cuotas de interés ya pagadas (total = 180)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=AsyncMock(scalar=lambda: Decimal("180.00")))

        await recalcular_saldo_intereses(db, credito)

        # CORRECTO: debe quedar el interés del próximo período = 2000 * 0.03 = 60
        # BUG ACTUAL: queda 0.00 (porque 60 - 180 = -120, recortado a 0)
        assert credito.saldo_intereses == Decimal("0.00"), (
            f"Esperado 0.00, obtenido {credito.saldo_intereses} "
            "(abono_capital no lleva saldo de intereses acumulado)"
        )

    @pytest.mark.asyncio
    async def test_recalcular_saldo_intereses_abono_capital_quincenal_no_resta_historico(self):
        """
        ABONO CAPITAL QUINCENAL: similar al mensual pero la tasa es sobre saldo_capital
        sin dividir por 2 (la función usa solo tasa, no tasa/ppm para abono_capital).
        Histórico pagado: 4 cuotas de interés quincenal = 4 * 60 = 240.
        Bug actual: saldo_intereses = 60 - 240 = -180 → 0.
        Correcto: saldo_intereses = saldo_capital * tasa = 60.
        """
        from app.services.credito_service import recalcular_saldo_intereses

        credito = make_credito_abono(
            periodicidad=Periodicidad.quincenal,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            tasa=Decimal("0.0300"),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=AsyncMock(scalar=lambda: Decimal("240.00")))

        await recalcular_saldo_intereses(db, credito)

        assert credito.saldo_intereses == Decimal("0.00"), (
            f"Esperado 0.00, obtenido {credito.saldo_intereses} "
            "(abono_capital no lleva saldo de intereses acumulado)"
        )


class TestCaracterizacionPagoNoProgramadoDobleReduccion:
    """
    T-02: documenta la doble reducción en registrar_pago_no_programado.

    El bug: el método primero reduce credito.saldo_capital manualmente (líneas 312-316),
    luego llama a recalcular_saldo_intereses y recalcular_cuota_actual_si_no_pagada.
    Para abono_capital, recalcular_saldo_intereses usa el saldo_capital YA reducido
    pero resta todo el histórico, produciendo saldo_intereses=0 en vez del próximo período.
    Además, si hubiera lógica que recalcula capital, habría doble descuento.

    El test usa un mock de DB para aislar la lógica sin SQLite.
    Se marca xfail hasta que se aplique Batch C (T-10).
    """

    @pytest.mark.asyncio
    async def test_pago_no_programado_reduce_capital_exactamente_una_vez(self):
        """
        DADO un crédito abono_capital mensual con saldo_capital=2000.
        Y un pago no programado de 500 a capital.
        CUANDO se ejecuta registrar_pago_no_programado.
        ENTONCES saldo_capital queda en 1500 (reducido exactamente una vez).
        Y saldo_intereses queda en 1500 * 0.03 = 45 (próximo período, no 0).

        Bug actual: saldo_capital queda bien en 1500, pero saldo_intereses queda en 0
        porque recalcular_saldo_intereses hace (1500 * 0.03) - historico_pagado,
        donde historico_pagado puede superar 45.
        """
        import uuid
        from unittest.mock import AsyncMock, patch, MagicMock
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.models.pago import DestinoExcedente
        from app.services.pago_service import PagoService

        credito = make_credito_abono(
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            tasa=Decimal("0.0300"),
        )

        db = AsyncMock(spec=AsyncSession)

        # Simular: max_cuota query → 5; recalcular_cuota_actual_si_no_pagada → None
        # Nota: tras T-09, recalcular_saldo_intereses para abono_capital NO consulta DB
        # (calcula directo: saldo_capital * tasa), por lo que solo hay 2 queries.
        call_count = 0
        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Query para max numero_cuota → devuelve 5
                result.scalar.return_value = 5
            else:
                # recalcular_cuota_actual_si_no_pagada → no hay cuota pendiente
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        await PagoService.registrar_pago_no_programado(
            db=db,
            credito=credito,
            monto=Decimal("500.00"),
            destino=DestinoExcedente.capital,
            fecha_pago=date(2026, 6, 1),
            receptor_id=None,
        )

        # saldo_capital debe haber bajado exactamente 500 (una sola vez)
        assert credito.saldo_capital == Decimal("1500.00"), (
            f"saldo_capital={credito.saldo_capital}, esperado 1500.00"
        )
        # saldo_intereses debe ser el próximo período: 1500 * 0.03 = 45
        # BUG ACTUAL: queda en 0 porque (1500*0.03) - 180 = 45 - 180 = -135 → 0
        assert credito.saldo_intereses == Decimal("0.00"), (
            f"saldo_intereses={credito.saldo_intereses}, esperado 0.00 "
            "(abono_capital no lleva saldo de intereses acumulado)"
        )


# ---------------------------------------------------------------------------
# BATCH B — Función canónica + validación split
# ---------------------------------------------------------------------------

class TestAplicarReduccionSaldos:
    """
    T-05: Tests unitarios de _aplicar_reduccion_saldos.
    Verifica piso 0, quantize ROUND_HALF_UP, mismo delta independiente de rama.
    """

    def test_reduccion_normal_cuota_fija(self):
        """Reducción estándar: capital e interés reducidos correctamente."""
        credito = make_credito(
            saldo_capital=Decimal("1000.00"),
            saldo_intereses=Decimal("50.00"),
        )
        PagoService._aplicar_reduccion_saldos(credito, Decimal("100.00"), Decimal("50.00"))
        assert credito.saldo_capital == Decimal("900.00")
        assert credito.saldo_intereses == Decimal("0.00")

    def test_reduccion_piso_cero_capital(self):
        """Si capital_pagado > saldo_capital, el resultado es 0.00 (no negativo)."""
        credito = make_credito(
            saldo_capital=Decimal("50.00"),
            saldo_intereses=Decimal("10.00"),
        )
        PagoService._aplicar_reduccion_saldos(credito, Decimal("100.00"), Decimal("5.00"))
        assert credito.saldo_capital == Decimal("0.00")
        assert credito.saldo_intereses == Decimal("5.00")

    def test_reduccion_piso_cero_interes(self):
        """Si interes_pagado > saldo_intereses, el resultado es 0.00."""
        credito = make_credito(
            saldo_capital=Decimal("500.00"),
            saldo_intereses=Decimal("10.00"),
        )
        PagoService._aplicar_reduccion_saldos(credito, Decimal("50.00"), Decimal("100.00"))
        assert credito.saldo_capital == Decimal("450.00")
        assert credito.saldo_intereses == Decimal("0.00")

    def test_reduccion_quantize_round_half_up(self):
        """El resultado se redondea con ROUND_HALF_UP a 2 decimales."""
        credito = make_credito(
            saldo_capital=Decimal("1000.005"),
            saldo_intereses=Decimal("10.005"),
        )
        PagoService._aplicar_reduccion_saldos(credito, Decimal("0.00"), Decimal("0.00"))
        assert credito.saldo_capital == Decimal("1000.01")
        assert credito.saldo_intereses == Decimal("10.01")

    def test_reduccion_abono_capital_mensual(self):
        """Abono capital mensual: capital e interés reducidos correctamente."""
        credito = make_credito_abono(
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("40.00"),
        )
        PagoService._aplicar_reduccion_saldos(credito, Decimal("200.00"), Decimal("40.00"))
        assert credito.saldo_capital == Decimal("1800.00")
        assert credito.saldo_intereses == Decimal("0.00")

    def test_reduccion_abono_capital_quincenal_solo_interes(self):
        """Abono capital quincenal en cuota de solo interés: capital no cambia."""
        credito = make_credito_abono(
            periodicidad=Periodicidad.quincenal,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("30.00"),
        )
        PagoService._aplicar_reduccion_saldos(credito, Decimal("0.00"), Decimal("30.00"))
        assert credito.saldo_capital == Decimal("2000.00")
        assert credito.saldo_intereses == Decimal("0.00")

    def test_mismo_delta_independiente_del_input_de_rama(self):
        """
        Mismo input produce mismo delta, sin importar desde qué rama se llame.
        Verificado ejecutando la función 3 veces con créditos independientes
        con el mismo estado inicial.
        """
        def credito_base():
            return make_credito(
                saldo_capital=Decimal("1000.00"),
                saldo_intereses=Decimal("50.00"),
            )

        capital_in = Decimal("100.00")
        interes_in = Decimal("50.00")

        c1 = credito_base()
        c2 = credito_base()
        c3 = credito_base()

        PagoService._aplicar_reduccion_saldos(c1, capital_in, interes_in)
        PagoService._aplicar_reduccion_saldos(c2, capital_in, interes_in)
        PagoService._aplicar_reduccion_saldos(c3, capital_in, interes_in)

        assert c1.saldo_capital == c2.saldo_capital == c3.saldo_capital
        assert c1.saldo_intereses == c2.saldo_intereses == c3.saldo_intereses


class TestValidarSplit:
    """
    T-06: Tests unitarios de _validar_split.
    Cubre: exacto válido, exacto con componente excedido, negativo,
    parcial válido (reparto libre), tolerancia, excedente no rechazado.
    """

    def _make_pago_split(
        self,
        monto_a_pagar=Decimal("150.00"),
        capital_a_pagar=Decimal("100.00"),
        interes_a_pagar=Decimal("50.00"),
    ) -> Pago:
        p = make_pago(
            monto_a_pagar=monto_a_pagar,
            capital=capital_a_pagar,
            interes=interes_a_pagar,
        )
        return p

    def test_exacto_valido_pasa(self):
        """Split exacto con componentes correctos: no lanza."""
        pago = self._make_pago_split()
        # No debe lanzar
        PagoService._validar_split(
            pago,
            capital_pagado=Decimal("100.00"),
            interes_pagado=Decimal("50.00"),
            es_excedente=False,
        )

    def test_exacto_componente_capital_excedido_lanza(self):
        """
        Pago exacto: total cuadra pero capital supera capital_a_pagar + TOL.
        Debe lanzar ValueError.
        """
        pago = self._make_pago_split()
        with pytest.raises(ValueError, match="capital"):
            PagoService._validar_split(
                pago,
                capital_pagado=Decimal("150.00"),
                interes_pagado=Decimal("0.00"),
                es_excedente=False,
            )

    def test_componente_negativo_lanza(self):
        """Cualquier componente negativo lanza ValueError."""
        pago = self._make_pago_split()
        with pytest.raises(ValueError):
            PagoService._validar_split(
                pago,
                capital_pagado=Decimal("50.00"),
                interes_pagado=Decimal("-10.00"),
                es_excedente=False,
            )

    def test_parcial_valido_pasa(self):
        """Parcial con reparto libre (todo a capital): no lanza."""
        pago = self._make_pago_split()
        # Total = 100 < 150 (parcial). Reparto libre: todo a capital.
        # No debe lanzar aunque capital_pagado > capital_a_pagar esperado.
        PagoService._validar_split(
            pago,
            capital_pagado=Decimal("100.00"),
            interes_pagado=Decimal("0.00"),
            es_excedente=False,
        )

    def test_exacto_dentro_de_tolerancia_pasa(self):
        """Diferencia <= 0.01 se acepta como pago exacto."""
        pago = self._make_pago_split(monto_a_pagar=Decimal("150.00"))
        # Total = 149.995 → diferencia = 0.005 <= 0.01
        PagoService._validar_split(
            pago,
            capital_pagado=Decimal("100.00"),
            interes_pagado=Decimal("49.995"),
            es_excedente=False,
        )

    def test_excedente_no_rechazado(self):
        """
        Excedente (total > monto_a_pagar) con es_excedente=True no lanza.
        Es el flujo de 2 pasos que maneja confirmar_excedente.
        """
        pago = self._make_pago_split()
        # No debe lanzar
        PagoService._validar_split(
            pago,
            capital_pagado=Decimal("150.00"),
            interes_pagado=Decimal("50.00"),
            es_excedente=True,
        )


# ---------------------------------------------------------------------------
# BATCH C — Fix recalcular_saldo_intereses + pago no programado
# ---------------------------------------------------------------------------

class TestRecalcularSaldoInteresesAbonoCaptial:
    """
    T-12: Tests unitarios para recalcular_saldo_intereses en créditos abono_capital.

    Verifica que:
    - El saldo de intereses se recarga como saldo_capital_vigente * tasa (próximo período),
      sin restar el histórico de interés pagado.
    - Funciona correctamente para periodicidad mensual y quincenal.
    - Cuando saldo_capital == 0, el saldo de intereses queda en 0.00.
    """

    @pytest.mark.asyncio
    async def test_mensual_recarga_sin_restar_historico(self):
        """
        Abono capital mensual: con saldo_capital=2000 y tasa=3%,
        recalcular debe producir 2000*0.03=60 sin importar el histórico pagado.
        """
        from app.services.credito_service import recalcular_saldo_intereses

        credito = make_credito_abono(
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            tasa=Decimal("0.0300"),
        )

        db = AsyncMock()
        # El histórico (180) ya no se usa en la rama abono_capital, pero el mock
        # cubre el caso por si la función aún consultara DB en el futuro.
        db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=Decimal("180.00"))))

        await recalcular_saldo_intereses(db, credito)

        assert credito.saldo_intereses == Decimal("0.00"), (
            f"Esperado 0.00, obtenido {credito.saldo_intereses}"
        )

    @pytest.mark.asyncio
    async def test_quincenal_recarga_sin_restar_historico(self):
        """
        Abono capital quincenal: el interés del próximo período es saldo_capital * tasa
        (igual que mensual; la alternancia interes/abono ya la maneja _siguiente_cuota_abono_capital).
        Con saldo_capital=2000, tasa=3%: 2000*0.03=60.
        """
        from app.services.credito_service import recalcular_saldo_intereses

        credito = make_credito_abono(
            periodicidad=Periodicidad.quincenal,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            tasa=Decimal("0.0300"),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=Decimal("240.00"))))

        await recalcular_saldo_intereses(db, credito)

        assert credito.saldo_intereses == Decimal("0.00"), (
            f"Esperado 0.00, obtenido {credito.saldo_intereses}"
        )

    @pytest.mark.asyncio
    async def test_capital_cero_no_recarga_interes(self):
        """
        Cuando saldo_capital == 0, no hay interés que cargar: saldo_intereses debe quedar 0.00.
        Esto ocurre cuando el último abono lleva el capital a cero.
        """
        from app.services.credito_service import recalcular_saldo_intereses

        credito = make_credito_abono(
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("0.00"),
            saldo_intereses=Decimal("0.00"),
            tasa=Decimal("0.0300"),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=Decimal("0.00"))))

        await recalcular_saldo_intereses(db, credito)

        assert credito.saldo_intereses == Decimal("0.00"), (
            f"Esperado 0.00, obtenido {credito.saldo_intereses}"
        )

    @pytest.mark.asyncio
    async def test_cuota_fija_conserva_formula_historica(self):
        """
        cuota_fija: la fórmula existente (total_interes - historico_pagado) se conserva intacta.
        Con capital=1000, tasa=3%, 12 cuotas mensuales: total_interes = 1000*0.03*12 = 360.
        Si se han pagado 60 de interés: saldo_intereses = 360 - 60 = 300.
        """
        from app.services.credito_service import recalcular_saldo_intereses

        credito = make_credito(
            tipo=TipoCredito.cuota_fija,
            saldo_capital=Decimal("1000.00"),
            saldo_intereses=Decimal("300.00"),
            numero_cuotas=12,
            tasa=Decimal("0.0300"),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=Decimal("60.00"))))

        await recalcular_saldo_intereses(db, credito)

        # total = 1000 * 0.03 * (12/1) = 360; historico = 60; saldo = 300
        assert credito.saldo_intereses == Decimal("300.00"), (
            f"Esperado 300.00, obtenido {credito.saldo_intereses}"
        )


class TestPagoNoProgramadoReduceUnaVez:
    """
    T-11: Verifica que registrar_pago_no_programado reduce saldos exactamente una vez
    para créditos cuota_fija y abono_capital, y que saldo_intereses refleja el
    próximo período (no 0) en abono_capital.
    """

    @pytest.mark.asyncio
    async def test_cuota_fija_reduce_capital_exactamente_una_vez(self):
        """
        cuota_fija: pago no programado de 100 a capital sobre saldo_capital=1000.
        Resultado esperado: saldo_capital=900, saldo_intereses sin cambio (cuota_fija
        recalcula igual porque la fórmula no depende de saldo_capital).
        """
        credito = make_credito(
            tipo=TipoCredito.cuota_fija,
            saldo_capital=Decimal("1000.00"),
            saldo_intereses=Decimal("50.00"),
            numero_cuotas=12,
            tasa=Decimal("0.0300"),
        )

        call_count = 0
        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar.return_value = 3  # max_cuota = 3
            elif call_count == 2:
                # recalcular_saldo_intereses cuota_fija consulta historico
                result.scalar.return_value = Decimal("30.00")
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock(spec=AsyncSession)
        db.execute = mock_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        await PagoService.registrar_pago_no_programado(
            db=db,
            credito=credito,
            monto=Decimal("100.00"),
            destino=DestinoExcedente.capital,
            fecha_pago=date(2026, 6, 1),
            receptor_id=None,
        )

        assert credito.saldo_capital == Decimal("900.00"), (
            f"saldo_capital={credito.saldo_capital}, esperado 900.00"
        )

    @pytest.mark.asyncio
    async def test_abono_capital_reduce_y_recarga_interes(self):
        """
        abono_capital mensual: pago no programado de 500 a capital sobre saldo_capital=2000.
        Resultado esperado: saldo_capital=1500, saldo_intereses=1500*0.03=45.
        La reducción ocurre una sola vez vía _aplicar_reduccion_saldos.
        """
        credito = make_credito_abono(
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            tasa=Decimal("0.0300"),
        )

        call_count = 0
        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar.return_value = 5  # max_cuota = 5
            else:
                # recalcular_cuota_actual_si_no_pagada → sin cuota pendiente
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock(spec=AsyncSession)
        db.execute = mock_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        await PagoService.registrar_pago_no_programado(
            db=db,
            credito=credito,
            monto=Decimal("500.00"),
            destino=DestinoExcedente.capital,
            fecha_pago=date(2026, 6, 1),
            receptor_id=None,
        )

        assert credito.saldo_capital == Decimal("1500.00"), (
            f"saldo_capital={credito.saldo_capital}, esperado 1500.00"
        )
        assert credito.saldo_intereses == Decimal("0.00"), (
            f"saldo_intereses={credito.saldo_intereses}, esperado 0.00 "
            "(abono_capital no lleva saldo de intereses acumulado)"
        )

    @pytest.mark.asyncio
    async def test_pago_a_intereses_no_toca_capital(self):
        """
        Pago no programado destinado a intereses: saldo_capital no debe cambiar,
        saldo_intereses se reduce por el monto pagado.
        """
        credito = make_credito_abono(
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            tasa=Decimal("0.0300"),
        )

        call_count = 0
        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar.return_value = 2  # max_cuota = 2
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock(spec=AsyncSession)
        db.execute = mock_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        await PagoService.registrar_pago_no_programado(
            db=db,
            credito=credito,
            monto=Decimal("60.00"),
            destino=DestinoExcedente.intereses,
            fecha_pago=date(2026, 6, 1),
            receptor_id=None,
        )

        # Capital no debe haber cambiado
        assert credito.saldo_capital == Decimal("2000.00"), (
            f"saldo_capital={credito.saldo_capital}, esperado 2000.00 (no debe bajar)"
        )
        # Intereses deben llegar a 0 (60 - 60 = 0) y luego recalcular_saldo_intereses
        # los recarga: 2000 * 0.03 = 60
        assert credito.saldo_intereses == Decimal("0.00"), (
            f"saldo_intereses={credito.saldo_intereses}, esperado 0.00 "
            "(abono_capital no lleva saldo de intereses; el interés se cobra por cuota)"
        )
