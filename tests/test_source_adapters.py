import unittest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from adapters.sources.rss import RssAdapter
from adapters.sources.huggingface import HuggingFacePapersAdapter
from adapters.sources.arxiv import ArxivAdapter
from adapters.sources.maum_site import MaumSiteAdapter
from adapters.sources.base import RawCollectedItem
from domain.models import SourceTestResponse


class TestSourceAdapters(unittest.TestCase):
    def test_rss_adapter_mock(self):
        adapter = RssAdapter()
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0">
          <channel>
            <title>Mock Tech News</title>
            <item>
              <title>Mock AI News 1</title>
              <link>https://example.com/item/1</link>
              <description>Summary of mock AI news.</description>
            </item>
          </channel>
        </rss>"""

        async def run_test():
            mock_test_res = SourceTestResponse(success=True)
            with patch("adapters.sources.rss.test_source_url", new=AsyncMock(return_value=mock_test_res)):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.content = xml_content
                with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
                    items = await adapter.fetch_items("https://example.com/rss.xml")
                    self.assertEqual(len(items), 1)
                    self.assertEqual(items[0].title, "Mock AI News 1")
                    self.assertEqual(items[0].url, "https://example.com/item/1")

        asyncio.run(run_test())

    def test_arxiv_weekend_fallback_to_huggingface(self):
        arxiv_adapter = ArxivAdapter()
        # arXiv 결과가 0건(주말 skipDays)일 때 Hugging Face로 폴백하는지 검증
        mock_hf_items = [
            RawCollectedItem(
                title="Weekend Paper on Reasoning",
                url="https://huggingface.co/papers/2501.9999",
                summary="Reasoning models analysis",
                source_name="Hugging Face Daily Papers",
                source_kind="HUGGINGFACE_PAPERS"
            )
        ]

        async def run_test():
            with patch.object(arxiv_adapter.hf_fallback, "fetch_items", new=AsyncMock(return_value=mock_hf_items)):
                with patch("adapters.sources.arxiv.test_source_url", new=AsyncMock(return_value=SourceTestResponse(success=False))):
                    items = await arxiv_adapter.fetch_items("https://rss.arxiv.org/rss/cs.AI")
                    self.assertEqual(len(items), 1)
                    self.assertEqual(items[0].title, "Weekend Paper on Reasoning")
                    self.assertEqual(items[0].extra_metadata.get("fallback_from"), "ARXIV_WEEKEND_SKIPDAYS")

        asyncio.run(run_test())

    def test_maum_site_adapter(self):
        maum_adapter = MaumSiteAdapter()

        async def run_test():
            mock_test_res = SourceTestResponse(success=True)
            with patch("adapters.sources.maum_site.test_source_url", new=AsyncMock(return_value=mock_test_res)):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = "<html><head><title>마음지기 — AI 마음친구</title></head></html>"
                with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
                    config = {
                        "angle_title": "번아웃 극복",
                        "hook_template": "지친 나를 위해 딱 3분",
                        "body_template": "마음의 소리에 귀 기울여보세요."
                    }
                    items = await maum_adapter.fetch_items("https://maumjigi.com", config=config)
                    self.assertEqual(len(items), 1)
                    self.assertIn("번아웃 극복", items[0].title)
                    self.assertIn("3분", items[0].summary)
                    self.assertEqual(items[0].url, "https://maumjigi.com")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
