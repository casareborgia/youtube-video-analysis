"""
자율 소셜 오퍼레이터 설정 및 관리 API 라우트
- 루틴(Routines) 설정 CRUD
- 출처(Sources) 설정 CRUD 및 SSRF 안전 검증 (/api/sources/test)
- 마음지기 프로모션 앵글 관리
- 파일럿 통합 상태 조회
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from domain.models import (
    RoutineResponse, RoutineUpdate,
    SourceResponse, SourceCreate, SourceUpdate,
    SourceTestRequest, SourceTestResponse,
    PromotionAngle
)
from repositories.routine_repository import RoutineRepository
from services.source_validator import test_source_url

router = APIRouter(prefix="/api", tags=["autonomous-social-operator"])
repo = RoutineRepository()


def _resolve_routine(id_or_code: str) -> RoutineResponse:
    if id_or_code.isdigit():
        routine = repo.get_routine_by_id(int(id_or_code))
    else:
        routine = repo.get_routine_by_code(id_or_code)

    if not routine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"루틴을 찾을 수 없습니다: {id_or_code}"
        )
    return routine


from services.pipeline_runner import RoutinePipelineRunner

pipeline_runner = RoutinePipelineRunner(repo)


# --- Routines Endpoints ---
@router.get("/routines", response_model=List[RoutineResponse])
def list_routines():
    """모든 자율 운영 루틴 목록 조회"""
    return repo.get_routines()


@router.get("/routines/{id_or_code}", response_model=RoutineResponse)
def get_routine(id_or_code: str):
    """특정 루틴 상세 조회 (ID 또는 CODE)"""
    return _resolve_routine(id_or_code)


from services.scheduler_cron import global_scheduler


@router.put("/routines/{id_or_code}", response_model=RoutineResponse)
def update_routine(id_or_code: str, update_data: RoutineUpdate):
    """루틴 설정 변경 (스케줄, 모드, 활성화 여부 등) 후 실시간 스케줄러 동적 재로드"""
    target = _resolve_routine(id_or_code)
    updated = repo.update_routine(target.id, update_data)
    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="루틴 수정 실패")

    # 스케줄러에 최신 일정 동적 반영
    try:
        global_scheduler.reload_jobs()
    except Exception as e:
        print(f"[autonomous_routes] 스케줄러 리로드 경고: {e}")

    return updated


@router.post("/routines/{id_or_code}/run")
async def run_routine_now(id_or_code: str, limit: int = Query(1, ge=1, le=5)):
    """루틴 파이프라인 1회 즉시 실행 (수집 -> 중복제거 -> 큐레이션 -> 초안 생성)"""
    target = _resolve_routine(id_or_code)
    results = await pipeline_runner.run_pipeline_for_routine(target.code, limit_items=limit)
    return {
        "routine_code": target.code,
        "executed_items_count": len(results),
        "results": results
    }


# --- Sources Endpoints ---
@router.get("/sources", response_model=List[SourceResponse])
def list_sources(routine_id: Optional[int] = Query(None, description="루틴 ID 필터")):
    """등록된 출처 목록 조회"""
    return repo.get_sources(routine_id=routine_id)


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(source_id: int):
    """특정 출처 조회"""
    source = repo.get_source_by_id(source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"출처를 찾을 수 없습니다: {source_id}")
    return source


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(source_data: SourceCreate):
    """새 출처 등록 (SSRF 안전 검증 선행)"""
    # 1. 루틴 존재 확인
    routine = repo.get_routine_by_id(source_data.routine_id)
    if not routine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"연결할 루틴이 존재하지 않습니다 (ID: {source_data.routine_id})"
        )

    # 2. SSRF 방어 및 도메인 검증
    test_res = await test_source_url(source_data.url)
    if not test_res.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"출처 URL 검증 실패: {test_res.error}"
        )

    return repo.add_source(source_data)


@router.put("/sources/{source_id}", response_model=SourceResponse)
async def update_source(source_id: int, update_data: SourceUpdate):
    """출처 수정 (URL 변경 시 SSRF 재검증)"""
    existing = repo.get_source_by_id(source_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"출처를 찾을 수 없습니다: {source_id}")

    if update_data.url and update_data.url != existing.url:
        test_res = await test_source_url(update_data.url)
        if not test_res.success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"수정할 URL 검증 실패: {test_res.error}"
            )

    updated = repo.update_source(source_id, update_data)
    return updated


@router.delete("/sources/{source_id}")
def delete_source(source_id: int):
    """출처 삭제"""
    existing = repo.get_source_by_id(source_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"출처를 찾을 수 없습니다: {source_id}")

    success = repo.delete_source(source_id)
    return {"success": success, "deleted_id": source_id}


@router.post("/sources/test", response_model=SourceTestResponse)
async def test_source_endpoint(req: SourceTestRequest):
    """출처 연결 및 SSRF 방어 사전 테스트 엔드포인트"""
    return await test_source_url(req.url)


# --- Promotion Angles Endpoints ---
@router.get("/routines/{id_or_code}/angles", response_model=List[PromotionAngle])
def get_routine_angles(id_or_code: str):
    """루틴의 프로모션 앵글 목록 조회"""
    routine = _resolve_routine(id_or_code)
    return repo.get_angles(routine.id)


@router.get("/routines/{id_or_code}/next-angle", response_model=Optional[PromotionAngle])
def get_next_angle(id_or_code: str):
    """다음 순환 앵글 조회 (순환 선택 및 timestamp 업데이트)"""
    routine = _resolve_routine(id_or_code)
    return repo.get_next_angle(routine.id)


# --- Pilot Dashboard Status ---
@router.get("/pilot/status")
def get_pilot_status():
    """자율 소셜 오퍼레이터 종합 대시보드 상태 요약"""
    routines = repo.get_routines()
    total_sources = sum(len(r.sources) for r in routines)
    active_routines = sum(1 for r in routines if r.enabled)

    return {
        "status": "OPERATIONAL",
        "active_routines": active_routines,
        "total_routines": len(routines),
        "total_sources": total_sources,
        "routines": [
            {
                "code": r.code,
                "name": r.name,
                "mode": r.mode.value,
                "enabled": r.enabled,
                "schedules_count": len(r.schedules),
                "sources_count": len(r.sources)
            }
            for r in routines
        ]
    }


# --- Outbox Publication Endpoints ---
from services.publication_orchestrator import PublicationOrchestrator

orchestrator = PublicationOrchestrator(repo)


@router.get("/outbox/jobs")
def list_outbox_jobs(limit: int = Query(20, ge=1, le=100), status_filter: Optional[str] = Query(None, alias="status")):
    """발행 Outbox 작업 목록 조회"""
    return repo.get_outbox_jobs(limit=limit, status=status_filter)


@router.get("/outbox/jobs/{job_id}")
def get_outbox_job(job_id: int):
    """특정 Outbox 작업 상세 및 2-Step Steps 조회"""
    job = repo.get_outbox_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"작업을 찾을 수 없습니다: {job_id}")
    return job


@router.post("/outbox/jobs/{job_id}/execute")
async def execute_outbox_job(job_id: int, dry_run: bool = Query(False, description="모의 실행 여부")):
    """Outbox 작업의 본문 -> 첫 답글 2단계 체인 발행 실행"""
    job = repo.get_outbox_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"작업을 찾을 수 없습니다: {job_id}")

    res = await orchestrator.execute_job(job_id=job_id, dry_run=dry_run)
    return res.model_dump()


@router.post("/outbox/jobs/{job_id}/approve")
async def approve_and_execute_outbox_job(job_id: int, dry_run: bool = Query(False)):
    """검토(REVIEW) 대기 중인 초안 작업을 승인하고 즉시 발행 실행"""
    job = repo.get_outbox_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"작업을 찾을 수 없습니다: {job_id}")

    res = await orchestrator.execute_job(job_id=job_id, dry_run=dry_run)
    return {
        "message": "작업이 승인되어 발행되었습니다.",
        "result": res.model_dump()
    }


# --- Scheduler Endpoints ---
@router.get("/scheduler/jobs")
def get_scheduler_jobs():
    """APScheduler에 등록된 실시간 크론 작업 현황 및 다음 실행 시각 조회"""
    return {
        "is_running": global_scheduler.is_running,
        "jobs": global_scheduler.get_jobs_summary()
    }


@router.post("/scheduler/reload")
def reload_scheduler_jobs():
    """DB 루틴 설정 기준으로 스케줄러 잡 동적 리로드"""
    global_scheduler.reload_jobs()
    return {
        "success": True,
        "message": "스케줄러 작업이 성공적으로 리로드되었습니다.",
        "jobs_count": len(global_scheduler.get_jobs_summary())
    }
