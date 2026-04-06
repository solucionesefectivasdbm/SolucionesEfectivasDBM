"""
services/audit_service.py — Registro de auditoría.

DECISIÓN TÉCNICA: La auditoría se escribe en la misma transacción
que la operación principal. Si el audit falla, toda la operación
hace rollback. Esto garantiza consistencia: nunca tendremos una
operación sin su log de auditoría correspondiente.

REGLA CRÍTICA: nunca loguear el valor real de password_hash.
"""
import uuid
from datetime import datetime

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog, AccionAudit


CAMPO_SENSIBLE_PASSWORD = "password_hash"
VALOR_CAMBIO_PASSWORD = "[CAMBIO DE CONTRASEÑA]"


async def registrar_cambio(
    db: AsyncSession,
    entidad: str,
    entidad_id: uuid.UUID,
    accion: AccionAudit,
    usuario_id: uuid.UUID,
    ip_origen: str,
    campo: Optional[str] = None,
    valor_anterior: Optional[str] = None,
    valor_nuevo: Optional[str] = None,
) -> None:
    """
    Registra un cambio en el audit_log.

    Args:
        db: Sesión activa de base de datos.
        entidad: Nombre de la tabla afectada ("clientes", "creditos", etc).
        entidad_id: UUID del registro afectado.
        accion: CREATE, UPDATE o DELETE.
        usuario_id: UUID del usuario que realizó la acción.
        ip_origen: IP del cliente.
        campo: Nombre del campo modificado (solo para UPDATE).
        valor_anterior: Valor antes del cambio.
        valor_nuevo: Valor después del cambio.
    """
    # Protección: nunca loguear contraseñas reales
    if campo == CAMPO_SENSIBLE_PASSWORD:
        valor_anterior = VALOR_CAMBIO_PASSWORD if valor_anterior else None
        valor_nuevo = VALOR_CAMBIO_PASSWORD if valor_nuevo else None

    log = AuditLog(
        entidad=entidad,
        entidad_id=entidad_id,
        accion=accion,
        campo_modificado=campo,
        valor_anterior=str(valor_anterior) if valor_anterior is not None else None,
        valor_nuevo=str(valor_nuevo) if valor_nuevo is not None else None,
        usuario_id=usuario_id,
        fecha_accion=datetime.utcnow(),
        ip_origen=ip_origen,
    )
    db.add(log)
    # No hacemos flush aquí — el commit lo maneja get_db()


async def registrar_creacion(
    db: AsyncSession,
    entidad: str,
    entidad_id: uuid.UUID,
    usuario_id: uuid.UUID,
    ip_origen: str,
) -> None:
    """Atajo para registrar una creación."""
    await registrar_cambio(
        db=db,
        entidad=entidad,
        entidad_id=entidad_id,
        accion=AccionAudit.CREATE,
        usuario_id=usuario_id,
        ip_origen=ip_origen,
    )


async def registrar_eliminacion(
    db: AsyncSession,
    entidad: str,
    entidad_id: uuid.UUID,
    usuario_id: uuid.UUID,
    ip_origen: str,
) -> None:
    """Atajo para registrar un borrado lógico."""
    await registrar_cambio(
        db=db,
        entidad=entidad,
        entidad_id=entidad_id,
        accion=AccionAudit.DELETE,
        usuario_id=usuario_id,
        ip_origen=ip_origen,
    )


async def registrar_actualizacion_campos(
    db: AsyncSession,
    entidad: str,
    entidad_id: uuid.UUID,
    usuario_id: uuid.UUID,
    ip_origen: str,
    cambios: dict,  # {campo: (valor_anterior, valor_nuevo)}
) -> None:
    """
    Registra múltiples campos modificados en una sola operación UPDATE.
    Crea un registro de audit_log por cada campo modificado.
    """
    for campo, (anterior, nuevo) in cambios.items():
        if anterior != nuevo:  # Solo registrar si realmente cambió
            await registrar_cambio(
                db=db,
                entidad=entidad,
                entidad_id=entidad_id,
                accion=AccionAudit.UPDATE,
                usuario_id=usuario_id,
                ip_origen=ip_origen,
                campo=campo,
                valor_anterior=anterior,
                valor_nuevo=nuevo,
            )
