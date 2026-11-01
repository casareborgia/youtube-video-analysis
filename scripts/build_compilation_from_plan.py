#!/usr/bin/env python3
"""
루나의 심야 서재 — 편성안 JSON 으로 주간 컴필레이션 만들기 (업로드 없음)

강화학습 시뮬레이터가 만든 편성안(예: ~/coding/강화학습시뮬레이터/data/youtube/luna/compilation_plan_2026-10-31.json)을
읽기만 해서, 주차 하나의 곡을 짧은 크로스페이드로 이어 붙이고 장르 대표 BGA 루프를 입혀 롱폼 영상을 만든다.
편성안 원소: {week, publish_date, theme, label, duration_s, tracks:[{start, track_id, title, audio_path, duration_s, first_release}]}

음량은 베가 기준(-14 LUFS / -1 dBTP)에 맞춘다: 곡마다 통합 음량을 재서 -14 LUFS 로 게인을 맞추고,
이어 붙인 뒤 샘플 피크 리미터(-2 dBFS, 인코딩 후 트루피크 여유)를 건다. 결과 음량은 다시 재서 기록한다.

산출물: data/luna_compilations/<publish_date>_<theme>/
- compilation_audio.mp3 / compilation_video.mp4
- youtube_metadata.json (scripts/upload_luna_compilation.py 입력과 같은 키) / youtube_metadata.txt
- build_report.json (곡별 측정 음량·게인, 실제 시작 시각, 최종 음량 검증)

업로드·예약·공개는 하지 않는다. 올릴 때는 사람이 확인한 뒤 upload_luna_compilation.py 로 따로 진행한다.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

import luna_engine  # noqa: E402  장르→대표 룸 매핑
from create_luna_compilation import (  # noqa: E402  기존 컴필레이션(HzfRkSiTyeI 계열)과 같은 표기를 쓴다
    BASE_TAGS, CHANNEL_SUBSCRIBE_URL, duration_label, format_timestamp, get_audio_duration, run_ffmpeg,
)

COMPILATIONS_DIR = BASE_DIR / "data" / "luna_compilations"

TARGET_LUFS = -14.0
TARGET_TP_DBTP = -1.0
LIMITER_CEILING_DBFS = -2.0  # 샘플 피크 기준. AAC/MP3 인코딩 뒤 트루피크가 -1 dBTP 를 넘지 않게 여유를 둔다
MAX_TRACK_GAIN_DB = 12.0
DEFAULT_CROSSFADE_S = 2.0
SAMPLE_RATE = 48000
DURATION_MISMATCH_S = 3.0  # 편성안 길이와 실제 길이 차이가 이보다 크면 경고
CHANNEL_NAME = "루나의 심야 서재"
AI_DISCLOSURE = "※ 이 영상의 음악과 배경 그림은 AI 도구(Google Lyria·Imagen 등)로 만들었습니다."

# 테마 → (제목 상황 문구, 이모지, 설명 첫 문단, 해시태그, 태그)
THEME_COPY = {
    "city_night": ("불 꺼진 도시의 밤, 창밖 야경과 듣는 시티팝·R&B", "🌃",
                   "불빛이 번지는 도심의 밤, 발코니 너머 야경을 바라보며 듣는 루나의 심야 서재 시티팝·신스웨이브·R&B 플레이리스트입니다. 🌃\n"
                   "늦은 퇴근길, 혼자 정리하는 밤, 드라이브에 함께 틀어두세요.",
                   "#시티팝 #RnB #CityPopPlaylist", ["시티팝", "알앤비", "신스웨이브", "CityPop", "NightDrive"]),
    "kindie_vocal": ("밤에 혼자 듣는 잔잔한 감성 보컬", "🌙",
                     "하루를 조용히 돌아보는 밤, 마음에 오래 남는 목소리를 모은 루나의 심야 서재 감성 플레이리스트입니다. 🌙",
                     "#감성플레이리스트 #밤에듣는노래 #인디감성", ["감성플레이리스트", "밤에듣는노래", "인디감성"]),
    "calm_instrumental": ("생각을 비우는 밤의 연주곡 (피아노·앰비언트·로파이)", "🌙",
                          "생각이 많은 밤, 말없이 곁을 지켜주는 루나의 심야 서재 연주곡 플레이리스트입니다. 🎹\n"
                          "공부·작업·잠들기 전 시간에 틀어두세요.",
                          "#연주곡 #새벽피아노 #로파이", ["연주곡", "새벽피아노", "로파이", "앰비언트"]),
}


# ── 편성안 읽기·검증 ─────────────────────────────────────────────────

def load_plan(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("편성안은 비어 있지 않은 리스트여야 합니다.")
    return data


def select_week(plan: List[Dict[str, Any]], week: Optional[int] = None,
                publish_date: Optional[str] = None) -> Dict[str, Any]:
    matches = [w for w in plan
               if (week is None or w.get("week") == week) and (publish_date is None or w.get("publish_date") == publish_date)]
    if len(matches) != 1:
        raise ValueError(f"주차를 하나로 고를 수 없습니다 (week={week}, publish_date={publish_date}, 일치 {len(matches)}개)")
    return matches[0]


def validate_week(entry: Dict[str, Any]) -> None:
    for key in ("week", "publish_date", "theme", "tracks"):
        if key not in entry:
            raise ValueError(f"편성안 주차에 {key} 가 없습니다.")
    tracks = entry["tracks"]
    if not isinstance(tracks, list) or len(tracks) < 2:
        raise ValueError("컴필레이션에는 곡이 2곡 이상 있어야 합니다.")
    ids = [t.get("track_id") for t in tracks]
    dup = [k for k, n in Counter(ids).items() if n > 1]
    if dup:
        raise ValueError(f"같은 주차에 같은 곡이 두 번 있습니다: {dup}")
    for t in tracks:
        for key in ("track_id", "title", "audio_path"):
            if not t.get(key):
                raise ValueError(f"트랙에 {key} 가 없습니다: {t}")


def output_dir_for(entry: Dict[str, Any], root: Path = COMPILATIONS_DIR) -> Path:
    return Path(root) / f"{entry['publish_date']}_{entry['theme']}"


# ── 타임라인·메타데이터 ─────────────────────────────────────────────────

def compute_timeline(durations: List[float], crossfade: float) -> List[float]:
    """크로스페이드만큼 겹치므로 i번째 곡 시작 = 앞 곡 시작 + 앞 곡 길이 - 크로스페이드."""
    starts, t = [], 0.0
    for i, d in enumerate(durations):
        starts.append(t)
        t += d - (crossfade if i < len(durations) - 1 else 0.0)
    return starts


def total_duration(durations: List[float], crossfade: float) -> float:
    return sum(durations) - crossfade * (len(durations) - 1)


def theme_copy(entry: Dict[str, Any]):
    if entry["theme"] in THEME_COPY:
        return THEME_COPY[entry["theme"]]
    label = entry.get("label") or entry["theme"]
    return (label, "🌙", f"{label} — 루나의 심야 서재 플레이리스트입니다. 🌙", "#플레이리스트", [])


def build_youtube_metadata(entry: Dict[str, Any], items: List[Dict[str, Any]], total_seconds: float) -> Dict[str, Any]:
    """items: [{title, start, first_release}] (start 는 실제 렌더 기준 초). ★ = 이 컴필레이션에서 처음 공개하는 곡."""
    phrase, emoji, intro, hashtags, theme_tags = theme_copy(entry)
    has_new = any(it["first_release"] for it in items)
    title = f"{duration_label(total_seconds)} {phrase} {emoji}{' (미발표곡 포함)' if has_new else ''} | {CHANNEL_NAME}"
    if len(title) > 100:  # 유튜브 제목 한도
        title = f"{duration_label(total_seconds)} {phrase} {emoji} | {CHANNEL_NAME}"
    lines = [f"{format_timestamp(it['start'])} {it['title']}{' ★' if it['first_release'] else ''}" for it in items]
    new_note = "\n★ 표시는 이 플레이리스트에서 처음 공개하는 곡입니다.\n" if has_new else ""
    description = f"""{intro}

[Tracklist / 타임라인]
{chr(10).join(lines)}
{new_note}
[Credits]
음악: 루나의 심야 서재 (Luna's Midnight Room)
{AI_DISCLOSURE}

채널 구독으로 루나의 따뜻한 서재에 매일 밤 머물러보세요 🐾
{CHANNEL_SUBSCRIBE_URL}

#루나의심야서재 #플레이리스트 #새벽감성 {hashtags}"""
    tags = list(dict.fromkeys(BASE_TAGS + theme_tags))[:15]
    return {
        "youtube_title": title,
        "youtube_description": description,
        "youtube_tags": tags,
        # 유튜브 '변경되거나 합성된 콘텐츠' 공개 (API: status.containsSyntheticMedia). 업로드 단계에서 켠다
        "contains_synthetic_media": True,
    }


def pick_visual_genre(genres: List[str]) -> str:
    """곡 장르 텍스트들 → 가장 많은 대표 룸 키 (동률이면 먼저 나온 곡의 룸)."""
    keys = [luna_engine.resolve_signature_bga(g or "")["genre_key"] for g in genres]
    if not keys:
        return "lofi"
    counts = Counter(keys)
    best = max(counts.values())
    return next(k for k in keys if counts[k] == best)


# ── 오디오 측정·합성 ─────────────────────────────────────────────────

def parse_loudnorm_json(stderr: str) -> Dict[str, float]:
    """ffmpeg loudnorm(print_format=json) stderr 끝의 JSON 블록을 읽는다."""
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end < start:
        raise ValueError("loudnorm 측정 결과를 찾을 수 없습니다.")
    raw = json.loads(stderr[start:end + 1])
    return {"i": float(raw["input_i"]), "tp": float(raw["input_tp"]), "lra": float(raw["input_lra"])}


def measure_loudness(path: Path) -> Dict[str, float]:
    """통합 음량(LUFS)·트루피크(dBTP)·LRA. 오디오가 든 영상 파일도 된다."""
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
         "-af", f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP_DBTP}:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"음량 측정 실패: {path}\n{(res.stderr or '')[-400:]}")
    return parse_loudnorm_json(res.stderr)


def track_gain_db(measured_lufs: float) -> float:
    return max(-MAX_TRACK_GAIN_DB, min(MAX_TRACK_GAIN_DB, TARGET_LUFS - measured_lufs))


def build_audio_filter(gains_db: List[float], crossfade: float) -> str:
    """입력마다 48k 스테레오 + 게인 → acrossfade 사슬 → 샘플 피크 리미터."""
    n = len(gains_db)
    parts = [f"[{i}:a]aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
             f"volume={g:.2f}dB[a{i}]" for i, g in enumerate(gains_db)]
    prev = "a0"
    for i in range(1, n):
        out = f"x{i}"
        parts.append(f"[{prev}][a{i}]acrossfade=d={crossfade}:c1=tri:c2=tri[{out}]")
        prev = out
    limit = 10 ** (LIMITER_CEILING_DBFS / 20)
    parts.append(f"[{prev}]alimiter=limit={limit:.4f}:attack=5:release=50:level=disabled[out]")
    return ";".join(parts)


def render_audio(audio_paths: List[str], gains_db: List[float], crossfade: float, out_path: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    for p in audio_paths:
        cmd += ["-i", os.path.abspath(p)]
    cmd += ["-filter_complex", build_audio_filter(gains_db, crossfade), "-map", "[out]", "-ar", str(SAMPLE_RATE)]
    if out_path.suffix == ".wav":
        cmd += ["-c:a", "pcm_s24le"]
    else:
        cmd += ["-c:a", "libmp3lame", "-b:a", "320k"]
    run_ffmpeg(cmd + [str(out_path)], "오디오 크로스페이드 합성")


def render_video(bga_video: str, master_wav: Path, duration: float, out_path: Path) -> None:
    """대표 BGA 루프(재인코딩 없이 복사) + AAC 320k. 스트림 복사가 안 되면 1080p 재인코딩."""
    head = ["ffmpeg", "-y", "-hide_banner", "-stream_loop", "-1", "-i", bga_video, "-i", str(master_wav),
            "-map", "0:v:0", "-map", "1:a:0"]
    tail = ["-c:a", "aac", "-b:a", "320k", "-ar", str(SAMPLE_RATE), "-t", f"{duration:.3f}", "-shortest",
            "-movflags", "+faststart", str(out_path)]
    try:
        run_ffmpeg(head + ["-c:v", "copy"] + tail, "BGA 루프(stream copy)")
    except RuntimeError as e:
        print(f"[!] 스트림 복사 불가 → 1080p 재인코딩\n    {e}")
        run_ffmpeg(head + ["-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"] + tail,
                   "BGA 루프(재인코딩)")


def _track_genre(audio_path: str) -> str:
    meta_file = Path(audio_path).parent / "meta.json"
    try:
        return json.loads(meta_file.read_text(encoding="utf-8")).get("genre") or ""
    except Exception:
        return ""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ── 조립 ─────────────────────────────────────────────────────────────

def build_compilation(plan_path: Path, entry: Dict[str, Any], out_dir: Path, crossfade: float = DEFAULT_CROSSFADE_S,
                      render_video_file: bool = True) -> Dict[str, Any]:
    validate_week(entry)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg가 설치되어 있지 않습니다.")
    tracks = entry["tracks"]
    missing = [t["audio_path"] for t in tracks if not Path(t["audio_path"]).is_file()]
    if missing:
        raise FileNotFoundError(f"오디오 파일이 없습니다: {missing}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 곡별 실제 길이·음량 측정 → 게인
    warnings, measured = [], []
    for t in tracks:
        dur = get_audio_duration(t["audio_path"])
        if dur <= crossfade * 2:
            raise ValueError(f"길이 측정 실패 또는 너무 짧은 곡: {t['track_id']} ({dur:.2f}s)")
        if t.get("duration_s") and abs(dur - float(t["duration_s"])) > DURATION_MISMATCH_S:
            warnings.append(f"{t['track_id']}: 편성안 길이 {t['duration_s']}s ≠ 실제 {dur:.1f}s")
        loud = measure_loudness(Path(t["audio_path"]))
        measured.append({"duration": dur, "loudness": loud, "gain_db": round(track_gain_db(loud["i"]), 2)})
        print(f"[*] {t['track_id']} {dur:6.1f}s  {loud['i']:6.2f} LUFS  TP {loud['tp']:5.2f}  → {measured[-1]['gain_db']:+.2f} dB")

    durations = [m["duration"] for m in measured]
    starts = compute_timeline(durations, crossfade)

    # 2. 오디오 — 24bit WAV 마스터(영상용, 작업 후 삭제) + 320k MP3(보관용)
    out_audio = out_dir / "compilation_audio.mp3"
    out_video = out_dir / "compilation_video.mp4"
    with tempfile.TemporaryDirectory(dir=str(out_dir), prefix="_work_") as work:
        master_wav = Path(work) / "master.wav"
        print(f"[*] 크로스페이드 {crossfade}s · {len(tracks)}곡 합성 → {master_wav.name}")
        render_audio([t["audio_path"] for t in tracks], [m["gain_db"] for m in measured], crossfade, master_wav)
        actual = get_audio_duration(master_wav) or total_duration(durations, crossfade)
        run_ffmpeg(["ffmpeg", "-y", "-hide_banner", "-i", str(master_wav), "-c:a", "libmp3lame", "-b:a", "320k",
                    str(out_audio)], "MP3 인코딩")

        # 3. 영상 — 곡 장르 다수결 대표 룸의 BGA 루프
        visual_key = pick_visual_genre([_track_genre(t["audio_path"]) for t in tracks])
        sig = luna_engine.resolve_signature_bga(visual_key, ensure_exists=render_video_file)
        if render_video_file:
            if not sig.get("video_path"):
                raise RuntimeError(f"대표 BGA 영상이 없습니다 ({sig['room_name']}). --bga-dir 를 확인하세요.")
            print(f"[*] 대표 BGA({sig['room_name']}) 루프 합성 → {out_video}")
            render_video(sig["video_path"], master_wav, actual, out_video)

    # 4. 최종 음량 검증 (영상이 있으면 실제로 올라갈 AAC 기준)
    final_loud = measure_loudness(out_video if render_video_file else out_audio)
    loud_ok = abs(final_loud["i"] - TARGET_LUFS) <= 1.0 and final_loud["tp"] <= TARGET_TP_DBTP
    if not loud_ok:
        warnings.append(f"최종 음량이 목표를 벗어남: {final_loud['i']} LUFS / {final_loud['tp']} dBTP")

    items = [{"title": t["title"], "start": s, "first_release": bool(t.get("first_release"))} for t, s in zip(tracks, starts)]
    meta = build_youtube_metadata(entry, items, actual)
    meta.update({
        "genre": f"{entry['publish_date']}_{entry['theme']}",
        "theme": entry["theme"],
        "week": entry["week"],
        "publish_date": entry["publish_date"],
        "format": "compilation_1h" if actual >= 3600 else "compilation_long",
        "room_name": sig["room_name"],
        "video_file": str(out_video) if render_video_file else None,
        "audio_file": str(out_audio),
        "thumbnail_file": sig.get("thumbnail_path"),
        "duration_seconds": round(actual, 2),
        "tracks": [{"track_id": t["track_id"], "title": t["title"], "start_seconds": round(s, 2),
                    "start": format_timestamp(s), "first_release": bool(t.get("first_release"))}
                   for t, s in zip(tracks, starts)],
        "upload_status": "not_uploaded",  # 드라이런 산출물. 업로드는 사람이 확인 후 별도로
    })
    (out_dir / "youtube_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "youtube_metadata.txt").write_text(
        f"=== 제목 ===\n{meta['youtube_title']}\n\n=== 설명란 ===\n{meta['youtube_description']}\n\n"
        f"=== 태그 ===\n{', '.join(meta['youtube_tags'])}\n\n=== 공개 설정 ===\n변경되거나 합성된 콘텐츠: 예 (AI 생성)\n",
        encoding="utf-8")

    report = {
        "plan_file": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "week": entry["week"],
        "publish_date": entry["publish_date"],
        "theme": entry["theme"],
        "crossfade_s": crossfade,
        "target": {"lufs": TARGET_LUFS, "true_peak_dbtp": TARGET_TP_DBTP, "limiter_ceiling_dbfs": LIMITER_CEILING_DBFS},
        "plan_duration_s": entry.get("duration_s"),
        "actual_duration_s": round(actual, 2),
        "final_loudness": final_loud,
        "final_loudness_ok": loud_ok,
        "tracks": [{"track_id": t["track_id"], "plan_start": t.get("start"), "actual_start": format_timestamp(s),
                    "duration_s": round(m["duration"], 2), "input_lufs": m["loudness"]["i"],
                    "input_tp": m["loudness"]["tp"], "gain_db": m["gain_db"], "audio_path": t["audio_path"]}
                   for t, s, m in zip(tracks, starts, measured)],
        "warnings": warnings,
        "uploaded": False,
    }
    (out_dir / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"metadata": meta, "report": report}


def main():
    parser = argparse.ArgumentParser(description="편성안 JSON → 루나 주간 컴필레이션 (업로드 없음)")
    parser.add_argument("--plan", required=True, help="편성안 JSON 경로 (읽기만 한다)")
    parser.add_argument("--week", type=int, default=None, help="주차 번호")
    parser.add_argument("--publish-date", default=None, help="YYYY-MM-DD (주차 대신 또는 함께)")
    parser.add_argument("--crossfade", type=float, default=DEFAULT_CROSSFADE_S, help="곡 사이 크로스페이드(초)")
    parser.add_argument("--out-root", default=None, help="출력 루트 (기본: data/luna_compilations)")
    parser.add_argument("--bga-dir", default=None, help="대표 BGA·썸네일 폴더 (기본: data/bga_assets)")
    parser.add_argument("--no-video", action="store_true", help="오디오·메타데이터만")
    parser.add_argument("--plan-only", action="store_true", help="제목·타임라인만 출력 (파일 생성 없음, 편성안 길이 기준)")
    args = parser.parse_args()

    plan_path = Path(args.plan).expanduser()
    entry = select_week(load_plan(plan_path), args.week, args.publish_date)
    validate_week(entry)
    if args.bga_dir:
        luna_engine.BGA_ASSETS_DIR = str(Path(args.bga_dir).expanduser())

    if args.plan_only:
        durs = [float(t.get("duration_s") or 0) for t in entry["tracks"]]
        starts = compute_timeline(durs, args.crossfade)
        items = [{"title": t["title"], "start": s, "first_release": bool(t.get("first_release"))}
                 for t, s in zip(entry["tracks"], starts)]
        meta = build_youtube_metadata(entry, items, total_duration(durs, args.crossfade))
        print(f"제목: {meta['youtube_title']}\n\n{meta['youtube_description']}\n\n태그: {', '.join(meta['youtube_tags'])}")
        return

    out_dir = output_dir_for(entry, Path(args.out_root).expanduser() if args.out_root else COMPILATIONS_DIR)
    res = build_compilation(plan_path, entry, out_dir, args.crossfade, render_video_file=not args.no_video)
    meta, report = res["metadata"], res["report"]
    print(f"\n[완료] {meta['youtube_title']}\n- 길이: {int(meta['duration_seconds'] // 60)}분 {int(meta['duration_seconds'] % 60)}초"
          f"\n- 최종 음량: {report['final_loudness']['i']} LUFS / {report['final_loudness']['tp']} dBTP"
          f"\n- 출력: {out_dir}\n- 업로드: 하지 않음")
    for w in report["warnings"]:
        print(f"[!] {w}")


if __name__ == "__main__":
    main()
