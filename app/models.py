"""Pydantic-модели."""

from typing import Optional, List, Any
from pydantic import BaseModel, Field


class Quote(BaseModel):
    """Цитата."""
    id: str
    author: str
    text: str
    tags: Optional[List[str]] = None
    year: Optional[int] = None
    lang: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class QuoteUpdate(BaseModel):
    """Обновление цитаты редакцией."""
    author: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=16384)


class CatalogSource(BaseModel):
    """Адрес каталога."""
    url: str


class Stats(BaseModel):
    """Статистика."""
    served_local: int = 0
    served_from_catalog: int = 0
    catalog_reads: int = 0
    evictions: int = 0
    local: int = 0
    bytes: int = 0
    catalog: int = 0