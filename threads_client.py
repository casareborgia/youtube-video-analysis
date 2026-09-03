"""
Meta Threads 공식 API 클라이언트 모듈
- 2단계 게시 프로토콜 (Media Container Creation -> Publish)
- 5개 타래 순차 연쇄 발행 (Sequential Reply Chaining via reply_to_id)
- User Access Token 직접 입력 및 OAuth 2.0 인증 지원
- 장기 토큰(Long-Lived Access Token, 60일 유효) 교환 및 자동 저장
"""

import os
import time
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, List, Dict, Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "threads_config.json"

THREADS_API_BASE = "https://graph.threads.net/v1.0"
THREADS_OAUTH_AUTH_URL = "https://threads.net/oauth/authorize"
THREADS_OAUTH_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
THREADS_LONG_TOKEN_URL = "https://graph.threads.net/access_token"


def _http_request(url: str, method: str = "GET", params: dict = None, data: dict = None, headers: dict = None) -> dict:
    """urllib 기반의 안정적인 경량 HTTP 요청 유틸"""
    req_headers = {"User-Agent": "TubeInsight-ThreadsClient/1.0"}
    if headers:
        req_headers.update(headers)

    full_url = url
    if params:
        query_str = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        sep = "&" if "?" in full_url else "?"
        full_url = f"{full_url}{sep}{query_str}"

    req_data = None
    if data is not None:
        req_data = urllib.parse.urlencode({k: v for k, v in data.items() if v is not None}).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(full_url, data=req_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            err_json = json.loads(error_body)
            error_msg = err_json.get("error", {}).get("message", error_body)
        except Exception:
            error_msg = error_body
        raise RuntimeError(f"Threads API Error ({e.code}): {error_msg}")
    except Exception as e:
        raise RuntimeError(f"Threads Request Failed: {e}")


def load_config() -> dict:
    """설정 파일 및 환경변수로부터 Threads 자격증명 로드"""
    conf = {
        "access_token": os.environ.get("THREADS_ACCESS_TOKEN", "").strip(),
        "user_id": os.environ.get("THREADS_USER_ID", "").strip(),
        "app_id": os.environ.get("THREADS_APP_ID", "").strip(),
        "app_secret": os.environ.get("THREADS_APP_SECRET", "").strip(),
        "redirect_uri": os.environ.get("THREADS_REDIRECT_URI", "http://127.0.0.1:8765/api/threads/auth/callback").strip(),
        "username": "",
        "profile_pic": "",
        "token_expires_at": 0
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                conf.update({k: v for k, v in saved.items() if v})
        except Exception:
            pass
    return conf


def save_config(updates: dict):
    """자격증명을 data/threads_config.json에 저장하고 os.environ 동기화"""
    current = load_config()
    current.update(updates)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save threads_config: {e}")

    # 환경변수 동기화
    if current.get("access_token"):
        os.environ["THREADS_ACCESS_TOKEN"] = current["access_token"]
    if current.get("user_id"):
        os.environ["THREADS_USER_ID"] = current["user_id"]
    if current.get("app_id"):
        os.environ["THREADS_APP_ID"] = current["app_id"]
    if current.get("app_secret"):
        os.environ["THREADS_APP_SECRET"] = current["app_secret"]


def get_status() -> dict:
    """현재 Threads 계정 연동 상태 및 프로필 정보 조회"""
    conf = load_config()
    token = conf.get("access_token")
    user_id = conf.get("user_id")
    has_app_creds = bool(conf.get("app_id") and conf.get("app_secret"))

    if not token:
        return {
            "connected": False,
            "mode": "unconfigured",
            "has_app_creds": has_app_creds,
            "user_id": None,
            "username": None,
            "message": "Threads API 토큰 또는 App ID가 등록되지 않았습니다."
        }

    # 토큰 유효성 및 계정 정보 확인
    try:
        user_info = _http_request(
            f"{THREADS_API_BASE}/me",
            params={
                "fields": "id,username,name,threads_profile_picture_url,threads_biography",
                "access_token": token
            }
        )
        real_uid = user_info.get("id", user_id)
        username = user_info.get("username", "")
        profile_pic = user_info.get("threads_profile_picture_url", "")

        # 설정에 캐싱 업데이트
        save_config({
            "user_id": real_uid,
            "username": username,
            "profile_pic": profile_pic
        })

        masked_token = (token[:6] + "..." + token[-4:]) if len(token) > 10 else "***"
        return {
            "connected": True,
            "mode": "live",
            "has_app_creds": has_app_creds,
            "user_id": real_uid,
            "username": username,
            "profile_pic": profile_pic,
            "masked_token": masked_token,
            "message": f"@{username} 계정에 성공적으로 연결되었습니다."
        }
    except Exception as e:
        return {
            "connected": False,
            "mode": "invalid_token",
            "has_app_creds": has_app_creds,
            "user_id": user_id,
            "username": conf.get("username"),
            "message": f"토큰 인증 실패: {e}"
        }


# ── 1. 컨테이너 생성 및 단일 발행 (2-Step Publishing) ───────────────────────

def create_media_container(text: str, reply_to_id: Optional[str] = None, image_url: Optional[str] = None) -> str:
    """
    [1단계] 미디어 컨테이너 생성
    - text: 본문 텍스트 (최대 500자)
    - reply_to_id: 이전 게시물 ID (타래 연결 시 사용)
    - image_url: 첨부 이미지 URL (선택)
    반환: creation_id (문자열)
    """
    conf = load_config()
    token = conf.get("access_token")
    user_id = conf.get("user_id")

    if not token or not user_id:
        raise ValueError("Threads Access Token과 User ID가 설정되지 않았습니다.")

    payload = {
        "access_token": token,
        "text": text
    }

    if image_url:
        payload["media_type"] = "IMAGE"
        payload["image_url"] = image_url
    else:
        payload["media_type"] = "TEXT"

    if reply_to_id:
        payload["reply_to_id"] = str(reply_to_id).strip()

    url = f"{THREADS_API_BASE}/{user_id}/threads"
    res = _http_request(url, method="POST", data=payload)
    creation_id = res.get("id")
    if not creation_id:
        raise RuntimeError(f"컨테이너 생성 응답에 id가 없습니다: {res}")
    return creation_id


def publish_media_container(creation_id: str) -> str:
    """
    [2단계] 생성된 미디어 컨테이너 최종 발행
    반환: 실제 발행된 threads media_id
    """
    conf = load_config()
    token = conf.get("access_token")
    user_id = conf.get("user_id")

    if not token or not user_id:
        raise ValueError("Threads Access Token과 User ID가 필요합니다.")

    url = f"{THREADS_API_BASE}/{user_id}/threads_publish"
    payload = {
        "access_token": token,
        "creation_id": creation_id
    }

    res = _http_request(url, method="POST", data=payload)
    media_id = res.get("id")
    if not media_id:
        raise RuntimeError(f"발행 응답에 id가 없습니다: {res}")
    return media_id


def publish_single_post(text: str, reply_to_id: Optional[str] = None, image_url: Optional[str] = None) -> Dict[str, Any]:
    """1단계 컨테이너 생성 + 2단계 최종 발행 원스톱 실행"""
    creation_id = create_media_container(text=text, reply_to_id=reply_to_id, image_url=image_url)
    if image_url:
        time.sleep(2)
    else:
        time.sleep(1)

    media_id = publish_media_container(creation_id)
    conf = load_config()
    username = conf.get("username", "")
    post_url = f"https://www.threads.net/@{username}/post/{media_id}" if username else f"https://www.threads.net/post/{media_id}"

    return {
        "media_id": media_id,
        "creation_id": creation_id,
        "post_url": post_url,
        "reply_to_id": reply_to_id
    }


# ── 2. 5개 바이럴 타래 순차 연쇄 발행 (Sequential Thread Chaining) ──────────

def publish_thread_sequence(posts: List[str], delay_seconds: float = 2.0, progress_cb=None) -> Dict[str, Any]:
    """
    여러 개의 글(기본 5개 타래)을 reply_to_id로 엮어 연속 타래로 순차 발행합니다.
    - posts[0]: 메인 훅 포스트
    - posts[1..n]: 이전 포스트에 대한 답글(Reply)로 연쇄 연결
    """
    if not posts:
        raise ValueError("발행할 타래 내용이 비어 있습니다.")

    status = get_status()
    if not status.get("connected"):
        raise RuntimeError(f"Threads API가 연결되어 있지 않습니다: {status.get('message')}")

    results = []
    parent_media_id = None
    first_post_url = None

    total = len(posts)
    for idx, post_text in enumerate(posts):
        clean_text = str(post_text).strip()
        if not clean_text:
            continue

        step_num = idx + 1
        if progress_cb:
            progress_cb(int((step_num / total) * 90), f"타래 {step_num}/{total} 발행 중...")

        # 1번 글은 단독 포스트, 2번 글부터는 직전 글의 reply_to_id 전달
        pub_res = publish_single_post(text=clean_text, reply_to_id=parent_media_id)
        current_media_id = pub_res["media_id"]
        
        if idx == 0:
            first_post_url = pub_res["post_url"]

        results.append({
            "step": step_num,
            "media_id": current_media_id,
            "reply_to_id": parent_media_id,
            "post_url": pub_res["post_url"],
            "snippet": clean_text[:60] + ("..." if len(clean_text) > 60 else "")
        })

        parent_media_id = current_media_id

        if idx < total - 1 and delay_seconds > 0:
            time.sleep(delay_seconds)

    if progress_cb:
        progress_cb(100, "전체 스레드 타래 연쇄 발행 완료!")

    return {
        "status": "success",
        "total_published": len(results),
        "root_media_id": results[0]["media_id"] if results else None,
        "thread_url": first_post_url,
        "items": results
    }


# ── 3. OAuth 2.0 및 토큰 교환 ───────────────────────────────────────────

def get_oauth_authorization_url() -> str:
    """OAuth 2.0 웹 인증 시작 URL 생성"""
    conf = load_config()
    app_id = conf.get("app_id")
    redirect_uri = conf.get("redirect_uri")

    if not app_id:
        raise ValueError("THREADS_APP_ID가 설정되지 않았습니다.")

    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": "threads_basic,threads_content_publish,threads_read_replies",
        "response_type": "code"
    }
    return f"{THREADS_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"


def handle_oauth_callback(code: str) -> dict:
    """웹 콜백에서 수신한 code로 단기 토큰 발급 후 60일 장기 토큰으로 교환"""
    conf = load_config()
    app_id = conf.get("app_id")
    app_secret = conf.get("app_secret")
    redirect_uri = conf.get("redirect_uri")

    if not app_id or not app_secret:
        raise ValueError("THREADS_APP_ID와 THREADS_APP_SECRET가 필요합니다.")

    # 1. 단기 토큰 발급
    token_res = _http_request(
        THREADS_OAUTH_TOKEN_URL,
        method="POST",
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code
        }
    )
    short_token = token_res.get("access_token")
    user_id = str(token_res.get("user_id", ""))

    if not short_token:
        raise RuntimeError(f"단기 토큰 발급 실패: {token_res}")

    # 2. 60일 장기 토큰 교환
    try:
        long_res = _http_request(
            THREADS_LONG_TOKEN_URL,
            params={
                "grant_type": "th_exchange_token",
                "client_secret": app_secret,
                "access_token": short_token
            }
        )
        final_token = long_res.get("access_token", short_token)
        expires_in = long_res.get("expires_in", 5184000)
    except Exception as e:
        print(f"Warning: 장기 토큰 교환 실패(단기 토큰 사용): {e}")
        final_token = short_token
        expires_in = 3600

    save_config({
        "access_token": final_token,
        "user_id": user_id,
        "token_expires_at": int(time.time()) + int(expires_in)
    })

    return get_status()


def disconnect():
    """Threads 계정 연동 해제 및 저장된 토큰 제거"""
    save_config({
        "access_token": "",
        "user_id": "",
        "username": "",
        "profile_pic": "",
        "token_expires_at": 0
    })
    return {"status": "success", "message": "Threads 계정 연결이 해제되었습니다."}
