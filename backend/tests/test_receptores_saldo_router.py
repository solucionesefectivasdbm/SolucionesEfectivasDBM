"""
tests/test_receptores_saldo_router.py — GET /receptores/saldos,
GET /receptores/{id}/saldo, GET /receptores/{id}/movimientos (item 9,
receiver-cash-balance, PR 1 — read-only ledger foundation).

Covers: roles (admin/recaudador 200, registrador/gestor 403), 404 on an
unknown or soft-deleted receptor, pagination shape on movimientos, and the
CRITICAL route-ordering case — GET /receptores/saldos MUST be registered
BEFORE GET /receptores/{receptor_id}, or the UUID path param shadows it
and FastAPI tries to parse "saldos" as a UUID, returning 422 instead of 200.
"""
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.receptor_movimiento import MovimientoReceptor, TipoMovimiento
from app.models.usuario import TipoUsuario, Usuario
from app.utils.fechas import ahora_bogota

RECEPTORES_URL = "/api/v1/receptores"


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


def _mk_receptor(**kwargs) -> Receptor:
    defaults = dict(
        id=uuid.uuid4(), nombre=f"Receptor {uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
    )
    defaults.update(kwargs)
    return Receptor(**defaults)


def _mk_cuenta(receptor_id: uuid.UUID, **kwargs) -> CuentaBancaria:
    defaults = dict(
        id=uuid.uuid4(), receptor_id=receptor_id, entidad_bancaria="Banco",
        tipo_cuenta=TipoCuenta.ahorros, numero_cuenta=uuid.uuid4().hex[:6],
        es_predeterminada=False,
    )
    defaults.update(kwargs)
    return CuentaBancaria(**defaults)


def _mk_usuario_real(**kwargs) -> Usuario:
    """A REAL (persisted) Usuario row — distinct from the mocked
    current_user used for auth — needed as the FK target for seeded
    MovimientoReceptor rows so `usuario_nombre` resolves via the join."""
    defaults = dict(
        id=uuid.uuid4(), username=f"actor{uuid.uuid4().hex[:6]}", password_hash="x",
        telefono="3000000000", tipo_usuario=TipoUsuario.admin,
    )
    defaults.update(kwargs)
    return Usuario(**defaults)


@pytest_asyncio.fixture
async def client_factory(db_session):
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


# ─── Route ordering (critical — task 1.8) ──────────────────────────────────

@pytest.mark.asyncio
async def test_ruta_saldos_no_es_eclipsada_por_receptor_id(client_factory):
    """If `/receptores/saldos` were registered AFTER
    `/receptores/{receptor_id}`, FastAPI would try to parse "saldos" as a
    UUID path param and return 422 instead of dispatching to this route."""
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(RECEPTORES_URL + "/saldos", params={"receptor_ids": str(uuid.uuid4())})
    assert resp.status_code == 200


# ─── GET /receptores/saldos ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_saldos_devuelve_saldo_por_receptor(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id, es_predeterminada=True)
    db_session.add_all([receptor, cuenta])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(RECEPTORES_URL + "/saldos", params={"receptor_ids": str(receptor.id)})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["receptor_id"] == str(receptor.id)
    assert Decimal(str(body[0]["saldo_total"])) == Decimal("0.00")
    assert len(body[0]["por_cuenta"]) == 1
    assert body[0]["por_cuenta"][0]["cuenta_bancaria_id"] == str(cuenta.id)


@pytest.mark.asyncio
async def test_saldos_receptor_desconocido_devuelve_saldo_cero_sin_error(client_factory):
    """The plural endpoint is a bulk lookup, not an existence check
    (that's the singular endpoint's job — see 404 tests below): an unknown
    id simply has no cuentas, so its saldo is 0."""
    client = await client_factory(_mk_user(TipoUsuario.admin))
    receptor_id = uuid.uuid4()
    resp = await client.get(RECEPTORES_URL + "/saldos", params={"receptor_ids": str(receptor_id)})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["receptor_id"] == str(receptor_id)
    assert Decimal(str(body[0]["saldo_total"])) == Decimal("0.00")
    assert body[0]["por_cuenta"] == []


@pytest.mark.asyncio
async def test_saldos_receptor_id_malformado_devuelve_422(client_factory):
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(RECEPTORES_URL + "/saldos", params={"receptor_ids": "no-es-un-uuid"})
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", [TipoUsuario.admin, TipoUsuario.recaudador])
async def test_saldos_permitido_para_admin_y_recaudador(client_factory, rol):
    client = await client_factory(_mk_user(rol))
    resp = await client.get(RECEPTORES_URL + "/saldos", params={"receptor_ids": str(uuid.uuid4())})
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor])
async def test_saldos_rechazado_para_registrador_y_gestor(client_factory, rol):
    client = await client_factory(_mk_user(rol))
    resp = await client.get(RECEPTORES_URL + "/saldos", params={"receptor_ids": str(uuid.uuid4())})
    assert resp.status_code == 403


# ─── GET /receptores/{id}/saldo ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_obtener_saldo_receptor_existente(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id)
    db_session.add_all([receptor, cuenta])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/saldo")

    assert resp.status_code == 200
    body = resp.json()
    assert body["receptor_id"] == str(receptor.id)
    assert len(body["por_cuenta"]) == 1


@pytest.mark.asyncio
async def test_obtener_saldo_receptor_desconocido_404(client_factory):
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(f"{RECEPTORES_URL}/{uuid.uuid4()}/saldo")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_obtener_saldo_receptor_soft_deleted_404(client_factory, db_session):
    receptor = _mk_receptor()
    db_session.add(receptor)
    await db_session.flush()
    receptor.deleted_at = ahora_bogota()
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/saldo")
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor])
async def test_obtener_saldo_rechazado_para_roles_sin_permiso(client_factory, db_session, rol):
    receptor = _mk_receptor()
    db_session.add(receptor)
    await db_session.flush()

    client = await client_factory(_mk_user(rol))
    resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/saldo")
    assert resp.status_code == 403


# ─── GET /receptores/{id}/movimientos ───────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_movimientos_forma_de_paginacion(client_factory, db_session):
    actor = _mk_usuario_real()
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id)
    db_session.add_all([actor, receptor, cuenta])
    await db_session.flush()
    for _ in range(3):
        db_session.add(MovimientoReceptor(
            id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.correccion,
            monto=Decimal("10.00"), usuario_id=actor.id,
        ))
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.recaudador))
    resp = await client.get(
        f"{RECEPTORES_URL}/{receptor.id}/movimientos", params={"page": 1, "page_size": 2},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"items", "total", "page", "page_size", "pages"}
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["usuario_nombre"] == actor.username


@pytest.mark.asyncio
async def test_listar_movimientos_receptor_desconocido_404(client_factory):
    client = await client_factory(_mk_user(TipoUsuario.recaudador))
    resp = await client.get(f"{RECEPTORES_URL}/{uuid.uuid4()}/movimientos")
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor])
async def test_listar_movimientos_rechazado_para_roles_sin_permiso(client_factory, db_session, rol):
    receptor = _mk_receptor()
    db_session.add(receptor)
    await db_session.flush()

    client = await client_factory(_mk_user(rol))
    resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/movimientos")
    assert resp.status_code == 403
