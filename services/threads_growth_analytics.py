"""Threads 계정 인사이트 수집, 성장 캠페인 관리 및 효과 분석 서비스 (ThreadsGrowthAnalyticsService).

지시서 요구사항 충족:
1. 공식 Threads 인사이트 API (GET /me/threads_insights, GET /{id}/insights) 연동 및 시계열 스냅샷 저장.
2. 성장 캠페인 생명주기 (시작 팔로워 수, 종료/현재 팔로워 수, 일평균 순증 계산).
3. 캠페인별 후보 발굴 수, 승인된 답글 수, 성공 실행 수, 실패율 및 반응 좋은 검색어 분석.
4. 캠페인 기간과 미실행 기간의 팔로워 증가율 비교 (분모 0 및 결측치 안전 처리).
5. 개별 계정의 팔로우 전환은 팔로워 API 한계상 "상관관계 관찰값(추정)"으로 투명하게 명시.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import llm_client
import social_store
import threads_client

logger = logging.getLogger("ThreadsGrowthAnalyticsService")


# ──────────────────────────────────────────────────────────────────────────
# 터치포인트 상태 어휘 통일
# engagement_automation 이 돌려주는 실행 결과 상태("success", "already_done", "blocked_quota", ...)와
# 캠페인 요약이 집계하는 상태("executed", "failed", "skipped", ...)가 달라 수치가 0 으로 나오던 문제를 막는다.
# 기록 시점(app.py)과 집계 시점(get_campaign_summary) 양쪽에서 같은 함수로 정규화한다.
# ──────────────────────────────────────────────────────────────────────────
TOUCHPOINT_STATUSES = ("pending_approval", "approved", "executed", "failed", "skipped", "already_done", "dry_run", "rejected")

_TOUCHPOINT_STATUS_MAP = {
    "success": "executed",
    "succeeded": "executed",
    "done": "executed",
    "executed": "executed",
    "already_done": "already_done",
    "duplicate": "already_done",
    "skipped_duplicate": "already_done",
    "dry_run": "dry_run",
    "blocked_quota": "skipped",
    "skipped": "skipped",
    "pending_approval": "pending_approval",
    "approved": "approved",
    "rejected": "rejected",
    "failed": "failed",
    "error": "failed",
}


def normalize_touchpoint_status(raw: Any) -> str:
    """실행 결과 상태를 캠페인 집계용 표준 상태로 바꾼다. 모르는 값은 failed/skipped 힌트로 추정하고, 그래도 모르면 'unknown'."""
    key = str(raw or "").strip().lower()
    if not key:
        return "unknown"
    if key in _TOUCHPOINT_STATUS_MAP:
        return _TOUCHPOINT_STATUS_MAP[key]
    if key.startswith("skipped"):
        return "skipped"
    if "fail" in key or "error" in key or "denied" in key:
        return "failed"
    return "unknown"


# ──────────────────────────────────────────────────────────────────────────
# 답글 초안 생성 — 상대 글 내용에 맞춰 LLM(Gemini/로컬)이 작성하고, 실패 시에만 범용 템플릿으로 대체
# 고정 문장을 여러 계정에 반복해서 달면 스팸으로 보이므로 템플릿은 폴백 전용이다.
# ──────────────────────────────────────────────────────────────────────────
_FALLBACK_REPLY_TEMPLATES = {
    "AI": [
        "공감합니다! 실무 자동화 파이프라인에서 특히 체감되는 부분이네요. 좋은 인사이트 감사합니다 💡",
        "정말 흥미로운 관점이네요! 관련해서 어떤 툴이나 구조를 주로 활용하시는지도 궁금합니다 :)",
    ],
    "개발자": [
        "개발하면서 누구나 한 번쯤 겪는 고민인데 큰 공감이 되네요! 유익한 내용 감사합니다 🚀",
        "실무 경험이 묻어나는 인사이트네요. 구조 설계하실 때 어떤 점을 가장 중요하게 보시는지 궁금합니다!",
    ],
    "스타트업": [
        "스타트업 빌딩 과정의 생생한 기록이네요. 문제 해결 과정에 깊이 공감하고 응원합니다! 🙌",
        "실행력이 정말 대단하십니다. 시장 검증 단계에서 배우신 점도 인상 깊게 읽었습니다 📈",
    ],
    "일반": [
        "글에 담긴 생각에 깊이 공감합니다! 오늘 하루도 의미 있게 마무리하시길 응원할게요 ✨",
        "정성스러운 글 잘 읽고 갑니다. 앞으로도 소통하며 자주 교류하고 싶네요 😊",
    ],
}

_REPLY_SYSTEM_PROMPT = (
    "당신은 Threads 에서 진심 어린 소통을 하는 한국어 사용자입니다. "
    "상대방 게시물을 읽고 그 글의 구체적인 내용에 반응하는 답글 초안 3개를 JSON 으로 작성합니다.\n"
    "규칙:\n"
    "- 각 답글은 60~180자, 한국어, 존댓말.\n"
    "- 반드시 상대 글의 구체적인 표현이나 상황을 한 번 이상 언급한다 (일반론 금지).\n"
    "- 3개 중 최소 1개는 상대가 답하고 싶어질 질문을 포함한다.\n"
    "- '맞팔', '선팔', '팔로우 부탁', 광고, 링크, 해시태그 도배, 과장된 칭찬은 금지.\n"
    "- 이모지는 답글당 최대 1개.\n"
    "- 출력은 {\"drafts\": [\"...\", \"...\", \"...\"]} 형식의 JSON 객체 하나만."
)


def _fallback_reply_drafts(post_text: str, topic: str) -> List[str]:
    t = (post_text or "").lower()
    if "ai" in t or "인공지능" in post_text or topic == "AI":
        return list(_FALLBACK_REPLY_TEMPLATES["AI"])
    if "개발" in post_text or "코딩" in post_text or topic == "개발자":
        return list(_FALLBACK_REPLY_TEMPLATES["개발자"])
    if "창업" in post_text or "스타트업" in post_text or topic == "스타트업":
        return list(_FALLBACK_REPLY_TEMPLATES["스타트업"])
    return list(_FALLBACK_REPLY_TEMPLATES["일반"])


def draft_reply_candidates(post_text: str, topic: str = "일반", author: str = "") -> Tuple[List[str], str, str]:
    """
    반환: (drafts, source, note)
      source = "llm" (상대 글 맞춤 생성) | "template" (LLM 실패 폴백)
    """
    text = (post_text or "").strip()
    if not text:
        raise ValueError("답글을 작성할 대상 게시물 본문(post_text)이 비어 있습니다.")
    if len(text) > 2000:
        text = text[:2000]

    user_msg = (
        f"주제: {topic or '일반'}\n"
        f"작성자: @{author.strip()}\n" if author else f"주제: {topic or '일반'}\n"
    ) + f"상대 게시물:\n\"\"\"\n{text}\n\"\"\"\n\n위 규칙대로 답글 초안 3개를 JSON 으로만 출력하세요."
    messages = [{"role": "system", "content": _REPLY_SYSTEM_PROMPT}, {"role": "user", "content": user_msg}]

    try:
        parsed, _raw = llm_client.call_llm_json(messages, max_tokens=800, temperature=0.8)
        drafts = parsed.get("drafts") if isinstance(parsed, dict) else None
        if not isinstance(drafts, list):
            raise ValueError("LLM 응답에 drafts 배열이 없음")
        clean: List[str] = []
        banned = ("맞팔", "선팔", "팔로우 부탁", "http://", "https://")
        for d in drafts:
            d_str = str(d or "").strip()
            if 10 <= len(d_str) <= 300 and not any(b in d_str for b in banned):
                clean.append(d_str)
        if not clean:
            raise ValueError("LLM 초안이 모두 규칙(길이·금지어)에 걸림")
        return clean[:3], "llm", ""
    except Exception as exc:
        note = f"LLM 초안 생성 실패로 범용 템플릿 사용: {str(exc)[:120]}"
        logger.warning(note)
        return _fallback_reply_drafts(text, topic or "일반"), "template", note


class ThreadsGrowthAnalyticsService:
    """Threads 팔로워 성장 및 인사이트 분석 서비스."""

    def __init__(self, store: Optional[social_store.SocialStore] = None):
        self.store = store or social_store.SocialStore()

    def capture_account_snapshot(
        self,
        access_token: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """공식 Threads API를 호출하여 현재 계정 메트릭 스냅샷을 DB에 저장."""
        now = int(now_ts or time.time())
        try:
            insights_res = threads_client.get_account_insights(
                metric="views,likes,replies,reposts,quotes,followers_count",
                access_token=access_token,
            )
        except Exception as exc:
            logger.warning("Threads 계정 인사이트 조회 실패 (저장 생략): %s", exc)
            return {
                "status": "error",
                "message": f"계정 인사이트 조회 실패: {exc}",
                "captured_at": now,
            }

        data_list = insights_res.get("data", [])
        metric_map: Dict[str, int] = {}
        for item in data_list:
            m_name = item.get("name")
            values = item.get("values", [])
            val = values[-1].get("value", 0) if values else item.get("total_value", {}).get("value", 0)
            if m_name:
                metric_map[m_name] = int(val or 0)

        followers_count = metric_map.get("followers_count", 0)
        views = metric_map.get("views", 0)
        likes = metric_map.get("likes", 0)
        replies = metric_map.get("replies", 0)
        reposts = metric_map.get("reposts", 0)
        quotes = metric_map.get("quotes", 0)

        snapshot_id = self.store.insert_insight_snapshot(
            followers_count=followers_count,
            views=views,
            likes=likes,
            replies=replies,
            reposts=reposts,
            quotes=quotes,
            raw_metrics=insights_res,
            captured_at=now,
        )

        snap_dict = {
            "id": snapshot_id,
            "captured_at": now,
            "followers_count": followers_count,
            "views": views,
            "likes": likes,
            "replies": replies,
            "reposts": reposts,
            "quotes": quotes,
        }
        return {
            "status": "success",
            "snapshot_id": snapshot_id,
            "captured_at": now,
            "followers_count": followers_count,
            "views": views,
            "likes": likes,
            "replies": replies,
            "reposts": reposts,
            "quotes": quotes,
            "snapshot": snap_dict,
        }

    def capture_post_insights(
        self,
        thread_ids: List[str],
        access_token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """복수 게시물에 대한 공식 인사이트 메트릭 수집."""
        results: List[Dict[str, Any]] = []
        for tid in thread_ids:
            clean_id = str(tid).strip()
            if not clean_id:
                continue
            try:
                res = threads_client.get_post_insights(thread_id=clean_id, access_token=access_token)
                data_list = res.get("data", [])
                m_map: Dict[str, int] = {}
                for item in data_list:
                    m_name = item.get("name")
                    val = item.get("values", [{}])[0].get("value", 0)
                    if m_name:
                        m_map[m_name] = int(val or 0)
                results.append({
                    "thread_id": clean_id,
                    "metrics": m_map,
                    "status": "success",
                })
            except Exception as exc:
                results.append({
                    "thread_id": clean_id,
                    "metrics": {},
                    "status": "error",
                    "error": str(exc),
                })
        return results

    def start_campaign(
        self,
        name: str,
        topic: str,
        search_queries: Optional[List[str]] = None,
        baseline_followers_count: Optional[int] = None,
        campaign_id: Optional[str] = None,
        started_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        """새 성장 캠페인 생성 및 기준 팔로워 수(baseline) 저장."""
        now = int(started_at or time.time())
        base_count = baseline_followers_count
        if base_count is None:
            # 1순위: 즉시 스냅샷 시도
            try:
                snap = self.capture_account_snapshot(now_ts=now)
                if snap.get("status") == "success" and snap.get("followers_count") is not None:
                    base_count = snap.get("followers_count")
            except Exception:
                pass

        if base_count is None:
            # 2순위: 기존 최근 스냅샷 참조
            latest = self.store.get_latest_insight_snapshot()
            if latest and latest.get("followers_count") is not None:
                base_count = latest.get("followers_count")

        if base_count is None:
            raise ValueError(
                "계정 팔로워 수(baseline)를 확인할 수 없습니다. "
                "Threads 계정 연결 및 인사이트 권한(threads_manage_insights)을 확인하거나 기준 팔로워 수를 직접 입력하세요."
            )

        return self.store.create_growth_campaign(
            name=name,
            topic=topic,
            search_queries=search_queries,
            baseline_followers_count=int(base_count),
            campaign_id=campaign_id,
            started_at=now,
        )

    def finish_campaign(
        self,
        campaign_id: str,
        final_followers_count: Optional[int] = None,
        ended_at: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """캠페인 완료 처리 및 최종 팔로워 수 확정."""
        now = int(ended_at or time.time())
        final_count = final_followers_count
        if final_count is None:
            try:
                snap = self.capture_account_snapshot(now_ts=now)
                if snap.get("status") == "success" and snap.get("followers_count") is not None:
                    final_count = snap.get("followers_count")
            except Exception:
                pass

        if final_count is None:
            latest = self.store.get_latest_insight_snapshot()
            if latest and latest.get("followers_count") is not None:
                final_count = latest.get("followers_count")

        if final_count is None:
            camp = self.store.get_growth_campaign(campaign_id)
            final_count = camp.get("baseline_followers_count", 0) if camp else 0

        return self.store.end_growth_campaign(
            campaign_id=campaign_id,
            final_followers_count=int(final_count),
            ended_at=now,
        )

    def get_campaign_summary(
        self,
        campaign_id: str,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """캠페인 진행 결과 및 성장 지표 종합 산출."""
        camp = self.store.get_growth_campaign(campaign_id)
        if not camp:
            return {"status": "error", "message": f"캠페인({campaign_id})을 찾을 수 없습니다."}

        now = int(now_ts or time.time())
        started_at = camp["started_at"]
        ended_at = camp.get("ended_at") or now
        duration_seconds = max(1, ended_at - started_at)
        duration_days = max(0.01, duration_seconds / 86400.0)

        baseline = camp.get("baseline_followers_count", 0)
        final_or_current = camp.get("final_followers_count")
        if final_or_current is None or camp.get("status") == "active":
            latest = self.store.get_latest_insight_snapshot()
            final_or_current = latest.get("followers_count", baseline) if latest else baseline

        net_followers_gain = final_or_current - baseline
        daily_follower_growth = round(net_followers_gain / duration_days, 2)

        # 터치포인트 집계
        touchpoints = self.store.list_growth_touchpoints(campaign_id=campaign_id, limit=500)
        total_touchpoints = len(touchpoints)
        # 과거에 원시 상태("success" 등)로 저장된 행도 집계되도록 읽을 때도 정규화한다
        statuses = [normalize_touchpoint_status(t.get("action_status")) for t in touchpoints]
        approved_count = sum(1 for st in statuses if st in ("approved", "executed"))
        executed_count = sum(1 for st in statuses if st == "executed")
        failed_count = sum(1 for st in statuses if st == "failed")
        pending_count = sum(1 for st in statuses if st == "pending_approval")
        skipped_count = sum(1 for st in statuses if st in ("skipped", "already_done"))

        execution_attempts = executed_count + failed_count
        failure_rate = round((failed_count / execution_attempts * 100), 1) if execution_attempts > 0 else 0.0

        # 반응 및 쿼리별 분포
        query_counts: Dict[str, int] = {}
        for tp in touchpoints:
            q = tp.get("search_query") or "기본"
            query_counts[q] = query_counts.get(q, 0) + 1

        top_queries = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "name": camp.get("name"),
            "topic": camp.get("topic"),
            "campaign_status": camp.get("status"),
            "started_at": started_at,
            "ended_at": camp.get("ended_at"),
            "duration_days": round(duration_days, 1),
            "followers_metrics": {
                "baseline_followers_count": baseline,
                "current_followers_count": final_or_current,
                "net_followers_gain": net_followers_gain,
                "daily_follower_growth": daily_follower_growth,
                "note": "개별 계정의 전환은 Threads API 한계상 관찰된 총 팔로워 수의 순증 상관관계입니다.",
            },
            "actions_metrics": {
                "total_candidates": total_touchpoints,
                "pending_approval": pending_count,
                "approved_actions": approved_count,
                "executed_actions": executed_count,
                "failed_actions": failed_count,
                "skipped_actions": skipped_count,
                "failure_rate_percent": failure_rate,
            },
            "top_search_queries": [{"query": q, "count": c} for q, c in top_queries],
        }

    def compare_campaign_periods(
        self,
        campaign_id: str,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """캠페인 실행 기간 vs 캠페인 직전 동일 기간의 팔로워 성장 효과 비교."""
        camp = self.store.get_growth_campaign(campaign_id)
        if not camp:
            return {"status": "error", "message": "캠페인을 찾을 수 없습니다."}

        now = int(now_ts or time.time())
        camp_start = camp["started_at"]
        camp_end = camp.get("ended_at") or now
        duration = max(86400, camp_end - camp_start)

        pre_start = camp_start - duration
        pre_end = camp_start

        # 1. 직전 기간 스냅샷 조회
        pre_snapshots = self.store.list_insight_snapshots(since=pre_start, until=pre_end, limit=200)
        # 2. 캠페인 기간 스냅샷 조회
        camp_snapshots = self.store.list_insight_snapshots(since=camp_start, until=camp_end, limit=200)

        pre_gain = 0
        if len(pre_snapshots) >= 2:
            pre_gain = pre_snapshots[-1].get("followers_count", 0) - pre_snapshots[0].get("followers_count", 0)

        baseline = camp.get("baseline_followers_count", 0)
        final_count = camp.get("final_followers_count")
        if final_count is None:
            latest = self.store.get_latest_insight_snapshot()
            final_count = latest.get("followers_count", baseline) if latest else baseline

        camp_gain = final_count - baseline
        growth_diff = camp_gain - pre_gain
        days = round(duration / 86400.0, 1)
        gain_ratio = round(camp_gain / pre_gain, 2) if pre_gain > 0 else (None if camp_gain <= 0 else round(float(camp_gain), 2))

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "name": camp.get("name"),
            "period_days": days,
            "campaign_duration_days": days,
            "pre_campaign_gain": pre_gain,
            "campaign_gain": camp_gain,
            "net_lift": growth_diff,
            "gain_ratio_vs_pre_period": gain_ratio,
            "lift_description": (
                f"캠페인 기간 동안 직전 동일 기간 대비 {growth_diff:+d}명의 추가 팔로워 증가가 관찰되었습니다."
                if growth_diff != 0
                else "직전 기간과 동일한 팔로워 증가 추세를 보였습니다."
            ),
            "disclaimer": "본 수치는 캠페인 활동량과 전체 팔로워 수 순증 간의 상관관계 관찰값이며, 플랫폼 외부 유입이나 알고리즘 변동에 따른 인과관계를 단정하지 않습니다.",
        }
