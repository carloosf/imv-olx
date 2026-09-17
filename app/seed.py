import logging
from typing import List, Dict, Any
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import SearchQuery

logger = logging.getLogger("imv_olx.seed")

INITIAL_SEARCH_QUERIES: List[Dict[str, Any]] = [
    {
        "name": "SP - São Paulo e Região (Aluguel)",
        "olx_url": "https://www.olx.com.br/imoveis/aluguel/estado-sp/sao-paulo-e-regiao",
        "is_active": True,
    },
    {
        "name": "RJ - Rio de Janeiro e Região (Aluguel)",
        "olx_url": "https://www.olx.com.br/imoveis/aluguel/estado-rj/rio-de-janeiro-e-regiao",
        "is_active": True,
    },
    {
        "name": "PR - Curitiba e Região (Aluguel)",
        "olx_url": "https://www.olx.com.br/imoveis/aluguel/estado-pr/regiao-de-curitiba-e-paranagua",
        "is_active": True,
    },
    {
        "name": "PE - Recife e Região (Aluguel)",
        "olx_url": "https://www.olx.com.br/imoveis/aluguel/estado-pe/grande-recife",
        "is_active": True,
    },
]


async def seed_initial_regions(force: bool = False) -> int:
    """
    Garante que as 3 regiões alvo padrão (SP, RJ, PR) estejam cadastradas na tabela SearchQuery com is_active=True.
    Retorna a quantidade de novas regiões inseridas.
    """
    async with AsyncSessionLocal() as session:
        inserted_count = 0
        for item in INITIAL_SEARCH_QUERIES:
            # Verifica se já existe uma query com a mesma URL ou nome
            check = await session.execute(
                select(SearchQuery).where(
                    (SearchQuery.name == item["name"]) | (SearchQuery.olx_url == item["olx_url"])
                )
            )
            if not check.scalars().first():
                query_obj = SearchQuery(
                    name=item["name"],
                    olx_url=item["olx_url"],
                    is_active=item["is_active"],
                )
                session.add(query_obj)
                inserted_count += 1

        if inserted_count > 0:
            await session.commit()
            logger.info(f"Seed concluído com sucesso: {inserted_count} novas regiões cadastradas no banco SQLite.")
        else:
            logger.info("Todas as 4 regiões alvo padrão já constam na tabela SearchQuery.")

        return inserted_count



if __name__ == "__main__":
    import asyncio
    from app.database import init_db

    async def main():
        await init_db()
        count = await seed_initial_regions(force=True)
        print(f"Seed finalizado: {count} novas buscas cadastradas.")

    asyncio.run(main())
