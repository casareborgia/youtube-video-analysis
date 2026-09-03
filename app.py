import os
import re
import sys
import json
import gc
import urllib.parse
import asyncio
import subprocess
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
import pandas as pd
import yt_dlp

import llm_client
from tts_service import TTSService, AUDIO_DIR, VOICES_DIR, ZIP_DIR, EDGE_PRESETS, QWEN_PRESETS
from prompt_generator import (
    PromptGenerator,
    STYLE_PRESETS,
    SUPPORTED_MODELS,
    SUPPORTED_LANGUAGES
)
import trend_scout
import channel_builder
import marketing
import producer
import uploader

app = FastAPI(title="TubeInsight AI — 유튜브 영상 완전 분석 & 8초 비디오 AI 기획 스튜디오")

# ==========================================
# 제로트러스트 보안 헤더 미들웨어
# ==========================================
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https://i.ytimg.com https://*.youtube.com; "
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "media-src 'self' blob: data:; "
        "connect-src 'self';"
    )
    return response

# ==========================================
# 제로트러스트 입력 검증 헬퍼 (Never Trust, Always Verify)
# ==========================================
VIDEO_ID_REGEX = re.compile(r'^[a-zA-Z0-9_-]{5,30}$')
SAFE_FILENAME_REGEX = re.compile(r'^[a-zA-Z0-9_.\-가-힣]+$')

def verify_video_id(video_id: str) -> str:
    """video_id 파라미터가 안전한 유튜브 ID 형식인지 엄격 검증"""
    if not video_id or not VIDEO_ID_REGEX.match(video_id):
        raise HTTPException(status_code=400, detail="유효하지 않거나 안전하지 않은 영상 ID 형식입니다.")
    return video_id

def verify_youtube_url(url: str) -> str:
    """SSRF 방지를 위해 신뢰할 수 있는 공식 유튜브 도메인만 허용"""
    if not url or not isinstance(url, str):
        raise HTTPException(status_code=400, detail="URL이 입력되지 않았습니다.")

    url_clean = url.strip()
    allowed_domains = ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"]
    match = re.match(r'^https?://([^/]+)', url_clean)
    if not match:
        raise HTTPException(status_code=400, detail="유효한 HTTP/HTTPS URL 형식이 아닙니다.")

    domain = match.group(1).lower()
    if not any(domain == d or domain.endswith("." + d) for d in allowed_domains):
        raise HTTPException(status_code=400, detail="공식 유튜브(youtube.com, youtu.be) URL만 분석할 수 있습니다.")
    return url_clean

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

INDEX_FILE = DATA_DIR / "metadata_index.json"

def load_index() -> List[Dict[str, Any]]:
    """메타데이터 인덱스를 로드하고, 실제 파일이 삭제된 고아 데이터는 자동 동기화/정리"""
    if not INDEX_FILE.exists():
        return []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            raw_index = json.load(f)

        valid_index = []
        is_changed = False
        for item in raw_index:
            v_id = item.get("id")
            if not v_id:
                is_changed = True
                continue
            meta_file = DATA_DIR / f"{v_id}_metadata.json"
            if meta_file.exists():
                report_file = DATA_DIR / f"{v_id}_리포트.txt"
                item["has_report"] = report_file.exists()
                valid_index.append(item)
            else:
                is_changed = True

        if is_changed:
            save_index(valid_index)

        return valid_index
    except Exception:
        return []

def save_index(index_data: List[Dict[str, Any]]):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)

class AnalyzeRequest(BaseModel):
    url: str
    extract_subtitles: bool = True
    extract_comments: bool = True
    max_comments: int = 100
    auto_generate_ai_report: bool = False
    max_playlist_items: Optional[int] = 10

class LLMSelectRequest(BaseModel):
    backend: str = "auto"  # auto | lmstudio | ollama

class PromptCustomTopicRequest(BaseModel):
    topic: str
    scene_count: int = 6
    model: str = "google_flow"
    aspect_ratio: str = "16:9"
    style_key: str = "photorealistic_8k"
    custom_subject: Optional[str] = ""
    language: Optional[str] = "korean"

class PromptExportRequest(BaseModel):
    scenes: List[Dict[str, Any]]
    format: str = "autoflow_txt"  # autoflow_txt | csv | json
    video_title: Optional[str] = "prompt_batch"

class TTSSceneRequest(BaseModel):
    text: str
    voice_id: str = "edge_injoon"
    scene_index: int = 1
    topic_slug: Optional[str] = "scene"
    language: Optional[str] = "korean"

class TTSBatchRequest(BaseModel):
    scenes: List[Dict[str, Any]]
    voice_id: str = "edge_injoon"
    topic: Optional[str] = "custom_topic"
    language: Optional[str] = "korean"

def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

# ==========================================
# LLM 실시간 상태 및 제어 API
# ==========================================
@app.get("/api/llm/status")
async def get_llm_status():
    """LM Studio & Ollama 실행 상태 및 활성 모델 확인"""
    probes = llm_client.probe_all()
    pref = llm_client.get_preference()
    active_backend = llm_client.detect_backend()

    return {
        "status": "success",
        "backends": probes,
        "preference": pref,
        "active": active_backend
    }

@app.post("/api/llm/select")
async def select_llm_backend(req: LLMSelectRequest):
    """사용자가 선호하는 LLM 백엔드 전환 설정"""
    try:
        saved_pref = llm_client.set_preference(req.backend)
        return {"status": "success", "preference": saved_pref}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ==========================================
# 유튜브 영상 분석 API
# ==========================================
@app.post("/api/analyze")
async def analyze_youtube(req: AnalyzeRequest):
    """유튜브 단일 영상 또는 재생목록의 메타데이터 및 댓글 심층 분석"""
    try:
        safe_url = verify_youtube_url(req.url)
        from analyze import analyze_video
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, analyze_video, safe_url)

        # 인덱스 갱신
        vid = result["id"]
        info = result["info"]
        index = load_index()
        index = [item for item in index if item.get('id') != vid]
        index.insert(0, {
            "id": vid,
            "title": info.get("title"),
            "channel": info.get("channel"),
            "channel_follower_count": info.get("channel_follower_count", 0),
            "upload_date": info.get("upload_date", ""),
            "duration_string": info.get("duration_string", "00:00"),
            "view_count": info.get("view_count", 0),
            "like_count": info.get("like_count", 0),
            "comment_count": info.get("comment_count", 0),
            "comments_extracted": len(result.get("comments", [])),
            "has_ai_report": bool(result.get("report")),
            "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "url": safe_url,
            "thumbnail": info.get("thumbnail")
        })
        save_index(index)

        return {"status": "success", "count": 1, "data": [result]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/history")
async def get_history():
    index = load_index()
    return {"status": "success", "total": len(index), "data": index}

@app.get("/api/metadata/{video_id}")
async def get_metadata_detail(video_id: str):
    safe_id = verify_video_id(video_id)
    file_path = DATA_DIR / f"{safe_id}_metadata.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="해당 영상의 메타데이터를 찾을 수 없습니다.")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    report_file = DATA_DIR / f"{safe_id}_리포트.txt"
    if report_file.exists():
        try:
            with open(report_file, "r", encoding="utf-8") as rf:
                data["ai_report"] = rf.read()
                data["report"] = data["ai_report"]
                data["has_ai_report"] = True
        except Exception:
            pass

    return {"status": "success", "data": data}

@app.get("/api/ai-report/{video_id}/download")
async def download_ai_report(video_id: str):
    safe_id = verify_video_id(video_id)
    report_file = DATA_DIR / f"{safe_id}_리포트.txt"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="생성된 AI 리포트가 없습니다.")
    return FileResponse(
        report_file,
        filename=f"{safe_id}_리포트.txt",
        media_type="text/plain; charset=utf-8"
    )

@app.delete("/api/metadata/{video_id}")
async def delete_metadata(video_id: str):
    """영상 및 연관 파일 완전 삭제"""
    clean_vid = urllib.parse.unquote(video_id).strip()
    safe_vid = re.sub(r'[^A-Za-z0-9_-]', '', clean_vid)

    if not clean_vid and not safe_vid:
        raise HTTPException(status_code=400, detail="유효하지 않은 영상 ID입니다.")

    gc.collect()

    deleted_files = []
    failed_files = []

    # DATA_DIR 전체 하위 경로(rglob) 대상 검색
    targets = set()
    for p in DATA_DIR.rglob("*"):
        if p.is_file():
            name = p.name
            if (clean_vid and clean_vid in name) or (safe_vid and safe_vid in name):
                targets.add(p)

    for p in targets:
        try:
            p.unlink()
            deleted_files.append(str(p.relative_to(DATA_DIR)))
        except Exception as e:
            print(f"[Delete Error] Failed to remove {p}: {e}")
            failed_files.append(str(p.relative_to(DATA_DIR)))

    # metadata_index.json에서 삭제 대상 항목 확실하게 제거
    raw_index = []
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                raw_index = json.load(f)
        except Exception as e:
            print(f"[Index Load Error] {e}")

    new_index = [
        item for item in raw_index 
        if item.get('id') != clean_vid and item.get('id') != safe_vid
    ]
    save_index(new_index)

    # 핵심 메타데이터 파일 삭제 실패 시 500 에러 처리
    meta_file1 = DATA_DIR / f"{clean_vid}_metadata.json"
    meta_file2 = DATA_DIR / f"{safe_vid}_metadata.json"
    if meta_file1.exists() or meta_file2.exists():
        raise HTTPException(
            status_code=500,
            detail=f"영상 데이터 파일 삭제에 실패했습니다. (오류 파일: {', '.join(failed_files)})"
        )

    return {
        "status": "success",
        "deleted_files": deleted_files,
        "failed_files": failed_files
    }

# ==========================================
# AI 프롬프트 스튜디오 API
# ==========================================
@app.get("/api/prompt/strengths")
async def get_prompt_strengths():
    strengths = PromptGenerator.extract_common_strengths(DATA_DIR)
    return {"status": "success", "data": strengths}

@app.get("/api/prompt/options")
async def get_prompt_options():
    return {
        "models": {k: {"name": v["name"], "description": v["description"], "default_aspect": v["default_aspect"]} for k, v in SUPPORTED_MODELS.items()},
        "style_presets": STYLE_PRESETS,
        "languages": SUPPORTED_LANGUAGES,
        "aspect_ratios": [
            {"value": "16:9", "label": "16:9 (Landscape - YouTube / Cinema)"},
            {"value": "9:16", "label": "9:16 (Portrait - Shorts / Reels / TikTok)"},
            {"value": "1:1", "label": "1:1 (Square - Instagram Feed)"},
            {"value": "21:9", "label": "21:9 (Cinemascope - Ultra-wide)"}
        ]
    }

@app.post("/api/prompt/generate-custom")
async def generate_custom_topic_prompts(req: PromptCustomTopicRequest):
    """8초 단위 씬 대본 및 AI 영상 생성 프롬프트 창작"""
    if not req.topic or not req.topic.strip():
        raise HTTPException(status_code=400, detail="새로운 영상 주제(Topic)를 입력해주세요.")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            PromptGenerator.generate_prompts_from_custom_topic,
            req.topic.strip(),
            req.scene_count,
            req.model,
            req.aspect_ratio,
            req.style_key,
            req.custom_subject or "",
            req.language or "korean",
            DATA_DIR
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"프롬프트 생성 실패: {str(e)}")

@app.post("/api/prompt/export")
async def export_prompts(req: PromptExportRequest):
    """AutoFlow-Pro 호환 TXT, CSV, JSON 형식으로 내보내기"""
    if not req.scenes:
        raise HTTPException(status_code=400, detail="내보낼 씬 데이터가 없습니다.")

    title_slug = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', req.video_title or "prompt_batch")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if req.format == "autoflow_txt":
        txt_content = PromptGenerator.export_autoflow_txt(req.scenes)
        filename = f"autoflow_prompts_{title_slug}_{timestamp}.txt"
        return PlainTextResponse(
            content=txt_content,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    elif req.format == "csv":
        csv_content = PromptGenerator.export_csv_data(req.scenes, req.video_title)
        filename = f"prompts_smart_task_{title_slug}_{timestamp}.csv"
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    else:
        json_content = json.dumps(req.scenes, ensure_ascii=False, indent=2)
        filename = f"prompts_workflow_{title_slug}_{timestamp}.json"
        return PlainTextResponse(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

# ==========================================
# 하이브리드 TTS & 음성 스튜디오 API
# ==========================================
@app.get("/api/tts/voices")
async def get_tts_voices():
    voices = TTSService.get_registered_voices()
    return {"status": "success", "data": voices}

@app.post("/api/tts/upload-voice")
async def upload_voice_clone(
    voice_file: UploadFile = File(...),
    voice_name: str = Form("내 목소리"),
    ref_text: str = Form("")
):
    allowed_exts = {".wav", ".mp3", ".m4a", ".ogg"}
    orig_name = Path(voice_file.filename or "voice.wav").name
    file_ext = Path(orig_name).suffix.lower()
    if file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="오디오 파일(.wav, .mp3, .m4a)만 업로드할 수 있습니다.")

    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', orig_name)
    temp_path = DATA_DIR / f"temp_{safe_name}"
    try:
        content = await voice_file.read()
        if len(content) > 30 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="음성 파일 크기는 최대 30MB를 초과할 수 없습니다.")

        with open(temp_path, "wb") as f:
            f.write(content)

        res = TTSService.register_my_voice(temp_path, voice_name=voice_name[:30], ref_text=ref_text[:300])
        if temp_path.exists():
            temp_path.unlink()
        return res
    except HTTPException:
        if temp_path.exists():
            temp_path.unlink()
        raise
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(status_code=500, detail=f"보이스 등록 실패: {str(e)}")

@app.post("/api/tts/generate-scene")
async def generate_scene_tts(req: TTSSceneRequest):
    """단일 씬 음성 합성 (Edge-TTS 고속 또는 Qwen-TTS)"""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="합성할 텍스트가 없습니다.")

    slug = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', req.topic_slug or "scene")[:20]
    res = TTSService.synthesize_speech(
        text=req.text.strip(),
        voice_id=req.voice_id,
        scene_index=req.scene_index,
        topic_slug=slug,
        language=req.language or "korean"
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "음성 합성 실패"))
    return res

@app.post("/api/tts/generate-all-scenes")
async def generate_all_scenes_tts(req: TTSBatchRequest):
    """전체 씬 일괄 고속 병렬 합성 + 마스터 오디오 병합 + 원클릭 ZIP 번들 생성"""
    if not req.scenes:
        raise HTTPException(status_code=400, detail="합성할 씬 목록이 없습니다.")

    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            TTSService.generate_all_scenes_audio_batch,
            req.scenes,
            req.topic or "custom_topic",
            req.voice_id
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"일괄 음성 합성 실패: {str(e)}")

@app.get("/api/audio/{filename:path}")
async def get_audio_file(filename: str):
    """오디오 스트리밍 서빙 (하위 폴더 포함 안전 검증)"""
    file_path = (AUDIO_DIR / filename).resolve()
    if not file_path.is_relative_to(AUDIO_DIR.resolve()) or not file_path.exists():
        raise HTTPException(status_code=404, detail="오디오 파일을 찾을 수 없습니다.")

    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(file_path, media_type=media_type)

@app.get("/api/audio/zip/{filename}")
async def download_audio_zip(filename: str):
    """원클릭 일괄 다운로드 ZIP 번들 서빙 (Path Traversal 방어)"""
    safe_name = Path(filename).name
    file_path = (ZIP_DIR / safe_name).resolve()
    if not file_path.is_relative_to(ZIP_DIR.resolve()) or not file_path.exists():
        raise HTTPException(status_code=404, detail="요청한 ZIP 파일을 찾을 수 없습니다.")

    return FileResponse(
        file_path,
        filename=safe_name,
        media_type="application/zip"
    )

@app.get("/api/export/csv")
async def export_csv():
    index = load_index()
    if not index:
        raise HTTPException(status_code=404, detail="저장된 메타데이터가 없습니다.")

    full_data = []
    for item in index:
        v_id = item.get('id')
        detail_path = DATA_DIR / f"{v_id}_metadata.json"
        if detail_path.exists():
            try:
                with open(detail_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    info = d.get("info", d)
                    full_data.append({
                        "ID": d.get("id"),
                        "제목": info.get("title"),
                        "채널": info.get("channel"),
                        "구독자수": info.get("channel_follower_count", 0),
                        "업로드일자": info.get("upload_date"),
                        "재생시간": info.get("duration_string", "00:00"),
                        "조회수": info.get("view_count"),
                        "좋아요수": info.get("like_count"),
                        "댓글수": info.get("comment_count"),
                        "AI리포트생성여부": "생성됨" if (DATA_DIR / f"{v_id}_리포트.txt").exists() else "미생성",
                        "영상URL": d.get("url"),
                        "분석일시": item.get("analyzed_at")
                    })
            except Exception:
                continue

    df = pd.DataFrame(full_data)
    csv_file = DATA_DIR / "youtube_metadata_export.csv"
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")
    return FileResponse(
        csv_file,
        filename=f"youtube_metadata_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        media_type="text/csv"
    )

@app.post("/api/open-folder")
async def open_data_folder():
    try:
        subprocess.run(["open", str(DATA_DIR)], check=True)
        return {"status": "success", "message": "Finder에서 data 폴더를 열었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"폴더 열기 실패: {str(e)}")

# ==========================================
# Phase 1: 트렌드 스카우터 API
# ==========================================
class TrendAnalyzeRequest(BaseModel):
    category_id: str = "0"
    trends_payload: Optional[Dict[str, Any]] = None

@app.get("/api/trends/top20")
async def get_trends_top20(category_id: str = Query("0"), region_code: str = Query("KR")):
    """카테고리별 실시간 인기 급상승 영상 Top 20 조회"""
    try:
        data = trend_scout.fetch_top20_trends(category_id=category_id, region_code=region_code)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"트렌드 조회 실패: {e}")

@app.post("/api/trends/analyze")
async def analyze_trends(req: TrendAnalyzeRequest):
    """실시간 급상승 Top 영상 기반 알고리즘 인사이트 리포트 생성"""
    try:
        payload = req.trends_payload
        if not payload:
            payload = trend_scout.fetch_top20_trends(category_id=req.category_id)
        result = trend_scout.analyze_trends_with_llm(payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"트렌드 분석 실패: {e}")


# ==========================================
# Phase 1: 채널 빌더 & 레오의 채널 진단 API
# ==========================================
class ChannelGenRequest(BaseModel):
    topic: str
    concept: Optional[str] = ""
    target_audience: Optional[str] = ""
    language: Optional[str] = "ko"
    category_id: Optional[int] = 28

@app.get("/api/channel/check-handle")
async def check_handle(handle: str = Query(...)):
    """유튜브 실시간 핸들(@) 중복 확인"""
    available, msg = channel_builder.check_handle_availability(handle)
    return {"available": available, "message": msg, "handle": handle}

@app.post("/api/channel/generate")
async def generate_channel(req: ChannelGenRequest):
    """8대 채널 세팅 AI 기획 자동 생성"""
    try:
        plan = channel_builder.generate_channel_settings(
            topic=req.topic,
            concept=req.concept or "",
            target_audience=req.target_audience or "",
            category_id=req.category_id or 28,
            language=req.language or "ko"
        )
        return plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채널 기획 실패: {e}")

@app.get("/api/channel/my-status")
async def get_channel_diagnostics():
    """로그인된 내 채널 통계 및 에이전트 레오의 알고리즘 성장 진단"""
    try:
        diag = channel_builder.get_my_channel_diagnostics()
        return diag
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채널 진단 실패: {e}")

@app.get("/api/channel/history")
async def get_channel_history():
    """저장된 채널 기획서 목록 조회"""
    return channel_builder.list_plans()

@app.get("/api/channel/plan/{plan_id}")
async def get_channel_plan(plan_id: str):
    """특정 채널 기획서 상세 조회"""
    plan = channel_builder.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="채널 기획서를 찾을 수 없습니다.")
    return plan


# ==========================================
# Phase 3: 원소스 멀티유즈(OSMU) 마케팅 엔진 API
# ==========================================
class MarketingGenRequest(BaseModel):
    topic: str
    context: Optional[str] = ""
    mode: Optional[str] = "all"  # all | threads | blog | newsletter
    tone: Optional[str] = "viral_hook"
    audience: Optional[str] = "크리에이터, 직장인, 마케터"
    platform: Optional[str] = "threads"
    thread_count: Optional[int] = 5
    blog_length: Optional[str] = "medium"
    campaign_type: Optional[str] = "educational"

@app.post("/api/marketing/generate")
async def generate_marketing_content(req: MarketingGenRequest):
    """멀티채널 마케팅(스레드, 블로그, 뉴스레터) 올인원 생성"""
    try:
        mode = req.mode or "all"
        if mode == "threads":
            res = marketing.generate_threads_x(
                topic=req.topic,
                context=req.context or "",
                platform=req.platform or "threads",
                tone=req.tone or "viral_hook",
                count=req.thread_count or 5,
                audience=req.audience or ""
            )
        elif mode == "blog":
            res = marketing.generate_blog_post(
                topic=req.topic,
                context=req.context or "",
                target_audience=req.audience or "",
                length=req.blog_length or "medium",
                tone=req.tone or "informative"
            )
        elif mode == "newsletter":
            res = marketing.generate_newsletter(
                topic=req.topic,
                context=req.context or "",
                campaign_type=req.campaign_type or "educational",
                audience=req.audience or ""
            )
        else:
            res = marketing.generate_omni_marketing(
                topic=req.topic,
                context=req.context or "",
                tone=req.tone or "viral_hook",
                audience=req.audience or ""
            )

        entry_id = marketing.save_entry(req.topic, mode, res)
        return {"status": "success", "id": entry_id, "mode": mode, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"마케팅 생성 실패: {e}")

@app.get("/api/marketing/history")
async def get_marketing_history():
    """마케팅 보관함 목록"""
    return marketing.list_marketing_history()

@app.get("/api/marketing/{entry_id}")
async def get_marketing_item(entry_id: str):
    """마케팅 포스트 상세 조회"""
    item = marketing.load_entry(entry_id)
    if not item:
        raise HTTPException(status_code=404, detail="마케팅 문서를 찾을 수 없습니다.")
    return item


# ==========================================
# Phase 4: 영상 자동 제작 (Producer) & 유튜브 업로더 API
# ==========================================
_producer_jobs: Dict[str, Dict[str, Any]] = {}

class ProducerBuildRequest(BaseModel):
    plan_id: str
    resolution: Optional[str] = "1080p"
    burn_subtitles: Optional[bool] = True
    subtitle_style: Optional[str] = "clean"
    fit_narration: Optional[bool] = True
    transition: Optional[str] = "fade"
    sfx_volume: Optional[float] = 0.35

def _run_build_worker(job_id: str, plan_dict: dict, options: dict):
    def on_progress(step, msg, pct):
        _producer_jobs[job_id] = {
            "status": "processing",
            "step": step,
            "message": msg,
            "percent": pct
        }

    try:
        res = producer.build_video(plan_dict, options=options, progress=on_progress)
        _producer_jobs[job_id] = {
            "status": "completed",
            "percent": 100,
            "message": "영상 합성이 완료되었습니다.",
            "result": res
        }
    except Exception as e:
        _producer_jobs[job_id] = {
            "status": "failed",
            "percent": 0,
            "message": f"합성 실패: {str(e)}"
        }

@app.post("/api/producer/build")
async def build_video_endpoint(req: ProducerBuildRequest, background_tasks: BackgroundTasks):
    """ffmpeg 기반 영상 합성 작업 시작 (BackgroundTasks)"""
    plan = channel_builder.get_plan(req.plan_id)
    if not plan:
        # 혹시 output 디렉토리의 기획서인지 확인
        plan_file = OUTPUT_DIR / f"{req.plan_id}.json"
        if plan_file.exists():
            with open(plan_file, "r", encoding="utf-8") as f:
                plan = json.load(f)

    if not plan:
        raise HTTPException(status_code=404, detail="합성할 기획서(plan_id)를 찾을 수 없습니다.")

    job_id = f"job_{int(time.time() * 1000)}"
    _producer_jobs[job_id] = {
        "status": "queued",
        "percent": 0,
        "message": "영상 합성 대기 중..."
    }

    options = {
        "resolution": req.resolution or "1080p",
        "burn_subtitles": req.burn_subtitles,
        "subtitle_style": req.subtitle_style or "clean",
        "fit_narration": req.fit_narration,
        "transition": req.transition or "fade",
        "sfx_volume": req.sfx_volume or 0.35
    }

    background_tasks.add_task(_run_build_worker, job_id, plan, options)
    return {"status": "success", "job_id": job_id}

@app.get("/api/producer/status/{job_id}")
async def get_producer_status(job_id: str):
    """영상 합성 진행 상태 조회"""
    job = _producer_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업 ID를 찾을 수 없습니다.")
    return job

@app.get("/api/youtube/status")
async def get_youtube_status():
    """유튜브 OAuth 인증 및 연동 채널 상태 조회"""
    return uploader.status()

class YoutubeUploadRequest(BaseModel):
    video_file: str
    title: str
    description: Optional[str] = ""
    tags: Optional[List[str]] = []
    category_id: Optional[str] = "28"
    privacy_status: Optional[str] = "unlisted"
    thumbnail_file: Optional[str] = None
    pinned_comment: Optional[str] = None

@app.post("/api/youtube/upload")
async def upload_youtube_video(req: YoutubeUploadRequest):
    """YouTube Data API v3 원클릭 영상, 썸네일, 고정댓글 업로드"""
    st = uploader.status()
    if not st.get("authorized"):
        raise HTTPException(status_code=401, detail="YouTube OAuth 계정 인증이 필요합니다.")

    try:
        res = uploader.upload_video(
            video_file=req.video_file,
            title=req.title,
            description=req.description or "",
            tags=req.tags or [],
            category_id=req.category_id or "28",
            privacy_status=req.privacy_status or "unlisted",
            thumbnail_file=req.thumbnail_file,
            pinned_comment=req.pinned_comment
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"유튜브 업로드 실패: {e}")


# ==========================================
# 정적 파일 서빙 및 렌더 디렉토리 마운트
# ==========================================
if os.path.exists(producer.RENDERS_DIR):
    app.mount("/data/renders", StaticFiles(directory=str(producer.RENDERS_DIR)), name="renders")
if os.path.exists(channel_builder.CHANNELS_DIR):
    app.mount("/data/channels", StaticFiles(directory=str(channel_builder.CHANNELS_DIR)), name="channels")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=True)
