#!/usr/bin/env python3
"""
예약 공개 유튜브 영상 11건의 메타데이터(제목, 설명란, 태그, 예약일시)를
개편된 채널 컨셉(Lo-Fi & Piano 중심 락인, 모바일 훅 전면 배치, AI 흔적 세탁)에 맞추어 일괄 업데이트합니다.

※ 2026-10-11 실제 채널에 1회 적용 완료(11/11건). 재실행하면 같은 값으로 다시 덮어쓰며
   videos.update 는 건당 50 쿼터를 소모하므로, 확인 용도라면 --dry-run 으로 실행하세요.

    python scripts/apply_scheduled_video_adjustments.py --dry-run
"""

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import uploader

CHANNEL_ID = "UCowTfbpKpXDBF3Mc50H4iGQ"

# 11개 영상별 맞춤 개편 데이터
ADJUSTMENTS = {
    "JwgbMsjLDRg": {
        "title": "[Ambient] 우주 한가운데서 찾는 깊은 침묵 🌌 아득한 정적 (Abandoned Core)",
        "genre_tag": "Ambient",
        "story_hint": "광활한 밤하늘과 심해의 아득한 고요 속에서, 복잡한 생각을 비우고 온전한 침묵으로 들어가는 앰비언트 사운드스케이프입니다.",
        "new_publish_at": None  # 변경 없음 (10/11 21:00 KST)
    },
    "QXtK8pQeltk": {
        "title": "[Piano] 지나간 날을 다정하게 배웅하며 🌙 시간의 궤적 (Traces on Dust Keys)",
        "genre_tag": "Piano",
        "story_hint": "먼지 쌓인 피아노 건반 위로 내려앉은 기억들을 조용히 어루만지며, 지나간 시간들을 따뜻하게 배웅하는 서정적인 펠트 피아노 선율입니다.",
        "new_publish_at": None  # 변경 없음 (10/12 21:00 KST)
    },
    "Zj0T9Ey-qBc": {
        "title": "[Chill] 차가운 새벽 공기, 손끝에 닿는 온기 ☕ 1시 05분 (Warm Can)",
        "genre_tag": "Chill",
        "story_hint": "차가운 밤거리, 자판기에서 뽑은 따뜻한 캔커피 하나를 손에 쥐고 걸어가는 늦은 귀가길. 고요한 새벽 공기 속 작은 위로를 전합니다.",
        "new_publish_at": None  # 변경 없음 (10/13 21:00 KST)
    },
    "fVuhMfgNicY": {
        "title": "[Lo-Fi] 새벽 3시, 구겨진 마음을 다스릴 때 🕯️ (Creased Silences)",
        "genre_tag": "Lo-Fi",
        "story_hint": "잠 못 드는 새벽 3시, 구겨진 마음과 어지러운 감정들을 다정한 온도로 천천히 펴내는 로파이 칠아웃 선율입니다.",
        "new_publish_at": None  # 변경 없음 (10/14 21:00 KST)
    },
    "QUYW3_CLjsI": {
        "title": "[Jazz] 조용한 밤 깊은 사색을 위한 선율 🎷 푸른 시간의 몽상 (Blue Hour)",
        "genre_tag": "Jazz",
        "story_hint": "새벽으로 넘어가는 푸른 어스름 속, 부드러운 피아노와 콘트라베이스가 자아내는 깊은 사색의 재즈 선율입니다.",
        "new_publish_at": "2026-10-15T12:00:00Z"  # 10/16 중복 방지 -> 10/15 21:00 KST로 분산
    },
    "XQJNhMOvC0c": {
        "title": "[Lo-Fi] 지친 일상을 채우는 선선한 바람 🍃 4시의 식물원 (Glasshouse Solitude)",
        "genre_tag": "Lo-Fi",
        "story_hint": "오후 4시 햇살이 부드럽게 스며드는 식물원 온실 속, 풀내음과 선선한 바람에 지친 마음을 잠시 기대어 쉬어가는 로파이 비트입니다.",
        "new_publish_at": None  # 변경 없음 (10/16 21:00 KST)
    },
    "eS6nCUlvJW8": {
        "title": "[Chill] 새벽 4시, 전하지 못한 마음에 빠져들 때 🌙 (Unsent Telepathy)",
        "genre_tag": "Chill",
        "story_hint": "결국 보내지 못한 밤의 메모들. 깊어가는 어둠 속에서 말하지 못한 진심을 조용히 품어주는 감성 칠아웃 사운드입니다.",
        "new_publish_at": None  # 변경 없음 (10/17 21:00 KST)
    },
    "EK8TSuSAQtM": {
        "title": "[Lo-Fi] 복잡한 밤 도심을 벗어나는 드라이브 🚗 (Midnight Expressway)",
        "genre_tag": "Lo-Fi",
        "story_hint": "복잡했던 낮의 소음을 뒤로하고 불 꺼진 도심 외곽 도로를 달릴 때, 차분하게 마음을 가라앉혀주는 심야 드라이브 로파이입니다.",
        "new_publish_at": None  # 변경 없음 (10/18 21:00 KST)
    },
    "ifGFKXnJV5U": {
        "title": "[Lo-Fi] 비 내리는 퇴근길, 지친 마음에 건네는 안식 🌧️ (Smudged Numbers)",
        "genre_tag": "Lo-Fi",
        "story_hint": "유리창을 두드리는 빗방울과 번진 영수증의 무게. 하루 동안 무거웠던 어깨를 가볍게 털어내고 편안한 쉼으로 인도하는 로파이 선율입니다.",
        "new_publish_at": None  # 변경 없음 (10/19 21:00 KST)
    },
    "urhtvA0fTtM": {
        "title": "[Ambient] 지친 마음을 가만히 안아주는 온기 🌿 초록의 볕 (Glasshouse Solace)",
        "genre_tag": "Ambient",
        "story_hint": "유리창 너머로 쏟아지는 부드러운 온기와 초록 식물들의 숨결. 깊은 이완과 평온한 수면을 위한 시네마틱 앰비언트입니다.",
        "new_publish_at": None  # 변경 없음 (10/20 21:00 KST)
    },
    "EfnAzo8Hsg0": {
        "title": "[Piano] 잊혀진 기억이 불현듯 차오를 때 🌙 조용한 위로 (Faded Contours)",
        "genre_tag": "Piano",
        "story_hint": "지나간 줄 알았던 소중한 순간들이 어스름한 밤에 문득 차오를 때, 말없이 곁을 지켜주는 포근한 피아노 독주곡입니다.",
        "new_publish_at": None  # 변경 없음 (10/22 21:00 KST)
    }
}

CLEAN_TAGS = [
    "루나의심야서재",
    "로파이",
    "수면음악",
    "새벽피아노",
    "공부할때듣는음악",
    "힐링BGM",
    "Chillhop",
    "SleepBGM",
    "새벽감성",
    "편안한음악",
    "플레이리스트"
]


def update_scheduled_videos(dry_run: bool = False):
    print(f"=== [루나의 심야 서재] 예약 영상 11건 일괄 개편 {'점검(dry-run)' if dry_run else '시작'} ===")
    creds = uploader._creds(CHANNEL_ID)
    if not creds:
        print("[오류] 채널 OAuth 토큰을 가져올 수 없습니다.")
        sys.exit(1)

    svc = uploader._service(creds)
    success_count = 0

    for vid, adj in ADJUSTMENTS.items():
        print(f"\n[*] 처리 중: {vid}")
        try:
            # 1. 기존 영상 메타데이터 가져오기
            res = svc.videos().list(part="snippet,status", id=vid).execute()
            items = res.get("items", [])
            if not items:
                print(f"  [경고] 비디오 ID {vid}를 찾을 수 없습니다. 건너뜁니다.")
                continue

            video = items[0]
            snippet = video["snippet"]
            status = video["status"]

            old_title = snippet["title"]
            new_title = adj["title"]
            snippet_before_desc = snippet.get("description", "")
            tags_before = snippet.get("tags") or []

            print(f"  - 기존 제목: {old_title}")
            print(f"  - 변경 제목: {new_title}")

            # 2. 설명란 정제 (AI 흔적 제거 & 루나의 심야 서재 표준 템플릿)
            story = adj["story_hint"]
            new_desc = f"""{story}

오늘 하루 어떤 순간이 가장 마음에 머무셨나요?
불을 끄고 편안한 자세로 지친 마음을 쉬어가세요. 🌙

음악: 루나의 심야 서재 (Luna's Midnight Room)
기획 & 큐레이션: 에이전트 레오 (Agent Leo)
사운드 마스터링: 베가 (Vega)

구독과 좋아요는 밤의 서재를 밝히는 따뜻한 온기가 됩니다. 🕯️

#루나의심야서재 #수면음악 #로파이 #새벽피아노 #힐링음악 #SleepBGM #Chillhop #공부할때듣는음악
"""

            # 3. snippet 업데이트 구성
            snippet["title"] = new_title
            snippet["description"] = new_desc
            snippet["tags"] = CLEAN_TAGS

            # 4. status 업데이트 (예약일시 변경 필요한 경우)
            body_parts = ["snippet"]
            req_body = {
                "id": vid,
                "snippet": snippet
            }

            if adj.get("new_publish_at"):
                status["publishAt"] = adj["new_publish_at"]
                status["privacyStatus"] = "private"  # publishAt 설정 시 반드시 private 유지
                req_body["status"] = status
                body_parts.append("status")
                print(f"  - 예약 시각 이동: {adj['new_publish_at']}")

            # 5. API 실행
            if dry_run:
                # 유튜브는 설명 끝 개행을 떼어 저장하므로 strip 기준으로 비교
                changed = (old_title != new_title
                           or snippet_before_desc.strip() != new_desc.strip()
                           or sorted(tags_before) != sorted(CLEAN_TAGS))
                print(f"  [dry-run] 변경 필요: {'예' if changed else '아니오(이미 적용됨)'}")
                success_count += 1
                continue
            svc.videos().update(
                part=",".join(body_parts),
                body=req_body
            ).execute()

            print(f"  [+] 업데이트 성공!")
            success_count += 1
            time.sleep(1.0)  # Rate limit 방지

        except Exception as e:
            print(f"  [오류] 비디오 {vid} 업데이트 실패: {e}")

    print(f"\n==================================================")
    print(f"[완료] 총 {len(ADJUSTMENTS)}건 중 {success_count}건 {'점검' if dry_run else '개편'} 완료!")
    print(f"==================================================")


if __name__ == "__main__":
    update_scheduled_videos(dry_run="--dry-run" in sys.argv[1:])
