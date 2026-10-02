"""TubeInsight Threads & X 통합 자동화 공통 저장소 (SocialStore).

Phase 1 Rework v3 반영:
- P1-1: 동시 실행 일일 한도 초과 원천 차단 (reserve_engagement_slot - BEGIN IMMEDIATE 원자적 슬롯 예약).
- P1-2: 공통 실행 시도(social_job_attempts) 테이블 및 이력 보존 API 구현 (시도별 워커, 시작/종료 시각, 결과, 오류, 재시도 번호).
- P1-3: v1->v2 마이그레이션 시 하위 항목(social_job_items) 임시 백업 및 복원 (CASCADE 유실 방지).
- P2: worker_id와 locked_by 동시 전달 시 불일치(mismatch) 검증 (불일치 시 ValueError, 소유자 없는 running 진입 원천 차단).
- create_job 동시성 경쟁 조건 원천 차단 (INSERT ON CONFLICT DO NOTHING + SELECT).
- 경로 탐색(Path Traversal) 및 토큰 원문 저장 엄격 차단.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_PATH = DATA_DIR / "social_engagement.db"

CURRENT_SCHEMA_VERSION = 2

VALID_PLATFORMS = {"threads", "x"}
VALID_JOB_TYPES = {"publish", "reply", "engagement"}
VALID_JOB_STATUSES = {
    "draft",
    "approved",
    "scheduled",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
}

# 엄격한 상태 전이 매핑 (draft에서 바로 scheduled 또는 running으로 갈 수 없음)
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    "draft": {"approved", "cancelled"},
    "approved": {"scheduled", "running", "cancelled"},
    "scheduled": {"running", "cancelled", "approved"},
    "running": {"succeeded", "partial", "failed", "cancelled"},
    "partial": {"approved", "scheduled", "running", "cancelled"},
    "failed": {"approved", "scheduled", "running", "cancelled"},
    "cancelled": {"draft", "approved"},
    "succeeded": set(),  # 완료 상태는 전이 불가
}

# 허용된 자격증명 참조 형식 화이트리스트
SAFE_OPAQUE_REF_PATTERN = re.compile(
    r"^(env(:[A-Za-z0-9_]+)?|config:(threads|x))$"
)
SAFE_FILE_REF_PATTERN = re.compile(
    r"^(data|secrets)/[A-Za-z0-9_.-]+(\.json)?$"
)

# 민감정보(토큰/비밀번호/키) 마스킹 패턴
SENSITIVE_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.~+/=]+", re.IGNORECASE), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(access_token|client_secret|token|api_key|secret|password)=([^\s&'\"]+)",
            re.IGNORECASE,
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(
            r'("?(?:access_token|client_secret|token|api_key|secret|password)"?\s*:\s*)"([^"]+)"',
            re.IGNORECASE,
        ),
        r'\1"[REDACTED]"',
    ),
    (re.compile(r"\b(raw[-_]secret[-_]token[-_][A-Za-z0-9]+)\b", re.IGNORECASE), "[REDACTED]"),
]


def sanitize_sensitive_data(text: str) -> str:
    """텍스트 내 포함될 수 있는 토큰 및 자격증명 원문을 [REDACTED]로 마스킹."""
    if not text:
        return ""
    result = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def is_safe_credential_ref(ref: str) -> bool:
    """자격증명 참조 안전성 검증 (경로 탐색, 절대 경로, 토큰 원문 차단)."""
    if not ref:
        return True
    s = ref.strip()

    # 1. 공백, Bearer, 경로 탐색 기호(.., \\, //), 절대 경로(/ 또는 드라이브 문자) 거부
    if (
        " " in s
        or "bearer" in s.lower()
        or ".." in s
        or "\\" in s
        or "//" in s
        or s.startswith("/")
        or bool(re.match(r"^[A-Za-z]:", s))
    ):
        return False

    # 2. 토큰 원문 의심 패턴 차단
    if s.startswith("raw-") or len(s) > 120:
        return False

    # 3. Opaque 참조 (env, env:KEY, config:threads 등) 허용
    if SAFE_OPAQUE_REF_PATTERN.match(s):
        return True

    # 4. 파일 경로 참조 (data/*.json, secrets/*.json) 허용 및 정규화 경로 탈출 검사
    if SAFE_FILE_REF_PATTERN.match(s):
        try:
            resolved = (BASE_DIR / s).resolve()
            allowed_roots = [DATA_DIR.resolve(), (BASE_DIR / "secrets").resolve()]
            if any(str(resolved).startswith(str(root)) for root in allowed_roots):
                return True
        except Exception:
            return False

    return False


class SocialStoreError(Exception):
    """소셜 스토어 기본 예외"""
    pass


class InvalidStateTransitionError(SocialStoreError):
    """유효하지 않은 상태 전이 시도 예외"""
    pass


class JobNotFoundError(SocialStoreError):
    """작업을 찾을 수 없는 예외"""
    pass


class WorkerOwnershipError(SocialStoreError):
    """워커 리스 소유권 상실 또는 불일치 예외"""
    pass


class SocialStore:
    """Threads/X 통합 자동화 공통 저장소 클래스"""

    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self, immediate: bool = False):
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            if immediate:
                conn.isolation_level = None
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            else:
                with conn:
                    yield conn
        finally:
            conn.close()

    def get_schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("PRAGMA user_version").fetchone()
            return int(row[0]) if row else 0

    def _init_schema(self) -> None:
        with self._connect() as conn:
            row = conn.execute("PRAGMA user_version").fetchone()
            current_ver = int(row[0]) if row else 0

            # 미래 스키마 버전 거부
            if current_ver > CURRENT_SCHEMA_VERSION:
                raise SocialStoreError(
                    f"지원되지 않는 상위 스키마 버전입니다 ({current_ver} > {CURRENT_SCHEMA_VERSION}). "
                    f"애플리케이션 업데이트가 필요합니다."
                )

            # 1. 기존 engagement_events 테이블 보존 및 생성
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS engagement_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    day_key TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    detail TEXT NOT NULL DEFAULT '',
                    UNIQUE(platform, account_id, post_id, action, dry_run)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_engagement_day ON engagement_events(day_key, status)")

            # 2. social_accounts 테이블
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    credential_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    scopes TEXT NOT NULL DEFAULT '[]',
                    token_expires_at INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(platform, account_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_social_accounts_plat ON social_accounts(platform, status)")

            # 3. v1에서 v2로의 마이그레이션 처리
            if current_ver == 1:
                self._migrate_v1_to_v2(conn)
            elif current_ver == 0:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS social_jobs (
                        job_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        job_type TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'draft',
                        actor_account_id TEXT NOT NULL DEFAULT '',
                        dry_run INTEGER NOT NULL DEFAULT 1,
                        scheduled_at INTEGER DEFAULT 0,
                        approved_at INTEGER DEFAULT 0,
                        started_at INTEGER DEFAULT 0,
                        finished_at INTEGER DEFAULT 0,
                        locked_by TEXT DEFAULT '',
                        locked_at INTEGER DEFAULT 0,
                        target_id TEXT NOT NULL DEFAULT '',
                        target_url TEXT NOT NULL DEFAULT '',
                        content_payload TEXT NOT NULL DEFAULT '{}',
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        max_retries INTEGER NOT NULL DEFAULT 3,
                        last_error_code TEXT NOT NULL DEFAULT '',
                        last_error_message TEXT NOT NULL DEFAULT '',
                        result_payload TEXT NOT NULL DEFAULT '{}',
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        UNIQUE(platform, actor_account_id, idempotency_key)
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_social_jobs_sched ON social_jobs(status, scheduled_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_social_jobs_actor ON social_jobs(actor_account_id, platform)")
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

            # 4. social_job_items 타래/배치 하위 항목 테이블
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_job_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    item_index INTEGER NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    media_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    platform_post_id TEXT NOT NULL DEFAULT '',
                    platform_post_url TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    executed_at INTEGER DEFAULT 0,
                    UNIQUE(job_id, item_index),
                    FOREIGN KEY(job_id) REFERENCES social_jobs(job_id) ON DELETE CASCADE
                )
                """
            )

            # 5. social_dedup_keys 멱등성 및 중복 방지 키
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_dedup_keys (
                    dedup_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )

            # 6. social_job_attempts 실행 시도 테이블 (P1 필수 요구사항)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_job_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    worker_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at INTEGER NOT NULL,
                    finished_at INTEGER DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    result_payload TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    UNIQUE(job_id, attempt_number),
                    FOREIGN KEY(job_id) REFERENCES social_jobs(job_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_social_attempts_job ON social_job_attempts(job_id)")

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """v1 -> v2 마이그레이션. social_job_items 임시 백업 및 복원으로 ON DELETE CASCADE 유실 원천 방지."""
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='social_jobs'"
        ).fetchone()

        if table_exists:
            items_table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='social_job_items'"
            ).fetchone()
            if items_table_exists:
                conn.execute(
                    "CREATE TEMPORARY TABLE IF NOT EXISTS social_job_items_backup AS SELECT * FROM social_job_items"
                )
                conn.execute("DROP TABLE social_job_items")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_jobs_v2 (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    actor_account_id TEXT NOT NULL DEFAULT '',
                    dry_run INTEGER NOT NULL DEFAULT 1,
                    scheduled_at INTEGER DEFAULT 0,
                    approved_at INTEGER DEFAULT 0,
                    started_at INTEGER DEFAULT 0,
                    finished_at INTEGER DEFAULT 0,
                    locked_by TEXT DEFAULT '',
                    locked_at INTEGER DEFAULT 0,
                    target_id TEXT NOT NULL DEFAULT '',
                    target_url TEXT NOT NULL DEFAULT '',
                    content_payload TEXT NOT NULL DEFAULT '{}',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    last_error_code TEXT NOT NULL DEFAULT '',
                    last_error_message TEXT NOT NULL DEFAULT '',
                    result_payload TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(platform, actor_account_id, idempotency_key)
                )
                """
            )

            conn.execute(
                """
                INSERT OR IGNORE INTO social_jobs_v2
                (job_id, idempotency_key, platform, job_type, status, actor_account_id,
                 dry_run, scheduled_at, approved_at, started_at, finished_at,
                 locked_by, locked_at, target_id, target_url, content_payload,
                 retry_count, max_retries, last_error_code, last_error_message,
                 result_payload, created_at, updated_at)
                SELECT
                 job_id, idempotency_key, platform, job_type, status, actor_account_id,
                 dry_run, scheduled_at, approved_at, started_at, finished_at,
                 locked_by, locked_at, target_id, target_url, content_payload,
                 retry_count, max_retries, last_error_code, last_error_message,
                 result_payload, created_at, updated_at
                FROM social_jobs
                """
            )

            conn.execute("DROP TABLE social_jobs")
            conn.execute("ALTER TABLE social_jobs_v2 RENAME TO social_jobs")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_social_jobs_sched ON social_jobs(status, scheduled_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_social_jobs_actor ON social_jobs(actor_account_id, platform)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_job_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    item_index INTEGER NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    media_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    platform_post_id TEXT NOT NULL DEFAULT '',
                    platform_post_url TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    executed_at INTEGER DEFAULT 0,
                    UNIQUE(job_id, item_index),
                    FOREIGN KEY(job_id) REFERENCES social_jobs(job_id) ON DELETE CASCADE
                )
                """
            )
            if items_table_exists:
                conn.execute(
                    """
                    INSERT INTO social_job_items
                    (id, job_id, item_index, content, media_url, status, platform_post_id, platform_post_url, error_message, executed_at)
                    SELECT id, job_id, item_index, content, media_url, status, platform_post_id, platform_post_url, error_message, executed_at
                    FROM social_job_items_backup
                    """
                )
                conn.execute("DROP TABLE social_job_items_backup")

        # attempts 테이블 생성
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_job_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                worker_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                started_at INTEGER NOT NULL,
                finished_at INTEGER DEFAULT 0,
                error_code TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                result_payload TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                UNIQUE(job_id, attempt_number),
                FOREIGN KEY(job_id) REFERENCES social_jobs(job_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

    # ==========================================
    # 계정 메타데이터 관리 (소셜 계정)
    # ==========================================
    def upsert_account(
        self,
        platform: str,
        account_id: str,
        username: str = "",
        display_name: str = "",
        credential_ref: str = "",
        status: str = "active",
        scopes: Optional[List[str]] = None,
        token_expires_at: int = 0,
    ) -> Dict[str, Any]:
        """계정 메타데이터를 저장하거나 갱신 (토큰 원문 및 경로 탐색 엄격 차단)."""
        if platform not in VALID_PLATFORMS:
            raise ValueError(f"지원하지 않는 플랫폼입니다: {platform}")
        if not account_id:
            raise ValueError("account_id는 필수입니다.")

        if credential_ref and not is_safe_credential_ref(credential_ref):
            raise ValueError(
                f"유효하지 않은 credential_ref 형식입니다. 토큰 원문 또는 경로 탐색은 허용되지 않습니다: {credential_ref}"
            )

        now_ts = int(time.time())
        scopes_json = json.dumps(scopes or [], ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO social_accounts
                (platform, account_id, username, display_name, credential_ref, status, scopes, token_expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, account_id)
                DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    credential_ref = excluded.credential_ref,
                    status = excluded.status,
                    scopes = excluded.scopes,
                    token_expires_at = excluded.token_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    platform,
                    account_id,
                    username,
                    display_name,
                    credential_ref,
                    status,
                    scopes_json,
                    token_expires_at,
                    now_ts,
                    now_ts,
                ),
            )
        return self.get_account(platform, account_id) or {}

    def get_account(self, platform: str, account_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM social_accounts WHERE platform = ? AND account_id = ?",
                (platform, account_id),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["scopes"] = json.loads(data.get("scopes") or "[]")
            except Exception:
                data["scopes"] = []
            return data

    def list_accounts(self, platform: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            if platform:
                rows = conn.execute(
                    "SELECT * FROM social_accounts WHERE platform = ? ORDER BY id DESC",
                    (platform,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM social_accounts ORDER BY id DESC").fetchall()
            results = []
            for row in rows:
                d = dict(row)
                try:
                    d["scopes"] = json.loads(d.get("scopes") or "[]")
                except Exception:
                    d["scopes"] = []
                results.append(d)
            return results

    # ==========================================
    # 공통 작업 (social_jobs) 관리
    # ==========================================
    def create_job(
        self,
        platform: str,
        job_type: str,
        actor_account_id: str,
        idempotency_key: Optional[str] = None,
        dry_run: bool = True,
        scheduled_at: int = 0,
        target_id: str = "",
        target_url: str = "",
        content_payload: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        새 공통 작업을 생성하거나 동일 (platform, actor_account_id, idempotency_key)가 있으면 기존 작업 반환.
        INSERT ... ON CONFLICT DO NOTHING 후 SELECT로 동시성 경쟁 조건 원천 차단.
        """
        if platform not in VALID_PLATFORMS:
            raise ValueError(f"지원하지 않는 플랫폼: {platform}")
        if job_type not in VALID_JOB_TYPES:
            raise ValueError(f"지원하지 않는 작업 유형: {job_type}")

        now_ts = int(time.time())
        actor_clean = actor_account_id.strip() or "default"
        auto_idempotency = idempotency_key or f"ik_{platform}_{job_type}_{now_ts}_{uuid.uuid4().hex[:8]}"

        job_id = f"job_{int(now_ts)}_{uuid.uuid4().hex[:8]}"
        clean_content = sanitize_sensitive_data(json.dumps(content_payload or {}, ensure_ascii=False))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO social_jobs
                (job_id, idempotency_key, platform, job_type, status, actor_account_id,
                 dry_run, scheduled_at, approved_at, started_at, finished_at,
                 locked_by, locked_at, target_id, target_url, content_payload,
                 retry_count, max_retries, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, 0, 0, 0, '', 0, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(platform, actor_account_id, idempotency_key) DO NOTHING
                """,
                (
                    job_id,
                    auto_idempotency,
                    platform,
                    job_type,
                    actor_clean,
                    int(dry_run),
                    scheduled_at,
                    target_id,
                    target_url,
                    clean_content,
                    max_retries,
                    now_ts,
                    now_ts,
                ),
            )

            row = conn.execute(
                """
                SELECT * FROM social_jobs
                WHERE platform = ? AND actor_account_id = ? AND idempotency_key = ?
                """,
                (platform, actor_clean, auto_idempotency),
            ).fetchone()
            return self._parse_job_row(row) if row else {}

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM social_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return self._parse_job_row(row)

    def list_jobs(
        self,
        platform: Optional[str] = None,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        query = "SELECT * FROM social_jobs WHERE 1=1"
        params: List[Any] = []
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if job_type:
            query += " AND job_type = ?"
            params.append(job_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(safe_limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._parse_job_row(r) for r in rows]

    def transition_job_status(
        self,
        job_id: str,
        new_status: str,
        scheduled_at: Optional[int] = None,
        locked_by: Optional[str] = None,
        worker_id: Optional[str] = None,
        result_payload: Optional[Dict[str, Any]] = None,
        error_code: str = "",
        error_message: str = "",
    ) -> Dict[str, Any]:
        """
        작업 상태를 안전하게 전이하며 유효하지 않은 전이는 예외 처리.
        - P1: 승인 없는 작업의 예약/실행 차단 (approved_at > 0 필수).
        - P1: running 상태 진입 시 유효한 worker_id (또는 locked_by) 필수 강제.
        - P1: running 작업 완료/실패 시 소유자 펜싱 검증 및 social_job_attempts 동기화.
        - P2: worker_id와 locked_by 동시 입력 시 불일치(mismatch) 검증.
        """
        if new_status not in VALID_JOB_STATUSES:
            raise ValueError(f"유효하지 않은 상태값입니다: {new_status}")

        w = (worker_id or "").strip()
        l = (locked_by or "").strip()
        if w and l and w != l:
            raise ValueError(f"worker_id('{w}')와 locked_by('{l}')가 서로 일치하지 않습니다.")
        lock_owner = w or l

        now_ts = int(time.time())
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM social_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                raise JobNotFoundError(f"작업을 찾을 수 없습니다: {job_id}")

            current_status = row["status"]
            allowed = VALID_TRANSITIONS.get(current_status, set())
            if new_status not in allowed:
                raise InvalidStateTransitionError(
                    f"상태 전이 불가: '{current_status}' -> '{new_status}' (허용 목록: {allowed})"
                )

            # 승인 없이 scheduled 또는 running으로 전이 시도 차단
            effective_approved = row["approved_at"] > 0 or new_status == "approved"
            if new_status in {"scheduled", "running"} and not effective_approved:
                raise InvalidStateTransitionError(
                    "승인되지 않은 작업(approved_at=0)은 예약 또는 실행 상태로 전이할 수 없습니다. "
                    "먼저 approved 상태로 전환하세요."
                )

            # running 진입 시 소유자 필수 강제
            if new_status == "running" and not lock_owner:
                raise WorkerOwnershipError(
                    "작업을 running 상태로 전이하려면 유효한 worker_id (또는 locked_by)가 필수입니다."
                )

            # running 상태의 완료/실패/취소 전이 시 소유자 펜싱 검증
            if current_status == "running":
                if not lock_owner:
                    raise WorkerOwnershipError(
                        "실행 중인(running) 작업의 상태 전이를 완료하려면 유효한 worker_id가 필수입니다."
                    )
                current_locked_by = row["locked_by"]
                if current_locked_by != lock_owner:
                    raise WorkerOwnershipError(
                        f"워커 소유권 상실: 리스가 만료되어 다른 워커({current_locked_by})에 의해 재점유되었습니다. "
                        f"(요청 워커: {lock_owner})"
                    )

            updates: List[str] = ["status = ?", "updated_at = ?"]
            params: List[Any] = [new_status, now_ts]

            if new_status == "approved":
                updates.append("approved_at = ?")
                params.append(now_ts)

            if scheduled_at is not None:
                updates.append("scheduled_at = ?")
                params.append(scheduled_at)

            clean_err_msg = sanitize_sensitive_data(error_message[:4000]) if error_message else ""
            clean_err_code = sanitize_sensitive_data(error_code[:128]) if error_code else ""
            clean_result = sanitize_sensitive_data(json.dumps(result_payload, ensure_ascii=False)) if result_payload is not None else "{}"

            if new_status == "running":
                next_attempt = row["retry_count"] + 1
                updates.append("started_at = CASE WHEN started_at = 0 THEN ? ELSE started_at END")
                params.append(now_ts)
                updates.append("locked_by = ?")
                params.append(lock_owner)
                updates.append("locked_at = ?")
                params.append(now_ts)
                updates.append("retry_count = ?")
                params.append(next_attempt)

                # 이전 실행 시도가 running으로 남아있다면 lease_expired로 종료
                conn.execute(
                    """
                    UPDATE social_job_attempts
                    SET status = 'lease_expired',
                        finished_at = ?,
                        error_code = 'LEASE_EXPIRED',
                        error_message = 'Job lease expired or was preempted'
                    WHERE job_id = ?
                      AND status = 'running'
                    """,
                    (now_ts, job_id),
                )

                # social_job_attempts 새 시도 기록
                conn.execute(
                    """
                    INSERT INTO social_job_attempts
                    (job_id, attempt_number, worker_id, status, started_at, finished_at, created_at)
                    VALUES (?, ?, ?, 'running', ?, 0, ?)
                    """,
                    (job_id, next_attempt, lock_owner, now_ts, now_ts),
                )

            if new_status in {"succeeded", "partial", "failed", "cancelled"}:
                updates.append("finished_at = ?")
                params.append(now_ts)
                updates.append("locked_by = ''")
                updates.append("locked_at = 0")

                # 활성 attempt 완료 업데이트
                conn.execute(
                    """
                    UPDATE social_job_attempts
                    SET status = ?,
                        finished_at = ?,
                        error_code = ?,
                        error_message = ?,
                        result_payload = ?
                    WHERE job_id = ? AND attempt_number = ?
                    """,
                    (
                        new_status,
                        now_ts,
                        clean_err_code,
                        clean_err_msg,
                        clean_result,
                        job_id,
                        row["retry_count"],
                    ),
                )

            if result_payload is not None:
                updates.append("result_payload = ?")
                params.append(clean_result)

            if error_code or error_message:
                updates.append("last_error_code = ?")
                params.append(clean_err_code)
                updates.append("last_error_message = ?")
                params.append(clean_err_msg)

            if current_status == "running":
                sql = f"UPDATE social_jobs SET {', '.join(updates)} WHERE job_id = ? AND status = 'running' AND locked_by = ?"
                params.extend([job_id, lock_owner])
            else:
                sql = f"UPDATE social_jobs SET {', '.join(updates)} WHERE job_id = ? AND status = ?"
                params.extend([job_id, current_status])

            res = conn.execute(sql, params)
            if res.rowcount == 0:
                check_row = conn.execute("SELECT status, locked_by FROM social_jobs WHERE job_id = ?", (job_id,)).fetchone()
                if not check_row:
                    raise JobNotFoundError(f"작업을 찾을 수 없습니다: {job_id}")
                raise WorkerOwnershipError(
                    f"상태 전이 경쟁 충돌 또는 워커 소유권 상실: "
                    f"현재 상태={check_row['status']}, 현재 점유={check_row['locked_by']}"
                )

        return self.get_job(job_id) or {}

    # ==========================================
    # 실행 시도 (social_job_attempts) 관리
    # ==========================================
    def get_job_attempts(self, job_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM social_job_attempts WHERE job_id = ? ORDER BY attempt_number ASC",
                (job_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                try:
                    d["result_payload"] = json.loads(d.get("result_payload") or "{}")
                except Exception:
                    d["result_payload"] = {}
                results.append(d)
            return results

    def record_job_attempt(
        self,
        job_id: str,
        attempt_number: int,
        worker_id: str,
        status: str = "running",
        started_at: Optional[int] = None,
        finished_at: int = 0,
        error_code: str = "",
        error_message: str = "",
        result_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now_ts = int(time.time())
        st_at = started_at if started_at is not None else now_ts
        clean_err = sanitize_sensitive_data(error_message[:4000])
        clean_code = sanitize_sensitive_data(error_code[:128])
        clean_res = sanitize_sensitive_data(json.dumps(result_payload or {}, ensure_ascii=False))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO social_job_attempts
                (job_id, attempt_number, worker_id, status, started_at, finished_at, error_code, error_message, result_payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, attempt_number)
                DO UPDATE SET
                    worker_id = excluded.worker_id,
                    status = excluded.status,
                    finished_at = excluded.finished_at,
                    error_code = excluded.error_code,
                    error_message = excluded.error_message,
                    result_payload = excluded.result_payload
                """,
                (
                    job_id,
                    attempt_number,
                    worker_id,
                    status,
                    st_at,
                    finished_at,
                    clean_code,
                    clean_err,
                    clean_res,
                    now_ts,
                ),
            )
            row = conn.execute(
                "SELECT * FROM social_job_attempts WHERE job_id = ? AND attempt_number = ?",
                (job_id, attempt_number),
            ).fetchone()
            return dict(row) if row else {}

    # ==========================================
    # 원자적 작업 점유 및 리스 갱신 (Atomic Job Lease & Fencing)
    # ==========================================
    def acquire_job_lease(
        self,
        worker_id: str,
        now_timestamp: Optional[int] = None,
        lease_timeout_seconds: int = 300,
    ) -> Optional[Dict[str, Any]]:
        """
        실행 대기 중인 작업 중 실행 시각이 도래한 작업을 원자적으로 점유하고 social_job_attempts에 시도 기록.
        - approved_at > 0 (사전 승인된 작업)만 점유 대상.
        """
        worker_clean = (worker_id or "").strip()
        if not worker_clean:
            raise ValueError("worker_id는 필수입니다.")

        now_ts = int(now_timestamp if now_timestamp is not None else time.time())
        expired_threshold = now_ts - lease_timeout_seconds

        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT job_id, retry_count FROM social_jobs
                WHERE approved_at > 0
                  AND (
                    (status IN ('approved', 'scheduled') AND (scheduled_at <= 0 OR scheduled_at <= ?))
                    OR
                    (status = 'running' AND locked_at > 0 AND locked_at < ?)
                  )
                ORDER BY scheduled_at ASC, created_at ASC
                LIMIT 1
                """,
                (now_ts, expired_threshold),
            )
            row = cursor.fetchone()
            if not row:
                return None

            candidate_id = row["job_id"]
            next_attempt = row["retry_count"] + 1

            result = conn.execute(
                """
                UPDATE social_jobs
                SET status = 'running',
                    locked_by = ?,
                    locked_at = ?,
                    started_at = CASE WHEN started_at = 0 THEN ? ELSE started_at END,
                    retry_count = ?,
                    updated_at = ?
                WHERE job_id = ?
                  AND approved_at > 0
                  AND (
                      status IN ('approved', 'scheduled')
                      OR (status = 'running' AND locked_at > 0 AND locked_at < ?)
                  )
                """,
                (worker_clean, now_ts, now_ts, next_attempt, now_ts, candidate_id, expired_threshold),
            )
            if result.rowcount == 0:
                return None

            # 만료된 리스 재점유 시 이전 실행 시도(running)를 같은 트랜잭션에서 lease_expired로 종료
            conn.execute(
                """
                UPDATE social_job_attempts
                SET status = 'lease_expired',
                    finished_at = ?,
                    error_code = 'LEASE_EXPIRED',
                    error_message = 'Job lease expired and was reclaimed by another worker'
                WHERE job_id = ?
                  AND status = 'running'
                """,
                (now_ts, candidate_id),
            )

            # social_job_attempts 새 시도 기록
            conn.execute(
                """
                INSERT INTO social_job_attempts
                (job_id, attempt_number, worker_id, status, started_at, finished_at, created_at)
                VALUES (?, ?, ?, 'running', ?, 0, ?)
                """,
                (candidate_id, next_attempt, worker_clean, now_ts, now_ts),
            )

            job_row = conn.execute(
                "SELECT * FROM social_jobs WHERE job_id = ?", (candidate_id,)
            ).fetchone()
            return self._parse_job_row(job_row) if job_row else None

    def renew_job_lease(
        self,
        job_id: str,
        worker_id: str,
        now_timestamp: Optional[int] = None,
    ) -> bool:
        worker_clean = (worker_id or "").strip()
        if not worker_clean:
            return False
        now_ts = int(now_timestamp if now_timestamp is not None else time.time())
        with self._connect() as conn:
            res = conn.execute(
                """
                UPDATE social_jobs
                SET locked_at = ?,
                    updated_at = ?
                WHERE job_id = ? AND status = 'running' AND locked_by = ?
                """,
                (now_ts, now_ts, job_id, worker_clean),
            )
            return res.rowcount > 0

    # ==========================================
    # 작업 하위 항목 (social_job_items)
    # ==========================================
    def add_job_items(self, job_id: str, items: List[Dict[str, Any]]) -> None:
        with self._connect() as conn:
            for item in items:
                clean_content = sanitize_sensitive_data(item.get("content", ""))
                conn.execute(
                    """
                    INSERT INTO social_job_items
                    (job_id, item_index, content, media_url, status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, item_index)
                    DO UPDATE SET
                        content = excluded.content,
                        media_url = excluded.media_url,
                        status = excluded.status
                    """,
                    (
                        job_id,
                        int(item.get("item_index", 0)),
                        clean_content,
                        item.get("media_url", ""),
                        item.get("status", "pending"),
                    ),
                )

    def get_job_items(self, job_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM social_job_items WHERE job_id = ? ORDER BY item_index ASC",
                (job_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_job_item(
        self,
        job_id: str,
        item_index: int,
        status: str,
        platform_post_id: str = "",
        platform_post_url: str = "",
        error_message: str = "",
    ) -> None:
        now_ts = int(time.time())
        clean_err = sanitize_sensitive_data(error_message[:2000])
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE social_job_items
                SET status = ?,
                    platform_post_id = ?,
                    platform_post_url = ?,
                    error_message = ?,
                    executed_at = ?
                WHERE job_id = ? AND item_index = ?
                """,
                (
                    status,
                    platform_post_id,
                    platform_post_url,
                    clean_err,
                    now_ts,
                    job_id,
                    item_index,
                ),
            )

    # ==========================================
    # 실행 계정(actor_account_id) 기반 멱등/중복 방지
    # ==========================================
    def record_dedup_action(
        self,
        platform: str,
        actor_account_id: str,
        action: str,
        target_id: str,
        post_id: str = "",
        dry_run: bool = False,
        job_id: str = "",
    ) -> bool:
        now_ts = int(time.time())
        actor_clean = actor_account_id.strip() or "default"
        target_clean = target_id.strip() or post_id.strip()
        dedup_key = f"{platform}:{actor_clean}:{action}:{target_clean}:{int(dry_run)}"

        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO social_dedup_keys (dedup_key, job_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (dedup_key, job_id, now_ts),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def is_action_already_done(
        self,
        platform: str,
        actor_account_id: str,
        action: str,
        target_id: str,
        dry_run: bool = False,
    ) -> bool:
        actor_clean = actor_account_id.strip() or "default"
        dedup_key = f"{platform}:{actor_clean}:{action}:{target_id.strip()}:{int(dry_run)}"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM social_dedup_keys WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
            return row is not None

    # ==========================================
    # 원자적 일일 슬롯 예약 (P1 동시성 일일 한도 초과 방지)
    # ==========================================
    def reserve_engagement_slot(
        self,
        platform: str,
        actor_account_id: str,
        action: str,
        target_id: str,
        daily_total_limit: int = 100,
        daily_action_limit: int = 50,
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        """
        BEGIN IMMEDIATE 쓰기 트랜잭션으로 중복 검사, 일일 한도 검사, 슬롯 예약을 원자적으로 수행.
        동시 다중 워커 실행 시에도 일일 한도 초과를 완벽 차단.
        """
        if dry_run:
            if self.is_action_already_done(platform, actor_account_id, action, target_id, dry_run=True):
                return False, "skipped_duplicate"
            return True, "dry_run"

        actor_clean = actor_account_id.strip() or "default"
        day = self._day_key()
        dedup_key = f"{platform}:{actor_clean}:{action}:{target_id.strip()}:0"

        with self._connect(immediate=True) as conn:
            # 1. 중복 확인
            row = conn.execute(
                "SELECT 1 FROM social_dedup_keys WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
            if row is not None:
                return False, "skipped_duplicate"

            # 2. 일일 전체 한도 확인
            total_count = conn.execute(
                """SELECT COUNT(*) FROM engagement_events
                   WHERE day_key=? AND dry_run=0 AND status IN ('success', 'already_done', 'reserved')""",
                (day,),
            ).fetchone()[0]
            if total_count >= daily_total_limit:
                return False, "daily_total"

            # 3. 일일 동작별 한도 확인
            action_count = conn.execute(
                """SELECT COUNT(*) FROM engagement_events
                   WHERE day_key=? AND action=? AND dry_run=0 AND status IN ('success', 'already_done', 'reserved')""",
                (day, action),
            ).fetchone()[0]
            if action_count >= daily_action_limit:
                return False, f"daily_{action}"

            # 4. 슬롯 예약 등록 (engagement_events와 social_dedup_keys 모두 원자적 기록)
            now_ts = int(time.time())
            conn.execute(
                """INSERT INTO engagement_events
                   (created_at, day_key, platform, account_id, post_id, action, status, dry_run, detail)
                   VALUES (?, ?, ?, ?, ?, ?, 'reserved', 0, 'slot_reserved')
                   ON CONFLICT(platform, account_id, post_id, action, dry_run)
                   DO UPDATE SET created_at=excluded.created_at, day_key=excluded.day_key,
                                 status='reserved', detail='slot_reserved'""",
                (now_ts, day, platform, actor_clean, target_id, action),
            )
            conn.execute(
                """INSERT INTO social_dedup_keys (dedup_key, job_id, created_at)
                   VALUES (?, 'reserved', ?)""",
                (dedup_key, now_ts),
            )
            return True, "reserved"

    def reconcile_stale_reservations(self, timeout_seconds: int = 600) -> int:
        """
        프로세스 비정상 종료 등으로 오래된 'reserved' 상태에 머물러 있는 슬롯을 'unknown'으로 전환하고
        dedup_key를 정리하여 영구 차단을 방지하는 안전 복구 절차.
        """
        now_ts = int(time.time())
        stale_threshold = now_ts - max(0, timeout_seconds)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, platform, account_id, post_id, action, dry_run
                FROM engagement_events
                WHERE status = 'reserved' AND created_at <= ?
                """,
                (stale_threshold,),
            ).fetchall()

            if not rows:
                return 0

            conn.execute(
                """
                UPDATE engagement_events
                SET status = 'unknown',
                    detail = 'reservation_timed_out_reconciled'
                WHERE status = 'reserved' AND created_at <= ?
                """,
                (stale_threshold,),
            )

            for r in rows:
                actor_clean = (r["account_id"] or "").strip() or "default"
                dedup_key = f"{r['platform']}:{actor_clean}:{r['action']}:{r['post_id']}:{r['dry_run']}"
                conn.execute(
                    "DELETE FROM social_dedup_keys WHERE dedup_key = ? AND job_id = 'reserved'",
                    (dedup_key,),
                )
            return len(rows)

    # ==========================================
    # 기존 engagement_events 호환 인터페이스
    # ==========================================
    @staticmethod
    def _day_key() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def record_engagement(
        self,
        platform: str,
        account_id: str,
        post_id: str,
        action: str,
        status: str,
        dry_run: bool,
        detail: Any = "",
    ) -> None:
        detail_raw = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        detail_text = sanitize_sensitive_data(detail_raw)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO engagement_events
                   (created_at, day_key, platform, account_id, post_id, action, status, dry_run, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, account_id, post_id, action, dry_run)
                   DO UPDATE SET created_at=excluded.created_at, day_key=excluded.day_key,
                                 status=excluded.status, detail=excluded.detail""",
                (
                    int(time.time()),
                    self._day_key(),
                    platform,
                    account_id,
                    post_id,
                    action,
                    status,
                    int(dry_run),
                    detail_text[:4000],
                ),
            )

    def history(self, limit: int = 100) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM engagement_events ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ==========================================
    # 내부 유틸
    # ==========================================
    def _parse_job_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["content_payload"] = json.loads(data.get("content_payload") or "{}")
        except Exception:
            data["content_payload"] = {}
        try:
            data["result_payload"] = json.loads(data.get("result_payload") or "{}")
        except Exception:
            data["result_payload"] = {}
        return data
