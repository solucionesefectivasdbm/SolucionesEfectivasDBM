"""
tests/test_reportes_por_cuenta.py — `GET /reportes` desglose `por_cuenta`
dentro de cada receptor (receiver-bank-account-assignment PR2b).

Req: Report Per-Account Sub-Breakdown. El receptor se deriva vía
`Pago.cuenta_bancaria_id -> CuentaBancaria.receptor_id` (nunca
`Pago.receptor_id`, deprecado desde PR2a). Los subtotales por cuenta deben
sumar exactamente el total del receptor, y los pagos sin `cuenta_bancaria_id`
se excluyen de ambos niveles, igual que hoy.
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


def _mk_cuenta(receptor_id: uuid.UUID, *, etiqueta="A", predeterminada=False) -> CuentaBancaria:
    return CuentaBancaria(
        id=uuid.uuid4(), receptor_id=receptor_id, entidad_bancaria=etiqueta,
        tipo_cuenta=TipoCuenta.ahorros, numero_cuenta=f"{etiqueta}1",
        es_predeterminada=predeterminada,
    )


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Reporte", apellidos=f"Cuenta{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"ReporteCuenta-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )


def _mk_pago_pagado(
    credito_id: uuid.UUID, cuenta_bancaria_id: uuid.UUID | None,
    capital: Decimal, interes: Decimal,
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


def _repartos_para(*pagos: Pago) -> list[PagoReparto]:
    """payment-multi-recipient (item 10, PR2): `reportes.py` ahora lee de
    `pago_repartos`, no de `Pago.cuenta_bancaria_id` directo. Estos fixtures
    arman el `Pago` a mano (sin pasar por `PagoService`), así que necesitan
    la fila de reparto por defecto (100% a `cuenta_bancaria_id`) para que
    las aserciones de recaudado no queden en 0 — mismo criterio que
    `pago_reparto_service.crear_reparto_por_defecto`."""
    filas = []
    for p in pagos:
        if p.pagado and p.cuenta_bancaria_id and (p.capital_pagado + p.interes_pagado) > Decimal("0.00"):
            filas.append(PagoReparto(
                id=uuid.uuid4(), pago_id=p.id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=p.cuenta_bancaria_id, monto=p.capital_pagado + p.interes_pagado,
            ))
    return filas


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
async def test_subtotales_suman_al_receptor(client_admin_db: AsyncClient, db_session):
    """Req: Report Per-Account Sub-Breakdown — 'Subtotals sum to receptor'."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B")
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    cliente_a, cliente_b = _mk_cliente(), _mk_cliente()
    db_session.add_all([cliente_a, cliente_b])
    await db_session.flush()
    credito_a, credito_b = _mk_credito(cliente_a.id), _mk_credito(cliente_b.id)
    db_session.add_all([credito_a, credito_b])
    await db_session.flush()
    pago_a = _mk_pago_pagado(credito_a.id, cuenta_a.id, Decimal("80.00"), Decimal("20.00"))
    pago_b = _mk_pago_pagado(credito_b.id, cuenta_b.id, Decimal("40.00"), Decimal("10.00"))
    db_session.add_all([pago_a, pago_b])
    await db_session.flush()
    db_session.add_all(_repartos_para(pago_a, pago_b))
    await db_session.flush()

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    receptores = [r for r in body["por_receptor"] if r["receptor_id"] == str(receptor.id)]
    assert len(receptores) == 1
    r = receptores[0]
    assert r["total_recaudado"] == 150.0

    por_cuenta = {c["cuenta_bancaria_id"]: c for c in r["por_cuenta"]}
    assert por_cuenta[str(cuenta_a.id)]["total_recaudado"] == 100.0
    assert por_cuenta[str(cuenta_b.id)]["total_recaudado"] == 50.0
    assert sum(c["total_recaudado"] for c in r["por_cuenta"]) == r["total_recaudado"]


@pytest.mark.asyncio
async def test_totales_receptor_iguales_a_formula_previa(client_admin_db: AsyncClient, db_session):
    """Req: Report Per-Account Sub-Breakdown — 'Totals equal pre-change values'."""
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta])
    await db_session.flush()
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago_pagado(credito.id, cuenta.id, Decimal("83.33"), Decimal("16.67"))
    db_session.add(pago)
    await db_session.flush()
    db_session.add_all(_repartos_para(pago))
    await db_session.flush()

    # Fórmula previa al cambio (acumulación por pago, en float):
    # capital_rec += capital_pagado; intereses_rec += interes_pagado;
    # total_recaudado = capital_rec + intereses_rec.
    pagos = [pago]
    capital_rec = 0.0
    intereses_rec = 0.0
    for p in pagos:
        capital_rec += float(p.capital_pagado)
        intereses_rec += float(p.interes_pagado)
    esperado_total = capital_rec + intereses_rec

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    r = next(x for x in resp.json()["por_receptor"] if x["receptor_id"] == str(receptor.id))
    assert r["total_capital_recaudado"] == capital_rec
    assert r["total_intereses_recaudados"] == intereses_rec
    assert r["total_recaudado"] == esperado_total


@pytest.mark.asyncio
async def test_totales_receptor_se_acumulan_por_pago_no_por_cuenta(client_admin_db: AsyncClient, db_session):
    """Req: Report Per-Account Sub-Breakdown — 'Totals equal pre-change values'.

    Con dos cuentas y montos intercalados, sumar por cuenta y luego sumar las
    cuentas NO es byte-idéntico (float) a acumular pago a pago. El total del
    receptor debe seguir la fórmula previa (por pago, en orden de `todos`);
    los subtotales `por_cuenta` se acumulan aparte.
    """
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B")
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    clientes = [_mk_cliente() for _ in range(4)]
    db_session.add_all(clientes)
    await db_session.flush()
    creditos = [_mk_credito(c.id) for c in clientes]
    db_session.add_all(creditos)
    await db_session.flush()

    # Intercalado A, B, A, B: 83333.33 + 16666.67 + 0.2 + 0.1 == 100000.3
    # pago a pago, pero (83333.33 + 0.2) + (16666.67 + 0.1) == 100000.29999999999.
    pagos = [
        _mk_pago_pagado(creditos[0].id, cuenta_a.id, Decimal("83333.33"), Decimal("0.00")),
        _mk_pago_pagado(creditos[1].id, cuenta_b.id, Decimal("16666.67"), Decimal("0.00")),
        _mk_pago_pagado(creditos[2].id, cuenta_a.id, Decimal("0.20"), Decimal("0.00")),
        _mk_pago_pagado(creditos[3].id, cuenta_b.id, Decimal("0.10"), Decimal("0.00")),
    ]
    for p in pagos:
        db_session.add(p)
        await db_session.flush()
    db_session.add_all(_repartos_para(*pagos))
    await db_session.flush()

    capital_rec = 0.0
    intereses_rec = 0.0
    for p in pagos:
        capital_rec += float(p.capital_pagado)
        intereses_rec += float(p.interes_pagado)
    esperado_total = capital_rec + intereses_rec

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    r = next(x for x in resp.json()["por_receptor"] if x["receptor_id"] == str(receptor.id))
    assert r["total_capital_recaudado"] == capital_rec
    assert r["total_recaudado"] == esperado_total

    por_cuenta = {c["cuenta_bancaria_id"]: c for c in r["por_cuenta"]}
    assert por_cuenta[str(cuenta_a.id)]["total_capital_recaudado"] == float(Decimal("83333.33")) + float(Decimal("0.20"))
    assert por_cuenta[str(cuenta_b.id)]["total_capital_recaudado"] == float(Decimal("16666.67")) + float(Decimal("0.10"))


@pytest.mark.asyncio
async def test_orden_determinista_por_receptor_y_por_cuenta(client_admin_db: AsyncClient, db_session):
    """`por_receptor` se ordena por nombre (luego id) y `por_cuenta` por
    etiqueta (luego id), sin depender del orden de inserción."""
    r_zeta = Receptor(
        id=uuid.uuid4(), nombre="Zeta Receptor", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000",
    )
    r_alfa = Receptor(
        id=uuid.uuid4(), nombre="Alfa Receptor", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000",
    )
    cuenta_z = _mk_cuenta(r_zeta.id, etiqueta="Z", predeterminada=True)
    cuenta_zeta_b = _mk_cuenta(r_zeta.id, etiqueta="B")
    cuenta_alfa = _mk_cuenta(r_alfa.id, etiqueta="A", predeterminada=True)
    # Insertar en orden inverso al esperado.
    db_session.add_all([r_zeta, r_alfa, cuenta_z, cuenta_zeta_b, cuenta_alfa])
    await db_session.flush()

    clientes = [_mk_cliente() for _ in range(3)]
    db_session.add_all(clientes)
    await db_session.flush()
    creditos = [_mk_credito(c.id) for c in clientes]
    db_session.add_all(creditos)
    await db_session.flush()
    pagos_orden = []
    for credito, cuenta in zip(creditos, [cuenta_z, cuenta_zeta_b, cuenta_alfa]):
        pago = _mk_pago_pagado(credito.id, cuenta.id, Decimal("10.00"), Decimal("1.00"))
        db_session.add(pago)
        await db_session.flush()
        pagos_orden.append(pago)
    db_session.add_all(_repartos_para(*pagos_orden))
    await db_session.flush()

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    ids_objetivo = {str(r_zeta.id), str(r_alfa.id)}
    receptores = [r for r in resp.json()["por_receptor"] if r["receptor_id"] in ids_objetivo]
    assert [r["receptor_id"] for r in receptores] == [str(r_alfa.id), str(r_zeta.id)]

    zeta = receptores[1]
    assert [c["cuenta_bancaria_id"] for c in zeta["por_cuenta"]] == [
        str(cuenta_zeta_b.id), str(cuenta_z.id),
    ]


@pytest.mark.asyncio
async def test_pagos_sin_cuenta_excluidos(client_admin_db: AsyncClient, db_session):
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta])
    await db_session.flush()
    cliente_con, cliente_sin = _mk_cliente(), _mk_cliente()
    db_session.add_all([cliente_con, cliente_sin])
    await db_session.flush()
    credito_con, credito_sin = _mk_credito(cliente_con.id), _mk_credito(cliente_sin.id)
    db_session.add_all([credito_con, credito_sin])
    await db_session.flush()
    pago_con = _mk_pago_pagado(credito_con.id, cuenta.id, Decimal("50.00"), Decimal("10.00"))
    pago_sin = _mk_pago_pagado(credito_sin.id, None, Decimal("999.00"), Decimal("999.00"))
    db_session.add_all([pago_con, pago_sin])
    await db_session.flush()
    db_session.add_all(_repartos_para(pago_con, pago_sin))
    await db_session.flush()

    resp = await client_admin_db.get(REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"})
    assert resp.status_code == 200, resp.text
    r = next(x for x in resp.json()["por_receptor"] if x["receptor_id"] == str(receptor.id))
    assert r["total_recaudado"] == 60.0
    assert len(r["por_cuenta"]) == 1
    assert r["por_cuenta"][0]["total_recaudado"] == 60.0
