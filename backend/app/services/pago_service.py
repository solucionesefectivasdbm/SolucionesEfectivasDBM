"""
services/pago_service.py — Lógica de procesamiento de pagos.

Esta es la pieza más compleja del sistema. Maneja los 3 escenarios
de pago para ambos tipos de crédito:
  1. Pago exacto
  2. Pago parcial (paga menos)
  3. Pago con excedente (paga más) → requiere decisión del usuario

DECISIÓN TÉCNICA: El flujo de excedente es un proceso en 2 pasos:
  - Paso 1: registrar_pago() detecta el excedente y retorna
            requiere_decision=True sin modificar el crédito todavía.
  - Paso 2: confirmar_excedente() aplica la decisión del usuario
            y completa el pago.
Esto evita estados intermedios inconsistentes en la DB.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credito import Credito, TipoCredito
from app.models.pago import Pago, TipoCuota, DestinoExcedente
from app.schemas.pago import RegistrarPagoRequest, RegistrarPagoResponse
from app.services.credito_service import generar_siguiente_cuota


class PagoService:

    @staticmethod
    async def registrar_pago(
        db: AsyncSession,
        pago: Pago,
        credito: Credito,
        request: RegistrarPagoRequest,
        fecha_hoy: date,
    ) -> RegistrarPagoResponse:
        """
        Registra el pago de una cuota. Maneja los 3 escenarios.

        Returns:
            RegistrarPagoResponse con requiere_decision=True si hay excedente.
        """
        monto_pagado = (request.capital_pagado + request.interes_pagado).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        if monto_pagado < pago.monto_a_pagar:
            return await PagoService._pago_parcial(
                db, pago, credito, request, monto_pagado, fecha_hoy
            )
        elif monto_pagado == pago.monto_a_pagar:
            return await PagoService._pago_exacto(
                db, pago, credito, request, fecha_hoy
            )
        else:
            # Excedente: retornar sin modificar hasta que el usuario decida
            excedente = (monto_pagado - pago.monto_a_pagar).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            from app.schemas.pago import PagoResponse
            return RegistrarPagoResponse(
                pago=PagoResponse.model_validate(pago),
                requiere_decision=True,
                excedente=excedente,
                mensaje=f"Hay un excedente de {excedente}. Por favor indique el destino.",
            )

    @staticmethod
    async def _pago_exacto(
        db: AsyncSession,
        pago: Pago,
        credito: Credito,
        request: RegistrarPagoRequest,
        fecha_hoy: date,
    ) -> RegistrarPagoResponse:
        """Procesa pago exacto: marca pagado, actualiza saldos, genera siguiente cuota."""
        pago.capital_pagado = request.capital_pagado
        pago.interes_pagado = request.interes_pagado
        pago.pagado = True
        pago.fecha_pago_real = fecha_hoy

        # Actualizar saldos del crédito
        credito.saldo_capital = (credito.saldo_capital - request.capital_pagado).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if credito.saldo_capital < 0:
            credito.saldo_capital = Decimal("0.00")

        credito.saldo_intereses = max(
            Decimal("0.00"),
            (credito.saldo_intereses - request.interes_pagado).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
        )

        # Verificar cierre de crédito
        await PagoService._verificar_cierre_credito(db, credito, pago)

        # Generar siguiente cuota si el crédito sigue activo
        if credito.activo:
            nueva_cuota = await generar_siguiente_cuota(
                db=db,
                credito=credito,
                cuota_anterior=pago,
                receptor_id=pago.receptor_id,
            )
            if nueva_cuota:
                db.add(nueva_cuota)

        from app.schemas.pago import PagoResponse
        return RegistrarPagoResponse(
            pago=PagoResponse.model_validate(pago),
            mensaje="Pago registrado correctamente",
        )

    @staticmethod
    async def _pago_parcial(
        db: AsyncSession,
        pago: Pago,
        credito: Credito,
        request: RegistrarPagoRequest,
        monto_pagado: Decimal,
        fecha_hoy: date,
    ) -> RegistrarPagoResponse:
        pago.capital_pagado = request.capital_pagado
        pago.interes_pagado = request.interes_pagado
        pago.pagado = True
        pago.fecha_pago_real = fecha_hoy

        faltante = (pago.monto_a_pagar - monto_pagado).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Actualizar saldos
        credito.saldo_capital = max(
            Decimal("0.00"),
            (credito.saldo_capital - request.capital_pagado).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
        )
        credito.saldo_intereses = max(
            Decimal("0.00"),
            (credito.saldo_intereses - request.interes_pagado).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
        )

        # REGLA CLAVE: cuotas de ABONO nunca arrastran faltante
        from app.models.pago import TipoCuota
        saldo_a_arrastrar = Decimal("0.00") if pago.tipo_cuota == TipoCuota.abono else faltante

        await PagoService._verificar_cierre_credito(db, credito, pago)

        if credito.activo:
            nueva_cuota = await generar_siguiente_cuota(
                db=db,
                credito=credito,
                cuota_anterior=pago,
                receptor_id=pago.receptor_id,
                saldo_pendiente=saldo_a_arrastrar,
            )
            if nueva_cuota:
                db.add(nueva_cuota)

        from app.schemas.pago import PagoResponse
        return RegistrarPagoResponse(
            pago=PagoResponse.model_validate(pago),
            mensaje=f"Pago registrado. El abono redujo el saldo capital.",
        )

    @staticmethod
    async def confirmar_excedente(
        db: AsyncSession,
        pago: Pago,
        credito: Credito,
        request: RegistrarPagoRequest,
        destino: DestinoExcedente,
        fecha_hoy: date,
    ) -> RegistrarPagoResponse:
        """
        Paso 2 del flujo de excedente: aplica la decisión del usuario
        y completa el pago.
        """
        monto_pagado = request.capital_pagado + request.interes_pagado
        excedente = (monto_pagado - pago.monto_a_pagar).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        pago.capital_pagado = request.capital_pagado
        pago.interes_pagado = request.interes_pagado
        pago.pagado = True
        pago.fecha_pago_real = fecha_hoy
        pago.es_excedente_a = destino

        # Aplicar excedente al destino elegido
        if destino == DestinoExcedente.capital:
            credito.saldo_capital = max(
                Decimal("0.00"),
                (credito.saldo_capital - pago.capital_a_pagar - excedente).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
            )
            credito.saldo_intereses = max(
                Decimal("0.00"),
                (credito.saldo_intereses - pago.interes_a_pagar).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
            )
        else:  # intereses
            credito.saldo_capital = max(
                Decimal("0.00"),
                (credito.saldo_capital - pago.capital_a_pagar).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
            )
            credito.saldo_intereses = max(
                Decimal("0.00"),
                (credito.saldo_intereses - pago.interes_a_pagar - excedente).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
            )

        await PagoService._verificar_cierre_credito(db, credito, pago)

        if credito.activo:
            nueva_cuota = await generar_siguiente_cuota(
                db=db,
                credito=credito,
                cuota_anterior=pago,
                receptor_id=pago.receptor_id,
            )
            if nueva_cuota:
                db.add(nueva_cuota)

        from app.schemas.pago import PagoResponse
        return RegistrarPagoResponse(
            pago=PagoResponse.model_validate(pago),
            mensaje=f"Pago con excedente registrado. {excedente} aplicado a {destino.value}.",
        )

    @staticmethod
    async def _verificar_cierre_credito(
        db: AsyncSession,
        credito: Credito,
        cuota_actual: Pago,
    ) -> None:
        """
        Verifica si el crédito debe cerrarse y lo marca como inactivo.

        Condiciones de cierre:
        - saldo_capital <= 0 (ambos tipos)
        - cuota_fija: número de cuota >= numero_cuotas
        """
        debe_cerrar = False

        if credito.saldo_capital <= 0:
            debe_cerrar = True

        if (
            credito.tipo_credito == TipoCredito.cuota_fija
            and credito.numero_cuotas is not None
            and cuota_actual.numero_cuota >= credito.numero_cuotas
        ):
            debe_cerrar = True

        if debe_cerrar:
            credito.activo = False
            credito.saldo_capital = Decimal("0.00")

    @staticmethod
    async def registrar_pago_no_programado(
        db: AsyncSession,
        credito: Credito,
        monto: Decimal,
        destino: DestinoExcedente,
        fecha_pago: date,
        receptor_id,
    ) -> Pago:
        """
        Registra un pago no programado. No afecta las cuotas programadas.
        El número de cuota se asigna como el máximo + 1 (pero tipo no_programada).
        """
        result = await db.execute(
            select(Pago.numero_cuota)
            .where(Pago.credito_id == credito.id)
            .order_by(Pago.numero_cuota.desc())
            .limit(1)
        )
        max_cuota = result.scalar() or 0

        if destino == DestinoExcedente.capital:
            credito.saldo_capital = max(
                Decimal("0.00"),
                (credito.saldo_capital - monto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )
            capital_pago = monto
            interes_pago = Decimal("0.00")
        else:
            credito.saldo_intereses = max(
                Decimal("0.00"),
                (credito.saldo_intereses - monto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )
            capital_pago = Decimal("0.00")
            interes_pago = monto

        from app.utils.momentos import get_momento
        pago = Pago(
            credito_id=credito.id,
            numero_cuota=max_cuota + 1,
            tipo_cuota=TipoCuota.no_programada,
            monto_a_pagar=monto,
            capital_a_pagar=capital_pago,
            interes_a_pagar=interes_pago,
            capital_pagado=capital_pago,
            interes_pagado=interes_pago,
            momento=get_momento(fecha_pago),
            fecha_maxima=fecha_pago,
            receptor_id=receptor_id,
            pagado=True,
            fecha_pago_real=fecha_pago,
        )
        db.add(pago)
        await db.flush()  # Asegura que pago.id esté disponible

        # Verificar cierre por saldo
        if credito.saldo_capital <= 0:
            credito.activo = False
            credito.saldo_capital = Decimal("0.00")

        return pago
