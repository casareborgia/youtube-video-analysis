"""
하이브리드 TTS & Voice Studio 서비스
1. 무료 고음질 Edge-TTS (인준, 선희, 현수 한국어 성우 / 5개 씬 동시 병렬 합성)
2. Qwen3-TTS 뉴럴 보이스 클로닝 (Zero-shot Voice Clone / Voice Design)
3. 씬별 오디오 + 마스터 오디오 + 대본 텍스트 원클릭 ZIP 번들 다운로드 생성
"""

import os
import sys
import re
import json
import asyncio
import zipfile
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import edge_tts

# 기본 디렉토리 설정
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
VOICES_DIR = DATA_DIR / "voices"
ZIP_DIR = DATA_DIR / "zips"

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
VOICES_DIR.mkdir(parents=True, exist_ok=True)
ZIP_DIR.mkdir(parents=True, exist_ok=True)

# Qwen-TTS 가상환경 경로 탐색
QWEN_TTS_ENV_DIR = os.getenv("QWEN_TTS_DIR")
if QWEN_TTS_ENV_DIR:
    QWEN_TTS_DIR = Path(QWEN_TTS_ENV_DIR)
else:
    QWEN_TTS_DIR = BASE_DIR.parent / "QWEN-tts"
    if not QWEN_TTS_DIR.exists():
        QWEN_TTS_DIR = Path.home() / "coding" / "QWEN-tts"

QWEN_PYTHON_ENV = os.getenv("QWEN_PYTHON")
if QWEN_PYTHON_ENV:
    QWEN_PYTHON = Path(QWEN_PYTHON_ENV)
else:
    QWEN_PYTHON = QWEN_TTS_DIR / ".venv" / "bin" / "python"

# 기본 무료 고품질 Edge-TTS 한국어 프리셋
EDGE_PRESETS = [
    {
        "id": "edge_injoon",
        "voice_id": "ko-KR-InJoonNeural",
        "engine": "edge-tts",
        "language": "korean",
        "name": "⚡ 인준 (남성 다큐·지식 전문)",
        "gender": "male",
        "description": "차분하고 신뢰감 넘치는 다큐멘터리/지식 전달 어조 (무료 고속)",
        "default_rate": "+5%",
        "is_free": True,
    },
    {
        "id": "edge_sunhi",
        "voice_id": "ko-KR-SunHiNeural",
        "engine": "edge-tts",
        "language": "korean",
        "name": "⚡ 선희 (여성 다큐·뉴스 전문)",
        "gender": "female",
        "description": "또렷하고 전달력 높은 전문 아나운서 어조 (무료 고속)",
        "default_rate": "+3%",
        "is_free": True,
    },
    {
        "id": "edge_hyunsu",
        "voice_id": "ko-KR-HyunsuNeural",
        "engine": "edge-tts",
        "language": "korean",
        "name": "⚡ 현수 (남성 스토리텔러)",
        "gender": "male",
        "description": "몰입감 높은 역동적 스토리텔러/유튜브 해설 어조 (무료 고속)",
        "default_rate": "+4%",
        "is_free": True,
    },
    {
        "id": "edge_andrew_en",
        "voice_id": "en-US-AndrewMultilingualNeural",
        "engine": "edge-tts",
        "language": "english",
        "name": "⚡ Andrew (English storyteller)",
        "gender": "male",
        "description": "따뜻하고 자연스러운 영어 이야기꾼 어조 — 해외 쇼츠(Shiji Files) 기본 (무료 고속)",
        "default_rate": "+0%",
        "is_free": True,
    },
]


def voice_language(voice_id: str) -> Optional[str]:
    """edge 프리셋·코드의 언어. 언어를 따라가는 목소리(Qwen3·내 목소리)는 None."""
    preset = next((ep for ep in EDGE_PRESETS if ep["id"] == voice_id), None)
    if preset:
        return preset.get("language")
    if str(voice_id or "").startswith("ko-KR-"):
        return "korean"
    return None

# Qwen3-TTS 프리셋
QWEN_PRESETS = [
    {
        "id": "my_voice",
        "engine": "qwen-tts",
        "name": "👤 내 목소리 (Voice Clone)",
        "type": "clone",
        "description": "사용자가 업로드/등록한 참조 음성 기반 맞춤형 복제 보이스",
        "is_custom": True,
    },
    {
        "id": "docu_male",
        "engine": "qwen-tts",
        "name": "🎙️ 진중한 다큐멘터리 남성 성우 (Ryan)",
        "type": "preset",
        "speaker": "ryan",
        "description": "차분하고 신뢰감 넘치는 묵직한 내레이션 (Qwen3-TTS)",
        "instruct": "차분하고 진중하며 긴장감 있는 다큐멘터리 톤으로 말해줘",
    },
    {
        "id": "docu_female",
        "engine": "qwen-tts",
        "name": "🎙️ 명확하고 차분한 여성 성우 (Sohee)",
        "type": "preset",
        "speaker": "sohee",
        "description": "지식 전달 및 호기심을 유발하는 맑고 지적인 톤 (Qwen3-TTS)",
        "instruct": "또박또박하고 차분하며 전달력 높은 톤으로 말해줘",
    },
    {
        "id": "mystery_narrator",
        "engine": "qwen-tts",
        "name": "🎙️ 미스터리 / 스릴러 성우 (Uncle Fu)",
        "type": "preset",
        "speaker": "uncle_fu",
        "description": "어둡고 숨막히는 미스터리/괴담/SF 분위기 연출 (Qwen3-TTS)",
        "instruct": "어둡고 낮은 톤으로 긴장감을 조성하며 속삭이듯 말해줘",
    },
    {
        "id": "shorts_energetic",
        "engine": "qwen-tts",
        "name": "🎙️ 트렌디 쇼츠 / 릴스 성우 (Vivian)",
        "type": "preset",
        "speaker": "vivian",
        "description": "빠르고 귀에 꽂히는 에너지 넘치는 톤 (Qwen3-TTS)",
        "instruct": "빠른 속도로 활기차고 귀에 꽂히게 말해줘",
    },
    {
        "id": "voice_design",
        "engine": "qwen-tts",
        "name": "🎨 AI 보이스 디자인 (Voice Design)",
        "type": "design",
        "description": "원하는 목소리 특징을 자연어 프롬프트로 직접 설계 (Qwen3-TTS)",
        "instruct": "50대 중후반의 깊고 묵직한 다큐멘터리 남성 해설가 톤",
    },
]

# 지원 언어
SUPPORTED_LANGUAGES = [
    {"id": "korean", "name": "🇰🇷 한국어 (Korean)"},
    {"id": "english", "name": "🇺🇸 English (영어)"},
    {"id": "japanese", "name": "🇯🇵 日本語 (일본어)"},
    {"id": "chinese", "name": "🇨🇳 中文 (중국어)"},
    {"id": "french", "name": "🇫🇷 Français (프랑스어)"},
    {"id": "german", "name": "🇩🇪 Deutsch (독일어)"},
    {"id": "spanish", "name": "🇪🇸 Español (스페인어)"},
]

RUNNER_SCRIPT = BASE_DIR / "qwen_tts_runner.py"


def clean_narration_text(text: str) -> str:
    """마크다운 기호 및 특수문자를 제거하여 TTS가 자연스럽게 발화할 수 있도록 정제"""
    if not text:
        return ""
    clean = re.sub(r'[*_#`"|\-\[\]\(\)]', ' ', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


_SENTENCE_END_RE = re.compile(r"[.!?…。！？]['\"”’)]*$")
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$")


def _strip_punct(word: str) -> str:
    return re.sub(r"[\W_]+", "", word or "")


def word_boundaries_to_captions(boundaries: List[Dict[str, Any]], text: Optional[str] = None,
                                page_break_at_end: bool = True) -> List[Dict[str, Any]]:
    """edge-tts WordBoundary(offset·duration, 100ns 틱) → shorts_engine 자막 토큰.

    규약(작업계획서 S-1 메모): 새 어절은 text 앞에 공백 1칸, 문장 끝(마침표·물음표·느낌표)에는 pageBreakAfter.
    Azure 는 한국어 어절을 구두점 없이 보내므로(실측 2026-10-19: "손해입니다." → "손해입니다") 원문 text 를 주면
    어절을 순서대로 맞춰 구두점을 되살리고 문장 끝을 판정한다. 구두점만 있는 이벤트는 앞 어절에 붙인다.
    마지막 토큰은 항상 pageBreakAfter(씬 단위 합성이므로 씬 끝 = 페이지 끝).
    """
    source = [w for w in re.split(r"\s+", text or "") if w]
    cursor = 0
    out: List[Dict[str, Any]] = []
    for b in boundaries or []:
        word = str(b.get("text") or "").strip()
        if not word:
            continue
        # 원문 어절과 정렬: 구두점을 뗀 형태가 같은 어절을 앞에서부터 3칸 안에서 찾는다
        if source and not _PUNCT_ONLY_RE.match(word):
            core = _strip_punct(word)
            for j in range(cursor, min(cursor + 3, len(source))):
                if core and _strip_punct(source[j]) == core:
                    word = source[j]
                    cursor = j + 1
                    break
        start_ms = int(round(int(b.get("offset") or 0) / 10000))
        end_ms = int(round((int(b.get("offset") or 0) + int(b.get("duration") or 0)) / 10000))
        end_ms = max(start_ms + 1, end_ms)
        if out and _PUNCT_ONLY_RE.match(word):
            out[-1]["text"] += word
            out[-1]["endMs"] = max(out[-1]["endMs"], end_ms)
            if _SENTENCE_END_RE.search(word):
                out[-1]["pageBreakAfter"] = True
            continue
        tok: Dict[str, Any] = {"text": (" " if out else "") + word, "startMs": start_ms, "endMs": end_ms}
        if _SENTENCE_END_RE.search(word):
            tok["pageBreakAfter"] = True
        out.append(tok)
    # 이벤트가 겹치거나 역행하면 단조 증가로 보정한다
    for i in range(1, len(out)):
        if out[i]["startMs"] < out[i - 1]["endMs"]:
            out[i - 1]["endMs"] = out[i]["startMs"] if out[i]["startMs"] > out[i - 1]["startMs"] else out[i - 1]["endMs"]
    if out and page_break_at_end:
        out[-1]["pageBreakAfter"] = True
    return out


def merge_audio_files(input_files: List[str], output_file: str) -> bool:
    """여러 MP3/WAV 오디오 파일을 하나의 완전한 MP3 파일로 병합 (ffmpeg 또는 바이너리 결합)"""
    existing_files = [f for f in input_files if os.path.exists(f)]
    if not existing_files:
        return False

    # 1. ffmpeg concat 시도
    concat_list_file = os.path.splitext(output_file)[0] + "_concat.txt"
    try:
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for ef in existing_files:
                f.write(f"file '{os.path.abspath(ef)}'\n")

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list_file,
            "-c:a", "libmp3lame", "-q:a", "2",
            output_file
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)
        if os.path.exists(concat_list_file):
            os.remove(concat_list_file)
        if res.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 100:
            return True
    except Exception:
        if os.path.exists(concat_list_file):
            os.remove(concat_list_file)

    # 2. MP3 단순 바이너리 이어붙이기 폴백
    try:
        with open(output_file, "wb") as outfile:
            for fpath in existing_files:
                with open(fpath, "rb") as infile:
                    outfile.write(infile.read())
        return True
    except Exception as e:
        print(f"[Merge Audio Fallback Error] {e}")
        return False


def _runner_error(proc) -> str:
    """qwen_tts_runner 가 stdout 마지막 줄에 남긴 {"status": "error", "error": ...} 를 꺼낸다. 없으면 stderr 끝줄."""
    for line in reversed((proc.stdout or "").strip().splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    tail = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
    return tail[-1] if tail else f"종료 코드 {proc.returncode}"


class TTSService:
    @staticmethod
    def get_registered_voices() -> List[Dict[str, Any]]:
        """사용 가능한 모든 보이스 (Edge-TTS 무료 성우 + 등록된 내 목소리 + Qwen3 프리셋) 반환"""
        voices = []

        # 1. Edge-TTS 프리셋 (최상단)
        for ep in EDGE_PRESETS:
            voices.append(dict(ep))

        # 2. 내 목소리 프로필 확인
        custom_voice_file = VOICES_DIR / "my_voice.wav"
        custom_voice_meta = VOICES_DIR / "my_voice.json"
        has_custom_voice = custom_voice_file.exists()
        custom_name = "👤 내 목소리 (Voice Clone)"
        custom_desc = "내 목소리 샘플이 등록되어 있습니다." if has_custom_voice else "목소리 샘플을 업로드하여 등록하세요."

        if custom_voice_meta.exists():
            try:
                with open(custom_voice_meta, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    custom_name = f"👤 {meta.get('name', '내 목소리')} (Voice Clone)"
                    custom_desc = meta.get("description", custom_desc)
            except Exception:
                pass

        for qp in QWEN_PRESETS:
            item = dict(qp)
            if item.get("id") == "my_voice":
                item["name"] = custom_name
                item["description"] = custom_desc
                item["is_registered"] = has_custom_voice
            voices.append(item)

        return voices

    @staticmethod
    def register_my_voice(audio_file_path: Path, voice_name: str = "내 목소리", ref_text: str = "") -> Dict[str, Any]:
        """사용자의 음성 샘플을 등록하여 Voice Clone 참조 음성으로 저장"""
        dest_audio = VOICES_DIR / "my_voice.wav"
        dest_meta = VOICES_DIR / "my_voice.json"

        cmd = ["ffmpeg", "-y", "-i", str(audio_file_path), "-ar", "24000", "-ac", "1", str(dest_audio)]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except Exception:
            shutil.copyfile(audio_file_path, dest_audio)

        meta = {
            "name": voice_name,
            "ref_text": ref_text.strip(),
            "created_at": str(Path(dest_audio).stat().st_mtime if dest_audio.exists() else 0),
        }
        with open(dest_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "voice_id": "my_voice",
            "name": voice_name,
            "ref_audio": str(dest_audio),
            "ref_text": ref_text,
        }

    @classmethod
    async def synthesize_edge_tts_single(
        cls,
        text: str,
        voice_code: str = "ko-KR-InJoonNeural",
        rate: str = "+5%",
        pitch: str = "+0Hz",
        output_file: str = "output.mp3",
        with_word_boundaries: bool = False,
    ):
        """단일 문장 Edge-TTS 음성 합성.

        기본(with_word_boundaries=False)은 기존과 동일하게 파일 경로(str)를 돌려준다.
        with_word_boundaries=True 면 Communicate.stream() 의 WordBoundary 이벤트(offset·duration, 100ns 단위)를 모아
        shorts_engine 자막 토큰({"text", "startMs", "endMs", "pageBreakAfter"}) 으로 바꿔
        {"file", "captions", "word_count"} 를 돌려준다 (작업계획서_쇼츠_자동화 S-2 3항).
        """
        clean_text = clean_narration_text(text)
        if not clean_text or len(clean_text) < 2:
            return None
        if not with_word_boundaries:
            comm = edge_tts.Communicate(clean_text, voice=voice_code, rate=rate, pitch=pitch)
            await comm.save(output_file)
            return output_file

        # edge-tts 7.x 는 boundary="WordBoundary" 를 줘야 단어 이벤트를 보낸다(기본은 SentenceBoundary). 6.x 는 인자가 없고 항상 단어 단위.
        try:
            comm = edge_tts.Communicate(clean_text, voice=voice_code, rate=rate, pitch=pitch, boundary="WordBoundary")
        except TypeError:
            comm = edge_tts.Communicate(clean_text, voice=voice_code, rate=rate, pitch=pitch)
        boundaries: List[Dict[str, Any]] = []
        try:
            with open(output_file, "wb") as f:
                async for chunk in comm.stream():
                    ctype = chunk.get("type")
                    if ctype == "audio":
                        f.write(chunk.get("data") or b"")
                    elif ctype == "WordBoundary":
                        boundaries.append({"offset": int(chunk.get("offset") or 0),
                                           "duration": int(chunk.get("duration") or 0),
                                           "text": str(chunk.get("text") or "")})
        except Exception:
            # 중간에 끊긴 반쪽 파일이 성공 결과로 쓰이지 않게 지우고 오류는 그대로 올린다
            if os.path.exists(output_file):
                os.remove(output_file)
            raise
        captions = word_boundaries_to_captions(boundaries, text=clean_text)
        return {"file": output_file, "captions": captions, "word_count": len(captions)}

    @classmethod
    def synthesize_speech(
        cls,
        text: str,
        voice_id: str = "edge_injoon",
        scene_index: int = 1,
        topic_slug: str = "scene",
        language: str = "korean"
    ) -> Dict[str, Any]:
        """단일 씬 텍스트 음성 합성 (Edge-TTS 또는 Qwen-TTS 분기)"""
        slug = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', topic_slug or "scene")[:25]
        clean_text = clean_narration_text(text)
        if not clean_text or len(clean_text) < 2:
            return {"status": "error", "message": "합성할 유효한 대본 텍스트가 없습니다."}

        # 1. Edge-TTS 프리셋 확인
        edge_map = {ep["id"]: ep for ep in EDGE_PRESETS}
        if voice_id in edge_map or voice_id.startswith("ko-KR-"):
            voice_conf = edge_map.get(voice_id, EDGE_PRESETS[0])
            voice_code = voice_conf.get("voice_id", "ko-KR-InJoonNeural") if voice_id in edge_map else voice_id
            rate = voice_conf.get("default_rate", "+5%")

            out_filename = f"{slug}_scene_{scene_index:02d}.mp3"
            out_path = AUDIO_DIR / out_filename

            # edge-tts 가 실패해도 Qwen 기본 화자로 넘어가지 않는다 — 다른 목소리가 성공으로 나가면 고장을 알아챌 수 없다
            if out_path.exists():
                out_path.unlink()
            try:
                asyncio.run(cls.synthesize_edge_tts_single(clean_text, voice_code=voice_code, rate=rate, output_file=str(out_path)))
            except Exception as e:
                if out_path.exists():
                    out_path.unlink()
                return {"status": "error", "engine": "edge-tts", "message": f"Edge-TTS 합성 실패: {type(e).__name__}: {e}"}
            if out_path.exists() and out_path.stat().st_size > 0:
                return {
                    "status": "success",
                    "scene_index": scene_index,
                    "voice_id": voice_id,
                    "voice_name": voice_conf.get("name", voice_code),
                    "audio_url": f"/api/audio/{out_filename}",
                    "filename": out_filename,
                    "engine": "edge-tts"
                }
            if out_path.exists():
                out_path.unlink()
            return {"status": "error", "engine": "edge-tts", "message": "Edge-TTS 합성 실패: 음성이 비어 있습니다."}

        # 2. Qwen-TTS 또는 Voice Clone 실행
        out_filename = f"{slug}_scene_{scene_index:02d}.wav"
        out_path = AUDIO_DIR / out_filename

        qwen_map = {qp["id"]: qp for qp in QWEN_PRESETS}
        if voice_id not in qwen_map:
            return {"status": "error", "message": f"알 수 없는 목소리입니다: {voice_id}"}
        voice_config = qwen_map[voice_id]
        lang_code = language.lower() if language else "korean"

        cmd = [
            str(QWEN_PYTHON) if QWEN_PYTHON.exists() else sys.executable,
            str(RUNNER_SCRIPT),
            "--text", clean_text,
            "--output", str(out_path),
            "--language", lang_code
        ]

        if voice_id == "my_voice":
            ref_audio = VOICES_DIR / "my_voice.wav"
            ref_meta = VOICES_DIR / "my_voice.json"
            ref_text = ""
            if ref_meta.exists():
                try:
                    with open(ref_meta, "r", encoding="utf-8") as f:
                        ref_text = json.load(f).get("ref_text", "")
                except Exception:
                    pass
            if ref_audio.exists():
                cmd.extend(["--mode", "clone", "--ref_audio", str(ref_audio), "--ref_text", ref_text])
            else:
                cmd.extend(["--mode", "preset", "--speaker", "ryan", "--instruct", "진중한 내레이션"])
        elif voice_id == "voice_design":
            cmd.extend([
                "--mode", "design",
                "--instruct", voice_config.get("instruct", "50대 중후반의 깊고 묵직한 다큐멘터리 남성 해설가 톤")
            ])
        else:
            cmd.extend([
                "--mode", "preset",
                "--speaker", voice_config.get("speaker", "sohee"),
                "--instruct", voice_config.get("instruct", "")
            ])

        # 지난 실행의 같은 이름 파일이 남아 있으면 실패가 성공으로 보이므로 먼저 지운다
        if out_path.exists():
            out_path.unlink()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {"status": "error", "engine": "qwen-tts", "message": "Qwen-TTS 합성 실패: 120초 안에 끝나지 않았습니다 (시간 초과)."}
        except Exception as e:
            return {"status": "error", "engine": "qwen-tts", "message": f"Qwen-TTS 실행 실패: {e}"}

        if proc.returncode == 0 and out_path.exists():
            return {
                "status": "success",
                "scene_index": scene_index,
                "voice_id": voice_id,
                "voice_name": voice_config["name"],
                "audio_url": f"/api/audio/{out_filename}",
                "filename": out_filename,
                "engine": "qwen-tts"
            }
        return {"status": "error", "engine": "qwen-tts", "message": f"Qwen-TTS 합성 실패: {_runner_error(proc)}"}

    @classmethod
    def generate_all_scenes_audio_batch(
        cls,
        scenes: List[Dict[str, Any]],
        topic: str,
        voice_id: str = "edge_injoon",
        rate: str = "+5%"
    ) -> Dict[str, Any]:
        """
        전체 씬 일괄 고속 병렬 합성(Edge-TTS 비동기 Semaphore) + 마스터 오디오 병합 + 원클릭 ZIP 번들링
        """
        safe_topic = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', topic or "video")[:30]
        topic_audio_dir = AUDIO_DIR / safe_topic
        topic_audio_dir.mkdir(parents=True, exist_ok=True)

        edge_map = {ep["id"]: ep for ep in EDGE_PRESETS}
        is_edge = voice_id in edge_map or voice_id.startswith("ko-KR-")
        edge_voice_code = edge_map.get(voice_id, {}).get("voice_id", voice_id if voice_id.startswith("ko-KR-") else "ko-KR-InJoonNeural")

        results = []
        audio_files_for_merge = []
        edge_tasks = []
        errors = []

        for i, scene in enumerate(scenes, 1):
            scene_num = scene.get("scene_num") or scene.get("scene_index", i)
            narration = scene.get("subtitle") or scene.get("narration") or ""
            time_range = scene.get("time_range") or f"씬 {scene_num}"
            clean_text = clean_narration_text(narration)

            ext = "mp3" if is_edge else "wav"
            filename = f"scene_{scene_num:02d}.{ext}"
            out_path = topic_audio_dir / filename

            item = {
                "scene_num": scene_num,
                "time_range": time_range,
                "subtitle": narration,
                "audio_url": None,
                "audio_file": str(out_path),
            }
            # 지난번 결과가 남아 있으면 이번 실패가 성공처럼 ZIP 에 들어가므로 먼저 지운다
            if out_path.exists():
                out_path.unlink()

            if not clean_text or len(clean_text) < 2:
                results.append(item)
                continue

            if is_edge:
                edge_tasks.append((clean_text, str(out_path), item))
            else:
                # Qwen-TTS 단일 생성
                res = cls.synthesize_speech(clean_text, voice_id=voice_id, scene_index=scene_num, topic_slug=safe_topic)
                src = AUDIO_DIR / (res.get("filename") or "")
                if res.get("status") == "success" and src.is_file():
                    shutil.move(str(src), str(out_path))
                else:
                    item["error"] = res.get("message") or "음성 합성에 실패했습니다."
                    errors.append({"scene_num": scene_num, "message": item["error"]})
                    results.append(item)
                    continue

            item["audio_url"] = f"/api/audio/{safe_topic}/{filename}"
            results.append(item)
            audio_files_for_merge.append(str(out_path))

        # Edge-TTS 병렬 합성 실행 (최대 5개 동시). 실패한 씬은 표시만 하고 나머지는 계속 만든다
        if edge_tasks:
            async def _batch_edge():
                sem = asyncio.Semaphore(5)
                async def _one(t, p):
                    async with sem:
                        comm = edge_tts.Communicate(t, edge_voice_code, rate=rate)
                        await comm.save(p)
                return await asyncio.gather(*[_one(t, p) for t, p, _ in edge_tasks], return_exceptions=True)

            outcomes = asyncio.run(_batch_edge())
            for (_t, p, item), outcome in zip(edge_tasks, outcomes):
                if isinstance(outcome, BaseException) or not os.path.exists(p) or os.path.getsize(p) == 0:
                    if os.path.exists(p):
                        os.remove(p)
                    reason = f"{type(outcome).__name__}: {outcome}" if isinstance(outcome, BaseException) else "음성이 비어 있습니다."
                    item["error"] = f"Edge-TTS 합성 실패: {reason}"
                    item["audio_url"] = None
                    errors.append({"scene_num": item["scene_num"], "message": item["error"]})
                    if p in audio_files_for_merge:
                        audio_files_for_merge.remove(p)
            errors.sort(key=lambda e: e["scene_num"])

        # 1. 전체 마스터 오디오 병합 (full_narration.mp3)
        full_filename = "full_narration.mp3"
        full_path = topic_audio_dir / full_filename
        existing_files = [f for f in audio_files_for_merge if os.path.exists(f)]
        merge_audio_files(existing_files, str(full_path))

        # 2. 원클릭 일괄 다운로드 ZIP 압축파일 생성
        zip_filename = f"{safe_topic}_전체오디오_일괄다운로드.zip"
        zip_path = ZIP_DIR / zip_filename

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            # 전체 마스터 오디오 추가
            if full_path.exists():
                zinfo = zipfile.ZipInfo.from_file(str(full_path), arcname="00_전체_나레이션_마스터.mp3")
                zinfo.flag_bits |= 0x800
                with open(full_path, "rb") as f:
                    zipf.writestr(zinfo, f.read())

            # 씬별 오디오 추가
            for item in results:
                num = item["scene_num"]
                time_tag = item["time_range"].replace(" ", "").replace("~", "_").replace(":", "")
                arc_name = f"{num:02d}_씬{num:02d}_{time_tag}_나레이션.{ext}"
                if os.path.exists(item["audio_file"]):
                    zinfo = zipfile.ZipInfo.from_file(item["audio_file"], arcname=arc_name)
                    zinfo.flag_bits |= 0x800
                    with open(item["audio_file"], "rb") as f:
                        zipf.writestr(zinfo, f.read())

            # 대본 및 타임스탬프 텍스트 파일 추가
            script_content = f"🎬 [{topic}] 씬별 나레이션 대본 & 타임스탬프\n" + "=" * 50 + "\n\n"
            for item in results:
                script_content += f"[씬 {item['scene_num']:02d}] {item['time_range']}\n{item['subtitle'] or '(대본 없음)'}\n\n"

            script_zinfo = zipfile.ZipInfo("대본_및_타임스탬프.txt")
            script_zinfo.flag_bits |= 0x800
            zipf.writestr(script_zinfo, script_content.encode("utf-8"))

        made = [r for r in results if r.get("audio_url")]
        if errors and not made:
            return {"status": "error", "message": errors[0]["message"], "errors": errors, "scenes_audio": results,
                    "topic": topic, "voice_id": voice_id, "total_scenes": len(results)}

        return {
            "status": "success",
            "topic": topic,
            "voice_id": voice_id,
            "errors": errors,
            "scenes_audio": results,
            "full_audio_url": f"/api/audio/{safe_topic}/{full_filename}",
            "zip_download_url": f"/api/audio/zip/{zip_filename}",
            "zip_filename": zip_filename,
            "total_scenes": len(results)
        }
