@echo off
REM Windows: 더블클릭으로 실행 (Python 3.10 이상 권장)
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -c "import yt_dlp, edge_tts, av, imageio_ffmpeg, dotenv, google.genai" 2>NUL || %PY% -m pip install -r requirements.txt
start "" "http://localhost:8989"
%PY% server.py
pause
