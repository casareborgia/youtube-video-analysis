"""
유튜브 영상 심층 분석 독립 모듈
- yt-dlp 메타데이터 및 댓글 수집
- VTT / SRT 정밀 타임스탬프 자막 파서
- llm_client (LM Studio / Ollama 자동 감지 & 자동 이어쓰기) 연동
"""

import sys
import os
import re
import json
import glob
import subprocess
from pathlib import Path
import llm_client

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def sh(args, cwd=None):
    return subprocess.run(args, capture_output=True, text=True, cwd=str(cwd or BASE_DIR)).stdout


def extract_video_id(url: str) -> str:
    match = re.search(r'(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})', url)
    return match.group(1) if match else None


def parse_subtitles_with_timestamps(filepath: str) -> str:
    """
    VTT / SRT 자막 파일에서 [MM:SS] 타임스탬프와 함께 발화 텍스트를 정확하게 추출합니다.
    """
    if not os.path.exists(filepath):
        return ""

    content = open(filepath, encoding="utf-8", errors="ignore").read()

    cue_blocks = re.findall(
        r'(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3}) --> (?:\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})[^\n]*\n([\s\S]*?)(?=\n(?:\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})|\Z)',
        content
    )

    segments = []
    for start_time, body in cue_blocks:
        lines = body.strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = start_time.split(':')
            if len(parts) == 3:
                m, s = parts[1], parts[2].split('.')[0]
                t_str = f"{m}:{s}"
            elif len(parts) == 2:
                m, s = parts[0], parts[1].split('.')[0]
                t_str = f"{m}:{s}"
            else:
                t_str = "00:00"

            if '<' in line and '>' in line:
                clean_text = re.sub(r'<[^>]+>', '', line)
                clean_text = re.sub(r'align:[^\s]+', '', clean_text)
                clean_text = re.sub(r'position:[^\s]+', '', clean_text).strip()
                if clean_text and (not segments or segments[-1]['text'] != clean_text):
                    segments.append({"time": t_str, "text": clean_text})
            elif not any('<' in l for l in lines):
                clean_text = re.sub(r'align:[^\s]+', '', line)
                clean_text = re.sub(r'position:[^\s]+', '', clean_text).strip()
                if clean_text and (not segments or segments[-1]['text'] != clean_text):
                    segments.append({"time": t_str, "text": clean_text})

    merged = []
    cur_time = None
    cur_texts = []
    last_word_stream = []

    for seg in segments:
        words = seg["text"].split()
        new_words = []
        for w in words:
            if not last_word_stream or last_word_stream[-1] != w:
                new_words.append(w)
                last_word_stream.append(w)
                if len(last_word_stream) > 10:
                    last_word_stream.pop(0)

        if not new_words:
            continue

        if cur_time is None:
            cur_time = seg["time"]

        cur_texts.extend(new_words)

        if any(w.endswith(('.', '?', '!')) for w in new_words) or len(cur_texts) >= 12:
            merged.append(f"[{cur_time}] {' '.join(cur_texts)}")
            cur_time = None
            cur_texts = []

    if cur_texts:
        merged.append(f"[{cur_time}] {' '.join(cur_texts)}")

    return "\n".join(merged)


def fetch_subtitles(vid: str, output_dir: Path) -> str:
    """수동 및 자동 자막을 수집하여 타임스탬프가 포함된 텍스트로 추출"""
    sh(["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", "ko,ko-orig,ko-KR,en,en-US,all", "-o", str(output_dir / vid), f"https://youtu.be/{vid}"])

    priority_patterns = [
        str(output_dir / f"{vid}.ko.vtt"), str(output_dir / f"{vid}.ko.srt"),
        str(output_dir / f"{vid}.ko-orig.vtt"), str(output_dir / f"{vid}.ko-orig.srt"),
        str(output_dir / f"{vid}.ko-KR.vtt"), str(output_dir / f"{vid}.ko-KR.srt"),
        str(output_dir / f"{vid}.en.vtt"), str(output_dir / f"{vid}.en.srt"),
        str(output_dir / f"{vid}.*.vtt"), str(output_dir / f"{vid}.*.srt")
    ]

    for pat in priority_patterns:
        matched = glob.glob(pat)
        for f in matched:
            parsed = parse_subtitles_with_timestamps(f)
            if parsed and len(parsed.strip()) > 30:
                return parsed

    return "(자막 없음)"


def analyze_video(url: str, progress_callback=None) -> dict:
    vid = extract_video_id(url)
    if not vid:
        raise ValueError("올바른 유튜브 링크가 아닙니다.")

    if progress_callback:
        progress_callback("metadata", "1/4 메타데이터 분석 중...")
    print("1/4 메타데이터 수집 중...")
    meta_raw = sh(["yt-dlp", "--skip-download", "--dump-json", f"https://youtu.be/{vid}"])
    try:
        meta = json.loads(meta_raw)
    except Exception:
        meta = {}

    if not meta:
        raise RuntimeError(
            "유튜브 영상 정보를 가져오지 못했습니다. "
            "① yt-dlp 설치 확인 ② 인터넷 연결 ③ 영상이 공개 상태인지 확인해주세요."
        )

    info = {
        "id": vid,
        "title": meta.get("title") or "제목 없음",
        "channel": meta.get("channel") or meta.get("uploader") or "채널명 미상",
        "channel_follower_count": meta.get("channel_follower_count", 0),
        "view_count": meta.get("view_count", 0),
        "like_count": meta.get("like_count", 0),
        "comment_count": meta.get("comment_count", 0),
        "duration": meta.get("duration", 0),
        "duration_string": meta.get("duration_string", "00:00"),
        "upload_date": meta.get("upload_date", ""),
        "thumbnail": meta.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "description": meta.get("description", ""),
        "categories": meta.get("categories", []),
        "tags": meta.get("tags", [])
    }

    if progress_callback:
        progress_callback("subtitles", "2/4 자막 및 타임스탬프 추출 중...")
    print("2/4 타임스탬프 자막 추출 중...")
    transcript = fetch_subtitles(vid, DATA_DIR)

    transcript_file = DATA_DIR / f"{vid}_자막전문.txt"
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(transcript)

    if progress_callback:
        progress_callback("comments", "3/4 댓글 수집 중...")
    print("3/4 댓글 수집 중...")
    sh(["yt-dlp", "--skip-download", "--write-comments",
        "--extractor-args", "youtube:max_comments=200", "-o", str(DATA_DIR / f"{vid}_c"), f"https://youtu.be/{vid}"])

    comments = []
    comments_file = DATA_DIR / f"{vid}_c.info.json"
    if comments_file.exists():
        try:
            cs = json.load(open(comments_file, encoding="utf-8")).get("comments") or []
            cs.sort(key=lambda c: c.get("like_count") or 0, reverse=True)
            comments = [{
                "text": c.get("text", ""),
                "like_count": c.get("like_count", 0),
                "author": c.get("author", "익명"),
                "author_thumbnail": c.get("author_thumbnail", "")
            } for c in cs[:20]]
        except Exception:
            pass

    prompt_comments = ["[" + str(c.get("like_count", 0)) + "] " + (c.get("text") or "")[:100] for c in comments[:15]]

    base_context = (
        f"[영상 정보]\n- 제목: {info['title']}\n- 채널: {info['channel']}\n- 조회수: {info['view_count']:,}\n- 길이: {info['duration_string']}\n\n"
        f"[타임스탬프 자막 스크립트]\n{transcript[:6500]}\n\n"
        f"[설명란]\n{(info['description'])[:800]}\n\n"
        f"[상위 베스트 댓글]\n" + "\n".join(prompt_comments)
    )

    if progress_callback:
        progress_callback("ai_analysis", "4/4 로컬 AI 심층 분석 중...")
    print("4/4 로컬 AI 심층 분석 리포트 생성 중...")

    p = f"""당신은 대한민국 최고의 유튜브 콘텐츠 기획 전문가입니다. 실제 영상의 [타임스탬프 자막 스크립트]와 메타데이터를 정밀 분석해주세요.

{base_context}

작성 요청 사항 (1번부터 5번 끝까지 완결):
### 1. 제목·훅 구조 (Title & Hook Structure)
- 시청자의 클릭을 유도한 핵심 심리 기제와 키워드 해체
- 썸네일/제목의 충격 요인 및 호기심 유발 공식 분석

### 2. 전개 방식 (단계별 서사 구조)
- 자막의 실제 타임스탬프 시간대별 전개 구조를 5단계(도입 -> 갈등 심화 -> 난제 제시 -> 해결 시도 -> 비판적 결론/여운)로 상세히 나누어 분석

### 3. 핵심 메시지 & 통찰 (Core Message)
- 영상이 궁극적으로 전달하는 본질적인 메시지와 사회적/지식적 시사점

### 4. 댓글 여론 특징 (Comment Sentiment)
- 상위 댓글 반응 및 시청자들의 주된 감정 포인트 심층 요약

### 5. 내 채널에 적용할 점 3가지 (Actionable Channel Playbook)
- 📌 Tip 1: '낭만' vs '현실' 극적 대비 훅 공식 및 구체적 스크립트 적용 템플릿
- 📌 Tip 2: 정밀 수치와 전문 공학/지식 팩트로 신뢰도 구축하는 방법
- 📌 Tip 3: 시청 지속시간(Retention)을 2배로 늘리는 난제·딜레마 전개 구조
"""
    try:
        report = llm_client.call_llm([{"role": "user", "content": p}], max_tokens=4096)
    except Exception as e:
        report = f"(로컬 AI 연결 안내: {e})\n\n[수동 분석용 프롬프트]\n" + p

    report_file = DATA_DIR / f"{vid}_리포트.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    result_data = {
        "id": vid,
        "url": url,
        "info": info,
        "transcript": transcript,
        "comments": comments,
        "report": report,
        "report_file": str(report_file)
    }

    cache_file = DATA_DIR / f"{vid}_metadata.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    return result_data


if __name__ == "__main__":
    url_input = sys.argv[1] if len(sys.argv) > 1 else input("유튜브 링크: ").strip()
    res = analyze_video(url_input)
    print("\n" + "=" * 50)
    print(res["report"])
    print("=" * 50)
