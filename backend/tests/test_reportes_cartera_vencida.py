"""
tests/test_reportes_cartera_vencida.py — `GET /reportes/cartera-vencida`
(reportes-cartera-vencida-y-rango-fechas, design D4-D8).

Req: Cartera Vencida Is Event-Based on Entrada en Mora.
Req: Cartera Vencida Totals and Por-Gestor Breakdown Only.
Req: Cartera Vencida Is Live, Not a Historical Snapshot.
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
from app.models.gestor import Gestor
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

CARTERA_URL = "/api/v1/reportes/cartera-vencida"


def _mk_cliente(**kw) -> Cliente:
    defaults = dict(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Cartera", apellidos=f"Test{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )
    defaults.update(kw)
    return Cliente(**defaults)


def _mk_credito(cliente_id: uuid.UUID, **kw) -> Credito:
    defaults = dict(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Cartera-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )
    defaults.update(kw)
    return Credito(**defaults)


def _mk_pago(
    credito_id: uuid.UUID, numero_cuota: int, fecha_maxima: date,
    capital: Decimal, interes: Decimal, *, pagado: bool = False,
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


def _mk_gestor(*, nombre="Gestor", apellidos=None) -> Gestor:
    return Gestor(
        id=uuid.uuid4(), user_id=uuid.uuid4(), cedula=str(uuid.uuid4().int)[:10],
        nombre=nombre, apellidos=apellidos or f"Prueba{uuid.uuid4().hex[:6]}",
        telefono="3000000000", direccion="Calle 1",
        correo_electronico=f"{uuid.uuid4().hex[:8]}@test.com",
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


# ─── Requirement: Cartera Vencida Is Event-Based on Entrada en Mora ─────────

@pytest.mark.asyncio
async def test_incluido_cuando_entrada_en_mora_cae_en_la_ventana(client_admin_db, db_session, fijar_hoy):
    """Scenario: Included when entrada-en-mora falls in the window."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    # fecha_maxima=2026-09-27 -> momento m1 sept (25-29) -> fecha_entrada_mora=2026-09-30.
    pago = _mk_pago(credito.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"))
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-30", "fecha_hasta": "2026-10-04"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cantidad_cuotas"] == 1
    assert body["total_vencido"] == 100.0
    assert body["total_capital_vencido"] == 80.0
    assert body["total_intereses_vencidos"] == 20.0


@pytest.mark.asyncio
async def test_excluido_cuando_entrada_en_mora_cae_fuera_de_la_ventana(client_admin_db, db_session, fijar_hoy):
    """Scenario: Excluded when entrada-en-mora falls outside the window."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    # Mismo pago (fecha_entrada_mora=2026-09-30); la ventana termina antes.
    pago = _mk_pago(credito.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"))
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-25", "fecha_hasta": "2026-09-29"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cantidad_cuotas"] == 0
    assert body["total_vencido"] == 0.0
    assert body["por_gestor"] == []


@pytest.mark.asyncio
async def test_pago_pagado_nunca_se_incluye(client_admin_db, db_session, fijar_hoy):
    """Scenario: Paid payments are never included."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"), pagado=True)
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-30", "fecha_hasta": "2026-10-04"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cantidad_cuotas"] == 0


# ─── Requirement: Cartera Vencida Totals and Por-Gestor Breakdown Only ──────

@pytest.mark.asyncio
async def test_totales_y_desglose_por_gestor(client_admin_db, db_session, fijar_hoy):
    """Scenario: Totals and gestor breakdown present."""
    gestor_a = _mk_gestor(nombre="Ana")
    gestor_b = _mk_gestor(nombre="Beto")
    db_session.add_all([gestor_a, gestor_b])
    await db_session.flush()
    cliente_a = _mk_cliente(gestor_id=gestor_a.id)
    cliente_b = _mk_cliente(gestor_id=gestor_b.id)
    db_session.add_all([cliente_a, cliente_b])
    await db_session.flush()
    credito_a = _mk_credito(cliente_a.id)
    credito_b = _mk_credito(cliente_b.id)
    db_session.add_all([credito_a, credito_b])
    await db_session.flush()
    pago_a = _mk_pago(credito_a.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"))
    pago_b = _mk_pago(credito_b.id, 1, date(2026, 9, 27), Decimal("50.00"), Decimal("10.00"))
    db_session.add_all([pago_a, pago_b])
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-30", "fecha_hasta": "2026-10-04"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_vencido"] == 160.0
    assert body["total_capital_vencido"] == 130.0
    assert body["total_intereses_vencidos"] == 30.0
    assert len(body["por_gestor"]) == 2
    # Orden (gestor_nombre, gestor_id): Ana antes que Beto.
    assert body["por_gestor"][0]["gestor_id"] == str(gestor_a.id)
    assert body["por_gestor"][1]["gestor_id"] == str(gestor_b.id)
    assert body["por_gestor"][0]["total_vencido"] == 100.0
    assert body["por_gestor"][0]["cantidad_cuotas"] == 1
    assert body["por_gestor"][1]["total_vencido"] == 60.0
    assert body["por_gestor"][1]["cantidad_cuotas"] == 1
    suma = body["por_gestor"][0]["total_vencido"] + body["por_gestor"][1]["total_vencido"]
    assert suma == body["total_vencido"]


@pytest.mark.asyncio
async def test_sin_desglose_por_receptor(client_admin_db, db_session, fijar_hoy):
    """Scenario: No receptor breakdown in the response."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"))
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-30", "fecha_hasta": "2026-10-04"},
    )
    assert resp.status_code == 200, resp.text
    assert "por_receptor" not in resp.json()


# ─── Requirement: Cartera Vencida Is Live, Not a Historical Snapshot ────────

@pytest.mark.asyncio
async def test_pago_aplazado_desaparece_de_ventana_pasada_al_reconsultar(client_admin_db, db_session, fijar_hoy):
    """Scenario: Deferred payment disappears from a past window on re-query."""
    gestor = _mk_gestor(nombre="Carla")
    db_session.add(gestor)
    await db_session.flush()
    cliente = _mk_cliente(gestor_id=gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    # fecha_maxima=2026-09-10 (m3) -> fecha_entrada_mora=2026-09-14, dentro de septiembre.
    pago = _mk_pago(credito.id, 1, date(2026, 9, 10), Decimal("50.00"), Decimal("30.00"))
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 10, 20))

    ventana = {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}
    antes = await client_admin_db.get(CARTERA_URL, params=ventana)
    assert antes.status_code == 200, antes.text
    body_antes = antes.json()
    assert body_antes["cantidad_cuotas"] == 1
    assert len(body_antes["por_gestor"]) == 1

    # Aplazamiento: nueva fecha_maxima cuya fecha_entrada_mora cae en octubre.
    pago.fecha_maxima = date(2026, 10, 12)
    pago.veces_aplazado = 1
    await db_session.flush()

    despues = await client_admin_db.get(CARTERA_URL, params=ventana)
    assert despues.status_code == 200, despues.text
    body_despues = despues.json()
    assert body_despues["cantidad_cuotas"] == 0
    assert body_despues["total_vencido"] == 0.0
    assert body_despues["por_gestor"] == []


@pytest.mark.asyncio
async def test_ventana_totalmente_futura_retorna_reporte_vacio(client_admin_db, db_session, fijar_hoy):
    """Scenario: Window entirely in the future returns an empty report."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    # fecha_maxima=2026-10-05 (m3 oct) cae dentro de la ventana solicitada
    # (2026-10-01..2026-10-31), pero su fecha_entrada_mora (2026-10-14) es
    # futura respecto a "hoy" -> debe quedar excluida por el recorte (D5).
    pago = _mk_pago(credito.id, 1, date(2026, 10, 5), Decimal("80.00"), Decimal("20.00"))
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 9, 23))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-10-01", "fecha_hasta": "2026-10-31"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cantidad_cuotas"] == 0
    assert body["total_vencido"] == 0.0
    assert body["por_gestor"] == []
    # Diseño (Interfaces contract): fecha_fin en la respuesta ya viene recortada a hoy.
    assert body["fecha_fin"] == "2026-09-23"


@pytest.mark.asyncio
async def test_ventana_parcialmente_futura_se_recorta_no_se_rechaza(client_admin_db, db_session, fijar_hoy):
    """Scenario: Window partially in the future is clamped, not rejected."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    # Dentro de la porción recortada (2026-09-15..2026-09-23):
    # fecha_maxima=2026-09-15 (m4) -> fecha_entrada_mora=2026-09-19.
    dentro_del_recorte = _mk_pago(credito.id, 1, date(2026, 9, 15), Decimal("40.00"), Decimal("10.00"))
    # Solo estaría dentro de la ventana COMPLETA (no recortada):
    # fecha_maxima=2026-09-20 (m5) -> fecha_entrada_mora=2026-09-25 (después de "hoy").
    solo_en_ventana_completa = _mk_pago(credito.id, 2, date(2026, 9, 20), Decimal("999.00"), Decimal("1.00"))
    db_session.add_all([dentro_del_recorte, solo_en_ventana_completa])
    await db_session.flush()
    fijar_hoy(date(2026, 9, 23))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-15", "fecha_hasta": "2026-10-15"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cantidad_cuotas"] == 1
    assert body["total_vencido"] == 50.0
    assert body["fecha_fin"] == "2026-09-23"


# ─── D6/D8 guards ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cuota_soft_deleted_excluida(client_admin_db, db_session, fijar_hoy):
    """Design D6: cuota soft-deleted (deleted_at) no cuenta como cartera vencida."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"))
    db_session.add(pago)
    await db_session.flush()
    from app.utils.tz import ahora_bogota
    pago.deleted_at = ahora_bogota()
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-30", "fecha_hasta": "2026-10-04"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cantidad_cuotas"] == 0


@pytest.mark.asyncio
async def test_credito_saldado_excluido(client_admin_db, db_session, fijar_hoy):
    """Design D6: crédito cerrado operativamente (zero-balance-credit-closure,
    regla 9) queda fuera aunque `activo` siga en True — mismo guard que
    `/pagos/alertas/vencidos` (`credito_operativamente_abierto()`, no solo
    `activo == True`)."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(
        cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"),
    )
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"))
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-30", "fecha_hasta": "2026-10-04"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cantidad_cuotas"] == 0


@pytest.mark.asyncio
async def test_cuota_sin_gestor_cuenta_en_totales_pero_no_en_desglose(client_admin_db, db_session, fijar_hoy):
    """Design D8: cuota sin gestor asociado cuenta en los totales pero no
    aparece en `por_gestor` (mismo comportamiento que Ingresos)."""
    cliente = _mk_cliente()  # gestor_id apunta a un UUID sin Gestor real.
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, 1, date(2026, 9, 27), Decimal("80.00"), Decimal("20.00"))
    db_session.add(pago)
    await db_session.flush()
    fijar_hoy(date(2026, 10, 10))

    resp = await client_admin_db.get(
        CARTERA_URL, params={"fecha_desde": "2026-09-30", "fecha_hasta": "2026-10-04"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cantidad_cuotas"] == 1
    assert body["total_vencido"] == 100.0
    assert body["por_gestor"] == []


# ─── Requirement: Two Mutually Exclusive Filter Modes (regresión compartida,
# resolver_ventana ya cubierto exhaustivamente en test_reportes_intervalo.py
# vía /reportes/ingresos — acá solo se confirma que /cartera-vencida también
# lo usa) ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modo_momento_resuelve_la_ventana_en_cartera_vencida(client_admin_db, fijar_hoy):
    fijar_hoy(date(2026, 9, 23))
    resp = await client_admin_db.get(
        CARTERA_URL, params={"anio": 2026, "mes": 9, "momento": "m1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fecha_inicio"] == "2026-09-25"
    assert body["anio"] == 2026
    assert body["mes"] == 9
    assert body["momento"] == "m1"


@pytest.mark.asyncio
async def test_ningun_modo_es_rechazado_en_cartera_vencida(client_admin_db):
    resp = await client_admin_db.get(CARTERA_URL)
    assert resp.status_code == 422
