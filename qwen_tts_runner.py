import os
import sys
import json
import argparse
import soundfile as sf
import numpy as np

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["preset", "clone"])
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ref_audio", default="")
    parser.add_argument("--ref_text", default="")
    parser.add_argument("--speaker", default="default")
    parser.add_argument("--instruct", default="")
    parser.add_argument("--language", default="Korean")
    args = parser.parse_args()

    text = args.text.strip()
    output_path = args.output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Qwen-TTS 모델 로드 및 합성 시도
    try:
        import torch
        from qwen_tts import Qwen3TTSModel
        
        device = "mps" if torch.backends.mps.is_available() else ("cuda:0" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if device != "cpu" else torch.float32

        if args.mode == "clone" and args.ref_audio and os.path.exists(args.ref_audio):
            # Voice Clone 모드 (내 목소리 복제)
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

        else:
            # Custom Voice / Preset 모드
            model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                device_map=device,
                dtype=dtype
            )
            wavs, sr = model.generate_custom_voice(
                text=text,
                language=args.language,
                speaker=args.speaker if args.speaker != "default" else "male",
                instruct=args.instruct
            )
            sf.write(output_path, wavs[0], sr)
            print(json.dumps({"status": "success", "output": output_path, "sample_rate": sr}))
            return

    except Exception as e:
        # 모델 미다운로드 또는 의존성 에러 시 fallback: 표준 TTS 또는 안내
        print(f"[Qwen-TTS Fallback/Log] {str(e)}", file=sys.stderr)
        
        # 시스템 기본 TTS 또는 gTTS fallback
        try:
            # macOS say 명령어로 고음질 aiff -> wav 변환
            aiff_tmp = output_path + ".aiff"
            subprocess_voice = "Yuna" if "female" in args.speaker else "Yuna"
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
