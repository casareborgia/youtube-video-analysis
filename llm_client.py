"""
로컬 LLM 백엔드 자동 감지 & 하이브리드 클라이언트
LM Studio(1234) / Ollama(11434) 겸용
- 우선순위: 사용자 설정 > LM Studio > Ollama
- 토큰 길이 초과(finish_reason == 'length') 시 자동 이어쓰기(Auto-continue) 지원
"""

import os
import json
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

import os
import json
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

LMSTUDIO_URL = "http://127.0.0.1:1234"
OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"

_cache = {"ts": 0.0, "backend": None}
_selected_model: str | None = None


def _load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_settings(data: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save settings: {e}")


def _load_preference() -> str:
    try:
        return _load_settings().get("llm_backend", "gemini")
    except Exception:
        pass
    return "gemini"


_preference = _load_preference()


def _load_selected_model() -> str | None:
    try:
        return _load_settings().get("selected_model", None)
    except Exception:
        return None


_selected_model = _load_selected_model()


def get_preference() -> str:
    global _preference
    return _preference


def set_preference(pref: str) -> str:
    """사용자가 선택한 백엔드를 저장합니다 (재시작 후에도 유지)."""
    global _preference
    if pref not in ("gemini", "auto", "lmstudio", "ollama"):
        raise ValueError("backend는 gemini / auto / lmstudio / ollama 중 하나여야 합니다.")
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


def get_selected_model() -> str | None:
    """현재 사용자가 선택한 모델명을 반환합니다."""
    global _selected_model
    return _selected_model


def set_selected_model(model: str | None) -> str | None:
    """사용자가 선택한 특정 모델을 저장합니다 (재시작 후에도 유지)."""
    global _selected_model
    _selected_model = model
    try:
        data = {}
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        if model:
            data["selected_model"] = model
        else:
            data.pop("selected_model", None)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Settings Error] {e}")
    _cache["backend"] = None
    _cache["ts"] = 0.0
    return model


def _get_json(url: str, timeout: float = 1.5):
    req = urllib.request.Request(url, headers={"User-Agent": "TubeInsight/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _is_chat_model(model_name: str) -> bool:
    """TTS, 오디오, 임베딩 모델을 제외하고 순수 텍스트/챗 모델인지 검사"""
    m = model_name.lower()
    for bad in ("tts", "voice", "embed", "bge", "rerank", "whisper", "audioldm"):
        if bad in m:
            return False
    return True


def detect_backend(force: str = None):
    """
    실행 중인 LLM 백엔드를 감지합니다.
    Gemini(클라우드) > LM Studio > Ollama 순서 또는 사용자 설정에 따름.
    """
    global _preference
    force = (
        force
        or os.environ.get("TUBEINSIGHT_LLM_BACKEND", "").lower()
        or (None if _preference in ("auto", "gemini") else _preference)
    )

    # 1. Gemini 클라우드 백엔드 체크 (force in None or gemini)
    if force in (None, "gemini"):
        try:
            import producer
            key = producer.gemini_key()
            if key:
                return {
                    "name": "Google Gemini",
                    "backend_type": "gemini",
                    "base": "https://generativelanguage.googleapis.com",
                    "model": DEFAULT_GEMINI_MODEL,
                    "port": 443,
                }
        except Exception:
            pass

    now = time.time()
    if force is None and _cache["backend"] is not None and (now - _cache["ts"] < 8):
        return _cache["backend"]

    backend = None

    # 2. LM Studio 체크 (force in None or lmstudio)
    if force in (None, "lmstudio"):
        try:
            data = _get_json(LMSTUDIO_URL + "/v1/models")
            all_models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            # TTS/임베딩 모델 제외하고 챗 모델 우선 필터링
            chat_models = [m for m in all_models if _is_chat_model(m)]
            selected = chat_models[0] if chat_models else (all_models[0] if all_models else None)
            if selected:
                backend = {
                    "name": "LM Studio",
                    "backend_type": "lmstudio",
                    "base": LMSTUDIO_URL,
                    "model": selected,
                    "port": 1234,
                }
        except Exception:
            backend = None

    # 3. Ollama 체크 (force in None or ollama)
    if backend is None and force in (None, "ollama"):
        try:
            data = _get_json(OLLAMA_URL + "/api/tags")
            all_models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
            chat_models = [m for m in all_models if _is_chat_model(m)]
            selected = chat_models[0] if chat_models else (all_models[0] if all_models else None)
            backend = {
                "name": "Ollama",
                "backend_type": "ollama",
                "base": OLLAMA_URL,
                "model": selected,
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
    백엔드의 실행 상태를 각각 확인합니다 (상단 상태 배지용).
    반환: {"gemini": {"online": bool, "model": str, "models": list},
            "lmstudio": {"online": bool, "model": str, "models": list},
            "ollama": {"online": bool, "model": str, "models": list}}
    """
    gem = {"online": False, "model": None, "models": [DEFAULT_GEMINI_MODEL, "gemini-2.5-flash", "gemini-1.5-pro"]}
    try:
        import producer
        if producer.gemini_key():
            gem = {
                "online": True,
                "model": DEFAULT_GEMINI_MODEL,
                "models": [DEFAULT_GEMINI_MODEL, "gemini-2.5-flash", "gemini-1.5-pro"],
            }
    except Exception:
        pass

    lms = {"online": False, "model": None, "models": []}
    try:
        data = _get_json(LMSTUDIO_URL + "/v1/models", timeout=1.2)
        raw_list = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        chat_list = [m for m in raw_list if _is_chat_model(m)]
        model_list = chat_list if chat_list else raw_list
        lms = {
            "online": True,
            "model": model_list[0] if model_list else "서버 켜짐 (모델 미선택)",
            "models": model_list,
        }
    except Exception:
        pass

    oll = {"online": False, "model": None, "models": []}
    try:
        data = _get_json(OLLAMA_URL + "/api/tags", timeout=1.2)
        raw_list = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
        chat_list = [m for m in raw_list if _is_chat_model(m)]
        model_list = chat_list if chat_list else raw_list
        oll = {
            "online": True,
            "model": model_list[0] if model_list else "모델 설치 필요",
            "models": model_list,
        }
    except Exception:
        pass

    return {"gemini": gem, "lmstudio": lms, "ollama": oll}


def get_active_backend(force=None):
    return detect_backend(force=force)


def call_gemini(
    messages: list,
    model: str = DEFAULT_GEMINI_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> str:
    """Google Gemini 3.6 Flash 클라우드 엔진을 호출합니다."""
    import producer
    client = producer.get_genai_client()

    system_text = ""
    user_parts = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            system_text += content + "\n"
        elif role == "user":
            user_parts.append(content)
        elif role == "assistant":
            user_parts.append(f"[Assistant]: {content}")

    combined_prompt = "\n\n".join(user_parts)
    if not combined_prompt and system_text:
        combined_prompt = system_text
        system_text = ""

    config = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if system_text:
        config["system_instruction"] = system_text.strip()
    if json_mode:
        config["response_mime_type"] = "application/json"

    try:
        resp = client.models.generate_content(
            model=model,
            contents=combined_prompt,
            config=config,
        )
        return resp.text or ""
    except Exception as e:
        if json_mode:
            config.pop("response_mime_type", None)
            resp = client.models.generate_content(
                model=model,
                contents=combined_prompt,
                config=config,
            )
            return resp.text or ""
        raise e


def call_llm(
    messages: list,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    max_continues: int = 2,
    json_mode: bool = False,
) -> str:
    """
    사용 가능한 LLM(Google Gemini 또는 로컬 LM Studio/Ollama)으로 메시지를 전송합니다.
    """
    backend = detect_backend()

    # 1. Gemini 클라우드 백엔드 처리
    if backend and backend.get("backend_type") == "gemini":
        model_name = _selected_model or backend.get("model") or DEFAULT_GEMINI_MODEL
        try:
            return call_gemini(
                messages,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as ge:
            print(f"[LLM Client] Gemini 호출 실패 -> 로컬 AI fallback 시도: {ge}")
            # 로컬 백엔드가 있으면 대체
            local_be = detect_backend(force="lmstudio") or detect_backend(force="ollama")
            if local_be:
                backend = local_be
            else:
                raise

    if backend is None:
        if _preference not in ("auto", "gemini"):
            name = "LM Studio" if _preference == "lmstudio" else "Ollama"
            raise RuntimeError(
                f"선택한 {name}이(가) 꺼져 있습니다. {name}을(를) 실행하거나, "
                "상단의 백엔드 배지를 다시 클릭해 자동(Auto) 모드로 전환해주세요."
            )
        raise RuntimeError(
            "사용 가능한 AI를 찾을 수 없습니다. Gemini API 키를 등록하거나 LM Studio/Ollama를 실행해주세요."
        )

    if not backend.get("model"):
        raise RuntimeError(
            "Ollama가 실행 중이지만 설치된 모델이 없습니다. "
            "터미널에서 'ollama run gemma4' 등으로 모델을 먼저 설치해주세요."
        )

    full_content = ""
    history = list(messages)

    # 사용자가 특정 모델을 선택했으면 그 모델을 우선 사용
    active_model = _selected_model or backend["model"]

    for step in range(max_continues):
        payload = {
            "model": active_model,
            "messages": history,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # LM Studio 는 response_format 으로 'json_schema' 또는 'text' 만 허용하며
        # {"type": "json_object"} 를 보내면 HTTP 400 으로 거절한다.
        # 이 경우 헤더를 생략하고 프롬프트 지시 + extract_json() 파싱에 의존한다.
        if json_mode and backend["backend_type"] != "lmstudio":
            payload["response_format"] = {"type": "json_object"}

        # Ollama /v1 호환 엔드포인트 또는 LM Studio /v1/chat/completions
        endpoint_url = backend["base"] + "/v1/chat/completions"

        def _post(body: dict):
            r = urllib.request.Request(
                endpoint_url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "TubeInsight/2.0"},
            )
            with urllib.request.urlopen(r, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            try:
                res_json = _post(payload)
            except urllib.error.HTTPError as he:
                # response_format 을 지원하지 않는 서버면 해당 필드만 빼고 한 번 재시도
                if he.code == 400 and "response_format" in payload:
                    retry_payload = {k: v for k, v in payload.items() if k != "response_format"}
                    res_json = _post(retry_payload)
                else:
                    raise
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
    """마크다운 ```json ... ``` 코드블록에서 첫 블록의 내용만 꺼냅니다."""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    return m.group(1) if m else text


def _drop_fence_markers(text: str) -> str:
    """코드펜스 마커만 제거해 본문을 이어붙입니다.

    토큰 길이 초과로 이어쓰기가 발생하면 하나의 JSON이 여러 코드블록으로
    쪼개져 돌아옵니다. 이때 _strip_fences()는 비탐욕 매칭이라 첫 조각만
    잡아 JSON이 잘리므로, 마커만 걷어내고 전체를 한 덩어리로 다룹니다.
    """
    return re.sub(r"```(?:json)?", "", text)


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


def _escape_ctrl_in_strings(s: str) -> str:
    """JSON 문자열 값 안의 이스케이프되지 않은 개행/탭을 \\n, \\t 로 바꿉니다.

    LLM 이 마크다운 장문을 문자열 값에 넣을 때 실제 개행 문자를 그대로 출력하는
    경우가 잦은데, JSON 명세상 문자열 안의 제어문자는 반드시 이스케이프되어야 하므로
    'Invalid control character' 로 파싱이 실패한다. 구조(문자열 밖) 공백은 그대로 둔다.
    """
    out = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            elif ch == "\\":
                out.append(ch)
                esc = True
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def _repair_json(s: str) -> str:
    """끝 쉼표·제어문자 제거 후, 잘린 응답이면 열린 문자열/괄호를 올바른 순서로 닫습니다."""
    s = _escape_ctrl_in_strings(s)
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
    # 펜스 처리 방식을 달리한 여러 후보를 순서대로 시도한다.
    # (첫 블록만 / 마커만 제거한 전체 / 원문) — 이어쓰기로 쪼개진 응답까지 복원하기 위함.
    for base in (_strip_fences(text), _drop_fence_markers(text), text):
        span = _balanced_json_span(base)
        if span and span not in candidates:
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
