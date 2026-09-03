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

import llm_client
import uploader

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TRENDS_DIR = DATA_DIR / "trends"
TRENDS_DIR.mkdir(parents=True, exist_ok=True)

# 주요 유튜브 카테고리 매핑
YOUTUBE_CATEGORIES = {
    "0": "전체 급상승",
    "10": "음악 (Music)",
    "20": "게임 (Gaming)",
    "24": "엔터테인먼트 (Entertainment)",
    "25": "뉴스 및 정치 (News & Politics)",
    "28": "과학기술 (Science & Tech)"
}


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
    수집된 Top 20 데이터를 로컬 LLM에 주입하여
    '흥행 후킹 공식, 시청자 반응, 추천 기획 주제, 에이전트 레오의 알고리즘 조언' 리포트 생성
    """
    items = trends_payload.get("items", [])[:15]
    cat_name = trends_payload.get("category_name", "전체")

    summary_corpus = []
    for it in items:
        views = f"{it.get('view_count', 0):,}회" if it.get("view_count") else "조회수 미제공"
        summary_corpus.append(f"- [{it.get('rank')}위] {it.get('title')} ({it.get('channel_title')} | {views})")

    titles_text = "\n".join(summary_corpus)

    system_prompt = """당신은 유튜브 알고리즘 및 바이럴 영상 분석 전문가 '에이전트 레오(Agent Leo)'입니다.
현재 실시간 인기 급상승 Top 영상들의 제목, 채널, 조회수 데이터를 분석하여 크리에이터가 즉시 실행할 수 있는 고밀도 트렌드 인사이트를 도출해야 합니다.

반드시 유효한 JSON 형식으로만 응답하세요.
```json
{
  "top_keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "hook_patterns": [
    {"pattern": "후킹 패턴명", "description": "제목에서 공통적으로 발견되는 심리적 트리거 및 이유"}
  ],
  "audience_triggers": "시청자들이 지금 이 영상들에 폭발적으로 반응하고 댓글을 다는 핵심 심리 요인 (2~3문장)",
  "recommended_topics": [
    {"topic": "추천 기획 주제", "angle": "어떤 차별화된 앵글과 8초 훅으로 진입해야 하는지"}
  ],
  "leo_algorithm_tip": "에이전트 레오의 원포인트 알고리즘 성장 팁 (CTR, 체류시간, 시청 지속시간 극대화 전략)"
}
```"""

    user_prompt = f"""[카테고리: {cat_name} 실시간 급상승 영상 목록]
{titles_text}

위 데이터를 분석하여 JSON 리포트를 작성해주세요."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    parsed = None
    try:
        parsed, raw = llm_client.call_llm_json(messages, max_tokens=2048, temperature=0.6)
    except Exception as e:
        print(f"[TrendScout] LLM analysis fallback due to: {e}")

    if not parsed or not isinstance(parsed, dict):
        parsed = {
            "top_keywords": ["AI 영상", "알고리즘", "수익화", "충격 진실", "단기 폭발"],
            "hook_patterns": [
                {"pattern": "극적 대비 훅", "description": "낭만적 이상과 냉혹한 현실의 차이를 대비시켜 클릭 유도"},
                {"pattern": "수치 기반 압도", "description": "구체적인 시간/금액/배수 수치를 배치하여 신뢰도 확보"}
            ],
            "audience_triggers": "단순 정보 나열보다 지금 당장 나에게 미칠 영향과 시간 절약, 경제적 이점에 시청자들의 관심이 집중되고 있습니다.",
            "recommended_topics": [
                {"topic": "초보자도 가능한 AI 8초 숏폼 파이프라인", "angle": "무료 툴만으로 하루만에 채널 개설부터 업로드까지 완성하는 실전 튜토리얼"},
                {"topic": "100만 뷰 알고리즘의 보이지 않는 비밀", "angle": "체류시간 8초 룰과 오픈 퀘스천을 통한 댓글 10배 폭발 전략"}
            ],
            "leo_algorithm_tip": "도입부 3초 안에 시청자의 기존 통념을 깨는 의문을 던지고, 아웃트로에서 양자택일 밸런스 질문으로 댓글 참여를 폭발시키세요."
        }

    return {
        "status": "success",
        "category_name": cat_name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "analysis": parsed
    }
