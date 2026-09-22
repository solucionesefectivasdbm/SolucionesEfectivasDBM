"""
tests/test_gestores_busqueda.py — Filtro `busqueda` de GET /gestores.

Covers: búsqueda parcial e insensible a mayúsculas sobre nombre, apellidos y
cédula; varios tokens exigen que TODOS aparezcan (aunque estén en columnas
distintas); `total` respeta el filtro (el count comparte la misma condición
que el query de items). Fixtures copiadas de
test_gestores_cuenta_bancaria.py.
"""
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.gestor import Gestor
from app.models.usuario import TipoUsuario, Usuario


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


def _mk_usuario_gestor() -> Usuario:
    return Usuario(
        id=uuid.uuid4(), username=f"gestor{uuid.uuid4().hex[:8]}",
        password_hash="x", telefono="3000000000",
        tipo_usuario=TipoUsuario.gestor, activo=True,
    )


def _mk_gestor(*, user_id: uuid.UUID, nombre: str, apellidos: str, cedula: str | None = None) -> Gestor:
    return Gestor(
        id=uuid.uuid4(), user_id=user_id, cedula=cedula or str(uuid.uuid4().int)[:10],
        nombre=nombre, apellidos=apellidos, telefono="3000000000",
        direccion="Calle 1", correo_electronico=f"{uuid.uuid4().hex[:8]}@test.com",
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


async def _sembrar(db_session, *gestores: Gestor) -> None:
    usuarios = [_mk_usuario_gestor() for _ in gestores]
    for gestor, usuario in zip(gestores, usuarios):
        gestor.user_id = usuario.id
    db_session.add_all([*usuarios, *gestores])
    await db_session.flush()


@pytest.mark.asyncio
async def test_busqueda_parcial_por_cedula(client_factory, db_session):
    marca = uuid.uuid4().hex[:8]
    coincide = _mk_gestor(user_id=uuid.uuid4(), nombre=f"Ana {marca}", apellidos="Uno",
                          cedula=f"99{uuid.uuid4().int % 10**8:08d}")
    no_coincide = _mk_gestor(user_id=uuid.uuid4(), nombre=f"Luis {marca}", apellidos="Dos")
    await _sembrar(db_session, coincide, no_coincide)

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get("/api/v1/gestores", params={"busqueda": coincide.cedula})

    assert resp.status_code == 200
    ids = [g["id"] for g in resp.json()["items"]]
    assert ids == [str(coincide.id)]


@pytest.mark.asyncio
async def test_busqueda_insensible_a_mayusculas_por_apellidos(client_factory, db_session):
    marca = uuid.uuid4().hex[:8]
    coincide = _mk_gestor(user_id=uuid.uuid4(), nombre="Ana", apellidos=f"Mattos{marca}")
    no_coincide = _mk_gestor(user_id=uuid.uuid4(), nombre="Ana", apellidos=f"Sanabria{marca}")
    await _sembrar(db_session, coincide, no_coincide)

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get("/api/v1/gestores", params={"busqueda": f"MATTOS{marca.upper()}"})

    assert resp.status_code == 200
    ids = [g["id"] for g in resp.json()["items"]]
    assert ids == [str(coincide.id)]


@pytest.mark.asyncio
async def test_busqueda_varios_tokens_cruza_nombre_y_apellidos(client_factory, db_session):
    """El caso que el patrón viejo (OR simple sobre el texto completo) no cubría."""
    marca = uuid.uuid4().hex[:8]
    coincide = _mk_gestor(user_id=uuid.uuid4(), nombre=f"Carolina{marca}", apellidos=f"Mattos{marca}")
    no_coincide = _mk_gestor(user_id=uuid.uuid4(), nombre=f"Carolina{marca}", apellidos=f"Sanabria{marca}")
    await _sembrar(db_session, coincide, no_coincide)

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(
        "/api/v1/gestores", params={"busqueda": f"carolina{marca} mattos{marca}"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [g["id"] for g in body["items"]] == [str(coincide.id)]
    # El count comparte la condición del query de items.
    assert body["total"] == 1
