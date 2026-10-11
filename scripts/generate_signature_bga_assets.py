#!/usr/bin/env python3
"""
루나의 심야 서재 — 3대 시그니처 룸(3 Rooms) BGA 심리스 루프 에셋 생성기

배너 및 프로필과 100% 동기화된 '잠자는 삼색 고양이' 2D 일러스트를 입력받아,
시작과 끝이 완벽하게 이어지는 16초 무손실 심리스 루프 비디오(MP4)를 제작합니다.
- bga_lofi_study.mp4
- bga_piano_moonlight.mp4
- bga_ambient_bedroom.mp4
"""

import os
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BGA_ASSETS_DIR = DATA_DIR / "bga_assets"
BGA_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# 3대 코어 장르별 배너 싱크 삼색 고양이 일러스트 (저장소 data/bga_assets 에 보관)
# ※ Antigravity brain 디렉터리는 세션 캐시라 언제든 비워질 수 있어 저장소 사본을 1순위로 쓰고, 없을 때만 폴백한다.
_BRAIN_DIR = Path("/Users/leeseungjun/.gemini/antigravity-ide/brain/c3482952-7e3d-4c3d-adb4-8833764d9230")
SOURCE_IMAGES = {
    "lofi": BGA_ASSETS_DIR / "thumb_lofi_cat.jpg",
    "piano": BGA_ASSETS_DIR / "thumb_piano_cat.jpg",
    "ambient": BGA_ASSETS_DIR / "thumb_ambient_cat.jpg",
    "sleep": BGA_ASSETS_DIR / "thumb_sleep_cat.jpg",
    "jazz": BGA_ASSETS_DIR / "thumb_jazz_cat.jpg",
    "chill": BGA_ASSETS_DIR / "thumb_chill_cat.jpg",
    "acoustic": BGA_ASSETS_DIR / "thumb_acoustic_cat.jpg",
}
_BRAIN_FALLBACK = {
    "lofi": _BRAIN_DIR / "lofi_cat_banner_sync_1791700806507.jpg",
    "piano": _BRAIN_DIR / "piano_cat_banner_sync_1791700829563.jpg",
    "ambient": _BRAIN_DIR / "ambient_cat_banner_sync_1791700850279.jpg",
    "sleep": _BRAIN_DIR / "thumb_sleep_cat_1791705597450.jpg",
    "jazz": _BRAIN_DIR / "thumb_jazz_cat_1791705560606.jpg",
    "chill": _BRAIN_DIR / "thumb_chill_cat_1791705581671.jpg",
    "acoustic": _BRAIN_DIR / "thumb_acoustic_cat_1791705615061.jpg",
}

TARGET_FILES = {
    "lofi": BGA_ASSETS_DIR / "bga_lofi_study.mp4",
    "piano": BGA_ASSETS_DIR / "bga_piano_moonlight.mp4",
    "ambient": BGA_ASSETS_DIR / "bga_ambient_bedroom.mp4",
    "sleep": BGA_ASSETS_DIR / "bga_sleep_sanctuary.mp4",
    "jazz": BGA_ASSETS_DIR / "bga_jazz_cafe.mp4",
    "chill": BGA_ASSETS_DIR / "bga_chill_balcony.mp4",
    "acoustic": BGA_ASSETS_DIR / "bga_acoustic_attic.mp4",
}


def render_seamless_loop(img_path: Path, out_mp4: Path, duration_sec: int = 16, fps: int = 30) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg가 시스템에 설치되어 있지 않습니다.")

    if not img_path.exists():
        raise FileNotFoundError(f"소스 이미지 파일을 찾을 수 없습니다: {img_path}")

    total_frames = duration_sec * fps
    print(f"[*] BGA 렌더링 시작 -> {out_mp4.name} (소요 시간: {duration_sec}초, {total_frames} 프레임)")

    # 사인(sin) 함수 기반 줌: sin(0) = 0 -> sin(PI/2) = 1 -> sin(PI) = 0
    # 시작 프레임(zoom=1.00)과 끝 프레임(zoom=1.00)이 완전 일치하는 무결점 심리스 루프
    # 미세 줌 배율: 1.00 ~ 1.028 (고양이 호흡 및 서재 공간의 잔잔한 앰비언스 일치)
    zoom_expr = f"1.0+0.028*sin(PI*on/{total_frames})"
    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"

    cmd = [
        ffmpeg, "-y",
        "-loop", "1",
        "-i", str(img_path),
        "-vf", (
            f"scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s=1920x1080:fps={fps},"
            # JPEG 입력은 full-range(yuvj) 라 그대로 두면 pc 레인지로 인코딩된다 → 영상 표준(limited/tv) 으로 변환
            f"scale=in_range=full:out_range=limited,format=yuv420p"
        ),
        "-color_range", "tv",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-t", str(duration_sec),
        "-movflags", "+faststart",
        str(out_mp4)
    ]

    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        tail = "\n".join((res.stderr or "").strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg 렌더링 실패:\n{tail}")

    size_mb = out_mp4.stat().st_size / (1024 * 1024)
    print(f"[+] 생성 완료: {out_mp4.name} ({size_mb:.2f} MB, {duration_sec}s, 1080p@30fps)")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="3대 시그니처 룸 BGA 루프 에셋 생성")
    parser.add_argument("--force", action="store_true",
                        help="이미 생성된 에셋도 다시 렌더링 (기본: 존재하면 건너뜀 — 업로드된 영상과 에셋이 달라지는 것을 방지)")
    args = parser.parse_args()

    print("=" * 65)
    print("🐾 루나의 심야 서재 3대 시그니처 룸 BGA 에셋 자동 생성")
    print("=" * 65)

    for genre, img_p in SOURCE_IMAGES.items():
        out_p = TARGET_FILES[genre]
        if out_p.exists() and not args.force:
            print(f"[=] {out_p.name} 이미 존재 → 건너뜀 (--force 로 재생성)")
            continue
        if not img_p.exists() and _BRAIN_FALLBACK[genre].exists():
            img_p = _BRAIN_FALLBACK[genre]
        render_seamless_loop(img_p, out_p, duration_sec=16, fps=30)

    print("\n[✔] 3대 시그니처 룸 BGA 에셋 전체 생성 성공!")
    for g, p in TARGET_FILES.items():
        print(f"  - [{g.upper()}] {p.name} ({p.stat().st_size / (1024*1024):.2f} MB)")


if __name__ == "__main__":
    main()
