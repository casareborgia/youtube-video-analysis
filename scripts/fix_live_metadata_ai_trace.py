#!/usr/bin/env python3
"""
2026-10-11 시그니처 BGA 교체 6편 + 1시간 컴필레이션(HzfRkSiTyeI) 라이브 메타데이터에서 AI 흔적 제거.

replace_scheduled_videos_with_bga.py / upload_luna_compilation.py 의 초기 버전이 설명란 크레딧에
'에이전트 루나 (Agent Luna)', 태그·해시태그에 'AgentLuna' 를 넣어 올렸다. 채널 정책(기계적 수식어 금지)에 맞춰
설명란의 해당 문구와 태그만 치환하고 제목·예약 시각·나머지 본문은 그대로 둔다. videos.update 는 건당 50 쿼터.

    python scripts/fix_live_metadata_ai_trace.py            # dry-run: 변경 전/후 표시
    python scripts/fix_live_metadata_ai_trace.py --execute  # 실제 반영
"""
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import uploader

CHANNEL_ID = "UCowTfbpKpXDBF3Mc50H4iGQ"
VIDEO_IDS = ["HzfRkSiTyeI", "qDWW10tvUsU", "36KRU3_vYtU", "xBGzcWqMT5A", "iuu4v2GFcfo", "6Bvupz7wtjM", "H55FAKD0hUU"]

DESC_REPLACEMENTS = [
    ("- 작곡 & 연주: 에이전트 루나 (Agent Luna) - 루나의 심야 서재", "- 음악: 루나의 심야 서재 (Luna's Midnight Room)"),
    ("음악: 에이전트 루나 (Agent Luna) - 루나의 심야 서재", "음악: 루나의 심야 서재 (Luna's Midnight Room)"),
    ("베가 (Vega Engine)", "베가 (Vega)"),
    (" #AgentLuna", " #SleepBGM"),
]
TAG_REPLACEMENTS = {"AgentLuna": "SleepBGM"}
BANNED = ("Agent Luna", "에이전트 루나", "AgentLuna", "AI음악")


def clean_description(desc: str) -> str:
    for a, b in DESC_REPLACEMENTS:
        desc = desc.replace(a, b)
    return desc


def clean_tags(tags):
    out = []
    for t in tags or []:
        t2 = TAG_REPLACEMENTS.get(t, t)
        if t2 not in out:
            out.append(t2)
    return out


def main():
    execute = "--execute" in sys.argv[1:]
    svc = uploader._service(uploader._creds(CHANNEL_ID))
    res = svc.videos().list(part="snippet", id=",".join(VIDEO_IDS)).execute()
    changed = 0
    for it in res.get("items", []):
        sn = it["snippet"]
        new_desc = clean_description(sn.get("description", ""))
        new_tags = clean_tags(sn.get("tags"))
        if new_desc == sn.get("description", "") and new_tags == (sn.get("tags") or []):
            print(f"[=] {it['id']} 변경 없음")
            continue
        leftover = [w for w in BANNED if w in new_desc or any(w in t for t in new_tags)]
        print(f"[*] {it['id']} {sn['title'][:40]}")
        print(f"    tags: {sorted(set(sn.get('tags') or []) - set(new_tags))} -> {sorted(set(new_tags) - set(sn.get('tags') or []))}")
        for a, b in DESC_REPLACEMENTS:
            if a in sn.get("description", ""):
                print(f"    desc: {a!r} -> {b!r}")
        if leftover:
            print(f"    [!] 치환 후에도 남은 금지어: {leftover}")
        if execute:
            sn["description"] = new_desc
            sn["tags"] = new_tags
            svc.videos().update(part="snippet", body={"id": it["id"], "snippet": sn}).execute()
            print("    [+] 반영 완료")
            time.sleep(1.0)
        changed += 1
    print(f"\n{'반영' if execute else '변경 필요'}: {changed}건 / {len(VIDEO_IDS)}건" + ("" if execute else "  (--execute 로 실행)"))


if __name__ == "__main__":
    main()
