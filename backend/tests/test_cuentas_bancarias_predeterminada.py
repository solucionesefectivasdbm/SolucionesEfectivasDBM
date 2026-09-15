"""
tests/test_cuentas_bancarias_predeterminada.py — Regla de cuenta predeterminada
(receiver-bank-account-assignment, PR1a).

Covers: primera cuenta es predeterminada; segunda no lo es; PUT
.../predeterminada intercambia el default atómicamente; el cambio de default
NO mueve asignaciones existentes de gestores/pagos; cuenta de otro receptor ->
404; llamada idempotente; roles no admin -> 403 sin escrituras; el índice
único parcial se aplica en SQLite vía inserción ORM directa; el response
expone `es_predeterminada`. Fixtures de usuario copiadas de
test_desvalidar_pago.py.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AuditLog
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
async def test_primera_cuenta_es_predeterminada(client_factory, db_session):
    receptor = _mk_receptor()
    db_session.add(receptor)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(
        f"/api/v1/receptores/{receptor.id}/cuentas",
        json={"entidad_bancaria": "Bancolombia", "tipo_cuenta": "Ahorros", "numero_cuenta": "111"},
    )

    assert resp.status_code == 201
    assert resp.json()["es_predeterminada"] is True


@pytest.mark.asyncio
async def test_segunda_cuenta_no_es_predeterminada(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta_a])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(
        f"/api/v1/receptores/{receptor.id}/cuentas",
        json={"entidad_bancaria": "Davivienda", "tipo_cuenta": "Corriente", "numero_cuenta": "222"},
    )

    assert resp.status_code == 201
    assert resp.json()["es_predeterminada"] is False
    await db_session.refresh(cuenta_a)
    assert cuenta_a.es_predeterminada is True


@pytest.mark.asyncio
async def test_admin_cambia_predeterminada_sin_mover_asignaciones(client_factory, db_session):
    """Admin flips the default (A -> B) atomically; existing gestor/pago on A are untouched."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    gestor = Gestor(
        id=uuid.uuid4(), user_id=uuid.uuid4(), cedula=str(uuid.uuid4().int)[:10],
        nombre="Gestor", apellidos="Prueba", telefono="3000000000",
        direccion="Calle 1", correo_electronico=f"{uuid.uuid4().hex[:8]}@test.com",
        cuenta_bancaria_id=cuenta_a.id,
    )
    db_session.add_all([receptor, cuenta_a, cuenta_b, gestor])
    await db_session.flush()
    pago = Pago(
        id=uuid.uuid4(), credito_id=uuid.uuid4(), numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("100000.00"),
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=False,
        cuenta_bancaria_id=cuenta_a.id,
    )
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(f"/api/v1/receptores/{receptor.id}/cuentas/{cuenta_b.id}/predeterminada")

    assert resp.status_code == 200
    assert resp.json()["es_predeterminada"] is True
    await db_session.refresh(cuenta_a)
    await db_session.refresh(cuenta_b)
    await db_session.refresh(gestor)
    await db_session.refresh(pago)
    assert cuenta_a.es_predeterminada is False
    assert cuenta_b.es_predeterminada is True
    assert gestor.cuenta_bancaria_id == cuenta_a.id
    assert pago.cuenta_bancaria_id == cuenta_a.id

    # A-F3: exactamente un registro de auditoría por el cambio A -> B.
    audit_query = select(AuditLog).where(
        AuditLog.entidad == "receptores",
        AuditLog.entidad_id == receptor.id,
        AuditLog.campo_modificado == "es_predeterminada",
    )
    logs = (await db_session.execute(audit_query)).scalars().all()
    assert len(logs) == 1
    assert logs[0].valor_anterior == str(cuenta_a.id)
    assert logs[0].valor_nuevo == str(cuenta_b.id)

    # Repeating the call on the already-default account is idempotent.
    resp2 = await client.put(f"/api/v1/receptores/{receptor.id}/cuentas/{cuenta_b.id}/predeterminada")
    assert resp2.status_code == 200
    await db_session.refresh(cuenta_a)
    await db_session.refresh(cuenta_b)
    assert cuenta_a.es_predeterminada is False
    assert cuenta_b.es_predeterminada is True
    logs2 = (await db_session.execute(audit_query)).scalars().all()
    assert len(logs2) == 1


@pytest.mark.asyncio
async def test_cuenta_de_otro_receptor_rechazada(client_factory, db_session):
    receptor1 = _mk_receptor()
    receptor2 = _mk_receptor()
    cuenta_r2 = _mk_cuenta(receptor2.id, etiqueta="C", predeterminada=True)
    db_session.add_all([receptor1, receptor2, cuenta_r2])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(f"/api/v1/receptores/{receptor1.id}/cuentas/{cuenta_r2.id}/predeterminada")

    assert resp.status_code == 404
    await db_session.refresh(cuenta_r2)
    assert cuenta_r2.es_predeterminada is True


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor, TipoUsuario.recaudador])
async def test_no_admin_no_puede_cambiar_predeterminada(client_factory, db_session, rol):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    client = await client_factory(_mk_user(rol))
    resp = await client.put(f"/api/v1/receptores/{receptor.id}/cuentas/{cuenta_b.id}/predeterminada")

    assert resp.status_code == 403
    await db_session.refresh(cuenta_a)
    await db_session.refresh(cuenta_b)
    assert cuenta_a.es_predeterminada is True
    assert cuenta_b.es_predeterminada is False


@pytest.mark.asyncio
async def test_insertar_segunda_predeterminada_viola_indice_unico(db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta_a])
    await db_session.flush()

    db_session.add(_mk_cuenta(receptor.id, etiqueta="B", predeterminada=True))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_receptor_response_expone_es_predeterminada(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.get(f"/api/v1/receptores/{receptor.id}")

    assert resp.status_code == 200
    cuentas = {c["id"]: c["es_predeterminada"] for c in resp.json()["cuentas_bancarias"]}
    assert cuentas[str(cuenta_a.id)] is True
    assert cuentas[str(cuenta_b.id)] is False


# --- Judgment Day round 1: A-F1/B-F2, A-F2, A-F6, A-F3 ---

@pytest.mark.asyncio
async def test_post_cuenta_con_default_concurrente_devuelve_409(client_factory, db_session, monkeypatch):
    """A-F1: si otra transacción ya dejó una predeterminada, el índice único parcial
    dispara IntegrityError y el endpoint debe responder 409 sin persistir la fila."""
    from app.services import cuenta_bancaria_service

    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    db_session.add_all([receptor, cuenta_a])
    # Commit: el endpoint hace rollback y en prod cada request tiene su propia
    # sesión; sin commit el rollback borraría también estas filas de fixture.
    receptor_id = receptor.id  # el rollback del endpoint expira los objetos ORM
    await db_session.commit()

    async def _forzar_default(db, receptor_id):
        return True

    monkeypatch.setattr(cuenta_bancaria_service, "sin_predeterminada", _forzar_default)

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(
        f"/api/v1/receptores/{receptor_id}/cuentas",
        json={"entidad_bancaria": "Davivienda", "tipo_cuenta": "Corriente", "numero_cuenta": "222"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "El receptor ya tiene una cuenta predeterminada"
    try:
        total = (await db_session.execute(
            select(func.count()).select_from(CuentaBancaria)
            .where(CuentaBancaria.receptor_id == receptor_id)
        )).scalar()
        assert total == 1
    finally:
        # Limpieza de las filas committeadas (la DB en memoria es de sesión).
        await db_session.execute(delete(CuentaBancaria).where(CuentaBancaria.receptor_id == receptor_id))
        await db_session.execute(delete(Receptor).where(Receptor.id == receptor_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_put_predeterminada_integrity_error_devuelve_409(client_factory, db_session, monkeypatch):
    """B-F2: IntegrityError en marcar_predeterminada -> rollback + 409."""
    from app.services import cuenta_bancaria_service

    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    async def _explota(db, receptor_id, cuenta_id):
        raise IntegrityError("", {}, Exception())

    monkeypatch.setattr(cuenta_bancaria_service, "marcar_predeterminada", _explota)

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(f"/api/v1/receptores/{receptor.id}/cuentas/{cuenta_b.id}/predeterminada")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Conflicto al cambiar la cuenta predeterminada, reintente"
    audit_total = (await db_session.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.entidad_id == receptor.id)
    )).scalar()
    assert audit_total == 0


@pytest.mark.asyncio
async def test_receptor_legacy_sin_predeterminada_nueva_cuenta_es_default(client_factory, db_session):
    """A-F2: receptor con cuenta legacy (es_predeterminada=False) -> la nueva cuenta
    pasa a ser predeterminada; la legacy sigue en False."""
    receptor = _mk_receptor()
    legacy = _mk_cuenta(receptor.id, etiqueta="L", predeterminada=False)
    db_session.add_all([receptor, legacy])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(
        f"/api/v1/receptores/{receptor.id}/cuentas",
        json={"entidad_bancaria": "Bancolombia", "tipo_cuenta": "Ahorros", "numero_cuenta": "333"},
    )

    assert resp.status_code == 201
    assert resp.json()["es_predeterminada"] is True
    await db_session.refresh(legacy)
    assert legacy.es_predeterminada is False


@pytest.mark.asyncio
async def test_put_predeterminada_receptor_eliminado_devuelve_404(client_factory, db_session):
    """A-F6: receptor soft-deleted -> 404 y flags intactos."""
    receptor = _mk_receptor()
    receptor.deleted_at = datetime.now(timezone.utc)
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B", predeterminada=False)
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.put(f"/api/v1/receptores/{receptor.id}/cuentas/{cuenta_b.id}/predeterminada")

    assert resp.status_code == 404
    await db_session.refresh(cuenta_a)
    await db_session.refresh(cuenta_b)
    assert cuenta_a.es_predeterminada is True
    assert cuenta_b.es_predeterminada is False
