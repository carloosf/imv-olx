from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./data/houses.db",
        description="URL assíncrona do banco de dados (SQLite ou PostgreSQL)"
    )

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(
        default=None,
        description="Token do Bot gerado pelo @BotFather no Telegram"
    )
    TELEGRAM_CHAT_ID: Optional[str] = Field(
        default=None,
        description="ID do Chat ou Canal do Telegram para envio dos alertas"
    )


    # Scheduler
    CHECK_INTERVAL_MINUTES: int = Field(
        default=10,
        ge=1,
        description="Intervalo em minutos para checagem de novos anúncios"
    )

    # Server settings
    APP_HOST: str = Field(default="0.0.0.0", description="Host do servidor FastAPI")
    APP_PORT: int = Field(default=8000, description="Porta do servidor FastAPI")
    DEBUG: bool = Field(default=False, description="Modo debug")
    ADMIN_SECRET_KEY: str = Field(
        default="admin_secret_key_change_me",
        description="Chave secreta para autorização de endpoints administrativos (ex: disparo manual de scraping)"
    )


def get_settings() -> Settings:
    """Retorna as configurações da aplicação lendo o .env."""
    return Settings()
