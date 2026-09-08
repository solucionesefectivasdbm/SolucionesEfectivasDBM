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


def esta_saldado(credito: Credito) -> bool:
    """
    Regla 9 (zero-balance-credit-closure): un crédito `cuota_fija` está
    saldado solo cuando `saldo_capital <= 0` Y `saldo_intereses <= 0`. El
    capital en cero NO alcanza mientras quede interés pendiente.

    Un crédito `abono_capital` está saldado cuando `saldo_capital <= 0`
    únicamente — no lleva `saldo_intereses` acumulado a nivel de crédito
    (regla 3: `recalcular_saldo_intereses` lo fija en 0.00 para este tipo).
    Se ramifica explícitamente sobre `tipo_credito` en vez de evaluar ambos
    saldos sin condición, para documentar la regla 3 en el punto de decisión
    y no depender silenciosamente de ese invariante.
    """
    if credito.saldo_capital > Decimal("0.00"):
        return False
    if credito.tipo_credito == TipoCredito.cuota_fija:
        return credito.saldo_intereses <= Decimal("0.00")
    return True


def cerrar_credito(credito: Credito) -> bool:
    """
    Regla 9/12 (zero-balance-credit-closure): ÚNICO escritor de
    `activo=False` por crédito saldado. NUNCA escribe `saldo_capital` ni
    `saldo_intereses` — la condonación de deuda que existía antes en
    `_verificar_cierre_credito` (forzar `saldo_capital = 0.00`) queda
    eliminada por construcción, no por un guard adicional.

    Idempotente: si el crédito ya estaba cerrado (`activo == False`), no
    hace nada y retorna `False`. Retorna `True` solo cuando efectivamente
    transiciona `activo` de `True` a `False`.
    """
    if not credito.activo:
        return False
    credito.activo = False
    return True


_Q_ARRASTRE = Decimal("0.01")


def desglosar_arrastre(
    cuota_anterior: "Pago | None", saldo_pendiente: Decimal
) -> tuple[Decimal, Decimal]:
    """
    Desglosa el arrastre (faltante de una cuota `cuota_fija` anterior) en sus
    componentes de capital e interés, a partir de la cuota anterior persistida.

    Retorna (arrastre_capital, arrastre_interes); la suma es EXACTAMENTE
    igual a `saldo_pendiente` (el interés absorbe el residual), lo que
    garantiza `capital_a_pagar + interes_a_pagar == monto_a_pagar` sin
    deriva de redondeo, incluso cuando un componente fue sobrepagado.
    """
    total = (saldo_pendiente or Decimal("0.00")).quantize(_Q_ARRASTRE, rounding=ROUND_HALF_UP)
    if cuota_anterior is None or total <= Decimal("0.00"):
        return Decimal("0.00"), Decimal("0.00")

    falta_cap = (cuota_anterior.capital_a_pagar - cuota_anterior.capital_pagado).quantize(
        _Q_ARRASTRE, rounding=ROUND_HALF_UP
    )
    arr_cap = min(max(falta_cap, Decimal("0.00")), total)
    return arr_cap, (total - arr_cap)


async def generar_prefijo_cliente(db: AsyncSession, cliente) -> str:
    """
    Calcula el prefijo de número de crédito para un cliente, basado en su nombre.

    Reglas:
    - Si el cliente es el único cliente ACTIVO con ese par (nombre, apellidos),
      el prefijo es simplemente "{nombre} {apellidos}".
    - Si hay 2+ clientes activos con el mismo nombre+apellidos, se añade un
      disambiguador "(N)" donde N es la posición del cliente ordenada por
      created_at ascendente (tiebreak por id). Ej: "Juan Pérez(1)", "Juan Pérez(2)".
    """
    from app.models.cliente import Cliente as ClienteModel

    label_base = f"{cliente.nombre} {cliente.apellidos}"

    siblings = (await db.execute(
        select(ClienteModel).where(
            ClienteModel.nombre == cliente.nombre,
            ClienteModel.apellidos == cliente.apellidos,
            ClienteModel.deleted_at == None,  # noqa: E711
        ).order_by(ClienteModel.created_at.asc(), ClienteModel.id.asc())
    )).scalars().all()

    if len(siblings) <= 1:
        return label_base

    for idx, s in enumerate(siblings, start=1):
        if s.id == cliente.id:
            return f"{label_base}({idx})"

    # Fallback: cliente no está activo (soft-deleted). Usar label base sin disambig.
    return label_base


async def renumerar_creditos_con_prefijo(
    db: AsyncSession,
    cliente_id: uuid.UUID,
    prefijo_base: str,
) -> list[tuple[uuid.UUID, str, str]]:
    """
    Renumera TODOS los créditos del cliente (incluyendo soft-deleted) para que
    usen el `prefijo_base` dado. Genera números de la forma "{prefijo_base}-CR-NNN".

    Maneja dos tipos de colisión contra el UNIQUE constraint:
    1. Créditos de OTROS clientes que ya usan ese prefijo: se saltan esos
       secuenciales ocupados.
    2. Colisión intra-cliente cuando algunos créditos del mismo cliente ya
       tienen el prefijo destino: se hace rename en dos fases (a valor
       temporal y luego al definitivo).

    Retorna lista de (credito_id, numero_anterior, numero_nuevo) para auditoría.
    """
    creditos = (await db.execute(
        select(Credito)
        .where(Credito.cliente_id == cliente_id)
        .order_by(Credito.created_at.asc(), Credito.numero_credito_cliente.asc())
    )).scalars().all()

    if not creditos:
        return []

    prefix = f"{prefijo_base}-CR-"

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

    asignaciones: list[tuple[Credito, str, str]] = []
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

    # Fase 1: renombrar a valores temporales únicos (rompe ciclos intra-cliente)
    for credito, _, _ in asignaciones:
        credito.numero_credito_cliente = f"T{credito.id.hex[:19]}"
    await db.flush()

    # Fase 2: asignar valores finales
    cambios: list[tuple[uuid.UUID, str, str]] = []
    for credito, anterior, nuevo in asignaciones:
        credito.numero_credito_cliente = nuevo
        cambios.append((credito.id, anterior, nuevo))

    return cambios


async def sincronizar_prefijos_por_nombre(
    db: AsyncSession,
    nombre: str,
    apellidos: str,
) -> list[tuple[uuid.UUID, str, str]]:
    """
    Recalcula los prefijos correctos para TODOS los clientes activos que
    comparten el par (nombre, apellidos) y renumera sus créditos.

    Se invoca después de:
    - Crear un cliente (puede agregar disambig a hermanos existentes).
    - Actualizar el nombre/apellidos de un cliente (tanto el nombre viejo
      como el nuevo deben re-sincronizarse).
    - Eliminar (soft) un cliente (puede quitar el disambig al hermano que queda).
    """
    from app.models.cliente import Cliente as ClienteModel

    activos = (await db.execute(
        select(ClienteModel).where(
            ClienteModel.nombre == nombre,
            ClienteModel.apellidos == apellidos,
            ClienteModel.deleted_at == None,  # noqa: E711
        ).order_by(ClienteModel.created_at.asc(), ClienteModel.id.asc())
    )).scalars().all()

    label_base = f"{nombre} {apellidos}"
    cambios_total: list[tuple[uuid.UUID, str, str]] = []

    if len(activos) == 1:
        cambios = await renumerar_creditos_con_prefijo(db, activos[0].id, label_base)
        cambios_total.extend(cambios)
    else:
        for idx, cliente in enumerate(activos, start=1):
            prefijo = f"{label_base}({idx})"
            cambios = await renumerar_creditos_con_prefijo(db, cliente.id, prefijo)
            cambios_total.extend(cambios)

    return cambios_total


async def generar_numero_credito(db: AsyncSession, prefijo_base: str) -> str:
    """
    Genera el siguiente número de crédito disponible bajo el prefijo dado.
    Formato: "{prefijo_base}-CR-{NNN}".

    El secuencial se calcula consultando directamente la tabla `creditos`
    por el patrón del prefijo, así se respetan los huecos causados por
    borrados físicos antiguos y se evita cualquier colisión con el
    UNIQUE constraint `creditos_numero_credito_cliente_key`.
    """
    prefix = f"{prefijo_base}-CR-"
    result = await db.execute(
        select(func.count(Credito.id)).where(
            Credito.numero_credito_cliente.like(f"{prefix}%")
        )
    )
    count = result.scalar() or 0
    secuencial = count + 1
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
    Primera cuota de abono_capital. La estructura depende de la periodicidad:
    - Mensual: cuota combinada — interés + abono mínimo en una sola cuota.
    - Otras periodicidades: solo interés (las cuotas alternan interés / abono).
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

    if credito.periodicidad == Periodicidad.mensual:
        # Cuota combinada: interés + abono mínimo (capital).
        abono = credito.abono_minimo if credito.abono_minimo else Decimal("0.00")
        monto_total = (interes + abono).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Pago(
            credito_id=credito.id,
            numero_cuota=1,
            tipo_cuota=TipoCuota.programada,
            monto_a_pagar=monto_total,
            capital_a_pagar=abono,
            interes_a_pagar=interes,
            momento=momento,
            fecha_maxima=fecha_maxima,
            receptor_id=receptor_id,
            es_ultimo_pago=False,
        )

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
        es_ultimo_pago=False,
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

    Regla 10: para `cuota_fija`, capital saldado con `saldo_intereses`
    pendiente NO detiene la generación — sigue con la cola de cuotas de
    solo interés (ver `_siguiente_cuota_fija`). La generación se detiene
    únicamente cuando el crédito queda saldado (`esta_saldado`).
    """
    if esta_saldado(credito):
        return None

    siguiente_numero = cuota_anterior.numero_cuota + 1
    fecha_maxima = siguiente_fecha_maxima(cuota_anterior.fecha_maxima, credito)
    momento = get_momento(fecha_maxima)

    if credito.tipo_credito == TipoCredito.cuota_fija:
        return _siguiente_cuota_fija(
            credito, cuota_anterior, siguiente_numero, fecha_maxima, momento, receptor_id, saldo_pendiente
        )
    else:
        return _siguiente_cuota_abono_capital(
            credito, cuota_anterior, siguiente_numero, fecha_maxima, momento, receptor_id, saldo_pendiente
        )


def _siguiente_cuota_fija(
    credito: Credito,
    cuota_anterior: Pago,
    numero: int,
    fecha_maxima: date,
    momento: str,
    receptor_id: uuid.UUID | None,
    saldo_pendiente: Decimal,
) -> Pago:
    """
    Genera la siguiente cuota para crédito cuota_fija (interés simple).
    Cada cuota tiene la misma porción de capital e interés calculados
    sobre el capital_prestado original, más el arrastre (si lo hay)
    desglosado por componente vía `desglosar_arrastre`.

    Regla 10: si el capital ya está saldado pero queda `saldo_intereses`
    pendiente, delega en `_siguiente_cuota_fija_solo_interes` — la cola de
    cuotas de solo interés.
    """
    if credito.saldo_capital <= Decimal("0.00"):
        return _siguiente_cuota_fija_solo_interes(credito, numero, fecha_maxima, momento, receptor_id)

    capital_por_cuota = calcular_capital_cuota_fija(
        credito.capital_prestado, credito.numero_cuotas,
    )
    interes = calcular_interes_cuota_fija(
        credito.capital_prestado, credito.tasa_interes_mensual, credito.periodicidad,
    )

    arr_cap, arr_int = desglosar_arrastre(cuota_anterior, saldo_pendiente)
    capital_a_pagar = (capital_por_cuota + arr_cap).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    interes_a_pagar = (interes + arr_int).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    monto_total = (capital_a_pagar + interes_a_pagar).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    es_ultima = credito.saldo_capital <= capital_a_pagar and credito.saldo_intereses <= interes_a_pagar

    return Pago(
        credito_id=credito.id,
        numero_cuota=numero,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=monto_total,
        capital_a_pagar=capital_a_pagar,
        interes_a_pagar=interes_a_pagar,
        momento=momento,
        fecha_maxima=fecha_maxima,
        receptor_id=receptor_id,
        es_ultimo_pago=es_ultima,
    )


def _siguiente_cuota_fija_solo_interes(
    credito: Credito,
    numero: int,
    fecha_maxima: date,
    momento: str,
    receptor_id: uuid.UUID | None,
) -> Pago:
    """
    Regla 10 — cola de cuotas de solo interés: el capital de un crédito
    `cuota_fija` ya está saldado (`saldo_capital <= 0`) pero queda
    `saldo_intereses` pendiente. Cobra únicamente interés, TOPADO a
    `saldo_intereses` para nunca cobrar de más (ver design: el `max()`
    piso de `_aplicar_reduccion_saldos` absorbería silenciosamente el
    exceso, produciendo un sobrecobro invisible — el espejo del bug de
    condonación de deuda que esta iniciativa elimina).

    `interes_base` es constante (se calcula sobre `capital_prestado`, el
    capital original, no el saldo vigente — modelo de interés simple), así
    que el tope solo liga en la última cuota de la cola. Sin arrastre
    (`saldo_pendiente = 0`): el saldo ya es el libro contable, y el próximo
    cálculo de `min(interes_base, saldo_intereses)` autocorrige cualquier
    faltante de un pago parcial anterior.
    """
    interes_base = calcular_interes_cuota_fija(
        credito.capital_prestado, credito.tasa_interes_mensual, credito.periodicidad,
    )
    interes_a_pagar = min(interes_base, credito.saldo_intereses)
    if interes_a_pagar <= Decimal("0.00"):
        # Degenerado: tasa o capital_prestado en 0 → cobra el remanente completo
        # en una sola cuota (interes_base sería 0, nunca cubriría el saldo).
        interes_a_pagar = credito.saldo_intereses
    es_ultima = credito.saldo_intereses <= interes_a_pagar

    return Pago(
        credito_id=credito.id,
        numero_cuota=numero,
        tipo_cuota=TipoCuota.interes,
        monto_a_pagar=interes_a_pagar,
        capital_a_pagar=Decimal("0.00"),
        interes_a_pagar=interes_a_pagar,
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
    Genera la siguiente cuota para abono_capital. La estructura depende de la
    periodicidad:

    - Mensual: cada cuota es combinada (interés sobre saldo_capital actual +
      abono mínimo). El saldo_pendiente (faltante de intereses de la cuota
      anterior) se suma al monto total — siempre hay interés donde arrastrar.

    - Otras periodicidades: alternancia INTERÉS → ABONO → INTERÉS → ABONO.
      Solo las cuotas de interés admiten arrastre. Las de abono nunca.
    """
    if credito.periodicidad == Periodicidad.mensual:
        interes = calcular_interes_periodo(credito.saldo_capital, credito.tasa_interes_mensual)
        abono = credito.abono_minimo if credito.abono_minimo else Decimal("0.00")
        monto_total = (interes + abono + saldo_pendiente).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return Pago(
            credito_id=credito.id,
            numero_cuota=numero,
            tipo_cuota=TipoCuota.programada,
            monto_a_pagar=monto_total,
            capital_a_pagar=abono,
            interes_a_pagar=interes,
            momento=momento,
            fecha_maxima=fecha_maxima,
            receptor_id=receptor_id,
            es_ultimo_pago=False,
        )

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


async def recalcular_saldo_intereses(
    db: AsyncSession,
    credito: Credito,
) -> None:
    """
    Recalcula `saldo_intereses` del crédito a partir de los valores actuales
    (capital_prestado, tasa_interes_mensual, periodicidad, numero_cuotas) y
    descuenta lo que ya ha sido cobrado en pagos previos.

    - Cuota fija: total = capital * tasa * (numero_cuotas / periodos_por_mes)
    - Abono capital: total = saldo_capital * tasa (un período de interés)

    Se invoca cuando un Admin modifica capital o tasa, ya que de lo contrario
    el saldo queda con el valor calculado al momento de creación.
    """
    total_interes_pagado = (await db.execute(
        select(func.coalesce(func.sum(Pago.interes_pagado), Decimal("0.00"))).where(
            Pago.credito_id == credito.id,
            Pago.deleted_at == None,  # noqa: E711
        )
    )).scalar() or Decimal("0.00")

    if credito.tipo_credito == TipoCredito.cuota_fija and credito.numero_cuotas:
        ppm = Decimal(_periodos_por_mes(credito.periodicidad))
        num_meses = Decimal(credito.numero_cuotas) / ppm
        nuevo_total = credito.capital_prestado * credito.tasa_interes_mensual * num_meses
        nuevo_saldo = nuevo_total - Decimal(total_interes_pagado)
        if nuevo_saldo < Decimal("0.00"):
            nuevo_saldo = Decimal("0.00")
        credito.saldo_intereses = nuevo_saldo.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        # Abono capital — NO lleva saldo de intereses acumulado: el interés total es
        # indeterminado (depende de cuánto tarde el cliente en bajar el capital). El
        # interés se cobra período a período en la cuota (Pago.interes_a_pagar), no como
        # un saldo a nivel crédito.
        credito.saldo_intereses = Decimal("0.00")


async def recalcular_cuota_actual_si_no_pagada(
    db: AsyncSession,
    credito: Credito,
) -> bool:
    """
    Recalcula la cuota ACTUAL del crédito (la primera sin pagar, sea cual sea
    su número) usando los valores actuales del crédito (capital_prestado,
    tasa_interes_mensual, abono_minimo, etc.).

    Solo aplica si la cuota actual no tiene montos registrados
    (capital_pagado=0 y interes_pagado=0). Si el recaudador ya le dio check
    pero aún no se registraron montos, igual se recalcula — el check solo
    confirma recepción, no congela los montos esperados.

    Se invoca cuando un Admin modifica capital_prestado, tasa_interes_mensual
    o abono_minimo, para que el cambio se vea reflejado DESDE la cuota actual
    (no solo en las cuotas posteriores que se generen luego).

    Mantiene numero_cuota, fecha_maxima, momento y receptor_id intactos —
    solo actualiza los montos (capital_a_pagar, interes_a_pagar, monto_a_pagar)
    y el tipo de cuota.
    """
    actual = (await db.execute(
        select(Pago).where(
            Pago.credito_id == credito.id,
            Pago.pagado == False,  # noqa: E712
            Pago.deleted_at == None,  # noqa: E711
        ).order_by(Pago.numero_cuota).limit(1)
    )).scalar_one_or_none()

    if not actual:
        return False
    if actual.capital_pagado > 0 or actual.interes_pagado > 0:
        return False

    ppm = Decimal(_periodos_por_mes(credito.periodicidad))

    if (
        credito.tipo_credito == TipoCredito.cuota_fija
        and credito.saldo_capital <= Decimal("0.00")
    ):
        # Regla 10: capital ya saldado, saldo_intereses pendiente — la cuota
        # actual debe recalcularse como solo-interés, topada a saldo_intereses.
        # Sin arrastre: sería doble conteo (el saldo ya refleja el faltante).
        interes_base = calcular_interes_cuota_fija(
            credito.capital_prestado, credito.tasa_interes_mensual, credito.periodicidad,
        )
        interes_x = min(interes_base, credito.saldo_intereses)
        if interes_x <= Decimal("0.00"):
            interes_x = credito.saldo_intereses

        actual.tipo_cuota = TipoCuota.interes
        actual.capital_a_pagar = Decimal("0.00")
        actual.interes_a_pagar = interes_x
        actual.monto_a_pagar = interes_x
        actual.es_ultimo_pago = credito.saldo_intereses <= interes_x
    elif credito.tipo_credito == TipoCredito.cuota_fija and credito.numero_cuotas:
        capital_x = calcular_capital_cuota_fija(
            credito.capital_prestado, credito.numero_cuotas,
        )
        if actual.numero_cuota == 1 and credito.calcular_interes_dias_corridos:
            interes = calcular_interes_primera_cuota(
                credito.capital_prestado, credito.tasa_interes_mensual,
                credito.fecha_apertura, credito.fecha_inicial_pago,
            )
        else:
            interes = calcular_interes_cuota_fija(
                credito.capital_prestado, credito.tasa_interes_mensual, credito.periodicidad,
            )

        # Re-derivar el arrastre pendiente desde la cuota pagada inmediatamente
        # anterior, para no sobrescribirlo con los valores base recalculados
        # (mismo defecto de clase que el reset de saldo_capital en edición).
        cuota_previa_pagada = (await db.execute(
            select(Pago).where(
                Pago.credito_id == credito.id,
                Pago.numero_cuota < actual.numero_cuota,
                Pago.pagado == True,  # noqa: E712
                Pago.deleted_at == None,  # noqa: E711
            ).order_by(Pago.numero_cuota.desc()).limit(1)
        )).scalar_one_or_none()

        saldo_pendiente = Decimal("0.00")
        if cuota_previa_pagada is not None:
            saldo_pendiente = max(
                Decimal("0.00"),
                (
                    cuota_previa_pagada.monto_a_pagar
                    - cuota_previa_pagada.capital_pagado
                    - cuota_previa_pagada.interes_pagado
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )
        arr_cap, arr_int = desglosar_arrastre(cuota_previa_pagada, saldo_pendiente)

        capital_x = (capital_x + arr_cap).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        interes = (interes + arr_int).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        actual.tipo_cuota = TipoCuota.programada
        actual.capital_a_pagar = capital_x
        actual.interes_a_pagar = interes
        actual.monto_a_pagar = (capital_x + interes).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        actual.es_ultimo_pago = (
            credito.saldo_capital <= capital_x and credito.saldo_intereses <= interes
        )
    else:
        # abono_capital
        if actual.numero_cuota == 1 and credito.calcular_interes_dias_corridos:
            interes = calcular_interes_primera_cuota(
                credito.saldo_capital, credito.tasa_interes_mensual,
                credito.fecha_apertura, credito.fecha_inicial_pago,
            )
        else:
            interes = calcular_interes_periodo(credito.saldo_capital, credito.tasa_interes_mensual)
        abono = credito.abono_minimo if credito.abono_minimo else Decimal("0.00")

        if credito.periodicidad == Periodicidad.mensual:
            # Cuota combinada: interés + abono mínimo
            actual.tipo_cuota = TipoCuota.programada
            actual.capital_a_pagar = abono
            actual.interes_a_pagar = interes
            actual.monto_a_pagar = (interes + abono).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            # Quincenal/otras: respetar el tipo de la cuota (interés o abono)
            if actual.tipo_cuota == TipoCuota.abono:
                actual.capital_a_pagar = abono
                actual.interes_a_pagar = Decimal("0.00")
                actual.monto_a_pagar = abono
            else:
                actual.tipo_cuota = TipoCuota.interes
                actual.capital_a_pagar = Decimal("0.00")
                actual.interes_a_pagar = interes
                actual.monto_a_pagar = interes
        actual.es_ultimo_pago = False
    return True


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
        fecha_actual = siguiente_fecha_maxima(fecha_actual, credito)
