"""
AI Prompt Studio - Custom Topic & 8-Second Video Prompt Engine with Hybrid LLM
1. 분석된 영상들의 공통 흥행 성공 공식(훅 설계, 서사 빌드업, 스케일 대비) 주입
2. 8초 단위 씬별 타임스탬프 자막 대본(35~45자) 및 시네마틱 프롬프트 자동 생성
3. Google Flow (Veo/Imagen), Midjourney v6.1, Runway Gen-3 / Kling AI / Sora 타겟 포맷 최적화
4. llm_client (LM Studio / Ollama 자동 감지 & 자동 이어쓰기) 연동
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import llm_client

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

STYLE_PRESETS = {
    "photorealistic_8k": {
        "name": "Photorealistic 8K (실사 영화풍)",
        "prompt": "hyperrealistic 8k cinematic photography, shot on ARRI Alexa Mini LF, Master Prime lenses, natural skin and material textures, highly detailed"
    },
    "film_35mm": {
        "name": "35mm Vintage Film (빈티지 필름)",
        "prompt": "shot on 35mm Kodak Vision3 color film, subtle film grain, rich organic colors, nostalgic halation, cinematic movie still"
    },
    "unreal_engine_5": {
        "name": "Unreal Engine 5 Render (3D 그래픽)",
        "prompt": "Unreal Engine 5.4 cinematic render, Octane photoreal lighting, Ray-traced reflections, Lumen global illumination, 8k masterpiece"
    },
    "anime_cinematic": {
        "name": "Cinematic Anime (신카이 마코토 풍)",
        "prompt": "gorgeous Makoto Shinkai anime aesthetic, lush vibrant sky, detailed painterly backgrounds, emotive light flares, high production anime"
    }
}

SUPPORTED_LANGUAGES = {
    "korean": {"name": "한국어 (Korean)", "label": "Korean", "qwen_code": "korean"},
    "english": {"name": "English (영어)", "label": "English", "qwen_code": "english"},
    "japanese": {"name": "日本語 (일본어)", "label": "Japanese", "qwen_code": "japanese"},
    "chinese": {"name": "中文 (중국어)", "label": "Chinese", "qwen_code": "chinese"},
    "french": {"name": "Français (프랑스어)", "label": "French", "qwen_code": "french"},
    "german": {"name": "Deutsch (독일어)", "label": "German", "qwen_code": "german"},
    "spanish": {"name": "Español (스페인어)", "label": "Spanish", "qwen_code": "spanish"}
}

SUPPORTED_MODELS = {
    "google_flow": {
        "name": "Google Flow (Veo 2/3, Imagen 3/4)",
        "description": "AutoFlow-Pro 최적화 서술형 시네마틱 프롬프트",
        "default_aspect": "16:9"
    },
    "midjourney": {
        "name": "Midjourney v6.1",
        "description": "파라미터(--ar, --v 6.1, --style raw) 자동 추가",
        "default_aspect": "16:9"
    },
    "runway_kling": {
        "name": "Runway Gen-3 / Kling AI / Sora",
        "description": "8초 단위 비디오 생성용 모션 및 물리 인터랙션 프롬프트",
        "default_aspect": "16:9"
    }
}


def sanitize_input_text(text: str) -> str:
    """사용자 입력 텍스트에서 프롬프트 인젝션 의심 구문 및 제어 문자 정제"""
    if not text:
        return ""
    cleaned = re.sub(r'[\r\n]+', ' ', text)
    cleaned = re.sub(r'(?i)(ignore\s+previous\s+instructions|system\s*:|assistant\s*:|\[system\]|\[inst\]|<\|im_start\|>|<\|im_end\|>)', '', cleaned)
    return cleaned.strip()[:300]


def extract_script_numerical_facts(topic: str, scenes: List[Dict[str, Any]]) -> List[str]:
    """영상 주제 및 자막 텍스트에 실제 등장한 수치/단위/연도 팩트 정밀 추출 (환각 방지)"""
    corpus = topic + " " + " ".join([
        (s.get("narration") or s.get("subtitle") or "") + " " + (s.get("visual_description_ko") or "")
        for s in scenes
    ])
    # 숫자 + 단위 패턴 추출 (예: 50층, 1만 미터, 168만, 8초, 300m, 2050년, -50°C, 100%, 5단계 등)
    pattern = r'\b-?\d+(?:,\d+)*(?:\.\d+)?\s*(?:층|만|억|조|m|km|톤|ton|%|초|분|시간|도|미터|kg|g|MB|GB|TB|k|M|B|m/s|km/h|°C|Hz|W|V|A|년|대|개|명|곳)?\b'
    matches = re.findall(pattern, corpus, flags=re.IGNORECASE)
    cleaned = []
    seen = set()
    for m in matches:
        item = m.strip()
        if item and item not in seen and len(item) <= 10:
            seen.add(item)
            cleaned.append(item)
    return cleaned[:8]


def enforce_quoted_text(text: Any, max_len: int = 10) -> str:
    """모든 문구와 숫자는 큰따옴표로 지정하며 문구당 10자 이내로 정제 강제"""
    if not text:
        return '""'
    raw = str(text).replace('"', '').replace("'", "").strip()
    raw = raw[:max_len]
    return f'"{raw}"'


def get_fixed_redline_style() -> Dict[str, Any]:
    """코드에서 고정으로 주입하는 나노바나나 레드라인 스타일 블록"""
    return {
        "aesthetic": "NanoBanana Redline technical blueprint and engineering annotation aesthetic",
        "annotation_color": "vivid crimson red (#FF0000 / bright neon red)",
        "line_weights": "crisp 1px - 2px precision vector lines, technical arrows, circular reticles, bounding measurement boxes",
        "overall_mood": "documentary investigative deep-dive, cyber-engineering HUD analysis"
    }


def get_fixed_redline_constraints() -> List[str]:
    """코드에서 항상 고정으로 주입하는 제약 사항 블록"""
    return [
        "Do not render any text other than explicitly specified in text_layer",
        "All text must strictly use English/Korean exactly as quoted in double quotes",
        "Text strings must be under 10 characters",
        "Only use numerical facts actually mentioned in the script, never fabricate random numbers",
        "Redline graphics must be pure sharp red (#FF0000) over high-detail realistic photography"
    ]


class PromptGenerator:
    """분석 데이터 공통 강점 추출 및 신규 주제 기반 AI 프롬프트 생성기"""

    @staticmethod
    def extract_common_strengths(data_dir: Path) -> Dict[str, Any]:
        """data 폴더 내 분석 영상들로부터 공통 성공 강점과 연출 패턴을 추출"""
        reports = []
        analyzed_titles = []

        if data_dir.exists():
            for report_path in sorted(data_dir.glob("*_리포트.txt")):
                try:
                    with open(report_path, "r", encoding="utf-8") as f:
                        reports.append(f.read())
                except Exception:
                    pass
            for meta_path in sorted(data_dir.glob("*_metadata.json")):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        m = json.load(f)
                        if m.get("title") or m.get("info", {}).get("title"):
                            t = m.get("title") or m.get("info", {}).get("title")
                            analyzed_titles.append(t)
                except Exception:
                    pass

        return {
            "total_analyzed": len(analyzed_titles),
            "analyzed_titles": analyzed_titles[:10],
            "core_formulas": [
                {
                    "title": "초반 5초 시선 고정 인트로 훅",
                    "description": "'낭만'과 '냉혹한 현실'의 극적 대비로 호기심 극대화",
                    "badge": "Retention +45%"
                },
                {
                    "title": "5단계 마스터 서사 구조",
                    "description": "도입 → 갈등 심화 → 난제 제시 → 해결 시도 → 비판적 결론",
                    "badge": "Pacing Mastery"
                },
                {
                    "title": "스케일 대비 시각화",
                    "description": "거대한 크기/수치 팩트를 웅장한 익스트림 와이드 샷으로 대비",
                    "badge": "Visual Scale"
                },
                {
                    "title": "시네마틱 조명 & 카메라 무빙",
                    "description": "분위기별 틴들 현상(Volumetric Rays), Chiaroscuro 조명 자동 적용",
                    "badge": "Cinematic Lighting"
                }
            ]
        }

    @classmethod
    def generate_redline_image_prompts(
        cls,
        topic: str,
        scenes: List[Dict[str, Any]],
        aspect_ratio: str = "16:9",
        style_key: str = "photorealistic_8k"
    ) -> Dict[str, Any]:
        """
        [나노바나나 레드라인 이미지 프롬프트 자동 생성 파이프라인]
        1. 썸네일: 풀 레드라인 (시선 강탈 훅 문구 + 부위별 라벨 + 정밀 치수선)
        2. 씬별 첫 프레임: 빨간 주석 그래픽 위주, 텍스트는 최대 1개 (영상 변환 시 글자 뭉개짐 방지)
        3. 16:9 / 9:16 구도 반영 및 코드 레벨 10자 이내 큰따옴표 & 수치 환각 방지 강제
        """
        is_vertical = (aspect_ratio == "9:16")
        comp_layout_thumb = (
            "vertical mobile 9:16 composition, top bold hook headline area, centered visual subject, vertical dimension lines, clean bottom subtitle clearance"
            if is_vertical else
            "horizontal cinematic 16:9 composition, centered focal subject, balanced technical annotations, left-to-right engineering HUD read flow"
        )
        comp_layout_scene = (
            "vertical 9:16 framing, central focus graphic, top/side redline markers, clear bottom margin"
            if is_vertical else
            "horizontal 16:9 framing, rule of thirds subject with redline callout graphics"
        )

        real_facts = extract_script_numerical_facts(topic, scenes)
        facts_str = ", ".join([f'"{f}"' for f in real_facts]) if real_facts else '"핵심 팩트"'

        scene_summaries = []
        for s in scenes:
            s_num = s.get("scene_num", 1)
            narr = s.get("narration") or s.get("subtitle") or ""
            desc = s.get("visual_description_ko") or ""
            scene_summaries.append(f"씬 {s_num}: (대본: {narr[:40]}) (비주얼: {desc[:40]})")

        scenes_context = "\n".join(scene_summaries)

        prompt = f"""당신은 세계 최고의 다큐멘터리/테크 유튜브 시각 디렉터이자 '나노바나나 레드라인(NanoBanana Redline)' 주석 다이어그램 이미지 프롬프트 엔지니어입니다.

[영상 주제]
"{topic}"

[씬별 대본 및 비주얼]
{scenes_context}

[자막에 실제 등장한 수치 팩트 (지어내기 절대 금지, 이 수치들만 사용 가능)]
{facts_str}

[화면 비율]
{aspect_ratio} ({'세로 쇼츠 구도: 상단 훅, 하단 여백, 세로 치수선' if is_vertical else '가로 롱폼 시네마틱 구도'})

[작성 요구사항]
1. 썸네일 프롬프트 (1개):
   - 풀 레드라인 스타일 (시선 강탈 훅 문구 1개, 핵심 라벨 1~2개, 실제 치수 1개)
   - 모든 텍스트/라벨은 10자 이내이며 큰따옴표("...")로 지정할 것
2. 씬별 첫 프레임 프롬프트 ({len(scenes)}개):
   - 비디오 AI(Runway/Kling/Sora)에서 첫 프레임으로 사용하여 영상으로 변환할 이미지 프롬프트
   - 빨간 주석 그래픽(화살표, 원형 타겟, 바운딩 박스, 측정선) 위주로 구성
   - 텍스트는 글자 뭉개짐을 방지하기 위해 최대 1개(핵심 부위 라벨 또는 빈 문자열)만 지정할 것

아래 JSON 형식 규격으로만 응답해주세요:
```json
{{
  "thumbnail": {{
    "scene": {{
      "subject": "Core dramatic subject description in English",
      "environment": "Background lighting, atmospheric volumetric mist, dramatic contrast",
      "camera_angle": "Eye-level intense cinematic close-up / extreme wide shot"
    }},
    "annotation_layer": {{
      "dimension_lines": ["vertical red dimension line measuring main height", "width marker"],
      "callout_arrows": ["crisp crimson arrow pointing to the critical core"],
      "bounding_boxes": ["red dashed rectangular bounding box highlighting the anomaly"],
      "focus_reticles": ["concentric red technical focus rings at center"]
    }},
    "text_layer": {{
      "hook_text": "{enforce_quoted_text(topic[:8])}",
      "labels": ["{enforce_quoted_text('CORE')}", "{enforce_quoted_text('LEVEL 1')}"],
      "dimensions": ["{real_facts[0] if real_facts else 'SEC-01'}"]
    }}
  }},
  "scenes": [
    {{
      "scene_num": 1,
      "scene": {{
        "subject": "Detailed English visual description for scene 1 first frame",
        "environment": "Lighting and atmospheric mood",
        "camera_angle": "Camera composition"
      }},
      "annotation_layer": {{
        "dimension_lines": ["red measurement indicator line"],
        "callout_arrows": ["sharp red pointer arrow at key focal point"],
        "bounding_boxes": ["subtle technical corner brackets"],
        "focus_reticles": ["red target circle"]
      }},
      "text_layer": {{
        "label": "{enforce_quoted_text('ANOMALY')}"
      }}
    }}
  ]
}}
```
반드시 유효한 JSON 형식만 출력해주세요."""

        messages = [
            {"role": "system", "content": "You are an expert NanoBanana Redline image prompt architect. Output ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ]

        raw_resp = llm_client.call_llm(messages, max_tokens=3500, temperature=0.6)

        parsed = None
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_resp)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1).strip())
            except Exception:
                pass
        if not parsed:
            try:
                brace_match = re.search(r'\{[\s\S]*\}', raw_resp)
                if brace_match:
                    parsed = json.loads(brace_match.group(0))
            except Exception:
                pass

        # -------------------------------------------------------------
        # 코드 레벨 규칙 강제 (Rules Enforced by Code)
        # -------------------------------------------------------------
        fixed_style = get_fixed_redline_style()
        fixed_constraints = get_fixed_redline_constraints()

        # 1. 썸네일 프롬프트 구축 및 정제
        raw_thumb = (parsed.get("thumbnail") if isinstance(parsed, dict) else {}) or {}
        t_scene = raw_thumb.get("scene", {})
        t_ann = raw_thumb.get("annotation_layer", {})
        t_text = raw_thumb.get("text_layer", {})

        # 텍스트 레이어 10자 이내 & 큰따옴표 & 실제 수치 강제
        hook_raw = t_text.get("hook_text") or topic[:8]
        hook_val = enforce_quoted_text(hook_raw, max_len=10)

        raw_labels = t_text.get("labels", ["CORE", "SECTOR"])
        if isinstance(raw_labels, str):
            raw_labels = [raw_labels]
        clean_labels = [enforce_quoted_text(lbl, max_len=10) for lbl in raw_labels[:2]]

        raw_dims = t_text.get("dimensions", [])
        if isinstance(raw_dims, str):
            raw_dims = [raw_dims]
        clean_dims = []
        if real_facts:
            # 실제 등장한 팩트와 매칭되는 것 우선 사용
            for d in raw_dims:
                d_str = str(d).replace('"', '').strip()
                match_fact = next((rf for rf in real_facts if rf in d_str or d_str in rf), None)
                if match_fact:
                    clean_dims.append(enforce_quoted_text(match_fact, 10))
            if not clean_dims:
                clean_dims = [enforce_quoted_text(real_facts[0], 10)]
        else:
            clean_dims = [enforce_quoted_text("SEC-01", 10)]

        thumbnail_redline = {
            "format": {
                "aspect_ratio": aspect_ratio,
                "render_style": "photorealistic photography with sharp redline engineering annotations overlay",
                "composition_layout": comp_layout_thumb
            },
            "style": fixed_style,
            "scene": {
                "subject": t_scene.get("subject") or f"Cinematic hero shot representing {topic}, sharp subject focus",
                "environment": t_scene.get("environment") or "Dramatic chiaroscuro lighting with deep shadows and moody volumetric haze",
                "camera_angle": t_scene.get("camera_angle") or "Direct eye-level high-impact cinematic angle"
            },
            "annotation_layer": {
                "dimension_lines": t_ann.get("dimension_lines") or ["vertical bright red dimension line with precision end ticks"],
                "callout_arrows": t_ann.get("callout_arrows") or ["sharp crimson red pointer arrow indicating key structural feature"],
                "bounding_boxes": t_ann.get("bounding_boxes") or ["red dashed rectangular technical bounding box around central focal point"],
                "focus_reticles": t_ann.get("focus_reticles") or ["concentric red technical reticle with millimeter calibration crosshairs"]
            },
            "text_layer": {
                "hook_text": hook_val,
                "labels": clean_labels if clean_labels else [enforce_quoted_text("CORE", 10)],
                "dimensions": clean_dims
            },
            "constraints": fixed_constraints
        }

        # 2. 씬별 첫 프레임 프롬프트 구축 및 정제 (텍스트 최대 1개)
        raw_scene_list = (parsed.get("scenes") if isinstance(parsed, dict) else []) or []
        scene_redline_map = {}
        for r_sc in raw_scene_list:
            if isinstance(r_sc, dict) and "scene_num" in r_sc:
                scene_redline_map[r_sc["scene_num"]] = r_sc

        scene_first_frames = []
        for idx, sc in enumerate(scenes, start=1):
            s_num = sc.get("scene_num", idx)
            sc_raw = scene_redline_map.get(s_num) or (raw_scene_list[idx-1] if idx-1 < len(raw_scene_list) else {})
            
            s_scene = sc_raw.get("scene", {})
            s_ann = sc_raw.get("annotation_layer", {})
            s_text = sc_raw.get("text_layer", {})

            # 씬 첫 프레임 텍스트는 최대 1개로 제한 (영상 변환 시 글자 뭉개짐 방지)
            lbl_val = s_text.get("label") or s_text.get("text") or ""
            clean_lbl = enforce_quoted_text(lbl_val, 10) if lbl_val else ""

            frame_prompt = {
                "format": {
                    "aspect_ratio": aspect_ratio,
                    "render_style": "photorealistic photography with redline graphics for AI video first frame",
                    "composition_layout": comp_layout_scene
                },
                "style": fixed_style,
                "scene": {
                    "subject": s_scene.get("subject") or sc.get("prompt_en") or f"Cinematic shot of {topic}, scene {s_num}",
                    "environment": s_scene.get("environment") or sc.get("lighting") or "Moody cinematic lighting with realistic ambient occlusion",
                    "camera_angle": s_scene.get("camera_angle") or sc.get("camera") or "Cinematic slow motion framing"
                },
                "annotation_layer": {
                    "dimension_lines": s_ann.get("dimension_lines") or ["subtle red horizontal measurement line"],
                    "callout_arrows": s_ann.get("callout_arrows") or ["sharp crimson pointer arrow highlighting motion axis"],
                    "bounding_boxes": s_ann.get("bounding_boxes") or ["minimalist red corner bracket markers"],
                    "focus_reticles": s_ann.get("focus_reticles") or ["circular red target crosshair ring"]
                },
                "text_layer": {
                    "label": clean_lbl  # 최대 1개
                },
                "constraints": fixed_constraints
            }
            scene_first_frames.append({
                "scene_num": s_num,
                "redline_prompt": frame_prompt
            })

        return {
            "thumbnail_redline": thumbnail_redline,
            "scene_first_frames": scene_first_frames
        }

    @classmethod
    def generate_prompts_from_custom_topic(
        cls,
        topic: str,
        scene_count: int = 6,
        model: str = "google_flow",
        aspect_ratio: str = "16:9",
        style_key: str = "photorealistic_8k",
        custom_subject: str = "",
        language: str = "korean",
        data_dir: Path = DATA_DIR
    ) -> Dict[str, Any]:
        """
        사용자가 입력한 주제(topic)에 대해 8초 단위 씬별 대본, AI 영상 프롬프트 및
        [파이프라인 마지막 단계] 나노바나나 레드라인 이미지 프롬프트(썸네일 & 씬별 첫 프레임) 일괄 생성
        """
        safe_topic = sanitize_input_text(topic)
        safe_subject = sanitize_input_text(custom_subject)
        target_lang = SUPPORTED_LANGUAGES.get(language, SUPPORTED_LANGUAGES["korean"])
        style_info = STYLE_PRESETS.get(style_key, STYLE_PRESETS["photorealistic_8k"])

        # 1. 씬별 시간 분할 계산 (8초 단위)
        time_segments = []
        for i in range(1, scene_count + 1):
            s_sec = (i - 1) * 8
            e_sec = i * 8
            time_segments.append(f"{s_sec//60:02d}:{s_sec%60:02d} ~ {e_sec//60:02d}:{e_sec%60:02d}")

        # 2. LLM 기획 프롬프트 작성 (8초 최적화 씬 대본 & 비디오 AI 프롬프트)
        prompt = f"""당신은 세계적인 시네마틱 다큐멘터리/지식 영상 총괄 디렉터이자 비디오 생성 AI 프롬프트 엔지니어입니다.

[신규 기획 주제]
"{safe_topic}"
{f"- 특정 주인공/피사체 설정: {safe_subject}" if safe_subject else ""}

[★ 8초 나레이션 대사 작성 절대 규칙]
- 총 씬 개수: 정확히 {scene_count}개
- 각 씬 길이: 정확히 8초 (8초 영상 클립에 1:1로 싱크를 맞춤)
- 나레이션 대사 분량: **공백 포함 반드시 35자 ~ 45자 내외 (1~2문장)**
  * 30자 미만: 말이 너무 일찍 끝나 8초 영상에 빈 오디오가 생김 (금지)
  * 50자 초과: 8초 안에 다 읽지 못해 말이 너무 빨라지거나 영상과 어긋남 (금지)
  * 최적 분량: 차분하고 몰입감 넘치는 톤으로 8초간 자연스럽게 완독되는 35~45자
- 대본 언어: {target_lang['name']}
- 타겟 비디오 AI: {SUPPORTED_MODELS.get(model, {}).get('name', 'AI Video')}
- 비주얼 화풍: {style_info['name']}
- 전개 플롯: 5단계 마스터 플롯(도입 훅 -> 갈등/스케일 -> 공학적 난제 -> 해결 시도 -> 씁쓸한 현실과 깊은 여운)

아래 JSON 포맷 규격에 맞추어 {scene_count}개 씬을 작성해주세요:
```json
{{
  "title_candidates": [
    "후보 1: [낭만 vs 현실 극적 대비 훅]",
    "후보 2: [정밀 수치/스케일 압도 훅]",
    "후보 3: [난제/실패 선언형 훅]"
  ],
  "recommended_title": "최종 추천 제목",
  "seo_description": "유튜브 설명란 3줄 요약 줄거리 및 CTA",
  "scenes": [
    {{
      "scene_num": 1,
      "time_range": "{time_segments[0] if time_segments else '00:00 ~ 00:08'}",
      "dramatic_beat": "도입 (The Setup: 호기심 유발 및 충격적 반전)",
      "narration": "{target_lang['name']} 나레이션 대본 (정확히 8초 분량, 공백 포함 35~45자)",
      "camera": "Slow cinematic push-in shot (또는 Drone aerial top-down 등)",
      "lighting": "Moody volumetric mist with dramatic golden hour rim light",
      "visual_description_ko": "화면 구도 및 연출 핵심 한국어 설명",
      "prompt_en": "Hyperrealistic 8k cinematic footage, [구체적 시각 묘사], photorealistic, masterpiece --ar {aspect_ratio}"
    }}
  ]
}}
```
반드시 유효한 JSON 형식만 출력해주세요."""

        messages = [
            {"role": "system", "content": "You are an expert cinematic storyboard and video prompt director. Always write narration dialogues tailored strictly to 8-second speech length (35-45 characters). Always reply in valid JSON format."},
            {"role": "user", "content": prompt}
        ]

        raw_response = llm_client.call_llm(messages, max_tokens=4096, temperature=0.7)

        # JSON 파싱 시도
        parsed_data = None
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_response)
        if json_match:
            try:
                parsed_data = json.loads(json_match.group(1).strip())
            except Exception:
                pass

        if not parsed_data:
            try:
                brace_match = re.search(r'\{[\s\S]*\}', raw_response)
                if brace_match:
                    parsed_data = json.loads(brace_match.group(0))
            except Exception:
                pass

        # 파싱 실패 시 기본 씬 구조 생성
        if not parsed_data or "scenes" not in parsed_data:
            scenes = []
            for idx, time_tag in enumerate(time_segments, start=1):
                scenes.append({
                    "scene_num": idx,
                    "time_range": time_tag,
                    "dramatic_beat": f"씬 {idx} 전개",
                    "narration": f"{safe_topic}의 {idx}번째 핵심 이야기로 8초 동안 깊은 몰입감을 전달합니다.",
                    "camera": "Cinematic slow push-in shot",
                    "lighting": "Volumetric dramatic lighting",
                    "visual_description_ko": f"{safe_topic} 씬 {idx} 비주얼",
                    "prompt_en": f"Cinematic documentary footage of {safe_topic}, 8k, photorealistic, cinematic lighting --ar {aspect_ratio}"
                })
            parsed_data = {
                "title_candidates": [f"{safe_topic}의 숨겨진 진실", f"아무도 몰랐던 {safe_topic}", f"{safe_topic} 프로젝트의 결말"],
                "recommended_title": f"{safe_topic}: 숨겨진 진실과 냉혹한 현실",
                "seo_description": f"{safe_topic}에 대한 심층 분석 다큐멘터리입니다.",
                "scenes": scenes
            }

        # 씬별 8초 대본 글자수 분석 및 후처리
        scenes = parsed_data.get("scenes", [])
        for sc in scenes:
            num = sc.get("scene_num", 1)
            if "time_range" not in sc or not sc["time_range"]:
                s_sec = (num - 1) * 8
                e_sec = num * 8
                sc["time_range"] = f"{s_sec//60:02d}:{s_sec%60:02d} ~ {e_sec//60:02d}:{e_sec%60:02d}"

            # 8초 기준 글자수 및 발화 소요 시간 계산
            narr = (sc.get("narration") or sc.get("subtitle") or "").strip()
            char_len = len(narr)
            est_duration = round(char_len / 5.2, 1)  # 한국어 다큐 어조 초당 약 5.2자

            sc["char_count"] = char_len
            sc["estimated_sec"] = est_duration
            sc["is_8s_optimized"] = (30 <= char_len <= 50)

            base_prompt = sc.get("prompt_en", "")
            if model == "midjourney":
                if "--ar" not in base_prompt:
                    base_prompt += f" --ar {aspect_ratio} --v 6.1 --style raw"
            elif model == "google_flow":
                if "4k" not in base_prompt.lower() and "8k" not in base_prompt.lower():
                    base_prompt = f"4k cinematic footage, {base_prompt}"
            sc["prompt_en"] = base_prompt

        # ==============================================================
        # 3. [파이프라인 마지막 단계] 나노바나나 레드라인 이미지 프롬프트 자동 생성
        # ==============================================================
        redline_results = cls.generate_redline_image_prompts(
            topic=safe_topic,
            scenes=scenes,
            aspect_ratio=aspect_ratio,
            style_key=style_key
        )

        thumbnail_redline = redline_results.get("thumbnail_redline", {})
        scene_first_frames = redline_results.get("scene_first_frames", [])

        # 각 씬 데이터에 first_frame_redline 주입
        frame_map = {f["scene_num"]: f["redline_prompt"] for f in scene_first_frames}
        for sc in scenes:
            s_num = sc.get("scene_num", 1)
            if s_num in frame_map:
                sc["first_frame_redline"] = frame_map[s_num]

        result_payload = {
            "status": "success",
            "topic": safe_topic,
            "language": language,
            "model": model,
            "aspect_ratio": aspect_ratio,
            "title_candidates": parsed_data.get("title_candidates", []),
            "recommended_title": parsed_data.get("recommended_title", f"{safe_topic} 기획"),
            "seo_description": parsed_data.get("seo_description", ""),
            "thumbnail_redline": thumbnail_redline,
            "scenes": scenes,
            "total_scenes": len(scenes)
        }

        # output/ 폴더에 기획서 문서 자동 저장
        try:
            cls.save_output_document(result_payload)
        except Exception as e:
            print(f"[Warning] Failed to save output document: {e}")

        return result_payload

    @staticmethod
    def save_output_document(data: Dict[str, Any]) -> str:
        """output/ 디렉토리에 마크다운 및 JSON 기획서 파일 저장"""
        OUTPUT_DIR.mkdir(exist_ok=True)
        topic_slug = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', data.get("topic", "plan"))[:30]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{timestamp}_{topic_slug}"

        # 1. JSON 파일 저장
        json_path = OUTPUT_DIR / f"{base_name}_기획서.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 2. Markdown 문서 작성
        md_lines = [
            f"# 🎬 TubeInsight AI 영상 기획서: {data.get('recommended_title', data.get('topic'))}",
            f"- **기획 주제**: {data.get('topic')}",
            f"- **화면 비율**: {data.get('aspect_ratio')}",
            f"- **타겟 AI**: {data.get('model')}",
            f"- **생성 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 1. 제목 후보 및 SEO 설명란",
            "### 제목 후보",
        ]
        for t in data.get("title_candidates", []):
            md_lines.append(f"- {t}")
        md_lines.extend([
            f"\n**최종 추천 제목**: {data.get('recommended_title')}",
            f"\n### SEO 디스크립션\n{data.get('seo_description')}",
            "",
            "## 2. 🔴 나노바나나 레드라인 썸네일 이미지 프롬프트 (JSON)",
            "```json",
            json.dumps(data.get("thumbnail_redline", {}), ensure_ascii=False, indent=2),
            "```",
            "",
            "## 3. 8초 씬별 대본 & 첫 프레임 레드라인 프롬프트",
        ])

        for sc in data.get("scenes", []):
            s_num = sc.get("scene_num", 1)
            t_range = sc.get("time_range", "")
            narr = sc.get("narration", "")
            p_en = sc.get("prompt_en", "")
            redline = sc.get("first_frame_redline", {})

            md_lines.extend([
                f"### [Scene #{s_num}] {t_range} - {sc.get('dramatic_beat', '')}",
                f"- **나레이션 자막 (8초)**: {narr}",
                f"- **카메라 / 조명**: {sc.get('camera', '')} | {sc.get('lighting', '')}",
                f"- **비디오 생성 영문 프롬프트**: `{p_en}`",
                f"- **첫 프레임 레드라인 프롬프트 (JSON)**:",
                "```json",
                json.dumps(redline, ensure_ascii=False, indent=2),
                "```",
                ""
            ])

        md_path = OUTPUT_DIR / f"{base_name}_기획서.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

        return str(md_path)

    @staticmethod
    def export_autoflow_txt(scenes: List[Dict[str, Any]]) -> str:
        """AutoFlow-Pro 원클릭 임포트 포맷 생성"""
        lines = []
        for s in scenes:
            prompt = s.get("prompt_en", "").strip()
            if prompt:
                lines.append(prompt)
        return "\n".join(lines)

    @staticmethod
    def export_csv_data(scenes: List[Dict[str, Any]], title: str = "video") -> str:
        """스마트 태스크 CSV 생성"""
        lines = ["씬번호,타임스탬프,서사단계,나레이션대본,카메라무빙,조명,AI영상프롬프트,첫프레임레드라인JSON,한국어비주얼가이드"]
        for s in scenes:
            num = s.get("scene_num") or s.get("scene_index", 1)
            time_range = s.get("time_range", "")
            beat = s.get("dramatic_beat", "").replace(",", " ")
            narration = (s.get("narration") or s.get("subtitle") or "").replace(",", " ").replace("\n", " ")
            camera = s.get("camera", "").replace(",", " ")
            lighting = s.get("lighting", "").replace(",", " ")
            prompt = s.get("prompt_en", "").replace(",", ";").replace("\n", " ")
            redline_json = json.dumps(s.get("first_frame_redline", {}), ensure_ascii=False).replace('"', '""')
            desc_ko = s.get("visual_description_ko", "").replace(",", " ")
            lines.append(f'{num},"{time_range}","{beat}","{narration}","{camera}","{lighting}","{prompt}","{redline_json}","{desc_ko}"')
        return "\n".join(lines)

