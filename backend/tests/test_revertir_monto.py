"""
tests/test_revertir_monto.py — POST /pagos/{id}/revertir-monto (PR2b, design D1/D8).

The "before" state comes from the REAL forward services on SQLite; the endpoint runs through httpx/ASGI on a
session like production (autoflush=False; get_db flushes like the real commit). SQLite ignores FOR UPDATE:
only sequential double-call semantics are proven. Service rules: test_revertir_monto_servicio.py."""
import uuid
from datetime import date
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AccionAudit, AuditLog
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import DestinoExcedente, Pago
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.pago import RegistrarPagoRequest
from app.services.credito_service import crear_primera_cuota
from app.services.pago_service import PagoService

FECHA = date(2026, 3, 1)  # fecha_pago_real of every forward registration
SIN_MONTO = "Esta cuota no tiene un monto registrado para revertir."
PRIMERO = "Hay pagos posteriores registrados. Revierta primero {}."


@pytest_asyncio.fixture
async def db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Session like production (autoflush=False, see app.database.AsyncSessionLocal)."""
    maker = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def como(db):
    """como(rol) -> (client, user): the same ASGI client acting as a new user of that role."""
    async def override_db():
        yield db
        await db.flush()  # what the real get_db commit does: the changes must be persistable

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        def _como(rol: TipoUsuario) -> tuple[AsyncClient, MagicMock]:
            user = MagicMock(spec=Usuario)
            user.id, user.tipo_usuario = uuid.uuid4(), rol
            app.dependency_overrides[get_current_user] = lambda: user
            return client, user

        yield _como
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


async def _credito(db, capital="1000000.00", cuotas=10) -> tuple[Credito, Pago]:
    """Monthly 3% cuota_fija credit plus its first cuota, validated and assigned to a bank account.
    Cliente / cuenta rows are not created: SQLite does not enforce those FKs."""
    capital = Decimal(capital)
    credito = Credito(
        id=uuid.uuid4(), cliente_id=uuid.uuid4(), numero_credito_cliente=f"RM-{uuid.uuid4().hex[:10]}",
        tipo_credito=TipoCredito.cuota_fija, capital_prestado=capital, tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1), periodicidad=Periodicidad.mensual,
        saldo_capital=capital, saldo_intereses=(capital * Decimal("0.03") * cuotas).quantize(Decimal("0.01")),
        numero_cuotas=cuotas, activo=True,
    )
    db.add(credito)
    primera = await crear_primera_cuota(credito, uuid.uuid4())
    primera.validado_recaudador, primera.tipo_validacion = True, "completo"
    db.add(primera)
    await db.flush()
    return credito, primera


async def _registrar(db, credito, pago, capital, interes) -> None:
    """Forward registration through the real service, flushed like a commit."""
    montos = RegistrarPagoRequest(capital_pagado=Decimal(capital), interes_pagado=Decimal(interes))
    await PagoService.registrar_pago(db, pago, credito, montos, FECHA)
    await db.flush()


async def _pendientes(db, credito) -> list[Pago]:
    """Unpaid, not-deleted cuotas of the credit, in order."""
    return list((await db.scalars(
        select(Pago).where(Pago.credito_id == credito.id, Pago.pagado.is_(False), Pago.deleted_at.is_(None))
        .order_by(Pago.numero_cuota, Pago.id)
    )).all())


async def _estado(db, credito) -> list:
    """Persisted columns (but updated_at) of the credit and every cuota (soft-deleted too), then the audit row count."""
    await db.flush()
    await db.refresh(credito)
    cuotas = (await db.scalars(
        select(Pago).where(Pago.credito_id == credito.id).order_by(Pago.numero_cuota, Pago.id)
        .execution_options(populate_existing=True)
    )).all()
    return [
        {c.name: getattr(o, c.name) for c in o.__table__.columns if c.name != "updated_at"}
        for o in (credito, *cuotas)
    ] + [await db.scalar(select(func.count()).select_from(AuditLog))]


async def _no_programada(db, credito, fecha=FECHA) -> Pago:
    """Forward no_programada payment (50000 to capital, no bank account) through the real service."""
    pago = await PagoService.registrar_pago_no_programado(
        db, credito, Decimal("50000.00"), DestinoExcedente.capital, fecha, None)
    await db.flush()
    return pago


def _url(pago: Pago) -> str:
    return f"/api/v1/pagos/{pago.id}/revertir-monto"


@pytest_asyncio.fixture
async def registrado(db) -> tuple[Credito, Pago, Pago]:
    """cuota #1 (100000 + 30000) paid exactly -> balances 900000 / 270000; returns (credito, #1, #2 it generated)."""
    credito, pago = await _credito(db)
    await _registrar(db, credito, pago, "100000.00", "30000.00")
    return credito, pago, (await _pendientes(db, credito))[0]


@pytest.mark.asyncio
class TestRolYObjetivo:
    @pytest.mark.parametrize("rol", [TipoUsuario.admin, TipoUsuario.registrador], ids=lambda r: r.value)
    async def test_admin_y_registrador_revierten_sin_indicar_motivo(self, db, como, registrado, rol):
        credito, pago, _ = registrado
        client, _ = como(rol)

        r = await client.post(_url(pago))

        assert r.status_code == 200, r.text
        assert (r.json()["id"], r.json()["pagado"], r.json()["fecha_pago_real"]) == (str(pago.id), False, None)
        assert (await _estado(db, credito))[0]["saldo_capital"] == Decimal("1000000.00")

    @pytest.mark.parametrize("rol", [TipoUsuario.recaudador, TipoUsuario.gestor], ids=lambda r: r.value)
    async def test_otros_roles_reciben_403_y_nada_cambia(self, db, como, registrado, rol):
        credito, pago, _ = registrado
        antes = await _estado(db, credito)
        client, _ = como(rol)

        r = await client.post(_url(pago))

        assert r.status_code == 403
        assert await _estado(db, credito) == antes

    async def test_cuota_sin_monto_registrado_se_rechaza_con_detail_de_texto(self, db, como, registrado, caplog):
        credito, _, sucesora = registrado
        antes = await _estado(db, credito)
        client, _ = como(TipoUsuario.admin)

        r = await client.post(_url(sucesora))

        assert (r.status_code, r.json().get("detail")) == (422, SIN_MONTO)
        assert await _estado(db, credito) == antes
        assert "motivo=no_pagado" in caplog.text

    async def test_segunda_llamada_sobre_la_misma_cuota_se_rechaza(self, db, como, registrado):
        credito, pago, _ = registrado
        client, _ = como(TipoUsuario.admin)
        assert (await client.post(_url(pago))).status_code == 200
        revertido = await _estado(db, credito)

        r = await client.post(_url(pago))

        assert (r.status_code, r.json().get("detail")) == (422, SIN_MONTO)
        assert await _estado(db, credito) == revertido


@pytest.mark.asyncio
class TestAuditoria:
    async def test_audita_pago_sucesora_y_credito_a_nombre_de_quien_revierte(self, db, como, registrado):
        credito, pago, sucesora = registrado
        client, user = como(TipoUsuario.registrador)

        r = await client.post(_url(pago), json={"motivo": "monto digitado mal"})

        assert r.status_code == 200, r.text
        filas = (await db.scalars(select(AuditLog).where(AuditLog.usuario_id == user.id))).all()
        U = AccionAudit.UPDATE
        assert {(a.entidad_id, a.accion, a.campo_modificado, a.valor_anterior, a.valor_nuevo) for a in filas} == {
            (pago.id, U, "pagado", "True", "False"), (pago.id, U, "capital_pagado", "100000.00", "0.00"),
            (pago.id, U, "interes_pagado", "30000.00", "0.00"), (pago.id, U, "fecha_pago_real", "2026-03-01", "None"),
            (pago.id, U, "motivo_reversion", "None", "monto digitado mal"),
            (sucesora.id, AccionAudit.DELETE, None, None, None),
            (credito.id, U, "saldo_capital", "900000.00", "1000000.00"),
            (credito.id, U, "saldo_intereses", "270000.00", "300000.00"),
        }

    async def test_un_pago_no_programado_se_audita_como_eliminacion_y_motivo(self, db, como, registrado):
        credito, _, _ = registrado
        u = await _no_programada(db, credito)
        client, user = como(TipoUsuario.admin)

        r = await client.post(_url(u), json={"motivo": "pago duplicado"})

        assert r.status_code == 200, r.text
        filas = (await db.scalars(select(AuditLog).where(AuditLog.entidad_id == u.id))).all()
        assert {(a.accion, a.campo_modificado, a.valor_nuevo, a.usuario_id) for a in filas} == {
            (AccionAudit.DELETE, None, None, user.id),
            (AccionAudit.UPDATE, "motivo_reversion", "pago duplicado", user.id),
        }


@pytest.mark.asyncio
class TestOrdenLifo:
    async def test_una_cuota_anterior_se_rechaza_hasta_revertir_la_ultima(self, db, como, registrado, caplog):
        credito, p1, p2 = registrado
        await _registrar(db, credito, p2, "100000.00", "30000.00")
        p3 = (await _pendientes(db, credito))[0]
        await _registrar(db, credito, p3, "100000.00", "30000.00")
        client, _ = como(TipoUsuario.admin)
        antes = await _estado(db, credito)

        r = await client.post(_url(p1))

        assert (r.status_code, r.json().get("detail")) == (422, PRIMERO.format("la cuota #3"))
        assert await _estado(db, credito) == antes
        assert "motivo=lifo" in caplog.text
        for pago in (p3, p2, p1):
            assert (await client.post(_url(pago))).status_code == 200

    async def test_un_pago_no_programado_posterior_cuenta_como_posterior(self, db, como, registrado):
        credito, p1, _ = registrado
        u = await _no_programada(db, credito)
        client, _ = como(TipoUsuario.registrador)
        antes = await _estado(db, credito)

        r = await client.post(_url(p1))

        assert (r.status_code, r.json().get("detail")) == (422, PRIMERO.format("el pago no programado"))
        assert await _estado(db, credito) == antes
        assert (await client.post(_url(u))).status_code == 200
        assert (await client.post(_url(p1))).status_code == 200

    async def test_un_pago_no_programado_entre_la_creacion_y_el_pago_de_una_cuota_es_anterior(self, db, como, registrado):
        """Cuota #2 is created BEFORE the no_programada U but paid AFTER it (same day): U is the earlier payment."""
        credito, _, p2 = registrado
        u = await _no_programada(db, credito)
        await _registrar(db, credito, p2, "100000.00", "30000.00")
        client, _ = como(TipoUsuario.admin)

        for pago in (p2, u):
            assert (await client.post(_url(pago))).status_code == 200

    async def test_el_orden_es_por_fecha_de_pago_y_no_por_numero_de_cuota(self, db, como, registrado):
        """A no_programada backdated before cuota #1 takes numero_cuota 3, yet it is the EARLIER payment."""
        credito, p1, _ = registrado
        u = await _no_programada(db, credito, fecha=date(2026, 2, 15))
        assert u.numero_cuota > p1.numero_cuota
        client, _ = como(TipoUsuario.admin)

        r = await client.post(_url(u))

        assert (r.status_code, r.json().get("detail")) == (422, PRIMERO.format("la cuota #1"))
        assert (await client.post(_url(p1))).status_code == 200


@pytest.mark.asyncio
class TestCuotaSucesora:
    @pytest.mark.parametrize("pagada", [False, True], ids=["con-montos-sin-pagar", "pagada-y-anterior-por-fecha"])
    async def test_sucesora_con_montos_o_pagada_se_rechaza(self, db, como, registrado, caplog, pagada):
        credito, p1, p2 = registrado
        if pagada:
            await _registrar(db, credito, p2, "100000.00", "30000.00")
            p1.fecha_pago_real = date(2026, 3, 2)  # P1 now sorts after P2: only the successor guard can stop it
        else:
            p2.capital_pagado = Decimal("1000.00")
        antes = await _estado(db, credito)
        client, _ = como(TipoUsuario.admin)

        r = await client.post(_url(p1))

        assert (r.status_code, r.json().get("detail")) == (422, "La cuota siguiente ya tiene montos registrados.")
        assert await _estado(db, credito) == antes
        assert "motivo=sucesora_con_montos" in caplog.text

    async def test_mas_de_una_sucesora_impaga_es_inconsistente(self, db, como, registrado, caplog):
        credito, p1, p2 = registrado
        db.add(Pago(credito_id=credito.id, numero_cuota=3, tipo_cuota=p2.tipo_cuota, monto_a_pagar=p2.monto_a_pagar,
                    momento=p2.momento, fecha_maxima=p2.fecha_maxima))
        antes = await _estado(db, credito)
        client, _ = como(TipoUsuario.admin)

        r = await client.post(_url(p1))

        assert (r.status_code, r.json().get("detail")) == (422, "El crédito tiene más de una cuota siguiente pendiente.")
        assert await _estado(db, credito) == antes
        assert "motivo=sucesoras_multiples" in caplog.text

    async def test_sin_sucesora_revierte_y_reabre_el_credito_saldado(self, db, como):
        credito, pago = await _credito(db, capital="100000.00", cuotas=1)
        await _no_programada(db, credito)  # registered before the closing payment: it has no successor to date it
        await _registrar(db, credito, pago, "100000.00", "3000.00")
        assert (credito.activo, await _pendientes(db, credito)) == (False, [])
        client, _ = como(TipoUsuario.registrador)

        r = await client.post(_url(pago))

        assert r.status_code == 200, r.text
        assert (credito.activo, await _pendientes(db, credito)) == (True, [pago])
