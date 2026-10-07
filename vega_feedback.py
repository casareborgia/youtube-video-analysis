"""vega_feedback.py - 사운드 엔지니어 베가(Vega) 피드백 로그 및 프리셋 보정 제안 모듈

재마스터·렌더·A/B 선택 기록을 data/luna_music/vega_feedback.jsonl 에 남기고,
장르별 최근 기록의 중앙값(statistics.median)으로 프리셋 보정값을 제안한다.
자동 적용 없음, ML 없음, 새 의존성 없음 (표준 라이브러리 statistics 사용).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import time
from typing import Any, Dict, List, Optional

import luna_engine
import vega_engine

# append-only JSON Lines 저장 경로 (data/ 는 .gitignore 대상)
FEEDBACK_PATH = Path(luna_engine.LUNA_DIR) / "vega_feedback.jsonl"

# 파라미터별 최대 허용 delta 클램프 한도
# target_lufs ±1.0 LU | compressor.threshold_db ±1.0 dB | compressor.ratio ±0.3 |
# saturator.drive_db ±1.0 dB | stereo_image.width ±0.1 | low/high shelf gain_db ±1.0 dB
CLAMP_LIMITS: Dict[str, float] = {
    "target_lufs": 1.0,
    "compressor.threshold_db": 1.0,
    "compressor.ratio": 0.3,
    "saturator.drive_db": 1.0,
    "stereo_image.width": 0.1,
    "tonal_eq.low_shelf_gain_db": 1.0,
    "tonal_eq.high_shelf_gain_db": 1.0,
}



def _normalize_genre(genre: Optional[str]) -> str:
    """장르 표시명/키를 프리셋 키로 정규화한다 (vega_engine.resolve_genre_key 위임, 미해석 시 "default")."""
    return vega_engine.resolve_genre_key(genre)


def _record_genre_key(rec: dict) -> str:
    """기록의 장르 키. 구버전 기록(genre_key 없음)은 genre 표시명에서 해석한다."""
    return rec.get("genre_key") or _normalize_genre(rec.get("genre"))


def extract_shelf_gains(tonal_eq: Any) -> tuple[float, float]:
    """tonal_eq 설정(dict 또는 Pydantic 객체)에서 low_shelf 및 high_shelf의 gain_db를 추출한다."""
    low_gain = 0.0
    high_gain = 0.0
    bands = []
    if isinstance(tonal_eq, dict):
        bands = tonal_eq.get("bands", [])
    elif hasattr(tonal_eq, "bands"):
        bands = tonal_eq.bands or []

    for b in bands:
        ft = b.get("filter_type") if isinstance(b, dict) else getattr(b, "filter_type", None)
        g = b.get("gain_db", 0.0) if isinstance(b, dict) else getattr(b, "gain_db", 0.0)
        try:
            val = float(g)
        except (ValueError, TypeError):
            val = 0.0
        if ft == "low_shelf":
            low_gain = val
        elif ft == "high_shelf":
            high_gain = val
    return low_gain, high_gain


def extract_decisions_summary(decisions: Any) -> Dict[str, float]:
    """decisions 딕셔너리 또는 객체에서 프리셋 보정 대상 수치들을 정규화하여 추출한다."""
    if not decisions:
        return {}
    
    if not isinstance(decisions, dict) and hasattr(decisions, "model_dump"):
        decisions = decisions.model_dump()
    elif not isinstance(decisions, dict) and hasattr(decisions, "dict"):
        decisions = decisions.dict()

    if not isinstance(decisions, dict):
        return {}

    comp = decisions.get("compressor") or {}
    sat = decisions.get("saturator") or {}
    stereo = decisions.get("stereo_image") or {}
    tonal = decisions.get("tonal_eq") or {}

    low_shelf, high_shelf = extract_shelf_gains(tonal)

    try:
        t_lufs = float(decisions.get("target_lufs", -14.0))
    except (ValueError, TypeError):
        t_lufs = -14.0

    try:
        c_thresh = float(comp.get("threshold_db", -18.0))
    except (ValueError, TypeError):
        c_thresh = -18.0

    try:
        c_ratio = float(comp.get("ratio", 2.0))
    except (ValueError, TypeError):
        c_ratio = 2.0

    try:
        s_drive = float(sat.get("drive_db", 0.0))
    except (ValueError, TypeError):
        s_drive = 0.0

    try:
        s_mix = float(sat.get("mix", 0.0))
    except (ValueError, TypeError):
        s_mix = 0.0

    try:
        st_width = float(stereo.get("width", 1.0))
    except (ValueError, TypeError):
        st_width = 1.0

    return {
        "target_lufs": round(t_lufs, 2),
        "compressor.threshold_db": round(c_thresh, 2),
        "compressor.ratio": round(c_ratio, 2),
        "saturator.drive_db": round(s_drive, 2),
        "saturator.mix": round(s_mix, 2),
        "stereo_image.width": round(st_width, 2),
        "tonal_eq.low_shelf_gain_db": round(low_shelf, 2),
        "tonal_eq.high_shelf_gain_db": round(high_shelf, 2),
    }


def extract_metrics_summary(metrics: Any) -> Dict[str, float]:
    """before/after 측정치에서 integrated_lufs, true_peak_dbtp 추출."""
    if not metrics:
        return {}
    if not isinstance(metrics, dict) and hasattr(metrics, "model_dump"):
        metrics = metrics.model_dump()
    elif not isinstance(metrics, dict) and hasattr(metrics, "dict"):
        metrics = metrics.dict()
    if not isinstance(metrics, dict):
        return {}
    try:
        lufs = float(metrics.get("integrated_lufs", 0.0))
    except (ValueError, TypeError):
        lufs = 0.0
    try:
        tp = float(metrics.get("true_peak_dbtp", 0.0))
    except (ValueError, TypeError):
        tp = 0.0
    return {
        "integrated_lufs": round(lufs, 2),
        "true_peak_dbtp": round(tp, 2),
    }


def build_feedback_event(event_type: str, track: dict, **extra: Any) -> dict:
    """트랙 및 추가 정보로부터 정규화된 피드백 이벤트 딕셔너리를 구성한다.
    
    오디오·파일 경로·토큰은 일체 포함하지 않는다.
    """
    mastering = (track.get("mastering") or {}) if isinstance(track, dict) else {}
    genre = str(track.get("genre") or mastering.get("genre") or "")
    mood = str(track.get("mood") or "")

    event: Dict[str, Any] = {
        "ts": time.time(),
        "event": event_type,
        "track_id": str(track.get("track_id") or ""),
        "genre": genre,
        "genre_key": str(mastering.get("genre_key") or _normalize_genre(genre)),
        "mood": mood,
    }

    if event_type == "preference":
        event["choice"] = str(extra.get("choice") or "master")

    # mastering 요약 필드 주입
    if mastering:
        event["prompt"] = str(extra.get("prompt") if "prompt" in extra else mastering.get("prompt", ""))
        event["use_llm"] = bool(extra.get("use_llm") if "use_llm" in extra else (mastering.get("decision_source") == "llm"))
        event["decision_source"] = str(mastering.get("decision_source") or "")
        event["decision_model"] = mastering.get("decision_model")
        event["target_lufs"] = float(mastering.get("target_lufs", -14.0))
        event["ceiling_dbtp"] = float(mastering.get("ceiling_dbtp", -1.0))
        event["decisions"] = extract_decisions_summary(mastering.get("decisions"))
        event["before"] = extract_metrics_summary(mastering.get("before"))
        event["after"] = extract_metrics_summary(mastering.get("after"))

    # 기타 extra 필드 반영
    for k, v in extra.items():
        if k not in event and k not in ("audio_url", "video_url", "audio_file", "cover_file"):
            event[k] = v

    return event


def record_feedback(event: dict) -> dict:
    """피드백 이벤트를 FEEDBACK_PATH에 JSON Lines로 추가(append-only) 기록한다.
    
    쓰기 실패 시 절대 예외를 밖으로 던지지 않고 {"status": "skipped", "reason": ...}을 반환한다.
    """
    try:
        if not isinstance(event, dict):
            return {"status": "skipped", "reason": "invalid_event_dict"}

        event_type = event.get("event")
        if event_type not in ("remaster", "render", "preference"):
            return {"status": "skipped", "reason": f"unknown_event_{event_type}"}

        # 정제된 레코드 구성 (민감 정보·경로 제외)
        rec: Dict[str, Any] = {
            "ts": float(event.get("ts") or time.time()),
            "event": event_type,
            "track_id": str(event.get("track_id") or ""),
            "genre": str(event.get("genre") or ""),
            "genre_key": str(event.get("genre_key") or _normalize_genre(event.get("genre"))),
            "mood": str(event.get("mood") or ""),
        }

        if event_type == "preference":
            rec["choice"] = str(event.get("choice") or "master")

        for k in ("prompt", "use_llm", "decision_source", "decision_model", "target_lufs", "ceiling_dbtp"):
            if k in event:
                rec[k] = event[k]

        if "decisions" in event and isinstance(event["decisions"], dict):
            rec["decisions"] = event["decisions"]
        if "before" in event and isinstance(event["before"], dict):
            rec["before"] = event["before"]
        if "after" in event and isinstance(event["after"], dict):
            rec["after"] = event["after"]

        path = Path(FEEDBACK_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        return {"status": "ok", "event": rec}
    except Exception as e:
        return {"status": "skipped", "reason": str(e)}


def load_feedback(genre: Optional[str] = None, event: Optional[str] = None, limit: int = 200) -> List[dict]:
    """저장된 피드백 기록을 읽어 최근순(최신순)으로 정렬하여 반환한다."""
    path = Path(FEEDBACK_PATH)
    if not path.exists():
        return []

    records: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    records.append(data)
                except Exception:
                    continue
    except Exception:
        return []

    # 장르 및 이벤트 필터링
    filtered: List[dict] = []
    norm_g = _normalize_genre(genre)
    for r in records:
        if genre and _record_genre_key(r) != norm_g and r.get("genre") != genre:
            continue
        if event and r.get("event") != event:
            continue
        filtered.append(r)

    # 최근순 정렬 (파일 끝이 최신)
    filtered.reverse()
    if limit and limit > 0:
        return filtered[:limit]
    return filtered


def suggest_preset_adjustment(genre: str, min_samples: int = 3, window: int = 20) -> dict:
    """해당 장르의 최근 window 건 피드백 중앙값을 계산하여 프리셋 보정값을 제안한다.
    
    대상: 해당 장르의 최근 window 건 중 event ∈ {remaster(decision_source=="llm"), render}
    표본 < min_samples → {"status": "insufficient", "samples": n, "min_samples": 3}
    |delta| < 0.05 인 항목은 제안에서 제외한다.
    자동 적용은 수행하지 않으며 제안만 반환한다.
    """
    if not genre:
        return {"status": "insufficient", "genre": genre, "samples": 0, "min_samples": min_samples}

    # 전체 기록 읽기
    path = Path(FEEDBACK_PATH)
    if not path.exists():
        return {"status": "insufficient", "genre": genre, "samples": 0, "min_samples": min_samples}

    raw_records: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return {"status": "insufficient", "genre": genre, "samples": 0, "min_samples": min_samples}

    # 조건에 부합하는 대상 필터링
    # event == "render" OR (event == "remaster" and decision_source == "llm")
    target_samples: List[dict] = []
    norm_g = _normalize_genre(genre)
    for r in raw_records:
        if _record_genre_key(r) != norm_g and r.get("genre") != genre:
            continue
        ev = r.get("event")
        src = r.get("decision_source")
        dec = r.get("decisions")
        # 결정값이 없는 기록(마스터링 없이 렌더 등)은 표본으로 세지 않는다
        if not isinstance(dec, dict) or not dec:
            continue
        if ev == "render" or (ev == "remaster" and src == "llm"):
            target_samples.append(r)

    # 최근 window 건만 취함
    if len(target_samples) > window:
        target_samples = target_samples[-window:]

    n = len(target_samples)
    if n < min_samples:
        return {
            "status": "insufficient",
            "genre": genre,
            "samples": n,
            "min_samples": min_samples,
        }

    # 기준 프리셋 가져오기
    preset = vega_engine.preset_for_genre(norm_g)
    preset_low, preset_high = extract_shelf_gains(preset.tonal_eq)
    preset_values: Dict[str, float] = {
        "target_lufs": float(preset.target_lufs),
        "compressor.threshold_db": float(preset.compressor.threshold_db),
        "compressor.ratio": float(preset.compressor.ratio),
        "saturator.drive_db": float(preset.saturator.drive_db),
        "stereo_image.width": float(preset.stereo_image.width),
        "tonal_eq.low_shelf_gain_db": float(preset_low),
        "tonal_eq.high_shelf_gain_db": float(preset_high),
    }

    # 각 파라미터별 표본 값 수집
    collected_values: Dict[str, List[float]] = {k: [] for k in CLAMP_LIMITS}
    for s in target_samples:
        dec = s.get("decisions") or {}
        if not isinstance(dec, dict):
            continue
        for param in CLAMP_LIMITS:
            if param in dec and dec[param] is not None:
                try:
                    collected_values[param].append(float(dec[param]))
                except (ValueError, TypeError):
                    pass

    suggestions: List[dict] = []
    for param, limit in CLAMP_LIMITS.items():
        vals = collected_values.get(param, [])
        if not vals:
            continue
        med = float(statistics.median(vals))
        preset_val = preset_values.get(param, 0.0)
        raw_delta = med - preset_val

        # delta 클램프
        clamped_delta = max(-limit, min(limit, raw_delta))

        # |delta| < 0.05 인 항목은 제외
        if abs(clamped_delta) < 0.05:
            continue

        suggested_val = round(preset_val + clamped_delta, 2)
        suggestions.append({
            "param": param,
            "preset": round(preset_val, 2),
            "median": round(med, 2),
            "suggested": suggested_val,
            "delta": round(clamped_delta, 2),
        })

    return {
        "status": "ok",
        "genre": genre,
        "samples": n,
        "window": window,
        "suggestions": suggestions,
        "note": "제안값이며 자동 적용되지 않습니다",
    }
