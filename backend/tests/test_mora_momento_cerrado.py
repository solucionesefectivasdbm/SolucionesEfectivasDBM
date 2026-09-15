"""
tests/test_mora_momento_cerrado.py — Overdue evaluation at momento close
(scheduled-overdue-evaluation change).

Covers:
- GET /pagos/alertas/vencidos: counts only `en_mora` (momento cerrado)
- GET /clientes and GET /clientes/{id}: `al_dia` uses the same predicate
- GET /pagos: `vencido`/`en_mora` flags on real, virtual, deferred and
  partial rows
- GET /creditos/{id}/cuotas: same `vencido`/`en_mora` flags per cuota

Fixtures copied/adapted from test_aplazamientos.py; `fijar_hoy` comes from
conftest.py (design decision 4).
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

_FAKE_GESTOR_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _mk_cliente(**kw) -> Cliente:
    defaults = dict(
        id=uuid.uuid4(), gestor_id=_FAKE_GESTOR_ID, nombre="Ana",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )
    defaults.update(kw)
    return Cliente(**defaults)


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


def _mk_pago(credito_id: uuid.UUID, **kw) -> Pago:
    defaults = dict(
        id=uuid.uuid4(), numero_cuota=1, tipo_cuota=TipoCuota.programada,
        monto_a_pagar=Decimal("110000.00"), capital_a_pagar=Decimal("100000.00"),
        interes_a_pagar=Decimal("10000.00"), capital_pagado=Decimal("0.00"),
        interes_pagado=Decimal("0.00"), momento="m1", fecha_maxima=date(2026, 3, 27),
        pagado=False, validado_recaudador=False, veces_aplazado=0,
    )
    defaults.update(kw)
    return Pago(credito_id=credito_id, **defaults)


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


# ---------------------------------------------------------------------------
# GET /pagos/alertas/vencidos — solo en_mora (momento cerrado)
# ---------------------------------------------------------------------------

class TestAlertasVencidosMomentoCerrado:
    @pytest.mark.asyncio
    async def test_momento_abierto_no_lista(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 3, 27))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 29))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pagos"] == []
        assert body["total_pagos_vencidos"] == 0

    @pytest.mark.asyncio
    async def test_momento_cerrado_lista_con_flags(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 3, 27))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 30))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["pagos"]) == 1
        assert body["pagos"][0]["en_mora"] is True
        assert body["pagos"][0]["vencido"] is True
        assert body["total_pagos_vencidos"] == 1

    @pytest.mark.asyncio
    async def test_cruce_de_mes_m2(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 4, 2), momento="m2")
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(_mk_user(TipoUsuario.admin))

        fijar_hoy(date(2026, 4, 4))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert r.json()["pagos"] == []

        fijar_hoy(date(2026, 4, 5))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert len(r.json()["pagos"]) == 1

    @pytest.mark.asyncio
    async def test_alerta_vencidos_excluye_credito_saldado(self, client_factory, db_session, fijar_hoy):
        """
        Re-pin de test_pagos_router.py::test_alerta_vencidos_excluye_credito_saldado:
        con fecha_maxima = hoy_bogota() - 1 día se volvía vacuo (casi siempre
        sigue en el mismo momento). Se fija un `hoy` donde el pago está
        claramente en_mora, para que la exclusión por crédito saldado siga
        siendo significativa.
        """
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 3, 27))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 30))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert r.status_code == 200, r.text
        ids = [p["credito_id"] for p in r.json()["pagos"]]
        assert str(credito.id) not in ids

    @pytest.mark.asyncio
    async def test_deferred_row_evaluated_on_current_date(self, client_factory, db_session, fijar_hoy):
        """Aplazado (veces_aplazado>0) evaluado solo por su fecha_maxima actual."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 4, 10), veces_aplazado=1, momento="m3")
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(_mk_user(TipoUsuario.admin))

        fijar_hoy(date(2026, 4, 13))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert r.json()["pagos"] == []

        fijar_hoy(date(2026, 4, 14))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert len(r.json()["pagos"]) == 1

    @pytest.mark.asyncio
    async def test_partial_payment_counts_as_unpaid(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(
            credito.id, fecha_maxima=date(2026, 3, 27),
            capital_pagado=Decimal("50000.00"), pagado=False,
        )
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 30))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get("/api/v1/pagos/alertas/vencidos")
        assert r.status_code == 200, r.text
        assert len(r.json()["pagos"]) == 1
        assert r.json()["pagos"][0]["en_mora"] is True


# ---------------------------------------------------------------------------
# GET /clientes?al_dia= and GET /clientes/{id} — mismo predicado
# ---------------------------------------------------------------------------

class TestClientesAlDiaMomentoCerrado:
    @pytest.mark.asyncio
    async def test_al_dia_dentro_del_momento(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 3, 27))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 29))

        client = await client_factory(_mk_user(TipoUsuario.admin))

        r_list = await client.get("/api/v1/clientes", params={"al_dia": True})
        assert r_list.status_code == 200, r_list.text
        ids = [c["id"] for c in r_list.json()["items"]]
        assert str(cliente.id) in ids

        r_detail = await client.get(f"/api/v1/clientes/{cliente.id}")
        assert r_detail.status_code == 200, r_detail.text
        assert r_detail.json()["al_dia"] is True

    @pytest.mark.asyncio
    async def test_en_atraso_tras_cierre(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 3, 27))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 30))

        client = await client_factory(_mk_user(TipoUsuario.admin))

        r_list_true = await client.get("/api/v1/clientes", params={"al_dia": True})
        ids_true = [c["id"] for c in r_list_true.json()["items"]]
        assert str(cliente.id) not in ids_true

        r_list_false = await client.get("/api/v1/clientes", params={"al_dia": False})
        ids_false = [c["id"] for c in r_list_false.json()["items"]]
        assert str(cliente.id) in ids_false

        r_list_all = await client.get("/api/v1/clientes")
        item = next(c for c in r_list_all.json()["items"] if c["id"] == str(cliente.id))
        assert item["al_dia"] is False

        r_detail = await client.get(f"/api/v1/clientes/{cliente.id}")
        assert r_detail.json()["al_dia"] is False


# ---------------------------------------------------------------------------
# GET /pagos — vencido/en_mora en filas reales y virtuales
# ---------------------------------------------------------------------------

class TestPagoResponseFlagsMora:
    @pytest.mark.asyncio
    async def test_listar_pagos_flags(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 3, 27))
        pago_pagado = _mk_pago(
            credito.id, numero_cuota=2, fecha_maxima=date(2026, 3, 5),
            pagado=True, capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("10000.00"),
        )
        db_session.add_all([cliente, credito, pago, pago_pagado])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 28))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get("/api/v1/pagos", params={"anio": 2026, "mes": 3})
        assert r.status_code == 200, r.text
        items = r.json()["items"]

        item = next(i for i in items if i["id"] == str(pago.id))
        assert item["vencido"] is True
        assert item["en_mora"] is False

        item_pagado = next(i for i in items if i["id"] == str(pago_pagado.id))
        assert item_pagado["vencido"] is False
        assert item_pagado["en_mora"] is False

    @pytest.mark.asyncio
    async def test_virtual_row_flags_false(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, fecha_inicial_pago=date(2026, 2, 1))
        # Cuota #1 pendiente (bloqueadora); crédito sin anchor -> fallback
        # +30d, así que la cuota #2 se proyecta para el 3 de marzo de 2026.
        pago1 = _mk_pago(credito.id, numero_cuota=1, fecha_maxima=date(2026, 2, 1), pagado=False)
        db_session.add_all([cliente, credito, pago1])
        await db_session.flush()
        fijar_hoy(date(2026, 9, 15))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get("/api/v1/pagos", params={"anio": 2026, "mes": 3})
        assert r.status_code == 200, r.text
        virtuales = [item for item in r.json()["items"] if item["es_proyectada"]]
        assert len(virtuales) >= 1
        assert all(v["vencido"] is False and v["en_mora"] is False for v in virtuales)

    @pytest.mark.asyncio
    async def test_aplazados_flags(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 3, 27), veces_aplazado=1)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 30))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get("/api/v1/pagos/aplazados")
        assert r.status_code == 200, r.text
        item = next(i for i in r.json()["items"] if i["id"] == str(pago.id))
        assert item["vencido"] is True
        assert item["en_mora"] is True


# ---------------------------------------------------------------------------
# GET /creditos/{id}/cuotas — vencido/en_mora por cuota
# ---------------------------------------------------------------------------

class TestHistorialCuotasFlagsMora:
    @pytest.mark.asyncio
    async def test_historial_cuotas_flags(self, client_factory, db_session, fijar_hoy):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        # cuota 1: momento cerrado (m5 marzo) -> vencida y en mora
        pago_mora = _mk_pago(credito.id, numero_cuota=1, fecha_maxima=date(2026, 3, 27))
        # cuota 2: vencida dentro del momento abierto (m1 abre el 30) -> no en mora
        pago_vencido = _mk_pago(credito.id, numero_cuota=2, fecha_maxima=date(2026, 3, 30))
        # cuota 3: pagada -> nunca vencida ni en mora
        pago_pagado = _mk_pago(
            credito.id, numero_cuota=3, fecha_maxima=date(2026, 3, 5),
            pagado=True, capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("10000.00"),
        )
        db_session.add_all([cliente, credito, pago_mora, pago_vencido, pago_pagado])
        await db_session.flush()
        fijar_hoy(date(2026, 3, 31))

        client = await client_factory(_mk_user(TipoUsuario.admin))
        r = await client.get(f"/api/v1/creditos/{credito.id}/cuotas")
        assert r.status_code == 200, r.text
        por_id = {i["id"]: i for i in r.json()}

        assert por_id[str(pago_mora.id)]["vencido"] is True
        assert por_id[str(pago_mora.id)]["en_mora"] is True
        assert por_id[str(pago_vencido.id)]["vencido"] is True
        assert por_id[str(pago_vencido.id)]["en_mora"] is False
        assert por_id[str(pago_pagado.id)]["vencido"] is False
        assert por_id[str(pago_pagado.id)]["en_mora"] is False
