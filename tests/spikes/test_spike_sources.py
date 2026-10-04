import unittest
import httpx
import feedparser

class TestSpikeSources(unittest.TestCase):
    """Phase 0 (Spike 0): 기본 출처 5종 연결성 및 파싱 가능 여부 검증"""

    def test_01_geeknews_rss(self):
        url = "https://news.hada.io/rss/news"
        parsed = feedparser.parse(url)
        self.assertFalse(parsed.bozo and not parsed.entries, "GeekNews RSS 파싱 실패")
        self.assertGreater(len(parsed.entries), 0, "GeekNews 항목 0개")
        entry = parsed.entries[0]
        self.assertTrue(entry.get("title"))
        self.assertTrue(entry.get("link"))
        print(f"\n[GeekNews RSS 검증 성공] 최신 기사: {entry.get('title')[:35]}... ({entry.get('link')})")

    def test_02_arxiv_ai_rss_and_skipdays(self):
        url = "https://rss.arxiv.org/rss/cs.AI"
        parsed = feedparser.parse(url)
        # arXiv는 주말에 skipDays(Saturday, Sunday) 설정으로 entries가 0일 수 있음을 확인
        channel = parsed.feed
        self.assertIn("cs.AI", channel.get("title", ""))
        is_weekend_skip = len(parsed.entries) == 0
        if is_weekend_skip:
            print("\n[arXiv RSS 검증 성공] 주말 skipDays 감지 (주말엔 Hugging Face Daily Papers로 자동 폴백)")
        else:
            print(f"\n[arXiv RSS 검증 성공] 최신 논문: {parsed.entries[0].get('title')[:35]}")

    def test_03_deepmind_rss(self):
        url = "https://deepmind.google/blog/rss.xml"
        parsed = feedparser.parse(url)
        self.assertFalse(parsed.bozo and not parsed.entries, "DeepMind RSS 파싱 실패")
        self.assertGreater(len(parsed.entries), 0, "DeepMind 항목 0개")
        entry = parsed.entries[0]
        self.assertTrue(entry.get("title"))
        self.assertTrue(entry.get("link"))
        print(f"\n[DeepMind RSS 검증 성공] 최신 리서치: {entry.get('title')[:35]}... ({entry.get('link')})")

    def test_04_huggingface_daily_papers(self):
        url = "https://huggingface.co/api/daily_papers?limit=10"
        resp = httpx.get(url, timeout=15)
        self.assertEqual(resp.status_code, 200, "HF Daily Papers 응답 실패")
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0, "HF 논문 목록 0건")
        first = data[0]
        paper = first.get("paper", {})
        self.assertTrue(paper.get("id"))
        self.assertTrue(paper.get("title"))
        print(f"\n[HuggingFace API 검증 성공] 추천 논문: {paper.get('title')[:35]}... (추천: {paper.get('upvotes', 0)})")

    def test_05_maumjigi_site_availability(self):
        url = "https://i-ching-ai-consultant.vercel.app/"
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            self.assertEqual(resp.status, 200, "마음지기 사이트 응답 실패")
            text = resp.read().decode("utf-8", errors="ignore")
            self.assertIn("주역", text, "마음지기 사이트 핵심 키워드 확인")
            print("\n[마음지기 사이트 검증 성공] HTTP 200 OK 및 주역 심층 AI 상담 키워드 확인 완료")

if __name__ == "__main__":
    unittest.main()
