"""
로컬 LLM 백엔드 자동 감지 & 하이브리드 클라이언트
LM Studio(1234) / Ollama(11434) 겸용
- 우선순위: 사용자 설정 > LM Studio > Ollama
- 토큰 길이 초과(finish_reason == 'length') 시 자동 이어쓰기(Auto-continue) 지원
"""

import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

LMSTUDIO_URL = "http://127.0.0.1:1234"
OLLAMA_URL = "http://127.0.0.1:11434"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"

_cache = {"ts": 0.0, "backend": None}


def _load_preference() -> str:
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("llm_backend", "auto")
    except Exception:
        pass
    return "auto"


_preference = _load_preference()


def get_preference() -> str:
    global _preference
    return _preference


def set_preference(pref: str) -> str:
    """사용자가 선택한 백엔드를 저장합니다 (재시작 후에도 유지)."""
    global _preference
    if pref not in ("auto", "lmstudio", "ollama"):
        raise ValueError("backend는 auto / lmstudio / ollama 중 하나여야 합니다.")
    _preference = pref
    try:
        data = {}
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["llm_backend"] = pref
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Settings Error] {e}")
    _cache["backend"] = None
    _cache["ts"] = 0.0
    return pref


def _get_json(url: str, timeout: float = 1.5):
    req = urllib.request.Request(url, headers={"User-Agent": "TubeInsight/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def detect_backend(force: str = None):
    """
    실행 중인 로컬 LLM 백엔드를 감지합니다.
    반환: {"name": "LM Studio"|"Ollama", "base": url, "model": str|None, "port": int} 또는 None
    """
    global _preference
    force = (
        force
        or os.environ.get("TUBEINSIGHT_LLM_BACKEND", "").lower()
        or (None if _preference == "auto" else _preference)
    )

    now = time.time()
    if force is None and _cache["backend"] is not None and (now - _cache["ts"] < 8):
        return _cache["backend"]

    backend = None

    # 1. LM Studio 체크 (force in None or lmstudio)
    if force in (None, "lmstudio"):
        try:
            data = _get_json(LMSTUDIO_URL + "/v1/models")
            models = data.get("data") or []
            model = models[0].get("id") if models else None
            backend = {
                "name": "LM Studio",
                "backend_type": "lmstudio",
                "base": LMSTUDIO_URL,
                "model": model or "local",
                "port": 1234,
            }
        except Exception:
            backend = None

    # 2. Ollama 체크 (force in None or ollama)
    if backend is None and force in (None, "ollama"):
        try:
            data = _get_json(OLLAMA_URL + "/api/tags")
            models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
            backend = {
                "name": "Ollama",
                "backend_type": "ollama",
                "base": OLLAMA_URL,
                "model": models[0] if models else None,
                "port": 11434,
            }
        except Exception:
            backend = None

    if force is None:
        _cache["backend"] = backend
        _cache["ts"] = now

    return backend


def probe_all():
    """
    두 백엔드의 실행 상태를 각각 확인합니다 (상단 상태 배지용).
    반환: {"lmstudio": {"online": bool, "model": str}, "ollama": {"online": bool, "model": str}}
    """
    lms = {"online": False, "model": None}
    try:
        data = _get_json(LMSTUDIO_URL + "/v1/models", timeout=1.2)
        models = data.get("data") or []
        lms = {"online": True, "model": models[0].get("id") if models else "서버 켜짐 (모델 미선택)"}
    except Exception:
        pass

    oll = {"online": False, "model": None}
    try:
        data = _get_json(OLLAMA_URL + "/api/tags", timeout=1.2)
        models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
        oll = {"online": True, "model": models[0] if models else "모델 설치 필요"}
    except Exception:
        pass

    return {"lmstudio": lms, "ollama": oll}


def get_active_backend(force=None):
    return detect_backend(force=force)


def call_llm(
    messages: list,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    max_continues: int = 2,
    json_mode: bool = False,
) -> str:
    """
    사용 가능한 로컬 LLM(LM Studio 또는 Ollama)으로 메시지를 전송합니다.
    - finish_reason == 'length' 시 자동으로 이어쓰기를 수행합니다.
    """
    backend = detect_backend()

    if backend is None:
        if _preference != "auto":
            name = "LM Studio" if _preference == "lmstudio" else "Ollama"
            raise RuntimeError(
                f"선택한 {name}이(가) 꺼져 있습니다. {name}을(를) 실행하거나, "
                "상단의 백엔드 배지를 다시 클릭해 자동(Auto) 모드로 전환해주세요."
            )
        raise RuntimeError(
            "로컬 AI를 찾을 수 없습니다. LM Studio(포트 1234) 또는 Ollama(포트 11434)를 실행해주세요."
        )

    if not backend.get("model"):
        raise RuntimeError(
            "Ollama가 실행 중이지만 설치된 모델이 없습니다. "
            "터미널에서 'ollama run gemma4' 등으로 모델을 먼저 설치해주세요."
        )

    full_content = ""
    history = list(messages)

    for step in range(max_continues):
        payload = {
            "model": backend["model"],
            "messages": history,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        # Ollama /v1 호환 엔드포인트 또는 LM Studio /v1/chat/completions
        endpoint_url = backend["base"] + "/v1/chat/completions"
        req = urllib.request.Request(
            endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "TubeInsight/2.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                res_json = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as e:
            # Ollama native API fallback
            if backend["backend_type"] == "ollama":
                try:
                    native_payload = {
                        "model": backend["model"],
                        "messages": history,
                        "options": {"num_predict": max_tokens, "temperature": temperature, "num_ctx": 16384},
                        "stream": False,
                    }
                    if json_mode:
                        native_payload["format"] = "json"
                    n_req = urllib.request.Request(
                        backend["base"] + "/api/chat",
                        data=json.dumps(native_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(n_req, timeout=300) as n_res:
                        n_json = json.loads(n_res.read().decode("utf-8"))
                        piece = n_json.get("message", {}).get("content", "")
                        full_content += piece
                        break
                except Exception as inner_e:
                    raise RuntimeError(f"Ollama 호출 실패: {inner_e}") from inner_e
            raise RuntimeError(f"로컬 AI({backend['name']}) 연결 오류: {e}") from e

        choice = res_json["choices"][0]
        piece = choice["message"].get("content", "")
        finish_reason = choice.get("finish_reason")

        full_content += piece
        if finish_reason != "length" or not piece.strip():
            break

        history.append({"role": "assistant", "content": piece})
        history.append({
            "role": "user",
            "content": "이전 답변이 토큰 길이 제한으로 중간에 끊겼습니다. 바로 직전에 끊긴 부분부터 자연스럽게 이어서 계속 작성해주세요.",
        })

    return full_content.strip()


def _strip_fences(text: str) -> str:
    """마크다운 ```json ... ``` 코드블록 태그 제거"""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    return m.group(1) if m else text


def _balanced_json_span(text: str) -> str:
    """첫 { 또는 [ 부터 짝이 맞는 지점까지 잘라냅니다 (앞뒤 불필요한 텍스트 제거)."""
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return ""
    stack = []
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:
                return text[start:i + 1]
    return text[start:]


def _repair_json(s: str) -> str:
    """끝 쉼표·제어문자 제거 후, 잘린 응답이면 열린 문자열/괄호를 올바른 순서로 닫습니다."""
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    stack = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_str:
        s += '"'
    s = re.sub(r",\s*$", "", s)
    s = re.sub(r':\s*$', ': null', s)
    return s + "".join(reversed(stack))


def extract_json(text: str):
    """LLM 응답에서 JSON 객체/배열을 최대한 복원해 반환합니다. 실패 시 None."""
    if not text:
        return None
    candidates = [text.strip(), _strip_fences(text).strip()]
    span = _balanced_json_span(_strip_fences(text))
    if span:
        candidates.append(span)
    for cand in candidates:
        for fixer in (lambda s: s, _repair_json):
            try:
                return json.loads(fixer(cand))
            except Exception:
                continue
    return None


def call_llm_json(messages: list, max_tokens: int = 4096, temperature: float = 0.5, max_continues: int = 2):
    """JSON 응답을 요구하고 파싱까지 마친 결과를 반환합니다. 파싱 실패 시 (None, raw_text)."""
    raw = call_llm(messages, max_tokens=max_tokens, temperature=temperature, max_continues=max_continues, json_mode=True)
    return extract_json(raw), raw
