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

import social_store
import threads_client

logger = logging.getLogger("ThreadsGrowthAnalyticsService")


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
        approved_count = sum(1 for t in touchpoints if t.get("action_status") in ("approved", "executed"))
        executed_count = sum(1 for t in touchpoints if t.get("action_status") == "executed")
        failed_count = sum(1 for t in touchpoints if t.get("action_status") == "failed")
        pending_count = sum(1 for t in touchpoints if t.get("action_status") == "pending_approval")

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
