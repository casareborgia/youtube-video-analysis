"""
루나 제작 정책 파일(data/luna_policy.json) — 강화학습 시뮬레이터가 만든 선택 확률을 읽고 검증한다.

정책 파일은 시뮬레이터(~/coding/강화학습시뮬레이터)의 밴딧 학습기가 주 1회 갱신한다.
TubeInsight 는 그 확률로 다음 곡의 형식·장르·무드(·보컬 모드)를 뽑고, 실제 선택 확률을 결정 기록에 남긴다.
파일이 없거나 만료됐거나 스키마가 틀리면 호출 측(trend_scout)이 기존 균형 가중치로 돌아간다.

스키마 (schema_version 1):
{
  "schema_version": 1,
  "policy_version": "luna-0.1.0+ts-2026w44",
  "valid_until": "2026-11-07T00:00:00Z",          # 시간대 포함 ISO 8601. 이 시각 이후는 만료
  "exploration_floor": 0.10,                       # 균등 탐색 비율 ε. 각 선택지 확률 ≥ ε / 선택지 수
  "arms": {                                        # 차원별 선택지 → 확률 (차원끼리는 독립으로 뽑는다)
    "format": {"single": 0.9, "compilation_1h": 0.1},
    "genre": {"lofi": 0.2, ...},                   # 채널 고정 장르를 전부 담아야 한다
    "mood": {...},                                 # 생략하면 호출 측이 균등으로 채운다
    "vocal_mode": {...}                            # 생략하면 "auto" 고정
  }
}
"""

import json
import math
import os
import random
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
POLICY_PATH = DATA_DIR / "luna_policy.json"

SCHEMA_VERSION = 1
# 사용자 결정(2026-10-24): 유력한 형식에 많이 배정하되 10% 균등 탐색은 남긴다
MIN_EXPLORATION_FLOOR = 0.10
FORMATS = ("single", "compilation_1h", "compilation_long", "shorts")
VOCAL_MODES = ("auto", "instrumental", "lyrics")
REQUIRED_DIMENSIONS = ("format", "genre")
OPTIONAL_DIMENSIONS = ("mood", "vocal_mode")
_SUM_TOLERANCE = 1e-3
_FLOOR_TOLERANCE = 1e-9

SOURCE_POLICY = "policy_file"
SOURCE_FALLBACK = "fallback_balanced"


class PolicyError(ValueError):
    """정책 파일이 없거나, 만료됐거나, 스키마가 맞지 않을 때."""


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError("valid_until 이 비어 있습니다.")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise PolicyError(f"valid_until 형식이 잘못됐습니다: {value}") from e
    if dt.tzinfo is None:
        raise PolicyError(f"valid_until 에 시간대가 없습니다: {value}")
    return dt.astimezone(timezone.utc)


def _validate_dimension(name: str, probs: Any, allowed: Sequence[str], floor: float,
                        required_keys: Optional[Iterable[str]] = None) -> Dict[str, float]:
    if not isinstance(probs, dict) or not probs:
        raise PolicyError(f"arms.{name} 는 비어 있지 않은 객체여야 합니다.")
    unknown = [k for k in probs if k not in allowed]
    if unknown:
        raise PolicyError(f"arms.{name} 에 허용되지 않는 선택지: {unknown}")
    missing = [k for k in (required_keys or ()) if k not in probs]
    if missing:
        raise PolicyError(f"arms.{name} 에 빠진 선택지(확률 0이 됨): {missing}")
    values = {}
    for k, v in probs.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise PolicyError(f"arms.{name}.{k} 확률이 숫자가 아닙니다: {v!r}")
        values[k] = float(v)
    total = sum(values.values())
    if abs(total - 1.0) > _SUM_TOLERANCE:
        raise PolicyError(f"arms.{name} 확률 합이 1이 아닙니다: {total:.6f}")
    min_p = floor / len(values)
    low = {k: v for k, v in values.items() if v + _FLOOR_TOLERANCE < min_p}
    if low:
        raise PolicyError(f"arms.{name} 확률이 탐색 하한 {min_p:.4f} 보다 작습니다: {low}")
    return {k: v / total for k, v in values.items()}


def validate_policy(policy: Any, allowed: Dict[str, Sequence[str]],
                    required_coverage: Optional[Dict[str, Iterable[str]]] = None,
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """정책을 검증하고 확률을 정규화한 사본을 돌려준다. 문제가 있으면 PolicyError.

    allowed: 차원 → 허용 선택지 (예: {"format": FORMATS, "genre": [...], "mood": [...], "vocal_mode": VOCAL_MODES})
    required_coverage: 차원 → 반드시 들어 있어야 할 선택지 (예: 채널 고정 장르)
    """
    if not isinstance(policy, dict):
        raise PolicyError("정책은 JSON 객체여야 합니다.")
    if policy.get("schema_version") != SCHEMA_VERSION:
        raise PolicyError(f"schema_version 이 {SCHEMA_VERSION} 이 아닙니다: {policy.get('schema_version')!r}")
    version = policy.get("policy_version")
    if not isinstance(version, str) or not version.strip():
        raise PolicyError("policy_version 이 비어 있습니다.")
    valid_until = _parse_utc(policy.get("valid_until"))
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now_utc >= valid_until:
        raise PolicyError(f"정책이 만료됐습니다 (valid_until={policy.get('valid_until')}).")
    floor = policy.get("exploration_floor")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not math.isfinite(floor):
        raise PolicyError(f"exploration_floor 가 숫자가 아닙니다: {floor!r}")
    if not (MIN_EXPLORATION_FLOOR - _FLOOR_TOLERANCE <= floor <= 1.0):
        raise PolicyError(f"exploration_floor 는 {MIN_EXPLORATION_FLOOR} 이상 1 이하여야 합니다: {floor}")
    arms = policy.get("arms")
    if not isinstance(arms, dict):
        raise PolicyError("arms 가 없습니다.")
    for dim in REQUIRED_DIMENSIONS:
        if dim not in arms:
            raise PolicyError(f"arms.{dim} 가 없습니다.")
    unknown_dims = [d for d in arms if d not in REQUIRED_DIMENSIONS + OPTIONAL_DIMENSIONS]
    if unknown_dims:
        raise PolicyError(f"알 수 없는 차원: {unknown_dims}")

    coverage = required_coverage or {}
    normalized = {
        dim: _validate_dimension(dim, probs, allowed.get(dim, ()), float(floor), coverage.get(dim))
        for dim, probs in arms.items()
    }
    out = dict(policy)
    out["arms"] = normalized
    out["exploration_floor"] = float(floor)
    return out


def load_policy(allowed: Dict[str, Sequence[str]], path: Optional[Path] = None,
                required_coverage: Optional[Dict[str, Iterable[str]]] = None,
                now: Optional[datetime] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """(검증된 정책 또는 None, 사유). 파일 없음·깨짐·만료·스키마 오류는 None 과 사유를 돌려준다."""
    p = Path(path or POLICY_PATH)
    if not p.exists():
        return None, f"정책 파일 없음: {p}"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"정책 파일을 읽을 수 없음: {e}"
    try:
        return validate_policy(raw, allowed, required_coverage, now), "ok"
    except PolicyError as e:
        return None, str(e)


def write_policy_atomic(policy: Dict[str, Any], allowed: Dict[str, Sequence[str]], path: Optional[Path] = None,
                        required_coverage: Optional[Dict[str, Iterable[str]]] = None,
                        now: Optional[datetime] = None) -> Path:
    """임시 파일에 쓰고 → 다시 읽어 검증한 뒤 → os.replace 로 교체한다. 검증 실패 시 기존 파일은 그대로."""
    target = Path(path or POLICY_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".luna_policy.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(policy, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        written = json.loads(Path(tmp_name).read_text(encoding="utf-8"))
        validate_policy(written, allowed, required_coverage, now)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
    return target


def draw(probs: Dict[str, float], exclude: Iterable[str] = (), eligible: Optional[Iterable[str]] = None,
         rng: Optional[random.Random] = None) -> Tuple[str, float, List[str]]:
    """확률표에서 하나를 뽑는다 → (선택, 실제 선택 확률, 후보 목록).

    eligible·exclude 로 후보를 좁히면 남은 후보끼리 재정규화한 조건부 확률이 실제 선택 확률이다.
    """
    allowed = set(eligible) if eligible is not None else None
    excluded = set(exclude)
    pool = [k for k in probs if k not in excluded and (allowed is None or k in allowed) and probs[k] > 0]
    if not pool:
        raise ValueError("뽑을 후보가 없습니다.")
    weights = [probs[k] for k in pool]
    total = sum(weights)
    chosen = (rng or random).choices(pool, weights=weights, k=1)[0]
    return chosen, probs[chosen] / total, pool


def main(argv: Optional[List[str]] = None) -> int:
    """python luna_policy.py install <정책.json> — 시뮬레이터가 만든 정책을 검증 후 원자적으로 설치한다."""
    import trend_scout  # 허용 장르·무드 목록. 무거운 import 라 CLI 에서만 불러온다

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("install", "check"):
        print("사용법: python luna_policy.py install|check <정책.json>")
        return 2
    src = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    allowed, coverage = trend_scout.policy_arm_constraints()
    try:
        if args[0] == "check":
            validate_policy(src, allowed, coverage)
            print(f"[OK] {src.get('policy_version')} 검증 통과")
        else:
            dst = write_policy_atomic(src, allowed, required_coverage=coverage)
            print(f"[OK] {src.get('policy_version')} → {dst}")
    except PolicyError as e:
        print(f"[거부] {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
