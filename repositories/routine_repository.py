"""
자율 소셜 오퍼레이터 설정 및 상태 저장소 (SQLite WAL)
- 4대 기본 루틴 및 8대 마음지기 앵글 자동 Seed
- 출처(Source) CRUD 및 SSRF 안전 등록
- 수집 이력 중복방지 및 아웃박스 작업 관리
"""

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional
from domain.enums import RoutineMode, TriggerType, SourceType, JobStatus, StepType
from domain.models import (
    RoutineResponse, RoutineUpdate,
    SourceResponse, SourceCreate, SourceUpdate,
    PromotionAngle, ScheduleItem
)

from contextlib import contextmanager

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "autonomous_operator.db")


class RoutineRepository:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. routines 테이블
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS routines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                mode TEXT NOT NULL DEFAULT 'REVIEW',
                trigger_type TEXT NOT NULL DEFAULT 'SCHEDULE',
                schedule_json TEXT NOT NULL DEFAULT '[]',
                timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
                max_posts_per_day INTEGER NOT NULL DEFAULT 3,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """)

            # 2. sources 테이블
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                routine_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                config_json TEXT DEFAULT '{}',
                etag TEXT,
                last_modified TEXT,
                last_checked_at INTEGER DEFAULT 0,
                health_status TEXT DEFAULT 'HEALTHY',
                FOREIGN KEY (routine_id) REFERENCES routines(id) ON DELETE CASCADE
            );
            """)

            # 3. promotion_angles 테이블 (마음지기 등)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotion_angles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                routine_id INTEGER NOT NULL,
                angle_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                hook_template TEXT NOT NULL,
                body_template TEXT NOT NULL,
                weight INTEGER NOT NULL DEFAULT 1,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                last_used_at INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (routine_id) REFERENCES routines(id) ON DELETE CASCADE
            );
            """)

            # 4. collected_items 테이블 (중복 방지용)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS collected_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                source_id INTEGER,
                routine_id INTEGER NOT NULL,
                collected_at INTEGER NOT NULL,
                FOREIGN KEY (routine_id) REFERENCES routines(id) ON DELETE CASCADE
            );
            """)

            # 5. outbox_jobs 테이블 (스마트 체인 발행 큐)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS outbox_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                routine_id INTEGER NOT NULL,
                idempotency_key TEXT UNIQUE NOT NULL,
                topic_key TEXT NOT NULL,
                platforms TEXT NOT NULL DEFAULT '["THREADS", "X"]',
                status TEXT NOT NULL DEFAULT 'PENDING',
                retry_count INTEGER NOT NULL DEFAULT 0,
                scheduled_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (routine_id) REFERENCES routines(id) ON DELETE CASCADE
            );
            """)

            # 6. publication_steps 테이블 (본문 -> 첫 답글 2단계 체인)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS publication_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                step_type TEXT NOT NULL,
                content TEXT NOT NULL,
                remote_id TEXT,
                parent_step_id INTEGER,
                status TEXT NOT NULL DEFAULT 'PENDING',
                error_message TEXT,
                executed_at INTEGER,
                FOREIGN KEY (job_id) REFERENCES outbox_jobs(id) ON DELETE CASCADE
            );
            """)

            conn.commit()

        # 기본 데이터 시드
        self._seed_default_data()

    def _seed_default_data(self):
        now = int(time.time())
        default_routines = [
            {
                "code": "AI_TREND",
                "name": "AI 동향 및 테크 브리핑",
                "description": "GeekNews 및 주요 AI 트렌드 요약 + 셀프 답글 링크 체인",
                "mode": RoutineMode.REVIEW.value,
                "schedule": [
                    {"local_time": "09:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI"], "enabled": True},
                    {"local_time": "14:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI"], "enabled": True},
                    {"local_time": "21:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI"], "enabled": True}
                ],
                "max_posts": 3,
                "sources": [
                    {"name": "GeekNews RSS", "kind": SourceType.RSS_ATOM.value, "url": "https://news.hada.io/rss/news"},
                    {"name": "Hugging Face Daily Papers", "kind": SourceType.JSON_API.value, "url": "https://huggingface.co/api/daily_papers?limit=10"}
                ]
            },
            {
                "code": "MAUM_PROMO",
                "name": "마음지기 서비스 홍보 및 힐링 인사이트",
                "description": "마음지기 8대 앵글 순환 발행 + 감정 케어 메시지",
                "mode": RoutineMode.REVIEW.value,
                "schedule": [
                    {"local_time": "13:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], "enabled": True},
                    {"local_time": "18:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], "enabled": True}
                ],
                "max_posts": 2,
                "sources": [
                    {"name": "마음지기 웹사이트", "kind": SourceType.SITE_ADAPTER.value, "url": "https://maumjigi.com"}
                ]
            },
            {
                "code": "RESEARCH",
                "name": "최신 AI 연구논문 심층 브리핑",
                "description": "arXiv 및 Hugging Face/DeepMind 최신 논문 해설",
                "mode": RoutineMode.REVIEW.value,
                "schedule": [
                    {"local_time": "20:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI"], "enabled": True}
                ],
                "max_posts": 1,
                "sources": [
                    {"name": "arXiv cs.AI RSS", "kind": SourceType.ARXIV.value, "url": "https://rss.arxiv.org/rss/cs.AI"},
                    {"name": "Hugging Face Papers API", "kind": SourceType.HUGGINGFACE_PAPERS.value, "url": "https://huggingface.co/api/daily_papers?limit=20"},
                    {"name": "Google DeepMind Blog", "kind": SourceType.RSS_ATOM.value, "url": "https://deepmind.google/blog/rss.xml"}
                ]
            },
            {
                "code": "COMMENT_REPLY",
                "name": "소셜 댓글 감시 및 공감 답글 (Sentinel)",
                "description": "48시간 이내 소셜 댓글 탐지 및 맞춤형 답글 제안",
                "mode": RoutineMode.REVIEW.value,
                "schedule": [
                    {"local_time": "11:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], "enabled": True},
                    {"local_time": "22:00", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], "enabled": True}
                ],
                "max_posts": 10,
                "sources": []
            }
        ]

        maum_angles = [
            ("감정 환기 & 쉼표", "하루 동안 억눌렀던 감정, 잠시 내려놓아도 괜찮습니다.", "바쁜 일상 속 나를 돌보는 작은 쉼표. 마음지기에서 오늘 하루 내 마음의 온도를 확인해보세요."),
            ("번아웃 극복 & 에너지 리셋", "지친 나를 위해 딱 3분, 마음의 소리에 귀 기울여보세요.", "지속적인 긴장과 피로는 마음의 경고 신호입니다. 마음지기 감정 일기와 함께 나를 토닥여주세요."),
            ("관계 갈등 & 대화의 지혜", "상대방의 말에 상처받았을 때, 내 마음부터 다독이는 연습.", "마음이 단단해야 관계에서도 상처받지 않습니다. 마음지기 공감 피드백으로 나를 보호하세요."),
            ("불안·우울 안심 케어", "불안이 파도처럼 밀려올 때, 호흡과 함께 머무르는 법.", "혼자 끙끙 앓지 마세요. 안전하고 따뜻한 AI 마음친구 마음지기가 24시간 곁을 지킵니다."),
            ("자존감 & 자기 자비", "누구보다 스스로에게 가장 다정한 친구가 되어주세요.", "남들의 시선보다 중요한 것은 내면의 평화입니다. 마음지기 마음챙김 가이드와 함께해요."),
            ("전문가 감수 심리 솔루션", "심리상담 전문가들의 통찰을 녹여낸 데일리 케어.", "과학적이고 체계적인 심리 접근법으로 여러분의 일상 회복을 돕습니다."),
            ("완벽한 익명성 보장", "누구에게도 말 못 할 고민, 마음지기에선 온전히 안전합니다.", "어떤 비밀도, 어떤 흔적도 안전하게 보호됩니다. 마음 편히 털어놓으세요."),
            ("매일 5분 나를 만나는 여정", "오늘 하루 어떤 감정을 느끼셨나요? 마음지기가 함께합니다.", "기록하는 것만으로도 치유는 시작됩니다. 오늘 밤, 마음지기에서 당신의 이야기를 들려주세요.")
        ]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for r in default_routines:
                cursor.execute("SELECT id FROM routines WHERE key = ?", (r["code"],))
                row = cursor.fetchone()
                if not row:
                    cursor.execute("""
                    INSERT INTO routines (key, name, description, mode, trigger_type, schedule_json, max_posts_per_day, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """, (
                        r["code"], r["name"], r["description"], r["mode"],
                        TriggerType.SCHEDULE.value, json.dumps(r["schedule"]),
                        r["max_posts"], now, now
                    ))
                    routine_id = cursor.lastrowid
                    for s in r["sources"]:
                        cursor.execute("""
                        INSERT INTO sources (routine_id, name, kind, url, enabled, config_json)
                        VALUES (?, ?, ?, ?, 1, '{}')
                        """, (routine_id, s["name"], s["kind"], s["url"]))
                else:
                    routine_id = row["id"]

                # 마음지기 루틴인 경우 8대 앵글 시드
                if r["code"] == "MAUM_PROMO":
                    cursor.execute("SELECT COUNT(*) as cnt FROM promotion_angles WHERE routine_id = ?", (routine_id,))
                    cnt = cursor.fetchone()["cnt"]
                    if cnt == 0:
                        for idx, (title, hook, body) in enumerate(maum_angles):
                            cursor.execute("""
                            INSERT INTO promotion_angles (routine_id, angle_index, title, hook_template, body_template, weight, enabled, last_used_at)
                            VALUES (?, ?, ?, ?, ?, 1, 1, 0)
                            """, (routine_id, idx + 1, title, hook, body))

            conn.commit()

    # --- Routine CRUD ---
    def get_routines(self) -> List[RoutineResponse]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM routines ORDER BY id ASC")
            rows = cursor.fetchall()
            routines = []
            for r in rows:
                routines.append(self._row_to_routine(conn, r))
            return routines

    def get_routine_by_id(self, routine_id: int) -> Optional[RoutineResponse]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM routines WHERE id = ?", (routine_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_routine(conn, row)

    def get_routine_by_code(self, code: str) -> Optional[RoutineResponse]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM routines WHERE key = ?", (code,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_routine(conn, row)

    def get_routine_by_key(self, routine_key: str) -> Optional[RoutineResponse]:
        return self.get_routine_by_code(routine_key)

    def update_routine(self, routine_id: int, update_data: RoutineUpdate) -> Optional[RoutineResponse]:
        now = int(time.time())
        fields = []
        values = []

        if update_data.name is not None:
            fields.append("name = ?")
            values.append(update_data.name)
        if update_data.description is not None:
            fields.append("description = ?")
            values.append(update_data.description)
        if update_data.mode is not None:
            fields.append("mode = ?")
            values.append(update_data.mode.value)
        if update_data.schedules is not None:
            fields.append("schedule_json = ?")
            values.append(json.dumps([s.model_dump() for s in update_data.schedules]))
        if update_data.timezone is not None:
            fields.append("timezone = ?")
            values.append(update_data.timezone)
        if update_data.max_posts_per_day is not None:
            fields.append("max_posts_per_day = ?")
            values.append(update_data.max_posts_per_day)
        if update_data.enabled is not None:
            fields.append("enabled = ?")
            values.append(1 if update_data.enabled else 0)

        if not fields:
            return self.get_routine_by_id(routine_id)

        fields.append("updated_at = ?")
        values.append(now)
        values.append(routine_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = f"UPDATE routines SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, tuple(values))
            conn.commit()

        return self.get_routine_by_id(routine_id)

    def _row_to_routine(self, conn: sqlite3.Connection, row: sqlite3.Row) -> RoutineResponse:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sources WHERE routine_id = ? ORDER BY id ASC", (row["id"],))
        source_rows = cursor.fetchall()
        sources = [self._row_to_source(s) for s in source_rows]

        schedule_raw = json.loads(row["schedule_json"]) if row["schedule_json"] else []
        schedules = [ScheduleItem(**s) for s in schedule_raw]

        return RoutineResponse(
            id=row["id"],
            code=row["key"],
            name=row["name"],
            description=row["description"] or "",
            mode=RoutineMode(row["mode"]),
            trigger_type=TriggerType(row["trigger_type"]),
            schedules=schedules,
            source_ids=[s.id for s in sources],
            sources=sources,
            timezone=row["timezone"],
            max_posts_per_day=row["max_posts_per_day"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    # --- Source CRUD ---
    def get_sources(self, routine_id: Optional[int] = None) -> List[SourceResponse]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if routine_id is not None:
                cursor.execute("SELECT * FROM sources WHERE routine_id = ? ORDER BY id ASC", (routine_id,))
            else:
                cursor.execute("SELECT * FROM sources ORDER BY id ASC")
            return [self._row_to_source(s) for s in cursor.fetchall()]

    def get_source_by_id(self, source_id: int) -> Optional[SourceResponse]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
            row = cursor.fetchone()
            return self._row_to_source(row) if row else None

    def add_source(self, source_data: SourceCreate) -> SourceResponse:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO sources (routine_id, name, kind, url, enabled, config_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                source_data.routine_id,
                source_data.name,
                source_data.kind.value,
                source_data.url,
                1 if source_data.enabled else 0,
                json.dumps(source_data.config_json or {})
            ))
            source_id = cursor.lastrowid
            conn.commit()
            return self.get_source_by_id(source_id)

    def update_source(self, source_id: int, update_data: SourceUpdate) -> Optional[SourceResponse]:
        fields = []
        values = []

        if update_data.name is not None:
            fields.append("name = ?")
            values.append(update_data.name)
        if update_data.kind is not None:
            fields.append("kind = ?")
            values.append(update_data.kind.value)
        if update_data.url is not None:
            fields.append("url = ?")
            values.append(update_data.url)
        if update_data.enabled is not None:
            fields.append("enabled = ?")
            values.append(1 if update_data.enabled else 0)
        if update_data.config_json is not None:
            fields.append("config_json = ?")
            values.append(json.dumps(update_data.config_json))

        if not fields:
            return self.get_source_by_id(source_id)

        values.append(source_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = f"UPDATE sources SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, tuple(values))
            conn.commit()

        return self.get_source_by_id(source_id)

    def delete_source(self, source_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_source(self, row: sqlite3.Row) -> SourceResponse:
        config = json.loads(row["config_json"]) if row["config_json"] else {}
        return SourceResponse(
            id=row["id"],
            routine_id=row["routine_id"],
            name=row["name"],
            kind=SourceType(row["kind"]),
            url=row["url"],
            enabled=bool(row["enabled"]),
            config_json=config,
            etag=row["etag"],
            last_modified=row["last_modified"],
            last_checked_at=row["last_checked_at"],
            health_status=row["health_status"] or "HEALTHY"
        )

    # --- Promotion Angles ---
    def get_angles(self, routine_id: int) -> List[PromotionAngle]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM promotion_angles WHERE routine_id = ? AND enabled = 1 ORDER BY angle_index ASC",
                (routine_id,)
            )
            rows = cursor.fetchall()
            return [
                PromotionAngle(
                    id=r["id"],
                    routine_id=r["routine_id"],
                    angle_index=r["angle_index"],
                    title=r["title"],
                    hook_template=r["hook_template"],
                    body_template=r["body_template"],
                    weight=r["weight"],
                    enabled=bool(r["enabled"]),
                    last_used_at=r["last_used_at"]
                )
                for r in rows
            ]

    def get_next_angle(self, routine_id: int) -> Optional[PromotionAngle]:
        """가장 오래전에 사용된 앵글을 순환 선택하고 사용 시간 갱신"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM promotion_angles 
                WHERE routine_id = ? AND enabled = 1 
                ORDER BY last_used_at ASC, angle_index ASC 
                LIMIT 1
                """,
                (routine_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            now = int(time.time())
            cursor.execute("UPDATE promotion_angles SET last_used_at = ? WHERE id = ?", (now, row["id"]))
            conn.commit()

            return PromotionAngle(
                id=row["id"],
                routine_id=row["routine_id"],
                angle_index=row["angle_index"],
                title=row["title"],
                hook_template=row["hook_template"],
                body_template=row["body_template"],
                weight=row["weight"],
                enabled=bool(row["enabled"]),
                last_used_at=now
            )

    # --- Duplication & Collection History ---
    def is_item_collected(self, url_hash: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM collected_items WHERE url_hash = ?", (url_hash,))
            return cursor.fetchone() is not None

    def record_collected_item(self, url_hash: str, url: str, title: str, summary: str, source_id: int, routine_id: int):
        now = int(time.time())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR IGNORE INTO collected_items (url_hash, url, title, summary, source_id, routine_id, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (url_hash, url, title, summary, source_id, routine_id, now))
            conn.commit()

    # --- Outbox Jobs & Steps ---
    def create_outbox_job(self, routine_id: int, idempotency_key: str, topic_key: str, platforms: List[str], scheduled_at: int) -> int:
        now = int(time.time())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM outbox_jobs WHERE idempotency_key = ?", (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                return existing["id"]

            cursor.execute("""
            INSERT INTO outbox_jobs (routine_id, idempotency_key, topic_key, platforms, status, scheduled_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?)
            """, (routine_id, idempotency_key, topic_key, json.dumps(platforms), scheduled_at, now, now))
            job_id = cursor.lastrowid
            conn.commit()
            return job_id

    def add_publication_step(self, job_id: int, platform: str, step_type: StepType, content: str, parent_step_id: Optional[int] = None) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO publication_steps (job_id, platform, step_type, content, parent_step_id, status)
            VALUES (?, ?, ?, ?, ?, 'PENDING')
            """, (job_id, platform, step_type.value, content, parent_step_id))
            step_id = cursor.lastrowid
            conn.commit()
            return step_id

    def update_publication_step(self, step_id: int, status: str, remote_id: Optional[str] = None, error_message: Optional[str] = None):
        now = int(time.time())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE publication_steps 
            SET status = ?, remote_id = COALESCE(?, remote_id), error_message = ?, executed_at = ?
            WHERE id = ?
            """, (status, remote_id, error_message, now, step_id))
            conn.commit()

    def get_outbox_jobs(self, limit: int = 20, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM outbox_jobs"
            params = []
            if status:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            jobs = []
            for r in rows:
                job_id = r["id"]
                cursor.execute("SELECT * FROM publication_steps WHERE job_id = ? ORDER BY id ASC", (job_id,))
                step_rows = cursor.fetchall()
                steps = [dict(s) for s in step_rows]
                job_dict = dict(r)
                job_dict["platforms"] = json.loads(r["platforms"]) if r["platforms"] else []
                job_dict["steps"] = steps
                jobs.append(job_dict)
            return jobs

    def get_outbox_job_by_id(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM outbox_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute("SELECT * FROM publication_steps WHERE job_id = ? ORDER BY id ASC", (job_id,))
            steps = [dict(s) for s in cursor.fetchall()]
            job_dict = dict(row)
            job_dict["platforms"] = json.loads(row["platforms"]) if row["platforms"] else []
            job_dict["steps"] = steps
            return job_dict
