# 유튜브 링크 하나로 완전 분석 — 0원
# 사용법: python3 analyze.py "https://youtu.be/영상ID"
import sys, os, re, json, subprocess, urllib.request, glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PATH 환경변수에 pip 사용자 설치 경로 추가 (설치된 파이썬 버전과 무관하게 탐색)
_extra_bins = [os.path.expanduser("~/.local/bin")] + glob.glob(os.path.expanduser("~/Library/Python/*/bin"))
os.environ["PATH"] = ":".join(_extra_bins + [os.environ.get("PATH", "")])

UV_BIN = os.path.expanduser("~/.local/bin/uv")

def sh(args):
    # 항상 프로젝트 폴더(BASE_DIR)에서 실행 → 어디서 서버를 켜도 결과 파일 위치가 일정함
    if args and args[0] == "yt-dlp" and os.path.exists(UV_BIN):
        res = subprocess.run([UV_BIN, "run", "--with", "yt-dlp", "yt-dlp"] + args[1:],
                             capture_output=True, text=True, cwd=BASE_DIR)
        if res.returncode == 0:
            return res.stdout
    res = subprocess.run(args, capture_output=True, text=True, cwd=BASE_DIR)
    if res.returncode != 0 and res.stderr:
        print(f"  ⚠️ 명령 실패 ({args[0]}): {res.stderr.strip().splitlines()[-1] if res.stderr.strip() else '알 수 없는 오류'}")
    return res.stdout

def extract_video_id(url):
    match = re.search(r'(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})', url)
    return match.group(1) if match else None

def parse_subtitles_with_timestamps(filepath):
    """
    VTT / SRT 자막 파일에서 [MM:SS] 타임스탬프와 함께 발화 텍스트를 정확하게 추출합니다.
    """
    if not os.path.exists(filepath):
        return ""

    content = open(filepath, encoding='utf-8', errors='ignore').read()
    
    # Match VTT / SRT cue blocks
    cue_blocks = re.findall(
        r'(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3}) --> (?:\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})[^\n]*\n([\s\S]*?)(?=\n(?:\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})|\Z)',
        content
    )
    
    segments = []
    for start_time, body in cue_blocks:
        lines = body.strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Format start time into MM:SS
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

    # Group into readable timestamped lines
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

def fetch_subtitles(vid):
    """
    수동 자막 및 자동 자막(Auto-subs)을 모두 다운로드하여 타임스탬프가 포함된 텍스트로 추출합니다.
    """
    sh(["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", "ko,ko-orig,ko-KR,en,en-US,all", "-o", vid, "https://youtu.be/" + vid])
    
    priority_patterns = [
        f"{vid}.ko.vtt", f"{vid}.ko.srt",
        f"{vid}.ko-orig.vtt", f"{vid}.ko-orig.srt",
        f"{vid}.ko-KR.vtt", f"{vid}.ko-KR.srt",
        f"{vid}.en.vtt", f"{vid}.en.srt",
        f"{vid}.*.vtt", f"{vid}.*.srt"
    ]
    
    for pat in priority_patterns:
        matched = glob.glob(os.path.join(BASE_DIR, pat))
        for f in matched:
            parsed = parse_subtitles_with_timestamps(f)
            if parsed and len(parsed.strip()) > 30:
                print(f"  ✓ 타임스탬프 자막 추출 완료: {os.path.basename(f)} ({len(parsed):,}자)")
                return parsed

    return "(자막 없음)"

def call_local_llm(messages, max_tokens=4096, max_continues=3):
    # LM Studio / Ollama 자동 감지 공용 클라이언트 사용 (llm_client.py)
    import llm_client
    return llm_client.call_llm(messages, max_tokens=max_tokens, temperature=0.7, max_continues=max_continues)

def analyze_video(url, progress_callback=None):
    vid = extract_video_id(url)
    if not vid:
        raise ValueError("올바른 유튜브 링크가 아닙니다.")

    if progress_callback: progress_callback("metadata", "1/4 메타데이터 분석 중...")
    print("1/4 메타데이터...")
    meta_raw = sh(["yt-dlp", "--skip-download", "--dump-json", "https://youtu.be/" + vid])
    try:
        meta = json.loads(meta_raw)
    except Exception:
        meta = {}

    # yt-dlp 실패(미설치, 네트워크, 유튜브 차단)를 성공처럼 넘기지 않고 명확히 알림
    if not meta:
        raise RuntimeError(
            "유튜브 영상 정보를 가져오지 못했습니다. "
            "① yt-dlp 설치 확인 (pip install yt-dlp) ② 인터넷 연결 ③ 영상 링크가 공개 상태인지 확인해주세요."
        )


    info = {
        "id": vid,
        "title": meta.get("title") or "제목 없음",
        "channel": meta.get("channel") or meta.get("uploader") or "채널명 미상",
        "channel_follower_count": meta.get("channel_follower_count"),
        "view_count": meta.get("view_count") or 0,
        "like_count": meta.get("like_count") or 0,
        "comment_count": meta.get("comment_count") or 0,
        "duration": meta.get("duration") or 0,
        "duration_string": meta.get("duration_string") or "00:00",
        "upload_date": meta.get("upload_date") or "",
        "thumbnail": meta.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "description": meta.get("description") or "",
        "categories": meta.get("categories") or [],
        "tags": meta.get("tags") or []
    }

    if progress_callback: progress_callback("subtitles", "2/4 자막 및 타임스탬프 추출 중...")
    print("2/4 타임스탬프 포함 자막 추출...")
    transcript = fetch_subtitles(vid)

    # Save dedicated transcript file with timestamps
    transcript_file = os.path.join(BASE_DIR, vid + "_자막전문.txt")
    open(transcript_file, "w", encoding="utf-8").write(transcript)

    if progress_callback: progress_callback("comments", "3/4 댓글 수집 중...")
    print("3/4 댓글...")
    sh(["yt-dlp", "--skip-download", "--write-comments",
        "--extractor-args", "youtube:max_comments=200", "-o", vid + "_c", "https://youtu.be/" + vid])
    
    comments = []
    comments_file = os.path.join(BASE_DIR, vid + "_c.info.json")
    if os.path.exists(comments_file):
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

    print("4/4 로컬 AI 분할 심층 분석 시작 (Gemma 4 Multi-Stage)...")
    
    try:
        # Stage 1: 구조 분석 (1. 제목·훅 구조, 2. 전개 방식 단계별)
        if progress_callback: progress_callback("ai_stage1", "4/4 [1단계] 제목·훅 및 타임라인 분석 중...")
        print("  ▶ 1단계: 제목·훅 및 5단계 스토리 전개 분석...")
        p1 = (
            f"당신은 대한민국 최고의 유튜브 콘텐츠 기획 전문가입니다. 실제 영상의 [타임스탬프 자막 스크립트]와 메타데이터를 정밀 분석해주세요.\n\n"
            f"{base_context}\n\n"
            f"작성 요청 사항:\n"
            f"### 1. 제목·훅 구조 (Title & Hook Structure)\n"
            f"- 시청자의 클릭을 유도한 핵심 심리 기제와 키워드 해체\n"
            f"- 썸네일/제목의 충격 요인 및 호기심 유발 공식 분석\n\n"
            f"### 2. 전개 방식 (단계별) (Story Pacing & Development)\n"
            f"- 자막의 실제 타임스탬프 시간대별 전개 구조를 5단계(도입 -> 갈등 심화 -> 난제 제시 -> 해결 시도 -> 비판적 결론/여운)로 상세히 나누어 분석\n"
        )
        report_part1 = call_local_llm([{"role": "user", "content": p1}], max_tokens=4096)

        # Stage 2: 메시지 & 댓글 여론 분석 (3. 핵심 메시지, 4. 댓글 여론 특징)
        if progress_callback: progress_callback("ai_stage2", "4/4 [2단계] 핵심 메시지 및 댓글 여론 분석 중...")
        print("  ▶ 2단계: 핵심 메시지 및 댓글 여론 심층 분석...")
        p2 = (
            f"이어서 다음 두 가지 항목을 분석해주세요.\n\n"
            f"### 3. 핵심 메시지 & 통찰 (Core Message)\n"
            f"- 영상이 궁극적으로 전달하는 본질적인 메시지와 사회적/지식적 시사점\n\n"
            f"### 4. 댓글 여론 특징 (Comment Sentiment)\n"
            f"- 상위 댓글 반응 및 시청자들의 주된 감정 포인트 심층 요약\n"
        )
        report_part2 = call_local_llm([
            {"role": "user", "content": p1},
            {"role": "assistant", "content": report_part1},
            {"role": "user", "content": p2}
        ], max_tokens=4096)

        # Stage 3: 내 채널 적용 플레이북 (5. 내 채널에 적용할 점 3가지)
        if progress_callback: progress_callback("ai_stage3", "4/4 [3단계] 내 채널 적용 3대 플레이북 생성 중...")
        print("  ▶ 3단계: 내 채널 적용 3대 실행 플레이북 생성...")
        p3 = (
            f"마지막으로 이 영상의 흥행 공식을 내 채널 콘텐츠에 적용할 수 있는 구체적인 가이드를 작성해주세요. Tip 1, Tip 2, Tip 3 모두 상세한 적용 방안과 스크립트 템플릿까지 완결해 주세요.\n\n"
            f"### 5. 내 채널에 적용할 점 3가지 (Actionable Channel Playbook)\n"
            f"- 📌 Tip 1: '낭만' vs '현실' 극적 대비 훅 공식 및 구체적 스크립트 적용 템플릿\n"
            f"- 📌 Tip 2: 정밀 수치와 전문 공학/지식 팩트로 신뢰도 구축하는 방법\n"
            f"- 📌 Tip 3: 시청 지속시간(Retention)을 2배로 늘리는 난제·딜레마 전개 구조\n"
        )
        report_part3 = call_local_llm([
            {"role": "user", "content": p1},
            {"role": "assistant", "content": report_part1},
            {"role": "user", "content": p2},
            {"role": "assistant", "content": report_part2},
            {"role": "user", "content": p3}
        ], max_tokens=4096)

        report = f"# 유튜브 영상 심층 분석 리포트: {info['title']}\n\n" + report_part1.strip() + "\n\n---\n\n" + report_part2.strip() + "\n\n---\n\n" + report_part3.strip()

    except Exception as e:
        print(f"LM Studio 연결 실패 또는 오류: {e}")
        prompt_fallback = (
            "아래 유튜브 영상을 분석해줘.\n"
            "[메타데이터] " + json.dumps({k: info[k] for k in ["title", "channel", "view_count", "like_count", "comment_count", "duration_string"]}, ensure_ascii=False) + "\n"
            "[설명란] " + (info["description"])[:800] + "\n"
            "[타임스탬프 자막] " + transcript[:6000] + "\n"
            "[상위 댓글]\n" + "\n".join(prompt_comments) + "\n\n"
            "분석 항목:\n1. 제목·훅 구조\n2. 전개 방식(단계별)\n3. 핵심 메시지\n"
            "4. 댓글 여론 특징\n5. 내 채널에 적용할 점 3가지"
        )
        report = "(LM STUDIO 서버 꺼짐 — 아래 프롬프트를 아무 AI에나 붙여넣기)\n\n" + prompt_fallback

    report_file = os.path.join(BASE_DIR, vid + "_리포트.txt")
    open(report_file, "w", encoding="utf-8").write(report)

    # Save a complete metadata json for web cache
    cache_file = os.path.join(BASE_DIR, vid + "_data.json")
    result_data = {
        "id": vid,
        "url": url,
        "info": info,
        "transcript": transcript,
        "comments": comments,
        "report": report
    }
    open(cache_file, "w", encoding="utf-8").write(json.dumps(result_data, ensure_ascii=False, indent=2))

    return result_data

if __name__ == "__main__":
    url_input = sys.argv[1] if len(sys.argv) > 1 else input("유튜브 링크: ").strip()
    result = analyze_video(url_input)
    print("\n" + "="*50)
    print(result["report"])
    print("="*50)
    print(f"\n저장 완료: {result['id']}_리포트.txt, {result['id']}_자막전문.txt, {result['id']}_data.json")
