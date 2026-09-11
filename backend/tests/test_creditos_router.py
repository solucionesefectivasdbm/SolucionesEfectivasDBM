"""
tests/test_creditos_router.py — Zero-balance-credit-closure PR 3: predicado
"operativamente abierto" en resumen-cartera, señal `pendiente_de_cierre`,
confirmación explícita de cierre.

Todos los créditos se ejercitan vía HTTP real (httpx AsyncClient) contra la
app real y una sesión aiosqlite real — sin mockear la lógica de negocio.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario
from app.services.credito_service import credito_operativamente_abierto


def _mk_credito(
    *,
    tipo_credito: TipoCredito = TipoCredito.cuota_fija,
    saldo_capital: Decimal,
    saldo_intereses: Decimal = Decimal("0.00"),
    activo: bool = True,
    numero_cuotas: int | None = 12,
) -> Credito:
    return Credito(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=tipo_credito,
        capital_prestado=Decimal("1200000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual,
        saldo_capital=saldo_capital,
        saldo_intereses=saldo_intereses,
        numero_cuotas=numero_cuotas,
        activo=activo,
    )


@pytest_asyncio.fixture
async def make_client(db_session):
    """Factory de AsyncClient con el usuario/rol y la sesión de DB inyectados."""
    created: list[AsyncClient] = []

    async def _make(tipo: TipoUsuario) -> AsyncClient:
        user = MagicMock(spec=Usuario)
        user.id = uuid.uuid4()
        user.tipo_usuario = tipo
        user.activo = True
        user.deleted_at = None

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


# ──────────────────────────────────────────────────────────────────────────────
# 3.1/3.2 — credito_operativamente_abierto() y resumen-cartera
# ──────────────────────────────────────────────────────────────────────────────

class TestCreditoOperativamenteAbierto:
    @pytest.mark.asyncio
    async def test_credito_saldado_no_cumple_el_predicado(self, db_session):
        """cuota_fija con ambos saldos en cero: activo=True pero NO abierto operativamente."""
        from sqlalchemy import select

        credito = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add(credito)
        await db_session.flush()

        row = (await db_session.execute(
            select(Credito).where(Credito.id == credito.id, credito_operativamente_abierto())
        )).scalar_one_or_none()
        assert row is None

    @pytest.mark.asyncio
    async def test_capital_saldado_interes_pendiente_si_cumple_el_predicado(self, db_session):
        """cuota_fija con capital en cero pero interés pendiente: SÍ abierto operativamente."""
        from sqlalchemy import select

        credito = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("5000.00"))
        db_session.add(credito)
        await db_session.flush()

        row = (await db_session.execute(
            select(Credito).where(Credito.id == credito.id, credito_operativamente_abierto())
        )).scalar_one_or_none()
        assert row is not None
        assert row.id == credito.id


class TestResumenCarteraExcluyeSaldados:
    @pytest.mark.asyncio
    async def test_credito_saldado_activo_true_no_suma_en_resumen(self, make_client, db_session):
        """Un crédito saldado con activo=True (pendiente de confirmar) no debe
        aportar a saldo_capital/saldo_intereses del resumen de cartera."""
        credito_saldado = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        credito_abierto = _mk_credito(saldo_capital=Decimal("300000.00"), saldo_intereses=Decimal("9000.00"))
        db_session.add_all([credito_saldado, credito_abierto])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.get("/api/v1/creditos/resumen-cartera")
        assert r.status_code == 200, r.text
        data = r.json()
        assert Decimal(str(data["saldo_capital"])) == Decimal("300000.00")
        assert Decimal(str(data["saldo_intereses"])) == Decimal("9000.00")

    @pytest.mark.asyncio
    async def test_capital_saldado_interes_pendiente_permanece_en_resumen(self, make_client, db_session):
        """Regla 9: capital en cero con interés pendiente SIGUE sumando al total."""
        credito = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("4200.00"))
        db_session.add(credito)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.get("/api/v1/creditos/resumen-cartera")
        assert r.status_code == 200, r.text
        data = r.json()
        assert Decimal(str(data["saldo_intereses"])) == Decimal("4200.00")


# ──────────────────────────────────────────────────────────────────────────────
# Follow-up PR3: cobertura de `cliente_id` en resumen-cartera (fuera del scope
# original — añadido por hook `gga run` pre-commit; ver apply-progress).
# ──────────────────────────────────────────────────────────────────────────────

class TestResumenCarteraFiltroCliente:
    @pytest.mark.asyncio
    async def test_sin_cliente_id_suma_toda_la_cartera(self, make_client, db_session):
        """Comportamiento preexistente sin regresión: sin `cliente_id`, el
        resumen suma los créditos abiertos de TODOS los clientes."""
        cliente_a = uuid.uuid4()
        cliente_b = uuid.uuid4()
        credito_a = _mk_credito(saldo_capital=Decimal("300000.00"), saldo_intereses=Decimal("9000.00"))
        credito_a.cliente_id = cliente_a
        credito_b = _mk_credito(saldo_capital=Decimal("150000.00"), saldo_intereses=Decimal("4500.00"))
        credito_b.cliente_id = cliente_b
        db_session.add_all([credito_a, credito_b])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.get("/api/v1/creditos/resumen-cartera")
        assert r.status_code == 200, r.text
        data = r.json()
        assert Decimal(str(data["saldo_capital"])) == Decimal("450000.00")
        assert Decimal(str(data["saldo_intereses"])) == Decimal("13500.00")

    @pytest.mark.asyncio
    async def test_con_cliente_id_solo_suma_los_creditos_de_ese_cliente(self, make_client, db_session):
        """Con `cliente_id`, el resumen se acota a los créditos abiertos de
        ese cliente puntual y excluye los de otros clientes."""
        cliente_objetivo = uuid.uuid4()
        cliente_otro = uuid.uuid4()
        credito_objetivo = _mk_credito(saldo_capital=Decimal("300000.00"), saldo_intereses=Decimal("9000.00"))
        credito_objetivo.cliente_id = cliente_objetivo
        credito_otro = _mk_credito(saldo_capital=Decimal("150000.00"), saldo_intereses=Decimal("4500.00"))
        credito_otro.cliente_id = cliente_otro
        db_session.add_all([credito_objetivo, credito_otro])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.get(f"/api/v1/creditos/resumen-cartera?cliente_id={cliente_objetivo}")
        assert r.status_code == 200, r.text
        data = r.json()
        # Prueba que el parámetro sí filtra: si se ignorara, el total sería
        # 450000.00 (la suma de ambos clientes) en vez de 300000.00.
        assert Decimal(str(data["saldo_capital"])) == Decimal("300000.00")
        assert Decimal(str(data["saldo_intereses"])) == Decimal("9000.00")

    @pytest.mark.asyncio
    async def test_con_cliente_id_credito_saldado_sin_confirmar_no_suma(self, make_client, db_session):
        """Regla 6/9 bajo filtro: un crédito saldado (ambos saldos en cero)
        con `activo=True` sin confirmar cierre no debe aportar al total
        filtrado, igual que en el total sin filtrar. Se incluye además un
        crédito ABIERTO de OTRO cliente para probar que el filtro sí actúa
        (si se ignorara `cliente_id`, ese otro crédito inflaría el total)."""
        cliente_objetivo = uuid.uuid4()
        cliente_otro = uuid.uuid4()
        credito_saldado = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        credito_saldado.cliente_id = cliente_objetivo
        credito_abierto = _mk_credito(saldo_capital=Decimal("300000.00"), saldo_intereses=Decimal("9000.00"))
        credito_abierto.cliente_id = cliente_objetivo
        credito_de_otro = _mk_credito(saldo_capital=Decimal("999999.00"), saldo_intereses=Decimal("50000.00"))
        credito_de_otro.cliente_id = cliente_otro
        db_session.add_all([credito_saldado, credito_abierto, credito_de_otro])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.get(f"/api/v1/creditos/resumen-cartera?cliente_id={cliente_objetivo}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert Decimal(str(data["saldo_capital"])) == Decimal("300000.00")
        assert Decimal(str(data["saldo_intereses"])) == Decimal("9000.00")

    @pytest.mark.asyncio
    async def test_cliente_id_desconocido_devuelve_total_cero_sin_error(self, make_client, db_session):
        """Un `cliente_id` que no coincide con ningún crédito no genera error:
        el endpoint aplica `coalesce(sum(...), 0)`, por lo que devuelve un
        resumen en cero (contrato real leído del código, no inventado)."""
        credito_a = _mk_credito(saldo_capital=Decimal("300000.00"), saldo_intereses=Decimal("9000.00"))
        db_session.add(credito_a)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.get(f"/api/v1/creditos/resumen-cartera?cliente_id={uuid.uuid4()}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert Decimal(str(data["saldo_capital"])) == Decimal("0")
        assert Decimal(str(data["saldo_intereses"])) == Decimal("0")
        assert Decimal(str(data["saldo_total"])) == Decimal("0")


# ──────────────────────────────────────────────────────────────────────────────
# 3.4/3.5 — pendiente_de_cierre expuesto en PATCH sin tocar activo
# ──────────────────────────────────────────────────────────────────────────────

class TestPendienteDeCierreEnPatch:
    @pytest.mark.asyncio
    async def test_patch_que_salda_el_credito_expone_pendiente_de_cierre_sin_cerrar(
        self, make_client, db_session
    ):
        """abono_capital: bajar capital_prestado al monto ya pagado deja
        saldo_capital=0 → esta_saldado=True → pendiente_de_cierre=True,
        pero activo permanece True (rule 2: PATCH nunca cierra)."""
        credito = Credito(
            id=uuid.uuid4(),
            cliente_id=uuid.uuid4(),
            numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
            tipo_credito=TipoCredito.abono_capital,
            capital_prestado=Decimal("100000.00"),
            tasa_interes_mensual=Decimal("0.0300"),
            fecha_apertura=date(2026, 1, 1),
            fecha_inicial_pago=date(2026, 2, 1),
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("40000.00"),
            saldo_intereses=Decimal("0.00"),
            abono_minimo=Decimal("10000.00"),
            numero_cuotas=None,
            activo=True,
        )
        db_session.add(credito)
        db_session.add(Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("70000.00"),
            capital_a_pagar=Decimal("60000.00"), interes_a_pagar=Decimal("3000.00"),
            capital_pagado=Decimal("60000.00"), interes_pagado=Decimal("3000.00"),
            momento="m1", fecha_maxima=date(2026, 2, 1), pagado=True,
        ))
        db_session.add(Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
            tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("11200.00"),
            capital_a_pagar=Decimal("10000.00"), interes_a_pagar=Decimal("1200.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m1", fecha_maxima=date(2026, 3, 1), pagado=False,
        ))
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.patch(
            f"/api/v1/creditos/{credito.id}",
            json={"capital_prestado": 60000},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["activo"] is True
        assert data["pendiente_de_cierre"] is True
        assert Decimal(str(data["saldo_capital"])) == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_patch_sin_saldar_no_expone_pendiente_de_cierre(self, make_client, db_session):
        """Contraprueba: si el PATCH no salda el crédito, pendiente_de_cierre es False."""
        credito = Credito(
            id=uuid.uuid4(),
            cliente_id=uuid.uuid4(),
            numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
            tipo_credito=TipoCredito.abono_capital,
            capital_prestado=Decimal("100000.00"),
            tasa_interes_mensual=Decimal("0.0300"),
            fecha_apertura=date(2026, 1, 1),
            fecha_inicial_pago=date(2026, 2, 1),
            periodicidad=Periodicidad.mensual,
            saldo_capital=Decimal("40000.00"),
            saldo_intereses=Decimal("0.00"),
            abono_minimo=Decimal("10000.00"),
            numero_cuotas=None,
            activo=True,
        )
        db_session.add(credito)
        db_session.add(Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("13000.00"),
            capital_a_pagar=Decimal("10000.00"), interes_a_pagar=Decimal("3000.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m1", fecha_maxima=date(2026, 2, 1), pagado=False,
        ))
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.patch(
            f"/api/v1/creditos/{credito.id}",
            json={"abono_minimo": 15000},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["activo"] is True
        assert data["pendiente_de_cierre"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 3.6/3.7 — POST /creditos/{id}/cerrar
# ──────────────────────────────────────────────────────────────────────────────

class TestConfirmarCierre:
    @pytest.mark.asyncio
    async def test_credito_desconocido_404(self, make_client):
        client = await make_client(TipoUsuario.admin)
        r = await client.post(f"/api/v1/creditos/{uuid.uuid4()}/cerrar")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_credito_ya_cerrado_422(self, make_client, db_session):
        credito = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"), activo=False)
        db_session.add(credito)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(f"/api/v1/creditos/{credito.id}/cerrar")
        assert r.status_code == 422
        assert "cerrado" in r.json()["detail"].lower()
        assert "dos veces" in r.json()["detail"].lower() or "nuevamente" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_credito_no_saldado_422_nombra_el_saldo_pendiente(self, make_client, db_session):
        credito = _mk_credito(saldo_capital=Decimal("150000.00"), saldo_intereses=Decimal("4500.00"))
        db_session.add(credito)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(f"/api/v1/creditos/{credito.id}/cerrar")
        assert r.status_code == 422
        detail = r.json()["detail"].lower()
        assert "capital" in detail
        assert "150000" in detail or "150,000" in detail or "150.000" in detail

    @pytest.mark.parametrize("rol", [TipoUsuario.admin, TipoUsuario.recaudador, TipoUsuario.registrador])
    @pytest.mark.asyncio
    async def test_rol_permitido_confirma_y_escribe_auditoria(self, make_client, db_session, rol):
        from sqlalchemy import select
        from app.models.audit_log import AuditLog

        credito = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add(credito)
        await db_session.flush()

        client = await make_client(rol)
        r = await client.post(f"/api/v1/creditos/{credito.id}/cerrar")
        assert r.status_code == 200, r.text
        assert r.json()["activo"] is False
        assert credito.activo is False

        logs = (await db_session.execute(
            select(AuditLog).where(AuditLog.entidad_id == credito.id)
        )).scalars().all()
        assert len(logs) >= 1

    @pytest.mark.asyncio
    async def test_gestor_403(self, make_client, db_session):
        credito = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add(credito)
        await db_session.flush()

        client = await make_client(TipoUsuario.gestor)
        r = await client.post(f"/api/v1/creditos/{credito.id}/cerrar")
        assert r.status_code == 403
        assert credito.activo is True

    @pytest.mark.asyncio
    async def test_doble_click_produce_un_cierre_y_un_422(self, make_client, db_session):
        """Regla 11: la confirmación NO es idempotente — un segundo intento rechaza."""
        credito = _mk_credito(saldo_capital=Decimal("0.00"), saldo_intereses=Decimal("0.00"))
        db_session.add(credito)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r1 = await client.post(f"/api/v1/creditos/{credito.id}/cerrar")
        assert r1.status_code == 200
        r2 = await client.post(f"/api/v1/creditos/{credito.id}/cerrar")
        assert r2.status_code == 422
