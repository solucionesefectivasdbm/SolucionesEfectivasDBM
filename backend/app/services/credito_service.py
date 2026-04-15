"""
services/credito_service.py — Lógica de creación y recálculo de créditos.

DECISIÓN TÉCNICA: Todo el cálculo financiero usa Decimal, nunca float.
Decimal evita errores de representación binaria (0.1 + 0.2 != 0.3 en float).
En operaciones de millones de pesos, estos errores se acumulan.

La fórmula de cuota fija usa interés simple:
    interes_total = capital * tasa_mensual * n
    cuota = (capital + interes_total) / n
Cada cuota tiene la misma porción de capital y la misma porción de interés.
"""
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credito import Credito, TipoCredito, Periodicidad
from app.models.pago import Pago, TipoCuota
from app.schemas.credito import CreditoCreate
from app.utils.fechas import (
    siguiente_fecha_maxima,
    calcular_interes_primera_cuota,
    debe_usar_dias_corridos,
)
from app.utils.momentos import get_momento


def _periodos_por_mes(periodicidad: Periodicidad) -> int:
    """Cuántos pagos caen en un mes según la periodicidad."""
    return {
        Periodicidad.diario: 30,
        Periodicidad.semanal: 4,
        Periodicidad.quincenal: 2,
        Periodicidad.mensual: 1,
    }[periodicidad]


def calcular_cuota_fija(
    capital: Decimal,
    tasa_mensual: Decimal,
    num_cuotas: int,
    periodicidad: Periodicidad,
) -> Decimal:
    """
    Calcula el monto fijo de cuota usando interés simple.

    El interés mensual se divide entre los pagos del mes según periodicidad.
    Ejemplo quincenal: 2 pagos/mes → cada pago lleva la mitad del interés mensual.
    """
    n = Decimal(num_cuotas)
    ppm = Decimal(_periodos_por_mes(periodicidad))
    num_meses = n / ppm
    interes_total = capital * tasa_mensual * num_meses
    cuota = (capital + interes_total) / n
    return cuota.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_interes_cuota_fija(
    capital_total: Decimal,
    tasa_mensual: Decimal,
    periodicidad: Periodicidad,
) -> Decimal:
    """
    Calcula el interés por cuota para cuota fija (interés simple).
    El interés mensual se divide entre los pagos del mes.
    Quincenal: interes_cuota = capital * tasa / 2
    """
    ppm = Decimal(_periodos_por_mes(periodicidad))
    return (capital_total * tasa_mensual / ppm).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_capital_cuota_fija(
    capital_total: Decimal,
    num_cuotas: int,
) -> Decimal:
    """
    Calcula la porción de capital por cuota (capital / num_cuotas).
    """
    return (capital_total / Decimal(num_cuotas)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_interes_periodo(capital: Decimal, tasa_mensual: Decimal) -> Decimal:
    """Calcula el interés de un período completo."""
    return (capital * tasa_mensual).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def renumerar_creditos_por_cedula(
    db: AsyncSession,
    cliente_id: uuid.UUID,
    nueva_cedula: str,
) -> list[tuple[uuid.UUID, str, str]]:
    """
    Renumera todos los créditos del cliente para que usen la nueva cédula.

    Se invoca cuando el cliente cambia su cédula (por ejemplo, reemplazo de
    un valor placeholder por el dato real). Actualiza `numero_credito_cliente`
    en TODOS los créditos del cliente — incluyendo los soft-deleted —
    para liberar el prefijo anterior y evitar colisiones futuras.

    Si el nuevo prefijo ya está siendo usado por créditos de OTROS clientes
    (p. ej. porque esa misma cédula la tuvo antes otro cliente distinto),
    se saltan esos secuenciales ocupados.

    Retorna lista de (credito_id, numero_anterior, numero_nuevo) para
    registrar en el log de auditoría.
    """
    creditos = (await db.execute(
        select(Credito)
        .where(Credito.cliente_id == cliente_id)
        .order_by(Credito.created_at.asc(), Credito.numero_credito_cliente.asc())
    )).scalars().all()

    if not creditos:
        return []

    prefix = f"{nueva_cedula}-CR-"

    # Secuenciales ya ocupados bajo el nuevo prefijo por OTROS clientes
    existentes = (await db.execute(
        select(Credito.numero_credito_cliente).where(
            Credito.numero_credito_cliente.like(f"{prefix}%"),
            Credito.cliente_id != cliente_id,
        )
    )).scalars().all()

    ocupados: set[int] = set()
    for num in existentes:
        try:
            ocupados.add(int(num[len(prefix):]))
        except (ValueError, IndexError):
            pass

    # Planear la asignación final (captura valor anterior antes de cualquier mutación)
    asignaciones: list[tuple[Credito, str, str]] = []  # (credito, anterior, nuevo)
    siguiente = 1
    for credito in creditos:
        while siguiente in ocupados:
            siguiente += 1
        nuevo_numero = f"{prefix}{siguiente:03d}"
        anterior = credito.numero_credito_cliente
        if anterior != nuevo_numero:
            asignaciones.append((credito, anterior, nuevo_numero))
        ocupados.add(siguiente)
        siguiente += 1

    if not asignaciones:
        return []

    # Paso 1: renombrar a valores temporales únicos para romper ciclos intra-cliente.
    # Caso típico: un crédito existente tiene 'CED-CR-001' y queremos asignarlo a otro
    # crédito del mismo cliente. Actualizar directamente viola el UNIQUE a mitad del flush.
    # La columna numero_credito_cliente es VARCHAR(20); usamos 'T' + 19 hex de UUID (= 20 chars).
    for credito, _, _ in asignaciones:
        credito.numero_credito_cliente = f"T{credito.id.hex[:19]}"
    await db.flush()

    # Paso 2: asignar los valores finales
    cambios: list[tuple[uuid.UUID, str, str]] = []
    for credito, anterior, nuevo in asignaciones:
        credito.numero_credito_cliente = nuevo
        cambios.append((credito.id, anterior, nuevo))

    return cambios


async def generar_numero_credito(db: AsyncSession, cedula_cliente: str) -> str:
    """
    Genera el número de crédito en formato {cedula}-CR-{secuencial:03d}.

    Busca el siguiente secuencial disponible consultando directamente la tabla
    `creditos` por el patrón del número. Así funciona aunque la cédula del cliente
    haya cambiado, o aunque haya existido un cliente distinto con esa cédula en
    el pasado (cuyos créditos ya no aparecen al unir por cliente.cedula).

    El secuencial incluye créditos con borrado lógico para evitar duplicados
    contra el UNIQUE constraint `creditos_numero_credito_cliente_key`.
    """
    prefix = f"{cedula_cliente}-CR-"
    result = await db.execute(
        select(func.count(Credito.id)).where(
            Credito.numero_credito_cliente.like(f"{prefix}%")
        )
    )
    count = result.scalar() or 0
    secuencial = count + 1
    # Defensivo: si ya existe el número generado (p. ej. por huecos en la
    # numeración causados por borrados físicos antiguos), avanzar hasta hallar uno libre.
    while True:
        candidato = f"{prefix}{secuencial:03d}"
        existe = (await db.execute(
            select(func.count(Credito.id)).where(
                Credito.numero_credito_cliente == candidato
            )
        )).scalar()
        if not existe:
            return candidato
        secuencial += 1


async def crear_primera_cuota(
    credito: Credito,
    receptor_id: uuid.UUID | None,
) -> Pago:
    """
    Crea la primera cuota de un crédito recién creado.
    La lógica difiere según el tipo de crédito.
    """
    fecha_maxima = credito.fecha_inicial_pago
    momento = get_momento(fecha_maxima)

    if credito.tipo_credito == TipoCredito.cuota_fija:
        return await _primera_cuota_fija(credito, fecha_maxima, momento, receptor_id)
    else:
        return await _primera_cuota_abono_capital(credito, fecha_maxima, momento, receptor_id)


async def _primera_cuota_fija(
    credito: Credito,
    fecha_maxima: date,
    momento: str,
    receptor_id: uuid.UUID | None,
) -> Pago:
    """Primera cuota de crédito cuota_fija (interés simple)."""
    capital_por_cuota = calcular_capital_cuota_fija(
        credito.capital_prestado, credito.numero_cuotas,
    )

    if credito.calcular_interes_dias_corridos:
        interes = calcular_interes_primera_cuota(
            credito.capital_prestado,
            credito.tasa_interes_mensual,
            credito.fecha_apertura,
            credito.fecha_inicial_pago,
        )
    else:
        interes = calcular_interes_cuota_fija(
            credito.capital_prestado, credito.tasa_interes_mensual, credito.periodicidad,
        )

    cuota_monto = (capital_por_cuota + interes).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    es_ultima = credito.numero_cuotas == 1

    return Pago(
        credito_id=credito.id,
        numero_cuota=1,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=cuota_monto,
        capital_a_pagar=capital_por_cuota,
        interes_a_pagar=interes,
        momento=momento,
        fecha_maxima=fecha_maxima,
        receptor_id=receptor_id,
        es_ultimo_pago=es_ultima,
    )


async def _primera_cuota_abono_capital(
    credito: Credito,
    fecha_maxima: date,
    momento: str,
    receptor_id: uuid.UUID | None,
) -> Pago:
    """
    Primera cuota de abono_capital — siempre es de tipo INTERÉS.
    En abono_capital la cuota de interés es solo interés (sin amortización).
    """
    if credito.calcular_interes_dias_corridos:
        interes = calcular_interes_primera_cuota(
            credito.saldo_capital,
            credito.tasa_interes_mensual,
            credito.fecha_apertura,
            credito.fecha_inicial_pago,
        )
    else:
        interes = calcular_interes_periodo(credito.saldo_capital, credito.tasa_interes_mensual)

    return Pago(
        credito_id=credito.id,
        numero_cuota=1,
        tipo_cuota=TipoCuota.interes,
        monto_a_pagar=interes,
        capital_a_pagar=Decimal("0.00"),
        interes_a_pagar=interes,
        momento=momento,
        fecha_maxima=fecha_maxima,
        receptor_id=receptor_id,
    )


async def generar_siguiente_cuota(
    db: AsyncSession,
    credito: Credito,
    cuota_anterior: Pago,
    receptor_id: uuid.UUID | None,
    saldo_pendiente: Decimal = Decimal("0.00"),
) -> Pago | None:
    """
    Genera la siguiente cuota después de que la anterior fue pagada.
    Retorna None si el crédito debe cerrarse (saldo_capital <= 0).

    DECISIÓN: saldo_pendiente acumula el faltante de pagos parciales
    de la cuota anterior. Se suma al monto_a_pagar de la nueva cuota.
    """
    if credito.saldo_capital <= 0:
        return None

    siguiente_numero = cuota_anterior.numero_cuota + 1
    fecha_maxima = siguiente_fecha_maxima(cuota_anterior.fecha_maxima, credito.periodicidad)
    momento = get_momento(fecha_maxima)

    if credito.tipo_credito == TipoCredito.cuota_fija:
        return _siguiente_cuota_fija(
            credito, siguiente_numero, fecha_maxima, momento, receptor_id, saldo_pendiente
        )
    else:
        return _siguiente_cuota_abono_capital(
            credito, cuota_anterior, siguiente_numero, fecha_maxima, momento, receptor_id, saldo_pendiente
        )


def _siguiente_cuota_fija(
    credito: Credito,
    numero: int,
    fecha_maxima: date,
    momento: str,
    receptor_id: uuid.UUID | None,
    saldo_pendiente: Decimal,
) -> Pago:
    """
    Genera la siguiente cuota para crédito cuota_fija (interés simple).
    Cada cuota tiene la misma porción de capital e interés calculados
    sobre el capital_prestado original.
    """
    capital_por_cuota = calcular_capital_cuota_fija(
        credito.capital_prestado, credito.numero_cuotas,
    )
    interes = calcular_interes_cuota_fija(
        credito.capital_prestado, credito.tasa_interes_mensual, credito.periodicidad,
    )
    cuota_base = (capital_por_cuota + interes).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    monto_total = cuota_base + saldo_pendiente
    es_ultima = numero >= credito.numero_cuotas

    return Pago(
        credito_id=credito.id,
        numero_cuota=numero,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=monto_total,
        capital_a_pagar=capital_por_cuota,
        interes_a_pagar=interes,
        momento=momento,
        fecha_maxima=fecha_maxima,
        receptor_id=receptor_id,
        es_ultimo_pago=es_ultima,
    )


def _siguiente_cuota_abono_capital(
    credito: Credito,
    cuota_anterior: Pago,
    numero: int,
    fecha_maxima: date,
    momento: str,
    receptor_id: uuid.UUID | None,
    saldo_pendiente: Decimal,
) -> Pago:
    """
    Genera la siguiente cuota para abono_capital.
    Secuencia: INTERÉS → ABONO → INTERÉS → ABONO...
    
    REGLA: El saldo pendiente SOLO se arrastra en cuotas de INTERÉS.
    Las cuotas de ABONO nunca tienen arrastre — el cliente abona
    lo que puede y el saldo capital se reduce con lo pagado.
    """
    if cuota_anterior.tipo_cuota == TipoCuota.interes:
        # Siguiente es ABONO
        # Si hay abono_minimo definido, ese es el monto esperado.
        # Si no hay abono_minimo, monto_a_pagar = 0 (libre)
        # NUNCA se arrastra saldo a cuotas de abono
        monto_base = credito.abono_minimo if credito.abono_minimo else Decimal("0.00")
        return Pago(
            credito_id=credito.id,
            numero_cuota=numero,
            tipo_cuota=TipoCuota.abono,
            monto_a_pagar=monto_base,
            capital_a_pagar=monto_base,
            interes_a_pagar=Decimal("0.00"),
            momento=momento,
            fecha_maxima=fecha_maxima,
            receptor_id=receptor_id,
        )
    else:
        # La anterior fue ABONO → siguiente es INTERÉS
        # El interés se calcula sobre el saldo capital ACTUAL (ya reducido)
        # El saldo_pendiente de intereses SÍ puede arrastrarse
        interes = calcular_interes_periodo(credito.saldo_capital, credito.tasa_interes_mensual)
        monto_total = interes + saldo_pendiente
        return Pago(
            credito_id=credito.id,
            numero_cuota=numero,
            tipo_cuota=TipoCuota.interes,
            monto_a_pagar=monto_total,
            capital_a_pagar=Decimal("0.00"),
            interes_a_pagar=interes,
            momento=momento,
            fecha_maxima=fecha_maxima,
            receptor_id=receptor_id,
        )


async def recalcular_cuotas_futuras(
    db: AsyncSession,
    credito: Credito,
    desde_fecha: date,
) -> None:
    """
    Recalcula momento y fecha_maxima de todas las cuotas futuras
    cuando el Admin modifica la fecha del pago activo.
    Se usa después de que el Admin cambia la fecha del pago activo
    desde la ventana de créditos.
    """
    result = await db.execute(
        select(Pago)
        .where(
            Pago.credito_id == credito.id,
            Pago.pagado == False,  # noqa: E712
            Pago.deleted_at == None,  # noqa: E711
        )
        .order_by(Pago.numero_cuota)
    )
    cuotas_futuras = result.scalars().all()

    fecha_actual = desde_fecha
    for cuota in cuotas_futuras:
        cuota.fecha_maxima = fecha_actual
        cuota.momento = get_momento(fecha_actual)
        fecha_actual = siguiente_fecha_maxima(fecha_actual, credito.periodicidad)
