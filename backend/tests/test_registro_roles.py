"""
tests/test_registro_roles.py — Role matrix for amount registration
(recaudo-registra-montos-registrador-supervisa, PR1).

`registrar`, `confirmar-excedente` and `no-programado` accept admin, registrador
and recaudador; any other role (gestor) gets 403 and nothing changes. Pago has no
"validated by" column, so a recaudador registering on a validated pago always
acts on one validated by someone else. Fixtures follow test_desvalidar_pago.py.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

_FAKE_GESTOR_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_SALDO_INICIAL = Decimal("1200000.00")


class _Caso(NamedTuple):
    path: str  # formatted with pago_id / credito_id
    body: dict
    status_ok: int
    saldo_capital_final: Decimal  # proves the registration logic ran, not just the gate

    def url(self, credito: Credito, pago: Pago) -> str:
        return self.path.format(pago_id=pago.id, credito_id=credito.id)


_CASOS = {
    "registrar": _Caso(
        "/api/v1/pagos/{pago_id}/registrar",
        {"capital_pagado": "100000.00", "interes_pagado": "10000.00"},
        200, Decimal("1100000.00"),
    ),
    "confirmar_excedente": _Caso(
        "/api/v1/pagos/{pago_id}/confirmar-excedente",
        {"capital_pagado": 105000.0, "interes_pagado": 10000.0, "destino_excedente": "capital"},
        200, Decimal("1095000.00"),
    ),
    "no_programado": _Caso(
        "/api/v1/pagos/no-programado/{credito_id}",
        {"monto": "50000.00", "destino": "capital", "fecha_pago": "2026-03-01"},
        201, Decimal("1150000.00"),
    ),
}
_POR_ENDPOINT = pytest.mark.parametrize("caso", _CASOS.values(), ids=list(_CASOS))


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


async def _seed(db_session) -> tuple[Credito, Pago]:
    """Active cuota_fija credit with one validated, unpaid cuota (100000 + 10000)."""
    cliente = Cliente(
        id=uuid.uuid4(), gestor_id=_FAKE_GESTOR_ID, nombre="Ana",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )
    credito = Credito(
        id=uuid.uuid4(), cliente_id=cliente.id,
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija, capital_prestado=_SALDO_INICIAL,
        tasa_interes_mensual=Decimal("0.0300"), fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1), periodicidad=Periodicidad.mensual,
        saldo_capital=_SALDO_INICIAL, saldo_intereses=Decimal("0.00"),
        numero_cuotas=12, activo=True,
    )
    pago = Pago(
        id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("110000.00"),
        capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("10000.00"),
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=False,
        validado_recaudador=True, tipo_validacion="completo",
    )
    db_session.add_all([cliente, credito, pago])
    await db_session.flush()
    return credito, pago


async def _pagados(db_session, credito_id) -> int:
    rows = await db_session.execute(
        select(Pago).where(Pago.credito_id == credito_id, Pago.pagado.is_(True))
    )
    return len(rows.scalars().all())


async def _audit_de(db_session, usuario_id) -> list[AuditLog]:
    rows = await db_session.execute(select(AuditLog).where(AuditLog.usuario_id == usuario_id))
    return list(rows.scalars().all())


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


class TestRegistroPorRol:
    @pytest.mark.parametrize(
        "rol",
        [TipoUsuario.admin, TipoUsuario.registrador, TipoUsuario.recaudador],
        ids=lambda r: r.value,
    )
    @_POR_ENDPOINT
    @pytest.mark.asyncio
    async def test_allowed_role_registers_and_audit_is_attributed(
        self, client_factory, db_session, rol, caso
    ):
        credito, pago = await _seed(db_session)
        user = _mk_user(rol)
        client = await client_factory(user)

        r = await client.post(caso.url(credito, pago), json=caso.body)

        assert r.status_code == caso.status_ok, r.text
        assert credito.saldo_capital == caso.saldo_capital_final
        assert await _pagados(db_session, credito.id) == 1
        assert {a.entidad for a in await _audit_de(db_session, user.id)} == {"pagos"}

    @_POR_ENDPOINT
    @pytest.mark.asyncio
    async def test_gestor_gets_403_and_nothing_changes(self, client_factory, db_session, caso):
        credito, pago = await _seed(db_session)
        user = _mk_user(TipoUsuario.gestor)
        client = await client_factory(user)

        r = await client.post(caso.url(credito, pago), json=caso.body)

        assert r.status_code == 403
        assert credito.saldo_capital == _SALDO_INICIAL
        assert pago.pagado is False
        assert await _pagados(db_session, credito.id) == 0
        assert await _audit_de(db_session, user.id) == []
