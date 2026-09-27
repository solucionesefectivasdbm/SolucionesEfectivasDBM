"""
tests/test_fecha_original_backfill.py — Unit tests puros para
`resolver_fecha_original` (atraso-pago-aplazado-corte-original, Fase 4,
design.md "Backfill Algorithm").

RED: `app/services/fecha_original_backfill.py` todavía no existe.
"""
from datetime import date, datetime

from app.services.fecha_original_backfill import resolver_fecha_original


class TestResolverFechaOriginal:
    def test_gana_la_fila_de_auditoria_mas_antigua(self):
        """Varias filas de audit_log para el mismo pago: se usa el
        valor_anterior de la más antigua cronológicamente (motivo=auditoria)."""
        eventos = [
            (datetime(2026, 3, 1, 10, 0), "2026-02-10"),
            (datetime(2026, 3, 15, 9, 0), "2026-02-25"),
        ]

        fecha, motivo = resolver_fecha_original(
            fecha_actual=date(2026, 4, 1),
            fecha_pago_real=None,
            eventos=eventos,
            ultimo_reanclaje=None,
        )

        assert fecha == date(2026, 2, 10)
        assert motivo == "auditoria"

    def test_sin_filas_usa_fallback_a_fecha_maxima_actual(self):
        """Sin ninguna fila de audit_log para el pago: fallback a fecha_maxima
        vigente (motivo=sin_auditoria)."""
        fecha, motivo = resolver_fecha_original(
            fecha_actual=date(2026, 4, 1),
            fecha_pago_real=None,
            eventos=[],
            ultimo_reanclaje=None,
        )

        assert fecha == date(2026, 4, 1)
        assert motivo == "sin_auditoria"

    def test_valor_no_parseable_usa_fallback(self):
        """valor_anterior no parseable con date.fromisoformat: fallback
        (motivo=valor_invalido)."""
        eventos = [(datetime(2026, 3, 1, 10, 0), "no-es-una-fecha")]

        fecha, motivo = resolver_fecha_original(
            fecha_actual=date(2026, 4, 1),
            fecha_pago_real=None,
            eventos=eventos,
            ultimo_reanclaje=None,
        )

        assert fecha == date(2026, 4, 1)
        assert motivo == "valor_invalido"

    def test_valor_anterior_none_usa_fallback(self):
        """valor_anterior ausente (None) en la fila de audit_log: mismo
        fallback que un valor no parseable (motivo=valor_invalido)."""
        eventos = [(datetime(2026, 3, 1, 10, 0), None)]

        fecha, motivo = resolver_fecha_original(
            fecha_actual=date(2026, 4, 1),
            fecha_pago_real=None,
            eventos=eventos,
            ultimo_reanclaje=None,
        )

        assert fecha == date(2026, 4, 1)
        assert motivo == "valor_invalido"

    def test_eventos_previos_al_reanclaje_se_ignoran(self):
        """Un re-anclaje del crédito (recalcular_cuotas_futuras) ya reseteó
        fecha_maxima_original para este pago (no pagado) — los eventos de
        aplazamiento anteriores al re-anclaje ya no cuentan (motivo=reanclado)."""
        eventos = [(datetime(2026, 1, 5, 8, 0), "2026-01-01")]
        ultimo_reanclaje = datetime(2026, 2, 1, 0, 0)

        fecha, motivo = resolver_fecha_original(
            fecha_actual=date(2026, 4, 1),
            fecha_pago_real=None,
            eventos=eventos,
            ultimo_reanclaje=ultimo_reanclaje,
        )

        assert fecha == date(2026, 4, 1)
        assert motivo == "reanclado"

    def test_pago_pagado_antes_del_reanclaje_conserva_el_valor_de_auditoria(self):
        """Excepción a la regla anterior: si el pago ya estaba pagado ANTES
        del re-anclaje, recalcular_cuotas_futuras nunca lo tocó (su query
        filtra pagado == False), así que sus eventos previos siguen siendo
        la historia real y no se descartan."""
        eventos = [(datetime(2026, 1, 5, 8, 0), "2026-01-01")]
        ultimo_reanclaje = datetime(2026, 2, 1, 0, 0)

        fecha, motivo = resolver_fecha_original(
            fecha_actual=date(2026, 4, 1),
            fecha_pago_real=date(2026, 1, 20),  # pagado antes del re-anclaje
            eventos=eventos,
            ultimo_reanclaje=ultimo_reanclaje,
        )

        assert fecha == date(2026, 1, 1)
        assert motivo == "auditoria"

    def test_evento_posterior_o_igual_al_reanclaje_si_se_usa(self):
        """Triangulación del límite (>=): un evento posterior al re-anclaje
        sobrevive el filtro y se usa con normalidad; uno anterior se descarta."""
        eventos = [
            (datetime(2026, 1, 5, 8, 0), "2026-01-01"),  # descartado (previo)
            (datetime(2026, 2, 10, 8, 0), "2026-02-05"),  # conservado (posterior)
        ]
        ultimo_reanclaje = datetime(2026, 2, 1, 0, 0)

        fecha, motivo = resolver_fecha_original(
            fecha_actual=date(2026, 4, 1),
            fecha_pago_real=None,
            eventos=eventos,
            ultimo_reanclaje=ultimo_reanclaje,
        )

        assert fecha == date(2026, 2, 5)
        assert motivo == "auditoria"
