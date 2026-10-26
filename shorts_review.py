"""쇼츠 품질 검수 — U-1 렌더 전 스토리보드 린트 (작업계획서_영상생성_업그레이드 6장 U-1).

비용 0, 수 ms. job.json 의 storyboard·captions 만 보고 지적(P0/P1/P2)과 슬라이드쇼 위험 점수를 낸다.
빌드를 막지는 않는다 — 위험 점수 4.0 이상이면 API 가 한 번 더 확인을 받는다(결정 ⑦).

근거(코드 복사 없음, 수치·규칙만 재작성):
- HyperFrames (Apache-2.0) skills/hyperframes/references/story.md §6·§8, review.md, captions.md:
  읽기 시간 0.3초/단어 + 0.5초·마지막 줄 2초, 3초 넘게 변화 없음, 빈 첫 프레임, 0초 자막, 화면 문구가 대사 반복
- OpenMontage (AGPL-3.0, 규칙만 참고) lib/slideshow_risk.py·variation_checker.py:
  타이포 과의존 비율, 반복, 위험 점수 판정 구간(2.0/3.0/4.0)
이 모듈은 shorts_engine 을 import 하지 않는다(순환 방지). 화면 수치는 remotion/src/ShortsScene.tsx 기준.
"""

import os
import re
import subprocess
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional

import shorts_captions

# 글자 중심 씬(타이포 과의존 계산 대상)과 화면이 계속 움직이는 씬
TEXT_KINDS = ("text_card", "stat_card", "bar_chart", "compare", "seal", "map")
MOVING_KINDS = ("image", "flyover", "scene3d")

# 읽기 시간 (HF story.md §6: 0.3초/단어 + 0.5초, 마지막 줄 2초 이상). 한국어는 어절을 단어로 본다
READ_BASE_SECONDS = 0.5
READ_PER_WORD_SECONDS = 0.3
LAST_LINE_MIN_SECONDS = 2.0
DEAD_STRETCH_SECONDS = 3.0
CAPTION_ZERO_MS = 100
SCREEN_VOICE_RATIO = 0.8
SCREEN_VOICE_MIN_CHARS = 8
DEFAULT_TRANSITION = "fade"         # ShortsScene presentationFor 의 기본값

# 등장 애니메이션이 끝나는 시각(초). ShortsScene.tsx 의 spring·countUp 프레임 수 / 30fps
_FPS = 30.0


def _anim_end_seconds(scene: dict) -> float:
    kind = scene.get("kind") or "image"
    if kind == "text_card":
        return (8 + 18) / _FPS                      # 부제 spring 8프레임 지연 + 18
    if kind == "stat_card":
        return (6 + 40) / _FPS                      # countUp delay 6 + dur 40
    if kind == "bar_chart":
        n = max(1, len(scene.get("bars") or []))
        return (6 + (n - 1) * 10 + 40) / _FPS
    if kind == "compare":
        n = max(1, len(scene.get("rows") or []))
        return (6 + (n - 1) * 14 + 40) / _FPS
    if kind == "seal":
        n = len(_seal_chars(scene.get("hanzi")))
        return (SEAL_STAMP_FRAMES + n * SEAL_CHAR_FRAMES + 12) / _FPS   # 인장 → 글자 한 자씩 → 번역 페이드
    if kind == "map":
        n = len(scene.get("arrows") or [])
        return (10 + n * 14 + 30) / _FPS                                  # 지도 → 나라 강조 → 화살표
    return 0.0


# 원문 인장(seal) — remotion/src/SealScene.tsx 의 등장 프레임 수와 맞춘다
SEAL_STAMP_FRAMES = 14
SEAL_CHAR_FRAMES = 4
SEAL_MAX_CHARS = 12                 # 문장부호 제외. 넘치면 인장 글자가 작아져 폰에서 읽히지 않는다
SEAL_CHARS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "remotion", "public", "fonts", "NotoSerifTC-Seal.chars.txt")
_seal_font_chars: Optional[set] = None


def _seal_chars(hanzi: Optional[str]) -> List[str]:
    """인장에 찍히는 글자(문장부호·공백 제외)."""
    return [c for c in str(hanzi or "") if re.match(r"\w", c)]


def _seal_font_charset() -> Optional[set]:
    global _seal_font_chars
    if _seal_font_chars is None and os.path.exists(SEAL_CHARS_FILE):
        with open(SEAL_CHARS_FILE, encoding="utf-8") as f:
            _seal_font_chars = set(f.read())
    return _seal_font_chars


def _seal_findings(scenes: List[dict]) -> List[dict]:
    """원문 인장 검사 — 렌더 전 린트와 렌더 후 리뷰가 함께 쓴다(P0 면 발행 잠금)."""
    out: List[dict] = []
    starts = _scene_starts(scenes)
    charset = _seal_font_charset()
    for i, s in enumerate(scenes):
        if (s.get("kind") or "image") != "seal":
            continue
        num = int(s.get("scene_num") or i + 1)
        if not str(s.get("source") or "").strip():
            out.append(_finding("P0", "seal_no_source", f"씬 {num} 원문 인장에 출전이 없습니다.",
                                "구절 DB 에서 찾은 출전(예: Shiji, ch. 85)을 source 에 넣으세요 — 출전 없는 인용은 발행하지 않습니다.",
                                scene=num, t=starts[i]))
        chars = _seal_chars(s.get("hanzi"))
        if charset is None:
            out.append(_finding("P1", "seal_glyph_unchecked", f"씬 {num} 인장 글꼴 글자 목록이 없어 글자 검사를 못 했습니다.",
                                "scripts/build_seal_font.py 로 글꼴을 다시 만드세요.", scene=num, t=starts[i]))
        else:
            missing = "".join(dict.fromkeys(c for c in chars if c not in charset))
            if missing:
                out.append(_finding("P0", "seal_missing_glyph", f"씬 {num} 인장 글꼴에 없는 글자: {missing}",
                                    "다른 구절을 고르거나 scripts/build_seal_font.py 로 글꼴을 다시 만드세요.", scene=num, t=starts[i]))
        if len(chars) > SEAL_MAX_CHARS:
            out.append(_finding("P1", "seal_too_long", f"씬 {num} 인장 원문이 {len(chars)}자입니다(권장 {SEAL_MAX_CHARS}자 이하).",
                                "핵심 구절만 남기세요 — 나머지는 번역·자막으로.", scene=num, t=starts[i]))
    return out


# Shiji Files v3 고정 틀(2026-10-27 사용자 지시 — 이후 시리즈도 바꾸지 않는다). format_version 3 잡에만 적용한다.
V3_SCENES = 6
V3_SEAL_INDEX = 3       # 4씬 = 원문 인장
V3_INSIGHT_INDEX = 4    # 5씬 = 원문 근거가 있는 통찰
_QUESTION_END = re.compile(r"\?[\s\"'”’)]*$")


def _shiji_v3_findings(job: dict) -> List[dict]:
    """v3 틀 위반은 모두 P0 — 렌더 전 린트와 렌더 후 리뷰가 함께 써서 발행을 잠근다."""
    if job.get("format_version") != 3:
        return []
    scenes = (job.get("storyboard") or {}).get("scenes") or []
    fix = "v3 틀: 콜드 오픈 · 배경 · 결정적 한 수 · 원문 인장 · 원문 근거 통찰 · 질문 (6씬, 순서 고정)"
    out: List[dict] = []
    if len(scenes) != V3_SCENES:
        out.append(_finding("P0", "v3_scene_count", f"v3 틀은 6씬인데 {len(scenes)}씬입니다.", fix))
        return out
    if (scenes[V3_SEAL_INDEX].get("kind") or "image") != "seal":
        out.append(_finding("P0", "v3_seal_position", "4번째 씬이 원문 인장(seal)이 아닙니다.", fix, scene=V3_SEAL_INDEX + 1))
    ins = scenes[V3_INSIGHT_INDEX]
    if not str(ins.get("grounding") or "").strip() or not str(ins.get("grounding_source") or "").strip():
        out.append(_finding("P0", "v3_insight_grounding", "5번째 씬(통찰)에 원문 근거(grounding)와 출전(grounding_source)이 없습니다.",
                            "통찰은 원문 한 줄에서 꺼낸다 — 근거 원문과 출전을 적으세요. 근거가 없으면 그 통찰은 쓰지 않습니다.",
                            scene=V3_INSIGHT_INDEX + 1))
    if not _QUESTION_END.search(str(scenes[-1].get("narration") or "").strip()):
        out.append(_finding("P0", "v3_question", "마지막 씬이 시청자에게 묻는 질문(물음표)으로 끝나지 않습니다.", fix, scene=V3_SCENES))
    return out


# 넘치면 글자가 잘리는 길이(최소 글자 크기에서 한 줄에 들어가는 한글 수 × 줄 수, 폭 894px 기준 근사)
# ShortsScene 은 글자를 34px 아래로 줄이지 않으므로(HF text_below_floor 28px 는 구조상 걸리지 않음) 넘침을 대신 본다
END_TAG_ENTER_SECONDS = 10 / _FPS  # 엔드 태그 페이드인 10프레임 — 그동안은 읽을 수 없다 (HF check 가 Remotion 결과에서 잡은 것)
HOOK_MAX_CHARS = 30                 # 훅 배너: 최소 48px · 2줄
CARD_TITLE_MAX_CHARS = 42           # text_card 제목: 최소 56px · 3줄

# 상투어 (OM variation_checker GENERIC_PHRASES · HF story.md 금지어를 한국어로)
GENERIC_PHRASES = (
    "혁신적", "획기적", "놀라운", "놀랍게도", "엄청난", "믿을 수 없는", "게임체인저", "게임 체인저",
    "완벽한", "완벽하게", "단 몇 초 만에", "몇 초 만에", "차원이 다른", "최첨단", "역대급", "충격적인",
    "판도를 바꿀", "판도를 바꾸는", "미쳤다",
)

LEVEL_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def _words(text: Optional[str]) -> int:
    """어절 수. '·' '→' 같은 기호만 있는 토큰은 세지 않는다."""
    return len([w for w in str(text or "").split() if re.search(r"\w", w)])


def _norm(text: Optional[str]) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


def _finding(level: str, code: str, message: str, fix: str, scene: Optional[int] = None, t: Optional[float] = None) -> dict:
    return {"level": level, "code": code, "scene": scene, "t": (round(t, 1) if t is not None else None),
            "message": message, "fix": fix}


def _screen_texts(scene: dict) -> List[str]:
    """씬 안에서 시청자가 읽어야 하는 문구(자막 제외)."""
    kind = scene.get("kind") or "image"
    out = [scene.get("title"), scene.get("subtitle")]
    if kind == "stat_card":
        out.append(scene.get("label"))
    elif kind == "bar_chart":
        out += [b.get("label") for b in scene.get("bars") or [] if isinstance(b, dict)]
    elif kind == "compare":
        out += [r.get("label") for r in scene.get("rows") or [] if isinstance(r, dict)]
    elif kind == "seal":
        out = [scene.get("translation"), scene.get("source")]   # 한자 원문은 읽기 대상이 아니라 그림으로 본다
    elif kind == "map":
        out = [scene.get("title"), scene.get("year")]
    elif kind == "image":
        out = []                    # 이미지 씬은 화면 문구 없이 자막만 쓴다
    return [str(x).strip() for x in out if x and str(x).strip()]


def _scene_starts(scenes: List[dict]) -> List[float]:
    starts, t = [], 0.0
    for s in scenes:
        starts.append(t)
        t += float(s.get("seconds") or 0)
    return starts


def _caption_pages(job: dict) -> List[tuple]:
    """화면에 실제로 뜨는 자막 그룹 (start_ms, hide_ms) — 렌더러와 같은 shorts_captions 규칙(U-3)."""
    groups = shorts_captions.caption_groups(job.get("captions") or [], job.get("caption_energy") or shorts_captions.DEFAULT_ENERGY)
    return [(g["startMs"], g["hideMs"]) for g in groups]


def _change_events(scene: dict, start: float, pages: List[tuple], word_starts: Optional[List[int]] = None) -> Optional[List[float]]:
    """씬 구간 안에서 화면이 바뀌는 시각(초). 자막 그룹이 뜨고 지는 것, 강조 어절이 옮겨 가는 것도 변화로 친다.

    나레이션은 있는데 이 씬에 자막이 아직 없으면(빌드 전) None — 빌드가 씬 길이를 실제 발화 길이로 다시 맞추므로 판단하지 않는다.
    """
    end = start + float(scene.get("seconds") or 0)
    page_events = [x for ps, pe in pages for x in (ps / 1000.0, pe / 1000.0) if start <= x <= end]
    page_events += [ms / 1000.0 for ms in (word_starts or []) if start <= ms / 1000.0 <= end]
    if not page_events and _norm(scene.get("narration")):
        return None
    events = [start, start + _anim_end_seconds(scene)] + page_events
    return sorted(e for e in events if start <= e <= end)


def _lint_findings(job: dict) -> List[dict]:
    sb = job.get("storyboard") or {}
    scenes = sb.get("scenes") or []
    hook = (sb.get("hook_text") or "").strip()
    hook_seconds = float(sb.get("hook_seconds") or 3.0)
    end_tag = sb.get("end_tag") or {}
    captions = job.get("captions") or []
    pages = _caption_pages(job)
    word_starts = [int(c["startMs"]) for c in captions if isinstance(c.get("startMs"), (int, float))]
    starts = _scene_starts(scenes)
    out: List[dict] = []

    # first_frame_empty — 첫 프레임은 쇼츠 피드의 썸네일이다
    first_kind = (scenes[0].get("kind") or "image") if scenes else None
    if not hook and first_kind not in MOVING_KINDS:
        out.append(_finding("P0", "first_frame_empty", "첫 화면에 훅 문구도 움직이는 비주얼도 없습니다 (피드 썸네일이 빈 배경).",
                            "훅 문구(3~5어절)를 넣거나 1번 씬을 이미지·3D 씬으로 바꾸세요.", scene=1, t=0.0))

    # line_unread — 훅·카드 문구·엔드 태그
    if hook:
        need = READ_BASE_SECONDS + READ_PER_WORD_SECONDS * _words(hook)
        if hook_seconds < need:
            out.append(_finding("P0", "line_unread", f"훅 \"{hook}\" 노출 {hook_seconds:.1f}초 < 읽는 데 필요한 {need:.1f}초.",
                                f"훅을 {max(2, int((hook_seconds - READ_BASE_SECONDS) / READ_PER_WORD_SECONDS))}어절 이하로 줄이세요.", scene=1, t=0.0))
        if len(hook) > HOOK_MAX_CHARS:
            out.append(_finding("P1", "text_overflow", f"훅이 {len(hook)}자로 배너 두 줄({HOOK_MAX_CHARS}자)을 넘습니다.",
                                "훅을 짧게 줄이세요.", scene=1, t=0.0))
    for i, s in enumerate(scenes):
        num = int(s.get("scene_num") or i + 1)
        texts = _screen_texts(s)
        if texts:
            visible = float(s.get("seconds") or 0) - _anim_end_seconds(s)
            need = READ_BASE_SECONDS + READ_PER_WORD_SECONDS * sum(_words(x) for x in texts)
            if visible < need:
                out.append(_finding("P0", "line_unread", f"씬 {num} 화면 문구({sum(_words(x) for x in texts)}어절)를 읽을 시간 {visible:.1f}초 < 필요 {need:.1f}초.",
                                    "문구를 줄이거나 씬을 늘리세요.", scene=num, t=starts[i]))
        if (s.get("kind") or "image") == "text_card" and len(str(s.get("title") or "")) > CARD_TITLE_MAX_CHARS:
            out.append(_finding("P1", "text_overflow", f"씬 {num} 카드 제목이 {len(s.get('title'))}자로 세 줄({CARD_TITLE_MAX_CHARS}자)을 넘습니다.",
                                "제목을 줄이고 나머지는 부제로 옮기세요.", scene=num, t=starts[i]))
    tag_text = (end_tag.get("text") or "").strip()
    if tag_text:
        tag_seconds = float(end_tag.get("seconds") or 0)
        visible = tag_seconds - END_TAG_ENTER_SECONDS
        # 부제(출처·채널명)는 작은 보조 줄이라 읽기 시간에 넣지 않는다
        need = max(LAST_LINE_MIN_SECONDS, READ_BASE_SECONDS + READ_PER_WORD_SECONDS * _words(tag_text))
        if visible < need:
            out.append(_finding("P0", "line_unread", f"엔드 태그가 읽히는 시간 {visible:.1f}초(등장 {END_TAG_ENTER_SECONDS:.2f}초 제외) < 필요 {need:.1f}초 (마지막 줄은 2초 이상).",
                                f"엔드 태그를 {need + END_TAG_ENTER_SECONDS:.1f}초 이상으로 늘리세요.", t=sum(float(s.get('seconds') or 0) for s in scenes)))

    # dead_stretch — 화면이 3초 넘게 그대로인 구간 (카드형 씬만; 켄번즈·3D 는 계속 움직인다)
    for i, s in enumerate(scenes):
        if (s.get("kind") or "image") in MOVING_KINDS:
            continue
        num = int(s.get("scene_num") or i + 1)
        end = starts[i] + float(s.get("seconds") or 0)
        ev = _change_events(s, starts[i], pages, word_starts)
        if ev is None:
            continue
        ev = ev + [end]
        gap, at = 0.0, starts[i]
        for a, b in zip(ev, ev[1:]):
            if b - a > gap:
                gap, at = b - a, a
        if gap > DEAD_STRETCH_SECONDS:
            out.append(_finding("P1", "dead_stretch", f"씬 {num} 에서 {gap:.1f}초 동안 화면이 바뀌지 않습니다.",
                                "씬을 줄이거나 나레이션을 채우거나, 움직이는 씬(이미지·3D)으로 바꾸세요.", scene=num, t=at))

    # typography_overreliance
    if scenes:
        n_text = sum(1 for s in scenes if (s.get("kind") or "image") in TEXT_KINDS)
        ratio = n_text / len(scenes)
        if ratio >= 1.0:
            out.append(_finding("P0", "typography_overreliance", f"씬 {len(scenes)}개가 모두 글자 카드입니다 — 움직이는 슬라이드처럼 보입니다.",
                                "최소 1~2개 씬을 이미지·flyover·scene3d 로 바꾸세요."))
        elif ratio > 0.6:
            out.append(_finding("P1", "typography_overreliance", f"글자 카드 씬 비율 {n_text}/{len(scenes)} ({ratio:.0%}) > 60%.",
                                "글자 카드 하나를 이미지·3D 씬으로 바꾸세요."))

    # repetition — 같은 종류 3연속, 같은 전환 반복, 팔레트 전부 같음
    run_kind, run_len, run_start = None, 0, 0
    for i, s in enumerate(scenes + [{"kind": None}]):
        k = s.get("kind") or ("image" if i < len(scenes) else None)
        if k == run_kind:
            run_len += 1
        else:
            if run_kind and run_len >= 3:
                out.append(_finding("P1", "repetition", f"씬 {run_start + 1}~{run_start + run_len} 이 연속 {run_len}번 {run_kind} 입니다.",
                                    "가운데 씬을 다른 종류로 바꾸세요.", scene=run_start + 1, t=starts[run_start]))
            run_kind, run_len, run_start = k, 1, i
    seams = [(s.get("transition") or DEFAULT_TRANSITION) for s in scenes[1:]]
    if len(seams) >= 2 and len(set(seams)) == 1:
        out.append(_finding("P1", "repetition", f"이음새 {len(seams)}개가 모두 같은 전환({seams[0]}) 입니다.",
                            "전환을 2종 이상 섞으세요 (U-3 자동 배정 예정)."))
    else:
        for j in range(1, len(seams)):
            if seams[j] == seams[j - 1] and seams[j] != "none":
                out.append(_finding("P1", "repetition", f"씬 {j + 1}→{j + 2} 전환이 바로 앞과 같습니다({seams[j]}).",
                                    "앞뒤 전환을 다르게 하세요.", scene=j + 2, t=starts[j + 1]))
    palettes = [s.get("palette") for s in scenes if (s.get("kind") or "image") not in ("image",)]
    if len(palettes) >= 3 and len(set(map(str, palettes))) == 1:
        out.append(_finding("P1", "repetition", f"카드 씬 {len(palettes)}개가 모두 같은 팔레트입니다.", "팔레트를 씬마다 바꾸세요."))

    # screen_repeats_voice — 화면 문구가 대사를 그대로 반복
    for i, s in enumerate(scenes):
        num = int(s.get("scene_num") or i + 1)
        narration = s.get("narration") or ""
        sentences = [x for x in re.split(r"(?<=[.?!。])\s+", narration) if x.strip()]
        for txt in [s.get("title"), s.get("subtitle")]:
            nt = _norm(txt)
            if len(nt) < SCREEN_VOICE_MIN_CHARS:
                continue
            same = nt in _norm(narration) or any(SequenceMatcher(None, nt, _norm(x)).ratio() >= SCREEN_VOICE_RATIO for x in sentences)
            if same:
                out.append(_finding("P1", "screen_repeats_voice", f"씬 {num} 화면 문구 \"{txt}\" 가 나레이션을 그대로 반복합니다.",
                                    "화면에는 숫자·핵심어만, 설명은 목소리로 나누세요.", scene=num, t=starts[i]))
                break

    # generic_phrase — 상투어
    sources = [("훅", hook, 1, 0.0)] + [(f"씬 {int(s.get('scene_num') or i + 1)}", " ".join(str(s.get(k) or "") for k in ("title", "subtitle", "narration")),
                                        int(s.get("scene_num") or i + 1), starts[i]) for i, s in enumerate(scenes)]
    sources.append(("엔드 태그", f"{tag_text} {end_tag.get('subtext') or ''}", None, None))
    for where, text, num, t in sources:
        hits = [p for p in GENERIC_PHRASES if p in str(text)]
        if hits:
            out.append(_finding("P2", "generic_phrase", f"{where} 에 상투어: {', '.join(hits)}.",
                                "구체적인 숫자·사실로 바꾸세요.", scene=num, t=t))

    # caption_at_zero — 렌더러가 첫 그룹을 CAPTION_MIN_START_MS 뒤로 미루므로 화면 기준으로 본다
    if pages:
        first_ms = pages[0][0]
        if first_ms is not None and first_ms < CAPTION_ZERO_MS:
            out.append(_finding("P2", "caption_at_zero", f"첫 자막이 {first_ms}ms 에 바로 뜹니다 (원래 있던 글자처럼 보임).",
                                "첫 자막을 0.1~0.3초 뒤에 시작하세요 (U-3).", scene=1, t=first_ms / 1000.0))
    out += _seal_findings(scenes)
    out += _shiji_v3_findings(job)
    return out


def risk_score(job: dict) -> dict:
    """슬라이드쇼 위험 점수 — 4축 0~5점 평균 (OM slideshow_risk 판정 구간: <2 strong, <3 acceptable, <4 revise, ≥4 fail)."""
    sb = job.get("storyboard") or {}
    scenes = sb.get("scenes") or []
    n = len(scenes) or 1
    kinds = [(s.get("kind") or "image") for s in scenes]

    rep, reasons = 0.0, []
    if kinds:
        top = max(kinds.count(k) for k in set(kinds))
        if top / n > 0.7:
            rep += 2.0
            reasons.append(f"같은 종류가 {top}/{n}")
        if any(kinds[i] == kinds[i + 1] == kinds[i + 2] for i in range(len(kinds) - 2)):
            rep += 1.5
            reasons.append("같은 종류 3연속")
    seams = [(s.get("transition") or DEFAULT_TRANSITION) for s in scenes[1:]]
    if len(seams) >= 2 and len(set(seams)) == 1:
        rep += 1.5
        reasons.append(f"전환 전부 {seams[0]}")
    repetition = {"score": min(5.0, rep), "reason": ", ".join(reasons) or "반복 적음"}

    ratio = sum(1 for k in kinds if k in TEXT_KINDS) / n
    t_score = 5.0 if ratio >= 1.0 else 4.0 if ratio > 0.6 else 2.5 if ratio > 0.4 else 1.0 if ratio > 0.2 else 0.0
    typography = {"score": t_score, "reason": f"글자 카드 {ratio:.0%}"}

    moving = sum(1 for k in kinds if k in MOVING_KINDS) / n
    motion = {"score": round(5.0 * (1.0 - moving) * 0.8, 1), "reason": f"움직이는 씬 {moving:.0%}"}

    hook = (sb.get("hook_text") or "").strip()
    w = _words(hook)
    if not hook:
        h = (5.0, "훅 없음")
    elif w < 2 or w > 5:
        h = (2.5, f"훅 {w}어절 (권장 3~5)")
    elif hook.endswith("?") or re.search(r"\d", hook):
        h = (0.0, "질문·숫자 훅")
    else:
        h = (1.0, "평서문 훅")
    hook_axis = {"score": h[0], "reason": h[1]}

    axes = {"repetition": repetition, "typography": typography, "motion": motion, "hook": hook_axis}
    score = round(sum(a["score"] for a in axes.values()) / len(axes), 2)
    verdict = "strong" if score < 2.0 else "acceptable" if score < 3.0 else "revise" if score < 4.0 else "fail"
    return {"score": score, "verdict": verdict, "axes": axes}


def lint_storyboard(job: dict) -> dict:
    """job → {"findings", "counts", "risk", "needs_confirm", "at"}. 지적은 P0 → P2, 시각 순."""
    findings = _lint_findings(job)
    findings.sort(key=lambda f: (LEVEL_ORDER[f["level"]], f["t"] if f["t"] is not None else 1e9))
    counts = {lv: sum(1 for f in findings if f["level"] == lv) for lv in ("P0", "P1", "P2")}
    risk = risk_score(job)
    return {"version": 1, "at": time.time(), "findings": findings, "counts": counts, "risk": risk,
            "needs_confirm": risk["verdict"] == "fail"}


# ── U-4 렌더 후 리뷰 (작업계획서_영상생성_업그레이드 6장 U-4) ─────────────────────────
# 근거: HyperFrames skills/hyperframes/references/review.md (Apache-2.0) — 씬 시작·중간 시트, 이음새 ±0.2초 시트, 폰 폭(360px) 시트,
# "점수는 매기지 않는다", P0/P1/P2 지적. OpenMontage lib/delivery_promise.py(규칙만) — 약속을 조용히 낮추지 말고 멈춰서 묻기.
# ffmpeg 만 쓴다(비용 0). 비전 모델 리뷰는 결정 ② 에 따라 하지 않는다 — 시트는 사람이 본다.

REVIEW_FPS = 30.0
SHEET_TILE_WIDTH = 270            # 씬·이음새 시트 한 칸 폭(4칸 = 1080)
PHONE_TILE_WIDTH = 360            # 폰 폭 시트 한 칸 폭 (HF review: 360px 에서 읽혀야 한다)
SEAM_PROBE_BEFORE = 0.3           # 이음새 앞뒤로 프레임을 몇 초 뽑아 튐을 잴지
SEAM_PROBE_AFTER = 0.5
SEAM_JUMP_LEVEL = 40.0            # 이웃 프레임 평균 밝기 차(0~255)가 이보다 크고
SEAM_JUMP_SHARE = 0.35            # 그 한 프레임이 전환 구간 전체 변화량의 이 비율 이상이면 "전환 중 튐"
                                  # (색 범람처럼 크게 바뀌어도 여러 프레임에 퍼지면 정상 — Argon 실측: 정상 0.12~0.17, 튐 0.42)
BLACK_FRAME_LEVEL = 12.0          # 시트 프레임 평균 밝기가 이보다 낮으면 검은 화면
CUT_TRANSITIONS = ("none", "dip")  # 원래 한 프레임에 바뀌는 전환(튐 검사 제외)
PROMISE_DEFAULT = {"scene": "data_explainer", "music": "music"}


def review_timeline(job: dict) -> dict:
    """씬 시작·끝, 이음새(씬 2부터의 시작), 엔드 태그 구간(초)."""
    sb = job.get("storyboard") or {}
    scenes = sb.get("scenes") or []
    starts = _scene_starts(scenes)
    ends = [s + float(sc.get("seconds") or 0) for s, sc in zip(starts, scenes)]
    tag = float((sb.get("end_tag") or {}).get("seconds") or 0)
    total = (ends[-1] if ends else 0.0) + tag
    seams = [{"t": starts[i], "scene": int(scenes[i].get("scene_num") or i + 1),
              "transition": scenes[i].get("transition") or "fade"} for i in range(1, len(scenes))]
    return {"starts": starts, "ends": ends, "seams": seams, "end_tag": (ends[-1], total) if (ends and tag > 0) else None, "total": total}


def _frame_index(t: float, total: float) -> int:
    return max(0, min(int(round(t * REVIEW_FPS)), int(total * REVIEW_FPS) - 1))


def make_contact_sheet(ff: str, video: str, times: List[float], out: str, tile_width: int, cols: int, total: float,
                       runner=subprocess.run) -> Optional[str]:
    """times 의 프레임을 한 번 디코딩으로 골라 cols 칸 격자 JPG 로. 실패하면 None."""
    idx = sorted({_frame_index(t, total) for t in times})
    if not ff or not idx or not os.path.exists(video):
        return None
    rows = (len(idx) + cols - 1) // cols
    expr = "+".join(f"eq(n\\,{i})" for i in idx)
    vf = f"select='{expr}',scale={tile_width}:-2,tile={cols}x{rows}:padding=4:color=0x111111"
    try:
        res = runner([ff, "-y", "-v", "error", "-i", video, "-vf", vf, "-frames:v", "1", "-vsync", "0", "-q:v", "4", out],
                     capture_output=True, text=True, timeout=180)
        return out if getattr(res, "returncode", 1) == 0 and os.path.exists(out) else None
    except Exception:
        return None


def frame_levels(ff: str, video: str, frames: List[int], runner=subprocess.run) -> Dict[int, float]:
    """프레임 번호 → 평균 밝기(0~255), 54×96 그레이로 한 번 디코딩."""
    frames = sorted(set(frames))
    if not ff or not frames or not os.path.exists(video):
        return {}
    expr = "+".join(f"eq(n\\,{i})" for i in frames)
    try:
        res = runner([ff, "-v", "error", "-i", video, "-vf", f"select='{expr}',scale=54:96,format=gray", "-vsync", "0",
                      "-f", "rawvideo", "-"], capture_output=True, timeout=180)
    except Exception:
        return {}
    data = getattr(res, "stdout", b"") or b""
    size = 54 * 96
    out = {}
    for k, f in enumerate(frames):
        chunk = data[k * size:(k + 1) * size]
        if len(chunk) == size:
            out[f] = sum(chunk) / float(size)
    return out


def frame_diffs(ff: str, video: str, start_frame: int, count: int, runner=subprocess.run) -> List[float]:
    """start_frame 부터 count 장의 이웃 프레임 평균 절대 차(54×96 그레이). 전환 튐 검사용."""
    if not ff or count < 2 or not os.path.exists(video):
        return []
    try:
        res = runner([ff, "-v", "error", "-i", video, "-vf",
                      f"select='between(n\\,{start_frame}\\,{start_frame + count - 1})',scale=54:96,format=gray",
                      "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True, timeout=180)
    except Exception:
        return []
    data = getattr(res, "stdout", b"") or b""
    size = 54 * 96
    frames = [data[i * size:(i + 1) * size] for i in range(len(data) // size)]
    return [sum(abs(a - b) for a, b in zip(f1, f2)) / float(size) for f1, f2 in zip(frames, frames[1:])]


def promise_of(job: dict) -> str:
    return job.get("promise") or PROMISE_DEFAULT.get(job.get("format") or "scene", "data_explainer")


def _promise_findings(job: dict) -> List[dict]:
    """렌더러 폴백·씬 대체가 제작 약속을 낮췄으면 P0 (OM delivery_promise: 조용히 낮추지 말 것)."""
    render = job.get("render") or {}
    out = []
    if render.get("renderer_used") == "ffmpeg":
        why = render.get("fallback_reason") or "ffmpeg 렌더러 선택"
        replaced = [w for w in render.get("warnings") or [] if "단색" in w or "생략" in w]
        out.append(_finding("P0", "promise_downgraded",
                            f"약속({promise_of(job)})보다 낮은 렌더: Remotion 대신 ffmpeg ({why})." + (f" {' '.join(replaced)}" if replaced else ""),
                            "Remotion 렌더가 되는 상태에서 다시 빌드하세요(폰트·노드 의존성 확인)."))
    return out


def review_render(job: dict, ff: Optional[str], out_dir: str, url_prefix: str, runner=subprocess.run) -> dict:
    """렌더 결과(job.render.file) → 시트 3장 + 지적. 반환값을 job["review"] 에 넣는 것은 호출부."""
    t0 = time.time()
    video = (job.get("render") or {}).get("file")
    tl = review_timeline(job)
    total = tl["total"]
    scenes_all = (job.get("storyboard") or {}).get("scenes") or []
    findings = _promise_findings(job) + _seal_findings(scenes_all) + _shiji_v3_findings(job)
    # 로컬 AI 이미지(ComfyUI)는 가짜 한자·글자가 섞일 수 있다 — 원문을 내세우는 채널이라 사람이 시트에서 확인한다(발행은 막지 않음)
    comfy = [int(s.get("scene_num") or i + 1) for i, s in enumerate(scenes_all)
             if (s.get("kind") or "image") == "image" and s.get("image_source") == "comfyui"]
    if comfy:
        findings.append(_finding("P2", "image_text_check", f"AI 이미지 씬 {', '.join(map(str, comfy))} 에 가짜 글자·한자가 없는지 확인하세요.",
                                 "글자가 보이면 그 씬 이미지를 다시 만드세요(씬 번호만 지우고 재빌드)."))
    sheets: Dict[str, Optional[str]] = {"scenes": None, "seams": None, "phone": None}
    times: Dict[str, List[float]] = {"scenes": [], "seams": [], "phone": []}
    if video and os.path.exists(video) and ff:
        os.makedirs(out_dir, exist_ok=True)
        for s, e in zip(tl["starts"], tl["ends"]):
            times["scenes"] += [min(s + 0.3, e), (s + e) / 2]
        for seam in tl["seams"]:
            times["seams"] += [max(0.0, seam["t"] - 0.2), seam["t"] + 0.2]
        times["phone"] = [(s + e) / 2 for s, e in zip(tl["starts"], tl["ends"])]
        if tl["end_tag"]:
            times["phone"].append(sum(tl["end_tag"]) / 2)
        specs = {"scenes": (SHEET_TILE_WIDTH, 4), "seams": (SHEET_TILE_WIDTH, 4), "phone": (PHONE_TILE_WIDTH, 3)}
        for key, (w, cols) in specs.items():
            if times[key]:
                name = f"review_{key}.jpg"
                if make_contact_sheet(ff, video, times[key], os.path.join(out_dir, name), w, cols, total, runner=runner):
                    sheets[key] = f"{url_prefix}/{name}"
        # 검은 화면: 씬 시트 프레임(시작+0.3초·중간) 중 평균 밝기가 매우 낮은 것
        idx = {_frame_index(t, total): t for t in times["scenes"]}
        for f, level in sorted(frame_levels(ff, video, list(idx), runner=runner).items()):
            if level < BLACK_FRAME_LEVEL:
                findings.append(_finding("P1", "black_frame", f"t={idx[f]:.1f}s 화면이 거의 검습니다(평균 밝기 {level:.0f}).",
                                         "씬 소재가 비었거나 등장 애니메이션이 늦습니다 — 해당 씬을 확인하세요.", t=idx[f]))
        # 전환 중 튐: 이웃 프레임 차가 한 번에 크게 뛰는 곳(원래 컷인 전환은 제외)
        for seam in tl["seams"]:
            if seam["transition"] in CUT_TRANSITIONS:
                continue
            f0 = _frame_index(seam["t"] - SEAM_PROBE_BEFORE, total)
            diffs = frame_diffs(ff, video, f0, int((SEAM_PROBE_BEFORE + SEAM_PROBE_AFTER) * REVIEW_FPS) + 1, runner=runner)
            if len(diffs) >= 3:
                peak = max(diffs)
                if peak > SEAM_JUMP_LEVEL and peak >= SEAM_JUMP_SHARE * sum(diffs):
                    at = seam["t"] - SEAM_PROBE_BEFORE + (diffs.index(peak) + 1) / REVIEW_FPS
                    findings.append(_finding("P1", "seam_jump",
                                             f"씬 {seam['scene']} 로 넘어가는 {seam['transition']} 전환 중 화면이 한 프레임에 튑니다(차 {peak:.0f}).",
                                             "전환 길이를 늘리거나 다른 전환으로 바꾸세요.", scene=seam["scene"], t=at))
    elif not ff:
        findings.append(_finding("P2", "review_skipped", "ffmpeg 가 없어 시트를 만들지 못했습니다.", "ffmpeg 를 설치하세요."))
    findings.sort(key=lambda f: (LEVEL_ORDER[f["level"]], f["t"] if f["t"] is not None else 1e9))
    counts = {lv: sum(1 for f in findings if f["level"] == lv) for lv in ("P0", "P1", "P2")}
    return {"version": 1, "at": time.time(), "elapsed_sec": round(time.time() - t0, 2), "sheets": sheets, "times": times,
            "findings": findings, "counts": counts, "promise": promise_of(job), "needs_review": counts["P0"] > 0, "override": None}
