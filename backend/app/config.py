"""
config.py — Configuración central con pydantic-settings.

Usamos pydantic-settings para leer variables de entorno con validación
automática de tipos. En producción (Railway) las variables se configuran
en el dashboard; en desarrollo se leen desde .env
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Base de datos
    database_url: str = "postgresql+asyncpg://user:password@localhost/soluciones_efectivas"

    # JWT
    secret_key: str = "cambia_esto_en_produccion"
    access_token_expire_minutes: int = 15
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


@lru_cache
def get_settings() -> Settings:
    """
    lru_cache garantiza que Settings se instancia una sola vez.
    Usar como dependencia: settings = Depends(get_settings)
    """
    return Settings()
