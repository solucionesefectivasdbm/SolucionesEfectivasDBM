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

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
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
    @pytest.mark.asyncio
    async def test_alerta_vencidos_excluye_credito_saldado(self, client_admin, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id, saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add_all([cliente, credito])
        await db_session.flush()
        ayer = hoy_bogota() - timedelta(days=1)
        db_session.add(_mk_pago_pendiente(credito.id, 12, ayer))
        await db_session.flush()

        r = await client_admin.get("/api/v1/pagos/alertas/vencidos")
        assert r.status_code == 200, r.text
        ids = [p["credito_id"] for p in r.json()["pagos"]]
        assert str(credito.id) not in ids

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
