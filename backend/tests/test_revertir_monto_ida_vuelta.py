"""
tests/test_revertir_monto_ida_vuelta.py — round trips and cascades of POST /pagos/{id}/revertir-monto (PR2b-ii).

The "before" state comes from the REAL forward services on SQLite; the revert runs through httpx/ASGI on a session like
production (autoflush=False; get_db flushes like the real commit). SQLite ignores FOR UPDATE: only sequential calls are
proven, not true concurrency. Roles, guards, audit: test_revertir_monto.py. Service: test_revertir_monto_servicio.py.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import DestinoExcedente, Pago
from app.models.pago_reparto import PagoReparto
from app.models.receptor import CuentaBancaria, Receptor, TipoCuenta
from app.models.receptor_movimiento import MovimientoReceptor, TipoMovimiento
from app.models.usuario import TipoUsuario, Usuario
from app.schemas.pago import RegistrarPagoRequest
from app.services.credito_service import (
    cerrar_credito_con_interes_pendiente, credito_operativamente_abierto, crear_primera_cuota,
)
from app.services.pago_service import PagoService
from app.services.receptor_ledger_service import saldos_por_cuenta

FECHA = date(2026, 3, 1)  # fecha_pago_real of every forward registration
CAPITAL, INTERESES = DestinoExcedente.capital, DestinoExcedente.intereses
ABONO_CAPITAL = {"tipo": TipoCredito.abono_capital, "abono_minimo": Decimal("50000.00")}
DOS_CUOTAS = {"capital": "100000.00", "cuotas": 2}  # 50000 + 3000 per cuota


@pytest_asyncio.fixture
async def db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Session like production (autoflush=False, see app.database.AsyncSessionLocal)."""
    maker = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def como(db):
    """como(rol) -> (client, user): the same ASGI client acting as a new user of that role. The LAST call wins the
    dependency overrides, so call it right before each request."""
    async def override_db():
        yield db
        await db.flush()  # what the real get_db commit does: the changes must be persistable

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        def _como(rol: TipoUsuario) -> tuple[AsyncClient, MagicMock]:
            user = MagicMock(spec=Usuario)
            user.id, user.tipo_usuario = uuid.uuid4(), rol
            app.dependency_overrides[get_current_user] = lambda: user
            return client, user

        yield _como
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


async def _credito(
    db, tipo=TipoCredito.cuota_fija, capital="1000000.00", cuotas=10, abono_minimo=None, quincenal=False,
) -> tuple[Credito, Pago]:
    """3% credit (monthly, or fortnightly: two cuotas a month) plus its first cuota, validated and assigned to a bank
    account. Cliente / cuenta rows are not created: SQLite does not enforce those FKs."""
    fija, capital, por_mes = tipo == TipoCredito.cuota_fija, Decimal(capital), 2 if quincenal else 1
    intereses = (capital * Decimal("0.03") * cuotas / por_mes).quantize(Decimal("0.01")) if fija else Decimal("0.00")
    credito = Credito(
        id=uuid.uuid4(), cliente_id=uuid.uuid4(), numero_credito_cliente=f"RM-{uuid.uuid4().hex[:10]}",
        tipo_credito=tipo, capital_prestado=capital, tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1), fecha_inicial_pago=date(2026, 2, 1), saldo_capital=capital,
        periodicidad=Periodicidad.quincenal if quincenal else Periodicidad.mensual, saldo_intereses=intereses,
        abono_minimo=abono_minimo, numero_cuotas=cuotas if fija else None, activo=True,
    )
    primera = await crear_primera_cuota(credito, uuid.uuid4())
    primera.validado_recaudador, primera.tipo_validacion = True, "completo"
    db.add_all([credito, primera])
    await db.flush()
    return credito, primera


async def _registrar(db, credito, pago, capital, interes, destino=None) -> None:
    """Forward registration through the real services (exact / partial, or excedente), flushed like a commit."""
    montos = RegistrarPagoRequest(capital_pagado=Decimal(capital), interes_pagado=Decimal(interes))
    if destino:
        await PagoService.confirmar_excedente(db, pago, credito, montos, destino, FECHA)
    else:
        await PagoService.registrar_pago(db, pago, credito, montos, FECHA)
    await db.flush()


async def _pendientes(db, credito) -> list[Pago]:
    """Unpaid, not-deleted cuotas of the credit, in order."""
    filtro = (Pago.credito_id == credito.id, Pago.pagado.is_(False), Pago.deleted_at.is_(None))
    return list(await db.scalars(select(Pago).where(*filtro).order_by(Pago.numero_cuota, Pago.id)))


async def _repartos_borrados(db, pago_id) -> list[bool]:
    """One flag per reparto row of the pago (True = soft-deleted), read straight from the DB, False first."""
    filas = await db.scalars(select(PagoReparto.deleted_at).where(PagoReparto.pago_id == pago_id))
    return sorted(borrado is not None for borrado in filas)


async def _saldo(db, cuenta_id) -> Decimal:
    """Cash balance of a bank account, as the receptor ledger computes it on read."""
    return (await saldos_por_cuenta(db, [cuenta_id]))[cuenta_id].saldo


def _columnas(fila) -> dict:
    return {c.name: getattr(fila, c.name) for c in fila.__table__.columns if c.name != "updated_at"}


async def _foto(db, credito) -> tuple:
    """What a round trip must restore, read back from the DB: credit columns, live cuotas and active repartos by id
    (those of soft-deleted pagos included: they must not stay active)."""
    await db.flush()
    await db.refresh(credito)
    del_credito = select(Pago.id).where(Pago.credito_id == credito.id)
    pagos = select(Pago).where(Pago.id.in_(del_credito), Pago.deleted_at.is_(None))
    repartos = select(PagoReparto).where(PagoReparto.pago_id.in_(del_credito), PagoReparto.deleted_at.is_(None))
    return (
        _columnas(credito),
        {p.id: _columnas(p) for p in await db.scalars(pagos.execution_options(populate_existing=True))},
        {r.id: _columnas(r) for r in await db.scalars(repartos.execution_options(populate_existing=True))},
    )


def _url(pago: Pago) -> str:
    return f"/api/v1/pagos/{pago.id}/revertir-monto"


async def _registrar_de_nuevo(client, pago, interes="30000.00"):
    """Register the restored cuota (100000 + interes) again, through the endpoint."""
    cuerpo = {"capital_pagado": "100000.00", "interes_pagado": interes}
    return await client.post(f"/api/v1/pagos/{pago.id}/registrar", json=cuerpo)


@pytest_asyncio.fixture
async def registrado(db) -> tuple[Credito, Pago, Pago]:
    """cuota #1 (100000 + 30000) paid exactly -> balances 900000 / 270000; returns (credito, #1, #2 it generated)."""
    credito, pago = await _credito(db)
    await _registrar(db, credito, pago, "100000.00", "30000.00")
    return credito, pago, (await _pendientes(db, credito))[0]


def _op_cuota(capital=None, interes=None, destino=None, cierre=False):
    """Operation: register the first pending cuota (exact unless amounts are given; destino: excedente;
    cierre: regla 14 explicit closure right after a partial payment)."""
    async def operacion(db, credito) -> Pago:
        pago = (await _pendientes(db, credito))[0]
        await _registrar(db, credito, pago, capital or pago.capital_a_pagar, interes or pago.interes_a_pagar, destino)
        if cierre:
            cerrar_credito_con_interes_pendiente(credito)
            await db.flush()
        return pago
    return operacion


def _op_no_programada(monto, destino):
    """Operation: register a no_programada payment (numero_cuota = max + 1, no successor)."""
    async def operacion(db, credito) -> Pago:
        pago = await PagoService.registrar_pago_no_programado(db, credito, Decimal(monto), destino, FECHA, uuid.uuid4())
        await db.flush()
        return pago
    return operacion


EXACTA = _op_cuota()
ESCENARIOS = [
    pytest.param({}, [EXACTA, _op_cuota("80000.00", "20000.00"), EXACTA], id="cuota_fija-parcial-con-arrastre"),
    pytest.param({}, [EXACTA, _op_no_programada("200000.00", CAPITAL), EXACTA], id="no_programada-a-capital"),
    pytest.param({}, [EXACTA, _op_no_programada("40000.00", INTERESES), EXACTA], id="no_programada-a-intereses"),
    pytest.param(
        {}, [_op_cuota("100000.00", "50000.00", CAPITAL), _op_cuota("120000.00", "30000.00", INTERESES), EXACTA],
        id="excedente-a-capital-y-a-intereses",
    ),
    pytest.param(
        DOS_CUOTAS, [EXACTA, _op_cuota("60000.00", "3000.00", CAPITAL)], id="excedente-con-piso-en-cero-que-salda",
    ),
    pytest.param({"capital": "100000.00", "cuotas": 1}, [EXACTA], id="saldado-en-una-cuota"),
    pytest.param(  # fortnightly (50000 + 1500 per cuota): the interest replayed on reopening divides by 2 a month
        {**DOS_CUOTAS, "quincenal": True}, [EXACTA, _op_cuota("50000.00", "0.00", cierre=True)],
        id="regla-14-cierre-con-interes-pendiente-quincenal",
    ),
    pytest.param(
        ABONO_CAPITAL, [EXACTA, _op_no_programada("200000.00", CAPITAL), EXACTA, _op_cuota("50000.00", "10000.00")],
        id="abono_capital-mensual",
    ),
    pytest.param(
        ABONO_CAPITAL, [_op_no_programada("100000.00", INTERESES), _op_cuota("50000.00", "40000.00", CAPITAL), EXACTA],
        id="abono_capital-excedente-tras-no_programada",
    ),
    pytest.param(
        ABONO_CAPITAL, [EXACTA, _op_no_programada("950000.00", CAPITAL)], id="abono_capital-no_programada-que-salda",
    ),
]


@pytest.mark.asyncio
class TestIdaYVuelta:
    @pytest.mark.parametrize("credito_kwargs, operaciones", ESCENARIOS)
    async def test_cada_reversion_lifo_restaura_el_estado_previo_a_su_operacion(
        self, db, como, credito_kwargs, operaciones,
    ):
        credito, _ = await _credito(db, **credito_kwargs)
        client, _ = como(TipoUsuario.registrador)
        for _ in range(2):  # the second round registers again, and reverts again, what the first one reverted
            fotos, registrados = [await _foto(db, credito)], []
            for operacion in operaciones:
                registrados.append(await operacion(db, credito))
                fotos.append(await _foto(db, credito))
            assert all(antes != despues for antes, despues in zip(fotos, fotos[1:]))  # each operation changed something

            for pago, antes in zip(reversed(registrados), reversed(fotos[:-1])):
                r = await client.post(_url(pago))

                assert r.status_code == 200, r.text
                assert await _foto(db, credito) == antes

    async def test_el_credito_saldado_reabierto_vuelve_a_ser_operativo_y_admite_el_pago(self, db, como):
        credito, pago = await _credito(db, capital="100000.00", cuotas=1)
        await _registrar(db, credito, pago, "100000.00", "3000.00")
        abiertos = select(Credito.id).where(Credito.id == credito.id, credito_operativamente_abierto())
        assert (credito.activo, list(await db.scalars(abiertos))) == (False, [])
        client, _ = como(TipoUsuario.admin)

        assert (await client.post(_url(pago))).status_code == 200

        assert (credito.activo, list(await db.scalars(abiertos))) == (True, [credito.id])
        assert [(p.id, p.validado_recaudador) for p in await _pendientes(db, credito)] == [(pago.id, True)]
        r = await _registrar_de_nuevo(client, pago, interes="3000.00")  # not "El crédito está cerrado"
        assert (r.status_code, credito.activo, credito.saldo_capital) == (200, False, Decimal("0.00")), r.text


@pytest.mark.asyncio
class TestRepartosYSaldoDelReceptor:
    async def test_revertir_borra_los_repartos_y_registrar_de_nuevo_crea_uno_solo(self, db, como, registrado):
        credito, pago, sucesora = registrado
        cuenta = pago.cuenta_bancaria_id
        assert (await _repartos_borrados(db, pago.id), await _saldo(db, cuenta)) == ([False], Decimal("130000.00"))
        client, _ = como(TipoUsuario.admin)

        assert (await client.post(_url(pago))).status_code == 200
        assert (await _repartos_borrados(db, pago.id), await _saldo(db, cuenta)) == ([True], Decimal("0.00"))

        r = await _registrar_de_nuevo(client, pago)

        assert r.status_code == 200, r.text
        assert await _repartos_borrados(db, pago.id) == [False, True]  # exactly one active default reparto again
        assert await _saldo(db, cuenta) == Decimal("130000.00")
        assert (credito.saldo_capital, credito.saldo_intereses) == (Decimal("900000.00"), Decimal("270000.00"))
        generada = await _pendientes(db, credito)
        assert [(p.numero_cuota, p.id != sucesora.id) for p in generada] == [(2, True)]  # a fresh cuota #2

    async def test_el_saldo_baja_lo_que_aportaba_el_pago_y_puede_quedar_negativo(self, db, como, registrado):
        _, pago, _ = registrado
        cuenta = pago.cuenta_bancaria_id
        db.add(MovimientoReceptor(
            cuenta_bancaria_id=cuenta, tipo=TipoMovimiento.salida, monto=Decimal("100000.00"), usuario_id=uuid.uuid4(),
        ))
        await db.flush()
        assert await _saldo(db, cuenta) == Decimal("30000.00")  # 130000 collected, 100000 already handed over
        client, _ = como(TipoUsuario.admin)

        r = await client.post(_url(pago))

        assert r.status_code == 200, r.text
        assert await _saldo(db, cuenta) == Decimal("-100000.00")  # the 130000 are gone and the revert is not blocked


@pytest.mark.asyncio
class TestDesvalidarTrasRevertir:
    @pytest.mark.parametrize("rol", [TipoUsuario.admin, TipoUsuario.recaudador], ids=lambda r: r.value)
    async def test_se_rechaza_mientras_esta_pagada_y_funciona_tras_revertir(self, db, como, registrado, rol):
        _, pago, _ = registrado
        desvalidar = f"/api/v1/pagos/{pago.id}/desvalidar"
        client, _ = como(rol)
        r = await client.post(desvalidar)
        esperado = "No se puede revertir: el pago ya fue registrado con montos."
        assert (r.status_code, r.json().get("detail")) == (422, esperado)

        client, _ = como(TipoUsuario.registrador)
        assert (await client.post(_url(pago))).status_code == 200
        client, _ = como(rol)
        r = await client.post(desvalidar)

        assert (r.status_code, r.json().get("validado_recaudador")) == (200, False)


@pytest_asyncio.fixture
async def dividida(db, como):
    """cuota #1 (100000 + 30000, account x) split 70000 x / 60000 y by an admin, then reverted.
    Returns (admin client, #1, x, y). The split clears the account of #1 (aplicar_herencia)."""
    receptor = Receptor(id=uuid.uuid4(), nombre="Receptor", cedula=uuid.uuid4().hex[:12], telefono="3000000000")
    x, y = (
        CuentaBancaria(
            id=uuid.uuid4(), receptor_id=receptor.id, entidad_bancaria="Banco", tipo_cuenta=TipoCuenta.ahorros,
            numero_cuenta=str(i),
        ) for i in (1, 2)
    )
    db.add_all([receptor, x, y])
    credito, pago = await _credito(db)
    pago.cuenta_bancaria_id = x.id
    await _registrar(db, credito, pago, "100000.00", "30000.00")
    admin, _ = como(TipoUsuario.admin)
    reparto = {"repartos": [
        {"tipo_destinatario": "cuenta_bancaria", "cuenta_bancaria_id": str(cuenta.id), "monto": monto}
        for cuenta, monto in ((x, "70000.00"), (y, "60000.00"))
    ]}
    assert (await admin.put(f"/api/v1/pagos/{pago.id}/repartos", json=reparto)).status_code == 200
    assert (await admin.post(_url(pago))).status_code == 200
    return admin, pago, x, y


@pytest.mark.asyncio
class TestDivisionEntreVariasCuentas:
    """Decision of PR2b: with 2+ accounts there is no single account to restore, and guessing one would misattribute
    receptor cash. The reverted cuota stays without account (no default reparto on re-registration) until the bank
    account update assigns one, before or after registering again."""

    async def test_revertir_deja_la_cuota_sin_cuenta_y_el_reparto_nace_al_asignarla(self, db, dividida):
        admin, pago, x, y = dividida
        await db.refresh(pago)
        assert pago.cuenta_bancaria_id is None
        assert await _repartos_borrados(db, pago.id) == [True, True, True]  # default (replaced by the split) + x + y

        r = await _registrar_de_nuevo(admin, pago)

        assert r.status_code == 200, r.text
        assert await _repartos_borrados(db, pago.id) == [True, True, True]  # no default reparto: money unattributed
        assert [await _saldo(db, c.id) for c in (x, y)] == [Decimal("0.00"), Decimal("0.00")]

        r = await admin.patch(f"/api/v1/pagos/{pago.id}/cuenta-bancaria", json={"cuenta_bancaria_id": str(x.id)})

        assert r.status_code == 200, r.text
        assert await _repartos_borrados(db, pago.id) == [False, True, True, True]
        assert [await _saldo(db, c.id) for c in (x, y)] == [Decimal("130000.00"), Decimal("0.00")]

    async def test_asignar_otra_cuenta_antes_de_registrar_de_nuevo_crea_el_reparto_al_registrar(self, db, dividida):
        admin, pago, x, y = dividida

        r = await admin.patch(f"/api/v1/pagos/{pago.id}/cuenta-bancaria", json={"cuenta_bancaria_id": str(y.id)})
        assert r.status_code == 200, r.text
        assert await _repartos_borrados(db, pago.id) == [True, True, True]  # still unpaid: nothing to attribute yet

        r = await _registrar_de_nuevo(admin, pago)

        assert r.status_code == 200, r.text
        assert await _repartos_borrados(db, pago.id) == [False, True, True, True]
        assert [await _saldo(db, c.id) for c in (x, y)] == [Decimal("0.00"), Decimal("130000.00")]


@pytest.mark.asyncio
class TestMotivo:
    async def test_un_motivo_de_500_caracteres_se_acepta_y_el_de_501_se_rechaza(self, db, como, registrado):
        _, pago, _ = registrado
        client, _ = como(TipoUsuario.admin)

        r = await client.post(_url(pago), json={"motivo": "x" * 501})

        detail = r.json().get("detail")
        assert r.status_code == 422
        assert isinstance(detail, list) and detail[0]["loc"][-1] == "motivo"  # FastAPI's validation list, not a string

        r = await client.post(_url(pago), json={"motivo": "x" * 500})

        assert r.status_code == 200, r.text
        motivos = select(AuditLog.valor_nuevo).where(
            AuditLog.entidad_id == pago.id, AuditLog.campo_modificado == "motivo_reversion",
        )
        assert list(await db.scalars(motivos)) == ["x" * 500]


@pytest.mark.asyncio
class TestPagoNoProgramadoRevertido:
    async def test_una_segunda_llamada_se_rechaza_sin_tocar_nada(self, db, como, registrado):
        credito, _, _ = registrado
        pago = await _op_no_programada("50000.00", CAPITAL)(db, credito)
        client, _ = como(TipoUsuario.admin)
        assert (await client.post(_url(pago))).status_code == 200
        revertido = await _foto(db, credito)

        r = await client.post(_url(pago))  # the soft-deleted row is gone for the endpoint: 404, never a silent success

        assert r.status_code == 404
        assert await _foto(db, credito) == revertido
