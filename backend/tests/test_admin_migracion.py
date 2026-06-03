"""
tests/test_admin_migracion.py — Test FUNCIONAL del endpoint de recálculo de saldos.

A diferencia de test_admin_router.py (que solo cubre acceso 403/200 con DB
vacía), acá se insertan créditos con saldo INFLADO (el estado que dejó el bug)
y se verifica que la migración los corrige a:
  saldo_capital   = capital_prestado − Σ capital_pagado
  saldo_intereses = (cuota_fija)  total_interes − Σ interes_pagado
                    (abono_capital) saldo_capital_corregido × tasa
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

ENDPOINT = "/api/v1/admin/migracion/recalcular-saldos"


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


async def _credito(db_session, **kw) -> Credito:
    defaults = dict(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente=f"Test {uuid.uuid4().hex[:8]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("1000.00"),
        saldo_intereses=Decimal("360.00"),
        numero_cuotas=12,
        activo=True,
    )
    defaults.update(kw)
    c = Credito(**defaults)
    db_session.add(c)
    await db_session.flush()
    return c


async def _pago_pagado(db_session, credito, capital, interes, numero=1):
    db_session.add(Pago(
        id=uuid.uuid4(), credito_id=credito.id, numero_cuota=numero,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=(capital + interes),
        capital_a_pagar=capital, interes_a_pagar=interes,
        capital_pagado=capital, interes_pagado=interes,
        momento="m1", fecha_maxima=date(2026, 2, 1), pagado=True,
    ))
    await db_session.flush()


class TestMigracionRecalculo:
    @pytest.mark.asyncio
    async def test_cuota_fija_saldo_inflado_se_corrige(self, client_admin_db, db_session):
        # Estado del bug: saldo_capital=1000 (debería ser 600), saldo_intereses=360 (debería 330).
        credito = await _credito(
            db_session,
            tipo_credito=TipoCredito.cuota_fija,
            capital_prestado=Decimal("1000.00"),
            saldo_capital=Decimal("1000.00"),
            saldo_intereses=Decimal("360.00"),
            numero_cuotas=12,
        )
        await _pago_pagado(db_session, credito, Decimal("400.00"), Decimal("30.00"))

        r = await client_admin_db.post(ENDPOINT)
        assert r.status_code == 200, r.text
        data = r.json()

        assert credito.saldo_capital == Decimal("600.00"), credito.saldo_capital
        # interes_total = 1000 * 0.03 * 12 = 360; pagado 30 → 330
        assert credito.saldo_intereses == Decimal("330.00"), credito.saldo_intereses

        assert data["total_corregidos"] >= 1
        entry = next(e for e in data["corregidos"] if e["credito_id"] == str(credito.id))
        assert entry["saldo_capital"] == ["1000.00", "600.00"]
        assert entry["saldo_intereses"] == ["360.00", "330.00"]

    @pytest.mark.asyncio
    async def test_abono_capital_saldo_inflado_se_corrige(self, client_admin_db, db_session):
        # abono_capital: saldo_capital=2000 (debería 1500), saldo_intereses=60 (debería 1500*0.03=45).
        credito = await _credito(
            db_session,
            tipo_credito=TipoCredito.abono_capital,
            capital_prestado=Decimal("2000.00"),
            saldo_capital=Decimal("2000.00"),
            saldo_intereses=Decimal("60.00"),
            numero_cuotas=None,
        )
        await _pago_pagado(db_session, credito, Decimal("500.00"), Decimal("60.00"))

        r = await client_admin_db.post(ENDPOINT)
        assert r.status_code == 200, r.text

        assert credito.saldo_capital == Decimal("1500.00"), credito.saldo_capital
        assert credito.saldo_intereses == Decimal("45.00"), credito.saldo_intereses

    @pytest.mark.asyncio
    async def test_credito_ya_correcto_no_se_toca(self, client_admin_db, db_session):
        # Saldos ya correctos → no debe contarlo como corregido.
        credito = await _credito(
            db_session,
            tipo_credito=TipoCredito.cuota_fija,
            capital_prestado=Decimal("1000.00"),
            saldo_capital=Decimal("600.00"),
            saldo_intereses=Decimal("330.00"),
            numero_cuotas=12,
        )
        await _pago_pagado(db_session, credito, Decimal("400.00"), Decimal("30.00"))

        r = await client_admin_db.post(ENDPOINT)
        assert r.status_code == 200, r.text
        data = r.json()

        assert credito.saldo_capital == Decimal("600.00")
        assert credito.saldo_intereses == Decimal("330.00")
        # No debe aparecer en la lista de corregidos.
        assert all(e["credito_id"] != str(credito.id) for e in data["corregidos"])
