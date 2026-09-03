#!/bin/bash
# macOS: 더블클릭으로 실행 (처음 한 번은 터미널에서 chmod +x run.command)
cd "$(dirname "$0")"
# Omni 영상 생성(google-genai 2.x)에는 Python 3.10 이상이 필요 → .venv 가 있으면 우선 사용
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi
$PY -c "import yt_dlp, edge_tts, av, imageio_ffmpeg, dotenv, google.genai" 2>/dev/null || $PY -m pip install -r requirements.txt
(sleep 2; open "http://localhost:8989") &
$PY server.py
