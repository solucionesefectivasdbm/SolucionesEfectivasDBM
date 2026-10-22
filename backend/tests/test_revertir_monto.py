"""
tests/test_revertir_monto.py — POST /pagos/{id}/revertir-monto (PR2b, design D1/D8).

The "before" state comes from the REAL forward services on SQLite; the endpoint then runs through httpx/ASGI.
The session mimics production (autoflush=False) and the get_db override flushes after each request, like the
real commit. SQLite ignores FOR UPDATE: the lock is not proven here, only sequential double-call semantics.
The service rules (D2-D7) are covered in test_revertir_monto_servicio.py.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.pago import RegistrarPagoRequest
from app.services.credito_service import crear_primera_cuota
from app.services.pago_service import PagoService

FECHA = date(2026, 3, 1)  # fecha_pago_real of every forward registration
SIN_MONTO = "Esta cuota no tiene un monto registrado para revertir."


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
            user.id, user.tipo_usuario, user.activo, user.deleted_at = uuid.uuid4(), rol, True, None
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
    await db.flush()
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


async def _estado(db, credito) -> list[dict]:
    """Persisted columns (but updated_at) of the credit and of every cuota (soft-deleted too), read back from the DB."""
    await db.flush()
    await db.refresh(credito)
    cuotas = (await db.scalars(
        select(Pago).where(Pago.credito_id == credito.id).order_by(Pago.numero_cuota, Pago.id)
        .execution_options(populate_existing=True)
    )).all()
    return [
        {c.name: getattr(o, c.name) for c in o.__table__.columns if c.name != "updated_at"}
        for o in (credito, *cuotas)
    ]


def _url(pago: Pago) -> str:
    return f"/api/v1/pagos/{pago.id}/revertir-monto"


@pytest_asyncio.fixture
async def registrado(db) -> tuple[Credito, Pago, Pago]:
    """cuota #1 (100000 + 30000) paid exactly -> balances 900000 / 270000.
    Returns (credito, cuota #1, cuota #2 generated by that registration)."""
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
        assert pago.pagado is True  # the registered state the 403 left untouched

    async def test_cuota_sin_monto_registrado_se_rechaza_con_detail_de_texto(self, db, como, registrado):
        credito, _, sucesora = registrado
        antes = await _estado(db, credito)
        client, _ = como(TipoUsuario.admin)

        r = await client.post(_url(sucesora))

        assert (r.status_code, r.json()["detail"]) == (422, SIN_MONTO)
        assert await _estado(db, credito) == antes

    async def test_segunda_llamada_sobre_la_misma_cuota_se_rechaza(self, db, como, registrado):
        credito, pago, _ = registrado
        client, _ = como(TipoUsuario.admin)
        assert (await client.post(_url(pago))).status_code == 200
        revertido = await _estado(db, credito)

        r = await client.post(_url(pago))

        assert (r.status_code, r.json()["detail"]) == (422, SIN_MONTO)
        assert await _estado(db, credito) == revertido
