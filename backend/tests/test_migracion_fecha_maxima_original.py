"""
tests/test_migracion_fecha_maxima_original.py — Alembic revision
a7b8c9d0e1f2 (agrega `fecha_maxima_original` a `pagos`).

RED: el archivo de revisión todavía no existe, así que cargarlo falla.

Prueba la migración en aislamiento (no la cadena completa de alembic,
porque revisiones previas usan SQL crudo específico de Postgres como
`gen_random_uuid()` que SQLite no puede ejecutar) enlazando un contexto
`Operations` de Alembic directamente a una conexión SQLite descartable
e invocando el `upgrade()` de la revisión.
"""
import importlib.util
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_REVISION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "a7b8c9d0e1f2_add_fecha_maxima_original_to_pagos.py"
)


def _cargar_revision() -> ModuleType:
    """Carga el archivo de revisión como módulo, igual que hace Alembic
    internamente (el nombre del archivo empieza con un hash hex, no es
    un identificador válido para un `import` normal)."""
    spec = importlib.util.spec_from_file_location(
        "revision_fecha_maxima_original", _REVISION_PATH
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _crear_tabla_pagos_previa(conn) -> None:
    """Esquema mínimo de `pagos` tal como existe justo antes de esta
    revisión — solo las columnas que su `upgrade()` necesita."""
    conn.execute(sa.text(
        "CREATE TABLE pagos (id TEXT PRIMARY KEY, fecha_maxima DATE NOT NULL)"
    ))


def _insertar_pago(conn, fecha_maxima: date) -> str:
    pago_id = str(uuid.uuid4())
    conn.execute(
        sa.text("INSERT INTO pagos (id, fecha_maxima) VALUES (:id, :fecha_maxima)"),
        {"id": pago_id, "fecha_maxima": fecha_maxima.isoformat()},
    )
    return pago_id


def _correr_upgrade(conn) -> None:
    contexto = MigrationContext.configure(conn)
    with Operations.context(contexto):
        _cargar_revision().upgrade()


class TestMigracionFechaMaximaOriginal:
    """Fase 1, tarea 1.1: la migración agrega la columna nullable, la
    llena por backfill desde `fecha_maxima`, y crea su índice — sin
    tocar Postgres (se prueba contra SQLite, aislada de la cadena)."""

    def test_upgrade_agrega_columna_e_indice_sin_fallar(self):
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                _crear_tabla_pagos_previa(conn)
                _insertar_pago(conn, date(2026, 10, 5))
                _correr_upgrade(conn)

                columnas = {
                    fila[1] for fila in conn.execute(
                        sa.text("PRAGMA table_info(pagos)")
                    ).fetchall()
                }
                indices = conn.execute(
                    sa.text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='index' AND name='ix_pagos_fecha_maxima_original'"
                    )
                ).fetchall()

            assert "fecha_maxima_original" in columnas
            assert len(indices) == 1
        finally:
            engine.dispose()

    def test_backfill_deja_columna_sin_nulos_para_filas_existentes(self):
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                _crear_tabla_pagos_previa(conn)
                id_octubre = _insertar_pago(conn, date(2026, 10, 5))
                id_diciembre = _insertar_pago(conn, date(2026, 12, 20))
                _correr_upgrade(conn)

                filas = conn.execute(
                    sa.text("SELECT id, fecha_maxima_original FROM pagos")
                ).fetchall()
                nulos = conn.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM pagos WHERE fecha_maxima_original IS NULL"
                    )
                ).scalar_one()

            valores = {fila[0]: fila[1] for fila in filas}
            assert valores[id_octubre] == "2026-10-05"
            assert valores[id_diciembre] == "2026-12-20"
            assert nulos == 0
        finally:
            engine.dispose()
