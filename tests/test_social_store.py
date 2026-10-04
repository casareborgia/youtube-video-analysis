"""Unit tests for social_store.py (Phase 1 Rework v3).

Tests:
1. Schema initialization and versioning (version = 2).
2. v1 -> v2 migration (replacing global UNIQUE(idempotency_key) with composite key AND preserving social_job_items).
3. Migration from pre-existing DB with legacy engagement_events.
4. Path traversal and raw token rejection in credential_ref.
5. Error message and payload token sanitization.
6. Scoped idempotency per actor_account_id & 12-thread parallel concurrency safety.
7. Approval bypass blocked (approved_at > 0 required) & ownerless running state blocked.
8. Worker ownership fencing: missing, wrong, expired worker blocked on running job completion.
9. Mismatched worker_id and locked_by rejected with ValueError (P2).
10. Execution attempts (social_job_attempts) tracking and persistence across restarts (P1).
11. Atomic daily limit reservation preventing concurrent over-quota execution (P1).
12. Job items management.
"""

import concurrent.futures
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import engagement_automation
import social_store


class SocialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_social.db"
        self.store = social_store.SocialStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_initialization_and_version(self):
        version = self.store.get_schema_version()
        self.assertEqual(version, 2)

    def test_v1_to_v2_migration(self):
        # Create a legacy v1 database with global UNIQUE(idempotency_key) AND social_job_items with FK CASCADE
        v1_db = Path(self.temp_dir.name) / "v1.db"
        conn = sqlite3.connect(str(v1_db))
        with conn:
            conn.execute(
                """
                CREATE TABLE social_jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
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
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE social_job_items (
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
            # Insert existing v1 job for actor-a
            conn.execute(
                """
                INSERT INTO social_jobs
                (job_id, idempotency_key, platform, job_type, status, actor_account_id,
                 dry_run, scheduled_at, approved_at, started_at, finished_at,
                 locked_by, locked_at, target_id, target_url, content_payload,
                 retry_count, max_retries, created_at, updated_at)
                VALUES ('job_v1_01', 'shared_key_123', 'threads', 'publish', 'draft', 'actor-a',
                        1, 0, 0, 0, 0, '', 0, '', '', '{}', 0, 3, 1600000000, 1600000000)
                """
            )
            # Insert 2 child items for job_v1_01
            conn.execute(
                """
                INSERT INTO social_job_items (job_id, item_index, content, status)
                VALUES ('job_v1_01', 0, 'First sub-tweet', 'pending'),
                       ('job_v1_01', 1, 'Second sub-tweet', 'succeeded')
                """
            )
            conn.execute("PRAGMA user_version = 1")
        conn.close()

        # Initialize SocialStore on v1 DB -> must auto-migrate to v2
        migrated = social_store.SocialStore(v1_db)
        self.assertEqual(migrated.get_schema_version(), 2)

        # 1. Verify old job intact
        old_job = migrated.get_job("job_v1_01")
        self.assertIsNotNone(old_job)
        self.assertEqual(old_job["actor_account_id"], "actor-a")

        # 2. P1: Verify child items in social_job_items were NOT deleted by CASCADE!
        child_items = migrated.get_job_items("job_v1_01")
        self.assertEqual(len(child_items), 2, "Child items must be preserved after migration!")
        self.assertEqual(child_items[0]["content"], "First sub-tweet")
        self.assertEqual(child_items[1]["content"], "Second sub-tweet")
        self.assertEqual(child_items[1]["status"], "succeeded")

        # 3. Now actor-b creates job with the SAME idempotency_key 'shared_key_123'
        job_b = migrated.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="actor-b",
            idempotency_key="shared_key_123",
            content_payload={"text": "Hello from actor-b"},
        )
        self.assertIsNotNone(job_b)
        self.assertEqual(job_b["actor_account_id"], "actor-b")
        self.assertNotEqual(old_job["job_id"], job_b["job_id"])

    def test_future_schema_version_rejected(self):
        future_db = Path(self.temp_dir.name) / "future.db"
        conn = sqlite3.connect(str(future_db))
        with conn:
            conn.execute("PRAGMA user_version = 7")
        conn.close()

        with self.assertRaises(social_store.SocialStoreError):
            social_store.SocialStore(future_db)

    def test_migration_from_preexisting_db(self):
        legacy_db = Path(self.temp_dir.name) / "legacy.db"
        conn = sqlite3.connect(str(legacy_db))
        with conn:
            conn.execute(
                """
                CREATE TABLE engagement_events (
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
            conn.execute(
                """
                INSERT INTO engagement_events
                (created_at, day_key, platform, account_id, post_id, action, status, dry_run, detail)
                VALUES (1600000000, '2026-09-01', 'threads', 'legacy_user', 'legacy_post', 'follow', 'success', 0, 'legacy')
                """
            )
        conn.close()

        migrated_store = social_store.SocialStore(legacy_db)
        self.assertEqual(migrated_store.get_schema_version(), 2)

        history = migrated_store.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["account_id"], "legacy_user")

    def test_path_traversal_and_raw_token_rejection(self):
        bad_traversals = [
            "data/../../.env.json",
            "secrets/../../../tmp/token",
            "/etc/passwd",
            "\\Windows\\system32",
            "data/..",
            "data//secret.json",
            "raw-secret-token-1234567890",
            "Bearer eyJhbGci...",
        ]
        for bad in bad_traversals:
            with self.assertRaises(ValueError, msg=f"Should reject: {bad}"):
                self.store.upsert_account(
                    platform="threads",
                    account_id="user_traversal",
                    credential_ref=bad,
                )

        good_refs = [
            "env",
            "env:THREADS_ACCESS_TOKEN",
            "config:threads",
            "config:x",
            "data/threads_config.json",
        ]
        for good in good_refs:
            acc = self.store.upsert_account(
                platform="threads",
                account_id=f"user_ok_{good.replace(':', '_').replace('/', '_')}",
                credential_ref=good,
            )
            self.assertEqual(acc["credential_ref"], good)

    def test_error_and_payload_sanitization(self):
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="actor_sec",
            content_payload={"msg": "token=super_secret_val"},
        )
        self.assertIn("token=[REDACTED]", str(job["content_payload"]))

        self.store.transition_job_status(job["job_id"], "approved")
        self.store.transition_job_status(job["job_id"], "running", worker_id="w_sec")
        failed_job = self.store.transition_job_status(
            job["job_id"],
            "failed",
            worker_id="w_sec",
            error_code="AUTH_FAIL",
            error_message="HTTP 401: Invalid token Bearer raw-secret-token-1234567890",
        )
        self.assertNotIn("raw-secret-token-1234567890", failed_job["last_error_message"])
        self.assertIn("Bearer [REDACTED]", failed_job["last_error_message"])

    def test_worker_ownership_fencing_on_running_job(self):
        now_ts = int(time.time())
        job = self.store.create_job(
            platform="x",
            job_type="publish",
            actor_account_id="act_fence",
        )
        self.store.transition_job_status(job["job_id"], "approved")
        self.store.transition_job_status(job["job_id"], "scheduled", scheduled_at=now_ts - 5)

        # Worker Alpha leases job
        leased = self.store.acquire_job_lease(worker_id="worker_alpha", now_timestamp=now_ts)
        self.assertIsNotNone(leased)
        self.assertEqual(leased["locked_by"], "worker_alpha")

        # 1. Missing worker_id on running job completion must fail!
        with self.assertRaises(social_store.WorkerOwnershipError):
            self.store.transition_job_status(
                job["job_id"], "succeeded", worker_id=None
            )

        with self.assertRaises(social_store.WorkerOwnershipError):
            self.store.transition_job_status(
                job["job_id"], "succeeded", worker_id=""
            )

        # 2. Wrong worker_id must fail!
        with self.assertRaises(social_store.WorkerOwnershipError):
            self.store.transition_job_status(
                job["job_id"], "succeeded", worker_id="wrong_worker"
            )

        # 3. Simulate Worker Alpha lease expired and Worker Beta re-leased it
        re_leased = self.store.acquire_job_lease(
            worker_id="worker_beta",
            now_timestamp=now_ts + 400,
            lease_timeout_seconds=300,
        )
        self.assertIsNotNone(re_leased)
        self.assertEqual(re_leased["locked_by"], "worker_beta")

        # Worker Alpha attempts late completion -> BLOCKED!
        with self.assertRaises(social_store.WorkerOwnershipError):
            self.store.transition_job_status(
                job["job_id"],
                "succeeded",
                worker_id="worker_alpha",
            )

        # Worker Beta completes successfully
        completed = self.store.transition_job_status(
            job["job_id"],
            "succeeded",
            worker_id="worker_beta",
            result_payload={"id": "tweet_beta"},
        )
        self.assertEqual(completed["status"], "succeeded")

    def test_mismatched_worker_and_locked_by_rejected(self):
        # P2: Passing differing worker_id and locked_by must raise ValueError
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_mismatch",
        )
        self.store.transition_job_status(job["job_id"], "approved")

        with self.assertRaises(ValueError):
            self.store.transition_job_status(
                job["job_id"],
                "running",
                worker_id="worker-a",
                locked_by="worker-b",
            )

    def test_approval_bypass_and_ownerless_running_blocked(self):
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_approv",
            dry_run=False,
        )
        job_id = job["job_id"]
        self.assertEqual(job["status"], "draft")

        with self.assertRaises(social_store.InvalidStateTransitionError):
            self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(time.time()))

        with self.assertRaises(social_store.InvalidStateTransitionError):
            self.store.transition_job_status(job_id, "running")

        # Leasable only after approved
        self.assertIsNone(self.store.acquire_job_lease(worker_id="worker_test"))

        self.store.transition_job_status(job_id, "approved")

        # Attempt to transition to running without worker_id or locked_by must be rejected!
        with self.assertRaises(social_store.WorkerOwnershipError):
            self.store.transition_job_status(job_id, "running")

        with self.assertRaises(social_store.WorkerOwnershipError):
            self.store.transition_job_status(job_id, "running", worker_id="")

        # Entering running with a valid worker succeeds and sets locked_by
        run_job = self.store.transition_job_status(job_id, "running", worker_id="worker_manual")
        self.assertEqual(run_job["status"], "running")
        self.assertEqual(run_job["locked_by"], "worker_manual")
        self.assertGreater(run_job["locked_at"], 0)

    def test_concurrent_create_job_idempotency(self):
        # Real multi-threaded concurrency test (12 parallel threads)
        def worker_task(idx):
            return self.store.create_job(
                platform="x",
                job_type="publish",
                actor_account_id="actor_race",
                idempotency_key="race_key_parallel_999",
                content_payload={"text": f"Thread {idx}"},
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(worker_task, i) for i in range(12)]
            results = [f.result() for f in futures]

        job_ids = {r["job_id"] for r in results}
        self.assertEqual(len(job_ids), 1, "All 12 concurrent workers must receive the exact same job_id!")

    def test_job_attempts_tracking_and_persistence(self):
        # P1: social_job_attempts must record each attempt, timestamps, worker, and survive restarts
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_attempts",
        )
        job_id = job["job_id"]
        self.store.transition_job_status(job_id, "approved")

        # Attempt 1: leased by worker_1
        leased = self.store.acquire_job_lease(worker_id="worker_1", now_timestamp=1700000000)
        self.assertEqual(leased["job_id"], job_id)

        attempts = self.store.get_job_attempts(job_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["attempt_number"], 1)
        self.assertEqual(attempts[0]["worker_id"], "worker_1")
        self.assertEqual(attempts[0]["status"], "running")
        self.assertEqual(attempts[0]["started_at"], 1700000000)

        # Worker 1 completes attempt 1
        self.store.transition_job_status(
            job_id,
            "succeeded",
            worker_id="worker_1",
            result_payload={"platform_post_id": "th_post_111"},
        )

        # Reopen store to verify persistence across app restarts
        reopened_store = social_store.SocialStore(self.db_path)
        persisted_attempts = reopened_store.get_job_attempts(job_id)
        self.assertEqual(len(persisted_attempts), 1)
        self.assertEqual(persisted_attempts[0]["status"], "succeeded")
        self.assertEqual(persisted_attempts[0]["result_payload"]["platform_post_id"], "th_post_111")
        self.assertGreater(persisted_attempts[0]["finished_at"], 0)

    def test_concurrent_daily_limit_not_exceeded(self):
        # P1: Concurrently executing with daily limit 1 must never allow 2 successes
        eng_db = Path(self.temp_dir.name) / "eng_concurrent.db"
        store = engagement_automation.EngagementStore(eng_db)
        svc = engagement_automation.EngagementAutomationService(store=store)
        svc.policy.daily_total = 1
        svc.policy.delay_seconds = 0

        target1 = engagement_automation.EngagementTarget(
            platform="threads", post_id="post_concur_1", account_id="acc_1"
        )
        target2 = engagement_automation.EngagementTarget(
            platform="threads", post_id="post_concur_2", account_id="acc_2"
        )

        class MockLiveClient:
            def perform(self, action, target):
                time.sleep(0.05)
                return {"status": "success", "post_id": target.post_id}

        svc._client = lambda platform, fallback: MockLiveClient()

        def run_worker(target):
            return svc.execute(targets=[target], actions=["like"], dry_run=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(run_worker, target1)
            f2 = executor.submit(run_worker, target2)
            res1 = f1.result()
            res2 = f2.result()

        all_results = res1["results"] + res2["results"]
        statuses = [r["status"] for r in all_results]

        # Exactly 1 success, 1 blocked_quota!
        self.assertEqual(statuses.count("success"), 1, f"Expected 1 success, got {statuses}")
        self.assertEqual(statuses.count("blocked_quota"), 1, f"Expected 1 blocked_quota, got {statuses}")
        self.assertEqual(svc.store.daily_count(), 1, "daily_count must not exceed limit 1!")

    def test_job_items_management(self):
        job = self.store.create_job(
            platform="x",
            job_type="publish",
            actor_account_id="act_items",
        )
        items = [
            {"item_index": 0, "content": "1/3 First tweet"},
            {"item_index": 1, "content": "2/3 Second tweet Bearer secret123"},
        ]
        self.store.add_job_items(job["job_id"], items)
        retrieved = self.store.get_job_items(job["job_id"])
        self.assertEqual(len(retrieved), 2)
        self.assertIn("Bearer [REDACTED]", retrieved[1]["content"])

    def test_reclaim_expired_lease_closes_previous_attempt(self):
        """P1: 리스 만료 후 재점유 시 이전 시도가 lease_expired로 종료되고 새 시도가 생성되는지 검증"""
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_reassign",
        )
        job_id = job["job_id"]
        self.store.transition_job_status(job_id, "approved")

        t1 = 1700000000
        # 1. worker-a 가 점유
        leased_a = self.store.acquire_job_lease(worker_id="worker-a", now_timestamp=t1, lease_timeout_seconds=300)
        self.assertIsNotNone(leased_a)

        attempts_1 = self.store.get_job_attempts(job_id)
        self.assertEqual(len(attempts_1), 1)
        self.assertEqual(attempts_1[0]["worker_id"], "worker-a")
        self.assertEqual(attempts_1[0]["status"], "running")
        self.assertEqual(attempts_1[0]["finished_at"], 0)

        # 2. 리스 만료 후 worker-b 가 재점유 (t2 = t1 + 400 > 300)
        t2 = t1 + 400
        leased_b = self.store.acquire_job_lease(worker_id="worker-b", now_timestamp=t2, lease_timeout_seconds=300)
        self.assertIsNotNone(leased_b)
        self.assertEqual(leased_b["locked_by"], "worker-b")

        # 재점유 직후 시도 목록 검증: 이전 시도 worker-a는 lease_expired 여야 함!
        attempts_after_reassign = self.store.get_job_attempts(job_id)
        self.assertEqual(len(attempts_after_reassign), 2)
        # Attempt 1 (worker-a)
        self.assertEqual(attempts_after_reassign[0]["attempt_number"], 1)
        self.assertEqual(attempts_after_reassign[0]["worker_id"], "worker-a")
        self.assertEqual(attempts_after_reassign[0]["status"], "lease_expired")
        self.assertEqual(attempts_after_reassign[0]["error_code"], "LEASE_EXPIRED")
        self.assertEqual(attempts_after_reassign[0]["finished_at"], t2)

        # Attempt 2 (worker-b)
        self.assertEqual(attempts_after_reassign[1]["attempt_number"], 2)
        self.assertEqual(attempts_after_reassign[1]["worker_id"], "worker-b")
        self.assertEqual(attempts_after_reassign[1]["status"], "running")
        self.assertEqual(attempts_after_reassign[1]["finished_at"], 0)

        # 3. worker-b 가 작업 성공 완료
        self.store.transition_job_status(
            job_id,
            "succeeded",
            worker_id="worker-b",
            result_payload={"result": "ok_by_b"},
        )

        # 완료 직후 시도 목록 검증: worker-a는 계속 lease_expired, worker-b는 succeeded
        attempts_after_finish = self.store.get_job_attempts(job_id)
        self.assertEqual(len(attempts_after_finish), 2)
        self.assertEqual(attempts_after_finish[0]["status"], "lease_expired")
        self.assertEqual(attempts_after_finish[0]["finished_at"], t2)

        self.assertEqual(attempts_after_finish[1]["status"], "succeeded")
        self.assertGreater(attempts_after_finish[1]["finished_at"], 0)
        self.assertEqual(attempts_after_finish[1]["result_payload"]["result"], "ok_by_b")

    def test_reconcile_stale_reservations(self):
        """오래된 reserved 슬롯의 안전 복구 및 재시도 허용 검증"""
        # 슬롯 예약
        ok, reason = self.store.reserve_engagement_slot(
            platform="threads",
            actor_account_id="act_stale",
            target_id="post_stale_1",
            action="like",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "reserved")

        # 바로 다시 시도하면 duplicate로 거부됨
        ok2, reason2 = self.store.reserve_engagement_slot(
            platform="threads",
            actor_account_id="act_stale",
            target_id="post_stale_1",
            action="like",
        )
        self.assertFalse(ok2)
        self.assertEqual(reason2, "skipped_duplicate")

        # 0초 타임아웃으로 stale reservation 정리 실행
        reconciled = self.store.reconcile_stale_reservations(timeout_seconds=0)
        self.assertEqual(reconciled, 1)

        # 정리 후 다시 슬롯 예약 가능
        ok3, reason3 = self.store.reserve_engagement_slot(
            platform="threads",
            actor_account_id="act_stale",
            target_id="post_stale_1",
            action="like",
        )
        self.assertTrue(ok3)
        self.assertEqual(reason3, "reserved")


if __name__ == "__main__":
    unittest.main()
