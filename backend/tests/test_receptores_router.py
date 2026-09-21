"""
tests/test_receptores_router.py — Rutas base de receptores (GET/POST /receptores).

Covers: listado paginado con `items/total/page/page_size/pages` y cuentas
anidadas; filtro `busqueda` parcial e insensible a mayúsculas sobre nombre;
`page_size` > 50 -> 422; creación 201 y visible en el listado posterior;
roles registrador/gestor -> 403 en ambas rutas. Fixtures copiadas de
test_cuentas_bancarias_predeterminada.py.
"""
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.usuario import TipoUsuario, Usuario


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


def _mk_receptor(nombre: str | None = None) -> Receptor:
    return Receptor(
        id=uuid.uuid4(), nombre=nombre or f"Receptor {uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
    )


def _mk_cuenta(receptor_id: uuid.UUID, *, etiqueta="A", predeterminada=False) -> CuentaBancaria:
    return CuentaBancaria(
        id=uuid.uuid4(), receptor_id=receptor_id, entidad_bancaria=etiqueta,
        tipo_cuenta=TipoCuenta.ahorros, numero_cuenta=f"{etiqueta}1",
        es_predeterminada=predeterminada,
    )


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


@pytest.mark.asyncio
async def test_listar_receptores_pagina_con_cuentas_anidadas(client_factory, db_session):
    marca = uuid.uuid4().hex[:8]
    receptor_a = _mk_receptor(f"Alfa {marca}")
    receptor_b = _mk_receptor(f"Beta {marca}")
    cuenta = _mk_cuenta(receptor_a.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor_a, receptor_b, cuenta])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get("/api/v1/receptores", params={"busqueda": marca})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"items", "total", "page", "page_size", "pages"}
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["pages"] == 1
    assert [r["id"] for r in body["items"]] == [str(receptor_a.id), str(receptor_b.id)]
    cuentas_a = body["items"][0]["cuentas_bancarias"]
    assert [c["id"] for c in cuentas_a] == [str(cuenta.id)]
    assert cuentas_a[0]["es_predeterminada"] is True
    assert body["items"][1]["cuentas_bancarias"] == []


@pytest.mark.asyncio
async def test_listar_receptores_busqueda_parcial_por_nombre(client_factory, db_session):
    marca = uuid.uuid4().hex[:8]
    coincide = _mk_receptor(f"Carolina {marca}")
    no_coincide = _mk_receptor(f"Roberto {marca}")
    db_session.add_all([coincide, no_coincide])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get("/api/v1/receptores", params={"busqueda": f"CAROL"})

    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["items"]]
    assert str(coincide.id) in ids
    assert str(no_coincide.id) not in ids


@pytest.mark.asyncio
async def test_listar_receptores_page_size_mayor_a_50_devuelve_422(client_factory):
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get("/api/v1/receptores", params={"page_size": 51})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_crear_receptor_devuelve_201_y_aparece_en_listado(client_factory):
    marca = uuid.uuid4().hex[:8]
    payload = {
        "nombre": f"Nuevo {marca}",
        "cedula": str(uuid.uuid4().int)[:10],
        "telefono": "3111111111",
    }

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post("/api/v1/receptores", json=payload)

    assert resp.status_code == 201
    body = resp.json()
    assert body["nombre"] == payload["nombre"]
    assert body["cedula"] == payload["cedula"]
    assert body["telefono"] == payload["telefono"]
    assert body["cuentas_bancarias"] == []
    assert "id" in body

    listado = await client.get("/api/v1/receptores", params={"busqueda": marca})
    assert listado.status_code == 200
    assert [r["id"] for r in listado.json()["items"]] == [body["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor])
async def test_roles_sin_permiso_reciben_403_en_listar_y_crear(client_factory, rol):
    client = await client_factory(_mk_user(rol))

    resp_get = await client.get("/api/v1/receptores")
    resp_post = await client.post(
        "/api/v1/receptores",
        json={"nombre": "Sin permiso", "cedula": "1234567", "telefono": "3000000000"},
    )

    assert resp_get.status_code == 403
    assert resp_post.status_code == 403
