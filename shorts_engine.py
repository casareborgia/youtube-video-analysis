"""쇼츠(9:16) 엔진 — S-1: Remotion `ShortsScene` 렌더 래퍼 + ffmpeg 폴백 + 프로브
                  S-2: 씬 기획서 → 잡, 이미지(Gemini, 편당·일일 상한), 나레이션(edge-tts 단어 타이밍) + BGM, 음량 보정, QC, 빌드 오케스트레이션.

작업계획서_쇼츠_자동화_Shorts_Reels.md 7장 S-1·S-2 범위. 발행(S-3)은 아직 없다.

설계 원칙 (choonsik_bga.render_bga 와 동일):
- 기본 렌더러는 Remotion(SHORTS_RENDERER=remotion), 미설치·실패 시 ffmpeg 로 자동 폴백하고 사유를 기록한다.
- Remotion 은 remotion/public/shorts → data/shorts 심볼릭 링크로만 파일을 읽으므로 잡 폴더 밖의 자산은 안으로 복사한다.
- 출력은 항상 data/shorts/<shorts_id>/final_9x16.mp4 이며, 기존 파일을 덮어쓰기 전에 백업하지 않는다(쇼츠는 재생성 비용이 낮다).
"""

import asyncio
import datetime
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

import concept_packs
import producer  # ffmpeg_path(drawtext 지원 바이너리 우선), audio_duration, find_font, generate_images, list_media
import scene3d_spec
import scene_store
import shorts_captions
import shorts_review
import tts_service

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHORTS_DIR = os.path.join(BASE_DIR, "data", "shorts")
REMOTION_DIR = os.path.join(BASE_DIR, "remotion")
REMOTION_PUBLIC_PREFIX = "shorts"  # remotion/public/shorts -> ../../data/shorts
COMPOSITION_ID = "ShortsScene"

FPS = 30
WIDTH, HEIGHT = 1080, 1920
MAX_SECONDS = 60.0            # 유튜브 쇼츠 판정 상한(파이프라인 상한)
FINAL_NAME = "final_9x16.mp4"

# 작업계획서 5.1 — OpenMontage media_profiles 규격을 재작성(코드 복사 아님)
PLATFORM_PROFILES = {
    "youtube_shorts": {"width": 1080, "height": 1920, "fps": 30, "crf": 20, "max_seconds": 60, "max_mb": None},
    "instagram_reels": {"width": 1080, "height": 1920, "fps": 30, "crf": 20, "max_seconds": 90, "max_mb": 250},
}
# 작업계획서 5.2 — 공통 안전 영역 900×1400 중앙
SAFE_ZONE = {"top": 120, "bottom": 300, "left": 90, "right": 96}

# 씬 종류 — image 외에는 이미지 생성 비용 없이 Remotion 이 그린다 (작업계획서 비용 절감안 ①)
SCENE_KINDS = ("image", "text_card", "stat_card", "bar_chart", "compare", "flyover", "scene3d", "seal", "map")
SCENE_KIND_FIELDS = ("palette", "title", "subtitle", "value", "unit", "prefix", "decimals", "label", "bars", "rows", "time_of_day", "seed",
                     "scene3d", "hanzi", "translation", "source", "states", "arrows", "year")
# seal(원문 인장): hanzi 원문 + translation 자체 번역 + source 출전 — 출전이 없으면 린트 P0(가짜 명언 금지, 파일럿 계획 P-3)
SEAL_TRANSLATION_MAX = 120
SEAL_SOURCE_MAX = 40
# map(전국시대 개략도): remotion/src/warringStatesMap.ts 의 나라 id 와 같은 목록
MAP_STATES = ("qin", "chu", "qi", "yan", "zhao", "wei", "han")
MAP_DEFAULT_YEAR = "c. 260 BC"
FLYOVER_TIMES = ("sunrise", "day", "sunset")   # flyover(3D 항공) 씬의 하늘 시간대
SCENE_TRANSITIONS = ("fade", "slide", "wipe", "zoom_through", "color_flood", "whip", "dip", "none")   # 씬으로 들어오는 전환 (Remotion, ffmpeg 폴백은 무시)
# U-3 자동 배정 (HF motion.md: 원인 있는 전환 3~5종, 같은 전환 연속 금지, 하드컷은 이음새의 1/3 이하 — 자동 배정은 하드컷을 쓰지 않는다)
AUTO_TRANSITION_ROTATION = ("slide", "whip", "wipe", "fade")
FALLBACK_PALETTE = ("0x1b2a4a", "0x3a1f4f", "0x0f3d3e", "0x4a2a1b", "0x1f3f2a", "0x2b1b4a")

DEFAULT_ACCENT = "#ffd166"
DEFAULT_BGM_VOLUME = 0.16          # BGM 배율 상한 (조용한 곡이어도 이보다 키우지 않는다)
BGM_UNDER_NARRATION_LU = 22.0      # 2026-10-25 사용자 결정: 대사가 들려야 하므로 BGM 은 나레이션보다 22 LU 아래
BGM_FALLBACK_VOLUME = 0.035        # 음량을 못 잴 때: 루나 곡(약 -12 LUFS)·edge-tts(약 -20 LUFS) 기준 22 LU 근사
DEFAULT_TRANSITION = 0.4
DEFAULT_END_TAG_SECONDS = 2.4      # 마지막 줄은 페이드인(10프레임)을 빼고 2초 이상 보여야 한다 (U-1 line_unread, HF story.md §6)

_ID_RE = re.compile(r"^[A-Za-z0-9_\-가-힣]{3,80}$")
_FILTER_CACHE = {}


# ── 잡 저장소 ────────────────────────────────────────────────────────────────

def _safe_id(shorts_id: str) -> str:
    if not shorts_id or not _ID_RE.match(str(shorts_id)) or ".." in str(shorts_id):
        raise ValueError(f"유효하지 않은 쇼츠 ID: {shorts_id!r}")
    return str(shorts_id)


def job_dir(shorts_id: str, create: bool = False) -> str:
    d = os.path.join(SHORTS_DIR, _safe_id(shorts_id))
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def save_job(job: dict) -> str:
    d = job_dir(job["shorts_id"], create=True)
    job["updated_at"] = time.time()
    path = os.path.join(d, "job.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load_job(shorts_id: str) -> Optional[dict]:
    path = os.path.join(job_dir(shorts_id), "job.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 렌더러 선택 ──────────────────────────────────────────────────────────────

def remotion_available() -> bool:
    return os.path.isdir(os.path.join(REMOTION_DIR, "node_modules"))


def default_renderer() -> str:
    """SHORTS_RENDERER 환경변수. 기본 remotion (쇼츠는 훅·자막 타이포가 핵심이라 BGA 와 달리 Remotion 이 기본)."""
    r = os.getenv("SHORTS_RENDERER", "remotion").strip().lower()
    return "ffmpeg" if r == "ffmpeg" else "remotion"


def total_seconds(job: dict) -> float:
    sb = job.get("storyboard") or {}
    scenes = sb.get("scenes") or []
    total = sum(float(s.get("seconds") or 0) for s in scenes)
    tag = sb.get("end_tag") or {}
    return round(total + float(tag.get("seconds") or 0), 3)


# ── 자막 유틸 ────────────────────────────────────────────────────────────────

def proportional_captions(text: str, start_ms: int, end_ms: int, page_break_at_end: bool = True) -> List[dict]:
    """단어 타임스탬프가 없는 음성(Qwen 등)용 — 어절 글자 수에 비례해 [start_ms, end_ms] 를 나눈다.

    @remotion/captions 규약: 새 어절은 text 앞에 공백 하나. 문장(씬) 끝에는 pageBreakAfter 로 페이지를 끊는다.
    """
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    if not words or end_ms <= start_ms:
        return []
    weights = [max(1, len(w)) for w in words]
    total_w = float(sum(weights))
    span = end_ms - start_ms
    out, cursor = [], float(start_ms)
    for i, (w, wt) in enumerate(zip(words, weights)):
        dur = span * (wt / total_w)
        s, e = int(round(cursor)), int(round(cursor + dur))
        if i == len(words) - 1:
            e = int(end_ms)
        tok = {"text": (" " if i > 0 else "") + w, "startMs": s, "endMs": max(s + 1, e)}
        out.append(tok)
        cursor += dur
    if page_break_at_end:
        out[-1]["pageBreakAfter"] = True
    return out


def _srt_time(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def captions_to_srt(captions: List[dict], path: str, page_ms: int = 1200) -> str:
    """ffmpeg 폴백용 SRT. 틱톡식 페이지 규칙(page_ms 안에서 묶고 pageBreakAfter 에서 끊음)을 단순 재현."""
    cues, cur = [], None
    for c in captions or []:
        if cur is not None and (c["startMs"] - cur["start"] > page_ms):
            cues.append(cur)
            cur = None
        if cur is None:
            cur = {"start": c["startMs"], "end": c["endMs"], "text": c["text"].strip()}
        else:
            cur["end"] = c["endMs"]
            cur["text"] = (cur["text"] + " " + c["text"].strip()).strip()
        if c.get("pageBreakAfter"):
            cues.append(cur)
            cur = None
    if cur is not None:
        cues.append(cur)
    lines = []
    for i, q in enumerate(cues, 1):
        lines += [str(i), f"{_srt_time(q['start'])} --> {_srt_time(q['end'])}", q["text"], ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ── Remotion 렌더 ────────────────────────────────────────────────────────────

def _ensure_in_job_dir(shorts_id: str, path: str, prefix: str) -> str:
    """Remotion 은 public/shorts/<id>/ 아래만 읽을 수 있으므로 잡 폴더 밖 파일은 복사해 들여온다. 반환: public 기준 상대 경로."""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"파일이 없습니다: {path}")
    d = job_dir(shorts_id, create=True)
    ap = os.path.abspath(path)
    if os.path.dirname(ap) != os.path.abspath(d):
        dest = os.path.join(d, f"{prefix}_{os.path.basename(ap)}")
        if not os.path.exists(dest) or os.path.getmtime(dest) < os.path.getmtime(ap):
            shutil.copy(ap, dest)
        ap = dest
    return f"{REMOTION_PUBLIC_PREFIX}/{shorts_id}/{os.path.basename(ap)}"


def _scene3d_assets(shorts_id: str, spec: Optional[dict], index: int, job: dict) -> dict:
    """scene3d 의 3D 모델 파일(model.src)을 잡 폴더로 들여와 public 경로로 바꾼다. 파일이 없으면 그 물체만 빼고 경고를 남긴다."""
    spec = dict(spec or scene3d_spec.normalize_scene3d(None, index))
    objects = []
    for o in spec.get("objects") or []:
        if o.get("type") == "model":
            try:
                o = dict(o, src=_ensure_in_job_dir(shorts_id, o.get("src"), f"scene_{index:02d}_model"))
            except FileNotFoundError:
                job.setdefault("warnings", []).append(f"씬 {index} 3D 모델 파일이 없어 뺐습니다: {o.get('src')}")
                continue
        objects.append(o)
    spec["objects"] = objects
    return spec


def build_remotion_props(job: dict) -> dict:
    shorts_id = _safe_id(job["shorts_id"])
    sb = job.get("storyboard") or {}
    scenes_in = sb.get("scenes") or []
    if not scenes_in:
        raise RuntimeError("스토리보드에 씬이 없습니다.")
    scenes = []
    for i, s in enumerate(scenes_in, 1):
        kind = (s.get("kind") or "image").strip().lower()
        if kind not in SCENE_KINDS:
            raise RuntimeError(f"씬 {s.get('scene_num', i)} 의 kind 가 올바르지 않습니다: {kind}")
        item = {
            "kind": kind,
            "seconds": float(s.get("seconds") or 0),
            "motion": s.get("motion") or ("zoom_in" if i % 2 == 1 else "zoom_out"),
        }
        if s.get("transition") in SCENE_TRANSITIONS:
            item["transition"] = s["transition"]
        if kind == "image":
            img = s.get("image")
            if not img:
                raise RuntimeError(f"씬 {s.get('scene_num', i)} 에 이미지가 없습니다.")
            item["image"] = _ensure_in_job_dir(shorts_id, img, f"scene_{i:02d}")
        else:
            # 비용 0 씬: 이미지 없이 타이포·데이터 비주얼. 종류별 필드만 그대로 전달한다.
            for k in SCENE_KIND_FIELDS:
                if s.get(k) is not None:
                    item[k] = s[k]
            if kind == "scene3d":
                item["scene3d"] = _scene3d_assets(shorts_id, item.get("scene3d"), i, job)
        scenes.append(item)
    audio = job.get("audio") or {}
    narration = audio.get("narration")
    bgm = audio.get("bgm")
    tag = sb.get("end_tag") or None
    props = {
        "jobId": shorts_id,
        "scenes": scenes,
        "hookText": sb.get("hook_text") or "",
        "hookSeconds": float(sb.get("hook_seconds") or 3.0),
        "endTag": ({"text": tag.get("text", ""), "subtext": tag.get("subtext", ""), "seconds": float(tag.get("seconds") or DEFAULT_END_TAG_SECONDS)} if tag else None),
        # U-3: 그룹 경계(문장 끝·쉼·어절 상한)에 pageBreakAfter, 씬 강조어 토큰에 emphasis
        "captions": [
            {k: v for k, v in c.items() if k in ("text", "startMs", "endMs", "pageBreakAfter", "emphasis")}
            for c in shorts_captions.mark_emphasis(
                shorts_captions.group_captions(job.get("captions") or [], job.get("caption_energy") or shorts_captions.DEFAULT_ENERGY),
                scenes_in)
        ],
        "captionPageMs": shorts_captions.GROUPED_PAGE_MS,
        "captionHoldMs": shorts_captions.CAPTION_HOLD_MS,
        "captionMinStartMs": shorts_captions.CAPTION_MIN_START_MS,
        "narrationAudio": _ensure_in_job_dir(shorts_id, narration, "narration") if narration else None,
        "bgmAudio": _ensure_in_job_dir(shorts_id, bgm, "bgm") if bgm else None,
        "bgmVolume": float(audio.get("bgm_volume") if audio.get("bgm_volume") is not None else DEFAULT_BGM_VOLUME),
        "bgmBoost": float(audio.get("bgm_duck_boost") or BGM_DUCK_BOOST),
        "accent": job.get("accent") or DEFAULT_ACCENT,
        "brand": job.get("brand") or "",
        "transitionSeconds": float(job.get("transition_seconds") or DEFAULT_TRANSITION),
        "sfx": bool(job.get("sfx")),
    }
    return props


def render_shorts_remotion(job: dict, progress_cb: Optional[Callable] = None, timeout: int = 900, runner=subprocess.run) -> dict:
    def step(pct, msg):
        if progress_cb:
            progress_cb("shorts_render", msg, pct)
        print(f"[{pct}%] [ShortsRemotion] {msg}")

    if not remotion_available():
        raise RuntimeError("Remotion 미설치: cd remotion && npm ci")
    shorts_id = _safe_id(job["shorts_id"])
    total = total_seconds(job)
    if total <= 0:
        raise RuntimeError("쇼츠 길이가 0초입니다.")
    if total > MAX_SECONDS:
        raise RuntimeError(f"쇼츠 길이 {total:.1f}초가 상한 {MAX_SECONDS:.0f}초를 넘습니다. 씬 길이를 줄이세요.")

    props = build_remotion_props(job)
    d = job_dir(shorts_id, create=True)
    props_path = os.path.join(d, "remotion_props.json")
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False, indent=2)
    out_file = os.path.join(d, FINAL_NAME)

    step(10, f"Remotion 렌더 시작 ({total:.1f}초, {COMPOSITION_ID})...")
    cmd = [
        "npx", "remotion", "render", "src/index.ts", COMPOSITION_ID, out_file,
        "--props", props_path, "--log", "error",
    ]
    t0 = time.time()
    proc = runner(cmd, cwd=REMOTION_DIR, timeout=timeout, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-400:]
        raise RuntimeError(f"Remotion 렌더 실패: {err}")
    if not os.path.exists(out_file):
        raise RuntimeError("Remotion 렌더가 성공했다고 보고했지만 출력 파일이 없습니다.")
    elapsed = round(time.time() - t0, 2)

    job["render"] = {
        "renderer_used": "remotion",
        "file": out_file,
        "url": f"/data/shorts/{shorts_id}/{FINAL_NAME}",
        "elapsed_sec": elapsed,
        "rendered_at": time.time(),
        "props_file": props_path,
        "warnings": [],
    }
    job["status"] = "rendered"
    save_job(job)
    step(100, f"Remotion 렌더 완료 ({elapsed}초) → {out_file}")
    return job


# ── ffmpeg 폴백 렌더 ─────────────────────────────────────────────────────────

def _ffmpeg_has_filter(ff: str, name: str) -> bool:
    key = (ff, name)
    if key not in _FILTER_CACHE:
        try:
            res = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20)
            _FILTER_CACHE[key] = bool(re.search(rf"^\s*\S+\s+{re.escape(name)}\s", res.stdout or "", re.M))
        except Exception:
            _FILTER_CACHE[key] = False
    return _FILTER_CACHE[key]


def _ff_run(cmd, timeout=900, runner=subprocess.run):
    res = runner(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        tail = "\n".join((res.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(f"ffmpeg 실패:\n{tail}")
    return res


def _subtitle_font_name(font_path: Optional[str]) -> Optional[str]:
    if not font_path:
        return None
    b = os.path.basename(font_path).lower()
    if "applesdgothicneo" in b:
        return "Apple SD Gothic Neo"
    if "applegothic" in b:
        return "AppleGothic"
    if "nanumgothic" in b:
        return "NanumGothic"
    if "notosanscjk" in b:
        return "Noto Sans CJK KR"
    if "malgun" in b:
        return "Malgun Gothic"
    return None


def render_shorts_ffmpeg(job: dict, progress_cb: Optional[Callable] = None, runner=subprocess.run) -> dict:
    """Remotion 없이 ffmpeg 만으로 렌더. 켄번즈 씬 → xfade 이어붙이기 → 나레이션+BGM(덕킹) → SRT 자막(가능할 때).
    훅 문구·엔드 태그·어절 하이라이트는 생략되며 warnings 에 남긴다."""
    def step(pct, msg):
        if progress_cb:
            progress_cb("shorts_render", msg, pct)
        print(f"[{pct}%] [ShortsFFmpeg] {msg}")

    ff = producer.ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg를 찾을 수 없습니다. 'pip3 install imageio-ffmpeg'를 실행해주세요.")
    shorts_id = _safe_id(job["shorts_id"])
    sb = job.get("storyboard") or {}
    scenes = sb.get("scenes") or []
    if not scenes:
        raise RuntimeError("스토리보드에 씬이 없습니다.")
    total = total_seconds(job)
    if total > MAX_SECONDS:
        raise RuntimeError(f"쇼츠 길이 {total:.1f}초가 상한 {MAX_SECONDS:.0f}초를 넘습니다.")
    d = job_dir(shorts_id, create=True)
    work = os.path.join(d, "work_ffmpeg")
    os.makedirs(work, exist_ok=True)
    warnings = ["ffmpeg 폴백: 훅 문구·엔드 태그·어절 하이라이트는 생략됩니다."]
    fade = float(job.get("transition_seconds") or DEFAULT_TRANSITION)
    tag = sb.get("end_tag") or {}
    tag_sec = float(tag.get("seconds") or 0)

    # 1. 씬별 켄번즈 (무음)
    files, durs = [], []
    kind_scenes = [i for i, s in enumerate(scenes, 1) if (s.get("kind") or "image") != "image"]
    if kind_scenes:
        warnings.append(f"ffmpeg 폴백: 타이포·데이터 씬({', '.join(map(str, kind_scenes))})은 단색 배경으로 대체됩니다.")
    for i, s in enumerate(scenes, 1):
        img = s.get("image")
        if (s.get("kind") or "image") != "image":
            img = os.path.join(work, f"kind_bg_{i:02d}.png")
            color = FALLBACK_PALETTE[(i - 1) % len(FALLBACK_PALETTE)]
            _ff_run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={WIDTH}x{HEIGHT}:d=1",
                     "-frames:v", "1", img], runner=runner)
        if not img or not os.path.exists(img):
            raise FileNotFoundError(f"씬 {i} 이미지가 없습니다: {img}")
        # Remotion 타임라인과 같은 절대 시각을 유지한다: 마지막이 아닌 씬은 다음 씬의 페이드만큼 더 길게 만들고
        # xfade offset 을 씬 시작 시각(이전 씬 seconds 누적)에 두면 총 길이 = Σseconds + 엔드 태그가 된다.
        dur = float(s.get("seconds") or 0) + (tag_sec if i == len(scenes) else fade)
        frames = int(dur * FPS) + 1
        motion = s.get("motion") or ("zoom_in" if i % 2 == 1 else "zoom_out")
        if motion == "zoom_out":
            z = f"1.12-0.12*on/{frames}"
            x = "iw/2-(iw/zoom/2)"
        elif motion in ("pan_left", "pan_right"):
            z = "1.12"
            sign = "-" if motion == "pan_left" else "+"
            x = f"iw/2-(iw/zoom/2){sign}0.03*iw*(2*on/{frames}-1)"
        else:
            z = f"1+0.12*on/{frames}"
            x = "iw/2-(iw/zoom/2)"
        out = os.path.join(work, f"scene_{i:02d}.mp4")
        vf = (f"scale={WIDTH * 2}:-2,zoompan=z='{z}':d={frames}:x='{x}':y='ih/2-(ih/zoom/2)':s={WIDTH}x{HEIGHT}:fps={FPS},"
              f"format=yuv420p")
        step(5 + int(45 * (i - 1) / len(scenes)), f"씬 {i}/{len(scenes)} 켄번즈...")
        _ff_run([ff, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", img, "-vf", vf,
                 "-t", f"{dur:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", out],
                runner=runner)
        files.append(out)
        durs.append(dur)

    # 2. xfade 체인 + 오디오
    audio = job.get("audio") or {}
    narration = audio.get("narration")
    bgm = audio.get("bgm")
    bgm_vol = float(audio.get("bgm_volume") if audio.get("bgm_volume") is not None else DEFAULT_BGM_VOLUME)
    bgm_boost = float(audio.get("bgm_duck_boost") or BGM_DUCK_BOOST)
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    for f_ in files:
        cmd += ["-i", f_]
    n = len(files)
    a_idx = {}
    if narration and os.path.exists(narration):
        a_idx["nar"] = len(files) + len(a_idx)
        cmd += ["-i", narration]
    if bgm and os.path.exists(bgm):
        a_idx["bgm"] = len(files) + len(a_idx)
        cmd += ["-stream_loop", "-1", "-i", bgm]

    parts = []
    if n == 1:
        parts.append("[0:v]null[vcat]")
        v_total = durs[0]
    else:
        prev = "[0:v]"
        offset = 0.0
        for i in range(1, n):
            offset += durs[i - 1] - fade
            label = "[vcat]" if i == n - 1 else f"[vx{i}]"
            parts.append(f"{prev}[{i}:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}{label}")
            prev = label
        v_total = sum(durs) - fade * (n - 1)  # = Σseconds + 엔드 태그

    # 자막 (libass 지원 바이너리에서만)
    srt_path = None
    if job.get("captions"):
        srt_path = captions_to_srt(job["captions"], os.path.join(d, "captions.srt"))
    v_last = "[vcat]"
    if srt_path and _ffmpeg_has_filter(ff, "subtitles"):
        font_path = producer.find_font()
        fname = _subtitle_font_name(font_path)
        # libass 는 SRT 를 PlayRes 384×288 기준으로 그린다. MarginV=58 ≈ 1920 기준 약 390px(하단 데드존 300px 위), FontSize=17 ≈ 113px
        style = "FontSize=17,Bold=1,Outline=2,Shadow=1,Alignment=2,MarginV=58,MarginL=24,MarginR=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000"
        if fname:
            style = f"FontName={fname}," + style
        srt_esc = srt_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        parts.append(f"[vcat]subtitles='{srt_esc}':force_style='{style}'[vsub]")
        v_last = "[vsub]"
    elif srt_path:
        warnings.append("ffmpeg 에 subtitles 필터가 없어 자막을 굽지 못했습니다 (captions.srt 는 저장됨).")

    if "nar" in a_idx and "bgm" in a_idx:
        parts.append(f"[{a_idx['nar']}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad,asplit=2[nar][key]")
        parts.append(f"[{a_idx['bgm']}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={min(0.5, bgm_vol * bgm_boost):.3f}[bg]")
        parts.append("[bg][key]sidechaincompress=threshold=0.02:ratio=6:attack=60:release=600:makeup=1[ducked]")
        parts.append("[ducked][nar]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    elif "nar" in a_idx:
        parts.append(f"[{a_idx['nar']}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[a]")
    elif "bgm" in a_idx:
        parts.append(f"[{a_idx['bgm']}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={min(0.5, bgm_vol * bgm_boost):.3f}[a]")
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        parts.append(f"[{len(files)}:a]anull[a]")

    out_file = os.path.join(d, FINAL_NAME)
    cmd += ["-filter_complex", ";".join(parts), "-map", v_last, "-map", "[a]", "-t", f"{v_total:.3f}",
            "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out_file]
    step(60, "씬 이어붙이기·오디오 믹스·자막...")
    t0 = time.time()
    _ff_run(cmd, runner=runner)
    elapsed = round(time.time() - t0, 2)

    job["render"] = {
        "renderer_used": "ffmpeg",
        "file": out_file,
        "url": f"/data/shorts/{shorts_id}/{FINAL_NAME}",
        "elapsed_sec": elapsed,
        "rendered_at": time.time(),
        "warnings": warnings,
    }
    job["status"] = "rendered"
    save_job(job)
    step(100, f"ffmpeg 렌더 완료 ({elapsed}초) → {out_file}")
    return job


# ── 디스패처 ─────────────────────────────────────────────────────────────────

def render_shorts(job: dict, renderer: Optional[str] = None, progress_cb: Optional[Callable] = None) -> dict:
    """렌더러 통합 디스패처. Remotion 기본, 미설치·실패 시 ffmpeg 폴백 + fallback_reason 기록."""
    req = (renderer or default_renderer()).strip().lower()
    job["renderer_requested"] = req
    fallback_reason = None
    if req == "remotion":
        try:
            if not remotion_available():
                raise RuntimeError("Remotion 미설치")
            job = render_shorts_remotion(job, progress_cb=progress_cb)
        except Exception as e:
            if isinstance(e, ValueError) or "상한" in str(e) or "씬이 없" in str(e):
                raise  # 입력 오류는 폴백해도 똑같이 실패한다
            fallback_reason = f"{type(e).__name__}: {str(e)[:200]}"
            job = render_shorts_ffmpeg(job, progress_cb=progress_cb)
    else:
        job = render_shorts_ffmpeg(job, progress_cb=progress_cb)
    if fallback_reason:
        job["render"]["fallback_reason"] = fallback_reason
    else:
        job.get("render", {}).pop("fallback_reason", None)
    try:
        job["render"]["probe"] = probe_video(job["render"]["file"])
    except Exception as e:  # ffprobe 가 없어도 렌더 결과는 유효하다
        job["render"]["probe"] = {"error": str(e)[:200]}
    save_job(job)
    return job


# ── 프로브 ───────────────────────────────────────────────────────────────────

def probe_video(path: str) -> dict:
    """ffprobe 로 해상도·길이·fps·용량·오디오 유무. S-2 QC 의 입력."""
    ff = producer.ffmpeg_path()
    ffprobe = None
    if ff:
        cand = os.path.join(os.path.dirname(ff), "ffprobe")
        ffprobe = cand if os.path.exists(cand) else shutil.which("ffprobe")
    ffprobe = ffprobe or shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe 를 찾을 수 없습니다.")
    res = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
                         capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {(res.stderr or '')[-200:]}")
    info = json.loads(res.stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = 0.0
    try:
        num, den = (v.get("r_frame_rate") or "0/1").split("/")
        fps = round(float(num) / float(den), 3) if float(den) else 0.0
    except Exception:
        pass
    return {
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": fps,
        "duration": round(float((info.get("format") or {}).get("duration") or 0), 3),
        "size_bytes": int((info.get("format") or {}).get("size") or 0),
        "video_codec": v.get("codec_name"),
        "audio_present": a is not None,
        "audio_codec": a.get("codec_name") if a else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# S-2. 파이프라인 F1 (정보형 씬 쇼츠): 기획서 → 잡 → 이미지 → 음성/자막 → 렌더 → 음량 → QC
# ═══════════════════════════════════════════════════════════════════════════

SHORTS_USAGE_FILE = os.path.join(BASE_DIR, "data", "shorts_usage.json")   # choonsik_bga.bga_usage.json 과 같은 {날짜: 장수}
DEFAULT_MAX_IMAGES_PER_JOB = 7     # env SHORTS_MAX_IMAGES_PER_JOB
DEFAULT_MAX_IMAGES_PER_DAY = 40    # env SHORTS_MAX_IMAGES_PER_DAY (2026-10-19 사용자 결정 ④)
IMAGE_USD_PER_IMAGE = 0.039        # Gemini 2.5 Flash Image: 출력 1290토큰 × $30/M ≈ $0.039/장 (공식 요금표 기준 추정)
USD_KRW = 1400

MIN_SCENE_SECONDS = 3.0            # 60초 컷 때 씬을 이보다 짧게 줄이지 않는다
SCENE_PAD_SECONDS = 0.35           # 씬 나레이션 뒤 숨 고르기(무음). 자막·씬 시각은 이 패드를 포함한 길이로 계산
TRIM_SILENCE_DB = -40.0            # edge-tts 끝 무음 판정 기준
TRIM_KEEP_SECONDS = 0.08           # 끝 무음을 자를 때 남겨 두는 꼬리(말끝이 뚝 끊기지 않게)
# U-2 오디오 2.0 (작업계획서_영상생성_업그레이드 6장 U-2). 근거: HyperFrames sound.md·mixing.md, OpenMontage sound-design.md·audio_energy(규칙만)
VOICE_EQ_FILTER = "highpass=f=80,equalizer=f=3000:t=q:w=1:g=2.5,alimiter=limit=0.891:level=0:latency=1"  # 웅웅거림 제거·명료도 +2.5dB·피크 -1dB
BGM_CARVE_FILTER = "equalizer=f=3000:t=o:w=1:g=-3"   # BGM 에서 말소리 대역(2~4kHz)을 3dB 비워 대사가 묻히지 않게
BGM_DUCK_BOOST = 2.2               # 발화 밖 BGM 배율(발화 중 bgm_volume 의 몇 배). 2026-10-25 사용자 결정 ④: A/B(1.6·2.2·3.0) 듣고 2.2
BGM_ENTRY_DROP_LU = 6.0            # 곡의 상위 10% 단기 음량에서 이만큼 아래를 넘는 첫 지점을 "곡이 살아나는 곳"으로 본다
BGM_ENTRY_MIN_SECONDS = 1.0        # 이보다 앞이면 처음부터 튼다
DEFAULT_VOICE_ID = "edge_injoon"   # 2026-10-19 사용자 결정 ②: 기본 성우 edge-tts
SHORTS_LANGUAGES = ("korean", "english")   # 나레이션 언어 — 내 목소리(Qwen3)는 이 값으로 합성한다
TARGET_LUFS = -18.0                # 2026-10-25 사용자 결정: 대사 위주라 듣기 편한 -18 (작업계획서 5.3 의 -14 에서 변경)
TARGET_TRUE_PEAK = -1.0
LUFS_TOLERANCE = 1.0
QC_MIN_BRIGHTNESS = 12.0           # 첫 프레임 평균 밝기(0~255). 블랙 오프닝 금지
SHORTS_PROGRESS_SPAN = {"images": (0, 40), "audio": (40, 60), "render": (60, 97), "qc": (97, 100)}


# ── 일일 사용량 (data/shorts_usage.json) ─────────────────────────────────────

def per_job_cap() -> int:
    return int(os.getenv("SHORTS_MAX_IMAGES_PER_JOB", str(DEFAULT_MAX_IMAGES_PER_JOB)))


def daily_cap() -> int:
    return int(os.getenv("SHORTS_MAX_IMAGES_PER_DAY", str(DEFAULT_MAX_IMAGES_PER_DAY)))


def _read_usage_data() -> dict:
    if not os.path.exists(SHORTS_USAGE_FILE):
        return {}
    try:
        with open(SHORTS_USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_usage_data(data: dict):
    os.makedirs(os.path.dirname(SHORTS_USAGE_FILE), exist_ok=True)
    with open(SHORTS_USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today_usage() -> int:
    val = _read_usage_data().get(datetime.date.today().isoformat(), 0)
    return int(val) if isinstance(val, (int, float)) else 0


def _increment_usage(n: int = 1):
    key = datetime.date.today().isoformat()
    data = _read_usage_data()
    cur = data.get(key, 0)
    data[key] = (int(cur) if isinstance(cur, (int, float)) else 0) + int(n)
    _write_usage_data(data)


def usage_summary() -> dict:
    today = get_today_usage()
    cap = daily_cap()
    return {"today": today, "cap": cap, "remaining": max(0, cap - today), "per_job_cap": per_job_cap(),
            "usd_per_image": IMAGE_USD_PER_IMAGE}


# ── 잡 생성 (씬 기획서 9:16 → job.json, 작업계획서 5.4) ──────────────────────

def _slug(text: str, limit: int = 24) -> str:
    """_ID_RE(영숫자·_·-·한글) 안에서만 만든다. scene_store._slug 는 \\w 라 다른 문자가 섞일 수 있다."""
    s = re.sub(r"[^A-Za-z0-9가-힣]+", "_", (text or "").strip()).strip("_")
    return s[:limit].strip("_") or "shorts"


def _hook_from_title(title: str, max_words: int = 5) -> str:
    words = re.sub(r"[\[\]\(\)\"':#]", " ", title or "").split()
    return " ".join(words[:max_words])


def _scene_motion(i: int) -> str:
    return ("zoom_in", "zoom_out", "pan_left", "pan_right")[(i - 1) % 4]


def _kind_spec(spec: Optional[dict] = None) -> tuple:
    """(허용 kind 목록, 종류별 필드) — 컨셉 팩 규격 우선, 없으면 shorts_info 기본값."""
    spec = spec or concept_packs.shorts_spec("shorts_info")
    return (tuple(spec.get("scene_kinds") or ("image",)), tuple(spec.get("scene_kind_fields") or ()))


def _clip_text(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def fill_kind_defaults(scene: dict, spec: Optional[dict] = None) -> dict:
    """씬 kind 를 검증하고 종류별 필수 필드가 없으면 채우거나 text_card 로 내린다 (Remotion 이 빈 카드를 그리지 않게).

    - 모르는 kind → image
    - text_card: title 없으면 나레이션 앞 18자
    - stat_card: value 가 숫자가 아니면 text_card 로
    - bar_chart: bars 2개 미만이면 text_card 로 / compare: rows 없으면 text_card 로
    - flyover: 3D 항공 장면. time_of_day 는 sunrise|day|sunset(기본 sunset), seed 는 지형 모양(기본 씬 번호), title 은 지명 라벨(선택, ≤12자)
    - scene3d: 범용 3D 장면. scene3d 설명(환경·바닥·카메라·물체)을 scene3d_spec 으로 정리한다(없어도 기본 장면)
    - seal: 원문 인장. hanzi 가 없으면 text_card 로. source 가 비어도 바꾸지 않는다(린트가 P0 로 막는다)
    - map: 전국시대 개략도. states·arrows 는 MAP_STATES 만 남기고, year 기본 c. 260 BC
    """
    kinds, _fields = _kind_spec(spec)
    kind = str(scene.get("kind") or "image").strip().lower()
    if kind not in kinds:
        kind = "image"
    narration = scene.get("narration") or ""

    def to_text_card(reason: str):
        scene["kind"] = "text_card"
        scene.setdefault("title", _clip_text(scene.get("title") or narration, 18))
        scene.setdefault("kind_note", reason)

    if kind == "stat_card":
        try:
            scene["value"] = float(scene.get("value"))
        except (TypeError, ValueError):
            to_text_card("stat_card 에 value 가 없어 text_card 로 대체")
            return scene
        scene["kind"] = kind
        scene.setdefault("label", _clip_text(narration, 24))
    elif kind == "bar_chart":
        bars = [b for b in (scene.get("bars") or []) if isinstance(b, dict) and b.get("label") is not None and b.get("value") is not None]
        if len(bars) < 2:
            to_text_card("bar_chart 에 막대가 2개 미만이라 text_card 로 대체")
            return scene
        scene["kind"], scene["bars"] = kind, bars
        scene.setdefault("title", _clip_text(narration, 18))
    elif kind == "compare":
        rows = [r for r in (scene.get("rows") or []) if isinstance(r, dict) and r.get("label") is not None
                and r.get("from") is not None and r.get("to") is not None]
        if not rows:
            to_text_card("compare 에 전→후 행이 없어 text_card 로 대체")
            return scene
        scene["kind"], scene["rows"] = kind, rows
        scene.setdefault("title", _clip_text(narration, 18))
    elif kind == "text_card":
        scene["kind"] = kind
        if not (scene.get("title") or "").strip():
            scene["title"] = _clip_text(narration, 18)
    elif kind == "scene3d":
        scene["kind"] = kind
        scene["scene3d"] = scene3d_spec.normalize_scene3d(scene.get("scene3d"), int(scene.get("scene_num") or 1))
    elif kind == "seal":
        hanzi = re.sub(r"\s+", "", str(scene.get("hanzi") or ""))
        if not hanzi:
            to_text_card("seal 에 원문(hanzi)이 없어 text_card 로 대체")
            return scene
        scene["kind"], scene["hanzi"] = kind, hanzi
        scene["translation"] = _clip_text(scene.get("translation") or "", SEAL_TRANSLATION_MAX)
        scene["source"] = _clip_text(scene.get("source") or "", SEAL_SOURCE_MAX)
    elif kind == "map":
        scene["kind"] = kind
        states = [str(x).strip().lower() for x in (scene.get("states") or [])]
        scene["states"] = [x for x in states if x in MAP_STATES]
        scene["arrows"] = [{"from": a["from"], "to": a["to"]} for a in (scene.get("arrows") or [])
                           if isinstance(a, dict) and a.get("from") in MAP_STATES and a.get("to") in MAP_STATES
                           and a.get("from") != a.get("to")]
        scene["year"] = _clip_text(scene.get("year") or MAP_DEFAULT_YEAR, 16)
        if (scene.get("title") or "").strip():
            scene["title"] = _clip_text(scene["title"], 24)
    elif kind == "flyover":
        scene["kind"] = kind
        if scene.get("time_of_day") not in FLYOVER_TIMES:
            scene["time_of_day"] = "sunset"
        try:
            scene["seed"] = int(scene.get("seed"))
        except (TypeError, ValueError):
            scene["seed"] = int(scene.get("scene_num") or 1)
        if (scene.get("title") or "").strip():
            scene["title"] = _clip_text(scene["title"], 12)
    else:
        scene["kind"] = "image"
    return scene


def _is_image_scene(scene: dict) -> bool:
    return (scene.get("kind") or "image") == "image"


def list_jobs() -> List[dict]:
    out = []
    if not os.path.isdir(SHORTS_DIR):
        return out
    for name in os.listdir(SHORTS_DIR):
        path = os.path.join(SHORTS_DIR, name, "job.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                j = json.load(f)
        except Exception:
            continue
        out.append(job_summary(j))
    out.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return out


def job_summary(job: dict) -> dict:
    sb = job.get("storyboard") or {}
    render = job.get("render") or {}
    qc = job.get("qc") or {}
    return {
        "shorts_id": job.get("shorts_id"),
        "status": job.get("status"),
        "format": job.get("format"),
        "title": ((job.get("metadata") or {}).get("youtube") or {}).get("title") or job.get("topic") or "",
        "topic": job.get("topic", ""),
        "plan_id": (job.get("source") or {}).get("plan_id"),
        "platforms": job.get("platforms") or [],
        "scene_count": len(sb.get("scenes") or []),
        "total_seconds": total_seconds(job),
        "caption_source": job.get("caption_source"),
        "renderer_used": render.get("renderer_used"),
        "video_url": render.get("url"),
        "qc_passed": qc.get("passed"),
        "progress": job.get("progress"),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def delete_job(shorts_id: str) -> bool:
    d = job_dir(shorts_id)
    if not os.path.isdir(d):
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def _resolve_scene_images(job: dict, plan: Optional[dict] = None) -> int:
    """기획서의 미디어 인덱스(producer.list_media)에 있는 씬 이미지를 잡 씬에 연결한다. 반환: 이미지가 있는 씬 수."""
    plan_id = (job.get("source") or {}).get("plan_id")
    if not plan_id:
        return 0
    try:
        idx = producer.list_media(plan_id)
        d = producer.render_dir(plan_id)
    except Exception:
        return 0
    found = 0
    for sc in (job.get("storyboard") or {}).get("scenes") or []:
        if not _is_image_scene(sc):
            continue   # 비용 0 씬(text_card 등)은 이미지가 필요 없다
        if sc.get("image") and os.path.exists(sc["image"]):
            found += 1
            continue
        item = idx.get(str(sc.get("scene_num")))
        if not item:
            continue
        fname = item.get("image_file") if item.get("type") == "video" else item.get("file")
        if fname and os.path.exists(os.path.join(d, fname)):
            sc["image"] = os.path.join(d, fname)
            found += 1
    return found


def fit_to_max_seconds(job: dict, max_seconds: float = MAX_SECONDS, min_scene: float = MIN_SCENE_SECONDS) -> List[str]:
    """씬 길이 합(+엔드 태그)이 상한을 넘으면 마지막 씬부터 줄인다(씬당 min_scene 까지). 그래도 넘으면 뒤 씬을 뺀다. 반환: 경고 목록."""
    sb = job.setdefault("storyboard", {})
    scenes = sb.get("scenes") or []
    warnings: List[str] = []
    excess = round(total_seconds(job) - max_seconds, 3)
    if excess <= 0:
        return warnings
    warnings.append(f"씬 길이 합 {total_seconds(job):.1f}초가 상한 {max_seconds:.0f}초를 넘어 마지막 씬부터 줄였습니다.")
    for sc in reversed(scenes):
        room = float(sc.get("seconds") or 0) - min_scene
        if room <= 0:
            continue
        cut = min(room, excess)
        before = float(sc.get("seconds") or 0)
        sc["seconds"] = round(before - cut, 2)
        excess = round(excess - cut, 3)
        warnings.append(f"씬 {sc.get('scene_num')}: {before:.1f}초 → {sc['seconds']:.1f}초")
        if excess <= 0:
            break
    while excess > 0 and len(scenes) > 1:
        dropped = scenes.pop()
        excess = round(excess - float(dropped.get("seconds") or 0), 3)
        warnings.append(f"씬 {dropped.get('scene_num')} 제거 (상한 초과)")
    job.setdefault("warnings", []).extend(warnings)
    return warnings


def assign_transitions(job: dict) -> List[str]:
    """사용자가 정하지 않은 이음새에 전환을 자동 배정한다(transition_auto=True). 반환: 이음새별 전환.

    - 같은 종류 씬이 이어지면 바뀐 것을 알리는 color_flood·dip
    - 이미지·3D(움직이는) 씬으로 들어갈 때는 zoom_through
    - 나머지는 slide → whip → wipe → fade 순환
    - 바로 앞 이음새와 같은 전환은 피하고, 이음새가 3개 이상이면 3종 이상이 되게 한다
    """
    scenes = (job.get("storyboard") or {}).get("scenes") or []
    seams: List[str] = []
    rot = 0
    for i in range(1, len(scenes)):
        cur, prev = scenes[i], scenes[i - 1]
        if cur.get("transition") in SCENE_TRANSITIONS and not cur.get("transition_auto"):
            seams.append(cur["transition"])
            continue
        last = seams[-1] if seams else None
        k_cur, k_prev = cur.get("kind") or "image", prev.get("kind") or "image"
        if k_cur == k_prev:
            prefs = ["color_flood", "dip"]
        elif k_cur in ("image", "flyover", "scene3d"):
            prefs = ["zoom_through", "whip"]
        else:
            prefs = []
        prefs += [AUTO_TRANSITION_ROTATION[(rot + j) % len(AUTO_TRANSITION_ROTATION)] for j in range(len(AUTO_TRANSITION_ROTATION))]
        recent = set(seams[-2:])
        pick = next((t for t in prefs if t != last and t not in recent), None) or next(t for t in prefs if t != last)
        if pick in AUTO_TRANSITION_ROTATION:
            rot = AUTO_TRANSITION_ROTATION.index(pick) + 1
        cur["transition"], cur["transition_auto"] = pick, True
        seams.append(pick)
    return seams


def _llm_emphasis(narrations: List[str]) -> List[str]:
    """로컬 LLM 에 씬별 강조어 1개를 묻는다(숫자·고유명사 우선, 대본에 있는 그대로). 실패하면 빈 목록."""
    import llm_client
    lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(narrations))
    messages = [
        {"role": "system", "content": "쇼츠 자막에서 강조할 핵심어를 고르는 편집자입니다. JSON 만 답합니다."},
        {"role": "user", "content": (
            "각 문장에서 시청자가 꼭 기억해야 할 단어를 하나씩 고르세요. 숫자(단위 포함)나 고유명사를 우선하고, "
            "문장에 적힌 그대로 한 어절만 쓰세요. 마땅한 단어가 없으면 빈 문자열.\n"
            f"{lines}\n\n형식: {{\"words\": [\"...\", ...]}} (문장 수 {len(narrations)}개와 같은 길이)")},
    ]
    # max_continues 는 요청 횟수 상한이라 1 이상이어야 실제로 호출된다 (0 이면 아무 요청 없이 빈 답)
    data, _raw = llm_client.call_llm_json(messages, max_tokens=400, temperature=0.2, max_continues=1)
    words = (data or {}).get("words") if isinstance(data, dict) else None
    return [str(w or "") for w in words] if isinstance(words, list) else []


def ensure_emphasis(job: dict, llm: Optional[Callable] = None) -> None:
    """강조어가 없는 씬만 채운다(LLM → 숫자 어절 → 없음). 실패해도 빌드는 계속한다."""
    scenes = (job.get("storyboard") or {}).get("scenes") or []
    if any("emphasis" not in s for s in scenes):
        shorts_captions.pick_emphasis_words(scenes, llm=llm if llm is not None else _llm_emphasis)


def refresh_lint(job: dict) -> dict:
    """U-1 렌더 전 린트를 다시 돌려 job["lint"] 에 저장(저장은 호출부). 빌드를 막지 않는다."""
    job["lint"] = shorts_review.lint_storyboard(job)
    return job["lint"]


def build_job_from_plan(plan_id: str, platforms: Optional[List[str]] = None, voice_id: Optional[str] = None,
                        plan: Optional[dict] = None, language: Optional[str] = None) -> dict:
    """저장된 9:16 씬 기획서 → data/shorts/<id>/job.json (작업계획서 5.4 스키마). 이미지·음성은 build_job 에서 채운다."""
    if language is not None and language not in SHORTS_LANGUAGES:
        raise ValueError(f"지원하지 않는 언어입니다: {language}. 가능: {', '.join(SHORTS_LANGUAGES)}")
    plan = plan or scene_store.load_plan(plan_id)
    if not plan:
        raise FileNotFoundError(f"씬 기획서를 찾을 수 없습니다: {plan_id}")
    aspect = plan.get("aspect_ratio") or "16:9"
    if aspect != "9:16":
        raise ValueError(f"쇼츠는 9:16 기획서만 받습니다 (이 기획서는 {aspect}). 3단계에서 화면 비율을 9:16 으로 다시 기획하세요.")
    scenes_in = plan.get("structured_scenes") or []
    if not scenes_in:
        raise ValueError("기획서에 씬이 없습니다.")
    plats = [p for p in (platforms or ["youtube_shorts"]) if p in PLATFORM_PROFILES]
    if not plats:
        raise ValueError(f"지원하지 않는 플랫폼입니다: {platforms}. 가능: {', '.join(PLATFORM_PROFILES)}")

    spec = concept_packs.shorts_spec(plan.get("concept_key"))
    max_scenes = int(spec.get("max_scenes") or 6)
    topic = plan.get("topic") or plan.get("title") or "쇼츠"
    title = plan.get("title") or topic
    shorts_id = f"shorts_{int(time.time())}_{_slug(topic)}"
    n = 1
    while os.path.exists(os.path.join(SHORTS_DIR, shorts_id)):
        n += 1
        shorts_id = f"shorts_{int(time.time())}_{_slug(topic, 20)}_{n}"
    _safe_id(shorts_id)

    warnings: List[str] = []
    if len(scenes_in) > max_scenes:
        warnings.append(f"씬 {len(scenes_in)}개 중 앞 {max_scenes}개만 사용합니다 (쇼츠 씬 상한).")
        scenes_in = scenes_in[:max_scenes]
    scenes = []
    _kinds, kind_fields = _kind_spec(spec)
    for i, sc in enumerate(scenes_in, 1):
        narration = (sc.get("narration") or sc.get("subtitle") or "").strip()
        item = {
            "scene_num": int(sc.get("scene_num") or i),
            "seconds": float(sc.get("seconds") or plan.get("scene_seconds") or 8.0),
            "narration": narration,
            "kind": sc.get("kind") or "image",
            "image": None,
            "motion": _scene_motion(i),
            "beat": sc.get("dramatic_beat") or "",
            "visual": sc.get("visual_description_ko") or "",
        }
        for k in kind_fields:   # 비용 0 씬(작업계획서 7b)의 종류별 필드를 그대로 넘긴다
            if sc.get(k) is not None:
                item[k] = sc[k]
        scenes.append(fill_kind_defaults(item, spec))
    hook_words = spec.get("hook_words") or {"min": 3, "max": 5}
    hook = (plan.get("hook_text") or "").strip() or _hook_from_title(title, int(hook_words.get("max", 5)))
    tag_default = spec.get("end_tag") or {}
    end_tag = {
        "text": (plan.get("end_tag_text") or tag_default.get("text") or "구독하고 다음 편 보기").strip(),
        "subtext": (plan.get("end_tag_subtext") or tag_default.get("subtext") or "").strip(),
        "seconds": float(tag_default.get("seconds") or DEFAULT_END_TAG_SECONDS),
    }
    yt_title = title if "#shorts" in title.lower() else f"{title} #Shorts"
    description = "\n\n".join(x for x in [plan.get("seo_description") or "", plan.get("engagement_question") or ""] if x)
    job = {
        "shorts_id": shorts_id,
        "format": "scene",
        "source": {"plan_id": plan.get("plan_id") or plan_id, "track_id": None},
        "status": "planned",
        "topic": topic,
        "platforms": plats,
        "voice_id": voice_id or DEFAULT_VOICE_ID,
        **({"language": language} if language else {}),
        "concept_key": plan.get("concept_key") or "",
        "storyboard": {
            "hook_text": hook,
            "hook_seconds": float(spec.get("hook_seconds") or 3.0),
            "scenes": scenes,
            "end_tag": end_tag,
        },
        "captions": [],
        "caption_source": None,
        "caption_page_ms": 1200,
        "audio": {"narration": None, "bgm": None, "bgm_track_id": None, "bgm_volume": DEFAULT_BGM_VOLUME, "lufs": None, "true_peak": None},
        "render": {},
        "qc": {},
        "metadata": {
            "youtube": {"title": yt_title[:100], "description": description[:4900], "tags": ["Shorts"], "pinned_comment": plan.get("pinned_comment") or ""},
            "instagram": {"caption": f"{title}\n\n{description}"[:2200], "hashtags": []},
        },
        "publish": {"youtube": {"video_id": None, "publish_at": None}, "instagram": {"media_id": None, "permalink": None}},
        "warnings": warnings,
        "created_at": time.time(),
    }
    _resolve_scene_images(job, plan)
    fit_to_max_seconds(job)
    assign_transitions(job)
    refresh_lint(job)
    save_job(job)
    return job


def update_storyboard(job: dict, hook_text: Optional[str] = None, scenes: Optional[List[dict]] = None,
                      end_tag: Optional[dict] = None) -> dict:
    """UI 스토리보드 카드 편집 반영. 씬은 scene_num 기준으로 narration·seconds·motion·transition·kind·title·subtitle 만 바꾼다(이미지 경로는 UI 가 못 바꾼다)."""
    sb = job.setdefault("storyboard", {})
    spec = concept_packs.shorts_spec(job.get("concept_key"))
    kinds, _fields = _kind_spec(spec)
    if hook_text is not None:
        sb["hook_text"] = str(hook_text).strip()[:60]
    if scenes:
        by_num = {int(s.get("scene_num") or 0): s for s in sb.get("scenes") or []}
        for edit in scenes:
            cur = by_num.get(int(edit.get("scene_num") or 0))
            if not cur:
                continue
            if edit.get("narration") is not None:
                cur["narration"] = str(edit["narration"]).strip()[:400]
            if edit.get("seconds") is not None:
                cur["seconds"] = max(1.0, min(15.0, float(edit["seconds"])))
            if edit.get("motion") in ("zoom_in", "zoom_out", "pan_left", "pan_right"):
                cur["motion"] = edit["motion"]
            if edit.get("transition") in SCENE_TRANSITIONS:
                cur["transition"] = edit["transition"]
                cur.pop("transition_auto", None)   # 사용자가 고른 전환은 자동 배정이 덮지 않는다
            if edit.get("emphasis") is not None:
                cur["emphasis"] = str(edit["emphasis"]).strip()[:20]
                cur["emphasis_source"] = "user" if cur["emphasis"] else "none"
            for k in ("title", "subtitle"):
                if edit.get(k) is not None:
                    cur[k] = str(edit[k]).strip()[:40]
            if edit.get("hanzi") is not None:
                cur["hanzi"] = re.sub(r"\s+", "", str(edit["hanzi"]))[:24]
            if edit.get("translation") is not None:
                cur["translation"] = _clip_text(edit["translation"], SEAL_TRANSLATION_MAX)
            if edit.get("source") is not None:
                cur["source"] = _clip_text(edit["source"], SEAL_SOURCE_MAX)
            if edit.get("kind") in kinds and edit["kind"] != (cur.get("kind") or "image"):
                cur["kind"] = edit["kind"]
                cur.pop("kind_note", None)
                fill_kind_defaults(cur, spec)
    if end_tag is not None:
        cur_tag = sb.setdefault("end_tag", {"text": "", "subtext": "", "seconds": DEFAULT_END_TAG_SECONDS})
        for k in ("text", "subtext"):
            if end_tag.get(k) is not None:
                cur_tag[k] = str(end_tag[k]).strip()[:40]
        if end_tag.get("seconds") is not None:
            cur_tag["seconds"] = max(0.0, min(4.0, float(end_tag["seconds"])))
    fit_to_max_seconds(job)
    assign_transitions(job)
    refresh_lint(job)
    save_job(job)
    return job


# ── 이미지 (producer.generate_images 9:16 재사용, 편당·일일 상한, 과금 가드) ─────

def _scenes_needing_images(job: dict) -> List[dict]:
    """kind=image 인데 파일이 없는 씬만 (비용 0 씬은 제외)."""
    return [sc for sc in (job.get("storyboard") or {}).get("scenes") or []
            if _is_image_scene(sc) and not (sc.get("image") and os.path.exists(sc["image"]))]


def estimate_images(job: dict, plan: Optional[dict] = None) -> dict:
    """생성 전 예상 장수·비용·한도. API 가 그대로 돌려주고 UI 가 확인 모달에 띄운다."""
    _resolve_scene_images(job, plan)
    needed = len(_scenes_needing_images(job))
    usage = usage_summary()
    cap_job = usage["per_job_cap"]
    allowed, reason = True, ""
    if needed > cap_job:
        allowed, reason = False, f"편당 이미지 상한({cap_job}장)을 넘습니다 (필요 {needed}장)."
    elif usage["today"] + needed > usage["cap"]:
        allowed, reason = False, f"일일 이미지 상한({usage['cap']}장)을 넘습니다 (오늘 {usage['today']}장 사용, 요청 {needed}장)."
    elif needed > 0 and not producer.gemini_key():
        allowed, reason = False, "Gemini API 키가 없습니다. ③ 탭의 환경 영역에서 키를 저장하세요."
    usd = round(needed * IMAGE_USD_PER_IMAGE, 3)
    all_scenes = (job.get("storyboard") or {}).get("scenes") or []
    image_scenes = [sc for sc in all_scenes if _is_image_scene(sc)]
    return {
        "needed": needed,
        "scenes": [sc.get("scene_num") for sc in _scenes_needing_images(job)],
        "reused": len(image_scenes) - needed,
        "cost_free": len(all_scenes) - len(image_scenes),
        "usd": usd,
        "krw": int(round(usd * USD_KRW, -1)),
        "usage": usage,
        "allowed": allowed,
        "reason": reason,
    }


def generate_job_images(job: dict, progress_cb: Optional[Callable] = None, generator: Optional[Callable] = None) -> dict:
    """씬 이미지를 Gemini 로 생성한다(9:16, 기획서 미디어 폴더에 저장 → 씬에 연결). 썸네일은 만들지 않는다(쇼츠는 커스텀 썸네일 미사용).

    호출 전 상한을 다시 검사한다 — API 의 confirm 가드와 별개로 엔진 단독 호출도 과금을 막아야 한다.
    """
    plan_id = (job.get("source") or {}).get("plan_id")
    plan = scene_store.load_plan(plan_id) if plan_id else None
    if not plan:
        raise FileNotFoundError(f"기획서를 찾을 수 없습니다: {plan_id}")
    est = estimate_images(job, plan)
    if est["needed"] == 0:
        return {"generated": [], "errors": [], "reused": est["reused"]}
    if not est["allowed"]:
        raise RuntimeError(est["reason"])
    slots = [str(n) for n in est["scenes"]]
    gen = generator or producer.generate_images

    def cb(step, msg, pct):
        if progress_cb:
            progress_cb("images", msg, pct)

    res = gen(plan, slots=slots, progress=cb) or {}
    generated = list(res.get("generated") or [])
    if generated:
        _increment_usage(len(generated))
    _resolve_scene_images(job, plan)
    still = _scenes_needing_images(job)
    errors = list(res.get("errors") or [])
    job.setdefault("warnings", []).extend(f"이미지 생성 실패(씬 {e.get('slot')}): {str(e.get('error'))[:120]}" for e in errors)
    save_job(job)
    if still:
        raise RuntimeError("이미지가 없는 씬이 남았습니다: " + ", ".join(str(s.get("scene_num")) for s in still)
                           + ((" — " + "; ".join(str(e.get("error"))[:80] for e in errors)) if errors else ""))
    return {"generated": generated, "errors": errors, "reused": est["reused"]}


# ── 오디오: 씬 나레이션(edge-tts 단어 타이밍) + 이어붙이기 + BGM ─────────────

def job_language(job: dict, voice_id: Optional[str]) -> str:
    """나레이션 언어: 잡에 정한 값 → edge 프리셋의 언어 → korean."""
    return job.get("language") or tts_service.voice_language(voice_id or "") or "korean"


def _default_synth(voice_id: str, language: str = "korean") -> Callable:
    """씬 하나를 합성하는 함수를 만든다. 반환 함수: (text, scene_num, out_path_base) → {"file", "captions"|None, "engine"}.
    language 는 언어를 따라가는 목소리(Qwen3·내 목소리)에만 쓰인다 — edge 프리셋은 목소리 자체가 언어를 정한다."""
    edge_map = {ep["id"]: ep for ep in tts_service.EDGE_PRESETS}
    is_edge = voice_id in edge_map or str(voice_id).startswith("ko-KR-")

    def synth(text: str, scene_num: int, out_base: str) -> dict:
        if is_edge:
            conf = edge_map.get(voice_id, tts_service.EDGE_PRESETS[0])
            code = conf.get("voice_id") if voice_id in edge_map else voice_id
            out = out_base + ".mp3"
            res = asyncio.run(tts_service.TTSService.synthesize_edge_tts_single(
                text, voice_code=code, rate=conf.get("default_rate", "+5%"), output_file=out, with_word_boundaries=True))
            if not res or not os.path.exists(out):
                raise RuntimeError(f"씬 {scene_num} edge-tts 합성 실패")
            caps = res.get("captions") or None
            last_end = max(float(c.get("endMs") or 0) for c in caps) / 1000.0 if caps else 0.0
            _trim_trailing_silence(producer.ffmpeg_path(), out, min_seconds=last_end)
            return {"file": out, "captions": caps, "engine": "edge-tts"}
        res = tts_service.TTSService.synthesize_speech(text, voice_id=voice_id, scene_index=scene_num, topic_slug="shorts",
                                                       language=language)
        if res.get("status") != "success":
            raise RuntimeError(f"씬 {scene_num} 음성 합성 실패: {res.get('message')}")
        src = os.path.join(str(tts_service.AUDIO_DIR), res.get("filename") or "")
        out = out_base + os.path.splitext(src)[1]
        shutil.copy(src, out)
        return {"file": out, "captions": None, "engine": res.get("engine") or "qwen-tts"}
    return synth


def _trim_trailing_silence(ff: Optional[str], path: str, min_seconds: float = 0.0,
                           threshold_db: float = TRIM_SILENCE_DB, keep: float = TRIM_KEEP_SECONDS) -> bool:
    """edge-tts 가 끝에 붙이는 무음(InJoon 약 1.2초)을 잘라 제자리에 덮어쓴다. 반환: 잘랐으면 True.

    앞쪽 무음은 단어 타이밍(WordBoundary)의 기준점이라 건드리지 않는다.
    min_seconds(마지막 단어 끝) 앞으로는 자르지 않는다 — edge-tts 의 단어 끝 시각은 실제 소리보다 0.2초쯤 늦게
    잡히므로, 무음 기준으로 잘린 길이가 그보다 짧으면 min_seconds + keep 지점에서 자른다(자막이 음성보다 길어지지 않게).
    """
    if not ff or not os.path.exists(path):
        return False
    tmp = path + ".trim.mp3"
    enc = ["-c:a", "libmp3lame", "-q:a", "2", tmp]
    try:
        res = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-af",
                              f"areverse,silenceremove=start_periods=1:start_threshold={threshold_db:g}dB:start_silence={keep:g},areverse",
                              *enc], capture_output=True, text=True, timeout=120)
        dur = producer.audio_duration(tmp) if res.returncode == 0 and os.path.exists(tmp) else None
        if not dur:
            return False
        if dur < min_seconds:
            target = min_seconds + keep
            original = producer.audio_duration(path) or 0.0
            if target >= original - 0.05:
                return False   # 자를 만한 무음이 없다
            res = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-t", f"{target:.3f}", *enc],
                                 capture_output=True, text=True, timeout=120)
            if res.returncode != 0 or not os.path.exists(tmp):
                return False
        os.replace(tmp, path)
        return True
    except Exception:
        return False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _pad_audio(ff: Optional[str], src: str, dst: str, pad: float) -> str:
    """끝에 pad 초 무음을 붙인 복사본. ffmpeg 가 없으면 원본을 그대로 쓴다."""
    if not ff or pad <= 0:
        return src
    try:
        res = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-af", f"apad=pad_dur={pad:.3f}",
                              "-c:a", "libmp3lame", "-q:a", "2", dst], capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and os.path.exists(dst):
            return dst
    except Exception:
        pass
    return src


def voice_eq_enabled() -> bool:
    """SHORTS_VOICE_EQ=0 이면 나레이션 EQ 를 끈다(기본 켬)."""
    return os.environ.get("SHORTS_VOICE_EQ", "1").strip().lower() not in ("0", "false", "no", "off")


def _filter_inplace(ff: Optional[str], path: str, af: str, runner=subprocess.run) -> bool:
    """오디오 필터를 걸어 제자리에 덮어쓴다(mp3). 실패하면 원본을 그대로 두고 False."""
    if not ff or not path or not os.path.exists(path):
        return False
    tmp = path + ".fx.mp3"
    try:
        res = runner([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-af", af,
                      "-c:a", "libmp3lame", "-q:a", "2", tmp], capture_output=True, text=True, timeout=180)
        if res.returncode != 0 or not os.path.exists(tmp):
            return False
        os.replace(tmp, path)
        return True
    except Exception:
        return False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def short_term_loudness(path: str, runner=subprocess.run) -> List[tuple]:
    """ffmpeg ebur128 의 0.1초 간격 단기(3초) 음량 [(t, S), ...]. 실패하면 빈 목록."""
    ff = producer.ffmpeg_path()
    if not ff or not path or not os.path.exists(path):
        return []
    try:
        res = runner([ff, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128", "-f", "null", "-"],
                     capture_output=True, text=True, timeout=180)
    except Exception:
        return []
    return [(float(t), float(v)) for t, v in re.findall(r"t:\s*([\d.]+)\s+TARGET:.*?S:\s*(-?[\d.]+)", res.stderr or "")]


def bgm_entry_offset(path: str, duration: float, samples: Optional[List[tuple]] = None) -> float:
    """곡에서 영상 길이만큼 틀 시작 지점(초) — 조용한 인트로를 건너뛴다 (OM audio_energy 개념 재작성).

    단기 음량이 곡의 상위 10% 값보다 BGM_ENTRY_DROP_LU 아래를 처음 넘는 곳을 찾고, 3초 창의 지연을 감안해 1.5초 당긴다.
    곡이 영상보다 짧거나 측정이 안 되면 0. 끝에서 영상 길이가 남도록 뒤로는 넘기지 않는다.
    """
    pts = [(t, v) for t, v in (samples if samples is not None else short_term_loudness(path)) if v > -70]
    if not pts:
        return 0.0
    length = max(t for t, _ in pts)
    latest = length - duration - 0.5
    if latest <= BGM_ENTRY_MIN_SECONDS:
        return 0.0
    vals = sorted(v for _, v in pts)
    ref = vals[min(len(vals) - 1, int(len(vals) * 0.9))]
    first = next((t for t, v in pts if v >= ref - BGM_ENTRY_DROP_LU), 0.0)
    entry = min(max(0.0, first - 1.5), latest)
    return round(entry, 2) if entry >= BGM_ENTRY_MIN_SECONDS else 0.0


def prepare_bgm(ff: Optional[str], src: str, dst: str, offset: float, duration: float, carve: bool = True,
                runner=subprocess.run) -> Optional[str]:
    """루나 원곡(읽기 전용)에서 offset 부터 duration+1초를 잘라 잡 폴더에 BGM 을 만든다. 말소리 대역도 비운다. 실패하면 None."""
    if not ff or not src or not os.path.exists(src):
        return None
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, offset):.2f}", "-t", f"{duration + 1.0:.2f}", "-i", src]
    if carve:
        cmd += ["-af", BGM_CARVE_FILTER]
    cmd += ["-c:a", "libmp3lame", "-q:a", "2", dst]
    try:
        res = runner(cmd, capture_output=True, text=True, timeout=180)
        return dst if res.returncode == 0 and os.path.exists(dst) else None
    except Exception:
        return None


def pick_bgm(track_id: Optional[str] = None) -> Optional[dict]:
    """루나 트랙 중 vocal_mode == 'instrumental' 인 음원을 고른다(최신순). 없으면 None → 무음."""
    try:
        import luna_engine
        tracks = luna_engine.list_tracks()
    except Exception:
        return None
    if track_id:
        cands = [t for t in tracks if t.get("track_id") == track_id]
    else:
        cands = [t for t in tracks if (t.get("vocal_mode") or "").lower() == "instrumental"]
    for t in cands:
        tid = t.get("track_id")
        if not tid:
            continue
        meta = luna_engine.load_track(tid) or {}
        for cand in (meta.get("audio_file"), os.path.join(luna_engine.LUNA_DIR, tid, "audio.mp3")):
            if cand and os.path.exists(cand):
                return {"track_id": tid, "file": cand, "title": t.get("title") or tid}
    return None


def synthesize_job_audio(job: dict, voice_id: Optional[str] = None, progress_cb: Optional[Callable] = None,
                         synth: Optional[Callable] = None, merger: Optional[Callable] = None,
                         bgm_picker: Optional[Callable] = None, lufs_probe: Optional[Callable] = None) -> dict:
    """씬별 나레이션 합성 → 씬 길이를 실제 발화 길이(+패드)로 맞춤 → 자막 토큰(절대 ms) → 이어붙이기 → BGM 선택 → LUFS 측정(가능할 때).

    자막 원천: edge-tts WordBoundary 가 있으면 그대로(caption_source=edge_tts), 없으면 글자 수 비례(proportional).
    """
    def step(pct, msg):
        if progress_cb:
            progress_cb("audio", msg, pct)

    shorts_id = _safe_id(job["shorts_id"])
    vid = voice_id or job.get("voice_id") or DEFAULT_VOICE_ID
    job["voice_id"] = vid
    lang = job_language(job, vid)
    job["narration_language"] = lang   # 이번 합성에 쓴 언어 — 목소리에서 추정한 값은 job["language"] 에 굳히지 않는다
    voice_lang = tts_service.voice_language(vid)
    if voice_lang and voice_lang != lang:
        msg = f"목소리 언어({voice_lang})와 잡 언어({lang})가 다릅니다 — 목소리는 {voice_lang} 로 읽습니다."
        if msg not in (job.get("warnings") or []):
            job.setdefault("warnings", []).append(msg)
    sb = job.get("storyboard") or {}
    scenes = sb.get("scenes") or []
    if not scenes:
        raise RuntimeError("스토리보드에 씬이 없습니다.")
    d = job_dir(shorts_id, create=True)
    synth = synth or _default_synth(vid, lang)
    merge = merger or tts_service.merge_audio_files
    ff = producer.ffmpeg_path()

    captions: List[dict] = []
    files: List[str] = []
    sources = set()
    cursor_ms = 0
    for i, sc in enumerate(scenes, 1):
        text = (sc.get("narration") or "").strip()
        if not text:
            raise RuntimeError(f"씬 {sc.get('scene_num')} 나레이션이 비어 있습니다.")
        step(int(80 * (i - 1) / len(scenes)), f"나레이션 합성 {i}/{len(scenes)}...")
        res = synth(text, int(sc.get("scene_num") or i), os.path.join(d, f"narration_{i:02d}"))
        afile = res["file"]
        dur = producer.audio_duration(afile)
        toks = res.get("captions") or []
        if not dur:
            dur = (toks[-1]["endMs"] / 1000.0 + 0.2) if toks else max(1.0, len(text) / 5.2)
        dur = float(dur)
        pad = SCENE_PAD_SECONDS if ff else 0.0
        padded = _pad_audio(ff, afile, os.path.join(d, f"narration_{i:02d}_pad.mp3"), pad)
        if padded == afile:
            pad = 0.0
        if toks:
            toks = [dict(t, startMs=t["startMs"] + cursor_ms, endMs=t["endMs"] + cursor_ms) for t in toks]
            toks[-1]["pageBreakAfter"] = True
            sources.add("edge_tts")
        else:
            toks = proportional_captions(text, cursor_ms, cursor_ms + int(round(dur * 1000)))
            sources.add("proportional")
        captions.extend(toks)
        sc["seconds"] = round(dur + pad, 2)
        sc["narration_file"] = afile
        sc["narration_seconds"] = round(dur, 3)
        sc["caption_source"] = "edge_tts" if res.get("captions") else "proportional"
        files.append(padded)
        cursor_ms += int(round(sc["seconds"] * 1000))

    step(85, "나레이션 이어붙이기...")
    narration = os.path.join(d, "narration.mp3")
    if not merge(files, narration) or not os.path.exists(narration):
        raise RuntimeError("나레이션 병합에 실패했습니다 (ffmpeg 확인).")
    # U-2: 나레이션 EQ (80Hz 아래 제거·3kHz +2.5dB·피크 -1dB). 시간축은 바뀌지 않아 자막 타이밍은 그대로다
    voice_eq = voice_eq_enabled() and _filter_inplace(ff, narration, VOICE_EQ_FILTER)

    # 60초 상한: 발화가 길어 넘치면 엔드 태그를 먼저 줄이고, 그래도 넘으면 대본을 줄이라고 실패시킨다(음성 중간을 자르지 않는다)
    tag = sb.setdefault("end_tag", {"text": "", "subtext": "", "seconds": DEFAULT_END_TAG_SECONDS})
    if total_seconds(job) > MAX_SECONDS and float(tag.get("seconds") or 0) > 1.5:
        tag["seconds"] = 1.5
        job.setdefault("warnings", []).append("길이 상한 때문에 엔드 태그를 1.5초로 줄였습니다.")
    if total_seconds(job) > MAX_SECONDS:
        raise RuntimeError(f"나레이션을 합친 길이 {total_seconds(job):.1f}초가 상한 {MAX_SECONDS:.0f}초를 넘습니다. 씬 대본을 줄이세요.")

    picker = bgm_picker or pick_bgm
    bgm = picker(job.get("audio", {}).get("bgm_track_id")) if picker else None
    audio = job.setdefault("audio", {})
    audio.update({
        "narration": narration,
        "voice_eq": bool(voice_eq),
        "bgm": bgm["file"] if bgm else None,
        "bgm_source": bgm["file"] if bgm else None,
        "bgm_offset": 0.0,
        "bgm_track_id": bgm["track_id"] if bgm else None,
        "bgm_title": bgm.get("title") if bgm else None,
        "bgm_volume": audio.get("bgm_volume", DEFAULT_BGM_VOLUME),
        "bgm_duck_boost": float(audio.get("bgm_duck_boost") or BGM_DUCK_BOOST),
        "narration_seconds": round(cursor_ms / 1000.0, 3),
    })
    if bgm:
        # U-2: 곡의 조용한 인트로를 건너뛰고(진입점), 말소리 대역을 비운 구간만 잡 폴더에 만든다. 실패하면 원곡 처음부터
        offset = bgm_entry_offset(bgm["file"], total_seconds(job))
        prepared = prepare_bgm(ff, bgm["file"], os.path.join(d, "bgm_prepared.mp3"), offset, total_seconds(job))
        if prepared:
            audio["bgm"] = prepared
            audio["bgm_offset"] = offset
        # 곡마다 마스터링 음량이 달라 고정 배율 대신 "나레이션보다 N LU 아래"로 맞춘다. 루나 원곡은 읽기만 한다.
        probe = lufs_probe or integrated_lufs
        under = float(audio.get("bgm_under_lu") or BGM_UNDER_NARRATION_LU)
        n_lufs, b_lufs = probe(narration), probe(audio["bgm"], seconds=None if prepared else 120)
        audio["bgm_under_lu"] = under
        audio["bgm_lufs"] = b_lufs
        if n_lufs is not None and b_lufs is not None:
            audio["bgm_volume"] = bgm_volume_for(n_lufs, b_lufs, under)
        else:
            audio["bgm_volume"] = BGM_FALLBACK_VOLUME
            job.setdefault("warnings", []).append(f"BGM 음량을 잴 수 없어 기본 배율 {BGM_FALLBACK_VOLUME} 로 깝니다.")
    else:
        job.setdefault("warnings", []).append("연주곡(vocal_mode=instrumental) 루나 트랙이 없어 BGM 없이 만듭니다.")
    job["captions"] = captions
    job["caption_source"] = "edge_tts" if sources == {"edge_tts"} else "proportional"
    loud = measure_loudness(narration)
    audio["narration_lufs"] = loud["lufs"] if loud else None
    job["status"] = "assets"
    save_job(job)
    step(100, f"오디오 준비 완료 ({cursor_ms / 1000:.1f}초, 자막 {len(captions)}토큰, {job['caption_source']})")
    return job


# ── 음량 (베가 분석 함수가 있으면 측정, 벗어나면 loudnorm 1패스) ─────────────

def integrated_lufs(path: Optional[str], seconds: Optional[float] = None, runner=subprocess.run) -> Optional[float]:
    """ffmpeg ebur128 통합 LUFS. 최종 스테레오 믹스에서 들리는 크기와 맞는다
    (vega 측정은 모노 나레이션을 약 3dB 크게 잰다). seconds 를 주면 앞부분만 잰다. 실패하면 None."""
    ff = producer.ffmpeg_path()
    if not ff or not path or not os.path.exists(path):
        return None
    cmd = [ff, "-hide_banner", "-nostats", "-i", path] + (["-t", f"{seconds:g}"] if seconds else []) + \
          ["-vn", "-af", "ebur128", "-f", "null", "-"]
    try:
        res = runner(cmd, capture_output=True, text=True, timeout=180)
        found = re.findall(r"I:\s+(-?[\d.]+) LUFS", res.stderr or "")
        return float(found[-1]) if found else None
    except Exception:
        return None


def bgm_volume_for(narration_lufs: float, bgm_lufs: float, under_lu: float = BGM_UNDER_NARRATION_LU) -> float:
    """BGM 이 나레이션보다 under_lu 만큼 작게 깔리는 배율. DEFAULT_BGM_VOLUME 을 넘지 않는다."""
    return round(min(DEFAULT_BGM_VOLUME, 10 ** ((narration_lufs - under_lu - bgm_lufs) / 20)), 4)


def measure_loudness(path: str) -> Optional[dict]:
    """vega_engine(pyloudnorm) 으로 통합 LUFS·트루피크. 의존성이 없거나 실패하면 None (측정 생략)."""
    if not path or not os.path.exists(path):
        return None
    try:
        import vega_engine
        if not vega_engine.is_available():
            return None
        audio, sr = vega_engine.load_audio(path)
        a = vega_engine.analyze(audio, sr)
        if a.get("is_silent"):
            return {"lufs": -70.0, "true_peak": -120.0, "silent": True}
        return {"lufs": float(a["integrated_lufs"]), "true_peak": float(a["true_peak_dbtp"]), "silent": False}
    except Exception:
        return None


def normalize_loudness(job: dict, measurer: Optional[Callable] = None, runner=subprocess.run) -> dict:
    """렌더 결과의 LUFS 가 목표 ±1dB 를 벗어나면 보정한다(영상 스트림은 copy). 측정 불가면 건너뛴다.

    볼륨만 올리거나 내려도 트루피크가 상한 안이면 그렇게 해서 대사의 강약을 지키고,
    넘칠 때만 loudnorm 1패스(동적 압축)를 쓴다.
    """
    render = job.get("render") or {}
    path = render.get("file")
    audio = job.setdefault("audio", {})
    measure = measurer or measure_loudness
    loud = measure(path) if path else None
    audio["lufs"] = loud["lufs"] if loud else None
    audio["true_peak"] = loud["true_peak"] if loud else None
    audio["loudnorm_applied"] = False
    if not loud or loud.get("silent"):
        return job
    if abs(loud["lufs"] - TARGET_LUFS) <= LUFS_TOLERANCE and loud["true_peak"] <= TARGET_TRUE_PEAK + 0.1:
        return job
    ff = producer.ffmpeg_path()
    if not ff:
        return job
    gain = TARGET_LUFS - loud["lufs"]
    if loud["true_peak"] + gain <= TARGET_TRUE_PEAK:
        method, af = "gain", f"volume={gain:.2f}dB"
    else:
        method, af = "loudnorm", f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK}:LRA=11"
    tmp = os.path.join(os.path.dirname(path), "final_9x16_loudnorm.mp4")
    res = runner([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-c:v", "copy",
                  "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                  "-movflags", "+faststart", tmp], capture_output=True, text=True, timeout=600)
    if getattr(res, "returncode", 1) == 0 and os.path.exists(tmp):
        os.replace(tmp, path)
        audio["loudnorm_applied"] = True
        audio["loudness_method"] = method
        audio["lufs_before"] = loud["lufs"]
        after = measure(path)
        if after:
            audio["lufs"], audio["true_peak"] = after["lufs"], after["true_peak"]
        try:
            render["probe"] = probe_video(path)
        except Exception:
            pass
    else:
        job.setdefault("warnings", []).append("loudnorm 보정 실패 — 측정값 그대로 둡니다.")
    save_job(job)
    return job


# ── QC ───────────────────────────────────────────────────────────────────────

def first_frame_brightness(path: str, ff: Optional[str] = None, runner=subprocess.run) -> Optional[float]:
    """첫 프레임을 96×54 그레이로 뽑아 평균 밝기(0~255). ffmpeg 가 없으면 None."""
    ff = ff or producer.ffmpeg_path()
    if not ff or not path or not os.path.exists(path):
        return None
    try:
        res = runner([ff, "-v", "error", "-i", path, "-frames:v", "1", "-vf", "scale=96:54,format=gray", "-f", "rawvideo", "-"],
                     capture_output=True, timeout=60)
        data = res.stdout or b""
        if getattr(res, "returncode", 1) != 0 or not data:
            return None
        return round(sum(data) / float(len(data)), 2)
    except Exception:
        return None


def qc_job(job: dict, probe: Optional[dict] = None, brightness: Optional[float] = None,
           loudness: Optional[dict] = None, measure: bool = True) -> dict:
    """작업계획서 S-2 6항. 통과 → qc_passed, 하나라도 실패 → failed. 측정 불가 항목은 skipped 로 남기고 판정에서 뺀다."""
    render = job.get("render") or {}
    path = render.get("file")
    checks: List[dict] = []

    def add(name, passed, detail="", skipped=False):
        checks.append({"name": name, "passed": (None if skipped else bool(passed)), "detail": detail, "skipped": bool(skipped)})

    if not path or not os.path.exists(path):
        add("file_exists", False, f"렌더 파일 없음: {path}")
        pr = {}
    else:
        add("file_exists", True, os.path.basename(path))
        pr = probe or (render.get("probe") if (render.get("probe") or {}).get("width") else None)
        if pr is None:
            try:
                pr = probe_video(path)
            except Exception as e:
                pr = {"error": str(e)[:120]}
    if pr.get("width"):
        dur = float(pr.get("duration") or 0)
        add("duration<=60", dur <= MAX_SECONDS + 0.1, f"{dur:.2f}초")
        add("1080x1920", int(pr.get("width") or 0) == WIDTH and int(pr.get("height") or 0) == HEIGHT, f"{pr.get('width')}x{pr.get('height')}")
        add("audio_present", bool(pr.get("audio_present")), pr.get("audio_codec") or "오디오 스트림 없음")
    elif path and os.path.exists(path):
        add("probe", False, pr.get("error") or "ffprobe 실패", skipped=False)

    if path and os.path.exists(path):
        br = brightness if brightness is not None else (first_frame_brightness(path) if measure else None)
        if br is None:
            add("first_frame_not_black", None, "측정 불가(ffmpeg 없음)", skipped=True)
        else:
            add("first_frame_not_black", br >= QC_MIN_BRIGHTNESS, f"평균 밝기 {br:.1f} (기준 ≥ {QC_MIN_BRIGHTNESS:.0f})")
        loud = loudness
        if loud is None and (job.get("audio") or {}).get("lufs") is not None:
            loud = {"lufs": job["audio"]["lufs"], "true_peak": job["audio"].get("true_peak")}
        if loud is None and measure:
            loud = measure_loudness(path)
        if not loud or loud.get("lufs") is None:
            add("lufs_within_1db", None, "측정 불가(베가 의존성 없음)", skipped=True)
        else:
            diff = abs(float(loud["lufs"]) - TARGET_LUFS)
            add("lufs_within_1db", diff <= LUFS_TOLERANCE, f"{float(loud['lufs']):.1f} LUFS (목표 {TARGET_LUFS:.0f} ±{LUFS_TOLERANCE:.0f})")

    failed = [c["name"] for c in checks if c["passed"] is False]
    passed = not failed and any(c["passed"] for c in checks)
    job["qc"] = {"passed": passed, "checks": checks, "failed": failed, "checked_at": time.time()}
    if passed:
        job["status"] = "qc_passed"
        job.pop("error", None)
    else:
        job["status"] = "failed"
        job["error"] = "QC 실패: " + ", ".join(f"{c['name']}({c['detail']})" for c in checks if c["passed"] is False)
    save_job(job)
    return job


# ── 렌더 후 리뷰 (U-4) ────────────────────────────────────────────────────────

REVIEW_OVERRIDE_MIN_CHARS = 5      # "그래도 진행" 사유 최소 글자 수


def run_review(job: dict, runner=subprocess.run) -> dict:
    """렌더 결과로 확인 시트 3장·지적을 만들어 job["review"] 에 넣는다(비용 0, ffmpeg 만).

    QC 를 통과했는데 리뷰에 P0 가 있으면 상태를 needs_review 로 둔다(발행 잠금). 다시 돌리면 이전 "그래도 진행" 기록은 지운다.
    """
    sid = _safe_id(job["shorts_id"])
    review = shorts_review.review_render(job, producer.ffmpeg_path(), job_dir(sid, create=True), f"/data/shorts/{sid}", runner=runner)
    job["review"] = review
    if job.get("status") in ("qc_passed", "needs_review"):
        job["status"] = "needs_review" if review["needs_review"] else "qc_passed"
    save_job(job)
    return job


def override_review(job: dict, reason: str) -> dict:
    """리뷰 P0 를 알고도 진행한다 — 사유를 남기고 qc_passed 로 돌린다."""
    reason = (reason or "").strip()
    if job.get("status") != "needs_review":
        raise ValueError("검토 필요 상태가 아닙니다.")
    if len(reason) < REVIEW_OVERRIDE_MIN_CHARS:
        raise ValueError(f"진행 사유를 {REVIEW_OVERRIDE_MIN_CHARS}자 이상 적어 주세요.")
    job.setdefault("review", {})["override"] = {"reason": reason[:300], "at": time.time()}
    job["status"] = "qc_passed"
    save_job(job)
    return job


def publish_allowed(job: dict) -> tuple:
    """발행(S-3·S-6)해도 되는지와 이유. QC 통과 + 렌더 후 리뷰 P0 없음(또는 사유를 남기고 진행)일 때만 True."""
    if not (job.get("qc") or {}).get("passed"):
        return False, "QC 를 통과하지 않았습니다."
    review = job.get("review")
    if not review:
        return False, "렌더 후 리뷰가 없습니다 — 리뷰를 먼저 돌리세요."
    if review.get("needs_review") and not review.get("override"):
        p0 = [f["message"] for f in review.get("findings") or [] if f.get("level") == "P0"]
        return False, "렌더 후 리뷰 P0: " + " / ".join(p0[:3])
    if job.get("status") != "qc_passed":
        return False, f"상태가 {job.get('status')} 입니다."
    return True, ""


# ── 빌드 오케스트레이션 (API 워커가 호출) ─────────────────────────────────────

def build_job(job: dict, options: Optional[dict] = None, progress_cb: Optional[Callable] = None, **hooks) -> dict:
    """이미지(0~40%) → 음성/자막(40~60%) → 렌더(60~97%) → 음량·QC(97~100%). 실패하면 status=failed + error 를 남기고 잡을 돌려준다.

    hooks: 테스트용 주입 — generator(이미지), synth/merger/bgm_picker(오디오), renderer_fn(렌더), measurer(음량), qc_kwargs.
    """
    opts = options or {}

    def step(stage, msg, pct):
        job["progress"] = {"stage": stage, "message": msg, "percent": int(pct), "at": time.time()}
        if progress_cb:
            progress_cb(stage, msg, int(pct))

    def scaled(stage):
        lo, hi = SHORTS_PROGRESS_SPAN[stage]
        return lambda _s, msg, pct: step(stage, msg, lo + (hi - lo) * max(0, min(100, int(pct or 0))) / 100.0)

    try:
        job["status"] = "assets"
        job.pop("error", None)
        save_job(job)
        est = estimate_images(job)
        if est["needed"] > 0:
            if not opts.get("confirm"):
                raise RuntimeError(f"Gemini 이미지 {est['needed']}장 생성에는 confirm=true 가 필요합니다 (예상 ${est['usd']}).")
            step("images", f"이미지 {est['needed']}장 생성 시작 (오늘 {est['usage']['today']}/{est['usage']['cap']})", 0)
            generate_job_images(job, progress_cb=scaled("images"), generator=hooks.get("generator"))
        else:
            step("images", f"기존 이미지 {est['reused']}장 재사용 (생성 비용 없음)", 40)
        ensure_emphasis(job, llm=hooks.get("emphasis_llm"))
        assign_transitions(job)
        synthesize_job_audio(job, voice_id=opts.get("voice_id"), progress_cb=scaled("audio"),
                             synth=hooks.get("synth"), merger=hooks.get("merger"), bgm_picker=hooks.get("bgm_picker"),
                             lufs_probe=hooks.get("lufs_probe"))
        refresh_lint(job)   # 실제 발화 타이밍(자막)이 생긴 뒤 다시 검사 — 경고만, 빌드는 계속
        render_fn = hooks.get("renderer_fn") or render_shorts
        render_fn(job, renderer=opts.get("renderer"), progress_cb=scaled("render"))
        step("render", "음량 측정·보정...", 97)
        normalize_loudness(job, measurer=hooks.get("measurer"))
        step("qc", "QC 검사...", 98)
        qc_job(job, **(hooks.get("qc_kwargs") or {}))
        if job.get("status") == "qc_passed":
            step("qc", "렌더 후 리뷰 (확인 시트)...", 99)
            run_review(job, **({"runner": hooks["review_runner"]} if hooks.get("review_runner") else {}))
        msg = {"qc_passed": "QC·리뷰 통과 — 쇼츠 완성", "needs_review": "QC 통과 · 렌더 후 리뷰 검토 필요"}.get(job.get("status"))
        step("qc", msg or (job.get("error") or "QC 실패"), 100)
        save_job(job)   # 마지막 진행률(100%)까지 job.json 에 남긴다 — UI 폴링이 이 값을 읽는다
    except Exception as e:
        job["status"] = "failed"
        job["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        step(job.get("progress", {}).get("stage") or "build", job["error"], job.get("progress", {}).get("percent") or 0)
        save_job(job)
    return job
