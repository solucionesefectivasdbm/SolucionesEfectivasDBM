"""
tests/test_models.py — Tests for ORM model fields.

RED phase: these tests verify the Credito model exposes anchor_dia_1 and
anchor_dia_2 as nullable integer attributes. They fail before A2 is applied.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.gestor import Gestor
from app.models.pago import Pago, TipoCuota
from app.models.receptor import Receptor
from app.models.receptor_movimiento import MovimientoReceptor, TipoMovimiento
from app.models.usuario import TipoUsuario, Usuario


def _make_credito(**kwargs) -> Credito:
    """Minimal Credito instance for ORM-level attribute checks (no DB)."""
    defaults = dict(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente="TEST-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 20),
        periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("1000000.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=12,
        calcular_interes_dias_corridos=False,
        activo=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kwargs)
    return Credito(**defaults)


class TestCreditoAnchorColumns:
    """REQ-1.1: Credito model exposes anchor_dia_1 and anchor_dia_2."""

    def test_mensual_anchor_dia_1_equals_fecha_day(self):
        """Scenario 1.1.a: mensual with fecha_inicial_pago day 20 → anchor_dia_1 == 20, anchor_dia_2 is None."""
        credito = _make_credito(
            periodicidad=Periodicidad.mensual,
            fecha_inicial_pago=date(2026, 1, 20),
            anchor_dia_1=20,
            anchor_dia_2=None,
        )
        assert credito.anchor_dia_1 == 20
        assert credito.anchor_dia_2 is None

    def test_quincenal_anchor_both_set(self):
        """Scenario 1.1.b: quincenal with anchor days 15 and 30."""
        credito = _make_credito(
            periodicidad=Periodicidad.quincenal,
            anchor_dia_1=15,
            anchor_dia_2=30,
        )
        assert credito.anchor_dia_1 == 15
        assert credito.anchor_dia_2 == 30

    def test_semanal_anchor_both_null(self):
        """Scenario 1.1.c: semanal leaves both anchors NULL."""
        credito = _make_credito(
            periodicidad=Periodicidad.semanal,
            numero_cuotas=None,
            anchor_dia_1=None,
            anchor_dia_2=None,
        )
        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None

    def test_diario_anchor_both_null(self):
        """Scenario 1.1.d: diario leaves both anchors NULL."""
        credito = _make_credito(
            periodicidad=Periodicidad.diario,
            numero_cuotas=None,
            anchor_dia_1=None,
            anchor_dia_2=None,
        )
        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None

    def test_model_has_anchor_dia_1_attribute(self):
        """Credito model exposes anchor_dia_1 as an attribute (hasattr check)."""
        credito = _make_credito(anchor_dia_1=None, anchor_dia_2=None)
        assert hasattr(credito, "anchor_dia_1")

    def test_model_has_anchor_dia_2_attribute(self):
        """Credito model exposes anchor_dia_2 as an attribute (hasattr check)."""
        credito = _make_credito(anchor_dia_1=None, anchor_dia_2=None)
        assert hasattr(credito, "anchor_dia_2")


class TestReceptorIdDroppedFromGestorAndPago:
    """PR4 (receiver-bank-account-assignment, decision 7/task 18.2): the
    deprecated `receptor_id` mapped columns are removed from Gestor/Pago,
    and Receptor keeps no `gestores`/`pagos` relationships. Fails while the
    deprecated columns still exist (RED before 18.1/18.2)."""

    def test_gestor_has_no_receptor_id_column(self):
        columnas = {c.key for c in inspect(Gestor).columns}
        assert "receptor_id" not in columnas

    def test_pago_has_no_receptor_id_column(self):
        columnas = {c.key for c in inspect(Pago).columns}
        assert "receptor_id" not in columnas

    def test_receptor_has_no_gestores_relationship(self):
        relaciones = {r.key for r in inspect(Receptor).relationships}
        assert "gestores" not in relaciones

    def test_receptor_has_no_pagos_relationship(self):
        relaciones = {r.key for r in inspect(Receptor).relationships}
        assert "pagos" not in relaciones


def _mk_pago_minimo(**kwargs) -> Pago:
    """Pago mínimo para pruebas a nivel de mapper. No requiere un Credito
    real: SQLite en tests no aplica FOREIGN KEY (igual que TestMovimientoReceptor
    más abajo)."""
    defaults = dict(
        id=uuid.uuid4(), credito_id=uuid.uuid4(), numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("110000.00"),
        capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("10000.00"),
        capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
        momento="m1", fecha_maxima=date(2026, 10, 5), pagado=False,
        validado_recaudador=False,
    )
    defaults.update(kwargs)
    return Pago(**defaults)


class TestPagoFechaMaximaOriginal:
    """Fase 1 (atraso-pago-aplazado-corte-original): `Pago.fecha_maxima_original`
    se fija una sola vez al crear el pago, vía un listener `before_insert`
    (design.md decisión D3). Falla mientras el modelo no tenga la columna."""

    @pytest.mark.asyncio
    async def test_creacion_fija_fecha_maxima_original_igual_a_fecha_maxima(self, db_session):
        """Spec 'Creación de pago fija el corte original': al insertar,
        fecha_maxima_original queda igual a fecha_maxima."""
        pago = _mk_pago_minimo(fecha_maxima=date(2026, 10, 5))
        db_session.add(pago)
        await db_session.flush()
        assert pago.fecha_maxima_original == date(2026, 10, 5)

    @pytest.mark.asyncio
    async def test_no_sobrescribe_fecha_maxima_original_si_ya_viene_fijada(self, db_session):
        """Design D3: el listener solo copia fecha_maxima cuando la columna
        nueva es None — un valor explícito (p.ej. una fila reconstruida por
        el backfill del PR4) no debe ser pisado en el insert."""
        pago = _mk_pago_minimo(
            fecha_maxima=date(2026, 10, 5),
            fecha_maxima_original=date(2026, 9, 1),
        )
        db_session.add(pago)
        await db_session.flush()
        assert pago.fecha_maxima_original == date(2026, 9, 1)


def _mk_usuario(**kwargs) -> Usuario:
    defaults = dict(
        id=uuid.uuid4(), username=f"user{uuid.uuid4().hex[:8]}", password_hash="x",
        telefono="3000000000", tipo_usuario=TipoUsuario.admin,
    )
    defaults.update(kwargs)
    return Usuario(**defaults)


def _mk_movimiento(cuenta_bancaria_id, usuario_id, **kwargs) -> MovimientoReceptor:
    defaults = dict(
        id=uuid.uuid4(), cuenta_bancaria_id=cuenta_bancaria_id, usuario_id=usuario_id,
        tipo=TipoMovimiento.salida, monto=Decimal("100.00"), nota=None,
    )
    defaults.update(kwargs)
    return MovimientoReceptor(**defaults)


class TestMovimientoReceptor:
    """item 9 (receiver-cash-balance): `MovimientoReceptor` is the
    append-only ledger row (`salida`/`correccion`). No AuditMixin —
    immutable, mirrors AuditLog: no deleted_at, no updated_at. The CHECK
    constraint enforces sign-by-tipo at the DB level. SQLite DOES enforce
    CHECK constraints (unlike FOR UPDATE, which it silently ignores), so
    this is a real behavioral test, not a structural one.
    """

    def test_model_exposes_expected_fields(self):
        cuenta_id, usuario_id = uuid.uuid4(), uuid.uuid4()
        m = _mk_movimiento(
            cuenta_id, usuario_id, tipo=TipoMovimiento.correccion,
            monto=Decimal("-15.00"), nota="ajuste conteo físico",
        )
        assert m.cuenta_bancaria_id == cuenta_id
        assert m.tipo == TipoMovimiento.correccion
        assert m.monto == Decimal("-15.00")
        assert m.nota == "ajuste conteo físico"
        assert m.usuario_id == usuario_id

    def test_model_has_no_audit_mixin_fields(self):
        """Immutable ledger row: no soft-delete, no update tracking."""
        columnas = {c.key for c in inspect(MovimientoReceptor).columns}
        assert "deleted_at" not in columnas
        assert "updated_at" not in columnas

    @pytest.mark.asyncio
    async def test_salida_monto_positivo_persiste(self, db_session):
        m = _mk_movimiento(uuid.uuid4(), uuid.uuid4(), tipo=TipoMovimiento.salida, monto=Decimal("50.00"))
        db_session.add(m)
        await db_session.flush()
        assert m.created_at is not None

    @pytest.mark.asyncio
    async def test_check_constraint_rechaza_salida_monto_cero(self, db_session):
        m = _mk_movimiento(uuid.uuid4(), uuid.uuid4(), tipo=TipoMovimiento.salida, monto=Decimal("0.00"))
        db_session.add(m)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_check_constraint_rechaza_salida_monto_negativo(self, db_session):
        m = _mk_movimiento(uuid.uuid4(), uuid.uuid4(), tipo=TipoMovimiento.salida, monto=Decimal("-10.00"))
        db_session.add(m)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_check_constraint_rechaza_correccion_monto_cero(self, db_session):
        m = _mk_movimiento(uuid.uuid4(), uuid.uuid4(), tipo=TipoMovimiento.correccion, monto=Decimal("0.00"))
        db_session.add(m)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_check_constraint_acepta_correccion_negativa(self, db_session):
        m = _mk_movimiento(uuid.uuid4(), uuid.uuid4(), tipo=TipoMovimiento.correccion, monto=Decimal("-25.00"))
        db_session.add(m)
        await db_session.flush()
        assert m.monto == Decimal("-25.00")


class TestUsuarioMovimientosReceptorBackref:
    """design.md: `Usuario` gets `movimientos_receptor` (mirrors `audit_logs`)."""

    @pytest.mark.asyncio
    async def test_usuario_expone_movimientos_receptor(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        await db_session.flush()

        movimiento = _mk_movimiento(uuid.uuid4(), usuario.id, tipo=TipoMovimiento.salida, monto=Decimal("30.00"))
        db_session.add(movimiento)
        await db_session.flush()

        await db_session.refresh(usuario, ["movimientos_receptor"])
        assert movimiento in usuario.movimientos_receptor
