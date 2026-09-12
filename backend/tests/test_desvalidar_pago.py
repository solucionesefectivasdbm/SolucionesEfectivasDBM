"""
tests/test_desvalidar_pago.py — Reversal endpoint hardening (payment-reversal-recaudo-fix).

Covers: successful reversal + audit + logging, ordered rejections (pagado ->
montos registrados -> no validado) with logging and no mutation, role matrix
(admin/recaudador allowed, registrador/gestor 403 with zero DB writes/logs),
repeated calls (second call on an already-reverted pago is rejected; row
locking itself is NOT proven here — SQLite ignores `FOR UPDATE`, so this only
verifies sequential-call semantics, not true concurrent serialization), and
attempt logging via caplog against logger "app.routers.pagos".
"""
import logging
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

_FAKE_GESTOR_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_PAGOS_LOGGER = "app.routers.pagos"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=_FAKE_GESTOR_ID, nombre="Ana",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija, capital_prestado=Decimal("1200000.00"),
        tasa_interes_mensual=Decimal("0.0300"), fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1), periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("1200000.00"), saldo_intereses=Decimal("0.00"),
        numero_cuotas=12, activo=True,
    )


def _mk_pago(
    credito_id: uuid.UUID, *, validado_recaudador: bool = True, pagado: bool = False,
    capital_pagado: Decimal = Decimal("0.00"), interes_pagado: Decimal = Decimal("0.00"),
    tipo_validacion=None,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("110000.00"),
        capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("10000.00"),
        capital_pagado=capital_pagado, interes_pagado=interes_pagado,
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=pagado,
        validado_recaudador=validado_recaudador, tipo_validacion=tipo_validacion,
    )


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


async def _audit_rows(db_session, pago_id):
    return (await db_session.execute(
        select(AuditLog).where(AuditLog.entidad_id == pago_id)
    )).scalars().all()


@pytest_asyncio.fixture
async def client_factory(db_session):
    """Returns a factory that builds an AsyncClient overridden for a given user."""
    created = []

    async def _make(user: MagicMock) -> AsyncClient:
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


class TestSuccessfulReversal:
    @pytest.mark.asyncio
    async def test_reversal_clears_flags_writes_audit_and_logs(self, client_factory, db_session, caplog):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, validado_recaudador=True, tipo_validacion="completo")
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        with caplog.at_level(logging.INFO, logger=_PAGOS_LOGGER):
            r = await client.post(f"/api/v1/pagos/{pago.id}/desvalidar")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["validado_recaudador"] is False
        assert body["tipo_validacion"] is None

        rows = await _audit_rows(db_session, pago.id)
        campos = {row.campo_modificado: row for row in rows}
        assert "validado_recaudador" in campos
        assert campos["validado_recaudador"].usuario_id == admin.id
        # tipo_validacion estaba seteado ("completo") -> también debe auditarse
        # su reseteo a None, para no perder trazabilidad del valor anterior.
        assert "tipo_validacion" in campos
        assert campos["tipo_validacion"].valor_anterior == "completo"
        assert len(rows) == 2

        info_lines = [rec.message for rec in caplog.records if rec.levelno == logging.INFO]
        assert sum("DESVALIDAR OK" in msg for msg in info_lines) == 1


class TestReversalRejections:
    @pytest.mark.parametrize(
        "kwargs,detail,motivo",
        [
            (dict(pagado=True), "No se puede revertir: el pago ya fue registrado con montos.", "pagado"),
            (
                dict(capital_pagado=Decimal("50000.00")),
                "No se puede revertir: el pago tiene montos registrados.",
                "montos_registrados",
            ),
            (dict(validado_recaudador=False), "Este pago no estaba validado.", "no_validado"),
            (
                dict(pagado=True, capital_pagado=Decimal("100000.00"), interes_pagado=Decimal("10000.00")),
                "No se puede revertir: el pago ya fue registrado con montos.",
                "pagado",
            ),
        ],
        ids=["ya_pagado", "montos_registrados", "no_validado", "orden_pagado_antes_de_montos"],
    )
    @pytest.mark.asyncio
    async def test_rejection_no_mutation_and_logs_motivo(
        self, client_factory, db_session, caplog, kwargs, detail, motivo
    ):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        base_kwargs = dict(validado_recaudador=True)
        base_kwargs.update(kwargs)
        pago = _mk_pago(credito.id, **base_kwargs)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        admin = _mk_user(TipoUsuario.admin)
        client = await client_factory(admin)

        with caplog.at_level(logging.WARNING, logger=_PAGOS_LOGGER):
            r = await client.post(f"/api/v1/pagos/{pago.id}/desvalidar")

        assert r.status_code == 422
        assert r.json()["detail"] == detail
        assert len(await _audit_rows(db_session, pago.id)) == 0

        warn_lines = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
        assert sum(f"motivo={motivo}" in msg for msg in warn_lines) == 1
        if motivo == "pagado" and kwargs.get("capital_pagado"):
            assert not any("motivo=montos_registrados" in msg for msg in warn_lines)


class TestRoleMatrix:
    @pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor])
    @pytest.mark.asyncio
    async def test_forbidden_roles_no_db_write_no_log(self, client_factory, db_session, caplog, rol):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, validado_recaudador=True)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(_mk_user(rol))

        with caplog.at_level(logging.INFO, logger=_PAGOS_LOGGER):
            r = await client.post(f"/api/v1/pagos/{pago.id}/desvalidar")

        assert r.status_code == 403
        await db_session.refresh(pago)
        assert pago.validado_recaudador is True
        assert len(await _audit_rows(db_session, pago.id)) == 0
        app_records = [rec for rec in caplog.records if rec.name == _PAGOS_LOGGER]
        assert len(app_records) == 0

    @pytest.mark.parametrize("rol", [TipoUsuario.admin, TipoUsuario.recaudador])
    @pytest.mark.asyncio
    async def test_allowed_roles_can_reverse(self, client_factory, db_session, rol):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, validado_recaudador=True)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(_mk_user(rol))
        r = await client.post(f"/api/v1/pagos/{pago.id}/desvalidar")
        assert r.status_code == 200, r.text


class TestRepeatedCalls:
    @pytest.mark.asyncio
    async def test_second_call_on_reverted_pago_returns_422(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id, validado_recaudador=True)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(_mk_user(TipoUsuario.admin))

        r1 = await client.post(f"/api/v1/pagos/{pago.id}/desvalidar")
        assert r1.status_code == 200, r1.text

        r2 = await client.post(f"/api/v1/pagos/{pago.id}/desvalidar")
        assert r2.status_code == 422
        assert r2.json()["detail"] == "Este pago no estaba validado."
        assert len(await _audit_rows(db_session, pago.id)) == 1
