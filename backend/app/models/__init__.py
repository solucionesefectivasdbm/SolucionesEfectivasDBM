"""
Importar todos los modelos aquí para que Alembic los descubra
automáticamente al generar migraciones.

IMPORTANTE: El orden de importación importa por las foreign keys.
"""
from app.models.usuario import Usuario, TipoUsuario  # noqa: F401
from app.models.receptor import Receptor, CuentaBancaria, TipoCuenta  # noqa: F401
from app.models.gestor import Gestor  # noqa: F401
from app.models.cliente import Cliente  # noqa: F401
from app.models.credito import Credito, TipoCredito, Periodicidad  # noqa: F401
from app.models.pago import Pago, TipoCuota, DestinoExcedente  # noqa: F401
from app.models.audit_log import AuditLog, AccionAudit  # noqa: F401
from app.models.token_revocado import TokenRevocado  # noqa: F401
