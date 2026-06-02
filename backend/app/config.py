"""
config.py — Configuración central con pydantic-settings.

Usamos pydantic-settings para leer variables de entorno con validación
automática de tipos. En producción (Railway) las variables se configuran
en el dashboard; en desarrollo se leen desde .env
"""
from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor por defecto inseguro del secret_key. Se rechaza explícitamente en
# producción (ver _validar_secret_key_produccion) para evitar que la app
# arranque firmando JWTs con una clave pública conocida.
INSECURE_SECRET_KEY = "cambia_esto_en_produccion"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Base de datos
    database_url: str = "postgresql+asyncpg://user:password@localhost/soluciones_efectivas"

    # JWT
    secret_key: str = INSECURE_SECRET_KEY
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # CORS (separar multiples origenes con coma)
    allowed_origins: str = "http://localhost:5173"

    # Entorno: development | production
    environment: str = "development"

    # Bcrypt
    bcrypt_rounds: int = 12

    # Rate limiting: max intentos de login por IP en 15 min
    login_max_attempts: int = 10
    login_block_minutes: int = 30

    # Puerto (Railway inyecta $PORT)
    port: int = 8000

    @property
    def database_url_async(self) -> str:
        """
        Railway provee DATABASE_URL con prefijo 'postgresql://'
        pero asyncpg necesita 'postgresql+asyncpg://'.
        Esta propiedad normaliza el formato automáticamente.
        """
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _validar_secret_key_produccion(self) -> "Settings":
        """
        Impide arrancar en producción con el secret_key por defecto.

        Sin este guard, si la variable de entorno SECRET_KEY falta en el
        deploy, la app booteaba firmando JWTs con una clave pública conocida,
        permitiendo forjar tokens de cualquier usuario (incluido admin).
        """
        if self.is_production and self.secret_key == INSECURE_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY no puede usar el valor por defecto en producción. "
                "Configure una clave secreta única y privada en las variables "
                "de entorno antes de desplegar."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """
    lru_cache garantiza que Settings se instancia una sola vez.
    Usar como dependencia: settings = Depends(get_settings)
    """
    return Settings()
