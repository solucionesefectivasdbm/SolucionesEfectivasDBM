"""
tests/test_admin_backfill.py — Integration tests para el endpoint temporal
`POST /pagos/admin/backfill-fecha-maxima-original` (atraso-pago-aplazado-
corte-original, Fase 4).

RED: el endpoint todavía no existe en routers/pagos.py (404).

TEMPORAL: este endpoint y este archivo de test se eliminan en un commit
posterior una vez ejecutado el backfill en producción (ver design.md
"Migration / Rollout" y la nota de Fase 4 en tasks.md).

Cubre (spec.md "Backfill Requirements"):
- Reconstrucción desde auditoría (primer valor_anterior cronológico).
- Fallback sin fila de auditoría (no escribe cambio real, fecha_maxima_original
  ya migrado en Fase 1 == fecha_maxima).
- Conteo de verificación previo (dry_run=True, default) reporta totales sin
  escribir nada.
- Segunda corrida aplicada es no-op (a_modificar=0) — idempotencia.
- No-admin recibe 403.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AccionAudit, AuditLog
from app.models.cliente import Cliente
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

_FAKE_GESTOR_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_ENDPOINT = "/api/v1/pagos/admin/backfill-fecha-maxima-original"


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
        tipo_credito=TipoCredito.cuota_fija, capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0500"), fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 10), periodicidad=Periodicidad.quincenal,
        saldo_capital=Decimal("1000000.00"), saldo_intereses=Decimal("0.00"),
        abono_minimo=Decimal("100000.00"), numero_cuotas=10, activo=True,
    )


def _mk_pago(
    credito_id: uuid.UUID,
    *,
    fecha_maxima: date = date(2026, 4, 1),
    fecha_maxima_original: date | None = None,
    veces_aplazado: int = 0,
    fecha_pago_real: date | None = None,
    pagado: bool = False,
) -> Pago:
    """`fecha_maxima_original` por defecto == `fecha_maxima`, simulando el
    estado post-migración de Fase 1 (UPDATE ciego) previo al backfill de
    Fase 4."""
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("170000.00"),
        capital_a_pagar=Decimal("100000.00"), interes_a_pagar=Decimal("70000.00"),
        momento="m3", fecha_maxima=fecha_maxima,
        fecha_maxima_original=fecha_maxima_original or fecha_maxima,
        veces_aplazado=veces_aplazado, fecha_pago_real=fecha_pago_real, pagado=pagado,
    )


def _mk_audit_fecha_maxima(
    pago_id: uuid.UUID, usuario_id: uuid.UUID, fecha_accion: datetime, valor_anterior: str,
) -> AuditLog:
    return AuditLog(
        id=uuid.uuid4(), entidad="pagos", entidad_id=pago_id, accion=AccionAudit.UPDATE,
        campo_modificado="fecha_maxima", valor_anterior=valor_anterior, valor_nuevo="2026-04-01",
        usuario_id=usuario_id, fecha_accion=fecha_accion, ip_origen="127.0.0.1",
    )


def _mk_user(rol: TipoUsuario) -> MagicMock:
    user = MagicMock(spec=Usuario)
    user.id = uuid.uuid4()
    user.tipo_usuario = rol
    user.activo = True
    user.deleted_at = None
    return user


@pytest_asyncio.fixture
async def client_factory(db_session):
    """Factory que arma un AsyncClient con get_current_user/get_db overridden
    para un usuario dado (mismo patrón de test_pagos_backfill_arrastre_abono_capital.py)."""
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


class TestBackfillFechaMaximaOriginal:
    @pytest.mark.asyncio
    async def test_reconstruye_desde_auditoria_en_modo_aplicado(self, client_factory, db_session):
        """spec.md: 'Backfill reconstruye desde auditoría'."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        admin = _mk_user(TipoUsuario.admin)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 4, 1), veces_aplazado=1)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        db_session.add_all([
            _mk_audit_fecha_maxima(pago.id, admin.id, datetime(2026, 3, 1, 10, 0), "2026-03-10"),
            _mk_audit_fecha_maxima(pago.id, admin.id, datetime(2026, 3, 20, 9, 0), "2026-03-25"),
        ])
        await db_session.flush()

        client = await client_factory(admin)
        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is False
        assert body["con_auditoria"] == 1
        assert body["a_modificar"] == 1

        await db_session.refresh(pago)
        assert pago.fecha_maxima_original == date(2026, 3, 10)
        # fecha_maxima (vigente, aplazada) permanece intacta
        assert pago.fecha_maxima == date(2026, 4, 1)

        auditorias = (await db_session.execute(
            select(AuditLog).where(
                AuditLog.entidad == "pagos",
                AuditLog.entidad_id == pago.id,
                AuditLog.campo_modificado == "fecha_maxima_original",
            )
        )).scalars().all()
        assert len(auditorias) == 1
        assert auditorias[0].valor_anterior == "2026-04-01"
        assert auditorias[0].valor_nuevo == "2026-03-10"

    @pytest.mark.asyncio
    async def test_dry_run_no_escribe_nada(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        admin = _mk_user(TipoUsuario.admin)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 4, 1))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        db_session.add(_mk_audit_fecha_maxima(pago.id, admin.id, datetime(2026, 3, 1, 10, 0), "2026-03-10"))
        await db_session.flush()

        client = await client_factory(admin)
        r = await client.post(_ENDPOINT, json={"dry_run": True})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert body["a_modificar"] == 1

        await db_session.refresh(pago)
        assert pago.fecha_maxima_original == date(2026, 4, 1)  # sin cambios

        auditorias = (await db_session.execute(
            select(AuditLog).where(AuditLog.campo_modificado == "fecha_maxima_original")
        )).scalars().all()
        assert auditorias == []

    @pytest.mark.asyncio
    async def test_default_es_dry_run(self, client_factory, db_session):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        admin = _mk_user(TipoUsuario.admin)
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(admin)
        r = await client.post(_ENDPOINT, json={})

        assert r.status_code == 200, r.text
        assert r.json()["dry_run"] is True

    @pytest.mark.asyncio
    async def test_pago_sin_auditoria_usa_fallback_y_no_cuenta_como_a_modificar(
        self, client_factory, db_session
    ):
        """spec.md: 'Backfill sin fila de auditoría usa fallback' — la Fase 1
        ya dejó fecha_maxima_original == fecha_maxima, así que el fallback no
        produce ningún cambio real (a_modificar no lo cuenta)."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        admin = _mk_user(TipoUsuario.admin)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 4, 1), veces_aplazado=2)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        client = await client_factory(admin)
        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["a_modificar"] == 0
        assert body["aplazados_sin_auditoria"] == 1

        await db_session.refresh(pago)
        assert pago.fecha_maxima_original == date(2026, 4, 1)

    @pytest.mark.asyncio
    async def test_conteo_previo_reporta_cobertura_de_auditoria(self, client_factory, db_session):
        """spec.md: 'Conteo previo informa cobertura de auditoría' — el
        dry_run (paso de verificación) reporta el total y cuántos pagos van
        a fallback por falta de auditoría, sin aplicar nada."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        admin = _mk_user(TipoUsuario.admin)
        # Un pago nunca aplazado (no cuenta en aplazados_sin_auditoria).
        pago_normal = _mk_pago(credito.id, veces_aplazado=0)
        # Un pago aplazado sin fila de auditoría (cuenta en el fallback).
        pago_sin_auditoria = _mk_pago(credito.id, veces_aplazado=1)
        db_session.add_all([cliente, credito, pago_normal, pago_sin_auditoria])
        await db_session.flush()

        client = await client_factory(admin)
        r = await client.post(_ENDPOINT, json={"dry_run": True})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_pagos"] == 2
        assert body["aplazados_sin_auditoria"] == 1

    @pytest.mark.asyncio
    async def test_segunda_corrida_aplicada_da_a_modificar_cero(self, client_factory, db_session):
        """Idempotencia: el resultado depende solo de audit_log/fecha_maxima,
        nunca de la columna misma."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        admin = _mk_user(TipoUsuario.admin)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 4, 1))
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        db_session.add(_mk_audit_fecha_maxima(pago.id, admin.id, datetime(2026, 3, 1, 10, 0), "2026-03-10"))
        await db_session.flush()

        client = await client_factory(admin)

        primera = await client.post(_ENDPOINT, json={"dry_run": False})
        assert primera.json()["a_modificar"] == 1

        segunda = await client.post(_ENDPOINT, json={"dry_run": False})
        assert segunda.status_code == 200
        assert segunda.json()["a_modificar"] == 0

    @pytest.mark.asyncio
    async def test_evento_previo_a_reanclaje_no_se_usa_sobre_pago_pendiente(
        self, client_factory, db_session
    ):
        """Un pago paid=False cuyo crédito fue re-anclado después del último
        evento de aplazamiento: el fallback aplica (motivo=reanclado), no el
        valor histórico previo al re-anclaje."""
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        admin = _mk_user(TipoUsuario.admin)
        pago = _mk_pago(credito.id, fecha_maxima=date(2026, 4, 1), pagado=False)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()
        db_session.add_all([
            _mk_audit_fecha_maxima(pago.id, admin.id, datetime(2026, 1, 5, 8, 0), "2026-01-01"),
            AuditLog(
                id=uuid.uuid4(), entidad="creditos", entidad_id=credito.id,
                accion=AccionAudit.UPDATE, campo_modificado="anchor_fechas",
                valor_anterior="d1=10,d2=25", valor_nuevo="d1=15,d2=28",
                usuario_id=admin.id, fecha_accion=datetime(2026, 2, 1, 0, 0),
                ip_origen="127.0.0.1",
            ),
        ])
        await db_session.flush()

        client = await client_factory(admin)
        r = await client.post(_ENDPOINT, json={"dry_run": False})

        assert r.status_code == 200, r.text
        assert r.json()["reanclados"] == 1
        assert r.json()["a_modificar"] == 0  # fallback == fecha_maxima_original ya migrado

        await db_session.refresh(pago)
        assert pago.fecha_maxima_original == date(2026, 4, 1)

    @pytest.mark.parametrize("rol", [TipoUsuario.registrador, TipoUsuario.recaudador, TipoUsuario.gestor])
    @pytest.mark.asyncio
    async def test_no_admin_403(self, client_factory, db_session, rol):
        cliente = _mk_cliente()
        credito = _mk_credito(cliente.id)
        pago = _mk_pago(credito.id)
        db_session.add_all([cliente, credito, pago])
        await db_session.flush()

        user = _mk_user(rol)
        client = await client_factory(user)

        r = await client.post(_ENDPOINT, json={"dry_run": True})

        assert r.status_code == 403
        await db_session.refresh(pago)
        assert pago.fecha_maxima_original == pago.fecha_maxima
