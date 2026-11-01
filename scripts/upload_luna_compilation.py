#!/usr/bin/env python3
"""
루나의 심야 서재 장르별 롱폼 컴필레이션 유튜브 업로드 스크립트

scripts/create_luna_compilation.py 가 만든 data/luna_compilations/<장르>/youtube_metadata.json 을 읽어
제목·설명(타임라인)·태그·장르 대표 썸네일로 업로드한다. 기본은 계획만 출력(dry-run), --execute 로 실제 업로드.

※ 2026-10-11 로파이 1시간본(HzfRkSiTyeI)은 이 스크립트의 이전 버전으로 data/luna_compilations/ 루트에서 올렸다.
"""

import sys
import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

COMPILATIONS_DIR = BASE_DIR / "data" / "luna_compilations"
CHANNEL_ID = "UCowTfbpKpXDBF3Mc50H4iGQ"
# 채널 정책: 공개 메타데이터에 넣지 않는 기계적 수식어·AI 페르소나 표기
BANNED_WORDS = ("Agent Luna", "에이전트 루나", "에이전트루나", "AgentLuna", "AI음악", "에이전트 레오", "Agent Leo")


def load_plan(genre: str, comp_dir: Path = COMPILATIONS_DIR) -> dict:
    """업로드 계획을 읽고 검증한다. 문제가 있으면 ValueError."""
    out_dir = comp_dir / genre
    meta_file = out_dir / "youtube_metadata.json"
    if not meta_file.exists():
        raise ValueError(f"메타데이터가 없습니다: {meta_file} — 먼저 create_luna_compilation.py --genre {genre} 를 실행하세요.")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    video = Path(meta.get("video_file") or "")
    if not video.is_file():
        raise ValueError(f"영상 파일이 없습니다: {video}")
    public_text = " ".join([meta["youtube_title"], meta["youtube_description"], *meta["youtube_tags"]])
    hits = [w for w in BANNED_WORDS if w.lower() in public_text.lower()]
    if hits:
        raise ValueError(f"공개 메타데이터에 금지 표기가 있습니다: {hits}")
    if len(meta["youtube_title"]) > 100:
        raise ValueError(f"제목이 100자를 넘습니다 ({len(meta['youtube_title'])}자)")
    meta["_result_file"] = str(out_dir / "upload_result.json")
    decision = out_dir / "decision.json"
    meta["_decision"] = json.loads(decision.read_text(encoding="utf-8")) if decision.exists() else None
    return meta


MIN_LEAD = timedelta(minutes=30)  # 예약 공개는 업로드(수 GB)가 끝난 뒤여야 한다


def check_publish_at(publish_at: str, now: datetime = None) -> None:
    """예약 시각이 지금 + 30분 이후인지. 지났거나 너무 가까우면 ValueError."""
    when = datetime.fromisoformat(publish_at)
    if when.tzinfo is None:
        raise ValueError(f"예약 시각에 시간대가 없습니다: {publish_at}")
    now = now or datetime.now(timezone.utc)
    if when <= now + MIN_LEAD:
        raise ValueError(f"예약 시각 {publish_at} 이 지났거나 30분 안입니다. --publish-at 으로 새 시각을 주세요.")


def record_decision_applied(out_dir: Path) -> bool:
    """주간 컴필레이션(decision.json 이 있는 폴더)이면 업로드한 video_id 를 결정 기록에 덧붙인다.
    실패하면 False (업로드는 이미 끝났으므로 다시 올리지 말고 record-applied 로 기록만 다시 한다)."""
    if not (out_dir / "decision.json").exists():
        return True
    try:
        from luna_weekly_compilation import record_applied_for
        res = record_applied_for(out_dir)
        print(f"[✔] 결정 기록에 업로드 반영: {res}")
        return True
    except Exception as e:
        print(f"[!] 결정 기록 반영 실패({e}). 업로드는 됐습니다. 기록만 다시: "
              f"python scripts/luna_weekly_compilation.py record-applied --dir {out_dir.name}")
        return False


def upload_kwargs(meta: dict, privacy: str, publish_at: str = None, playlist_id: str = None) -> dict:
    """uploader.upload_video 에 넘길 인자. Luna 컴필레이션은 AI 생성물이라 메타데이터에 키가 없어도 합성 표시를 켠다."""
    return dict(
        video_path=str(meta["video_file"]),
        title=meta["youtube_title"],
        description=meta["youtube_description"],
        tags=meta["youtube_tags"],
        privacy=privacy,
        publish_at=publish_at,
        thumbnail_path=meta.get("thumbnail_file"),
        category_id="10",
        channel_id=CHANNEL_ID,
        playlist_id=playlist_id,
        contains_synthetic_media=bool(meta.get("contains_synthetic_media", True)),
    )


def main():
    parser = argparse.ArgumentParser(description="루나 장르별 컴필레이션 업로드")
    parser.add_argument("--genre", required=True, help="data/luna_compilations/<genre> (예: piano, ambient)")
    parser.add_argument("--execute", action="store_true", help="실제 업로드 실행 (없으면 계획만 출력)")
    parser.add_argument("--publish-at", default=None, help="예약 공개 일시 ISO 8601 (예: 2026-10-25T22:00:00+09:00). 주면 private+예약")
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"], help="예약이 없을 때 공개 범위 (기본 private)")
    parser.add_argument("--playlist-id", default=None, help="업로드 후 추가할 재생목록 ID")
    parser.add_argument("--force", action="store_true", help="이미 업로드 마커가 있어도 다시 업로드 (중복 영상 주의)")
    args = parser.parse_args()

    try:
        meta = load_plan(args.genre, COMPILATIONS_DIR)
    except ValueError as e:
        print(f"[Error] {e}")
        sys.exit(1)
    result_file = Path(meta["_result_file"])
    # 업로드 완료 마커: 같은 컴필레이션을 두 번 올리는 사고(수 GB 재업로드 + 쿼터 1,600) 방지
    if result_file.exists() and not args.force:
        prev = json.loads(result_file.read_text(encoding="utf-8"))
        print(f"[=] 이미 업로드된 컴필레이션입니다: {prev.get('url')} (publish_at {prev.get('publish_at')})")
        sys.exit(0)
    decision = meta.get("_decision")
    if decision and not args.publish_at and decision.get("publish_at"):
        args.publish_at = decision["publish_at"]  # 주간 컴필레이션: 확정 요청에 적힌 공개 시각
    if args.publish_at:
        try:
            check_publish_at(args.publish_at)
        except ValueError as e:
            print(f"[Error] {e}")
            sys.exit(1)
    if decision and decision.get("status") not in ("awaiting_approval", "uploaded"):
        print(f"[Error] 주간 컴필레이션 렌더가 끝나지 않았습니다 (status={decision.get('status')}).")
        sys.exit(1)

    privacy = "private" if args.publish_at else args.privacy
    video = Path(meta["video_file"])
    print("=" * 65)
    print(f"루나의 심야 서재 {args.genre} 컴필레이션 업로드 계획")
    print("=" * 65)
    print(f"- 영상: {video} ({video.stat().st_size / 1024 ** 3:.2f} GB, {meta['duration_seconds'] / 60:.1f}분)")
    print(f"- 룸 / 썸네일: {meta['room_name']} / {meta.get('thumbnail_file')}")
    print(f"- 공개: {privacy}" + (f" (예약 {args.publish_at})" if args.publish_at else ""))
    print(f"- 재생목록: {args.playlist_id or '없음'} / AI 합성 표시: {'켬' if meta.get('contains_synthetic_media', True) else '끔'}")
    print(f"- 제목: {meta['youtube_title']}")
    print(f"- 태그: {', '.join(meta['youtube_tags'])}")
    print("-" * 65)
    print(meta["youtube_description"])
    print("-" * 65)
    if not args.execute:
        print("[dry-run] 실제 업로드는 --execute 를 붙여 실행하세요.")
        return

    import uploader  # 실제 업로드 때만 (dry-run 은 구글 라이브러리 없이도 돈다)

    def progress_cb(step, msg, pct):
        print(f"[{pct}%] {msg}")

    kw = upload_kwargs(meta, privacy=privacy, publish_at=args.publish_at, playlist_id=args.playlist_id)
    res = uploader.upload_video(progress=progress_cb, **kw)
    result_file.write_text(json.dumps({
        "video_id": res.get("video_id"), "url": res.get("url"), "publish_at": args.publish_at, "privacy": privacy,
        "video_file": str(video), "title": meta["youtube_title"], "thumbnail_set": res.get("thumbnail_set"),
        "playlist_added": res.get("playlist_added"), "playlist_id": args.playlist_id,
        "contains_synthetic_media": kw["contains_synthetic_media"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[✔] 업로드 완료: {res.get('url')} (썸네일 {res.get('thumbnail_set')})")
    if not record_decision_applied(result_file.parent):
        sys.exit(2)
    for w in res.get("warnings") or []:
        print(f"[!] {w}")


if __name__ == "__main__":
    main()
