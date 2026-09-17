from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from app.database import Base


# ==========================================
# SQLAlchemy ORM Models
# ==========================================
class SearchQuery(Base):
    __tablename__ = "search_queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    olx_url = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_synced_at = Column(DateTime, nullable=True)

    houses = relationship("HouseAd", back_populates="search_query", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<SearchQuery id={self.id} name='{self.name}' active={self.is_active}>"


class HouseAd(Base):
    __tablename__ = "house_ads"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    search_query_id = Column(Integer, ForeignKey("search_queries.id"), nullable=True, index=True)
    external_id = Column(String(100), unique=True, index=True, nullable=False)
    title = Column(String(500), nullable=False)
    price_val = Column(Float, nullable=True, index=True)
    price_str = Column(String(100), nullable=False, default="Sob Consulta")
    location = Column(String(255), nullable=True, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    url = Column(Text, nullable=False)
    image_url = Column(Text, nullable=True)
    created_at_olx = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    notified_telegram = Column(Boolean, default=False, nullable=False, index=True)

    search_query = relationship("SearchQuery", back_populates="houses")

    # Propriedades de compatibilidade
    @property
    def price(self) -> Optional[float]:
        return self.price_val

    @price.setter
    def price(self, val: Optional[float]):
        self.price_val = val

    @property
    def price_formatted(self) -> str:
        return self.price_str

    @price_formatted.setter
    def price_formatted(self, val: Optional[str]):
        self.price_str = val or "Sob Consulta"

    def __repr__(self) -> str:
        return f"<HouseAd id={self.id} external_id='{self.external_id}' title='{self.title[:30]}...' price_val={self.price_val}>"


# ==========================================
# Pydantic Schemas
# ==========================================
class SearchQueryBase(BaseModel):
    name: str
    olx_url: str
    is_active: bool = True


class SearchQueryCreate(SearchQueryBase):
    pass


class SearchQueryRead(SearchQueryBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HouseAdBase(BaseModel):
    external_id: str
    title: str
    price_val: Optional[float] = None
    price_str: Optional[str] = None
    price: Optional[float] = None
    price_formatted: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    url: str
    image_url: Optional[str] = None
    created_at_olx: Optional[datetime] = None
    search_query_id: Optional[int] = None


class HouseAdCreate(HouseAdBase):
    pass


class HouseAdRead(HouseAdBase):
    id: int
    created_at: datetime
    notified_telegram: bool

    model_config = ConfigDict(from_attributes=True)


class HouseAdFilter(BaseModel):
    search_query_id: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    search: Optional[str] = None
    notified_only: Optional[bool] = None
    limit: int = 1000
    offset: int = 0


class HouseAdListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[HouseAdRead]


class MonitorTriggerResponse(BaseModel):
    message: str
    status: str
    found_count: int = 0
    new_count: int = 0
    notified_count: int = 0


class MonitorStatus(BaseModel):
    is_running: bool
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_found_count: int = 0
    last_new_count: int = 0
    total_ads_stored: int = 0
    check_interval_minutes: int

