"""
tests/test_reportes_corte_original.py — El reporte de ingresos usa el mismo
criterio que el listado de Pagos (`listar_pagos`):

- Ventana por `fecha_maxima_original` (corte inmutable), no `fecha_maxima`
  vigente: un pago aplazado se cuenta en el momento donde nació.
- Pendientes de créditos NO operativamente abiertos (inactivos / saldados) se
  excluyen; los pagos ya pagados se conservan siempre como historial.
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
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario

REPORTES_URL = "/api/v1/reportes"


def _mk_cliente() -> Cliente:
    return Cliente(
        id=uuid.uuid4(), gestor_id=uuid.uuid4(),
        nombre="Reporte", apellidos=f"Corte{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID, *, saldo_capital="850.00", activo=True) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Corte-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal(saldo_capital),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=activo,
    )


def _mk_pago(
    credito_id: uuid.UUID, *, pagado: bool, fecha_maxima: date,
    fecha_maxima_original: date | None = None, numero_cuota: int = 1,
) -> Pago:
    capital, interes = Decimal("100.00"), Decimal("20.00")
    return Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=numero_cuota,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=capital + interes,
        capital_a_pagar=capital, interes_a_pagar=interes,
        capital_pagado=capital if pagado else Decimal("0.00"),
        interes_pagado=interes if pagado else Decimal("0.00"),
        momento="m3", fecha_maxima=fecha_maxima,
        fecha_maxima_original=fecha_maxima_original,
        pagado=pagado, validado_recaudador=pagado, es_ultimo_pago=False,
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


# feb 2026 m3 = días 8-14 aprox (ver utils/momentos); se usa fecha_desde/hasta
# explícitas para no depender de los límites de momento.
VENTANA_ORIGINAL = {"fecha_desde": "2026-02-01", "fecha_hasta": "2026-02-28"}
VENTANA_NUEVA = {"fecha_desde": "2026-03-01", "fecha_hasta": "2026-03-31"}


class TestVentanaPorCorteOriginal:

    @pytest.mark.asyncio
    async def test_pendiente_aplazado_cuenta_en_ventana_original_no_en_la_nueva(
        self, client_admin_db: AsyncClient, db_session
    ):
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id)
        db_session.add(credito)
        await db_session.flush()
        # Aplazado: fecha_maxima vigente se movió a marzo, nació en febrero.
        db_session.add(_mk_pago(
            credito.id, pagado=False,
            fecha_maxima=date(2026, 3, 10), fecha_maxima_original=date(2026, 2, 10),
        ))
        await db_session.flush()

        r_orig = await client_admin_db.get(REPORTES_URL, params=VENTANA_ORIGINAL)
        r_nueva = await client_admin_db.get(REPORTES_URL, params=VENTANA_NUEVA)
        assert r_orig.status_code == 200, r_orig.text
        assert r_nueva.status_code == 200, r_nueva.text

        assert r_orig.json()["total_pendiente"] == 120.00
        assert r_orig.json()["total_capital_pendiente"] == 100.00
        assert r_nueva.json()["total_pendiente"] == 0.00


class TestGuardCreditoOperativamenteAbierto:

    @pytest.mark.asyncio
    async def test_pendiente_de_credito_saldado_se_excluye_pero_pagado_se_conserva(
        self, client_admin_db: AsyncClient, db_session
    ):
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        # Saldado: activo=True pero saldo_capital = 0 (regla 9).
        credito = _mk_credito(cliente.id, saldo_capital="0.00")
        db_session.add(credito)
        await db_session.flush()
        db_session.add(_mk_pago(
            credito.id, pagado=True, fecha_maxima=date(2026, 2, 10), numero_cuota=1,
        ))
        db_session.add(_mk_pago(
            credito.id, pagado=False, fecha_maxima=date(2026, 2, 12), numero_cuota=2,
        ))
        await db_session.flush()

        r = await client_admin_db.get(REPORTES_URL, params=VENTANA_ORIGINAL)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_recaudado"] == 120.00   # historial conservado
        assert body["total_pendiente"] == 0.00     # pendiente excluido

    @pytest.mark.asyncio
    async def test_pendiente_de_credito_inactivo_se_excluye_pero_pagado_se_conserva(
        self, client_admin_db: AsyncClient, db_session
    ):
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id, activo=False)
        db_session.add(credito)
        await db_session.flush()
        db_session.add(_mk_pago(
            credito.id, pagado=True, fecha_maxima=date(2026, 2, 10), numero_cuota=1,
        ))
        db_session.add(_mk_pago(
            credito.id, pagado=False, fecha_maxima=date(2026, 2, 12), numero_cuota=2,
        ))
        await db_session.flush()

        r = await client_admin_db.get(REPORTES_URL, params=VENTANA_ORIGINAL)
        body = r.json()
        assert body["total_recaudado"] == 120.00
        assert body["total_pendiente"] == 0.00
