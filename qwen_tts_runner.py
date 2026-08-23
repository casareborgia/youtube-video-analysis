import os
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
            import subprocess
            aiff_tmp = output_path + ".aiff"
            subprocess_voice = "Yuna"
            subprocess.run(["say", "-v", subprocess_voice, text, "-o", aiff_tmp], check=False)
            if os.path.exists(aiff_tmp):
                subprocess.run(["ffmpeg", "-y", "-i", aiff_tmp, output_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if os.path.exists(aiff_tmp):
                    os.remove(aiff_tmp)
                print(json.dumps({"status": "success", "output": output_path, "note": "fallback_system_tts"}))
                return
        except Exception:
            pass
            
        print(json.dumps({"status": "error", "error": str(e)}))

if __name__ == "__main__":
    main()
