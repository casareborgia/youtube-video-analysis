"""
에이전트 레오의 트렌드 스카우터 (Trend Scout)
1. YouTube Data API v3 (또는 yt-dlp / Trending Feed fallback) 기반 카테고리별 인기 급상승 Top 20 수집
2. 로컬 LLM을 통한 시청 시간대, 시청자 반응, 다음 주 추천 키워드 및 알고리즘 공략 리포트 자동 생성
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional

import random
import llm_client
import concept_packs
import uploader

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TRENDS_DIR = DATA_DIR / "trends"
TRENDS_DIR.mkdir(parents=True, exist_ok=True)
TOPIC_HISTORY_FILE = TRENDS_DIR / "topic_history.json"

# 레오 음악 브리프(루나용) 결과 캐시 — 스카우팅 1회 = YouTube Data API 1회 + Gemini 1회(≈3.5k 토큰) 비용이므로
# 같은 지역의 최근 결과를 파일로 보관하고 TTL 안에서는 재사용한다. 0 이하로 두면 캐시를 쓰지 않는다.
MUSIC_BRIEF_TTL_HOURS = float(os.getenv("LEO_MUSIC_BRIEF_TTL_HOURS", "6"))


def _music_brief_cache_file(region_code: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", (region_code or "KR").upper()) or "KR"
    return TRENDS_DIR / f"luna_music_briefs_{safe}.json"


def load_cached_music_briefs(region_code: str = "KR") -> Optional[Dict[str, Any]]:
    """저장된 마지막 음악 브리프를 돌려준다. 없거나 깨졌으면 None. API 호출은 하지 않는다."""
    path = _music_brief_cache_file(region_code)
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not data.get("analysis"):
            return None
        fetched_at = float(data.get("fetched_at") or 0)
        age = max(0.0, time.time() - fetched_at) if fetched_at else None
        data["cached"] = True
        data["age_seconds"] = round(age, 1) if age is not None else None
        data["age_hours"] = round(age / 3600.0, 2) if age is not None else None
        return data
    except Exception as e:
        print(f"[TrendScout] music brief cache load failed: {e}")
        return None


def _save_music_briefs_cache(region_code: str, result: Dict[str, Any]) -> None:
    try:
        with open(_music_brief_cache_file(region_code), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[TrendScout] music brief cache save failed: {e}")

# 주요 유튜브 카테고리 매핑
YOUTUBE_CATEGORIES = {
    "0": "전체 급상승",
    "10": "음악 (Music)",
    "20": "게임 (Gaming)",
    "24": "엔터테인먼트 (Entertainment)",
    "25": "뉴스 및 정치 (News & Politics)",
    "28": "과학기술 (Science & Tech)"
}

# 에이전트 루나 확장 장르 및 무드 매핑 (돌려막기 방지 및 스펙트럼 다변화)
LUNA_GENRES = {
    "lofi": "Lo-Fi / Chillhop",
    "ambient": "Cinematic Ambient",
    "synthwave": "Synthwave / Cyberpunk",
    "sleep": "Deep Sleep / Delta Wave",
    "jazz": "Late Night Jazz / Lounge",
    "piano": "Neoclassical Piano",
    "citypop": "Nostalgic City Pop",
    "acoustic": "Warm Acoustic / Folk",
    "rnb-chill": "Slow R&B Chillout",
    "dark-ambient": "Dark Atmospheric Ambient"
}

LUNA_MOODS = {
    "dawn": "새벽 감성 (Dawn Solitude)",
    "rainy": "비 오는 창가 (Rainy Window)",
    "focus": "깊은 몰입 (Deep Focus)",
    "dreamy": "몽환적 여운 (Dreamy Reverie)",
    "warm": "따스한 위로 (Warm Comfort)",
    "nostalgia": "아련한 그리움 (Nostalgia)",
    "bittersweet": "달콤씁쓸한 기억 (Bittersweet)",
    "breezy": "선선한 바람 (Breezy Afternoon)",
    "reflective": "조용한 사색 (Reflective Silence)",
    "cozy": "포근한 안식 (Cozy Haven)"
}


def _load_topic_history(history_type: str = "general") -> List[str]:
    """최근 제안된 기획 주제 히스토리를 로드하여 중복/돌려막기 방지에 활용합니다."""
    try:
        if TOPIC_HISTORY_FILE.exists():
            with open(TOPIC_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(history_type, [])
    except Exception as e:
        print(f"[TrendScout] Error loading topic history: {e}")
    return []


def _save_topic_history(history_type: str, new_topics: List[str], max_keep: int = 40):
    """새로 추천된 주제들을 히스토리에 누적 저장합니다."""
    try:
        data = {}
        if TOPIC_HISTORY_FILE.exists():
            try:
                with open(TOPIC_HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        
        current = data.get(history_type, [])
        for t in new_topics:
            if t and t not in current:
                current.insert(0, t)
        
        data[history_type] = current[:max_keep]
        with open(TOPIC_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[TrendScout] Error saving topic history: {e}")


def fetch_top20_trends(category_id: str = "0", region_code: str = "KR") -> Dict[str, Any]:
    """
    카테고리별 실시간 인기 급상승 Top 20 수집.
    OAuth 토큰이 있으면 YouTube Data API v3 사용, 없으면 yt-dlp / Feed fallback 처리
    """
    items = []
    source = "mock"
    cat_name = YOUTUBE_CATEGORIES.get(str(category_id), "전체 급상승")

    # 1. YouTube Data API v3 시도 (토큰이 있는 경우)
    try:
        creds = uploader._creds()
        if creds and creds.valid:
            service = uploader._service(creds)
            params = {
                "part": "snippet,statistics,contentDetails",
                "chart": "mostPopular",
                "regionCode": region_code,
                "maxResults": 20
            }
            if category_id and category_id != "0":
                params["videoCategoryId"] = str(category_id)

            req = service.videos().list(**params)
            resp = req.execute()
            raw_items = resp.get("items", [])

            for idx, item in enumerate(raw_items, start=1):
                snip = item.get("snippet", {})
                stats = item.get("statistics", {})
                vid_id = item.get("id", "")
                thumbs = snip.get("thumbnails", {})
                thumb_url = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or {}).get("url", "")

                items.append({
                    "rank": idx,
                    "video_id": vid_id,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "title": snip.get("title", ""),
                    "channel_title": snip.get("channelTitle", ""),
                    "published_at": snip.get("publishedAt", ""),
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                    "thumbnail": thumb_url,
                    "tags": snip.get("tags", [])[:5]
                })
            source = "youtube_api"
    except Exception as e:
        print(f"[TrendScout] YouTube API fetch skipped or failed: {e}")

    # 2. API 실패 또는 미인증 시 yt-dlp / Trending Feed fallback 시도
    if not items:
        try:
            import subprocess
            cmd = [
                "yt-dlp",
                "--flat-playlist",
                "-J",
                f"https://www.youtube.com/feed/trending",
                "--playlist-end", "20"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                entries = data.get("entries", [])
                for idx, entry in enumerate(entries[:20], start=1):
                    vid_id = entry.get("id", "")
                    items.append({
                        "rank": idx,
                        "video_id": vid_id,
                        "url": f"https://www.youtube.com/watch?v={vid_id}",
                        "title": entry.get("title", ""),
                        "channel_title": entry.get("uploader", "") or entry.get("channel", ""),
                        "published_at": "",
                        "view_count": entry.get("view_count") or 0,
                        "like_count": 0,
                        "comment_count": 0,
                        "thumbnail": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg" if vid_id else "",
                        "tags": []
                    })
                if items:
                    source = "yt_dlp"
        except Exception as yt_err:
            print(f"[TrendScout] yt-dlp fallback failed: {yt_err}")

    # 3. 비상 Fallback (네트워크 장애 대비 대표 트렌드 시뮬레이션)
    if not items:
        fallback_samples = [
            ("AI가 만든 8초 영상의 충격적 퀄리티", "테크인사이트", 480000, 15000, 1200),
            ("초전도체 상용화 드디어 성공했나? 긴급 분석", "사이언스랩", 320000, 9500, 890),
            ("하루 10분으로 유튜브 수익화 끝내는 현실적 방법", "부업마스터", 290000, 8200, 640),
            ("100만 유튜버들이 절대 안 알려주는 알고리즘 비밀", "에이전트레오", 510000, 21000, 3100),
            ("2026년 하반기 무조건 떡상하는 쇼츠 키워드 TOP 5", "트렌드포커스", 180000, 5400, 420),
            ("한국인이 가장 많이 본 다큐멘터리 몰아보기", "스토리박스", 750000, 33000, 1800)
        ]
        for idx, (t, ch, v, l, c) in enumerate(fallback_samples, start=1):
            items.append({
                "rank": idx,
                "video_id": f"demo_{idx}",
                "url": f"https://www.youtube.com/results?search_query={urllib.parse.quote(t)}",
                "title": t,
                "channel_title": ch,
                "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "view_count": v,
                "like_count": l,
                "comment_count": c,
                "thumbnail": "",
                "tags": ["유튜브", "알고리즘", "트렌드"]
            })
        source = "sample_feed"

    result = {
        "status": "success",
        "category_id": str(category_id),
        "category_name": cat_name,
        "region_code": region_code,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "total_items": len(items),
        "items": items
    }

    # 캐시 저장
    try:
        cache_file = TRENDS_DIR / f"trends_{category_id}_{region_code}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return result


def analyze_trends_with_llm(trends_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    수집된 Top 20 데이터를 로컬/클라우드 LLM에 주입하여
    '흥행 후킹 공식, 시청자 반응, 추천 기획 주제, 에이전트 레오의 알고리즘 조언' 리포트 생성
    - 동적 샘플링 및 최근 추천 히스토리 배제를 통해 '돌려막기' 방지
    """
    raw_items = trends_payload.get("items", [])
    cat_name = trends_payload.get("category_name", "전체")

    # 1. 동적 샘플링 (Top 3 핵심 트렌드 고정 + 나머지 순위 중 무작위 8~10개 조합)
    if len(raw_items) > 5:
        top_core = raw_items[:3]
        pool = raw_items[3:20]
        sample_k = min(len(pool), random.randint(7, 10))
        sampled_tail = random.sample(pool, sample_k)
        items = top_core + sampled_tail
    else:
        items = raw_items[:15]

    summary_corpus = []
    for it in items:
        views = f"{it.get('view_count', 0):,}회" if it.get("view_count") else "조회수 미제공"
        summary_corpus.append(f"- [{it.get('rank')}위] {it.get('title')} ({it.get('channel_title')} | {views})")

    titles_text = "\n".join(summary_corpus)

    # 2. 최근 추천 히스토리 로드 (중복 배제용)
    recent_history = _load_topic_history("general")
    history_notice = ""
    if recent_history:
        history_list = "\n".join(f"  - {h}" for h in recent_history[:8])
        history_notice = f"""
[중복 엄격 금지: 최근 이미 추천된 기획 주제 목록]
아래 목록에 있는 주제나 유사한 표현/소재는 절대 피하고 완전히 새로운 관점과 타깃의 기획을 작성하세요:
{history_list}
"""

    concept_list = "\n".join(
        f"    - {c['key']}: {c['name']} — {c['description'][:44]}" for c in concept_packs.list_packs()
    )
    system_prompt = f"""당신은 유튜브 알고리즘 및 바이럴 영상 분석 전문가 '에이전트 레오(Agent Leo)'입니다.
실시간 인기 급상승 영상 목록을 분석하여 크리에이터가 즉시 실행할 수 있는 고밀도 트렌드 인사이트와 차별화된 8초 숏폼 기획을 도출해야 합니다.

반드시 유효한 JSON 형식으로만 응답하세요.

[필수 규칙]
1. top_keywords: 정확히 5개 (오늘 차트의 핵심 키워드)
2. hook_patterns: 2~3개 (실제 영상들에서 발견되는 심리적 트리거)
3. recommended_topics: **반드시 3개** (서로 다른 소재·타깃·포맷으로 확연히 구분).
   - 각 주제마다 concept 을 아래 목록에서 하나 골라 지정하세요(다른 값 금지):
{concept_list}
4. **다양성 및 참신성 지침**:
   - 뻔하고 상투적인 AI 튜토리얼이나 뻔한 게임/이슈 요약 대신, 오늘 차트의 독특한 사건, 반전 요소, 인간 심리, 흥미로운 디테일을 발굴하여 새로운 앵글을 제시하세요.
{history_notice}

```json
{{
  "top_keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "hook_patterns": [
    {{"pattern": "후킹 패턴명1", "description": "제목에서 공통적으로 발견되는 심리적 트리거 및 이유"}},
    {{"pattern": "후킹 패턴명2", "description": "또 다른 심리적 트리거 및 이유"}}
  ],
  "audience_triggers": "시청자들이 지금 이 영상들에 폭발적으로 반응하고 댓글을 다는 핵심 심리 요인 (2~3문장)",
  "recommended_topics": [
    {{"topic": "참신한 추천 기획 주제 1", "angle": "어떤 차별화된 앵글과 8초 훅으로 진입해야 하는지", "concept": "컨셉키"}},
    {{"topic": "추천 기획 주제 2 (1번과 완전히 다른 소재·타깃)", "angle": "차별화된 앵글과 8초 훅", "concept": "컨셉키"}},
    {{"topic": "추천 기획 주제 3 (1·2번과 완전히 다른 소재·타깃)", "angle": "차별화된 앵글과 8초 훅", "concept": "컨셉키"}}
  ],
  "leo_algorithm_tip": "에이전트 레오의 원포인트 알고리즘 성장 팁 (CTR, 체류시간, 시청 지속시간 극대화 전략)"
}}
```"""

    user_prompt = f"""[카테고리: {cat_name} 실시간 급상승 영상 목록]
{titles_text}

위 데이터를 분석하여 JSON 리포트를 작성해주세요.
recommended_topics 는 서로 다른 소재로 반드시 3개를 채워주세요."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    parsed = None
    try:
        # temperature를 0.85로 상향하여 다양성과 독창성 확보
        parsed, raw = llm_client.call_llm_json(messages, max_tokens=4096, temperature=0.85)
    except Exception as e:
        print(f"[TrendScout] LLM analysis fallback due to: {e}")

    if not parsed or not isinstance(parsed, dict) or not parsed.get("recommended_topics"):
        # 다변화된 Fallback 테마 풀 (돌려막기 방지)
        fallback_pools = [
            {
                "top_keywords": ["시각적 쾌감", "역발상", "디테일 집착", "극단적 실험", "몰입"],
                "hook_patterns": [
                    {"pattern": "상식 파괴 훅", "description": "대중이 당연하게 여기던 상식을 1초 만에 뒤집는 시각적 증거 제시"},
                    {"pattern": "과정의 마이크로 클로즈업", "description": "결과보다 완성되는 찰나의 마찰음과 촉감을 부각하여 도파민 분비"}
                ],
                "audience_triggers": "정보 습득을 넘어 짧은 시간 안에 뇌에 강렬한 시각적·청각적 자극과 카타르시스를 주는 영상에 열광하고 있습니다.",
                "recommended_topics": [
                    {"topic": "누구도 시도하지 않은 극단적 내구성 테스트", "angle": "일상 용품을 극한의 물리적 충격에 노출시키며 첫 3초 슬로우모션 파괴 컷으로 시선 강탈", "concept": "redline_eng_doc"},
                    {"topic": "100년 전 방식 그대로 복원한 장인의 도구", "angle": "현대 첨단 기술을 배제하고 오직 손의 감각으로 완성하는 복원 과정의 ASMR적 몰입", "concept": "person_narrative"},
                    {"topic": "우리가 몰랐던 일상 속 0.1%의 설계 비밀", "angle": "매일 마주치지만 아무도 몰랐던 물건의 홈과 구멍에 숨겨진 공학적 이유 설명", "concept": "info_knowledge"}
                ],
                "leo_algorithm_tip": "도입부 3초 안에 시청자의 기존 통념을 깨는 의문을 던지고, 아웃트로에서 양자택일 밸런스 질문으로 댓글 참여를 폭발시키세요."
            },
            {
                "top_keywords": ["심리 반전", "팩트 추적", "스토리텔링", "도파민", "공감대"],
                "hook_patterns": [
                    {"pattern": "결말 선공개 훅", "description": "충격적인 최후 결과를 먼저 보여주고 '어떻게 이런 일이 일어났을까?' 유도"},
                    {"pattern": "비밀 누설 프레임", "description": "업계 내부자만 알던 비공식 규칙을 조심스럽게 털어놓는 듯한 톤앤매너"}
                ],
                "audience_triggers": "단순한 지식보다 감정을 뒤흔드는 스토리와 인간 본성에 대한 흥미진진한 탐구에 댓글 참여율이 치솟고 있습니다.",
                "recommended_topics": [
                    {"topic": "전 세계를 속였던 역사상 가장 대담한 위조범", "angle": "가짜 그림 한 점으로 미술계를 뒤흔든 인물의 치밀한 심리전과 마지막 반전", "concept": "person_narrative"},
                    {"topic": "당신의 뇌가 숏폼에 중독되는 정확한 8초의 메커니즘", "angle": "신경전달물질의 분비 타이밍을 그래픽 도식으로 시각화하여 지적 호기심 자극", "concept": "info_knowledge"},
                    {"topic": "버려진 폐가에서 발견된 미스터리한 설계도", "angle": "알 수 없는 기계 장치가 그려진 청사진의 용도를 하나씩 추적해가는 미스터리 탐구", "concept": "redline_eng_doc"}
                ],
                "leo_algorithm_tip": "댓글창을 '토론의 장'으로 만드세요. 영상 말미에 정답 없는 도덕적/선택적 딜레마를 던지면 알고리즘이 폭발합니다."
            }
        ]
        parsed = random.choice(fallback_pools)

    # 모델이 목록에 없는 컨셉 키를 지어낼 수 있으므로 서버에서 검증하고
    # 이름을 함께 실어 UI 가 바로 표시할 수 있게 한다
    valid = {c["key"]: c["name"] for c in concept_packs.list_packs()}
    saved_topics = []
    for t in (parsed.get("recommended_topics") or []):
        if not isinstance(t, dict):
            continue
        key = t.get("concept")
        if key not in valid:
            key = concept_packs.DEFAULT_CONCEPT
        t["concept"] = key
        t["concept_name"] = valid[key]
        if t.get("topic"):
            saved_topics.append(t["topic"])

    # 신규 주제 히스토리 누적 저장 (다음번 중복 방지용)
    if saved_topics:
        _save_topic_history("general", saved_topics)

    return {
        "status": "success",
        "category_name": cat_name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "analysis": parsed
    }


# ── 레오의 음악 트렌드 스카우터 & 루나 기획 브리프 연동 ─────────────────

# 기본 장르 가중치 (루나 채널 성향 반영: 대중적 감성 보컬/멜로디 1.0, 무보컬 특수 장르 0.4)
GENRE_BASE_WEIGHTS = {
    "lofi": 1.0,
    "ambient": 1.0,
    "synthwave": 1.0,
    "sleep": 0.4,           # 무보컬 수면 델타파 (특수 목적)
    "jazz": 1.0,
    "piano": 1.0,
    "citypop": 1.0,
    "acoustic": 1.0,
    "rnb-chill": 1.0,
    "dark-ambient": 0.4     # 무보컬 다크 앰비언트 (특수 목적)
}


def get_production_genre_stats(limit: int = 30) -> Dict[str, int]:
    """최근 실제 제작된 음원들(data/luna_music/*/meta.json)의 장르 빈도를 집계합니다."""
    luna_dir = DATA_DIR / "luna_music"
    counts = {g: 0 for g in LUNA_GENRES}
    if not luna_dir.exists():
        return counts

    meta_files = sorted(
        luna_dir.glob("*/meta.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )[:limit]

    for mf in meta_files:
        try:
            with open(mf, "r", encoding="utf-8") as f:
                d = json.load(f)
                raw_g = (d.get("genre") or "").strip().lower()
                leo_g = (d.get("leo_brief", {}).get("genre") or "").strip().lower()
                matched = None
                for k, v in LUNA_GENRES.items():
                    if k == raw_g or k == leo_g or v.lower() in raw_g:
                        matched = k
                        break
                if matched:
                    counts[matched] += 1
        except Exception:
            continue
    return counts


def pick_balanced_genres(count: int = 2, stats: Optional[Dict[str, int]] = None) -> List[str]:
    """
    최근 실제 제작 빈도의 역가중치를 적용하여,
    가장 덜 생성된 장르들을 우선적으로 가중 랜덤 선별합니다 (중복 없음).
    """
    if stats is None:
        stats = get_production_genre_stats(limit=30)

    candidates = list(LUNA_GENRES.keys())
    weights = []
    for g in candidates:
        base = GENRE_BASE_WEIGHTS.get(g, 1.0)
        recent_cnt = stats.get(g, 0)
        # 출현 빈도가 높을수록 급격히 감점 (1 / (1 + n * 1.5))
        w = base / (1.0 + recent_cnt * 1.5)
        weights.append(w)

    selected = []
    cand_pool = list(candidates)
    weight_pool = list(weights)

    for _ in range(count):
        if not cand_pool:
            break
        chosen = random.choices(cand_pool, weights=weight_pool, k=1)[0]
        selected.append(chosen)
        idx = cand_pool.index(chosen)
        cand_pool.pop(idx)
        weight_pool.pop(idx)

    return selected


def pick_balanced_moods(count: int = 2, exclude: Optional[List[str]] = None) -> List[str]:
    """무드 다양성을 위해 무작위 2개 무드를 선별합니다 (중복 없음)."""
    cand = [m for m in LUNA_MOODS.keys() if m not in (exclude or [])]
    return random.sample(cand, min(count, len(cand)))


def analyze_music_trends_for_luna(region_code: str = "KR", force_refresh: bool = False,
                                  max_age_hours: Optional[float] = None) -> Dict[str, Any]:
    """
    유튜브 음악(Music, 카테고리 10)의 실시간 급상승 차트를 분석하여,
    에이전트 루나가 즉시 작곡에 착수할 수 있는 '음악 기획 브리프 3선'을 자동 도출합니다.
    - 장르 다양성 보장: 1·2번 브리프는 제작 이력 기반 가중치로 코드가 선별, 3번 브리프는 LLM이 차트에 맞춰 자율 선택
    - 프롬프트 내 하드코딩된 장르 나열 및 (예: ...) 닻내림을 전면 제거
    - 비용 보호: 최근 결과가 max_age_hours(기본 MUSIC_BRIEF_TTL_HOURS) 안에 있으면 API 호출 없이 캐시를 돌려준다.
      force_refresh=True 면 항상 새로 수집한다. 반환값의 cached 로 구분한다.
    """
    ttl_hours = MUSIC_BRIEF_TTL_HOURS if max_age_hours is None else float(max_age_hours)
    if not force_refresh and ttl_hours > 0:
        cached = load_cached_music_briefs(region_code)
        if cached and cached.get("age_hours") is not None and cached["age_hours"] < ttl_hours:
            return cached

    trends = fetch_top20_trends(category_id="10", region_code=region_code)
    raw_items = trends.get("items", [])

    # 1. 동적 샘플링 (Top 3 핵심 인기곡 + 나머지 중 무작위 7~9개 샘플링)
    if len(raw_items) > 5:
        top_core = raw_items[:3]
        pool = raw_items[3:20]
        sample_k = min(len(pool), random.randint(7, 10))
        sampled_tail = random.sample(pool, sample_k)
        items = top_core + sampled_tail
    else:
        items = raw_items[:15]

    titles_text = "\n".join(
        f"- [{it.get('rank')}위] {it.get('title')} ({it.get('channel_title')})"
        for it in items
    )

    # 2. 최근 음악 브리프 히스토리 로드
    recent_history = _load_topic_history("music")
    history_notice = ""
    if recent_history:
        history_list = "\n".join(f"  - {h}" for h in recent_history[:8])
        history_notice = f"""
[중복 엄격 금지: 최근 이미 추천된 음악 브리프 목록]
아래 목록과 동일하거나 유사한 곡명·테마·소재는 완전히 피하세요:
{history_list}
"""

    # 3. 코드 레벨 장르 & 무드 배정 (가중 랜덤 회전)
    assigned_genres = pick_balanced_genres(count=2)
    assigned_moods = pick_balanced_moods(count=2)
    g1, g2 = assigned_genres[0], assigned_genres[1]
    m1, m2 = assigned_moods[0], assigned_moods[1]
    g1_name, g2_name = LUNA_GENRES[g1], LUNA_GENRES[g2]
    m1_name, m2_name = LUNA_MOODS[m1], LUNA_MOODS[m2]

    allowed_genres_str = ", ".join(f'"{k}"({v})' for k, v in LUNA_GENRES.items())
    allowed_moods_str = ", ".join(f'"{k}"({v})' for k, v in LUNA_MOODS.items())

    system_prompt = f"""당신은 유튜브 알고리즘 및 글로벌 음악 트렌드 분석 전문가 '에이전트 레오(Agent Leo)'입니다.
현재 실시간 유튜브 음악 급상승 차트를 분석하여, AI 음악 아티스트 '에이전트 루나(Agent Luna)'가 즉시 제작할 수 있는 [음악 기획 브리프 3선]을 도출해야 합니다.

[장르 및 무드 배정 지침 (필수 준수)]
1. **브리프 1 배정**:
   - 장르: 반드시 '{g1}' ({g1_name})
   - 무드: 반드시 '{m1}' ({m1_name})
   - 차트의 인기 요인 중 이 장르/무드와 결합할 수 있는 서사와 감성을 녹여내세요.
2. **브리프 2 배정**:
   - 장르: 반드시 '{g2}' ({g2_name})
   - 무드: 반드시 '{m2}' ({m2_name})
   - 브리프 1과 완전히 대조되는 차별화된 스토리라인과 타깃 리스너를 설정하세요.
3. **브리프 3 자율 선정**:
   - 장르: 현재 급상승 차트의 최신 정서와 가장 잘 어울리는 장르를 자유롭게 선정하세요.
   - 단, 1번('{g1}')과 2번('{g2}')에서 사용한 장르는 절대 중복 선택할 수 없으며, 반드시 서로 다른 제3의 장르를 골라야 합니다.
   - 무드 역시 1번('{m1}'), 2번('{m2}')과 다른 무드를 선정하세요.

[허용 장르 및 무드 풀]
- 허용 장르: {allowed_genres_str}
- 허용 무드: {allowed_moods_str}

[클리셰(돌려막기) 방지 및 작성 규칙]
- 흔해빠진 상투적 클리셰(비 오는 창가 로파이, 새벽 드라이브 등)를 기계적으로 반복하지 마세요.
- 실제 현재 급상승 차트 곡들의 가사 정서(예: 성인의 회상, 계절의 전환, 청춘의 방황, 따스한 위로, 골목길의 햇살, 낯선 여행지의 설렘 등)에서 영감을 얻어 참신한 일상적/시네마틱 서사를 부여하세요.
{history_notice}
- 반드시 유효한 JSON만 반환하세요.

```json
{{
  "chart_insights": "현재 급상승 차트에서 청자들을 사로잡은 사운드 질감과 심리적 감정선 분석 (2~3문장)",
  "top_keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "luna_briefs": [
    {{
      "brief_id": 1,
      "title_concept": "참신하고 감각적인 곡 제목 아이디어 (영문 + 국문)",
      "genre": "{g1}",
      "genre_name": "{g1_name}",
      "mood": "{m1}",
      "mood_name": "{m1_name}",
      "topic": "곡 테마 및 감성 스토리라인 (차트의 정서나 일상/시네마틱 순간에서 포착한 구체적 묘사)",
      "angle": "레오의 30초 도입부 후킹 전략 (어떤 악기와 사운드 텍스처로 귀를 사로잡을지)",
      "target_audience": "타깃 리스너층 (예: 늦은 오후 카페에서 글을 쓰는 창작자)",
      "keywords": ["키워드1", "키워드2", "키워드3"]
    }},
    {{
      "brief_id": 2,
      "title_concept": "두 번째 곡 제목 (1번과 완전히 다른 소재)",
      "genre": "{g2}",
      "genre_name": "{g2_name}",
      "mood": "{m2}",
      "mood_name": "{m2_name}",
      "topic": "곡 테마 및 감성 스토리라인",
      "angle": "30초 후킹 전략",
      "target_audience": "타깃 리스너",
      "keywords": ["키워드1", "키워드2", "키워드3"]
    }},
    {{
      "brief_id": 3,
      "title_concept": "세 번째 곡 제목 (차트 기반 추천 곡)",
      "genre": "차트 정서에 어울리는 제3의 장르 키 (1, 2번 제외)",
      "genre_name": "제3의 장르 한글 명칭",
      "mood": "제3의 무드 키 (1, 2번 제외)",
      "mood_name": "제3의 무드 한글 명칭",
      "topic": "곡 테마 및 감성 스토리라인",
      "angle": "30초 후킹 전략",
      "target_audience": "타깃 리스너",
      "keywords": ["키워드1", "키워드2", "키워드3"]
    }}
  ]
}}
```"""

    user_prompt = f"""[실시간 유튜브 음악 인기 급상승 차트]
{titles_text or "최신 감성/어쿠스틱/인디 팝 음원 차트"}

위 차트를 바탕으로 루나를 위한 완전히 새롭고 차별화된 음악 기획 브리프 3선을 생성해주세요.
브리프 1은 '{g1_name}', 브리프 2는 '{g2_name}' 장르로 작성하고, 브리프 3은 차트에 맞는 다른 장르로 기획해주세요."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    parsed = None
    try:
        parsed, _ = llm_client.call_llm_json(messages, max_tokens=3500, temperature=0.88)
    except Exception as e:
        print(f"[TrendScout] Music trend analysis error: {e}")

    # Fallback 필요 시 동적 가중치 장르에 맞추어 생성
    if not parsed or not isinstance(parsed, dict) or not parsed.get("luna_briefs"):
        rem_genres = [g for g in LUNA_GENRES.keys() if g not in (g1, g2)]
        g3 = random.choice(rem_genres)
        g3_name = LUNA_GENRES[g3]
        rem_moods = [m for m in LUNA_MOODS.keys() if m not in (m1, m2)]
        m3 = random.choice(rem_moods)
        m3_name = LUNA_MOODS[m3]

        parsed = {
            "chart_insights": "지나간 계절의 기억과 따스한 온기를 전하는 다채로운 사운드가 차트 전반에서 깊은 위로를 전하고 있습니다.",
            "top_keywords": ["계절의온기", "사운드위로", "청춘의기억", "마음의쉼표", "감성플레이리스트"],
            "luna_briefs": [
                {
                    "brief_id": 1,
                    "title_concept": f"Whispers of {g1_name} (기억의 여운)",
                    "genre": g1,
                    "genre_name": g1_name,
                    "mood": m1,
                    "mood_name": m1_name,
                    "topic": f"{g1_name}의 독창적인 사운드 텍스처로 풀어내는 나만의 작은 휴식.",
                    "angle": "도입부 15초 만에 귀를 사로잡는 시그니처 멜로디와 사운드스케이프",
                    "target_audience": "일상 속 감성적 위로와 몰입을 원하는 리스너",
                    "keywords": [g1, m1, "감성BGM"]
                },
                {
                    "brief_id": 2,
                    "title_concept": f"Echoes in the City ({g2_name}의 밤)",
                    "genre": g2,
                    "genre_name": g2_name,
                    "mood": m2,
                    "mood_name": m2_name,
                    "topic": f"{g2_name}의 세련된 리듬감과 함께 펼쳐지는 낭만적인 순간.",
                    "angle": "귀를 사로잡는 그루브와 몽환적인 톤 설계",
                    "target_audience": "야간 퇴근길이나 드라이브를 즐기는 2030 세대",
                    "keywords": [g2, m2, "트렌디음악"]
                },
                {
                    "brief_id": 3,
                    "title_concept": f"Dawn Reflections ({g3_name}의 사색)",
                    "genre": g3,
                    "genre_name": g3_name,
                    "mood": m3,
                    "mood_name": m3_name,
                    "topic": f"차트 트렌드의 정서를 담아낸 {g3_name} 서정곡.",
                    "angle": "차분한 터치와 따뜻한 화성 진행으로 깊은 몰입감 선사",
                    "target_audience": "명상, 독서, 또는 사색을 즐기는 힐링 리스너",
                    "keywords": [g3, m3, "힐링플레이리스트"]
                }
            ]
        }

    # 4. 후처리 가드레일 (Post-processing Guardrail): 배정 장르 100% 강제 검증 및 중복 방지
    briefs = parsed.get("luna_briefs") or []

    # 1번 브리프 장르/무드 강제 확정
    if len(briefs) >= 1 and isinstance(briefs[0], dict):
        briefs[0]["genre"] = g1
        briefs[0]["genre_name"] = g1_name
        briefs[0]["mood"] = m1
        briefs[0]["mood_name"] = m1_name

    # 2번 브리프 장르/무드 강제 확정
    if len(briefs) >= 2 and isinstance(briefs[1], dict):
        briefs[1]["genre"] = g2
        briefs[1]["genre_name"] = g2_name
        briefs[1]["mood"] = m2
        briefs[1]["mood_name"] = m2_name

    # 3번 브리프: 1·2번과 중복 시 제3의 장르로 자동 회전 교체
    if len(briefs) >= 3 and isinstance(briefs[2], dict):
        b3_g = (briefs[2].get("genre") or "").strip().lower()
        if b3_g in (g1, g2) or b3_g not in LUNA_GENRES:
            remaining = [g for g in LUNA_GENRES.keys() if g not in (g1, g2)]
            new_g = random.choice(remaining)
            briefs[2]["genre"] = new_g
            briefs[2]["genre_name"] = LUNA_GENRES[new_g]
        else:
            briefs[2]["genre"] = b3_g
            briefs[2]["genre_name"] = LUNA_GENRES[b3_g]

        b3_m = (briefs[2].get("mood") or "").strip().lower()
        if b3_m in (m1, m2) or b3_m not in LUNA_MOODS:
            remaining_m = [m for m in LUNA_MOODS.keys() if m not in (m1, m2)]
            new_m = random.choice(remaining_m)
            briefs[2]["mood"] = new_m
            briefs[2]["mood_name"] = LUNA_MOODS[new_m]
        else:
            briefs[2]["mood"] = b3_m
            briefs[2]["mood_name"] = LUNA_MOODS[b3_m]

    # 신규 브리프 타이틀 히스토리 누적 저장
    saved_brief_titles = []
    for b in briefs:
        if isinstance(b, dict):
            b_title = b.get("title_concept") or b.get("title") or ""
            if b_title:
                saved_brief_titles.append(b_title)

    if saved_brief_titles:
        _save_topic_history("music", saved_brief_titles)

    result = {
        "status": "success",
        "category_id": "10",
        "category_name": "음악 (Music)",
        "region_code": region_code,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fetched_at": time.time(),
        "cached": False,
        "analysis": parsed
    }
    _save_music_briefs_cache(region_code, result)
    return result


