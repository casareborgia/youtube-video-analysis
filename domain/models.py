from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from domain.enums import RoutineMode, SourceType, RunStatus, JobStatus


class ScheduleItem(BaseModel):
    id: Optional[int] = None
    local_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="HH:mm 형식")
    days_of_week: List[str] = Field(default_factory=lambda: ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"])
    enabled: bool = True


class RoutineBase(BaseModel):
    code: str = Field(..., description="루틴 고유 코드 (AI_TREND, MAUM_PROMO 등)")
    name: str
    enabled: bool = True
    mode: RoutineMode = RoutineMode.REVIEW
    timezone: str = "Asia/Seoul"
    platforms: List[str] = Field(default_factory=lambda: ["threads", "x"])
    description: str = ""

    @property
    def key(self) -> str:
        return self.code


class RoutineCreate(RoutineBase):
    schedules: List[ScheduleItem] = Field(default_factory=list)
    source_ids: List[int] = Field(default_factory=list)


class RoutineUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    mode: Optional[RoutineMode] = None
    timezone: Optional[str] = None
    platforms: Optional[List[str]] = None
    description: Optional[str] = None
    version: Optional[int] = None
    schedules: Optional[List[ScheduleItem]] = None
    source_ids: Optional[List[int]] = None
    max_posts_per_day: Optional[int] = None


class SourceBase(BaseModel):
    name: str
    kind: SourceType
    url: str
    enabled: bool = True
    config_json: Dict[str, Any] = Field(default_factory=dict)


class SourceCreate(SourceBase):
    routine_id: int


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[SourceType] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None
    config_json: Optional[Dict[str, Any]] = None


class SourceResponse(SourceBase):
    id: int
    routine_id: int
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    last_checked_at: Optional[int] = None
    health_status: str = "HEALTHY"


class RoutineResponse(RoutineBase):
    id: int
    version: int = 1
    schedules: List[ScheduleItem] = Field(default_factory=list)
    source_ids: List[int] = Field(default_factory=list)
    sources: List[SourceResponse] = Field(default_factory=list)
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None
    max_posts_per_day: int = 3
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class SourceTestRequest(BaseModel):
    url: str
    kind: SourceType = SourceType.RSS_ATOM


class SourceTestResponse(BaseModel):
    success: bool
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    items_count: int = 0
    sample_title: Optional[str] = None
    sample_url: Optional[str] = None
    error: Optional[str] = None


class PromotionAngle(BaseModel):
    id: int
    routine_id: int
    angle_index: int
    title: str
    hook_template: str
    body_template: str
    weight: int = 1
    enabled: bool = True
    last_used_at: int = 0


class StructuredDraft(BaseModel):
    headline: str
    body: str = Field(..., description="링크 없는 본문 (140자 내외 목표)")
    first_reply: str = Field(..., description="첫 번째 셀프 답글 (원문/서비스 링크)")
    topic_key: str
    claims: List[Dict[str, str]] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    quality_score: float = 1.0


class RunTriggerRequest(BaseModel):
    mode: Optional[RoutineMode] = None  # None이면 루틴의 기본 모드
    source_ids: Optional[List[int]] = None
    ignore_schedule: bool = True
    ignore_dedup: bool = False
    dry_run: Optional[bool] = None
