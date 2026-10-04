import re
import unittest
import asyncio
from services.content_generator import ContentGenerator
from adapters.sources.base import RawCollectedItem


class TestContentGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = ContentGenerator()

    def test_zero_penalty_chaining_contract_ai_trend(self):
        async def run_test():
            item = RawCollectedItem(
                title="OpenAI o1 추론 모델 공개 및 벤치마크 분석",
                url="https://news.hada.io/topic?id=17400",
                summary="OpenAI가 복잡한 과학, 코딩, 수학 문제를 심층 추론하는 o1 모델을 공식 출시했습니다.",
                source_name="GeekNews",
                source_kind="RSS_ATOM"
            )
            draft = await self.generator.generate_draft_for_item(item, routine_code="AI_TREND")

            # 1. 본문에는 외부 링크가 절대 없어야 함 (Zero-Penalty)
            body_links = re.findall(r"https?://", draft.body)
            self.assertEqual(len(body_links), 0, f"본문에 링크가 포함되어 있습니다: {draft.body}")

            # 2. 첫 답글에는 원문 링크가 반드시 포함되어야 함
            self.assertIn("https://news.hada.io/topic?id=17400", draft.first_reply)

            # 3. 본문에 리트윗/공유 유도 CTA 포함 여부
            self.assertTrue("🔁" in draft.body or "답글" in draft.body)

        asyncio.run(run_test())

    def test_zero_penalty_chaining_maum_promo(self):
        async def run_test():
            item = RawCollectedItem(
                title="[마음지기 힐링 레터] 번아웃 극복",
                url="https://maumjigi.com",
                summary="지친 나를 위해 딱 3분 쉼표를 선물하세요.",
                source_name="마음지기",
                source_kind="SITE_ADAPTER"
            )
            angle_info = {
                "title": "번아웃 극복 & 에너지 리셋",
                "hook_template": "지친 나를 위해 딱 3분, 마음의 소리에 귀 기울여보세요.",
                "body_template": "지속적인 긴장과 피로는 마음의 경고 신호입니다."
            }
            draft = await self.generator.generate_draft_for_item(
                item, routine_code="MAUM_PROMO", angle_info=angle_info
            )

            # 본문 링크 0개
            self.assertEqual(len(re.findall(r"https?://", draft.body)), 0)
            # 첫 답글에 마음지기 링크
            self.assertIn("https://maumjigi.com", draft.first_reply)
            # 본문에 해시태그 포함
            self.assertIn("#마음", draft.body)

        asyncio.run(run_test())

    def test_zero_penalty_chaining_research(self):
        async def run_test():
            item = RawCollectedItem(
                title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via RL",
                url="https://huggingface.co/papers/2501.12948",
                summary="Large language models reasoning capabilities with pure reinforcement learning.",
                source_name="Hugging Face Daily Papers",
                source_kind="HUGGINGFACE_PAPERS"
            )
            draft = await self.generator.generate_draft_for_item(item, routine_code="RESEARCH")

            # 본문 링크 0개
            self.assertEqual(len(re.findall(r"https?://", draft.body)), 0)
            # 첫 답글에 논문 링크
            self.assertIn("https://huggingface.co/papers/2501.12948", draft.first_reply)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
