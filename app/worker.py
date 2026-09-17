import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import HouseAd, HouseAdCreate, SearchQuery
from app.scraper import OLXScraper
from app.telegram import TelegramNotifier

logger = logging.getLogger("imv_olx.worker")


async def process_single_search_query(
    query_id: int,
    query_name: str,
    olx_url: str,
    scraper: OLXScraper,
    notifier: TelegramNotifier,
) -> dict:
    """
    Processa uma única busca da OLX:
    1. Executa scraping da página 1 via extração da tag __NEXT_DATA__.
    2. Identifica e insere apenas anúncios inéditos (external_id novo).
    3. Dispara alertas no Telegram apenas para os novos anúncios cadastrados.
    """
    logger.info(f"[Worker] Iniciando scraping para: '{query_name}' (ID: {query_id}) -> {olx_url}")
    
    # 1. Executa o scraping da página
    ads_found: List[HouseAdCreate] = await scraper.scrape(olx_url)
    found_count = len(ads_found)
    
    if not ads_found:
        logger.warning(f"[Worker] Nenhum anúncio retornado para '{query_name}'.")
        return {"query_id": query_id, "found": 0, "new": 0, "notified": 0}

    # 2. Abre sessão dedicada para consultar e salvar os novos anúncios
    new_count = 0
    notified_count = 0

    async with AsyncSessionLocal() as session:
        external_ids = [ad.external_id for ad in ads_found]
        existing_result = await session.execute(
            select(HouseAd.external_id).where(HouseAd.external_id.in_(external_ids))
        )
        existing_ids = set(existing_result.scalars().all())

        new_ads = [ad for ad in ads_found if ad.external_id not in existing_ids]
        new_count = len(new_ads)

        logger.info(
            f"[Worker] Região '{query_name}': {found_count} anúncios na página, {new_count} novos para cadastrar."
        )

        if not new_ads:
            return {"query_id": query_id, "found": found_count, "new": 0, "notified": 0}

        # Ordena do mais antigo para o mais recente para disparar notificações na ordem correta
        new_ads.sort(key=lambda item: item.created_at_olx or datetime.min)

        # 3. Insere no SQLite associando search_query_id
        saved_entities: List[HouseAd] = []
        for item in new_ads:
            pval = item.price_val if item.price_val is not None else item.price
            pstr = item.price_str or item.price_formatted or "Sob Consulta"
            
            ad_entity = HouseAd(
                search_query_id=query_id,
                external_id=item.external_id,
                title=item.title,
                price_val=pval,
                price_str=pstr,
                location=item.location,
                latitude=item.latitude,
                longitude=item.longitude,
                url=item.url,
                image_url=item.image_url,
                created_at_olx=item.created_at_olx,
                created_at=datetime.now(timezone.utc),
                notified_telegram=False,
            )
            session.add(ad_entity)
            saved_entities.append(ad_entity)

        await session.commit()

        # Recarrega entidades para obter IDs
        for entity in saved_entities:
            await session.refresh(entity)

        # 4. Dispara notificações no Telegram para os novos anúncios
        for entity in saved_entities:
            try:
                success = await notifier.notify_ad(entity)
                if success:
                    entity.notified_telegram = True
                    notified_count += 1
                    # Intervalo seguro para não estourar rate limit da API do Telegram
                    await asyncio.sleep(0.5)
            except Exception as exc:
                logger.error(f"[Worker] Erro ao enviar notificação do anúncio {entity.external_id}: {exc}")

        await session.commit()

    logger.info(
        f"[Worker] Concluído '{query_name}': {new_count} salvos, {notified_count} notificados no Telegram."
    )
    return {
        "query_id": query_id,
        "found": found_count,
        "new": new_count,
        "notified": notified_count,
    }


async def run_worker_loop():
    """
    Loop contínuo do Worker em background com fila controlada (round-robin com jitter):
    1. Consulta todas as SearchQuery ativas (is_active == True).
    2. Itera sequencialmente sobre cada uma com delay de segurança entre 5s e 8s.
    3. Ao finalizar a rodada, aguarda intervalo de aproximadamente 10 minutos (600s + jitter).
    4. Trata cancelamento de forma graciosa sem deixar conexões presas.
    """
    logger.info("[Worker] Iniciando loop contínuo de monitoramento multi-região...")
    scraper = OLXScraper()
    notifier = TelegramNotifier()
    settings = get_settings()

    # Delay inicial breve antes da primeira rodada (3s a 6s)
    try:
        await asyncio.sleep(random.uniform(3.0, 6.0))
    except asyncio.CancelledError:
        logger.info("[Worker] Worker cancelado durante inicialização.")
        return

    while True:
        try:
            logger.info("[Worker] === Iniciando nova rodada de monitoramento ===")
            
            # 1. Consulta buscas ativas no SQLite com sessão isolada
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SearchQuery).where(SearchQuery.is_active == True).order_by(SearchQuery.id.asc())
                )
                active_queries = list(result.scalars().all())

            if not active_queries:
                logger.warning("[Worker] Nenhuma busca ativa encontrada na tabela SearchQuery. Aguardando 60s...")
                await asyncio.sleep(60.0)
                continue

            logger.info(f"[Worker] {len(active_queries)} regiões ativas encontradas para processamento nesta rodada.")

            # 2. Processa cada busca sequencialmente com delay entre requisições
            for index, query in enumerate(active_queries):
                try:
                    await process_single_search_query(
                        query_id=query.id,
                        query_name=query.name,
                        olx_url=query.olx_url,
                        scraper=scraper,
                        notifier=notifier,
                    )
                except Exception as exc:
                    logger.exception(f"[Worker] Falha isolada na busca ID {query.id} ('{query.name}'): {exc}")

                # Se não for a última query da rodada, aplica delay de segurança (5 a 8 segundos)
                if index < len(active_queries) - 1:
                    safety_delay = random.uniform(5.0, 8.0)
                    logger.info(f"[Worker] Aplicando delay de segurança de {safety_delay:.2f}s antes da próxima região...")
                    await asyncio.sleep(safety_delay)

            # 3. Intervalo de ciclo completo (~10 minutos com jitter)
            base_seconds = settings.CHECK_INTERVAL_MINUTES * 60 if settings.CHECK_INTERVAL_MINUTES else 600
            jitter_offset = random.uniform(-15.0, 30.0)
            round_interval = max(60.0, base_seconds + jitter_offset)
            
            logger.info(
                f"[Worker] === Rodada concluída com sucesso! Próxima execução em {round_interval:.1f}s (~{round_interval/60:.1f} min) ==="
            )
            await asyncio.sleep(round_interval)

        except asyncio.CancelledError:
            logger.info("[Worker] Sinal de cancelamento recebido. Encerrando worker de forma graciosa...")
            break
        except Exception as exc:
            logger.exception(f"[Worker] Erro inesperado no loop principal: {exc}. Aguardando 30s para retomar...")
            try:
                await asyncio.sleep(30.0)
            except asyncio.CancelledError:
                break
