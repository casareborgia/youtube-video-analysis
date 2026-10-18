"""쇼츠(9:16) 엔진 — S-1: Remotion `ShortsScene` 렌더 래퍼 + ffmpeg 폴백 + 프로브.

작업계획서_쇼츠_자동화_Shorts_Reels.md 7장 S-1 범위만 담는다.
잡 생성(씬 기획 → 잡)·TTS 단어 타이밍·이미지 생성·발행은 S-2/S-3 에서 이 모듈에 추가된다.

설계 원칙 (choonsik_bga.render_bga 와 동일):
- 기본 렌더러는 Remotion(SHORTS_RENDERER=remotion), 미설치·실패 시 ffmpeg 로 자동 폴백하고 사유를 기록한다.
- Remotion 은 remotion/public/shorts → data/shorts 심볼릭 링크로만 파일을 읽으므로 잡 폴더 밖의 자산은 안으로 복사한다.
- 출력은 항상 data/shorts/<shorts_id>/final_9x16.mp4 이며, 기존 파일을 덮어쓰기 전에 백업하지 않는다(쇼츠는 재생성 비용이 낮다).
"""

import json
import os
import re
import shutil
import subprocess
import time
from typing import Callable, List, Optional

import producer  # ffmpeg_path(drawtext 지원 바이너리 우선), audio_duration, find_font

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
SCENE_KINDS = ("image", "text_card", "stat_card", "bar_chart", "compare")
SCENE_KIND_FIELDS = ("palette", "title", "subtitle", "value", "unit", "prefix", "decimals", "label", "bars", "rows")
FALLBACK_PALETTE = ("0x1b2a4a", "0x3a1f4f", "0x0f3d3e", "0x4a2a1b", "0x1f3f2a", "0x2b1b4a")

DEFAULT_ACCENT = "#ffd166"
DEFAULT_BGM_VOLUME = 0.16
DEFAULT_TRANSITION = 0.4

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
        "endTag": ({"text": tag.get("text", ""), "subtext": tag.get("subtext", ""), "seconds": float(tag.get("seconds") or 2.0)} if tag else None),
        "captions": [
            {k: v for k, v in c.items() if k in ("text", "startMs", "endMs", "pageBreakAfter")}
            for c in (job.get("captions") or [])
        ],
        "captionPageMs": int(job.get("caption_page_ms") or 1200),
        "narrationAudio": _ensure_in_job_dir(shorts_id, narration, "narration") if narration else None,
        "bgmAudio": _ensure_in_job_dir(shorts_id, bgm, "bgm") if bgm else None,
        "bgmVolume": float(audio.get("bgm_volume") if audio.get("bgm_volume") is not None else DEFAULT_BGM_VOLUME),
        "accent": job.get("accent") or DEFAULT_ACCENT,
        "brand": job.get("brand") or "",
        "transitionSeconds": float(job.get("transition_seconds") or DEFAULT_TRANSITION),
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
        parts.append(f"[{a_idx['bgm']}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={min(0.5, bgm_vol * 2.2):.3f}[bg]")
        parts.append("[bg][key]sidechaincompress=threshold=0.02:ratio=6:attack=60:release=600:makeup=1[ducked]")
        parts.append("[ducked][nar]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    elif "nar" in a_idx:
        parts.append(f"[{a_idx['nar']}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[a]")
    elif "bgm" in a_idx:
        parts.append(f"[{a_idx['bgm']}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={min(0.5, bgm_vol * 2.2):.3f}[a]")
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
