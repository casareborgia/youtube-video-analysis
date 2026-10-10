"""춘식 BGA UI 패널 및 프론트엔드 자산 단위 테스트 (Phase C-1c)."""

import os
import shutil
import subprocess
import unittest


class ChoonsikBgaUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
        cls.base = base
        with open(os.path.join(base, "index.html"), encoding="utf-8") as f:
            cls.html = f.read()
        with open(os.path.join(base, "app.js"), encoding="utf-8") as f:
            cls.js = f.read()

    def test_index_html_contains_bga_ids(self):
        expected_ids = [
            "lunaBgaPanel",
            "lunaBgaUsage",
            "btnLunaBgaPlan",
            "btnLunaBgaGenerate",
            "lunaBgaShots",
            "lunaBgaClips",
            "lunaBgaRendererSelect",
            "lunaBgaWaveformCheck",
            "btnLunaBgaRender",
            "lunaBgaRenderNote",
            "lunaVideoSourceBadge",
        ]
        for el_id in expected_ids:
            self.assertIn(f'id="{el_id}"', self.html, f"HTML 내 id='{el_id}' 요소 누락")

    def test_index_html_retains_existing_ids(self):
        existing_ids = [
            "btnRenderLunaVideo",
            "lunaShortsPanel",
            "btnUploadLunaYt",
            "lunaWithShortsCheck",
        ]
        for el_id in existing_ids:
            self.assertIn(f'id="{el_id}"', self.html, f"기존 핵심 id='{el_id}' 요소가 보존되지 않음")

    def test_app_js_contains_bga_strings(self):
        expected_strings = [
            "renderLunaBgaPanel",
            "/api/luna/bga/plan",
            "/api/luna/bga/generate",
            "/api/luna/bga/render",
            "confirm: true",
            "window.confirm",
            "luna_bga_renderer",
        ]
        for s in expected_strings:
            self.assertIn(s, self.js, f"app.js 내 필수 패턴 '{s}' 누락")

    def test_node_check_app_js(self):
        if not shutil.which("node"):
            self.skipTest("시스템에 node 가 설치되어 있지 않음")
        res = subprocess.run(
            ["node", "--check", os.path.join(self.base, "app.js")],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"node --check 실패:\n{res.stderr}")


if __name__ == "__main__":
    unittest.main()
