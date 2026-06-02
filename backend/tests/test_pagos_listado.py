"""
tests/test_pagos_listado.py — Listado de pagos optimizado.

Cubre:
- _pago_row_a_dict: mapea cada columna al campo correcto de PagoResponse,
  sin perder ni alterar datos (la optimización debe preservar la salida).
- Smoke de integración: la query de solo-columnas compila y ejecuta vía HTTP.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.pago import DestinoExcedente, TipoCuota
from app.models.usuario import TipoUsuario, Usuario
from app.routers.pagos import _pago_row_a_dict
from app.schemas.pago import PagoResponse


def _fake_row(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        credito_id=uuid.uuid4(),
        numero_cuota=3,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=Decimal("100462.13"),
        capital_a_pagar=Decimal("70462.13"),
        interes_a_pagar=Decimal("30000.00"),
        capital_pagado=Decimal("0.00"),
        interes_pagado=Decimal("0.00"),
        momento="m3",
        fecha_maxima=date(2026, 3, 10),
        receptor_id=None,
        pagado=False,
        validado_recaudador=False,
        fecha_pago_real=None,
        es_excedente_a=None,
        es_ultimo_pago=False,
        tipo_validacion=None,
        cliente_nombre="Juan",
        cliente_apellidos="Pérez",
        numero_credito_cliente="Juan Pérez-CR-001",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPagoRowADict:
    def test_dict_cubre_todos_los_campos_de_response(self):
        """El dict debe traer todos los campos que PagoResponse necesita."""
        d = _pago_row_a_dict(_fake_row())
        requeridos = set(PagoResponse.model_fields.keys())
        faltantes = requeridos - set(d.keys())
        assert not faltantes, f"Faltan campos en el dict: {faltantes}"

    def test_round_trip_preserva_valores(self):
        """El dict valida como PagoResponse sin alterar datos."""
        row = _fake_row()
        resp = PagoResponse.model_validate(_pago_row_a_dict(row))
        assert resp.id == row.id
        assert resp.credito_id == row.credito_id
        assert resp.numero_cuota == 3
        assert resp.tipo_cuota == TipoCuota.programada
        assert resp.monto_a_pagar == Decimal("100462.13")
        assert resp.cliente_nombre == "Juan Pérez"
        assert resp.numero_credito_cliente == "Juan Pérez-CR-001"
        assert resp.es_proyectada is False
        assert resp.razon_bloqueo is None

    def test_excedente_y_receptor_se_mapean(self):
        receptor = uuid.uuid4()
        row = _fake_row(
            es_excedente_a=DestinoExcedente.capital,
            receptor_id=receptor,
            pagado=True,
        )
        resp = PagoResponse.model_validate(_pago_row_a_dict(row))
        assert resp.es_excedente_a == DestinoExcedente.capital
        assert resp.receptor_id == receptor
        assert resp.pagado is True


@pytest_asyncio.fixture
async def client_admin_db(db_session):
    """Cliente HTTP como admin, con get_db apuntando a la sesión de test."""
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
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestListarPagosIntegracion:
    @pytest.mark.asyncio
    async def test_listado_db_vacia_responde_200_vacio(self, client_admin_db: AsyncClient):
        """La query de solo-columnas compila y ejecuta; sin datos devuelve vacío."""
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0
