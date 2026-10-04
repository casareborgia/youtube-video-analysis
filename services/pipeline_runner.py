"""
루틴 실행 파이프라인 (Pipeline Runner)
- 수집(Collect) -> 중복제거(Dedup) -> 큐레이션(Curate) -> 구조화 생성(Generate) 파이프라인 오케스트레이션
"""

import time
from typing import List, Optional, Dict, Any
from domain.models import StructuredDraft, RoutineResponse
from domain.enums import SourceType
from repositories.routine_repository import RoutineRepository
from adapters.sources import get_adapter_for_source_type
from adapters.sources.base import RawCollectedItem
from services.deduplicator import DeduplicationService
from services.content_generator import ContentGenerator


from services.publication_orchestrator import PublicationOrchestrator
from domain.enums import RoutineMode


class RoutinePipelineRunner:
    def __init__(self, repo: Optional[RoutineRepository] = None):
        self.repo = repo or RoutineRepository()
        self.deduplicator = DeduplicationService(self.repo)
        self.generator = ContentGenerator()
        self.orchestrator = PublicationOrchestrator(self.repo)

    async def run_pipeline_for_routine(
        self,
        routine_code: str,
        limit_items: int = 1,
        ignore_dedup: bool = False,
        dry_run_override: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        루틴에 등록된 출처들로부터 데이터를 수집하고 최우선 콘텐츠 초안(본문 + 첫 답글)을 생성한 뒤,
        루틴 모드(AUTO/DRY_RUN/REVIEW)에 맞게 Outbox 체인 작업을 등록 및 실행합니다.
        """
        routine = self.repo.get_routine_by_code(routine_code)
        if not routine or not routine.enabled:
            return []

        all_collected: List[RawCollectedItem] = []

        # 1. 출처별 수집
        if routine_code == "MAUM_PROMO":
            angle = self.repo.get_next_angle(routine.id)
            angle_dict = angle.model_dump() if angle else None

            from adapters.sources.maum_site import MaumSiteAdapter
            adapter = MaumSiteAdapter()
            items = await adapter.fetch_items("https://maumjigi.com", config=angle_dict)
            for it in items:
                it.extra_metadata["angle_dict"] = angle_dict
            all_collected.extend(items)
            ignore_dedup = True
        else:
            for src in routine.sources:
                if not src.enabled:
                    continue
                adapter = get_adapter_for_source_type(src.kind)
                config = src.config_json or {}
                items = await adapter.fetch_items(src.url, config=config)
                for item in items:
                    item.extra_metadata["source_id"] = src.id
                all_collected.extend(items)

        # 2. 중복 제거
        if ignore_dedup:
            unseen_items = all_collected
        else:
            unseen_items = self.deduplicator.filter_unseen_items(all_collected, routine.id)

        if not unseen_items:
            return []

        # 3. 큐레이션
        best_items = self.deduplicator.curate_best_items(unseen_items, max_items=limit_items)

        results: List[Dict[str, Any]] = []
        for item in best_items:
            source_id = item.extra_metadata.get("source_id", 0)

            # 4. 본문 및 첫 답글 생성 (Zero-Penalty Chaining)
            draft = await self.generator.generate_draft_for_item(
                item=item,
                routine_code=routine_code,
                angle_info=item.extra_metadata.get("angle_dict")
            )

            # 5. 수집 이력 기록
            self.deduplicator.mark_item_as_collected(item, routine_id=routine.id, source_id=source_id)

            # 6. Outbox Job 등록
            job_id = self.orchestrator.create_chain_job(
                routine_id=routine.id,
                draft=draft,
                platforms=routine.platforms or ["threads", "x"],
                mode=routine.mode
            )

            # 7. 모드별 실행 (AUTO 또는 DRY_RUN인 경우 즉시 실행)
            is_dry_run = dry_run_override if dry_run_override is not None else (routine.mode == RoutineMode.DRY_RUN)
            job_result = None

            if routine.mode in (RoutineMode.AUTO, RoutineMode.DRY_RUN) or dry_run_override is not None:
                job_result = await self.orchestrator.execute_job(job_id=job_id, dry_run=is_dry_run)

            results.append({
                "job_id": job_id,
                "routine_code": routine_code,
                "mode": routine.mode.value,
                "source_name": item.source_name,
                "original_url": item.url,
                "original_title": item.title,
                "draft": draft.model_dump(),
                "execution_result": job_result.model_dump() if job_result else None,
                "created_at": int(time.time())
            })

        return results
