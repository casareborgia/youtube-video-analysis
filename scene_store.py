# -*- coding: utf-8 -*-
"""씬 기획서 저장소 — 3단계(씬 기획)의 결과를 4단계(영상 합성)가 소비할 수 있게 보관한다.

씬 기획 결과는 지금까지 브라우저 메모리에만 존재해서, producer 가 요구하는
structured_scenes 를 가진 기획서가 어디에도 만들어지지 않았다. 채널 기획서
(channel_builder)는 채널명·설명·키워드를 담는 별개의 문서라 여기에 얹지 않고
씬 전용 저장소를 둔다.

producer.build_video 가 요구하는 최소 형태:
    plan_id, aspect_ratio, scene_seconds, structured_scenes[{scene_num, seconds, subtitle}]
    선택: audio_data.scenes_audio[{scene_num, audio_file}]
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCENES_DIR = os.path.join(BASE_DIR, "data", "scene_plans")
os.makedirs(SCENES_DIR, exist_ok=True)

PLAN_ID_RE = re.compile(r"^scenes_[0-9]+(?:_[\w가-힣-]+)?$")


def _slug(text: str, limit: int = 24) -> str:
    s = re.sub(r"[^\w가-힣]+", "_", (text or "").strip())
    return s.strip("_")[:limit] or "untitled"


def _path(plan_id: str) -> str:
    """저장 경로. 경로 순회를 막기 위해 파일명만 취하고 형식을 검증한다."""
    safe = os.path.basename(str(plan_id))
    if not PLAN_ID_RE.match(safe):
        raise ValueError("올바르지 않은 기획서 ID 형식입니다.")
    return os.path.join(SCENES_DIR, f"{safe}.json")


def build_plan(batch: Dict[str, Any], scene_seconds: float = 8.0) -> Dict[str, Any]:
    """씬 기획 응답(batch)을 producer 가 읽는 기획서 형태로 변환한다.

    나레이션은 자막(subtitle)이자 TTS 대본이므로 두 이름 모두로 담아 둔다.
    """
    scenes_in = batch.get("scenes") or []
    structured: List[Dict[str, Any]] = []
    audio_scenes: List[Dict[str, Any]] = []

    for idx, sc in enumerate(scenes_in, start=1):
        num = int(sc.get("scene_num") or idx)
        narration = (sc.get("narration") or sc.get("subtitle") or "").strip()
        structured.append({
            "scene_num": num,
            "seconds": float(sc.get("seconds") or scene_seconds),
            "subtitle": narration,
            "narration": narration,
            "time_range": sc.get("time_range", ""),
            "dramatic_beat": sc.get("dramatic_beat", ""),
            "camera": sc.get("camera", ""),
            "lighting": sc.get("lighting", ""),
            "sfx": sc.get("sfx", ""),
            "prompt_en": sc.get("prompt_en", ""),
            "visual_description_ko": sc.get("visual_description_ko", ""),
            "first_frame_redline": sc.get("first_frame_redline"),
        })
        # 씬 기획 탭에서 이미 합성한 음성이 있으면 함께 넘긴다
        audio_file = sc.get("audio_file")
        if audio_file and os.path.exists(audio_file):
            audio_scenes.append({"scene_num": num, "audio_file": audio_file})

    topic = batch.get("topic") or "씬 기획"
    plan_id = f"scenes_{int(time.time())}_{_slug(topic)}"

    return {
        "plan_id": plan_id,
        "topic": topic,
        "title": batch.get("recommended_title") or topic,
        "aspect_ratio": batch.get("aspect_ratio") or "16:9",
        "scene_seconds": scene_seconds,
        "language": batch.get("language", "korean"),
        "model": batch.get("model", ""),
        "seo_description": batch.get("seo_description", ""),
        "title_candidates": batch.get("title_candidates", []),
        "engagement_question": batch.get("engagement_question", ""),
        "pinned_comment": batch.get("pinned_comment", ""),
        "thumbnail_redline": batch.get("thumbnail_redline"),
        "structured_scenes": structured,
        "audio_data": {"scenes_audio": audio_scenes},
        "created_at": time.time(),
    }


def save_plan(plan: Dict[str, Any]) -> str:
    """기획서를 저장하고 plan_id 를 반환한다."""
    plan_id = plan.get("plan_id") or f"scenes_{int(time.time())}"
    plan["plan_id"] = plan_id
    with open(_path(plan_id), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return plan_id


def load_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_path(plan_id), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_plans() -> List[Dict[str, Any]]:
    """최신순 요약 목록. producer 탭 드롭다운용."""
    out = []
    try:
        names = os.listdir(SCENES_DIR)
    except Exception:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(SCENES_DIR, name), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        out.append({
            "id": d.get("plan_id") or name[:-5],
            "topic": d.get("topic", ""),
            "title": d.get("title", ""),
            "scene_count": len(d.get("structured_scenes") or []),
            "audio_count": len((d.get("audio_data") or {}).get("scenes_audio") or []),
            "aspect_ratio": d.get("aspect_ratio", "16:9"),
            "created_at": d.get("created_at", 0),
        })
    out.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return out


def delete_plan(plan_id: str) -> bool:
    try:
        os.remove(_path(plan_id))
        return True
    except Exception:
        return False
