"""
tests/test_pago_reparto_router.py — `GET`/`PUT /pagos/{id}/repartos`
(payment-multi-recipient, item 10, PR2): matriz de roles, auditoría, y el
wiring end-to-end del reemplazo + herencia (task 2.7/2.8).

Cobertura de validación (suma exacta, duplicados, existencia) ya vive en
`test_pago_reparto_service.py::TestReemplazarRepartos` — acá solo se prueba
UN caso 422 de punta a punta para confirmar que el router traduce
`ValueError` -> 422 (igual que `registrar_pago`/`confirmar_excedente`).
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
from app.models.pago import Pago, TipoCuota
from app.models.pago_reparto import PagoReparto, TipoDestinatario
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.usuario import TipoUsuario, Usuario


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


def _mk_receptor(**kwargs) -> Receptor:
    defaults = dict(
        id=uuid.uuid4(), nombre=f"Receptor {uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
    )
    defaults.update(kwargs)
    return Receptor(**defaults)


def _mk_cuenta(receptor_id: uuid.UUID, *, etiqueta="A") -> CuentaBancaria:
    return CuentaBancaria(
        id=uuid.uuid4(), receptor_id=receptor_id, entidad_bancaria=etiqueta,
        tipo_cuenta=TipoCuenta.ahorros, numero_cuenta=f"{etiqueta}1",
        es_predeterminada=False,
    )


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Reparto", apellidos=f"Router{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"RepartoRouter-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )


def _mk_pago(credito_id: uuid.UUID, **overrides) -> Pago:
    base = dict(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("100.00"),
        capital_a_pagar=Decimal("80.00"), interes_a_pagar=Decimal("20.00"),
        capital_pagado=Decimal("80.00"), interes_pagado=Decimal("20.00"),
        momento="m3", fecha_maxima=date(2026, 2, 10),
        pagado=True, validado_recaudador=True, es_ultimo_pago=False,
        cuenta_bancaria_id=None,
    )
    base.update(overrides)
    return Pago(**base)


@pytest_asyncio.fixture
async def client_factory(db_session):
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


async def _preparar_pago_pagado(db_session, **pago_overrides) -> tuple[Pago, CuentaBancaria]:
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id)
    cliente = _mk_cliente()
    db_session.add_all([receptor, cuenta, cliente])
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, cuenta_bancaria_id=cuenta.id, **pago_overrides)
    db_session.add(pago)
    await db_session.flush()
    return pago, cuenta


@pytest.mark.asyncio
async def test_get_repartos_devuelve_las_filas_activas(client_factory, db_session):
    pago, cuenta = await _preparar_pago_pagado(db_session)
    reparto = PagoReparto(
        id=uuid.uuid4(), pago_id=pago.id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
        cuenta_bancaria_id=cuenta.id, monto=Decimal("100.00"),
    )
    db_session.add(reparto)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(f"/api/v1/pagos/{pago.id}/repartos")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["cuenta_bancaria_id"] == str(cuenta.id)
    assert body[0]["monto"] == "100.00"
    assert "·" in body[0]["etiqueta"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rol,esperado", [
        (TipoUsuario.registrador, 403),
        (TipoUsuario.admin, 200),
        (TipoUsuario.recaudador, 200),
    ],
)
async def test_matriz_roles_get_repartos(client_factory, db_session, rol, esperado):
    pago, _ = await _preparar_pago_pagado(db_session)
    client = await client_factory(_mk_user(rol))
    resp = await client.get(f"/api/v1/pagos/{pago.id}/repartos")
    assert resp.status_code == esperado, resp.text


@pytest.mark.asyncio
async def test_put_repartos_reemplaza_y_audita(client_factory, db_session):
    """Req: Split Allocation Persistence + audit_log via
    audit_service.registrar_actualizacion_campos (task 2.7)."""
    pago, cuenta_a = await _preparar_pago_pagado(db_session)
    receptor_b = _mk_receptor()
    cuenta_b = _mk_cuenta(receptor_b.id, etiqueta="B")
    db_session.add_all([receptor_b, cuenta_b])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(
        f"/api/v1/pagos/{pago.id}/repartos",
        json={"repartos": [
            {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta_a.id), "monto": "60.00"},
            {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta_b.id), "monto": "40.00"},
        ]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    montos = {item["cuenta_bancaria_id"]: item["monto"] for item in body}
    assert montos[str(cuenta_a.id)] == "60.00"
    assert montos[str(cuenta_b.id)] == "40.00"

    activos = (await db_session.execute(
        select(PagoReparto).where(PagoReparto.pago_id == pago.id, PagoReparto.deleted_at == None)  # noqa: E711
    )).scalars().all()
    assert len(activos) == 2

    logs = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.entidad == "pagos", AuditLog.entidad_id == pago.id,
            AuditLog.campo_modificado == "repartos",
        )
    )).scalars().all()
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_put_repartos_limpia_siguiente_cuota_pendiente(client_factory, db_session):
    """Wiring end-to-end de `aplicar_herencia` (task 2.6/2.8) — 2
    destinatarios en el pago 1 limpian la cuenta heredada de la cuota 2 ya
    generada, y también queda auditado sobre la cuota 2."""
    pago, cuenta_a = await _preparar_pago_pagado(db_session)
    receptor_b = _mk_receptor()
    cuenta_b = _mk_cuenta(receptor_b.id, etiqueta="B")
    db_session.add_all([receptor_b, cuenta_b])
    await db_session.flush()
    siguiente = _mk_pago(
        pago.credito_id, numero_cuota=2, cuenta_bancaria_id=cuenta_a.id,
        pagado=False, validado_recaudador=False,
        capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
    )
    db_session.add(siguiente)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(
        f"/api/v1/pagos/{pago.id}/repartos",
        json={"repartos": [
            {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta_a.id), "monto": "60.00"},
            {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta_b.id), "monto": "40.00"},
        ]},
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(pago)
    assert pago.cuenta_bancaria_id is None
    await db_session.refresh(siguiente)
    assert siguiente.cuenta_bancaria_id is None

    logs_siguiente = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.entidad == "pagos", AuditLog.entidad_id == siguiente.id,
            AuditLog.campo_modificado == "cuenta_bancaria_id",
        )
    )).scalars().all()
    assert len(logs_siguiente) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rol,esperado", [
        (TipoUsuario.registrador, 403),
        (TipoUsuario.admin, 200),
        (TipoUsuario.recaudador, 200),
    ],
)
async def test_matriz_roles_put_repartos(client_factory, db_session, rol, esperado):
    pago, cuenta_a = await _preparar_pago_pagado(db_session)
    client = await client_factory(_mk_user(rol))
    resp = await client.put(
        f"/api/v1/pagos/{pago.id}/repartos",
        json={"repartos": [
            {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta_a.id), "monto": "100.00"},
        ]},
    )
    assert resp.status_code == esperado, resp.text


@pytest.mark.asyncio
async def test_put_repartos_suma_incorrecta_422(client_factory, db_session):
    pago, cuenta_a = await _preparar_pago_pagado(db_session)
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(
        f"/api/v1/pagos/{pago.id}/repartos",
        json={"repartos": [
            {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta_a.id), "monto": "50.00"},
        ]},
    )
    assert resp.status_code == 422, resp.text

    activos = (await db_session.execute(
        select(PagoReparto).where(PagoReparto.pago_id == pago.id)
    )).scalars().all()
    assert activos == []


@pytest.mark.asyncio
async def test_put_repartos_pago_pendiente_422(client_factory, db_session):
    pago, cuenta_a = await _preparar_pago_pagado(
        db_session, pagado=False, capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
    )
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(
        f"/api/v1/pagos/{pago.id}/repartos",
        json={"repartos": [
            {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta_a.id), "monto": "100.00"},
        ]},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_put_repartos_mismo_id_para_cuenta_y_cliente_422(client_factory, db_session):
    """Guard Pydantic: exactamente uno de cuenta_bancaria_id/cliente_id."""
    pago, cuenta_a = await _preparar_pago_pagado(db_session)
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(
        f"/api/v1/pagos/{pago.id}/repartos",
        json={"repartos": [
            {
                "tipo_destinatario": "cuenta_bancaria",
                "cuenta_bancaria_id": str(cuenta_a.id),
                "cliente_id": str(uuid.uuid4()),
                "monto": "100.00",
            },
        ]},
    )
    assert resp.status_code == 422, resp.text
