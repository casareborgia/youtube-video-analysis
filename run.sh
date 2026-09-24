#!/bin/bash

# ==============================================================================
# TubeInsight AI & Agent Luna 올인원 자동화 스튜디오 실행 스크립트
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "🎬 TubeInsight AI & Agent Luna 스튜디오 시작 중..."
echo "=================================================="

# 1. 환경 설정 파일(.env) 확인 및 자동 초기화
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "💡 .env 파일이 감지되지 않아 .env.example에서 복사 생성합니다."
    cp .env.example .env
    echo "   (필요한 API 키는 웹 대시보드 우측 상단 [환경설정] 모달에서 입력 가능합니다)"
fi

# 2. 가상환경(.venv) 확인 및 의존성 설치
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "⚠️ 가상환경(.venv)이 존재하지 않아 신규 생성합니다..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "📦 requirements.txt 전체 패키지 자동 설치 중 (최초 1회 실행)..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# 3. ffmpeg 설치 여부 점검 (경고 안내만 출력하고 진행)
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️ [주의] 시스템 ffmpeg가 감지되지 않았습니다."
    echo "   macOS: brew install ffmpeg"
    echo "   Ubuntu/Debian: sudo apt update && sudo apt install -y ffmpeg"
    echo "   (imageio-ffmpeg 번들이 폴백으로 사용될 수 있습니다)"
fi

# 4. OS별 브라우저 자동 오픈 (백그라운드 비동기)
PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"
URL="http://${HOST}:${PORT}"

open_browser() {
    sleep 1.2
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open "$URL" 2>/dev/null || true
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v xdg-open &> /dev/null; then
            xdg-open "$URL" 2>/dev/null || true
        fi
    elif command -v cmd.exe &> /dev/null; then
        cmd.exe /c start "$URL" 2>/dev/null || true
    fi
}
open_browser &

echo "🌐 대시보드 웹 주소: $URL"
echo "📁 데이터 저장 위치: $SCRIPT_DIR/data/"
echo "종료하려면 터미널에서 [Ctrl + C]를 누르세요."
echo "=================================================="

# 5. Uvicorn 비동기 웹 서버 구동
exec python -m uvicorn app:app --host "$HOST" --port "$PORT" --reload
