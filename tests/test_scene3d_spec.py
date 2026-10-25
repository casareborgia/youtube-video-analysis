"""범용 3D 장면(scene3d) 설명 검증 — 기획 AI 가 조금 틀려도 Remotion 렌더가 깨지지 않게 정리한다."""
import unittest

import scene3d_spec as s3


class NormalizeScene3dTests(unittest.TestCase):
    def test_empty_spec_gets_safe_defaults(self):
        out = s3.normalize_scene3d(None, scene_num=2)
        self.assertEqual(out["environment"], "studio")
        self.assertEqual(out["ground"], "floor")            # 스튜디오 기본 바닥
        self.assertEqual(out["time_of_day"], "sunset")
        self.assertEqual(out["camera"], {"move": "orbit", "distance": 8.0, "height": 2.5, "sweep": 40.0})
        self.assertEqual(out["accent"], "#ffd166")
        self.assertEqual(out["seed"], 2)
        self.assertEqual(out["objects"], [])

    def test_environment_decides_default_ground(self):
        self.assertEqual(s3.normalize_scene3d({"environment": "sky"})["ground"], "terrain")
        self.assertEqual(s3.normalize_scene3d({"environment": "space"})["ground"], "none")
        self.assertEqual(s3.normalize_scene3d({"environment": "dark"})["ground"], "grid")
        self.assertEqual(s3.normalize_scene3d({"environment": "sky", "ground": "water"})["ground"], "water")

    def test_unknown_values_fall_back(self):
        out = s3.normalize_scene3d({"environment": "underwater", "ground": "lava", "time_of_day": "midnight",
                                    "camera": {"move": "spin", "distance": 999, "height": "x", "sweep": -720},
                                    "accent": "red"})
        self.assertEqual((out["environment"], out["ground"], out["time_of_day"]), ("studio", "floor", "sunset"))
        self.assertEqual(out["camera"]["move"], "orbit")
        self.assertEqual(out["camera"]["distance"], 60.0)        # 상한
        self.assertEqual(out["camera"]["height"], 2.5)
        self.assertEqual(out["camera"]["sweep"], -360.0)         # 하한
        self.assertEqual(out["accent"], "#ffd166")

    def test_objects_are_cleaned_and_limited(self):
        objs = [
            {"type": "box", "color": "#ff0000", "position": [1, 2, 3, 4], "scale": 50, "spin": 30, "material": "metal"},
            {"type": "sphere", "position": "here", "material": "lava"},
            {"type": "dragon"},                                   # 모르는 물체는 빠진다
            {"type": "text", "text": "아주 긴 문구가 화면을 넘어가지 않도록 잘라야 합니다 정말로"},
            {"type": "bars", "items": [{"label": "A", "value": 87, "highlight": True}, {"label": "B", "value": "x"},
                                       {"label": "C", "value": 50}], "unit": "%"},
            {"type": "bars", "items": [{"label": "only", "value": 1}]},   # 막대 2개 미만은 빠진다
            {"type": "globe", "pins": [{"lat": 37.5, "lon": 127.0, "label": "서울"}, {"lat": 999, "lon": 0}], "arcs": True},
            {"type": "particles", "count": 999999, "color": "#00ffcc"},
        ] + [{"type": "torus"}] * 20
        out = s3.normalize_scene3d({"objects": objs})["objects"]
        self.assertLessEqual(len(out), s3.MAX_OBJECTS)
        box = out[0]
        self.assertEqual((box["type"], box["color"], box["position"], box["scale"], box["spin"], box["material"]),
                         ("box", "#ff0000", [1.0, 2.0, 3.0], [20.0, 20.0, 20.0], 30.0, "metal"))
        sphere = out[1]
        self.assertEqual((sphere["position"], sphere["material"]), ([0.0, 0.0, 0.0], "standard"))
        types = [o["type"] for o in out]
        self.assertNotIn("dragon", types)
        text = next(o for o in out if o["type"] == "text")
        self.assertLessEqual(len(text["text"]), 24)
        bars = [o for o in out if o["type"] == "bars"]
        self.assertEqual(len(bars), 1)
        self.assertEqual([i["label"] for i in bars[0]["items"]], ["A", "C"])
        self.assertEqual(bars[0]["unit"], "%")
        globe = next(o for o in out if o["type"] == "globe")
        self.assertEqual(globe["pins"], [{"lat": 37.5, "lon": 127.0, "label": "서울"}])
        self.assertFalse(globe["arcs"])                          # 핀이 하나뿐이면 연결선을 그리지 않는다
        parts = next(o for o in out if o["type"] == "particles")
        self.assertEqual(parts["count"], 3000)

    def test_model_keeps_src_only(self):
        out = s3.normalize_scene3d({"objects": [{"type": "model", "src": "robot.glb", "scale": 2},
                                                {"type": "model"}]})["objects"]
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["src"], out[0]["scale"]), ("robot.glb", [2.0, 2.0, 2.0]))

    def test_flyover_camera_requires_terrain(self):
        out = s3.normalize_scene3d({"environment": "studio", "camera": {"move": "flyover"}})
        self.assertEqual(out["camera"]["move"], "orbit")         # 지형이 없으면 항공 이동은 의미가 없다
        out = s3.normalize_scene3d({"environment": "sky", "camera": {"move": "flyover"}})
        self.assertEqual(out["camera"]["move"], "flyover")


if __name__ == "__main__":
    unittest.main()
