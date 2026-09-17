import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.router import router as api_router
from app.config import get_settings
from app.database import get_db, init_db
from app.models import HouseAdFilter
from app.scheduler import shutdown_scheduler, start_scheduler
from app.services import get_monitor_status, list_house_ads

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("imv_olx.main")

settings = get_settings()

# Diretório de templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação FastAPI (inicialização e encerramento)."""
    logger.info("Iniciando aplicação imv-olx...")
    # 1. Inicializa tabelas do banco de dados
    await init_db()
    logger.info("Banco de dados inicializado.")

    # 2. Inicializa o agendador periódico APScheduler
    start_scheduler()

    # 3. Inicia escuta assíncrona de comandos interativos no Telegram (/verificar, /status)
    from app.telegram import TelegramNotifier
    from app.services import run_sync_routine
    telegram_task = asyncio.create_task(TelegramNotifier().start_polling(run_sync_routine))

    yield

    # 4. Finaliza tarefas e agendador no shutdown
    logger.info("Encerrando aplicação...")
    telegram_task.cancel()
    shutdown_scheduler()


# Instância principal da aplicação FastAPI
app = FastAPI(
    title="Monitor de Imóveis OLX & Alertas Telegram",
    description="API assíncrona e serviço de monitoramento periódico de anúncios imobiliários da OLX Brasil com envio automático de alertas no Telegram.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusão dos endpoints da API
app.include_router(api_router)


from app.services import (
    get_dashboard_stats,
    get_monitor_status,
    list_house_ads,
    list_search_queries,
)


@app.get("/", response_class=HTMLResponse, summary="Painel Web Interativo de Imóveis")
async def index_page(
    request: Request,
    query_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None),
    max_price: Optional[float] = Query(default=None),
    limit: int = Query(default=60),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """Renderiza o painel visual com a listagem dos imóveis, KPIs estatísticos e filtros."""
    filters = HouseAdFilter(
        search_query_id=query_id,
        search=search,
        min_price=min_price,
        max_price=max_price,
        limit=limit,
        offset=offset,
    )
    houses, total = await list_house_ads(db, filters)
    stats_data = await get_dashboard_stats(db, search_query_id=query_id)
    queries_list = await list_search_queries(db)
    status_info = await get_monitor_status(db)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "houses": houses,
            "total": total,
            "stats": stats_data,
            "status": status_info,
            "queries_list": queries_list,
            "selected_query_id": query_id,
            "search_query": search,
            "min_price": min_price,
            "max_price": max_price,
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
