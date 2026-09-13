"""
tests/test_aplazamientos.py — Payment deferrals (payment-deferrals change).

Covers:
- Deferral Counter (existing rows default to 0; reversal keeps the counter)
- Extended Date Modification (`PATCH /pagos/{id}/fecha` with `es_aplazamiento`)
- Deferral Rejections (paid payment; backward/same date; deferred then paid)
- Role Gate (admin/recaudador allowed; registrador/gestor 403)
- Distinguishable Audit (deferral writes 2 audit rows; correction writes 1)
- Cross-Period Deferred Listing (`GET /pagos/aplazados`)
- Double Visualization (`listar_pagos` carries `veces_aplazado`)

Fixtures copied/adapted from test_desvalidar_pago.py.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.gestor import Gestor
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

_FAKE_GESTOR_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _mk_cliente(gestor_id: uuid.UUID | None = None) -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=gestor_id or _FAKE_GESTOR_ID, nombre="Ana",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID, **kw) -> Credito:
    defaults = dict(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija, capital_prestado=Decimal("1200000.00"),
        tasa_interes_mensual=Decimal("0.0300"), fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1), periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("1200000.00"), saldo_intereses=Decimal("0.00"),
        numero_cuotas=12, activo=True,
    )
    defaults.update(kw)
    return Credito(**defaults)


def _mk_pago(
    credito_id: uuid.UUID, *, fecha_maxima: date = date(2026, 10, 5),
    pagado: bool = False, veces_aplazado: int = 0, numero_cuota: int = 1,
    momento: str | None = None,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=numero_cuota,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("110000.00"),
        capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("10000.00"),
        capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
        momento=momento or "m1", fecha_maxima=fecha_maxima, pagado=pagado,
        validado_recaudador=False, veces_aplazado=veces_aplazado,
    )


def _mk_user(rol: TipoUsuario, gestor_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


async def _audit_rows(db_session, pago_id):
    return (await db_session.execute(
        select(AuditLog).where(AuditLog.entidad_id == pago_id)
    )).scalars().all()


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


# ---------------------------------------------------------------------------
# Deferral Counter
# ---------------------------------------------------------------------------

class TestDeferralCounter:
    @pytest.mark.asyncio
    async def test_existing_rows_default_to_zero(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.get(
            "/api/v1/pagos", params={"anio": 2026, "mes": 10},
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["veces_aplazado"] == 0

    @pytest.mark.asyncio
    async def test_reversal_keeps_the_counter(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, veces_aplazado=2)
        pago.validado_recaudador = True
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.post(f"/api/v1/pagos/{pago.id}/desvalidar")
        assert r.status_code == 200, r.text
        assert r.json()["veces_aplazado"] == 2


# ---------------------------------------------------------------------------
# Extended Date Modification
# ---------------------------------------------------------------------------

class TestExtendedDateModification:
    @pytest.mark.asyncio
    async def test_plain_correction_unchanged(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha", json={"fecha_maxima": "2026-10-12"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fecha_maxima"] == "2026-10-12"
        assert body["veces_aplazado"] == 0

    @pytest.mark.asyncio
    async def test_first_deferral(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-12", "es_aplazamiento": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fecha_maxima"] == "2026-10-12"
        assert body["veces_aplazado"] == 1

    @pytest.mark.asyncio
    async def test_second_deferral(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r1 = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-12", "es_aplazamiento": True},
        )
        assert r1.status_code == 200, r1.text

        r2 = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-19", "es_aplazamiento": True},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["veces_aplazado"] == 2

    @pytest.mark.asyncio
    async def test_correction_after_deferral(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5), veces_aplazado=1)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-20", "es_aplazamiento": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fecha_maxima"] == "2026-10-20"
        assert body["veces_aplazado"] == 1


# ---------------------------------------------------------------------------
# Deferral Rejections
# ---------------------------------------------------------------------------

class TestDeferralRejections:
    @pytest.mark.asyncio
    async def test_paid_payment_cannot_be_deferred(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5), pagado=True)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-20", "es_aplazamiento": True},
        )
        assert r.status_code == 422
        assert "aplaz" in r.json()["detail"].lower()

        await db_session.refresh(pago)
        assert pago.fecha_maxima == date(2026, 10, 5)
        assert pago.veces_aplazado == 0
        assert len(await _audit_rows(db_session, pago.id)) == 0

    @pytest.mark.parametrize("nueva_fecha", ["2026-10-05", "2026-10-01"])
    @pytest.mark.asyncio
    async def test_backward_or_same_date_is_not_a_deferral(
        self, client_factory, db_session, nueva_fecha
    ):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": nueva_fecha, "es_aplazamiento": True},
        )
        assert r.status_code == 422
        assert "adelante" in r.json()["detail"].lower()

        await db_session.refresh(pago)
        assert pago.fecha_maxima == date(2026, 10, 5)
        assert pago.veces_aplazado == 0
        assert len(await _audit_rows(db_session, pago.id)) == 0

    @pytest.mark.asyncio
    async def test_same_or_backward_date_without_flag_is_allowed(self, client_factory, db_session):
        """Without es_aplazamiento, direction is not validated (unchanged today's behaviour)."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha", json={"fecha_maxima": "2026-10-01"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["fecha_maxima"] == "2026-10-01"

    @pytest.mark.asyncio
    async def test_deferred_then_paid_further_deferral_rejected(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5), veces_aplazado=1, pagado=True)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-20", "es_aplazamiento": True},
        )
        assert r.status_code == 422
        await db_session.refresh(pago)
        assert pago.veces_aplazado == 1

    @pytest.mark.asyncio
    async def test_projected_row_404_persists_nothing(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        virtual_id = uuid.uuid5(uuid.NAMESPACE_OID, f"{uuid.uuid4()}-1")
        r = await client.patch(
            f"/api/v1/pagos/{virtual_id}/fecha",
            json={"fecha_maxima": "2026-10-20", "es_aplazamiento": True},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Role Gate
# ---------------------------------------------------------------------------

class TestRoleGate:
    @pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor])
    @pytest.mark.asyncio
    async def test_forbidden_roles(self, client_factory, db_session, rol):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(_mk_user(rol))
        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-12", "es_aplazamiento": True},
        )
        assert r.status_code == 403
        await db_session.refresh(pago)
        assert pago.fecha_maxima == date(2026, 10, 5)
        assert pago.veces_aplazado == 0

    @pytest.mark.parametrize("rol", [TipoUsuario.admin, TipoUsuario.recaudador])
    @pytest.mark.asyncio
    async def test_allowed_roles(self, client_factory, db_session, rol):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(_mk_user(rol))
        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-12", "es_aplazamiento": True},
        )
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Distinguishable Audit
# ---------------------------------------------------------------------------

class TestDistinguishableAudit:
    @pytest.mark.asyncio
    async def test_deferral_audited(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha",
            json={"fecha_maxima": "2026-10-12", "es_aplazamiento": True},
        )
        assert r.status_code == 200, r.text

        rows = await _audit_rows(db_session, pago.id)
        campos = {row.campo_modificado: row for row in rows}
        assert len(rows) == 2
        assert campos["fecha_maxima"].valor_anterior == "2026-10-05"
        assert campos["fecha_maxima"].valor_nuevo == "2026-10-12"
        assert campos["veces_aplazado"].valor_anterior == "0"
        assert campos["veces_aplazado"].valor_nuevo == "1"
        assert campos["veces_aplazado"].usuario_id == admin.id

    @pytest.mark.asyncio
    async def test_correction_audited_as_today(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 5))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.patch(
            f"/api/v1/pagos/{pago.id}/fecha", json={"fecha_maxima": "2026-10-12"},
        )
        assert r.status_code == 200, r.text

        rows = await _audit_rows(db_session, pago.id)
        assert len(rows) == 1
        assert rows[0].campo_modificado == "fecha_maxima"


# ---------------------------------------------------------------------------
# Cross-Period Deferred Listing
# ---------------------------------------------------------------------------

class TestCrossPeriodDeferredListing:
    @pytest.mark.asyncio
    async def test_spans_months(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago_oct = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 15), veces_aplazado=1, numero_cuota=1)
        pago_dic = _mk_pago(credito.id, fecha_maxima=date(2026, 12, 15), veces_aplazado=1, numero_cuota=2)
        db_session.add_all([cliente, credito, pago_oct, pago_dic])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.get("/api/v1/pagos/aplazados")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert [item["id"] for item in body["items"]] == [str(pago_oct.id), str(pago_dic.id)]

    @pytest.mark.asyncio
    async def test_paid_excluded_by_default(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago_pendiente = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 15), veces_aplazado=1, numero_cuota=1)
        pago_pagado = _mk_pago(
            credito.id, fecha_maxima=date(2026, 11, 15), veces_aplazado=1, pagado=True, numero_cuota=2,
        )
        db_session.add_all([cliente, credito, pago_pendiente, pago_pagado])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r1 = await client.get("/api/v1/pagos/aplazados")
        assert r1.status_code == 200, r1.text
        assert r1.json()["total"] == 1
        assert r1.json()["items"][0]["id"] == str(pago_pendiente.id)

        r2 = await client.get("/api/v1/pagos/aplazados", params={"incluir_pagados": True})
        assert r2.status_code == 200, r2.text
        assert r2.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_gestor_scoping(self, client_factory, db_session):
        gestor_a_user = uuid.uuid4()
        gestor_b_user = uuid.uuid4()
        gestor_a = Gestor(
            id=uuid.uuid4(), user_id=gestor_a_user, cedula=str(uuid.uuid4().int)[:10],
            nombre="Gestor", apellidos="A", telefono="3000000001", direccion="Calle A",
            correo_electronico=f"a{uuid.uuid4().hex[:6]}@test.com",
        )
        gestor_b = Gestor(
            id=uuid.uuid4(), user_id=gestor_b_user, cedula=str(uuid.uuid4().int)[:10],
            nombre="Gestor", apellidos="B", telefono="3000000002", direccion="Calle B",
            correo_electronico=f"b{uuid.uuid4().hex[:6]}@test.com",
        )
        cliente_a = _mk_cliente(gestor_id=gestor_a.id)
        cliente_b = _mk_cliente(gestor_id=gestor_b.id)
        credito_a = _mk_credito(cliente_a.id)
        credito_b = _mk_credito(cliente_b.id)
        pago_a = _mk_pago(credito_a.id, fecha_maxima=date(2026, 10, 15), veces_aplazado=1)
        pago_b = _mk_pago(credito_b.id, fecha_maxima=date(2026, 10, 20), veces_aplazado=1)
        db_session.add_all([
            gestor_a, gestor_b, cliente_a, cliente_b, credito_a, credito_b, pago_a, pago_b,
        ])
        await db_session.flush()

        gestor_user = MagicMock(spec=Usuario)
        gestor_user.id = gestor_a_user
        gestor_user.tipo_usuario = TipoUsuario.gestor
        gestor_user.activo = True
        gestor_user.deleted_at = None
        client = await client_factory(gestor_user)

        r = await client.get("/api/v1/pagos/aplazados")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(pago_a.id)

    @pytest.mark.asyncio
    async def test_veces_aplazado_zero_and_soft_deleted_excluded(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago_nunca_aplazado = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 15), veces_aplazado=0, numero_cuota=1)
        pago_aplazado = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 16), veces_aplazado=1, numero_cuota=2)
        from datetime import datetime, timezone
        pago_borrado = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 17), veces_aplazado=1, numero_cuota=3)
        pago_borrado.deleted_at = datetime.now(timezone.utc)
        db_session.add_all([cliente, credito, pago_nunca_aplazado, pago_aplazado, pago_borrado])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.get("/api/v1/pagos/aplazados")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(pago_aplazado.id)

    @pytest.mark.asyncio
    async def test_operationally_closed_credit_excluded(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito_cerrado = _mk_credito(cliente.id, activo=False)
        credito_abierto = _mk_credito(cliente.id)
        pago_cerrado = _mk_pago(
            credito_cerrado.id, fecha_maxima=date(2026, 10, 15), veces_aplazado=1, numero_cuota=1,
        )
        pago_abierto = _mk_pago(
            credito_abierto.id, fecha_maxima=date(2026, 10, 20), veces_aplazado=1, numero_cuota=1,
        )
        db_session.add_all([cliente, credito_cerrado, credito_abierto, pago_cerrado, pago_abierto])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r = await client.get("/api/v1/pagos/aplazados")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(pago_abierto.id)

    @pytest.mark.asyncio
    async def test_pagination_sort_and_busqueda_contract(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago1 = _mk_pago(credito.id, fecha_maxima=date(2026, 10, 15), veces_aplazado=1, numero_cuota=1)
        pago2 = _mk_pago(credito.id, fecha_maxima=date(2026, 11, 15), veces_aplazado=1, numero_cuota=2)
        db_session.add_all([cliente, credito, pago1, pago2])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r_desc = await client.get("/api/v1/pagos/aplazados", params={"sort_dir": "desc"})
        assert r_desc.status_code == 200, r_desc.text
        body_desc = r_desc.json()
        assert body_desc["total"] == 2
        assert body_desc["pages"] == 1
        assert body_desc["page_size"] == 50
        assert [item["id"] for item in body_desc["items"]] == [str(pago2.id), str(pago1.id)]

        r_bad_page_size = await client.get("/api/v1/pagos/aplazados", params={"page_size": 51})
        assert r_bad_page_size.status_code == 422

        r_busqueda = await client.get(
            "/api/v1/pagos/aplazados", params={"busqueda": cliente.nombre},
        )
        assert r_busqueda.status_code == 200, r_busqueda.text
        assert r_busqueda.json()["total"] == 2

        r_busqueda_vacia = await client.get(
            "/api/v1/pagos/aplazados", params={"busqueda": "NombreQueNoExiste"},
        )
        assert r_busqueda_vacia.status_code == 200, r_busqueda_vacia.text
        assert r_busqueda_vacia.json()["total"] == 0


# ---------------------------------------------------------------------------
# Double Visualization
# ---------------------------------------------------------------------------

class TestDoubleVisualization:
    @pytest.mark.asyncio
    async def test_present_in_both_views(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 11, 10), veces_aplazado=1, momento="m2")
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        r1 = await client.get(
            "/api/v1/pagos", params={"anio": 2026, "mes": 11},
        )
        assert r1.status_code == 200, r1.text
        items1 = r1.json()["items"]
        assert len(items1) == 1
        assert items1[0]["veces_aplazado"] == 1

        r2 = await client.get("/api/v1/pagos/aplazados")
        assert r2.status_code == 200, r2.text
        assert r2.json()["items"][0]["veces_aplazado"] == 1
