"""
tests/test_reportes_arrastre.py — Reported pending totals reflect the TRUE
(arrastre-inclusive) amounts, not base-only values.

Spec: Requirement "Reported Pending Totals Reflect True Amounts", scenario
"Totals rise after correction". `reportes.py` computes pending capital/
interest as `capital_a_pagar - capital_pagado` / `interes_a_pagar -
interes_pagado` (lines 91-92, 113-114, 133-134) directly from the persisted
row — it needs no code change from this feature, but was never exercised by
any test in this change. This test proves the totals rise by exactly the
disaggregated arrastre once a pending cuota's components are corrected,
locking in the owner-accepted "rise is intended correctness" behavior.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

REPORTES_URL = "/api/v1/reportes"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Reporte", apellidos="Test", cedula=str(uuid.uuid4().int)[:10],
        telefono="3000000000", direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Reporte-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"),
        tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 10),
        periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=10,
        calcular_interes_dias_corridos=False,
        activo=True,
    )


def _mk_pago_pendiente(
    credito_id: uuid.UUID,
    capital_a_pagar: Decimal,
    interes_a_pagar: Decimal,
    monto_a_pagar: Decimal,
) -> Pago:
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=2,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=monto_a_pagar,
        capital_a_pagar=capital_a_pagar, interes_a_pagar=interes_a_pagar,
        capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
        momento="m3", fecha_maxima=date(2026, 2, 9),
        pagado=False, validado_recaudador=False, es_ultimo_pago=False,
    )


@pytest_asyncio.fixture
async def client_admin_db(db_session):
    admin = MagicMock(spec=Usuario)
    admin.id = uuid.uuid4()
    admin.tipo_usuario = TipoUsuario.admin
    admin.activo = True
    admin.deleted_at = None

    async def override_user():
        return admin

    async def override_db():
        yield db_session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestTotalesPendientesReflejanArrastre:

    @pytest.mark.asyncio
    async def test_totales_suben_tras_correccion_de_arrastre(
        self, client_admin_db: AsyncClient, db_session
    ):
        """
        A pending `cuota_fija` row starts at base components (100.00/20.00).
        The reported pending totals for its month/momento must equal exactly
        those base values. Once the row is corrected to arrastre-inclusive
        components (150.00/30.00 — a 50.00/10.00 carry-over), the SAME report
        query MUST report the higher TRUE amounts, not the stale base values.
        """
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id)
        db_session.add(credito)
        await db_session.flush()

        pago = _mk_pago_pendiente(
            credito.id,
            capital_a_pagar=Decimal("100.00"),
            interes_a_pagar=Decimal("20.00"),
            monto_a_pagar=Decimal("120.00"),
        )
        db_session.add(pago)
        await db_session.flush()

        r_antes = await client_admin_db.get(
            REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"}
        )
        assert r_antes.status_code == 200, r_antes.text
        body_antes = r_antes.json()
        assert body_antes["total_capital_pendiente"] == 100.00
        assert body_antes["total_intereses_pendientes"] == 20.00
        assert body_antes["total_pendiente"] == 120.00

        # Correct the row to arrastre-inclusive components (the disaggregated
        # 50.00 capital / 10.00 interest carry-over), exactly as the backfill
        # (or a fresh generation) would produce. monto_a_pagar already
        # reflected the arrastre before correction, per the shipped defect.
        pago.capital_a_pagar = Decimal("150.00")
        pago.interes_a_pagar = Decimal("30.00")
        await db_session.flush()

        r_despues = await client_admin_db.get(
            REPORTES_URL, params={"anio": 2026, "mes": 2, "momento": "m3"}
        )
        assert r_despues.status_code == 200, r_despues.text
        body_despues = r_despues.json()

        # TRUE amounts reported, not clamped back to base — this rise is
        # intended correctness (spec Requirement 6), not a regression.
        assert body_despues["total_capital_pendiente"] == 150.00
        assert body_despues["total_intereses_pendientes"] == 30.00
        assert body_despues["total_pendiente"] == 180.00

        # Exact rise equals the disaggregated arrastre — no clamping, no drift.
        assert (
            body_despues["total_capital_pendiente"] - body_antes["total_capital_pendiente"]
            == 50.00
        )
        assert (
            body_despues["total_intereses_pendientes"] - body_antes["total_intereses_pendientes"]
            == 10.00
        )
