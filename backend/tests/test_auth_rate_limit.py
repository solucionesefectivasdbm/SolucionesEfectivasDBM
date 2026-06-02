"""
tests/test_auth_rate_limit.py — Rate limiting de login y guard del secret_key.

Cubre:
- Bloqueo de login tras N intentos fallidos por IP.
- Limpieza del contador tras login exitoso.
- Expiración de fallos fuera de la ventana de bloqueo.
- Rechazo del secret_key por defecto en producción.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import INSECURE_SECRET_KEY, Settings
from app.routers import auth as auth_module


@pytest.fixture(autouse=True)
def _limpiar_estado():
    """Cada test arranca con el almacén de fallos vacío."""
    auth_module._failed_login_attempts.clear()
    yield
    auth_module._failed_login_attempts.clear()


class TestRateLimitLogin:
    def test_no_bloqueado_inicialmente(self):
        assert auth_module._login_bloqueado("1.2.3.4") is False

    def test_se_bloquea_tras_max_intentos(self):
        ip = "9.9.9.9"
        for _ in range(auth_module.settings.login_max_attempts):
            auth_module._registrar_fallo_login(ip)
        assert auth_module._login_bloqueado(ip) is True

    def test_un_intento_por_debajo_del_maximo_no_bloquea(self):
        ip = "9.9.9.9"
        for _ in range(auth_module.settings.login_max_attempts - 1):
            auth_module._registrar_fallo_login(ip)
        assert auth_module._login_bloqueado(ip) is False

    def test_login_exitoso_limpia_fallos(self):
        ip = "8.8.8.8"
        for _ in range(auth_module.settings.login_max_attempts):
            auth_module._registrar_fallo_login(ip)
        auth_module._limpiar_fallos_login(ip)
        assert auth_module._login_bloqueado(ip) is False

    def test_fallos_vencidos_se_descartan(self):
        ip = "7.7.7.7"
        viejo = datetime.now(timezone.utc) - timedelta(
            minutes=auth_module.settings.login_block_minutes + 1
        )
        auth_module._failed_login_attempts[ip] = (
            [viejo] * auth_module.settings.login_max_attempts
        )
        assert auth_module._login_bloqueado(ip) is False

    def test_ips_independientes(self):
        ip_atacante = "6.6.6.6"
        for _ in range(auth_module.settings.login_max_attempts):
            auth_module._registrar_fallo_login(ip_atacante)
        assert auth_module._login_bloqueado(ip_atacante) is True
        # Otra IP no debe verse afectada.
        assert auth_module._login_bloqueado("5.5.5.5") is False


class TestSecretKeyGuard:
    def test_default_rechazado_en_produccion(self):
        with pytest.raises(ValueError):
            Settings(environment="production", secret_key=INSECURE_SECRET_KEY)

    def test_custom_aceptado_en_produccion(self):
        s = Settings(
            environment="production",
            secret_key="una-clave-larga-unica-y-privada-123456",
        )
        assert s.is_production is True

    def test_default_permitido_en_desarrollo(self):
        s = Settings(environment="development", secret_key=INSECURE_SECRET_KEY)
        assert s.is_production is False
