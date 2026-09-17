from curl_cffi import requests
from bs4 import BeautifulSoup
import re

url = "https://www.olx.com.br/imoveis/venda/casas/estado-sp/sao-paulo"
r = requests.get(url, impersonate="chrome120")
soup = BeautifulSoup(r.text, "html.parser")
cards = soup.find_all("section", class_=re.compile(r"olx-adcard"))

print("Total cards found:", len(cards))
for i, card in enumerate(cards[:3]):
    print(f"\n--- Card #{i+1} ---")
    # Link and ID
    a = card.find("a", href=True)
    url = a["href"] if a else "No URL"
    ext_id = url.split("-")[-1] if "-" in url else "No ID"
    
    # Title
    h2 = card.find(["h2", "h3"])
    title = h2.get_text(strip=True) if h2 else (a.get("title") if a else "No Title")
    
    # Price
    price_tag = card.find(class_=re.compile(r"price|valor", re.I)) or card.find("h3")
    price_text = price_tag.get_text(strip=True) if price_tag else "No Price"
    
    # Location
    loc_tag = card.find(class_=re.compile(r"location|localizacao|address", re.I)) or card.find("p", class_=re.compile(r"location", re.I))
    # If not found by class, let's look for text containing SP or neighborhood
    loc_text = loc_tag.get_text(strip=True) if loc_tag else "No Location"
    
    # Image
    img = card.find("img")
    img_url = img.get("src") or img.get("data-src") if img else None
    
    print(f"ID: {ext_id}")
    print(f"Title: {title}")
    print(f"Price: {price_text}")
    print(f"Location: {loc_text}")
    print(f"Image: {img_url}")
    print(f"URL: {url}")
