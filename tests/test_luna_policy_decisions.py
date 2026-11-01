"""루나 정책 파일 선택(luna_policy·trend_scout) & 결정 기록(luna_decisions·luna_engine) 테스트.

외부 호출(YouTube 업로드·LLM)은 전부 mock 이고, 파일은 임시 폴더에만 쓴다.
"""

import json
import os
import random
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import luna_decisions
import luna_engine
import luna_policy
import trend_scout
import uploader

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # KST 2026-10-24(토) 21:00
GENRES = trend_scout.active_luna_genres()


def make_policy(**over):
    k = len(GENRES)
    genre = {g: 1.0 / k for g in GENRES}
    policy = {
        "schema_version": 1,
        "policy_version": "luna-0.1.0+ts-2026w44",
        "valid_until": "2026-11-07T00:00:00Z",
        "exploration_floor": 0.10,
        "arms": {"format": {"single": 0.9, "compilation_1h": 0.1}, "genre": genre},
    }
    policy.update(over)
    return policy


class PolicyValidationTests(unittest.TestCase):
    def setUp(self):
        self.allowed, self.coverage = trend_scout.policy_arm_constraints()

    def validate(self, policy):
        return luna_policy.validate_policy(policy, self.allowed, self.coverage, now=NOW)

    def test_valid_policy_is_normalized(self):
        p = make_policy()
        p["arms"]["format"] = {"single": 0.9004, "compilation_1h": 0.1}
        out = self.validate(p)
        self.assertAlmostEqual(sum(out["arms"]["format"].values()), 1.0, places=9)

    def test_expired_policy_rejected(self):
        with self.assertRaisesRegex(luna_policy.PolicyError, "만료"):
            self.validate(make_policy(valid_until="2026-10-24T11:59:59Z"))

    def test_naive_valid_until_rejected(self):
        with self.assertRaisesRegex(luna_policy.PolicyError, "시간대"):
            self.validate(make_policy(valid_until="2026-11-07T00:00:00"))

    def test_wrong_schema_version_rejected(self):
        with self.assertRaises(luna_policy.PolicyError):
            self.validate(make_policy(schema_version=2))

    def test_floor_below_minimum_rejected(self):
        with self.assertRaisesRegex(luna_policy.PolicyError, "exploration_floor"):
            self.validate(make_policy(exploration_floor=0.05))

    def test_probability_below_exploration_share_rejected(self):
        # 선택지 2개, ε=0.1 → 각 확률 ≥ 0.05 이어야 한다
        p = make_policy()
        p["arms"]["format"] = {"single": 0.97, "compilation_1h": 0.03}
        with self.assertRaisesRegex(luna_policy.PolicyError, "탐색 하한"):
            self.validate(p)

    def test_zero_probability_rejected(self):
        p = make_policy()
        p["arms"]["format"] = {"single": 1.0, "shorts": 0.0}
        with self.assertRaises(luna_policy.PolicyError):
            self.validate(p)

    def test_missing_core_genre_rejected(self):
        p = make_policy()
        p["arms"]["genre"] = {g: 1.0 / (len(GENRES) - 1) for g in GENRES[:-1]}
        with self.assertRaisesRegex(luna_policy.PolicyError, "빠진 선택지"):
            self.validate(p)

    def test_archived_genre_rejected(self):
        p = make_policy()
        p["arms"]["genre"] = dict(p["arms"]["genre"], synthwave=0.0)
        with self.assertRaisesRegex(luna_policy.PolicyError, "허용되지 않는"):
            self.validate(p)

    def test_sum_not_one_rejected(self):
        p = make_policy()
        p["arms"]["format"] = {"single": 0.5, "compilation_1h": 0.3}
        with self.assertRaisesRegex(luna_policy.PolicyError, "합"):
            self.validate(p)

    def test_bool_probability_rejected(self):
        p = make_policy()
        p["arms"]["format"] = {"single": True}
        with self.assertRaises(luna_policy.PolicyError):
            self.validate(p)


class PolicyFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "luna_policy.json"
        self.allowed, self.coverage = trend_scout.policy_arm_constraints()

    def test_load_missing_and_broken(self):
        pol, reason = luna_policy.load_policy(self.allowed, self.path, self.coverage, NOW)
        self.assertIsNone(pol)
        self.assertIn("없음", reason)
        self.path.write_text("{", encoding="utf-8")
        pol, reason = luna_policy.load_policy(self.allowed, self.path, self.coverage, NOW)
        self.assertIsNone(pol)

    def test_atomic_write_then_load(self):
        luna_policy.write_policy_atomic(make_policy(), self.allowed, self.path, self.coverage, NOW)
        pol, reason = luna_policy.load_policy(self.allowed, self.path, self.coverage, NOW)
        self.assertEqual(reason, "ok")
        self.assertEqual(pol["policy_version"], "luna-0.1.0+ts-2026w44")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["luna_policy.json"])  # 임시 파일이 남지 않는다

    def test_invalid_write_keeps_existing_file(self):
        luna_policy.write_policy_atomic(make_policy(), self.allowed, self.path, self.coverage, NOW)
        before = self.path.read_text(encoding="utf-8")
        bad = make_policy(policy_version="bad", exploration_floor=0.0)
        with self.assertRaises(luna_policy.PolicyError):
            luna_policy.write_policy_atomic(bad, self.allowed, self.path, self.coverage, NOW)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["luna_policy.json"])


class DrawTests(unittest.TestCase):
    def test_conditional_probability_after_exclusion(self):
        probs = {"a": 0.5, "b": 0.3, "c": 0.2}
        chosen, p, pool = luna_policy.draw(probs, exclude=["a"], rng=random.Random(1))
        self.assertEqual(sorted(pool), ["b", "c"])
        self.assertAlmostEqual(p, probs[chosen] / 0.5)

    def test_eligible_restriction(self):
        chosen, p, pool = luna_policy.draw({"single": 0.9, "shorts": 0.1}, eligible=["single"])
        self.assertEqual((chosen, p, pool), ("single", 1.0, ["single"]))

    def test_empty_pool_raises(self):
        with self.assertRaises(ValueError):
            luna_policy.draw({"a": 1.0}, exclude=["a"])


class PickPolicyAssignmentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "luna_policy.json"
        self.stats = {g: 0 for g in trend_scout.LUNA_GENRES}
        self.stats["lofi"] = 4

    def pick(self, **kw):
        return trend_scout.pick_policy_assignments(
            count=2, stats=self.stats, policy_path=self.path, now=NOW, rng=random.Random(7), **kw)

    def test_fallback_uses_balanced_weights(self):
        res = self.pick()
        self.assertEqual(res["source"], "fallback_balanced")
        self.assertIsNone(res["policy_version"])
        self.assertIn("없음", res["fallback_reason"])
        weights = trend_scout.balanced_genre_weights(self.stats)
        first, second = res["slots"]
        g1, g2 = first["chosen"]["genre"], second["chosen"]["genre"]
        self.assertNotEqual(g1, g2)
        total = sum(weights.values())
        self.assertAlmostEqual(first["probabilities"]["genre"], weights[g1] / total)
        # 두 번째는 비복원 추출의 조건부 확률
        self.assertAlmostEqual(second["probabilities"]["genre"], weights[g2] / (total - weights[g1]))
        self.assertAlmostEqual(first["probabilities"]["mood"], 1.0 / len(trend_scout.LUNA_MOODS))
        self.assertAlmostEqual(second["probabilities"]["mood"], 1.0 / (len(trend_scout.LUNA_MOODS) - 1))
        self.assertEqual(first["chosen"]["format"], "single")
        self.assertEqual(first["chosen"]["vocal_mode"], "auto")
        joint = first["probabilities"]["genre"] * first["probabilities"]["mood"]
        self.assertAlmostEqual(first["action_probability"], joint)

    def test_policy_file_used_with_restricted_format(self):
        policy = make_policy()
        policy["arms"]["genre"] = {g: (0.4 if g == "jazz" else 0.6 / (len(GENRES) - 1)) for g in GENRES}
        self.path.write_text(json.dumps(policy), encoding="utf-8")
        res = self.pick()
        self.assertEqual(res["source"], "policy_file")
        self.assertEqual(res["policy_version"], "luna-0.1.0+ts-2026w44")
        first = res["slots"][0]
        self.assertEqual(first["chosen"]["format"], "single")
        self.assertEqual(first["eligible_actions"]["format"], ["single"])
        self.assertAlmostEqual(first["probabilities"]["format"], 1.0)
        self.assertAlmostEqual(first["probabilities"]["genre"], policy["arms"]["genre"][first["chosen"]["genre"]])

    def test_policy_without_eligible_format_falls_back(self):
        policy = make_policy()
        policy["arms"]["format"] = {"compilation_1h": 1.0}
        self.path.write_text(json.dumps(policy), encoding="utf-8")
        res = self.pick()
        self.assertEqual(res["source"], "fallback_balanced")
        self.assertIn("정책으로 뽑을 수 없음", res["fallback_reason"])

    def test_expired_policy_falls_back(self):
        self.path.write_text(json.dumps(make_policy(valid_until="2026-10-01T00:00:00Z")), encoding="utf-8")
        res = self.pick()
        self.assertEqual(res["source"], "fallback_balanced")
        self.assertIn("만료", res["fallback_reason"])

    def test_context_only_has_selection_time_values(self):
        ctx = self.pick()["context"]
        self.assertEqual(ctx["date_kst"], "2026-10-24")
        self.assertEqual(ctx["weekday_kst"], "sat")
        self.assertEqual(ctx["hour_kst"], 21)
        self.assertEqual(ctx["recent_genre_counts_30"]["lofi"], 4)
        self.assertNotIn("synthwave", ctx["recent_genre_counts_30"])

    def test_probabilities_never_zero(self):
        res = trend_scout.pick_policy_assignments(count=2, stats={"lofi": 1000}, policy_path=self.path, now=NOW)
        for slot in res["slots"]:
            self.assertGreater(slot["action_probability"], 0.0)


class BriefPolicyDecisionTests(unittest.TestCase):
    def test_briefs_carry_policy_decision(self):
        fake = {"chart_insights": "x", "top_keywords": ["a"], "luna_briefs": [
            {"brief_id": 1, "title_concept": "A", "genre": "x", "mood": "x", "topic": "t", "angle": "a"},
            {"brief_id": 2, "title_concept": "B", "genre": "x", "mood": "x", "topic": "t", "angle": "a"},
            {"brief_id": 3, "title_concept": "C", "genre": "piano", "mood": "cozy", "topic": "t", "angle": "a"},
        ]}
        trends = {"status": "success", "items": [{"rank": i, "title": f"곡 {i}", "channel_title": "c"} for i in range(1, 8)]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(trend_scout, "TRENDS_DIR", tmp_path), \
                 patch.object(trend_scout, "TOPIC_HISTORY_FILE", tmp_path / "topic_history.json"), \
                 patch.object(trend_scout, "fetch_top20_trends", return_value=trends), \
                 patch.object(trend_scout, "get_production_genre_stats", return_value={}), \
                 patch.object(luna_policy, "POLICY_PATH", tmp_path / "none.json"), \
                 patch.object(trend_scout.llm_client, "call_llm_json", return_value=(fake, "{}")):
                result = trend_scout.analyze_music_trends_for_luna("KR", force_refresh=True)
        briefs = result["analysis"]["luna_briefs"]
        for b in briefs[:2]:
            pd = b["policy_decision"]
            self.assertEqual(pd["source"], "fallback_balanced")
            self.assertEqual(pd["chosen"]["genre"], b["genre"])
            self.assertEqual(pd["chosen"]["mood"], b["mood"])
            self.assertGreater(pd["action_probability"], 0)
        self.assertEqual(briefs[1]["policy_decision"]["draw_index"], 2)
        self.assertEqual(briefs[2]["policy_decision"]["source"], "llm_brief")
        self.assertIsNone(briefs[2]["policy_decision"]["action_probability"])


class DecisionLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "decisions.jsonl"

    def test_decision_then_applied_append_only(self):
        chosen = {"format": "single", "genre": "jazz", "mood": "rainy", "vocal_mode": "auto"}
        d = luna_decisions.record_decision(
            chosen=chosen, action_probability=0.04, source="policy_file", policy_version="v1",
            context={"date_kst": "2026-10-24"}, eligible_actions={"genre": GENRES}, track_id="luna_1",
            path=self.path, now=NOW)
        self.assertTrue(d["decision_id"].startswith("luna-"))
        self.assertEqual(d["created_at"], "2026-10-24T12:00:00Z")
        a = luna_decisions.record_applied(
            d["decision_id"], applied=dict(chosen, mood="cozy"), video_id="VID1",
            publish_at="2026-10-25T21:00:00+09:00", track_id="luna_1", path=self.path, now=NOW)
        self.assertEqual(a["changed_fields"], ["mood"])
        self.assertEqual(a["content_id"], "VID1")
        self.assertTrue(a["decision_found"])
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["event"] for x in lines], ["decision", "applied"])
        self.assertEqual(json.loads(lines[1])["decision_id"], d["decision_id"])

    def test_invalid_probability_rejected(self):
        for bad in (0.0, 1.5, -0.1):
            with self.assertRaises(ValueError):
                luna_decisions.record_decision(chosen={}, action_probability=bad, source="policy_file",
                                               policy_version="v", context={}, eligible_actions={}, path=self.path)
        self.assertFalse(self.path.exists())

    def test_load_skips_broken_line(self):
        luna_decisions.record_decision(chosen={}, action_probability=None, source="manual", policy_version=None,
                                       context={}, eligible_actions={}, path=self.path)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"event": "decis')
        self.assertEqual(len(luna_decisions.load_events(self.path)), 1)

    def test_track_decision_without_brief_is_manual(self):
        rec = luna_decisions.record_track_decision(
            {"track_id": "luna_9"}, None, {"format": "single", "genre": "piano", "mood": "dawn", "vocal_mode": "auto"},
            path=self.path)
        self.assertEqual(rec["source"], "manual")
        self.assertIsNone(rec["action_probability"])
        self.assertEqual(rec["chosen"]["genre"], "piano")


class EngineDecisionHookTests(unittest.TestCase):
    """곡 생성 → decision_id 가 meta.json 에 들어가고, 업로드 → 같은 id 로 applied 이벤트가 붙는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        lp.start()
        self.addCleanup(lp.stop)
        self.log = Path(self.tmp) / "decisions.jsonl"

    def brief(self):
        return {"genre": "jazz", "mood": "rainy", "policy_decision": {
            "source": "policy_file", "policy_version": "v1", "context_as_of": "2026-10-24T12:00:00Z",
            "context": {"weekday_kst": "sat"}, "eligible_actions": {"format": ["single"]},
            "chosen": {"format": "single", "genre": "jazz", "mood": "rainy", "vocal_mode": "auto"},
            "probabilities": {"genre": 0.2, "mood": 0.1}, "action_probability": 0.02, "draw_index": 1}}

    def test_generate_records_decision_and_human_change(self):
        track = {"track_id": "luna_d", "vocal_mode": "instrumental"}
        luna_engine.attach_track_decision(track, self.brief(), genre="jazz", mood="cozy")
        events = luna_decisions.load_events(self.log)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["decision_id"], track["decision_id"])
        self.assertEqual(events[0]["action_probability"], 0.02)
        self.assertEqual(events[0]["context_as_of"], "2026-10-24T12:00:00Z")
        self.assertEqual(events[0]["draw_index"], 1)
        self.assertEqual(track["applied_action"], {"format": "single", "genre": "jazz", "mood": "cozy",
                                                   "vocal_mode": "instrumental"})

    def test_log_failure_does_not_block_generation(self):
        track = {"track_id": "luna_e"}
        with patch.object(luna_decisions, "record_track_decision", side_effect=OSError("disk")):
            luna_engine.attach_track_decision(track, None, genre="lofi", mood="dawn")
        self.assertNotIn("decision_id", track)
        self.assertEqual(track["applied_action"]["genre"], "lofi")

    def test_upload_appends_applied_event(self):
        d = os.path.join(self.tmp, "luna_u")
        os.makedirs(d)
        for name in ("video.mp4", "cover.jpg"):
            Path(d, name).write_bytes(b"\x00")
        track = {"track_id": "luna_u", "title": "Song", "genre": "Late Night Jazz Cafe",
                 "video_file": os.path.join(d, "video.mp4"), "cover_file": os.path.join(d, "cover.jpg"),
                 "metadata": {"youtube_title": "Long", "youtube_description": "desc", "youtube_tags": ["t"],
                              "pinned_comment": "pin"}}
        luna_engine.attach_track_decision(track, self.brief(), genre="jazz", mood="cozy")
        luna_engine.save_track(track)
        fake = {"video_id": "VID1", "url": "https://youtu.be/VID1", "publish_at": "2026-10-25T21:00:00+09:00",
                "comment_posted": False, "warnings": []}
        with patch.object(uploader, "upload_video", return_value=fake), \
             patch.object(luna_engine, "_needs_signature_rerender", return_value=False):
            luna_engine.upload_luna_to_youtube("luna_u", privacy_status="private",
                                               publish_at="2026-10-25T21:00:00+09:00")
        saved = luna_engine.load_track("luna_u")
        self.assertEqual(saved["decision_id"], track["decision_id"])
        events = luna_decisions.load_events(self.log)
        self.assertEqual([e["event"] for e in events], ["decision", "applied"])
        applied = events[1]
        self.assertEqual(applied["decision_id"], track["decision_id"])
        self.assertEqual(applied["video_id"], "VID1")
        self.assertEqual(applied["publish_at"], "2026-10-25T21:00:00+09:00")
        self.assertEqual(applied["changed_fields"], ["mood"])

    def test_upload_without_decision_writes_nothing(self):
        luna_engine._record_upload_outcome({"track_id": "x", "uploaded_video_id": "V"})
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
