import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import engagement_automation
import services.engagement_discovery as engagement_discovery
import services.threads_growth_analytics as threads_growth_analytics
import social_store
import threads_client


class TestThreadsGrowthSystem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_social.db"
        self.patch_db = patch("social_store.DEFAULT_DB_PATH", self.db_path)
        self.patch_db.start()
        self.store = social_store.SocialStore(str(self.db_path))

    def tearDown(self):
        self.patch_db.stop()
        self.tmp.cleanup()

    # =========================================================================
    # 1. threads_client 공식 검색 API 및 인사이트 테스트
    # =========================================================================
    @patch("threads_client._http_request")
    def test_search_threads_posts_normalization(self, mock_http):
        mock_http.return_value = {
            "data": [
                {
                    "id": "thread_post_1001",
                    "text": "바이브코딩과 AI 자동화 파이프라인 구축 후기입니다.",
                    "timestamp": "2026-10-04T02:00:00+0000",
                    "permalink": "https://threads.net/@ai_dev/post/thread_post_1001",
                    "username": "ai_dev",
                }
            ],
            "paging": {"cursors": {"after": "cursor_next_token"}},
        }

        with patch("threads_client.load_config", return_value={"access_token": "test_token"}):
            res = threads_client.search_threads_posts(query="바이브코딩", search_type="RECENT", limit=10)

        self.assertEqual(len(res["data"]), 1)
        post = res["data"][0]
        self.assertEqual(post["id"], "thread_post_1001")
        self.assertEqual(post["username"], "ai_dev")
        self.assertEqual(res["paging"]["cursors"]["after"], "cursor_next_token")

    @patch("threads_client._http_request")
    def test_search_threads_posts_permission_error(self, mock_http):
        mock_http.side_effect = RuntimeError("Threads API Error (403): Application does not have capability threads_keyword_search")

        with patch("threads_client.load_config", return_value={"access_token": "test_token"}):
            with self.assertRaises(RuntimeError) as ctx:
                threads_client.search_threads_posts(query="AI")
            self.assertIn("threads_keyword_search", str(ctx.exception))

    @patch("threads_client._http_request")
    def test_get_account_insights(self, mock_http):
        mock_http.return_value = {
            "data": [
                {"name": "views", "values": [{"value": 1520}]},
                {"name": "likes", "values": [{"value": 240}]},
                {"name": "replies", "values": [{"value": 45}]},
                {"name": "reposts", "values": [{"value": 18}]},
                {"name": "quotes", "values": [{"value": 3}]},
                {"name": "followers_count", "values": [{"value": 850}]},
            ]
        }

        with patch("threads_client.load_config", return_value={"access_token": "test_token"}):
            raw = threads_client.get_account_insights()

        self.assertIn("data", raw)
        self.assertEqual(len(raw["data"]), 6)

    # =========================================================================
    # 2. 후보 품질 평가 및 계정 단위 중복 제거 테스트
    # =========================================================================
    def test_calculate_candidate_score(self):
        # 30분 이내 최신 + 주제 일치 + 본문 적정 + 소통 신호
        now_ts = int(time.time())
        sample_post = {
            "text": "AI 자동화 개발을 하면서 파이썬 에이전트 설계가 정말 중요하다는 걸 느꼈습니다. 다들 어떻게 생각하시나요?",
            "timestamp": now_ts - 600,
            "has_replies": True,
        }
        score, reasons = engagement_discovery.calculate_candidate_score(
            cand=sample_post,
            topic="AI",
            search_query="AI",
            now_ts=now_ts,
        )
        self.assertGreaterEqual(score, 70)
        self.assertTrue(any("주제" in r for r in reasons))
        self.assertTrue(any("최근" in r for r in reasons))

        # 스팸 키워드 감점 테스트
        spam_post = {
            "text": "부업 광고 텔레그램 문의",
        }
        spam_score, spam_reasons = engagement_discovery.calculate_candidate_score(
            cand=spam_post,
            topic="AI",
            search_query="AI",
            now_ts=now_ts,
        )
        self.assertLess(spam_score, 40)
        self.assertTrue(any("도배" in r or "스팸" in r for r in spam_reasons))

    @patch("threads_client.search_threads_posts")
    def test_discover_targets_operational_mode_and_deduplication(self, mock_search):
        # 동일 계정이 2개 게시물을 올린 경우 높은 점수의 1개만 선발되어야 함
        mock_search.return_value = {
            "data": [
                {
                    "id": "post_dup_1",
                    "text": "단답",
                    "username": "multi_poster",
                    "author_id": "user_multi",
                    "permalink": "https://threads.net/p1",
                    "timestamp": "2026-10-04T00:00:00Z",
                    "like_count": 0,
                    "reply_count": 0,
                },
                {
                    "id": "post_dup_2",
                    "text": "인공지능 모델 파이프라인 구축에 관한 상세 후기 공유합니다.",
                    "username": "multi_poster",
                    "author_id": "user_multi",
                    "permalink": "https://threads.net/p2",
                    "timestamp": "2026-10-04T02:00:00Z",
                    "like_count": 8,
                    "reply_count": 3,
                },
                {
                    "id": "post_other_1",
                    "text": "AI 스타트업 팁 정리",
                    "username": "startup_guru",
                    "author_id": "user_startup",
                    "permalink": "https://threads.net/p3",
                    "timestamp": "2026-10-04T01:30:00Z",
                    "like_count": 10,
                    "reply_count": 2,
                },
            ],
            "next_cursor": None,
        }

        svc = engagement_discovery.EngagementDiscoveryService(store=self.store)
        res = svc.discover_targets(
            platform="threads",
            topic="AI",
            limit=10,
            allow_demo_seeds=False,
            exclude_existing_relationships=False,
        )

        targets = res["targets"]
        # multi_poster는 1명만 존재해야 함
        multi_posters = [t for t in targets if t["username"] == "multi_poster"]
        self.assertEqual(len(multi_posters), 1)
        # 더 긴 텍스트와 반응이 있는 post_dup_2가 채택되었어야 함
        self.assertEqual(multi_posters[0]["post_id"], "post_dup_2")

        # 데모 시드가 포함되지 않았는지 검증
        demo_usernames = {s["username"] for s in engagement_discovery.DEMO_THREADS_SEED_TARGETS}
        for t in targets:
            self.assertNotIn(t["username"], demo_usernames)

        # 점수 내림차순 정렬 검증
        scores = [t["candidate_score"] for t in targets]
        self.assertEqual(scores, sorted(scores, reverse=True))

    # =========================================================================
    # 3. v4 스키마 마이그레이션 및 성장 분석 데이터 계층 테스트
    # =========================================================================
    def test_schema_v4_migration_and_crud(self):
        # 1) v4 테이블 생성 확인
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cursor.fetchall()}
            self.assertIn("threads_growth_campaigns", tables)
            self.assertIn("threads_account_insight_snapshots", tables)
            self.assertIn("threads_growth_touchpoints", tables)

        # 2) 캠페인 생성 및 상태 전이
        camp = self.store.create_growth_campaign(
            campaign_id="camp_test_01",
            name="2026 10월 AI 성장 캠페인",
            topic="AI",
            search_queries="바이브코딩, LLM",
            baseline_followers_count=500,
        )
        self.assertEqual(camp["status"].upper(), "ACTIVE")
        self.assertEqual(camp["baseline_followers_count"], 500)

        # 3) 터치포인트 기록
        tp_id = self.store.record_growth_touchpoint(
            campaign_id="camp_test_01",
            target_username="cool_dev",
            target_post_id="post_999",
            action_type="reply",
            action_status="executed",
            candidate_score=85,
        )
        self.assertGreater(tp_id, 0)

        # 4) 스냅샷 기록
        snap_id = self.store.insert_insight_snapshot(
            followers_count=525,
            views=1200,
            replies=30,
            reposts=10,
        )
        self.assertGreater(snap_id, 0)

        # 5) 캠페인 종료
        ended = self.store.end_growth_campaign("camp_test_01", final_followers_count=530)
        self.assertEqual(ended["status"].upper(), "COMPLETED")
        self.assertEqual(ended["final_followers_count"], 530)

    # =========================================================================
    # 4. 성장 분석 서비스 및 기간 비교 비즈니스 로직 테스트
    # =========================================================================
    def test_growth_analytics_summary_and_period_comparison(self):
        analytics_svc = threads_growth_analytics.ThreadsGrowthAnalyticsService(store=self.store)

        camp = analytics_svc.start_campaign(
            name="가을 캠페인",
            topic="개발자",
            search_queries="파이썬, 자동화",
            baseline_followers_count=1000,
        )
        camp_id = camp["campaign_id"]

        # 터치포인트 등록
        self.store.record_growth_touchpoint(
            campaign_id=camp_id,
            target_username="acc_1",
            target_post_id="post_1",
            action_type="reply",
            action_status="executed",
        )
        self.store.record_growth_touchpoint(
            campaign_id=camp_id,
            target_username="acc_2",
            target_post_id="post_2",
            action_type="repost",
            action_status="executed",
        )

        # 캠페인 종료 (팔로워 1000 -> 1050, 순증 50명)
        analytics_svc.finish_campaign(camp_id, final_followers_count=1050)

        # 요약 확인
        summary = analytics_svc.get_campaign_summary(camp_id)
        self.assertEqual(summary["followers_metrics"]["net_followers_gain"], 50)
        self.assertEqual(summary["actions_metrics"]["total_candidates"], 2)
        self.assertEqual(summary["actions_metrics"]["executed_actions"], 2)

        # 직전 기간 비교 (직전 스냅샷이 없더라도 0으로 안전 처리)
        comp = analytics_svc.compare_campaign_periods(camp_id)
        self.assertEqual(comp["campaign_gain"], 50)
        self.assertEqual(comp["pre_campaign_gain"], 0)
        self.assertIn("상관관계", comp["disclaimer"])

    # =========================================================================
    # 5. Threads 공식 답글(reply) 액션 실행 테스트
    # =========================================================================
    @patch("threads_client.reply_to_post")
    def test_threads_api_reply_action(self, mock_reply):
        mock_reply.return_value = {
            "post_id": "new_reply_999",
            "reply_to_id": "target_thread_123",
            "media_type": "TEXT",
            "permalink": "https://threads.net/reply/999",
        }

        with patch("threads_client.load_config", return_value={"access_token": "test_token"}):
            client = engagement_automation.ThreadsApiEngagementClient(token="test_token")
            target = engagement_automation.EngagementTarget(
                platform="threads",
                post_id="target_thread_123",
                account_id="acc_threads_123",
                reply_text="유익한 인사이트 잘 읽었습니다!",
            )

            res = client.perform("reply", target)
            self.assertEqual(res["status"], "success")
            mock_reply.assert_called_once_with(
                post_id="target_thread_123",
                text="유익한 인사이트 잘 읽었습니다!",
                access_token="test_token",
            )

    # =========================================================================
    # 7. 코덱스 지적사항 회귀 검증 (Regression Guard Tests)
    # =========================================================================
    def test_reply_action_requires_explicit_reply_text(self):
        """답글 동작 시 reply_text가 비어 있으면 사용자명을 답글로 게시하지 않고 차단되어야 함."""
        target_no_reply = engagement_automation.EngagementTarget(
            platform="threads",
            post_id="post_th_999",
            account_id="actual_username",
            label="actual_username",
            reply_text="",  # 빈 답글
        )
        svc = engagement_automation.EngagementAutomationService(store=self.store)
        res = svc.execute([target_no_reply], actions=["reply"], dry_run=True)
        results = res.get("results", [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "skipped_missing_reply_text")

        # Live client perform 호출 시에도 EngagementError 발생 검증
        client = engagement_automation.ThreadsApiEngagementClient(token="mock_token")
        with self.assertRaises(engagement_automation.EngagementError) as ctx:
            client.perform("reply", target_no_reply)
        self.assertIn("답글 본문", str(ctx.exception))

    def test_candidate_account_id_is_username_not_post_id(self):
        """공식 검색 수집 시 account_id가 post_id가 아닌 username으로 저장되어 계정 단위 관계 제외가 유지되어야 함."""
        mock_res = {
            "data": [
                {
                    "id": "post_id_99999",
                    "username": "influencer_user",
                    "text": "인공지능과 생산성 이야기 나눕니다.",
                    "timestamp": "2026-10-04T03:00:00+0000",
                    "permalink": "https://threads.net/@influencer_user/post/post_id_99999",
                }
            ]
        }
        with patch("threads_client.search_threads_posts", return_value=mock_res):
            disc_svc = engagement_discovery.EngagementDiscoveryService(store=self.store)
            cands, _ = disc_svc._fetch_threads_candidates(topic="AI", allow_demo_seeds=False)
            self.assertGreaterEqual(len(cands), 1)
            first = cands[0]
            # post_id는 게시물 ID, account_id는 작성자 username이어야 함!
            self.assertEqual(first["post_id"], "post_id_99999")
            self.assertEqual(first["account_id"], "influencer_user")
            self.assertEqual(first["username"], "influencer_user")

    def test_campaign_status_case_insensitivity_and_upper_normalization(self):
        """캠페인 상태 조회가 대소문자 무관하게 동작하고 반환값은 대문자로 표준화되어야 함."""
        camp = self.store.create_growth_campaign(
            name="대소문자 검증 캠페인",
            topic="스타트업",
            baseline_followers_count=120,
        )
        cid = camp["campaign_id"]

        # 'ACTIVE'로 조회해도 매칭
        upper_list = self.store.list_growth_campaigns(status="ACTIVE")
        self.assertTrue(any(c["campaign_id"] == cid for c in upper_list))
        # 'active'로 조회해도 매칭
        lower_list = self.store.list_growth_campaigns(status="active")
        self.assertTrue(any(c["campaign_id"] == cid for c in lower_list))

        # get_growth_campaign 반환 status도 대문자
        item = self.store.get_growth_campaign(cid)
        self.assertIsNotNone(item)
        self.assertEqual(item["status"], "ACTIVE")

    @patch("threads_client.publish_single_post")
    def test_reply_to_post_forwards_access_token_and_user_id(self, mock_publish):
        """reply_to_post 호출 시 명시적으로 넘긴 access_token이 publish_single_post로 전달되어야 함."""
        mock_publish.return_value = {
            "media_id": "media_reply_888",
            "creation_id": "c_888",
            "post_url": "https://threads.net/post/media_reply_888",
        }
        res = threads_client.reply_to_post(
            post_id="parent_post_777",
            text="답글 테스트입니다.",
            access_token="explicit_secret_token",
            user_id="explicit_uid",
        )
        mock_publish.assert_called_once_with(
            text="답글 테스트입니다.",
            reply_to_id="parent_post_777",
            access_token="explicit_secret_token",
            user_id="explicit_uid",
        )
        self.assertEqual(res["media_id"], "media_reply_888")

    def test_zero_baseline_prevention_on_empty_snapshot(self):
        """인사이트 수집 실패 시 기준 팔로워를 0으로 왜곡 저장하지 않고 명시적 에러가 발생해야 함."""
        analytics = threads_growth_analytics.ThreadsGrowthAnalyticsService(store=self.store)
        # 스냅샷이 없고 API 호출도 실패하는 상황 모의
        with patch.object(analytics, "capture_account_snapshot", return_value={"status": "error"}):
            with self.assertRaises(ValueError) as ctx:
                analytics.start_campaign(name="위험 캠페인", topic="AI")
            self.assertIn("계정 팔로워 수(baseline)를 확인할 수 없습니다", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
