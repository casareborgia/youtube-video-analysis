import unittest
from services.deduplicator import normalize_url, compute_url_hash, DeduplicationService
from adapters.sources.base import RawCollectedItem


class TestDeduplicator(unittest.TestCase):
    def test_url_normalization(self):
        url1 = "https://example.com/article?utm_source=twitter&utm_medium=social"
        url2 = "https://example.com/article"
        self.assertEqual(normalize_url(url1), url2)

        url_params = "https://news.hada.io/topic?id=123&utm_campaign=daily&ref=aside"
        expected = "https://news.hada.io/topic?id=123"
        self.assertEqual(normalize_url(url_params), expected)

    def test_url_hash_consistency(self):
        url1 = "https://example.com/item/42?utm_source=rss"
        url2 = "https://example.com/item/42"
        self.assertEqual(compute_url_hash(url1), compute_url_hash(url2))

    def test_curate_best_items(self):
        service = DeduplicationService()
        items = [
            RawCollectedItem(
                title="너무 짧음",
                url="https://example.com/1",
                summary="요약 없음",
                source_name="Test",
                source_kind="RSS"
            ),
            RawCollectedItem(
                title="Google DeepMind 새로운 멀티모달 AI 모델 연구 공개",
                url="https://example.com/2",
                summary="구글 딥마인드 연구진이 기존 LLM 한계를 돌파한 새로운 멀티모달 에이전트 아키텍처를 공개했습니다.",
                source_name="Test",
                source_kind="RSS"
            ),
        ]
        curated = service.curate_best_items(items, max_items=1)
        self.assertEqual(len(curated), 1)
        self.assertIn("DeepMind", curated[0].title)


if __name__ == "__main__":
    unittest.main()
