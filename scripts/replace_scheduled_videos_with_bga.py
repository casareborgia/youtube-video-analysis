#!/usr/bin/env python3
"""
루나의 심야 서재 — 10/11(오늘) ~ 10/16(금) 예약 공개 영상 6편 시그니처 BGA 안전 교체 스크립트

각 트랙별로:
1. 1080p 시그니처 룸 BGA(잠자는 삼색 고양이) 무손실 루프 비디오 렌더링
2. 신규 영상 유튜브 업로드 (기존과 동일한 예약 일시)
3. 신규 업로드 성공 확인 즉시 기존 구형 영상 안전 삭제

※ 2026-10-11 16:24~16:26 KST 에 6/6건 실행 완료 (구 영상 삭제됨). 기본 실행은 dry-run 이며,
   이미 교체된 트랙(meta.bga_updated_at 존재 또는 구 영상 없음)은 --execute 를 줘도 건너뛴다.
   업로드 1건 = 쿼터 약 1,600 이므로 하루 6건이 상한에 가깝다.
"""

import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import uploader

CHANNEL_ID = "UCowTfbpKpXDBF3Mc50H4iGQ"
DATA_DIR = BASE_DIR / "data"
LUNA_DIR = DATA_DIR / "luna_music"
BGA_DIR = DATA_DIR / "bga_assets"
# 썸네일 소스는 저장소 사본(data/bga_assets/thumb_*.jpg) 을 쓴다. brain 디렉터리는 세션 캐시라 사라질 수 있다.
THUMB_FILES = {
    "lofi_cat_banner_sync_1791700806507.jpg": BGA_DIR / "thumb_lofi_cat.jpg",
    "piano_cat_banner_sync_1791700829563.jpg": BGA_DIR / "thumb_piano_cat.jpg",
    "ambient_cat_banner_sync_1791700850279.jpg": BGA_DIR / "thumb_ambient_cat.jpg",
}

TARGETS = [
    {
        "old_video_id": "JwgbMsjLDRg",
        "track_id": "luna_1790519064",
        "bga_file": "bga_ambient_bedroom.mp4",
        "thumb_file": "ambient_cat_banner_sync_1791700850279.jpg",
        "publish_at": "2026-10-11T21:00:00+09:00",
        "title": "[Ambient] 우주 한가운데서 찾는 깊은 침묵 🌌 아득한 정적 (Abandoned Core)",
        "genre_tag": "Ambient",
        "story": "광활한 밤하늘과 심해의 아득한 고요 속에서, 복잡한 생각을 비우고 온전한 침묵으로 들어가는 앰비언트 사운드스케이프입니다.",
    },
    {
        "old_video_id": "QXtK8pQeltk",
        "track_id": "luna_1790868801",
        "bga_file": "bga_piano_moonlight.mp4",
        "thumb_file": "piano_cat_banner_sync_1791700829563.jpg",
        "publish_at": "2026-10-12T21:00:00+09:00",
        "title": "[Piano] 지나간 날을 다정하게 배웅하며 🌙 시간의 궤적 (Traces on Dust Keys)",
        "genre_tag": "Piano",
        "story": "먼지 쌓인 피아노 건반 위로 내려앉은 기억들을 조용히 어루만지며, 지나간 시간들을 따뜻하게 배웅하는 서정적인 펠트 피아노 선율입니다.",
    },
    {
        "old_video_id": "Zj0T9Ey-qBc",
        "track_id": "luna_1790522526",
        "bga_file": "bga_lofi_study.mp4",
        "thumb_file": "lofi_cat_banner_sync_1791700806507.jpg",
        "publish_at": "2026-10-13T21:00:00+09:00",
        "title": "[Chill] 차가운 새벽 공기, 손끝에 닿는 온기 ☕ 1시 05분 (Warm Can)",
        "genre_tag": "Chill",
        "story": "차가운 밤거리, 자판기에서 뽑은 따뜻한 캔커피 하나를 손에 쥐고 걸어가는 늦은 귀가길. 고요한 새벽 공기 속 작은 위로를 전합니다.",
    },
    {
        "old_video_id": "fVuhMfgNicY",
        "track_id": "luna_1790523368",
        "bga_file": "bga_lofi_study.mp4",
        "thumb_file": "lofi_cat_banner_sync_1791700806507.jpg",
        "publish_at": "2026-10-14T21:00:00+09:00",
        "title": "[Lo-Fi] 새벽 3시, 구겨진 마음을 다스릴 때 🕯️ (Creased Silences)",
        "genre_tag": "Lo-Fi",
        "story": "잠 못 드는 새벽 3시, 구겨진 마음과 어지러운 감정들을 다정한 온도로 천천히 펴내는 로파이 칠아웃 선율입니다.",
    },
    {
        "old_video_id": "QUYW3_CLjsI",
        "track_id": "luna_1790520688",
        "bga_file": "bga_lofi_study.mp4",
        "thumb_file": "lofi_cat_banner_sync_1791700806507.jpg",
        "publish_at": "2026-10-15T21:00:00+09:00",
        "title": "[Jazz] 조용한 밤 깊은 사색을 위한 선율 🎷 푸른 시간의 몽상 (Blue Hour)",
        "genre_tag": "Jazz",
        "story": "새벽으로 넘어가는 푸른 어스름 속, 부드러운 피아노와 콘트라베이스가 자아내는 깊은 사색의 재즈 선율입니다.",
    },
    {
        "old_video_id": "XQJNhMOvC0c",
        "track_id": "luna_1790525578",
        "bga_file": "bga_lofi_study.mp4",
        "thumb_file": "lofi_cat_banner_sync_1791700806507.jpg",
        "publish_at": "2026-10-16T21:00:00+09:00",
        "title": "[Lo-Fi] 지친 일상을 채우는 선선한 바람 🍃 4시의 식물원 (Glasshouse Solitude)",
        "genre_tag": "Lo-Fi",
        "story": "오후 4시 햇살이 부드럽게 스며드는 식물원 온실 속, 풀내음과 선선한 바람에 지친 마음을 잠시 기대어 쉬어가는 로파이 비트입니다.",
    },
]

# 채널 정책: 'AgentLuna', 'AI음악' 등 기계적 수식어는 공개 메타데이터에 넣지 않는다
CLEAN_TAGS = [
    "루나의심야서재", "로파이", "수면음악", "새벽피아노", "공부할때듣는음악",
    "힐링BGM", "Chillhop", "Piano", "Ambient", "SleepBGM"
]


def get_audio_duration(file_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 180.0
    cmd = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 180.0


def render_track_bga_video(track_dir: Path, bga_file: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg가 없습니다.")

    audio_file = track_dir / "audio_mastered.wav"
    if not audio_file.exists():
        audio_file = track_dir / "audio.mp3"

    duration = get_audio_duration(audio_file)
    out_video = track_dir / "video_signature_bga.mp4"

    cmd = [
        ffmpeg, "-y",
        "-stream_loop", "-1",
        "-i", str(bga_file),
        "-i", str(audio_file),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "320k",
        "-t", f"{duration:.3f}",
        "-shortest",
        "-movflags", "+faststart",
        str(out_video)
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        # 비호환 시 1080p 재인코딩 폴백
        cmd_reencode = [
            ffmpeg, "-y",
            "-stream_loop", "-1",
            "-i", str(bga_file),
            "-i", str(audio_file),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "320k",
            "-t", f"{duration:.3f}",
            "-shortest",
            "-movflags", "+faststart",
            str(out_video)
        ]
        res2 = subprocess.run(cmd_reencode, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if res2.returncode != 0:
            raise RuntimeError(f"비디오 렌더링 실패: {res2.stderr}")

    return out_video


def build_description(title: str, story: str, genre_tag: str) -> str:
    return f"""{story}

지친 하루의 끝, 조용한 위로와 온전한 쉼이 필요할 때 틀어두는 루나의 심야 서재입니다. 🌙
불을 끄고 침대에서, 혹은 깊은 공부와 작업 몰입에 함께하세요.

[Credits]
- 음악: 루나의 심야 서재 (Luna's Midnight Room)
- 기획 & 큐레이션: 에이전트 레오 (Agent Leo)
- 사운드 마스터링: 베가 (Vega) -16 LUFS True-Peak Mastered

채널 구독으로 루나의 따뜻한 서재에 매일 밤 머물러보세요 🐾
https://www.youtube.com/channel/UCowTfbpKpXDBF3Mc50H4iGQ?sub_confirmation=1

#{genre_tag} #루나의심야서재 #수면음악 #공부할때듣는음악 #새벽감성 #힐링음악"""


def main():
    execute = "--execute" in sys.argv[1:]
    print("=" * 65)
    print(f"🐾 [루나의 심야 서재] 10/11~10/16 예약 영상 6편 시그니처 BGA 안전 교체 {'(실행)' if execute else '(dry-run)'}")
    print("=" * 65)

    creds = uploader._creds(CHANNEL_ID)
    if not creds:
        raise RuntimeError("유튜브 인증 정보가 없습니다.")
    srv = uploader._service(creds)

    # 구 영상 존재 여부 1회 조회 (이미 삭제됐으면 교체 완료로 간주)
    old_ids = [t["old_video_id"] for t in TARGETS]
    existing = {it["id"] for it in srv.videos().list(part="id", id=",".join(old_ids)).execute().get("items", [])}

    results = []

    for i, t in enumerate(TARGETS, 1):
        print(f"\n[{i}/6] 처리 중: {t['title']}")
        print(f"  - 구 영상 ID: {t['old_video_id']}")
        print(f"  - 예약 일시: {t['publish_at']}")

        track_dir = LUNA_DIR / t["track_id"]
        bga_path = BGA_DIR / t["bga_file"]
        thumb_path = THUMB_FILES.get(t["thumb_file"], BGA_DIR / t["thumb_file"])

        # 0. 재실행 가드: 이미 교체된 트랙은 건너뜀 (중복 업로드·쿼터 소모 방지)
        meta_p = track_dir / "meta.json"
        meta = {}
        if meta_p.exists():
            try:
                meta = json.load(open(meta_p, encoding="utf-8"))
            except Exception:
                meta = {}
        if meta.get("bga_updated_at") or t["old_video_id"] not in existing:
            print(f"  [=] 이미 교체 완료 (현재 영상: {meta.get('uploaded_video_id')}) → 건너뜀")
            continue
        if not bga_path.exists():
            print(f"  [!] BGA 에셋 없음: {bga_path} → 건너뜀 (scripts/generate_signature_bga_assets.py 먼저 실행)")
            continue
        if not execute:
            print(f"  [dry-run] 렌더 → 업로드(publish_at {t['publish_at']}) → 구 영상 삭제 예정. --execute 로 실행.")
            continue

        # 1. BGA 비디오 렌더링
        print(f"  [*] 1080p 시그니처 BGA({t['bga_file']}) 비디오 렌더링...")
        v_path = render_track_bga_video(track_dir, bga_path)
        print(f"  [+] 비디오 렌더링 완료: {v_path.name} ({v_path.stat().st_size / (1024*1024):.2f} MB)")

        # 2. 신규 영상 예약 업로드
        desc = build_description(t["title"], t["story"], t["genre_tag"])
        print(f"  [*] 신규 영상 유튜브 업로드 전송 중...")

        upload_res = uploader.upload_video(
            video_path=str(v_path),
            title=t["title"],
            description=desc,
            tags=CLEAN_TAGS,
            privacy="private",
            publish_at=t["publish_at"],
            thumbnail_path=str(thumb_path) if thumb_path.exists() else None,
            category_id="10",
            channel_id=CHANNEL_ID
        )

        new_vid = upload_res.get("video_id")
        new_url = upload_res.get("url")
        print(f"  [✔] 신규 영상 업로드 성공! -> New Video ID: {new_vid} ({new_url})")

        # 3. 구 영상 안전 삭제 (신규 업로드가 확인되었으므로 즉시 삭제)
        old_vid = t["old_video_id"]
        print(f"  [*] 구 영상({old_vid}) 안전 삭제 중...")
        try:
            srv.videos().delete(id=old_vid).execute()
            print(f"  [✔] 구 영상({old_vid}) 삭제 완료!")
        except Exception as e:
            print(f"  [!] 구 영상 삭제 오류 (수동 확인 필요): {e}")

        # 4. meta.json 갱신 — 앱(app.py/luna_engine/static)이 읽는 키는 uploaded_video_id/uploaded_url 이다.
        #    (youtube_video_id 만 바꾸면 UI 와 숏폼 '3분 풀버전' 링크가 삭제된 구 영상을 가리킨다)
        if meta_p.exists():
            try:
                m_data = json.load(open(meta_p, encoding="utf-8"))
                m_data["replaced_video_id"] = old_vid
                m_data["uploaded_video_id"] = new_vid
                m_data["uploaded_url"] = new_url
                m_data["youtube_video_id"] = new_vid
                m_data["youtube_url"] = new_url
                m_data["bga_updated_at"] = time.time()
                json.dump(m_data, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"  [!] meta.json 갱신 실패 (수동 확인 필요): {e}")

        results.append({
            "title": t["title"],
            "publish_at": t["publish_at"],
            "old_vid": old_vid,
            "new_vid": new_vid,
            "new_url": new_url
        })

        time.sleep(2)  # API 안정성 딜레이

    print("\n" + "=" * 65)
    print(f"🎉 시그니처 BGA 교체 완료: {len(results)}건 처리" if results else "처리할 항목이 없습니다 (전부 교체 완료 또는 dry-run)")
    print("=" * 65)
    for r in results:
        print(f"- {r['publish_at'][:10]} | {r['title'][:40]}... -> {r['new_url']}")


if __name__ == "__main__":
    main()
