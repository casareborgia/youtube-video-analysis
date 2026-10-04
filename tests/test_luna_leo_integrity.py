"""Unit and integrity tests for Agent Luna and Agent Leo (Trend Scout).

Ensures that during the Threads/X integration and subsequent phases,
Agent Luna (luna_engine) and Agent Leo (trend_scout) remain 100% operational,
all presets, core schemas, endpoints, and data access work without regression.
"""

import unittest
import warnings

# Suppress StarletteDeprecationWarning when importing TestClient under -W error
warnings.filterwarnings("ignore", message=".*Using `httpx` with `starlette.testclient`.*")

from fastapi.testclient import TestClient

import luna_engine
import trend_scout
from app import app


class LunaLeoIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_luna_engine_core_specs_intact(self):
        """에이전트 루나 코어 프리셋 및 사운드 스펙 무결성 검증"""
        self.assertGreaterEqual(len(luna_engine.GENRE_PRESETS), 10)
        genre_ids = [g["id"] for g in luna_engine.GENRE_PRESETS]
        self.assertIn("lofi", genre_ids)
        self.assertIn("ambient", genre_ids)
        self.assertIn("synthwave", genre_ids)
        self.assertIn("citypop", genre_ids)

        # Every preset must have matching GENRE_SPECS
        for g_id in genre_ids:
            self.assertIn(g_id, luna_engine.GENRE_SPECS)
            spec = luna_engine.GENRE_SPECS[g_id]
            self.assertIn("bpm_range", spec)
            self.assertIn("instruments", spec)
            self.assertIn("visual_style", spec)

    def test_trend_scout_leo_core_specs_intact(self):
        """에이전트 레오(트렌드 스카우트) 카테고리 및 루나 연동 무결성 검증"""
        self.assertIn("10", trend_scout.YOUTUBE_CATEGORIES)  # 음악
        self.assertIn("0", trend_scout.YOUTUBE_CATEGORIES)   # 전체 급상승
        self.assertGreaterEqual(len(trend_scout.LUNA_GENRES), 10)
        self.assertGreaterEqual(len(trend_scout.LUNA_MOODS), 10)

    def test_luna_and_leo_api_routes_registered(self):
        routes = []
        for route in app.routes:
            if hasattr(route, "path"):
                routes.append(route.path)
            elif hasattr(route, "routes"):
                for sub in getattr(route, "routes", []):
                    if hasattr(sub, "path"):
                        routes.append(sub.path)
        
        # 루나 엔드포인트 목록
        required_luna_routes = [
            "/api/luna/presets",
            "/api/luna/generate",
            "/api/luna/render",
            "/api/luna/upload",
            "/api/luna/history",
            "/api/luna/playlist-recommendation",
            "/api/luna/unassigned-playlist-tracks",
            "/api/luna/batch-assign-playlists",
        ]
        for r in required_luna_routes:
            self.assertIn(r, routes, f"루나 라우트 누락: {r}")

        # 레오(트렌드) 엔드포인트 목록
        required_leo_routes = [
            "/api/trends/top20",
            "/api/trends/analyze",
            "/api/trends/music-for-luna",
        ]
        for r in required_leo_routes:
            self.assertIn(r, routes, f"레오 라우트 누락: {r}")

    def test_luna_api_endpoints_live_call(self):
        """루나 API 엔드포인트 직접 호출 동작 검증"""
        resp_presets = self.client.get("/api/luna/presets")
        self.assertEqual(resp_presets.status_code, 200)
        data = resp_presets.json()
        self.assertIn("genres", data)
        self.assertIn("moods", data)

        resp_history = self.client.get("/api/luna/history")
        self.assertEqual(resp_history.status_code, 200)
        self.assertIsInstance(resp_history.json(), list)

    def test_leo_api_endpoints_live_call(self):
        """레오 API 엔드포인트 직접 호출 동작 검증"""
        resp_top20 = self.client.get("/api/trends/top20?category_id=10&region_code=KR")
        self.assertEqual(resp_top20.status_code, 200)
        data = resp_top20.json()
        self.assertEqual(data.get("status"), "success")


if __name__ == "__main__":
    unittest.main()
