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

    # OLX Search
    OLX_SEARCH_URL: str = Field(
        default="https://www.olx.com.br/imoveis/aluguel/estado-pe/grande-recife/recife?pe=1800",
        description="URL com os filtros de busca de imóveis da OLX Brasil"
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


def get_settings() -> Settings:
    """Retorna as configurações da aplicação lendo o .env."""
    return Settings()
