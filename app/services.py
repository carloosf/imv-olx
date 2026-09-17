import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import (
    HouseAd,
    HouseAdCreate,
    HouseAdFilter,
    MonitorStatus,
    SearchQuery,
)
from app.scraper import OLXScraper
from app.telegram import TelegramNotifier

logger = logging.getLogger("imv_olx.services")

import random

# Estado global de monitoramento para consulta na API
monitor_state = {
    "is_running": False,
    "last_run_at": None,
    "last_run_status": "Aguardando primeira execução",
    "last_found_count": 0,
    "last_new_count": 0,
    "consecutive_errors": 0,
    "current_backoff_seconds": 0,
}


async def get_monitor_status(db: AsyncSession) -> MonitorStatus:
    """Retorna o status consolidado do serviço de monitoramento e contagem de registros."""
    settings = get_settings()
    total_query = select(func.count(HouseAd.id))
    total_result = await db.execute(total_query)
    total_count = total_result.scalar_one() or 0

    return MonitorStatus(
        is_running=monitor_state["is_running"],
        last_run_at=monitor_state["last_run_at"],
        last_run_status=monitor_state["last_run_status"],
        last_found_count=monitor_state["last_found_count"],
        last_new_count=monitor_state["last_new_count"],
        total_ads_stored=total_count,
        check_interval_minutes=settings.CHECK_INTERVAL_MINUTES,
    )


async def list_search_queries(db: AsyncSession) -> List[SearchQuery]:
    """Retorna a lista de buscas configuradas no banco."""
    query = select(SearchQuery).order_by(SearchQuery.id.asc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_dashboard_stats(db: AsyncSession, search_query_id: Optional[int] = None) -> Dict[str, Any]:
    """Calcula as métricas estatísticas agregadas (Total, Média de Preço, Menor Preço, Novos 24h)."""
    filters = []
    if search_query_id:
        filters.append(HouseAd.search_query_id == search_query_id)

    # 1. Total de imóveis
    total_query = select(func.count(HouseAd.id)).where(*filters)
    total_houses = (await db.execute(total_query)).scalar_one() or 0

    # 2. Preço médio
    avg_query = select(func.avg(HouseAd.price_val)).where(HouseAd.price_val > 0, *filters)
    avg_val = (await db.execute(avg_query)).scalar_one()

    # 3. Menor preço
    min_query = select(func.min(HouseAd.price_val)).where(HouseAd.price_val > 0, *filters)
    min_val = (await db.execute(min_query)).scalar_one()

    # 4. Novos nas últimas 24 horas
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    new_24h_query = select(func.count(HouseAd.id)).where(HouseAd.created_at >= since_24h, *filters)
    new_today = (await db.execute(new_24h_query)).scalar_one() or 0

    def format_brl(val: Optional[float]) -> str:
        if val is None or val == 0:
            return "N/A"
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    return {
        "total_houses": total_houses,
        "avg_price_val": avg_val or 0.0,
        "avg_price": format_brl(avg_val),
        "min_price_val": min_val or 0.0,
        "min_price": format_brl(min_val),
        "new_today": new_today,
    }


async def list_house_ads(
    db: AsyncSession,
    filters: HouseAdFilter,
) -> Tuple[List[HouseAd], int]:
    """Retorna lista paginada e filtrada de anúncios salvos no banco."""
    query = select(HouseAd)
    count_query = select(func.count(HouseAd.id))

    # Filtro por search_query_id
    if filters.search_query_id:
        query = query.where(HouseAd.search_query_id == filters.search_query_id)
        count_query = count_query.where(HouseAd.search_query_id == filters.search_query_id)

    # Filtro por preço mínimo
    if filters.min_price is not None:
        query = query.where(HouseAd.price_val >= filters.min_price)
        count_query = count_query.where(HouseAd.price_val >= filters.min_price)

    # Filtro por preço máximo
    if filters.max_price is not None:
        query = query.where(HouseAd.price_val <= filters.max_price)
        count_query = count_query.where(HouseAd.price_val <= filters.max_price)

    # Filtro de texto (busca no título ou localização)
    if filters.search:
        search_term = f"%{filters.search.strip()}%"
        criteria = or_(
            HouseAd.title.ilike(search_term),
            HouseAd.location.ilike(search_term),
        )
        query = query.where(criteria)
        count_query = count_query.where(criteria)

    # Filtro por notificado
    if filters.notified_only is not None:
        query = query.where(HouseAd.notified_telegram == filters.notified_only)
        count_query = count_query.where(HouseAd.notified_telegram == filters.notified_only)

    # Total de registros
    total_result = await db.execute(count_query)
    total = total_result.scalar_one() or 0

    # Ordenação e paginação (mais recentes primeiro)
    query = query.order_by(HouseAd.created_at.desc()).offset(filters.offset).limit(filters.limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return list(items), total


async def get_house_ad_by_id(db: AsyncSession, ad_id: int) -> Optional[HouseAd]:
    """Busca um imóvel pelo ID primário."""
    query = select(HouseAd).where(HouseAd.id == ad_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def run_sync_routine(custom_url: Optional[str] = None, query_id: Optional[int] = None) -> dict:
    """
    Rotina central de sincronização multi-região (disparada manualmente).
    Itera sobre todas as regiões ativas cadastradas no banco ou uma URL customizada.
    """
    global monitor_state
    if monitor_state["is_running"]:
        logger.info("Uma rotina de sincronização já está em andamento. Ignorando solicitação duplicada.")
        return {
            "status": "already_running",
            "message": "Sincronização já em andamento.",
            "found_count": 0,
            "new_count": 0,
            "notified_count": 0,
        }

    monitor_state["is_running"] = True
    scraper = OLXScraper()
    notifier = TelegramNotifier()

    total_found = 0
    total_new = 0
    total_notified = 0

    try:
        from app.worker import process_single_search_query

        async with AsyncSessionLocal() as session:
            if custom_url:
                active_queries = [SearchQuery(id=None, name="Custom", olx_url=custom_url)]
            elif query_id:
                result = await session.execute(select(SearchQuery).where(SearchQuery.id == query_id))
                active_queries = list(result.scalars().all())
            else:
                result = await session.execute(select(SearchQuery).where(SearchQuery.is_active == True).order_by(SearchQuery.id.asc()))
                active_queries = list(result.scalars().all())

        if not active_queries:
             logger.warning("Nenhuma busca ativa encontrada para sincronização manual.")
             return {
                 "status": "error",
                 "message": "Nenhuma busca ativa configurada.",
                 "found_count": 0, "new_count": 0, "notified_count": 0,
             }

        for idx, query in enumerate(active_queries):
            try:
                res = await process_single_search_query(
                    query_id=query.id,
                    query_name=query.name,
                    olx_url=query.olx_url,
                    scraper=scraper,
                    notifier=notifier
                )
                total_found += res.get("found", 0)
                total_new += res.get("new", 0)
                total_notified += res.get("notified", 0)

                # Update last_synced_at
                if query.id:
                    query.last_synced_at = datetime.now(timezone.utc)
                    session.add(query)
                    await session.commit()

            except Exception as e:
                logger.error(f"Erro ao processar região '{query.name}': {e}")
                monitor_state["consecutive_errors"] += 1
            
            if idx < len(active_queries) - 1:
                await asyncio.sleep(2.0)

        monitor_state.update({
            "last_run_at": datetime.now(timezone.utc),
            "last_run_status": f"Sucesso (Manual)",
            "last_found_count": total_found,
            "last_new_count": total_new,
            "consecutive_errors": 0,
        })
        logger.info(f"Sincronização manual concluída: {total_found} enc, {total_new} novos, {total_notified} notifs.")

    except Exception as e:
        logger.error(f"Erro fatal na rotina de sincronização manual: {e}")
        monitor_state.update({
            "last_run_status": f"Erro (Manual): {str(e)}",
            "consecutive_errors": monitor_state["consecutive_errors"] + 1
        })
    finally:
        monitor_state["is_running"] = False
        await scraper.close()
        
    return {
        "status": "completed",
        "message": "Rotina executada.",
        "found_count": total_found,
        "new_count": total_new,
        "notified_count": total_notified,
    }


