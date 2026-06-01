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
        # Abono capital — cada período de interés es independiente: el saldo de intereses
        # del próximo período es saldo_capital_vigente * tasa, sin restar el histórico pagado
        # (el histórico ya se consumió en cuotas cerradas de períodos anteriores).
        credito.saldo_intereses = calcular_interes_periodo(
            credito.saldo_capital, credito.tasa_interes_mensual
        )


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

    if credito.tipo_credito == TipoCredito.cuota_fija and credito.numero_cuotas:
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
        actual.tipo_cuota = TipoCuota.programada
        actual.capital_a_pagar = capital_x
        actual.interes_a_pagar = interes
        actual.monto_a_pagar = (capital_x + interes).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        actual.es_ultimo_pago = actual.numero_cuota >= credito.numero_cuotas
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
        fecha_actual = siguiente_fecha_maxima(fecha_actual, credito.periodicidad)
