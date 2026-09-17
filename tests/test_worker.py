import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from app.database import Base
from app.models import HouseAd, SearchQuery, HouseAdCreate
from app.seed import seed_initial_regions, INITIAL_SEARCH_QUERIES
from app.worker import process_single_search_query

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_seed_initial_regions(db_session):
    with patch("app.seed.AsyncSessionLocal", TestingSessionLocal):
        count = await seed_initial_regions()
        assert count == 3

        # Executando novamente não deve duplicar
        count_again = await seed_initial_regions()
        assert count_again == 0

        # Verifica registros no banco
        result = await db_session.execute(select(SearchQuery))
        queries = list(result.scalars().all())
        assert len(queries) == 3
        names = [q.name for q in queries]
        assert "SP - São Paulo e Região (Aluguel)" in names
        assert "RJ - Rio de Janeiro e Região (Aluguel)" in names
        assert "PR - Curitiba e Região (Aluguel)" in names


@pytest.mark.asyncio
async def test_process_single_search_query(db_session):
    # Insere uma query
    sq = SearchQuery(
        name="SP - Teste",
        olx_url="https://olx.com.br/sp",
        is_active=True,
    )
    db_session.add(sq)
    await db_session.commit()
    await db_session.refresh(sq)

    # Cria mock de scraper que retorna 2 anúncios
    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = [
        HouseAdCreate(
            external_id="sp-101",
            title="Apartamento SP 101",
            price_val=2200.0,
            price_str="R$ 2.200,00",
            location="São Paulo, Pinheiros",
            url="https://olx.com.br/sp-101",
            latitude=-23.5505,
            longitude=-46.6333,
        ),
        HouseAdCreate(
            external_id="sp-102",
            title="Casa SP 102",
            price_val=3500.0,
            price_str="R$ 3.500,00",
            location="São Paulo, Moema",
            url="https://olx.com.br/sp-102",
            latitude=-23.5505,
            longitude=-46.6333,
        ),
    ]

    mock_notifier = AsyncMock()
    mock_notifier.notify_ad.return_value = True

    with patch("app.worker.AsyncSessionLocal", TestingSessionLocal):
        result = await process_single_search_query(
            query_id=sq.id,
            query_name=sq.name,
            olx_url=sq.olx_url,
            scraper=mock_scraper,
            notifier=mock_notifier,
        )

        assert result["found"] == 2
        assert result["new"] == 2
        assert result["notified"] == 2

        # Verifica se foram persistidos no banco
        db_ads = (await db_session.execute(select(HouseAd))).scalars().all()
        assert len(db_ads) == 2
        assert db_ads[0].search_query_id == sq.id
        assert db_ads[0].notified_telegram is True

        # Executando novamente com os mesmos anúncios deve detectar 0 novos
        result2 = await process_single_search_query(
            query_id=sq.id,
            query_name=sq.name,
            olx_url=sq.olx_url,
            scraper=mock_scraper,
            notifier=mock_notifier,
        )
        assert result2["found"] == 2
        assert result2["new"] == 0
        assert result2["notified"] == 0
