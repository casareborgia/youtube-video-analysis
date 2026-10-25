"""로컬 ComfyUI 이미지 생성기 — Shiji Files 수묵 시네마틱 스타일 (작업계획서_ShijiFiles_파일럿3편 P-4).

producer.generate_images 와 같은 자리에 끼운다: generate_images(plan, slots, progress) → {"generated", "errors"}.
씬 이미지는 기획서 미디어 폴더(producer.render_dir)에 scene_XX.png 로 두고 미디어 인덱스에 source=comfyui 로 남긴다.

- 워크플로: comfy_workflows/z_image_turbo_api.json (자비스와 같은 z-image-turbo, 720×1280 장당 약 90초). COMFYUI_WORKFLOW 로 바꿀 수 있다.
- 비용 0 — Gemini 사용량에 세지 않는다(shorts_engine.generate_job_images).
- ComfyUI 가 꺼져 있으면 ComfyUnavailable 로 멈춘다. Gemini 로 자동 전환하지 않는다(과금 방지).
"""

import copy
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable, Dict, List, Optional

import producer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMFY_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
WORKFLOW_PATH = os.getenv("COMFYUI_WORKFLOW", os.path.join(BASE_DIR, "comfy_workflows", "z_image_turbo_api.json"))
WIDTH, HEIGHT = 720, 1280          # 9:16 — 쇼츠 1080×1920 으로 Remotion 이 키운다
IMAGE_TIMEOUT_SECONDS = 600
POLL_SECONDS = 3

# 배너(2026-10-26)와 같은 계열. z-image 는 cfg 1 이라 네거티브 프롬프트가 없어 '글자 없음'을 본문에 넣는다
INK_STYLE = ("dark traditional Chinese ink wash painting, cinematic composition, ancient China in the Warring States period, "
             "muted black and charcoal tones with warm gold light and a faint crimson sky, misty atmosphere, "
             "no text, no letters, no calligraphy, no watermark")


class ComfyUnavailable(RuntimeError):
    """ComfyUI 에 연결할 수 없을 때."""


def _post_json(url: str, body: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get_json(url: str, timeout: int = 30) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _get_bytes(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def comfy_available(base_url: str = COMFY_URL, timeout: float = 2.0) -> bool:
    try:
        _get_json(f"{base_url}/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


_FLOW_LEAD = re.compile(r"^\s*hyperrealistic\s+8k\s+cinematic\s+(footage|photograph|still)\s+of\s+", re.I)


def scene_prompt(scene: dict, style: str = INK_STYLE) -> str:
    """기획서 씬 → ComfyUI 프롬프트. Flow 용 prompt_en 의 'Audio:'·괄호 안내·--플래그·앞머리를 걷어내고 스타일을 붙인다."""
    base = (scene.get("prompt_en") or scene.get("visual_description_en") or scene.get("visual_description_ko")
            or scene.get("visual_prompt") or scene.get("narration") or "")
    base = re.split(r"\bAudio\s*:", base, maxsplit=1)[0]
    base = re.sub(r"--\w+.*$", "", base, flags=re.S)
    base = re.sub(r"\([^)]*\)", "", base)
    base = _FLOW_LEAD.sub("", base)
    base = re.sub(r"\s+", " ", base).strip().rstrip(".,;: ")
    return f"{base}, {style}" if base else style


def seed_for(plan_id: str, slot: str) -> int:
    """같은 기획서·씬이면 같은 그림 — 다시 돌려도 결과가 바뀌지 않게."""
    return int(hashlib.sha256(f"{plan_id}:{slot}".encode()).hexdigest()[:8], 16)


def _workflow(prompt: str, seed: int, prefix: str) -> dict:
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        wf = copy.deepcopy(json.load(f))
    for node in wf.values():
        t, inputs = node.get("class_type"), node.setdefault("inputs", {})
        if t == "CLIPTextEncode":
            inputs["text"] = prompt
        elif t == "EmptySD3LatentImage":
            inputs.update(width=WIDTH, height=HEIGHT, batch_size=1)
        elif t == "KSampler":
            inputs["seed"] = seed
        elif t == "SaveImage":
            inputs["filename_prefix"] = prefix
    return wf


def _run_one(prompt: str, seed: int, prefix: str, base_url: str) -> bytes:
    pid = _post_json(f"{base_url}/prompt", {"prompt": _workflow(prompt, seed, prefix), "client_id": str(uuid.uuid4())})["prompt_id"]
    t0 = time.time()
    while True:
        entry = (_get_json(f"{base_url}/history/{pid}") or {}).get(pid)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI 실행 오류 ({pid})")
            images = [i for o in (entry.get("outputs") or {}).values() for i in o.get("images", []) if i.get("type", "output") == "output"]
            if images:
                q = urllib.parse.urlencode({"filename": images[0]["filename"], "subfolder": images[0].get("subfolder", ""), "type": "output"})
                return _get_bytes(f"{base_url}/view?{q}")
        if time.time() - t0 > IMAGE_TIMEOUT_SECONDS:
            raise TimeoutError(f"ComfyUI 이미지가 {IMAGE_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다 ({pid})")
        time.sleep(POLL_SECONDS)


def generate_images(plan: dict, slots: Optional[List[str]] = None, progress: Optional[Callable] = None,
                    style: str = INK_STYLE, base_url: str = COMFY_URL) -> Dict[str, list]:
    """기획서 씬 이미지를 ComfyUI 로 만든다. 썸네일 슬롯은 만들지 않는다(쇼츠는 커스텀 썸네일 미사용)."""
    if not comfy_available(base_url):
        raise ComfyUnavailable(f"ComfyUI 에 연결할 수 없습니다({base_url}). ComfyUI 를 켠 뒤 다시 빌드하세요 — Gemini 로 넘어가지 않습니다.")
    plan_id = plan["plan_id"]
    scenes = {str(s.get("scene_num")): s for s in plan.get("structured_scenes") or []}
    targets = [str(s) for s in (slots or list(scenes)) if str(s) != "thumbnail"]
    d = producer.render_dir(plan_id)
    done, errors = [], []
    for n, slot in enumerate(targets, 1):
        if progress:
            progress("images", f"ComfyUI 이미지 {n}/{len(targets)} — 씬 {slot}", int(5 + 90 * (n - 1) / max(1, len(targets))))
        sc = scenes.get(slot)
        if not sc:
            errors.append({"slot": slot, "error": "기획서에 없는 씬"})
            continue
        prompt = scene_prompt(sc, style)
        try:
            data = _run_one(prompt, seed_for(plan_id, slot), f"shiji_{plan_id}_{slot}", base_url)
        except Exception as e:
            errors.append({"slot": slot, "error": f"{type(e).__name__}: {e}"})
            continue
        fname = f"scene_{int(slot):02d}.png"
        with open(os.path.join(d, fname), "wb") as f:
            f.write(data)
        idx = producer.list_media(plan_id)
        idx[slot] = {"file": fname, "type": "image", "source": "comfyui", "prompt": prompt}
        producer._save_index(plan_id, idx)
        done.append(slot)
    if progress:
        progress("images", f"ComfyUI 이미지 {len(done)}장 완료", 100)
    return {"generated": done, "errors": errors}
