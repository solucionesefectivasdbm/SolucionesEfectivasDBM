"""
tests/test_pagos_backfill_arrastre.py — One-off admin backfill for legacy
`cuota_fija` rows whose components never inflated with the arrastre already
present in `monto_a_pagar`.

TEMPORARY: this endpoint (and this test file) are deleted in the follow-up
commit once the backfill has run in production (PR 2, out of scope here).

Selection predicate (idempotency mechanism): `p.pagado = false AND
c.tipo_credito = 'cuota_fija' AND c.activo = true AND
p.monto_a_pagar > p.capital_a_pagar + p.interes_a_pagar`.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

BACKFILL_URL = "/api/v1/pagos/admin/backfill-arrastre-componentes"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Backfill", apellidos="Test", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID, activo: bool = True, tipo=TipoCredito.cuota_fija) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Backfill-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=tipo,
        capital_prestado=Decimal("1000.00"),
        tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 10),
        periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=10,
        calcular_interes_dias_corridos=False,
        activo=activo,
    )


def _mk_pago(
    credito_id: uuid.UUID,
    numero_cuota: int,
    monto_a_pagar: Decimal,
    capital_a_pagar: Decimal,
    interes_a_pagar: Decimal,
    pagado: bool = False,
    capital_pagado: Decimal = Decimal("0.00"),
    interes_pagado: Decimal = Decimal("0.00"),
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=numero_cuota,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=monto_a_pagar,
        capital_a_pagar=capital_a_pagar, interes_a_pagar=interes_a_pagar,
        capital_pagado=capital_pagado, interes_pagado=interes_pagado,
        momento="m3", fecha_maxima=date(2026, 2, 9),
        pagado=pagado, validado_recaudador=False, es_ultimo_pago=False,
    )


@pytest_asyncio.fixture
async def client_admin_db(db_session):
    admin = MagicMock(spec=Usuario)
    admin.id = uuid.uuid4()
    admin.tipo_usuario = TipoUsuario.admin
    admin.activo = True
    admin.deleted_at = None

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
async def client_registrador_db(db_session):
    registrador = MagicMock(spec=Usuario)
    registrador.id = uuid.uuid4()
    registrador.tipo_usuario = TipoUsuario.registrador
    registrador.activo = True
    registrador.deleted_at = None

    async def override_user():
        return registrador

    async def override_db():
        yield db_session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestBackfillArrastreComponentes:

    @pytest.mark.asyncio
    async def test_fila_calificada_es_corregida(self, client_admin_db: AsyncClient, db_session):
        """
        Legacy-shaped row: monto_a_pagar already includes the arrastre (180.00)
        but components are still at base level (100/20) — the defect this
        change fixes. Backfill must raise components using the disaggregation
        rule so cap+int == monto.
        """
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id)
        db_session.add(credito)
        await db_session.flush()

        cuota_previa_pagada = _mk_pago(
            credito.id, numero_cuota=1,
            monto_a_pagar=Decimal("120.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            pagado=True, capital_pagado=Decimal("50.00"), interes_pagado=Decimal("10.00"),
        )
        cuota_legacy = _mk_pago(
            credito.id, numero_cuota=2,
            monto_a_pagar=Decimal("180.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            pagado=False,
        )
        db_session.add_all([cuota_previa_pagada, cuota_legacy])
        await db_session.flush()

        r = await client_admin_db.post(BACKFILL_URL)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["corregidos"] == 1
        assert body["revisados"] >= 1
        assert body["omitidos"] == 0

        # Same session/identity map as the endpoint — the object is already
        # mutated in place; `refresh()` would instead re-SELECT and clobber
        # the pending (unflushed) change back to its stale DB value, since
        # this test session has autoflush disabled for `refresh()`.
        assert cuota_legacy.capital_a_pagar == Decimal("150.00")
        assert cuota_legacy.interes_a_pagar == Decimal("30.00")
        assert cuota_legacy.capital_a_pagar + cuota_legacy.interes_a_pagar == cuota_legacy.monto_a_pagar
        # monto_a_pagar itself is never rewritten
        assert cuota_legacy.monto_a_pagar == Decimal("180.00")

    @pytest.mark.asyncio
    async def test_segunda_corrida_es_idempotente(self, client_admin_db: AsyncClient, db_session):
        """After correction, `monto_a_pagar == capital_a_pagar + interes_a_pagar`,
        so a second run selects zero rows — cannot double-inflate."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id)
        db_session.add(credito)
        await db_session.flush()

        cuota_previa_pagada = _mk_pago(
            credito.id, numero_cuota=1,
            monto_a_pagar=Decimal("120.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            pagado=True, capital_pagado=Decimal("50.00"), interes_pagado=Decimal("10.00"),
        )
        cuota_legacy = _mk_pago(
            credito.id, numero_cuota=2,
            monto_a_pagar=Decimal("180.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            pagado=False,
        )
        db_session.add_all([cuota_previa_pagada, cuota_legacy])
        await db_session.flush()

        r1 = await client_admin_db.post(BACKFILL_URL)
        assert r1.status_code == 200, r1.text
        assert r1.json()["corregidos"] == 1

        r2 = await client_admin_db.post(BACKFILL_URL)
        assert r2.status_code == 200, r2.text
        assert r2.json()["corregidos"] == 0

        # Same session/identity map as the endpoint — the object is already
        # mutated in place; `refresh()` would instead re-SELECT and clobber
        # the pending (unflushed) change back to its stale DB value, since
        # this test session has autoflush disabled for `refresh()`.
        assert cuota_legacy.capital_a_pagar == Decimal("150.00")
        assert cuota_legacy.interes_a_pagar == Decimal("30.00")

    @pytest.mark.asyncio
    async def test_fila_sin_cuota_previa_pagada_es_omitida(self, client_admin_db: AsyncClient, db_session):
        """A qualifying row with no previous PAID cuota is skipped and
        reported, never guessed."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id)
        db_session.add(credito)
        await db_session.flush()

        # numero_cuota=1: no prior cuota at all.
        cuota_sin_previa = _mk_pago(
            credito.id, numero_cuota=1,
            monto_a_pagar=Decimal("180.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            pagado=False,
        )
        db_session.add(cuota_sin_previa)
        await db_session.flush()

        r = await client_admin_db.post(BACKFILL_URL)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["corregidos"] == 0
        assert body["omitidos"] == 1
        assert len(body["detalle"]) == 1
        assert body["detalle"][0]["pago_id"] == str(cuota_sin_previa.id)
        assert body["detalle"][0]["razon"]

        await db_session.refresh(cuota_sin_previa)
        assert cuota_sin_previa.capital_a_pagar == Decimal("100.00")
        assert cuota_sin_previa.interes_a_pagar == Decimal("20.00")

    @pytest.mark.asyncio
    async def test_pagos_registrados_abono_capital_y_saldos_no_se_tocan(
        self, client_admin_db: AsyncClient, db_session
    ):
        """Registered/historical payments, `abono_capital` rows and `Credito`
        balances are never modified by the backfill."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        credito_fija = _mk_credito(cliente.id)
        credito_abono = _mk_credito(cliente.id, tipo=TipoCredito.abono_capital)
        db_session.add_all([credito_fija, credito_abono])
        await db_session.flush()

        saldo_capital_abono_antes = credito_abono.saldo_capital
        saldo_capital_fija_antes = credito_fija.saldo_capital

        # Historical/registered payment on the cuota_fija credit — already
        # pagado=True, so it never qualifies for the selection predicate.
        pago_historico = _mk_pago(
            credito_fija.id, numero_cuota=1,
            monto_a_pagar=Decimal("180.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            pagado=True, capital_pagado=Decimal("100.00"), interes_pagado=Decimal("20.00"),
        )
        # abono_capital row shaped like it could qualify — out of scope by tipo_credito.
        pago_abono = _mk_pago(
            credito_abono.id, numero_cuota=1,
            monto_a_pagar=Decimal("180.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            pagado=False,
        )
        db_session.add_all([pago_historico, pago_abono])
        await db_session.flush()

        r = await client_admin_db.post(BACKFILL_URL)
        assert r.status_code == 200, r.text
        assert r.json()["corregidos"] == 0

        await db_session.refresh(pago_historico)
        await db_session.refresh(pago_abono)
        await db_session.refresh(credito_fija)
        await db_session.refresh(credito_abono)

        assert pago_historico.capital_pagado == Decimal("100.00")
        assert pago_historico.interes_pagado == Decimal("20.00")
        assert pago_abono.capital_a_pagar == Decimal("100.00")
        assert pago_abono.interes_a_pagar == Decimal("20.00")
        assert credito_fija.saldo_capital == saldo_capital_fija_antes
        assert credito_abono.saldo_capital == saldo_capital_abono_antes

    @pytest.mark.asyncio
    async def test_no_admin_recibe_403(self, client_registrador_db: AsyncClient):
        r = await client_registrador_db.post(BACKFILL_URL)
        assert r.status_code == 403, r.text
