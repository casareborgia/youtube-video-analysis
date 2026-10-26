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

import copy
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
        # 이미지 프롬프트 사양. layers 가 프롬프트에 요구할 JSON 구조를 결정한다.
        "image": {
            "persona": "세계 최고의 다큐멘터리/테크 유튜브 시각 디렉터이자 '나노바나나 레드라인(NanoBanana Redline)' 주석 다이어그램 이미지 프롬프트 엔지니어",
            "layers": ["scene", "annotation_layer", "text_layer"],
            "thumbnail_rule": "풀 레드라인 스타일 (시선 강탈 훅 문구 1개, 핵심 라벨 1~2개, 실제 치수 1개)",
            "scene_rule": "빨간 주석 그래픽(화살표, 원형 타겟, 바운딩 박스, 측정선) 위주로 구성",
            "schema_annotation": {
                "dimension_lines": ["vertical red dimension line measuring main height", "width marker"],
                "callout_arrows": ["crisp crimson arrow pointing to the critical core"],
                "bounding_boxes": ["red dashed rectangular bounding box highlighting the anomaly"],
                "focus_reticles": ["concentric red technical focus rings at center"],
            },
            "annotation_defaults": {
                "dimension_lines": ["vertical bright red dimension line with precision end ticks"],
                "callout_arrows": ["sharp crimson red pointer arrow indicating key structural feature"],
                "bounding_boxes": ["red dashed rectangular technical bounding box around central focal point"],
                "focus_reticles": ["concentric red technical reticle with millimeter calibration crosshairs"],
            },
            "model_directive": "Red engineering annotation overlay must point at the described targets.",
            # 화면 텍스트 허용 범위. 씬 첫 프레임은 영상으로 변환되므로 컨셉마다 다르다.
            "text_policy": {"thumbnail": True, "scene": True},
            "render_style_thumb": "photorealistic photography with sharp redline engineering annotations overlay",
            "render_style_scene": "photorealistic photography with redline graphics for AI video first frame",
            "composition": {
                "thumb_h": "horizontal cinematic 16:9 composition, centered focal subject, balanced technical annotations, left-to-right engineering HUD read flow",
                "scene_h": "horizontal 16:9 framing, rule of thirds subject with redline callout graphics",
            },
        },
    },

    "human_story": {
        "name": "인물·서사 중심",
        "description": "한 사람의 선택과 그 대가를 따라가는 감정 중심 내러티브. 도면 주석 없이 인물과 공간의 정서로 끌고 간다",
        "plot": "일상(평온) -> 균열(사건) -> 선택(갈림길) -> 대가(결과) -> 여운(남은 것)",
        "image_aesthetic": {
            "aesthetic": "intimate cinematic character photography, natural available light, shallow depth of field",
            "palette": "warm muted earth tones with soft highlight rolloff",
            "framing": "close and medium shots that keep the subject's face and hands readable",
            "overall_mood": "quiet emotional realism, unforced and observational",
        },
        "image_constraints": [
            "Do not render any text other than explicitly specified in text_layer",
            "All text must strictly use English/Korean exactly as quoted in double quotes",
            "Text strings must be under 10 characters",
            "No technical overlays, no diagram lines, no measurement marks, no HUD graphics",
            "Keep the frame photographic and unretouched over {style}",
        ],
        "render_style": "따뜻한 자연광 시네마틱 인물 사진, 얕은 심도, 부드러운 그림자, 절제된 색보정",
        "image": {
            "persona": "인물 다큐멘터리 시각 디렉터이자 감정 중심 시네마토그래퍼",
            # 주석 레이어 없음 — 이 팩의 그림에는 도면 그래픽이 들어가지 않는다
            "layers": ["scene", "text_layer"],
            "thumbnail_rule": "인물의 표정이나 결정적 순간이 중심. 짧은 감정 훅 문구 1개만 허용",
            "scene_rule": "인물의 시선·손·자세와 공간의 정서로 장면을 설명. 그래픽 요소 금지",
            "schema_annotation": None,
            "annotation_defaults": None,
            "model_directive": "Photographic frame only. Do not draw arrows, lines, boxes, reticles, diagrams or any graphic overlay.",
            # 인물 프레임에 글자가 얹히면 몰입을 깬다. 씬에는 텍스트를 넣지 않는다.
            "text_policy": {"thumbnail": True, "scene": False},
            "render_style_thumb": "natural light cinematic portrait photography, filmic grain",
            "render_style_scene": "natural light cinematic still for AI video first frame",
            "composition": {
                "thumb_h": "horizontal cinematic 16:9 composition, subject slightly off-center, generous negative space",
                "scene_h": "horizontal 16:9 framing, rule of thirds with breathing room around the subject",
            },
        },
    },

    "info_breakdown": {
        "name": "정보·지식 정리형",
        "description": "통념을 뒤집는 근거를 단계로 쌓아 결론에 도달하는 설명형. 라벨로 핵심을 짚되 도면 그래픽은 쓰지 않는다",
        "plot": "질문(왜 그런가) -> 통념(다들 이렇게 안다) -> 반전 근거(사실은) -> 검증(어떻게 아는가) -> 결론(그래서 무엇을)",
        "image_aesthetic": {
            "aesthetic": "clean editorial explanatory photography, uncluttered composition, single clear subject",
            "palette": "neutral bright tones with one saturated accent on the key object",
            "framing": "centered or symmetric framing that isolates the thing being explained",
            "overall_mood": "calm, precise, textbook-clear",
        },
        "image_constraints": [
            "Do not render any text other than explicitly specified in text_layer",
            "All text must strictly use English/Korean exactly as quoted in double quotes",
            "Text strings must be under 10 characters",
            "Keep the background uncluttered so the labelled subject reads instantly",
            "No diagram lines, no measurement marks, no HUD graphics over {style}",
        ],
        "render_style": "밝고 정갈한 에디토리얼 설명 사진, 균일한 조명, 배경 정리, 핵심 사물에 시선 집중",
        "image": {
            "persona": "지식 설명 콘텐츠의 시각 디렉터이자 에디토리얼 사진 감독",
            "layers": ["scene", "text_layer"],
            "thumbnail_rule": "설명 대상 하나를 크고 명확하게. 핵심 단어 라벨 1개만 허용",
            "scene_rule": "설명 대상을 배경 정리된 화면에 단독으로 배치. 도면 그래픽 금지",
            "schema_annotation": None,
            "annotation_defaults": None,
            "model_directive": "Clean editorial photograph. No diagram lines, arrows or overlays; only the labelled subject.",
            "text_policy": {"thumbnail": True, "scene": True},
            "render_style_thumb": "clean editorial product photography, even lighting",
            "render_style_scene": "clean editorial still for AI video first frame",
            "composition": {
                "thumb_h": "horizontal 16:9 composition, single centered subject, generous clean background",
                "scene_h": "horizontal 16:9 framing, isolated subject with uncluttered surroundings",
            },
        },
    },

    "product_review": {
        "name": "리뷰·제품 검증형",
        "description": "기대와 실제의 간극을 짚고 비교로 판정하는 리뷰. 스펙을 가리키는 최소한의 콜아웃만 사용한다",
        "plot": "기대(왜 궁금한가) -> 첫인상(실제로 보니) -> 한계(걸리는 점) -> 비교(대안과 견주면) -> 판정(누구에게 맞는가)",
        "image_aesthetic": {
            "aesthetic": "crisp studio product photography with tactile material detail",
            "palette": "neutral studio grey with controlled specular highlights",
            "framing": "three-quarter product angle showing form and key controls",
            "overall_mood": "objective, hands-on, close inspection",
        },
        "image_constraints": [
            "Do not render any text other than explicitly specified in text_layer",
            "All text must strictly use English/Korean exactly as quoted in double quotes",
            "Text strings must be under 10 characters",
            "Only use numerical facts actually mentioned in the script, never fabricate specs",
            "Callouts stay minimal and never cover the product over {style}",
        ],
        "render_style": "정밀 스튜디오 제품 사진, 재질감 강조, 통제된 반사광, 중립 배경",
        "image": {
            "persona": "테크 리뷰 채널의 제품 사진 디렉터",
            "layers": ["scene", "annotation_layer", "text_layer"],
            "thumbnail_rule": "제품을 크게, 판정을 암시하는 짧은 문구 1개",
            "scene_rule": "짚는 부위를 향한 최소한의 콜아웃만. 치수선·레티클은 쓰지 않는다",
            "schema_annotation": {
                "callout_arrows": ["thin neutral arrow pointing at the control being discussed"],
                "bounding_boxes": ["subtle corner brackets around the detail in question"],
            },
            "annotation_defaults": {
                "callout_arrows": ["thin light-grey arrow indicating the key control"],
                "bounding_boxes": ["subtle thin corner brackets framing the detail"],
            },
            "model_directive": "Keep callouts minimal and unobtrusive; never cover or obscure the product itself.",
            "text_policy": {"thumbnail": True, "scene": True},
            "render_style_thumb": "studio product photography with soft gradient backdrop",
            "render_style_scene": "studio product still for AI video first frame",
            "composition": {
                "thumb_h": "horizontal 16:9 composition, product hero angle filling the frame",
                "scene_h": "horizontal 16:9 framing, product three-quarter view with clean margins",
            },
        },
    },
    # 쇼츠(9:16) 정보형 — 작업계획서_쇼츠_자동화 7장 S-2. 서사 골격은 5씬 고정 순서이고,
    # 씬당 5~8초·총 30~58초를 shorts 블록에 수치로 둔다(shorts_engine 이 길이 컷·훅·엔드 태그 기본값으로 읽는다).
    "shorts_info": {
        "name": "쇼츠 정보형 (9:16)",
        "description": "2초 안에 멈추게 하는 훅 → 핵심 2개 → 반전/근거 → CTA. 세로 쇼츠 전용, 씬당 5~8초·총 30~58초",
        "plot": "훅(1씬, 2초 안에 시선 고정) -> 핵심 1 -> 핵심 2 -> 반전/근거(사실은) -> CTA(구독·다음 편)",
        "shorts": {
            "format": "scene",
            "scene_seconds": {"min": 5.0, "max": 8.0},
            "total_seconds": {"min": 30.0, "max": 58.0},
            "max_scenes": 6,
            "min_scenes": 4,
            "hook_words": {"min": 3, "max": 5},
            "hook_seconds": 3.0,
            # 한국어 초당 5.2자 기준: 30초 ≈ 70~80어절(≈155자), 60초 ≈ 125~150어절(≈310자)
            "ko_chars_per_sec": 5.2,
            "narration_chars_per_scene": {"min": 26, "max": 42},
            "end_tag": {"text": "구독하고 다음 편 보기", "subtext": "", "seconds": 2.4},  # 페이드인 0.33초를 빼고도 2초 읽히게(U-1 line_unread)
            "beats": ["훅", "핵심 1", "핵심 2", "반전/근거", "CTA"],
            # 씬 종류(작업계획서 7b, PR #42): image 외에는 Remotion 이 그려 이미지 비용 0. shorts_engine.SCENE_KINDS 와 같은 목록.
            "scene_kinds": ["image", "text_card", "stat_card", "bar_chart", "compare", "flyover", "scene3d"],
            "scene_kind_fields": ["palette", "title", "subtitle", "value", "unit", "prefix", "decimals", "label", "bars", "rows", "time_of_day", "seed",
                                  "scene3d"],
            "kind_guide": {
                "image": "히어로 장면(피사체·공간이 중요할 때). 편당 1~2씬만 — 유일한 생성 비용",
                "text_card": "훅·전환·결론 문장 (title ≤ 18자, subtitle ≤ 24자)",
                "stat_card": "숫자 하나를 크게 (value 숫자, unit 단위, label 설명)",
                "bar_chart": "2~5개 비교 (bars[{label, value, highlight}], unit)",
                "compare": "전→후 변화 (rows[{label, from, to, unit}])",
                "flyover": "지역·여행·자연·도시 이야기의 드론 항공 장면(3D 지형·강·하늘). title 은 지명 라벨(선택, ≤ 12자), time_of_day sunrise|day|sunset",
                "scene3d": ("어떤 주제든 쓰는 범용 3D 장면. scene3d 에 environment(sky|space|studio|dark)·ground(terrain|water|grid|floor|none)·"
                            "camera{move: orbit|dolly|flyover|pan|static}·accent(#hex)·objects 를 조합 — objects: globe{pins[{lat,lon,label}],arcs} "
                            "/ bars{items[{label,value,highlight}],unit} / text{text≤24자} / box·sphere·torus·cone·cylinder·icosahedron{material: "
                            "standard|metal|glass|emissive, position[x,y,z], scale, spin} / particles{count} / model{src}"),
            },
            "max_image_scenes": 2,
        },
        "image_aesthetic": {
            "aesthetic": "bold vertical mobile-first editorial photography, one oversized subject filling the frame",
            "palette": "high-contrast neutral base with one saturated accent color on the key object",
            "framing": "vertical 9:16, subject centered in the middle 60% so top hook text and bottom captions stay clear",
            "overall_mood": "punchy, instantly readable at phone size, zero clutter",
        },
        "image_constraints": [
            "Do not render any text other than explicitly specified in text_layer",
            "All text must strictly use English/Korean exactly as quoted in double quotes",
            "Text strings must be under 10 characters",
            "Keep the top 15% and bottom 20% of the frame free of important detail (overlay safe zones)",
            "Single dominant subject, uncluttered background, readable on a phone screen over {style}",
        ],
        "render_style": "모바일 세로 화면용 굵고 선명한 에디토리얼 사진, 핵심 피사체 하나를 크게, 고대비, 배경 정리",
        "image": {
            "persona": "유튜브 쇼츠·릴스 전문 비주얼 디렉터이자 세로 구도 사진 감독",
            "layers": ["scene", "text_layer"],
            "thumbnail_rule": "세로 9:16, 피사체 하나를 화면 가운데 크게. 훅 단어 라벨 1개만 허용",
            "scene_rule": "피사체 하나를 세로 화면 중앙 60% 안에 크게 배치. 상단·하단은 비워 둔다. 도면 그래픽 금지",
            "schema_annotation": None,
            "annotation_defaults": None,
            "model_directive": "Vertical 9:16 photograph with one dominant subject; keep top and bottom margins clean for overlays. No diagram lines or HUD graphics.",
            # 훅·자막은 Remotion 이 얹으므로 이미지에는 글자를 넣지 않는다
            "text_policy": {"thumbnail": True, "scene": False},
            "render_style_thumb": "bold vertical editorial photography, high contrast, phone-readable",
            "render_style_scene": "bold vertical editorial still, subject centered, clean top and bottom margins",
            "composition": {
                "thumb_h": "vertical 9:16 mobile composition, oversized centered subject, clean top and bottom margins",
                "scene_h": "vertical 9:16 framing, single subject in the central band, uncluttered surroundings",
            },
        },
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


def image_spec(key: str = None) -> Dict[str, Any]:
    """이미지 프롬프트 사양. layers 가 요구할 JSON 구조를 결정한다."""
    return get_pack(key).get("image", {})


def has_layer(key: str, layer: str) -> bool:
    return layer in (get_pack(key).get("image", {}).get("layers") or [])


def allows_text(key: str = None, slot: str = "scene") -> bool:
    """해당 슬롯(thumbnail/scene)에 화면 텍스트를 허용하는지."""
    policy = get_pack(key).get("image", {}).get("text_policy") or {}
    return bool(policy.get(slot, True))


def model_directive(key: str = None) -> str:
    """이미지 모델에 주는 추가 지시문. 컨셉마다 그래픽 오버레이 허용 여부가 다르다."""
    return get_pack(key).get("image", {}).get("model_directive", "")


def render_style(key: str = None) -> str:
    """producer 가 이미지 프롬프트 앞에 붙일 렌더 톤 문자열."""
    return get_pack(key)["render_style"]


def image_constraints(key: str = None, style_text: str = "") -> List[str]:
    """이미지 제약 목록. {style} 자리에 선택된 화풍을 채워 넣는다."""
    fallback = "high-detail realistic photography"
    style_text = (style_text or "").strip() or fallback
    return [c.replace("{style}", style_text) for c in get_pack(key)["image_constraints"]]


def _shiji_pack() -> Dict[str, Any]:
    """Shiji Files 고사 쇼츠(작업계획서_ShijiFiles_파일럿3편 P-3) — shorts_info 규격에 원문 인장·전국시대 지도 씬을 더한 전용 팩.
    두 씬은 이 팩에만 둔다 — 범용 쇼츠 기획 프롬프트에 고전 원문·지도 선택지가 섞이지 않게."""
    pack = copy.deepcopy(CONCEPT_PACKS["shorts_info"])
    pack["name"] = "Shiji Files 고사 쇼츠 (9:16)"
    pack["description"] = "사기·전국책 고사를 영어로 — 콜드 오픈 → 배경(지도) → 결정적 한 수 → 원문 인장 → 결말·예고"
    spec = pack["shorts"]
    spec["scene_kinds"] = spec["scene_kinds"] + ["seal", "map"]
    spec["scene_kind_fields"] = spec["scene_kind_fields"] + ["hanzi", "translation", "source", "states", "arrows", "year",
                                                           "grounding", "grounding_source"]
    # v3 고정 틀(2026-10-27 사용자 지시 — 이후 시리즈도 바꾸지 않는다): 6씬 순서 고정, 5씬 통찰은 원문 근거 필수, 6씬은 질문.
    # shorts_review._shiji_v3_findings 가 format_version 3 잡에 P0(발행 잠금)로 강제한다.
    spec["format_version"] = 3
    spec["min_scenes"] = spec["max_scenes"] = 6
    spec["beats"] = ["Cold open — the most shocking fact", "Setup — who, and what is at stake", "The move — what happened, as recorded",
                     "Original words — seal with source", "Why it worked — one insight grounded in an original line",
                     "Question — hand it back to the viewer"]
    pack["plot"] = "콜드 오픈(충격적 사실) -> 배경 -> 결정적 한 수 -> 원문 인장 -> 왜 통했나(원문 근거 통찰) -> 질문"
    # 수묵 시네마틱 톤(P-4): 로컬 ComfyUI 이미지(비용 0), 금색 강조, 영어 엔드 태그, 전환은 dip·zoom_through 위주
    spec["image_backend"] = "comfyui"
    spec["image_style"] = ("dark traditional Chinese ink wash painting, cinematic composition, ancient China in the Warring States period, "
                           "muted black and charcoal tones with warm gold light and a faint crimson sky, misty atmosphere, "
                           "no text, no letters, no calligraphy, no watermark")
    spec["accent"] = "#d4af37"
    spec["transitions"] = ["dip", "zoom_through", "fade", "wipe"]
    spec["end_tag"] = {"text": "Follow for the next story", "subtext": "Shiji Files", "seconds": spec["end_tag"].get("seconds", 2.4)}
    pack["render_style"] = "어두운 수묵 시네마틱 — 먹색 바탕, 금빛 조명, 옅은 붉은 하늘, 전국시대 중국. 글자 없음"
    pack["image_aesthetic"] = {
        "aesthetic": "dark traditional Chinese ink wash painting, cinematic, ancient China",
        "palette": "muted black and charcoal with warm gold light and a faint crimson accent",
        "framing": "vertical 9:16, subject in the central band so top hook text and bottom captions stay clear",
        "overall_mood": "solemn, mysterious, historical",
    }
    spec["kind_guide"].update({
        "seal": ("고전 원문 인장 카드. hanzi 원문(문장부호 빼고 ≤ 12자, 구절 DB 에서 그대로) · translation 자체 번역 · "
                 "source 출전(예: Shiji, ch. 85) — 출전 없으면 발행 잠금"),
        "map": ("전국시대 7국 개략도. states 강조 나라(qin|chu|qi|yan|zhao|wei|han) · arrows[{from,to}] 진군 동선 · "
                "year(기본 c. 260 BC) · title(선택, ≤ 24자)"),
    })
    return pack


CONCEPT_PACKS["shorts_shiji"] = _shiji_pack()

DEFAULT_SHORTS_SPEC = CONCEPT_PACKS["shorts_info"]["shorts"]


def is_shorts_pack(key: str = None) -> bool:
    """쇼츠 전용 팩인지(shorts 블록 보유)."""
    return bool(CONCEPT_PACKS.get(key or "", {}).get("shorts"))


def shorts_spec(key: str = None) -> Dict[str, Any]:
    """쇼츠 길이·훅·엔드 태그 규격. 쇼츠 팩이 아니면 shorts_info 의 기본 규격을 돌려준다."""
    spec = get_pack(key).get("shorts") if key else None
    return dict(spec or DEFAULT_SHORTS_SPEC)
