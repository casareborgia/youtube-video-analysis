"""Unit tests for Phase 3: Content Generation, Review, and Editable Drafts.

Tests cover:
- Platform normalization ('twitter' -> 'x', case insensitivity, unsupported platforms)
- Post content validation (empty strings, whitespace-only, platform length limits: Threads 500, X 280)
- Conversion of marketing generator output into integrated drafts (social_jobs + social_job_items)
- Manual single and thread draft creation and item editing
- Protection against modifying non-draft jobs (approved, running, etc.)
- AI Reply/Comment draft generation with tone, context, persona
- Lossless conversion of drafts to publish request payloads (Phase 3 completion condition)
- FastAPI endpoints integration
"""

from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

# Suppress StarletteDeprecationWarning for TestClient under -W error
warnings.filterwarnings("ignore", message=".*Using `httpx` with `starlette.testclient`.*")

from fastapi.testclient import TestClient

from app import app
import content_service
import social_store


class ContentDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_content_social.db"
        self.store = social_store.SocialStore(self.db_path)
        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_platform_normalization(self):
        self.assertEqual(content_service.normalize_platform("twitter"), "x")
        self.assertEqual(content_service.normalize_platform("Twitter "), "x")
        self.assertEqual(content_service.normalize_platform("X"), "x")
        self.assertEqual(content_service.normalize_platform("threads"), "threads")
        self.assertEqual(content_service.normalize_platform("Threads "), "threads")

        with self.assertRaises(ValueError):
            content_service.normalize_platform("facebook")
        with self.assertRaises(ValueError):
            content_service.normalize_platform("")

    def test_post_content_validation_and_length_limits(self):
        # Empty text rejected
        with self.assertRaises(ValueError):
            content_service.validate_post_content("threads", "")
        with self.assertRaises(ValueError):
            content_service.validate_post_content("x", "   \n\t  ")

        # Threads limit: 500
        threads_ok = "A" * 500
        self.assertEqual(len(content_service.validate_post_content("threads", threads_ok)), 500)

        threads_too_long = "A" * 501
        with self.assertRaises(ValueError):
            content_service.validate_post_content("threads", threads_too_long)

        # X limit: 280
        x_ok = "B" * 280
        self.assertEqual(len(content_service.validate_post_content("x", x_ok)), 280)

        x_too_long = "B" * 281
        with self.assertRaises(ValueError):
            content_service.validate_post_content("x", x_too_long)

    def test_create_draft_from_marketing(self):
        marketing_sample = {
            "topic": "100만 유튜버의 비밀",
            "platform": "twitter",  # Should map to 'x'
            "hook_formula": "호기심 갭 + 데이터",
            "hook_score": 98,
            "summary": "유튜브 숏폼 알고리즘을 해킹하는 3가지 공식",
            "hashtags": ["#유튜브팁", "#크리에이터", "#숏폼"],
            "posts": [
                {"index": 1, "text": "1/3 🧵 8초 만에 시청자를 사로잡는 오프닝 후킹 비결", "role": "hook"},
                {"index": 2, "text": "2/3 📌 첫 3초 시선 고정, 자막과 사운드의 싱크 조절", "role": "body"},
                {"index": 3, "text": "3/3 🚀 오늘부터 즉시 적용해보세요! 북마크 & 리트윗 필수", "role": "cta"},
            ],
        }

        res = content_service.create_draft_from_marketing(
            marketing_data=marketing_sample,
            actor_account_id="creator_actor_01",
            dry_run=True,
            store=self.store,
        )

        job = res["job"]
        items = res["items"]

        self.assertEqual(job["platform"], "x")
        self.assertEqual(job["status"], "draft")
        self.assertEqual(job["job_type"], "publish")
        self.assertEqual(job["content_payload"]["format"], "thread")
        self.assertEqual(job["actor_account_id"], "creator_actor_01")
        self.assertEqual(len(items), 3)

        self.assertEqual(items[0]["item_index"], 0)
        self.assertEqual(items[0]["content"], "1/3 🧵 8초 만에 시청자를 사로잡는 오프닝 후킹 비결")
        self.assertEqual(items[0]["status"], "pending")

        self.assertEqual(items[2]["item_index"], 2)
        self.assertEqual(items[2]["content"], "3/3 🚀 오늘부터 즉시 적용해보세요! 북마크 & 리트윗 필수")

    def test_manual_draft_and_item_editing(self):
        # 1. Create manual draft
        res = content_service.create_manual_draft(
            platform="threads",
            posts=["첫 번째 스레드 포스트입니다.", "두 번째 스레드 본문입니다."],
            actor_account_id="manual_creator",
            topic="일상 공유",
            store=self.store,
        )
        job_id = res["job"]["job_id"]
        self.assertEqual(res["job"]["status"], "draft")

        # 2. Update item 1 content
        updated = content_service.update_draft_item(
            job_id=job_id,
            item_index=1,
            new_content="수정된 두 번째 스레드 본문 내용입니다!",
            store=self.store,
        )
        self.assertEqual(updated["items"][1]["content"], "수정된 두 번째 스레드 본문 내용입니다!")

        # 3. Transition to approved -> updating draft item must fail!
        self.store.transition_job_status(job_id, "approved")
        with self.assertRaises(social_store.InvalidStateTransitionError):
            content_service.update_draft_item(
                job_id=job_id,
                item_index=0,
                new_content="승인 후 수정 시도",
                store=self.store,
            )

    @patch("llm_client.call_llm_json")
    def test_generate_reply_draft(self, mock_llm):
        mock_llm.return_value = (
            {
                "reply": "영상 기획에서 후킹의 중요성에 100% 동감합니다! 저도 첫 3초 분석에 집중하고 있어요 😊",
                "tone": "friendly",
                "reasoning": "공감과 실전 경험 공유",
            },
            "",
        )

        res = content_service.generate_reply_draft(
            platform="x",
            original_post="유튜브 숏폼은 첫 3초가 영상의 80%를 결정합니다. 어떻게 생각하시나요?",
            post_context="8초 비디오 AI 기획 관련 토론",
            tone="friendly",
        )

        self.assertEqual(res["platform"], "x")
        self.assertEqual(res["tone"], "friendly")
        self.assertIn("100% 동감합니다", res["reply"])
        self.assertTrue(res["char_count"] <= 280)

    def test_convert_draft_to_publish_request_lossless(self):
        """Phase 3 핵심 완료 조건: 생성 결과가 발행 요청으로 손실 없이 변환되는지 검증"""
        original_posts = [
            "1/3 🔥 첫 번째 스레드: 완벽한 데이터 검증",
            "2/3 ⚡ 두 번째 스레드: 특수문자 및 이모지 보존 !@#$%^&*()_+",
            "3/3 🎯 세 번째 스레드: https://tubeinsight.ai 링크 포함",
        ]

        draft = content_service.create_manual_draft(
            platform="threads",
            posts=original_posts,
            actor_account_id="lossless_tester",
            topic="무손실 검증",
            store=self.store,
        )
        job_id = draft["job"]["job_id"]

        # Convert to publish request
        pub_req = content_service.convert_draft_to_publish_request(
            job_id=job_id,
            approve=True,
            store=self.store,
        )

        # 1. Status became approved
        self.assertEqual(pub_req["status"], "approved")
        self.assertGreater(pub_req["approved_at"], 0)

        # 2. Perfect lossless preservation of text and sequence
        self.assertEqual(pub_req["posts"], original_posts)
        self.assertEqual(len(pub_req["items"]), 3)
        for i, text in enumerate(original_posts):
            self.assertEqual(pub_req["items"][i]["item_index"], i)
            self.assertEqual(pub_req["items"][i]["content"], text)

        self.assertEqual(pub_req["platform"], "threads")
        self.assertEqual(pub_req["actor_account_id"], "lossless_tester")

    def test_fastapi_draft_and_reply_endpoints(self):
        # 1. POST /api/social/drafts/manual
        resp_draft = self.client.post(
            "/api/social/drafts/manual",
            json={
                "platform": "x",
                "posts": ["테스트 트윗 1", "테스트 트윗 2"],
                "actor_account_id": "api_user",
                "dry_run": True,
            },
        )
        self.assertEqual(resp_draft.status_code, 200)
        data = resp_draft.json()
        job_id = data["draft"]["job"]["job_id"]

        # 2. PUT /api/social/drafts/{job_id}/items/0
        resp_update = self.client.put(
            f"/api/social/drafts/{job_id}/items/0",
            json={"content": "수정된 테스트 트윗 1"},
        )
        self.assertEqual(resp_update.status_code, 200)

        # 3. POST /api/social/drafts/{job_id}/convert-to-publish
        resp_pub = self.client.post(f"/api/social/drafts/{job_id}/convert-to-publish?approve=true")
        self.assertEqual(resp_pub.status_code, 200)
        pub_data = resp_pub.json()
        self.assertEqual(pub_data["publish_request"]["status"], "approved")
        self.assertEqual(pub_data["publish_request"]["posts"][0], "수정된 테스트 트윗 1")

        # 4. POST /api/social/reply/generate
        resp_reply = self.client.post(
            "/api/social/reply/generate",
            json={
                "platform": "threads",
                "original_post": "스레드 반응이 너무 좋네요!",
                "tone": "friendly",
            },
        )
        self.assertEqual(resp_reply.status_code, 200)
        self.assertIn("reply", resp_reply.json()["reply"])


if __name__ == "__main__":
    unittest.main()
