import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

import httpx

from app.models import HouseAdCreate
from app.geocoder import geocode_location

logger = logging.getLogger("imv_olx.scraper")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com.br/",
}


class OLXScraper:
    """Scraper assíncrono e resiliente para listagens de imóveis da OLX Brasil."""

    def __init__(self, headers: Optional[Dict[str, str]] = None, timeout: float = 20.0):
        self.headers = headers or DEFAULT_HEADERS
        self.timeout = timeout

    async def fetch_page(self, url: str) -> Optional[str]:
        """Realiza a requisição HTTP para a URL fornecida contornando bloqueios de TLS/WAF."""
        # 1. Tenta com curl_cffi (impersonate Chrome) para contornar proteções Cloudflare/Datadome
        if HAS_CURL_CFFI:
            try:
                response = curl_requests.get(
                    url,
                    headers=self.headers,
                    impersonate="chrome120",
                    timeout=int(self.timeout),
                )
                if response.status_code in (200, 403) and len(response.text) > 1000:
                    return response.text
                elif response.status_code == 200:
                    return response.text
            except Exception as exc:
                logger.warning(f"curl_cffi falhou ({exc}), tentando fallback para httpx...")

        # 2. Fallback para httpx
        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                follow_redirects=True,
                timeout=self.timeout,
            ) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.text
                elif response.status_code in (403, 429) and len(response.text) > 2000:
                    return response.text
                else:
                    logger.warning(
                        f"OLX retornou status {response.status_code} para a URL: {url}"
                    )
                    return response.text if len(response.text) > 2000 else None
        except Exception as exc:
            logger.error(f"Erro ao acessar a OLX ({url}): {exc}")
            return None

    def extract_next_data(self, html_content: str) -> Optional[Dict[str, Any]]:
        """Extrai e faz o parse do JSON presente na tag <script id='__NEXT_DATA__'>."""
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            script_tag = soup.find("script", id="__NEXT_DATA__")
            if not script_tag or not script_tag.string:
                return None

            data = json.loads(script_tag.string)
            return data
        except Exception as exc:
            logger.debug(f"Erro ao extrair __NEXT_DATA__: {exc}")
            return None

    def _extract_ads_list_from_json(self, next_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Localiza a lista de anúncios dentro do dicionário __NEXT_DATA__."""
        if not isinstance(next_data, dict):
            return []

        page_props = next_data.get("props", {}).get("pageProps", {})

        if "ads" in page_props and isinstance(page_props["ads"], list):
            return page_props["ads"]

        initial_data = page_props.get("initialData", {})
        if isinstance(initial_data, dict) and "ads" in initial_data and isinstance(initial_data["ads"], list):
            return initial_data["ads"]

        redux = page_props.get("reduxStore", {}).get("initialState", {})
        if isinstance(redux, dict):
            ad_list = redux.get("adList", {}).get("ads", [])
            if isinstance(ad_list, list) and ad_list:
                return ad_list

        return []

    def _clean_price(self, price_raw: Any) -> tuple[Optional[float], Optional[str]]:
        """Normaliza o valor do preço para Float e String formatada."""
        if price_raw is None:
            return None, "Sob Consulta"

        if isinstance(price_raw, (int, float)):
            val = float(price_raw)
            return val, f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        price_str = str(price_raw).strip()
        if not price_str or "consulta" in price_str.lower():
            return None, "Sob Consulta"

        digits_only = re.sub(r"[^\d]", "", price_str)
        if digits_only:
            try:
                if "," in price_str and len(price_str.split(",")[-1]) == 2:
                    val = float(digits_only) / 100.0
                else:
                    val = float(digits_only)
                formatted = f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                return val, formatted
            except ValueError:
                pass

        return None, price_str

    def _extract_image_url(self, raw_ad: Dict[str, Any]) -> Optional[str]:
        """Extrai a URL da imagem principal do anúncio a partir do JSON."""
        images = raw_ad.get("images")
        if isinstance(images, list) and images:
            first_img = images[0]
            if isinstance(first_img, dict):
                return (
                    first_img.get("original")
                    or first_img.get("large")
                    or first_img.get("thumbnail")
                    or first_img.get("url")
                )
            elif isinstance(first_img, str):
                return first_img

        for key in ("imageUrl", "thumbnail", "image", "mainPhoto"):
            val = raw_ad.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val

        return None

    def _extract_location(self, raw_ad: Dict[str, Any]) -> Optional[str]:
        """Extrai a localização formatada a partir do JSON."""
        loc_data = raw_ad.get("location")
        if isinstance(loc_data, str) and loc_data:
            return loc_data

        loc_details = raw_ad.get("locationDetails") or raw_ad.get("location") or {}
        if isinstance(loc_details, dict):
            parts = []
            neighborhood = loc_details.get("neighbourhood") or loc_details.get("bairro")
            city = loc_details.get("municipality") or loc_details.get("cidade") or loc_details.get("city")
            uf = loc_details.get("uf") or loc_details.get("state") or loc_details.get("estado")
            if neighborhood:
                parts.append(neighborhood)
            if city:
                parts.append(city)
            if uf:
                parts.append(uf)
            if parts:
                return ", ".join(parts)

        return raw_ad.get("friendlyLocation")

    def _extract_date(self, raw_ad: Dict[str, Any]) -> Optional[datetime]:
        """Converte a data da OLX em objeto datetime."""
        for date_key in ("date", "publicationDate", "created", "publishDate", "origDate"):
            val = raw_ad.get(date_key)
            if not val:
                continue

            if isinstance(val, (int, float)):
                try:
                    if val > 1e11:
                        return datetime.fromtimestamp(val / 1000.0, timezone.utc)
                    return datetime.fromtimestamp(val, timezone.utc)
                except Exception:
                    pass

            if isinstance(val, str):
                try:
                    clean_str = val.replace("Z", "+00:00")
                    return datetime.fromisoformat(clean_str)
                except Exception:
                    pass

        return None

    def parse_ad_item(self, raw_ad: Dict[str, Any]) -> Optional[HouseAdCreate]:
        """Converte um item bruto da OLX em um schema validado HouseAdCreate."""
        try:
            ext_id = (
                raw_ad.get("listId")
                or raw_ad.get("adId")
                or raw_ad.get("id")
            )
            if not ext_id:
                return None
            ext_id = str(ext_id)

            title = (
                raw_ad.get("subject")
                or raw_ad.get("title")
                or "Imóvel sem título"
            )
            title = str(title).strip()

            url = raw_ad.get("url") or raw_ad.get("friendlyUrl")
            if not url:
                return None
            if not url.startswith("http"):
                url = f"https://www.olx.com.br{url}"

            raw_price = (
                raw_ad.get("priceValue")
                or raw_ad.get("price")
                or raw_ad.get("priceLabel")
            )
            price_val, price_fmt = self._clean_price(raw_price)
            location = self._extract_location(raw_ad)
            lat, lon = geocode_location(location, ext_id)
            image_url = self._extract_image_url(raw_ad)
            created_at_olx = self._extract_date(raw_ad)

            return HouseAdCreate(
                external_id=ext_id,
                title=title,
                price_val=price_val,
                price_str=price_fmt or "Sob Consulta",
                price=price_val,
                price_formatted=price_fmt,
                location=location,
                latitude=lat,
                longitude=lon,
                url=url,
                image_url=image_url,
                created_at_olx=created_at_olx,
            )
        except Exception as exc:
            logger.warning(f"Erro ao processar anúncio JSON: {exc}")
            return None

    def _parse_location_and_date_from_dom_text(self, raw_text: Optional[str]) -> tuple[Optional[str], Optional[datetime]]:
        """Separa o texto de localização da data de publicação e converte a data para datetime."""
        if not raw_text:
            return None, None

        raw_str = raw_text.strip()
        pattern = r"(Hoje|Ontem|\d{1,2}\s+de\s+[a-záéíóúç]+)[,\s]+(\d{1,2}:\d{2})"
        match = re.search(pattern, raw_str, re.IGNORECASE)

        months_map = {
            "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
            "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
        }

        location = raw_str
        parsed_date = None

        if match:
            location = raw_str[:match.start()].strip(" ,-\n\t")
            date_part = match.group(1).lower().strip()
            time_part = match.group(2).strip()
            try:
                h, m = [int(x) for x in time_part.split(":")]
                now = datetime.now(timezone.utc)
                if "hoje" in date_part:
                    parsed_date = now.replace(hour=h, minute=m, second=0, microsecond=0)
                elif "ontem" in date_part:
                    from datetime import timedelta
                    yesterday = now - timedelta(days=1)
                    parsed_date = yesterday.replace(hour=h, minute=m, second=0, microsecond=0)
                else:
                    dm = re.search(r"(\d{1,2})\s+de\s+([a-z]+)", date_part)
                    if dm:
                        day = int(dm.group(1))
                        mon_str = dm.group(2)[:3]
                        month = months_map.get(mon_str, now.month)
                        parsed_date = datetime(now.year, month, day, h, m, tzinfo=timezone.utc)
            except Exception:
                parsed_date = None

        return (location or "Recife e Região"), parsed_date

    def _extract_image_from_card(self, card) -> Optional[str]:
        """Extrai a URL da foto principal do anúncio a partir da tag HTML do card."""
        # 1. Procura em tags <source> (geralmente trazem .webp e .jpg de alta qualidade)
        for source in card.find_all("source"):
            srcset = source.get("srcset") or source.get("data-srcset")
            if srcset and srcset.startswith("http"):
                url = srcset.split(",")[0].split()[0]
                if "img.olx.com.br" in url:
                    return url

        # 2. Procura em tags <img>
        for img in card.find_all("img"):
            for attr in ("src", "data-src", "data-original", "srcset"):
                val = img.get(attr)
                if val and isinstance(val, str) and val.startswith("http") and "img.olx.com.br" in val:
                    url = val.split(",")[0].split()[0]
                    return url

        # 3. Fallback genérico para qualquer tag com imagem
        any_img = card.find("img")
        if any_img:
            return any_img.get("src") or any_img.get("data-src")

        return None

    def parse_html_dom_cards(self, html_content: str) -> List[HouseAdCreate]:
        """Extrai anúncios diretamente das tags HTML dos cards caso o __NEXT_DATA__ não esteja presente."""
        soup = BeautifulSoup(html_content, "html.parser")
        cards = soup.find_all("section", class_=re.compile(r"olx-adcard"))
        parsed_list: List[HouseAdCreate] = []

        for card in cards:
            try:
                a_tag = card.find("a", href=True)
                if not a_tag:
                    continue

                url = a_tag["href"]
                if not url.startswith("http"):
                    url = f"https://www.olx.com.br{url}"

                # Extrai o ID do link (últimos dígitos)
                id_match = re.search(r"-(\d+)$", url) or re.search(r"/(\d+)$", url)
                if not id_match:
                    continue
                ext_id = id_match.group(1)

                # Título
                h2 = card.find(["h2", "h3"])
                title = h2.get_text(strip=True) if h2 else (a_tag.get("title") or "Imóvel OLX")

                # Preço
                price_tag = card.find(class_=re.compile(r"price|valor", re.I)) or card.find("h3")
                price_raw = price_tag.get_text(strip=True) if price_tag else None
                price_val, price_fmt = self._clean_price(price_raw)

                # Localização e Data de publicação separadas
                loc_tag = card.find(class_=re.compile(r"location|localizacao|address", re.I))
                raw_loc_text = loc_tag.get_text(strip=True) if loc_tag else None
                location, olx_date = self._parse_location_and_date_from_dom_text(raw_loc_text)
                lat, lon = geocode_location(location, ext_id)

                # Imagem
                img = card.find("img")
                image_url = None
                if img:
                    image_url = img.get("src") or img.get("data-src")

                ad_obj = HouseAdCreate(
                    external_id=ext_id,
                    title=title,
                    price_val=price_val,
                    price_str=price_fmt or "Sob Consulta",
                    price=price_val,
                    price_formatted=price_fmt,
                    location=location,
                    latitude=lat,
                    longitude=lon,
                    url=url,
                    image_url=image_url,
                    created_at_olx=olx_date,
                )
                parsed_list.append(ad_obj)
            except Exception as exc:
                logger.debug(f"Erro ao extrair card HTML: {exc}")

        return parsed_list

    async def scrape(self, url: str) -> List[HouseAdCreate]:
        """Fluxo completo com fallback duplo: __NEXT_DATA__ JSON e HTML DOM Cards."""
        logger.info(f"Iniciando scraping da URL OLX: {url}")
        html = await self.fetch_page(url)
        if not html:
            logger.warning("Nenhum conteúdo HTML foi obtido da OLX.")
            return []

        # 1. Estratégia Principal: __NEXT_DATA__
        next_data = self.extract_next_data(html)
        if next_data:
            ads_raw = self._extract_ads_list_from_json(next_data)
            if ads_raw:
                logger.info(f"Encontrados {len(ads_raw)} anúncios no JSON __NEXT_DATA__.")
                parsed_ads: List[HouseAdCreate] = []
                for ad_item in ads_raw:
                    parsed = self.parse_ad_item(ad_item)
                    if parsed:
                        parsed_ads.append(parsed)
                if parsed_ads:
                    logger.info(f"Total de {len(parsed_ads)} anúncios válidos extraídos via JSON.")
                    return parsed_ads

        # 2. Estratégia de Fallback: DOM HTML (olx-adcard)
        logger.info("Utilizando parser dos cards HTML DOM da OLX...")
        dom_ads = self.parse_html_dom_cards(html)
        logger.info(f"Total de {len(dom_ads)} anúncios válidos extraídos via DOM.")
        return dom_ads
