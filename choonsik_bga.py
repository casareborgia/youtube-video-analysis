import os
import re
import json
import time
import shutil
import mimetypes
import datetime
import subprocess
from typing import Callable, Optional

import luna_engine
import vega_engine
import producer
import llm_client

BGA_DIR_NAME = "bga"                      # data/luna_music/<id>/bga/
BGA_CLIP_SECONDS = 8
BGA_N_SHOTS = 3
BGA_MAX_CLIPS_PER_TRACK = 3
BGA_DEFAULT_DAILY_CAP = 12                # env BGA_MAX_CLIPS_PER_DAY 로 덮어씀
BGA_XFADE_SECONDS = 1.0
BGA_POLL_INTERVAL = 10                    # 초
BGA_POLL_TIMEOUT = 300                    # 초
BGA_RATE_PER_SEC = {"720p": 0.08, "1080p": 0.10}   # USD, 무오디오, 2차 출처 — 공식 단가 아님
BGA_USAGE_FILE = os.path.join(luna_engine.DATA_DIR, "bga_usage.json")

BGA_CAMERA_MOVES = [
    "very slow push-in dolly toward the focal subject",
    "slow lateral drift with gentle parallax between foreground and background",
    "slow pull-back revealing more of the scene",
]
BGA_LIGHTING = "soft volumetric light, global illumination, subtle cinematic film grain"
BGA_GRADING_BY_GENRE = {
    "lofi": "muted nostalgic warm tones", "piano": "muted nostalgic warm tones", "acoustic": "muted nostalgic warm tones",
    "ambient": "cool desaturated deep blue", "sleep": "cool desaturated deep blue", "dark-ambient": "cool desaturated deep blue",
    "synthwave": "teal and magenta neon", "citypop": "teal and magenta neon",
    "jazz": "warm amber low-key", "rnb-chill": "warm amber low-key",
}
BGA_PROMPT_SUFFIX = ("No people, no text, no logos, no camera shake, clean lens, no vignette, no lens condensation, "
                     "seamless slow motion suitable for looping, start exactly from the reference image")


def daily_cap() -> int:
    return int(os.getenv("BGA_MAX_CLIPS_PER_DAY", str(BGA_DEFAULT_DAILY_CAP)))


def _read_usage_data() -> dict:
    if not os.path.exists(BGA_USAGE_FILE):
        return {}
    try:
        with open(BGA_USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_usage_data(data: dict):
    os.makedirs(os.path.dirname(BGA_USAGE_FILE), exist_ok=True)
    with open(BGA_USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today_usage() -> int:
    today_key = datetime.date.today().isoformat()
    data = _read_usage_data()
    val = data.get(today_key, 0)
    return int(val) if isinstance(val, (int, float)) else 0


def _increment_usage(n: int = 1):
    today_key = datetime.date.today().isoformat()
    data = _read_usage_data()
    current = int(data.get(today_key, 0)) if isinstance(data.get(today_key), (int, float)) else 0
    data[today_key] = current + n
    _write_usage_data(data)


def estimate_bga_cost(n_shots: int = BGA_N_SHOTS, duration: int = BGA_CLIP_SECONDS, resolution: str = None) -> dict:
    res = resolution or os.getenv("BGA_RESOLUTION", "720p")
    rate = BGA_RATE_PER_SEC.get(res, BGA_RATE_PER_SEC["720p"])
    total_sec = n_shots * duration
    cost = round(total_sec * rate, 2)
    return {
        "usd": cost,
        "clips": n_shots,
        "seconds": total_sec,
        "resolution": res,
        "rate_per_sec": rate,
        "rate_source": "secondary",
    }


def _build_template_shot(base_prompt: str, index: int, grading: str) -> dict:
    cam = BGA_CAMERA_MOVES[index % len(BGA_CAMERA_MOVES)]
    prompt = f"{base_prompt}. Camera: {cam}. Lighting: {BGA_LIGHTING}. Color grading: {grading}. {BGA_PROMPT_SUFFIX}"
    return {
        "index": index,
        "camera": cam,
        "prompt": prompt,
        "source": "template",
    }


def plan_bga_shots(track_data: dict, n_shots: int = BGA_N_SHOTS) -> list:
    visual_prompt = (track_data.get("visual_prompt") or track_data.get("story") or track_data.get("title") or "Cinematic ambient music background").strip()
    genre_raw = track_data.get("genre", "")
    genre_key = vega_engine.resolve_genre_key(genre_raw) if hasattr(vega_engine, "resolve_genre_key") else "ambient"
    grading = BGA_GRADING_BY_GENRE.get(genre_key, "muted nostalgic warm tones")
    
    bpm_match = re.search(r"(\d+)\s*BPM", track_data.get("lyria_prompt") or "", re.IGNORECASE)
    bpm_info = f" (BPM: {bpm_match.group(1)})" if bpm_match else ""
    mood = track_data.get("mood", "")

    shots = None
    system_prompt = (
        "You are an expert cinematic visual director specializing in generating seamless background video (BGA) prompts for Veo 3.1.\n"
        f"You must create exactly {n_shots} sequential shots for ambient looping music videos.\n"
        "Return ONLY a valid JSON object in the format:\n"
        '{"shots": [{"camera": "<camera move description>", "prompt": "<detailed visual prompt for Veo 3.1>"}]}'
    )
    user_prompt = (
        f"Scene Base Concept: {visual_prompt}\n"
        f"Genre: {genre_raw} (Style: {grading}){bpm_info}\n"
        f"Mood: {mood}\n"
        f"Required Camera Moves for the {n_shots} shots:\n"
        + "\n".join(f"- Shot {i}: {BGA_CAMERA_MOVES[i % len(BGA_CAMERA_MOVES)]}" for i in range(n_shots))
    )

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        parsed, raw = llm_client.call_llm_json(messages, max_tokens=1500, temperature=0.6)
        if isinstance(parsed, dict) and "shots" in parsed and isinstance(parsed["shots"], list):
            llm_shots = parsed["shots"]
            if len(llm_shots) == n_shots:
                validated = []
                for i, s in enumerate(llm_shots):
                    cam = BGA_CAMERA_MOVES[i % len(BGA_CAMERA_MOVES)]
                    p = s.get("prompt") or visual_prompt
                    if BGA_PROMPT_SUFFIX not in p:
                        p = f"{p.rstrip('.')}. Lighting: {BGA_LIGHTING}. Color grading: {grading}. {BGA_PROMPT_SUFFIX}"
                    validated.append({
                        "index": i,
                        "camera": cam,
                        "prompt": p,
                        "source": "llm",
                    })
                shots = validated
    except Exception as e:
        print(f"[ChoonsikBGA] LLM shot planning failed: {e}")

    if not shots:
        shots = [_build_template_shot(visual_prompt, i, grading) for i in range(n_shots)]

    track_data.setdefault("bga", {})
    track_data["bga"]["shots"] = shots
    track_data["bga"]["planned_at"] = time.time()
    luna_engine.save_track(track_data)
    return shots


def _make_vertex_client():
    project = os.environ.get("GCP_PROJECT")
    if not project:
        raise RuntimeError("GCP_PROJECT 미설정")
    location = os.getenv("GCP_VIDEO_LOCATION", "us-central1")
    from google import genai
    return genai.Client(vertexai=True, project=project, location=location)


def generate_bga_clips(track_data: dict, shots: list = None, progress_cb=None, dry_run: bool = False, client=None, sleep_fn=time.sleep) -> dict:
    def step(pct, msg):
        if progress_cb:
            progress_cb("bga_generate", msg, pct)
        print(f"[{pct}%] [ChoonsikBGA] {msg}")

    if shots is None:
        shots = (track_data.get("bga") or {}).get("shots")
        if not shots:
            shots = plan_bga_shots(track_data)

    if len(shots) > BGA_MAX_CLIPS_PER_TRACK:
        raise ValueError(f"트랙당 BGA 클립 수는 최대 {BGA_MAX_CLIPS_PER_TRACK}개입니다. (요청: {len(shots)})")

    current_usage = get_today_usage()
    cap = daily_cap()
    if current_usage + len(shots) > cap:
        raise RuntimeError(f"일일 Veo 클립 상한({cap}개)을 초과합니다. (현재 사용: {current_usage}, 요청: {len(shots)})")

    track_id = track_data.get("track_id")
    if not track_id:
        raise ValueError("유효한 트랙 ID가 없습니다.")

    t_dir = os.path.join(luna_engine.LUNA_DIR, track_id)
    cover_file = track_data.get("cover_file") or os.path.join(t_dir, "cover.jpg")
    if not os.path.exists(cover_file):
        raise FileNotFoundError(f"커버 이미지 파일이 없습니다: {cover_file}")

    bga = dict(track_data.get("bga") or {})
    if dry_run:
        step(100, f"BGA 생성 드라이런 완료 (샷 {len(shots)}개, 과금 호출 없음)")
        bga.update({
            "dry_run": True,
            "estimate": estimate_bga_cost(len(shots)),
            "shots": shots,
        })
        track_data["bga"] = bga
        luna_engine.save_track(track_data)
        return track_data

    if client is None:
        client = _make_vertex_client()

    from google.genai import types

    bga_dir = os.path.join(t_dir, BGA_DIR_NAME)
    os.makedirs(bga_dir, exist_ok=True)

    with open(cover_file, "rb") as cf:
        cover_bytes = cf.read()
    cover_mime = mimetypes.guess_type(cover_file)[0] or "image/jpeg"
    img = types.Image(image_bytes=cover_bytes, mime_type=cover_mime)

    cfg_kwargs = {
        "aspect_ratio": "16:9",
        "duration_seconds": BGA_CLIP_SECONDS,
        "number_of_videos": 1,
        "generate_audio": False,
    }
    if os.getenv("BGA_RESOLUTION") == "1080p":
        cfg_kwargs["resolution"] = "1080p"
    cfg = types.GenerateVideosConfig(**cfg_kwargs)

    model_name = os.getenv("BGA_VEO_MODEL", "veo-3.1-fast-generate-001")
    clips_record = dict(bga.get("clips") or {})
    done_count = 0

    for i, shot in enumerate(shots):
        shot_pct_base = int((i / len(shots)) * 90)
        step(shot_pct_base + 5, f"Veo 3.1 샷 {i+1}/{len(shots)} 비디오 생성 요청...")

        clip_dest = os.path.join(bga_dir, f"clip_{i}.mp4")
        clip_entry = {
            "index": i,
            "status": "pending",
            "file": None,
            "url": None,
            "operation_name": None,
            "error": None,
        }

        try:
            op = client.models.generate_videos(
                model=model_name,
                prompt=shot.get("prompt") or "",
                image=img,
                config=cfg,
            )
            clip_entry["operation_name"] = getattr(op, "name", None)

            start_time = time.time()
            while not op.done:
                if time.time() - start_time > BGA_POLL_TIMEOUT:
                    raise TimeoutError(f"샷 {i} 폴링 시간 초과 ({BGA_POLL_TIMEOUT}초)")
                sleep_fn(BGA_POLL_INTERVAL)
                op = client.operations.get(op)

            if getattr(op, "error", None):
                clip_entry["status"] = "failed"
                clip_entry["error"] = str(op.error)
            else:
                resp = getattr(op, "response", None) or getattr(op, "result", None)
                vids = getattr(resp, "generated_videos", None) or []
                if not vids:
                    rai_reason = getattr(resp, "rai_media_filtered_reasons", None)
                    clip_entry["status"] = "failed"
                    clip_entry["error"] = f"영상 생성 필터됨: {rai_reason}" if rai_reason else "영상이 생성되지 않았습니다 (빈 응답)"
                else:
                    v_item = vids[0]
                    v_bytes = getattr(getattr(v_item, "video", None), "video_bytes", None) or getattr(v_item, "video_bytes", None)
                    if not v_bytes:
                        clip_entry["status"] = "failed"
                        clip_entry["error"] = "비디오 바이트 데이터가 없습니다."
                    else:
                        with open(clip_dest, "wb") as vf:
                            vf.write(v_bytes)
                        _increment_usage(1)
                        clip_entry["status"] = "done"
                        clip_entry["file"] = clip_dest
                        clip_entry["url"] = f"/data/luna_music/{track_id}/bga/clip_{i}.mp4"
                        done_count += 1
                        step(shot_pct_base + int(90 / len(shots)), f"샷 {i+1}/{len(shots)} 클립 저장 완료")
        except Exception as e:
            clip_entry["status"] = "failed"
            clip_entry["error"] = str(e)
            print(f"[ChoonsikBGA] 샷 {i} 생성 실패: {e}")

        clips_record[str(i)] = clip_entry
        bga["clips"] = clips_record
        track_data["bga"] = bga
        luna_engine.save_track(track_data)

    bga["generated_at"] = time.time()
    bga["done_count"] = done_count
    bga["cost_estimate_usd"] = estimate_bga_cost(done_count)["usd"]
    track_data["bga"] = bga
    luna_engine.save_track(track_data)

    if done_count == 0:
        raise RuntimeError("모든 BGA 클립 생성이 실패했습니다.")

    step(100, f"BGA 클립 생성 완료 ({done_count}/{len(shots)}개 성공)")
    return track_data


def render_bga_loop(track_data: dict, with_waveform: bool = False, upscale: bool = True, progress_cb=None) -> dict:
    def step(pct, msg):
        if progress_cb:
            progress_cb("bga_render", msg, pct)
        print(f"[{pct}%] [ChoonsikBGA] {msg}")

    track_id = track_data.get("track_id")
    if not track_id:
        raise ValueError("유효한 트랙 ID가 없습니다.")

    t_dir = os.path.join(luna_engine.LUNA_DIR, track_id)
    bga = dict(track_data.get("bga") or {})
    clips_dict = bga.get("clips") or {}

    valid_clips = []
    # 키 정렬 (0, 1, 2 순서)
    for k in sorted(clips_dict.keys(), key=lambda x: int(x) if x.isdigit() else x):
        c = clips_dict[k]
        if c.get("status") == "done":
            c_file = c.get("file") or os.path.join(t_dir, BGA_DIR_NAME, f"clip_{k}.mp4")
            if os.path.exists(c_file):
                valid_clips.append(c_file)

    if len(valid_clips) < 2:
        raise RuntimeError("BGA 클립이 2개 미만 — 켄번즈 렌더를 사용하세요")

    audio_file = track_data.get("audio_file") or os.path.join(t_dir, "audio.mp3")
    if not os.path.exists(audio_file):
        raise FileNotFoundError(f"오디오 파일이 없습니다: {audio_file}")

    audio_dur = float(producer.audio_duration(audio_file) or track_data.get("duration_seconds") or 180.0)

    step(15, "BGA 심리스 루프 단위(loop_unit.mp4) 생성 중...")
    bga_dir = os.path.join(t_dir, BGA_DIR_NAME)
    os.makedirs(bga_dir, exist_ok=True)
    loop_unit_path = os.path.join(bga_dir, "loop_unit.mp4")

    # 1단계: N개 클립 간 크로스페이드 연결
    # 각 클립 길이 측정
    lens = [float(producer.audio_duration(f) or BGA_CLIP_SECONDS) for f in valid_clips]
    n = len(valid_clips)

    inputs = []
    for f in valid_clips:
        inputs.extend(["-i", f])

    # xfade 필터 체인 구성
    filter_parts = []
    last_pad = "0:v"
    curr_offset = 0.0

    for idx in range(1, n):
        curr_offset += (lens[idx - 1] - BGA_XFADE_SECONDS)
        next_pad = f"v{idx}" if idx < n - 1 else "vchain"
        filter_parts.append(
            f"[{last_pad}][{idx}:v]xfade=transition=fade:duration={BGA_XFADE_SECONDS}:offset={curr_offset:.3f}[{next_pad}]"
        )
        last_pad = next_pad

    filter_complex_chain = ";".join(filter_parts)
    unit_raw_path = os.path.join(bga_dir, "unit_raw.mp4")
    cmd_chain = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex_chain,
        "-map", "[vchain]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        unit_raw_path
    ]
    proc = subprocess.run(cmd_chain, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"BGA 체인 렌더 실패: {proc.stderr[-300:]}")

    # 2단계: 루프 이음새 (unit_raw 의 마지막 1초와 시작 1초를 xfade 한 브리지를 끝에 붙이고 앞 1초 트리밍)
    raw_dur = float(producer.audio_duration(unit_raw_path) or sum(lens) - (n - 1) * BGA_XFADE_SECONDS)
    # [main_body][bridge] 연결 방식:
    # 0s~1s (head), 1s~(raw_dur-1s) (body), (raw_dur-1s)~raw_dur (tail)
    # tail 과 head 를 xfade 하여 1초 브리지 생성 후 body 뒤에 concat
    tail_start = max(0.0, raw_dur - BGA_XFADE_SECONDS)
    bridge_filter = (
        f"[0:v]trim=start=1:end={raw_dur:.3f},setpts=PTS-STARTPTS[body];"
        f"[0:v]trim=start={tail_start:.3f}:end={raw_dur:.3f},setpts=PTS-STARTPTS[tail];"
        f"[0:v]trim=start=0:end=1,setpts=PTS-STARTPTS[head];"
        f"[tail][head]xfade=transition=fade:duration={BGA_XFADE_SECONDS}:offset=0[bridge];"
        f"[body][bridge]concat=n=2:v=1:a=0[vunit]"
    )
    cmd_unit = [
        "ffmpeg", "-y", "-i", unit_raw_path,
        "-filter_complex", bridge_filter,
        "-map", "[vunit]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        loop_unit_path
    ]
    proc = subprocess.run(cmd_unit, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        # 브리지 실패 시 unit_raw 를 그대로 사용
        print(f"[ChoonsikBGA] 루프 브리지 경고, unit_raw 사용: {proc.stderr[-200:]}")
        shutil.copy(unit_raw_path, loop_unit_path)

    # 3단계: 최종 비디오 렌더링
    step(50, "최종 비디오(video.mp4) 렌더링 중...")
    final_video_path = os.path.join(t_dir, "video.mp4")

    # 기존 켄번즈 백업 (video_source != "bga")
    if os.path.exists(final_video_path) and track_data.get("video_source") != "bga":
        backup_path = os.path.join(t_dir, "video_cover_backup.mp4")
        if not os.path.exists(backup_path):
            shutil.copy(final_video_path, backup_path)

    probe_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", loop_unit_path],
        capture_output=True, text=True
    )
    w, h = 1280, 720
    try:
        p_json = json.loads(probe_probe.stdout)
        s_info = p_json["streams"][0]
        w, h = int(s_info["width"]), int(s_info["height"])
    except Exception:
        pass

    target_w, target_h = (1920, 1080) if upscale else (w, h)
    scale_part = f"scale={target_w}:{target_h}:flags=lanczos" if upscale else f"scale={target_w}:{target_h}"
    fade_out_start = max(0.0, audio_dur - 3.0)

    if with_waveform:
        wave_filter = luna_engine.waveform_overlay_filter(target_w, 180)
        final_filter = (
            f"[0:v]{scale_part},fade=in:st=0:d=2,fade=out:st={fade_out_start:.3f}:d=3[bg];"
            f"[1:a]{wave_filter}[wave];"
            f"[bg][wave]overlay=0:H-180[vfinal]"
        )
        map_v = "[vfinal]"
    else:
        final_filter = f"[0:v]{scale_part},fade=in:st=0:d=2,fade=out:st={fade_out_start:.3f}:d=3[vfinal]"
        map_v = "[vfinal]"

    cmd_final = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", loop_unit_path,
        "-i", audio_file,
        "-filter_complex", final_filter,
        "-map", map_v, "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{audio_dur:.3f}", "-shortest",
        final_video_path
    ]
    proc = subprocess.run(cmd_final, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"최종 BGA 비디오 렌더링 실패: {proc.stderr[-300:]}")

    track_data["video_file"] = final_video_path
    track_data["video_url"] = f"/data/luna_music/{track_id}/video.mp4"
    track_data["rendered_at"] = time.time()
    track_data["video_source"] = "bga"
    track_data.pop("video_stale", None)

    bga["loop_unit_file"] = loop_unit_path
    bga["rendered_at"] = time.time()
    track_data["bga"] = bga

    luna_engine.save_track(track_data)
    step(100, "BGA 루프 비디오 렌더링 완료!")
    return track_data


REMOTION_DIR = os.path.join(luna_engine.BASE_DIR, "remotion")


def render_bga_remotion(track_data: dict, progress_cb=None, timeout: int = 1800, runner=subprocess.run) -> dict:
    def step(pct, msg):
        if progress_cb:
            progress_cb("bga_remotion", msg, pct)
        print(f"[{pct}%] [RemotionBGA] {msg}")

    # 1. 전제 검사
    node_modules_dir = os.path.join(REMOTION_DIR, "node_modules")
    if not os.path.exists(node_modules_dir):
        raise RuntimeError("Remotion 미설치: cd remotion && npm ci")

    track_id = track_data.get("track_id")
    if not track_id:
        raise ValueError("유효한 트랙 ID가 없습니다.")

    t_dir = os.path.join(luna_engine.LUNA_DIR, track_id)
    bga = dict(track_data.get("bga") or {})
    loop_unit_path = bga.get("loop_unit_file") or os.path.join(t_dir, BGA_DIR_NAME, "loop_unit.mp4")
    if not os.path.exists(loop_unit_path):
        raise RuntimeError("loop_unit.mp4 없음 — render_bga_loop 를 먼저 실행")

    audio_file = track_data.get("audio_file") or os.path.join(t_dir, "audio.mp3")
    if not os.path.exists(audio_file):
        raise FileNotFoundError(f"오디오 파일이 없습니다: {audio_file}")
    # 베가 마스터본(track["audio_file"], 보통 audio_mastered.wav)을 그대로 쓴다. audio.mp3 는 마스터링 전 원본이다.
    # Remotion 은 public/luna → data/luna_music 심볼릭 링크로만 파일을 읽으므로 트랙 폴더 밖이면 안으로 복사한다.
    if os.path.dirname(os.path.abspath(audio_file)) != os.path.abspath(t_dir):
        copied = os.path.join(t_dir, "audio_remotion_src" + os.path.splitext(audio_file)[1])
        shutil.copy(audio_file, copied)
        audio_file = copied
    audio_rel = f"luna/{track_id}/{os.path.basename(audio_file)}"

    # 2. 메타데이터 및 props 준비
    title_full = (track_data.get("title") or "Agent Luna").strip()
    if "(" in title_full:
        parts = title_full.split("(", 1)
        title_clean = parts[0].strip()
        sub_part = parts[1].rstrip(")").strip()
    else:
        title_clean = title_full
        sub_part = ""

    genre_name = track_data.get("genre") or ""
    subtitle_clean = f"{sub_part} · {genre_name}".strip(" ·") if sub_part else genre_name

    loop_unit_sec = float(producer.audio_duration(loop_unit_path) or 22.0)
    audio_dur = float(producer.audio_duration(audio_file) or track_data.get("duration_seconds") or 180.0)

    props = {
        "trackId": track_id,
        "loopUnit": f"luna/{track_id}/bga/loop_unit.mp4",
        "loopUnitSeconds": loop_unit_sec,
        "audio": audio_rel,
        "durationSeconds": audio_dur,
        "title": title_clean,
        "subtitle": subtitle_clean,
        "accent": "#a5b4fc",
        "spectrum": True,
    }

    out_file = os.path.join(t_dir, "video_remotion.mp4")

    # 3. 렌더 실행 (video.mp4 를 절대 덮지 않음)
    step(20, f"Remotion 렌더 시작 (약 {audio_dur:.1f}초, LunaBga)...")
    cmd = [
        "npx", "remotion", "render", "src/index.ts", "LunaBga",
        out_file, "--props", json.dumps(props), "--log", "error"
    ]

    start_time = time.time()
    proc = runner(cmd, cwd=REMOTION_DIR, timeout=timeout, capture_output=True, text=True)
    if proc.returncode != 0:
        err_msg = (proc.stderr or proc.stdout or "")[-300:]
        raise RuntimeError(f"Remotion 렌더 실패: {err_msg}")

    elapsed = time.time() - start_time
    bga["remotion"] = {
        "file": out_file,
        "url": f"/data/luna_music/{track_id}/video_remotion.mp4",
        "elapsed_sec": round(elapsed, 2),
        "rendered_at": time.time(),
    }
    track_data["bga"] = bga
    luna_engine.save_track(track_data)

    step(100, f"Remotion 비디오 렌더링 완료 ({elapsed:.1f}초) -> {out_file}")
    return track_data


def remotion_available() -> bool:
    """Remotion 빌드 도구 및 node_modules 설치 여부 확인"""
    return os.path.isdir(os.path.join(REMOTION_DIR, "node_modules"))


def default_renderer() -> str:
    """기본 BGA 렌더러 (BGA_RENDERER 환경변수; 기본 ffmpeg, remotion 지정 가능)"""
    r = os.getenv("BGA_RENDERER", "ffmpeg").strip().lower()
    return "remotion" if r == "remotion" else "ffmpeg"


def _promote_remotion_output(track_data: dict) -> dict:
    """Remotion 결과(video_remotion.mp4)를 메인 비디오(video.mp4)로 승격하여 채택"""
    track_id = track_data.get("track_id")
    t_dir = os.path.join(luna_engine.LUNA_DIR, track_id)
    bga = track_data.get("bga", {})
    rem_meta = bga.get("remotion", {})
    rem_file = rem_meta.get("file")
    if not rem_file or not os.path.exists(rem_file):
        raise RuntimeError(f"Remotion 결과 파일이 존재하지 않습니다: {rem_file}")

    final_video_path = os.path.join(t_dir, "video.mp4")
    current_source = track_data.get("video_source")

    # 기존 커버 켄번즈 영상 백업 (bga 계열이 아닐 때만 1회 백업)
    if os.path.exists(final_video_path) and current_source not in ("bga", "bga-remotion"):
        backup_path = os.path.join(t_dir, "video_cover_backup.mp4")
        if not os.path.exists(backup_path):
            shutil.copy(final_video_path, backup_path)

    # video_remotion.mp4 -> video.mp4 복사 (원본 video_remotion.mp4 는 보존)
    shutil.copy(rem_file, final_video_path)

    track_data["video_file"] = final_video_path
    track_data["video_url"] = f"/data/luna_music/{track_id}/video.mp4"
    track_data["rendered_at"] = time.time()
    track_data["video_source"] = "bga-remotion"
    track_data.pop("video_stale", None)

    luna_engine.save_track(track_data)
    return track_data


def render_bga(
    track_data: dict,
    renderer: Optional[str] = None,
    with_waveform: bool = False,
    upscale: bool = True,
    progress_cb: Optional[Callable[[str, str, int], None]] = None,
) -> dict:
    """BGA 비디오 렌더러 통합 디스패처 (ffmpeg 기본 / Remotion 선택 및 자동 폴백)"""
    req_renderer = (renderer or default_renderer()).strip().lower()
    bga = track_data.setdefault("bga", {})
    bga["renderer_requested"] = req_renderer

    if req_renderer == "remotion":
        try:
            if not remotion_available():
                raise RuntimeError("Remotion 미설치")
            # loop_unit.mp4 가 없으면 먼저 만들고, 폴백 대비 ffmpeg 렌더 선행
            track_data = render_bga_loop(
                track_data,
                with_waveform=with_waveform,
                upscale=upscale,
                progress_cb=progress_cb,
            )
            track_data = render_bga_remotion(track_data, progress_cb=progress_cb)
            track_data = _promote_remotion_output(track_data)
            bga = track_data.setdefault("bga", {})
            bga["renderer_used"] = "remotion"
            bga.pop("fallback_reason", None)
        except Exception as e:
            # 클립 2개 미만 에러는 폴백하지 않고 그대로 전파
            if "2개 미만" in str(e):
                raise
            bga = track_data.setdefault("bga", {})
            bga["fallback_reason"] = f"{type(e).__name__}: {str(e)[:200]}"
            track_data = render_bga_loop(
                track_data,
                with_waveform=with_waveform,
                upscale=upscale,
                progress_cb=progress_cb,
            )
            bga = track_data.setdefault("bga", {})
            bga["renderer_used"] = "ffmpeg"
    else:
        track_data = render_bga_loop(
            track_data,
            with_waveform=with_waveform,
            upscale=upscale,
            progress_cb=progress_cb,
        )
        bga = track_data.setdefault("bga", {})
        bga["renderer_used"] = "ffmpeg"
        bga.pop("fallback_reason", None)

    luna_engine.save_track(track_data)
    return track_data


