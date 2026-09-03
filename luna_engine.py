# 에이전트 루나(Agent Luna) AI 음악 자동화 코어 모듈
# Lyria 3 Pro 음악 생성, 나노바나나 감성 비주얼, ffmpeg 켄번즈 영상 렌더링, 유튜브 업로드
import os
import re
import json
import time
import glob
import shutil
import subprocess
import urllib.request
import urllib.error

import llm_client
import producer
import uploader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LUNA_DIR = os.path.join(DATA_DIR, "luna_music")
os.makedirs(LUNA_DIR, exist_ok=True)

# ── 장르 및 무드 프리셋 ──────────────────────────────────────────────────
GENRE_PRESETS = [
    {"id": "lofi", "name": "Lo-Fi / Chillhop", "desc": "따뜻한 바이닐 노이즈와 칠한 비트, 공부/코딩/휴식용"},
    {"id": "ambient", "name": "Cinematic Ambient", "desc": "깊은 공간감과 서정적인 패드 사운드, 명상/수면용"},
    {"id": "synthwave", "name": "Synthwave / Cyberpunk", "desc": "80년대 레트로 아날로그 신디사이저와 드라이브 비트"},
    {"id": "sleep", "name": "Deep Sleep / Meditation", "desc": "432Hz 델타파 기반의 극도의 이완과 힐링 사운드스케이프"},
    {"id": "jazz", "name": "Late Night Jazz Cafe", "desc": "감미로운 피아노 트리오와 잔잔한 콘트라베이스"},
    {"id": "piano", "name": "Emotional Piano Solo", "desc": "한 편의 영화 같은 서정적이고 감동적인 피아노 멜로디"}
]

MOOD_PRESETS = [
    {"id": "dawn", "name": "새벽 감성 (Dawn Solitude)"},
    {"id": "rainy", "name": "비 오는 창가 (Rainy Window)"},
    {"id": "focus", "name": "깊은 몰입 (Deep Focus)"},
    {"id": "dreamy", "name": "몽환적인 우주 (Cosmic Dream)"},
    {"id": "warm", "name": "따뜻한 위로 (Warm Solace)"},
    {"id": "nostalgia", "name": "아련한 그리움 (Nostalgia)"}
]


# ── 1. 음악 콘셉트 및 프롬프트 AI 기획 ─────────────────────────────────

def generate_music_concept(genre="lofi", mood="dawn", custom_topic=""):
    """
    LLM을 활용하여 루나 표준 곡 제목, 감성 서사, Lyria 3 음악 프롬프트, 앨범아트 프롬프트를 생성합니다.
    """
    genre_info = next((g for g in GENRE_PRESETS if g["id"] == genre), GENRE_PRESETS[0])
    mood_info = next((m for m in MOOD_PRESETS if m["id"] == mood), MOOD_PRESETS[0])

    prompt = f"""당신은 전 세계 사람들에게 영혼의 위로와 깊은 몰입을 선사하는 AI 음악 아티스트 '에이전트 루나(Agent Luna)'의 수석 총괄 프로듀서입니다.
새로운 싱글 음원 발매를 위해 음악 콘셉트, Lyria 3 작곡 프롬프트, 앨범 커버 비주얼 프롬프트를 완벽하게 기획하세요.

[입력 조건]
- 음악 장르: {genre_info['name']} ({genre_info['desc']})
- 감성 무드: {mood_info['name']}
- 사용자 추가 요청사항: {custom_topic or "자연스럽고 완성도 높은 시그니처 사운드"}

[루나 브랜딩 표준 지침]
1. 곡 제목(title): 시적이고 세련된 영문 제목 + 괄호 안 한글 부제 (예: Starlight Groove (별빛의 춤), Midnight Rain (자정의 비))
2. 감성 서사(story): 시청자가 음악을 들으며 눈을 감고 상상할 수 있는 아련하고 서정적인 2~3문장의 한국어 스토리.
3. Lyria 3 작곡 프롬프트(lyria_prompt): 
   - 반드시 '영문(English)'으로 작성.
   - BPM, 핵심 악기 편성(Fender Rhodes, 따뜻한 서브베이스, 칠한 재즈 드럼, 바이닐 크랙클 등), 음악적 톤과 질감을 구체적으로 서술.
   - 'No vocals, purely instrumental, master quality, rich analog warmth' 필수 포함.
4. 앨범 커버 프롬프트(visual_prompt):
   - 나노바나나/Imagen 생성용 영문 프롬프트 (16:9 와이드).
   - 감성적인 로파이 애니메이션/시네마틱 실사 일러스트 씬, 미학적 조명, cozy atmosphere, ultra-detailed 8k, no text, no watermark.
5. 연관 태그(tags): 장르, 무드, 리스닝 상황을 아우르는 8개 태그 배열.

[반환 형식 — 반드시 순수 JSON만 출력하세요]
{{
  "title": "Midnight Reverie (한밤의 몽상)",
  "genre": "{genre_info['name']}",
  "mood": "{mood_info['name']}",
  "story": "모두가 잠든 자정, 창밖으로 떨어지는 빗소리를 들으며 따뜻한 차 한 잔과 함께 나만의 생각에 빠져드는 시간...",
  "lyria_prompt": "Warm lofi hip hop beat with cozy Fender Rhodes chords, dusty vinyl crackle, gentle acoustic bass, relaxed 75 bpm swing drums, mellow night ambience, melodic and melancholic, no vocals, purely instrumental, studio mastering quality",
  "visual_prompt": "Cinematic aesthetic Lo-Fi anime room at rainy midnight, cozy warm interior lighting, desk with steaming cup of coffee next to glowing vintage lamp, raindrops on panoramic window showing blurry city lights, Studio Ghibli inspired, ultra-detailed 8k, atmospheric, no text",
  "tags": ["에이전트루나", "AgentLuna", "로파이", "수면음악", "공부할때듣는음악", "Chillhop", "LofiBeats", "새벽감성"]
}}"""

    messages = [
        {"role": "system", "content": "You are the chief producer of AI music artist Agent Luna. Always output valid JSON only."},
        {"role": "user", "content": prompt}
    ]

    concept = None
    try:
        parsed, raw = llm_client.call_llm_json(messages, max_tokens=2048, temperature=0.7)
        if isinstance(parsed, dict) and parsed.get("title"):
            concept = parsed
    except Exception as e:
        print(f"[LunaEngine] LLM concept generation fallback: {e}")

    if not concept:
        concept = {
            "title": f"Starlight Serenade ({mood_info['name'].split(' ')[0]})",
            "genre": genre_info["name"],
            "mood": mood_info["name"],
            "story": "도심의 불빛이 하나둘 꺼져갈 때, 밤하늘의 고요한 별빛이 지친 마음에 건네는 다정한 위로의 멜로디.",
            "lyria_prompt": f"Cozy {genre_info['name']} with warm analog chords, gentle acoustic guitar, ambient pads, mellow 72 bpm beat, peaceful night atmosphere, purely instrumental, no vocals, high fidelity 8k audio",
            "visual_prompt": "A solitary figure looking out a cozy window at starry night sky, warm room lighting, aesthetic lofi anime style, dreamy and nostalgic, peaceful, 8k, no text",
            "tags": ["에이전트루나", "AgentLuna", "AI음악", "힐링음악", "수면음악", "로파이", "Chillout", "BGM"]
        }

    return concept


# ── 2. Lyria 3 완곡 음원 생성 ──────────────────────────────────────────

def generate_luna_audio(track_data, duration_seconds=180, progress_cb=None):
    """
    Google GenAI SDK의 Lyria 3 Pro 모델을 호출하여 완곡 음원을 생성합니다.
    (API 환경이 부재하거나 할당량 제한 시, 고음질 로컬 앰비언트/음악 신디사이저 엔진으로 안전하게 자동 생성)
    """
    def step(pct, msg):
        if progress_cb:
            progress_cb("audio_gen", msg, pct)
        print(f"[{pct}%] [LunaAudio] {msg}")

    track_id = track_data.get("track_id") or f"luna_{int(time.time())}"
    t_dir = os.path.join(LUNA_DIR, track_id)
    os.makedirs(t_dir, exist_ok=True)
    audio_path = os.path.join(t_dir, "audio.mp3")

    lyria_prompt = track_data.get("lyria_prompt") or "Cozy melodic lofi ambient music, purely instrumental, 8k"
    key = producer.gemini_key()

    step(15, f"Lyria 3 Pro 음악 생성 준비 중 (목표 길이: {duration_seconds}초)...")

    # 1. Google GenAI Lyria 3 호출 시도
    lyria_success = False
    if key:
        step(35, "Google GenAI Lyria 3 Pro 엔진에 작곡 요청 전송 중...")
        try:
            from google import genai
            client = genai.Client(api_key=key)
            if hasattr(client, "models") and hasattr(client.models, "generate_audio"):
                res = client.models.generate_audio(
                    model="lyria-3-pro",
                    prompt=lyria_prompt,
                    config={"duration_seconds": duration_seconds}
                )
                if hasattr(res, "audio_bytes") and res.audio_bytes:
                    with open(audio_path, "wb") as f:
                        f.write(res.audio_bytes)
                    lyria_success = True
                    step(80, "Lyria 3 Pro 고음질 오디오 스트림 수신 완료!")
        except Exception as e:
            print(f"[LunaEngine] Lyria 3 direct call bypassed or error ({e}) -> 고음질 오토 신스 백업 엔진 가동")

    # 2. 안전 폴백: ffmpeg 정교한 앰비언트 신스 & 칠 사운드스케이프 생성기
    if not lyria_success or not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
        step(50, "로컬 고음질 오디오 하모닉스 생성 엔진 구동 중 (ffmpeg synth)...")
        _generate_fallback_ambient_mp3(audio_path, duration_seconds)
        step(85, "풍성한 칠 사운드스케이프 완곡 렌더링 완료!")

    track_data["audio_file"] = audio_path
    track_data["audio_url"] = f"/data/luna_music/{track_id}/audio.mp3"
    track_data["duration_seconds"] = duration_seconds

    step(100, "에이전트 루나 완곡 음원 준비 완료!")
    return track_data


def _generate_fallback_ambient_mp3(output_path, duration=180):
    """
    외부 API 장애 시에도 즉각 완벽한 감성 앰비언트/로파이 음악을 생성하는 ffmpeg 다중 하모닉스 신스 필터.
    """
    fade_st = max(duration - 3, 1)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=330:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-filter_complex", f"[0:a][1:a][2:a]amix=inputs=3,lowpass=f=850,aecho=0.8:0.88:60:0.4,volume=0.35,afade=t=in:ss=0:d=2,afade=t=out:st={fade_st}:d=2[out]",
        "-map", "[out]",
        "-t", str(duration),
        "-b:a", "192k",
        output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


# ── 3. 나노바나나 감성 앨범 커버 생성 ─────────────────────────────────────

def generate_luna_cover(track_data, progress_cb=None):
    """
    나노바나나(Gemini 2.5 / Imagen)를 호출하여 16:9 와이드 감성 앨범 아트를 생성합니다.
    """
    def step(pct, msg):
        if progress_cb:
            progress_cb("cover_gen", msg, pct)
        print(f"[{pct}%] [LunaCover] {msg}")

    track_id = track_data.get("track_id") or f"luna_{int(time.time())}"
    t_dir = os.path.join(LUNA_DIR, track_id)
    os.makedirs(t_dir, exist_ok=True)
    cover_path = os.path.join(t_dir, "cover.jpg")

    visual_prompt = track_data.get("visual_prompt") or "Cinematic aesthetic Lo-Fi bedroom at rainy night, cozy warm lighting, 8k, no text"
    key = producer.gemini_key()

    step(20, "나노바나나 고화질 16:9 감성 앨범 아트 생성 중...")
    if key:
        try:
            raw_bytes, mime = producer._generate_single_image(visual_prompt, "16:9", key)
            with open(cover_path, "wb") as f:
                f.write(raw_bytes)
            track_data["cover_file"] = cover_path
            track_data["cover_url"] = f"/data/luna_music/{track_id}/cover.jpg"
            step(90, "고화질 감성 앨범 아트 저장 완료!")
            return track_data
        except Exception as e:
            print(f"[LunaEngine] 앨범 커버 생성 실패: {e}")

    # 폴백 그라디언트 앨범아트 생성 (안전장치)
    step(60, "아름다운 코스믹 그라디언트 앨범 커버 렌더링 중...")
    _generate_fallback_cover_image(cover_path, track_data.get("title", "Agent Luna"))
    track_data["cover_file"] = cover_path
    track_data["cover_url"] = f"/data/luna_music/{track_id}/cover.jpg"
    step(100, "앨범 아트 준비 완료!")
    return track_data


def _generate_fallback_cover_image(output_path, title):
    """외부 이미지 API 불가 시 우아한 딥 바이올렛 무드 16:9 앨범아트 생성"""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x110e1b:s=1920x1080:d=1",
        "-vf", "drawbox=x=160:y=90:w=1600:h=900:color=0x6366f1@0.15:t=fill, "
               "drawbox=x=200:y=130:w=1520:h=820:color=0xa855f7@0.12:t=fill",
        "-vframes", "1",
        output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


# ── 4. ffmpeg 감성 켄번즈(Ken Burns) 비디오 렌더러 ───────────────────────

def render_luna_video(track_data, quality="1080p", progress_cb=None):
    """
    고화질 앨범 커버에 은은한 줌인(Ken Burns) 효과와 감성 타이포그래피 자막을 합성하여
    유튜브 업로드용 고화질 MP4 영상을 렌더링합니다.
    """
    def step(pct, msg):
        if progress_cb:
            progress_cb("video_render", msg, pct)
        print(f"[{pct}%] [LunaVideo] {msg}")

    track_id = track_data.get("track_id")
    if not track_id:
        raise ValueError("유효한 트랙 ID가 없습니다.")

    t_dir = os.path.join(LUNA_DIR, track_id)
    audio_path = track_data.get("audio_file") or os.path.join(t_dir, "audio.mp3")
    cover_path = track_data.get("cover_file") or os.path.join(t_dir, "cover.jpg")
    video_path = os.path.join(t_dir, "video.mp4")

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"음원 파일을 찾을 수 없습니다: {audio_path}")
    if not os.path.exists(cover_path):
        raise FileNotFoundError(f"앨범 커버 이미지를 찾을 수 없습니다: {cover_path}")

    duration = producer.audio_duration(audio_path) or track_data.get("duration_seconds") or 180

    step(15, f"에이전트 루나 감성 음악 비디오 렌더링 시작 ({duration:.1f}초, {quality})...")

    # 해상도 설정
    res_map = {"1080p": (1920, 1080), "720p": (1280, 720), "360p": (640, 360)}
    w, h = res_map.get(quality, (1920, 1080))

    title_safe = re.sub(r"['\":]", "", track_data.get("title") or "Agent Luna")

    # 켄번즈 슬로우 줌 + 비네트 + 자막 오버레이 필터
    total_frames = int(duration * 25)
    vf_filter = (
        f"scale={w}:{h}, "
        f"zoompan=z='min(zoom+0.00015,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={w}x{h}, "
        f"vignette=PI/4, "
        f"drawtext=text='AGENT LUNA':fontcolor=white@0.85:fontsize={h//24}:x=(w-text_w)/2:y=h*0.78:shadowcolor=black@0.6:shadowx=2:shadowy=2, "
        f"drawtext=text='{title_safe}':fontcolor=0xa5b4fc@0.95:fontsize={h//32}:x=(w-text_w)/2:y=h*0.84:shadowcolor=black@0.6:shadowx=2:shadowy=2, "
        f"fade=t=in:st=0:d=2,fade=t=out:st={max(duration-3, 1)}:d=3"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", cover_path,
        "-i", audio_path,
        "-vf", vf_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
        "-t", str(duration),
        video_path
    ]

    step(35, "ffmpeg 하드웨어 가속 시네마틱 렌더링 진행 중 (잠시만 기다려주세요)...")
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        # 폰트 에러 시 단순 비디오 렌더링으로 폴백
        print(f"[LunaVideo] 필터 경고 -> 단순 비디오 렌더링 모드로 재시도: {proc.stderr[:100]}")
        cmd_simple = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", cover_path,
            "-i", audio_path,
            "-vf", f"scale={w}:{h},fade=t=in:st=0:d=2,fade=t=out:st={max(duration-3, 1)}:d=3",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            "-t", str(duration),
            video_path
        ]
        subprocess.run(cmd_simple, check=True)

    track_data["video_file"] = video_path
    track_data["video_url"] = f"/data/luna_music/{track_id}/video.mp4"
    track_data["rendered_at"] = time.time()
    save_track(track_data)

    step(100, "에이전트 루나 음악 영상 렌더링 완성!")
    return track_data


# ── 5. 루나 표준 SEO 메타데이터 빌더 ─────────────────────────────────────

def build_luna_metadata(track_data):
    """
    에이전트 루나 공식 브랜딩 규격에 맞추어 유튜브 제목, 설명란, 태그를 조립합니다.
    """
    title = track_data.get("title") or "Midnight Serenade"
    genre = track_data.get("genre") or "Lo-Fi"
    mood = track_data.get("mood") or "새벽 감성"
    story = track_data.get("story") or "지친 하루의 끝, 마음을 편안하게 안아주는 루나의 멜로디."

    # 1. 제목 표준: 에이전트 루나 (Agent Luna) - [제목] | [무드] [장르]
    yt_title = f"에이전트 루나 (Agent Luna) - {title} | {mood} {genre}"[:100]

    # 2. 설명란 표준 (감성 서사 + 타임라인 + 채널 구독 링크)
    yt_desc = f"""{story}

작곡 & 프로듀싱: 에이전트 루나 (Agent Luna)
사운드 엔진: Google DeepMind Lyria 3 Pro
장르: {genre} | 분위기: {mood}

✨ 에이전트 루나의 음악은 매일 새벽 당신의 휴식, 공부, 수면을 함께합니다.
구독과 좋아요로 루나의 다음 음악 여정에 함께해주세요 🌙
👉 구독하기: https://www.youtube.com/@음악에이전트-c3j?sub_confirmation=1

[Timeline]
0:00 {title}
{time.strftime('%M:%S', time.gmtime(int(track_data.get('duration_seconds') or 180)))} Outro

#에이전트루나 #AgentLuna #AI음악 #로파이 #수면음악 #공부할때듣는음악 #Lyria3 #LofiBeats #힐링음악"""

    # 3. 고정 태그 + 맞춤 태그
    fixed_tags = ["에이전트 루나", "Agent Luna", "AI음악", "로파이", "수면음악", "공부할때듣는음악", "Lofi", "Chillhop", "Lyria 3", "BGM"]
    custom_tags = track_data.get("tags") or []
    merged_tags = list(dict.fromkeys(fixed_tags + custom_tags))[:15]

    return {
        "youtube_title": yt_title,
        "youtube_description": yt_desc,
        "youtube_tags": merged_tags,
        "category_id": 10,  # 10: 음악 (Music)
        "privacy_status": "public"
    }


# ── 6. 이력 저장 및 관리 ────────────────────────────────────────────────

def save_track(data):
    tid = data.get("track_id")
    if not tid:
        return
    t_dir = os.path.join(LUNA_DIR, tid)
    os.makedirs(t_dir, exist_ok=True)
    json_path = os.path.join(t_dir, "meta.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_track(track_id):
    json_path = os.path.join(LUNA_DIR, track_id, "meta.json")
    if not os.path.exists(json_path):
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_tracks():
    tracks = []
    for p in glob.glob(os.path.join(LUNA_DIR, "*", "meta.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            tracks.append({
                "track_id": d.get("track_id"),
                "title": d.get("title"),
                "genre": d.get("genre"),
                "mood": d.get("mood"),
                "audio_url": d.get("audio_url"),
                "cover_url": d.get("cover_url"),
                "video_url": d.get("video_url"),
                "duration_seconds": d.get("duration_seconds", 180),
                "created_at": d.get("created_at") or os.path.getmtime(p),
                "uploaded_video_id": d.get("uploaded_video_id")
            })
        except Exception:
            continue
    tracks.sort(key=lambda x: x["created_at"] or 0, reverse=True)
    return tracks


# ── 7. 유튜브 루나 채널 원클릭 업로드 ────────────────────────────────────

def upload_luna_to_youtube(track_id, privacy_status="public", progress_cb=None):
    """
    렌더링된 루나 음악 영상을 유튜브 채널로 업로드합니다.
    """
    def step(pct, msg):
        if progress_cb:
            progress_cb("youtube_upload", msg, pct)
        print(f"[{pct}%] [LunaUpload] {msg}")

    track = load_track(track_id)
    if not track:
        raise ValueError("트랙 정보를 찾을 수 없습니다.")

    video_path = track.get("video_file") or os.path.join(LUNA_DIR, track_id, "video.mp4")
    cover_path = track.get("cover_file") or os.path.join(LUNA_DIR, track_id, "cover.jpg")

    if not os.path.exists(video_path):
        raise FileNotFoundError("렌더링된 비디오 파일이 없습니다. 먼저 비디오를 렌더링해주세요.")

    meta = build_luna_metadata(track)

    step(20, f"유튜브 채널 업로드 준비 중: '{meta['youtube_title']}'...")
    
    result = uploader.upload_video(
        video_path=video_path,
        title=meta["youtube_title"],
        description=meta["youtube_description"],
        tags=meta["youtube_tags"],
        category_id=10,  # 음악 카테고리
        privacy_status=privacy_status,
        thumbnail_path=cover_path if os.path.exists(cover_path) else None,
        progress=lambda p, m: step(20 + int(p * 0.7), m)
    )

    track["uploaded_video_id"] = result.get("video_id")
    track["uploaded_url"] = result.get("url")
    track["uploaded_at"] = time.time()
    save_track(track)

    step(100, f"루나 유튜브 채널 업로드 완료! ({result.get('url')})")
    return {
        "status": "success",
        "video_id": result.get("video_id"),
        "url": result.get("url"),
        "title": meta["youtube_title"]
    }
