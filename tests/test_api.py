import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.database import Base, get_db
from app.models import HouseAd

# Test database setup (in-memory SQLite)
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


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_houses_empty(client):
    response = await client.get("/api/houses")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_create_and_get_houses(client, db_session):
    # Insere registros simulados
    ad1 = HouseAd(
        external_id="olx-100",
        title="Casa Moderna no Morumbi",
        price=750000.0,
        price_formatted="R$ 750.000,00",
        location="São Paulo, Morumbi",
        url="https://olx.com.br/imovel-100",
        image_url="https://img.olx.com.br/100.jpg",
        notified_telegram=True,
    )
    ad2 = HouseAd(
        external_id="olx-200",
        title="Apartamento Compacto nos Jardins",
        price=1500000.0,
        price_formatted="R$ 1.500.000,00",
        location="São Paulo, Jardins",
        url="https://olx.com.br/imovel-200",
        image_url="https://img.olx.com.br/200.jpg",
        notified_telegram=False,
    )
    db_session.add_all([ad1, ad2])
    await db_session.commit()

    # 1. Listagem completa
    response = await client.get("/api/houses")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2

    # 2. Filtro por preço
    response_filter = await client.get("/api/houses?max_price=800000")
    assert response_filter.status_code == 200
    data_filter = response_filter.json()
    assert data_filter["total"] == 1
    assert data_filter["items"][0]["external_id"] == "olx-100"

    # 3. Filtro por texto
    response_search = await client.get("/api/houses?search=Jardins")
    assert response_search.status_code == 200
    data_search = response_search.json()
    assert data_search["total"] == 1
    assert data_search["items"][0]["external_id"] == "olx-200"

    # 4. Detalhes por ID
    first_id = data["items"][0]["id"]
    response_detail = await client.get(f"/api/houses/{first_id}")
    assert response_detail.status_code == 200
    assert response_detail.json()["id"] == first_id


@pytest.mark.asyncio
async def test_get_status(client):
    response = await client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "target_search_url" in data
    assert "check_interval_minutes" in data


@pytest.mark.asyncio
async def test_html_dashboard(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "Monitor de Imóveis OLX Brasil" in response.text
    assert "Sincronizar Agora" in response.text
