"""
tests/test_pago_reparto_service.py — pago_reparto_service (payment-multi-
recipient, item 10, PR1): `crear_reparto_por_defecto` (fila 100% al
registrar un pago) y `reemplazar_por_cuenta_unica` (sync interno del PATCH
legacy de cuenta bancaria).

PR1 solo cubre el caso de UN destinatario (registro normal y el PATCH
legacy). El reparto explícito multi-destinatario, con validación completa
de suma exacta / duplicados / existencia (`reemplazar_repartos`), llega en
PR2 — ver design.md.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cliente import Cliente
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.pago_reparto import PagoReparto, TipoDestinatario
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.services import pago_reparto_service


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
        nombre="Reparto", apellidos=f"Test{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Reparto-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )


def _mk_pago(credito_id: uuid.UUID, cuenta_bancaria_id, **overrides) -> Pago:
    base = dict(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=Decimal("100.00"),
        capital_a_pagar=Decimal("80.00"), interes_a_pagar=Decimal("20.00"),
        capital_pagado=Decimal("80.00"), interes_pagado=Decimal("20.00"),
        momento="m3", fecha_maxima=date(2026, 2, 10),
        pagado=True, validado_recaudador=True, es_ultimo_pago=False,
        cuenta_bancaria_id=cuenta_bancaria_id,
    )
    base.update(overrides)
    return Pago(**base)


async def _preparar_pago(db_session, **pago_overrides) -> tuple[Pago, CuentaBancaria]:
    """Crea receptor+cuenta+cliente+credito+pago. `pago_overrides` puede
    pasar `cuenta_bancaria_id=None` para simular un pago sin cuenta."""
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
    cuenta_id = pago_overrides.pop("cuenta_bancaria_id", cuenta.id)
    pago = _mk_pago(credito.id, cuenta_id, **pago_overrides)
    db_session.add(pago)
    await db_session.flush()
    return pago, cuenta


async def _repartos_activos(db_session, pago_id) -> list[PagoReparto]:
    return (await db_session.execute(
        select(PagoReparto).where(PagoReparto.pago_id == pago_id, PagoReparto.deleted_at == None)  # noqa: E711
    )).scalars().all()


class TestCrearRepartoPorDefecto:
    @pytest.mark.asyncio
    async def test_crea_una_fila_100_por_ciento_al_monto_pagado(self, db_session):
        """Req: Split Allocation Persistence (caso de 1 destinatario) —
        la fila creada cubre exactamente capital_pagado + interes_pagado."""
        pago, cuenta = await _preparar_pago(
            db_session, capital_pagado=Decimal("600.00"), interes_pagado=Decimal("400.00"),
        )

        reparto = await pago_reparto_service.crear_reparto_por_defecto(db_session, pago)

        assert reparto is not None
        assert reparto.pago_id == pago.id
        assert reparto.tipo_destinatario == TipoDestinatario.cuenta_bancaria
        assert reparto.cuenta_bancaria_id == cuenta.id
        assert reparto.cliente_id is None
        assert reparto.monto == Decimal("1000.00")

        filas = await _repartos_activos(db_session, pago.id)
        assert len(filas) == 1

    @pytest.mark.asyncio
    async def test_sin_cuenta_bancaria_no_crea_fila(self, db_session):
        """Invariante I1: solo pagos CON cuenta asignada tienen reparto."""
        pago, _ = await _preparar_pago(db_session, cuenta_bancaria_id=None)

        reparto = await pago_reparto_service.crear_reparto_por_defecto(db_session, pago)

        assert reparto is None
        assert await _repartos_activos(db_session, pago.id) == []

    @pytest.mark.asyncio
    async def test_monto_cero_no_crea_fila(self, db_session):
        """El CHECK ck_pago_repartos_monto_positivo exige monto > 0 — un
        pago pagado con total 0 no genera reparto."""
        pago, _ = await _preparar_pago(
            db_session, capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
        )

        reparto = await pago_reparto_service.crear_reparto_por_defecto(db_session, pago)

        assert reparto is None
        assert await _repartos_activos(db_session, pago.id) == []


class TestReemplazarPorCuentaUnica:
    """Sync interno usado por el PATCH legacy `/pagos/{id}/cuenta-bancaria`
    en un pago pagado (task 1.9/1.10) — cobertura a nivel de servicio,
    complementaria a la prueba de router en test_pagos_cuenta_bancaria.py."""

    @pytest.mark.asyncio
    async def test_pago_pendiente_no_crea_ni_borra_nada(self, db_session):
        pago, _ = await _preparar_pago(db_session, pagado=False)

        repartos_antes, repartos_despues = await pago_reparto_service.reemplazar_por_cuenta_unica(db_session, pago)

        assert repartos_antes == []
        assert repartos_despues is None
        assert await _repartos_activos(db_session, pago.id) == []

    @pytest.mark.asyncio
    async def test_pago_pagado_borra_repartos_previos_y_crea_uno_nuevo(self, db_session):
        pago, cuenta_original = await _preparar_pago(db_session)
        previo = await pago_reparto_service.crear_reparto_por_defecto(db_session, pago)
        assert previo is not None

        receptor_b = _mk_receptor()
        cuenta_b = _mk_cuenta(receptor_b.id)
        db_session.add_all([receptor_b, cuenta_b])
        await db_session.flush()
        pago.cuenta_bancaria_id = cuenta_b.id
        await db_session.flush()

        repartos_antes, repartos_despues = await pago_reparto_service.reemplazar_por_cuenta_unica(db_session, pago)

        assert len(repartos_antes) == 1
        assert repartos_antes[0]["id"] == str(previo.id)
        assert repartos_despues is not None
        assert repartos_despues["cuenta_bancaria_id"] == str(cuenta_b.id)

        await db_session.refresh(previo)
        assert previo.deleted_at is not None

        activos = await _repartos_activos(db_session, pago.id)
        assert len(activos) == 1
        assert activos[0].cuenta_bancaria_id == cuenta_b.id
        assert activos[0].monto == pago.capital_pagado + pago.interes_pagado

    @pytest.mark.asyncio
    async def test_dos_reemplazos_concurrentes_no_dejan_dos_repartos_activos(self, db_session):
        """Regresión del hallazgo de Judgment Day (Juez A): sin lock a nivel
        de router, dos llamadas concurrentes al servicio podían dejar 2
        filas activas para el mismo pago (doble conteo en el ledger). El
        lock vive en el router (`_get_pago_con_credito(lock=True)`), pero
        acá verificamos que, aun si el servicio se invoca dos veces en
        secuencia sin recargar `pago` entre medio, el estado final tiene
        una sola fila activa — el segundo `_soft_delete_repartos_activos`
        borra también la fila que el primer reemplazo acaba de crear."""
        pago, cuenta_original = await _preparar_pago(db_session)
        await pago_reparto_service.crear_reparto_por_defecto(db_session, pago)

        receptor_b = _mk_receptor()
        cuenta_b = _mk_cuenta(receptor_b.id)
        db_session.add_all([receptor_b, cuenta_b])
        await db_session.flush()
        pago.cuenta_bancaria_id = cuenta_b.id
        await db_session.flush()

        await pago_reparto_service.reemplazar_por_cuenta_unica(db_session, pago)
        await pago_reparto_service.reemplazar_por_cuenta_unica(db_session, pago)

        activos = await _repartos_activos(db_session, pago.id)
        assert len(activos) == 1
        assert activos[0].cuenta_bancaria_id == cuenta_b.id
