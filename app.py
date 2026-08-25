import os
import re
import sys
import json
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
    deleted_files = []
    for p in DATA_DIR.glob(f"*{video_id}*"):
        if p.is_file():
            try:
                p.unlink()
                deleted_files.append(p.name)
            except Exception as e:
                print(f"[Delete Error] {e}")

    index = load_index()
    index = [item for item in index if item.get('id') != video_id]
    save_index(index)

    return {"status": "success", "deleted_files": deleted_files}

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

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=True)
