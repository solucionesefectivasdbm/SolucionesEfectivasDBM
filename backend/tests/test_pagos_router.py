"""
tests/test_pagos_router.py — Zero-balance-credit-closure PR 3: regla 6/9
aplicada a GET /pagos (filas reales Y virtuales) y a las alertas de
vencidos/próximos a vencer. El "trap" documentado en el diseño: las filas
reales de GET /pagos no tenían NINGÚN filtro de `Credito.activo` — solo las
virtuales. Filtrar solo las virtuales deja la cuota pendiente persistida de
un crédito saldado visible en pantalla.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
from app.models.pago_reparto import PagoReparto, TipoDestinatario
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.usuario import TipoUsuario, Usuario
from app.utils.fechas import hoy_bogota

_FAKE_GESTOR_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(),
        gestor_id=_FAKE_GESTOR_ID,
        nombre="Ana",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000",
        direccion="Calle test",
        al_dia=True,
    )


def _mk_credito(
    cliente_id: uuid.UUID,
    *,
    saldo_capital: Decimal,
    saldo_intereses: Decimal = Decimal("0.00"),
    activo: bool = True,
    fecha_inicial_pago: date = date(2026, 2, 1),
) -> Credito:
    return Credito(
        id=uuid.uuid4(),
        cliente_id=cliente_id,
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1200000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=fecha_inicial_pago,
        periodicidad=Periodicidad.mensual,
        saldo_capital=saldo_capital,
        saldo_intereses=saldo_intereses,
        numero_cuotas=12,
        activo=activo,
    )


def _mk_pago_pendiente(credito_id: uuid.UUID, numero_cuota: int, fecha_maxima: date) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=numero_cuota,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("110000.00"),
        capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("10000.00"),
        capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
        momento="m1", fecha_maxima=fecha_maxima, pagado=False,
    )


@pytest_asyncio.fixture
async def client_admin(db_session):
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


class TestListarPagosExcluyeCreditosSaldados:
    @pytest.mark.asyncio
    async def test_fila_real_pendiente_de_credito_saldado_no_aparece(self, client_admin, db_session):
        """El 'trap': la cuota pendiente PERSISTIDA de un crédito saldado
        (activo=True aún sin confirmar) no debe listarse en GET /pagos."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add_all([cliente, credito])
        await db_session.flush()
        db_session.add(_mk_pago_pendiente(credito.id, 12, date(2026, 6, 1)))
        await db_session.flush()

        r = await client_admin.get("/api/v1/pagos", params={"anio": 2026, "mes": 6})
        assert r.status_code == 200, r.text
        ids = [item["credito_id"] for item in r.json()["items"]]
        assert str(credito.id) not in ids

    @pytest.mark.asyncio
    async def test_fila_real_pendiente_de_credito_con_interes_pendiente_si_aparece(
        self, client_admin, db_session
    ):
        """Regla 9: capital en cero pero interés pendiente SIGUE visible."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("5000.00"))
        db_session.add_all([cliente, credito])
        await db_session.flush()
        db_session.add(_mk_pago_pendiente(credito.id, 12, date(2026, 6, 1)))
        await db_session.flush()

        r = await client_admin.get("/api/v1/pagos", params={"anio": 2026, "mes": 6})
        assert r.status_code == 200, r.text
        ids = [item["credito_id"] for item in r.json()["items"]]
        assert str(credito.id) in ids

    @pytest.mark.asyncio
    async def test_fila_real_pagada_de_credito_saldado_si_permanece_como_historial(
        self, client_admin, db_session
    ):
        """Una cuota YA PAGADA es historial — no debe desaparecer solo porque
        el crédito quedó saldado después. El filtro de regla 6 aplica a filas
        pendientes, no reescribe el pasado."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add_all([cliente, credito])
        await db_session.flush()
        pago_pagado = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=12,
            tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("110000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("10000.00"),
            capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("10000.00"),
            momento="m1", fecha_maxima=date(2026, 6, 1), pagado=True,
        )
        db_session.add(pago_pagado)
        await db_session.flush()

        r = await client_admin.get("/api/v1/pagos", params={"anio": 2026, "mes": 6})
        assert r.status_code == 200, r.text
        ids = [item["credito_id"] for item in r.json()["items"]]
        assert str(credito.id) in ids

    @pytest.mark.asyncio
    async def test_fila_virtual_de_credito_saldado_no_aparece(self, client_admin, db_session):
        """Crédito saldado sin ninguna cuota pendiente persistida: tampoco debe
        proyectarse una fila virtual futura."""
        cliente = _mk_cliente()
        credito = _mk_credito(
            cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"),
            fecha_inicial_pago=date(2026, 2, 1),
        )
        db_session.add_all([cliente, credito])
        await db_session.flush()
        # Cuota 1 pagada; sin más cuotas persistidas → candidata a proyección
        # virtual de la #2 si el crédito siguiera contando como activo.
        db_session.add(Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("110000.00"),
            capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("10000.00"),
            capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("10000.00"),
            momento="m1", fecha_maxima=date(2026, 2, 1), pagado=True,
        ))
        await db_session.flush()

        r = await client_admin.get("/api/v1/pagos", params={"anio": 2026, "mes": 3})
        assert r.status_code == 200, r.text
        virtuales = [item for item in r.json()["items"] if item.get("es_proyectada")]
        assert all(v["credito_id"] != str(credito.id) for v in virtuales)


class TestAlertasExcluyenCreditosSaldados:
    # test_alerta_vencidos_excluye_credito_saldado re-pinned in
    # test_mora_momento_cerrado.py (scheduled-overdue-evaluation): con
    # fecha_maxima = hoy_bogota() - 1 día se volvía vacuo bajo la nueva
    # definición de mora (casi siempre sigue en el mismo momento cerrado).

    @pytest.mark.asyncio
    async def test_alerta_proximos_vencer_excluye_credito_saldado(self, client_admin, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add_all([cliente, credito])
        await db_session.flush()
        manana = hoy_bogota() + timedelta(days=1)
        db_session.add(_mk_pago_pendiente(credito.id, 12, manana))
        await db_session.flush()

        r = await client_admin.get("/api/v1/pagos/alertas/proximos-vencer")
        assert r.status_code == 200, r.text
        ids = [p["credito_id"] for p in r.json()]
        assert str(credito.id) not in ids


# ─── payment-multi-recipient (item 10, PR2): filtro EXISTS + repartos batched ──


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


def _mk_pago_pagado(credito_id: uuid.UUID, cuenta_bancaria_id, **overrides) -> Pago:
    base = dict(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("100.00"),
        capital_a_pagar=Decimal("60.00"), interes_a_pagar=Decimal("40.00"),
        capital_pagado=Decimal("60.00"), interes_pagado=Decimal("40.00"),
        momento="m1", fecha_maxima=date(2026, 6, 1), pagado=True,
        validado_recaudador=True, cuenta_bancaria_id=cuenta_bancaria_id,
    )
    base.update(overrides)
    return Pago(**base)


def _mk_reparto(pago_id: uuid.UUID, cuenta_bancaria_id: uuid.UUID, monto: Decimal) -> PagoReparto:
    return PagoReparto(
        id=uuid.uuid4(), pago_id=pago_id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
        cuenta_bancaria_id=cuenta_bancaria_id, monto=monto,
    )


class TestFiltroExistsRepartos:
    """Req: Cascading Filters on Payment Listing (delta) — 'Split payment
    matches multiple account filters' / 'no duplicate rows'. Un pago
    repartido ya no tiene una única `Pago.cuenta_bancaria_id` confiable
    (puede quedar en la cuenta A, o en None tras `aplicar_herencia`) — el
    filtro tiene que mirar `pago_repartos`, no la columna legacy."""

    @pytest.mark.asyncio
    async def test_split_matchea_por_la_cuenta_que_no_es_la_legacy(self, client_admin, db_session):
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("500.00"))
        db_session.add(credito)
        await db_session.flush()

        receptor_a, receptor_b = _mk_receptor(), _mk_receptor()
        cuenta_a = _mk_cuenta(receptor_a.id, etiqueta="A")
        cuenta_b = _mk_cuenta(receptor_b.id, etiqueta="B")
        db_session.add_all([receptor_a, receptor_b, cuenta_a, cuenta_b])
        await db_session.flush()

        # Pago.cuenta_bancaria_id sigue apuntando a A (valor legacy, como
        # quedaría tras el default de PR1) pero el reparto real es 60/40
        # entre A y B — simula el estado post PUT /repartos.
        pago = _mk_pago_pagado(credito.id, cuenta_a.id)
        db_session.add(pago)
        await db_session.flush()
        db_session.add_all([
            _mk_reparto(pago.id, cuenta_a.id, Decimal("60.00")),
            _mk_reparto(pago.id, cuenta_b.id, Decimal("40.00")),
        ])
        await db_session.flush()

        # Filtrar por B (la cuenta que NO coincide con Pago.cuenta_bancaria_id)
        # solo puede encontrar este pago vía EXISTS sobre pago_repartos.
        r = await client_admin.get(
            "/api/v1/pagos", params={"anio": 2026, "mes": 6, "cuenta_bancaria_id": str(cuenta_b.id)}
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert ids == {str(pago.id)}

        # Y por receptor_b también.
        r2 = await client_admin.get(
            "/api/v1/pagos", params={"anio": 2026, "mes": 6, "receptor_id": str(receptor_b.id)}
        )
        assert r2.status_code == 200, r2.text
        ids2 = {item["id"] for item in r2.json()["items"]}
        assert ids2 == {str(pago.id)}

    @pytest.mark.asyncio
    async def test_split_entre_dos_cuentas_del_mismo_receptor_no_duplica_fila(self, client_admin, db_session):
        """'no duplicate rows' — dos cuentas del receptor filtrado coinciden
        con el MISMO pago; debe aparecer una sola vez."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("500.00"))
        db_session.add(credito)
        await db_session.flush()

        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, etiqueta="A")
        cuenta_b = _mk_cuenta(receptor.id, etiqueta="B")
        db_session.add_all([receptor, cuenta_a, cuenta_b])
        await db_session.flush()

        pago = _mk_pago_pagado(credito.id, cuenta_a.id)
        db_session.add(pago)
        await db_session.flush()
        db_session.add_all([
            _mk_reparto(pago.id, cuenta_a.id, Decimal("60.00")),
            _mk_reparto(pago.id, cuenta_b.id, Decimal("40.00")),
        ])
        await db_session.flush()

        r = await client_admin.get(
            "/api/v1/pagos", params={"anio": 2026, "mes": 6, "receptor_id": str(receptor.id)}
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert ids == [str(pago.id)]
        assert r.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_listado_incluye_repartos_batched(self, client_admin, db_session):
        """Segunda mitad de la task 2.10: `repartos` viaja en cada item del
        listado (batched, sin N+1)."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("500.00"))
        db_session.add(credito)
        await db_session.flush()

        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, etiqueta="A")
        db_session.add_all([receptor, cuenta_a])
        await db_session.flush()

        pago = _mk_pago_pagado(credito.id, cuenta_a.id)
        db_session.add(pago)
        await db_session.flush()
        db_session.add(_mk_reparto(pago.id, cuenta_a.id, Decimal("100.00")))
        await db_session.flush()

        r = await client_admin.get("/api/v1/pagos", params={"anio": 2026, "mes": 6})
        assert r.status_code == 200, r.text
        item = next(i for i in r.json()["items"] if i["id"] == str(pago.id))
        assert len(item["repartos"]) == 1
        assert item["repartos"][0]["cuenta_bancaria_id"] == str(cuenta_a.id)
        assert item["repartos"][0]["monto"] == "100.00"
        assert "·" in item["repartos"][0]["etiqueta"]
