# -*- coding: utf-8 -*-
"""영상 컨셉 팩 — 서사 골격 · 이미지 미학 · 렌더 스타일을 한 세트로 묶는다.

기존에는 이 값들이 prompt_generator 와 producer 에 개별 상수로 흩어져 있었고,
서로 짝이 맞아야 하는데도 따로 수정해야 했다. 여기로 모아 교체 가능하게 만든다.

축은 두 개로 분리한다.
  - 컨셉(concept)  : 서사 골격 + 주석/그래픽 미학 + 렌더 톤  (이 파일)
  - 화풍(style_key): 사진/필름/3D/애니 등 렌더링 질감        (prompt_generator.STYLE_PRESETS)

화풍은 컨셉 위에 덧입히는 축이다. 컨셉이 '무엇을 어떤 문법으로 보여줄지'를 정하고,
화풍이 '어떤 질감으로 그릴지'를 정한다.
"""

from typing import Any, Dict, List

DEFAULT_CONCEPT = "redline_engineering"

CONCEPT_PACKS: Dict[str, Dict[str, Any]] = {
    # 이 프로젝트의 원래 컨셉. 기본값으로 유지한다.
    "redline_engineering": {
        "name": "레드라인 공학 다큐",
        "description": "기술 도면풍 빨간 주석과 미니어처 디오라마로 구조물·시스템을 해부하는 탐사 다큐",
        # 씬 대본 프롬프트에 주입되는 5단계 서사 골격
        "plot": "도입 훅 -> 갈등/스케일 -> 공학적 난제 -> 해결 시도 -> 씁쓸한 현실과 깊은 여운",
        # 레드라인 이미지 프롬프트의 style 블록
        "image_aesthetic": {
            "aesthetic": "NanoBanana Redline technical blueprint and engineering annotation aesthetic",
            "annotation_color": "vivid crimson red (#FF0000 / bright neon red)",
            "line_weights": "crisp 1px - 2px precision vector lines, technical arrows, circular reticles, bounding measurement boxes",
            "overall_mood": "documentary investigative deep-dive, cyber-engineering HUD analysis",
        },
        # {style} 자리에는 사용자가 고른 화풍(STYLE_PRESETS)이 들어간다
        "image_constraints": [
            "Do not render any text other than explicitly specified in text_layer",
            "All text must strictly use English/Korean exactly as quoted in double quotes",
            "Text strings must be under 10 characters",
            "Only use numerical facts actually mentioned in the script, never fabricate random numbers",
            "Redline graphics must be pure sharp red (#FF0000) over {style}",
        ],
        # producer 가 이미지 생성 프롬프트 앞에 붙이는 렌더 톤
        "render_style": "시네마틱 다큐멘터리 3D 미니어처 디오라마, 차가운 청록 색감, 부드러운 스튜디오 조명, 사실적인 질감, 빨간 공학 주석(레드라인)",
    },
}


def get_pack(key: str = None) -> Dict[str, Any]:
    """컨셉 팩을 반환한다. 알 수 없는 키는 기본 팩으로 대체한다."""
    return CONCEPT_PACKS.get(key or DEFAULT_CONCEPT, CONCEPT_PACKS[DEFAULT_CONCEPT])


def list_packs() -> List[Dict[str, str]]:
    """UI 용 컨셉 목록."""
    return [
        {"key": k, "name": v["name"], "description": v.get("description", "")}
        for k, v in CONCEPT_PACKS.items()
    ]


def render_style(key: str = None) -> str:
    """producer 가 이미지 프롬프트 앞에 붙일 렌더 톤 문자열."""
    return get_pack(key)["render_style"]


def image_constraints(key: str = None, style_text: str = "") -> List[str]:
    """이미지 제약 목록. {style} 자리에 선택된 화풍을 채워 넣는다."""
    fallback = "high-detail realistic photography"
    style_text = (style_text or "").strip() or fallback
    return [c.replace("{style}", style_text) for c in get_pack(key)["image_constraints"]]
