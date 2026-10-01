import tempfile
import unittest
from pathlib import Path

from engagement_automation import (
    EngagementAutomationService,
    EngagementPolicy,
    EngagementStore,
    EngagementTarget,
)


class EngagementAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = EngagementStore(Path(self.tmp.name) / "events.db")
        policy = EngagementPolicy(delay_seconds=0)
        self.service = EngagementAutomationService(store=store, policy=policy)
        self.target = EngagementTarget(
            platform="x",
            post_id="2105629134760370403",
            account_id="1453335049198202883",
            post_url="https://x.com/example/status/2105629134760370403",
            profile_url="https://x.com/example",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_never_constructs_live_client(self):
        self.service._client = lambda *_: self.fail("live client must not be created")
        result = self.service.execute([self.target], dry_run=True)
        self.assertEqual([r["status"] for r in result["results"]], ["dry_run"] * 3)

    def test_same_target_is_not_processed_twice(self):
        self.service.execute([self.target], actions=["like"], dry_run=True)
        result = self.service.execute([self.target], actions=["like"], dry_run=True)
        self.assertEqual(result["results"][0]["status"], "skipped_duplicate")

    def test_rejects_non_platform_url(self):
        bad = EngagementTarget(
            platform="threads",
            post_id="abc123",
            account_id="example",
            post_url="https://example.com/post/abc123",
        )
        with self.assertRaises(ValueError):
            self.service.execute([bad], dry_run=True)

    def test_rejects_url_for_different_platform(self):
        bad = EngagementTarget(
            platform="x",
            post_id="abc123",
            account_id="example",
            post_url="https://www.threads.com/@example/post/abc123",
        )
        with self.assertRaises(ValueError):
            self.service.execute([bad], dry_run=True)

    def test_request_target_limit(self):
        targets = [
            EngagementTarget("x", str(i), f"account{i}")
            for i in range(self.service.policy.max_targets_per_request + 1)
        ]
        with self.assertRaises(ValueError):
            self.service.execute(targets, dry_run=True)

    def test_rejects_empty_or_duplicate_actions(self):
        with self.assertRaises(ValueError):
            self.service.execute([self.target], actions=[], dry_run=True)
        with self.assertRaises(ValueError):
            self.service.execute([self.target], actions=["like", "like"], dry_run=True)


if __name__ == "__main__":
    unittest.main()
