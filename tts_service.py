"""
Qwen-TTS Integration Service
로컬 Qwen3-TTS 엔진(/Users/leeseungjun/coding/QWEN-tts)과 연동하여
1. 기본 프리셋 고품질 음성 합성
2. 사용자 목소리 복제(Zero-shot Voice Clone / 내 목소리 학습) 음성 합성
을 수행하는 백엔드 브릿지 서비스입니다.
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

QWEN_TTS_DIR = Path("/Users/leeseungjun/coding/QWEN-tts")
QWEN_PYTHON = QWEN_TTS_DIR / ".venv" / "bin" / "python"

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "data" / "audio"
VOICES_DIR = BASE_DIR / "data" / "voices"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
VOICES_DIR.mkdir(parents=True, exist_ok=True)

# 기본 내장 보이스 프리셋 정의 (Qwen3-TTS 공식 화자 매핑)
PRESET_VOICES = [
    {
        "id": "my_voice",
        "name": "👤 내 목소리 (Voice Clone)",
        "type": "clone",
        "description": "사용자가 업로드/등록한 참조 음성 기반 맞춤형 복제 보이스",
        "is_custom": True
    },
    {
        "id": "docu_male",
        "name": "🎙️ 진중한 다큐멘터리 남성 성우 (Ryan)",
        "type": "preset",
        "speaker": "ryan",
        "description": "차분하고 신뢰감 넘치는 묵직한 내레이션",
        "instruct": "차분하고 진중하며 긴장감 있는 다큐멘터리 톤으로 말해줘"
    },
    {
        "id": "docu_female",
        "name": "🎙️ 명확하고 차분한 여성 성우 (Sohee)",
        "type": "preset",
        "speaker": "sohee",
        "description": "지식 전달 및 호기심을 유발하는 맑고 지적인 톤",
        "instruct": "또박또박하고 차분하며 전달력 높은 톤으로 말해줘"
    },
    {
        "id": "mystery_narrator",
        "name": "🎙️ 미스터리 / 스릴러 성우 (Uncle Fu)",
        "type": "preset",
        "speaker": "uncle_fu",
        "description": "어둡고 숨막히는 미스터리/괴담/SF 분위기 연출",
        "instruct": "어둡고 낮은 톤으로 긴장감을 조성하며 속삭이듯 말해줘"
    },
    {
        "id": "shorts_energetic",
        "name": "🎙️ 트렌디 쇼츠 / 릴스 성우 (Vivian)",
        "type": "preset",
        "speaker": "vivian",
        "description": "빠르고 귀에 꽂히는 에너지 넘치는 톤",
        "instruct": "빠른 속도로 활기차고 귀에 꽂히게 말해줘"
    },
    {
        "id": "voice_design",
        "name": "🎨 AI 보이스 디자인 (Voice Design)",
        "type": "design",
        "description": "원하는 목소리 특징을 자연어 프롬프트로 직접 설계",
        "instruct": "50대 중후반의 깊고 묵직한 다큐멘터리 남성 해설가 톤"
    }
]

# 지원 언어 정의
SUPPORTED_LANGUAGES = [
    {"id": "korean", "name": "🇰🇷 한국어 (Korean)"},
    {"id": "english", "name": "🇺🇸 English (영어)"},
    {"id": "japanese", "name": "🇯🇵 日本語 (일본어)"},
    {"id": "chinese", "name": "🇨🇳 中文 (중국어)"},
    {"id": "french", "name": "🇫🇷 Français (프랑스어)"},
    {"id": "german", "name": "🇩🇪 Deutsch (독일어)"},
    {"id": "spanish", "name": "🇪🇸 Español (스페인어)"}
]

# Qwen-TTS 실행을 위한 독립 파이썬 스크립트 템플릿
RUNNER_SCRIPT = BASE_DIR / "qwen_tts_runner.py"

def ensure_runner_script():
    """Qwen-TTS 가상환경에서 실행될 격리 스크립트 생성"""
    code = '''import os
import sys
import json
import argparse
import soundfile as sf
import numpy as np

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["preset", "clone", "design"])
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ref_audio", default="")
    parser.add_argument("--ref_text", default="")
    parser.add_argument("--speaker", default="sohee")
    parser.add_argument("--instruct", default="")
    parser.add_argument("--language", default="korean")
    args = parser.parse_args()

    text = args.text.strip()
    output_path = args.output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        import torch
        from qwen_tts import Qwen3TTSModel
        
        # Mac CPU 환경에서 안정적 구동
        device = "cpu"
        dtype = torch.float32

        if args.mode == "clone" and args.ref_audio and os.path.exists(args.ref_audio):
            # 1. Voice Clone 모드 (내 목소리 복제 - Base 모델)
            model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
                device_map=device,
                dtype=dtype
            )
            wavs, sr = model.generate_voice_clone(
                text=text,
                language=args.language,
                ref_audio=args.ref_audio,
                ref_text=args.ref_text or None,
                x_vector_only_mode=(not bool(args.ref_text))
            )
            sf.write(output_path, wavs[0], sr)
            print(json.dumps({"status": "success", "output": output_path, "sample_rate": sr}))
            return

        elif args.mode == "design":
            # 2. Voice Design 모드 (자연어 보이스 설계 - VoiceDesign 모델)
            model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                device_map=device,
                dtype=dtype
            )
            instruct_text = args.instruct or "차분하고 깊은 40대 남성 내레이터"
            wavs, sr = model.generate_voice_design(
                text=text,
                language=args.language,
                instruct=instruct_text
            )
            sf.write(output_path, wavs[0], sr)
            print(json.dumps({"status": "success", "output": output_path, "sample_rate": sr}))
            return

        else:
            # 3. Custom Voice / Preset 모드 (지정 화자 + 어조 제어 - CustomVoice 모델)
            model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                device_map=device,
                dtype=dtype
            )
            speaker_name = args.speaker if args.speaker in model.get_supported_speakers() else "sohee"
            wavs, sr = model.generate_custom_voice(
                text=text,
                language=args.language,
                speaker=speaker_name,
                instruct=args.instruct
            )
            sf.write(output_path, wavs[0], sr)
            print(json.dumps({"status": "success", "output": output_path, "sample_rate": sr}))
            return

    except Exception as e:
        print(f"[Qwen-TTS Fallback/Log] {str(e)}", file=sys.stderr)
        
        try:
            aiff_tmp = output_path + ".aiff"
            subprocess_voice = "Yuna"
            os.system(f'say -v "{subprocess_voice}" "{text}" -o "{aiff_tmp}"')
            if os.path.exists(aiff_tmp):
                os.system(f'ffmpeg -y -i "{aiff_tmp}" "{output_path}" >/dev/null 2>&1')
                if os.path.exists(aiff_tmp):
                    os.remove(aiff_tmp)
                print(json.dumps({"status": "success", "output": output_path, "note": "fallback_system_tts"}))
                return
        except Exception:
            pass
            
        print(json.dumps({"status": "error", "error": str(e)}))

if __name__ == "__main__":
    main()
'''
    with open(RUNNER_SCRIPT, "w", encoding="utf-8") as f:
        f.write(code)

ensure_runner_script()

class TTSService:
    """Qwen-TTS 실행 관리자"""

    @staticmethod
    def get_registered_voices() -> List[Dict[str, Any]]:
        """사용 가능한 모든 보이스 목록 (기본 프리셋 + 등록된 내 목소리) 반환"""
        voices = []
        
        # 1. 등록된 내 목소리 파일 확인
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

        for p in PRESET_VOICES:
            item = dict(p)
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

        # wav 또는 mp3 등을 ffmpeg로 24kHz/16kHz 모노 wav로 정규화 변환
        cmd = ["ffmpeg", "-y", "-i", str(audio_file_path), "-ar", "24000", "-ac", "1", str(dest_audio)]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except Exception:
            # ffmpeg 실패 시 단순 복사
            shutil.copyfile(audio_file_path, dest_audio)

        meta = {
            "name": voice_name,
            "ref_text": ref_text.strip(),
            "created_at": str(Path(dest_audio).stat().st_mtime)
        }
        with open(dest_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "voice_id": "my_voice",
            "name": voice_name,
            "ref_audio": str(dest_audio),
            "ref_text": ref_text
        }

    @classmethod
    def synthesize_speech(
        cls,
        text: str,
        voice_id: str = "docu_male",
        scene_index: int = 1,
        topic_slug: str = "scene",
        language: str = "korean"
    ) -> Dict[str, Any]:
        """대본 텍스트를 Qwen-TTS(또는 Voice Clone)로 음성 합성"""
        ensure_runner_script()
        
        output_filename = f"{topic_slug}_scene_{scene_index}.wav"
        output_path = AUDIO_DIR / output_filename
        
        # 보이스 설정 찾기
        voices = {v["id"]: v for v in PRESET_VOICES}
        voice_config = voices.get(voice_id, PRESET_VOICES[1])
        lang_code = language.lower() if language else "korean"
        
        cmd = [
            str(QWEN_PYTHON) if QWEN_PYTHON.exists() else sys.executable,
            str(RUNNER_SCRIPT),
            "--text", text,
            "--output", str(output_path),
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
                # 등록된 음성이 없으면 기본 성우(ryan)로 생성
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
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            stdout = proc.stdout.strip()
            
            # JSON 응답 파싱
            for line in stdout.splitlines():
                if line.startswith("{") and line.endswith("}"):
                    try:
                        res = json.loads(line)
                        if res.get("status") == "success":
                            return {
                                "status": "success",
                                "scene_index": scene_index,
                                "voice_id": voice_id,
                                "voice_name": voice_config["name"],
                                "audio_url": f"/api/audio/{output_filename}",
                                "filename": output_filename
                            }
                    except Exception:
                        pass
        except Exception as e:
            print(f"[TTS Synthesize Error] {e}")

        # 파일이 생성되었는지 최종 확인
        if output_path.exists():
            return {
                "status": "success",
                "scene_index": scene_index,
                "voice_id": voice_id,
                "voice_name": voice_config["name"],
                "audio_url": f"/api/audio/{output_filename}",
                "filename": output_filename
            }

        return {
            "status": "error",
            "message": "음성 합성에 실패했습니다."
        }
