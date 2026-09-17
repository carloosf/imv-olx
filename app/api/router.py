from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    HouseAdFilter,
    HouseAdListResponse,
    HouseAdRead,
    MonitorStatus,
    MonitorTriggerResponse,
)
from app.services import (
    get_house_ad_by_id,
    get_monitor_status,
    list_house_ads,
    run_sync_routine,
)

router = APIRouter(prefix="/api", tags=["Imóveis & Monitor"])


@router.get("/houses", response_model=HouseAdListResponse, summary="Listar imóveis com filtros e paginação")
async def get_houses(
    limit: int = Query(default=20, ge=1, le=100, description="Quantidade máxima de itens por página"),
    offset: int = Query(default=0, ge=0, description="Deslocamento para paginação"),
    min_price: Optional[float] = Query(default=None, ge=0, description="Preço mínimo em R$"),
    max_price: Optional[float] = Query(default=None, ge=0, description="Preço máximo em R$"),
    search: Optional[str] = Query(default=None, description="Busca textual por título, bairro ou cidade"),
    notified_only: Optional[bool] = Query(default=None, description="Filtrar apenas anúncios já notificados"),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna a listagem de imóveis capturados da OLX salvos no banco de dados.
    Permite ordenação cronológica decrescente, busca textual e filtragem por faixa de preço.
    """
    filters = HouseAdFilter(
        min_price=min_price,
        max_price=max_price,
        search=search,
        notified_only=notified_only,
        limit=limit,
        offset=offset,
    )

    items, total = await list_house_ads(db, filters)
    return HouseAdListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[HouseAdRead.model_validate(item) for item in items],
    )


@router.get("/houses/{id}", response_model=HouseAdRead, summary="Obter detalhes de um imóvel")
async def get_house_detail(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Retorna os dados detalhados de um imóvel salvo com base no ID interno."""
    ad = await get_house_ad_by_id(db, id)
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Imóvel com ID {id} não foi encontrado.",
        )
    return HouseAdRead.model_validate(ad)


@router.post(
    "/monitor/trigger",
    response_model=MonitorTriggerResponse,
    summary="Disparar sincronização manual da OLX",
)
async def trigger_monitor_sync(
    background_tasks: BackgroundTasks,
    sync_now: bool = Query(
        default=True,
        description="Se True, aguarda o término da execução antes de responder; se False, agenda em background.",
    ),
    custom_url: Optional[str] = Query(
        default=None,
        description="URL customizada opcional para scraping pontual",
    ),
):
    """
    Endpoint administrativo para disparar a rotina de extração da OLX manualmente.
    Captura os novos anúncios, salva no banco e envia alertas no Telegram.
    """
    if sync_now:
        result = await run_sync_routine(custom_url=custom_url)
        return MonitorTriggerResponse(
            message=result.get("message", "Rotina executada."),
            status=result.get("status", "completed"),
            found_count=result.get("found_count", 0),
            new_count=result.get("new_count", 0),
            notified_count=result.get("notified_count", 0),
        )
    else:
        background_tasks.add_task(run_sync_routine, custom_url)
        return MonitorTriggerResponse(
            message="Sincronização agendada em background com sucesso.",
            status="scheduled",
            found_count=0,
            new_count=0,
            notified_count=0,
        )


@router.get("/status", response_model=MonitorStatus, summary="Status do monitor e estatísticas")
async def get_status(
    db: AsyncSession = Depends(get_db),
):
    """Retorna o status atual do serviço de monitoramento periódico e quantidade total de registros."""
    return await get_monitor_status(db)
