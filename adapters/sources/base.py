"""
수집 어댑터 공통 인터페이스 및 수집 데이터 모델
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class RawCollectedItem(BaseModel):
    title: str
    url: str
    summary: str = ""
    source_name: str
    source_kind: str
    published_at: Optional[str] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseSourceAdapter(ABC):
    @abstractmethod
    async def fetch_items(self, url: str, config: Optional[Dict[str, Any]] = None) -> List[RawCollectedItem]:
        """출처로부터 최신 항목 목록을 비동기 수집합니다."""
        pass
