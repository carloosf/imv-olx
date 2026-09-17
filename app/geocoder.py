import hashlib
import logging
import re
from typing import Dict, Optional, Tuple
import httpx

logger = logging.getLogger("imv_olx.geocoder")

# Cache em memória para evitar requisições repetidas ao Nominatim
GEOCODE_CACHE: Dict[str, Tuple[float, float]] = {}

# Dicionário local completo de coordenadas precisas para bairros de Recife e RMR (Fallback 100% garantido)
NEIGHBORHOOD_COORDS: Dict[str, Tuple[float, float]] = {
    # Recife - Zona Sul
    "boa viagem": (-8.1235, -34.9034),
    "pina": (-8.0963, -34.8947),
    "imbiribeira": (-8.0902, -34.9075),
    "ipsep": (-8.1102, -34.9199),
    "brasilia teimosa": (-8.0867, -34.8789),
    "brasília teimosa": (-8.0867, -34.8789),
    "setubal": (-8.1342, -34.9022),
    "setúbal": (-8.1342, -34.9022),
    "ibura": (-8.1186, -34.9431),
    "jordao": (-8.1356, -34.9317),
    "jordão": (-8.1356, -34.9317),

    # Recife - Zona Norte
    "passarinho": (-7.9818, -34.9232),
    "cajueiro": (-8.0121, -34.8857),
    "campina do barreto": (-8.0166, -34.8821),
    "casa amarela": (-8.0246, -34.9178),
    "casa forte": (-8.0338, -34.9183),
    "espinheiro": (-8.0416, -34.8961),
    "gracas": (-8.0447, -34.9015),
    "graças": (-8.0447, -34.9015),
    "aflitos": (-8.0397, -34.8989),
    "jaqueira": (-8.0367, -34.9042),
    "parnamirim": (-8.0322, -34.9083),
    "tamarineira": (-8.0289, -34.9039),
    "rosarinho": (-8.0306, -34.8989),
    "encruzilhada": (-8.0367, -34.8909),
    "torre": (-8.0456, -34.9102),
    "madalena": (-8.0538, -34.9084),
    "apipucos": (-8.0169, -34.9367),
    "monteiro": (-8.0256, -34.9250),
    "poco da panela": (-8.0333, -34.9208),
    "poço da panela": (-8.0333, -34.9208),
    "santana": (-8.0389, -34.9150),
    "arruda": (-8.0225, -34.8872),
    "campo grande": (-8.0317, -34.8806),
    "agua fria": (-8.0164, -34.8967),
    "água fria": (-8.0164, -34.8967),
    "beberibe": (-8.0067, -34.8986),
    "dois irmaos": (-8.0139, -34.9431),
    "dois irmãos": (-8.0139, -34.9431),
    "sitio dos pintos": (-8.0056, -34.9650),
    "sítio dos pintos": (-8.0056, -34.9650),
    "guabiraba": (-7.9892, -34.9389),
    "alto jose do pinho": (-8.0211, -34.9111),
    "alto josé do pinho": (-8.0211, -34.9111),
    "alto santa terezinha": (-8.0125, -34.9083),
    "vasco da gama": (-8.0118, -34.9191),
    "macaxeira": (-8.0133, -34.9294),
    "nova descoberta": (-8.0094, -34.9211),
    "fundao": (-8.0233, -34.8817),
    "fundão": (-8.0233, -34.8817),
    "porto da madeira": (-8.0156, -34.8833),

    # Recife - Zona Oeste
    "cordeiro": (-8.0511, -34.9285),
    "iputinga": (-8.0398, -34.9373),
    "varzea": (-8.0450, -34.9692),
    "várzea": (-8.0450, -34.9692),
    "caxanga": (-8.0356, -34.9542),
    "caxangá": (-8.0356, -34.9542),
    "engenho do meio": (-8.0566, -34.9424),
    "torroes": (-8.0617, -34.9389),
    "torrões": (-8.0617, -34.9389),
    "san martin": (-8.0702, -34.9288),
    "bongi": (-8.0656, -34.9189),
    "prado": (-8.0624, -34.9126),
    "zumbi": (-8.0522, -34.9150),
    "mustardinha": (-8.0689, -34.9139),
    "mangueira": (-8.0711, -34.9139),
    "afogados": (-8.0772, -34.9094),
    "estancia": (-8.0864, -34.9291),
    "estância": (-8.0864, -34.9291),
    "areias": (-8.0941, -34.9284),
    "barro": (-8.0931, -34.9514),
    "tejipio": (-8.0867, -34.9542),
    "tejipió": (-8.0867, -34.9542),
    "coqueiral": (-8.0914, -34.9647),
    "jardim sao paulo": (-8.0808, -34.9421),
    "jardim são paulo": (-8.0808, -34.9421),
    "toto": (-8.0778, -34.9689),
    "totó": (-8.0778, -34.9689),
    "curado": (-8.0694, -34.9819),
    "ilha do retiro": (-8.0606, -34.9039),

    # Recife - Centro
    "boa vista": (-8.0618, -34.8873),
    "soledade": (-8.0528, -34.8917),
    "santo amaro": (-8.0509, -34.8814),
    "derby": (-8.0578, -34.8990),
    "ilha do leite": (-8.0657, -34.8942),
    "paissandu": (-8.0583, -34.8986),
    "recife antigo": (-8.0628, -34.8711),
    "bairro do recife": (-8.0628, -34.8711),
    "santo antonio": (-8.0650, -34.8789),
    "santo antônio": (-8.0650, -34.8789),
    "sao jose": (-8.0694, -34.8817),
    "são josé": (-8.0694, -34.8817),
    "coque": (-8.0722, -34.8917),
    "cabanga": (-8.0798, -34.8976),

    # Região Metropolitana do Recife (RMR)
    "olinda": (-7.9989, -34.8456),
    "casa caiada": (-7.9867, -34.8389),
    "bairro novo": (-7.9933, -34.8417),
    "rio doce": (-7.9711, -34.8322),
    "jardim atlantico": (-7.9656, -34.8417),
    "jardim atlântico": (-7.9656, -34.8417),
    "jaboatao dos guararapes": (-8.1136, -35.0153),
    "jaboatão dos guararapes": (-8.1136, -35.0153),
    "piedade": (-8.1757, -34.9188),
    "candeias": (-8.2042, -34.9214),
    "barra de jangada": (-8.2356, -34.9389),
    "prazeres": (-8.1567, -34.9311),
    "paulista": (-7.9406, -34.8728),
    "janga": (-7.9433, -34.8278),
    "maria farinha": (-7.8767, -34.8389),
    "camaragibe": (-8.0217, -34.9819),
    "sao lourenco da mata": (-8.0028, -35.0189),
    "são lourenço da mata": (-8.0028, -35.0189),
    "abreu e lima": (-7.9133, -34.9011),
    "igarassu": (-7.8344, -34.9067),
    "itamaraca": (-7.7478, -34.8256),
    "ilha de itamaraca": (-7.7478, -34.8256),
    "ilha de itamaracá": (-7.7478, -34.8256),
    "cabo de santo agostinho": (-8.2833, -35.0333),
    "porto de galinhas": (-8.5042, -35.0069),
    "ipojuca": (-8.3986, -35.0639),
}


def _query_nominatim(location_query: str) -> Optional[Tuple[float, float]]:
    """Consulta as coordenadas reais no serviço OpenStreetMap Nominatim usando HTTPX com headers de navegador."""
    try:
        clean = re.sub(r"\s+", " ", location_query.strip())
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) == 2:
            formatted_query = f"{parts[1]}, {parts[0]}, PE, Brasil"
        elif len(parts) == 1:
            formatted_query = f"{parts[0]}, Recife, PE, Brasil"
        else:
            formatted_query = f"{clean}, PE, Brasil"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 imv-olx/1.0",
            "Accept": "application/json",
        }
        with httpx.Client(headers=headers, timeout=6.0) as client:
            resp = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": formatted_query, "format": "json", "limit": 1, "countrycodes": "br"}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    logger.info(f"Nominatim geocodificou com sucesso '{location_query}' -> ({lat}, {lon})")
                    return lat, lon
    except Exception as exc:
        logger.debug(f"Nominatim lookup indisponível para '{location_query}': {exc}")

    return None


def geocode_location(location_str: Optional[str], item_id: str = "") -> Tuple[Optional[float], Optional[float]]:
    """
    Geocodifica o endereço/bairro usando OpenStreetMap Nominatim com cache em memória
    e fallback para o dicionário geográfico detalhado.
    Aplica micro-jitter (150m-200m) determinístico para separar anúncios no mesmo bairro.
    """
    if not location_str:
        return -8.0578, -34.8829

    loc_key = location_str.lower().strip()

    # 1. Verifica no Cache em memória
    if loc_key in GEOCODE_CACHE:
        base_lat, base_lon = GEOCODE_CACHE[loc_key]
    else:
        base_coords = None

        # 2. Tenta encontrar no dicionário local de alta precisão de bairros de Recife e RMR
        loc_clean_no_punct = re.sub(r"[^\w\s]", " ", loc_key)
        for name, coords in NEIGHBORHOOD_COORDS.items():
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, loc_clean_no_punct) or name in loc_key:
                base_coords = coords
                break

        # 3. Se não achou no dicionário, consulta a API do OpenStreetMap Nominatim
        if not base_coords:
            base_coords = _query_nominatim(location_str)

        # 4. Fallback por município caso não encontre o bairro exato
        if not base_coords:
            if "jaboatao" in loc_key or "jaboatão" in loc_key:
                base_coords = (-8.1136, -35.0153)
            elif "olinda" in loc_key:
                base_coords = (-7.9989, -34.8456)
            elif "paulista" in loc_key:
                base_coords = (-7.9406, -34.8728)
            elif "itamaraca" in loc_key or "itamaracá" in loc_key:
                base_coords = (-7.7478, -34.8256)
            else:
                base_coords = (-8.0578, -34.8829) # Centro Recife

        GEOCODE_CACHE[loc_key] = base_coords
        base_lat, base_lon = base_coords

    # 5. Adiciona micro-offset determinístico baseado no hash do ID do anúncio (~150 a 200 metros)
    # Isso garante que se houver 5 casas no mesmo bairro (ex: Boa Viagem), cada uma tenha seu próprio círculo e pin distinto
    if item_id:
        hash_val = int(hashlib.md5(str(item_id).encode()).hexdigest()[:8], 16)
        offset_lat = ((hash_val % 1000) - 500) / 140000.0
        offset_lon = (((hash_val // 1000) % 1000) - 500) / 140000.0
        return round(base_lat + offset_lat, 6), round(base_lon + offset_lon, 6)

    return base_lat, base_lon

