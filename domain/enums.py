from enum import Enum

class RoutineMode(str, Enum):
    AUTO = "AUTO"          # 완전 자동 발행
    REVIEW = "REVIEW"      # 초안 생성 후 사용자 검토 대기
    DRY_RUN = "DRY_RUN"    # 모의 실행 (발행 안 함)

class TriggerType(str, Enum):
    SCHEDULE = "SCHEDULE"
    MANUAL = "MANUAL"

class SourceType(str, Enum):
    RSS_ATOM = "RSS_ATOM"
    ARXIV = "ARXIV"
    HUGGINGFACE_PAPERS = "HUGGINGFACE_PAPERS"
    JSON_API = "JSON_API"
    SITE_ADAPTER = "SITE_ADAPTER"

class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    COLLECTING = "COLLECTING"
    CURATING = "CURATING"
    GENERATING = "GENERATING"
    PUBLISHING = "PUBLISHING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"

class StepType(str, Enum):
    PARENT = "PARENT"
    FIRST_REPLY = "FIRST_REPLY"

class JobStatus(str, Enum):
    PENDING = "PENDING"
    PARENT_PUBLISHED = "PARENT_PUBLISHED"
    REPLY_PUBLISHED = "REPLY_PUBLISHED"
    SUCCEEDED = "SUCCEEDED"
    RETRY_WAIT = "RETRY_WAIT"
    FAILED = "FAILED"

class ReplyProposalStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
