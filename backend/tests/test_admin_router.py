"""
tests/test_admin_router.py — Tests de acceso al endpoint de migración admin-only.

T-15: Verifica que:
- Un usuario no-admin (recaudador) recibe 403 Forbidden.
- Un usuario admin recibe 200 con la estructura de resumen esperada.

Estrategia: override de get_current_user para simular roles sin pasar
por JWT real. La lógica de negocio (recálculo) se testea con DB vacía —
el resultado válido es total_revisados=0, total_corregidos=0, corregidos=[].
"""
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.dependencies import get_current_user
from app.main import app
from app.models.usuario import TipoUsuario, Usuario

API_PREFIX = "/api/v1"
ENDPOINT = f"{API_PREFIX}/admin/migracion/recalcular-saldos"


# ---------------------------------------------------------------------------
# Helpers: fabricar usuarios mock
# ---------------------------------------------------------------------------

def make_usuario(tipo: TipoUsuario) -> Usuario:
    u = MagicMock(spec=Usuario)
    u.id = uuid.uuid4()
    u.tipo_usuario = tipo
    u.activo = True
    u.deleted_at = None
    return u


# ---------------------------------------------------------------------------
# Fixtures: clientes HTTP con rol inyectado
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client_recaudador(db_session):
    """Cliente HTTP autenticado como recaudador."""
    usuario = make_usuario(TipoUsuario.recaudador)

    async def override_user():
        return usuario

    app.dependency_overrides[get_current_user] = override_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def client_admin(db_session):
    """Cliente HTTP autenticado como admin, con get_db apuntando a la DB de test."""
    from app.database import get_db
    usuario = make_usuario(TipoUsuario.admin)

    async def override_user():
        return usuario

    async def override_db():
        yield db_session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# T-15: Tests de control de acceso
# ---------------------------------------------------------------------------

class TestRecalcularSaldosAcceso:
    """Verifica que el endpoint de migración aplica require_role("admin")."""

    @pytest.mark.asyncio
    async def test_recaudador_recibe_403(self, client_recaudador: AsyncClient):
        """Usuario con rol recaudador debe recibir 403 Forbidden."""
        response = await client_recaudador.post(ENDPOINT)
        assert response.status_code == 403, (
            f"Esperado 403 para recaudador, recibido {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_admin_recibe_200(self, client_admin: AsyncClient):
        """Usuario admin debe recibir 200 con estructura de resumen válida."""
        response = await client_admin.post(ENDPOINT)
        assert response.status_code == 200, (
            f"Esperado 200 para admin, recibido {response.status_code}: {response.text}"
        )
        data = response.json()
        # Verificar estructura del resumen
        assert "total_revisados" in data, "Respuesta debe incluir total_revisados"
        assert "total_corregidos" in data, "Respuesta debe incluir total_corregidos"
        assert "corregidos" in data, "Respuesta debe incluir lista corregidos"
        assert isinstance(data["total_revisados"], int)
        assert isinstance(data["total_corregidos"], int)
        assert isinstance(data["corregidos"], list)

    @pytest.mark.asyncio
    async def test_admin_resumen_contadores_consistentes(self, client_admin: AsyncClient):
        """
        Los contadores del resumen deben ser internamente consistentes:
        total_corregidos <= total_revisados y len(corregidos) == total_corregidos.
        No asumimos cantidad exacta porque la DB de test es de scope=session.
        """
        response = await client_admin.post(ENDPOINT)
        assert response.status_code == 200
        data = response.json()
        assert data["total_corregidos"] <= data["total_revisados"], (
            "total_corregidos no puede superar total_revisados"
        )
        assert len(data["corregidos"]) == data["total_corregidos"], (
            "len(corregidos) debe coincidir con total_corregidos"
        )
        # Verificar estructura de cada detalle si hay corregidos
        for detalle in data["corregidos"]:
            assert "credito_id" in detalle
            assert "numero_credito" in detalle
            assert "saldo_capital" in detalle and len(detalle["saldo_capital"]) == 2
            assert "saldo_intereses" in detalle and len(detalle["saldo_intereses"]) == 2
