"""
tests/test_backfill_domingos_diario.py — daily-payments-skip-sunday Phase 5.

POST /creditos/admin/backfill-domingos-diario: corrección histórica única
(one-off, admin-only, idempotente) para cuotas PENDIENTES de créditos
`diario` cuya fecha_maxima quedó en domingo antes del fix de
daily-payments-skip-sunday. Cuotas pagadas y créditos no-diario nunca se
tocan (regla de negocio 3).

TEMPORAL — este endpoint y este archivo se eliminan en un PR de seguimiento
una vez que la corrida en producción confirme cero filas pendientes en
domingo (ver Phase 7 de tasks.md).

Todos los escenarios se ejercitan vía HTTP real (httpx AsyncClient) contra
la app real y una sesión aiosqlite real — sin mockear la lógica de negocio.
"""
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
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

BACKFILL_URL = "/api/v1/creditos/admin/backfill-domingos-diario"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(),
        gestor_id=uuid.uuid4(),
        nombre="Backfill",
        apellidos=f"Domingo{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000",
        direccion="Calle test",
    )


def _mk_credito(
    cliente_id: uuid.UUID,
    *,
    periodicidad: Periodicidad = Periodicidad.diario,
    fecha_inicial_pago: date,
    numero_cuotas: int = 5,
    activo: bool = True,
) -> Credito:
    return Credito(
        id=uuid.uuid4(),
        cliente_id=cliente_id,
        numero_credito_cliente=f"Backfill-{uuid.uuid4().hex[:10]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("500000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=fecha_inicial_pago,
        periodicidad=periodicidad,
        saldo_capital=Decimal("500000.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=numero_cuotas,
        activo=activo,
    )


def _mk_cuota(credito_id: uuid.UUID, numero: int, fecha_maxima: date, pagado: bool) -> Pago:
    return Pago(
        id=uuid.uuid4(),
        credito_id=credito_id,
        numero_cuota=numero,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=Decimal("100000.00"),
        capital_a_pagar=Decimal("70000.00"),
        interes_a_pagar=Decimal("30000.00"),
        capital_pagado=Decimal("70000.00") if pagado else Decimal("0.00"),
        interes_pagado=Decimal("30000.00") if pagado else Decimal("0.00"),
        momento="m1",
        fecha_maxima=fecha_maxima,
        pagado=pagado,
        validado_recaudador=pagado,
        es_ultimo_pago=False,
    )


@pytest_asyncio.fixture
async def make_client(db_session):
    """Factory de AsyncClient con el usuario/rol y la sesión de DB inyectados."""
    created: list[AsyncClient] = []

    async def _make(tipo: TipoUsuario) -> AsyncClient:
        user = MagicMock(spec=Usuario)
        user.id = uuid.uuid4()
        user.tipo_usuario = tipo
        user.activo = True
        user.deleted_at = None

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


class TestBackfillDomingosDiario:
    @pytest.mark.asyncio
    async def test_cascada_domingo_lunes_martes_a_lunes_martes_miercoles(
        self, make_client, db_session
    ):
        """Scenario: pending Sun,Mon,Tue -> Mon,Tue,Wed, reported.

        fecha_inicial_pago 2026-02-01 (domingo, legado pre-fix). Sin cuotas
        pagadas. Las 3 cuotas pendientes quedaron generadas con el bug viejo
        (domingo, lunes, martes) — el backfill debe re-caminar desde
        fecha_inicial_pago+1 (lunes) y producir lunes/martes/miércoles.
        """
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        credito = _mk_credito(
            cliente.id, fecha_inicial_pago=date(2026, 2, 1), numero_cuotas=3
        )
        db_session.add(credito)
        await db_session.flush()

        p1 = _mk_cuota(credito.id, 1, date(2026, 2, 1), pagado=False)  # domingo (bug)
        p2 = _mk_cuota(credito.id, 2, date(2026, 2, 2), pagado=False)  # lunes (bug)
        p3 = _mk_cuota(credito.id, 3, date(2026, 2, 3), pagado=False)  # martes (bug)
        db_session.add_all([p1, p2, p3])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(BACKFILL_URL)
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["creditos_corregidos"] == 1
        assert body["cuotas_corregidas"] == 3
        assert str(credito.id) in body["ids"]

        assert p1.fecha_maxima == date(2026, 2, 2)  # lunes
        assert p2.fecha_maxima == date(2026, 2, 3)  # martes
        assert p3.fecha_maxima == date(2026, 2, 4)  # miércoles

    @pytest.mark.asyncio
    async def test_solo_cuota_1_pendiente_en_domingo_se_mueve_a_lunes(
        self, make_client, db_session
    ):
        """Scenario: only pending row is cuota 1 on Sunday -> moves to Monday."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        credito = _mk_credito(
            cliente.id, fecha_inicial_pago=date(2026, 3, 1), numero_cuotas=1
        )
        db_session.add(credito)
        await db_session.flush()

        p1 = _mk_cuota(credito.id, 1, date(2026, 3, 1), pagado=False)  # domingo
        db_session.add(p1)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(BACKFILL_URL)
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["creditos_corregidos"] == 1
        assert body["cuotas_corregidas"] == 1

        assert p1.fecha_maxima == date(2026, 3, 2)  # lunes

    @pytest.mark.asyncio
    async def test_cuota_pagada_domingo_y_semanal_pendiente_domingo_no_se_tocan(
        self, make_client, db_session
    ):
        """Scenario: paid daily Sunday row + pending semanal Sunday row -> unchanged."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        # Crédito diario con cuota #1 YA PAGADA en domingo (histórica, se conserva).
        cr_diario = _mk_credito(
            cliente.id, fecha_inicial_pago=date(2026, 4, 5), numero_cuotas=1
        )
        db_session.add(cr_diario)
        await db_session.flush()
        p_pagada = _mk_cuota(cr_diario.id, 1, date(2026, 4, 5), pagado=True)  # domingo, pagada
        db_session.add(p_pagada)

        # Crédito semanal con cuota pendiente en domingo — la regla no aplica.
        cr_semanal = _mk_credito(
            cliente.id,
            periodicidad=Periodicidad.semanal,
            fecha_inicial_pago=date(2026, 4, 12),
            numero_cuotas=1,
        )
        db_session.add(cr_semanal)
        await db_session.flush()
        p_semanal = _mk_cuota(cr_semanal.id, 1, date(2026, 4, 12), pagado=False)  # domingo
        db_session.add(p_semanal)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(BACKFILL_URL)
        assert r.status_code == 200, r.text
        body = r.json()

        assert str(cr_diario.id) not in body["ids"]
        assert str(cr_semanal.id) not in body["ids"]

        assert p_pagada.fecha_maxima == date(2026, 4, 5)
        assert p_semanal.fecha_maxima == date(2026, 4, 12)

    @pytest.mark.asyncio
    async def test_segunda_corrida_es_idempotente(self, make_client, db_session):
        """Scenario: second run -> zero changes."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        credito = _mk_credito(
            cliente.id, fecha_inicial_pago=date(2026, 5, 3), numero_cuotas=2
        )
        db_session.add(credito)
        await db_session.flush()

        p1 = _mk_cuota(credito.id, 1, date(2026, 5, 3), pagado=False)  # domingo
        p2 = _mk_cuota(credito.id, 2, date(2026, 5, 4), pagado=False)  # lunes
        db_session.add_all([p1, p2])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r1 = await client.post(BACKFILL_URL)
        assert r1.status_code == 200, r1.text
        assert r1.json()["cuotas_corregidas"] > 0

        r2 = await client.post(BACKFILL_URL)
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["creditos_corregidos"] == 0
        assert body2["cuotas_corregidas"] == 0
        assert body2["ids"] == []

    @pytest.mark.asyncio
    async def test_gestor_403(self, make_client, db_session):
        client = await make_client(TipoUsuario.gestor)
        r = await client.post(BACKFILL_URL)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_registra_auditoria_por_credito_corregido(self, make_client, db_session):
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        credito = _mk_credito(
            cliente.id, fecha_inicial_pago=date(2026, 6, 7), numero_cuotas=1
        )
        db_session.add(credito)
        await db_session.flush()

        p1 = _mk_cuota(credito.id, 1, date(2026, 6, 7), pagado=False)  # domingo
        db_session.add(p1)
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(BACKFILL_URL)
        assert r.status_code == 200, r.text

        logs = (await db_session.execute(
            select(AuditLog).where(AuditLog.entidad_id == credito.id)
        )).scalars().all()
        assert len(logs) == 1

    @pytest.mark.asyncio
    async def test_abono_no_programado_no_ancla_la_cadena(self, make_client, db_session):
        """Scenario: paid `no_programada` row dated after the last scheduled paid
        row must NOT anchor `desde_fecha`. Chain restarts from cuota #1 paid
        (sábado 02-07) -> lunes 02-09, martes 02-10 (domingo 02-08 saltado)."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        credito = _mk_credito(
            cliente.id, fecha_inicial_pago=date(2026, 2, 7), numero_cuotas=3
        )
        db_session.add(credito)
        await db_session.flush()

        p1 = _mk_cuota(credito.id, 1, date(2026, 2, 7), pagado=True)   # sábado, pagada
        p2 = _mk_cuota(credito.id, 2, date(2026, 2, 8), pagado=False)  # domingo (bug)
        p3 = _mk_cuota(credito.id, 3, date(2026, 2, 9), pagado=False)  # lunes (bug)
        extra = _mk_cuota(credito.id, 4, date(2026, 2, 20), pagado=True)  # abono extra
        extra.tipo_cuota = TipoCuota.no_programada
        db_session.add_all([p1, p2, p3, extra])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(BACKFILL_URL)
        assert r.status_code == 200, r.text

        assert p2.fecha_maxima == date(2026, 2, 9)   # lunes
        assert p3.fecha_maxima == date(2026, 2, 10)  # martes
        assert extra.fecha_maxima == date(2026, 2, 20)

    @pytest.mark.asyncio
    async def test_diario_sin_pendiente_en_domingo_no_es_candidato(
        self, make_client, db_session
    ):
        """Scenario: active diario credit whose pending rows have no Sunday is
        not selected: untouched, not in ids, not counted in revisados."""
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        credito = _mk_credito(
            cliente.id, fecha_inicial_pago=date(2026, 7, 6), numero_cuotas=2
        )
        db_session.add(credito)
        await db_session.flush()

        p1 = _mk_cuota(credito.id, 1, date(2026, 7, 6), pagado=False)  # lunes
        p2 = _mk_cuota(credito.id, 2, date(2026, 7, 7), pagado=False)  # martes
        db_session.add_all([p1, p2])
        await db_session.flush()

        client = await make_client(TipoUsuario.admin)
        r = await client.post(BACKFILL_URL)
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["revisados"] == 0
        assert str(credito.id) not in body["ids"]
        assert p1.fecha_maxima == date(2026, 7, 6)
        assert p2.fecha_maxima == date(2026, 7, 7)
