#!/usr/bin/env python3
"""
루나의 심야 서재 — 주간 컴필레이션 준비 (결정 기록 + 렌더 + 확정 요청). 업로드는 하지 않는다.

흐름 (강화학습 시뮬레이터 docs/PLAN_LUNA_DELAYED_REWARD.md 8장)
1. prepare: 시뮬레이터 편성기 --candidates 로 이번 주 테마별 후보를 받는다(곡이 모자란 테마는 빠짐)
2. 후보 중 한 테마를 같은 확률로 뽑고, 그 확률을 결정 기록(data/luna_music/decisions.jsonl)에 남긴다
3. 뽑힌 후보를 build_compilation_from_plan 으로 렌더한다 (data/luna_compilations/<공개일>_<테마>/)
4. approval_request.md 와 macOS 알림으로 확정을 요청한다
5. 사람이 듣고 승인하면 upload_luna_compilation.py --genre <폴더> --execute 로 예약 업로드한다.
   업로드 스크립트가 같은 decision_id 로 applied(video_id)를 덧붙인다 → 시뮬레이터가 7일 시청 시간으로 보상을 붙인다

같은 공개일로 다시 실행하면 새로 뽑지 않는다(한 주에 두 번 뽑으면 기록된 확률이 틀려진다). 렌더가 끝나지 않았으면 이어서 렌더한다.

사용:
  python scripts/luna_weekly_compilation.py prepare --publish-date next     # 이틀 뒤 이후 첫 토요일
  python scripts/luna_weekly_compilation.py prepare --publish-date 2026-11-07 [--no-video]
  python scripts/luna_weekly_compilation.py record-applied --dir 2026-11-07_calm_instrumental   # 업로드 후 기록이 빠졌을 때
종료 코드: 0 준비됨(또는 이미 준비됨) · 1 오류 · 4 만들 수 있는 테마 없음
"""

import argparse
import contextlib
import fcntl
import importlib.util
import json
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import luna_decisions  # noqa: E402

COMPILATIONS_DIR = BASE_DIR / "data" / "luna_compilations"
LUNA_DIR = BASE_DIR / "data" / "luna_music"
SIM_DIR = Path(os.environ.get("LUNA_SIM_DIR", str(Path.home() / "coding" / "강화학습시뮬레이터")))
KST = timezone(timedelta(hours=9))
PUBLISH_WEEKDAY = 5  # 토요일
PUBLISH_TIME = "22:00"
LEAD_DAYS = 2  # 듣고 확정할 시간
SOURCE_UNIFORM = "compilation_uniform"  # 후보 테마를 같은 확률로 뽑음 (정책 파일이 생기면 바꾼다)
FORMAT = "compilation"

STATUS_DRAWING = "drawing"
STATUS_AWAITING_BUILD = "awaiting_build"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_UPLOADED = "uploaded"


def _load_builder():
    path = BASE_DIR / "scripts" / "build_compilation_from_plan.py"
    spec = importlib.util.spec_from_file_location("build_compilation_from_plan", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def next_publish_date(today: date, weekday: int = PUBLISH_WEEKDAY, lead_days: int = LEAD_DAYS) -> date:
    """today + lead_days 이후(같은 날 포함) 첫 weekday."""
    d = today + timedelta(days=lead_days)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def skipped_publish_date(today: date, root: Path = COMPILATIONS_DIR) -> Optional[date]:
    """next 로 다음 주 토요일을 고르게 되면서 이번 주 토요일이 준비 없이 지나가는 경우 그 날짜.
    (목요일 20시에 Mac 이 잠자고 있어 금요일에 깨어나 실행된 경우 등)"""
    this_sat = today + timedelta(days=(PUBLISH_WEEKDAY - today.weekday()) % 7)
    if this_sat < next_publish_date(today) and existing_decision(this_sat.isoformat(), root) is None:
        return this_sat
    return None


def publish_at_iso(publish_date: str, hhmm: str = PUBLISH_TIME) -> str:
    return f"{publish_date}T{hhmm}:00+09:00"


def existing_decision(publish_date: str, root: Path = COMPILATIONS_DIR) -> Optional[Path]:
    """같은 공개일로 이미 뽑은 결정 파일. 여러 개면 오류(사람이 정리해야 함)."""
    found = sorted(Path(root).glob(f"{publish_date}_*/decision.json"))
    if len(found) > 1:
        raise RuntimeError(f"같은 공개일의 결정 파일이 여러 개입니다: {[str(p) for p in found]}")
    return found[0] if found else None


def run_candidates(publish_date: str, sim_dir: Path = SIM_DIR, luna_dir: Path = LUNA_DIR,
                   comp_dir: Path = COMPILATIONS_DIR) -> List[Dict[str, Any]]:
    """시뮬레이터 편성기를 읽기 전용 입력으로 실행해 후보 JSON 을 받는다. 후보가 없으면 빈 리스트."""
    out_dir = sim_dir / "data" / "youtube" / "luna"
    cmd = [str(sim_dir / ".venv" / "bin" / "python"), "-m", "simulator.modules.youtube.own_channel",
           "plan-compilations", "--channel", "luna", "--luna-dir", str(luna_dir),
           "--past-compilations", str(comp_dir), "--first-date", publish_date, "--candidates",
           "--out-dir", str(out_dir)]
    proc = subprocess.run(cmd, cwd=str(sim_dir), capture_output=True, text=True, timeout=600)
    if proc.returncode == 4:
        return []
    if proc.returncode != 0:
        raise RuntimeError(f"편성기 실패 rc={proc.returncode}: {(proc.stderr or proc.stdout).strip()[-500:]}")
    data = json.loads((out_dir / f"compilation_candidates_{publish_date}.json").read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("후보 JSON 형식이 리스트가 아닙니다.")
    return data


def draw_candidate(candidates: List[Dict[str, Any]], rng: random.Random) -> Dict[str, Any]:
    """테마 하나를 같은 확률로 뽑는다. 반환: {entry, probability, themes}"""
    themes = [c["theme"] for c in candidates]
    if not themes or len(set(themes)) != len(themes):
        raise ValueError(f"후보 테마가 비었거나 중복입니다: {themes}")
    i = rng.randrange(len(candidates))
    return {"entry": candidates[i], "probability": 1.0 / len(candidates), "themes": themes}


def candidates_summary(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"theme": c["theme"], "duration_s": c.get("duration_s"), "reused": c.get("reused"),
             "n_tracks": len(c.get("tracks") or [])} for c in candidates]


def record_compilation_decision(state: Dict[str, Any], publish_date: str, path: Optional[Path] = None,
                                now: Optional[datetime] = None) -> Dict[str, Any]:
    """decision.json 의 추첨 결과를 같은 decision_id 로 결정 기록에 남긴다."""
    k = len(state["themes"])
    return luna_decisions.record_decision(
        chosen={"format": FORMAT, "genre": state["theme"], "mood": None, "vocal_mode": None},
        action_probability=state["probability"],
        source=SOURCE_UNIFORM,
        policy_version=None,
        context={"kind": "weekly_compilation", "publish_date": publish_date, "candidates": state.get("candidates") or []},
        eligible_actions={"format": [FORMAT], "genre": list(state["themes"])},
        probabilities={"format": 1.0, "genre": 1.0 / k},
        decision_id=state["decision_id"],
        path=path, now=now,
    )


def write_json(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def approval_text(state: Dict[str, Any], meta: Dict[str, Any], report: Dict[str, Any], out_dir: Path) -> str:
    loud = report.get("final_loudness") or {}
    lines = [
        f"# 루나 주간 컴필레이션 확정 요청 — {state['publish_date']}",
        "",
        f"- 테마: {state['theme']} (후보 {len(state['themes'])}개 중 확률 {state['probability']:.2f}로 뽑음: {', '.join(state['themes'])})",
        f"- 제목: {meta.get('youtube_title')}",
        f"- 길이: {int(meta.get('duration_seconds', 0) // 60)}분 · {len(meta.get('tracks') or [])}곡 · "
        f"음량 {loud.get('i')} LUFS / {loud.get('tp')} dBTP",
        f"- 들어볼 파일: {meta.get('video_file') or meta.get('audio_file')}",
        f"- 제안 공개: {state['publish_at']} (예약 공개, AI 합성 표시 켬)",
        "",
        "## 승인하면",
        "```",
        f".venv/bin/python scripts/upload_luna_compilation.py --genre {out_dir.name} --execute [--playlist-id <재생목록>]",
        "```",
        "공개 시각을 바꾸려면 `--publish-at` 을 직접 주세요. 곡을 바꾸고 싶으면 업로드하지 말고 알려 주세요"
        "(바꾼 편성은 추첨 결과가 아니므로 학습에서 빠집니다).",
    ]
    if report.get("warnings"):
        lines += ["", "## 경고"] + [f"- {w}" for w in report["warnings"]]
    lines += ["", "## 트랙리스트"] + [f"- {t.get('start')} {t.get('title')}" + (" ★" if t.get("first_release") else "")
                                    for t in meta.get("tracks") or []]
    return "\n".join(lines) + "\n"


def notify(message: str) -> None:
    try:
        subprocess.run(["/usr/bin/osascript", "-e",
                        f'display notification "{message}" with title "루나 주간 컴필레이션"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def logged_compilation_decisions(publish_date: str, path: Optional[Path] = None) -> List[str]:
    """결정 기록에 이미 있는 이 공개일의 주간 컴필레이션 decision_id."""
    return [ev["decision_id"] for ev in luna_decisions.load_events(path)
            if ev.get("event") == "decision" and isinstance(ev.get("context"), dict)
            and ev["context"].get("kind") == "weekly_compilation" and ev["context"].get("publish_date") == publish_date]


@contextlib.contextmanager
def date_lock(root: Path, publish_date: str):
    """같은 공개일 준비가 동시에 돌지 않게(launchd + 수동 실행) 잠근다. 잠겨 있으면 바로 실패."""
    root.mkdir(parents=True, exist_ok=True)
    f = open(root / f".{publish_date}.lock", "w")
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"{publish_date} 준비가 이미 실행 중입니다.")
        yield
    finally:
        f.close()


def _decide(publish_date: str, root: Path, rng, candidates_fn, decisions_path, publish_time) -> Optional[Path]:
    """결정 단계. 한 공개일에 한 번만 뽑는다. 반환: decision.json 경로 (후보 없음이면 None).

    순서: decision.json(status=drawing, decision_id 미리 정함) → 결정 기록 → status=awaiting_build.
    중간에 죽어도 다음 실행이 같은 decision_id 로 기록을 마저 하므로 다시 뽑지 않는다.
    """
    found = existing_decision(publish_date, root)
    stray = [p for p in sorted(root.glob(f"{publish_date}_*")) if p.is_dir() and not (p / "decision.json").exists()]
    if stray:
        raise RuntimeError(f"decision.json 없는 같은 공개일 폴더가 있습니다(사람이 정리 필요): {[str(p) for p in stray]}")
    logged = logged_compilation_decisions(publish_date, decisions_path)
    if found is None:
        if logged:
            raise RuntimeError(f"결정 기록에는 {publish_date} 추첨({logged})이 있는데 폴더가 없습니다. 다시 뽑지 않습니다.")
        candidates = candidates_fn(publish_date)
        if not candidates:
            return None
        draw = draw_candidate(candidates, rng or random.SystemRandom())
        entry = dict(draw["entry"])
        entry["publish_date"] = publish_date
        out_dir = root / f"{publish_date}_{entry['theme']}"
        out_dir.mkdir(parents=True, exist_ok=False)
        (out_dir / "plan.json").write_text(json.dumps([entry], ensure_ascii=False, indent=2), encoding="utf-8")
        state = {"decision_id": luna_decisions.new_decision_id(), "publish_date": publish_date,
                 "publish_at": publish_at_iso(publish_date, publish_time), "theme": entry["theme"],
                 "probability": draw["probability"], "themes": draw["themes"], "status": STATUS_DRAWING,
                 "candidates": candidates_summary(candidates)}
        found = out_dir / "decision.json"
        write_json(found, state)
    state = json.loads(found.read_text(encoding="utf-8"))
    if state.get("status") == STATUS_DRAWING:
        others = [d for d in logged if d != state["decision_id"]]
        if others:
            raise RuntimeError(f"{publish_date} 에 다른 추첨 기록이 있습니다: {others}")
        if state["decision_id"] not in logged:
            rec = record_compilation_decision(state, publish_date, path=decisions_path)
            state["decided_at"] = rec["created_at"]
        state["status"] = STATUS_AWAITING_BUILD
        write_json(found, state)
    return found


def prepare(publish_date: str, *, root: Path = COMPILATIONS_DIR, render_video: bool = True,
            rng: Optional[random.Random] = None, candidates_fn=run_candidates, builder=None,
            decisions_path: Optional[Path] = None, publish_time: str = PUBLISH_TIME) -> Dict[str, Any]:
    """결정(없으면 새로 뽑아 기록) → 렌더(안 됐으면) → 확정 요청. 반환: state (+ status)."""
    root = Path(root)
    with date_lock(root, publish_date):
        found = _decide(publish_date, root, rng, candidates_fn, decisions_path, publish_time)
        if found is None:
            return {"status": "no_candidates", "publish_date": publish_date}
        state = json.loads(found.read_text(encoding="utf-8"))
        out_dir = found.parent
        if state.get("status") in (STATUS_AWAITING_APPROVAL, STATUS_UPLOADED):
            return state
        return _build(state, out_dir, publish_date, builder, render_video)


def _build(state, out_dir: Path, publish_date: str, builder, render_video: bool) -> Dict[str, Any]:
    builder = builder or _load_builder()
    plan_path = out_dir / "plan.json"
    entry = builder.select_week(builder.load_plan(plan_path), publish_date=publish_date)
    builder.validate_week(entry)
    res = builder.build_compilation(plan_path, entry, out_dir, render_video_file=render_video)
    meta, report = res["metadata"], res["report"]
    (out_dir / "approval_request.md").write_text(approval_text(state, meta, report, out_dir), encoding="utf-8")
    state["status"] = STATUS_AWAITING_APPROVAL
    state["built_at"] = datetime.now(timezone.utc).isoformat()
    write_json(out_dir / "decision.json", state)
    return state


def record_applied_for(out_dir: Path, decisions_path: Optional[Path] = None) -> Dict[str, Any]:
    """업로드 결과(upload_result.json)를 같은 decision_id 로 결정 기록에 덧붙이고 decision.json 을 갱신한다.
    이미 기록했으면 다시 쓰지 않는다."""
    out_dir = Path(out_dir)
    state_path, result_path = out_dir / "decision.json", out_dir / "upload_result.json"
    if not state_path.exists():
        return {"recorded": False, "reason": "no_decision"}
    if not result_path.exists():
        raise RuntimeError(f"업로드 결과가 없습니다: {result_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    video_id = result.get("video_id")
    if not video_id:
        raise RuntimeError("upload_result.json 에 video_id 가 없습니다.")
    if state.get("status") == STATUS_UPLOADED and state.get("video_id") == video_id:
        return {"recorded": False, "reason": "already_recorded", "video_id": video_id}
    meta_path = out_dir / "youtube_metadata.json"
    theme = json.loads(meta_path.read_text(encoding="utf-8")).get("theme") if meta_path.exists() else None
    luna_decisions.record_applied(
        state["decision_id"],
        applied={"format": FORMAT, "genre": theme or state["theme"], "mood": None, "vocal_mode": None},
        video_id=video_id, publish_at=result.get("publish_at"), path=decisions_path)
    state.update({"status": STATUS_UPLOADED, "video_id": video_id, "applied_publish_at": result.get("publish_at")})
    write_json(state_path, state)
    return {"recorded": True, "video_id": video_id}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="루나 주간 컴필레이션 준비 (업로드 없음)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--publish-date", required=True, help="YYYY-MM-DD 또는 next(이틀 뒤 이후 첫 토요일)")
    p.add_argument("--publish-time", default=PUBLISH_TIME, help="KST HH:MM (기본 22:00)")
    p.add_argument("--no-video", action="store_true", help="오디오·메타데이터만 (시험용)")
    p.add_argument("--quiet", action="store_true", help="macOS 알림 끄기")
    r = sub.add_parser("record-applied")
    r.add_argument("--dir", required=True, help="data/luna_compilations/<폴더 이름>")
    args = parser.parse_args(argv)

    if args.command == "record-applied":
        print(json.dumps(record_applied_for(COMPILATIONS_DIR / args.dir), ensure_ascii=False))
        return 0

    skipped = None
    if args.publish_date == "next":
        today = datetime.now(KST).date()
        publish_date = next_publish_date(today).isoformat()
        skipped = skipped_publish_date(today)
        if skipped:
            msg = f"이번 주 {skipped} 컴필레이션이 준비되지 않았습니다(이틀 여유 없음). 다음 주 {publish_date} 분을 준비합니다."
            print(f"[!] {msg}", file=sys.stderr)
            if not args.quiet:
                notify(msg)
    else:
        publish_date = date.fromisoformat(args.publish_date).isoformat()
    try:
        state = prepare(publish_date, render_video=not args.no_video, publish_time=args.publish_time)
    except Exception as e:  # 알림을 띄우고 실패로 끝낸다 (결정 파일이 있으면 다음 실행이 이어서 렌더)
        if not args.quiet:
            notify(f"{publish_date} 준비 실패: {str(e)[:120]}")
        print(f"[Error] {e}", file=sys.stderr)
        return 1
    if skipped:
        state["skipped_publish_date"] = skipped.isoformat()
    print(json.dumps(state, ensure_ascii=False))
    if state["status"] == "no_candidates":
        if not args.quiet:
            notify(f"{publish_date}: 만들 수 있는 테마가 없습니다 (최근 4주 사용 곡 제외 후 50분 미만)")
        return 4
    if not args.quiet and state["status"] == STATUS_AWAITING_APPROVAL:
        notify(f"{publish_date} {state['theme']} 렌더 완료 — 듣고 확정해 주세요 (approval_request.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
