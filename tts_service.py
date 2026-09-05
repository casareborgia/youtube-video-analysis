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
        "name": "⚡ 현수 (남성 스토리텔러)",
        "gender": "male",
        "description": "몰입감 높은 역동적 스토리텔러/유튜브 해설 어조 (무료 고속)",
        "default_rate": "+4%",
        "is_free": True,
    },
]

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
        output_file: str = "output.mp3"
    ) -> str:
        """단일 문장 Edge-TTS 음성 합성"""
        clean_text = clean_narration_text(text)
        if not clean_text or len(clean_text) < 2:
            return None
        comm = edge_tts.Communicate(clean_text, voice=voice_code, rate=rate, pitch=pitch)
        await comm.save(output_file)
        return output_file

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

            try:
                asyncio.run(cls.synthesize_edge_tts_single(clean_text, voice_code=voice_code, rate=rate, output_file=str(out_path)))
                if out_path.exists():
                    return {
                        "status": "success",
                        "scene_index": scene_index,
                        "voice_id": voice_id,
                        "voice_name": voice_conf.get("name", voice_code),
                        "audio_url": f"/api/audio/{out_filename}",
                        "filename": out_filename,
                        "engine": "edge-tts"
                    }
            except Exception as e:
                print(f"[Edge-TTS Error] {e}")

        # 2. Qwen-TTS 또는 Voice Clone 실행
        out_filename = f"{slug}_scene_{scene_index:02d}.wav"
        out_path = AUDIO_DIR / out_filename

        qwen_map = {qp["id"]: qp for qp in QWEN_PRESETS}
        voice_config = qwen_map.get(voice_id, QWEN_PRESETS[1])
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

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if out_path.exists():
                return {
                    "status": "success",
                    "scene_index": scene_index,
                    "voice_id": voice_id,
                    "voice_name": voice_config["name"],
                    "audio_url": f"/api/audio/{out_filename}",
                    "filename": out_filename,
                    "engine": "qwen-tts"
                }
        except Exception as e:
            print(f"[Qwen-TTS Run Error] {e}")

        # 파일이 생성되었는지 최종 확인
        if out_path.exists():
            return {
                "status": "success",
                "scene_index": scene_index,
                "voice_id": voice_id,
                "voice_name": voice_config["name"],
                "audio_url": f"/api/audio/{out_filename}",
                "filename": out_filename,
                "engine": "qwen-tts"
            }

        return {"status": "error", "message": "음성 합성에 실패했습니다."}

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

            if not clean_text or len(clean_text) < 2:
                results.append(item)
                continue

            if is_edge:
                edge_tasks.append((clean_text, str(out_path)))
            else:
                # Qwen-TTS 단일 생성
                res = cls.synthesize_speech(clean_text, voice_id=voice_id, scene_index=scene_num, topic_slug=safe_topic)
                if res.get("status") == "success":
                    if os.path.exists(res.get("filename", "")):
                        shutil.move(res["filename"], str(out_path))

            item["audio_url"] = f"/api/audio/{safe_topic}/{filename}"
            results.append(item)
            audio_files_for_merge.append(str(out_path))

        # Edge-TTS 병렬 합성 실행 (최대 5개 동시)
        if edge_tasks:
            async def _batch_edge():
                sem = asyncio.Semaphore(5)
                async def _one(t, p):
                    async with sem:
                        comm = edge_tts.Communicate(t, edge_voice_code, rate=rate)
                        await comm.save(p)
                await asyncio.gather(*[_one(t, p) for t, p in edge_tasks])

            asyncio.run(_batch_edge())

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

        return {
            "status": "success",
            "topic": topic,
            "voice_id": voice_id,
            "scenes_audio": results,
            "full_audio_url": f"/api/audio/{safe_topic}/{full_filename}",
            "zip_download_url": f"/api/audio/zip/{zip_filename}",
            "zip_filename": zip_filename,
            "total_scenes": len(results)
        }
