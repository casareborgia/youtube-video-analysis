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

# 다중 채널 저장 구조
#   data/youtube/tokens/<channel_id>.json : 채널별 OAuth 토큰
#   data/youtube/channels.json            : 채널 메타 캐시 {channel_id: {...}}
#   data/youtube/active.json              : 현재 선택된 채널 {"channel_id": "..."}
TOKENS_DIR = os.path.join(YT_DIR, "tokens")
CHANNELS_FILE = os.path.join(YT_DIR, "channels.json")
ACTIVE_FILE = os.path.join(YT_DIR, "active.json")

# 단일 채널 시절의 레거시 경로 (최초 접근 시 1회 자동 이관)
TOKEN_FILE = os.path.join(YT_DIR, "token.json")
LEGACY_CHANNEL_FILE = os.path.join(YT_DIR, "channel.json")

# OAuth 브라우저 동의 대기 상한(초). 초과 시 무한 블로킹 대신 명확한 오류를 던진다.
AUTH_TIMEOUT_SECONDS = int(os.getenv("YOUTUBE_AUTH_TIMEOUT", "180"))

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]
PRIVACY = ("private", "unlisted", "public")
os.makedirs(YT_DIR, exist_ok=True)
os.makedirs(TOKENS_DIR, exist_ok=True)


def libs_available():
    return all(importlib.util.find_spec(m) is not None for m in ("googleapiclient", "google_auth_oauthlib", "google.oauth2"))


# ---------------------------------------------------------------
# 다중 채널 토큰 저장소
# ---------------------------------------------------------------
def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _token_path(channel_id):
    safe = "".join(c for c in str(channel_id) if c.isalnum() or c in "-_")
    if not safe:
        raise RuntimeError("올바르지 않은 채널 ID입니다.")
    return os.path.join(TOKENS_DIR, f"{safe}.json")


def _connected_ids():
    try:
        names = sorted(os.listdir(TOKENS_DIR))
    except Exception:
        return []
    return [n[:-5] for n in names if n.endswith(".json")]


def _channels_meta():
    data = _read_json(CHANNELS_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_channel_meta(info):
    if not info or not info.get("id"):
        return
    meta = _channels_meta()
    meta[info["id"]] = info
    _write_json(CHANNELS_FILE, meta)


def _migrate_legacy():
    """단일 채널(token.json) 구조를 채널별 토큰 구조로 1회 이관한다."""
    if not os.path.exists(TOKEN_FILE):
        return
    try:
        os.makedirs(TOKENS_DIR, exist_ok=True)
        info = _read_json(LEGACY_CHANNEL_FILE) or {}
        cid = info.get("id")
        if not cid:
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            info = _fetch_channel_with(creds) or {}
            cid = info.get("id")
        if not cid:
            return
        with open(TOKEN_FILE, encoding="utf-8") as f:
            raw = f.read()
        with open(_token_path(cid), "w", encoding="utf-8") as f:
            f.write(raw)
        _save_channel_meta(info)
        _write_json(ACTIVE_FILE, {"channel_id": cid})
        os.remove(TOKEN_FILE)
        try:
            os.remove(LEGACY_CHANNEL_FILE)
        except Exception:
            pass
    except Exception:
        # 이관에 실패하면 레거시 파일을 그대로 두어 기존 연결을 잃지 않는다
        pass


def get_active_channel_id():
    _migrate_legacy()
    active = (_read_json(ACTIVE_FILE, {}) or {}).get("channel_id")
    if active and os.path.exists(_token_path(active)):
        return active
    ids = _connected_ids()
    if ids:
        _write_json(ACTIVE_FILE, {"channel_id": ids[0]})
        return ids[0]
    return None


def set_active_channel(channel_id):
    if not os.path.exists(_token_path(channel_id)):
        raise RuntimeError("연결되지 않은 채널입니다. 먼저 해당 채널을 연결해주세요.")
    _write_json(ACTIVE_FILE, {"channel_id": channel_id})
    return channel_id


def list_channels():
    """연결된 모든 채널 목록. active=True 인 것이 현재 선택된 채널."""
    _migrate_legacy()
    active = get_active_channel_id()
    meta = _channels_meta()
    out = []
    for cid in _connected_ids():
        info = dict(meta.get(cid) or {})
        info["id"] = cid
        info.setdefault("title", cid)
        info["active"] = (cid == active)
        out.append(info)
    out.sort(key=lambda c: (not c["active"], str(c.get("title") or "").lower()))
    return out


# ---------------------------------------------------------------
# 인증 / 채널 조회
# ---------------------------------------------------------------
def _creds(channel_id=None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    cid = channel_id or get_active_channel_id()
    if not cid:
        return None
    path = _token_path(cid)
    if not os.path.exists(path):
        return None
    creds = Credentials.from_authorized_user_file(path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(path, "w") as f:
                f.write(creds.to_json())
        except Exception:
            return None
    return creds if creds and creds.valid else None


def _service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _fetch_channel_with(creds):
    if not creds:
        return None
    res = _service(creds).channels().list(part="snippet,statistics", mine=True).execute()
    items = res.get("items") or []
    if not items:
        return None
    it = items[0]
    snip = it.get("snippet") or {}
    return {
        "id": it["id"],
        "title": snip.get("title") or it["id"],
        "thumbnail": ((snip.get("thumbnails") or {}).get("default") or {}).get("url"),
        "subscribers": (it.get("statistics") or {}).get("subscriberCount"),
        "custom_url": snip.get("customUrl") or "",
    }


def _channel_cache(channel_id=None):
    cid = channel_id or get_active_channel_id()
    if not cid:
        return None
    return _channels_meta().get(cid)


def fetch_channel(creds=None):
    creds = creds or _creds()
    info = _fetch_channel_with(creds)
    _save_channel_meta(info)
    return info


def status(channel_id=None):
    st = {
        "libs": libs_available(),
        "client_secret": os.path.exists(CLIENT_SECRET),
        "authorized": False,
        "channel": None,
        "channels": [],
        "active_channel_id": None,
        "error": None,
    }
    if not st["libs"]:
        st["error"] = "pip3 install google-api-python-client google-auth-oauthlib"
        return st
    try:
        st["channels"] = list_channels()
        cid = channel_id or get_active_channel_id()
        st["active_channel_id"] = cid
        creds = _creds(cid) if cid else None
        if creds:
            st["authorized"] = True
            st["channel"] = _channel_cache(cid) or fetch_channel(creds)
    except Exception as e:
        st["error"] = str(e)[:200]
    return st


def authorize(progress=None):
    """브라우저를 열어 구글 로그인 → 선택한 채널의 토큰을 채널별로 저장한다.

    이미 연결된 채널을 다시 인증하면 해당 채널의 토큰만 갱신되고,
    다른 채널의 연결은 그대로 유지된다.
    """
    if not libs_available():
        raise RuntimeError("구글 API 패키지가 없습니다. 터미널에서 'pip3 install google-api-python-client google-auth-oauthlib'를 실행해주세요.")
    if not os.path.exists(CLIENT_SECRET):
        raise RuntimeError("data/youtube/client_secret.json 파일이 없습니다. Google Cloud Console에서 OAuth 클라이언트(데스크톱 앱) JSON을 받아 저장해주세요.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    if progress:
        progress("auth", "브라우저에서 구글 계정 로그인과 권한 허용을 진행해주세요...", 30)
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    try:
        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            prompt="consent",
            timeout_seconds=AUTH_TIMEOUT_SECONDS,
            success_message="TubeInsight 연결이 완료되었습니다. 이 창을 닫아도 됩니다.",
        )
    except Exception as e:
        detail = str(e)[:200] or type(e).__name__
        raise RuntimeError(
            f"브라우저 인증이 완료되지 않았습니다(대기 상한 {AUTH_TIMEOUT_SECONDS}초). "
            f"동의 창을 닫았거나 시간이 초과되었을 수 있습니다. 다시 시도해주세요. 원인: {detail}"
        ) from e
    if not creds:
        raise RuntimeError("인증 정보를 받지 못했습니다. 다시 시도해주세요.")

    if progress:
        progress("auth", "채널 정보 확인 중...", 80)
    info = _fetch_channel_with(creds)
    if not info or not info.get("id"):
        raise RuntimeError("연결된 유튜브 채널을 찾을 수 없습니다. 채널이 있는 계정으로 다시 시도해주세요.")

    with open(_token_path(info["id"]), "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    _save_channel_meta(info)
    set_active_channel(info["id"])
    return {"authorized": True, "channel": info, "channels": list_channels()}


def disconnect(channel_id=None):
    """channel_id를 주면 그 채널만, 생략하면 모든 채널의 연결을 해제한다."""
    _migrate_legacy()
    targets = [channel_id] if channel_id else _connected_ids()
    meta = _channels_meta()
    removed = []
    for cid in targets:
        try:
            os.remove(_token_path(cid))
            removed.append(cid)
        except Exception:
            pass
        meta.pop(cid, None)
    _write_json(CHANNELS_FILE, meta)

    rest = _connected_ids()
    active = (_read_json(ACTIVE_FILE, {}) or {}).get("channel_id")
    if not rest:
        _write_json(ACTIVE_FILE, {})
    elif active not in rest:
        _write_json(ACTIVE_FILE, {"channel_id": rest[0]})

    if not channel_id:
        for p in (TOKEN_FILE, LEGACY_CHANNEL_FILE):
            try:
                os.remove(p)
            except Exception:
                pass

    return {"removed": removed, "channels": list_channels()}


def update_channel_branding(description=None, keywords=None, default_language=None, channel_id=None):
    """
    YouTube Data API channels.update 를 사용하여 채널 설명란 및 키워드를 등록합니다.
    """
    creds = _creds(channel_id)
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
                 thumbnail_path=None, category_id="27", made_for_kids=False, progress=None,
                 channel_id=None, pinned_comment=None):
    """
    재개 가능(resumable) 업로드. publish_at(ISO 8601, 예: 2026-09-01T09:00:00+09:00)을 주면 예약 공개(privacy=private 필수).
    반환: {"video_id", "url", "thumbnail_set", "warnings"}
    """
    creds = _creds(channel_id)
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
    comment_posted = False
    if pinned_comment and str(pinned_comment).strip():
        if progress:
            progress("upload", "댓글 등록 중...", 96)
        try:
            youtube.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {
                            "snippet": {"textOriginal": str(pinned_comment)[:9000]}
                        },
                    }
                },
            ).execute()
            comment_posted = True
            # YouTube Data API v3에는 댓글 고정(pin) 기능이 없다. 등록만 하고 안내를 남긴다.
            warnings.append("댓글은 등록했지만 '고정'은 YouTube Data API가 지원하지 않습니다. 유튜브 스튜디오에서 직접 고정해주세요.")
        except Exception as e:
            warnings.append(f"댓글 등록 실패: {str(e)[:160]}")

    if privacy != "private" and not publish_at:
        warnings.append("OAuth 앱이 구글 검증을 받기 전에는 업로드된 영상이 비공개로 잠길 수 있습니다. 유튜브 스튜디오에서 공개 상태를 확인하세요.")
    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "thumbnail_set": thumb_ok,
            "comment_posted": comment_posted, "warnings": warnings,
            "privacy": status["privacyStatus"], "publish_at": publish_at}
