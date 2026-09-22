"""
tests/test_receptores_movimientos_router.py — POST /receptores/{id}/cuentas/{cuenta_id}/salidas
y .../correcciones (item 9, receiver-cash-balance, PR 2 — write endpoints).

Covers: 201 dentro de saldo, 409 sobregiro (exactamente +1 sobre el saldo),
201 exactamente-igual al saldo (design.md especifica 201 para ambas rutas
— POST que crea un recurso —, no 200; tasks.md usa "200" como taquigrafía
informal de "éxito", no como código HTTP literal, ver Deviations en
apply-progress), 403 para roles sin permiso, 404 cuenta de otro receptor /
cuenta inexistente, corrección negativa y positiva aceptadas, corrección
de monto cero rechazada (422 vía validador Pydantic — CorreccionCreate),
ausencia de chequeo de sobregiro en corrección (decision 4 del design), y
fila de audit_log escrita por cada escritura exitosa.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import func, select

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AccionAudit, AuditLog
from app.models.cliente import Cliente
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.receptor_movimiento import MovimientoReceptor
from app.models.usuario import TipoUsuario, Usuario

RECEPTORES_URL = "/api/v1/receptores"


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    user.username = f"actor{uuid.uuid4().hex[:6]}"
    return user


def _mk_receptor(**kwargs) -> Receptor:
    defaults = dict(
        id=uuid.uuid4(), nombre=f"Receptor {uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
    )
    defaults.update(kwargs)
    return Receptor(**defaults)


def _mk_cuenta(receptor_id: uuid.UUID, **kwargs) -> CuentaBancaria:
    defaults = dict(
        id=uuid.uuid4(), receptor_id=receptor_id, entidad_bancaria="Banco",
        tipo_cuenta=TipoCuenta.ahorros, numero_cuenta=uuid.uuid4().hex[:6],
        es_predeterminada=False,
    )
    defaults.update(kwargs)
    return CuentaBancaria(**defaults)


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Movimientos", apellidos=f"Test{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Mov-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )


async def _preparar_cuenta_con_saldo(db_session, monto: Decimal) -> tuple[Receptor, CuentaBancaria]:
    """Crea receptor + cuenta + un Pago pagado (todo capital, cero interés,
    por simplicidad) que deja exactamente `monto` de saldo inicial."""
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id)
    db_session.add_all([receptor, cuenta])
    await db_session.flush()
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    db_session.add(Pago(
        id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=monto,
        capital_a_pagar=monto, interes_a_pagar=Decimal("0.00"),
        capital_pagado=monto, interes_pagado=Decimal("0.00"),
        momento="m3", fecha_maxima=date(2026, 2, 10),
        pagado=True, validado_recaudador=True, es_ultimo_pago=False,
        cuenta_bancaria_id=cuenta.id,
    ))
    await db_session.flush()
    return receptor, cuenta


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


# ─── POST .../salidas ───────────────────────────────────────────────────────

class TestRegistrarSalida:
    @pytest.mark.asyncio
    async def test_salida_dentro_de_saldo_devuelve_201(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("500000.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/salidas",
            json={"monto": "300000.00", "nota": "retiro parcial"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["tipo"] == "salida"
        assert Decimal(str(body["monto"])) == Decimal("300000.00")
        assert body["nota"] == "retiro parcial"
        assert body["usuario_id"] == str(admin.id)
        assert body["usuario_nombre"] == admin.username
        assert body["cuenta_bancaria_id"] == str(cuenta.id)

    @pytest.mark.asyncio
    async def test_salida_excede_saldo_devuelve_409_y_no_persiste(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("500000.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/salidas",
            json={"monto": "500001.00"},
        )

        assert resp.status_code == 409
        total = (await db_session.execute(
            select(func.count()).select_from(MovimientoReceptor)
            .where(MovimientoReceptor.cuenta_bancaria_id == cuenta.id)
        )).scalar()
        assert total == 0

    @pytest.mark.asyncio
    async def test_salida_exactamente_igual_al_saldo_devuelve_201(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("500000.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/salidas",
            json={"monto": "500000.00"},
        )

        assert resp.status_code == 201
        saldo_resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/saldo")
        assert Decimal(str(saldo_resp.json()["saldo_total"])) == Decimal("0.00")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rol", [TipoUsuario.recaudador, TipoUsuario.registrador, TipoUsuario.gestor])
    async def test_salida_rechazada_para_roles_sin_permiso(self, client_factory, db_session, rol):
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("100.00"))

        client = await client_factory(_mk_user(rol))
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/salidas",
            json={"monto": "10.00"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_salida_cuenta_de_otro_receptor_devuelve_404(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        _, cuenta_propia = await _preparar_cuenta_con_saldo(db_session, Decimal("100.00"))
        otro_receptor = _mk_receptor()
        db_session.add(otro_receptor)
        await db_session.flush()

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{otro_receptor.id}/cuentas/{cuenta_propia.id}/salidas",
            json={"monto": "10.00"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Cuenta no encontrada"

    @pytest.mark.asyncio
    async def test_salida_cuenta_inexistente_devuelve_404(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor = _mk_receptor()
        db_session.add(receptor)
        await db_session.flush()

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{uuid.uuid4()}/salidas",
            json={"monto": "10.00"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Cuenta no encontrada"

    @pytest.mark.asyncio
    async def test_salida_escribe_audit_log(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("500000.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/salidas",
            json={"monto": "100000.00"},
        )
        movimiento_id = uuid.UUID(resp.json()["id"])

        log = (await db_session.execute(
            select(AuditLog).where(
                AuditLog.entidad == "receptor_movimientos",
                AuditLog.entidad_id == movimiento_id,
            )
        )).scalar_one_or_none()
        assert log is not None
        assert log.accion == AccionAudit.CREATE
        assert log.usuario_id == admin.id


# ─── POST .../correcciones ──────────────────────────────────────────────────

class TestRegistrarCorreccion:
    @pytest.mark.asyncio
    async def test_correccion_negativa_devuelve_201_y_resta_saldo(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("100000.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/correcciones",
            json={"monto": "-15000.00", "nota": "ajuste conteo físico"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert Decimal(str(body["monto"])) == Decimal("-15000.00")
        assert body["nota"] == "ajuste conteo físico"
        saldo_resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/saldo")
        assert Decimal(str(saldo_resp.json()["saldo_total"])) == Decimal("85000.00")

    @pytest.mark.asyncio
    async def test_correccion_positiva_devuelve_201_y_suma_saldo(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("100000.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/correcciones",
            json={"monto": "20000.00"},
        )

        assert resp.status_code == 201
        saldo_resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/saldo")
        assert Decimal(str(saldo_resp.json()["saldo_total"])) == Decimal("120000.00")

    @pytest.mark.asyncio
    async def test_correccion_monto_cero_devuelve_422(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("100.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/correcciones",
            json={"monto": "0"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rol", [TipoUsuario.recaudador, TipoUsuario.registrador, TipoUsuario.gestor])
    async def test_correccion_rechazada_para_roles_sin_permiso(self, client_factory, db_session, rol):
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("100.00"))

        client = await client_factory(_mk_user(rol))
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/correcciones",
            json={"monto": "10.00"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_correccion_no_tiene_chequeo_de_sobregiro(self, client_factory, db_session):
        """Decision 4 del design: a diferencia de salida, correccion puede
        dejar el saldo en negativo sin ser rechazada."""
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("100.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/correcciones",
            json={"monto": "-500.00"},
        )
        assert resp.status_code == 201
        saldo_resp = await client.get(f"{RECEPTORES_URL}/{receptor.id}/saldo")
        assert Decimal(str(saldo_resp.json()["saldo_total"])) == Decimal("-400.00")

    @pytest.mark.asyncio
    async def test_correccion_escribe_audit_log(self, client_factory, db_session):
        admin = _mk_user(TipoUsuario.admin)
        receptor, cuenta = await _preparar_cuenta_con_saldo(db_session, Decimal("100.00"))

        client = await client_factory(admin)
        resp = await client.post(
            f"{RECEPTORES_URL}/{receptor.id}/cuentas/{cuenta.id}/correcciones",
            json={"monto": "-10.00"},
        )
        movimiento_id = uuid.UUID(resp.json()["id"])

        log = (await db_session.execute(
            select(AuditLog).where(
                AuditLog.entidad == "receptor_movimientos",
                AuditLog.entidad_id == movimiento_id,
            )
        )).scalar_one_or_none()
        assert log is not None
        assert log.accion == AccionAudit.CREATE
        assert log.usuario_id == admin.id
