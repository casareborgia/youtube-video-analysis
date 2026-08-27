# 로컬 LLM 백엔드 자동 감지 클라이언트 — LM Studio(1234) / Ollama(11434) 겸용
# 우선순위: LM Studio → Ollama. 환경변수 TUBEINSIGHT_LLM_BACKEND=ollama|lmstudio 로 강제 가능.
import os
import json
import time
import urllib.request
import urllib.error

LMSTUDIO_URL = "http://127.0.0.1:1234"
OLLAMA_URL = "http://127.0.0.1:11434"

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

_cache = {"ts": 0.0, "backend": None}  # 감지 결과 10초 캐시 (다단계 LLM 호출 시 중복 감지 방지)


def _load_preference():
    try:
        return json.load(open(SETTINGS_FILE, encoding="utf-8")).get("llm_backend", "auto")
    except Exception:
        return "auto"


_preference = _load_preference()  # "auto" | "lmstudio" | "ollama" — 사용자가 UI에서 선택


def get_preference():
    return _preference


def set_preference(pref):
    """사용자가 선택한 백엔드를 저장합니다 (재시작 후에도 유지)."""
    global _preference
    if pref not in ("auto", "lmstudio", "ollama"):
        raise ValueError("backend는 auto / lmstudio / ollama 중 하나여야 합니다.")
    _preference = pref
    try:
        json.dump({"llm_backend": pref}, open(SETTINGS_FILE, "w", encoding="utf-8"))
    except Exception:
        pass
    _cache["backend"] = None
    _cache["ts"] = 0.0
    return pref


def _get_json(url, timeout=1.5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def detect_backend(force=None):
    """
    실행 중인 로컬 LLM 백엔드를 감지합니다.
    반환: {"name": "LM Studio"|"Ollama", "base": url, "model": str|None, "port": int} 또는 None
    - LM Studio: 로드된 모델 id 사용 (없으면 "local")
    - Ollama: 설치된 첫 모델 사용 (없으면 model=None — 호출 시 안내 에러)
    우선순위: force 인자 > 환경변수 > 사용자 선택(settings.json) > 자동(LM Studio 우선)
    """
    force = (force
             or os.environ.get("TUBEINSIGHT_LLM_BACKEND", "").lower()
             or (None if _preference == "auto" else _preference))

    now = time.time()
    if force is None and _cache["backend"] is not None and now - _cache["ts"] < 10:
        return _cache["backend"]

    backend = None

    if force in (None, "lmstudio"):
        try:
            data = _get_json(LMSTUDIO_URL + "/v1/models")
            models = data.get("data") or []
            model = models[0].get("id") if models else None
            backend = {"name": "LM Studio", "base": LMSTUDIO_URL, "model": model or "local", "port": 1234}
        except Exception:
            backend = None

    if backend is None and force in (None, "ollama"):
        try:
            data = _get_json(OLLAMA_URL + "/api/tags")
            models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
            backend = {"name": "Ollama", "base": OLLAMA_URL, "model": models[0] if models else None, "port": 11434}
        except Exception:
            backend = None

    if force is None:
        _cache["backend"] = backend
        _cache["ts"] = now
    return backend


def probe_all():
    """
    두 백엔드의 실행 상태를 각각 확인합니다 (상단 상태 표시용).
    반환: {"lmstudio": {"online", "model"}, "ollama": {"online", "model"}}
    """
    lms = {"online": False, "model": None}
    try:
        data = _get_json(LMSTUDIO_URL + "/v1/models")
        models = data.get("data") or []
        lms = {"online": True, "model": models[0].get("id") if models else None}
    except Exception:
        pass

    oll = {"online": False, "model": None}
    try:
        data = _get_json(OLLAMA_URL + "/api/tags")
        models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
        oll = {"online": True, "model": models[0] if models else None}
    except Exception:
        pass

    return {"lmstudio": lms, "ollama": oll}


def call_llm(messages, max_tokens=4096, temperature=0.7, max_continues=3):
    """
    감지된 백엔드의 OpenAI 호환 API(/v1/chat/completions)로 대화를 요청합니다.
    응답이 길이 제한으로 끊기면 자동으로 이어쓰기(최대 max_continues회).
    """
    backend = detect_backend()
    if backend is None:
        if _preference != "auto":
            name = "LM Studio" if _preference == "lmstudio" else "Ollama"
            raise RuntimeError(
                f"선택한 {name}이(가) 꺼져 있습니다. {name}을(를) 실행하거나, "
                "상단의 백엔드 배지를 다시 클릭해 자동 모드로 전환해주세요."
            )
        raise RuntimeError(
            "로컬 AI를 찾을 수 없습니다. LM Studio(포트 1234) 또는 Ollama(포트 11434)를 실행해주세요."
        )
    if not backend.get("model"):
        raise RuntimeError(
            "Ollama가 실행 중이지만 설치된 모델이 없습니다. "
            "터미널에서 'ollama pull gemma3' 등으로 모델을 먼저 받아주세요."
        )

    full_content = ""
    history = list(messages)

    for _ in range(max_continues):
        req = urllib.request.Request(
            backend["base"] + "/v1/chat/completions",
            data=json.dumps({
                "model": backend["model"],
                "messages": history,
                "max_tokens": max_tokens,
                "temperature": temperature
            }).encode(),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as response:
                res_json = json.load(response)
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"로컬 AI({backend['name']}) 연결이 끊겼습니다. 서버 상태를 확인하고 다시 시도해주세요."
            ) from e

        choice = res_json["choices"][0]
        piece = choice["message"].get("content", "")
        finish_reason = choice.get("finish_reason")

        full_content += piece
        if finish_reason != "length" or not piece.strip():
            break

        history.append({"role": "assistant", "content": piece})
        history.append({"role": "user", "content": "이전 답변이 중간에 끊겼습니다. 끊긴 부분부터 이어서 계속 작성해주세요."})

    return full_content
