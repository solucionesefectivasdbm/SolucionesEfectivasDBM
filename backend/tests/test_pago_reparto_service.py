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
from app.schemas.pago_reparto import RepartoItem
from app.services import pago_reparto_service
from app.utils.tz import ahora_bogota


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


# ─── PR2: reparto explícito multi-destinatario ──────────────────────────────


class TestReemplazarRepartos:
    """`reemplazar_repartos` (PR2) — reemplazo atómico del set completo de
    repartos de un pago pagado, con validación de suma exacta, duplicados y
    existencia de destinatarios (design.md 'Write API' / 'Sum check')."""

    @pytest.mark.asyncio
    async def test_split_dos_cuentas_reemplaza_el_activo_previo(self, db_session):
        """Req: Split Allocation Persistence — 'Split across two receiver accounts'."""
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("600.00"), interes_pagado=Decimal("400.00"),
        )
        previo = await pago_reparto_service.crear_reparto_por_defecto(db_session, pago)
        assert previo is not None

        receptor_b = _mk_receptor()
        cuenta_b = _mk_cuenta(receptor_b.id)
        db_session.add_all([receptor_b, cuenta_b])
        await db_session.flush()

        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("600.00"),
            ),
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_b.id, monto=Decimal("400.00"),
            ),
        ]

        antes, despues = await pago_reparto_service.reemplazar_repartos(db_session, pago, items)

        assert len(antes) == 1
        assert antes[0]["id"] == str(previo.id)
        assert len(despues) == 2

        await db_session.refresh(previo)
        assert previo.deleted_at is not None

        activos = await _repartos_activos(db_session, pago.id)
        assert len(activos) == 2
        assert sum((r.monto for r in activos), Decimal("0.00")) == Decimal("1000.00")

    @pytest.mark.asyncio
    async def test_split_mixto_cuenta_y_cliente_no_crea_credito(self, db_session):
        """Req: Split Allocation Persistence — 'Mixed account and client split'.
        Req: Client-Type Split Never Creates Credit."""
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("70.00"), interes_pagado=Decimal("30.00"),
        )
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        creditos_antes = (await db_session.execute(select(Credito))).scalars().all()
        cantidad_creditos_antes = len(creditos_antes)

        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("70.00"),
            ),
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cliente,
                cliente_id=cliente.id, monto=Decimal("30.00"),
            ),
        ]

        _, despues = await pago_reparto_service.reemplazar_repartos(db_session, pago, items)
        assert len(despues) == 2

        creditos_despues = (await db_session.execute(select(Credito))).scalars().all()
        assert len(creditos_despues) == cantidad_creditos_antes

        activos = await _repartos_activos(db_session, pago.id)
        tipos = {r.tipo_destinatario for r in activos}
        assert tipos == {TipoDestinatario.cuenta_bancaria, TipoDestinatario.cliente}

    @pytest.mark.asyncio
    async def test_split_tres_destinatarios_dos_cuentas_y_un_cliente(self, db_session):
        """Regresión de cobertura (Judgment Day, Juez B): el spec/design
        habla de reparto entre "múltiples" destinatarios sin límite de 2 —
        cubrir explícitamente un split a 3 (2 cuentas + 1 cliente), no solo
        el caso de 2, para no dejar la aritmética N-aria sin probar."""
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("500.00"), interes_pagado=Decimal("100.00"),
        )
        receptor_b = _mk_receptor()
        cuenta_b = _mk_cuenta(receptor_b.id)
        db_session.add_all([receptor_b, cuenta_b])
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()

        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("300.00"),
            ),
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_b.id, monto=Decimal("250.00"),
            ),
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cliente,
                cliente_id=cliente.id, monto=Decimal("50.00"),
            ),
        ]

        _, despues = await pago_reparto_service.reemplazar_repartos(db_session, pago, items)

        assert len(despues) == 3
        activos = await _repartos_activos(db_session, pago.id)
        assert len(activos) == 3
        assert sum((r.monto for r in activos), Decimal("0.00")) == Decimal("600.00")
        cuentas = {r.cuenta_bancaria_id for r in activos if r.tipo_destinatario == TipoDestinatario.cuenta_bancaria}
        assert cuentas == {cuenta_a.id, cuenta_b.id}

        # 3+ destinatarios también bloquea la herencia (misma regla que 2).
        h = pago_reparto_service.cuenta_heredable(despues)
        assert h is None

    @pytest.mark.asyncio
    async def test_suma_incorrecta_rechaza_y_no_modifica_nada(self, db_session):
        """Req: Split Integrity Validation — 'Split sum mismatch rejected'."""
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("60.00"), interes_pagado=Decimal("40.00"),
        )
        previo = await pago_reparto_service.crear_reparto_por_defecto(db_session, pago)

        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("99.99"),
            ),
        ]

        with pytest.raises(ValueError):
            await pago_reparto_service.reemplazar_repartos(db_session, pago, items)

        await db_session.refresh(previo)
        assert previo.deleted_at is None
        activos = await _repartos_activos(db_session, pago.id)
        assert len(activos) == 1
        assert activos[0].id == previo.id

    @pytest.mark.asyncio
    async def test_destinatario_duplicado_rechazado(self, db_session):
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("50.00"), interes_pagado=Decimal("50.00"),
        )
        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("50.00"),
            ),
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("50.00"),
            ),
        ]

        with pytest.raises(ValueError):
            await pago_reparto_service.reemplazar_repartos(db_session, pago, items)

        assert await _repartos_activos(db_session, pago.id) == []

    @pytest.mark.asyncio
    async def test_cuenta_bancaria_desconocida_rechazada(self, db_session):
        pago, _ = await _preparar_pago(
            db_session, capital_pagado=Decimal("100.00"), interes_pagado=Decimal("0.00"),
        )
        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=uuid.uuid4(), monto=Decimal("100.00"),
            ),
        ]

        with pytest.raises(ValueError):
            await pago_reparto_service.reemplazar_repartos(db_session, pago, items)

    @pytest.mark.asyncio
    async def test_cliente_eliminado_rechazado(self, db_session):
        pago, _ = await _preparar_pago(
            db_session, capital_pagado=Decimal("0.00"), interes_pagado=Decimal("100.00"),
        )
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        cliente.deleted_at = ahora_bogota()
        await db_session.flush()

        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cliente,
                cliente_id=cliente.id, monto=Decimal("100.00"),
            ),
        ]

        with pytest.raises(ValueError):
            await pago_reparto_service.reemplazar_repartos(db_session, pago, items)

    @pytest.mark.asyncio
    async def test_conjunto_vacio_rechazado(self, db_session):
        pago, _ = await _preparar_pago(db_session)

        with pytest.raises(ValueError):
            await pago_reparto_service.reemplazar_repartos(db_session, pago, [])

    @pytest.mark.asyncio
    async def test_pago_pendiente_rechazado(self, db_session):
        """Req: When split allowed — solo pagos pagados (design.md)."""
        pago, cuenta_a = await _preparar_pago(db_session, pagado=False)
        items = [
            RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("100.00"),
            ),
        ]

        with pytest.raises(ValueError):
            await pago_reparto_service.reemplazar_repartos(db_session, pago, items)


class TestCuentaHeredable:
    """`cuenta_heredable` (PR2) — decide si la siguiente cuota debe seguir
    heredando cuenta tras un reparto (design.md decisión 'Inheritance',
    Engram #1079/#1081: bloquea con 2+ destinatarios de CUALQUIER tipo, no
    solo 2+ cuentas)."""

    def test_un_destinatario_tipo_cuenta_devuelve_esa_cuenta(self):
        cuenta_id = uuid.uuid4()
        repartos = [{
            "id": str(uuid.uuid4()), "cuenta_bancaria_id": str(cuenta_id),
            "cliente_id": None, "monto": "100.00",
        }]
        assert pago_reparto_service.cuenta_heredable(repartos) == cuenta_id

    def test_un_destinatario_tipo_cliente_devuelve_none(self):
        repartos = [{
            "id": str(uuid.uuid4()), "cuenta_bancaria_id": None,
            "cliente_id": str(uuid.uuid4()), "monto": "100.00",
        }]
        assert pago_reparto_service.cuenta_heredable(repartos) is None

    def test_dos_cuentas_devuelve_none(self):
        repartos = [
            {"id": str(uuid.uuid4()), "cuenta_bancaria_id": str(uuid.uuid4()), "cliente_id": None, "monto": "60.00"},
            {"id": str(uuid.uuid4()), "cuenta_bancaria_id": str(uuid.uuid4()), "cliente_id": None, "monto": "40.00"},
        ]
        assert pago_reparto_service.cuenta_heredable(repartos) is None

    def test_cuenta_y_cliente_devuelve_none(self):
        """cuenta A + cliente X = 2 destinatarios -> bloquea herencia, aunque
        solo haya UNA cuenta bancaria involucrada (Engram #1079)."""
        repartos = [
            {"id": str(uuid.uuid4()), "cuenta_bancaria_id": str(uuid.uuid4()), "cliente_id": None, "monto": "70.00"},
            {"id": str(uuid.uuid4()), "cuenta_bancaria_id": None, "cliente_id": str(uuid.uuid4()), "monto": "30.00"},
        ]
        assert pago_reparto_service.cuenta_heredable(repartos) is None


class TestAplicarHerencia:
    """`aplicar_herencia` (PR2) — wiring de `cuenta_heredable` sobre el pago
    actual y la siguiente cuota pendiente."""

    @pytest.mark.asyncio
    async def test_un_destinatario_no_toca_la_siguiente_cuota(self, db_session):
        pago, cuenta_a = await _preparar_pago(db_session)
        siguiente = _mk_pago(
            pago.credito_id, cuenta_a.id, numero_cuota=2, pagado=False,
            validado_recaudador=False, capital_pagado=Decimal("0.00"),
            interes_pagado=Decimal("0.00"),
        )
        db_session.add(siguiente)
        await db_session.flush()

        _, despues = await pago_reparto_service.reemplazar_repartos(
            db_session, pago,
            [RepartoItem(
                tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("100.00"),
            )],
        )
        anterior, h, afectados = await pago_reparto_service.aplicar_herencia(db_session, pago, despues)

        assert h == cuenta_a.id
        assert pago.cuenta_bancaria_id == cuenta_a.id
        assert afectados == []
        await db_session.refresh(siguiente)
        assert siguiente.cuenta_bancaria_id == cuenta_a.id

    @pytest.mark.asyncio
    async def test_dos_destinatarios_limpia_la_siguiente_cuota_pendiente(self, db_session):
        """Req: No Account Inheritance After Split — 'Prior payment split
        across two accounts'."""
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("600.00"), interes_pagado=Decimal("400.00"),
        )
        receptor_b = _mk_receptor()
        cuenta_b = _mk_cuenta(receptor_b.id)
        db_session.add(receptor_b)
        db_session.add(cuenta_b)
        await db_session.flush()
        siguiente = _mk_pago(
            pago.credito_id, cuenta_a.id, numero_cuota=2, pagado=False,
            validado_recaudador=False, capital_pagado=Decimal("0.00"),
            interes_pagado=Decimal("0.00"),
        )
        db_session.add(siguiente)
        await db_session.flush()

        _, despues = await pago_reparto_service.reemplazar_repartos(
            db_session, pago,
            [
                RepartoItem(tipo_destinatario=TipoDestinatario.cuenta_bancaria, cuenta_bancaria_id=cuenta_a.id, monto=Decimal("600.00")),
                RepartoItem(tipo_destinatario=TipoDestinatario.cuenta_bancaria, cuenta_bancaria_id=cuenta_b.id, monto=Decimal("400.00")),
            ],
        )
        anterior, h, afectados = await pago_reparto_service.aplicar_herencia(db_session, pago, despues)

        assert h is None
        assert pago.cuenta_bancaria_id is None
        assert afectados == [siguiente.id]
        await db_session.refresh(siguiente)
        assert siguiente.cuenta_bancaria_id is None

    @pytest.mark.asyncio
    async def test_siguiente_cuota_modificada_manualmente_no_se_toca(self, db_session):
        """'manually changed next cuota is not touched' (tasks.md 2.5)."""
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("600.00"), interes_pagado=Decimal("400.00"),
        )
        receptor_b = _mk_receptor()
        cuenta_b = _mk_cuenta(receptor_b.id)
        receptor_c = _mk_receptor()
        cuenta_c = _mk_cuenta(receptor_c.id)
        db_session.add_all([receptor_b, cuenta_b, receptor_c, cuenta_c])
        await db_session.flush()
        # La siguiente cuota YA fue reasignada manualmente a C (no a la A
        # heredada por defecto) antes de que alguien reparta el pago 1.
        siguiente = _mk_pago(
            pago.credito_id, cuenta_c.id, numero_cuota=2, pagado=False,
            validado_recaudador=False, capital_pagado=Decimal("0.00"),
            interes_pagado=Decimal("0.00"),
        )
        db_session.add(siguiente)
        await db_session.flush()

        _, despues = await pago_reparto_service.reemplazar_repartos(
            db_session, pago,
            [
                RepartoItem(tipo_destinatario=TipoDestinatario.cuenta_bancaria, cuenta_bancaria_id=cuenta_a.id, monto=Decimal("600.00")),
                RepartoItem(tipo_destinatario=TipoDestinatario.cuenta_bancaria, cuenta_bancaria_id=cuenta_b.id, monto=Decimal("400.00")),
            ],
        )
        anterior, h, afectados = await pago_reparto_service.aplicar_herencia(db_session, pago, despues)

        assert h is None
        assert afectados == []
        await db_session.refresh(siguiente)
        assert siguiente.cuenta_bancaria_id == cuenta_c.id

    @pytest.mark.asyncio
    async def test_cuenta_y_cliente_tambien_limpia_la_siguiente_cuota(self, db_session):
        """Req: No Account Inheritance After Split — 'Prior payment split
        between one account and one client' (Engram #1079: 1 cuenta + 1
        cliente = 2 destinatarios, también bloquea)."""
        pago, cuenta_a = await _preparar_pago(
            db_session, capital_pagado=Decimal("70.00"), interes_pagado=Decimal("30.00"),
        )
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        siguiente = _mk_pago(
            pago.credito_id, cuenta_a.id, numero_cuota=2, pagado=False,
            validado_recaudador=False, capital_pagado=Decimal("0.00"),
            interes_pagado=Decimal("0.00"),
        )
        db_session.add(siguiente)
        await db_session.flush()

        _, despues = await pago_reparto_service.reemplazar_repartos(
            db_session, pago,
            [
                RepartoItem(tipo_destinatario=TipoDestinatario.cuenta_bancaria, cuenta_bancaria_id=cuenta_a.id, monto=Decimal("70.00")),
                RepartoItem(tipo_destinatario=TipoDestinatario.cliente, cliente_id=cliente.id, monto=Decimal("30.00")),
            ],
        )
        anterior, h, afectados = await pago_reparto_service.aplicar_herencia(db_session, pago, despues)

        assert h is None
        assert afectados == [siguiente.id]
        await db_session.refresh(siguiente)
        assert siguiente.cuenta_bancaria_id is None
