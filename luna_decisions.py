"""
루나 제작 결정 기록 (append-only JSONL: data/luna_music/decisions.jsonl)

곡을 만들 때 무엇을 어떤 확률로 골랐는지(decision)와, 업로드 후 실제로 무엇이 적용됐는지(applied)를
같은 decision_id 로 한 줄씩 덧붙인다. 7일 성과(시청 시간)는 강화학습 시뮬레이터가 video_id 로 따로 붙인다.

시뮬레이터 docs/YOUTUBE_MODULE_SPEC.md 7장 대응:
- DecisionLog(decision_id, context_as_of, observation, eligible_actions, chosen_action, action_probability,
  policy_version, created_at) ↔ event="decision" 줄. observation=context, chosen_action=chosen.
- record_applied(decision_id, applied_action, content_id) ↔ event="applied" 줄. content_id=video_id.
  applied_action 이 chosen 과 다르면(사람이 바꿈) 원래 추천의 보상으로 학습하지 않는다.
"""

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DECISIONS_PATH = BASE_DIR / "data" / "luna_music" / "decisions.jsonl"

SCHEMA_VERSION = 1
ACTION_FIELDS = ("format", "genre", "mood", "vocal_mode")
# 정책 없이 사람이 직접 고른 곡·LLM 이 자율로 고른 브리프 — 선택 확률을 모르므로 None 으로 남기고 학습에서 뺀다
SOURCE_MANUAL = "manual"
SOURCE_LLM_BRIEF = "llm_brief"


def utc_now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def new_decision_id() -> str:
    return f"luna-{uuid.uuid4().hex}"


def _action(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: values.get(k) for k in ACTION_FIELDS}


def _append(record: Dict[str, Any], path: Optional[Path]) -> Dict[str, Any]:
    p = Path(path or DECISIONS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # 동시 생성 요청이 한 줄을 섞어 쓰지 않도록
        try:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return record


def record_decision(*, chosen: Dict[str, Any], action_probability: Optional[float], source: str,
                    policy_version: Optional[str], context: Dict[str, Any], eligible_actions: Dict[str, List[str]],
                    probabilities: Optional[Dict[str, Optional[float]]] = None, track_id: Optional[str] = None,
                    decision_id: Optional[str] = None, context_as_of: Optional[str] = None,
                    draw_index: Optional[int] = None,
                    path: Optional[Path] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """선택 시점의 결정을 한 줄 덧붙이고 그 기록을 돌려준다.
    draw_index: 한 번에 여러 곡을 뽑았을 때 몇 번째 추출인지 (레오 브리프 1·2번). 2 이상이면 조건부 확률이다."""
    if action_probability is not None and not (0.0 < float(action_probability) <= 1.0):
        raise ValueError(f"action_probability 는 (0, 1] 이어야 합니다: {action_probability}")
    created = utc_now_iso(now)
    record = {
        "event": "decision",
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id or new_decision_id(),
        "created_at": created,
        "context_as_of": context_as_of or created,
        "policy_version": policy_version,
        "source": source,
        "context": context,
        "eligible_actions": eligible_actions,
        "chosen": _action(chosen),
        "action_probability": None if action_probability is None else float(action_probability),
        "probabilities": probabilities or {},
        "draw_index": draw_index,
        "track_id": track_id,
    }
    return _append(record, path)


def record_applied(decision_id: str, *, applied: Dict[str, Any], video_id: Optional[str],
                   publish_at: Optional[str] = None, track_id: Optional[str] = None,
                   path: Optional[Path] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """업로드 후 실제 적용 값을 같은 decision_id 로 덧붙인다. chosen 과 다른 필드는 changed_fields 에 남긴다."""
    if not decision_id:
        raise ValueError("decision_id 가 비어 있습니다.")
    applied_action = _action(applied)
    decision = find_decision(decision_id, path)
    chosen = (decision or {}).get("chosen") or {}
    changed = [k for k in ACTION_FIELDS if decision and chosen.get(k) != applied_action.get(k)]
    record = {
        "event": "applied",
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "recorded_at": utc_now_iso(now),
        "applied_action": applied_action,
        "content_id": video_id,
        "video_id": video_id,
        "publish_at": publish_at,
        "track_id": track_id,
        "decision_found": decision is not None,
        "changed_fields": changed,
    }
    return _append(record, path)


def load_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """기록 전체. 깨진 줄(쓰다 끊긴 마지막 줄 등)은 건너뛴다."""
    p = Path(path or DECISIONS_PATH)
    if not p.exists():
        return []
    events = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                events.append(ev)
    return events


def find_decision(decision_id: str, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    for ev in load_events(path):
        if ev.get("event") == "decision" and ev.get("decision_id") == decision_id:
            return ev
    return None


def record_track_decision(track: Dict[str, Any], leo_brief: Optional[Dict[str, Any]], applied: Dict[str, Any],
                          path: Optional[Path] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """곡 생성 시 결정 기록. 레오 브리프에 정책 선택 정보(policy_decision)가 있으면 그 추천과 확률을 쓰고,
    없으면(직접 입력·자율 브리프) 실제 고른 값을 확률 None 으로 남긴다. 반환값의 decision_id 를 트랙에 넣는다."""
    pd = (leo_brief or {}).get("policy_decision") if isinstance(leo_brief, dict) else None
    if isinstance(pd, dict) and isinstance(pd.get("chosen"), dict):
        return record_decision(
            chosen=pd["chosen"],
            action_probability=pd.get("action_probability"),
            source=pd.get("source") or SOURCE_LLM_BRIEF,
            policy_version=pd.get("policy_version"),
            context=pd.get("context") or {},
            eligible_actions=pd.get("eligible_actions") or {},
            probabilities=pd.get("probabilities"),
            context_as_of=pd.get("context_as_of"),
            draw_index=pd.get("draw_index"),
            track_id=track.get("track_id"),
            path=path, now=now,
        )
    return record_decision(
        chosen=applied,
        action_probability=None,
        source=SOURCE_MANUAL,
        policy_version=None,
        context={},
        eligible_actions={},
        track_id=track.get("track_id"),
        path=path, now=now,
    )
