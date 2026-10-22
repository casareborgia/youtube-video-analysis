#!/usr/bin/env python3
"""
루나의 심야 서재 — 장르별 롱폼 컴필레이션(플레이리스트) 생성 유틸리티

data/luna_music 의 트랙을 장르 대표 룸(luna_engine.resolve_signature_bga) 기준으로 골라
오디오를 이어 붙이고, 같은 룸의 대표 BGA 루프 영상을 입혀 롱폼 비디오(MP4)를 만든다.
기본은 각 곡을 한 번씩만 싣는다(길이를 억지로 1시간에 맞추지 않음). --minutes 를 주면 그 길이까지 순환 반복.

산출물은 data/luna_compilations/<장르>/ 에 저장한다 (기존 로파이 1시간본은 data/luna_compilations/ 루트에 그대로 둔다).
- compilation_audio.mp3 / compilation_video.mp4
- youtube_metadata.json (업로드 스크립트 입력) / youtube_metadata.txt (사람이 읽는 용)
"""

import os
import sys
import json
import hashlib
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import luna_engine  # noqa: E402  장르→대표 룸 매핑을 엔진과 하나로 쓴다

DATA_DIR = BASE_DIR / "data"
LUNA_DIR = DATA_DIR / "luna_music"
COMPILATIONS_DIR = DATA_DIR / "luna_compilations"

CHANNEL_SUBSCRIBE_URL = luna_engine.LUNA_CHANNEL_SUBSCRIBE_URL

# 묶음 장르 → (포함할 룸 키, 영상·썸네일로 쓸 룸 키)
GROUP_GENRES = {
    "all_relax": (("lofi", "piano", "ambient", "sleep"), "lofi"),
    "all_sleep": (("piano", "ambient", "sleep"), "piano"),
}

# 장르 → (제목 상황 문구, 이모지, 설명 첫 문단, 해시태그, 태그)
GENRE_COPY = {
    "lofi": ("오늘 밤 생각 비우고 푹 쉬고 싶을 때 듣는 로파이", "🌧️",
             "지친 하루의 끝, 조용한 위로와 온전한 쉼이 필요할 때 틀어두는 루나의 심야 서재 로파이 플레이리스트입니다. 🌙\n불을 끄고 침대에서, 혹은 깊은 공부와 작업 몰입에 함께하세요.",
             "#로파이 #Chillhop #LoFiPlaylist", ["로파이", "Chillhop", "LoFiPlaylist", "공부할때듣는음악"]),
    "piano": ("잠 못 드는 새벽, 마음을 가만히 쓰다듬는 피아노", "🌙",
              "달빛이 스미는 창가, 오래된 피아노 앞에서 하루를 천천히 내려놓는 루나의 심야 서재 피아노 플레이리스트입니다. 🎹\n잠들기 전, 혹은 조용히 생각을 정리하고 싶은 밤에 틀어두세요.",
              "#새벽피아노 #피아노연주곡 #PianoPlaylist", ["새벽피아노", "피아노연주곡", "감성피아노", "PianoPlaylist", "잔잔한피아노"]),
    "ambient": ("깊은 밤 생각을 내려놓고 잠드는 앰비언트", "🌌",
                "도시의 불빛마저 잦아든 자정, 넓게 퍼지는 공간의 울림 속에 몸을 맡기는 루나의 심야 서재 앰비언트 플레이리스트입니다. 🌌\n잠들기 전, 명상이나 깊은 몰입이 필요한 시간에 함께하세요.",
                "#앰비언트 #명상음악 #AmbientPlaylist", ["앰비언트", "AmbientMusic", "명상음악", "AmbientPlaylist", "잠잘때듣는음악"]),
    "sleep": ("깊은 잠으로 데려가는 수면 음악", "🌙",
              "포근한 안식처에서 긴장을 풀고 깊은 잠에 드는 루나의 심야 서재 수면 플레이리스트입니다. 🌙",
              "#수면음악 #SleepBGM #DeepSleep", ["수면음악", "DeepSleep", "잠잘때듣는음악"]),
    "jazz": ("늦은 밤 재즈 카페에 홀로 앉아 듣는 재즈", "🎷",
             "불빛이 낮게 깔린 심야 재즈 카페, 루나의 심야 서재 재즈 플레이리스트입니다. 🎷",
             "#재즈 #카페음악 #JazzPlaylist", ["재즈", "카페음악", "JazzPlaylist"]),
    "acoustic": ("햇살 드는 다락방에서 듣는 어쿠스틱", "☀️",
                 "햇살이 스미는 다락방, 따뜻한 기타 선율의 루나의 심야 서재 어쿠스틱 플레이리스트입니다. ☀️",
                 "#어쿠스틱 #통기타 #AcousticPlaylist", ["어쿠스틱", "통기타", "AcousticPlaylist"]),
    "chill": ("도심 야경을 내려다보며 듣는 칠 플레이리스트", "🌃",
              "불빛이 번지는 도심 발코니, 루나의 심야 서재 칠 플레이리스트입니다. 🌃",
              "#칠아웃 #시티팝 #ChillPlaylist", ["칠아웃", "시티팝", "ChillPlaylist"]),
}
GROUP_COPY = {
    "all_relax": ("하루 끝에 틀어두는 휴식 음악 모음", "🌙", GENRE_COPY["lofi"][2], "#로파이 #새벽피아노 #힐링음악", ["로파이", "새벽피아노", "힐링음악"]),
    "all_sleep": ("잠들기 전 듣는 피아노 & 앰비언트 모음", "🌙", GENRE_COPY["piano"][2], "#수면음악 #새벽피아노 #SleepBGM", ["수면음악", "새벽피아노", "앰비언트"]),
}
# resolve_signature_bga 가 돌려주는 룸 키 (SIGNATURE_BGA_MAP 의 'rnb-chill' 같은 별칭은 제외)
GENRE_CHOICES = tuple(GENRE_COPY) + tuple(GROUP_GENRES)
BASE_TAGS = ["루나의심야서재", "LunasMidnightRoom", "플레이리스트", "수면음악", "새벽감성", "힐링음악", "SleepBGM", "BGM"]
AUDIO_CANDIDATES = ("audio_mastered.wav", "audio_mastered_preview.mp3", "audio.mp3", "audio_raw.mp3")


def run_ffmpeg(cmd: List[str], label: str) -> None:
    """ffmpeg 실행. 실패 시 stderr 마지막 줄들을 담아 예외를 던진다 (DEVNULL 로 묻히면 원인 추적 불가)."""
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        tail = "\n".join((res.stderr or "").strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg {label} 실패 (code {res.returncode}):\n{tail}")


def get_audio_duration(file_path) -> float:
    """ffprobe 로 재생 길이(초)를 잰다. 측정 실패 시 0 — 타임라인이 틀어지지 않도록 그 곡은 제외된다."""
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
            capture_output=True, text=True, check=True,
        )
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def room_keys_for(genre: str):
    """장르 인자 → (포함할 룸 키 집합, 영상·썸네일 룸 키)."""
    if genre in GROUP_GENRES:
        keys, visual = GROUP_GENRES[genre]
        return set(keys), visual
    if genre not in GENRE_COPY:
        raise ValueError(f"알 수 없는 장르: {genre} (선택: {', '.join(GENRE_CHOICES)})")
    return {genre}, genre


def scan_available_tracks(genre: str = "lofi", luna_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """장르 대표 룸이 일치하는 트랙을 생성 순(track_id 순)으로 반환한다."""
    keys, _ = room_keys_for(genre)
    tracks, seen_audio = [], {}
    for track_dir in sorted(Path(luna_dir or LUNA_DIR).glob("luna_*")):
        meta_file = track_dir / "meta.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if luna_engine.resolve_signature_bga(meta.get("genre") or "")["genre_key"] not in keys:
            continue
        audio_file = next((track_dir / c for c in AUDIO_CANDIDATES
                           if (track_dir / c).exists() and (track_dir / c).stat().st_size > 10000), None)
        if not audio_file:
            continue
        # 같은 음원이 트랙 폴더만 달리 두 번 저장된 경우가 있다 (예: Aetherial Drift) — 바이트가 같으면 한 번만 싣는다
        digest = hashlib.md5(audio_file.read_bytes()).hexdigest()
        if digest in seen_audio:
            print(f"[!] 같은 음원 중복 제외: {track_dir.name} (= {seen_audio[digest]})")
            continue
        seen_audio[digest] = track_dir.name
        duration = get_audio_duration(audio_file)
        if duration <= 0:
            print(f"[!] 길이 측정 실패로 제외: {track_dir.name} ({audio_file.name})")
            continue
        tracks.append({
            "track_id": track_dir.name,
            "title": meta.get("title") or track_dir.name,
            "genre": meta.get("genre") or "",
            "audio_file": str(audio_file),
            "duration": duration,
            "released": bool(meta.get("uploaded_video_id")),  # 단곡으로 이미 올라갔는지 (아니면 컴필레이션 최초 공개)
        })
    return tracks


def build_playlist(tracks: List[Dict[str, Any]], target_seconds: float = 0) -> List[Dict[str, Any]]:
    """target_seconds 가 0 이면 각 곡 한 번씩. 양수면 그 길이를 넘길 때까지 순환 반복."""
    if not tracks:
        raise ValueError("선별된 트랙이 없습니다.")
    if target_seconds <= 0:
        return list(tracks)
    playlist, total = [], 0.0
    while total < target_seconds:
        for t in tracks:
            playlist.append(t)
            total += t["duration"]
            if total >= target_seconds:
                break
    return playlist


def format_timestamp(seconds: float) -> str:
    """초를 MM:SS 또는 HH:MM:SS 타임라인 형식으로 변환합니다."""
    hrs, mins, secs = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"


def duration_label(seconds: float) -> str:
    hours = int(seconds // 3600)
    if hours >= 1:
        return "[1 Hour Playlist]" if hours == 1 else f"[{hours} Hours Playlist]"
    return f"[{int(seconds // 60)} Min Playlist]"


def build_youtube_metadata(genre: str, playlist: List[Dict[str, Any]], total_seconds: float,
                           channel_name: str = "루나의 심야 서재") -> Dict[str, Any]:
    """제목·설명(타임라인)·태그. 단곡으로 아직 올라가지 않은 곡은 ★ 로 '플레이리스트 최초 공개' 표시."""
    phrase, emoji, intro, hashtags, genre_tags = (GROUP_COPY.get(genre) or GENRE_COPY[genre])
    has_new = any(not t["released"] for t in playlist)
    title = f"{duration_label(total_seconds)} {phrase} {emoji}{' (미발표곡 포함)' if has_new else ''} | {channel_name}"
    if len(title) > 100:  # 유튜브 제목 한도
        title = f"{duration_label(total_seconds)} {phrase} {emoji} | {channel_name}"

    lines, t = [], 0.0
    for item in playlist:
        lines.append(f"{format_timestamp(t)} {item['title']}{'' if item['released'] else ' ★'}")
        t += item["duration"]
    new_note = "\n★ 표시는 이 플레이리스트에서 처음 공개하는 곡입니다.\n" if has_new else ""

    description = f"""{intro}

[Tracklist / 타임라인]
{chr(10).join(lines)}
{new_note}
[Credits]
음악: 루나의 심야 서재 (Luna's Midnight Room)

채널 구독으로 루나의 따뜻한 서재에 매일 밤 머물러보세요 🐾
{CHANNEL_SUBSCRIBE_URL}

#루나의심야서재 #플레이리스트 #수면음악 #새벽감성 {hashtags}"""
    tags = list(dict.fromkeys(BASE_TAGS + genre_tags))[:15]
    return {"youtube_title": title, "youtube_description": description, "youtube_tags": tags}


def assemble_compilation(tracks: List[Dict[str, Any]], genre: str, target_seconds: float = 0,
                         output_dir: Optional[Path] = None, render_video: bool = True) -> Dict[str, Any]:
    """오디오 concat → 대표 BGA 루프 합성 → 업로드용 메타데이터 저장."""
    output_dir = Path(output_dir or COMPILATIONS_DIR / genre)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg가 설치되어 있지 않습니다.")

    playlist = build_playlist(tracks, target_seconds)
    print(f"[*] {len(playlist)}곡 배치 (고유 {len({t['track_id'] for t in playlist})}곡)")

    # 1. 오디오 — 트랙마다 포맷이 다를 수 있다(audio_mastered.wav 48k / audio.mp3 44.1k 혼재).
    # concat demuxer 는 코덱·샘플레이트가 같아야 해서, 입력별로 44.1kHz 스테레오로 맞춘 뒤 filter_complex concat 으로 묶는다.
    out_audio = output_dir / "compilation_audio.mp3"
    cmd_audio = ["ffmpeg", "-y"]
    for item in playlist:
        cmd_audio += ["-i", os.path.abspath(item["audio_file"])]
    n = len(playlist)
    parts = [f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]" for i in range(n)]
    parts.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]")
    cmd_audio += ["-filter_complex", ";".join(parts), "-map", "[out]",
                  "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", str(out_audio)]
    print(f"[*] 오디오 concat -> {out_audio}")
    run_ffmpeg(cmd_audio, "오디오 concat")
    actual_duration = get_audio_duration(out_audio) or sum(t["duration"] for t in playlist)

    # 2. 비디오 — 장르 대표 룸 BGA 루프 (엔진과 같은 1:1 매핑). 없으면 커버로 바꾸지 않고 중단한다.
    _, visual_key = room_keys_for(genre)
    sig = luna_engine.resolve_signature_bga(visual_key, ensure_exists=render_video)
    out_video = output_dir / "compilation_video.mp4"
    if render_video:
        if not sig.get("video_path"):
            raise RuntimeError(f"대표 BGA 영상이 없습니다 ({sig['room_name']}). scripts/generate_signature_bga_assets.py 로 먼저 생성하세요.")
        head = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", sig["video_path"], "-i", str(out_audio), "-map", "0:v:0", "-map", "1:a:0"]
        tail = ["-c:a", "aac", "-b:a", "320k", "-t", f"{actual_duration:.3f}", "-shortest", "-movflags", "+faststart", str(out_video)]
        print(f"[*] 대표 BGA({sig['room_name']}) 루프 합성 -> {out_video}")
        try:
            # 재인코딩 없이 복사 → 화질 손실 0, 1시간도 수 분 내 조립
            run_ffmpeg(head + ["-c:v", "copy"] + tail, "BGA 루프(stream copy)")
        except RuntimeError as e:
            print(f"[!] 스트림 복사 불가 → 1080p 재인코딩\n    {e}")
            run_ffmpeg(head + ["-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p"] + tail,
                       "BGA 루프(재인코딩)")

    # 3. 메타데이터
    meta = build_youtube_metadata(genre, playlist, actual_duration)
    meta.update({
        "genre": genre,
        "room_name": sig["room_name"],
        "video_file": str(out_video) if render_video else None,
        "audio_file": str(out_audio),
        "thumbnail_file": sig.get("thumbnail_path"),
        "duration_seconds": round(actual_duration, 2),
        "tracks": [{"track_id": t["track_id"], "title": t["title"], "released": t["released"]} for t in playlist],
    })
    (output_dir / "youtube_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "youtube_metadata.txt").write_text(
        f"=== 제목 ===\n{meta['youtube_title']}\n\n=== 설명란 ===\n{meta['youtube_description']}\n\n=== 태그 ===\n{', '.join(meta['youtube_tags'])}\n",
        encoding="utf-8")
    print(f"[+] 메타데이터 저장: {output_dir / 'youtube_metadata.json'}")
    return meta


def main():
    parser = argparse.ArgumentParser(description="루나의 심야 서재 장르별 롱폼 컴필레이션 생성기")
    parser.add_argument("--genre", default="lofi", choices=GENRE_CHOICES, help="장르 대표 룸 키 또는 묶음(all_relax·all_sleep)")
    parser.add_argument("--minutes", type=int, default=0, help="목표 길이(분). 0(기본)이면 각 곡 한 번씩, 반복 없음")
    parser.add_argument("--no-video", action="store_true", help="비디오 없이 오디오·메타데이터만")
    parser.add_argument("--dry-run", action="store_true", help="곡 목록·제목만 출력하고 파일은 만들지 않음")
    parser.add_argument("--out-dir", default=None, help="출력 디렉토리 (기본: data/luna_compilations/<장르>)")
    args = parser.parse_args()

    tracks = scan_available_tracks(args.genre)
    print(f"=== [루나의 심야 서재] {args.genre} 컴필레이션 — 매칭 {len(tracks)}곡, "
          f"고유 합계 {sum(t['duration'] for t in tracks) / 60:.1f}분 ===")
    if not tracks:
        print("[오류] 조건에 맞는 트랙이 없습니다.")
        sys.exit(1)

    if args.dry_run:
        playlist = build_playlist(tracks, args.minutes * 60)
        meta = build_youtube_metadata(args.genre, playlist, sum(t["duration"] for t in playlist))
        print(f"\n제목: {meta['youtube_title']}\n\n{meta['youtube_description']}\n\n태그: {', '.join(meta['youtube_tags'])}")
        return

    meta = assemble_compilation(tracks, args.genre, args.minutes * 60,
                                Path(args.out_dir) if args.out_dir else None, render_video=not args.no_video)
    print(f"\n[완료] {meta['youtube_title']}\n- 길이: {int(meta['duration_seconds'] // 60)}분 {int(meta['duration_seconds'] % 60)}초"
          f"\n- 영상: {meta['video_file']}\n- 썸네일: {meta['thumbnail_file']}")


if __name__ == "__main__":
    main()
