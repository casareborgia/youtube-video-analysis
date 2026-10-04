"""
APScheduler 기반 자율 소셜 오퍼레이터 크론 스케줄러 (KST Asia/Seoul)
- 4대 루틴(AI동향, 마음지기 홍보, 연구논문, 댓글 센티넬)의 사용자 지정 스케줄 자동 실행
- 요일별 / 시간대별(HH:mm) 동적 리로드 및 상태 모니터링
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from repositories.routine_repository import RoutineRepository
from services.pipeline_runner import RoutinePipelineRunner
from services.comment_sentinel import CommentSentinel

KST = ZoneInfo("Asia/Seoul")
DAY_MAP = {
    "MON": "mon",
    "TUE": "tue",
    "WED": "wed",
    "THU": "thu",
    "FRI": "fri",
    "SAT": "sat",
    "SUN": "sun"
}


class AutonomousScheduler:
    def __init__(self, repo: Optional[RoutineRepository] = None):
        self.repo = repo or RoutineRepository()
        self.scheduler = AsyncIOScheduler(timezone=KST)
        self.pipeline_runner = RoutinePipelineRunner(self.repo)
        self.sentinel = CommentSentinel(self.repo)
        self._is_running = False

    def start(self):
        """스케줄러 시작 및 초기 잡 등록"""
        if not self._is_running:
            self.reload_jobs()
            self.scheduler.start()
            self._is_running = True

    def shutdown(self):
        """스케줄러 종료"""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False

    def reload_jobs(self):
        """DB에 저장된 최신 루틴 스케줄을 읽어 APScheduler 잡을 동적 재구성"""
        # 기존 등록된 모든 잡 제거
        self.scheduler.remove_all_jobs()

        routines = self.repo.get_routines()
        for routine in routines:
            if not routine.enabled:
                continue

            for idx, sched in enumerate(routine.schedules):
                if not sched.enabled:
                    continue

                # 시간 파싱 (HH:mm)
                parts = sched.local_time.split(":")
                if len(parts) != 2:
                    continue
                hour, minute = int(parts[0]), int(parts[1])

                # 요일 매핑
                days_str = ",".join([DAY_MAP.get(d, d.lower()) for d in sched.days_of_week]) or "*"

                trigger = CronTrigger(
                    hour=hour,
                    minute=minute,
                    day_of_week=days_str,
                    timezone=KST
                )

                job_id = f"routine_{routine.code}_{idx}_{sched.local_time.replace(':', '')}"

                self.scheduler.add_job(
                    func=self._dispatch_routine,
                    trigger=trigger,
                    id=job_id,
                    name=f"[{routine.code}] {routine.name} ({sched.local_time})",
                    kwargs={"routine_code": routine.code},
                    replace_existing=True
                )

    async def _dispatch_routine(self, routine_code: str):
        """스케줄 도래 시 해당 루틴 실행"""
        try:
            if routine_code == "COMMENT_REPLY":
                routine = self.repo.get_routine_by_code(routine_code)
                mode = routine.mode if routine else None
                await self.sentinel.run_sentinel_cycle(routine_mode=mode)
            else:
                await self.pipeline_runner.run_pipeline_for_routine(routine_code=routine_code, limit_items=1)
        except Exception as e:
            print(f"[AutonomousScheduler] 루틴({routine_code}) 자동 실행 중 예외: {e}")

    def get_jobs_summary(self) -> List[Dict[str, Any]]:
        """현재 등록된 스케줄 잡 현황 및 다음 실행 예정 시각 반환"""
        jobs = []
        for j in self.scheduler.get_jobs():
            nrt = getattr(j, "next_run_time", None)
            next_run = nrt.isoformat() if nrt else None
            jobs.append({
                "job_id": j.id,
                "name": j.name,
                "next_run_time": next_run,
                "trigger": str(j.trigger)
            })
        return jobs

    @property
    def is_running(self) -> bool:
        return self._is_running


# 전역 싱글톤 인스턴스
global_scheduler = AutonomousScheduler()
