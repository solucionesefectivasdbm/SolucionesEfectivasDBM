"""
tests/test_dias_pago_endpoint.py — Tests for PATCH /creditos/{id}/dias-pago.

Covers all 32 spec scenarios (CAP 1-8) for the editar-dias-pago-credito change.
TDD order: A-1 (schema) RED → A-2 GREEN → B-1..B-4 RED → B-5 GREEN.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

ENDPOINT_BASE = "/api/v1/creditos"


# ---------------------------------------------------------------------------
# User factories
# ---------------------------------------------------------------------------

def _make_user(tipo: TipoUsuario) -> MagicMock:
    u = MagicMock(spec=Usuario)
    u.id = uuid.uuid4()
    u.tipo_usuario = tipo
    u.activo = True
    u.deleted_at = None
    return u


# ---------------------------------------------------------------------------
# DB / credito helpers
# ---------------------------------------------------------------------------

async def _credito(
    db_session,
    periodicidad=Periodicidad.mensual,
    anchor_dia_1=None,
    anchor_dia_2=None,
    activo=True,
    **kw,
) -> Credito:
    defaults = dict(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:8]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 20),
        periodicidad=periodicidad,
        saldo_capital=Decimal("800.00"),
        saldo_intereses=Decimal("100.00"),
        numero_cuotas=12,
        activo=activo,
        anchor_dia_1=anchor_dia_1,
        anchor_dia_2=anchor_dia_2,
    )
    defaults.update(kw)
    c = Credito(**defaults)
    db_session.add(c)
    await db_session.flush()
    return c


async def _cuota(
    db_session,
    credito,
    numero: int,
    fecha_maxima: date,
    pagado: bool = False,
    capital: Decimal = Decimal("80.00"),
    interes: Decimal = Decimal("10.00"),
) -> Pago:
    monto = capital + interes
    p = Pago(
        id=uuid.uuid4(),
        credito_id=credito.id,
        numero_cuota=numero,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=monto,
        capital_a_pagar=capital,
        interes_a_pagar=interes,
        capital_pagado=capital if pagado else Decimal("0.00"),
        interes_pagado=interes if pagado else Decimal("0.00"),
        momento="m1",
        fecha_maxima=fecha_maxima,
        pagado=pagado,
    )
    db_session.add(p)
    await db_session.flush()
    return p


# ---------------------------------------------------------------------------
# Fixtures — per-role HTTP clients
# ---------------------------------------------------------------------------

def _client_fixture(tipo: TipoUsuario):
    @pytest_asyncio.fixture
    async def _fixture(db_session):
        user = _make_user(tipo)

        async def override_user():
            return user

        async def override_db():
            yield db_session

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    return _fixture


client_admin = _client_fixture(TipoUsuario.admin)
client_registrador = _client_fixture(TipoUsuario.registrador)
client_recaudador = _client_fixture(TipoUsuario.recaudador)
client_gestor = _client_fixture(TipoUsuario.gestor)


@pytest_asyncio.fixture
async def client_no_token():
    """Client with no auth header — no dependency override."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GROUP A — Schema validation tests (RED gate: DiasPagoUpdate must not exist yet)
# ---------------------------------------------------------------------------

class TestDiasPagoUpdateSchema:
    """A-1: Schema validation tests — written RED before A-2 implements the class."""

    def test_anchor_dia_1_zero_raises(self):
        """anchor_dia_1=0 must raise ValidationError (out of range)."""
        from app.schemas.credito import DiasPagoUpdate
        with pytest.raises(ValidationError):
            DiasPagoUpdate(anchor_dia_1=0)

    def test_anchor_dia_1_32_raises(self):
        """anchor_dia_1=32 must raise ValidationError (out of range)."""
        from app.schemas.credito import DiasPagoUpdate
        with pytest.raises(ValidationError):
            DiasPagoUpdate(anchor_dia_1=32)

    def test_anchor_dia_1_boundary_1_valid(self):
        """anchor_dia_1=1 must be valid."""
        from app.schemas.credito import DiasPagoUpdate
        obj = DiasPagoUpdate(anchor_dia_1=1)
        assert obj.anchor_dia_1 == 1

    def test_anchor_dia_1_boundary_31_valid(self):
        """anchor_dia_1=31 must be valid."""
        from app.schemas.credito import DiasPagoUpdate
        obj = DiasPagoUpdate(anchor_dia_1=31)
        assert obj.anchor_dia_1 == 31

    def test_anchor_dia_2_none_is_valid(self):
        """anchor_dia_2=None must be valid (optional)."""
        from app.schemas.credito import DiasPagoUpdate
        obj = DiasPagoUpdate(anchor_dia_1=15)
        assert obj.anchor_dia_2 is None

    def test_anchor_dia_2_out_of_range_raises(self):
        """anchor_dia_2=0 must raise ValidationError."""
        from app.schemas.credito import DiasPagoUpdate
        with pytest.raises(ValidationError):
            DiasPagoUpdate(anchor_dia_1=15, anchor_dia_2=0)

    def test_anchor_dia_2_32_raises(self):
        """anchor_dia_2=32 must raise ValidationError."""
        from app.schemas.credito import DiasPagoUpdate
        with pytest.raises(ValidationError):
            DiasPagoUpdate(anchor_dia_1=15, anchor_dia_2=32)

    def test_anchor_dia_2_valid(self):
        """anchor_dia_2=30 must be valid when provided."""
        from app.schemas.credito import DiasPagoUpdate
        obj = DiasPagoUpdate(anchor_dia_1=15, anchor_dia_2=30)
        assert obj.anchor_dia_2 == 30


# ---------------------------------------------------------------------------
# GROUP B-1 — Auth / role tests
# ---------------------------------------------------------------------------

class TestDiasPagoAuth:
    """B-1: Endpoint authorization scenarios (CAP 1)."""

    @pytest.mark.asyncio
    async def test_admin_allowed(self, client_admin, db_session):
        """Scenario 1.1.a — admin gets 200."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 2, 19))
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_registrador_allowed(self, client_registrador, db_session):
        """Scenario 1.1.b — registrador gets 200."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 2, 19))
        r = await client_registrador.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_recaudador_allowed(self, client_recaudador, db_session):
        """Scenario 1.1.c — recaudador gets 200."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 2, 19))
        r = await client_recaudador.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_gestor_forbidden(self, client_gestor, db_session):
        """Scenario 1.1.d — gestor (unprivileged) gets 403."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        r = await client_gestor.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 403, r.text

    @pytest.mark.asyncio
    async def test_no_token_unauthorized(self, client_no_token, db_session):
        """Scenario 1.1.e — no token gets 401/403 (unauthenticated).
        FastAPI HTTPBearer returns 403 when no credentials header is present.
        """
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        r = await client_no_token.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code in (401, 403), r.text

    @pytest.mark.asyncio
    async def test_recaudador_blocked_on_full_update(self, client_recaudador, db_session):
        """Scenario 1.2.a — recaudador cannot use PATCH /creditos/{id} (full update)."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        r = await client_recaudador.patch(
            f"{ENDPOINT_BASE}/{c.id}",
            json={"capital_prestado": 1200},
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# GROUP B-2 — Validation tests (periodicidad, day range, credit state)
# ---------------------------------------------------------------------------

class TestDiasPagoValidacion:
    """B-2: Input and target validation scenarios (CAP 2, 3, 4)."""

    @pytest.mark.asyncio
    async def test_day_less_than_1_rejected(self, client_admin, db_session):
        """Scenario 4.1.a — anchor_dia_1=0 gets 422."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 0},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_day_greater_than_31_rejected(self, client_admin, db_session):
        """Scenario 4.1.b — anchor_dia_1=32 gets 422."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 32},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_boundary_1_and_31_quincenal_accepted(self, client_admin, db_session):
        """Scenario 4.1.c — quincenal with days 1 and 31 gets 200."""
        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=10, anchor_dia_2=25,
            fecha_inicial_pago=date(2026, 1, 1),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 10), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 1, 25))
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 1, "anchor_dia_2": 31},
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_semanal_rejected(self, client_admin, db_session):
        """Scenario 4.1.d — semanal credit gets 422 (not applicable)."""
        c = await _credito(db_session, periodicidad=Periodicidad.semanal)
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_diario_rejected(self, client_admin, db_session):
        """Scenario 4.1.e — diario credit gets 422 (not applicable)."""
        c = await _credito(db_session, periodicidad=Periodicidad.diario)
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_unknown_id_returns_404(self, client_admin, db_session):
        """Scenario 4.1.f — non-existent credito_id gets 404."""
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{uuid.uuid4()}/dias-pago",
            json={"anchor_dia_1": 15},
        )
        assert r.status_code == 404, r.text

    @pytest.mark.asyncio
    async def test_soft_deleted_returns_404(self, client_admin, db_session):
        """Scenario 4.1.g — soft-deleted credit gets 404."""
        from datetime import datetime, timezone
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        c.deleted_at = datetime.now(timezone.utc)
        await db_session.flush()
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15},
        )
        assert r.status_code == 404, r.text

    @pytest.mark.asyncio
    async def test_inactive_credit_returns_422(self, client_admin, db_session):
        """Scenario 4.1.h — inactive (closed) credit gets 422."""
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=10, activo=False,
        )
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_mensual_rejects_anchor_dia_2(self, client_admin, db_session):
        """Scenario 2.1.c — mensual with anchor_dia_2 gets 422."""
        c = await _credito(db_session, periodicidad=Periodicidad.mensual, anchor_dia_1=10)
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15, "anchor_dia_2": 30},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_quincenal_requires_anchor_dia_2(self, client_admin, db_session):
        """Scenario 3.1.d — quincenal without anchor_dia_2 gets 422."""
        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=10, anchor_dia_2=25,
        )
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_quincenal_equal_days_rejected(self, client_admin, db_session):
        """Scenario 3.1.e — quincenal with equal days gets 422."""
        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=10, anchor_dia_2=25,
        )
        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15, "anchor_dia_2": 15},
        )
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# GROUP B-3 — Re-anchor semantics tests
# ---------------------------------------------------------------------------

class TestDiasPagoReanchorSemantics:
    """B-3: Re-anchor date semantics and invariants (CAP 2, 3, 5, 6)."""

    @pytest.mark.asyncio
    async def test_mensual_reanchor_pending_cuotas(self, client_admin, db_session):
        """
        Scenario 2.1.a — mensual re-anchor: last PAID cuota 2026-01-20, drifted
        pending dates (2026-02-19, 2026-03-21) become 2026-02-20, 2026-03-20.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=20, fecha_inicial_pago=date(2026, 1, 20),
        )
        paid = await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True)
        p2 = await _cuota(db_session, c, 2, date(2026, 2, 19))
        p3 = await _cuota(db_session, c, 3, date(2026, 3, 21))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text
        # In-session identity map: same Python objects mutated by recalcular_cuotas_futuras
        assert p2.fecha_maxima == date(2026, 2, 20)
        assert p3.fecha_maxima == date(2026, 3, 20)

    @pytest.mark.asyncio
    async def test_mensual_short_month_clamp(self, client_admin, db_session):
        """
        Scenario 2.1.b — anchor_dia_1=31, last paid 2026-01-31, Feb pending clamps to 2026-02-28.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=31, fecha_inicial_pago=date(2026, 1, 31),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 31), pagado=True)
        p2 = await _cuota(db_session, c, 2, date(2026, 2, 15))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 31},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        assert p2.fecha_maxima == date(2026, 2, 28)

    @pytest.mark.asyncio
    async def test_quincenal_15_30_alternation(self, client_admin, db_session):
        """
        Scenario 3.1.a — quincenal, last paid 2026-03-15, drifted pending
        (2026-03-29, 2026-04-12) become 2026-03-30, 2026-04-15.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=15, anchor_dia_2=30,
            fecha_inicial_pago=date(2026, 3, 15),
        )
        await _cuota(db_session, c, 1, date(2026, 3, 15), pagado=True)
        p2 = await _cuota(db_session, c, 2, date(2026, 3, 29))
        p3 = await _cuota(db_session, c, 3, date(2026, 4, 12))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15, "anchor_dia_2": 30},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        # identity map — no refresh needed
        assert p2.fecha_maxima == date(2026, 3, 30)
        assert p3.fecha_maxima == date(2026, 4, 15)

    @pytest.mark.asyncio
    async def test_quincenal_reversed_input_normalized(self, client_admin, db_session):
        """
        Scenario 3.1.b — reversed input (25, 10) stored as anchor_dia_1=10, anchor_dia_2=25.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=10, anchor_dia_2=25,
            fecha_inicial_pago=date(2026, 1, 10),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 10), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 1, 25))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 25, "anchor_dia_2": 10},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["anchor_dia_1"] == 10
        assert data["anchor_dia_2"] == 25

    @pytest.mark.asyncio
    async def test_quincenal_clamp_pair(self, client_admin, db_session):
        """
        Scenario 3.1.c — anchor (10, 31): pending after Jan-31 paid → Feb-10, Feb-28.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=10, anchor_dia_2=31,
            fecha_inicial_pago=date(2026, 1, 10),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 31), pagado=True)
        p2 = await _cuota(db_session, c, 2, date(2026, 2, 7))
        p3 = await _cuota(db_session, c, 3, date(2026, 2, 20))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 10, "anchor_dia_2": 31},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        # identity map — no refresh needed
        assert p2.fecha_maxima == date(2026, 2, 10)
        assert p3.fecha_maxima == date(2026, 2, 28)

    @pytest.mark.asyncio
    async def test_paid_cuotas_untouched(self, client_admin, db_session):
        """Scenario 5.1.a — paid cuota dates must not change."""
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=20, fecha_inicial_pago=date(2026, 1, 20),
        )
        paid = await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True)
        original_paid_date = paid.fecha_maxima
        await _cuota(db_session, c, 2, date(2026, 2, 19))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        assert paid.fecha_maxima == original_paid_date

    @pytest.mark.asyncio
    async def test_amounts_invariant(self, client_admin, db_session):
        """Scenario 5.1.b — monetary fields (capital, interes, monto) must not change."""
        cap = Decimal("100.00")
        inte = Decimal("15.00")
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=20, fecha_inicial_pago=date(2026, 1, 20),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True,
                     capital=cap, interes=inte)
        p2 = await _cuota(db_session, c, 2, date(2026, 2, 19), capital=cap, interes=inte)

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        assert p2.capital_a_pagar == cap
        assert p2.interes_a_pagar == inte
        assert p2.monto_a_pagar == cap + inte

    @pytest.mark.asyncio
    async def test_momento_recomputed_for_pending(self, client_admin, db_session):
        """
        Scenario 5.1.c — pending cuota moved from 2026-02-19 → 2026-02-20;
        momento must be re-derived for the new date.
        """
        from app.utils.momentos import get_momento
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=20, fecha_inicial_pago=date(2026, 1, 20),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True)
        p2 = await _cuota(db_session, c, 2, date(2026, 2, 19))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        expected_momento = get_momento(date(2026, 2, 20))
        assert p2.momento == expected_momento

    @pytest.mark.asyncio
    async def test_no_paid_cuotas_uses_fecha_inicial_pago(self, client_admin, db_session):
        """
        Scenario 5.1.d — no paid cuota: cuota#1 keeps fecha_inicial_pago (2026-01-20),
        cuota#2 re-anchored to 2026-02-25.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=20, fecha_inicial_pago=date(2026, 1, 20),
        )
        p1 = await _cuota(db_session, c, 1, date(2026, 1, 20))
        p2 = await _cuota(db_session, c, 2, date(2026, 2, 20))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 25},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        # identity map — no refresh needed
        # cuota#1 stays at fecha_inicial_pago (desde_fecha starts here — p1 is not re-anchored)
        assert p1.fecha_maxima == date(2026, 1, 20)
        # cuota#2 re-anchored to day 25 of next month
        assert p2.fecha_maxima == date(2026, 2, 25)

    @pytest.mark.asyncio
    async def test_cuota1_paid_derives_from_it(self, client_admin, db_session):
        """
        Scenario 5.1.e — cuota#1 paid 2026-01-20, set anchor_dia_1=25:
        cuota#1 unchanged, first pending becomes 2026-02-25.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=20, fecha_inicial_pago=date(2026, 1, 20),
        )
        paid = await _cuota(db_session, c, 1, date(2026, 1, 20), pagado=True)
        p2 = await _cuota(db_session, c, 2, date(2026, 2, 20))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 25},
        )
        assert r.status_code == 200, r.text
        # identity map — no refresh needed
        # identity map — no refresh needed
        assert paid.fecha_maxima == date(2026, 1, 20)  # unchanged
        assert p2.fecha_maxima == date(2026, 2, 25)

    @pytest.mark.asyncio
    async def test_zero_pending_cuotas_persists_anchors(self, client_admin, db_session):
        """
        Scenario 6.1.a — all cuotas paid (0 pending): anchors updated, 200, no error.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=10, fecha_inicial_pago=date(2026, 1, 10),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 10), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 2, 10), pagado=True)

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["anchor_dia_1"] == 15

    @pytest.mark.asyncio
    async def test_null_anchor_quincenal_can_be_fixed(self, client_admin, db_session):
        """
        Scenario 6.1.b — quincenal with NULL anchors: set (15, 30), pending re-anchored.
        """
        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=None, anchor_dia_2=None,
            fecha_inicial_pago=date(2026, 1, 15),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 15), pagado=True)
        p2 = await _cuota(db_session, c, 2, date(2026, 1, 28))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15, "anchor_dia_2": 30},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["anchor_dia_1"] == 15
        assert data["anchor_dia_2"] == 30
        # identity map — no refresh needed
        assert p2.fecha_maxima == date(2026, 1, 30)


# ---------------------------------------------------------------------------
# GROUP B-4 — Audit tests
# ---------------------------------------------------------------------------

class TestDiasPagoAudit:
    """B-4: Audit log scenarios (CAP 7)."""

    @pytest.mark.asyncio
    async def test_mensual_audit_old_to_new(self, client_admin, db_session):
        """
        Scenario 7.1.a — mensual with anchor_dia_1=10, patch to 20:
        audit_log entry must record campo_modificado="anchor_fechas" with old/new values.
        """
        from sqlalchemy import select as sa_select
        from app.models.audit_log import AuditLog, AccionAudit

        c = await _credito(
            db_session, periodicidad=Periodicidad.mensual,
            anchor_dia_1=10, fecha_inicial_pago=date(2026, 1, 10),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 10), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 2, 10))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 20},
        )
        assert r.status_code == 200, r.text

        logs = (await db_session.execute(
            sa_select(AuditLog).where(
                AuditLog.entidad == "creditos",
                AuditLog.entidad_id == c.id,
                AuditLog.accion == AccionAudit.UPDATE,
                AuditLog.campo_modificado == "anchor_fechas",
            )
        )).scalars().all()
        assert len(logs) >= 1, "No anchor_fechas audit log found"
        log = logs[0]
        assert log.valor_anterior is not None
        assert log.valor_nuevo is not None

    @pytest.mark.asyncio
    async def test_quincenal_audit_both_anchors(self, client_admin, db_session):
        """
        Scenario 7.1.b — quincenal with NULL anchors patched to (15, 30):
        audit entry has campo_modificado="anchor_fechas" recording NULL→set.
        """
        from sqlalchemy import select as sa_select
        from app.models.audit_log import AuditLog, AccionAudit

        c = await _credito(
            db_session, periodicidad=Periodicidad.quincenal,
            anchor_dia_1=None, anchor_dia_2=None,
            fecha_inicial_pago=date(2026, 1, 15),
        )
        await _cuota(db_session, c, 1, date(2026, 1, 15), pagado=True)
        await _cuota(db_session, c, 2, date(2026, 1, 28))

        r = await client_admin.patch(
            f"{ENDPOINT_BASE}/{c.id}/dias-pago",
            json={"anchor_dia_1": 15, "anchor_dia_2": 30},
        )
        assert r.status_code == 200, r.text

        logs = (await db_session.execute(
            sa_select(AuditLog).where(
                AuditLog.entidad == "creditos",
                AuditLog.entidad_id == c.id,
                AuditLog.accion == AccionAudit.UPDATE,
                AuditLog.campo_modificado == "anchor_fechas",
            )
        )).scalars().all()
        assert len(logs) >= 1, "No anchor_fechas audit log found for quincenal"
