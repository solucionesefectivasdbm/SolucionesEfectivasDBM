"""
tests/test_receptor_ledger_service.py — Balance computation + overdraft-safe
write for the receiver-cash-balance ledger (item 9).

Exhaustive in the style of test_reportes_arrastre.py, given this repo's
carryover-bug history (saldo_capital/saldo_intereses drift, PRs #30-#33,
#36-#39): the entire point of `receptor_ledger_service` is to compute the
balance on read instead of persisting a running total, so it never repeats
that class of bug. `saldo = recaudado (from Pago) - salidas + correcciones`.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.models.cliente import Cliente
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.models.pago_reparto import PagoReparto, TipoDestinatario
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.receptor_movimiento import MovimientoReceptor, TipoMovimiento
from app.models.usuario import TipoUsuario, Usuario
from app.services import receptor_ledger_service
from app.utils.fechas import ahora_bogota


def _mk_usuario(**kwargs) -> Usuario:
    defaults = dict(
        id=uuid.uuid4(), username=f"user{uuid.uuid4().hex[:8]}", password_hash="x",
        telefono="3000000000", tipo_usuario=TipoUsuario.admin,
    )
    defaults.update(kwargs)
    return Usuario(**defaults)


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
        nombre="Ledger", apellidos=f"Test{uuid.uuid4().hex[:6]}",
        cedula=str(uuid.uuid4().int)[:10], telefono="3000000000",
        direccion="Calle test", al_dia=True,
    )


def _mk_credito(cliente_id: uuid.UUID) -> Credito:
    return Credito(
        id=uuid.uuid4(), cliente_id=cliente_id,
        numero_credito_cliente=f"Ledger-CR-{uuid.uuid4().hex[:6]}",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000.00"), tasa_interes_mensual=Decimal("0.0200"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1),
        periodicidad=Periodicidad.mensual, saldo_capital=Decimal("850.00"),
        saldo_intereses=Decimal("0.00"), numero_cuotas=10,
        calcular_interes_dias_corridos=False, activo=True,
    )


def _mk_pago(
    credito_id: uuid.UUID, cuenta_bancaria_id: uuid.UUID, *,
    capital: Decimal = Decimal("0.00"), interes: Decimal = Decimal("0.00"),
    pagado: bool = True, deleted: bool = False,
) -> Pago:
    p = Pago(
        id=uuid.uuid4(), credito_id=credito_id, numero_cuota=1,
        tipo_cuota=TipoCuota.programada, monto_a_pagar=capital + interes,
        capital_a_pagar=capital, interes_a_pagar=interes,
        capital_pagado=capital, interes_pagado=interes,
        momento="m3", fecha_maxima=date(2026, 2, 10),
        pagado=pagado, validado_recaudador=pagado, es_ultimo_pago=False,
        cuenta_bancaria_id=cuenta_bancaria_id,
    )
    if deleted:
        p.deleted_at = ahora_bogota()
    return p


async def _preparar_cuenta(db_session, **cuenta_kwargs) -> tuple[Receptor, CuentaBancaria]:
    receptor = _mk_receptor()
    cuenta = _mk_cuenta(receptor.id, **cuenta_kwargs)
    db_session.add_all([receptor, cuenta])
    await db_session.flush()
    return receptor, cuenta


async def _agregar_pago(db_session, cuenta_id: uuid.UUID, capital: Decimal, interes: Decimal, **kwargs) -> Pago:
    """Crea cliente+credito+pago y, si el pago queda pagado (default) con
    cuenta y monto > 0, también su `pago_reparto` por defecto al 100% —
    exactamente lo que `crear_reparto_por_defecto` hace en producción al
    registrar un pago. Esto preserva la paridad de los tests existentes
    (single-recipient) ahora que `saldos_por_cuenta` lee de `pago_repartos`
    en vez de `Pago.cuenta_bancaria_id` directo."""
    cliente = _mk_cliente()
    db_session.add(cliente)
    await db_session.flush()
    credito = _mk_credito(cliente.id)
    db_session.add(credito)
    await db_session.flush()
    pago = _mk_pago(credito.id, cuenta_id, capital=capital, interes=interes, **kwargs)
    db_session.add(pago)
    await db_session.flush()
    if pago.pagado and cuenta_id is not None and (capital + interes) > Decimal("0.00"):
        db_session.add(PagoReparto(
            id=uuid.uuid4(), pago_id=pago.id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
            cuenta_bancaria_id=cuenta_id, monto=capital + interes,
        ))
        await db_session.flush()
    return pago


# ─── saldos_por_cuenta: término "recaudado" (SUM(Pago) con sus filtros) ────

class TestSaldosPorCuentaRecaudo:
    @pytest.mark.asyncio
    async def test_sin_pagos_saldo_cero(self, db_session):
        _, cuenta = await _preparar_cuenta(db_session)
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("0.00")
        assert resultado[cuenta.id].recaudado == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_pago_no_pagado_se_ignora(self, db_session):
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("500.00"), Decimal("50.00"), pagado=False)
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_pago_soft_deleted_se_ignora(self, db_session):
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("300.00"), Decimal("30.00"), pagado=True, deleted=True)
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_pago_pagado_suma_capital_mas_interes(self, db_session):
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("800.00"), Decimal("200.00"), pagado=True)
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].recaudado == Decimal("1000.00")
        assert resultado[cuenta.id].saldo == Decimal("1000.00")


# ─── saldos_por_cuenta: salidas / correcciones ─────────────────────────────

class TestSaldosPorCuentaMovimientos:
    @pytest.mark.asyncio
    async def test_salida_resta_del_saldo(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("500.00"), Decimal("0.00"))
        db_session.add(MovimientoReceptor(
            id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.salida,
            monto=Decimal("200.00"), usuario_id=usuario.id,
        ))
        await db_session.flush()
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].salidas == Decimal("200.00")
        assert resultado[cuenta.id].saldo == Decimal("300.00")

    @pytest.mark.asyncio
    async def test_correccion_positiva_suma(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("100.00"), Decimal("0.00"))
        db_session.add(MovimientoReceptor(
            id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.correccion,
            monto=Decimal("20.00"), usuario_id=usuario.id,
        ))
        await db_session.flush()
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].correcciones == Decimal("20.00")
        assert resultado[cuenta.id].saldo == Decimal("120.00")

    @pytest.mark.asyncio
    async def test_correccion_negativa_resta(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("100.00"), Decimal("0.00"))
        db_session.add(MovimientoReceptor(
            id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.correccion,
            monto=Decimal("-15.00"), usuario_id=usuario.id,
        ))
        await db_session.flush()
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].correcciones == Decimal("-15.00")
        assert resultado[cuenta.id].saldo == Decimal("85.00")

    @pytest.mark.asyncio
    async def test_mezcla_recaudo_salida_correccion(self, db_session):
        """Spec scenario: 'Balance with mixed movement types'."""
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("800000.00"), Decimal("200000.00"))
        db_session.add_all([
            MovimientoReceptor(
                id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.salida,
                monto=Decimal("200000.00"), usuario_id=usuario.id,
            ),
            MovimientoReceptor(
                id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.correccion,
                monto=Decimal("-50000.00"), usuario_id=usuario.id,
            ),
        ])
        await db_session.flush()
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("750000.00")


class TestSaldosPorCuentaMultiCuenta:
    @pytest.mark.asyncio
    async def test_aislamiento_entre_cuentas_del_mismo_receptor(self, db_session):
        """Spec scenario: 'Balance scoped per cuenta_bancaria, not per receptor'."""
        usuario = _mk_usuario()
        db_session.add(usuario)
        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, entidad_bancaria="A")
        cuenta_b = _mk_cuenta(receptor.id, entidad_bancaria="B")
        db_session.add_all([receptor, cuenta_a, cuenta_b])
        await db_session.flush()
        await _agregar_pago(db_session, cuenta_a.id, Decimal("100.00"), Decimal("0.00"))
        await _agregar_pago(db_session, cuenta_b.id, Decimal("500.00"), Decimal("0.00"))
        db_session.add(MovimientoReceptor(
            id=uuid.uuid4(), cuenta_bancaria_id=cuenta_a.id, tipo=TipoMovimiento.salida,
            monto=Decimal("40.00"), usuario_id=usuario.id,
        ))
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta_a.id, cuenta_b.id])
        assert resultado[cuenta_a.id].saldo == Decimal("60.00")
        assert resultado[cuenta_b.id].saldo == Decimal("500.00")


class TestSaldosPorCuentaPrecision:
    @pytest.mark.asyncio
    async def test_precision_de_centavos_no_se_pierde(self, db_session):
        """Siete filas de un centavo: si el cómputo degradara a float en
        algún punto, el total revelaría error de redondeo binario."""
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        for _ in range(7):
            await _agregar_pago(db_session, cuenta.id, Decimal("0.01"), Decimal("0.00"))
        db_session.add(MovimientoReceptor(
            id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.correccion,
            monto=Decimal("0.03"), usuario_id=usuario.id,
        ))
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("0.10")
        assert isinstance(resultado[cuenta.id].saldo, Decimal)


class TestSaldosPorCuentaReasignacion:
    """payment-multi-recipient (item 10) — deliberate behavior change from
    the receptor-ledger spec delta: once a Pago is paid, its `pago_repartos`
    rows are the ONLY balance driver. This replaces the pre-item-10 scenario
    ('reassigning Pago.cuenta_bancaria_id shifts two balances') since that
    field is no longer authoritative for a paid pago."""

    @pytest.mark.asyncio
    async def test_reasignar_pago_cuenta_bancaria_directo_no_mueve_el_saldo(self, db_session):
        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, entidad_bancaria="A")
        cuenta_b = _mk_cuenta(receptor.id, entidad_bancaria="B")
        db_session.add_all([receptor, cuenta_a, cuenta_b])
        await db_session.flush()
        pago = await _agregar_pago(db_session, cuenta_a.id, Decimal("100000.00"), Decimal("0.00"))

        pago.cuenta_bancaria_id = cuenta_b.id
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta_a.id, cuenta_b.id])
        assert resultado[cuenta_a.id].saldo == Decimal("100000.00")
        assert resultado[cuenta_b.id].saldo == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_editar_reparto_mueve_el_saldo_entre_cuentas(self, db_session):
        """Spec scenario (receptor-ledger delta): 'Editing a reparto
        reassigns balance without a Pago-level reassignment'."""
        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, entidad_bancaria="A")
        cuenta_b = _mk_cuenta(receptor.id, entidad_bancaria="B")
        db_session.add_all([receptor, cuenta_a, cuenta_b])
        await db_session.flush()
        pago = await _agregar_pago(db_session, cuenta_a.id, Decimal("100000.00"), Decimal("0.00"))

        antes = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta_a.id, cuenta_b.id])
        assert antes[cuenta_a.id].saldo == Decimal("100000.00")
        assert antes[cuenta_b.id].saldo == Decimal("0.00")

        reparto = (await db_session.execute(
            select(PagoReparto).where(PagoReparto.pago_id == pago.id)
        )).scalar_one()
        reparto.cuenta_bancaria_id = cuenta_b.id
        await db_session.flush()

        despues = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta_a.id, cuenta_b.id])
        assert despues[cuenta_a.id].saldo == Decimal("0.00")
        assert despues[cuenta_b.id].saldo == Decimal("100000.00")


class TestSaldosPorCuentaReparto:
    """payment-multi-recipient (item 10) — pago_repartos como fuente del
    'recaudado' (reemplaza la lectura directa de Pago.cuenta_bancaria_id)."""

    @pytest.mark.asyncio
    async def test_split_dos_cuentas_acredita_cada_una_una_vez(self, db_session):
        """Spec scenario (receptor-ledger delta): 'Split payment contributes
        partial amounts to two balances'."""
        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, entidad_bancaria="A")
        cuenta_b = _mk_cuenta(receptor.id, entidad_bancaria="B")
        db_session.add_all([receptor, cuenta_a, cuenta_b])
        await db_session.flush()
        cliente = _mk_cliente()
        db_session.add(cliente)
        await db_session.flush()
        credito = _mk_credito(cliente.id)
        db_session.add(credito)
        await db_session.flush()
        # cuenta_a en Pago.cuenta_bancaria_id queda como legado/no autoritativo
        # (invariante: para un pago pagado, solo pago_repartos manda).
        pago = _mk_pago(credito.id, cuenta_a.id, capital=Decimal("60000.00"), interes=Decimal("40000.00"))
        db_session.add(pago)
        await db_session.flush()
        db_session.add_all([
            PagoReparto(
                id=uuid.uuid4(), pago_id=pago.id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_a.id, monto=Decimal("60000.00"),
            ),
            PagoReparto(
                id=uuid.uuid4(), pago_id=pago.id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta_b.id, monto=Decimal("40000.00"),
            ),
        ])
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta_a.id, cuenta_b.id])
        assert resultado[cuenta_a.id].saldo == Decimal("60000.00")
        assert resultado[cuenta_b.id].saldo == Decimal("40000.00")

    @pytest.mark.asyncio
    async def test_reparto_tipo_cliente_se_ignora(self, db_session):
        """Spec scenario (receptor-ledger delta): 'Split payment with a
        client recipient contributes nothing to that client' — cliente-type
        rows never touch cuenta balances (cuenta_bancaria_id is NULL on them
        by construction, so the IN(cuenta_ids) filter never matches)."""
        _, cuenta = await _preparar_cuenta(db_session)
        cliente_credito = _mk_cliente()
        db_session.add(cliente_credito)
        await db_session.flush()
        credito = _mk_credito(cliente_credito.id)
        db_session.add(credito)
        await db_session.flush()
        pago = _mk_pago(credito.id, cuenta.id, capital=Decimal("70000.00"), interes=Decimal("0.00"))
        db_session.add(pago)
        await db_session.flush()
        cliente_destinatario = _mk_cliente()
        db_session.add(cliente_destinatario)
        await db_session.flush()
        db_session.add_all([
            PagoReparto(
                id=uuid.uuid4(), pago_id=pago.id, tipo_destinatario=TipoDestinatario.cuenta_bancaria,
                cuenta_bancaria_id=cuenta.id, monto=Decimal("70000.00"),
            ),
            PagoReparto(
                id=uuid.uuid4(), pago_id=pago.id, tipo_destinatario=TipoDestinatario.cliente,
                cliente_id=cliente_destinatario.id, monto=Decimal("30000.00"),
            ),
        ])
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("70000.00")

    @pytest.mark.asyncio
    async def test_reparto_soft_deleted_se_ignora(self, db_session):
        """Un reparto borrado lógicamente (editado/reemplazado) no debe
        contribuir al saldo, aunque su Pago siga pagado/activo."""
        _, cuenta = await _preparar_cuenta(db_session)
        pago = await _agregar_pago(db_session, cuenta.id, Decimal("50000.00"), Decimal("0.00"))
        reparto = (await db_session.execute(
            select(PagoReparto).where(PagoReparto.pago_id == pago.id)
        )).scalar_one()
        reparto.deleted_at = ahora_bogota()
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("0.00")


class TestSaldoSobreviveSoftDeleteDeReceptor:
    @pytest.mark.asyncio
    async def test_saldo_no_cambia_cuando_el_receptor_se_borra_logicamente(self, db_session):
        """Spec requirement: 'Ledger Entries Survive Receptor Soft-Delete'."""
        usuario = _mk_usuario()
        db_session.add(usuario)
        receptor, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("100.00"), Decimal("0.00"))
        db_session.add(MovimientoReceptor(
            id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.salida,
            monto=Decimal("30.00"), usuario_id=usuario.id,
        ))
        await db_session.flush()

        receptor.deleted_at = ahora_bogota()
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("70.00")


# ─── saldos_por_receptor ────────────────────────────────────────────────────

class TestSaldosPorReceptor:
    @pytest.mark.asyncio
    async def test_suma_saldo_total_de_todas_las_cuentas(self, db_session):
        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, entidad_bancaria="A", es_predeterminada=True)
        cuenta_b = _mk_cuenta(receptor.id, entidad_bancaria="B")
        db_session.add_all([receptor, cuenta_a, cuenta_b])
        await db_session.flush()
        await _agregar_pago(db_session, cuenta_a.id, Decimal("100.00"), Decimal("0.00"))
        await _agregar_pago(db_session, cuenta_b.id, Decimal("50.00"), Decimal("0.00"))

        resultado = await receptor_ledger_service.saldos_por_receptor(db_session, [receptor.id])
        saldo_receptor = resultado[receptor.id]
        assert saldo_receptor.saldo_total == Decimal("150.00")
        assert len(saldo_receptor.por_cuenta) == 2
        por_id = {c.cuenta_bancaria_id: c for c in saldo_receptor.por_cuenta}
        assert por_id[cuenta_a.id].es_predeterminada is True
        assert por_id[cuenta_a.id].saldo == Decimal("100.00")
        assert por_id[cuenta_a.id].etiqueta

    @pytest.mark.asyncio
    async def test_receptor_sin_cuentas_devuelve_saldo_cero(self, db_session):
        receptor = _mk_receptor()
        db_session.add(receptor)
        await db_session.flush()

        resultado = await receptor_ledger_service.saldos_por_receptor(db_session, [receptor.id])
        assert resultado[receptor.id].saldo_total == Decimal("0.00")
        assert resultado[receptor.id].por_cuenta == []


# ─── listar_movimientos ─────────────────────────────────────────────────────

class TestListarMovimientos:
    @pytest.mark.asyncio
    async def test_ordenados_por_fecha_descendente_con_paginacion(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        receptor, cuenta = await _preparar_cuenta(db_session)
        for _ in range(3):
            db_session.add(MovimientoReceptor(
                id=uuid.uuid4(), cuenta_bancaria_id=cuenta.id, tipo=TipoMovimiento.correccion,
                monto=Decimal("10.00"), usuario_id=usuario.id,
            ))
        await db_session.flush()

        items, total = await receptor_ledger_service.listar_movimientos(
            db_session, receptor.id, page=1, page_size=2,
        )
        assert total == 3
        assert len(items) == 2
        assert items[0].usuario_nombre == usuario.username

    @pytest.mark.asyncio
    async def test_filtra_por_cuenta_bancaria_id(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        receptor = _mk_receptor()
        cuenta_a = _mk_cuenta(receptor.id, entidad_bancaria="A")
        cuenta_b = _mk_cuenta(receptor.id, entidad_bancaria="B")
        db_session.add_all([receptor, cuenta_a, cuenta_b])
        await db_session.flush()
        db_session.add_all([
            MovimientoReceptor(
                id=uuid.uuid4(), cuenta_bancaria_id=cuenta_a.id, tipo=TipoMovimiento.salida,
                monto=Decimal("10.00"), usuario_id=usuario.id,
            ),
            MovimientoReceptor(
                id=uuid.uuid4(), cuenta_bancaria_id=cuenta_b.id, tipo=TipoMovimiento.salida,
                monto=Decimal("20.00"), usuario_id=usuario.id,
            ),
        ])
        await db_session.flush()

        items, total = await receptor_ledger_service.listar_movimientos(
            db_session, receptor.id, cuenta_bancaria_id=cuenta_a.id, page=1, page_size=50,
        )
        assert total == 1
        assert items[0].cuenta_bancaria_id == cuenta_a.id


# ─── FOR UPDATE — verificado por compilación, no por ejecución ────────────

class TestSelectCuentaForUpdate:
    """El overdraft check bloquea la fila de cuentas_bancarias con
    SELECT ... FOR UPDATE. SQLite (DB de test) ignora FOR UPDATE
    silenciosamente, así que ejecutarlo contra la DB de test daría un falso
    verde — se verifica compilando el statement contra el dialecto de
    Postgres, no ejecutándolo."""

    def test_for_update_presente_en_sql_compilado_postgres(self):
        statement = receptor_ledger_service._select_cuenta_for_update(uuid.uuid4())
        compilado = str(statement.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in compilado.upper()


# ─── registrar_movimiento ───────────────────────────────────────────────────

class TestRegistrarMovimiento:
    @pytest.mark.asyncio
    async def test_salida_dentro_del_saldo_se_persiste(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("500000.00"), Decimal("0.00"))
        await db_session.flush()

        movimiento = await receptor_ledger_service.registrar_movimiento(
            db_session, cuenta.id, TipoMovimiento.salida, Decimal("300000.00"), None, usuario.id,
        )
        assert movimiento.id is not None
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("200000.00")

    @pytest.mark.asyncio
    async def test_salida_excede_saldo_es_rechazada_sin_persistir(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("500000.00"), Decimal("0.00"))
        await db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            await receptor_ledger_service.registrar_movimiento(
                db_session, cuenta.id, TipoMovimiento.salida, Decimal("500001.00"), None, usuario.id,
            )
        assert exc_info.value.status_code == 409

        total = (await db_session.execute(
            select(func.count()).select_from(MovimientoReceptor)
            .where(MovimientoReceptor.cuenta_bancaria_id == cuenta.id)
        )).scalar()
        assert total == 0

    @pytest.mark.asyncio
    async def test_salida_exactamente_igual_al_saldo_se_acepta(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await _agregar_pago(db_session, cuenta.id, Decimal("500000.00"), Decimal("0.00"))
        await db_session.flush()

        await receptor_ledger_service.registrar_movimiento(
            db_session, cuenta.id, TipoMovimiento.salida, Decimal("500000.00"), None, usuario.id,
        )
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_correccion_negativa_salta_el_chequeo_de_sobregiro(self, db_session):
        """Decision 4 del design: las correcciones no tienen chequeo de
        sobregiro, aunque dejen el saldo en negativo."""
        usuario = _mk_usuario()
        db_session.add(usuario)
        _, cuenta = await _preparar_cuenta(db_session)
        await db_session.flush()

        movimiento = await receptor_ledger_service.registrar_movimiento(
            db_session, cuenta.id, TipoMovimiento.correccion, Decimal("-100.00"), "ajuste", usuario.id,
        )
        assert movimiento.monto == Decimal("-100.00")
        assert movimiento.nota == "ajuste"
        resultado = await receptor_ledger_service.saldos_por_cuenta(db_session, [cuenta.id])
        assert resultado[cuenta.id].saldo == Decimal("-100.00")

    @pytest.mark.asyncio
    async def test_cuenta_inexistente_devuelve_404(self, db_session):
        usuario = _mk_usuario()
        db_session.add(usuario)
        await db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            await receptor_ledger_service.registrar_movimiento(
                db_session, uuid.uuid4(), TipoMovimiento.salida, Decimal("10.00"), None, usuario.id,
            )
        assert exc_info.value.status_code == 404
