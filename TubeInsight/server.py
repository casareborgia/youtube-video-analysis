# TubeInsight 웹 서버 — 실행: python3 server.py  → http://localhost:8989
import os
import re
import sys
import json
import time
import uuid
import base64
import threading
import traceback
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import dotenv
import analyze
import generator
import tts_engine
import llm_client
import producer
import uploader
import marketing
import channel_builder

APP_VERSION = "0.4.0"
PORT = int(os.environ.get("TUBEINSIGHT_PORT", "8989"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ENV_FILE = os.path.join(BASE_DIR, ".env")
MAX_BODY_BYTES = 40 * 1024 * 1024  # 음성/미디어 업로드(base64) 상한

# .env 환경변수 로드
if os.path.exists(ENV_FILE):
    dotenv.load_dotenv(ENV_FILE, override=True)

# 브라우저에 내어줄 파일만 허용 (소스 코드·설정·분석 캐시는 서빙하지 않음)
STATIC_FILES = {"/index.html", "/app.js", "/style.css", "/favicon.ico"}
STATIC_PREFIXES = ("/vendor/", "/data/audio/", "/data/voices/", "/data/renders/", "/data/channels/")
ALLOWED_HOSTS = ("localhost", "127.0.0.1", "[::1]")

# 단계 키 → 진행률(%) — 프론트 진행 표시에 사용
STEP_PROGRESS = {
    "analyze": {"metadata": 8, "subtitles": 20, "comments": 30, "ai_stage1": 40, "ai_stage2": 58, "ai_stage3": 76, "ai_visual": 90},
    "generate": {"meta": 10, "scenes": 28, "proofread": 40, "prompts": 52, "redline": 72, "audio": 88},
    "tts": {"audio": 35},
    "images": {},
    "videos": {},
    "render": {},
    "auto": {},
    "upload": {},
    "yt_auth": {},
    "full": {},
    "channel_gen": {},
    "channel_img": {},
    "marketing": {
        "threadx_start": 10, "threadx_generating": 45, "threadx_done": 100,
        "blog_start": 10, "blog_generating": 50, "blog_done": 100,
        "newsletter_start": 10, "newsletter_generating": 50, "newsletter_done": 100,
        "omni_start": 5, "omni_threads": 25, "omni_blog": 60, "omni_newsletter": 85, "omni_done": 100
    }
}


# ── 백그라운드 작업 관리 ──────────────────────────────────────────────────

JOBS = {}
JOBS_LOCK = threading.Lock()


EXCLUSIVE_KINDS = {"generate", "tts", "full", "marketing"}  # 로컬 AI·TTS 모델을 쓰는 작업은 한 번에 하나만


def running_job(kinds):
    with JOBS_LOCK:
        for j in JOBS.values():
            if j["status"] == "running" and j["kind"] in kinds:
                return j
    return None


def start_job(kind, label, fn):
    """fn(progress) 를 스레드에서 실행하고 작업 id를 돌려줍니다. progress(step, message)로 진행 상황 갱신."""
    if kind in EXCLUSIVE_KINDS:
        busy = running_job(EXCLUSIVE_KINDS)
        if busy:
            raise ValueError(f"이미 '{busy['label']}' 작업이 진행 중입니다. 끝난 뒤 다시 시도해주세요.")
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "kind": kind, "label": label, "status": "running",
        "step": None, "message": "시작 중...", "progress": 2,
        "result": None, "error": None, "started_at": time.time(), "finished_at": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
        # 오래된 작업 정리 (최근 40개만 유지)
        if len(JOBS) > 40:
            for old in sorted(JOBS.values(), key=lambda j: j["started_at"])[: len(JOBS) - 40]:
                JOBS.pop(old["id"], None)

    def progress(step, message, pct=None):
        with JOBS_LOCK:
            job["step"] = step
            job["message"] = message
            target = pct if pct is not None else STEP_PROGRESS.get(kind, {}).get(step)
            if target is not None:
                job["progress"] = max(job["progress"], min(99, int(target)))

    def runner():
        try:
            result = fn(progress)
            with JOBS_LOCK:
                job.update({"status": "done", "result": result, "progress": 100, "message": "완료", "finished_at": time.time()})
        except Exception as e:
            traceback.print_exc()
            with JOBS_LOCK:
                job.update({"status": "error", "error": str(e), "finished_at": time.time()})

    threading.Thread(target=runner, daemon=True, name=f"job-{kind}-{job_id}").start()
    return job_id


def job_view(job):
    return {k: v for k, v in job.items()}


# ── 작업 본문 ─────────────────────────────────────────────────────────────

def run_analysis(url, force=False):
    vid = analyze.extract_video_id(url)
    if not vid:
        raise ValueError("유효한 유튜브 영상 링크(URL)가 아닙니다.")

    def work(progress):
        data = analyze.analyze_video(url, progress_callback=progress)
        data["cached"] = False
        return data

    return vid, work


def run_generation(params):
    topic = params["topic"]
    num_scenes = int(params.get("scenes") or 10)
    voice_id = params.get("voice_id") or "ko-KR-InJoonNeural"
    aspect_ratio = params.get("aspect_ratio") or "16:9"
    reference_id = params.get("reference_id") or None
    generate_audio = bool(params.get("generate_audio", True))

    def work(progress):
        plan = generator.generate_video_content(
            topic, num_scenes=num_scenes, aspect_ratio=aspect_ratio, reference_id=reference_id,
            style_guide=params.get("style_guide") or None,
            scene_seconds=int(params.get("scene_seconds") or 8), progress_callback=progress
        )
        if generate_audio:
            progress("audio", "나레이션 오디오 합성 중...")
            try:
                plan["audio_data"] = tts_engine.generate_all_scenes_audio(
                    plan["structured_scenes"], plan["plan_id"], voice_id=voice_id, progress_callback=progress
                )
            except Exception as e:
                plan["audio_data"] = None
                plan["audio_error"] = str(e)
            generator.save_plan(plan)
        return plan

    return work


def run_tts(params):
    plan_id = params.get("plan_id")
    voice_id = params.get("voice_id") or "ko-KR-InJoonNeural"
    plan = generator.load_plan(plan_id) if plan_id else None
    scenes = params.get("scenes") or (plan or {}).get("structured_scenes")
    if not scenes:
        raise ValueError("씬 데이터가 없습니다.")

    def work(progress):
        audio = tts_engine.generate_all_scenes_audio(scenes, plan_id or "quick", voice_id=voice_id, progress_callback=progress)
        if plan is not None:
            plan["audio_data"] = audio
            plan.pop("audio_error", None)
            generator.save_plan(plan)
        return audio

    return work


def _require_plan(plan_id):
    plan = generator.load_plan(plan_id or "")
    if not plan:
        raise ValueError("기획서를 찾을 수 없습니다. 먼저 ② 탭에서 기획서를 만들어주세요.")
    return plan


def run_scene_edit(params):
    """씬 나레이션 수정 → 기획서 저장 → 나레이션 오디오 재합성(전체 씬, 병합본·ZIP 갱신)."""
    plan = _require_plan(params.get("plan_id"))
    scene_num = int(params.get("scene_num") or 0)
    subtitle = params.get("subtitle") or ""
    voice_id = params.get("voice_id") or (plan.get("audio_data") or {}).get("voice_id") or "ko-KR-InJoonNeural"
    resynth = bool(params.get("resynthesize", True))
    generator.update_scene_subtitle(plan, scene_num, subtitle)

    def work(progress):
        if resynth:
            progress("audio", f"씬 {scene_num} 수정 반영 — 나레이션 재합성 중...", 20)
            plan["audio_data"] = tts_engine.generate_all_scenes_audio(plan["structured_scenes"], plan["plan_id"], voice_id=voice_id, progress_callback=progress)
            plan.pop("audio_error", None)
        generator.save_plan(plan)
        return plan

    return work


def run_images(params):
    plan = _require_plan(params.get("plan_id"))
    slots = params.get("slots") or None
    return lambda progress: producer.generate_images(plan, slots=slots, progress=progress)


def run_videos(params):
    plan = _require_plan(params.get("plan_id"))
    quality = params.get("quality") or "360p"
    slots = params.get("slots")
    slots = [str(x) for x in slots if str(x).isdigit()] if isinstance(slots, list) else None  # 잘못된 값은 전체 씬으로
    chain = bool(params.get("chain", True))
    skip_existing = bool(params.get("skip_existing", True))
    return lambda progress: producer.generate_videos(plan, quality=quality, slots=slots, chain=chain, skip_existing=skip_existing, progress=progress)


def run_render(params):
    plan = _require_plan(params.get("plan_id"))
    options = {
        "burn_subtitles": bool(params.get("burn_subtitles", True)),
        "fit_narration": bool(params.get("fit_narration", True)),
        "resolution": params.get("resolution") or "1080p",
        "subtitle_style": params.get("subtitle_style") or "outline",
        "transition": params.get("transition") or "fade",
    }
    return lambda progress: producer.build_video(plan, options, progress=progress)


def run_auto_produce(params):
    plan = _require_plan(params.get("plan_id"))
    options = {
        "include_videos": bool(params.get("include_videos", False)),
        "quality": params.get("quality") or "360p",
        "chain": bool(params.get("chain", True)),
        "subtitle_style": params.get("subtitle_style") or "outline",
        "transition": params.get("transition") or "fade",
        "burn_subtitles": bool(params.get("burn_subtitles", True)),
        "fit_narration": bool(params.get("fit_narration", True)),
        "resolution": params.get("resolution") or "1080p",
    }
    return lambda progress: producer.auto_produce(plan, options=options, progress=progress)


def run_upload(params):
    plan = _require_plan(params.get("plan_id"))
    render = producer.last_render(plan["plan_id"])
    if not render:
        raise ValueError("완성된 영상이 없습니다. 먼저 '영상 만들기'를 실행해주세요.")
    tags = params.get("tags")
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[,#\n]+", tags) if t.strip()]

    def work(progress):
        progress("upload", "유튜브 업로드 준비 중...", 3)
        return uploader.upload_video(
            render["video_file"],
            title=params.get("title") or (plan.get("meta") or {}).get("recommended", {}).get("title") or plan.get("topic"),
            description=params.get("description") or plan.get("description_plain") or "",
            tags=tags or [], privacy=params.get("privacy") or "private", publish_at=params.get("publish_at") or None,
            thumbnail_path=render.get("thumbnail_file"), category_id=params.get("category_id") or "27",
            made_for_kids=bool(params.get("made_for_kids", False)), progress=progress,
        )

    return work


GEN_STEP_PCT = {"meta": 4, "scenes": 10, "proofread": 16, "prompts": 20, "redline": 26, "audio": 30}


def run_full(params):
    """풀 오토: 주제 하나 → 기획·나레이션 → 이미지 → (선택)AI 영상 → 합성 → (선택)마케팅 3종."""
    topic = (params.get("topic") or "").strip()
    if not topic:
        raise ValueError("영상 주제를 입력해주세요.")
    num_scenes = int(params.get("scenes") or 10)
    voice_id = params.get("voice_id") or "ko-KR-InJoonNeural"
    aspect_ratio = params.get("aspect_ratio") or "16:9"
    reference_id = params.get("reference_id") or None
    include_videos = bool(params.get("include_videos", False))
    video_quality = params.get("video_quality") or "360p"
    resolution = params.get("resolution") or "1080p"
    do_marketing = bool(params.get("marketing", True))

    def work(progress):
        warnings = []
        # 1) 기획 + 나레이션 (0~32%)
        def gen_cb(step, msg):
            progress(step, f"1/3 기획·나레이션 — {msg}", GEN_STEP_PCT.get(step))
        plan = generator.generate_video_content(topic, num_scenes=num_scenes, aspect_ratio=aspect_ratio,
                                                reference_id=reference_id, style_guide=params.get("style_guide") or None,
                                                scene_seconds=int(params.get("scene_seconds") or 8), progress_callback=gen_cb)
        progress("audio", "1/3 기획·나레이션 — 나레이션 합성 중...", 30)
        try:
            plan["audio_data"] = tts_engine.generate_all_scenes_audio(plan["structured_scenes"], plan["plan_id"], voice_id=voice_id)
        except Exception as e:
            plan["audio_error"] = str(e)
            warnings.append(f"나레이션 합성 실패: {e}")
        generator.save_plan(plan)

        # 2) 이미지 → (영상) → 합성 (32~78%)
        def prod_cb(step, msg, pct=None):
            progress(step, f"2/3 영상 제작 — {msg}", 32 + (78 - 32) * (pct / 100.0) if pct is not None else None)
        render = producer.auto_produce(plan, {"include_videos": include_videos, "quality": video_quality,
                                              "resolution": resolution, "chain": True}, progress=prod_cb)
        warnings += list(render.get("warnings") or [])

        # 3) 마케팅 3종 (78~98%)
        marketing_result, marketing_id = None, None
        if do_marketing:
            ctx = (f"[영상 제목] {plan['meta']['recommended']['title']}\n[설명란]\n{plan.get('description_plain', '')[:600]}\n\n"
                   "[씬별 나레이션]\n" + "\n".join(f"씬 {sc['scene_num']}: {sc['subtitle']}" for sc in plan["structured_scenes"]))
            def mkt_cb(step, pct, msg):
                progress(step, f"3/3 마케팅 — {msg}", 78 + (98 - 78) * (pct / 100.0))
            try:
                marketing_result = marketing.generate_all_marketing(topic, context=ctx, options={}, on_progress=mkt_cb)
                marketing_id = marketing.save_entry(topic, "all", marketing_result)
            except Exception as e:
                warnings.append(f"마케팅 생성 실패: {e}")

        return {"plan": generator.load_plan(plan["plan_id"]), "render": render,
                "marketing": marketing_result, "marketing_id": marketing_id, "warnings": warnings}

    return work


def run_marketing(params):
    mode = params.get("mode") or "all"
    topic = (params.get("topic") or "새로운 콘텐츠 마케팅").strip()
    context = params.get("context") or ""
    options = params.get("options") or {}

    def work(progress):
        if mode == "threads":
            return marketing.generate_threads_x(
                topic=topic,
                context=context,
                platform=options.get("platform", "threads"),
                tone=options.get("tone", "viral_hook"),
                count=int(options.get("count", 5)),
                audience=options.get("audience", "크리에이터, 직장인, 마케터"),
                on_progress=lambda step, pct, msg: progress(step, msg, pct)
            )
        elif mode == "blog":
            return marketing.generate_seo_blog(
                topic=topic,
                context=context,
                platform_target=options.get("blog_platform", "general"),
                tone=options.get("tone", "professional"),
                audience=options.get("audience", "전문가 및 일반 독자"),
                on_progress=lambda step, pct, msg: progress(step, msg, pct)
            )
        elif mode == "newsletter":
            return marketing.generate_newsletter(
                topic=topic,
                context=context,
                campaign_type=options.get("campaign_type", "video_launch"),
                audience=options.get("audience", "구독자 및 충성 팬"),
                offer=options.get("offer", ""),
                on_progress=lambda step, pct, msg: progress(step, msg, pct)
            )
        else:  # "all"
            return marketing.generate_all_marketing(
                topic=topic,
                context=context,
                options=options,
                on_progress=lambda step, pct, msg: progress(step, msg, pct)
            )

    def work_and_save(progress):
        result = work(progress)
        try:
            marketing.save_entry(topic, mode, result)
        except Exception as e:
            print(f"마케팅 보관함 저장 실패: {e}")
        return result

    return work_and_save


def run_channel_gen(params):
    topic = (params.get("topic") or "").strip()
    if not topic:
        raise ValueError("채널 주제를 입력해주세요.")
    lang = params.get("lang") or "ko"
    audience = params.get("audience") or None
    tone = params.get("tone") or None
    persona_type = params.get("persona_type") or "character"
    audio_lang = params.get("audio_lang") or lang

    def work(progress):
        return channel_builder.generate_channel_setup(
            topic=topic,
            lang=lang,
            audience=audience,
            tone=tone,
            persona_type=persona_type,
            audio_lang=audio_lang,
            progress_callback=progress
        )

    return work


def run_channel_images(params):
    ch_id = params.get("channel_id")
    channel_data = channel_builder.load_channel(ch_id) if ch_id else params.get("channel_data")
    if not channel_data:
        raise ValueError("채널 세팅 데이터를 찾을 수 없습니다.")

    def work(progress):
        return channel_builder.generate_channel_images(channel_data, progress_callback=progress)

    return work


# ── HTTP 핸들러 ───────────────────────────────────────────────────────────

class TubeInsightHandler(SimpleHTTPRequestHandler):
    server_version = f"TubeInsight/{APP_VERSION}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # 조용한 로그: 상태 폴링은 생략
    def log_message(self, fmt, *args):
        line = fmt % args
        if "/api/status" in line or "/api/jobs/" in line or "/vendor/" in line:
            return
        sys.stderr.write(f"[{self.log_date_time_string()}] {line}\n")

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ALLOWED_HOSTS

    # ── GET ──
    def do_GET(self):
        if not self._host_ok():
            self.send_json({"error": "허용되지 않은 호스트입니다."}, 403)
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        q = lambda k, d=None: query.get(k, [d])[0]

        try:
            if path == "/api/status":
                self.send_json(self.status_payload())
            elif path == "/api/search":
                query_text = (q("q") or "").strip()
                if not query_text:
                    self.send_json({"error": "검색어를 입력해주세요."}, 400)
                else:
                    self.send_json({"status": "success", "results": analyze.search_videos(query_text)})
            elif path == "/api/report":
                self.handle_report(q("id"))
            elif path == "/api/history":
                self.send_json({"status": "success", "analyses": analyze.list_analyses(), "plans": generator.list_plans()})
            elif path == "/api/knowledge":
                self.send_json({"status": "success", "guides": generator.list_style_guides()})
            elif path == "/api/channel/history":
                self.send_json({"status": "success", "channels": channel_builder.list_channels()})
            elif path == "/api/channel":
                ch = channel_builder.load_channel(q("id") or "")
                if ch:
                    self.send_json({"status": "success", "data": ch})
                else:
                    self.send_json({"error": "채널 세팅을 찾을 수 없습니다."}, 404)
            elif path == "/api/marketing/history":
                self.send_json({"status": "success", "history": marketing.list_marketing_history()})
            elif path == "/api/marketing/get":
                entry = marketing.load_entry(q("id") or "")
                if entry:
                    self.send_json({"status": "success", "entry": entry})
                else:
                    self.send_json({"error": "보관함 항목을 찾을 수 없습니다."}, 404)
            elif path == "/api/plan":
                plan = generator.load_plan(q("id") or "")
                if plan:
                    self.send_json({"status": "success", "data": plan})
                else:
                    self.send_json({"error": "기획서를 찾을 수 없습니다."}, 404)
            elif path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    view = job_view(job) if job else None
                if view:
                    self.send_json({"status": "success", "job": view})
                else:
                    self.send_json({"error": "작업을 찾을 수 없습니다. 서버가 재시작되었을 수 있습니다."}, 404)
            elif path == "/api/render/status":
                plan_id = q("plan_id") or ""
                self.send_json({
                    "status": "success",
                    "env": producer.environment(),
                    "youtube": uploader.status(),
                    "media": producer.media_view(plan_id) if plan_id else {},
                    "render": producer.last_render(plan_id) if plan_id else None,
                })
            elif path == "/api/render/estimate":
                num_scenes = int(q("scenes") or 10)
                quality = q("quality") or "360p"
                self.send_json({"status": "success", "estimate": producer.estimate_costs(num_scenes, quality)})
            elif path == "/api/voice/profiles":
                self.send_json({"status": "success", "voices": tts_engine.VoiceProfileManager.list_all_voices(),
                                "clone_available": tts_engine.clone_available()})
            elif path == "/":
                self.path = "/index.html"
                super().do_GET()
            elif path in STATIC_FILES or path.startswith(STATIC_PREFIXES):
                super().do_GET()
            else:
                self.send_json({"error": "Not Found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_json({"error": str(e)}, 500)
            except Exception:
                pass

    # ── POST ──
    def do_POST(self):
        if not self._host_ok():
            self.send_json({"error": "허용되지 않은 호스트입니다."}, 403)
            return
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self.send_json({"error": "요청이 너무 큽니다 (최대 40MB)."}, 413)
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}

        try:
            if path == "/api/analyze":
                self.handle_analyze(data)
            elif path == "/api/generate":
                topic = (data.get("topic") or "").strip()
                if not topic:
                    self.send_json({"error": "영상 주제를 입력해주세요."}, 400)
                    return
                data["topic"] = topic
                job_id = start_job("generate", f"기획: {topic}", run_generation(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/pipeline/full":
                job_id = start_job("full", f"풀 오토: {(data.get('topic') or '')[:24]}", run_full(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/marketing/generate":
                topic = (data.get("topic") or "마케팅 콘텐츠").strip()
                job_id = start_job("marketing", f"마케팅: {topic}", run_marketing(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/marketing/save":
                marketing._save_marketing_history(data)
                self.send_json({"status": "success"})
            elif path == "/api/plan/scene":
                job_id = start_job("tts", "나레이션 수정", run_scene_edit(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/tts/generate-scenes":
                job_id = start_job("tts", "나레이션 합성", run_tts(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/channel/generate":
                topic = (data.get("topic") or "").strip()
                if not topic:
                    self.send_json({"error": "채널 주제를 입력해주세요."}, 400)
                    return
                job_id = start_job("channel_gen", f"채널 기획: {topic}", run_channel_gen(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/channel/images":
                job_id = start_job("channel_img", "채널 이미지 생성", run_channel_images(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/channel/check-handle":
                handle = (data.get("handle") or "").strip()
                avail, msg = channel_builder.check_handle_availability(handle)
                self.send_json({"status": "success", "handle": handle, "available": avail, "message": msg, "url": f"https://www.youtube.com/@{handle}"})
            elif path == "/api/channel/apply-branding":
                res = uploader.update_channel_branding(
                    description=data.get("description"),
                    keywords=data.get("keywords"),
                    default_language=data.get("default_language")
                )
                self.send_json(res)
            elif path == "/api/voice/upload":
                self.handle_voice_upload(data)
            elif path == "/api/llm/select":
                if "model" in data:
                    llm_client.set_model(data.get("backend"), data.get("model") or None)
                else:
                    llm_client.set_preference(data.get("backend", "auto"))
                self.send_json({"status": "success", "llm": llm_client.active_backend_status()})
            elif path == "/api/settings":
                key_valid, key_msg = None, None
                if "gemini_api_key" in data:
                    producer.set_gemini_key(data.get("gemini_api_key") or "")
                    if (data.get("gemini_api_key") or "").strip():
                        key_valid, key_msg = producer.validate_gemini_key()
                self.send_json({"status": "success", "env": producer.environment(), "key_valid": key_valid, "key_message": key_msg})
            elif path == "/api/render/media":
                b64 = data.get("data_base64") or ""
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                if not b64:
                    raise ValueError("파일 데이터가 없습니다.")
                item = producer.save_media(data.get("plan_id"), data.get("slot"), data.get("filename") or "", base64.b64decode(b64))
                self.send_json({"status": "success", "item": item, "media": producer.media_view(data.get("plan_id"))})
            elif path == "/api/render/media/delete":
                producer.delete_media(data.get("plan_id"), data.get("slot"))
                self.send_json({"status": "success", "media": producer.media_view(data.get("plan_id"))})
            elif path == "/api/render/images":
                job_id = start_job("images", "이미지 생성", run_images(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/render/videos":
                job_id = start_job("videos", "Omni 영상 생성", run_videos(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/render/build":
                job_id = start_job("render", "영상 합성", run_render(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/render/auto":
                job_id = start_job("auto", "원클릭 영상 제작", run_auto_produce(data))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/youtube/auth":
                job_id = start_job("yt_auth", "유튜브 연결", lambda progress: uploader.authorize(progress))
                self.send_json({"status": "queued", "job_id": job_id})
            elif path == "/api/youtube/secret":
                import base64 as _b64
                b64 = data.get("data_base64") or ""
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                raw = _b64.b64decode(b64) if b64 else b""
                try:
                    j = json.loads(raw.decode("utf-8"))
                    assert "installed" in j or "web" in j
                except Exception:
                    self.send_json({"error": "올바른 OAuth 클라이언트 JSON이 아닙니다. '데스크톱 앱' 유형으로 만든 JSON인지 확인하세요."}, 400)
                    return
                if "web" in j and "installed" not in j:
                    self.send_json({"error": "'웹 애플리케이션' 유형입니다. OAuth 클라이언트를 '데스크톱 앱' 유형으로 다시 만들어주세요."}, 400)
                    return
                with open(uploader.CLIENT_SECRET, "wb") as f:
                    f.write(raw)
                self.send_json({"status": "success", "youtube": uploader.status()})
            elif path == "/api/youtube/disconnect":
                uploader.disconnect()
                self.send_json({"status": "success", "youtube": uploader.status()})
            elif path == "/api/youtube/upload":
                job_id = start_job("upload", "유튜브 업로드", run_upload(data))
                self.send_json({"status": "queued", "job_id": job_id})
            else:
                self.send_json({"error": "Not Found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as e:
            try:
                self.send_json({"error": str(e)}, 400)
            except Exception:
                pass
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_json({"status": "error", "error": str(e)}, 500)
            except Exception:
                pass

    # ── 핸들러 ──
    def status_payload(self):
        llm = llm_client.active_backend_status()
        backends = llm.pop("backends")
        try:
            import yt_dlp
            ytdlp_version = yt_dlp.version.__version__
        except Exception:
            ytdlp_version = None
        return {
            "version": APP_VERSION,
            "python": sys.version.split()[0],
            "llm": llm,
            "backends": backends,
            "tts": {"edge": True, "clone_available": tts_engine.clone_available()},
            "yt_dlp": ytdlp_version,
            "render": producer.environment(),
            "youtube": {"libs": uploader.libs_available(), "client_secret": os.path.exists(uploader.CLIENT_SECRET),
                        "authorized": os.path.exists(uploader.TOKEN_FILE)},
            "server_port": PORT,
        }

    def handle_analyze(self, data):
        url = (data.get("url") or "").strip()
        force = bool(data.get("force", False))
        if not url:
            self.send_json({"error": "YouTube 영상 링크나 ID를 입력해주세요."}, 400)
            return
        vid = analyze.extract_video_id(url)
        if not vid:
            self.send_json({"error": "올바른 YouTube 링크 또는 영상 ID가 아닙니다."}, 400)
            return
        if not force and analyze.is_cached(vid):
            self.send_json({"status": "cached", "data": analyze.load_cached(vid)})
            return

        def work(progress):
            return analyze.analyze_pipeline(vid, progress_callback=progress)

        job_id = start_job("analyze", f"분석: {vid}", work)
        self.send_json({"status": "queued", "job_id": job_id})

    def handle_report(self, vid):
        if not vid:
            self.send_json({"error": "영상 ID가 필요합니다."}, 400)
            return
        data = analyze.load_cached(vid)
        if data:
            self.send_json({"status": "success", "data": data})
        else:
            self.send_json({"error": "분석 결과를 찾을 수 없습니다."}, 404)

    def handle_voice_upload(self, data):
        name = (data.get("name") or "내 목소리").strip()[:40]
        ref_text = (data.get("ref_text") or "").strip()[:500]
        audio_b64 = data.get("audio_base64") or ""
        if not audio_b64:
            self.send_json({"error": "녹음된 오디오 데이터가 필요합니다."}, 400)
            return
        if "," in audio_b64:
            audio_b64 = audio_b64.split(",", 1)[1]
        audio_bytes = base64.b64decode(audio_b64)
        if len(audio_bytes) < 2000:
            self.send_json({"error": "녹음이 너무 짧습니다. 3초 이상 녹음해주세요."}, 400)
            return
        profile_id = f"voice_{int(time.time())}"
        audio_filename = f"{profile_id}.webm"
        with open(os.path.join(tts_engine.VOICES_DIR, audio_filename), "wb") as f:
            f.write(audio_bytes)
        profile = tts_engine.VoiceProfileManager.save_profile(profile_id, name, ref_text, audio_filename)
        self.send_json({"status": "success", "profile": profile, "clone_available": tts_engine.clone_available()})

    def send_json(self, data, status=200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def run():
    os.makedirs(DATA_DIR, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), TubeInsightHandler)  # 내 컴퓨터에서만 접속 가능
    httpd.daemon_threads = True
    print(f"🚀 TubeInsight v{APP_VERSION} 실행 중: http://localhost:{PORT}")
    print("   브라우저에서 위 주소를 열어주세요. 종료: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버 종료됨")


if __name__ == "__main__":
    run()
