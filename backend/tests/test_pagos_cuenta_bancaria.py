"""
tests/test_pagos_cuenta_bancaria.py — PATCH de cuenta bancaria de un pago y
herencia de cuenta al generar la siguiente cuota (receiver-bank-account-
assignment, PR2a — subset PATCH + herencia; el subset de filtros en cascada
y reportes se agrega en PR2b).

Covers: `PATCH /pagos/{id}/cuenta-bancaria` mueve el pago a una cuenta de
OTRO receptor, expone el receptor derivado vía `cuenta_bancaria.receptor` y
audita `cuenta_bancaria_id` viejo -> nuevo; cuenta desconocida -> 404 sin
cambios; fila proyectada (virtual, sin id real) -> 404; el path viejo
`PATCH /pagos/{id}/receptor` -> 404/405; matriz de roles; al pagar una cuota,
la siguiente hereda `cuenta_bancaria_id` del pago recién pagado (que ya
refleja la cuenta vigente del gestor). Fixtures de usuario copiadas de
`test_cuentas_bancarias_predeterminada.py`.
"""
import uuid
from datetime import date
from decimal import Decimal
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
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.gestor import Gestor
from app.models.pago import Pago, TipoCuota
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.usuario import TipoUsuario, Usuario


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


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


def _mk_credito(cliente_id: uuid.UUID | None = None, **overrides) -> Credito:
    base = dict(
        id=uuid.uuid4(), cliente_id=cliente_id or uuid.uuid4(),
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija, capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0300"), fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1), periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("1000000.00"), saldo_intereses=Decimal("30000.00"),
        numero_cuotas=12, calcular_interes_dias_corridos=False, activo=True,
    )
    base.update(overrides)
    return Credito(**base)


def _mk_pago(credito_id: uuid.UUID, **overrides) -> Pago:
    base = dict(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("113333.33"),
        capital_a_pagar=Decimal("83333.33"), interes_a_pagar=Decimal("30000.00"),
        capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=False,
        validado_recaudador=False, cuenta_bancaria_id=None,
    )
    base.update(overrides)
    return Pago(**base)


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


@pytest.mark.asyncio
async def test_patch_cuenta_bancaria_mueve_a_otro_receptor(client_factory, db_session):
    """Req: Individual Payment Account Change — 'Move to another receptor's account'."""
    r1 = _mk_receptor()
    r2 = _mk_receptor()
    cuenta_a = _mk_cuenta(r1.id, etiqueta="A", predeterminada=True)
    cuenta_c = _mk_cuenta(r2.id, etiqueta="C", predeterminada=True)
    db_session.add_all([r1, r2, cuenta_a, cuenta_c])
    await db_session.flush()

    credito = _mk_credito()
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/pagos/{pago.id}/cuenta-bancaria",
        json={"cuenta_bancaria_id": str(cuenta_c.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cuenta_bancaria_id"] == str(cuenta_c.id)
    assert body["cuenta_bancaria"]["receptor"]["id"] == str(r2.id)

    logs = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.entidad == "pagos", AuditLog.entidad_id == pago.id,
            AuditLog.campo_modificado == "cuenta_bancaria_id",
        )
    )).scalars().all()
    assert len(logs) == 1
    assert logs[0].valor_anterior == str(cuenta_a.id)
    assert logs[0].valor_nuevo == str(cuenta_c.id)


@pytest.mark.asyncio
async def test_patch_cuenta_bancaria_desconocida_404_sin_cambios(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta_a])
    await db_session.flush()

    credito = _mk_credito()
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/pagos/{pago.id}/cuenta-bancaria",
        json={"cuenta_bancaria_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 404
    await db_session.refresh(pago)
    assert pago.cuenta_bancaria_id == cuenta_a.id
    logs = (await db_session.execute(
        select(AuditLog).where(AuditLog.entidad_id == pago.id)
    )).scalars().all()
    assert logs == []


@pytest.mark.asyncio
async def test_patch_cuenta_bancaria_fila_proyectada_404(client_factory, db_session):
    """Virtual/projected rows have no real id in the pagos table -> 404."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta_a])
    await db_session.flush()

    virtual_id = uuid.uuid5(uuid.NAMESPACE_OID, f"{uuid.uuid4()}-1")

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/pagos/{virtual_id}/cuenta-bancaria",
        json={"cuenta_bancaria_id": str(cuenta_a.id)},
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_path_viejo_receptor_ya_no_existe(client_factory, db_session):
    """Req: Individual Payment Account Change — old path MUST return 404 or 405."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta_a])
    await db_session.flush()

    credito = _mk_credito()
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/pagos/{pago.id}/receptor",
        json={"receptor_id": str(receptor.id)},
    )

    assert resp.status_code in (404, 405)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rol,esperado", [
        (TipoUsuario.registrador, 403),
        (TipoUsuario.admin, 200),
        (TipoUsuario.recaudador, 200),
    ],
)
async def test_matriz_roles_patch_cuenta_bancaria(client_factory, db_session, rol, esperado):
    """Req: Role Gates — 'Registrador cannot change payment account'."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    credito = _mk_credito()
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(rol))
    resp = await client.patch(
        f"/api/v1/pagos/{pago.id}/cuenta-bancaria",
        json={"cuenta_bancaria_id": str(cuenta_b.id)},
    )

    assert resp.status_code == esperado, resp.text
    await db_session.refresh(pago)
    if esperado == 200:
        assert pago.cuenta_bancaria_id == cuenta_b.id
    else:
        assert pago.cuenta_bancaria_id == cuenta_a.id


@pytest.mark.asyncio
async def test_siguiente_cuota_hereda_cuenta_vigente_tras_cambio_de_gestor(client_factory, db_session):
    """Req: Payment Account Inheritance — 'Next cuota inherits current account'."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    usuario = Usuario(
        id=uuid.uuid4(), username=f"gestor{uuid.uuid4().hex[:8]}",
        password_hash="x", telefono="3000000000",
        tipo_usuario=TipoUsuario.gestor, activo=True,
    )
    db_session.add_all([receptor, cuenta_a, cuenta_b, usuario])
    await db_session.flush()

    gestor = Gestor(
        id=uuid.uuid4(), user_id=usuario.id, cedula=str(uuid.uuid4().int)[:10],
        nombre="Gestor", apellidos="Prueba", telefono="3000000000",
        direccion="Calle 1", correo_electronico=f"{uuid.uuid4().hex[:8]}@test.com",
        cuenta_bancaria_id=cuenta_a.id,
    )
    db_session.add(gestor)
    await db_session.flush()

    cliente = Cliente(
        id=uuid.uuid4(), gestor_id=gestor.id, nombre="Cliente",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle 2",
    )
    db_session.add(cliente)
    await db_session.flush()

    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()

    pago1 = _mk_pago(
        credito.id, numero_cuota=1, cuenta_bancaria_id=cuenta_a.id, validado_recaudador=True,
    )
    db_session.add(pago1)
    await db_session.flush()

    # Gestor se mueve de A a B; el pago 1 (no pagado) se propaga a B.
    admin_client = await client_factory(_mk_user(TipoUsuario.admin))
    resp_patch = await admin_client.patch(
        f"/api/v1/gestores/{gestor.id}", json={"cuenta_bancaria_id": str(cuenta_b.id)}
    )
    assert resp_patch.status_code == 200, resp_patch.text
    await db_session.refresh(pago1)
    assert pago1.cuenta_bancaria_id == cuenta_b.id

    registrador_client = await client_factory(_mk_user(TipoUsuario.registrador))
    resp_pago = await registrador_client.post(
        f"/api/v1/pagos/{pago1.id}/registrar",
        json={"capital_pagado": "83333.33", "interes_pagado": "30000.00"},
    )
    assert resp_pago.status_code == 200, resp_pago.text

    siguiente = (await db_session.execute(
        select(Pago).where(Pago.credito_id == credito.id, Pago.numero_cuota == 2)
    )).scalar_one()
    assert siguiente.cuenta_bancaria_id == cuenta_b.id
