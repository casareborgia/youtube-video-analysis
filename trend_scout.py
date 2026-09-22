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

def analyze_music_trends_for_luna(region_code: str = "KR") -> Dict[str, Any]:
    """
    유튜브 음악(Music, 카테고리 10)의 실시간 급상승 차트를 분석하여,
    에이전트 루나가 즉시 작곡에 착수할 수 있는 '음악 기획 브리프 3선'을 자동 도출합니다.
    - 편향된 고정 예시 제거, 확장 장르/무드 풀, 동적 샘플링 및 최근 주제 배제 적용
    """
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

    allowed_genres_str = ", ".join(f'"{k}"({v})' for k, v in LUNA_GENRES.items())
    allowed_moods_str = ", ".join(f'"{k}"({v})' for k, v in LUNA_MOODS.items())

    system_prompt = f"""당신은 유튜브 알고리즘 및 글로벌 음악 트렌드 분석 전문가 '에이전트 레오(Agent Leo)'입니다.
현재 실시간 유튜브 음악 급상승 차트를 분석하여, AI 음악 아티스트 '에이전트 루나(Agent Luna)'가 즉시 제작할 수 있는 [음악 기획 브리프 3선]을 도출해야 합니다.

[작성 및 다양성 규칙]
1. **장르 및 무드 다양성 필수**:
   - 3개의 브리프는 서로 완전히 다른 장르(genre)와 무드(mood)를 선택해야 합니다.
   - 허용 장르: {allowed_genres_str}
   - 허용 무드: {allowed_moods_str}
2. **클리셰(돌려막기) 엄격 방지**:
   - '비 오는 창가 로파이', '새벽 드라이브 신스웨이브', '우주 명상 앰비언트' 같은 흔해빠진 상투적 클리셰 조합을 기계적으로 반복하지 마세요.
   - 실제 현재 급상승 차트의 최신 가사 정서(예: 성인의 회상, 계절의 전환, 청춘의 방황, 따스한 위로, 골목길의 햇살, 낯선 여행지의 설렘 등)에서 영감을 얻어 참신한 서사를 부여하세요.
   - 어쿠스틱 포크, 시티팝, 네오클래시컬 피아노, 슬로우 R&B, 재즈 라운지 등 다채로운 사운드 스펙트럼을 적극 활용하세요.
{history_notice}
3. 반드시 유효한 JSON만 반환하세요.

```json
{{
  "chart_insights": "현재 급상승 차트에서 청자들을 사로잡은 사운드 질감과 심리적 감정선 분석 (2~3문장)",
  "top_keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "luna_briefs": [
    {{
      "brief_id": 1,
      "title_concept": "참신하고 감각적인 곡 제목 아이디어 (영문 + 국문)",
      "genre": "선택한 장르 키 (예: citypop)",
      "genre_name": "선택한 장르 한글 명칭",
      "mood": "선택한 무드 키 (예: nostalgia)",
      "mood_name": "선택한 무드 한글 명칭",
      "topic": "곡 테마 및 감성 스토리라인 (차트의 정서나 일상/시네마틱 순간에서 포착한 구체적 묘사)",
      "angle": "레오의 30초 도입부 후킹 전략 (어떤 악기와 사운드 텍스처로 귀를 사로잡을지)",
      "target_audience": "타깃 리스너층 (예: 늦은 오후 카페에서 글을 쓰는 창작자)",
      "keywords": ["키워드1", "키워드2", "키워드3"]
    }},
    {{
      "brief_id": 2,
      "title_concept": "두 번째 곡 제목 (1번과 전혀 다른 장르와 소재)",
      "genre": "다른 장르 키 (예: acoustic)",
      "genre_name": "장르 한글 명칭",
      "mood": "다른 무드 키 (예: bittersweet)",
      "mood_name": "무드 한글 명칭",
      "topic": "곡 테마 및 감성 스토리라인",
      "angle": "30초 후킹 전략",
      "target_audience": "타깃 리스너",
      "keywords": ["키워드1", "키워드2", "키워드3"]
    }},
    {{
      "brief_id": 3,
      "title_concept": "세 번째 곡 제목 (1·2번과 완전히 다른 장르와 소재)",
      "genre": "또 다른 장르 키 (예: piano)",
      "genre_name": "장르 한글 명칭",
      "mood": "또 다른 무드 키 (예: warm)",
      "mood_name": "무드 한글 명칭",
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
비슷한 주제나 클리셰를 반복하지 말고 각 브리프마다 확고한 개성을 부여해주세요."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    parsed = None
    try:
        # temperature를 0.88로 설정하여 창의적인 음악 기획 도출
        parsed, _ = llm_client.call_llm_json(messages, max_tokens=3500, temperature=0.88)
    except Exception as e:
        print(f"[TrendScout] Music trend analysis error: {e}")

    if not parsed or not isinstance(parsed, dict) or not parsed.get("luna_briefs"):
        # 다채로운 Fallback 테마 풀 (비상시에도 매번 다른 음악 제안)
        fallback_pools = [
            {
                "chart_insights": "지나간 계절의 기억과 따스한 온기를 전하는 어쿠스틱·인디 팝 사운드가 차트 전반에서 깊은 위로를 전하고 있습니다.",
                "top_keywords": ["계절의온기", "어쿠스틱위로", "골목길오후", "청춘의기억", "마음의쉼표"],
                "luna_briefs": [
                    {
                        "brief_id": 1,
                        "title_concept": "Old Bookstore Sunlight (헌책방에 드리운 햇살)",
                        "genre": "acoustic",
                        "genre_name": "Warm Acoustic / Folk",
                        "mood": "nostalgia",
                        "mood_name": "아련한 그리움 (Nostalgia)",
                        "topic": "오래된 종이 냄새와 먼지 낀 유리창 사이로 비치는 오후 3시의 햇살을 바라보며 잊고 지낸 순수를 되찾는 시간.",
                        "angle": "도입부 핑거스타일 어쿠스틱 기타 선율과 섬세한 첼로의 온화한 잔향으로 10초 만에 향수 자극",
                        "target_audience": "복잡한 도시를 벗어나 아날로그 감성의 위로를 찾는 사람",
                        "keywords": ["어쿠스틱", "포크", "햇살BGM"]
                    },
                    {
                        "brief_id": 2,
                        "title_concept": "City Lights in Rearview (백미러 속 도시의 불빛)",
                        "genre": "citypop",
                        "genre_name": "Nostalgic City Pop",
                        "mood": "bittersweet",
                        "mood_name": "달콤씁쓸한 기억 (Bittersweet)",
                        "topic": "떠나온 도시의 화려한 불빛을 뒤로하고 혼자만의 여행길에 오르는 찰나의 낭만과 쌉싸름한 해방감.",
                        "angle": "도입부 빈티지 신스 브라스와 경쾌한 슬랩 베이스 그루브로 세련된 레트로 감성 즉시 점화",
                        "target_audience": "야간 퇴근길이나 주말 드라이브를 즐기는 2030 세대",
                        "keywords": ["시티팝", "야간드라이브", "레트로"]
                    },
                    {
                        "brief_id": 3,
                        "title_concept": "First Snow on Whispering Leaves (낙엽 위에 내린 첫눈)",
                        "genre": "piano",
                        "genre_name": "Neoclassical Piano",
                        "mood": "dreamy",
                        "mood_name": "몽환적 여운 (Dreamy Reverie)",
                        "topic": "가을의 끝자락 마른 낙엽 위로 조용히 내려앉는 첫눈의 설렘과 아련함을 담은 서정적 독주곡.",
                        "angle": "부드러운 펠트 피아노 타건음과 앰비언트 스트링 패드로 마음속 불안을 씻어내는 정화 설계",
                        "target_audience": "명상, 독서, 또는 늦은 밤 일기를 쓰는 힐링 리스너",
                        "keywords": ["피아노", "첫눈", "수면힐링"]
                    }
                ]
            },
            {
                "chart_insights": "도심의 밤공기 속에서 혼자만의 리듬을 찾는 세련된 어번(Urban) 그루브와 몽환적인 재즈 선율이 큰 호응을 얻고 있습니다.",
                "top_keywords": ["심야라운지", "어번그루브", "재즈칠아웃", "도심의별빛", "깊은사색"],
                "luna_briefs": [
                    {
                        "brief_id": 1,
                        "title_concept": "Neon Velvet Jazz (네온 벨벳 라운지)",
                        "genre": "jazz",
                        "genre_name": "Late Night Jazz / Lounge",
                        "mood": "reflective",
                        "mood_name": "조용한 사색 (Reflective Silence)",
                        "topic": "비 온 뒤 젖은 도심 골목의 재즈 바 구석에서 칵테일 한 잔과 함께 듣는 색소폰의 서정.",
                        "angle": "도입부 브러시 드럼과 멜로우한 재즈 기타 리프가 만드는 깊이 있는 심야의 여유",
                        "target_audience": "하루를 우아하게 마무리하고 싶은 홈바/와인 애호가",
                        "keywords": ["재즈", "라운지BGM", "심야와인"]
                    },
                    {
                        "brief_id": 2,
                        "title_concept": "Slow Motion Skyline (슬로우 스카이라인)",
                        "genre": "rnb-chill",
                        "genre_name": "Slow R&B Chillout",
                        "mood": "breezy",
                        "mood_name": "선선한 바람 (Breezy Afternoon)",
                        "topic": "옥상 난간에 기대어 노을이 번져가는 하늘을 바라보며 시원한 바람을 맞을 때의 나른한 자유.",
                        "angle": "도입부 808 딥 베이스와 몽환적인 칠 R&B 건반 아르페지오로 편안한 그루브 전달",
                        "target_audience": "트렌디한 무드로 휴식을 취하고 싶은 리스너",
                        "keywords": ["알앤비", "노을", "칠아웃"]
                    },
                    {
                        "brief_id": 3,
                        "title_concept": "Deep Ocean Breathing (심해의 숨결)",
                        "genre": "dark-ambient",
                        "genre_name": "Dark Atmospheric Ambient",
                        "mood": "focus",
                        "mood_name": "깊은 몰입 (Deep Focus)",
                        "topic": "아무런 빛도 소음도 닿지 않는 깊은 바닷속에서 온전한 내면의 고요와 마주하는 궁극의 몰입 시간.",
                        "angle": "초저역대 서브 펄스와 공간감 넘치는 하모닉스 사운드로 잡념을 100% 차단하는 집중 설계",
                        "target_audience": "코딩, 딥워크, 논문 작성 등 극한의 집중이 필요한 크리에이터",
                        "keywords": ["다크앰비언트", "딥포커스", "심해음악"]
                    }
                ]
            }
        ]
        parsed = random.choice(fallback_pools)

    # 장르 및 무드 이름 보정 & 히스토리 기록
    briefs = parsed.get("luna_briefs") or []
    saved_brief_titles = []
    for b in briefs:
        if not isinstance(b, dict):
            continue
        g_key = b.get("genre", "lofi").lower()
        if g_key in LUNA_GENRES:
            b["genre_name"] = LUNA_GENRES[g_key]
        elif not b.get("genre_name"):
            b["genre_name"] = g_key.capitalize()

        m_key = b.get("mood", "dreamy").lower()
        if m_key in LUNA_MOODS:
            b["mood_name"] = LUNA_MOODS[m_key]
        elif not b.get("mood_name"):
            b["mood_name"] = m_key.capitalize()

        b_title = b.get("title_concept") or b.get("title") or ""
        if b_title:
            saved_brief_titles.append(b_title)

    # 신규 브리프 히스토리 누적 저장
    if saved_brief_titles:
        _save_topic_history("music", saved_brief_titles)

    return {
        "status": "success",
        "category_id": "10",
        "category_name": "음악 (Music)",
        "region_code": region_code,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "analysis": parsed
    }

