# Qwen3-TTS 뉴럴 보이스 클로닝(Voice Cloning) & 고음질 TTS 엔진
import os
import json
import asyncio
import re
import shutil
import zipfile
import numpy as np
import soundfile as sf
import edge_tts
import av
# torch는 무거운 선택 의존성 — 보이스 클로닝을 실제 사용할 때만 지연 로드 (Qwen3VoiceCloner.get_model 참고)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BASE_DIR, "voices")
AUDIO_DIR = os.path.join(BASE_DIR, "audio")

os.makedirs(VOICES_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# 기본 제공 무료 고품질 한국어 나레이션 프리셋
PRESET_VOICES = {
    "ko-KR-InJoonNeural": {
        "id": "ko-KR-InJoonNeural",
        "name": "인준 (남성 다큐·지식 전문)",
        "gender": "male",
        "style": "차분하고 신뢰감 넘치는 다큐멘터리 어조 (건축사전 스타일)",
        "default_rate": "+5%"
    },
    "ko-KR-SunHiNeural": {
        "id": "ko-KR-SunHiNeural",
        "name": "선희 (여성 다큐·뉴스 전문)",
        "gender": "female",
        "style": "또렷하고 전달력 높은 전문 아나운서 어조",
        "default_rate": "+3%"
    },
    "ko-KR-HyunsuNeural": {
        "id": "ko-KR-HyunsuNeural",
        "name": "현수 (남성 스토리텔러)",
        "gender": "male",
        "style": "몰입감 높은 역동적 스토리텔러 어조",
        "default_rate": "+4%"
    }
}

def load_audio_universal(audio_path, target_sr=24000):
    """
    WebM, MP3, WAV, M4A, OGG 등 모든 오디오 포맷을 24kHz 모노 numpy 배열로 안전하게 로드합니다.
    """
    try:
        container = av.open(audio_path)
        resampler = av.AudioResampler(format='s16', layout='mono', rate=target_sr)
        frames = []
        for frame in container.decode(audio=0):
            frame.pts = None
            for resampled in resampler.resample(frame):
                frames.append(resampled.to_ndarray())
        if frames:
            data = np.concatenate(frames, axis=1).squeeze()
            data_float = data.astype(np.float32) / 32768.0
            return data_float, target_sr
    except Exception as e:
        try:
            data, sr = sf.read(audio_path)
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            return data, sr
        except Exception as e2:
            print(f"오디오 파일 로드 오류: {e2}")
            return None, target_sr
    return None, target_sr

class Qwen3VoiceCloner:
    """
    Qwen3-TTS Zero-Shot Neural Voice Cloning 모델 매니저
    사용자가 업로드/녹음한 실제 목소리(ref_audio)와 발화 텍스트(ref_text)를 학습하여
    새로운 나레이션을 사용자의 실제 음색과 어조로 복제 생성합니다.
    """
    _model = None
    _device = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            import torch
            from qwen_tts import Qwen3TTSModel
            cls._device = 'mps' if torch.backends.mps.is_available() else 'cpu'
            dtype = torch.float32
            print(f"🔄 Qwen3-TTS Voice Cloning 모델 로드 중 ({cls._device})...")
            cls._model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                device_map=cls._device,
                dtype=dtype
            )
            print("✅ Qwen3-TTS Voice Cloning 모델 로드 완료!")
        return cls._model

    @classmethod
    def clone_voice(cls, text, ref_audio_path, ref_text, output_file):
        """
        Qwen3-TTS를 사용하여 사용자의 목소리로 나레이션을 복제 생성합니다.
        """
        model = cls.get_model()
        print(f"  🎙️ [Qwen3 보이스 클로닝] '{text[:30]}...' 생성 시작 (참조 음성: {os.path.basename(ref_audio_path)})")
        
        wavs, sr = model.generate_voice_clone(
            text=text,
            language="Korean",
            ref_audio=ref_audio_path,
            ref_text=ref_text
        )
        
        # Save output
        sf.write(output_file, wavs[0], sr)
        print(f"  ✅ [Qwen3 보이스 클로닝 완료] -> {output_file}")
        return output_file

class VoiceProfileManager:
    """
    사용자의 녹음된 목소리(ref_audio)와 발화 텍스트(ref_text)를 저장하고 영구 보존하여
    언제든지 내 목소리로 100% 일관되게 생성할 수 있도록 관리합니다.
    """
    @staticmethod
    def get_profiles_file():
        return os.path.join(VOICES_DIR, "profiles.json")

    @classmethod
    def load_profiles(cls):
        pf = cls.get_profiles_file()
        if os.path.exists(pf):
            try:
                return json.load(open(pf, encoding="utf-8"))
            except Exception:
                return {}
        return {}

    @classmethod
    def save_profile(cls, profile_id, name, ref_text, audio_filename):
        raw_audio_path = os.path.join(VOICES_DIR, audio_filename)
        clean_audio_filename = f"{profile_id}.clean.wav"
        clean_audio_path = os.path.join(VOICES_DIR, clean_audio_filename)

        # 1. Convert to clean 24kHz WAV
        data, sr = load_audio_universal(raw_audio_path, target_sr=24000)
        if data is not None and len(data) > 0:
            sf.write(clean_audio_path, data, sr)
        else:
            shutil.copy(raw_audio_path, clean_audio_path)

        profiles = cls.load_profiles()
        profiles[profile_id] = {
            "id": profile_id,
            "name": name,
            "ref_text": ref_text,
            "raw_audio_file": audio_filename,
            "clean_audio_file": clean_audio_filename,
            "audio_file": clean_audio_filename,
            "clean_audio_path": clean_audio_path,
            "created_at": os.path.getmtime(clean_audio_path) if os.path.exists(clean_audio_path) else None
        }
        json.dump(profiles, open(cls.get_profiles_file(), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"✅ 나만의 목소리 프로필 저장 완료: '{name}' (참조 텍스트: {ref_text[:30]}...)")
        return profiles[profile_id]

    @classmethod
    def list_all_voices(cls):
        profiles = cls.load_profiles()
        all_voices = []
        
        # 1. Custom Cloned Profiles first
        for pid, p in profiles.items():
            all_voices.append({
                "id": f"custom:{pid}",
                "name": f"🎙️ {p.get('name', '내 목소리')} (학습된 내 목소리)",
                "is_custom": True,
                "ref_text": p.get("ref_text", ""),
                "audio_url": f"/voices/{p.get('clean_audio_file', p.get('audio_file'))}",
                "style": "Qwen3-TTS 뉴럴 보이스 클로닝 적용"
            })
            
        # 2. Presets
        for vid, v in PRESET_VOICES.items():
            all_voices.append({
                "id": vid,
                "name": v["name"],
                "is_custom": False,
                "style": v["style"],
                "default_rate": v["default_rate"]
            })
            
        return all_voices

def clean_narration_text(text):
    """마크다운 기호 등을 제거하여 TTS가 읽기 좋은 순수 문장으로 정리"""
    clean = re.sub(r'[*_#`"|\-\[\]]', ' ', text or '')
    return re.sub(r'\s+', ' ', clean).strip()

def generate_scene_audio(text, voice_id="ko-KR-InJoonNeural", rate="+5%", pitch="+0Hz", output_file="output.mp3"):
    """
    씬 나레이션 오디오 생성:
    - custom voice 선택 시: Qwen3-TTS 신경망 보이스 클로닝으로 내 목소리 합성
    - preset voice 선택 시: Edge-TTS 스튜디오 나레이션으로 고속 합성
    - 대본이 비어 있으면 None 반환 (더미 문구가 녹음되는 것 방지)
    """
    clean_text = clean_narration_text(text)
    if not clean_text or len(clean_text) < 2:
        print("  ⚠️ 대본이 비어 있어 오디오 생성을 건너뜁니다.")
        return None

    # 1. Custom Cloned Voice (Qwen3-TTS Neural Voice Clone)
    if voice_id.startswith("custom:"):
        pid = voice_id.split(":", 1)[1]
        profiles = VoiceProfileManager.load_profiles()
        if pid in profiles:
            p = profiles[pid]
            ref_audio = p.get("clean_audio_path") or os.path.join(VOICES_DIR, p.get("clean_audio_file", f"{pid}.clean.wav"))
            ref_text = p.get("ref_text", "")
            
            if os.path.exists(ref_audio) and ref_text:
                try:
                    return Qwen3VoiceCloner.clone_voice(clean_text, ref_audio, ref_text, output_file)
                except Exception as e:
                    print(f"Qwen3 보이스 클로닝 오류 발생 (Edge-TTS로 fallback): {e}")

    # 2. Preset Voice (Edge-TTS)
    async def _run_edge():
        communicate = edge_tts.Communicate(clean_text, voice_id if not voice_id.startswith("custom:") else "ko-KR-InJoonNeural", rate=rate, pitch=pitch)
        await communicate.save(output_file)

    asyncio.run(_run_edge())
    return output_file

def merge_audio_files(input_files, output_file, target_sr=24000):
    """
    여러 MP3를 하나로 정식 인코딩 병합합니다.
    (단순 바이트 이어붙이기는 재생시간 표시 오류·편집툴 호환 문제가 있어 PyAV로 재인코딩)
    """
    try:
        out = av.open(output_file, mode='w')
        out_stream = out.add_stream('mp3', rate=target_sr)
        resampler = av.AudioResampler(format='s16', layout='stereo', rate=target_sr)
        for fpath in input_files:
            if not os.path.exists(fpath):
                continue
            container = av.open(fpath)
            for frame in container.decode(audio=0):
                frame.pts = None
                for rf in resampler.resample(frame):
                    for packet in out_stream.encode(rf):
                        out.mux(packet)
            container.close()
        for packet in out_stream.encode(None):
            out.mux(packet)
        out.close()
        return True
    except Exception as e:
        print(f"  ⚠️ 정식 오디오 병합 실패 — 단순 결합으로 대체합니다: {e}")
        return False

def generate_all_scenes_audio(scenes, topic, voice_id="ko-KR-InJoonNeural", rate="+5%"):
    """
    기획된 씬 리스트(씬 1~N)를 받아 각 8초 씬별 오디오 파일과
    전체 병합 오디오 파일, 그리고 원클릭 ZIP 일괄 다운로드 압축파일을 생성합니다.
    - 프리셋 보이스(Edge-TTS)는 병렬 합성으로 속도 개선
    - 대본이 비어 있는(파싱 실패) 씬은 건너뜀
    """
    safe_topic = re.sub(r'[\/\\:*?"<>|]', '_', topic)[:25]
    topic_audio_dir = os.path.join(AUDIO_DIR, safe_topic)
    os.makedirs(topic_audio_dir, exist_ok=True)

    results = []
    audio_files_for_merge = []
    is_preset_voice = not voice_id.startswith("custom:")
    edge_batch = []  # (clean_text, out_path) — 프리셋 보이스 병렬 합성용

    for i, scene in enumerate(scenes, 1):
        scene_num = scene.get("scene_num", i)
        subtitle_text = scene.get("subtitle", "")
        time_range = scene.get("time_range", f"씬 {i}")
        clean_text = clean_narration_text(subtitle_text)

        filename = f"scene_{scene_num:02d}.mp3"
        out_path = os.path.join(topic_audio_dir, filename)

        item = {
            "scene_num": scene_num,
            "time_range": time_range,
            "subtitle": subtitle_text,
            "audio_url": None,
            "audio_file": out_path
        }

        if not clean_text or len(clean_text) < 2:
            print(f"  ⚠️ 씬 {scene_num}: 대본 파싱 실패(빈 대본) — 오디오 생성 건너뜀")
            results.append(item)
            continue

        if is_preset_voice:
            edge_batch.append((clean_text, out_path))
        else:
            print(f"  ▶ 씬 {scene_num} 오디오 생성 중: \"{subtitle_text[:25]}...\" (Voice: {voice_id})")
            if generate_scene_audio(subtitle_text, voice_id=voice_id, rate=rate, output_file=out_path) is None:
                results.append(item)
                continue

        item["audio_url"] = f"/audio/{safe_topic}/{filename}"
        results.append(item)
        audio_files_for_merge.append(out_path)

    # 프리셋 보이스: Edge-TTS 병렬 합성 (동시 5개 제한)
    if edge_batch:
        print(f"  ▶ Edge-TTS 병렬 합성 시작: {len(edge_batch)}개 씬 (Voice: {voice_id})")

        async def _run_batch():
            sem = asyncio.Semaphore(5)

            async def _one(text, path):
                async with sem:
                    communicate = edge_tts.Communicate(text, voice_id, rate=rate)
                    await communicate.save(path)

            await asyncio.gather(*[_one(t, p) for t, p in edge_batch])

        asyncio.run(_run_batch())
        print(f"  ✅ 병렬 합성 완료 ({len(edge_batch)}개)")

    # 1. Merge full narration audio (정식 재인코딩 병합, 실패 시 단순 결합 폴백)
    full_filename = "full_narration.mp3"
    full_path = os.path.join(topic_audio_dir, full_filename)
    existing_files = [f for f in audio_files_for_merge if os.path.exists(f)]
    if not merge_audio_files(existing_files, full_path):
        with open(full_path, "wb") as outfile:
            for fpath in existing_files:
                with open(fpath, "rb") as infile:
                    outfile.write(infile.read())

    full_web_url = f"/audio/{safe_topic}/{full_filename}"

    # 2. Generate Batch Download ZIP Bundle (모든 씬 오디오 + 전체 병합본 + 자막 대본 텍스트)
    zip_filename = f"{safe_topic}_전체오디오_일괄다운로드.zip"
    zip_path = os.path.join(topic_audio_dir, zip_filename)
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        def add_file_to_zip(file_path, arcname):
            if os.path.exists(file_path):
                zinfo = zipfile.ZipInfo.from_file(file_path, arcname=arcname)
                zinfo.flag_bits |= 0x800  # Enable UTF-8 filename flag
                with open(file_path, "rb") as f:
                    zipf.writestr(zinfo, f.read())

        # Add full narration
        if os.path.exists(full_path):
            add_file_to_zip(full_path, "00_전체_나레이션_마스터.mp3")
            
        # Add individual scenes with clear Korean names
        for item in results:
            num = item["scene_num"]
            time_tag = item["time_range"].replace(" ", "").replace("~", "_")
            arc_name = f"{num:02d}_씬{num:02d}_{time_tag}_나레이션.mp3"
            if os.path.exists(item["audio_file"]):
                add_file_to_zip(item["audio_file"], arc_name)
                
        # Add Subtitle Script Text
        script_summary = f"🎬 [{topic}] 8초 씬별 나레이션 대본\n" + "="*50 + "\n\n"
        for item in results:
            script_summary += f"[씬 {item['scene_num']:02d}] {item['time_range']}\n{item['subtitle'] or '(대본 파싱 실패 — 기획서 원문을 확인하세요)'}\n\n"
        
        script_zinfo = zipfile.ZipInfo("대본_및_타임스탬프.txt")
        script_zinfo.flag_bits |= 0x800
        zipf.writestr(script_zinfo, script_summary.encode('utf-8'))

    zip_web_url = f"/audio/{safe_topic}/{zip_filename}"
    print(f"✅ 전체 나레이션 오디오 & ZIP 일괄 다운로드 생성 완료: {zip_path}")

    return {
        "topic": topic,
        "voice_id": voice_id,
        "scenes_audio": results,
        "full_audio_url": full_web_url,
        "full_audio_file": full_path,
        "zip_download_url": zip_web_url,
        "zip_file": zip_path
    }

if __name__ == "__main__":
    test_text = "국가 최고 기밀, 지하 50층에 잠든 비밀 벙커의 존재. 과연 그 안에는 무엇이 숨겨져 있을까요?"
    out = generate_scene_audio(test_text, output_file=os.path.join(AUDIO_DIR, "test_narration.mp3"))
    print(f"테스트 오디오 생성 완료: {out}")
