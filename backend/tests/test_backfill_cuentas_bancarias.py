"""
tests/test_backfill_cuentas_bancarias.py — Backfill SQL-only idempotente
(receiver-bank-account-assignment, PR1b).

Covers: receptor sin cuentas -> cuenta genérica predeterminada; receptor con
cuentas pero sin default -> elección por MIN(id); gestores/pagos con
cuenta_bancaria_id NULL se llenan desde el default de su receptor_id (solo
huecos, nunca sobrescribe); pagos no pagados que siguen sin cuenta heredan de
credito -> cliente -> gestor; pagos pagados/soft-deleted también se llenan;
dry_run no escribe; segunda corrida es idempotente (todo en cero); no-admin
-> 403 sin escrituras. Negativos: filas cuyo default no se puede resolver
(gestor sin receptor, receptor soft-deleted sin cuentas, gestor sin cuenta en
la cadena credito -> cliente -> gestor, o cadena con filas soft-deleted) no se
cuentan ni se escriben y solo aparecen en `pendientes`; el paso 1 no usa
MIN(uuid) (PostgreSQL no lo soporta). Fixtures de usuario copiadas de
test_cuentas_bancarias_predeterminada.py.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.cliente import Cliente
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.gestor import Gestor
from app.models.pago import Pago, TipoCuota
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.usuario import TipoUsuario, Usuario
from app.routers.receptores import _cuentas_sin_default_elegidas

ENDPOINT = "/api/v1/receptores/admin/backfill-cuentas-bancarias"


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


def _mk_receptor(**kwargs) -> Receptor:
    return Receptor(
        id=uuid.uuid4(), nombre=f"Receptor {uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        **kwargs,
    )


def _mk_cuenta(receptor_id: uuid.UUID, *, etiqueta="A", predeterminada=False) -> CuentaBancaria:
    return CuentaBancaria(
        id=uuid.uuid4(), receptor_id=receptor_id, entidad_bancaria=etiqueta,
        tipo_cuenta=TipoCuenta.ahorros, numero_cuenta=f"{etiqueta}1",
        es_predeterminada=predeterminada,
    )


def _mk_gestor(*, receptor_id=None, cuenta_bancaria_id=None) -> Gestor:
    return Gestor(
        id=uuid.uuid4(), user_id=uuid.uuid4(), cedula=str(uuid.uuid4().int)[:10],
        nombre="Gestor", apellidos="Prueba", telefono="3000000000",
        direccion="Calle 1", correo_electronico=f"{uuid.uuid4().hex[:8]}@test.com",
        receptor_id=receptor_id, cuenta_bancaria_id=cuenta_bancaria_id,
    )


def _mk_cliente(gestor_id: uuid.UUID) -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=gestor_id, nombre="Cliente", apellidos="Prueba",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000", direccion="Calle 2",
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"CR-{uuid.uuid4().hex[:8]}",
        tipo_credito=TipoCredito.abono_capital,
        capital_prestado=Decimal("1000000.00"), tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("1000000.00"),
    )


def _mk_pago(
    credito_id: uuid.UUID, *, receptor_id=None, cuenta_bancaria_id=None,
    pagado=False, deleted_at=None,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.abono, monto_a_pagar=Decimal("30000.00"),
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=pagado,
        receptor_id=receptor_id, cuenta_bancaria_id=cuenta_bancaria_id,
        deleted_at=deleted_at,
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
async def test_receptor_sin_cuentas_obtiene_generica_predeterminada(client_factory, db_session):
    receptor = _mk_receptor()
    db_session.add(receptor)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is False
    assert body["cuentas_genericas_creadas"] == 1

    cuentas = (await db_session.execute(
        select(CuentaBancaria).where(CuentaBancaria.receptor_id == receptor.id)
    )).scalars().all()
    assert len(cuentas) == 1
    generica = cuentas[0]
    assert generica.entidad_bancaria == "Por definir"
    assert generica.tipo_cuenta == TipoCuenta.ahorros
    assert generica.numero_cuenta == "0"
    assert generica.es_predeterminada is True


@pytest.mark.asyncio
async def test_receptor_con_cuentas_sin_default_elige_min_id(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A")
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B")
    if cuenta_b.id < cuenta_a.id:
        cuenta_a, cuenta_b = cuenta_b, cuenta_a
    db_session.add_all([receptor, cuenta_a, cuenta_b])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    assert resp.json()["predeterminadas_elegidas"] == 1
    await db_session.refresh(cuenta_a)
    await db_session.refresh(cuenta_b)
    assert cuenta_a.es_predeterminada is True
    assert cuenta_b.es_predeterminada is False


@pytest.mark.asyncio
async def test_llena_gestor_y_pago_desde_receptor_id(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    gestor = _mk_gestor(receptor_id=receptor.id)
    db_session.add_all([receptor, cuenta_a, gestor])
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, receptor_id=receptor.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["gestores_actualizados"] == 1
    assert body["pagos_por_receptor"] == 1
    await db_session.refresh(gestor)
    await db_session.refresh(pago)
    assert gestor.cuenta_bancaria_id == cuenta_a.id
    assert pago.cuenta_bancaria_id == cuenta_a.id


@pytest.mark.asyncio
async def test_llena_solo_huecos_no_sobrescribe(client_factory, db_session):
    """A-6.5: gestor ya en B; pago sin cuenta cuyo receptor_id apunta a A."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B")
    gestor = _mk_gestor(receptor_id=receptor.id, cuenta_bancaria_id=cuenta_b.id)
    db_session.add_all([receptor, cuenta_a, cuenta_b, gestor])
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, receptor_id=receptor.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    assert resp.json()["gestores_actualizados"] == 0
    await db_session.refresh(gestor)
    await db_session.refresh(pago)
    assert gestor.cuenta_bancaria_id == cuenta_b.id
    assert pago.cuenta_bancaria_id == cuenta_a.id


@pytest.mark.asyncio
async def test_pago_no_pagado_sin_receptor_hereda_de_gestor(client_factory, db_session):
    """A-6.6: pago sigue NULL tras el paso 4a (su propio receptor_id era NULL);
    hereda vía credito -> cliente -> gestor.cuenta_bancaria_id (paso 4b)."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    gestor = _mk_gestor(receptor_id=receptor.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add_all([receptor, cuenta_a, gestor])
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, receptor_id=None, pagado=False)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    assert resp.json()["pagos_por_gestor"] == 1
    await db_session.refresh(pago)
    assert pago.cuenta_bancaria_id == cuenta_a.id


@pytest.mark.asyncio
async def test_pagos_pagados_y_borrados_se_llenan_igual(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    gestor = _mk_gestor(receptor_id=receptor.id)
    db_session.add_all([receptor, cuenta_a, gestor])
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago_pagado = _mk_pago(credito.id, receptor_id=receptor.id, pagado=True)
    pago_borrado = _mk_pago(
        credito.id, receptor_id=receptor.id, deleted_at=datetime.now(timezone.utc)
    )
    db_session.add_all([pago_pagado, pago_borrado])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    assert resp.json()["pagos_por_receptor"] == 2
    await db_session.refresh(pago_pagado)
    await db_session.refresh(pago_borrado)
    assert pago_pagado.cuenta_bancaria_id == cuenta_a.id
    assert pago_borrado.cuenta_bancaria_id == cuenta_a.id


@pytest.mark.asyncio
async def test_dry_run_no_escribe_pero_cuenta_igual(client_factory, db_session):
    receptor = _mk_receptor()
    db_session.add(receptor)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp_dry = await client.post(ENDPOINT)  # dry_run=true por default

    assert resp_dry.status_code == 200
    body_dry = resp_dry.json()
    assert body_dry["dry_run"] is True
    assert body_dry["cuentas_genericas_creadas"] == 1

    cuentas = (await db_session.execute(
        select(CuentaBancaria).where(CuentaBancaria.receptor_id == receptor.id)
    )).scalars().all()
    assert cuentas == []

    resp_apply = await client.post(ENDPOINT, params={"dry_run": "false"})
    assert resp_apply.json()["cuentas_genericas_creadas"] == body_dry["cuentas_genericas_creadas"]


@pytest.mark.asyncio
async def test_segunda_corrida_es_idempotente(client_factory, db_session):
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A")
    cuenta_b = _mk_cuenta(receptor.id, etiqueta="B")
    gestor = _mk_gestor(receptor_id=receptor.id)
    db_session.add_all([receptor, cuenta_a, cuenta_b, gestor])
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, receptor_id=receptor.id)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    first = await client.post(ENDPOINT, params={"dry_run": "false"})
    assert first.status_code == 200
    assert first.json()["predeterminadas_elegidas"] == 1

    second = await client.post(ENDPOINT, params={"dry_run": "false"})
    assert second.status_code == 200
    body2 = second.json()
    assert body2["predeterminadas_elegidas"] == 0
    assert body2["cuentas_genericas_creadas"] == 0
    assert body2["gestores_actualizados"] == 0
    assert body2["pagos_por_receptor"] == 0
    assert body2["pagos_por_gestor"] == 0
    assert body2["pendientes"]["gestores_sin_cuenta"] == 0
    assert body2["pendientes"]["pagos_sin_cuenta_rellenables"] == 0
    assert body2["pendientes"]["pagos_sin_cuenta_no_rellenables"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.gestor, TipoUsuario.recaudador])
async def test_no_admin_no_puede_ejecutar_backfill(client_factory, db_session, rol):
    receptor = _mk_receptor()
    db_session.add(receptor)
    await db_session.flush()

    client = await client_factory(_mk_user(rol))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 403
    cuentas = (await db_session.execute(
        select(CuentaBancaria).where(CuentaBancaria.receptor_id == receptor.id)
    )).scalars().all()
    assert cuentas == []


def test_paso1_no_usa_min_sobre_uuid_en_postgresql():
    """CRITICAL-2: PostgreSQL has no min()/max() aggregate for uuid. The
    step-1 selection must rank rows with row_number() OVER (PARTITION BY
    receptor_id ORDER BY id) instead of min(cuentas_bancarias.id)."""
    sql = str(_cuentas_sin_default_elegidas().compile(dialect=postgresql.dialect()))
    normalized = " ".join(sql.split()).lower()
    assert "min(cuentas_bancarias.id)" not in normalized
    assert "row_number() over (partition by" in normalized
    assert "order by" in normalized


@pytest.mark.asyncio
async def test_gestor_sin_receptor_y_pago_sin_cuenta_resoluble_quedan_pendientes(
    client_factory, db_session,
):
    """CRITICAL-1 (a)/(c): gestor without receptor and without account; its
    unpaid pago has no receptor either. Neither step 3 nor 4b can resolve a
    default: nothing is counted, nothing is written, both rows appear in
    pendientes, and a second run still reports 0 on every step counter."""
    gestor = _mk_gestor(receptor_id=None, cuenta_bancaria_id=None)
    db_session.add(gestor)
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, receptor_id=None, pagado=False)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    first = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert first.status_code == 200
    body = first.json()
    assert body["gestores_actualizados"] == 0
    assert body["pagos_por_receptor"] == 0
    assert body["pagos_por_gestor"] == 0
    assert body["pendientes"]["gestores_sin_cuenta"] == 1
    assert body["pendientes"]["pagos_sin_cuenta_rellenables"] == 1
    assert body["pendientes"]["pagos_sin_cuenta_no_rellenables"] == 0
    await db_session.refresh(gestor)
    await db_session.refresh(pago)
    assert gestor.cuenta_bancaria_id is None
    assert pago.cuenta_bancaria_id is None

    second = await client.post(ENDPOINT, params={"dry_run": "false"})
    body2 = second.json()
    assert body2["gestores_actualizados"] == 0
    assert body2["pagos_por_receptor"] == 0
    assert body2["pagos_por_gestor"] == 0
    assert body2["pendientes"] == body["pendientes"]


@pytest.mark.asyncio
async def test_receptor_borrado_sin_cuentas_no_se_cuenta_ni_escribe(client_factory, db_session):
    """CRITICAL-1 (b)/(d): soft-deleted receptor with no accounts is skipped by
    step 2, so steps 3/4a resolve NULL for the gestor/pago pointing at it.
    They must not be counted or updated (NULL -> NULL) and must stay in
    pendientes; the second run keeps all step counters at 0."""
    receptor = _mk_receptor(deleted_at=datetime.now(timezone.utc))
    gestor = _mk_gestor(receptor_id=receptor.id)
    db_session.add_all([receptor, gestor])
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, receptor_id=receptor.id, pagado=True)
    db_session.add(pago)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    first = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert first.status_code == 200
    body = first.json()
    assert body["cuentas_genericas_creadas"] == 0
    assert body["gestores_actualizados"] == 0
    assert body["pagos_por_receptor"] == 0
    assert body["pagos_por_gestor"] == 0
    assert body["pendientes"]["gestores_sin_cuenta"] == 1
    assert body["pendientes"]["pagos_sin_cuenta_rellenables"] == 1
    assert body["pendientes"]["pagos_sin_cuenta_no_rellenables"] == 0
    await db_session.refresh(gestor)
    await db_session.refresh(pago)
    assert gestor.cuenta_bancaria_id is None
    assert pago.cuenta_bancaria_id is None

    second = await client.post(ENDPOINT, params={"dry_run": "false"})
    body2 = second.json()
    assert body2["predeterminadas_elegidas"] == 0
    assert body2["cuentas_genericas_creadas"] == 0
    assert body2["gestores_actualizados"] == 0
    assert body2["pagos_por_receptor"] == 0
    assert body2["pagos_por_gestor"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("entidad_borrada", ["credito", "cliente", "gestor"])
async def test_paso_4b_ignora_cadena_con_filas_soft_deleted(
    client_factory, db_session, entidad_borrada,
):
    """WARNING-1: the credito -> cliente -> gestor join in step 4b must filter
    deleted_at IS NULL on each hop; a soft-deleted link yields no account."""
    receptor = _mk_receptor()
    cuenta_a = _mk_cuenta(receptor.id, etiqueta="A", predeterminada=True)
    gestor = _mk_gestor(receptor_id=receptor.id, cuenta_bancaria_id=cuenta_a.id)
    db_session.add_all([receptor, cuenta_a, gestor])
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, receptor_id=None, pagado=False)
    db_session.add(pago)
    await db_session.flush()
    borrada = {"credito": credito, "cliente": cliente, "gestor": gestor}[entidad_borrada]
    borrada.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    assert resp.json()["pagos_por_gestor"] == 0
    await db_session.refresh(pago)
    assert pago.cuenta_bancaria_id is None


@pytest.mark.asyncio
async def test_pendientes_separa_pagos_no_rellenables(client_factory, db_session):
    """WARNING-2: paid or soft-deleted pagos without receptor_id are filled
    by no step; they must be reported apart from the still-unresolved
    in-scope pagos so a non-zero pending count is not mistaken for a bug."""
    gestor = _mk_gestor(receptor_id=None)
    db_session.add(gestor)
    await db_session.flush()
    cliente = _mk_cliente(gestor.id)
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago_pagado = _mk_pago(credito.id, receptor_id=None, pagado=True)
    pago_borrado = _mk_pago(credito.id, receptor_id=None, deleted_at=datetime.now(timezone.utc))
    db_session.add_all([pago_pagado, pago_borrado])
    await db_session.flush()

    client = await client_factory(_mk_user(TipoUsuario.admin))
    resp = await client.post(ENDPOINT, params={"dry_run": "false"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["pagos_por_receptor"] == 0
    assert body["pagos_por_gestor"] == 0
    assert body["pendientes"]["pagos_sin_cuenta_rellenables"] == 0
    assert body["pendientes"]["pagos_sin_cuenta_no_rellenables"] == 2
