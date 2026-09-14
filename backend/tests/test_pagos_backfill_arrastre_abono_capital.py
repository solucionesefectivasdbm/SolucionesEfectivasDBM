"""
tests/test_pagos_backfill_arrastre_abono_capital.py — One-off backfill
correction for `abono_capital` rows generated before the carry-over fix
(Req: One-off Backfill Correction).

TEMPORAL: this endpoint and this test file are deleted in PR-3, after the
backfill has run once in production (see design.md "Migration / Rollout").

Covers:
- A qualifying unpaid row (`monto_a_pagar > capital_a_pagar + interes_a_pagar
  + TOL`) gets `interes_a_pagar` corrected to `monto_a_pagar - capital_a_pagar`.
- `dry_run=True` (default) writes nothing to the DB.
- A second `dry_run=False` run is a no-op (idempotent by construction).
- `cuota_fija` rows, paid rows, and already-correct rows are left untouched.
- Non-admin roles get 403.
"""
import uuid
from datetime import date, datetime
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

_FAKE_GESTOR_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_ENDPOINT = "/api/v1/pagos/admin/backfill-arrastre-abono-capital"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=_FAKE_GESTOR_ID, nombre="Ana",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )


def _mk_credito(
    cliente_id: uuid.UUID,
    tipo_credito: TipoCredito = TipoCredito.abono_capital,
    activo: bool = True,
    deleted_at=None,
) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=tipo_credito, capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0500"), fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 10), periodicidad=Periodicidad.quincenal,
        saldo_capital=Decimal("1000000.00"), saldo_intereses=Decimal("0.00"),
        abono_minimo=Decimal("100000.00"), numero_cuotas=None, activo=activo,
        deleted_at=deleted_at,
    )


def _mk_pago(
    credito_id: uuid.UUID,
    *,
    numero_cuota: int = 1,
    tipo_cuota: TipoCuota = TipoCuota.interes,
    monto_a_pagar: Decimal = Decimal("170000.00"),
    capital_a_pagar: Decimal = Decimal("100000.00"),
    interes_a_pagar: Decimal = Decimal("50000.00"),
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
        momento="m3", fecha_maxima=date(2026, 1, 25), pagado=pagado,
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


class TestBackfillArrastreAbonoCapital:
    @pytest.mark.asyncio
    async def test_fila_calificada_se_corrige(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("170000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is False
        assert body["revisados"] == 1
        assert body["corregidos"] == 1
        assert body["detalle"][0]["interes_a_pagar"] == ["50000.00", "70000.00"]

        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("70000.00")
        assert pago.capital_a_pagar == Decimal("100000.00")
        assert pago.monto_a_pagar == Decimal("170000.00")

    @pytest.mark.asyncio
    async def test_dry_run_no_escribe_nada(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("170000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={"dry_run": True})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert body["revisados"] == 1
        assert body["corregidos"] == 0

        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("50000.00")

    @pytest.mark.asyncio
    async def test_default_es_dry_run(self, client_factory, db_session):
        """`dry_run` defaults to True when the body omits it."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("170000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert body["revisados"] == 1
        assert body["corregidos"] == 0
        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("50000.00")

    @pytest.mark.asyncio
    async def test_segunda_corrida_es_no_op(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("170000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        first = await client.post(_ENDPOINT, json={"dry_run": False})
        assert first.json()["corregidos"] == 1

        second = await client.post(_ENDPOINT, json={"dry_run": False})
        assert second.status_code == 200
        assert second.json()["revisados"] == 0
        assert second.json()["corregidos"] == 0

    @pytest.mark.asyncio
    async def test_fila_cuota_fija_no_se_toca(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, tipo_credito=TipoCredito.cuota_fija)
        # Same "malformed" shape, but on a cuota_fija credit — out of scope.
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("170000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        assert r.json()["revisados"] == 0
        assert r.json()["corregidos"] == 0
        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("50000.00")

    @pytest.mark.asyncio
    async def test_fila_pagada_no_se_toca(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("170000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
            capital_pagado=Decimal("100000.00"),
            interes_pagado=Decimal("50000.00"),
            pagado=True,
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        assert r.json()["revisados"] == 0
        assert r.json()["corregidos"] == 0
        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("50000.00")

    @pytest.mark.asyncio
    async def test_fila_ya_correcta_fuera_de_alcance(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("150000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        assert r.json()["revisados"] == 0
        assert r.json()["corregidos"] == 0
        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("50000.00")

    @pytest.mark.parametrize(
        "credito_kwargs,pago_kwargs",
        [
            ({}, {"tipo_cuota": TipoCuota.abono}),
            ({}, {"tipo_cuota": TipoCuota.no_programada}),
            ({"activo": False}, {}),
            ({}, {"deleted_at": datetime(2026, 2, 1)}),
            ({"deleted_at": datetime(2026, 2, 1)}, {}),
        ],
        ids=[
            "tipo_cuota_abono",
            "tipo_cuota_no_programada",
            "credito_inactivo",
            "pago_soft_deleted",
            "credito_soft_deleted",
        ],
    )
    @pytest.mark.asyncio
    async def test_predicado_excluye_filas_fuera_de_alcance(
        self, client_factory, db_session, credito_kwargs, pago_kwargs
    ):
        """Req: One-off Backfill Correction — predicate exclusions (review
        follow-up): abono/no_programada cuotas, inactive credits, and
        soft-deleted pagos/creditos must never be touched, even when the
        row's monto/capital/interes shape otherwise qualifies."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, **credito_kwargs)
        pago = _mk_pago(credito.id, **pago_kwargs)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        assert r.json()["revisados"] == 0
        assert r.json()["corregidos"] == 0
        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("50000.00")

    @pytest.mark.asyncio
    async def test_saldos_credito_no_se_tocan_en_corrida_aplicada(self, client_factory, db_session):
        """Req: One-off Backfill Correction — `saldo_capital`/`saldo_intereses`
        are never written, even on an applied (non-dry-run) correction."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        saldo_capital_original = credito.saldo_capital
        saldo_intereses_original = credito.saldo_intereses
        pago = _mk_pago(
            credito.id,
            monto_a_pagar=Decimal("170000.00"),
            capital_a_pagar=Decimal("100000.00"),
            interes_a_pagar=Decimal("50000.00"),
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        assert r.json()["corregidos"] == 1
        await db_session.refresh(credito)
        assert credito.saldo_capital == saldo_capital_original
        assert credito.saldo_intereses == saldo_intereses_original

    @pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.recaudador, TipoUsuario.gestor])
    @pytest.mark.asyncio
    async def test_no_admin_403(self, client_factory, db_session, rol):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        user = _mk_user(rol)
        client = await client_factory(user)

        r = await client.post(_ENDPOINT, json={"dry_run": True})

        assert r.status_code == 403
        await db_session.refresh(pago)
        assert pago.interes_a_pagar == Decimal("50000.00")
