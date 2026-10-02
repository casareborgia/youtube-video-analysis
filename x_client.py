"""X (Twitter) API v2 OAuth 2.0 & 공통 계정 어댑터 모듈.

작업지시서 Phase 2 요구사항 충족:
- OAuth 2.0 PKCE (S256) 사용자 인증 플로우 및 콜백 처리
- 필요 권한 범위 (Scopes) 관리 및 연결 상태/만료 조회 API
- 토큰 만료(TOKEN_EXPIRED) 및 권한 부족(INSUFFICIENT_SCOPE) 에러 코드 표준화
- 자격증명 참조 모델(data/x_config.json) 및 SocialStore 연동
- 모든 로그 및 에러 메시지 내 비밀정보 마스킹 (sanitize_sensitive_data)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import social_store
from social_store import sanitize_sensitive_data

# 설정 경로 및 상수
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "x_config.json"

# X (Twitter) OAuth 2.0 엔드포인트
X_OAUTH_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
X_OAUTH_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
X_OAUTH_REVOKE_URL = "https://api.twitter.com/2/oauth2/revoke"
X_USERS_ME_URL = "https://api.twitter.com/2/users/me"

# 기본 필수 권한 범위 (게시 발행, 읽기, 사용자 조회, 토큰 갱신, 스하리 인터랙션)
DEFAULT_SCOPES = [
    "tweet.read",
    "tweet.write",
    "users.read",
    "offline.access",
    "like.read",
    "like.write",
    "follows.read",
    "follows.write",
]

# 에러 코드 정의
ERR_TOKEN_EXPIRED = "TOKEN_EXPIRED"
ERR_INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
ERR_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
ERR_API_ERROR = "API_ERROR"
ERR_CONFIG_MISSING = "CONFIG_MISSING"


class XClientError(Exception):
    """X 클라이언트 기본 예외"""

    def __init__(self, message: str, code: str = ERR_API_ERROR, status_code: int = 400):
        super().__init__(sanitize_sensitive_data(message))
        self.code = code
        self.status_code = status_code


# ==========================================
# PKCE 헬퍼 함수
# ==========================================
def generate_pkce_pair() -> Tuple[str, str]:
    """
    OAuth 2.0 PKCE code_verifier 및 code_challenge(S256) 생성.
    RFC 7636 규격 준수:
    - code_verifier: 64바이트 난수를 URL-safe base64 인코딩 (43~128자)
    - code_challenge: SHA-256 해시를 URL-safe base64로 인코딩하고 패딩('=') 제거
    """
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def generate_state() -> str:
    """CSRF 방지용 랜덤 state 문자열 생성"""
    return secrets.token_urlsafe(32)


# ==========================================
# 설정 로드 및 저장 (보안 및 마스킹)
# ==========================================
def load_config() -> Dict[str, Any]:
    """
    환경 변수 및 data/x_config.json 로드.
    반환된 설정은 자격증명 참조 및 내부 동작용으로 사용됨.
    """
    conf = {
        "client_id": os.environ.get("X_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("X_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.environ.get(
            "X_REDIRECT_URI", "http://127.0.0.1:8765/api/x/auth/callback"
        ).strip(),
        "access_token": os.environ.get("X_ACCESS_TOKEN", "").strip(),
        "refresh_token": os.environ.get("X_REFRESH_TOKEN", "").strip(),
        "token_type": "bearer",
        "token_expires_at": 0,
        "scopes": list(DEFAULT_SCOPES),
        "user_id": os.environ.get("X_USER_ID", "").strip(),
        "username": "",
        "name": "",
        "profile_image_url": "",
    }

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    conf.update({k: v for k, v in saved.items() if v is not None})
        except Exception as e:
            print(f"Warning: Failed to read {CONFIG_FILE}: {sanitize_sensitive_data(str(e))}")

    return conf


def save_config(updates: Dict[str, Any], store: Optional[social_store.SocialStore] = None) -> Dict[str, Any]:
    """
    설정을 data/x_config.json에 저장하고 SocialStore(social_accounts)와 동기화.
    민감정보 로그 노출 방지 및 파일 권한 안전 설정.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conf = load_config()
    conf.update(updates)

    # 1. 파일 저장
    temp_file = CONFIG_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=2)
    temp_file.replace(CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass

    # 2. SocialStore에 계정 메타데이터 동기화 (자격증명 참조만 저장, 토큰 원문 저장 금지)
    if conf.get("user_id"):
        try:
            st = store or social_store.SocialStore()
            st.upsert_account(
                platform="x",
                account_id=str(conf["user_id"]),
                username=conf.get("username", ""),
                display_name=conf.get("name", ""),
                credential_ref="data/x_config.json",
                status="connected" if conf.get("access_token") else "disconnected",
                scopes=conf.get("scopes", DEFAULT_SCOPES),
                token_expires_at=int(conf.get("token_expires_at", 0)),
            )
        except Exception as e:
            print(f"Warning: Failed to sync X account to SocialStore: {sanitize_sensitive_data(str(e))}")

    return conf


# ==========================================
# HTTP 요청 저수준 함수 (모킹 가능)
# ==========================================
def _http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    auth_basic: Optional[Tuple[str, str]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """HTTP 요청 실행 및 JSON 파싱 (에러 메시지 민감정보 자동 마스킹)"""
    req_headers = dict(headers or {})
    req_headers["User-Agent"] = "TubeInsight-XClient/1.0"

    if auth_basic:
        raw = f"{auth_basic[0]}:{auth_basic[1]}".encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        req_headers["Authorization"] = f"Basic {b64}"

    req_data = None
    if data is not None:
        req_data = urllib.parse.urlencode({k: v for k, v in data.items() if v is not None}).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(error_body)
            err_msg = err_json.get("error_description") or err_json.get("error") or err_json.get("detail") or error_body
            err_code = err_json.get("error", "")
        except Exception:
            err_msg = error_body
            err_code = ""

        clean_msg = sanitize_sensitive_data(str(err_msg))

        if e.code == 401 or "expired" in clean_msg.lower() or "invalid_token" in err_code:
            raise XClientError(f"X API 인증 만료/오류 (401): {clean_msg}", code=ERR_TOKEN_EXPIRED, status_code=401)
        elif e.code == 403 or "scope" in clean_msg.lower() or "forbidden" in clean_msg.lower():
            raise XClientError(f"X API 권한 부족 (403): {clean_msg}", code=ERR_INSUFFICIENT_SCOPE, status_code=403)
        else:
            raise XClientError(f"X API 호출 실패 ({e.code}): {clean_msg}", code=ERR_API_ERROR, status_code=e.code)
    except Exception as e:
        raise XClientError(f"X 네트워크 요청 실패: {e}", code=ERR_API_ERROR, status_code=500)


# ==========================================
# OAuth 2.0 PKCE 인증 플로우
# ==========================================
def get_oauth_authorization_url(
    redirect_uri: Optional[str] = None,
    scopes: Optional[List[str]] = None,
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
) -> Dict[str, str]:
    """
    X OAuth 2.0 PKCE 인증 URL 및 state/verifier 반환.
    - state: CSRF 방지용
    - code_verifier: 토큰 발급 시 검증용 (호출자가 세션이나 캐시에 보관)
    """
    conf = load_config()
    client_id = conf.get("client_id")
    if not client_id:
        raise XClientError("X_CLIENT_ID 설정이 필요합니다.", code=ERR_CONFIG_MISSING)

    actual_redirect = (redirect_uri or conf.get("redirect_uri") or "").strip()
    if not actual_redirect:
        raise XClientError("X_REDIRECT_URI 설정이 필요합니다.", code=ERR_CONFIG_MISSING)

    actual_state = state or generate_state()
    verifier, challenge = generate_pkce_pair()
    actual_challenge = code_challenge or challenge

    scope_str = " ".join(scopes or conf.get("scopes") or DEFAULT_SCOPES)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": actual_redirect,
        "scope": scope_str,
        "state": actual_state,
        "code_challenge": actual_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = f"{X_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {
        "url": auth_url,
        "state": actual_state,
        "code_verifier": verifier,
        "code_challenge": actual_challenge,
    }


def handle_oauth_callback(
    code: str,
    code_verifier: str,
    redirect_uri: Optional[str] = None,
    store: Optional[social_store.SocialStore] = None,
) -> Dict[str, Any]:
    """
    콜백에서 수신한 authorization code와 code_verifier로 access token 발급 및 사용자 프로필 동기화.
    """
    conf = load_config()
    client_id = conf.get("client_id")
    client_secret = conf.get("client_secret")
    actual_redirect = (redirect_uri or conf.get("redirect_uri") or "").strip()

    if not client_id:
        raise XClientError("X_CLIENT_ID 설정이 필요합니다.", code=ERR_CONFIG_MISSING)
    if not code:
        raise XClientError("인가 코드(code)가 제공되지 않았습니다.", code=ERR_INVALID_CREDENTIALS)
    if not code_verifier:
        raise XClientError("PKCE code_verifier가 필요합니다.", code=ERR_INVALID_CREDENTIALS)

    # 1. Access Token 발급 요청
    auth_basic = (client_id, client_secret) if client_secret else None
    token_payload: Dict[str, Any] = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": actual_redirect,
        "code_verifier": code_verifier,
    }

    token_res = _http_request(
        X_OAUTH_TOKEN_URL,
        method="POST",
        data=token_payload,
        auth_basic=auth_basic,
    )

    access_token = token_res.get("access_token")
    if not access_token:
        raise XClientError(f"토큰 발급 실패: {token_res}", code=ERR_INVALID_CREDENTIALS)

    refresh_token = token_res.get("refresh_token", "")
    expires_in = int(token_res.get("expires_in", 7200))
    token_type = token_res.get("token_type", "bearer")
    scope_str = token_res.get("scope", "")
    scopes = scope_str.split(" ") if scope_str else list(DEFAULT_SCOPES)
    expires_at = int(time.time()) + expires_in

    # 2. 사용자 정보 조회 (/2/users/me)
    user_info = fetch_current_user(access_token)

    # 3. 설정 및 계정 저장소 동기화
    updates = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_type,
        "token_expires_at": expires_at,
        "scopes": scopes,
        "user_id": user_info.get("id", ""),
        "username": user_info.get("username", ""),
        "name": user_info.get("name", ""),
        "profile_image_url": user_info.get("profile_image_url", ""),
    }
    saved_conf = save_config(updates, store=store)

    return {
        "status": "success",
        "user_id": updates["user_id"],
        "username": updates["username"],
        "name": updates["name"],
        "scopes": scopes,
        "expires_at": expires_at,
    }


def refresh_access_token(
    refresh_token_str: Optional[str] = None,
    store: Optional[social_store.SocialStore] = None,
) -> Dict[str, Any]:
    """
    refresh_token을 사용하여 새로운 access_token 발급.
    """
    conf = load_config()
    client_id = conf.get("client_id")
    client_secret = conf.get("client_secret")
    ref_token = refresh_token_str or conf.get("refresh_token")

    if not client_id:
        raise XClientError("X_CLIENT_ID 설정이 필요합니다.", code=ERR_CONFIG_MISSING)
    if not ref_token:
        raise XClientError("refresh_token이 없습니다. 재로그인이 필요합니다.", code=ERR_TOKEN_EXPIRED, status_code=401)

    auth_basic = (client_id, client_secret) if client_secret else None
    data = {
        "grant_type": "refresh_token",
        "refresh_token": ref_token,
        "client_id": client_id,
    }

    token_res = _http_request(
        X_OAUTH_TOKEN_URL,
        method="POST",
        data=data,
        auth_basic=auth_basic,
    )

    access_token = token_res.get("access_token")
    if not access_token:
        raise XClientError("토큰 갱신 응답에 access_token이 없습니다.", code=ERR_TOKEN_EXPIRED)

    new_refresh = token_res.get("refresh_token", ref_token)
    expires_in = int(token_res.get("expires_in", 7200))
    expires_at = int(time.time()) + expires_in
    scope_str = token_res.get("scope", "")
    scopes = scope_str.split(" ") if scope_str else conf.get("scopes", DEFAULT_SCOPES)

    updates = {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_expires_at": expires_at,
        "scopes": scopes,
    }
    save_config(updates, store=store)

    return {
        "status": "success",
        "expires_at": expires_at,
        "scopes": scopes,
    }


def fetch_current_user(access_token: str) -> Dict[str, Any]:
    """
    X API v2 /2/users/me 호출하여 사용자 정보 확인.
    """
    if not access_token:
        raise XClientError("access_token이 필요합니다.", code=ERR_INVALID_CREDENTIALS)

    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"user.fields": "profile_image_url,description,public_metrics"}
    url = f"{X_USERS_ME_URL}?{urllib.parse.urlencode(params)}"

    res = _http_request(url, method="GET", headers=headers)
    data = res.get("data", {})
    return {
        "id": str(data.get("id", "")),
        "username": str(data.get("username", "")),
        "name": str(data.get("name", "")),
        "profile_image_url": str(data.get("profile_image_url", "")),
    }


# ==========================================
# 계정 연결 상태 및 유효성 검증
# ==========================================
def get_status(store: Optional[social_store.SocialStore] = None) -> Dict[str, Any]:
    """
    현재 X 계정 연결 상태, 스코프, 만료 여부 조회.
    """
    conf = load_config()
    access_token = conf.get("access_token", "")
    user_id = conf.get("user_id", "")
    username = conf.get("username", "")
    expires_at = int(conf.get("token_expires_at", 0))
    scopes = conf.get("scopes", [])

    now = int(time.time())

    # 1. 설정 및 토큰 없음
    if not access_token or not user_id:
        return {
            "platform": "x",
            "connected": False,
            "status": "disconnected",
            "account_id": "",
            "username": "",
            "display_name": "",
            "scopes": [],
            "expires_at": 0,
            "expires_in_seconds": 0,
            "error_code": None,
            "message": "X 계정이 연결되어 있지 않습니다.",
        }

    # 2. 토큰 만료 여부 확인
    is_expired = (expires_at > 0 and expires_at <= now)
    expires_in = max(0, expires_at - now) if expires_at > 0 else 0

    if is_expired:
        return {
            "platform": "x",
            "connected": False,
            "status": "expired",
            "account_id": user_id,
            "username": username,
            "display_name": conf.get("name", ""),
            "scopes": scopes,
            "expires_at": expires_at,
            "expires_in_seconds": 0,
            "error_code": ERR_TOKEN_EXPIRED,
            "message": "X 액세스 토큰이 만료되었습니다. 갱신 또는 재인증이 필요합니다.",
        }

    # 3. 권한 범위 검사
    required_core_scopes = {"tweet.read", "tweet.write"}
    current_scope_set = set(scopes)
    if not required_core_scopes.issubset(current_scope_set):
        return {
            "platform": "x",
            "connected": True,
            "status": "insufficient_scope",
            "account_id": user_id,
            "username": username,
            "display_name": conf.get("name", ""),
            "scopes": scopes,
            "expires_at": expires_at,
            "expires_in_seconds": expires_in,
            "error_code": ERR_INSUFFICIENT_SCOPE,
            "message": f"필수 권한이 부족합니다: {required_core_scopes - current_scope_set}",
        }

    return {
        "platform": "x",
        "connected": True,
        "status": "connected",
        "account_id": user_id,
        "username": username,
        "display_name": conf.get("name", ""),
        "profile_image_url": conf.get("profile_image_url", ""),
        "scopes": scopes,
        "expires_at": expires_at,
        "expires_in_seconds": expires_in,
        "error_code": None,
        "message": "X 계정이 정상 연동되어 있습니다.",
    }


def disconnect(store: Optional[social_store.SocialStore] = None) -> Dict[str, Any]:
    """
    X 계정 연동 해제 및 로컬 자격증명 정리.
    """
    conf = load_config()
    client_id = conf.get("client_id")
    client_secret = conf.get("client_secret")
    access_token = conf.get("access_token")
    user_id = conf.get("user_id")

    # 1. Revoke 토큰 시도 (비동기 최선 노력)
    if access_token and client_id:
        try:
            auth_basic = (client_id, client_secret) if client_secret else None
            _http_request(
                X_OAUTH_REVOKE_URL,
                method="POST",
                data={"token": access_token, "token_type_hint": "access_token", "client_id": client_id},
                auth_basic=auth_basic,
            )
        except Exception:
            pass

    # 2. 로컬 설정 정리
    updates = {
        "access_token": "",
        "refresh_token": "",
        "token_expires_at": 0,
        "user_id": "",
        "username": "",
        "name": "",
        "profile_image_url": "",
    }
    save_config(updates, store=store)

    # 3. SocialStore에서 삭제
    if user_id:
        try:
            st = store or social_store.SocialStore()
            st.delete_account("x", str(user_id))
        except Exception:
            pass

    return {"status": "success", "message": "X 계정 연동이 성공적으로 해제되었습니다."}
