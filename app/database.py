import os
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy import event, text, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from app.config import get_settings

settings = get_settings()

# Assegura que o diretório para o banco SQLite existe se for arquivo local
connect_args = {}
if "sqlite" in settings.DATABASE_URL:
    db_path = settings.DATABASE_URL.split(":///")[-1]
    if db_path and db_path != ":memory:":
        parent_dir = Path(db_path).parent
        parent_dir.mkdir(parents=True, exist_ok=True)
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    connect_args=connect_args,
)

# Ativa PRAGMA WAL no SQLite para alta concorrência sem lock entre background worker e API
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection para sessões assíncronas do banco de dados."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Cria as tabelas no banco de dados na inicialização e executa auto-seed de SearchQuery."""
    from app.models import SearchQuery

    async with engine.begin() as conn:
        if "sqlite" in settings.DATABASE_URL:
            await conn.execute(text("PRAGMA journal_mode=WAL;"))
            await conn.execute(text("PRAGMA synchronous=NORMAL;"))
        await conn.run_sync(Base.metadata.create_all)

    # Auto-seed: Se a tabela SearchQuery estiver vazia mas existir OLX_SEARCH_URL no .env, cria o primeiro registro
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SearchQuery))
        first_query = result.scalars().first()
        if not first_query and settings.OLX_SEARCH_URL:
            default_query = SearchQuery(
                name="Busca Padrão (Recife até R$ 1.800)",
                olx_url=settings.OLX_SEARCH_URL,
                is_active=True,
            )
            session.add(default_query)
            await session.commit()

