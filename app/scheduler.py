import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import get_settings
from app.services import run_sync_routine

logger = logging.getLogger("imv_olx.scheduler")

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    """Inicializa o agendador assíncrono de tarefas em background."""
    settings = get_settings()

    scheduler.add_job(
        run_sync_routine,
        trigger=IntervalTrigger(minutes=settings.CHECK_INTERVAL_MINUTES),
        id="olx_monitor_job",
        name="Monitoramento Periódico de Imóveis OLX",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info(
        f"APScheduler inicializado com sucesso. Intervalo de checagem: a cada {settings.CHECK_INTERVAL_MINUTES} minutos."
    )


def shutdown_scheduler() -> None:
    """Finaliza o agendador assíncrono de forma graciosa."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler finalizado com sucesso.")
