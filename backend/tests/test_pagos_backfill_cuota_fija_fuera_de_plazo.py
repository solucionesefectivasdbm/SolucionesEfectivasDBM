"""
tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py — One-off backfill
correction for `cuota_fija` past-term rows generated before the rule-15 fix
(Req: credit-closure "One-off Past-term Arrastre Backfill").

TEMPORAL: this endpoint and this test file are deleted in PR-C, after the
backfill has run once in production (see design.md "Migration / Rollout").

Covers:
- A qualifying unpaid past-term row (inflated by carried arrastre) gets its
  components reset to the base values and `monto_a_pagar` recomputed.
- `dry_run=True` (default) writes nothing to the DB.
- A second `dry_run=False` run is a no-op (idempotent by construction).
- `abono_capital` rows, paid rows, within-term rows, and already-base rows
  are left untouched.
- Non-admin roles get 403.
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

_FAKE_GESTOR_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
_ENDPOINT = "/api/v1/pagos/admin/backfill-cuota-fija-fuera-de-plazo"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=_FAKE_GESTOR_ID, nombre="Fernando",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )


def _mk_credito(
    cliente_id: uuid.UUID,
    tipo_credito: TipoCredito = TipoCredito.cuota_fija,
    activo: bool = True,
    deleted_at=None,
    saldo_capital: Decimal = Decimal("300000.00"),
    saldo_intereses: Decimal = Decimal("3600.00"),
    numero_cuotas: int | None = 12,
    capital_prestado: Decimal = Decimal("120000.00"),
    tasa: Decimal = Decimal("0.0300"),
) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=tipo_credito, capital_prestado=capital_prestado,
        tasa_interes_mensual=tasa, fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 15), periodicidad=Periodicidad.mensual,
        saldo_capital=saldo_capital, saldo_intereses=saldo_intereses,
        numero_cuotas=numero_cuotas, activo=activo, deleted_at=deleted_at,
    )


def _mk_pago(
    credito_id: uuid.UUID,
    *,
    numero_cuota: int = 13,
    tipo_cuota: TipoCuota = TipoCuota.programada,
    monto_a_pagar: Decimal = Decimal("19200.00"),
    capital_a_pagar: Decimal = Decimal("15600.00"),
    interes_a_pagar: Decimal = Decimal("3600.00"),
    capital_pagado: Decimal = Decimal("0.00"),
    interes_pagado: Decimal = Decimal("0.00"),
    pagado: bool = False,
    deleted_at=None,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=numero_cuota,
        tipo_cuota=tipo_cuota, monto_a_pagar=monto_a_pagar,
        capital_a_pagar=capital_a_pagar, interes_a_pagar=interes_a_pagar,
        capital_pagado=capital_pagado, interes_pagado=interes_pagado,
        momento="m3", fecha_maxima=date(2027, 1, 15), pagado=pagado,
        deleted_at=deleted_at,
    )


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


@pytest_asyncio.fixture
async def client_factory(db_session):
    """Returns a factory that builds an AsyncClient overridden for a given user."""
    created = []

    async def _make(user: MagicMock) -> AsyncClient:
        async def override_user():
            return user

        async def override_db():
            yield db_session

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        created.append(client)
        return client

    yield _make

    for c in created:
        await c.aclose()
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestBackfillCuotaFijaFueraDePlazo:
    @pytest.mark.asyncio
    async def test_fila_calificada_se_corrige(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("19200.00"),
            capital_a_pagar=Decimal("15600.00"),
            interes_a_pagar=Decimal("3600.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, params={"dry_run": "false"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is False
        assert body["revisados"] == 1
        assert body["corregidos"] == 1
        assert body["detalle"][0]["despues"] == {
            "capital": "10000.00", "interes": "3600.00", "monto": "13600.00",
        }

        await db_session.refresh(pago)
        assert pago.capital_a_pagar == Decimal("10000.00")
        assert pago.interes_a_pagar == Decimal("3600.00")
        assert pago.monto_a_pagar == Decimal("13600.00")

    @pytest.mark.asyncio
    async def test_dry_run_no_escribe_nada(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert body["revisados"] == 1
        assert body["corregidos"] == 0

        await db_session.refresh(pago)
        assert pago.capital_a_pagar == Decimal("15600.00")

    @pytest.mark.asyncio
    async def test_segundo_run_es_idempotente(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r1 = await client.post(_ENDPOINT, params={"dry_run": "false"})
        assert r1.json()["corregidos"] == 1

        r2 = await client.post(_ENDPOINT, params={"dry_run": "false"})
        body2 = r2.json()
        assert body2["corregidos"] == 0
        assert body2["detalle"] == []

    @pytest.mark.asyncio
    async def test_fila_abono_capital_no_se_toca(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(
            cliente.id, tipo_credito=TipoCredito.abono_capital, numero_cuotas=None,
        )
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, params={"dry_run": "false"})
        assert r.json()["revisados"] == 0

        await db_session.refresh(pago)
        assert pago.capital_a_pagar == Decimal("15600.00")

    @pytest.mark.asyncio
    async def test_fila_pagada_no_se_toca(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            capital_pagado=Decimal("10000.00"), interes_pagado=Decimal("3600.00"),
            pagado=True,
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, params={"dry_run": "false"})
        assert r.json()["revisados"] == 0

    @pytest.mark.asyncio
    async def test_fila_dentro_de_plazo_no_se_toca(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, numero_cuota=12)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, params={"dry_run": "false"})
        assert r.json()["revisados"] == 0

    @pytest.mark.asyncio
    async def test_fila_ya_en_base_no_se_toca(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("13600.00"),
            capital_a_pagar=Decimal("10000.00"),
            interes_a_pagar=Decimal("3600.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, params={"dry_run": "false"})
        body = r.json()
        assert body["corregidos"] == 0
        assert body["detalle"] == []

    @pytest.mark.asyncio
    async def test_no_admin_403(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        registrador = _mk_user(TipoUsuario.registrador)
        client = await client_factory(registrador)

        r = await client.post(_ENDPOINT, params={"dry_run": "false"})
        assert r.status_code == 403

        await db_session.refresh(pago)
        assert pago.capital_a_pagar == Decimal("15600.00")
