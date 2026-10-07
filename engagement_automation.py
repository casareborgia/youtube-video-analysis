"""Threads/X 참여 자동화 엔진.

스하리(팔로우 + 좋아요 + 리포스트)를 대상별로 한 번만 실행하고,
일일 한도와 감사 로그를 SQLite에 보관한다. 실제 실행은 명시적으로
dry_run=False를 전달했을 때만 허용한다.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple

import social_store
from social_store import SocialStore, sanitize_sensitive_data

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "social_engagement.db"

SUPPORTED_PLATFORMS = {"threads", "x"}
SUPPORTED_ACTIONS = ("follow", "like", "repost", "reply")


class EngagementError(RuntimeError):
    pass


class UnsupportedAction(EngagementError):
    pass


@dataclass(frozen=True)
class EngagementTarget:
    platform: str
    post_id: str
    account_id: str
    post_url: str = ""
    profile_url: str = ""
    label: str = ""
    reply_text: str = ""

    def validate(self) -> None:
        if self.platform not in SUPPORTED_PLATFORMS:
            raise ValueError("platform은 threads 또는 x여야 합니다.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.post_id or ""):
            raise ValueError("post_id 형식이 올바르지 않습니다.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", self.account_id or ""):
            raise ValueError("account_id 형식이 올바르지 않습니다.")
        allowed = ("threads.net", "threads.com") if self.platform == "threads" else ("x.com", "twitter.com")
        for url in (self.post_url, self.profile_url):
            if url:
                parsed = urllib.parse.urlparse(url)
                host = (parsed.hostname or "").lower()
                if parsed.scheme != "https" or not any(host == d or host.endswith("." + d) for d in allowed):
                    raise ValueError("Threads 또는 X의 HTTPS URL만 사용할 수 있습니다.")


@dataclass
class EngagementPolicy:
    max_targets_per_request: int = 10
    daily_total: int = 30
    daily_follow: int = 10
    daily_like: int = 25
    daily_repost: int = 10
    daily_reply: int = 15
    delay_seconds: float = 2.0

    def limit_for(self, action: str) -> int:
        return int(getattr(self, f"daily_{action}"))


class EngagementClient(Protocol):
    def perform(self, action: str, target: EngagementTarget) -> Dict[str, Any]: ...


class EngagementStore:
    """
    스하리 참여 이력 및 일일 한도 저장소.
    SocialStore와 동일한 DB 및 통합 스키마를 공유하며,
    공통 작업(social_jobs) 및 항목(social_job_items)과 완벽 동기화된다.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # SocialStore와 스키마 및 DB 인스턴스 공유
        self.social_store = SocialStore(path=self.path)
        self._init_schema()

    @contextmanager
    def _connect(self, immediate: bool = False):
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
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

    def _init_schema(self):
        with self._connect() as conn:
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

    @staticmethod
    def _day_key() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def already_completed(self, target: EngagementTarget, action: str, dry_run: bool) -> bool:
        """
        이미 성공 또는 완료된 상태인지 확인 (중복 실행 및 토글/취소 방지).
        """
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM engagement_events
                   WHERE platform=? AND account_id=? AND post_id=? AND action=?
                     AND dry_run=? AND status IN ('success', 'already_done', 'dry_run')""",
                (target.platform, target.account_id, target.post_id, action, int(dry_run)),
            ).fetchone()
        return row is not None

    def reserve_slot(
        self,
        target: EngagementTarget,
        action: str,
        policy: EngagementPolicy,
        dry_run: bool,
    ) -> Tuple[bool, str]:
        """
        BEGIN IMMEDIATE 쓰기 트랜잭션으로 중복 검사, 일일 한도 검사, 실행 슬롯 예약을 원자적 수행.
        동시 다중 워커 실행 시에도 일일 한도 초과를 원천 차단.
        """
        if dry_run:
            if self.already_completed(target, action, dry_run=True):
                return False, "skipped_duplicate"
            return True, "dry_run"

        with self._connect(immediate=True) as conn:
            # 1. 중복 확인
            row = conn.execute(
                """SELECT 1 FROM engagement_events
                   WHERE platform=? AND account_id=? AND post_id=? AND action=?
                     AND dry_run=0 AND status IN ('success', 'already_done', 'reserved')""",
                (target.platform, target.account_id, target.post_id, action),
            ).fetchone()
            if row is not None:
                return False, "skipped_duplicate"

            # 2. 일일 전체 한도 확인 (진행 중인 reserved 슬롯 포함)
            day = self._day_key()
            total_count = conn.execute(
                """SELECT COUNT(*) FROM engagement_events
                   WHERE day_key=? AND dry_run=0 AND status IN ('success', 'already_done', 'reserved')""",
                (day,),
            ).fetchone()[0]
            if total_count >= policy.daily_total:
                return False, "daily_total"

            # 3. 일일 동작별 한도 확인
            action_count = conn.execute(
                """SELECT COUNT(*) FROM engagement_events
                   WHERE day_key=? AND action=? AND dry_run=0 AND status IN ('success', 'already_done', 'reserved')""",
                (day, action),
            ).fetchone()[0]
            if action_count >= policy.limit_for(action):
                return False, f"daily_{action}"

            # 4. 슬롯 원자적 예약 (status='reserved')
            now_ts = int(time.time())
            conn.execute(
                """INSERT INTO engagement_events
                   (created_at, day_key, platform, account_id, post_id, action, status, dry_run, detail)
                   VALUES (?, ?, ?, ?, ?, ?, 'reserved', 0, 'slot_reserved')
                   ON CONFLICT(platform, account_id, post_id, action, dry_run)
                   DO UPDATE SET created_at=excluded.created_at, day_key=excluded.day_key,
                                 status='reserved', detail='slot_reserved'""",
                (now_ts, day, target.platform, target.account_id, target.post_id, action),
            )
            # social_dedup_keys 동시 등록
            dedup_key = f"{target.platform}:{target.account_id}:{action}:{target.post_id}:0"
            conn.execute(
                """INSERT OR REPLACE INTO social_dedup_keys (dedup_key, job_id, created_at)
                   VALUES (?, 'reserved', ?)""",
                (dedup_key, now_ts),
            )
            return True, "reserved"

    def daily_count(self, action: Optional[str] = None) -> int:
        query = "SELECT COUNT(*) FROM engagement_events WHERE day_key=? AND dry_run=0 AND status IN ('success','already_done')"
        params: List[Any] = [self._day_key()]
        if action:
            query += " AND action=?"
            params.append(action)
        with self._connect() as conn:
            return int(conn.execute(query, params).fetchone()[0])

    def record(self, target: EngagementTarget, action: str, status: str, dry_run: bool, detail: Any = ""):
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
                    int(time.time()), self._day_key(), target.platform, target.account_id,
                    target.post_id, action, status, int(dry_run), detail_text[:4000],
                ),
            )
            # 완료 시 dedup_key 업데이트
            if not dry_run and status in ("success", "already_done"):
                dedup_key = f"{target.platform}:{target.account_id}:{action}:{target.post_id}:0"
                conn.execute(
                    """INSERT OR REPLACE INTO social_dedup_keys (dedup_key, job_id, created_at)
                       VALUES (?, ?, ?)""",
                    (dedup_key, status, int(time.time())),
                )
            elif not dry_run and status in ("failed", "web_required"):
                dedup_key = f"{target.platform}:{target.account_id}:{action}:{target.post_id}:0"
                conn.execute(
                    "DELETE FROM social_dedup_keys WHERE dedup_key = ? AND job_id = 'reserved'",
                    (dedup_key,),
                )

    def history(self, limit: int = 100) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM engagement_events ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [dict(row) for row in rows]


def _json_request(url: str, method: str, token: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise EngagementError(f"API 오류 {exc.code}: {sanitize_sensitive_data(raw[:500])}") from exc


class XApiEngagementClient:
    """X API v2 공식 사용자 참여 동작 (좋아요, 팔로우, 리포스트)."""

    def __init__(self, token: Optional[str] = None, acting_user_id: Optional[str] = None):
        import x_client

        conf = x_client.load_config()
        self.token = (token or conf.get("access_token") or os.environ.get("X_USER_ACCESS_TOKEN", "")).strip()
        self.acting_user_id = (acting_user_id or conf.get("user_id") or os.environ.get("X_USER_ID", "")).strip()
        if not self.token or not self.acting_user_id:
            raise EngagementError("X_USER_ACCESS_TOKEN과 X_USER_ID가 필요합니다. X 로그인이 필요합니다.")

    def perform(self, action: str, target: EngagementTarget) -> Dict[str, Any]:
        import x_client

        try:
            if action == "follow":
                res = x_client.follow_user(
                    target_user_id=target.account_id,
                    acting_user_id=self.acting_user_id,
                    access_token=self.token,
                )
                return {"status": "success", "response": res, "via": "official_api"}
            if action == "like":
                res = x_client.like_tweet(
                    tweet_id=target.post_id,
                    acting_user_id=self.acting_user_id,
                    access_token=self.token,
                )
                return {"status": "success", "response": res, "via": "official_api"}
            if action == "repost":
                res = x_client.retweet(
                    tweet_id=target.post_id,
                    acting_user_id=self.acting_user_id,
                    access_token=self.token,
                )
                return {"status": "success", "response": res, "via": "official_api"}
        except x_client.XClientError as exc:
            # 이미 좋아요/팔로우된 상태인 경우 에러 메시지 분석
            msg = str(exc).lower()
            if "already" in msg or "duplicate" in msg:
                return {"status": "already_done", "detail": str(exc), "via": "official_api"}
            raise EngagementError(str(exc)) from exc
        raise UnsupportedAction(f"X에서 지원하지 않는 동작: {action}")


class ThreadsApiEngagementClient:
    """Threads 공식 API 참여 동작. 공개 Graph API에서는 리포스트만 공식 제공한다."""

    def __init__(self, token: Optional[str] = None):
        if token is None:
            import threads_client
            token = threads_client.load_config().get("access_token", "")
        self.token = (token or "").strip()
        if not self.token:
            raise EngagementError("Threads Access Token이 필요합니다.")

    def perform(self, action: str, target: EngagementTarget) -> Dict[str, Any]:
        import threads_client

        if action == "repost":
            try:
                res = threads_client.repost_post(post_id=target.post_id, access_token=self.token)
                return {"status": "success", "response": res, "via": "official_api"}
            except Exception as exc:
                msg = str(exc).lower()
                if "already" in msg or "duplicate" in msg:
                    return {"status": "already_done", "detail": str(exc), "via": "official_api"}
                raise EngagementError(str(exc)) from exc
        elif action == "reply":
            reply_text = (getattr(target, "reply_text", "") or "").strip()
            if not reply_text:
                raise EngagementError(f"답글 본문(reply_text)이 비어 있어 발행할 수 없습니다. (대상: {target.account_id})")
            try:
                res = threads_client.reply_to_post(post_id=target.post_id, text=reply_text, access_token=self.token)
                return {"status": "success", "response": res, "via": "official_api"}
            except Exception as exc:
                msg = str(exc).lower()
                if "already" in msg or "duplicate" in msg:
                    return {"status": "already_done", "detail": str(exc), "via": "official_api"}
                raise EngagementError(str(exc)) from exc
        else:
            raise UnsupportedAction(
                f"Threads 공식 API는 '{action}' 동작을 제공하지 않습니다. (공식 지원 동작: repost, reply)"
            )


class WebEngagementClient:
    """Threads/X 웹 UI 폴백.

    전용 Playwright 프로필을 사용한다.
    이미 완료된 상태를 사전에 감지하여 취소(Un-like, Un-follow)를 절대 수행하지 않는다.
    """

    def __init__(self, profile_dir: Optional[str] = None, headless: Optional[bool] = None):
        self.profile_dir = str(profile_dir or os.environ.get(
            "SOCIAL_BROWSER_PROFILE_DIR", DATA_DIR / "social_browser_profile"
        ))
        self.headless = bool(headless) if headless is not None else os.environ.get(
            "SOCIAL_BROWSER_HEADLESS", "false"
        ).lower() == "true"

    @staticmethod
    def _playwright():
        try:
            from playwright.sync_api import sync_playwright
            return sync_playwright
        except ImportError as exc:
            raise EngagementError(
                "웹 폴백에는 playwright가 필요합니다: pip install playwright && playwright install chromium"
            ) from exc

    def open_login_session(self):
        sync_playwright = self._playwright()
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(self.profile_dir, headless=False)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.threads.com/", wait_until="domcontentloaded")
            x_page = context.new_page()
            x_page.goto("https://x.com/", wait_until="domcontentloaded")
            input("Threads와 X 로그인을 마친 뒤 Enter를 누르세요...")
            context.close()

    @staticmethod
    def _first_visible(page, selectors: Iterable[str]):
        for selector in selectors:
            locator = page.locator(selector)
            for idx in range(min(locator.count(), 5)):
                candidate = locator.nth(idx)
                if candidate.is_visible():
                    return candidate
        return None

    def perform(self, action: str, target: EngagementTarget) -> Dict[str, Any]:
        url = target.profile_url if action == "follow" else target.post_url
        if not url:
            raise EngagementError(f"웹 {action} 실행에는 대상 URL이 필요합니다.")

        sync_playwright = self._playwright()
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                self.profile_dir, headless=self.headless, viewport={"width": 1280, "height": 900}
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1200)

            # 사전 상태 검사: 이미 완료된 경우 절대 클릭하지 않고 즉시 already_done 반환
            if action == "follow":
                done = self._first_visible(page, [
                    f'button[data-testid="{target.account_id}-unfollow"]',
                    'button:has-text("Following")', 'button:has-text("팔로잉")',
                    'button[aria-label*="Following"]', 'button[aria-label*="팔로잉"]',
                ])
                if done:
                    context.close()
                    return {"status": "already_done", "via": "web"}
                button = self._first_visible(page, [
                    f'button[data-testid="{target.account_id}-follow"]',
                    'button:has-text("Follow")', 'button:has-text("팔로우")',
                    'button[aria-label*="Follow"]', 'button[aria-label*="팔로우"]',
                ])
            elif action == "like":
                done = self._first_visible(page, [
                    'button[aria-label*="Unlike"]', 'button[aria-label*="좋아요 취소"]',
                    '[data-testid="unlike"]',
                ])
                if done:
                    context.close()
                    return {"status": "already_done", "via": "web"}
                button = self._first_visible(page, [
                    'button[aria-label*="Like"]', 'button[aria-label*="좋아요"]',
                    '[data-testid="like"]',
                ])
            elif action == "repost":
                done = self._first_visible(page, [
                    '[data-testid="unretweet"]',
                    'button[aria-label*="Undo repost"]',
                    'button[aria-label*="리포스트 취소"]',
                    'button[aria-label*="Reposted"]',
                ])
                if done:
                    context.close()
                    return {"status": "already_done", "via": "web"}
                button = self._first_visible(page, [
                    '[data-testid="retweet"]',
                    'button[aria-label*="Repost"]', 'button[aria-label*="리포스트"]',
                ])
            else:
                context.close()
                raise UnsupportedAction(action)

            if not button:
                context.close()
                raise EngagementError(f"{action} 버튼을 찾지 못했습니다. 로그인 상태나 UI 변경을 확인하세요.")
            button.click()

            if action == "repost":
                page.wait_for_timeout(400)
                confirm = self._first_visible(page, [
                    '[role="menuitem"]:has-text("Repost")',
                    '[role="menuitem"]:has-text("리포스트")',
                    '[role="dialog"] button:has-text("Repost")',
                    '[role="dialog"] button:has-text("리포스트")',
                ])
                if confirm:
                    confirm.click()
            page.wait_for_timeout(600)
            context.close()
        return {"status": "success", "via": "web"}


class EngagementAutomationService:
    def __init__(self, store: Optional[EngagementStore] = None, policy: Optional[EngagementPolicy] = None):
        self.store = store if store is not None else EngagementStore()
        self.policy = policy if policy is not None else EngagementPolicy()

    def _client(self, platform: str, use_web_fallback: bool) -> EngagementClient:
        if use_web_fallback:
            return WebEngagementClient()
        if platform == "threads":
            return ThreadsApiEngagementClient()
        if platform == "x":
            return XApiEngagementClient()
        raise ValueError(platform)

    def execute(
        self,
        targets: List[EngagementTarget],
        actions: Optional[List[str]] = None,
        dry_run: bool = True,
        use_web_fallback: bool = False,
        actor_account_id: str = "",
    ) -> Dict[str, Any]:
        actions = list(SUPPORTED_ACTIONS) if actions is None else actions
        if not targets:
            raise ValueError("대상이 비어 있습니다.")
        if len(targets) > self.policy.max_targets_per_request:
            raise ValueError(f"한 번에 최대 {self.policy.max_targets_per_request}개 대상만 처리할 수 있습니다.")
        if not actions or any(a not in SUPPORTED_ACTIONS for a in actions):
            raise ValueError(f"actions는 {', '.join(SUPPORTED_ACTIONS)}만 사용할 수 있습니다.")
        if len(actions) != len(set(actions)):
            raise ValueError("actions에 같은 동작을 중복 지정할 수 없습니다.")
        for target in targets:
            target.validate()

        # 공통 작업 모델(social_jobs) 등록
        primary_platform = targets[0].platform
        primary_account = targets[0].account_id
        job_id = None
        if hasattr(self.store, "social_store"):
            try:
                job_res = self.store.social_store.create_job(
                    platform=primary_platform,
                    job_type="engagement",
                    actor_account_id=primary_account,
                    dry_run=dry_run,
                    content_payload={
                        "targets_count": len(targets),
                        "actions": actions,
                        "dry_run": dry_run,
                        "use_web_fallback": use_web_fallback,
                    },
                )
                job_id = job_res.get("job_id")
                if job_id:
                    self.store.social_store.update_job_status(job_id=job_id, status="running")
            except Exception:
                job_id = None

        results = []
        has_failure = False
        has_success = False

        for target_idx, target in enumerate(targets):
            for action in actions:
                item = {
                    "platform": target.platform,
                    "post_id": target.post_id,
                    "action": action,
                    "account_id": target.account_id,
                    "target_label": target.label,
                    "post_url": target.post_url,
                    "profile_url": target.profile_url,
                    "reply_text": target.reply_text,
                }

                # 답글 동작 시 답글 본문 필수 검증 (비어 있으면 발행 차단)
                if action == "reply" and not (target.reply_text or "").strip():
                    item.update(status="skipped_missing_reply_text", detail="답글 본문이 비어 있어 실행이 제외되었습니다.")
                    results.append(item)
                    if job_id and hasattr(self.store, "social_store"):
                        self.store.social_store.add_job_item(
                            job_id=job_id,
                            item_order=len(results),
                            content={"target": target.__dict__, "action": action},
                            status="skipped_missing_reply_text",
                            error_message="답글 본문이 비어 있음",
                        )
                    continue

                allowed, reason = self.store.reserve_slot(target, action, self.policy, dry_run)
                if not allowed:
                    if reason == "skipped_duplicate":
                        item["status"] = "skipped_duplicate"
                    else:
                        item.update(status="blocked_quota", detail=reason)
                        has_failure = True
                    results.append(item)
                    if job_id and hasattr(self.store, "social_store"):
                        self.store.social_store.add_job_item(
                            job_id=job_id,
                            item_order=len(results),
                            content={"target": target.__dict__, "action": action},
                            status=item["status"],
                            error_message=reason if reason != "skipped_duplicate" else "",
                        )
                    continue

                if dry_run:
                    item["status"] = "dry_run"
                    self.store.record(target, action, "dry_run", True, item)
                    results.append(item)
                    has_success = True
                    if job_id and hasattr(self.store, "social_store"):
                        self.store.social_store.add_job_item(
                            job_id=job_id,
                            item_order=len(results),
                            content={"target": target.__dict__, "action": action},
                            status="dry_run",
                        )
                    continue

                try:
                    client = self._client(target.platform, use_web_fallback)
                    response = client.perform(action, target)
                    status = response.get("status", "success")
                    if status not in ("success", "already_done"):
                        status = "success"
                    item.update(status=status, response=response)
                    self.store.record(target, action, status, False, response)
                    has_success = True
                    if hasattr(self.store, "social_store"):
                        try:
                            from services.social_relationship_service import SocialRelationshipService
                            rel_svc = SocialRelationshipService(store=self.store.social_store)
                            target_user_key = target.label or target.account_id
                            rel_svc.record_engagement_success(
                                platform=target.platform,
                                actor_account_id=actor_account_id or "default",
                                action=action,
                                target_username=target_user_key,
                                target_post_id=target.post_id,
                            )
                        except Exception:
                            pass
                    if job_id and hasattr(self.store, "social_store"):
                        self.store.social_store.add_job_item(
                            job_id=job_id,
                            item_order=len(results),
                            content={"target": target.__dict__, "action": action},
                            status=status,
                        )
                except UnsupportedAction as exc:
                    item.update(status="web_required", detail=str(exc))
                    self.store.record(target, action, "web_required", False, str(exc))
                    has_failure = True
                    if job_id and hasattr(self.store, "social_store"):
                        self.store.social_store.add_job_item(
                            job_id=job_id,
                            item_order=len(results),
                            content={"target": target.__dict__, "action": action},
                            status="web_required",
                            error_message=str(exc),
                        )
                except Exception as exc:
                    err_msg = sanitize_sensitive_data(str(exc))
                    item.update(status="failed", detail=err_msg)
                    self.store.record(target, action, "failed", False, err_msg)
                    has_failure = True
                    if job_id and hasattr(self.store, "social_store"):
                        self.store.social_store.add_job_item(
                            job_id=job_id,
                            item_order=len(results),
                            content={"target": target.__dict__, "action": action},
                            status="failed",
                            error_message=err_msg,
                        )
                results.append(item)
                if self.policy.delay_seconds > 0:
                    time.sleep(self.policy.delay_seconds)

        # 공통 작업 완료 상태 판정 및 업데이트
        if job_id and hasattr(self.store, "social_store"):
            if has_failure and has_success:
                final_status = "partially_failed"
            elif has_failure and not has_success:
                final_status = "failed"
            else:
                final_status = "succeeded"
            self.store.social_store.update_job_status(
                job_id=job_id,
                status=final_status,
                result_payload={"results_count": len(results), "dry_run": dry_run},
            )

        resp = {
            "status": "success",
            "dry_run": dry_run,
            "requested_targets": len(targets),
            "results": results,
        }
        if job_id:
            resp["job_id"] = job_id
        return resp


def get_service() -> EngagementAutomationService:
    return EngagementAutomationService()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Threads/X 참여 자동화 도구")
    parser.add_argument("command", choices=["login"], help="전용 브라우저 프로필에 로그인")
    args = parser.parse_args()
    if args.command == "login":
        WebEngagementClient().open_login_session()
