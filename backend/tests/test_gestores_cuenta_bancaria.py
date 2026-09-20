"""
tests/test_gestores_cuenta_bancaria.py — Asignación de cuenta bancaria a
gestores y propagación a pagos no pagados (receiver-bank-account-assignment,
PR2a).

Covers: crear/actualizar gestor con `cuenta_bancaria_id` -> `GestorResponse`
expone `cuenta_bancaria_id` y la cuenta anidada (incl. su receptor); cuenta
desconocida -> 404 sin persistir; `PATCH /gestores/{id}` cambiando
`cuenta_bancaria_id` propaga a los pagos no pagados y no eliminados de los
créditos de sus clientes activos (los pagados no cambian); un segundo gestor
en la misma cuenta original no se ve afectado; `cuenta_bancaria_id: null`
no propaga. Fixtures de usuario copiadas de
`test_cuentas_bancarias_predeterminada.py`.
"""
import uuid
from datetime import date, datetime, timezone
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


def _mk_usuario_gestor() -> Usuario:
    return Usuario(
        id=uuid.uuid4(), username=f"gestor{uuid.uuid4().hex[:8]}",
        password_hash="x", telefono="3000000000",
        tipo_usuario=TipoUsuario.gestor, activo=True,
    )


def _mk_gestor(*, user_id: uuid.UUID, cuenta_bancaria_id: uuid.UUID | None = None) -> Gestor:
    return Gestor(
        id=uuid.uuid4(), user_id=user_id, cedula=str(uuid.uuid4().int)[:10],
        nombre="Gestor", apellidos=f"Prueba{uuid.uuid4().hex[:6]}", telefono="3000000000",
        direccion="Calle 1", correo_electronico=f"{uuid.uuid4().hex[:8]}@test.com",
        cuenta_bancaria_id=cuenta_bancaria_id,
    )


def _mk_cliente(gestor_id: uuid.UUID) -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=gestor_id, nombre="Cliente",
        apellidos=f"Prueba{uuid.uuid4().hex[:6]}", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle 2",
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Test-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija, capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0300"), fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1), periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("1000000.00"), saldo_intereses=Decimal("30000.00"),
        numero_cuotas=12, activo=True,
    )


def _mk_pago(
    credito_id: uuid.UUID, *, pagado: bool = False, cuenta_bancaria_id: uuid.UUID | None = None,
    numero_cuota: int = 1,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=numero_cuota,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("100000.00"),
        capital_a_pagar=Decimal("70000.00"), interes_a_pagar=Decimal("30000.00"),
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=pagado,
        cuenta_bancaria_id=cuenta_bancaria_id,
    )


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
async def test_crear_gestor_con_cuenta_expone_resumen_anidado(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    usuario = _mk_usuario_gestor()
    db_session.add_all([receptor, cuenta, usuario])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(
        "/api/v1/gestores",
        json={
            "user_id": str(usuario.id),
            "cedula": str(uuid.uuid4().int)[:10],
            "nombre": "Nuevo",
            "apellidos": "Gestor",
            "telefono": "3000000000",
            "direccion": "Calle 3",
            "correo_electronico": f"{uuid.uuid4().hex[:8]}@test.com",
            "cuenta_bancaria_id": str(cuenta.id),
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["cuenta_bancaria_id"] == str(cuenta.id)
    assert body["cuenta_bancaria"]["id"] == str(cuenta.id)
    assert body["cuenta_bancaria"]["receptor"]["id"] == str(receptor.id)


@pytest.mark.asyncio
async def test_crear_gestor_con_cuenta_desconocida_404_sin_persistir(client_factory, db_session):
    usuario = _mk_usuario_gestor()
    db_session.add(usuario)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(
        "/api/v1/gestores",
        json={
            "user_id": str(usuario.id),
            "cedula": str(uuid.uuid4().int)[:10],
            "nombre": "Nuevo",
            "apellidos": "Gestor",
            "telefono": "3000000000",
            "direccion": "Calle 3",
            "correo_electronico": f"{uuid.uuid4().hex[:8]}@test.com",
            "cuenta_bancaria_id": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 404
    from sqlalchemy import select
    count = (await db_session.execute(
        select(Gestor).where(Gestor.user_id == usuario.id)
    )).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_patch_gestor_propaga_a_no_pagados_no_a_pagados(client_factory, db_session):
    """Req: Gestor Account Assignment and Propagation — 'Propagates to unpaid only'."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    usuario = _mk_usuario_gestor()
    db_session.add_all([receptor, cuenta_a, cuenta_b, usuario])
    await db_session.flush()

    gestor = _mk_gestor(user_id=usuario.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(gestor)
    await db_session.flush()

    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()

    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()

    pago_pagado = _mk_pago(credito.id, pagado=True, cuenta_bancaria_id=cuenta_a.id, numero_cuota=1)
    pago_no_pagado = _mk_pago(credito.id, pagado=False, cuenta_bancaria_id=cuenta_a.id, numero_cuota=2)
    db_session.add_all([pago_pagado, pago_no_pagado])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/gestores/{gestor.id}", json={"cuenta_bancaria_id": str(cuenta_b.id)}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cuenta_bancaria_id"] == str(cuenta_b.id)
    # La cuenta anidada debe reflejar la NUEVA cuenta, no la cargada antes del cambio
    assert body["cuenta_bancaria"]["id"] == str(cuenta_b.id)
    assert body["cuenta_bancaria"]["receptor"]["id"] == str(receptor.id)

    await db_session.refresh(pago_pagado)
    await db_session.refresh(pago_no_pagado)
    assert pago_pagado.cuenta_bancaria_id == cuenta_a.id
    assert pago_no_pagado.cuenta_bancaria_id == cuenta_b.id


@pytest.mark.asyncio
async def test_patch_gestor_sin_cuenta_a_cuenta_expone_resumen_anidado(client_factory, db_session):
    """Gestor sin cuenta (null) -> PATCH asigna cuenta B: la respuesta anida la cuenta B."""
    receptor = _mk_receptor()
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=True)
    usuario = _mk_usuario_gestor()
    db_session.add_all([receptor, cuenta_b, usuario])
    await db_session.flush()

    gestor = _mk_gestor(user_id=usuario.id, cuenta_bancaria_id=None)
    db_session.add(gestor)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/gestores/{gestor.id}", json={"cuenta_bancaria_id": str(cuenta_b.id)}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cuenta_bancaria_id"] == str(cuenta_b.id)
    assert body["cuenta_bancaria"] is not None
    assert body["cuenta_bancaria"]["id"] == str(cuenta_b.id)
    assert body["cuenta_bancaria"]["receptor"]["id"] == str(receptor.id)


@pytest.mark.asyncio
async def test_patch_gestor_no_propaga_a_pagos_eliminados(client_factory, db_session):
    """Req: propaga solo a pagos no pagados y NO eliminados (soft-delete conserva su cuenta)."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    usuario = _mk_usuario_gestor()
    db_session.add_all([receptor, cuenta_a, cuenta_b, usuario])
    await db_session.flush()

    gestor = _mk_gestor(user_id=usuario.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(gestor)
    await db_session.flush()

    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()

    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()

    pago_eliminado = _mk_pago(credito.id, pagado=False, cuenta_bancaria_id=cuenta_a.id, numero_cuota=1)
    pago_eliminado.deleted_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    pago_vigente = _mk_pago(credito.id, pagado=False, cuenta_bancaria_id=cuenta_a.id, numero_cuota=2)
    db_session.add_all([pago_eliminado, pago_vigente])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/gestores/{gestor.id}", json={"cuenta_bancaria_id": str(cuenta_b.id)}
    )

    assert resp.status_code == 200, resp.text
    await db_session.refresh(pago_eliminado)
    await db_session.refresh(pago_vigente)
    assert pago_eliminado.cuenta_bancaria_id == cuenta_a.id
    assert pago_vigente.cuenta_bancaria_id == cuenta_b.id


@pytest.mark.asyncio
async def test_patch_gestor_no_afecta_otro_gestor_en_la_misma_cuenta(client_factory, db_session):
    """Req: Gestor Account Assignment and Propagation — 'Other gestor untouched'."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    usuario1 = _mk_usuario_gestor()
    usuario2 = _mk_usuario_gestor()
    db_session.add_all([receptor, cuenta_a, cuenta_b, usuario1, usuario2])
    await db_session.flush()

    gestor1 = _mk_gestor(user_id=usuario1.id, cuenta_bancaria_id=cuenta_a.id)
    gestor2 = _mk_gestor(user_id=usuario2.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add_all([gestor1, gestor2])
    await db_session.flush()

    cliente2 = _mk_cliente(gestor2.id)
    db_session.add(cliente2)
    await db_session.flush()

    credito2 = _mk_credito(cliente2.id)
    db_session.add(credito2)
    await db_session.flush()

    pago2 = _mk_pago(credito2.id, pagado=False, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(pago2)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/gestores/{gestor1.id}", json={"cuenta_bancaria_id": str(cuenta_b.id)}
    )

    assert resp.status_code == 200, resp.text
    await db_session.refresh(pago2)
    assert pago2.cuenta_bancaria_id == cuenta_a.id


@pytest.mark.asyncio
async def test_patch_gestor_cuenta_null_no_propaga(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    usuario = _mk_usuario_gestor()
    db_session.add_all([receptor, cuenta_a, usuario])
    await db_session.flush()

    gestor = _mk_gestor(user_id=usuario.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(gestor)
    await db_session.flush()

    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()

    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()

    pago = _mk_pago(credito.id, pagado=False, cuenta_bancaria_id=cuenta_a.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.patch(
        f"/api/v1/gestores/{gestor.id}", json={"nombre": "Cambiado", "cuenta_bancaria_id": None}
    )

    assert resp.status_code == 200, resp.text
    await db_session.refresh(pago)
    assert pago.cuenta_bancaria_id == cuenta_a.id
