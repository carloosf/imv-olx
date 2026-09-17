import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import HouseAd
from app.geocoder import geocode_location

async def recompute_all():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(HouseAd))
        ads = result.scalars().all()
        for ad in ads:
            lat, lon = geocode_location(ad.location, ad.external_id)
            ad.latitude = lat
            ad.longitude = lon
        await session.commit()
        print(f"Sucesso: {len(ads)} imóveis re-geocodificados com precisão por bairro e micro-offsets!")

if __name__ == "__main__":
    asyncio.run(recompute_all())
