"""
tests/test_creditos_actualizar.py — Saldo en la edición de crédito.

Regresión del bug: al cambiar la fecha de un pago/crédito, el formulario
reenvía capital_prestado (pre-cargado) y el backend reseteaba saldo_capital
al capital completo, "resucitando" el capital ya pagado.
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
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario


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
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


async def _crear_credito_con_pago(db_session, sufijo: str) -> Credito:
    """Crédito cuota_fija de 1000 con 400 de capital ya pagado → saldo 600."""
    credito = Credito(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente=f"Test {sufijo}-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("600.00"),
        saldo_intereses=Decimal("300.00"),
        numero_cuotas=12,
        activo=True,
    )
    db_session.add(credito)
    # Cuota 1 pagada con 400 de capital.
    db_session.add(Pago(
        id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("430.00"),
        capital_a_pagar=Decimal("400.00"), interes_a_pagar=Decimal("30.00"),
        capital_pagado=Decimal("400.00"), interes_pagado=Decimal("30.00"),
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=True,
    ))
    # Cuota 2 pendiente (target de los recálculos).
    db_session.add(Pago(
        id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("430.00"),
        capital_a_pagar=Decimal("400.00"), interes_a_pagar=Decimal("30.00"),
        capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
        momento="m1", fecha_maxima=date(2026, 3, 1), pagado=False,
    ))
    await db_session.flush()
    return credito


class TestActualizarCreditoSaldo:
    @pytest.mark.asyncio
    async def test_cambio_de_fecha_no_resetea_saldo_capital(self, client_admin_db, db_session):
        """
        Escenario reportado: el form reenvía capital_prestado (igual) al cambiar
        la fecha. saldo_capital debe quedarse en 600, NO volver a 1000.
        """
        credito = await _crear_credito_con_pago(db_session, "fecha")

        r = await client_admin_db.patch(
            f"/api/v1/creditos/{credito.id}",
            json={"capital_prestado": 1000, "fecha_pago_activo": "2026-04-01"},
        )
        assert r.status_code == 200, r.text
        assert credito.saldo_capital == Decimal("600.00"), (
            f"saldo_capital={credito.saldo_capital}, esperado 600.00 (no debe resetearse)"
        )

    @pytest.mark.asyncio
    async def test_cambio_real_de_capital_descuenta_lo_pagado(self, client_admin_db, db_session):
        """
        Si el capital cambia de verdad (1000 → 1200), el saldo es
        1200 − 400 (ya pagado) = 800, no 1200.
        """
        credito = await _crear_credito_con_pago(db_session, "capital")

        r = await client_admin_db.patch(
            f"/api/v1/creditos/{credito.id}",
            json={"capital_prestado": 1200},
        )
        assert r.status_code == 200, r.text
        assert credito.saldo_capital == Decimal("800.00"), (
            f"saldo_capital={credito.saldo_capital}, esperado 800.00 (1200 − 400 pagado)"
        )
