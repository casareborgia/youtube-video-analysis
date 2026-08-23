import os
import re
import sys
import json
import asyncio
import subprocess
import urllib.request
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, validator
import pandas as pd
import yt_dlp

app = FastAPI(title="YouTube Video Analyzer & Metadata Extractor with Local AI")

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
SAFE_FILENAME_REGEX = re.compile(r'^[a-zA-Z0-9_.-]+$')

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

# 기본 저장 경로 설정
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

# 메타데이터 인덱스 파일
INDEX_FILE = DATA_DIR / "metadata_index.json"

def load_index() -> List[Dict[str, Any]]:
    """메타데이터 인덱스를 로드하고, 실제 파일이 삭제된 고아 데이터는 자동 동기화/정리"""
    if not INDEX_FILE.exists():
        return []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            raw_index = json.load(f)
            
        # 실제 메타데이터 파일이 존재하는 항목만 유효 항목으로 유지
        valid_index = []
        is_changed = False
        for item in raw_index:
            v_id = item.get("id")
            if not v_id:
                is_changed = True
                continue
            meta_file = DATA_DIR / f"{v_id}_metadata.json"
            if meta_file.exists():
                # 리포트 파일 존재 여부 실시간 최신화
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

def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def extract_transcript(video_id: str) -> str:
    """yt-dlp로 한국어 자막(srt)을 추출하고 텍스트로 정제"""
    srt_base = str(DATA_DIR / video_id)
    srt_path = DATA_DIR / f"{video_id}.ko.srt"
    
    if not srt_path.exists():
        try:
            subprocess.run([
                "yt-dlp", "--skip-download", "--write-auto-subs", "--sub-langs", "ko",
                "--convert-subs", "srt", "-o", srt_base, f"https://youtu.be/{video_id}"
            ], capture_output=True, text=True, timeout=60)
        except Exception:
            pass

    if srt_path.exists():
        try:
            seen = []
            for l in open(srt_path, encoding="utf-8").read().splitlines():
                l = l.strip()
                if not l or l.isdigit() or "-->" in l:
                    continue
                if not seen or seen[-1] != l:
                    seen.append(l)
            return " ".join(seen)
        except Exception as e:
            return f"(자막 파싱 실패: {str(e)})"
    
    return "(자막 없음)"

def clean_description(desc: str) -> str:
    """설명란에서 불필요한 SNS 링크, 스폰서, 단순 태그 도배만 걸러내고 본문 시놉시스 유지"""
    if not desc:
        return ""
    lines = []
    for l in desc.splitlines():
        l_str = l.strip()
        if not l_str or l_str.startswith("http") or l_str.startswith("www."):
            continue
        if "인스타그램" in l_str or "페이스북" in l_str or "트위터" in l_str or "협찬문의" in l_str:
            continue
        lines.append(l_str)
    return "\n".join(lines)[:600]

def optimize_transcript(transcript: str, max_chars: int = 4000) -> str:
    """자막의 연속 중복 타임라인과 불필요한 음향 태그만 스마트 제거하여 문맥 깊이 100% 보존"""
    if not transcript or transcript == "(자막 없음)":
        return "(자막 없음)"
    cleaned = re.sub(r'\[(?:음악|박수|노래|한숨)\]|\>\>', ' ', transcript)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > max_chars:
        return cleaned[:max_chars]
    return cleaned

def call_local_ai_gemma(prompt: str, model_name: str = "gemma4:latest") -> str:
    """Ollama (1순위, 16384 컨텍스트 & 4096 출력 토큰) 및 LM Studio (2순위) 하이브리드 로컬 AI 호출"""
    # 1. Ollama 우선 시도 (Thinking 토큰을 감안하여 16384 ctx 및 4096 predict 완전 보장)
    try:
        ollama_data = json.dumps({
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "당신은 대한민국 최고의 유튜브 콘텐츠 전략가이자 심층 영상 분석가입니다.\n"
                        "주어진 영상의 메타데이터, 자막 흐름, 시청자 댓글 여론을 다각도로 분석하여 매우 전문적이고 깊이 있는 리포트를 작성하세요.\n"
                        "형식적인 요약에 그치지 말고, 영상의 본질적인 흥행 원리와 구체적인 시사점을 담아 아래 5가지 목차를 1번부터 5번 끝까지 완벽하게 작성해야 합니다."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "options": {
                "num_ctx": 16384,
                "num_predict": 4096,
                "temperature": 0.6
            },
            "stream": false
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=ollama_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            if "message" in res_json and "content" in res_json["message"]:
                content = res_json["message"]["content"]
                if content and len(content.strip()) > 100:
                    return content
    except Exception as ollama_err:
        pass

    # 2. LM Studio 폴백 시도
    try:
        lm_data = json.dumps({
            "model": "google/gemma-4-e4b",
            "messages": [
                {
                    "role": "system", 
                    "content": (
                        "당신은 대한민국 최고의 유튜브 콘텐츠 전략가이자 심층 영상 분석가입니다.\n"
                        "주어진 영상의 메타데이터, 자막 흐름, 시청자 댓글 여론을 다각도로 분석하여 매우 전문적이고 깊이 있는 리포트를 작성하세요.\n"
                        "형식적인 요약에 그치지 말고, 영상의 본질적인 흥행 원리와 구체적인 시사점을 담아 아래 5가지 목차를 1번부터 5번 끝까지 완벽하게 작성해야 합니다."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.6,
            "max_tokens": 4096
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://127.0.0.1:1234/v1/chat/completions",
            data=lm_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        return f"(Ollama 및 LM Studio 로컬 서버 연결 실패: {str(e)}\n\n아래 프롬프트를 AI에 직접 복사하여 사용하세요)\n\n" + prompt

def generate_video_ai_report(video_id: str) -> Dict[str, Any]:
    """메타데이터, 자막, 댓글을 종합하여 고품질 심층 AI 리포트 생성"""
    meta_path = DATA_DIR / f"{video_id}_metadata.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="영상 메타데이터를 먼저 수집해야 합니다.")
    
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 1. 자막 및 설명란 스마트 정제 (문맥 훼손 없는 노이즈 제거)
    raw_transcript = extract_transcript(video_id)
    transcript = optimize_transcript(raw_transcript, max_chars=4000)
    cleaned_desc = clean_description(meta.get("description", ""))

    # 2. 상위 공감 댓글 선별 (상위 12개, 추천수 명시)
    comments = meta.get("comments", [])
    top_comments = ["• [" + str(c.get("like_count",0)) + "개 추천] " + (c.get("text") or "").replace("\n", " ")[:90] for c in comments[:12]]

    # 3. 챕터 정보가 있는 경우 서사 흐름에 반영
    chapters = meta.get("chapters", [])
    chapters_str = "\n".join([f"- {c.get('start_time_formatted')} {c.get('title')}" for c in chapters[:10]]) if chapters else "(챕터 정보 없음)"

    # 4. 정밀 메타데이터
    info_dict = {
        "title": meta.get("title"),
        "channel": meta.get("channel"),
        "channel_follower_count": meta.get("channel_follower_count"),
        "view_count": meta.get("view_count"),
        "like_count": meta.get("like_count"),
        "comment_count": meta.get("comment_count"),
        "duration": meta.get("duration_string") or meta.get("duration_formatted"),
        "upload_date": meta.get("upload_date")
    }

    prompt = (
        "아래 유튜브 영상을 다각도로 심층 분석하여 최고 수준의 분석 리포트를 작성해줘.\n\n"
        "[영상 메타데이터]\n" + json.dumps(info_dict, ensure_ascii=False, indent=2) + "\n\n"
        "[영상 설명란]\n" + (cleaned_desc or "(설명 없음)") + "\n\n"
        "[챕터 타임라인]\n" + chapters_str + "\n\n"
        "[자막 전문 흐름]\n" + transcript + "\n\n"
        "[시청자 상위 댓글 여론]\n" + ("\n".join(top_comments) if top_comments else "(댓글 없음)") + "\n\n"
        "--- 반드시 아래 5가지 목차에 따라 심도 있는 분석과 구체적인 액션 플랜을 1번부터 5번 끝까지 완성해주세요 ---\n"
        "## 1. 제목·훅 구조 분석\n"
        "- 클릭을 유발한 심리적 트리거와 제목 키워드 분석\n"
        "- 영상 초반 이탈을 막은 인트로 훅(Hook) 설계 원리\n\n"
        "## 2. 전개 방식 (단계별 서사 구조)\n"
        "- 도입 → 전개 → 절정 → 결말의 단계별 빌드업 메커니즘\n"
        "- 시청 지속 시간을 극대화한 완급 조절 및 연출 특징\n\n"
        "## 3. 핵심 메시지 및 인사이트\n"
        "- 영상이 관객에게 남기는 궁극적인 메시지와 철학/본질\n"
        "- 단순 정보 나열을 넘어선 고유의 콘텐츠적 가치\n\n"
        "## 4. 댓글 여론 특징 및 시청자 반응\n"
        "- 시청자들이 가장 감탄하거나 공감한 포인트 분석\n"
        "- 댓글 반응을 통해 본 채널 팬덤의 특성과 몰입 요인\n\n"
        "## 5. 내 채널/콘텐츠에 적용할 점 3가지 (구체적 실행 방안)\n"
        "- **전략 1 (기획/제목/썸네일):** 내 채널에 바로 적용할 수 있는 구체적인 실행 계획\n"
        "- **전략 2 (연출/스토리텔링):** 시청 유지율을 높이기 위한 실전 연출 방안\n"
        "- **전략 3 (팬덤 구축/확장):** 댓글 참여 및 충성 구독자를 만드는 실행 방안"
    )

    # 4. 로컬 AI 호출
    report_content = call_local_ai_gemma(prompt)

    # 5. 리포트 파일 저장: [video_id]_리포트.txt
    report_file = DATA_DIR / f"{video_id}_리포트.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    # 메타데이터 갱신
    meta["ai_report"] = report_content
    meta["transcript"] = transcript[:3000]
    meta["has_ai_report"] = True
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "video_id": video_id,
        "report": report_content,
        "transcript_length": len(transcript),
        "report_file": str(report_file)
    }

def extract_single_video_metadata(
    url: str, 
    extract_subs: bool = True,
    extract_comments: bool = True,
    max_comments: int = 100,
    auto_ai_report: bool = False
) -> Dict[str, Any]:
    """단일 영상 상세 메타데이터, 챕터, 구독자 수, 댓글(Comments) 심층 추출"""
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'writesubtitles': extract_subs,
        'writeautomaticsub': extract_subs,
        'subtitleslangs': ['ko', 'en', 'auto'],
    }

    if extract_comments and max_comments > 0:
        ydl_opts['getcomments'] = True
        ydl_opts['extractor_args'] = {
            'youtube': {
                'max_comments': [str(max_comments), 'all', '10', '0']
            }
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise HTTPException(status_code=404, detail="영상 상세 정보를 가져올 수 없습니다.")

    video_id = info.get('id', '')
    title = info.get('title', '')
    channel = info.get('uploader') or info.get('channel', '')
    channel_id = info.get('channel_id', '')
    channel_url = info.get('uploader_url') or info.get('channel_url', '')
    channel_follower_count = info.get('channel_follower_count') or 0

    view_count = info.get('view_count', 0) or 0
    like_count = info.get('like_count', 0) or 0
    comment_count = info.get('comment_count', 0) or 0
    duration = info.get('duration', 0) or 0
    duration_string = info.get('duration_string') or format_duration(duration)
    
    upload_date = info.get('upload_date', '')
    if upload_date and len(upload_date) == 8:
        formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    else:
        formatted_date = upload_date

    description = info.get('description', '') or ''
    tags = info.get('tags', []) or []
    categories = info.get('categories', []) or []
    thumbnail = info.get('thumbnail', '')
    webpage_url = info.get('webpage_url', url)

    # 챕터 (Chapters)
    raw_chapters = info.get('chapters') or []
    chapters = []
    for idx, chap in enumerate(raw_chapters, start=1):
        chapters.append({
            "index": idx,
            "title": chap.get('title', f"Chapter {idx}"),
            "start_time": chap.get('start_time', 0),
            "end_time": chap.get('end_time', 0),
            "start_time_formatted": format_duration(int(chap.get('start_time', 0))),
            "end_time_formatted": format_duration(int(chap.get('end_time', 0)))
        })

    # 가용 해상도
    formats = info.get('formats', [])
    resolution_list = []
    for f in formats:
        height = f.get('height')
        if height and f"{height}p" not in resolution_list:
            resolution_list.append(f"{height}p")

    # 자막 요약
    subtitles = info.get('subtitles', {}) or {}
    automatic_captions = info.get('automatic_captions', {}) or {}
    subtitles_summary = {
        "manual_languages": list(subtitles.keys()),
        "automatic_languages": list(automatic_captions.keys()),
        "total_manual_count": len(subtitles),
        "total_auto_count": len(automatic_captions)
    }

    # 댓글 (Comments)
    raw_comments_iter = info.get('comments') or []
    raw_comments = list(raw_comments_iter)
    processed_comments = []
    for c in raw_comments:
        c_author = c.get('author') or 'Anonymous'
        c_author_id = c.get('author_id') or ''
        c_text = c.get('text') or ''
        c_like_count = c.get('like_count') or 0
        c_timestamp = c.get('timestamp')
        c_date = ''
        if c_timestamp:
            try:
                c_date = datetime.fromtimestamp(c_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                c_date = str(c_timestamp)
        
        processed_comments.append({
            "id": c.get('id', ''),
            "author": c_author,
            "author_id": c_author_id,
            "author_thumbnail": c.get('author_thumbnail', ''),
            "text": c_text,
            "like_count": c_like_count,
            "reply_count": c.get('reply_count', 0) or 0,
            "date": c_date,
            "is_favorited": c.get('is_favorited', False)
        })

    processed_comments.sort(key=lambda c: c.get('like_count') or 0, reverse=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "id": video_id,
        "title": title,
        "channel": channel,
        "channel_id": channel_id,
        "channel_url": channel_url,
        "channel_follower_count": channel_follower_count,
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "duration": duration,
        "duration_string": duration_string,
        "duration_formatted": format_duration(duration),
        "upload_date": formatted_date,
        "analyzed_at": now_str,
        "url": webpage_url,
        "thumbnail": thumbnail,
        "description": description,
        "tags": tags,
        "categories": categories,
        "chapters": chapters,
        "subtitles": subtitles_summary,
        "resolutions": sorted(resolution_list, key=lambda x: int(x.replace('p', '')) if x.replace('p', '').isdigit() else 0, reverse=True),
        "comments_count_extracted": len(processed_comments),
        "comments": processed_comments,
        "has_ai_report": False
    }

    # 개별 JSON 저장
    save_filename = f"{video_id}_metadata.json"
    file_path = DATA_DIR / save_filename
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # c.info.json 저장
    c_info_file_path = DATA_DIR / f"{video_id}_c.info.json"
    c_info_data = {
        "id": video_id,
        "title": title,
        "channel": channel,
        "channel_follower_count": channel_follower_count,
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "duration_string": duration_string,
        "upload_date": formatted_date,
        "chapters": chapters,
        "description": description,
        "subtitles": subtitles,
        "automatic_captions": automatic_captions,
        "comments": processed_comments
    }
    with open(c_info_file_path, "w", encoding="utf-8") as f:
        json.dump(c_info_data, f, ensure_ascii=False, indent=2)

    if processed_comments:
        comments_df = pd.DataFrame(processed_comments)
        comments_csv_path = DATA_DIR / f"{video_id}_comments.csv"
        comments_df.to_csv(comments_csv_path, index=False, encoding="utf-8-sig")

    # 자동 AI 리포트 옵션이 켜진 경우 실행
    ai_report_res = None
    if auto_ai_report:
        try:
            ai_report_res = generate_video_ai_report(video_id)
            metadata["ai_report"] = ai_report_res.get("report")
            metadata["has_ai_report"] = True
        except Exception:
            pass

    # 인덱스 갱신
    index = load_index()
    index = [item for item in index if item.get('id') != video_id]
    index.insert(0, {
        "id": video_id,
        "title": title,
        "channel": channel,
        "channel_follower_count": channel_follower_count,
        "upload_date": formatted_date,
        "duration_string": duration_string,
        "duration_formatted": format_duration(duration),
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "comments_extracted": len(processed_comments),
        "chapters_count": len(chapters),
        "has_ai_report": metadata.get("has_ai_report", False),
        "analyzed_at": now_str,
        "url": webpage_url,
        "thumbnail": thumbnail,
        "file_name": save_filename
    })
    save_index(index)

    return metadata

def extract_metadata_from_ytdlp(
    url: str, 
    extract_subs: bool = True, 
    extract_comments: bool = True,
    max_comments: int = 100,
    auto_ai_report: bool = False,
    max_items: int = 10
) -> List[Dict[str, Any]]:
    ydl_opts = {
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'quiet': True,
        'no_warnings': True,
    }

    results = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"yt-dlp 정보 추출 실패: {str(e)}")

        if not info:
            raise HTTPException(status_code=404, detail="영상 정보를 찾을 수 없습니다.")

        entries = info.get('entries')
        if entries:
            items_to_process = list(entries)[:max_items]
            for entry in items_to_process:
                video_url = entry.get('url') or entry.get('webpage_url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                try:
                    detailed_info = extract_single_video_metadata(
                        video_url, 
                        extract_subs=extract_subs,
                        extract_comments=extract_comments,
                        max_comments=max_comments,
                        auto_ai_report=auto_ai_report
                    )
                    results.append(detailed_info)
                except Exception as ex:
                    print(f"Error processing {video_url}: {ex}")
                    continue
        else:
            detailed_info = extract_single_video_metadata(
                url, 
                extract_subs=extract_subs,
                extract_comments=extract_comments,
                max_comments=max_comments,
                auto_ai_report=auto_ai_report
            )
            results.append(detailed_info)

    return results

@app.post("/api/analyze")
async def analyze_youtube(req: AnalyzeRequest):
    """유튜브 단일 영상 또는 재생목록의 메타데이터 및 댓글 심층 분석"""
    try:
        safe_url = verify_youtube_url(req.url)
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, 
            extract_metadata_from_ytdlp, 
            safe_url, 
            req.extract_subtitles,
            req.extract_comments,
            req.max_comments,
            req.auto_generate_ai_report,
            req.max_playlist_items or 10
        )
        return {"status": "success", "count": len(results), "data": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/ai-analyze/{video_id}")
async def run_ai_analysis(video_id: str):
    """LM Studio google/gemma-4-e4b 모델로 AI 리포트 비동기 생성"""
    safe_id = verify_video_id(video_id)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, generate_video_ai_report, safe_id)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    
    # 리포트 파일 내용이 있으면 로드
    report_file = DATA_DIR / f"{video_id}_리포트.txt"
    if report_file.exists():
        try:
            with open(report_file, "r", encoding="utf-8") as rf:
                data["ai_report"] = rf.read()
                data["has_ai_report"] = True
        except Exception:
            pass
            
    return {"status": "success", "data": data}

@app.get("/api/comments/{video_id}/csv")
async def export_video_comments_csv(video_id: str):
    file_path = DATA_DIR / f"{video_id}_metadata.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="해당 영상 데이터를 찾을 수 없습니다.")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    comments = data.get("comments", [])
    if not comments:
        raise HTTPException(status_code=404, detail="수집된 댓글이 없습니다.")

    df = pd.DataFrame(comments)
    csv_file = DATA_DIR / f"{video_id}_comments_export.csv"
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")
    return FileResponse(
        csv_file,
        filename=f"{video_id}_comments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        media_type="text/csv"
    )

@app.delete("/api/metadata/{video_id}")
async def delete_metadata(video_id: str):
    """영상 및 그에 연관된 모든 정보, 자막, AI 리포트, 오디오 파일 등을 완전 삭제"""
    deleted_files = []
    
    # 1. data/ 디렉토리 내 video_id가 포함된 모든 파일 검색 및 삭제
    for p in DATA_DIR.glob(f"*{video_id}*"):
        if p.is_file():
            try:
                p.unlink()
                deleted_files.append(p.name)
            except Exception as e:
                print(f"[Delete Error] {p.name}: {e}")
                
    # 2. data/audio/ 디렉토리 내 video_id가 포함된 오디오 파일 삭제
    audio_dir = DATA_DIR / "audio"
    if audio_dir.exists():
        for ap in audio_dir.glob(f"*{video_id}*"):
            if ap.is_file():
                try:
                    ap.unlink()
                    deleted_files.append(f"audio/{ap.name}")
                except Exception:
                    pass

    # 3. 메타데이터 인덱스 파일에서 제거
    index = load_index()
    index = [item for item in index if item.get('id') != video_id]
    save_index(index)
    
    return {
        "status": "success", 
        "message": f"영상({video_id}) 및 연관된 메타데이터, 자막, AI 리포트 등 총 {len(deleted_files)}개 파일이 완전히 삭제되었습니다.",
        "deleted_files": deleted_files
    }

# ==========================================
# AI 프롬프트 스튜디오 & AutoFlow-Pro 연동 API
# ==========================================
from prompt_generator import (
    PromptGenerator, 
    STYLE_PRESETS, 
    SUPPORTED_MODELS,
    SUPPORTED_LANGUAGES
)
from tts_service import TTSService, AUDIO_DIR

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
    voice_id: str = "docu_male"
    scene_index: int = 1
    topic_slug: Optional[str] = "scene"
    language: Optional[str] = "korean"

class TTSBatchRequest(BaseModel):
    scenes: List[Dict[str, Any]]
    voice_id: str = "docu_male"
    topic: Optional[str] = "custom_topic"
    language: Optional[str] = "korean"

@app.get("/api/prompt/strengths")
async def get_prompt_strengths():
    """분석 완료된 영상들에서 공통 도출된 성공 강점 및 패턴 제공"""
    strengths = PromptGenerator.extract_common_strengths(DATA_DIR)
    return {"status": "success", "data": strengths}

@app.get("/api/prompt/options")
async def get_prompt_options():
    """프롬프트 생성기 옵션 제공"""
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
    """사용자가 새로 입력한 주제에 대해 분석 영상 공통 강점을 반영하여 씬별 AI 프롬프트 생성"""
    if not req.topic or not req.topic.strip():
        raise HTTPException(status_code=400, detail="새로운 영상 주제(Topic)를 입력해주세요.")
        
    try:
        result = PromptGenerator.generate_prompts_from_custom_topic(
            topic=req.topic.strip(),
            scene_count=req.scene_count,
            model=req.model,
            aspect_ratio=req.aspect_ratio,
            style_key=req.style_key,
            custom_subject=req.custom_subject or "",
            language=req.language or "korean",
            data_dir=DATA_DIR
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"프롬프트 생성 실패: {str(e)}")

# ==========================================
# Qwen-TTS & Voice Clone 음성 합성 API
# ==========================================
@app.get("/api/tts/voices")
async def get_tts_voices():
    """사용 가능한 모든 보이스 목록 (내 목소리 Voice Clone 포함) 반환"""
    voices = TTSService.get_registered_voices()
    return {"status": "success", "data": voices}

@app.post("/api/tts/upload-voice")
async def upload_voice_clone(
    voice_file: UploadFile = File(...),
    voice_name: str = Form("내 목소리"),
    ref_text: str = Form("")
):
    """내 목소리 오디오 파일 업로드 및 Voice Clone 프로필 등록"""
    # 1. 파일 확장자 검증
    allowed_exts = {".wav", ".mp3", ".m4a", ".ogg"}
    orig_name = Path(voice_file.filename or "voice.wav").name
    file_ext = Path(orig_name).suffix.lower()
    if file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="오디오 파일(.wav, .mp3, .m4a)만 업로드할 수 있습니다.")
    
    # 2. 안전한 임시 파일 생성
    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', orig_name)
    temp_path = DATA_DIR / f"temp_{safe_name}"
    try:
        content = await voice_file.read()
        if len(content) > 30 * 1024 * 1024:  # 30MB 제한
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
    """단일 씬 대본 텍스트에 대한 음성 합성"""
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

@app.post("/api/tts/generate-batch")
async def generate_batch_tts(req: TTSBatchRequest):
    """전체 씬 일괄 음성 합성"""
    if not req.scenes:
        raise HTTPException(status_code=400, detail="합성할 씬 목록이 없습니다.")
        
    slug = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', req.topic or "topic")[:20]
    results = []
    
    for idx, sc in enumerate(req.scenes):
        narration = sc.get("narration", "").strip()
        if not narration:
            continue
        scene_idx = sc.get("scene_index", idx + 1)
        res = TTSService.synthesize_speech(
            text=narration,
            voice_id=req.voice_id,
            scene_index=scene_idx,
            topic_slug=slug,
            language=req.language or "korean"
        )
        results.append(res)
        
    return {
        "status": "success",
        "total": len(results),
        "data": results
    }

@app.get("/api/audio/{filename}")
async def get_audio_file(filename: str):
    """합성된 오디오 파일 스트리밍 서빙 (경로 순회 공격 방어)"""
    safe_name = Path(filename).name
    if not SAFE_FILENAME_REGEX.match(safe_name) or not safe_name.endswith(".wav"):
        raise HTTPException(status_code=400, detail="잘못된 오디오 파일명 형식입니다.")
        
    file_path = (AUDIO_DIR / safe_name).resolve()
    if not file_path.is_relative_to(AUDIO_DIR.resolve()) or not file_path.exists():
        raise HTTPException(status_code=404, detail="오디오 파일을 찾을 수 없습니다.")
    return FileResponse(file_path, media_type="audio/wav")

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
    else:  # json
        json_content = json.dumps(req.scenes, ensure_ascii=False, indent=2)
        filename = f"prompts_workflow_{title_slug}_{timestamp}.json"
        return PlainTextResponse(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
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
                    chapters_titles = [c.get("title", "") for c in d.get("chapters", [])]
                    full_data.append({
                        "ID": d.get("id"),
                        "제목": d.get("title"),
                        "채널": d.get("channel"),
                        "구독자수": d.get("channel_follower_count", 0),
                        "업로드일자": d.get("upload_date"),
                        "재생시간": d.get("duration_string") or d.get("duration_formatted"),
                        "조회수": d.get("view_count"),
                        "좋아요수": d.get("like_count"),
                        "댓글수": d.get("comment_count"),
                        "수집된댓글수": d.get("comments_count_extracted", 0),
                        "챕터개수": len(d.get("chapters", [])),
                        "챕터목록": " | ".join(chapters_titles),
                        "태그": ", ".join(d.get("tags", [])),
                        "카테고리": ", ".join(d.get("categories", [])),
                        "AI리포트생성여부": "생성됨" if (DATA_DIR / f"{v_id}_리포트.txt").exists() else "미생성",
                        "영상URL": d.get("url"),
                        "분석일시": d.get("analyzed_at")
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
    """Mac Finder로 data 폴더 열기"""
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

