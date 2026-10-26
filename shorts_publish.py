"""쇼츠 유튜브 발행 — S-3 파일럿 범위 (작업계획서_ShijiFiles_파일럿3편 4장 P-5, 작업계획서_쇼츠_자동화 S-3).

- 채널은 꼭 정해서 올린다: 인자 → SHORTS_YOUTUBE_CHANNEL_ID(.env). 활성 채널로 몰래 대체하지 않고, 루나 채널이면 거부한다.
- shorts_engine.publish_allowed(QC 통과 + 렌더 후 리뷰 P0 없음)를 반드시 거친다.
- 언제나 비공개로 먼저 올린다(예약이면 private + publishAt). 공개는 사람이 확인한 뒤 set_youtube_privacy 로.
- AI 합성 표시(containsSyntheticMedia)를 켜고, 아동용이 아님으로 올린다.
- 이번 범위 밖: 인스타 export 번들, LLM 메타데이터 — 제목은 사람이 정하고 설명은 템플릿.
- 원문 댓글(원문 한 줄 + 직역 + 출전): 비공개 영상에는 댓글을 달 수 없어(403) 업로드 때는 잡에 대기로 두고 공개 전환 때 등록한다.
  고정은 API 로 할 수 없다 — Studio 에서 한 번 누른다.
"""

import os
import time
from typing import Callable, Optional

import kanripo_db
import luna_engine
import shorts_engine
import uploader

SHIJI_PACK = "shorts_shiji"
SHIJI_HASHTAGS = "#history #ancientchina #shorts"
SHIJI_TAGS = ["Shorts", "ancient china", "chinese history", "shiji", "history stories"]
LANG_CODE = {"english": "en", "korean": "ko"}


class PublishRefused(RuntimeError):
    """발행 조건을 만족하지 않아 업로드하지 않았을 때(채널 가드·발행 잠금·중복 업로드)."""


def default_channel_id() -> str:
    return (os.getenv("SHORTS_YOUTUBE_CHANNEL_ID") or "").strip()


def _sources(job: dict) -> list:
    """원문 인장 씬의 출전(중복 제거, 순서 유지)."""
    out = []
    for s in (job.get("storyboard") or {}).get("scenes") or []:
        src = str(s.get("source") or "").strip()
        if (s.get("kind") or "image") == "seal" and src and src not in out:
            out.append(src)
    return out


def build_youtube_metadata(job: dict, title: Optional[str] = None, description: Optional[str] = None) -> dict:
    """업로드 메타데이터. Shiji 팩이면 설명 끝에 출전·칸리포 출처·번역 표기·해시태그를 붙인다."""
    yt = (job.get("metadata") or {}).get("youtube") or {}
    lang = LANG_CODE.get(job.get("narration_language") or job.get("language") or "korean", "ko")
    shiji = job.get("concept_key") == SHIJI_PACK
    lead = (description if description is not None else yt.get("description") or (job.get("storyboard") or {}).get("hook_text") or "").strip()
    parts = [lead] if lead else []
    srcs = _sources(job)
    if srcs:
        parts.append("\n".join(f"📜 Source: {s}" for s in srcs))
    if shiji or srcs:
        parts.append(f"{kanripo_db.CREDIT}\nTranslation: Shiji Files")
    if shiji:
        parts.append(SHIJI_HASHTAGS)
    tags = list(dict.fromkeys((yt.get("tags") or []) + (SHIJI_TAGS if shiji else [])))
    return {
        "title": (title or yt.get("title") or job.get("topic") or "Shorts").strip()[:100],
        "description": "\n\n".join(parts)[:5000],
        "tags": tags[:30],
        "category_id": "27",
        "default_language": lang,
        "audio_language": lang,
    }


def original_text_comment(job: dict) -> str:
    """원문 댓글 문구. 기획서에 적은 댓글이 있으면 그것, 없으면 원문 인장마다 '출전: 원문 / "직역"' + 칸리포 출처."""
    custom = str(((job.get("metadata") or {}).get("youtube") or {}).get("pinned_comment") or "").strip()
    if custom:
        return custom[:9000]
    lines, seen = [], set()
    for s in (job.get("storyboard") or {}).get("scenes") or []:
        if (s.get("kind") or "image") != "seal" or not s.get("hanzi") or s["hanzi"] in seen:
            continue
        seen.add(s["hanzi"])
        head = f"Original text, {s['source']}: {s['hanzi']}" if s.get("source") else f"Original text: {s['hanzi']}"
        lines.append(head + (f'\n"{s["translation"]}"' if s.get("translation") else ""))
    if not lines:
        return ""
    return "\n\n".join(lines + [f"From the {kanripo_db.CREDIT.replace('Original text: ', '')}."])


def _post_comment(job: dict, text: str) -> dict:
    """원문 댓글 등록 — 실패해도 공개 상태는 되돌리지 않고 경고만 남긴다."""
    pub = job["publish"]["youtube"]
    try:
        uploader.post_comment(pub["video_id"], text, channel_id=pub.get("channel_id"))
        pub.update(comment_posted=True, comment_text=text, comment_pending=None,
                   studio_comment_url=f"https://studio.youtube.com/video/{pub['video_id']}/comments")
    except Exception as e:
        pub["comment_posted"] = False
        pub.setdefault("warnings", []).append(f"원문 댓글 등록 실패: {str(e)[:160]}")
    return job


def post_original_comment(job: dict) -> dict:
    """이미 공개된 영상에 원문 댓글을 단다(이 기능 전에 공개한 편, 또는 공개 전환 때 실패한 편)."""
    pub = (job.get("publish") or {}).get("youtube") or {}
    if not pub.get("video_id"):
        raise PublishRefused("아직 업로드하지 않은 잡입니다.")
    if pub.get("privacy") != "public":
        raise PublishRefused("공개 영상에만 댓글을 달 수 있습니다 — 먼저 공개로 바꾸세요.")
    if pub.get("comment_posted"):
        raise PublishRefused("원문 댓글을 이미 달았습니다.")
    text = pub.get("comment_pending") or original_text_comment(job)
    if not text:
        raise PublishRefused("달 원문 댓글이 없습니다(원문 인장 씬이 없음).")
    _post_comment(job, text)
    shorts_engine.save_job(job)
    return job


def _guard_channel(channel_id: Optional[str]) -> str:
    cid = (channel_id or default_channel_id()).strip()
    if not cid:
        raise PublishRefused("발행할 채널이 없습니다 — channel_id 를 주거나 .env 의 SHORTS_YOUTUBE_CHANNEL_ID 를 설정하세요.")
    if cid == luna_engine.LUNA_CHANNEL_ID:
        raise PublishRefused("루나 채널로는 쇼츠를 발행하지 않습니다 — 쇼츠 채널을 지정하세요.")
    return cid


def publish_youtube(job: dict, channel_id: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None,
                    publish_at: Optional[str] = None, playlist_id: Optional[str] = None, progress: Optional[Callable] = None) -> dict:
    """비공개(또는 예약) 업로드 → job["publish"]["youtube"] 기록·저장. 조건이 안 맞으면 PublishRefused."""
    cid = _guard_channel(channel_id)
    ok, why = shorts_engine.publish_allowed(job)
    if not ok:
        raise PublishRefused(f"발행 잠금: {why}")
    pub = job.setdefault("publish", {}).setdefault("youtube", {})
    if pub.get("video_id"):
        raise PublishRefused(f"이미 업로드한 잡입니다(video_id {pub['video_id']}) — 다시 올리지 않습니다.")
    video = (job.get("render") or {}).get("file")
    if not video or not os.path.exists(video):
        raise PublishRefused("렌더 결과 파일이 없습니다.")
    meta = build_youtube_metadata(job, title=title, description=description)
    res = uploader.upload_video(
        video_path=video, title=meta["title"], description=meta["description"], tags=meta["tags"],
        privacy="private", publish_at=publish_at, category_id=meta["category_id"], made_for_kids=False,
        channel_id=cid, playlist_id=playlist_id, pinned_comment=None, progress=progress,
        default_language=meta["default_language"], audio_language=meta["audio_language"], contains_synthetic_media=True,
    )
    pub.update({"video_id": res.get("video_id"), "url": res.get("url"), "channel_id": cid, "privacy": "private",
                "publish_at": publish_at, "title": meta["title"], "uploaded_at": time.time(), "warnings": res.get("warnings") or [],
                "comment_pending": original_text_comment(job) or None, "comment_posted": False})
    shorts_engine.save_job(job)
    return job


def set_youtube_privacy(job: dict, privacy: str) -> dict:
    """업로드한 쇼츠의 공개 범위를 바꾼다(사람이 Studio·시트로 확인한 뒤)."""
    if privacy not in uploader.PRIVACY:
        raise ValueError(f"공개 범위는 {', '.join(uploader.PRIVACY)} 중 하나입니다: {privacy}")
    pub = (job.get("publish") or {}).get("youtube") or {}
    if not pub.get("video_id"):
        raise PublishRefused("아직 업로드하지 않은 잡입니다.")
    res = uploader.set_video_privacy(pub["video_id"], privacy, channel_id=pub.get("channel_id"))
    pub["privacy"] = res.get("privacy") or privacy
    if pub["privacy"] == "public":
        pub["publish_at"] = None
        if pub.get("comment_pending") and not pub.get("comment_posted"):
            _post_comment(job, pub["comment_pending"])
    shorts_engine.save_job(job)
    return job
