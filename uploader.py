# YouTube 업로드 — YouTube Data API v3 (OAuth 2.0, 사용자 본인 계정)
# 준비: Google Cloud Console에서 프로젝트 생성 → YouTube Data API v3 사용 설정 → OAuth 클라이언트(데스크톱 앱) 생성
#       → 내려받은 JSON을 data/youtube/client_secret.json 으로 저장
import os
import json
import time
import importlib.util

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YT_DIR = os.path.join(BASE_DIR, "data", "youtube")
CLIENT_SECRET = os.path.join(YT_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(YT_DIR, "token.json")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]
PRIVACY = ("private", "unlisted", "public")
os.makedirs(YT_DIR, exist_ok=True)


def libs_available():
    return all(importlib.util.find_spec(m) is not None for m in ("googleapiclient", "google_auth_oauthlib", "google.oauth2"))


def _creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not os.path.exists(TOKEN_FILE):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        except Exception:
            return None
    return creds if creds and creds.valid else None


def _service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def status():
    st = {"libs": libs_available(), "client_secret": os.path.exists(CLIENT_SECRET), "authorized": False, "channel": None, "error": None}
    if not st["libs"]:
        st["error"] = "pip3 install google-api-python-client google-auth-oauthlib"
        return st
    try:
        creds = _creds()
        if creds:
            st["authorized"] = True
            cached = _channel_cache()
            st["channel"] = cached or fetch_channel(creds)
    except Exception as e:
        st["error"] = str(e)[:200]
    return st


def _channel_cache():
    try:
        with open(os.path.join(YT_DIR, "channel.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def fetch_channel(creds=None):
    creds = creds or _creds()
    if not creds:
        return None
    res = _service(creds).channels().list(part="snippet,statistics", mine=True).execute()
    items = res.get("items") or []
    if not items:
        return None
    it = items[0]
    info = {
        "id": it["id"],
        "title": it["snippet"]["title"],
        "thumbnail": ((it["snippet"].get("thumbnails") or {}).get("default") or {}).get("url"),
        "subscribers": (it.get("statistics") or {}).get("subscriberCount"),
    }
    with open(os.path.join(YT_DIR, "channel.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False)
    return info


def authorize(progress=None):
    """브라우저를 열어 구글 로그인 → 토큰 저장. (로컬 콜백 서버 사용)"""
    if not libs_available():
        raise RuntimeError("구글 API 패키지가 없습니다. 터미널에서 'pip3 install google-api-python-client google-auth-oauthlib'를 실행해주세요.")
    if not os.path.exists(CLIENT_SECRET):
        raise RuntimeError("data/youtube/client_secret.json 파일이 없습니다. Google Cloud Console에서 OAuth 클라이언트(데스크톱 앱) JSON을 받아 저장해주세요.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    if progress:
        progress("auth", "브라우저에서 구글 계정 로그인과 권한 허용을 진행해주세요...", 30)
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  success_message="TubeInsight 연결이 완료되었습니다. 이 창을 닫아도 됩니다.")
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    if progress:
        progress("auth", "채널 정보 확인 중...", 80)
    return {"authorized": True, "channel": fetch_channel(creds)}


def disconnect():
    for p in (TOKEN_FILE, os.path.join(YT_DIR, "channel.json")):
        try:
            os.remove(p)
        except Exception:
            pass


def update_channel_branding(description=None, keywords=None, default_language=None):
    """
    YouTube Data API channels.update 를 사용하여 채널 설명란 및 키워드를 등록합니다.
    """
    creds = _creds()
    if not creds:
        raise RuntimeError("유튜브 계정이 연결되어 있지 않습니다. 먼저 유튜브 계정을 연결해주세요.")
    
    youtube = _service(creds)
    # 현재 채널 ID 조회
    ch_info = fetch_channel(creds)
    if not ch_info or not ch_info.get("id"):
        raise RuntimeError("연결된 채널 ID를 찾을 수 없습니다.")
    
    channel_id = ch_info["id"]

    # 키워드 포맷팅: 공백이 있는 단어는 큰따옴표로 감싸기
    if isinstance(keywords, list):
        kw_parts = []
        for k in keywords:
            k = str(k).strip()
            if " " in k and not (k.startswith('"') and k.endswith('"')):
                kw_parts.append(f'"{k}"')
            else:
                kw_parts.append(k)
        kw_str = " ".join(kw_parts)
    else:
        kw_str = str(keywords or "")

    body = {
        "id": channel_id,
        "brandingSettings": {
            "channel": {}
        }
    }
    if description:
        body["brandingSettings"]["channel"]["description"] = description[:1000]
    if kw_str:
        body["brandingSettings"]["channel"]["keywords"] = kw_str[:500]
    if default_language:
        body["brandingSettings"]["channel"]["defaultLanguage"] = default_language

    try:
        res = youtube.channels().update(part="brandingSettings", body=body).execute()
        return {"status": "success", "channel_id": channel_id, "updated": res.get("brandingSettings")}
    except Exception as e:
        from googleapiclient.errors import HttpError
        detail = str(e)
        if isinstance(e, HttpError):
            try:
                detail = json.loads(e.content.decode("utf-8"))["error"]["message"]
            except Exception:
                pass
        raise RuntimeError(f"채널 브랜딩 업데이트 실패: {detail}") from e


def upload_video(video_path, title, description, tags=None, privacy="private", publish_at=None,
                 thumbnail_path=None, category_id="27", made_for_kids=False, progress=None):
    """
    재개 가능(resumable) 업로드. publish_at(ISO 8601, 예: 2026-09-01T09:00:00+09:00)을 주면 예약 공개(privacy=private 필수).
    반환: {"video_id", "url", "thumbnail_set", "warnings"}
    """
    creds = _creds()
    if not creds:
        raise RuntimeError("유튜브 계정이 연결되어 있지 않습니다. 먼저 '유튜브 연결'을 눌러주세요.")
    if not os.path.exists(video_path):
        raise RuntimeError("업로드할 영상 파일이 없습니다. 먼저 '영상 만들기'를 실행해주세요.")
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    privacy = privacy if privacy in PRIVACY else "private"
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids)}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    body = {
        "snippet": {
            "title": (title or "제목 없음")[:100],
            "description": (description or "")[:5000],
            "tags": [t.strip()[:30] for t in (tags or []) if t.strip()][:30],
            "categoryId": str(category_id),
            "defaultLanguage": "ko",
        },
        "status": status,
    }
    youtube = _service(creds)
    media = MediaFileUpload(video_path, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retries = 0
    while response is None:
        try:
            st, response = request.next_chunk()
            if st and progress:
                progress("upload", f"업로드 중... {int(st.progress() * 100)}%", int(5 + 85 * st.progress()))
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                time.sleep(2 ** retries)
                continue
            detail = ""
            try:
                detail = json.loads(e.content.decode("utf-8"))["error"]["message"]
            except Exception:
                detail = str(e)[:200]
            raise RuntimeError(f"유튜브 업로드 실패: {detail}") from e

    video_id = response.get("id")
    warnings = []
    thumb_ok = False
    if thumbnail_path and os.path.exists(thumbnail_path):
        if progress:
            progress("upload", "썸네일 설정 중...", 94)
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")).execute()
            thumb_ok = True
        except Exception as e:
            warnings.append(f"썸네일 설정 실패(채널 전화번호 인증이 필요할 수 있습니다): {str(e)[:160]}")
    if privacy != "private" and not publish_at:
        warnings.append("OAuth 앱이 구글 검증을 받기 전에는 업로드된 영상이 비공개로 잠길 수 있습니다. 유튜브 스튜디오에서 공개 상태를 확인하세요.")
    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "thumbnail_set": thumb_ok, "warnings": warnings,
            "privacy": status["privacyStatus"], "publish_at": publish_at}
