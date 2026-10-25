"""범용 3D 장면(scene3d) 설명 검증·기본값 — 쇼츠 씬 kind="scene3d" 의 "scene3d" 필드.

기획 AI(또는 사람)가 환경·바닥·카메라·물체를 조합해 3D 장면을 서술하면 Remotion(remotion/src/three/)이 그대로 그린다.
여기서는 모르는 값·범위를 벗어난 숫자·긴 문자열을 정리해 렌더가 깨지지 않게 한다. 이미지 생성 비용은 0.
"""

import math
import re
from typing import Any, Dict, List, Optional

ENVIRONMENTS = ("sky", "space", "studio", "dark")
GROUNDS = ("terrain", "water", "grid", "floor", "none")
TIMES = ("sunrise", "day", "sunset", "night")
CAMERA_MOVES = ("orbit", "dolly", "flyover", "pan", "static")
PRIMITIVES = ("box", "sphere", "torus", "cone", "cylinder", "icosahedron")
MATERIALS = ("standard", "metal", "glass", "emissive")
OBJECT_TYPES = PRIMITIVES + ("text", "bars", "globe", "particles", "model")
MAX_OBJECTS = 12

DEFAULT_ACCENT = "#ffd166"
DEFAULT_GROUND = {"sky": "terrain", "space": "none", "studio": "floor", "dark": "grid"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _num(v: Any, default: float, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(f) or math.isinf(f):
        return float(default)
    return float(min(hi, max(lo, f)))


def _color(v: Any, default: str) -> str:
    return v if isinstance(v, str) and _HEX.match(v) else default


def _text(v: Any, n: int) -> str:
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _vec3(v: Any, default: List[float], lo: float = -50, hi: float = 50) -> List[float]:
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return [_num(v[i], default[i], lo, hi) for i in range(3)]
    return list(default)


def _scale(v: Any) -> List[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        s = _num(v, 1, 0.05, 20)
        return [s, s, s]
    return _vec3(v, [1.0, 1.0, 1.0], 0.05, 20)


def _object(o: Any, accent: str) -> Optional[Dict[str, Any]]:
    if not isinstance(o, dict):
        return None
    t = str(o.get("type") or "").strip().lower()
    if t not in OBJECT_TYPES:
        return None
    base = {
        "type": t,
        "position": _vec3(o.get("position"), [0.0, 0.0, 0.0]),
        "scale": _scale(o.get("scale", 1)),
        "spin": _num(o.get("spin"), 0, -360, 360),      # 초당 회전(도)
        "color": _color(o.get("color"), accent),
    }
    if t in PRIMITIVES:
        base["material"] = o.get("material") if o.get("material") in MATERIALS else "standard"
        return base
    if t == "text":
        text = _text(o.get("text"), 24)
        if not text:
            return None
        base.update(text=text, size=_num(o.get("size"), 1, 0.2, 5))
        base["color"] = _color(o.get("color"), "#ffffff")
        return base
    if t == "bars":
        items = []
        for it in o.get("items") or []:
            if not isinstance(it, dict) or it.get("label") is None:
                continue
            try:
                value = float(it.get("value"))
            except (TypeError, ValueError):
                continue
            items.append({"label": _text(it["label"], 10), "value": value, "highlight": bool(it.get("highlight"))})
        if len(items) < 2:
            return None
        base.update(items=items[:8], unit=_text(o.get("unit"), 6))
        return base
    if t == "globe":
        pins = []
        for p in o.get("pins") or []:
            if not isinstance(p, dict):
                continue
            try:
                lat, lon = float(p.get("lat")), float(p.get("lon"))
            except (TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            pins.append({"lat": lat, "lon": lon, "label": _text(p.get("label"), 10)})
        base.update(pins=pins[:8], arcs=bool(o.get("arcs")) and len(pins) >= 2)
        return base
    if t == "particles":
        base.update(count=int(_num(o.get("count"), 800, 50, 3000)), spread=_num(o.get("spread"), 12, 2, 60))
        return base
    if t == "model":
        src = str(o.get("src") or "").strip()
        if not src:
            return None
        base["src"] = src
        return base
    return None


def normalize_scene3d(spec: Any, scene_num: int = 1) -> Dict[str, Any]:
    """scene3d 설명을 정리해 돌려준다. spec 이 없거나 이상해도 그릴 수 있는 기본 장면을 만든다."""
    spec = spec if isinstance(spec, dict) else {}
    env = spec.get("environment") if spec.get("environment") in ENVIRONMENTS else "studio"
    ground = spec.get("ground") if spec.get("ground") in GROUNDS else DEFAULT_GROUND[env]
    time_of_day = spec.get("time_of_day") if spec.get("time_of_day") in TIMES else "sunset"
    cam_in = spec.get("camera") if isinstance(spec.get("camera"), dict) else {}
    move = cam_in.get("move") if cam_in.get("move") in CAMERA_MOVES else "orbit"
    if move == "flyover" and ground != "terrain":
        move = "orbit"   # 항공 이동은 지형 위에서만 의미가 있다
    camera = {
        "move": move,
        "distance": _num(cam_in.get("distance"), 8, 2, 60),
        "height": _num(cam_in.get("height"), 2.5, -10, 40),
        "sweep": _num(cam_in.get("sweep"), 40, -360, 360),   # 씬 동안 도는 각도(orbit)
    }
    accent = _color(spec.get("accent"), DEFAULT_ACCENT)
    try:
        seed = int(spec.get("seed"))
    except (TypeError, ValueError):
        seed = int(scene_num or 1)
    objects = [x for x in (_object(o, accent) for o in (spec.get("objects") or [])) if x][:MAX_OBJECTS]
    return {"environment": env, "ground": ground, "time_of_day": time_of_day, "camera": camera,
            "accent": accent, "seed": seed, "objects": objects}
