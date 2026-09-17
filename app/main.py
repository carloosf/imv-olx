import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.router import router as api_router
from app.config import get_settings
from app.database import get_db, init_db
from app.models import HouseAdFilter
from app.services import get_monitor_status, list_house_ads
from app.worker import run_worker_loop

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("imv_olx.main")

settings = get_settings()

# Diretório de templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def format_datetime_br(value: datetime, fmt="%d/%m %H:%M"):
    if not value:
        return "Pendente"
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    local_dt = value.astimezone(ZoneInfo("America/Sao_Paulo"))
    return local_dt.strftime(fmt)


templates.env.filters["br_time"] = format_datetime_br


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação FastAPI:
    1. Inicializa o banco SQLite e executa o seed das 3 regiões caso não existam.
    2. Inicia a task do worker em background (fila sequencial controlada com jitter).
    3. Inicia polling de comandos interativos do Telegram.
    4. Ao encerrar, cancela e aguarda as tasks graciosamente.
    """
    logger.info("Iniciando aplicação imv-olx...")
    
    # 1. Inicializa tabelas do SQLite e executa o seed das regiões padrão
    await init_db()
    logger.info("Banco de dados e seeds inicializados com sucesso.")

    # 2. Inicia o Worker de monitoramento em background
    worker_task = asyncio.create_task(run_worker_loop(), name="olx_background_worker")

    # 3. Inicia escuta assíncrona de comandos interativos no Telegram (/verificar, /status)
    from app.telegram import TelegramNotifier
    from app.services import run_sync_routine
    telegram_task = asyncio.create_task(
        TelegramNotifier().start_polling(run_sync_routine),
        name="telegram_bot_polling",
    )

    yield

    # 4. Encerramento gracioso das tasks
    logger.info("Encerrando aplicação e finalizando background tasks...")
    worker_task.cancel()
    telegram_task.cancel()
    await asyncio.gather(worker_task, telegram_task, return_exceptions=True)
    logger.info("Aplicação e tarefas em background finalizadas.")



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

from starlette.requests import Request as StarletteRequest
from starlette.responses import PlainTextResponse
import traceback as tb_module

@app.exception_handler(Exception)
async def global_exception_handler(request: StarletteRequest, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {''.join(tb_module.format_exception(exc))}")
    return PlainTextResponse("Internal Server Error", status_code=500)


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
    limit: int = Query(default=1000),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """Renderiza o painel visual com a listagem dos imóveis, KPIs estatísticos e filtros."""
    try:
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
                "queries": queries_list,
                "queries_list": queries_list,
                "selected_query_id": query_id,
                "search_query": search,
                "min_price": min_price,
                "max_price": max_price,
            },
        )
    except Exception as e:
        import traceback
        logger.error(f"ROUTE ERROR: {traceback.format_exc()}")
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
