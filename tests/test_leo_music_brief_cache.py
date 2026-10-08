"""tests/test_leo_music_brief_cache.py — 레오 음악 브리프 캐시 & 루나 탭 자동 스카우팅 제거 검증

스카우팅 1회 = YouTube Data API + Gemini 호출(비용). 탭 진입마다 자동 실행되던 문제를 막기 위해
(1) 결과를 파일로 캐시하고 TTL 안에서는 재사용, (2) 프론트는 탭 진입 시 저장본만 조회(cached_only)하도록 했다.
외부 호출(fetch_top20_trends, llm_client.call_llm_json)은 전부 mock.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import trend_scout
from app import app

BASE = Path(__file__).resolve().parent.parent

FAKE_TRENDS = {"status": "success", "items": [
    {"rank": i, "title": f"곡 {i}", "channel_title": f"채널 {i}"} for i in range(1, 8)
]}

def fake_llm_result():
    return {
        "chart_insights": "테스트 인사이트",
        "top_keywords": ["a", "b"],
        "luna_briefs": [
            {"brief_id": 1, "title_concept": "T1", "genre": "lofi", "mood": "dawn", "topic": "x", "angle": "y"},
            {"brief_id": 2, "title_concept": "T2", "genre": "jazz", "mood": "rainy", "topic": "x", "angle": "y"},
            {"brief_id": 3, "title_concept": "T3", "genre": "piano", "mood": "calm", "topic": "x", "angle": "y"},
        ],
    }


class _TempTrendsDirMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        self.patches = [
            patch.object(trend_scout, "TRENDS_DIR", tmp_path),
            patch.object(trend_scout, "TOPIC_HISTORY_FILE", tmp_path / "topic_history.json"),
            patch.object(trend_scout, "fetch_top20_trends", return_value=FAKE_TRENDS),
        ]
        for p in self.patches:
            p.start()
        self.llm = patch.object(trend_scout.llm_client, "call_llm_json", return_value=(fake_llm_result(), "{}"))
        self.llm_mock = self.llm.start()

    def tearDown(self):
        self.llm.stop()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class MusicBriefCacheTests(_TempTrendsDirMixin, unittest.TestCase):

    def test_no_cache_returns_none(self):
        self.assertIsNone(trend_scout.load_cached_music_briefs("KR"))

    def test_first_call_hits_llm_and_writes_cache(self):
        res = trend_scout.analyze_music_trends_for_luna("KR")
        self.assertEqual(res["status"], "success")
        self.assertFalse(res["cached"])
        self.assertIn("fetched_at", res)
        self.assertEqual(self.llm_mock.call_count, 1)
        self.assertTrue(trend_scout._music_brief_cache_file("KR").exists())
        cached = trend_scout.load_cached_music_briefs("KR")
        self.assertTrue(cached["cached"])
        self.assertEqual(len(cached["analysis"]["luna_briefs"]), 3)
        self.assertLess(cached["age_hours"], 0.1)

    def test_second_call_within_ttl_uses_cache_without_llm(self):
        trend_scout.analyze_music_trends_for_luna("KR")
        res2 = trend_scout.analyze_music_trends_for_luna("KR")
        self.assertTrue(res2["cached"])
        self.assertEqual(self.llm_mock.call_count, 1)   # 두 번째 호출은 LLM·YouTube 없이 캐시

    def test_force_refresh_bypasses_cache(self):
        trend_scout.analyze_music_trends_for_luna("KR")
        res2 = trend_scout.analyze_music_trends_for_luna("KR", force_refresh=True)
        self.assertFalse(res2["cached"])
        self.assertEqual(self.llm_mock.call_count, 2)

    def test_stale_cache_is_refreshed(self):
        trend_scout.analyze_music_trends_for_luna("KR")
        path = trend_scout._music_brief_cache_file("KR")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["fetched_at"] = time.time() - 7 * 3600          # 7시간 전 → 기본 TTL 6시간 초과
        path.write_text(json.dumps(data), encoding="utf-8")
        res = trend_scout.analyze_music_trends_for_luna("KR")
        self.assertFalse(res["cached"])
        self.assertEqual(self.llm_mock.call_count, 2)
        # TTL 을 넉넉히 주면 같은 캐시를 재사용
        res3 = trend_scout.analyze_music_trends_for_luna("KR", max_age_hours=48)
        self.assertTrue(res3["cached"])
        self.assertEqual(self.llm_mock.call_count, 2)

    def test_ttl_zero_disables_cache(self):
        trend_scout.analyze_music_trends_for_luna("KR")
        res = trend_scout.analyze_music_trends_for_luna("KR", max_age_hours=0)
        self.assertFalse(res["cached"])
        self.assertEqual(self.llm_mock.call_count, 2)

    def test_region_cache_files_are_separate_and_sanitized(self):
        self.assertNotEqual(trend_scout._music_brief_cache_file("KR"), trend_scout._music_brief_cache_file("US"))
        self.assertEqual(trend_scout._music_brief_cache_file("../x").name, "luna_music_briefs_X.json")

    def test_corrupt_cache_file_is_ignored(self):
        trend_scout._music_brief_cache_file("KR").write_text("{not json", encoding="utf-8")
        self.assertIsNone(trend_scout.load_cached_music_briefs("KR"))


class MusicBriefApiTests(_TempTrendsDirMixin, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_cached_only_without_cache_makes_no_external_calls(self):
        resp = self.client.get("/api/trends/music-for-luna?region=KR&cached_only=1")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "empty")
        self.assertIsNone(body["analysis"])
        self.assertFalse(body["cached"])
        self.assertEqual(self.llm_mock.call_count, 0)

    def test_cached_only_returns_saved_result(self):
        trend_scout.analyze_music_trends_for_luna("KR")
        resp = self.client.get("/api/trends/music-for-luna?region=KR&cached_only=1")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["cached"])
        self.assertEqual(self.llm_mock.call_count, 1)

    def test_refresh_flag_forces_new_scouting(self):
        trend_scout.analyze_music_trends_for_luna("KR")
        resp = self.client.get("/api/trends/music-for-luna?region=KR&refresh=1")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["cached"])
        self.assertEqual(self.llm_mock.call_count, 2)

    def test_default_call_reuses_cache(self):
        trend_scout.analyze_music_trends_for_luna("KR")
        resp = self.client.get("/api/trends/music-for-luna?region=KR")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["cached"])
        self.assertEqual(self.llm_mock.call_count, 1)


class MusicBriefUiAssetsTests(unittest.TestCase):
    """루나 탭 진입 시 자동 스카우팅(버튼 자동 클릭)이 다시 들어오지 않도록 프론트 자산을 검사한다."""

    @classmethod
    def setUpClass(cls):
        cls.js = (BASE / "static" / "app.js").read_text(encoding="utf-8")
        cls.html = (BASE / "static" / "index.html").read_text(encoding="utf-8")

    def test_no_auto_click_on_tab_enter(self):
        self.assertNotIn("fetchBtn.click()", self.js)

    def test_tab_enter_loads_cached_only_and_button_refreshes(self):
        self.assertIn("loadLeoMusicBriefs({ cachedOnly: true })", self.js)
        self.assertIn("loadLeoMusicBriefs({ refresh: true, autoApply: true })", self.js)
        self.assertIn("params.set('cached_only', '1')", self.js)
        self.assertIn("params.set('refresh', '1')", self.js)

    def test_button_warns_about_api_cost(self):
        self.assertIn('id="btnFetchMusicTrends"', self.html)
        self.assertIn("API 비용 발생", self.html)


if __name__ == "__main__":
    unittest.main()
