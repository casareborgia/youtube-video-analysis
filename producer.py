import os
import re
import json
import time
import base64
import shutil
import platform
import subprocess
import urllib.request
import urllib.error

try:
    import dotenv
except ImportError:
    dotenv = None

try:
    import av
except ImportError:
    av = None

import llm_client
import concept_packs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
RENDERS_DIR = os.path.join(DATA_DIR, "renders")
ENV_FILE = os.path.join(BASE_DIR, ".env")
os.makedirs(RENDERS_DIR, exist_ok=True)

# .env 로드
if dotenv and os.path.exists(ENV_FILE):
    dotenv.load_dotenv(ENV_FILE, override=True)


def audio_duration(path):
    """오디오/미디어 파일의 재생 시간(초)을 반환합니다 (av 라이브러리 또는 ffprobe 활용)."""
    if not path or not os.path.exists(path):
        return None
    if av is not None:
        try:
            container = av.open(path)
            dur = None
            if container.duration:
                dur = container.duration / av.time_base
            elif container.streams.audio and container.streams.audio[0].duration:
                stream = container.streams.audio[0]
                if stream.duration and stream.time_base:
                    dur = float(stream.duration * stream.time_base)
            container.close()
            if dur:
                return round(dur, 2)
        except Exception:
            pass

    # ffprobe fallback
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        try:
            cmd = [
                ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return round(float(res.stdout.strip()), 2)
        except Exception:
            pass
    return None
if os.path.exists(ENV_FILE):
    dotenv.load_dotenv(ENV_FILE, override=True)

FPS = 30
SCENE_SECONDS = 8.0
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
RESOLUTIONS = {
    "16:9": {"1080p": (1920, 1080), "720p": (1280, 720), "360p": (640, 360)},
    "9:16": {"1080p": (1080, 1920), "720p": (720, 1280), "360p": (360, 640)},
}

# 9강 모델 규격
IMAGE_MODEL = "nano-banana-pro-preview"  # 나노바나나 프로
FALLBACK_IMAGE_MODELS = ["gemini-2.5-flash-image", "imagen-3.0-generate-002"]
VIDEO_MODEL = "gemini-omni-1.1-flash"     # Omni 1.1 Flash (10초 단위 영상 생성)

# 렌더 톤은 컨셉 팩에서 가져온다 (지정 텍스트 외 글자 금지는 프롬프트 constraints 가 담당)
STYLE = concept_packs.render_style()
AUDIO_RULE = "효과음만, 나레이션 없음, 음악 없음"

GEMINI_REST_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_INTERACTION_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


# ── 환경 및 API 키 관리 ───────────────────────────────────────────────────

_FFMPEG_CACHE = {}


def _ffmpeg_has_drawtext(exe):
    """자막·플레이스홀더 렌더에 필수인 drawtext 필터 지원 여부."""
    if exe in _FFMPEG_CACHE:
        return _FFMPEG_CACHE[exe]
    ok = False
    try:
        out = subprocess.run([exe, "-hide_banner", "-filters"],
                             capture_output=True, text=True, timeout=20).stdout
        ok = any(len(parts) > 1 and parts[1] == "drawtext"
                 for parts in (l.split() for l in out.splitlines()))
    except Exception:
        ok = False
    _FFMPEG_CACHE[exe] = ok
    return ok


def ffmpeg_path():
    """drawtext 를 지원하는 ffmpeg 를 우선 고른다.

    libfreetype 없이 빌드된 ffmpeg 가 PATH 에 있으면 자막 번인과 플레이스홀더가
    'No such filter: drawtext' 로 실패한다. PATH 의 첫 바이너리를 무조건 쓰지 않고
    필요한 필터를 갖춘 쪽을 선택하며, 둘 다 없으면 있는 것이라도 반환한다.
    """
    candidates = []
    exe = shutil.which("ffmpeg")
    if exe:
        candidates.append(exe)
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and bundled not in candidates:
            candidates.append(bundled)
    except Exception:
        pass

    for c in candidates:
        if _ffmpeg_has_drawtext(c):
            return c
    return candidates[0] if candidates else None


def find_font():
    """자막 굽기용 한글 폰트 파일."""
    candidates = {
        "Darwin": [
            "/Library/Fonts/NanumGothicBold.ttf", os.path.expanduser("~/Library/Fonts/NanumGothicBold.ttf"),
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
            "/Library/Fonts/NanumGothic.ttf",
            os.path.expanduser("~/Library/Fonts/NanumGothic.ttf"),
        ],
        "Windows": [
            "C:/Windows/Fonts/malgunbd.ttf",
            "C:/Windows/Fonts/malgun.ttf",
            "C:/Windows/Fonts/NanumGothic.ttf",
        ],
        "Linux": [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ],
    }.get(platform.system(), [])
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def gemini_key():
    """우선순위: 환경변수 > .env 파일 > settings.json"""
    if os.path.exists(ENV_FILE):
        dotenv.load_dotenv(ENV_FILE, override=False)
    k = (os.environ.get("GEMINI_API_KEY") or llm_client._load_settings().get("gemini_api_key") or "").strip()
    return k


def set_gemini_key(key):
    """API 키를 .env 파일과 settings.json, os.environ에 모두 동기화하여 저장합니다."""
    key = (key or "").strip()
    # 1. settings.json 저장
    s = llm_client._load_settings()
    s["gemini_api_key"] = key
    llm_client._save_settings(s)

    # 2. os.environ 동기화
    if key:
        os.environ["GEMINI_API_KEY"] = key
    else:
        os.environ.pop("GEMINI_API_KEY", None)

    # 3. .env 파일 동기화
    lines = []
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []

    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("GEMINI_API_KEY="):
            if key:
                new_lines.append(f"GEMINI_API_KEY={key}\n")
            found = True
        else:
            new_lines.append(line)
    if not found and key:
        new_lines.append(f"GEMINI_API_KEY={key}\n")

    try:
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"Warning: Failed to write .env file: {e}")


def get_genai_client(api_key=None):
    """Google GenAI SDK Client 인스턴스를 반환합니다."""
    key = api_key or gemini_key()
    if not key:
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다. ③ 탭의 '환경' 영역에서 키를 저장해주세요.")
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:
        raise RuntimeError(f"Google GenAI SDK 초기화 실패: {e}")


def validate_gemini_key(key=None):
    """키가 실제로 통하는지 모델 목록 조회로 확인. (valid, message)"""
    key = (key or gemini_key() or "").strip()
    if not key:
        return False, "키 없음"
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
        headers={"x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=8):
            return True, "유효한 키"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "인증 실패 — 만료·회수된 키이거나 잘못된 키"
        return False, f"확인 실패 (HTTP {e.code})"
    except Exception as e:
        return None, f"네트워크 오류로 확인 못 함: {str(e)[:60]}"


def environment():
    return {
        "ffmpeg": bool(ffmpeg_path()),
        "font": find_font(),
        "gemini_key_set": bool(gemini_key()),
        "has_env_file": os.path.exists(ENV_FILE),
        "env_path": ENV_FILE if os.path.exists(ENV_FILE) else None,
    }


# ── 비용 계산기 (9강 공식 기준) ──────────────────────────────────────────

def estimate_costs(num_scenes, quality="360p"):
    """
    공식 가격: 720p 영상 1초에 약 $0.10, 360p는 1/3.
    Omni는 한 번에 10초 생성.
    """
    sec_per_scene = 10
    usd_per_sec_720p = 0.10
    ratio = {"360p": 1 / 3, "720p": 1.0, "1080p": 1.0}
    usd_krw = 1400

    q_ratio = ratio.get(quality, 1 / 3)
    usd = num_scenes * sec_per_scene * usd_per_sec_720p * q_ratio
    krw = usd * usd_krw
    return {
        "scenes": num_scenes,
        "seconds_total": num_scenes * sec_per_scene,
        "quality": quality,
        "usd": round(usd, 2),
        "krw": int(round(krw, -1)),
        "rate_per_sec_usd": round(usd_per_sec_720p * q_ratio, 3),
    }


# ── 씬 미디어 관리 ────────────────────────────────────────────────────────

def _safe(plan_id):
    return re.sub(r'[\/\\:*?"<>|]', "_", plan_id or "")[:80] or "plan"


def render_dir(plan_id):
    d = os.path.join(RENDERS_DIR, _safe(plan_id))
    os.makedirs(d, exist_ok=True)
    return d


def _media_index_path(plan_id):
    return os.path.join(render_dir(plan_id), "media.json")


def list_media(plan_id):
    try:
        with open(_media_index_path(plan_id), encoding="utf-8") as f:
            idx = json.load(f)
    except Exception:
        idx = {}
    d = render_dir(plan_id)
    return {k: v for k, v in idx.items() if os.path.exists(os.path.join(d, v.get("file", "")))}


def _save_index(plan_id, idx):
    with open(_media_index_path(plan_id), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def _first_frame_path(d, slot, item):
    """슬롯의 첫 프레임 이미지 경로. 슬롯이 영상이면 보존된 image_file 또는 같은 번호의 이미지 파일을 찾습니다."""
    if item and item.get("type") == "image":
        pth = os.path.join(d, item["file"])
        return pth if os.path.exists(pth) else None
    if item and item.get("image_file"):
        pth = os.path.join(d, item["image_file"])
        if os.path.exists(pth):
            return pth
    if slot != "thumbnail":
        try:
            base = "scene_%02d" % int(slot)
        except Exception:
            return None
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            pth = os.path.join(d, base + ext)
            if os.path.exists(pth):
                return pth
    return None


def media_url(plan_id, item):
    return f"/data/renders/{_safe(plan_id)}/{item['file']}"


def save_media(plan_id, slot, filename, data_bytes, source="upload", media_type=None):
    """slot: '1'..'N' 또는 'thumbnail'. 이미지/영상 확장자만 허용."""
    slot = str(slot)
    ext = os.path.splitext(filename or "")[1].lower()
    if not ext:
        ext = ".mp4" if media_type == "video" else ".png"

    if ext in IMAGE_EXTS or media_type == "image":
        kind = "image"
        if ext not in IMAGE_EXTS:
            ext = ".png"
    elif ext in VIDEO_EXTS or media_type == "video":
        kind = "video"
        if ext not in VIDEO_EXTS:
            ext = ".mp4"
    else:
        raise ValueError("이미지(png/jpg/webp) 또는 영상(mp4/mov/webm) 파일만 넣을 수 있습니다.")

    if slot == "thumbnail" and kind != "image":
        raise ValueError("썸네일은 이미지 파일이어야 합니다.")

    d = render_dir(plan_id)
    idx = list_media(plan_id)
    old = idx.get(slot)
    if old:
        try:
            os.remove(os.path.join(d, old["file"]))
        except Exception:
            pass

    fname = f"{'thumbnail' if slot == 'thumbnail' else 'scene_%02d' % int(slot)}{ext}"
    with open(os.path.join(d, fname), "wb") as f:
        f.write(data_bytes)
    idx[slot] = {"file": fname, "type": kind, "source": source}
    _save_index(plan_id, idx)
    return {"slot": slot, "type": kind, "source": source, "url": media_url(plan_id, idx[slot])}


def delete_media(plan_id, slot):
    """영상을 지우면 보존된 첫 프레임 이미지로 되돌아가고, 이미지를 지우면 슬롯이 비워집니다."""
    idx = list_media(plan_id)
    slot = str(slot)
    item = idx.pop(slot, None)
    if item:
        try:
            os.remove(os.path.join(render_dir(plan_id), item["file"]))
        except Exception:
            pass
        img = _first_frame_path(render_dir(plan_id), slot, item) if item.get("type") == "video" else None
        if img:
            idx[slot] = {"file": os.path.basename(img), "type": "image", "source": item.get("image_source") or "gemini"}
    _save_index(plan_id, idx)


def media_view(plan_id):
    d = render_dir(plan_id)
    out = {}
    for slot, it in list_media(plan_id).items():
        img = _first_frame_path(d, slot, it)
        out[slot] = {"type": it["type"], "url": media_url(plan_id, it), "source": it.get("source", "upload"), "file": it.get("file"),
                     "trim_start": it.get("trim_start", 0), "quality": it.get("quality"),
                     "image_url": (f"/data/renders/{_safe(plan_id)}/{os.path.basename(img)}" if img else None)}
    return out


# ── 나노바나나(Gemini) 이미지 생성 ────────────────────────────────────────

def _redline_prompt_text(block):
    """레드라인 JSON 프롬프트를 이미지 모델용 지시문으로 감쌉니다."""
    return (
        "Generate a single image following this JSON specification exactly. "
        "Render every string in text_layer verbatim in Korean with correct spelling, add no other text or letters. "
        "Red engineering annotation overlay must point at the described targets.\n\n"
        + json.dumps(block, ensure_ascii=False, indent=2)
    )


def _generate_single_image(prompt_text, aspect_ratio, api_key):
    """
    1차: google-genai SDK의 nano-banana-pro-preview 모델 호출
    2차: 폴백 모델 또는 REST API 호출
    """
    last_err = None
    # 1차 시도: SDK
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        for m in [IMAGE_MODEL] + FALLBACK_IMAGE_MODELS:
            try:
                res = client.models.generate_content(
                    model=m,
                    contents=prompt_text,
                    config=types.GenerateContentConfig(
                        image_config=types.ImageConfig(aspect_ratio=aspect_ratio)
                    ),
                )
                for cand in res.candidates or []:
                    content = getattr(cand, "content", None)
                    if not content:
                        continue
                    for part in getattr(content, "parts", []):
                        inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
                        if inline and getattr(inline, "data", None):
                            data_val = inline.data
                            raw_bytes = base64.b64decode(data_val) if isinstance(data_val, str) else data_val
                            mime = getattr(inline, "mime_type", None) or getattr(inline, "mimeType", None) or "image/png"
                            return raw_bytes, mime
            except Exception as inner_e:
                last_err = inner_e
                print(f"Model {m} SDK image gen attempt failed: {inner_e}")
                if "UNAUTHENTICATED" in str(inner_e) or "API_KEY_INVALID" in str(inner_e):
                    break  # 키 문제면 다른 모델을 시도해도 소용없음
                continue
    except Exception as sdk_err:
        print(f"GenAI SDK not available or failed, falling back to REST: {sdk_err}")

    # 2차 시도: REST API
    for m in [IMAGE_MODEL] + FALLBACK_IMAGE_MODELS:
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
        }
        req = urllib.request.Request(
            GEMINI_REST_URL.format(model=m),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                res = json.load(r)
            for cand in res.get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        return base64.b64decode(inline["data"]), inline.get("mimeType") or inline.get("mime_type") or "image/png"
        except Exception as rest_err:
            last_err = rest_err
            print(f"REST attempt on {m} failed: {rest_err}")
            if "401" in str(rest_err):
                break
            continue

    if last_err is not None:
        raise RuntimeError(_friendly_gemini_error(str(last_err)))
    raise RuntimeError("Gemini가 이미지를 반환하지 않았습니다 (안전 필터 또는 프롬프트 문제일 수 있습니다).")


def generate_images(plan, slots=None, progress=None):
    """미디어가 없는 씬(및 썸네일)의 레드라인 프롬프트로 이미지를 생성합니다."""
    key = gemini_key()
    if not key:
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다. ③ 탭의 '환경' 영역에서 키를 저장해주세요.")
    plan_id = plan["plan_id"]
    aspect = plan.get("aspect_ratio") or "16:9"
    idx = list_media(plan_id)
    scenes = plan.get("structured_scenes") or []
    targets = [str(s) for s in slots] if slots else [str(s["scene_num"]) for s in scenes] + ["thumbnail"]
    targets = [t for t in targets if t not in idx or (slots and idx[t].get("type") == "video" and not _first_frame_path(d, t, idx[t]))]
    done, errors = [], []
    d = render_dir(plan_id)

    for n, slot in enumerate(targets, 1):
        if progress:
            progress("images", f"이미지 생성 {n}/{len(targets)} — {'썸네일' if slot == 'thumbnail' else '씬 ' + slot}", int(5 + 90 * (n - 1) / max(1, len(targets))))
        if slot == "thumbnail":
            block = plan.get("thumbnail_prompt")
        else:
            sc = next((s for s in scenes if str(s.get("scene_num")) == slot), None)
            block = (sc or {}).get("image_prompt_json")
            if not block and sc:
                block = {
                    "scene": {"subject": sc.get("visual_prompt") or sc.get("subtitle") or "장면"},
                    "annotation_layer": [{"type": "leader_line", "target": "주요지점", "label": "포인트"}],
                    "text_layer": []
                }
        if not block:
            errors.append({"slot": slot, "error": "프롬프트 없음"})
            continue
        try:
            prompt = f"{STYLE}. {_redline_prompt_text(block)}"
            data, mime = _generate_single_image(prompt, aspect, key)
            ext = ".jpg" if "jpeg" in mime else ".png"
            fname = f"{'thumbnail' if slot == 'thumbnail' else 'scene_%02d' % int(slot)}{ext}"
            with open(os.path.join(d, fname), "wb") as f:
                f.write(data)
            idx = list_media(plan_id)
            if idx.get(slot, {}).get("type") == "video":
                idx[slot]["image_file"] = fname          # 영상은 유지하고 첫 프레임 이미지만 보강
                idx[slot]["image_source"] = "gemini"
            else:
                idx[slot] = {"file": fname, "type": "image", "source": "gemini"}
            _save_index(plan_id, idx)
            done.append(slot)
        except Exception as e:
            raw = str(e)
            errors.append({"slot": slot, "error": _friendly_gemini_error(raw)})
            if _is_daily_quota(raw):
                remaining = [t2 for t2 in targets[n:]]
                if remaining:
                    errors.append({"slot": ", ".join(remaining), "error": "한도 초과로 시도하지 않음"})
                break

    return {"generated": done, "errors": errors, "media": media_view(plan_id)}


# ── Omni 1.1 Flash 비디오 생성 (9강 연동) ──────────────────────────────────
# 규격: google-genai >= 2.0 (Python 3.10+). client.interactions.create(model, input, response_format[, previous_interaction_id])
#      → Interaction(id, status, output_video{data|uri}). 이어붙이기(previous_interaction_id)는 앞 장면을 포함한
#      "누적 영상"을 돌려주므로 씬 k 파일에서 (k-1)*10초 이후 구간만 씁니다(trim_start). 체인은 40초(4장면)까지.

OMNI_SECONDS = 10
OMNI_CHAIN_MAX = 4
OMNI_TIMEOUT = 900          # 초 — 장면당 1~2분, 여유 있게
OMNI_POLL_INTERVAL = 5


def _genai_version():
    try:
        import google.genai as g
        return g.__version__
    except Exception:
        return None


def _omni_client(api_key):
    """SDK 2.x 클라이언트. 구버전이면 None (REST 경로 사용)."""
    ver = _genai_version()
    if not ver or int(ver.split(".")[0]) < 2:
        return None
    from google import genai
    return genai.Client(api_key=api_key)


def _sdk_requirement_hint():
    ver = _genai_version() or "미설치"
    return (f"google-genai {ver} — Omni 영상 생성에는 2.0 이상이 필요합니다(Python 3.10+). "
            "프로젝트 폴더의 .venv로 서버를 실행하세요: `.venv/bin/python server.py` (run.command / run.bat 이 자동으로 처리)")


def _friendly_gemini_error(msg):
    """구글 API 오류를 짧은 한국어로. (원문은 로그에 남음)"""
    m = str(msg)
    if "requests_per_model_per_day" in m or "PerDay" in m:
        return ("일일 생성 한도 초과 — 이 모델은 하루 요청 횟수 제한이 있습니다(무료·1단계 등급 기준 20회). "
                "한도는 매일 오후 4~5시(한국 시간)에 초기화됩니다. 그때 다시 시도하거나, "
                "Google AI Studio에서 사용 등급(Tier) 상향을 신청하세요.")
    if "spending cap" in m:
        return "월 지출 한도 초과 — https://ai.studio/spend 에서 한도를 올려주세요."
    if "prepayment credits" in m or "Prepayment" in m:
        return ("이 API 키의 프로젝트는 선불(Prepay) 방식인데 크레딧이 소진되었습니다. "
                "https://ai.studio/projects 에서 충전하거나, 후불 결제가 연결된 프로젝트(예: Gemini Project)에서 키를 발급해 사용하세요.")
    if "RESOURCE_EXHAUSTED" in m or "429" in m:
        if "per_minute" in m or "PerMinute" in m:
            return "분당 요청 한도 초과 — 1~2분 뒤 다시 시도하세요."
        return "요청 한도 초과(429) — 잠시 후 다시 시도하거나 https://ai.dev/rate-limit 에서 사용량을 확인하세요."
    if "API key not valid" in m or "API_KEY_INVALID" in m or "UNAUTHENTICATED" in m or "'code': 401" in m or '"code": 401' in m:
        return ("Gemini API 키가 만료되었거나 회수되었습니다 (401). Google AI Studio(aistudio.google.com)에서 "
                "새 키를 발급받아 ③ 탭 환경 설정에 저장하세요.")
    if "SAFETY" in m or "blocked" in m.lower():
        return "안전 필터에 걸렸습니다 — 프롬프트의 표현을 조금 바꿔 다시 시도하세요."
    return m[:300]


def _is_daily_quota(msg):
    return "requests_per_model_per_day" in str(msg) or "spending cap" in str(msg)


def _find_video_block(obj):
    """SDK 객체 또는 REST JSON에서 type=video 인 출력(data/uri)을 찾습니다."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        if obj.get("type") == "video" and (obj.get("data") or obj.get("uri")):
            return obj
        for key in ("output_video", "outputVideo"):
            if isinstance(obj.get(key), dict):
                return obj[key]
        for key in ("outputs", "output", "content", "contents", "parts"):
            v = obj.get(key)
            if isinstance(v, list):
                for it in v:
                    hit = _find_video_block(it)
                    if hit:
                        return hit
            elif isinstance(v, dict):
                hit = _find_video_block(v)
                if hit:
                    return hit
        return None
    ov = getattr(obj, "output_video", None)
    if ov is not None and (getattr(ov, "data", None) or getattr(ov, "uri", None)):
        return {"data": getattr(ov, "data", None), "uri": getattr(ov, "uri", None), "mime_type": getattr(ov, "mime_type", None)}
    outputs = getattr(obj, "outputs", None) or []
    for it in outputs:
        if getattr(it, "type", None) == "video" and (getattr(it, "data", None) or getattr(it, "uri", None)):
            return {"data": getattr(it, "data", None), "uri": getattr(it, "uri", None), "mime_type": getattr(it, "mime_type", None)}
    return None


def _interaction_errors(obj):
    errs = obj.get("errors") if isinstance(obj, dict) else getattr(obj, "errors", None)
    if not errs:
        return ""
    msgs = []
    for e in errs:
        m = e.get("message") if isinstance(e, dict) else getattr(e, "message", None)
        msgs.append(str(m or e))
    return "; ".join(msgs)[:300]


def _status_of(obj):
    return (obj.get("status") if isinstance(obj, dict) else getattr(obj, "status", None)) or ""


def _id_of(obj):
    return (obj.get("id") if isinstance(obj, dict) else getattr(obj, "id", None)) or None


def _rest_json(url, api_key, payload=None, timeout=OMNI_TIMEOUT):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:400]
        try:
            body = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            pass
        raise RuntimeError(f"Gemini Interactions API 오류 (HTTP {e.code}): {body}") from e


def _create_interaction(client, api_key, payload):
    """SDK(2.x) 또는 REST로 인터랙션 생성. (응답 객체/딕셔너리) 반환."""
    if client is not None:
        return client.interactions.create(timeout=OMNI_TIMEOUT, **payload)
    return _rest_json(GEMINI_INTERACTION_URL, api_key, payload)


def _get_interaction(client, api_key, iid):
    if client is not None:
        return client.interactions.get(iid, timeout=120)
    return _rest_json(f"{GEMINI_INTERACTION_URL}/{iid}", api_key, timeout=120)


def _wait_interaction(client, api_key, r, progress=None, label=""):
    """status 가 queued/in_progress 이면 완료될 때까지 폴링."""
    started = time.time()
    while _status_of(r) in ("queued", "in_progress") and time.time() - started < OMNI_TIMEOUT:
        iid = _id_of(r)
        if not iid:
            break
        if progress:
            progress("videos", f"{label} 생성 중… ({int(time.time() - started)}초 경과)", None)
        time.sleep(OMNI_POLL_INTERVAL)
        r = _get_interaction(client, api_key, iid)
    return r


def _download_video_output(client, api_key, block, out_path):
    data = block.get("data")
    if data:
        video_bytes = base64.b64decode(data) if isinstance(data, str) else bytes(data)
        with open(out_path, "wb") as f:
            f.write(video_bytes)
        return
    uri = block.get("uri")
    if not uri:
        raise RuntimeError("영상 데이터도 다운로드 URI도 없습니다.")
    if client is not None:
        fid = uri.rstrip("/").split("/")[-1]
        for _ in range(90):
            try:
                info = client.files.get(name=f"files/{fid}")
                state = getattr(getattr(info, "state", None), "name", None) or str(getattr(info, "state", ""))
                if "ACTIVE" in state:
                    break
            except Exception:
                pass
            time.sleep(4)
        downloaded = client.files.download(file=uri)
        with open(out_path, "wb") as f:
            f.write(downloaded)
        return
    req = urllib.request.Request(uri if "alt=media" in uri else (uri + ("&" if "?" in uri else "?") + "alt=media"),
                                 headers={"x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=600) as r, open(out_path, "wb") as f:
        shutil.copyfileobj(r, f)


def generate_videos(plan, quality="360p", slots=None, chain=True, skip_existing=True, progress=None):
    """
    9강 영상 생성 자동화 (Omni 1.1 Flash):
    - 각 장면의 첫 프레임 이미지 + 영상 프롬프트로 10초 클립 생성
    - chain=True 이면 다음 장면은 previous_interaction_id 로 앞 장면을 이어받음 (누적 영상 → trim_start 로 구간 지정, 4장면마다 새 체인)
    - 장면 하나가 실패해도 나머지는 계속 (실패 원인은 errors 에 그대로 기록)
    """
    key = gemini_key()
    if not key:
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다. ③ 탭의 '환경' 영역에서 키를 저장해주세요.")
    client = _omni_client(key)
    if client is None:
        print("⚠️ " + _sdk_requirement_hint() + " — REST 경로로 시도합니다.")

    plan_id = plan["plan_id"]
    aspect = plan.get("aspect_ratio") or "16:9"
    quality = quality if quality in ("360p", "720p", "1080p") else "360p"
    scenes = plan.get("structured_scenes") or []
    if not scenes:
        raise RuntimeError("기획서에 씬 데이터가 없습니다.")
    d = render_dir(plan_id)

    idx = list_media(plan_id)
    skipped = []
    if slots:
        targets = [int(s) for s in slots]                      # 명시한 씬은 이미 영상이 있어도 다시 만듦("이 씬만 다시")
    else:
        targets = []
        for i, s in enumerate(scenes, 1):
            n = int(s.get("scene_num", i))
            if skip_existing and idx.get(str(n), {}).get("type") == "video":
                skipped.append(n)                              # 이미 AI 영상이 있음 → 과금 방지를 위해 건너뜀
            else:
                targets.append(n)
    target_scenes = [sc for sc in scenes if int(sc.get("scene_num", 0)) in targets]
    if not target_scenes:
        return {"generated": [], "skipped": skipped, "errors": [], "quality": quality, "chain": chain, "media": media_view(plan_id)}

    # 첫 프레임 이미지가 없는 장면만 먼저 생성 (있는 이미지는 재생성하지 않음)
    for sc in target_scenes:
        slot = str(int(sc["scene_num"]))
        if not _first_frame_path(d, slot, idx.get(slot)):
            if progress:
                progress("videos", f"씬 {slot} 첫 프레임 이미지 생성 중...", 5)
            res = generate_images(plan, slots=[slot])
            idx = list_media(plan_id)
            if slot not in idx:
                err = next((e["error"] for e in res.get("errors", []) if e["slot"] == slot), "이미지 생성 실패")
                print(f"씬 {slot} 이미지 없음: {err}")

    done, errors = [], []
    prev_id, chain_pos, last_num = None, 0, None
    fmt = {"type": "video", "resolution": quality, "aspect_ratio": aspect}

    for i, sc in enumerate(target_scenes, 1):
        num = int(sc["scene_num"])
        slot = str(num)
        # 바로 앞 씬이 이번 실행에서 만들어지지 않았다면, 저장된 앞 씬 영상의 interaction_id 로 체인을 이어감
        if chain and last_num != num - 1:
            prev_item = idx.get(str(num - 1)) or {}
            if prev_item.get("type") == "video" and prev_item.get("interaction_id") and int(prev_item.get("chain_pos", 0)) < OMNI_CHAIN_MAX - 1:
                prev_id, chain_pos = prev_item["interaction_id"], int(prev_item.get("chain_pos", 0)) + 1
            else:
                prev_id, chain_pos = None, 0
        label = f"씬 {num}/{len(target_scenes)}"
        pct = int(10 + 85 * (i - 1) / max(1, len(target_scenes)))
        if progress:
            progress("videos", f"{label} AI 영상 생성 중 ({quality})… 1~2분 소요", pct)

        text = f"{sc.get('visual_prompt') or sc.get('prompt_en') or sc.get('subtitle') or 'Cinematic documentary shot'} {AUDIO_RULE}"
        item = idx.get(slot)
        img_path = _first_frame_path(d, slot, item)
        use_chain = chain and prev_id is not None and chain_pos < OMNI_CHAIN_MAX

        try:
            if use_chain:
                payload = {"model": VIDEO_MODEL, "previous_interaction_id": prev_id,
                           "input": [{"type": "text", "text": text}], "response_format": fmt}
            else:
                if not img_path or not os.path.exists(img_path):
                    raise RuntimeError("첫 프레임 이미지가 없습니다. 먼저 이미지를 생성하거나 넣어주세요.")
                with open(img_path, "rb") as f:
                    frame_b64 = base64.b64encode(f.read()).decode("utf-8")
                mime = "image/jpeg" if img_path.lower().endswith((".jpg", ".jpeg")) else ("image/webp" if img_path.lower().endswith(".webp") else "image/png")
                payload = {"model": VIDEO_MODEL,
                           "input": [{"type": "image", "data": frame_b64, "mime_type": mime}, {"type": "text", "text": text}],
                           "response_format": fmt}
                prev_id, chain_pos = None, 0

            r = _create_interaction(client, key, payload)
            r = _wait_interaction(client, key, r, progress, label)
            status = _status_of(r)
            if status and status not in ("completed", "incomplete"):
                raise RuntimeError(f"인터랙션 상태 {status}: {_interaction_errors(r) or '상세 없음'}")
            block = _find_video_block(r)
            if not block:
                raise RuntimeError("응답에 영상 출력이 없습니다. " + (_interaction_errors(r) or f"(status={status or '?'})"))

            fname = f"scene_{num:02d}.mp4"
            _download_video_output(client, key, block, os.path.join(d, fname))
            trim_start = chain_pos * OMNI_SECONDS  # 누적 영상에서 이 장면이 시작하는 지점
            idx = list_media(plan_id)
            idx[slot] = {"file": fname, "type": "video", "source": "omni", "trim_start": trim_start,
                         "clip_seconds": OMNI_SECONDS, "quality": quality, "interaction_id": _id_of(r),
                         "chain_pos": chain_pos,
                         "image_file": os.path.basename(img_path) if img_path else None,
                         "image_source": ((item or {}).get("source") if (item or {}).get("type") == "image" else (item or {}).get("image_source")) or "gemini"}
            _save_index(plan_id, idx)
            done.append(slot)
            last_num = num
            prev_id = _id_of(r) if chain else None
            chain_pos = chain_pos + 1 if chain else 0
            if chain_pos >= OMNI_CHAIN_MAX:
                prev_id, chain_pos = None, 0  # 40초 한도 → 다음 장면은 새 체인
        except Exception as e:
            raw = str(e)
            if client is None and "legacy" in raw.lower():
                raw = _sdk_requirement_hint()
            msg = _friendly_gemini_error(raw)
            errors.append({"slot": slot, "error": msg})
            print(f"씬 {num} 영상 생성 실패: {raw[:300]}")
            prev_id, chain_pos, last_num = None, 0, None  # 체인 끊김 → 다음 장면은 자기 이미지로 새로 시작
            if _is_daily_quota(raw):
                remaining = [str(int(s2["scene_num"])) for s2 in target_scenes[i:]]
                if remaining:
                    errors.append({"slot": ", ".join(remaining), "error": "한도 초과로 시도하지 않음 (요청 횟수 절약)"})
                break

    return {"generated": done, "skipped": skipped, "errors": errors, "quality": quality, "chain": chain, "media": media_view(plan_id)}


# ── ffmpeg 합성 및 자막 버닝 ─────────────────────────────────────────────

def _run(cmd, timeout=600):
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        tail = "\n".join((res.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(f"ffmpeg 실패:\n{tail}")
    return res


def _split_phrases(text, max_chars):
    """나레이션을 자막용 짧은 구절로 쪼갭니다 (문장 → 쉼표 → 어절 순, 각 max_chars 이내)."""
    clean = re.sub(r'["“”*_`#\[\]]', "", text or "").strip()
    if not clean:
        return []
    # 문장·쉼표 뒤에서 1차 분할 (구두점은 구절 끝에 유지 — 레퍼런스 스타일)
    parts = re.split(r"(?<=[.?!,])\s+", clean)
    phrases = []
    for part in parts:
        words = part.split()
        cur = ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                phrases.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            phrases.append(cur)
    # 너무 짧은 꼬리 구절은 앞과 병합
    merged = []
    for ph in phrases:
        if merged and len(ph) <= 6 and len(merged[-1]) + len(ph) + 1 <= max_chars + 5:
            merged[-1] += " " + ph
        else:
            merged.append(ph)
    return merged


def _wrap_subtitle(text, max_chars, max_lines=3):
    """자막을 어절 단위로 줄바꿈. 줄 수가 넘치면 글자 수를 늘려 다시 시도(최대 max_lines줄)."""
    clean = re.sub(r'["“”*_`#\[\]]', "", text or "").strip()
    for limit in (max_chars, int(max_chars * 1.25), int(max_chars * 1.5)):
        lines, cur = [], ""
        for w in clean.split():
            if cur and len(cur) + 1 + len(w) > limit:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            return "\n".join(lines)
    return "\n".join(lines[:max_lines])


def _ff_escape(path):
    """drawtext/subtitles 필터 인자용 경로 이스케이프 (콜론·역슬래시·따옴표)."""
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _subtitle_filters(textfile, font, W, H, font_size, n_lines, style="outline"):
    """
    자막 스타일:
    - outline: 흰 볼드 + 두꺼운 검은 외곽선 + 그림자, 밴드 없음 — 화면을 가리지 않는 기본 스타일
    - clean:   하단 반투명 밴드(전체 폭) + 흰 글씨
    - box:     글자 뒤에만 반투명 상자
    """
    line_h = int(font_size * 1.35)
    margin = int(H * 0.07)
    text_h = n_lines * line_h
    common = (f"fontfile='{_ff_escape(font)}':textfile='{_ff_escape(textfile)}':fontsize={font_size}:fontcolor=white:"
              f"line_spacing={int(font_size * 0.35)}:x=(w-text_w)/2:text_align=C")
    if style == "outline":
        return [
            f"drawtext={common}:borderw={max(4, font_size // 6)}:bordercolor=black:"
            f"shadowx={max(2, font_size // 14)}:shadowy={max(2, font_size // 14)}:shadowcolor=black@0.5:y=h-text_h-{margin}",
        ]
    if style == "box":
        return [f"drawtext={common}:borderw={max(2, font_size // 14)}:bordercolor=black@0.85:box=1:boxcolor=black@0.35:"
                f"boxborderw={font_size // 3}:y=h-text_h-{margin}"]
    band_h = text_h + int(font_size * 1.1)
    band_y = H - margin - band_h
    text_y = band_y + int(font_size * 0.55)
    return [
        f"drawbox=x=0:y={band_y}:w={W}:h={band_h}:color=black@0.42:t=fill",
        f"drawtext={common}:borderw={max(2, font_size // 18)}:bordercolor=black@0.55:"
        f"shadowx={max(1, font_size // 22)}:shadowy={max(1, font_size // 22)}:shadowcolor=black@0.6:y={text_y}",
    ]


def _has_audio_stream(path):
    try:
        c = av.open(path)
        ok = len(c.streams.audio) > 0
        c.close()
        return ok
    except Exception:
        return False


def _run(cmd, timeout=900):
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        tail = "\n".join((res.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(f"ffmpeg 실패:\n{tail}")
    return res


def build_video(plan, options=None, progress=None):
    """
    씬별 미디어(AI 영상 클립 / 이미지 켄번즈 / 플레이스홀더) + ②의 나레이션 + 자막 → 씬 mp4 → 크로스페이드 이어붙이기 → final.mp4
    - 영상 클립에 효과음·배경음이 있으면 버리지 않고 나레이션 아래에 덕킹(나레이션 구간 자동 감쇠)해서 섞음
    - 나레이션이 8초를 넘으면(fit_narration) 씬을 그만큼 늘림
    옵션: resolution(1080p/720p/360p), burn_subtitles, subtitle_style(clean/box), fit_narration, transition(fade/none), sfx_volume(0~1)
    """
    options = options or {}
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg를 찾을 수 없습니다. 'pip3 install imageio-ffmpeg'를 실행해주세요.")

    plan_id = plan["plan_id"]
    aspect = plan.get("aspect_ratio") if plan.get("aspect_ratio") in RESOLUTIONS else "16:9"
    W, H = RESOLUTIONS[aspect].get(options.get("resolution") or "1080p", RESOLUTIONS[aspect]["1080p"])
    burn = bool(options.get("burn_subtitles", True))
    sub_style = options.get("subtitle_style") or "outline"
    fit_narration = bool(options.get("fit_narration", True))
    transition = options.get("transition", "fade")
    fade_d = 0.6 if transition in ("fade", "fadeblack") else 0.0
    sfx_volume = float(options.get("sfx_volume", 0.35))
    font = find_font()
    if burn and not font:
        burn = False

    font_size = int(H * (0.040 if aspect == "16:9" else 0.034))
    max_chars = 26 if aspect == "16:9" else 16

    d = render_dir(plan_id)
    work = os.path.join(d, "work")
    os.makedirs(work, exist_ok=True)
    media = list_media(plan_id)

    audio_map = {}
    for sa in ((plan.get("audio_data") or {}).get("scenes_audio") or []):
        if sa.get("audio_file") and os.path.exists(sa["audio_file"]):
            audio_map[int(sa["scene_num"])] = sa["audio_file"]

    scenes = plan.get("structured_scenes") or []
    if not scenes:
        raise RuntimeError("기획서에 씬이 없습니다.")
    base_secs = float(plan.get("scene_seconds") or SCENE_SECONDS)

    scene_files, durations, sub_specs, warnings = [], [], [], []
    for n, sc in enumerate(scenes, 1):
        num = int(sc.get("scene_num", n))
        if progress:
            progress("render", f"씬 {num}/{len(scenes)} 합성 중...", int(5 + 75 * (n - 1) / len(scenes)))
        audio = audio_map.get(num)
        dur = float(sc.get("seconds") or base_secs)
        if audio and fit_narration:
            a_dur = audio_duration(audio) or 0
            if a_dur + 0.25 > dur:
                dur = round(a_dur + 0.45, 2)
                warnings.append(f"씬 {num}: 나레이션이 {a_dur}초라 씬 길이를 {dur}초로 늘렸습니다.")
            elif a_dur > 0 and dur - a_dur > 1.0:
                dur = round(max(a_dur + 0.9, 2.5), 2)  # 무음 꼬리 제거 (여운 0.9초)
        dur = dur + fade_d  # 크로스페이드로 겹치는 만큼 보정 (마지막 씬은 페이드아웃 여유)

        item = media.get(str(num))
        out = os.path.join(work, f"scene_{num:02d}.mp4")
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
        vf = []
        clip_has_audio = False

        if item and item["type"] == "video":
            src_path = os.path.join(d, item["file"])
            ts = float(item.get("trim_start") or 0)
            if ts > 0:
                cmd += ["-ss", f"{ts}"]  # 이어붙인 누적 클립: 이 장면의 시작 지점부터
            cmd += ["-i", src_path]
            src_total = audio_duration(src_path) or float(item.get("clip_seconds") or 10)
            avail = max(src_total - ts, 1.0)
            stretch = ""
            if dur > avail + 0.15:
                # 클립(보통 10초)이 씬보다 짧으면 끝프레임 정지 대신 살짝 슬로모션으로 늘려 채움
                speed = dur / avail
                stretch = f",setpts=PTS*{speed:.4f},fps={FPS}"
                if speed > 1.35:
                    warnings.append(f"씬 {num}: 클립({avail:.1f}초)이 씬({dur:.1f}초)보다 많이 짧아 {speed:.2f}배 슬로모션으로 늘렸습니다.")
            # 영상 씬에도 미세한 푸시인(6%)을 얹음 — 내용이 정지된 클립도 재생성 비용 없이 살아 움직임
            v_frames = int(dur * FPS) + 1
            push = f"zoompan=z='1+0.06*on/{v_frames}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}"
            vf.append(f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}{stretch},"
                      f"tpad=stop_mode=clone:stop_duration={dur},{push}")
            clip_has_audio = _has_audio_stream(src_path) and sfx_volume > 0
        elif item and item["type"] == "image":
            cmd += ["-i", os.path.join(d, item["file"])]
            frames = int(dur * FPS) + 1
            zoom_in = (num % 2 == 1)
            # 줌 총량을 씬 길이에 비례시켜 항상 눈에 보이는 속도 유지 (긴 씬에서 느려져 멈춘 듯 보이는 것 방지)
            total = min(0.30, max(0.13, 0.018 * dur))
            drift = 0.028 * (1 if num % 4 < 2 else -1)  # 살짝 가로 이동 (씬마다 방향 교차)
            if zoom_in:
                z = f"1+{total:.3f}*on/{frames}"
                x = f"iw/2-(iw/zoom/2)+{drift:.3f}*iw*on/{frames}"
            else:
                z = f"{1 + total:.3f}-{total:.3f}*on/{frames}"
                x = f"iw/2-(iw/zoom/2)+{drift:.3f}*iw*({frames}-on)/{frames}"
            vf.append(f"scale={W * 2}:-2,zoompan=z='{z}':d={frames}:x='{x}':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}")
        else:
            cmd += ["-f", "lavfi", "-i", f"color=c=0x14161c:s={W}x{H}:r={FPS}"]
            warnings.append(f"씬 {num}: 미디어가 없어 플레이스홀더 배경으로 대체했습니다.")
            if font:
                vf.append(f"drawtext=fontfile='{_ff_escape(font)}':text='SCENE {num:02d}':fontsize={int(H * 0.06)}:fontcolor=white@0.25:x=(w-text_w)/2:y=(h-text_h)/2")

        if audio:
            cmd += ["-i", audio]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]

        sub_spec = None
        if burn and sc.get("subtitle"):
            phrase_chars = 14 if aspect == "16:9" else 11
            phrases = _split_phrases(sc["subtitle"], phrase_chars)
            a_dur_for_sub = audio_duration(audio) if audio else None
            sub_spec = {"phrases": phrases, "narr_dur": a_dur_for_sub, "num": num}
        vf.append("format=yuv420p")

        nar = "[1:a]apad,aformat=sample_rates=44100:channel_layouts=stereo"
        if clip_has_audio:
            # 효과음: 나레이션이 나오는 동안 자동으로 낮아지게(사이드체인 컴프레서) 섞음
            a_chain = (f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={sfx_volume}[sfx];"
                       f"{nar},asplit=2[nar][key];"
                       f"[sfx][key]sidechaincompress=threshold=0.03:ratio=8:attack=40:release=500:makeup=1[ducked];"
                       f"[ducked][nar]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[a]")
        else:
            a_chain = f"{nar}[a]"

        cmd += ["-filter_complex", f"[0:v]{','.join(vf)}[v];{a_chain}",
                "-map", "[v]", "-map", "[a]", "-t", f"{dur}", "-r", str(FPS),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", out]
        try:
            _run(cmd)
        except RuntimeError as e:
            if "text_align" in str(e) and burn:
                cmd[cmd.index("-filter_complex") + 1] = cmd[cmd.index("-filter_complex") + 1].replace(":text_align=C", "")
                _run(cmd)
            else:
                raise
        scene_files.append(out)
        durations.append(dur)
        sub_specs.append(sub_spec)

    if progress:
        progress("render", "씬 이어붙이기(크로스페이드) 및 최종 인코딩...", 85)
    final = os.path.join(d, "final.mp4")
    sub_filters = _timed_subtitle_filters(sub_specs, durations, fade_d, font, W, H, font_size, sub_style, work) if burn else []
    _concat_with_transitions(ff, scene_files, durations, final, fade_d, sub_filters, transition=transition)

    thumb_url = None
    thumb = media.get("thumbnail")
    if thumb:
        tj = os.path.join(d, "thumbnail_upload.jpg")
        try:
            _run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", os.path.join(d, thumb["file"]),
                  "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", "-q:v", "3", tj])
            thumb_url = f"/data/renders/{_safe(plan_id)}/thumbnail_upload.jpg"
        except Exception as e:
            warnings.append(f"썸네일 변환 실패: {e}")

    if progress:
        progress("render", "품질 검사(정지 구간 감지) 중...", 97)
    for w in _qc_freezes(ff, final, durations, fade_d):
        warnings.append(w)

    total = audio_duration(final)
    result = {
        "video_file": final,
        "video_url": f"/data/renders/{_safe(plan_id)}/final.mp4",
        "thumbnail_file": os.path.join(d, "thumbnail_upload.jpg") if thumb_url else None,
        "thumbnail_url": thumb_url,
        "duration": total,
        "resolution": f"{W}x{H}",
        "scenes": len(scene_files),
        "scene_durations": durations,
        "warnings": warnings,
        "subtitles_burned": burn,
        "subtitle_style": sub_style if burn else None,
        "transition": transition,
        "rendered_at": time.time(),
    }
    with open(os.path.join(d, "render.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def _timed_subtitle_filters(sub_specs, durations, fade_d, font, W, H, font_size, style, work):
    """
    각 씬의 나레이션을 짧은 구절로 나눠, 발화 진행(글자 수 비례)에 맞춰 순차 표시합니다.
    구절은 크게(기본 대비 1.3배) 한두 줄로 보여 화면을 가리지 않습니다.
    """
    filters = []
    start = 0.0
    big_size = int(font_size * 1.3)
    for k, (spec, dur) in enumerate(zip(sub_specs, durations)):
        end = start + dur
        if spec and spec.get("phrases"):
            phrases = spec["phrases"]
            narr = min(spec.get("narr_dur") or dur, dur)
            total_chars = sum(len(ph) for ph in phrases) or 1
            t = start + (fade_d / 2 if k > 0 else 0.05)
            speak_end = min(start + narr + 0.35, end - 0.05)
            span = max(speak_end - t, 0.8)
            for pi, ph in enumerate(phrases):
                w = max(span * len(ph) / total_chars, 0.7)
                a, b = t, min(t + w, speak_end) if pi < len(phrases) - 1 else speak_end
                tf = os.path.join(work, f"sub_{spec['num']:02d}_{pi:02d}.txt")
                with open(tf, "w", encoding="utf-8") as f:
                    f.write(ph)
                enable = f":enable='between(t,{a:.3f},{b:.3f})'"
                filters += [flt + enable for flt in _subtitle_filters(tf, font, W, H, big_size, 1, style)]
                t = b
        start = end - fade_d
    return filters


def _qc_freezes(ff, final, durations, fade_d, min_freeze=1.0):
    """합성 결과에서 1초 이상 화면 정지를 자동 감지해 씬 위치와 함께 보고합니다."""
    try:
        res = subprocess.run([ff, "-hide_banner", "-i", final, "-vf", f"freezedetect=n=0.003:d={min_freeze}", "-an", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=300)
        starts = [float(m) for m in re.findall(r"freeze_start: ([\d.]+)", res.stderr)]
        durs = [float(m) for m in re.findall(r"freeze_duration: ([\d.]+)", res.stderr)]
    except Exception:
        return []
    bounds, t = [], 0.0
    for d in durations:
        bounds.append(t)
        t += d - fade_d
    out = []
    for st, fd in list(zip(starts, durs))[:6]:
        scene = sum(1 for b in bounds if b <= st)
        out.append(f"⚠ 품질검사: {st:.1f}초(씬 {scene}) 부근에서 화면이 {fd:.1f}초 정지합니다 — 무료 재합성으로 해결되지 않으면 해당 씬만 재생성을 고려하세요.")
    if len(starts) > 6:
        out.append(f"⚠ 품질검사: 정지 구간이 총 {len(starts)}건 감지되었습니다.")
    return out


def _concat_with_transitions(ff, files, durations, final, fade_d=0.6, extra_filters=None, transition="fade"):
    """씬 mp4들을 크로스페이드(xfade/acrossfade)로 잇고 처음/끝에 페이드를 넣어 재인코딩."""
    n = len(files)
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    for p in files:
        cmd += ["-i", p]
    total = sum(durations) - fade_d * max(0, n - 1)
    parts = []
    if n == 1 or fade_d <= 0:
        # 전환 없음: 단순 연결
        streams = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        parts.append(f"{streams}concat=n={n}:v=1:a=1[vc][ac]")
        total = sum(durations)
    else:
        v_prev, a_prev, elapsed = "[0:v]", "[0:a]", durations[0]
        for i in range(1, n):
            offset = round(elapsed - fade_d, 3)
            xf = "fadeblack" if transition == "fadeblack" else "fade"
            parts.append(f"{v_prev}[{i}:v]xfade=transition={xf}:duration={fade_d}:offset={offset}[v{i}]")
            parts.append(f"{a_prev}[{i}:a]acrossfade=d={fade_d}:c1=tri:c2=tri[a{i}]")
            v_prev, a_prev = f"[v{i}]", f"[a{i}]"
            elapsed = elapsed + durations[i] - fade_d
        parts.append(f"{v_prev}null[vc]")
        parts.append(f"{a_prev}anull[ac]")
    fo = max(0.0, total - 0.9)
    vchain = ",".join(list(extra_filters or []) + [f"fade=t=in:st=0:d=0.6", f"fade=t=out:st={fo:.3f}:d=0.9"])
    parts.append(f"[vc]{vchain}[vout]")
    parts.append(f"[ac]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100,afade=t=in:st=0:d=0.4,afade=t=out:st={fo:.3f}:d=0.9[aout]")  # 씬 간 음량 편차 정규화
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", final]
    _run(cmd, timeout=1800)


def auto_produce(plan, options=None, progress=None):
    """
    원클릭 자동화 (②에서 만든 프롬프트·나레이션을 그대로 사용):
    1) 비어 있는 씬·썸네일 이미지 생성 (레드라인 이미지 프롬프트, 기획서 비율)
    2) (선택) Omni 1.1 Flash 영상 생성 (영상 프롬프트, 기획서 비율)
    3) 나레이션 오디오 + 자막 + 씬 미디어 → 최종 mp4
    단계별 실패는 warnings 로 취합해 결과에 담고, 씬 이미지를 하나도 못 만들면 원인을 그대로 알리고 중단합니다.
    """
    options = options or {}
    include_videos = bool(options.get("include_videos", False))
    quality = options.get("quality") or "360p"
    warnings = []

    def stage_progress(lo, hi, label):
        def _p(step, message, pct=None):
            if progress:
                scaled = lo + (hi - lo) * (pct / 100.0) if pct is not None else None
                progress("auto", f"{label} — {message}", int(scaled) if scaled is not None else None)
        return _p

    plan_id = plan["plan_id"]
    scenes = plan.get("structured_scenes") or []
    idx = list_media(plan_id)
    missing = [str(s["scene_num"]) for s in scenes if str(s["scene_num"]) not in idx] + (["thumbnail"] if "thumbnail" not in idx else [])

    if missing:
        if not gemini_key():
            warnings.append(f"Gemini API 키가 없어 이미지 {len(missing)}개를 생성하지 못했습니다 (직접 넣거나 키를 저장하세요).")
        else:
            if progress:
                progress("auto", f"1단계 — 이미지 {len(missing)}개 생성 시작", 3)
            res = generate_images(plan, slots=missing, progress=stage_progress(3, 35, "1단계 이미지"))
            for e in res.get("errors", []):
                warnings.append(f"{'썸네일' if e['slot'] == 'thumbnail' else '씬 ' + e['slot']} 이미지 실패: {e['error']}")
            scene_missing = [m for m in missing if m != "thumbnail"]
            if scene_missing and not any(s in res.get("generated", []) for s in scene_missing):
                first = next((e["error"] for e in res.get("errors", []) if e["slot"] != "thumbnail"), "원인 불명")
                raise RuntimeError(f"씬 이미지를 하나도 만들지 못해 중단했습니다: {first}")
    elif progress:
        progress("auto", "1단계 — 이미지가 모두 준비되어 있어 건너뜀", 35)

    if include_videos:
        if not gemini_key():
            warnings.append("Gemini API 키가 없어 AI 영상 생성을 건너뛰었습니다.")
        else:
            res = generate_videos(plan, quality=quality, chain=bool(options.get("chain", True)), skip_existing=True,
                                  progress=stage_progress(35, 72, f"2단계 AI 영상({quality})"))
            if res.get("skipped"):
                warnings.append(f"씬 {', '.join(map(str, res['skipped']))}: 이미 AI 영상이 있어 다시 만들지 않았습니다 (과금 없음).")
            for e in res.get("errors", []):
                warnings.append(f"씬 {e['slot']} 영상 실패 → 이미지로 대체: {e['error']}")

    if progress:
        progress("auto", "3단계 — 나레이션·자막 합성 시작", 72)
    result = build_video(plan, options, progress=stage_progress(72, 98, "3단계 합성"))
    result["warnings"] = warnings + list(result.get("warnings") or [])
    with open(os.path.join(render_dir(plan_id), "render.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def last_render(plan_id):
    try:
        with open(os.path.join(render_dir(plan_id), "render.json"), encoding="utf-8") as f:
            r = json.load(f)
        if os.path.exists(r.get("video_file", "")):
            return r
    except Exception:
        pass
    return None
