"""
tests/test_pagos_listado.py — Listado de pagos optimizado.

Cubre:
- _pago_row_a_dict: mapea cada columna al campo correcto de PagoResponse,
  sin perder ni alterar datos (la optimización debe preservar la salida).
- Smoke de integración: la query de solo-columnas compila y ejecuta vía HTTP.
- Ordenamiento por fecha_maxima con parámetro sort_dir (asc/desc) y tiebreaker.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models.cliente import Cliente
from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import DestinoExcedente, Pago, TipoCuota
from app.models.usuario import TipoUsuario, Usuario
from app.routers.pagos import _pago_row_a_dict
from app.schemas.pago import PagoResponse

# ──────────────────────────────────────────────────────────────────────────────
# Helpers para construir objetos de dominio en tests de sort
# ──────────────────────────────────────────────────────────────────────────────

_FAKE_GESTOR_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _mk_cliente(nombre: str, apellidos: str, cedula: str) -> Cliente:
    return Cliente(
        id=uuid.uuid4(),
        gestor_id=_FAKE_GESTOR_ID,
        nombre=nombre,
        apellidos=apellidos,
        cedula=cedula,
        telefono="3000000000",
        direccion="Calle test",
        al_dia=True,
    )


def _mk_credito(
    cliente_id: uuid.UUID,
    numero_credito: str,
    periodicidad: Periodicidad = Periodicidad.mensual,
    activo: bool = False,
    fecha_inicial_pago: date = date(2026, 2, 1),
) -> Credito:
    # activo=False evita que _calcular_virtuales proyecte cuotas extras en los
    # tests de sort, manteniendo el recuento de items predecible.
    # Pasar activo=True + fecha_inicial_pago en fixtures que necesitan virtuales.
    return Credito(
        id=uuid.uuid4(),
        cliente_id=cliente_id,
        numero_credito_cliente=numero_credito,
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=fecha_inicial_pago,
        periodicidad=periodicidad,
        saldo_capital=Decimal("1000000.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=12,
        calcular_interes_dias_corridos=False,
        activo=activo,
    )


def _mk_pago(credito_id: uuid.UUID, fecha_maxima: date, pago_id: uuid.UUID | None = None) -> Pago:
    return Pago(
        id=pago_id if pago_id is not None else uuid.uuid4(),
        credito_id=credito_id,
        numero_cuota=1,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=Decimal("100000.00"),
        capital_a_pagar=Decimal("70000.00"),
        interes_a_pagar=Decimal("30000.00"),
        capital_pagado=Decimal("0.00"),
        interes_pagado=Decimal("0.00"),
        momento="m2",
        fecha_maxima=fecha_maxima,
        pagado=False,
        validado_recaudador=False,
        es_ultimo_pago=False,
    )


def _fake_row(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        credito_id=uuid.uuid4(),
        numero_cuota=3,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=Decimal("100462.13"),
        capital_a_pagar=Decimal("70462.13"),
        interes_a_pagar=Decimal("30000.00"),
        capital_pagado=Decimal("0.00"),
        interes_pagado=Decimal("0.00"),
        momento="m3",
        fecha_maxima=date(2026, 3, 10),
        receptor_id=None,
        pagado=False,
        validado_recaudador=False,
        fecha_pago_real=None,
        es_excedente_a=None,
        es_ultimo_pago=False,
        tipo_validacion=None,
        cliente_nombre="Juan",
        cliente_apellidos="Pérez",
        numero_credito_cliente="Juan Pérez-CR-001",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPagoRowADict:
    def test_dict_cubre_todos_los_campos_de_response(self):
        """El dict debe traer todos los campos que PagoResponse necesita."""
        d = _pago_row_a_dict(_fake_row())
        requeridos = set(PagoResponse.model_fields.keys())
        faltantes = requeridos - set(d.keys())
        assert not faltantes, f"Faltan campos en el dict: {faltantes}"

    def test_round_trip_preserva_valores(self):
        """El dict valida como PagoResponse sin alterar datos."""
        row = _fake_row()
        resp = PagoResponse.model_validate(_pago_row_a_dict(row))
        assert resp.id == row.id
        assert resp.credito_id == row.credito_id
        assert resp.numero_cuota == 3
        assert resp.tipo_cuota == TipoCuota.programada
        assert resp.monto_a_pagar == Decimal("100462.13")
        assert resp.cliente_nombre == "Juan Pérez"
        assert resp.numero_credito_cliente == "Juan Pérez-CR-001"
        assert resp.es_proyectada is False
        assert resp.razon_bloqueo is None

    def test_excedente_y_receptor_se_mapean(self):
        receptor = uuid.uuid4()
        row = _fake_row(
            es_excedente_a=DestinoExcedente.capital,
            receptor_id=receptor,
            pagado=True,
        )
        resp = PagoResponse.model_validate(_pago_row_a_dict(row))
        assert resp.es_excedente_a == DestinoExcedente.capital
        assert resp.receptor_id == receptor
        assert resp.pagado is True


@pytest_asyncio.fixture
async def client_admin_db(db_session):
    """Cliente HTTP como admin, con get_db apuntando a la sesión de test."""
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


class TestListarPagosIntegracion:
    @pytest.mark.asyncio
    async def test_listado_db_vacia_responde_200_vacio(self, client_admin_db: AsyncClient):
        """La query de solo-columnas compila y ejecuta; sin datos devuelve vacío."""
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures de datos para tests de ordenamiento
# ──────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def datos_tres_fechas(db_session):
    """
    Inserta 3 pagos con fechas DISTINTAS donde el orden alfabético de clientes
    NO coincide con el orden cronológico. Esto garantiza RED contra el sort actual
    (por nombre de cliente).

    "Carlos Medina"  → 2026-03-10  (2do alfabético, 1ro cronológico)
    "Ana García"     → 2026-03-15  (1ro alfabético, 2do cronológico)
    "Zeta Pérez"     → 2026-03-20  (3ro alfabético, 3ro cronológico)

    Sort actual por nombre: [Ana(03-15), Carlos(03-10), Zeta(03-20)]
    Sort esperado ASC:       [Carlos(03-10), Ana(03-15), Zeta(03-20)]
    Sort esperado DESC:      [Zeta(03-20), Ana(03-15), Carlos(03-10)]
    """
    c1 = _mk_cliente("Carlos", "Medina", "100011")
    c2 = _mk_cliente("Ana", "García", "200022")
    c3 = _mk_cliente("Zeta", "Pérez", "300033")
    db_session.add_all([c1, c2, c3])
    await db_session.flush()

    cr1 = _mk_credito(c1.id, f"Carlos Medina-CR-001-{c1.id.hex[:6]}")
    cr2 = _mk_credito(c2.id, f"Ana García-CR-001-{c2.id.hex[:6]}")
    cr3 = _mk_credito(c3.id, f"Zeta Pérez-CR-001-{c3.id.hex[:6]}")
    db_session.add_all([cr1, cr2, cr3])
    await db_session.flush()

    p1 = _mk_pago(cr1.id, date(2026, 3, 10))   # Carlos, fecha más temprana
    p2 = _mk_pago(cr2.id, date(2026, 3, 15))   # Ana, fecha media
    p3 = _mk_pago(cr3.id, date(2026, 3, 20))   # Zeta, fecha más tardía
    db_session.add_all([p1, p2, p3])
    await db_session.flush()

    return {"p_temprano": p1, "p_medio": p2, "p_tardio": p3}


@pytest_asyncio.fixture
async def datos_misma_fecha_nombres_distintos(db_session):
    """
    Inserta 2 pagos con la misma fecha y nombres de cliente distintos.
    Ana García   → fecha_maxima = 2026-03-15  (nombre alphabetically first)
    Beto López   → fecha_maxima = 2026-03-15
    """
    c1 = _mk_cliente("Ana", "García", "400044")
    c2 = _mk_cliente("Beto", "López", "500055")
    db_session.add_all([c1, c2])
    await db_session.flush()

    cr1 = _mk_credito(c1.id, f"Ana García-CR-002-{c1.id.hex[:6]}")
    cr2 = _mk_credito(c2.id, f"Beto López-CR-002-{c2.id.hex[:6]}")
    db_session.add_all([cr1, cr2])
    await db_session.flush()

    p1 = _mk_pago(cr1.id, date(2026, 3, 15))
    p2 = _mk_pago(cr2.id, date(2026, 3, 15))
    db_session.add_all([p1, p2])
    await db_session.flush()

    return {"p_ana": p1, "p_beto": p2}


@pytest_asyncio.fixture
async def datos_misma_fecha_mismo_cliente(db_session):
    """
    Inserta 2 pagos del mismo cliente (mismo nombre) con la misma fecha.
    Para forzar RED contra el sort actual (que usa numero_cuota como tiebreaker):
    - El pago con el id str-MENOR recibe numero_cuota=2
    - El pago con el id str-MAYOR recibe numero_cuota=1
    Así el sort actual (por nc) pone el de mayor id primero, y el test falla.
    Con el nuevo sort (por str(id)) el de menor id va primero y el test pasa.
    """
    c1 = _mk_cliente("Darío", "Ruiz", "600066")
    db_session.add(c1)
    await db_session.flush()

    cr1 = _mk_credito(c1.id, f"Darío Ruiz-CR-001-{c1.id.hex[:6]}")
    cr2 = _mk_credito(c1.id, f"Darío Ruiz-CR-002-{c1.id.hex[:6]}")
    db_session.add_all([cr1, cr2])
    await db_session.flush()

    pa = _mk_pago(cr1.id, date(2026, 3, 15))
    pb = _mk_pago(cr2.id, date(2026, 3, 15))

    # Assign numero_cuota so that str(id) order ≠ nc order
    if str(pa.id) < str(pb.id):
        # pa is menor → give it nc=2 so current sort puts it AFTER pb
        pa.numero_cuota = 2
        pb.numero_cuota = 1
    else:
        # pb is menor → give it nc=2 so current sort puts it AFTER pa
        pa.numero_cuota = 1
        pb.numero_cuota = 2

    db_session.add_all([pa, pb])
    await db_session.flush()

    return {"pa": pa, "pb": pb}


# ──────────────────────────────────────────────────────────────────────────────
# Tests de ordenamiento — Fase 1 RED (TDD)
# ──────────────────────────────────────────────────────────────────────────────

class TestOrdenPagosSort:
    """Tests de sort_dir para el endpoint GET /pagos."""

    # 1.1 — Sin sort_dir, orden ASC por fecha_maxima (default)
    @pytest.mark.asyncio
    async def test_sin_sort_dir_orden_asc_por_fecha(
        self, client_admin_db: AsyncClient, datos_tres_fechas
    ):
        """Ausencia de sort_dir → rows ordenadas por fecha_maxima ASC.
        RED: sort actual por nombre da [Ana(03-15), Carlos(03-10), Zeta(03-20)] ≠ ASC cronológico.
        """
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 3
        fechas = [i["fecha_maxima"] for i in items]
        assert fechas == ["2026-03-10", "2026-03-15", "2026-03-20"]

    # 1.2 — sort_dir=asc explícito
    @pytest.mark.asyncio
    async def test_sort_dir_asc_orden_fecha_asc(
        self, client_admin_db: AsyncClient, datos_tres_fechas
    ):
        """sort_dir=asc → rows ordenadas por fecha_maxima ASC."""
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3&sort_dir=asc")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 3
        fechas = [i["fecha_maxima"] for i in items]
        assert fechas == ["2026-03-10", "2026-03-15", "2026-03-20"]

    # 1.3 — sort_dir=desc
    @pytest.mark.asyncio
    async def test_sort_dir_desc_orden_fecha_desc(
        self, client_admin_db: AsyncClient, datos_tres_fechas
    ):
        """sort_dir=desc → rows ordenadas por fecha_maxima DESC.
        RED: sort actual ignora sort_dir, da [Ana(03-15), Carlos(03-10), Zeta(03-20)] ≠ DESC.
        """
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3&sort_dir=desc")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 3
        fechas = [i["fecha_maxima"] for i in items]
        assert fechas == ["2026-03-20", "2026-03-15", "2026-03-10"]

    # 1.4 — Tiebreaker: misma fecha, nombres distintos → orden alfabético
    @pytest.mark.asyncio
    async def test_tiebreaker_misma_fecha_orden_alfabetico(
        self, client_admin_db: AsyncClient, datos_misma_fecha_nombres_distintos
    ):
        """Misma fecha_maxima, distintos clientes → orden alfabético por nombre."""
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 2
        nombres = [i["cliente_nombre"] for i in items]
        assert nombres[0].lower() < nombres[1].lower()  # Ana < Beto

    # 1.5 — Tiebreaker permanece ASC bajo sort_dir=desc
    @pytest.mark.asyncio
    async def test_tiebreaker_sigue_asc_bajo_desc(
        self, client_admin_db: AsyncClient, datos_misma_fecha_nombres_distintos
    ):
        """Misma fecha con sort_dir=desc → tiebreaker por nombre sigue siendo ASC."""
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3&sort_dir=desc")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 2
        nombres = [i["cliente_nombre"] for i in items]
        assert nombres[0].lower() < nombres[1].lower()  # Ana < Beto incluso en desc

    # 1.6 — Tiebreaker: misma fecha, mismo cliente → menor id primero
    @pytest.mark.asyncio
    async def test_tiebreaker_misma_fecha_mismo_cliente_menor_id_primero(
        self, client_admin_db: AsyncClient, datos_misma_fecha_mismo_cliente
    ):
        """Misma fecha y mismo nombre de cliente → el de menor str(id) aparece primero.
        RED: fixture asigna nc=2 al pago de menor id, nc=1 al de mayor id.
        Sort actual usa nc como tiebreaker → pone mayor-id primero → test FALLA.
        Sort nuevo usa str(id) → pone menor-id primero → test PASA.
        """
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 2
        assert items[0]["id"] < items[1]["id"]  # menor str(id) primero

    # 1.7 — sort_dir inválido → HTTP 400
    @pytest.mark.asyncio
    async def test_sort_dir_invalido_retorna_400(self, client_admin_db: AsyncClient):
        """sort_dir=random → HTTP 400 con mensaje de error claro."""
        r = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3&sort_dir=random")
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "sort_dir inválido. Use asc o desc"

    # 1.8 — Consistencia paginada: última fila página N ≤ primera fila página N+1
    @pytest.mark.asyncio
    async def test_orden_consistente_entre_paginas(
        self, client_admin_db: AsyncClient, datos_tres_fechas
    ):
        """Con page_size=1, la fecha de página 1 ≤ la de página 2 bajo sort_dir=asc.
        RED: sort actual por nombre da page1=[Ana(03-15)], page2=[Carlos(03-10)];
        "2026-03-15" <= "2026-03-10" es falso → test FALLA.
        """
        r1 = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3&sort_dir=asc&page=1&page_size=1")
        r2 = await client_admin_db.get("/api/v1/pagos?anio=2026&mes=3&sort_dir=asc&page=2&page_size=1")
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        fecha_p1 = r1.json()["items"][0]["fecha_maxima"]
        fecha_p2 = r2.json()["items"][0]["fecha_maxima"]
        assert fecha_p1 <= fecha_p2


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures y tests de filtro por periodicidad — TDD (daily-payments-button)
# ──────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def datos_periodicidades_mixtas(db_session):
    """
    Inserta 3 clientes/créditos con periodicidades distintas (diario, semanal,
    mensual) y un pago en el mes 3 de 2026 para cada uno.
    activo=False suprime la proyección de virtuales.
    """
    c_diario = _mk_cliente("Test", "Diario", "900001")
    c_semanal = _mk_cliente("Test", "Semanal", "900002")
    c_mensual = _mk_cliente("Test", "Mensual", "900003")
    db_session.add_all([c_diario, c_semanal, c_mensual])
    await db_session.flush()

    cr_diario = _mk_credito(c_diario.id, f"CR-DIA-{c_diario.id.hex[:6]}", Periodicidad.diario)
    cr_semanal = _mk_credito(c_semanal.id, f"CR-SEM-{c_semanal.id.hex[:6]}", Periodicidad.semanal)
    cr_mensual = _mk_credito(c_mensual.id, f"CR-MEN-{c_mensual.id.hex[:6]}", Periodicidad.mensual)
    db_session.add_all([cr_diario, cr_semanal, cr_mensual])
    await db_session.flush()

    p_diario = _mk_pago(cr_diario.id, date(2026, 3, 15))
    p_semanal = _mk_pago(cr_semanal.id, date(2026, 3, 15))
    p_mensual = _mk_pago(cr_mensual.id, date(2026, 3, 15))
    db_session.add_all([p_diario, p_semanal, p_mensual])
    await db_session.flush()

    return {
        "cr_diario": cr_diario,
        "cr_semanal": cr_semanal,
        "cr_mensual": cr_mensual,
        "p_diario": p_diario,
        "p_semanal": p_semanal,
        "p_mensual": p_mensual,
    }


@pytest_asyncio.fixture
async def datos_virtuales_excluir_periodicidad(db_session):
    """
    Dos créditos ACTIVOS para verificar que excluir_periodicidades también suprime
    filas virtuales (proyecciones de _calcular_virtuales):

    cr_diario  — periodicidad=diario, activo=True, fecha_inicial_pago=2026-03-10
                 Cuota #1 real (unpaid) en 2026-03-10 → bloqueador presente →
                 _calcular_virtuales proyectaría cuota #2 en 2026-03-11 (dentro de marzo).
                 Con excluir semanal+diario este crédito debe desaparecer por completo.

    cr_control — periodicidad=mensual, activo=True, fecha_inicial_pago=2026-03-01
                 Cuota #1 real (unpaid) en 2026-03-01 → bloqueador presente →
                 virtual cuota #2 cae en 2026-03-31 (dentro de marzo, fallback +30d).
                 NO excluido por la query regular → debe aparecer.
    """
    c_diario = _mk_cliente("Virt", "Diario", "910001")
    c_control = _mk_cliente("Virt", "Control", "910002")
    db_session.add_all([c_diario, c_control])
    await db_session.flush()

    cr_diario = _mk_credito(
        c_diario.id,
        f"CR-VD-{c_diario.id.hex[:6]}",
        periodicidad=Periodicidad.diario,
        activo=True,
        fecha_inicial_pago=date(2026, 3, 10),
    )
    cr_control = _mk_credito(
        c_control.id,
        f"CR-VC-{c_control.id.hex[:6]}",
        periodicidad=Periodicidad.mensual,
        activo=True,
        fecha_inicial_pago=date(2026, 3, 1),
    )
    db_session.add_all([cr_diario, cr_control])
    await db_session.flush()

    # Cuota #1 real para cada crédito, unpaid → establece el bloqueador en
    # _calcular_virtuales y habilita la proyección de la cuota #2.
    p_diario = _mk_pago(cr_diario.id, date(2026, 3, 10))
    p_control = _mk_pago(cr_control.id, date(2026, 3, 1))
    db_session.add_all([p_diario, p_control])
    await db_session.flush()

    return {
        "cr_diario": cr_diario,
        "cr_control": cr_control,
        "p_diario": p_diario,
        "p_control": p_control,
    }


class TestFiltroPeriodicidad:
    """Tests de filtrado por periodicidad en GET /pagos."""

    # 2.2 — solo_periodicidad=diario devuelve solo créditos diarios
    @pytest.mark.asyncio
    async def test_solo_periodicidad_diario(
        self, client_admin_db: AsyncClient, datos_periodicidades_mixtas
    ):
        """solo_periodicidad=diario → solo items con periodicidad diario."""
        r = await client_admin_db.get(
            "/api/v1/pagos?anio=2026&mes=3&solo_periodicidad=diario"
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) >= 1
        credito_ids = {i["credito_id"] for i in items}
        d = datos_periodicidades_mixtas
        assert str(d["cr_diario"].id) in credito_ids
        assert str(d["cr_semanal"].id) not in credito_ids
        assert str(d["cr_mensual"].id) not in credito_ids

    # 2.3 — excluir_periodicidad=semanal (param legacy) excluye semanales
    @pytest.mark.asyncio
    async def test_excluir_periodicidad_legacy_semanal(
        self, client_admin_db: AsyncClient, datos_periodicidades_mixtas
    ):
        """excluir_periodicidad=semanal (param singular legacy) → semanal ausente."""
        r = await client_admin_db.get(
            "/api/v1/pagos?anio=2026&mes=3&excluir_periodicidad=semanal"
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        credito_ids = {i["credito_id"] for i in items}
        d = datos_periodicidades_mixtas
        assert str(d["cr_semanal"].id) not in credito_ids
        assert str(d["cr_diario"].id) in credito_ids
        assert str(d["cr_mensual"].id) in credito_ids

    # 2.4 — excluir_periodicidades multi-valor excluye todas las listadas
    @pytest.mark.asyncio
    async def test_excluir_periodicidades_multiple(
        self, client_admin_db: AsyncClient, datos_periodicidades_mixtas
    ):
        """excluir_periodicidades=['semanal','diario'] → solo mensual presente.

        RED: el param excluir_periodicidades no existe todavía → el backend lo
        ignora y devuelve los tres créditos → la aserción falla.
        """
        r = await client_admin_db.get(
            "/api/v1/pagos",
            params=[
                ("anio", 2026),
                ("mes", 3),
                ("excluir_periodicidades", "semanal"),
                ("excluir_periodicidades", "diario"),
            ],
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        credito_ids = {i["credito_id"] for i in items}
        d = datos_periodicidades_mixtas
        assert str(d["cr_semanal"].id) not in credito_ids
        assert str(d["cr_diario"].id) not in credito_ids
        assert str(d["cr_mensual"].id) in credito_ids

    # 2.5 — excluir diario no filtra filas virtuales del crédito diario activo
    @pytest.mark.asyncio
    async def test_excluir_periodicidades_no_leak_virtuales(
        self, client_admin_db: AsyncClient, datos_virtuales_excluir_periodicidad
    ):
        """Regular-view query (excluir semanal+diario) no debe exponer filas virtuales
        de un crédito diario activo.

        Escenario: crédito diario ACTIVO con cuota #1 real (unpaid) → _calcular_virtuales
        proyectaría cuota #2 (fecha +1d) si el crédito no fuera excluido.
        El crédito mensual de control (activo) produce cuota virtual #2 (+30d) → sí aparece.

        RED: si se elimina el `excluir_set` guard en _calcular_virtuales, el crédito
        diario aparece con filas virtuales → la aserción falla.
        """
        d = datos_virtuales_excluir_periodicidad
        r = await client_admin_db.get(
            "/api/v1/pagos",
            params=[
                ("anio", 2026),
                ("mes", 3),
                ("excluir_periodicidades", "semanal"),
                ("excluir_periodicidades", "diario"),
            ],
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        all_credito_ids = {i["credito_id"] for i in items}

        # Crédito diario (activo) no debe aparecer — ni real ni virtual
        assert str(d["cr_diario"].id) not in all_credito_ids, (
            "El crédito diario activo filtró filas (reales o virtuales) hacia la vista regular"
        )
        # Crédito mensual de control sí debe aparecer (real + virtual dentro de marzo)
        assert str(d["cr_control"].id) in all_credito_ids, (
            "El crédito mensual de control no apareció en la respuesta"
        )
