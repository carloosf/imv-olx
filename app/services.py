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
        target_search_url=settings.OLX_SEARCH_URL,
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


async def run_sync_routine(custom_url: Optional[str] = None) -> dict:
    """
    Rotina central de sincronização:
    1. Faz scraping da URL da OLX.
    2. Identifica anúncios novos comparando external_id.
    3. Persiste novos registros no banco.
    4. Dispara alertas no Telegram em ordem cronológica (mais antigo para mais recente).
    5. Atualiza o status de notificação.
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
    settings = get_settings()
    target_url = custom_url or settings.OLX_SEARCH_URL
    scraper = OLXScraper()
    notifier = TelegramNotifier()

    found_count = 0
    new_count = 0
    notified_count = 0

    # 1. Aplica Jitter aleatório (3 a 15 segundos) para que as requisições não tenham padrão fixo de relógio
    if not custom_url:
        jitter_seconds = random.randint(3, 15)
        logger.info(f"Aplicando jitter aleatório de {jitter_seconds}s antes do scrape...")
        await asyncio.sleep(jitter_seconds)

    try:
        logger.info(f"Iniciando rotina de sincronização para: {target_url}")
        ads_found: List[HouseAdCreate] = await scraper.scrape(target_url)
        found_count = len(ads_found)

        if not ads_found:
            monitor_state["consecutive_errors"] += 1
            # Backoff progressivo caso ocorram falhas consecutivas
            backoff_min = min(60, 5 * (2 ** (monitor_state["consecutive_errors"] - 1)))
            monitor_state["current_backoff_seconds"] = backoff_min * 60
            logger.warning(
                f"Nenhum anúncio obtido (falhas consecutivas: {monitor_state['consecutive_errors']}). Backoff sugerido: {backoff_min} min."
            )
            monitor_state.update(
                {
                    "last_run_at": datetime.now(timezone.utc),
                    "last_run_status": f"Sem anúncios (tentativa {monitor_state['consecutive_errors']})",
                    "last_found_count": 0,
                    "last_new_count": 0,
                }
            )
            return {
                "status": "success",
                "message": "Nenhum anúncio encontrado na URL especificada.",
                "found_count": 0,
                "new_count": 0,
                "notified_count": 0,
            }

        # Reseta contador de erros em caso de sucesso
        monitor_state["consecutive_errors"] = 0
        monitor_state["current_backoff_seconds"] = 0

        async with AsyncSessionLocal() as session:
            # 1. Obtém lista de IDs externos encontrados
            external_ids = [ad.external_id for ad in ads_found]

            # 2. Consulta IDs que já existem no banco
            existing_query = select(HouseAd.external_id).where(HouseAd.external_id.in_(external_ids))
            existing_result = await session.execute(existing_query)
            existing_ids = set(existing_result.scalars().all())

            # 3. Filtra apenas os novos anúncios
            new_ads = [ad for ad in ads_found if ad.external_id not in existing_ids]
            new_count = len(new_ads)

            logger.info(f"Total encontrados: {found_count} | Novos anúncios: {new_count}")

            if not new_ads:
                monitor_state.update(
                    {
                        "last_run_at": datetime.now(timezone.utc),
                        "last_run_status": f"Sucesso ({found_count} analisados, 0 novos)",
                        "last_found_count": found_count,
                        "last_new_count": 0,
                    }
                )
                return {
                    "status": "success",
                    "message": f"Nenhum novo imóvel detectado ({found_count} verificados).",
                    "found_count": found_count,
                    "new_count": 0,
                    "notified_count": 0,
                }

            # 4. Ordena do mais antigo para o mais recente para disparar notificações na ordem correta
            def sort_key(item: HouseAdCreate):
                return item.created_at_olx or datetime.min

            new_ads.sort(key=sort_key)

            # 5. Salva os novos registros no banco
            saved_entities: List[HouseAd] = []

            # Busca ID da SearchQuery ativa correspondente
            default_query_result = await session.execute(select(SearchQuery.id).where(SearchQuery.is_active == True).limit(1))
            active_sq_id = default_query_result.scalar_one_or_none()

            for item in new_ads:
                pval = item.price_val if item.price_val is not None else item.price
                pstr = item.price_str or item.price_formatted or "Sob Consulta"
                ad_entity = HouseAd(
                    search_query_id=item.search_query_id or active_sq_id,
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

            # Recarrega os objetos salvos
            for entity in saved_entities:
                await session.refresh(entity)

            # 6. Dispara as notificações no Telegram
            for entity in saved_entities:
                try:
                    success = await notifier.notify_ad(entity)
                    if success:
                        entity.notified_telegram = True
                        notified_count += 1
                        # Pequeno intervalo para evitar rate limit na API do Telegram
                        await asyncio.sleep(0.5)
                except Exception as exc:
                    logger.error(f"Erro ao notificar anúncio {entity.external_id}: {exc}")

            await session.commit()

        monitor_state.update(
            {
                "last_run_at": datetime.now(timezone.utc),
                "last_run_status": f"Sucesso ({new_count} novos inseridos, {notified_count} notificados)",
                "last_found_count": found_count,
                "last_new_count": new_count,
            }
        )

        return {
            "status": "success",
            "message": f"Sincronização concluída: {new_count} novos anúncios salvos, {notified_count} alertas disparados.",
            "found_count": found_count,
            "new_count": new_count,
            "notified_count": notified_count,
        }

    except Exception as exc:
        logger.exception(f"Erro inesperado durante a rotina de sincronização: {exc}")
        monitor_state.update(
            {
                "last_run_at": datetime.now(timezone.utc),
                "last_run_status": f"Erro: {str(exc)}",
            }
        )
        return {
            "status": "error",
            "message": f"Erro na rotina de sincronização: {str(exc)}",
            "found_count": found_count,
            "new_count": new_count,
            "notified_count": notified_count,
        }
    finally:
        monitor_state["is_running"] = False
