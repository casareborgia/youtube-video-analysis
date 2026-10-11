#!/usr/bin/env python3
"""
에이전트 루나 (Agent Luna) - 롱폼 컴필레이션 플레이리스트 생성 유틸리티

기존 51개 이상의 음원 자산 중 'Lo-Fi / Piano' 등 핵심 휴식 장르 트랙들을 선별하여,
1시간 / 2시간 연속 재생 컴필레이션 오디오 및 비디오(MP4)를 자동 생성합니다.
유튜브 업로드에 최적화된 트랙리스트 타임라인(Timeline)과 감성 설명란도 함께 출력합니다.
"""

import os
import sys
import json
import glob
import random
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LUNA_DIR = DATA_DIR / "luna_music"
DEFAULT_OUT_DIR = DATA_DIR / "luna_compilations"


def get_audio_duration(file_path: Path) -> float:
    """ffprobe를 이용해 오디오 재생 길이(초)를 정밀 측정합니다."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 180.0  # 기본값 3분
    cmd = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 180.0


def scan_available_tracks(genre_filter: str = "lofi") -> List[Dict[str, Any]]:
    """luna_music 디렉토리 내의 트랙들을 스캔하고 장르 필터에 맞는 곡들을 반환합니다."""
    tracks = []
    if not LUNA_DIR.exists():
        return tracks

    genre_keywords = {
        "lofi": ["lo-fi", "lofi", "chillhop"],
        "piano": ["piano", "피아노"],
        "ambient": ["ambient", "cinematic ambient"],
        "sleep": ["sleep", "meditation", "delta"],
        "all_relax": ["lo-fi", "lofi", "chillhop", "piano", "피아노", "ambient", "sleep"]
    }.get(genre_filter.lower(), [genre_filter.lower()])

    for track_dir in sorted(LUNA_DIR.glob("luna_*")):
        meta_file = track_dir / "meta.json"
        if not meta_file.exists():
            continue

        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue

        genre_text = (meta.get("genre") or "").lower()
        title = meta.get("title") or track_dir.name

        # 장르 필터링
        if not any(k in genre_text for k in genre_keywords):
            continue

        # 오디오 파일 찾기 (마스터링된 파일 최우선)
        audio_file = None
        for candidate in ["audio_mastered.wav", "audio_mastered_preview.mp3", "audio.mp3", "audio_raw.mp3"]:
            p = track_dir / candidate
            if p.exists() and p.stat().st_size > 10000:
                audio_file = p
                break

        if not audio_file:
            continue

        # 커버 이미지 찾기
        cover_file = track_dir / "cover.jpg"
        if not cover_file.exists():
            for img in track_dir.glob("*.jpg"):
                cover_file = img
                break

        duration = get_audio_duration(audio_file)

        tracks.append({
            "track_id": track_dir.name,
            "title": title,
            "genre": meta.get("genre", "Lo-Fi"),
            "mood": meta.get("mood", "새벽 감성"),
            "audio_file": str(audio_file),
            "cover_file": str(cover_file) if cover_file and cover_file.exists() else None,
            "duration": duration,
            "story": meta.get("story", "")
        })

    return tracks


def format_timestamp(seconds: float) -> str:
    """초를 MM:SS 또는 HH:MM:SS 타임라인 형식으로 변환합니다."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def assemble_compilation(
    tracks: List[Dict[str, Any]],
    target_seconds: float = 3600.0,
    output_dir: Path = DEFAULT_OUT_DIR,
    compilation_title: str = "Lo-Fi Midnight Study",
    render_video: bool = True
) -> Dict[str, Any]:
    """선별된 트랙들을 묶어 롱폼 오디오/비디오 및 유튜브 메타데이터를 생성합니다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg가 설치되어 있지 않습니다.")

    if not tracks:
        raise ValueError("선별된 트랙이 없습니다.")

    # 목표 길이에 맞게 트랙 리스트 채우기 (곡 수가 적으면 순환 반복)
    playlist = []
    accumulated_time = 0.0
    while accumulated_time < target_seconds:
        for t in tracks:
            playlist.append(t)
            accumulated_time += t["duration"]
            if accumulated_time >= target_seconds:
                break

    print(f"[*] 총 {len(playlist)}개 트랙 배치 (총 예상 재생시간: {int(accumulated_time // 60)}분 {int(accumulated_time % 60)}초)")

    # 1. Concat 파일 목록 생성
    concat_txt = output_dir / "concat_list.txt"
    timeline_entries = []
    current_time = 0.0

    with open(concat_txt, "w", encoding="utf-8") as f:
        for idx, item in enumerate(playlist, 1):
            ts_str = format_timestamp(current_time)
            timeline_entries.append(f"{ts_str} {item['title']}")
            # ffmpeg concat을 위한 절대경로 쓰기
            f.write(f"file '{os.path.abspath(item['audio_file'])}'\n")
            current_time += item["duration"]

    out_audio = output_dir / "compilation_audio.mp3"
    print(f"[*] 오디오 스트림 Concat 진행 중 -> {out_audio}")

    # 재인코딩을 통한 안전 결합 (샘플레이트 통일 44.1kHz, 320k)
    cmd_audio = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
        "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", str(out_audio)
    ]
    subprocess.run(cmd_audio, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    actual_duration = get_audio_duration(out_audio)

    # 2. 비디오 렌더링 (대표 커버 또는 첫 트랙 커버 이미지 활용)
    out_video = output_dir / "compilation_video.mp4"
    cover_image = None
    for p in playlist:
        if p.get("cover_file") and os.path.exists(p["cover_file"]):
            cover_image = p["cover_file"]
            break

    if render_video and cover_image:
        print(f"[*] 1080p 롱폼 비디오 렌더링 시작 (커버: {os.path.basename(cover_image)})...")
        # 정지 이미지 기반 초고효율 비디오 렌더링 (단일 프레임 루프)
        cmd_video = [
            ffmpeg, "-y",
            "-loop", "1", "-framerate", "2", "-i", str(cover_image),
            "-i", str(out_audio),
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "ultrafast",
            "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-shortest",
            str(out_video)
        ]
        subprocess.run(cmd_video, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[+] 비디오 생성 완료: {out_video}")

    # 3. 유튜브 메타데이터 생성 (모바일 최적화 제목 및 타임라인 설명)
    timeline_text = "\n".join(timeline_entries)
    hours_int = int(actual_duration // 3600)
    duration_label = f"[{hours_int} Hours Playlist]" if hours_int >= 1 else f"[{int(actual_duration // 60)} Min Playlist]"
    
    yt_title = f"{duration_label} 오늘 밤 생각 비우고 푹 쉬고 싶을 때 듣는 로파이 모음 🌧️ | {compilation_title}"
    yt_description = f"""지친 하루의 끝, 조용한 위로와 온전한 쉼이 필요할 때 틀어두는 루나의 심야 서재 플레이리스트입니다. 🌙
불을 끄고 침대에서, 혹은 깊은 공부와 작업 몰입에 함께하세요.

[Tracklist / 타임라인]
{timeline_text}

음악: 루나의 심야 서재 (Luna's Midnight Room)
기획 & 큐레이션: 에이전트 레오 (Agent Leo)
사운드 마스터링: 베가 (Vega)

#루나의심야서재 #로파이 #플레이리스트 #수면음악 #공부할때듣는음악 #Chillhop #LoFiPlaylist #새벽감성
"""

    meta_txt_file = output_dir / "youtube_metadata.txt"
    with open(meta_txt_file, "w", encoding="utf-8") as f:
        f.write(f"=== 유튜브 업로드 권장 제목 ===\n{yt_title}\n\n")
        f.write(f"=== 유튜브 설명란 (복사하여 사용) ===\n{yt_description}\n")

    print(f"[+] 유튜브 메타데이터 저장 완료: {meta_txt_file}")

    return {
        "status": "success",
        "audio_file": str(out_audio),
        "video_file": str(out_video) if render_video and cover_image else None,
        "metadata_file": str(meta_txt_file),
        "total_tracks": len(playlist),
        "duration_seconds": actual_duration,
        "youtube_title": yt_title
    }


def main():
    parser = argparse.ArgumentParser(description="에이전트 루나 롱폼 컴필레이션 플레이리스트 생성기")
    parser.add_argument("--genre", type=str, default="lofi", choices=["lofi", "piano", "ambient", "sleep", "all_relax"],
                        help="필터링할 장르 (기본: lofi)")
    parser.add_argument("--minutes", type=int, default=60, help="목표 재생 시간(분) (기본: 60)")
    parser.add_argument("--title", type=str, default="Cozy Midnight Lo-Fi Room", help="컴필레이션 테마 제목")
    parser.add_argument("--no-video", action="store_true", help="비디오 렌더링을 건너뛰고 오디오만 생성")
    parser.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR), help="출력 디렉토리")

    args = parser.parse_args()

    print(f"=== [루나의 심야 서재] 롱폼 컴필레이션 제작 시작 ===")
    print(f"- 장르 필터: {args.genre}")
    print(f"- 목표 시간: {args.minutes}분 ({args.minutes * 60}초)")

    tracks = scan_available_tracks(args.genre)
    print(f"- 사용 가능한 매칭 트랙 수: {len(tracks)}곡")

    if not tracks:
        print(f"[경고] {args.genre} 장르와 일치하는 트랙이 없습니다. all_relax 로 재시도합니다.")
        tracks = scan_available_tracks("all_relax")
        print(f"- all_relax 대체 매칭 트랙 수: {len(tracks)}곡")

    if not tracks:
        print("[오류] data/luna_music 디렉토리에 사용할 수 있는 오디오 트랙이 없습니다.")
        sys.exit(1)

    result = assemble_compilation(
        tracks=tracks,
        target_seconds=args.minutes * 60.0,
        output_dir=Path(args.out_dir),
        compilation_title=args.title,
        render_video=not args.no_video
    )

    print(f"\n[완료] 롱폼 컴필레이션 생성이 성공적으로 끝났습니다!")
    print(f"- 제목: {result['youtube_title']}")
    print(f"- 총 재생 시간: {int(result['duration_seconds'] // 60)}분 {int(result['duration_seconds'] % 60)}초")
    print(f"- 메타데이터 파일: {result['metadata_file']}")


if __name__ == "__main__":
    main()
