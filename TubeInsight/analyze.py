# 유튜브 영상 분석 — 메타데이터 · 자막 · 댓글 수집 후 로컬 AI로 흥행 공식 분석
# 사용법: python3 analyze.py "https://youtu.be/영상ID"
import os
import re
import sys
import json
import time
import glob

import llm_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ANALYSES_DIR = os.path.join(DATA_DIR, "analyses")
os.makedirs(ANALYSES_DIR, exist_ok=True)

TRANSCRIPT_CHARS = 7000   # LLM에 넘길 자막 최대 글자 수
TOP_COMMENTS = 20

# 자막 언어 우선순위 (수동 자막 → 자동 자막 순으로 탐색)
SUB_LANG_PRIORITY = ["ko", "ko-KR", "ko-orig", "en", "en-US", "en-GB", "en-orig"]


def extract_video_id(url):
    match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", url or "")
    return match.group(1) if match else None


def cache_path(vid):
    return os.path.join(ANALYSES_DIR, f"{vid}.json")


def load_cached(vid):
    try:
        with open(cache_path(vid), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_analyses():
    """이력 화면용: 저장된 분석 요약 목록 (최신순)."""
    items = []
    for path in glob.glob(os.path.join(ANALYSES_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            info = d.get("info") or {}
            items.append({
                "id": d.get("id"),
                "title": info.get("title"),
                "channel": info.get("channel"),
                "view_count": info.get("view_count"),
                "thumbnail": info.get("thumbnail"),
                "duration_string": info.get("duration_string"),
                "ai_ok": d.get("ai_ok", True),
                "analyzed_at": d.get("analyzed_at") or os.path.getmtime(path),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["analyzed_at"] or 0, reverse=True)
    return items


def search_videos(query, limit=12):
    """키워드로 유튜브를 검색해 벤치마크 후보 목록을 돌려줍니다 (조회수 내림차순)."""
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt-dlp가 설치되어 있지 않습니다.") from e
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{int(limit)}:{query}", download=False)
    results = []
    for e in (info or {}).get("entries") or []:
        vid = e.get("id")
        if not vid or len(vid) != 11:
            continue
        dur = e.get("duration")
        results.append({
            "id": vid,
            "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or "",
            "view_count": e.get("view_count") or 0,
            "duration": dur,
            "duration_string": f"{int(dur // 60)}:{int(dur % 60):02d}" if dur else "",
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
            "analyzed": os.path.exists(cache_path(vid)),
        })
    results.sort(key=lambda x: x["view_count"], reverse=True)
    return results


# ── 1. 유튜브 데이터 수집 (yt-dlp 라이브러리 직접 사용: subprocess·임시파일 없음) ─────

def _ydl():
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt-dlp가 설치되어 있지 않습니다. 터미널에서 'pip3 install -r requirements.txt'를 실행해주세요.") from e
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "getcomments": True,
        "extractor_args": {"youtube": {"max_comments": ["200", "all", "30", "5"]}},
    }
    return yt_dlp.YoutubeDL(opts)


def fetch_video(vid):
    """메타데이터·댓글·자막 URL을 한 번의 요청으로 가져옵니다."""
    ydl = _ydl()
    try:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    except Exception as e:
        msg = str(e).splitlines()[-1] if str(e) else "알 수 없는 오류"
        raise RuntimeError(
            "유튜브 영상 정보를 가져오지 못했습니다. 인터넷 연결과 영상이 공개 상태인지 확인해주세요. "
            f"(세부: {msg[:200]})"
        ) from e
    if not info:
        raise RuntimeError("유튜브 영상 정보를 가져오지 못했습니다.")
    return ydl, info


def _pick_subtitle(info):
    """(url, ext, lang, kind) — 수동 자막을 우선, 없으면 자동 자막."""
    for kind in ("subtitles", "automatic_captions"):
        table = info.get(kind) or {}
        langs = [l for l in SUB_LANG_PRIORITY if l in table]
        if kind == "subtitles":
            langs += [l for l in table if l not in langs]  # 수동 자막은 어떤 언어든 사용
        for lang in langs:
            for fmt in table.get(lang) or []:
                if fmt.get("ext") in ("vtt", "srv3", "json3", "srt") and fmt.get("url"):
                    return fmt["url"], fmt["ext"], lang, kind
    return None, None, None, None


def fetch_transcript(ydl, info):
    """자막을 내려받아 [MM:SS] 타임스탬프 텍스트로 변환합니다. 없으면 '(자막 없음)'."""
    url, ext, lang, kind = _pick_subtitle(info)
    if not url:
        return "(자막 없음)", None
    try:
        raw = ydl.urlopen(url).read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  ⚠️ 자막 다운로드 실패({lang}): {e}")
        return "(자막 없음)", None
    if ext == "json3":
        text = parse_json3(raw)
    else:
        text = parse_vtt(raw)
    if len(text.strip()) < 30:
        return "(자막 없음)", None
    label = f"{lang} ({'수동' if kind == 'subtitles' else '자동'} 자막)"
    return text, label


def _fmt_time(t):
    parts = t.split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(float(parts[2]))
            total = h * 3600 + m * 60 + s
        else:
            m, s = int(parts[0]), int(float(parts[1]))
            total = m * 60 + s
    except Exception:
        return "00:00"
    return f"{total // 60:02d}:{total % 60:02d}"


def parse_vtt(content):
    """VTT/SRT 텍스트에서 타임스탬프와 발화를 추출하고, 자동 자막의 중복 단어를 정리합니다."""
    ts = r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})"
    cue_blocks = re.findall(rf"{ts} --> {ts}[^\n]*\n([\s\S]*?)(?=\n\s*\n|\n{ts}|\Z)", content)
    segments = []
    for start, _end, body, *_ in cue_blocks:
        t_str = _fmt_time(start.replace(",", "."))
        for line in body.strip().splitlines():
            line = re.sub(r"<[^>]+>", "", line)
            line = re.sub(r"(align|position|line|size):[^\s]+", "", line).strip()
            if line and (not segments or segments[-1]["text"] != line):
                segments.append({"time": t_str, "text": line})
    return _merge_segments(segments)


def parse_json3(content):
    try:
        data = json.loads(content)
    except Exception:
        return ""
    segments = []
    for ev in data.get("events") or []:
        text = "".join(seg.get("utf8", "") for seg in (ev.get("segs") or [])).strip()
        if not text or text == "\n":
            continue
        ms = ev.get("tStartMs", 0)
        segments.append({"time": f"{ms // 60000:02d}:{(ms // 1000) % 60:02d}", "text": text.replace("\n", " ")})
    return _merge_segments(segments)


def _merge_segments(segments):
    """자동 자막은 같은 단어가 연속 cue에 반복되므로 최근 단어 흐름과 비교해 중복을 제거하고 문장 단위로 묶습니다."""
    merged, cur_time, cur_texts, recent = [], None, [], []
    for seg in segments:
        new_words = []
        for w in seg["text"].split():
            if not recent or recent[-1] != w:
                new_words.append(w)
                recent.append(w)
                if len(recent) > 10:
                    recent.pop(0)
        if not new_words:
            continue
        if cur_time is None:
            cur_time = seg["time"]
        cur_texts.extend(new_words)
        if any(w.endswith((".", "?", "!")) for w in new_words) or len(cur_texts) >= 12:
            merged.append(f"[{cur_time}] {' '.join(cur_texts)}")
            cur_time, cur_texts = None, []
    if cur_texts:
        merged.append(f"[{cur_time}] {' '.join(cur_texts)}")
    return "\n".join(merged)


def extract_comments(info):
    cs = list(info.get("comments") or [])
    cs.sort(key=lambda c: c.get("like_count") or 0, reverse=True)
    return [{
        "text": (c.get("text") or "").strip(),
        "like_count": c.get("like_count") or 0,
        "author": c.get("author") or "익명",
        "author_thumbnail": c.get("author_thumbnail") or "",
    } for c in cs[:TOP_COMMENTS] if (c.get("text") or "").strip()]


# ── 2. 로컬 AI 분석 ─────────────────────────────────────────────────────

def _llm(messages, max_tokens=4096):
    return llm_client.call_llm(messages, max_tokens=max_tokens, temperature=0.7)


def run_ai_analysis(info, transcript, comments, progress_callback=None):
    """3단계 서술 리포트 + 대시보드용 JSON 요약을 생성합니다."""
    def step(key, msg):
        if progress_callback:
            progress_callback(key, msg)
        print("  ▶", msg)

    prompt_comments = "\n".join(f"[👍{c['like_count']}] {c['text'][:120]}" for c in comments[:15]) or "(댓글 없음)"
    base_context = (
        f"[영상 정보]\n- 제목: {info['title']}\n- 채널: {info['channel']} (구독자 {info.get('channel_follower_count') or '비공개'})\n"
        f"- 조회수: {info['view_count']:,} · 좋아요: {info['like_count']:,} · 댓글: {info['comment_count']:,}\n"
        f"- 길이: {info['duration_string']} · 게시일: {info['upload_date']}\n\n"
        f"[타임스탬프 자막 스크립트]\n{transcript[:TRANSCRIPT_CHARS]}\n\n"
        f"[설명란]\n{info['description'][:800]}\n\n"
        f"[상위 댓글]\n{prompt_comments}"
    )

    step("ai_stage1", "AI 분석 1/4 — 제목·훅 구조와 전개 방식")
    p1 = (
        "당신은 유튜브 콘텐츠 기획 전문가입니다. 아래 영상의 실제 자막·메타데이터·댓글을 근거로 분석해주세요. "
        "추측은 '추정'이라고 표시하고, 자막에 없는 사실을 지어내지 마세요. 한국어로, 마크다운 형식으로 작성합니다.\n\n"
        f"{base_context}\n\n"
        "작성 항목:\n"
        "### 1. 제목·훅 구조 (Title & Hook)\n"
        "- 제목과 썸네일이 클릭을 유도한 심리 기제를 키워드 단위로 해체\n"
        "- 첫 30초 자막에서 시청자를 붙잡는 장치(질문·대비·숫자·반전 등) 분석\n\n"
        "### 2. 전개 방식 (Story Pacing)\n"
        "- 자막의 실제 타임스탬프를 근거로 도입 → 갈등/문제 → 난제/딜레마 → 해결/반전 → 결론/여운 5단계로 구간을 나누고 각 구간의 역할 설명\n"
        "- 이탈을 막기 위해 사용한 리텐션 장치(떡밥, 질문, 숫자, 반전) 정리\n"
    )
    part1 = _llm([{"role": "user", "content": p1}])

    step("ai_stage2", "AI 분석 2/4 — 핵심 메시지와 댓글 여론")
    p2 = (
        "이어서 다음 두 항목을 분석해주세요.\n\n"
        "### 3. 핵심 메시지 (Core Message)\n"
        "- 영상이 궁극적으로 전달하는 메시지와 시청자가 얻어가는 지식·감정\n\n"
        "### 4. 댓글 여론 (Comment Sentiment)\n"
        "- 상위 댓글에서 드러나는 주된 반응과 감정, 반복되는 키워드, 시청자가 특히 반응한 지점\n"
    )
    part2 = _llm([
        {"role": "user", "content": p1}, {"role": "assistant", "content": part1}, {"role": "user", "content": p2},
    ])

    step("ai_stage3", "AI 분석 3/4 — 내 채널 적용 플레이북 및 채널 브랜딩")
    p3 = (
        "마지막으로 이 영상에서 추출한 흥행 공식을 다른 영상과 채널 개설에 적용할 수 있도록 실행 플레이북과 채널 브랜딩 분석을 작성해주세요.\n\n"
        "### 5. 내 영상에 적용할 점 3가지 (Playbook)\n"
        "- 이 영상에서 실제로 효과를 낸 장치 3가지를 골라, 각각 '왜 통했는지 → 내 영상에 적용하는 방법 → 바로 쓸 수 있는 스크립트 템플릿' 순서로 작성\n"
        "- 제목 공식은 [빈칸]이 있는 템플릿 형태로 제시\n\n"
        f"### 6. 채널 벤치마킹 및 신규 채널 기획 방향 (Channel Strategy)\n"
        f"- 원본 채널 '{info['channel']}'의 포지셔닝과 타겟 독자층 분석\n"
        "- 이 채널의 성공 요소를 벤치마킹하여 새롭게 개설할 수 있는 '추천 신규 채널 주제'와 '차별화 전략' 제안\n"
    )
    part3 = _llm([
        {"role": "user", "content": p1}, {"role": "assistant", "content": part1},
        {"role": "user", "content": p2}, {"role": "assistant", "content": part2},
        {"role": "user", "content": p3},
    ])

    report = (
        f"# 유튜브 영상 분석 리포트: {info['title']}\n\n"
        + part1.strip() + "\n\n---\n\n" + part2.strip() + "\n\n---\n\n" + part3.strip()
    )

    step("ai_visual", "AI 분석 4/4 — 대시보드 요약 정리")
    visual = build_visual_summary(info, report, transcript)
    return report, visual


VISUAL_SCHEMA = """{
  "hook": {"part_a": "제목의 앞부분 훅 요소(원문 그대로)", "part_b": "제목의 뒷부분 훅 요소(원문 그대로)", "mechanism": "클릭을 만든 심리 기제 한 문장"},
  "stages": [
    {"name": "도입", "time_range": "00:00~01:20", "summary": "한 줄 요약(20자 내외)"},
    {"name": "갈등", "time_range": "...", "summary": "..."},
    {"name": "난제", "time_range": "...", "summary": "..."},
    {"name": "반전", "time_range": "...", "summary": "..."},
    {"name": "여운", "time_range": "...", "summary": "..."}
  ],
  "core_message": "영상의 핵심 메시지 한 문장(60자 내외)",
  "keywords": ["#키워드1", "#키워드2", "#키워드3"],
  "sentiment": {"summary": "댓글 여론 한 줄 요약", "positive": 70, "neutral": 20, "negative": 10},
  "tips": [
    {"title": "적용 포인트 1 제목", "summary": "한 줄 설명"},
    {"title": "적용 포인트 2 제목", "summary": "한 줄 설명"},
    {"title": "적용 포인트 3 제목", "summary": "한 줄 설명"}
  ],
  "channel_strategy": {
    "channel_name": "원본 채널명",
    "positioning": "채널의 핵심 포지셔닝 및 타겟 독자(한 줄)",
    "core_tone": "브랜딩 톤앤매너",
    "recommended_new_channel_topic": "이 채널을 벤치마킹한 추천 신규 채널 주제 한 줄",
    "differentiation_point": "새 채널 기획 시 차별화 핵심 포인트"
  }
}"""


def build_visual_summary(info, report, transcript):
    """대시보드 카드용 JSON 요약. 실패하면 None (프론트가 리포트 텍스트로 대체)."""
    prompt = (
        "아래 분석 리포트를 대시보드 카드에 표시할 수 있도록 JSON으로 요약해주세요. "
        "리포트와 자막에 있는 내용만 사용하고, 시간 구간은 자막 타임스탬프를 근거로 실제 값으로 적습니다. "
        f"영상 길이는 {info['duration_string']}입니다.\n\n"
        f"[제목] {info['title']}\n[채널] {info['channel']}\n\n[리포트]\n{report[:6000]}\n\n"
        "반드시 아래 형식의 JSON 하나만 출력하세요 (설명 문장 금지):\n" + VISUAL_SCHEMA
    )
    try:
        data, raw = llm_client.call_llm_json([{"role": "user", "content": prompt}], max_tokens=1800, temperature=0.3)
    except Exception as e:
        print(f"  ⚠️ 대시보드 요약 생성 실패: {e}")
        return None
    if not isinstance(data, dict):
        return None
    return _sanitize_visual(data, info)


def _sanitize_visual(d, info):
    title = info.get("title") or ""
    channel = info.get("channel") or ""
    hook = d.get("hook") if isinstance(d.get("hook"), dict) else {}
    stages = [s for s in (d.get("stages") or []) if isinstance(s, dict)][:5]
    default_names = ["도입", "갈등", "난제", "반전", "여운"]
    clean_stages = []
    for i, name in enumerate(default_names):
        s = stages[i] if i < len(stages) else {}
        clean_stages.append({
            "name": str(s.get("name") or name)[:8],
            "time_range": str(s.get("time_range") or "")[:20],
            "summary": str(s.get("summary") or "")[:60],
        })
    sent = d.get("sentiment") if isinstance(d.get("sentiment"), dict) else {}

    def _num(v):
        try:
            return max(0, min(100, int(float(v))))
        except Exception:
            return None

    tips = [t for t in (d.get("tips") or []) if isinstance(t, dict) and t.get("title")][:3]
    cs = d.get("channel_strategy") if isinstance(d.get("channel_strategy"), dict) else {}
    clean_cs = {
        "channel_name": str(cs.get("channel_name") or channel)[:50],
        "positioning": str(cs.get("positioning") or f"{channel} 채널의 전문 지식 기반 콘텐츠")[:120],
        "core_tone": str(cs.get("core_tone") or "전문적이고 몰입감 있는 톤")[:60],
        "recommended_new_channel_topic": str(cs.get("recommended_new_channel_topic") or f"{title.split(' ')[0]} 관련 1인 미디어 채널")[:100],
        "differentiation_point": str(cs.get("differentiation_point") or "쇼츠와 8초 씬 구성을 결합한 빠른 템포의 시각화")[:120],
    }

    return {
        "hook": {
            "part_a": str(hook.get("part_a") or title[: len(title) // 2])[:60],
            "part_b": str(hook.get("part_b") or title[len(title) // 2:])[:60],
            "mechanism": str(hook.get("mechanism") or "")[:200],
        },
        "stages": clean_stages,
        "core_message": str(d.get("core_message") or "")[:200],
        "keywords": [("#" + str(k).lstrip("#"))[:20] for k in (d.get("keywords") or []) if str(k).strip()][:5],
        "sentiment": {
            "summary": str(sent.get("summary") or "")[:200],
            "positive": _num(sent.get("positive")), "neutral": _num(sent.get("neutral")), "negative": _num(sent.get("negative")),
        },
        "tips": [{"title": str(t.get("title"))[:60], "summary": str(t.get("summary") or "")[:200]} for t in tips],
        "channel_strategy": clean_cs,
    }


# ── 3. 전체 파이프라인 ───────────────────────────────────────────────────

def analyze_video(url, progress_callback=None):
    vid = extract_video_id(url)
    if not vid:
        raise ValueError("올바른 유튜브 링크가 아닙니다.")

    def step(key, msg):
        if progress_callback:
            progress_callback(key, msg)
        print(msg)

    step("metadata", "1/4 영상 정보·댓글 수집 중...")
    ydl, raw = fetch_video(vid)
    info = {
        "id": vid,
        "title": raw.get("title") or "제목 없음",
        "channel": raw.get("channel") or raw.get("uploader") or "채널명 미상",
        "channel_id": raw.get("channel_id") or raw.get("uploader_id") or "",
        "channel_url": raw.get("channel_url") or raw.get("uploader_url") or (f"https://www.youtube.com/{raw.get('uploader_id')}" if raw.get("uploader_id") else ""),
        "channel_follower_count": raw.get("channel_follower_count"),
        "view_count": raw.get("view_count") or 0,
        "like_count": raw.get("like_count") or 0,
        "comment_count": raw.get("comment_count") or 0,
        "duration": raw.get("duration") or 0,
        "duration_string": raw.get("duration_string") or "00:00",
        "upload_date": raw.get("upload_date") or "",
        "thumbnail": raw.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "description": raw.get("description") or "",
        "categories": raw.get("categories") or [],
        "tags": raw.get("tags") or [],
    }

    step("subtitles", "2/4 자막 추출 중...")
    transcript, transcript_source = fetch_transcript(ydl, raw)
    with open(os.path.join(ANALYSES_DIR, f"{vid}_자막전문.txt"), "w", encoding="utf-8") as f:
        f.write(transcript)

    step("comments", "3/4 상위 댓글 정리 중...")
    comments = extract_comments(raw)

    ai_ok, ai_error, visual = True, None, None
    backend = llm_client.detect_backend()
    try:
        report, visual = run_ai_analysis(info, transcript, comments, progress_callback)
    except Exception as e:
        ai_ok, ai_error = False, str(e)
        print(f"로컬 AI 분석 실패: {e}")
        prompt_comments = "\n".join(f"[👍{c['like_count']}] {c['text'][:120]}" for c in comments[:15])
        report = (
            f"(로컬 AI 분석 실패: {ai_error})\n\n아래 프롬프트를 다른 AI에 붙여넣으면 같은 분석을 받을 수 있습니다.\n\n---\n\n"
            "아래 유튜브 영상을 분석해줘.\n"
            "[메타데이터] " + json.dumps({k: info[k] for k in ["title", "channel", "view_count", "like_count", "comment_count", "duration_string"]}, ensure_ascii=False) + "\n"
            "[설명란] " + info["description"][:800] + "\n"
            "[타임스탬프 자막] " + transcript[:6000] + "\n"
            "[상위 댓글]\n" + prompt_comments + "\n\n"
            "분석 항목:\n1. 제목·훅 구조\n2. 전개 방식(5단계)\n3. 핵심 메시지\n4. 댓글 여론 특징\n5. 내 채널에 적용할 점 3가지"
        )

    with open(os.path.join(ANALYSES_DIR, f"{vid}_리포트.txt"), "w", encoding="utf-8") as f:
        f.write(report)

    result = {
        "id": vid,
        "url": f"https://youtu.be/{vid}",
        "info": info,
        "transcript": transcript,
        "transcript_source": transcript_source,
        "comments": comments,
        "report": report,
        "visual": visual,
        "ai_ok": ai_ok,
        "ai_error": ai_error,
        "llm": {"backend": backend["name"], "model": backend["model"]} if (backend and ai_ok) else None,
        "analyzed_at": time.time(),
    }
    # AI 분석이 실패한 결과는 캐시로 남기지 않습니다 (LLM을 켠 뒤 다시 분석할 수 있도록).
    if ai_ok:
        with open(cache_path(vid), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


if __name__ == "__main__":
    url_input = sys.argv[1] if len(sys.argv) > 1 else input("유튜브 링크: ").strip()
    result = analyze_video(url_input)
    print("\n" + "=" * 50)
    print(result["report"])
    print("=" * 50)
    print(f"\n저장 위치: data/analyses/{result['id']}.json")
