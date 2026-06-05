"""
tests/test_anclar_fechas.py — Tests funcionales para POST /admin/migracion/anclar-fechas.

Cubre CAP-5 (backfill) + CAP-8 (idempotency):
  - Mensual: deriva anchor_dia_1 = fecha_inicial_pago.day; recalcula cuotas pendientes.
  - Quincenal: deriva anchor pair desde los 2 primeros días distintos de Pago.fecha_maxima.
  - Quincenal <2 días distintos → flagged as requiere_revision_manual, no guess, no recalc.
  - Amounts/saldos unchanged (capital, intereses, monto invariant).
  - Idempotency: run twice → second run skips all (all counts reflect skipped), state identical.
  - semanal/diario → untouched (anchors remain NULL).
  - Admin auth required: non-admin gets 403.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

ENDPOINT = "/api/v1/admin/migracion/anclar-fechas"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin() -> Usuario:
    u = MagicMock(spec=Usuario)
    u.id = uuid.uuid4()
    u.tipo_usuario = TipoUsuario.admin
    u.activo = True
    u.deleted_at = None
    return u


def _make_recaudador() -> Usuario:
    u = MagicMock(spec=Usuario)
    u.id = uuid.uuid4()
    u.tipo_usuario = TipoUsuario.recaudador
    u.activo = True
    u.deleted_at = None
    return u


async def _credito(db_session, periodicidad=Periodicidad.mensual, **kw) -> Credito:
    defaults = dict(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:8]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2025, 11, 1),
        fecha_inicial_pago=date(2025, 11, 20),
        periodicidad=periodicidad,
        saldo_capital=Decimal("800.00"),
        saldo_intereses=Decimal("100.00"),
        numero_cuotas=12,
        activo=True,
        anchor_dia_1=None,
        anchor_dia_2=None,
    )
    defaults.update(kw)
    c = Credito(**defaults)
    db_session.add(c)
    await db_session.flush()
    return c


async def _cuota(
    db_session,
    credito,
    numero,
    fecha_maxima,
    pagado=False,
    capital=Decimal("80.00"),
    interes=Decimal("10.00"),
) -> Pago:
    """Create a cuota (paid or pending) with specific amounts."""
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
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client_admin(db_session):
    admin = _make_admin()

    async def override_user():
        return admin

    async def override_db():
        yield db_session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def client_recaudador(db_session):
    recaudador = _make_recaudador()

    async def override_user():
        return recaudador

    app.dependency_overrides[get_current_user] = override_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

class TestAnclarFechasAuth:
    @pytest.mark.asyncio
    async def test_recaudador_recibe_403(self, client_recaudador: AsyncClient):
        """Non-admin must receive 403 Forbidden."""
        response = await client_recaudador.post(ENDPOINT)
        assert response.status_code == 403, (
            f"Expected 403 for recaudador, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_admin_recibe_200(self, client_admin: AsyncClient):
        """Admin must receive 200 with expected summary structure."""
        response = await client_admin.post(ENDPOINT)
        assert response.status_code == 200, (
            f"Expected 200 for admin, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert "total_revisados" in data
        assert "total_anclados" in data
        assert "total_saltados" in data
        assert "requiere_revision_manual" in data
        assert isinstance(data["requiere_revision_manual"], list)


# ---------------------------------------------------------------------------
# CAP-5: Mensual backfill
# ---------------------------------------------------------------------------

class TestAnclarFechasMensual:
    @pytest.mark.asyncio
    async def test_mensual_deriva_anchor_de_fecha_inicial(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-5.1: mensual credit gets anchor_dia_1 = fecha_inicial_pago.day."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.mensual,
            fecha_inicial_pago=date(2025, 11, 20),
            anchor_dia_1=None,
            anchor_dia_2=None,
        )
        # Add one paid cuota and two pending cuotas at drifted dates
        await _cuota(db_session, credito, 1, date(2025, 11, 20), pagado=True)
        await _cuota(db_session, credito, 2, date(2025, 12, 19))  # drifted
        await _cuota(db_session, credito, 3, date(2026, 1, 22))   # drifted

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        # credito is the same Python object mutated in-session (identity map)
        assert credito.anchor_dia_1 == 20
        assert credito.anchor_dia_2 is None

    @pytest.mark.asyncio
    async def test_mensual_recalcula_cuotas_pendientes_a_dia_ancla(
        self, client_admin: AsyncClient, db_session
    ):
        """After backfill, pending mensual cuotas land on anchor day (the 20th)."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.mensual,
            fecha_inicial_pago=date(2025, 11, 20),
            anchor_dia_1=None,
            anchor_dia_2=None,
        )
        paid_cuota = await _cuota(db_session, credito, 1, date(2025, 11, 20), pagado=True)
        pending_2 = await _cuota(db_session, credito, 2, date(2025, 12, 19))  # drifted
        pending_3 = await _cuota(db_session, credito, 3, date(2026, 1, 22))   # drifted

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        # In-session identity map: same Python objects were mutated by recalcular_cuotas_futuras
        # Pending cuotas re-anchored to the 20th
        assert pending_2.fecha_maxima == date(2025, 12, 20)
        assert pending_3.fecha_maxima == date(2026, 1, 20)
        # Paid cuota unchanged
        assert paid_cuota.fecha_maxima == date(2025, 11, 20)

    @pytest.mark.asyncio
    async def test_mensual_amounts_invariant(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-6.3: monto_a_pagar, capital_a_pagar, interes_a_pagar are unchanged after backfill."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.mensual,
            fecha_inicial_pago=date(2025, 11, 20),
        )
        cap = Decimal("83.33")
        interes = Decimal("30.00")
        monto = cap + interes
        pending = await _cuota(
            db_session, credito, 1, date(2025, 12, 19),
            capital=cap, interes=interes
        )

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        # Identity map: same Python object; amounts must be unchanged
        assert pending.monto_a_pagar == monto
        assert pending.capital_a_pagar == cap
        assert pending.interes_a_pagar == interes


# ---------------------------------------------------------------------------
# CAP-5: Quincenal backfill
# ---------------------------------------------------------------------------

class TestAnclarFechasQuincenal:
    @pytest.mark.asyncio
    async def test_quincenal_deriva_anchor_pair_de_cuotas(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-5.2a: quincenal derives anchor pair from first 2 distinct Pago.fecha_maxima days."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.quincenal,
            fecha_inicial_pago=date(2025, 11, 15),
        )
        await _cuota(db_session, credito, 1, date(2025, 11, 15), pagado=True)
        await _cuota(db_session, credito, 2, date(2025, 11, 30), pagado=True)
        await _cuota(db_session, credito, 3, date(2025, 12, 14))  # pending drifted
        await _cuota(db_session, credito, 4, date(2025, 12, 28))  # pending drifted

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        assert credito.anchor_dia_1 == 15
        assert credito.anchor_dia_2 == 30

    @pytest.mark.asyncio
    async def test_quincenal_normaliza_pair_d1_menor_d2(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-5.2b: normalization — first two distinct days are sorted d1<d2 regardless of order in DB."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.quincenal,
            fecha_inicial_pago=date(2025, 11, 28),
        )
        # Cuota dates have day=28 first then day=12 — should normalize to d1=12, d2=28
        await _cuota(db_session, credito, 1, date(2025, 11, 28), pagado=True)
        await _cuota(db_session, credito, 2, date(2025, 12, 12), pagado=True)
        await _cuota(db_session, credito, 3, date(2025, 12, 29))

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        assert credito.anchor_dia_1 == 12
        assert credito.anchor_dia_2 == 28

    @pytest.mark.asyncio
    async def test_quincenal_recalcula_pendientes(
        self, client_admin: AsyncClient, db_session
    ):
        """After quincenal backfill, pending cuotas land on the anchor cadence."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.quincenal,
            fecha_inicial_pago=date(2025, 11, 15),
        )
        paid_1 = await _cuota(db_session, credito, 1, date(2025, 11, 15), pagado=True)
        paid_2 = await _cuota(db_session, credito, 2, date(2025, 11, 30), pagado=True)
        pending_3 = await _cuota(db_session, credito, 3, date(2025, 12, 14))
        pending_4 = await _cuota(db_session, credito, 4, date(2025, 12, 28))

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        # In-session identity map: same Python objects mutated by recalcular_cuotas_futuras
        # Last paid was Nov 30 (d2), so desde_fecha = Dec 15 (d1), then Dec 30 (d2)
        assert pending_3.fecha_maxima == date(2025, 12, 15)
        assert pending_4.fecha_maxima == date(2025, 12, 30)
        # Paid cuotas unchanged
        assert paid_1.fecha_maxima == date(2025, 11, 15)
        assert paid_2.fecha_maxima == date(2025, 11, 30)


# ---------------------------------------------------------------------------
# CAP-5 REQ-5.3: Quincenal <2 distinct cuota days → flagged, not guessed
# ---------------------------------------------------------------------------

class TestAnclarFechasQuincenalInsufficientData:
    @pytest.mark.asyncio
    async def test_quincenal_una_cuota_flaggeada(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-5.3a: quincenal with only 1 distinct fecha_maxima day is flagged, not processed."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.quincenal,
            fecha_inicial_pago=date(2025, 11, 15),
        )
        # Only one cuota → only one distinct day
        await _cuota(db_session, credito, 1, date(2025, 11, 15))

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        data = r.json()
        assert str(credito.id) in data["requiere_revision_manual"], (
            "Quincenal with <2 distinct cuota days must be in requiere_revision_manual"
        )

        # anchor_dia_1 must be seeded from fecha_inicial_pago.day (REQ-5.3a)
        assert credito.anchor_dia_1 == credito.fecha_inicial_pago.day
        # anchor_dia_2 must remain NULL (not guessed) — credito in identity map
        assert credito.anchor_dia_2 is None

    @pytest.mark.asyncio
    async def test_quincenal_sin_cuotas_flaggeada(
        self, client_admin: AsyncClient, db_session
    ):
        """Quincenal credit with zero cuotas is also flagged for manual review."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.quincenal,
            fecha_inicial_pago=date(2025, 11, 15),
        )
        # No cuotas at all

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        data = r.json()
        assert str(credito.id) in data["requiere_revision_manual"]

        assert credito.anchor_dia_2 is None


# ---------------------------------------------------------------------------
# CAP-5 REQ-5.4: semanal / diario untouched
# ---------------------------------------------------------------------------

class TestAnclarFechasSemanalDiario:
    @pytest.mark.asyncio
    async def test_semanal_no_tocado(self, client_admin: AsyncClient, db_session):
        """REQ-5.4: semanal credit is not processed — anchors remain NULL."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.semanal,
            fecha_inicial_pago=date(2025, 11, 15),
        )
        await _cuota(db_session, credito, 1, date(2025, 11, 15))

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None

    @pytest.mark.asyncio
    async def test_diario_no_tocado(self, client_admin: AsyncClient, db_session):
        """REQ-5.4: diario credit is not processed — anchors remain NULL."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.diario,
            fecha_inicial_pago=date(2025, 11, 15),
        )
        await _cuota(db_session, credito, 1, date(2025, 11, 15))

        r = await client_admin.post(ENDPOINT)
        assert r.status_code == 200, r.text

        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None


# ---------------------------------------------------------------------------
# CAP-8: Idempotency
# ---------------------------------------------------------------------------

class TestAnclarFechasIdempotency:
    @pytest.mark.asyncio
    async def test_segunda_ejecucion_es_noop(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-8.1a: second run skips all already-anchored credits — zero net change."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.mensual,
            fecha_inicial_pago=date(2025, 11, 20),
        )
        await _cuota(db_session, credito, 1, date(2025, 11, 20), pagado=True)
        await _cuota(db_session, credito, 2, date(2025, 12, 19))

        # First run — should process the credit
        r1 = await client_admin.post(ENDPOINT)
        assert r1.status_code == 200, r1.text
        data1 = r1.json()
        first_anclados = data1["total_anclados"]
        assert first_anclados >= 1

        # Capture state after first run (identity map — same Python object)
        anchor1_after = credito.anchor_dia_1
        assert anchor1_after == 20

        # Second run — credit already anchored, must be skipped
        r2 = await client_admin.post(ENDPOINT)
        assert r2.status_code == 200, r2.text
        data2 = r2.json()

        # All credits that were anchored in run 1 must be skipped in run 2
        assert data2["total_anclados"] == 0, (
            f"Second run must anchor 0 credits, got {data2['total_anclados']}"
        )
        assert data2["total_saltados"] >= first_anclados, (
            "Credits anchored in run 1 must be counted as skipped in run 2"
        )

        # State is identical (anchor unchanged)
        assert credito.anchor_dia_1 == anchor1_after

    @pytest.mark.asyncio
    async def test_quincenal_flaggeado_skipeado_en_segunda_ejecucion(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-8.1a (quincenal): flagged quincenal with anchor_dia_1 seeded is skipped on re-run."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.quincenal,
            fecha_inicial_pago=date(2025, 11, 15),
        )
        # Only one cuota → flagged on first run
        await _cuota(db_session, credito, 1, date(2025, 11, 15))

        # First run — must flag and seed anchor_dia_1
        r1 = await client_admin.post(ENDPOINT)
        assert r1.status_code == 200, r1.text
        data1 = r1.json()
        assert str(credito.id) in data1["requiere_revision_manual"]
        assert credito.anchor_dia_1 == 15  # seeded
        assert credito.anchor_dia_2 is None

        # Second run — anchor_dia_1 is not None → idempotency gate skips this credit
        r2 = await client_admin.post(ENDPOINT)
        assert r2.status_code == 200, r2.text
        data2 = r2.json()

        # Credit must NOT appear again in requiere_revision_manual on second run
        assert str(credito.id) not in data2["requiere_revision_manual"], (
            "Flagged quincenal with anchor_dia_1 seeded must be skipped (not re-flagged) on re-run"
        )
        # State unchanged
        assert credito.anchor_dia_1 == 15
        assert credito.anchor_dia_2 is None

    @pytest.mark.asyncio
    async def test_segunda_ejecucion_estado_identico(
        self, client_admin: AsyncClient, db_session
    ):
        """REQ-8.1b+8.2: running twice yields identical cuota dates (re-anchor is idempotent)."""
        credito = await _credito(
            db_session,
            periodicidad=Periodicidad.mensual,
            fecha_inicial_pago=date(2025, 11, 20),
        )
        await _cuota(db_session, credito, 1, date(2025, 11, 20), pagado=True)
        pending = await _cuota(db_session, credito, 2, date(2025, 12, 19))  # drifted

        # First run
        r1 = await client_admin.post(ENDPOINT)
        assert r1.status_code == 200, r1.text
        # Identity map: pending is the same Python object mutated in-session
        fecha_after_run1 = pending.fecha_maxima

        # Second run — credit is already anchored, recalcular re-runs but is itself idempotent
        r2 = await client_admin.post(ENDPOINT)
        assert r2.status_code == 200, r2.text
        fecha_after_run2 = pending.fecha_maxima

        assert fecha_after_run1 == fecha_after_run2, (
            "fecha_maxima must be identical after two runs"
        )
