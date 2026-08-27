import os
import sys
import re
import json
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import base64
import time
import analyze
import generator
import tts_engine
import llm_client

PORT = 8989
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class TubeInsightHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/status":
            self.handle_status()
        elif path == "/api/report":
            vid = query.get("id", [None])[0]
            self.handle_report_detail(vid)
        elif path == "/api/voice/profiles":
            self.handle_voice_profiles()
        else:
            if path == "/":
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(post_data) if post_data else {}
        except Exception:
            data = {}

        if path == "/api/analyze":
            url = data.get("url")
            if not url:
                self.send_json_response({"error": "유효한 url을 입력해주세요."}, status=400)
                return
            self.process_analysis(url)
        elif path == "/api/generate":
            topic = data.get("topic")
            scenes = data.get("scenes", 10)
            voice_id = data.get("voice_id", "ko-KR-InJoonNeural")
            generate_audio = data.get("generate_audio", True)
            if not topic:
                self.send_json_response({"error": "주제(topic)를 입력해주세요."}, status=400)
                return
            self.process_generation(topic, int(scenes), voice_id, generate_audio)
        elif path == "/api/tts/generate-scenes":
            topic = data.get("topic", "video")
            scenes = data.get("scenes", [])
            voice_id = data.get("voice_id", "ko-KR-InJoonNeural")
            rate = data.get("rate", "+5%")
            if not scenes:
                self.send_json_response({"error": "씬 데이터가 없습니다."}, status=400)
                return
            self.process_tts_scenes(topic, scenes, voice_id, rate)
        elif path == "/api/voice/upload":
            self.process_voice_upload(data)
        elif path == "/api/llm/select":
            try:
                pref = llm_client.set_preference(data.get("backend", "auto"))
                self.send_json_response({"status": "success", "preference": pref})
            except ValueError as e:
                self.send_json_response({"error": str(e)}, status=400)
        else:
            self.send_json_response({"error": "Not Found"}, status=404)

    def handle_voice_profiles(self):
        voices = tts_engine.VoiceProfileManager.list_all_voices()
        self.send_json_response({"status": "success", "voices": voices})

    def process_voice_upload(self, data):
        try:
            voice_name = data.get("name", "내 목소리").strip()
            ref_text = data.get("ref_text", "").strip()
            audio_base64 = data.get("audio_base64", "")
            base_voice = data.get("base_voice", "ko-KR-InJoonNeural")
            pitch = data.get("pitch", "+0Hz")
            rate = data.get("rate", "+4%")

            if not audio_base64:
                self.send_json_response({"error": "녹음된 오디오 데이터가 필요합니다."}, status=400)
                return

            profile_id = f"voice_{int(time.time())}"
            audio_filename = f"{profile_id}.wav"
            audio_path = os.path.join(tts_engine.VOICES_DIR, audio_filename)

            # Strip data url header if present
            if "," in audio_base64:
                audio_base64 = audio_base64.split(",", 1)[1]

            audio_bytes = base64.b64decode(audio_base64)
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)

            profile = tts_engine.VoiceProfileManager.save_profile(
                profile_id=profile_id,
                name=voice_name,
                ref_text=ref_text,
                audio_filename=audio_filename
            )

            self.send_json_response({"status": "success", "profile": profile})
        except Exception as e:
            self.send_json_response({"status": "error", "error": str(e)}, status=500)

    def process_tts_scenes(self, topic, scenes, voice_id="ko-KR-InJoonNeural", rate="+5%"):
        try:
            result = tts_engine.generate_all_scenes_audio(scenes, topic, voice_id=voice_id, rate=rate)
            self.send_json_response({"status": "success", "data": result})
        except Exception as e:
            self.send_json_response({"status": "error", "error": str(e)}, status=500)

    def process_generation(self, topic, num_scenes=10, voice_id="ko-KR-InJoonNeural", generate_audio=True):
        try:
            result = generator.generate_video_content(topic, num_scenes=num_scenes)
            
            # Automatically generate scene audios if requested
            if generate_audio and result.get("structured_scenes"):
                try:
                    tts_res = tts_engine.generate_all_scenes_audio(result["structured_scenes"], topic, voice_id=voice_id)
                    result["audio_data"] = tts_res
                except Exception as tts_err:
                    print(f"TTS 생성 오류 (무시 가능): {tts_err}")

            self.send_json_response({"status": "success", "data": result})
        except Exception as e:
            self.send_json_response({"status": "error", "error": str(e)}, status=500)

    def process_analysis(self, url):
        try:
            vid = analyze.extract_video_id(url)
            if not vid:
                self.send_json_response({"error": "유효한 유튜브 영상 링크(URL)가 아닙니다."}, status=400)
                return

            # Check if cached data already exists
            cache_file = os.path.join(BASE_DIR, f"{vid}_data.json")
            if os.path.exists(cache_file):
                try:
                    data = json.load(open(cache_file, encoding="utf-8"))
                    self.send_json_response({"status": "success", "data": data, "cached": True})
                    return
                except Exception:
                    pass

            result = analyze.analyze_video(url)
            self.send_json_response({"status": "success", "data": result, "cached": False})
        except Exception as e:
            self.send_json_response({"status": "error", "error": str(e)}, status=500)

    def handle_status(self):
        # LM Studio / Ollama 각각의 상태 + 실제 사용될(active) 백엔드 보고
        probes = llm_client.probe_all()
        pref = llm_client.get_preference()  # auto | lmstudio | ollama (사용자 선택)
        force = os.environ.get("TUBEINSIGHT_LLM_BACKEND", "").lower() or None
        choice = force or (None if pref == "auto" else pref)

        active = None
        if choice in ("lmstudio", "ollama"):
            active = choice if probes[choice]["online"] else None
        elif probes["lmstudio"]["online"]:
            active = "lmstudio"
        elif probes["ollama"]["online"]:
            active = "ollama"

        names = {"lmstudio": "LM Studio", "ollama": "Ollama"}
        self.send_json_response({
            "llm": {
                "online": active is not None,
                "active": active,
                "backend": names.get(active),
                "model": probes[active]["model"] if active else None,
                "preference": pref
            },
            "backends": probes,
            "server_port": PORT
        })

    def handle_report_detail(self, vid):
        if not vid or not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            self.send_json_response({"error": "올바른 영상 ID가 아닙니다."}, status=400)
            return

        cache_file = os.path.join(BASE_DIR, f"{vid}_data.json")
        if os.path.exists(cache_file):
            try:
                data = json.load(open(cache_file, encoding="utf-8"))
                self.send_json_response({"status": "success", "data": data})
                return
            except Exception:
                pass

        # Fallback to report file if exists
        report_file = os.path.join(BASE_DIR, f"{vid}_리포트.txt")
        if os.path.exists(report_file):
            text = open(report_file, encoding="utf-8").read()
            self.send_json_response({
                "status": "success",
                "data": {
                    "id": vid,
                    "info": {"id": vid, "title": f"영상 ({vid})"},
                    "report": text
                }
            })
            return

        self.send_json_response({"error": "리포트를 찾을 수 없습니다."}, status=404)

    def send_json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def run():
    # 127.0.0.1 바인딩: 내 컴퓨터에서만 접속 가능 (같은 와이파이의 타인 접근 차단)
    # ThreadingHTTPServer: 분석/생성이 몇 분 걸려도 다른 요청(상태 확인, 페이지)이 멈추지 않음
    server_address = ('127.0.0.1', PORT)
    httpd = ThreadingHTTPServer(server_address, TubeInsightHandler)
    print(f"🚀 유튜브 분석 웹 대시보드 서버 가동 중: http://localhost:{PORT}")
    print("   브라우저에서 위 주소를 열어주세요. 종료: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버 종료됨")

if __name__ == '__main__':
    run()
