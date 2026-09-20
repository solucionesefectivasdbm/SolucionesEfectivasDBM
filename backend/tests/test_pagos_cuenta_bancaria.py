"""
tests/test_pagos_cuenta_bancaria.py — PATCH de cuenta bancaria de un pago,
herencia de cuenta al generar la siguiente cuota, y (PR2b) filtros en
cascada `receptor_id`/`cuenta_bancaria_id` de `GET /pagos`.

Covers: `PATCH /pagos/{id}/cuenta-bancaria` mueve el pago a una cuenta de
OTRO receptor, expone el receptor derivado vía `cuenta_bancaria.receptor` y
audita `cuenta_bancaria_id` viejo -> nuevo; cuenta desconocida -> 404 sin
cambios; fila proyectada (virtual, sin id real) -> 404; el path viejo
`PATCH /pagos/{id}/receptor` -> 404/405; matriz de roles; al pagar una cuota,
la siguiente hereda `cuenta_bancaria_id` del pago recién pagado (que ya
refleja la cuenta vigente del gestor). `GET /pagos?receptor_id` agrega todas
las cuentas del receptor; `cuenta_bancaria_id` acota; par no coincidente ->
422; cualquiera de los dos filtros suprime filas virtuales; filas reales
exponen `cuenta_bancaria` anidada. Fixtures de usuario copiadas de
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


# ─── PR2b: filtros en cascada de GET /pagos ─────────────────────────────────

def _mk_cliente(gestor_id: uuid.UUID | None = None) -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=gestor_id or uuid.uuid4(),
        nombre="Cliente", apellidos=f"Filtro{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


async def _datos_filtro_cascada(db_session):
    """R1 tiene cuentas A y B; R2 tiene cuenta C. Un pago real por cuenta,
    todos dentro de anio=2026/mes=2 (fecha_maxima 2026-02-01, ver _mk_pago)."""
    r1, r2 = _mk_receptor(), _mk_receptor()
    cuenta_a = _mk_cuenta(r1.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(r1.id, etiqueta="B")
    cuenta_c = _mk_cuenta(r2.id, etiqueta="C", predeterminada=True)
    db_session.add_all([r1, r2, cuenta_a, cuenta_b, cuenta_c])
    await db_session.flush()

    clientes = [_mk_cliente() for _ in range(3)]
    db_session.add_all(clientes)
    await db_session.flush()
    creditos = [_mk_credito(c.id) for c in clientes]
    db_session.add_all(creditos)
    await db_session.flush()
    pago_a = _mk_pago(creditos[0].id, cuenta_bancaria_id=cuenta_a.id)
    pago_b = _mk_pago(creditos[1].id, cuenta_bancaria_id=cuenta_b.id)
    pago_c = _mk_pago(creditos[2].id, cuenta_bancaria_id=cuenta_c.id)
    db_session.add_all([pago_a, pago_b, pago_c])
    await db_session.flush()
    return {"r1": r1, "r2": r2, "cuenta_b": cuenta_b, "cuenta_c": cuenta_c,
            "pago_a": pago_a, "pago_b": pago_b, "pago_c": pago_c}


@pytest.mark.asyncio
async def test_receptor_id_agrega_cuentas_del_receptor(client_factory, db_session):
    """Req: Cascading Filters on Payment Listing — 'Receptor-only aggregates accounts'."""
    d = await _datos_filtro_cascada(db_session)
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(f"/api/v1/pagos?anio=2026&mes=2&receptor_id={d['r1'].id}")
    assert resp.status_code == 200, resp.text
    ids = {i["id"] for i in resp.json()["items"]}
    assert ids == {str(d["pago_a"].id), str(d["pago_b"].id)}


@pytest.mark.asyncio
async def test_cuenta_bancaria_id_acota(client_factory, db_session):
    """Req: Cascading Filters on Payment Listing — 'Account narrows'."""
    d = await _datos_filtro_cascada(db_session)
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(
        f"/api/v1/pagos?anio=2026&mes=2&receptor_id={d['r1'].id}&cuenta_bancaria_id={d['cuenta_b'].id}"
    )
    assert resp.status_code == 200, resp.text
    ids = {i["id"] for i in resp.json()["items"]}
    assert ids == {str(d["pago_b"].id)}


@pytest.mark.asyncio
async def test_par_no_coincidente_422(client_factory, db_session):
    """Req: Cascading Filters on Payment Listing — 'Mismatched pair rejected'."""
    d = await _datos_filtro_cascada(db_session)
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(
        f"/api/v1/pagos?anio=2026&mes=2&receptor_id={d['r1'].id}&cuenta_bancaria_id={d['cuenta_c'].id}"
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_par_con_cuenta_inexistente_404(client_factory, db_session):
    """`receptor_id` + `cuenta_bancaria_id` desconocida -> 404 (no 422): la
    cuenta no existe, no es que pertenezca a otro receptor."""
    d = await _datos_filtro_cascada(db_session)
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(
        f"/api/v1/pagos?anio=2026&mes=2&receptor_id={d['r1'].id}&cuenta_bancaria_id={uuid.uuid4()}"
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_fila_real_expone_cuenta_bancaria_anidada(client_factory, db_session):
    d = await _datos_filtro_cascada(db_session)
    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(f"/api/v1/pagos?anio=2026&mes=2&cuenta_bancaria_id={d['cuenta_b'].id}")
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["cuenta_bancaria_id"] == str(d["cuenta_b"].id)
    assert item["cuenta_bancaria"]["entidad_bancaria"] == "B"
    assert item["cuenta_bancaria"]["receptor"]["id"] == str(d["r1"].id)


@pytest.mark.asyncio
async def test_filtro_activo_suprime_virtuales(client_factory, db_session):
    """Req: Cascading Filters on Payment Listing — 'Virtual rows suppressed'."""
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id, etiqueta="V", predeterminada=True)
    cliente = _mk_cliente()
    db_session.add_all([receptor, cuenta, cliente])
    await db_session.flush()

    # cuota1 pagada, cuota2 pendiente (bloqueadora, real, 2026-03-01) -> cuota3
    # se proyecta como virtual dentro del mismo mes de marzo (sin anchor de
    # fecha fija, el fallback avanza +30d = 2026-03-31; mismo patrón que
    # test_pagos_listado.py::datos_virtual_sucesor_de_bloqueadora_con_arrastre).
    credito = _mk_credito(cliente.id, numero_cuotas=3)
    db_session.add(credito)
    await db_session.flush()
    cuota1 = _mk_pago(
        credito.id, numero_cuota=1, cuenta_bancaria_id=cuenta.id,
        fecha_maxima=date(2026, 2, 1),
        pagado=True, capital_pagado=Decimal("83333.33"), interes_pagado=Decimal("30000.00"),
        validado_recaudador=True,
    )
    cuota2_bloqueadora = _mk_pago(
        credito.id, numero_cuota=2, cuenta_bancaria_id=cuenta.id,
        fecha_maxima=date(2026, 3, 1), pagado=False, validado_recaudador=False,
    )
    db_session.add_all([cuota1, cuota2_bloqueadora])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))

    # Sin filtro: la cuota #3 se proyecta como virtual dentro de marzo.
    sin_filtro = await client.get("/api/v1/pagos?anio=2026&mes=3")
    assert sin_filtro.status_code == 200, sin_filtro.text
    virtuales_sin_filtro = [i for i in sin_filtro.json()["items"] if i["es_proyectada"]]
    assert len(virtuales_sin_filtro) >= 1
    assert any(i["cuenta_bancaria"] is None for i in virtuales_sin_filtro)

    # Con filtro de cuenta activo: ninguna fila virtual (no tienen cuenta asignada).
    con_filtro = await client.get(f"/api/v1/pagos?anio=2026&mes=3&cuenta_bancaria_id={cuenta.id}")
    assert con_filtro.status_code == 200, con_filtro.text
    items_con_filtro = con_filtro.json()["items"]
    assert len(items_con_filtro) >= 1  # la cuota #2 real sí tiene la cuenta
    assert all(not i["es_proyectada"] for i in items_con_filtro)
