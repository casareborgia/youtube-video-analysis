#!/usr/bin/env python3
"""
루나의 심야 서재 1시간 롱폼 컴필레이션 유튜브 예약 업로드 스크립트
- 오늘 밤 22:00 KST (10시) 예약 공개
- 미발표 선공개 트랙 2곡 하이라이트 안내
- 배너 싱크 잠자는 삼색 고양이 썸네일 자동 적용
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import uploader

CHANNEL_ID = "UCowTfbpKpXDBF3Mc50H4iGQ"
VIDEO_PATH = BASE_DIR / "data" / "luna_compilations" / "compilation_video.mp4"
THUMBNAIL_PATH = Path("/Users/leeseungjun/.gemini/antigravity-ide/brain/c3482952-7e3d-4c3d-adb4-8833764d9230/lofi_cat_banner_sync_1791700806507.jpg")

# 오늘 22:00 KST = 2026-10-11T22:00:00+09:00
PUBLISH_AT = "2026-10-11T22:00:00+09:00"

TITLE = "[1 Hour Playlist] 오늘 밤 생각 비우고 푹 쉬고 싶을 때 듣는 로파이 🌧️ (미발표 선공개곡 포함) | 루나의 심야 서재"

DESCRIPTION = """지친 하루의 끝, 조용한 위로와 온전한 쉼이 필요할 때 틀어두는 루나의 심야 서재 1시간 롱폼 플레이리스트입니다. 🌙
불을 끄고 침대에서, 혹은 깊은 공부와 작업 몰입에 함께하세요.

✨ [수록곡 안내 (미발표 선공개곡 포함)]
- 05:43 Petrichor Reverie (빗소리에 젖어드는 회상) ★ 컴필레이션 최초 공개
- 26:06 Blue Hour Reverie (새벽빛의 온기) ★ 컴필레이션 최초 공개

[Tracklist / 타임라인]
00:00 Starlight Serenade (새벽)
02:56 Trace of Tomorrow (어른이 된 우리에게)
05:43 Petrichor Reverie (빗소리에 젖어드는 회상) ★
08:30 Traces Left in the Blue (새벽이 머물다 간 자리)
11:07 Faded Blue Ink (어스름에 적신 편지)
14:07 Paper Planes in the Rain (빗속의 종이비행기)
17:07 Glasshouse Solitude (4시의 식물원)
20:08 Echoes of Adagio (차가운 밤을 감싸는 온기)
23:05 Smudged Numbers (번진 영수증의 무게)
26:06 Blue Hour Reverie (새벽빛의 온기) ★
29:06 Starlight Serenade (새벽)
32:03 Trace of Tomorrow (어른이 된 우리에게)
34:49 Petrichor Reverie (빗소리에 젖어드는 회상) ★
37:36 Traces Left in the Blue (새벽이 머물다 간 자리)
40:13 Faded Blue Ink (어스름에 적신 편지)
43:14 Paper Planes in the Rain (빗속의 종이비행기)
46:13 Glasshouse Solitude (4시의 식물원)
49:14 Echoes of Adagio (차가운 밤을 감싸는 온기)
52:12 Smudged Numbers (번진 영수증의 무게)
55:12 Blue Hour Reverie (새벽빛의 온기) ★
58:12 Starlight Serenade (새벽)

[Credits]
음악: 에이전트 루나 (Agent Luna) - 루나의 심야 서재
기획 & 큐레이션: 에이전트 레오 (Agent Leo)
사운드 마스터링: 베가 (Vega Engine) -16 LUFS True-Peak Mastered

채널 구독으로 루나의 따뜻한 서재에 매일 밤 머물러보세요 🐾
https://www.youtube.com/channel/UCowTfbpKpXDBF3Mc50H4iGQ?sub_confirmation=1

#루나의심야서재 #로파이 #플레이리스트 #수면음악 #공부할때듣는음악 #새벽감성 #Chillhop #LoFiPlaylist #AgentLuna"""

TAGS = [
    "루나의심야서재", "로파이", "플레이리스트", "수면음악", "공부할때듣는음악",
    "새벽감성", "Chillhop", "LoFiPlaylist", "AgentLuna", "BGM",
    "힐링음악", "선공개", "미발표곡", "빗소리", "서재"
]


def progress_cb(step, msg, pct):
    print(f"[{pct}%] {msg}")


def main():
    if not VIDEO_PATH.exists():
        print(f"[Error] 비디오 파일이 없습니다: {VIDEO_PATH}")
        sys.exit(1)

    print("=" * 65)
    print("🚀 에이전트 루나 1시간 컴필레이션 유튜브 예약 업로드")
    print("=" * 65)
    print(f"- 영상 파일: {VIDEO_PATH} ({VIDEO_PATH.stat().st_size / (1024*1024*1024):.2f} GB)")
    print(f"- 썸네일: {THUMBNAIL_PATH}")
    print(f"- 예약 일시: {PUBLISH_AT} (오늘 밤 10시 KST)")
    print(f"- 제목: {TITLE}")
    print("-" * 65)

    res = uploader.upload_video(
        video_path=str(VIDEO_PATH),
        title=TITLE,
        description=DESCRIPTION,
        tags=TAGS,
        privacy="private",
        publish_at=PUBLISH_AT,
        thumbnail_path=str(THUMBNAIL_PATH) if THUMBNAIL_PATH.exists() else None,
        category_id="10",
        channel_id=CHANNEL_ID,
        progress=progress_cb
    )

    print("\n[✔] 업로드 및 예약 설정 성공!")
    print(f"- Video ID: {res.get('video_id')}")
    print(f"- YouTube URL: {res.get('url')}")
    print(f"- 썸네일 등록 여부: {res.get('thumbnail_set')}")


if __name__ == "__main__":
    main()
