# 🎬 YouTube Video Analyzer & AI Prompt / Voice Studio

<div align="center">

![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.11+-brightgreen.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)
![Ollama](https://img.shields.io/badge/Ollama-Gemma%204-purple.svg)
![Qwen-TTS](https://img.shields.io/badge/Qwen3--TTS-1.7B-orange.svg)
![Zero-Trust](https://img.shields.io/badge/Security-Zero--Trust%20Hardened-success.svg)

<p align="center">
  <strong>[KO] 유튜브 흥행 영상의 심층 메타데이터와 연출 기법을 분석하고, 신규 주제의 기승전결 시네마틱 프롬프트·7개국어 대본·Qwen-TTS 음성(Voice Clone)을 원스톱으로 창작하는 멀티모달 AI 플랫폼입니다.</strong><br>
  <strong>[EN] A multimodal AI platform that analyzes YouTube viral videos to extract proven storytelling formulas, auto-generating cinematic storyboard prompts, 7-language scripts, and Qwen3-TTS narration with zero-shot voice cloning.</strong>
</p>

<p align="center">
  <a href="#-english"><strong>English</strong></a> •
  <a href="#-한국어-korean"><strong>한국어 (Korean)</strong></a>
</p>

</div>

---

# 🌐 English

## 🌟 Key Features

### 1. 🔍 Deep YouTube Video Analysis
- **High-Speed Ingestion with `yt-dlp`**: Extracts rich video metadata, chapter timelines, multilingual subtitles (KO/EN), and viewer comment sentiments in real-time.
- **Ollama Gemma 4 Strategic 5-Step Report**:
  1. *Title & Hook Structure*: Psychological triggers and opening retention mechanics.
  2. *Narrative Flow*: Progressive 4-stage storytelling mechanism (Hook → Exploration → Climax → Resolution).
  3. *Core Insights*: High-value takeaways and production essence.
  4. *Audience Reactions*: Key resonance factors from top comments.
  5. *Actionable Strategy*: 3 practical execution blueprints for creators.

### 2. 🎨 AI Cinematic Prompt Studio
- **Proven Success Formula Injection**: Automatically injects top viral formulas (5s opening hook, tension build-up, visual scale contrast, cinematic lighting) into new video prompts.
- **Auto-Inferred Camera Angle & Lighting**: The LLM autonomously determines the optimal camera motion (*Extreme Wide, Drone 360, Dolly Zoom, Low-Angle*) and lighting atmosphere (*Volumetric Fog, Cyberpunk Neon, Chiaroscuro*) based on the dramatic beat.
- **Target Generative AI Formats**:
  - 🎥 **Google Flow (Veo 2/3, Imagen 3/4)**: AutoFlow-Pro optimized descriptive prompts.
  - 🎨 **Midjourney v6.1**: Auto-appended parameters (`--ar 16:9 --v 6.1 --style raw`).
  - ⚡ **Runway Gen-3 / Kling AI / Luma**: Motion dynamics and physical interaction prompts.
- **High-Speed Optimization**: 75% token reduction with Python assembly engine, cutting generation latency down to **10–20 seconds**.

### 3. 🌐 7-Language Script Generation
- 🇰🇷 **Korean** • 🇺🇸 **English** • 🇯🇵 **Japanese** • 🇨🇳 **Chinese** • 🇫🇷 **French** • 🇩🇪 **German** • 🇪🇸 **Spanish**
- Automatically writes culturally natural narration scripts for global content creators.

### 4. 🎙️ Qwen3-TTS & Voice Clone Studio
- **3 Core Model Integrations**:
  - `CustomVoice`: Official voice actors (*Ryan, Sohee, Uncle Fu, Vivian*) + natural language tone control.
  - `VoiceClone (Base 1.7B)`: Zero-shot voice cloning from uploaded user reference audio.
  - `VoiceDesign (1.7B)`: Custom character voice creation using descriptive prompts.
- **Web UI Audio Player & Batch TTS**: In-browser audio streaming with a single-click `[Generate All Audio]` batch synthesizer.

### 5. 📤 AutoFlow-Pro & Multi-Format Export
- **AutoFlow-Pro `.txt`**: One-click batch import format for AutoFlow-Pro.
- **Smart Task `.csv`**: Structured spreadsheet dataset with scene numbers, narrations, prompts, angles, and aspect ratios.
- **Workflow `.json`**: Standard dataset for automated pipeline integrations.

### 6. 🛡️ Zero-Trust Security Hardened
- **PII & Path Neutralization**: Environment variable path resolution (`QWEN_PYTHON`, `QWEN_TTS_DIR`).
- **Command Injection Prevention**: `os.system` eliminated; replaced with parameterized `subprocess.run`.
- **SSRF Protection**: Strict domain whitelisting allowing only official YouTube domains (`verify_youtube_url`).
- **Path Traversal Defense**: Audio streaming and uploads verified with `is_relative_to` boundaries.
- **Security Headers Middleware**: Injected `nosniff`, `DENY` framing, and contextual `escapeHtml` sanitization.

---

## 🏗️ Architecture

```mermaid
graph TD
    subgraph 1.Analysis_Pipeline
        A[YouTube URL] --> B[yt-dlp Metadata / Subtitles / Comments]
        B --> C[Ollama Gemma 4 Deep Strategy Report]
        C --> D[Viral Success Formula Extraction]
    end

    subgraph 2.AI_Prompt_Studio
        E[New Topic / Concept] --> F[Scene Segmentation & Story Beats]
        D --> F
        F --> G[Camera & Lighting Auto-Inference]
        F --> H[Multilingual Script: 7 Languages]
        F --> I[Cinematic Prompt Synthesis: Google Flow / MJ / Runway]
    end

    subgraph 3.Audio_Studio
        H --> J[Qwen3-TTS & Voice Clone Engine]
        J --> K[🎙️ In-Browser Audio Player & Batch Synthesis]
    end

    subgraph 4.Export
        I --> L[📥 AutoFlow-Pro .txt / CSV / JSON]
    end
```

---

## 🚀 Quick Start (English)

### 1. Prerequisites
- **Python 3.11+**
- **FFmpeg** (`brew install ffmpeg` or your OS package manager)
- **Ollama** ([https://ollama.ai](https://ollama.ai)) with Gemma 4:
  ```bash
  ollama run gemma4:latest
  ```

### 2. Clone & Setup
```bash
git clone https://github.com/casareborgia/youtube-video-analysis.git
cd youtube-video-analysis

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables (Optional)
To customize Qwen-TTS paths, configure `.env`:
```bash
QWEN_TTS_DIR=/path/to/QWEN-tts
QWEN_PYTHON=/path/to/QWEN-tts/.venv/bin/python
OLLAMA_API_URL=http://127.0.0.1:11434/api/chat
```

### 4. Run Server
```bash
chmod +x run.sh
./run.sh
```
Open **[http://localhost:8765](http://localhost:8765)** in your web browser.

---
---

# 🇰🇷 한국어 (Korean)

## 🌟 주요 핵심 기능

### 1. 🔍 유튜브 심층 분석 (YouTube Video & Metadata Analyzer)
- **yt-dlp 기반 고속 수집**: 영상 메타데이터, 챕터 타임라인, 자막(한국어/영어), 시청자 댓글 여론 실시간 수집
- **Ollama Gemma 4 심층 5단계 전략 리포트**:
  1. 제목·훅(Hook) 구조 분석
  2. 전개 방식 (단계별 서사 구조)
  3. 핵심 메시지 및 인사이트
  4. 댓글 여론 특징 및 시청자 반응
  5. 내 채널에 바로 적용할 3가지 실행 전략

### 2. 🎨 AI 프롬프트 스튜디오 (AI Cinematic Prompt Studio)
- **성공 공식 자동 주입**: 분석된 영상들의 공통 강점(5초 오프닝 훅, 4단계 서사, 스케일 대비 연출, 시네마틱 조명)을 프롬프트 엔진에 자동 결합
- **카메라 앵글 & 시네마틱 조명 AI 자동 추론 (Auto-Inference)**: 씬별 분위기에 맞는 최적의 카메라 무빙(Extreme Wide, Drone 360, Dolly Zoom 등)과 조명(Volumetric Fog, Cyberpunk Neon, Chiaroscuro 등)을 스스로 판단하여 합성
- **타겟 생성 AI 모델 지원**:
  - 🎥 **Google Flow (Veo 2/3, Imagen 3/4)**: AutoFlow-Pro 최적화 서술형 프롬프트
  - 🎨 **Midjourney v6.1**: `--ar 16:9 --v 6.1 --style raw` 자동 결합
  - ⚡ **Runway Gen-3 / Kling AI / Luma**: 물리 인터랙션 & 카메라 모션 강조 프롬프트
- **초고속 생성 최적화**: 토큰 75% 절감 및 파이썬 엔진 결합으로 **10~20초대** 신속 생성

### 3. 🌐 7개국 다국어 대본 창작 (Multilingual Script Generator)
- 🇰🇷 **한국어** • 🇺🇸 **English** • 🇯🇵 **日本語** • 🇨🇳 **中文** • 🇫🇷 **Français** • 🇩🇪 **Deutsch** • 🇪🇸 **Español**
- 선택한 언어의 원어민 뉘앙스에 맞는 씬별 내레이션 대본을 자동 창작하여 글로벌 영상 기획 지원

### 4. 🎙️ Qwen3-TTS & 내 목소리 학습(Voice Clone) 통합 음성 스튜디오
- **3대 핵심 엔진 통합**:
  - `CustomVoice`: 공식 성우 프리셋 (`Ryan`, `Sohee`, `Uncle Fu`, `Vivian`) + 어조/감정 제어
  - `VoiceClone (Base 1.7B)`: 사용자 음성 파일 업로드 기반의 Zero-shot 본인 목소리 복제
  - `VoiceDesign (1.7B)`: 자연어 프롬프트 기반 가상 캐릭터 목소리 설계
- **웹 UI 오디오 플레이어 & 일괄 합성 (Batch TTS)**: 씬별 오디오 재생 및 전체 씬 일괄 생성

### 5. 📤 AutoFlow-Pro 및 멀티 포맷 내보내기 (Export)
- **AutoFlow-Pro `.txt`**: AutoFlow-Pro의 `[Import from .txt]` 원클릭 불러오기 호환 포맷
- **스마트 태스크 `.csv`**: 스프레드시트 및 업무 관리용 데이터셋
- **워크플로우 `.json`**: 파이프라인 연동용 표준 JSON

### 6. 🛡️ 제로트러스트(Zero-Trust) 보안 체계
- **개인 경로 식별자 완전 제거** 및 환경변수화 (`QWEN_PYTHON`, `QWEN_TTS_DIR`)
- **커맨드 인젝션 차단**: `os.system` 전면 제거 및 `subprocess.run` 인자 분리 적용
- **SSRF 방어**: 공식 유튜브 도메인 외 내부망 요청 차단 (`verify_youtube_url`)
- **Path Traversal 방어**: 오디오 서빙 및 업로드 경로 경계 검증 (`is_relative_to`)
- **보안 헤더 미들웨어**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`
- **XSS 방어**: `escapeHtml` 컨텍스트 이스케이프 강제 적용

---

## 📂 프로젝트 구조 (Directory Structure)

```
youtube-video-analysis/
├── app.py                  # FastAPI 메인 백엔드 서버 (제로트러스트 보안 미들웨어 탑재)
├── prompt_generator.py     # AI 시네마틱 프롬프트 & 7개국어 대본 창작 엔진
├── tts_service.py          # Qwen3-TTS & Voice Clone 음성 합성 서비스
├── qwen_tts_runner.py      # Qwen-TTS 격리 실행 러너 스크립트
├── analyze.py              # 유튜브 메타데이터 및 리포트 독립 분석 모듈
├── requirements.txt        # Python 의존성 목록
├── run.sh                  # 원클릭 실행 쉘 스크립트
├── .gitignore              # 제로트러스트 데이터 제외 규칙
├── data/                   # 분석 데이터 및 합성 오디오 저장소 (Git 제외)
│   ├── audio/              # 생성된 씬별 .wav 음성 파일
│   └── voices/             # 사용자 등록 Voice Clone 참조 파일
└── static/                 # 글래스모피즘 다크 테마 웹 대시보드
    ├── index.html          # 메인 UI (분석기 & 프롬프트 스튜디오)
    ├── style.css           # 모던 UI 스타일시트
    └── app.js              # 프론트엔드 비동기 컨트롤러 & 오디오 제어
```

---

## 📜 라이선스 (License)
This project is licensed under the **MIT License**.
