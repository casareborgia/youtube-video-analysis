# 로컬 LLM 클라이언트 — LM Studio(1234) / Ollama(11434) 자동 감지
# 우선순위: 인자 force > 환경변수 TUBEINSIGHT_LLM_BACKEND > 사용자 선택(data/settings.json) > 자동(LM Studio 우선)
import os
import re
import json
import time
import threading
import urllib.request
import urllib.error

LMSTUDIO_URL = "http://127.0.0.1:1234"
OLLAMA_URL = "http://127.0.0.1:11434"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Ollama는 기본 컨텍스트가 4096 토큰이라 긴 자막·다단계 대화가 조용히 잘립니다. 넉넉히 잡아 줍니다.
OLLAMA_NUM_CTX = int(os.environ.get("TUBEINSIGHT_NUM_CTX", "16384"))
REQUEST_TIMEOUT = 900  # 초 — 느린 로컬 모델 대비

_lock = threading.Lock()
_cache = {"ts": 0.0, "backend": None}  # 감지 결과 10초 캐시 (다단계 호출 시 중복 감지 방지)


def _load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


_preference = _load_settings().get("llm_backend", "auto")  # auto | lmstudio | ollama


def get_preference():
    return _preference


def get_model_pref(key):
    return _load_settings().get(f"{key}_model") or None


def set_model(key, model):
    """백엔드별 사용할 모델을 저장합니다 (해당 모델이 목록에 없으면 첫 모델 사용)."""
    if key not in ("lmstudio", "ollama"):
        raise ValueError("backend는 lmstudio / ollama 중 하나여야 합니다.")
    s = _load_settings()
    if model:
        s[f"{key}_model"] = model
    else:
        s.pop(f"{key}_model", None)
    _save_settings(s)
    with _lock:
        _cache["backend"] = None
        _cache["ts"] = 0.0
    return model


def _pick_model(key, models):
    pref = get_model_pref(key)
    if pref and pref in models:
        return pref
    return models[0] if models else None


def set_preference(pref):
    """사용자가 선택한 백엔드를 저장합니다 (재시작 후에도 유지)."""
    global _preference
    if pref not in ("auto", "lmstudio", "ollama"):
        raise ValueError("backend는 auto / lmstudio / ollama 중 하나여야 합니다.")
    _preference = pref
    try:
        s = _load_settings()
        s["llm_backend"] = pref
        _save_settings(s)
    except Exception:
        pass
    with _lock:
        _cache["backend"] = None
        _cache["ts"] = 0.0
    return pref


def _get_json(url, timeout=1.5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _post_json(url, payload, timeout=REQUEST_TIMEOUT):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _probe_lmstudio():
    data = _get_json(LMSTUDIO_URL + "/v1/models")
    models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
    return {"online": True, "model": models[0] if models else None, "models": models}


def _probe_ollama():
    data = _get_json(OLLAMA_URL + "/api/tags")
    models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
    return {"online": True, "model": models[0] if models else None, "models": models}


def probe_all():
    """두 백엔드의 실행 상태를 각각 확인합니다 (상단 상태 표시용)."""
    result = {}
    for key, fn in (("lmstudio", _probe_lmstudio), ("ollama", _probe_ollama)):
        try:
            result[key] = fn()
        except Exception:
            result[key] = {"online": False, "model": None, "models": []}
    return result


def _effective_force(force=None):
    return (force
            or os.environ.get("TUBEINSIGHT_LLM_BACKEND", "").lower()
            or (None if _preference == "auto" else _preference))


def detect_backend(force=None):
    """
    실행 중인 로컬 LLM 백엔드를 감지합니다.
    반환: {"key": "lmstudio"|"ollama", "name": str, "base": url, "model": str|None} 또는 None
    """
    force = _effective_force(force)
    now = time.time()
    with _lock:
        if force is None and _cache["backend"] is not None and now - _cache["ts"] < 10:
            return _cache["backend"]

    backend = None
    if force in (None, "lmstudio"):
        try:
            p = _probe_lmstudio()
            backend = {"key": "lmstudio", "name": "LM Studio", "base": LMSTUDIO_URL, "model": _pick_model("lmstudio", p["models"]) or "local"}
        except Exception:
            backend = None
    if backend is None and force in (None, "ollama"):
        try:
            p = _probe_ollama()
            backend = {"key": "ollama", "name": "Ollama", "base": OLLAMA_URL, "model": _pick_model("ollama", p["models"])}
        except Exception:
            backend = None

    if force is None:
        with _lock:
            _cache["backend"] = backend
            _cache["ts"] = now
    return backend


def active_backend_status():
    """상태 API용: 실제로 사용될 백엔드와 각 백엔드의 상태."""
    probes = probe_all()
    force = _effective_force()
    active = None
    if force in ("lmstudio", "ollama"):
        active = force if probes[force]["online"] else None
    elif probes["lmstudio"]["online"]:
        active = "lmstudio"
    elif probes["ollama"]["online"]:
        active = "ollama"
    names = {"lmstudio": "LM Studio", "ollama": "Ollama"}
    return {
        "online": active is not None and bool(probes[active]["model"]),
        "active": active,
        "backend": names.get(active),
        "model": _pick_model(active, probes[active]["models"]) if active else None,
        "preference": _preference,
        "backends": probes,
    }


def _offline_error():
    if _preference != "auto":
        name = "LM Studio" if _preference == "lmstudio" else "Ollama"
        return RuntimeError(
            f"선택한 {name}이(가) 꺼져 있습니다. {name}을(를) 실행하거나, "
            "상단의 백엔드 배지를 다시 클릭해 자동 모드로 전환해주세요."
        )
    return RuntimeError("로컬 AI를 찾을 수 없습니다. LM Studio(포트 1234) 또는 Ollama(포트 11434)를 실행해주세요.")


def _call_once(backend, messages, max_tokens, temperature, json_mode):
    """한 번의 채팅 요청. (content, finish_reason) 반환."""
    if backend["key"] == "ollama":
        payload = {
            "model": backend["model"],
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": OLLAMA_NUM_CTX, "num_predict": max_tokens, "temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        res = _post_json(backend["base"] + "/api/chat", payload)
        content = (res.get("message") or {}).get("content", "")
        finish = res.get("done_reason") or "stop"
        return content, finish

    payload = {
        "model": backend["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    res = _post_json(backend["base"] + "/v1/chat/completions", payload)
    choice = res["choices"][0]
    return choice["message"].get("content", ""), choice.get("finish_reason") or "stop"


def call_llm(messages, max_tokens=4096, temperature=0.7, max_continues=3, json_mode=False):
    """
    감지된 백엔드로 대화를 요청합니다.
    - Ollama: /api/chat (num_ctx 확장, JSON 모드 지원)
    - LM Studio: OpenAI 호환 /v1/chat/completions
    응답이 길이 제한으로 끊기면 자동으로 이어쓰기(최대 max_continues회).
    """
    backend = detect_backend()
    if backend is None:
        raise _offline_error()
    if not backend.get("model"):
        raise RuntimeError(
            "Ollama가 실행 중이지만 설치된 모델이 없습니다. "
            "터미널에서 'ollama pull gemma3' 등으로 모델을 먼저 받아주세요."
        )

    history = list(messages)
    full_content = ""
    for _ in range(max_continues):
        try:
            piece, finish = _call_once(backend, history, max_tokens, temperature, json_mode)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")[:300]
            except Exception:
                pass
            raise RuntimeError(f"로컬 AI({backend['name']})가 요청을 거부했습니다 (HTTP {e.code}). {body}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(
                f"로컬 AI({backend['name']}) 연결이 끊겼거나 응답이 너무 늦습니다. 서버 상태를 확인하고 다시 시도해주세요."
            ) from e

        full_content += piece
        if finish != "length" or not piece.strip():
            break
        history.append({"role": "assistant", "content": piece})
        history.append({"role": "user", "content": "이전 답변이 중간에 끊겼습니다. 끊긴 부분부터 이어서 계속 작성해주세요."})

    return full_content


# ── JSON 응답 파싱 유틸 ───────────────────────────────────────────────

def _strip_fences(text):
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    return m.group(1) if m else text


def _balanced_json_span(text):
    """첫 { 또는 [ 부터 짝이 맞는 지점까지 잘라냅니다 (앞뒤 잡담 제거)."""
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None
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
    return text[start:]  # 끊긴 경우: 있는 만큼


def extract_json(text):
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


def _repair_json(s):
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


def call_llm_json(messages, max_tokens=4096, temperature=0.5, max_continues=2):
    """JSON 응답을 요구하고 파싱까지 마친 결과를 반환합니다. 파싱 실패 시 (None, raw_text)."""
    raw = call_llm(messages, max_tokens=max_tokens, temperature=temperature, max_continues=max_continues, json_mode=True)
    return extract_json(raw), raw
