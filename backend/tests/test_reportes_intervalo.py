"""
tests/test_reportes_intervalo.py — `GET /reportes/ingresos`, modo por
intervalo (`fecha_desde`/`fecha_hasta`) y validación de `resolver_ventana`
(reportes-cartera-vencida-y-rango-fechas, design D2/D9).

Req: Two Mutually Exclusive Filter Modes.
Req: Ingresos Report Structure Unchanged (interval mode aggregation).
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.cliente import Cliente
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

INGRESOS_URL = "/api/v1/reportes/ingresos"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Intervalo", apellidos=f"Test{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Intervalo-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )


def _mk_pago(
    credito_id: uuid.UUID, numero_cuota: int, fecha_maxima: date,
    capital: Decimal, interes: Decimal, *, pagado: bool,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=numero_cuota,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=capital + interes,
        capital_a_pagar=capital, interes_a_pagar=interes,
        capital_pagado=capital if pagado else Decimal("0.00"),
        interes_pagado=interes if pagado else Decimal("0.00"),
        momento="m3", fecha_maxima=fecha_maxima,
        pagado=pagado, validado_recaudador=pagado, es_ultimo_pago=False,
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


@pytest.mark.asyncio
async def test_modo_momento_resuelve_igual_que_get_periodo_momento(client_admin_db):
    """Scenario: Momento mode resolves as today."""
    resp = await client_admin_db.get(
        INGRESOS_URL, params={"anio": 2026, "mes": 9, "momento": "m1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fecha_inicio"] == "2026-09-25"
    assert body["fecha_fin"] == "2026-09-29"
    assert body["anio"] == 2026
    assert body["mes"] == 9
    assert body["momento"] == "m1"


@pytest.mark.asyncio
async def test_modo_intervalo_usa_los_limites_crudos(client_admin_db):
    """Scenario: Interval mode uses the raw bounds."""
    resp = await client_admin_db.get(
        INGRESOS_URL,
        params={"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-15"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fecha_inicio"] == "2026-09-01"
    assert body["fecha_fin"] == "2026-09-15"
    assert body["anio"] is None
    assert body["mes"] is None
    assert body["momento"] is None


@pytest.mark.asyncio
async def test_ambos_modos_es_rechazado(client_admin_db):
    """Scenario: Both modes supplied is rejected."""
    resp = await client_admin_db.get(
        INGRESOS_URL,
        params={
            "anio": 2026, "mes": 9, "momento": "m1",
            "fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-15",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ningun_modo_es_rechazado(client_admin_db):
    """Scenario: Neither mode supplied is rejected."""
    resp = await client_admin_db.get(INGRESOS_URL)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_momento_parcial_es_rechazado(client_admin_db):
    """Design Validation rules: partial momento (anio+mes sin momento)."""
    resp = await client_admin_db.get(INGRESOS_URL, params={"anio": 2026, "mes": 9})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_intervalo_parcial_es_rechazado(client_admin_db):
    """Design Validation rules: partial interval (solo fecha_desde)."""
    resp = await client_admin_db.get(
        INGRESOS_URL, params={"fecha_desde": "2026-09-01"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_momento_invalido_es_422_no_500(client_admin_db):
    """Design D2: momento inválido devuelve 422 (antes causaba ValueError -> 500)."""
    resp = await client_admin_db.get(
        INGRESOS_URL, params={"anio": 2026, "mes": 9, "momento": "m6"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fecha_desde_posterior_a_fecha_hasta_es_422(client_admin_db):
    """Design Validation rules: fecha_desde <= fecha_hasta."""
    resp = await client_admin_db.get(
        INGRESOS_URL,
        params={"fecha_desde": "2026-09-15", "fecha_hasta": "2026-09-01"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_modo_intervalo_agrega_igual_que_modo_momento(client_admin_db, db_session):
    """Scenario: Interval mode aggregates the same way. Un pago pagado y uno
    pendiente dentro de la ventana suman; uno fuera de la ventana no debe
    aportar al total."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()

    dentro_pagado = _mk_pago(
        credito.id, 1, date(2026, 9, 5), Decimal("80.00"), Decimal("20.00"), pagado=True,
    )
    dentro_pendiente = _mk_pago(
        credito.id, 2, date(2026, 9, 10), Decimal("50.00"), Decimal("30.00"), pagado=False,
    )
    fuera_de_ventana = _mk_pago(
        credito.id, 3, date(2026, 9, 20), Decimal("999.00"), Decimal("1.00"), pagado=False,
    )
    db_session.add_all([dentro_pagado, dentro_pendiente, fuera_de_ventana])
    await db_session.flush()

    resp = await client_admin_db.get(
        INGRESOS_URL,
        params={"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-15"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_recaudado"] == 100.0
    assert body["total_capital_recaudado"] == 80.0
    assert body["total_intereses_recaudados"] == 20.0
    assert body["total_pendiente"] == 80.0
    assert body["total_capital_pendiente"] == 50.0
    assert body["total_intereses_pendientes"] == 30.0
