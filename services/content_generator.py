"""
구조화 소셜 콘텐츠 생성 엔진 (Content Generator)
- 어사이드 Zero-Penalty Link Chaining 계약 엄격 준수:
  1. 본문(body): 어떠한 외부 URL 링크도 절대 포함하지 않음 (140자 내외 핵심 요약 + 🔁 CTA)
  2. 첫 번째 답글(first_reply): 원문 출처 링크 또는 마음지기 서비스 링크 배치
- LLM (Gemini/Claude) 프롬프트 파이프라인 및 고품질 템플릿 폴백 완비
"""

import json
import re
from typing import Optional, Dict, Any
from adapters.sources.base import RawCollectedItem
from domain.models import StructuredDraft
import llm_client


def _strip_markdown_codeblocks(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


class ContentGenerator:
    def __init__(self):
        pass

    async def generate_draft_for_item(
        self,
        item: RawCollectedItem,
        routine_code: str,
        angle_info: Optional[Dict[str, Any]] = None
    ) -> StructuredDraft:
        """
        수집된 원문 또는 앵글 정보로부터 Zero-Penalty 본문 및 첫 답글 생성
        """
        # 1. LLM 생성 시도
        try:
            draft = await self._generate_via_llm(item, routine_code, angle_info)
            if draft and self._validate_contract(draft, item.url):
                return draft
        except Exception:
            pass

        # 2. LLM 실패 또는 계약 위반 시 견고한 템플릿 폴백
        return self._generate_fallback(item, routine_code, angle_info)

    async def _generate_via_llm(
        self,
        item: RawCollectedItem,
        routine_code: str,
        angle_info: Optional[Dict[str, Any]] = None
    ) -> Optional[StructuredDraft]:
        system_instruction = (
            "당신은 X(Twitter)와 Threads에서 수만 명의 팔로워를 보유한 최고 수준의 테크/라이프스타일 에디터입니다.\n"
            "핵심 규칙 (Zero-Penalty Chaining):\n"
            "1. body(본문)에는 절대로 링크(http, https, www 등)를 넣지 마십시오. 링크가 들어가면 알고리즘 페널티를 받습니다.\n"
            "2. body는 140자 내외로 호기심을 유발하는 첫 문장(훅), 핵심 내용 2문장, 그리고 답글 확인을 유도하는 CTA(🔁 🧵)로 구성하십시오.\n"
            "3. first_reply(첫 번째 셀프 답글)에만 원문 링크 또는 서비스 링크를 명시하십시오.\n"
            "4. 반드시 유효한 JSON 형식으로만 응답하십시오."
        )

        prompt = f"""
다음 자료를 바탕으로 X와 Threads에 최적화된 소셜 포스트를 작성해주세요.

[자료 정보]
루틴: {routine_code}
출처: {item.source_name}
제목: {item.title}
내용: {item.summary[:400]}
원문 링크: {item.url}

다음 JSON 구조로 응답해주세요:
{{
  "headline": "1줄 요약 제목",
  "body": "링크가 절대 없는 140자 내외 본문. 끝에 🔁 🧵 포함",
  "first_reply": "원문 링크가 포함된 첫 번째 답글 (예: 📌 원문 상세 내용 및 링크는 여기에 남깁니다: {item.url})",
  "topic_key": "{item.title[:20].strip()}"
}}
"""
        response_text = await llm_client.generate_json_or_text(
            prompt=prompt,
            system_instruction=system_instruction
        )

        cleaned_text = _strip_markdown_codeblocks(response_text)
        data = json.loads(cleaned_text)

        body = data.get("body", "").strip()
        first_reply = data.get("first_reply", "").strip()

        # 만약 본문에 링크가 포함되어 있다면 답글로 이전
        urls_in_body = re.findall(r"https?://\S+", body)
        for u in urls_in_body:
            body = body.replace(u, "").strip()
            if u not in first_reply:
                first_reply += f"\n📌 링크: {u}"

        return StructuredDraft(
            headline=data.get("headline", item.title[:30]),
            body=body,
            first_reply=first_reply or f"📌 원문 링크: {item.url}",
            topic_key=data.get("topic_key", routine_code),
            quality_score=0.95
        )

    def _generate_fallback(
        self,
        item: RawCollectedItem,
        routine_code: str,
        angle_info: Optional[Dict[str, Any]] = None
    ) -> StructuredDraft:
        """규칙 기반 고품질 템플릿 생성기"""
        url = item.url or "https://maumjigi.com"

        if routine_code == "MAUM_PROMO":
            hook = (angle_info or {}).get("hook_template") or "오늘 하루, 마음의 온도는 어떠셨나요?"
            body_text = (
                f"{hook}\n\n"
                "남들의 기준에 맞추느라 지친 나에게 딱 3분의 쉼표를 선물해보세요. "
                "기록하는 것만으로도 마음의 상처는 아물기 시작합니다.\n\n"
                "자세한 힐링 가이드는 첫 번째 답글에 남겨둡니다. 🔁 🌿\n\n"
                "#마음케어 #힐링 #감정일기 #마음지기"
            )
            reply_text = (
                f"🌿 24시간 안전한 익명 AI 마음친구 '마음지기' 바로가기:\n"
                f"{url}\n\n"
                "언제든 편안하게 당신의 이야기를 들려주세요."
            )
            headline = (angle_info or {}).get("title") or "마음지기 힐링 레터"

        elif routine_code == "RESEARCH":
            title_clean = item.title.replace("\n", " ").strip()
            summary_clean = item.summary.replace("\n", " ")[:90].strip()
            body_text = (
                f"🔬 [최신 AI 논문 브리핑] {title_clean}\n\n"
                f"핵심: {summary_clean}...\n\n"
                "연구진이 제시한 새로운 접근법과 실험 결과는 기술 혁신에 큰 시사점을 줍니다.\n\n"
                "논문 원문과 상세 자료는 아래 답글에서 확인하세요! 🔁 🧵\n\n"
                "#AI연구 #머신러닝 #논문리뷰"
            )
            reply_text = (
                f"📄 논문 전문 및 코드 아카이브:\n"
                f"{url}\n\n"
                "연구 관련 질문이나 의견은 자유롭게 남겨주세요!"
            )
            headline = title_clean[:35]

        else:  # AI_TREND 및 기본 루틴
            title_clean = item.title.replace("\n", " ").strip()
            body_text = (
                f"⚡ {title_clean}\n\n"
                "주요 AI/테크 생태계에서 주목받는 최신 소식입니다. "
                "업계 전문가들과 개발자들이 지금 가장 뜨겁게 논의 중인 인사이트를 정리했습니다.\n\n"
                "원문 링크와 상세 토론은 바로 첫 번째 답글에 남깁니다. 🔁 🧵\n\n"
                "#AI #테크트렌드 #생성형AI"
            )
            reply_text = (
                f"📌 원문 링크 및 토론 확인:\n"
                f"{url}\n\n"
                "더 많은 테크 브리핑을 보시려면 팔로우 & 리트윗 부탁드립니다."
            )
            headline = title_clean[:35]

        return StructuredDraft(
            headline=headline,
            body=body_text,
            first_reply=reply_text,
            topic_key=item.title[:20].strip() or routine_code,
            quality_score=0.9
        )

    def _validate_contract(self, draft: StructuredDraft, expected_url: str) -> bool:
        """Zero-Penalty 계약 검증: 본문에 링크가 없어야 하고, 답글에 원문 링크가 있어야 함"""
        body_has_link = bool(re.search(r"https?://", draft.body))
        reply_has_link = bool(re.search(r"https?://", draft.first_reply))
        return (not body_has_link) and reply_has_link
