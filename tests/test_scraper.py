import json
import pytest
from app.scraper import OLXScraper

MOCK_OLX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Casas a venda - SP</title>
</head>
<body>
    <div id="__next"></div>
    <script id="__NEXT_DATA__" type="application/json">
    {
        "props": {
            "pageProps": {
                "ads": [
                    {
                        "listId": 123456789,
                        "subject": "Linda Casa 3 Quartos em Pinheiros",
                        "price": "R$ 850.000",
                        "url": "https://sp.olx.com.br/sao-paulo-e-regiao/imoveis/linda-casa-3-quartos-pinheiros-123456789",
                        "location": "São Paulo, Pinheiros - Zona Oeste",
                        "images": [
                            {"original": "https://img.olx.com.br/images/12/123456.jpg"}
                        ],
                        "date": "2026-09-17T10:00:00Z"
                    },
                    {
                        "listId": 987654321,
                        "subject": "Casa Ampla com Piscina e Churrasqueira",
                        "priceValue": 1200000,
                        "url": "/sao-paulo-e-regiao/imoveis/casa-ampla-987654321",
                        "locationDetails": {
                            "neighbourhood": "Moema",
                            "municipality": "São Paulo",
                            "uf": "SP"
                        },
                        "images": [
                            {"original": "https://img.olx.com.br/images/98/987654.jpg"}
                        ],
                        "date": 1726567200
                    }
                ]
            }
        }
    }
    </script>
</body>
</html>
"""


def test_extract_next_data():
    scraper = OLXScraper()
    next_data = scraper.extract_next_data(MOCK_OLX_HTML)
    assert next_data is not None
    assert "props" in next_data
    assert "pageProps" in next_data["props"]
    ads = scraper._extract_ads_list_from_json(next_data)
    assert len(ads) == 2


def test_clean_price():
    scraper = OLXScraper()

    # Formato string brasileira com R$
    val, fmt = scraper._clean_price("R$ 850.000")
    assert val == 850000.0
    assert "850.000" in fmt

    # Formato numérico direto
    val, fmt = scraper._clean_price(1200000)
    assert val == 1200000.0
    assert "1.200.000" in fmt

    # Sob consulta / vazio
    val, fmt = scraper._clean_price(None)
    assert val is None
    assert fmt == "Sob Consulta"


def test_parse_ad_item():
    scraper = OLXScraper()
    next_data = scraper.extract_next_data(MOCK_OLX_HTML)
    ads = scraper._extract_ads_list_from_json(next_data)

    ad1 = scraper.parse_ad_item(ads[0])
    assert ad1 is not None
    assert ad1.external_id == "123456789"
    assert ad1.title == "Linda Casa 3 Quartos em Pinheiros"
    assert ad1.price == 850000.0
    assert "Pinheiros" in ad1.location
    assert ad1.image_url == "https://img.olx.com.br/images/12/123456.jpg"

    ad2 = scraper.parse_ad_item(ads[1])
    assert ad2 is not None
    assert ad2.external_id == "987654321"
    assert ad2.url.startswith("https://www.olx.com.br")
    assert "Moema" in ad2.location
    assert ad2.price == 1200000.0
