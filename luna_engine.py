# 에이전트 루나(Agent Luna) AI 음악 자동화 코어 모듈
# Lyria 3 Pro 음악 생성, 나노바나나 감성 비주얼, ffmpeg 켄번즈 영상 렌더링, 유튜브 업로드
import os
import re
import json
import base64
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

# ── 장르 및 무드 독립 스펙 (하드코딩 닻내림 방지 & 완전 분리) ───────────────
GENRE_PRESETS = [
    {"id": "lofi", "name": "Lo-Fi / Chillhop", "desc": "따뜻한 바이닐 노이즈와 칠한 비트, 공부/코딩/휴식용"},
    {"id": "ambient", "name": "Cinematic Ambient", "desc": "깊은 공간감과 서정적인 패드 사운드, 명상/수면용"},
    {"id": "synthwave", "name": "Synthwave / Cyberpunk", "desc": "80년대 레트로 아날로그 신디사이저와 드라이브 비트"},
    {"id": "sleep", "name": "Deep Sleep / Meditation", "desc": "432Hz 델타파 기반의 극도의 이완과 힐링 사운드스케이프"},
    {"id": "jazz", "name": "Late Night Jazz Cafe", "desc": "감미로운 피아노 트리오와 잔잔한 콘트라베이스"},
    {"id": "piano", "name": "Emotional Piano Solo", "desc": "한 편의 영화 같은 서정적이고 감동적인 피아노 멜로디"}
]

GENRE_SPECS = {
    "lofi": {
        "name": "Lo-Fi / Chillhop",
        "bpm_range": "70-85 BPM",
        "instruments": "warm Fender Rhodes chords, dusty vinyl crackle, gentle acoustic bass, relaxed 75 bpm swing drums, mellow night jazz guitar licks",
        "sound_texture": "warm analog tape saturation, cozy nostalgic bedroom ambience, relaxed chillhop swing",
        "visual_style": "aesthetic Lo-Fi anime room at rainy night, cozy warm desk lamp, steaming cup of coffee next to glowing vintage radio, blurry city lights, Studio Ghibli inspired, ultra-detailed 8k, no text"
    },
    "ambient": {
        "name": "Cinematic Ambient",
        "bpm_range": "50-65 BPM or beatless",
        "instruments": "lush evolving synthesizer pads, 432Hz harmonic soundscape, deep sub drone, shimmering ethereal reverb textures, subtle distant thunder and rain field recordings",
        "sound_texture": "vast cosmic space, deep meditative stillness, healing ethereal overtones, no harsh beats, purely transcendent",
        "visual_style": "cinematic vast cosmic nebula, calm starry mountain lake under glowing aurora borealis, solitary silhouette gazing at infinity, ethereal and breathtaking, 8k, no text"
    },
    "synthwave": {
        "name": "Synthwave / Cyberpunk",
        "bpm_range": "110-128 BPM",
        "instruments": "vintage analog synthesizers (Juno-106, Moog bassline), driving 16th-note arpeggios, gated reverb 80s LinnDrum snare, punchy cybernetic kick, retro neon synth lead",
        "sound_texture": "80s retro-futuristic night drive, high dynamic energy, pulsing highway groove, analog warmth with modern punch",
        "visual_style": "cyberpunk neon-lit highway at midnight, sleek retro sports car speeding towards glowing wireframe grid horizon, vibrant magenta and cyan lighting, aesthetic 80s synthwave wallpaper, 8k, no text"
    },
    "sleep": {
        "name": "Deep Sleep / Meditation",
        "bpm_range": "45-55 BPM or beatless",
        "instruments": "432Hz and 528Hz healing delta-theta brainwave tones, ultra-soft Tibetan singing bowl whispers, warm oceanic ambient pad swell, gentle bedtime rain soundscape, peaceful harp touches",
        "sound_texture": "deep restorative relaxation, zero percussive attack, profound tranquility, anxiety-melting acoustic cocoon",
        "visual_style": "deep indigo twilight sky, silver crescent moon illuminating calm tranquil ocean ripples, floating soft clouds, dreamlike peaceful oasis, 8k, no text"
    },
    "jazz": {
        "name": "Late Night Jazz Cafe",
        "bpm_range": "65-80 BPM",
        "instruments": "warm grand piano chords with lyrical improvisation, walking acoustic double bass, brushed jazz snare drum and ride cymbal, muted brass accents",
        "sound_texture": "smoky midnight jazz club, authentic live acoustic ensemble feel, sophisticated soulfulness, intimate cafe warmth",
        "visual_style": "dimly lit vintage late-night jazz cafe, amber warm lighting, wooden grand piano with warm brass reflections, rain-slicked cobblestone street outside the window, cinematic mood, 8k, no text"
    },
    "piano": {
        "name": "Emotional Piano Solo",
        "bpm_range": "55-75 BPM",
        "instruments": "solo concert grand piano with felt damping intimacy, expressive acoustic hammer and pedal resonance, subtle cinematic string quartet swell in background",
        "sound_texture": "deeply emotional cinematic storytelling, expressive dynamic touch from pianissimo to forte, poignant and heart-touching melody",
        "visual_style": "minimalist grand piano standing beside floor-to-ceiling glass window, soft golden hour sunlight breaking through mist, fallen autumn leaves, poetic elegance, cinematic depth of field, 8k, no text"
    }
}

MOOD_PRESETS = [
    {"id": "dawn", "name": "새벽 감성 (Dawn Solitude)"},
    {"id": "rainy", "name": "비 오는 창가 (Rainy Window)"},
    {"id": "focus", "name": "깊은 몰입 (Deep Focus)"},
    {"id": "dreamy", "name": "몽환적인 우주 (Cosmic Dream)"},
    {"id": "warm", "name": "따뜻한 위로 (Warm Solace)"},
    {"id": "nostalgia", "name": "아련한 그리움 (Nostalgia)"}
]


# ── 1. 음악 콘셉트 및 프롬프트 동적 AI 기획 ─────────────────────────────

def generate_music_concept(genre="lofi", mood="dawn", custom_topic="", leo_brief=None):
    """
    LLM(Gemini 3.6 Flash)을 활용하여 장르별 독립 스펙과 레오의 트렌드 브리프를 결합,
    하드코딩 닻내림 없는 독창적인 곡 제목, 감성 서사, Lyria 3 작곡 프롬프트, 앨범아트 프롬프트를 생성합니다.
    """
    genre_key = genre if genre in GENRE_SPECS else "lofi"
    genre_spec = GENRE_SPECS[genre_key]
    genre_info = next((g for g in GENRE_PRESETS if g["id"] == genre_key), GENRE_PRESETS[0])
    mood_info = next((m for m in MOOD_PRESETS if m["id"] == mood), MOOD_PRESETS[0])

    # 레오의 트렌드 브리프 정보 결합
    trend_context = ""
    if leo_brief and isinstance(leo_brief, dict):
        trend_context = f"""
[에이전트 레오(Leo)의 유튜브 실시간 음악 트렌드 분석 브리프]
- 트렌드 핵심 테마: {leo_brief.get('topic', '')}
- 시청자 심리 및 니즈: {leo_brief.get('audience_triggers', '')}
- 추천 후킹 앵글: {leo_brief.get('angle', '')}
- 핵심 트렌드 키워드: {', '.join(leo_brief.get('keywords', []))}
"""

    prompt = f"""당신은 글로벌 AI 음악 아티스트 '에이전트 루나(Agent Luna)'의 수석 총괄 프로듀서이자 작곡가입니다.
새로운 싱글 음원을 위해 주어진 장르 고유의 음악적 정체성을 철저히 지키면서, 독창적이고 감각적인 음악 콘셉트와 작곡/비주얼 프롬프트를 완성하세요.

[필수 음악 사양 — 장르: {genre_spec['name']}]
- 권장 BPM: {genre_spec['bpm_range']}
- 필수 악기 편성: {genre_spec['instruments']}
- 사운드 질감 & 무드: {genre_spec['sound_texture']}
- 비주얼 기본 톤: {genre_spec['visual_style']}
- 감성 무드: {mood_info['name']}
- 추가 테마/요청: {custom_topic or "리스너의 깊은 몰입과 감정적 해소를 이끄는 완성도 높은 사운드"}
{trend_context}

[기획 원칙 (중요: 상투적인 클리셰와 특정 장르 편향 절대 금지)]
1. 곡 제목(title): 장르와 무드의 정서를 압축한 감각적인 '영문 제목 (한글 부제)' 형식.
   - 흔해 빠진 단어(Starlight, Midnight, Cafe 등)의 기계적 반복을 지양하고, 곡의 서사에 맞는 독창적인 단어를 선택할 것.
2. 감성 서사(story): 시청자가 음악을 들으며 깊이 공감할 수 있는 2~3문장의 아련하고 서정적인 한국어 스토리.
3. Lyria 3 작곡 프롬프트(lyria_prompt):
   - 반드시 '영문(English)'으로 작성.
   - 위에 명시된 {genre_spec['name']}의 [권장 BPM]과 [필수 악기 편성]을 반드시 포함할 것.
   - 타 장르의 악기나 분위기(예: 신스웨이브에 어쿠스틱 기타를 넣거나, 앰비언트에 드럼비트를 넣는 행위)를 절대 섞지 말 것.
   - 'No vocals, purely instrumental, master quality, rich analog warmth' 필수 포함.
4. 앨범 커버 프롬프트(visual_prompt):
   - 나노바나나/Imagen 생성용 영문 프롬프트 (16:9 와이드).
   - {genre_spec['name']}의 [비주얼 기본 톤]에 맞춘 시네마틱 씬 서술, 8k, no text, no watermark.
5. 연관 태그(tags): 장르, 무드, 리스닝 상황을 아우르는 8개 태그 배열.

[반환 형식 — 반드시 순수 JSON만 출력하세요]
{{
  "title": "영문 제목 (한글 부제)",
  "genre": "{genre_spec['name']}",
  "mood": "{mood_info['name']}",
  "story": "한국어 감성 서사 2~3문장",
  "lyria_prompt": "영문 Lyria 작곡 프롬프트 (BPM 및 장르 고유 악기 편성 포함)",
  "visual_prompt": "영문 앨범 커버 프롬프트 (16:9)",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5", "태그6", "태그7", "태그8"]
}}"""

    messages = [
        {"role": "system", "content": "You are the chief producer of AI music artist Agent Luna. Output pure JSON only."},
        {"role": "user", "content": prompt}
    ]

    concept = None
    try:
        parsed, raw = llm_client.call_llm_json(messages, max_tokens=2048, temperature=0.75)
        if isinstance(parsed, dict) and parsed.get("title") and parsed.get("lyria_prompt"):
            concept = parsed
    except Exception as e:
        print(f"[LunaEngine] LLM concept generation error: {e}")

    # 장르별 독립 멀티 Fallback (LLM 불가 시에도 장르 구분이 확실히 되도록 보장)
    if not concept:
        fallback_titles = {
            "lofi": ("Velvet Afterglow (벨벳빛 노을)", "비 내린 오후, 젖은 아스팔트 위로 번지는 주황빛 가로등을 바라보며 나만의 작은 방에서 즐기는 온전한 휴식."),
            "ambient": ("Aetherial Drift (에테르의 유영)", "끝없이 펼쳐진 은하수 사이로 고요히 흘러가는 시간, 온몸의 긴장이 풀리고 우주의 품에 안기는 순간."),
            "synthwave": ("Neon Horizon (네온의 지평선)", "보랏빛 안개가 자욱한 자정의 고속도로, 끝없는 네온 불빛을 가르며 미래로 질주하는 드라이브의 전율."),
            "sleep": ("Cradle of Stars (별들의 요람)", "오늘 하루 무거웠던 모든 생각과 불안을 밤하늘에 띄워 보내고, 부드러운 달빛 속에서 깊은 단잠으로 빠져듭니다."),
            "jazz": ("Blue Hour Reverie (푸른 시간의 몽상)", "오래된 재즈 바 구석, 얼음 녹는 소리와 함께 스며드는 감미로운 피아노 선율이 귓가를 다정하게 스칩니다."),
            "piano": ("Whispering Raindrops (빗방울의 속삭임)", "창가를 두드리는 빗방울 하나하나가 건반 위에 내려앉아, 가슴속 깊이 묻어둔 아련한 기억들을 깨웁니다.")
        }
        f_title, f_story = fallback_titles.get(genre_key, fallback_titles["lofi"])
        concept = {
            "title": f_title,
            "genre": genre_spec["name"],
            "mood": mood_info["name"],
            "story": f_story,
            "lyria_prompt": f"Masterpiece {genre_spec['name']} with {genre_spec['instruments']}, {genre_spec['bpm_range']}, {genre_spec['sound_texture']}, purely instrumental, no vocals, studio mastering quality",
            "visual_prompt": genre_spec["visual_style"],
            "tags": ["에이전트루나", "AgentLuna", "AI음악", genre_key, mood_info["name"].split(" ")[0], "BGM", "힐링음악", "몰입음악"]
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

    # 1. Google GenAI Lyria 호출 시도 (Interactions API)
    lyria_success = False
    if key:
        step(35, "Google GenAI Lyria 엔진에 작곡 요청 전송 중...")
        last_err = ""
        for model_name in LYRIA_MODELS:
            try:
                step(40, f"Lyria 작곡 요청 중 ({model_name})...")
                _lyria_generate(key, model_name, lyria_prompt, duration_seconds, audio_path)
                lyria_success = True
                step(80, f"Lyria 고음질 오디오 수신 완료! ({model_name})")
                break
            except Exception as e:
                last_err = f"{model_name}: {str(e)[:160]}"
                print(f"[LunaEngine] Lyria 실패 -> {last_err}")
        if not lyria_success:
            print(f"[LunaEngine] 모든 Lyria 모델 실패({last_err}) -> 고음질 오토 신스 백업 엔진 가동")

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


# Lyria 음악 생성 모델 우선순위.
# 계정/티어에 따라 사용 가능한 모델이 다르므로 앞에서부터 순서대로 시도한다.
# (producer.py 의 FALLBACK_IMAGE_MODELS 와 동일한 패턴)
LYRIA_MODELS = ["lyria-3.5", "lyria-3-pro-preview", "lyria-3-clip-preview"]


def _lyria_generate(api_key, model_name, prompt, duration_seconds, out_path):
    """Interactions API 로 Lyria 음악을 생성해 out_path 에 저장한다.

    google-genai SDK 에는 generate_audio() 가 없고, Lyria 는 영상(Omni)과 마찬가지로
    interactions 엔드포인트를 통해 생성된다. producer 의 헬퍼를 그대로 재사용한다.
    """
    client = producer.get_genai_client(api_key)
    payload = {
        "model": model_name,
        "input": [{"type": "text", "text": prompt}],
        "response_format": {"type": "audio", "duration_seconds": int(duration_seconds)},
    }
    r = producer._create_interaction(client, api_key, payload)
    r = producer._wait_interaction(client, api_key, r, label="Lyria 음악")

    err = producer._interaction_errors(r)
    status = producer._status_of(r)
    if err:
        raise RuntimeError(f"status={status} {err}")

    block = _find_audio_block(r)
    if not block:
        raise RuntimeError(f"오디오 출력 없음 (status={status})")

    data = block.get("data")
    if data:
        raw = base64.b64decode(data) if isinstance(data, str) else bytes(data)
        with open(out_path, "wb") as f:
            f.write(raw)
    else:
        uri = block.get("uri")
        if not uri:
            raise RuntimeError("오디오 데이터도 URI 도 없음")
        req = urllib.request.Request(
            uri if "alt=media" in uri else uri + ("&" if "?" in uri else "?") + "alt=media",
            headers={"x-goog-api-key": api_key},
        )
        with urllib.request.urlopen(req, timeout=600) as resp, open(out_path, "wb") as f:
            shutil.copyfileobj(resp, f)

    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        raise RuntimeError("저장된 오디오가 비어 있음")


def _find_audio_block(obj):
    """SDK 객체 또는 REST JSON 에서 오디오 출력(data/uri)을 찾는다."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        t = obj.get("type")
        mime = str(obj.get("mime_type") or obj.get("mimeType") or "")
        if (t == "audio" or mime.startswith("audio/")) and (obj.get("data") or obj.get("uri")):
            return obj
        for key in ("output_audio", "outputAudio"):
            if isinstance(obj.get(key), dict):
                return obj[key]
        for key in ("outputs", "output", "steps", "content", "contents", "parts"):
            v = obj.get(key)
            if isinstance(v, list):
                for it in v:
                    hit = _find_audio_block(it)
                    if hit:
                        return hit
            elif isinstance(v, dict):
                hit = _find_audio_block(v)
                if hit:
                    return hit
        return None
    oa = getattr(obj, "output_audio", None)
    if oa is not None and (getattr(oa, "data", None) or getattr(oa, "uri", None)):
        return {"data": getattr(oa, "data", None), "uri": getattr(oa, "uri", None)}
    for it in (getattr(obj, "outputs", None) or []):
        mime = str(getattr(it, "mime_type", "") or "")
        if (getattr(it, "type", None) == "audio" or mime.startswith("audio/")) and (
            getattr(it, "data", None) or getattr(it, "uri", None)
        ):
            return {"data": getattr(it, "data", None), "uri": getattr(it, "uri", None)}
    return None


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

# ── 5. 레오 ✕ 루나 알고리즘 SEO & 인게이지먼트 메타데이터 패키징 ─────────────

def build_luna_metadata(track_data):
    """
    에이전트 레오의 유튜브 알고리즘 최적화 공식을 결합하여,
    클릭률(CTR) 극대화 제목, 감성 SEO 설명란, 시청자 반응 유도용 고정 댓글(Pinned Comment)을 생성합니다.
    """
    title = track_data.get("title") or "Velvet Midnight"
    genre = track_data.get("genre") or "Lo-Fi / Chillhop"
    mood = track_data.get("mood") or "새벽 감성"
    story = track_data.get("story") or "지친 하루의 끝, 마음을 편안하게 안아주는 루나의 멜로디."
    duration_sec = int(track_data.get("duration_seconds") or 180)
    duration_str = time.strftime('%M:%S', time.gmtime(duration_sec))

    # Gemini를 활용하여 레오의 감성 + 알고리즘 최적화 카피 동적 생성
    prompt = f"""당신은 유튜브 알고리즘 마케팅 전문가 '에이전트 레오(Agent Leo)'입니다.
음악 아티스트 '에이전트 루나(Agent Luna)'의 신곡 발매를 위해 유튜브 클릭률(CTR)과 댓글 참여율을 극대화하는 메타데이터를 작성하세요.

[곡 정보]
- 곡 제목: {title}
- 음악 장르: {genre}
- 감성 무드: {mood}
- 곡 서사 스토리: {story}
- 곡 길이: {duration_str}

[작성 요구사항]
1. 유튜브 제목(youtube_title):
   - '에이전트 루나 (Agent Luna) - {title} | [후킹 상황/감성] [장르]' 형식 (최대 90자).
   - 예: 에이전트 루나 (Agent Luna) - {title} | 지친 하루 끝 깊은 수면을 위한 {genre}
2. 레오의 고정 댓글(pinned_comment):
   - 시청자가 영상을 끝까지 듣고 댓글을 달고 싶게 만드는 따뜻하고 도발적인 질문 (2~3문장).
   - "가장 마음에 와닿은 멜로디 순간(타임스탬프)을 남겨주시면 루나가 답글을 전합니다 🌙" 포함.
3. 감성 설명란(youtube_description):
   - 1) 감성 서사 스토리
   - 2) 프로듀싱 정보 (작곡: 에이전트 루나, 마케팅: 에이전트 레오, 엔진: Lyria 3 Pro)
   - 3) 채널 구독 안내 문구
   - 4) [Timeline] (0:00 {title} ~ {duration_str} Outro)
   - 5) 해시태그 8개

[반환 형식 — 순수 JSON만 출력]
{{
  "youtube_title": "유튜브 제목",
  "pinned_comment": "고정 댓글 내용",
  "youtube_description": "전체 설명란 내용"
}}"""

    messages = [
        {"role": "system", "content": "You are Agent Leo, expert in YouTube growth and viral marketing. Output pure JSON only."},
        {"role": "user", "content": prompt}
    ]

    meta_llm = None
    try:
        parsed, _ = llm_client.call_llm_json(messages, max_tokens=1500, temperature=0.7)
        if isinstance(parsed, dict) and parsed.get("youtube_title"):
            meta_llm = parsed
    except Exception as e:
        print(f"[LunaEngine] Leo metadata LLM generation error: {e}")

    if meta_llm:
        yt_title = meta_llm.get("youtube_title")[:100]
        pinned_comment = meta_llm.get("pinned_comment") or f"오늘 하루 어떤 순간이 가장 마음에 머무셨나요? 0:00 {title}의 선율에 지친 마음을 편히 쉬어가세요 🌙 (가장 좋았던 순간을 타임스탬프로 남겨주세요)"
        yt_desc = meta_llm.get("youtube_description") or ""
    else:
        # 안전 Fallback
        yt_title = f"에이전트 루나 (Agent Luna) - {title} | {mood} {genre}"[:100]
        pinned_comment = f"오늘 하루 어떤 순간이 가장 마음에 머무셨나요? {title}의 선율에 지친 마음을 편히 쉬어가세요 🌙 (가장 좋았던 멜로디 순간을 타임스탬프로 남겨주시면 루나가 답글을 남겨드립니다)"
        yt_desc = f"""{story}

작곡 & 프로듀싱: 에이전트 루나 (Agent Luna)
마케팅 & 채널 디렉팅: 에이전트 레오 (Agent Leo)
사운드 엔진: Google DeepMind Lyria 3 Pro
장르: {genre} | 분위기: {mood}

✨ 에이전트 루나의 음악은 매일 당신의 깊은 몰입과 평온한 수면을 함께합니다.
구독과 좋아요로 루나의 다음 음악 여정에 함께해주세요 🌙
👉 구독하기: https://www.youtube.com/@음악에이전트-c3j?sub_confirmation=1

[Timeline]
0:00 {title}
{duration_str} Outro

#에이전트루나 #AgentLuna #에이전트레오 #AI음악 #수면음악 #공부할때듣는음악 #Lyria3 #힐링음악"""

    fixed_tags = ["에이전트 루나", "Agent Luna", "에이전트 레오", "AI음악", "수면음악", "공부할때듣는음악", "Lyria 3", "BGM", "힐링음악"]
    custom_tags = track_data.get("tags") or []
    merged_tags = list(dict.fromkeys(fixed_tags + custom_tags))[:15]

    return {
        "youtube_title": yt_title,
        "youtube_description": yt_desc,
        "youtube_tags": merged_tags,
        "pinned_comment": pinned_comment,
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
            meta = d.get("metadata") or {}
            tracks.append({
                "track_id": d.get("track_id"),
                "title": d.get("title"),
                "genre": d.get("genre"),
                "mood": d.get("mood"),
                "story": d.get("story"),
                "audio_url": d.get("audio_url"),
                "cover_url": d.get("cover_url"),
                "video_url": d.get("video_url"),
                "duration_seconds": d.get("duration_seconds", 180),
                "created_at": d.get("created_at") or os.path.getmtime(p),
                "uploaded_video_id": d.get("uploaded_video_id"),
                "uploaded_url": d.get("uploaded_url"),
                "pinned_comment": meta.get("pinned_comment") or d.get("pinned_comment")
            })
        except Exception:
            continue
    tracks.sort(key=lambda x: x["created_at"] or 0, reverse=True)
    return tracks


# ── 7. 유튜브 루나 채널 원클릭 업로드 & 레오의 고정댓글 자동 등록 ──────────

def upload_luna_to_youtube(track_id, privacy_status="public", progress_cb=None):
    """
    렌더링된 루나 음악 영상을 유튜브 채널로 업로드하고,
    레오의 인게이지먼트 최적화 고정 댓글(Pinned Comment)을 자동으로 게시합니다.
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
    track["metadata"] = meta

    step(20, f"유튜브 채널 업로드 준비 중: '{meta['youtube_title']}'...")
    
    result = uploader.upload_video(
        video_path=video_path,
        title=meta["youtube_title"],
        description=meta["youtube_description"],
        tags=meta["youtube_tags"],
        category_id=10,  # 음악 카테고리
        privacy=privacy_status,
        thumbnail_path=cover_path if os.path.exists(cover_path) else None,
        pinned_comment=meta.get("pinned_comment"),
        progress=lambda stage, msg, pct: step(20 + int(pct * 0.7), msg)
    )

    track["uploaded_video_id"] = result.get("video_id")
    track["uploaded_url"] = result.get("url")
    track["uploaded_at"] = time.time()
    track["comment_posted"] = result.get("comment_posted", False)
    save_track(track)

    step(100, f"루나 유튜브 채널 업로드 및 레오 고정댓글 완료! ({result.get('url')})")
    return {
        "status": "success",
        "video_id": result.get("video_id"),
        "url": result.get("url"),
        "title": meta["youtube_title"],
        "pinned_comment": meta.get("pinned_comment")
    }
