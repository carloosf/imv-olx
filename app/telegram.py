import asyncio
from datetime import datetime, timezone
import html
import logging
from typing import Optional
from zoneinfo import ZoneInfo
import httpx

from app.config import get_settings
from app.models import HouseAd

logger = logging.getLogger("imv_olx.telegram")


BRAZIL_TZ = ZoneInfo("America/Recife")


def format_br_datetime(dt: Optional[datetime]) -> str:
    """Converte qualquer datetime para o horário oficial brasileiro (Recife/Brasília UTC-3)."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(BRAZIL_TZ)
    return local_dt.strftime("%d/%m/%Y às %H:%M")


class TelegramNotifier:
    """Serviço assíncrono para envio de notificações formatadas para o Telegram."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 15.0,
    ):
        settings = get_settings()
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    @property
    def is_configured(self) -> bool:
        """Verifica se o token e chat_id estão devidamente configurados."""
        return bool(self.bot_token and self.chat_id and not str(self.bot_token).startswith("123456789:ABCdef"))

    def _build_html_caption(self, ad: HouseAd) -> str:
        """Constrói a mensagem formatada em HTML para o Telegram."""
        title_safe = html.escape(ad.title or "Imóvel Encontrado")
        price_safe = html.escape(ad.price_formatted or "Sob Consulta")
        location_safe = html.escape(ad.location or "Não informada")
        url_safe = html.escape(ad.url)

        date_str = ""
        if ad.created_at_olx:
            date_str = f"\n📅 <b>Publicado em:</b> {format_br_datetime(ad.created_at_olx)}"

        message = (
            f"🏡 <b>NOVO IMÓVEL NA OLX!</b>\n\n"
            f"📌 <b>Título:</b> {title_safe}\n"
            f"💰 <b>Valor:</b> {price_safe}\n"
            f"📍 <b>Localização:</b> {location_safe}"
            f"{date_str}\n\n"
            f"🔗 <a href='{url_safe}'>Abrir anúncio na OLX</a>"
        )
        return message

    async def notify_ad(self, ad: HouseAd) -> bool:
        """Dispara a notificação de um imóvel para o chat configurado no Telegram."""
        if not self.is_configured or not self.base_url:
            logger.info(
                f"[Simulação Telegram] Alerta para o imóvel '{ad.title}' ({ad.url}) - Bot não configurado."
            )
            return True

        message_html = self._build_html_caption(ad)

        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "👉 Ver Anúncio na OLX",
                        "url": ad.url,
                    }
                ]
            ]
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # 1. Tenta enviar como foto caso possua URL de imagem válida
            if ad.image_url and ad.image_url.startswith("http"):
                try:
                    payload = {
                        "chat_id": self.chat_id,
                        "photo": ad.image_url,
                        "caption": message_html,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup,
                    }
                    response = await client.post(
                        f"{self.base_url}/sendPhoto",
                        json=payload,
                    )
                    if response.status_code == 200:
                        logger.info(f"Notificação com foto enviada com sucesso para o anúncio ID: {ad.external_id}")
                        return True
                    else:
                        logger.warning(
                            f"Falha no sendPhoto ({response.status_code}): {response.text}. Tentando sendMessage..."
                        )
                except Exception as exc:
                    logger.warning(f"Erro ao enviar foto no Telegram: {exc}. Tentando sendMessage...")

            # 2. Envio alternativo como mensagem de texto
            try:
                payload = {
                    "chat_id": self.chat_id,
                    "text": message_html,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                    "disable_web_page_preview": False,
                }
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                )
                if response.status_code == 200:
                    logger.info(f"Notificação em texto enviada com sucesso para o anúncio ID: {ad.external_id}")
                    return True
                else:
                    logger.error(
                        f"Falha ao enviar mensagem no Telegram ({response.status_code}): {response.text}"
                    )
                    return False
            except Exception as exc:
                logger.error(f"Erro ao conectar com a API do Telegram: {exc}")
                return False

    async def send_raw_message(self, chat_id: str | int, text: str) -> bool:
        """Envia mensagem de texto simples formatada em HTML para um chat específico."""
        if not self.is_configured or not self.base_url:
            return False
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                res = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
                return res.status_code == 200
            except Exception as exc:
                logger.error(f"Erro ao enviar resposta no Telegram: {exc}")
                return False

    async def start_polling(self, sync_callback):
        """Loop de polling assíncrono para escutar comandos como /verificar e /status no Telegram."""
        if not self.is_configured or not self.base_url:
            logger.info("Bot do Telegram não configurado para polling interativo.")
            return

        offset = 0
        logger.info("Iniciando escuta de comandos do Telegram (/verificar, /status, /ajuda)...")

        async with httpx.AsyncClient(timeout=35.0) as client:
            while True:
                try:
                    res = await client.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": offset, "timeout": 20},
                    )
                    if res.status_code == 200:
                        data = res.json()
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1
                            message = update.get("message", {})
                            text = message.get("text", "").strip()
                            chat_id = message.get("chat", {}).get("id")

                            if not text or not chat_id:
                                continue

                            cmd = text.split()[0].lower()
                            if cmd in ("/verificar", "/checar", "/buscar"):
                                await self.send_raw_message(
                                    chat_id,
                                    "🔍 <b>Iniciando verificação na OLX agora...</b>\nAguarde um momento enquanto busco novos anúncios.",
                                )
                                result = await sync_callback()
                                msg = (
                                    f"✅ <b>Verificação Concluída!</b>\n\n"
                                    f"• <b>Status:</b> {result.get('status')}\n"
                                    f"• <b>Analisados:</b> {result.get('found_count', 0)}\n"
                                    f"• <b>Novos imóveis:</b> {result.get('new_count', 0)}\n"
                                    f"• <b>Alertas disparados:</b> {result.get('notified_count', 0)}"
                                )
                                await self.send_raw_message(chat_id, msg)

                            elif cmd == "/status":
                                await self.send_raw_message(
                                    chat_id,
                                    f"🤖 <b>Bot de Monitoramento OLX</b>\n"
                                    f"Status: Ativo e monitorando periodicamente.\n"
                                    f"Envie <code>/verificar</code> para rodar a busca imediatamente.",
                                )

                            elif cmd in ("/start", "/ajuda", "/help"):
                                await self.send_raw_message(
                                    chat_id,
                                    "👋 <b>Comandos disponíveis:</b>\n\n"
                                    "• <code>/verificar</code> - Executa a verificação na OLX imediatamente.\n"
                                    "• <code>/status</code> - Exibe o status do monitor.\n"
                                    "• <code>/ajuda</code> - Mostra esta mensagem de ajuda.",
                                )
                except Exception as exc:
                    logger.debug(f"Aviso no polling do Telegram: {exc}")
                await asyncio.sleep(2)
