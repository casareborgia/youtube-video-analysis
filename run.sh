#!/bin/bash

# 유튜브 영상 분석 실습 웹 대시보드 실행 스크립트
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "🚀 YouTube 영상 메타데이터 분석 스튜디오 시작 중..."
echo "=================================================="

# 가상환경 활성화
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "⚠️ 가상환경(.venv)이 존재하지 않아 생성합니다..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install fastapi "uvicorn[standard]" yt-dlp pandas openpyxl
fi

# 브라우저 자동 오픈 (백그라운드에서 1초 후 실행)
(sleep 1 && open "http://localhost:8765") &

echo "🌐 웹 서버 주소: http://localhost:8765"
echo "📁 메타데이터 저장 위치: $SCRIPT_DIR/data/"
echo "종료하려면 터미널에서 [Ctrl + C]를 누르세요."
echo "=================================================="

# Uvicorn 서버 실행
python -m uvicorn app:app --host 127.0.0.1 --port 8765
