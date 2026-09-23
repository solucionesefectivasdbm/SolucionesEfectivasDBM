"""
tests/test_reportes.py — `GET /reportes` atribuye ingresos de un pago
repartido por cuenta (payment-multi-recipient, item 10, PR2).

Req: Revenue Reports Attribute Split Pagos Per Cuenta. Antes de este PR,
`por_receptor`/`por_cuenta` agrupaban directo por `Pago.cuenta_bancaria_id`;
ahora leen de `pago_repartos` — cada cuenta ve exactamente su porción de
cada pago que repartió, sin doble conteo, y las filas tipo cliente quedan
excluidas del reporte por cuenta (no tienen `cuenta_bancaria_id`).
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
from app.models.pago_reparto import PagoReparto, TipoDestinatario
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.usuario import TipoUsuario, Usuario

REPORTES_URL = "/api/v1/reportes"


def _mk_receptor() -> Receptor:
    return Receptor(
        id=uuid.uuid4(), nombre=f"Receptor {uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
    )


def _mk_cuenta(receptor_id: uuid.UUID, *, etiqueta="A") -> CuentaBancaria:
    return CuentaBancaria(
        id=uuid.uuid4(), receptor_id=receptor_id, entidad_bancaria=etiqueta,
        tipo_cuenta=TipoCuenta.ahorros, numero_cuenta=f"{etiqueta}1",
        es_predeterminada=False,
    )


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Reporte", apellidos=f"Split{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"ReporteSplit-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )


def _mk_pago_pagado(
    credito_id: uuid.UUID, cuenta_bancaria_id, capital: Decimal, interes: Decimal,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=capital + interes,
        capital_a_pagar=capital, interes_a_pagar=interes,
        capital_pagado=capital, interes_pagado=interes,
        momento="m3", fecha_maxima=date(2026, 2, 10),
        pagado=True, validado_recaudador=True, es_ultimo_pago=False,
        cuenta_bancaria_id=cuenta_bancaria_id,
    )


def _mk_reparto_cuenta(pago_id: uuid.UUID, cuenta_bancaria_id: uuid.UUID, monto: Decimal) -> PagoReparto:
    return PagoReparto(
        id=uuid.uuid4(), pago_id=pago_id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
        cuenta_bancaria_id=cuenta_bancaria_id, monto=monto,
    )


def _mk_reparto_cliente(pago_id: uuid.UUID, cliente_id: uuid.UUID, monto: Decimal) -> PagoReparto:
    return PagoReparto(
        id=uuid.uuid4(), pago_id=pago_id, tipo_destinatario=TipoDestinatario.cliente,
        cliente_id=cliente_id, monto=monto,
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
async def test_split_aparece_bajo_cada_cuenta_por_su_porcion(client_admin_db, db_session):
    """Req: Revenue Reports Attribute Split Pagos Per Cuenta — 'Split
    payment appears under each of its cuentas'."""
    receptor_a, receptor_b = _mk_receptor(), _mk_receptor()
    cuenta_a = _mk_cuenta(receptor_a.id, etiqueta="A")
    cuenta_b = _mk_cuenta(receptor_b.id, etiqueta="B")
    db_session.add_all([receptor_a, receptor_b, cuenta_a, cuenta_b])
    await db_session.flush()

    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()

    # 100.000 = 80.000 capital + 20.000 interés, repartido 60/40.
    pago = _mk_pago_pagado(credito.id, cuenta_a.id, Decimal("80000.00"), Decimal("20000.00"))
    db_session.add(pago)
    await db_session.flush()
    db_session.add_all([
        _mk_reparto_cuenta(pago.id, cuenta_a.id, Decimal("60000.00")),
        _mk_reparto_cuenta(pago.id, cuenta_b.id, Decimal("40000.00")),
    ])
    await db_session.flush()

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    r_a = next(r for r in body["por_receptor"] if r["receptor_id"] == str(receptor_a.id))
    r_b = next(r for r in body["por_receptor"] if r["receptor_id"] == str(receptor_b.id))

    assert r_a["total_recaudado"] == 60000.0
    assert r_a["total_capital_recaudado"] == 48000.0
    assert r_a["total_intereses_recaudados"] == 12000.0
    assert r_b["total_recaudado"] == 40000.0
    assert r_b["total_capital_recaudado"] == 32000.0
    assert r_b["total_intereses_recaudados"] == 8000.0

    # No double counting: el total general del reporte sigue siendo el del
    # pago completo, no 100.000 + 100.000.
    assert body["total_recaudado"] == 100000.0
    assert body["total_capital_recaudado"] == 80000.0
    assert body["total_intereses_recaudados"] == 20000.0


@pytest.mark.asyncio
async def test_split_con_cliente_no_aporta_a_ese_cliente(client_admin_db, db_session):
    """Req: Revenue Reports Attribute Split Pagos Per Cuenta — 'Split
    payment with a client recipient contributes nothing to that client'."""
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id, etiqueta="A")
    db_session.add_all([receptor, cuenta])
    await db_session.flush()

    cliente_credito = _mk_cliente()
    cliente_destinatario = _mk_cliente()
    db_session.add_all([cliente_credito, cliente_destinatario])
    await db_session.flush()
    credito = _mk_credito(cliente_credito.id)
    db_session.add(credito)
    await db_session.flush()

    pago = _mk_pago_pagado(credito.id, cuenta.id, Decimal("70.00"), Decimal("30.00"))
    db_session.add(pago)
    await db_session.flush()
    db_session.add_all([
        _mk_reparto_cuenta(pago.id, cuenta.id, Decimal("70.00")),
        _mk_reparto_cliente(pago.id, cliente_destinatario.id, Decimal("30.00")),
    ])
    await db_session.flush()

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # El destinatario cuenta recibió 70 de un pago total de 100 (70 capital +
    # 30 interés) -> proporción 0.7, prorrateado: 49.00 capital + 21.00
    # interés = 70.00 total (design.md 'Sum check' no aplica acá — es el
    # prorrateo del reporte, no la validación de reemplazar_repartos).
    r = next(x for x in body["por_receptor"] if x["receptor_id"] == str(receptor.id))
    assert r["total_recaudado"] == 70.0
    assert r["total_capital_recaudado"] == 49.0
    assert r["total_intereses_recaudados"] == 21.0

    # El destinatario tipo cliente no genera ninguna entrada por_receptor.
    ids_receptor = {x["receptor_id"] for x in body["por_receptor"]}
    assert str(cliente_destinatario.id) not in ids_receptor


@pytest.mark.asyncio
async def test_split_tres_destinatarios_prorratea_cada_cuenta(client_admin_db, db_session):
    """Regresión de cobertura (Judgment Day, Juez B): el prorrateo por
    cuenta no debe estar hardcodeado para el caso de 2 destinatarios —
    cubrir un split a 3 (2 cuentas + 1 cliente) y confirmar que cada cuenta
    recibe exactamente su parte, sin doble conteo del total."""
    receptor_a, receptor_b = _mk_receptor(), _mk_receptor()
    cuenta_a = _mk_cuenta(receptor_a.id, etiqueta="A")
    cuenta_b = _mk_cuenta(receptor_b.id, etiqueta="B")
    db_session.add_all([receptor_a, receptor_b, cuenta_a, cuenta_b])
    await db_session.flush()

    cliente_credito = _mk_cliente()
    cliente_destinatario = _mk_cliente()
    db_session.add_all([cliente_credito, cliente_destinatario])
    await db_session.flush()
    credito = _mk_credito(cliente_credito.id)
    db_session.add(credito)
    await db_session.flush()

    # 100.000 = 80.000 capital + 20.000 interés, repartido 50/30/20.
    pago = _mk_pago_pagado(credito.id, cuenta_a.id, Decimal("80000.00"), Decimal("20000.00"))
    db_session.add(pago)
    await db_session.flush()
    db_session.add_all([
        _mk_reparto_cuenta(pago.id, cuenta_a.id, Decimal("50000.00")),
        _mk_reparto_cuenta(pago.id, cuenta_b.id, Decimal("30000.00")),
        _mk_reparto_cliente(pago.id, cliente_destinatario.id, Decimal("20000.00")),
    ])
    await db_session.flush()

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    r_a = next(r for r in body["por_receptor"] if r["receptor_id"] == str(receptor_a.id))
    r_b = next(r for r in body["por_receptor"] if r["receptor_id"] == str(receptor_b.id))
    assert r_a["total_recaudado"] == 50000.0
    assert r_b["total_recaudado"] == 30000.0

    # El destinatario cliente no aparece, y el total general no duplica ni
    # se queda corto: sigue siendo el monto real del pago (80/20 = 100).
    ids_receptor = {x["receptor_id"] for x in body["por_receptor"]}
    assert str(cliente_destinatario.id) not in ids_receptor
    assert body["total_recaudado"] == 100000.0
    assert body["total_capital_recaudado"] == 80000.0
    assert body["total_intereses_recaudados"] == 20000.0


@pytest.mark.asyncio
async def test_reparto_soft_deleted_no_cuenta(client_admin_db, db_session):
    """Un reparto reemplazado (soft-deleted) no debe aportar al reporte —
    solo los repartos ACTIVOS son fuente de verdad (invariante I1)."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A")
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B")
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()

    pago = _mk_pago_pagado(credito.id, cuenta_b.id, Decimal("50.00"), Decimal("50.00"))
    db_session.add(pago)
    await db_session.flush()
    reparto_viejo = _mk_reparto_cuenta(pago.id, cuenta_a.id, Decimal("100.00"))
    db_session.add(reparto_viejo)
    await db_session.flush()
    from app.utils.tz import ahora_bogota
    reparto_viejo.deleted_at = ahora_bogota()
    reparto_nuevo = _mk_reparto_cuenta(pago.id, cuenta_b.id, Decimal("100.00"))
    db_session.add(reparto_nuevo)
    await db_session.flush()

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    r = next(x for x in body["por_receptor"] if x["receptor_id"] == str(receptor.id))
    por_cuenta = {c["cuenta_bancaria_id"]: c for c in r["por_cuenta"]}
    # cuenta_a no tuvo NINGÚN reparto activo (el suyo fue soft-deleted y no
    # tiene pendientes tampoco) -> ni siquiera aparece en por_cuenta, igual
    # que cualquier cuenta sin movimientos (convención ya existente).
    assert str(cuenta_a.id) not in por_cuenta
    assert por_cuenta[str(cuenta_b.id)]["total_recaudado"] == 100.0
