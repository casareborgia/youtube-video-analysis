# TubeInsight x 에이전트 레오 통합 작업계획서

## 1. 개요 및 목적
기존 FastAPI 기반의 유튜브 영상 분석 플랫폼(`유튜브 영상분석실습`)에, 최신 `TubeInsight`의 올인원 파이프라인과 과거 프로젝트 `에이전트 레오(Agent Leo)`의 알고리즘 성장 공식을 융합합니다.
- **춘식 배제**: 구글플로우 사용으로 불필요한 비디오 디렉팅 로직은 제외.
- **Zero-Dependency 레오 이식**: 신규 패키지 추가 없이 기존 `uploader.py`(YouTube Data API v3 세션)와 `llm_client.py`(로컬 무료 LLM)를 활용하여 레오의 알고리즘 분석 및 인게이지먼트 로직 흡수.
- **FastAPI 제로트러스트 체계 유지**: 비동기 엔드포인트 구조와 엄격한 입력 검증 및 보안 미들웨어 유지.

---

## 2. 세부 단계별 구현 계획 (Phases)

### Phase 1: 레오의 트렌드 스카우터 & 채널 빌더/진단 (`channel_builder.py`, `trend_scout.py`)
- **[NEW] `trend_scout.py`** (또는 `analyze.py` 확장):
  - `uploader.py`의 `_service()`를 통해 카테고리별(음악, 엔터, 뉴스, 과학기술 등) 인기 급상승 Top 20 수집.
  - `llm_client.py`를 활용해 "시청 시간대, 시청자 반응, 다음 주 추천 키워드"를 요약하는 트렌드 리포트 생성.
  - 엔드포인트: `GET /api/trends/top20`
- **[PORT] `channel_builder.py`**:
  - 유튜브 실시간 핸들(@) 중복 검사 (`GET /api/channel/check-handle`).
  - 8대 채널 세팅(채널명, 설명, 태그, 카테고리 등) 자동 기획 (`POST /api/channel/generate`).
  - **레오의 채널 진단 추가**: 로그인된 내 채널 통계(조회수, 구독자, 비디오 수)를 진단하여 알고리즘 관점의 성장 조언을 제공하는 `GET /api/channel/my-status` 구현.

---

### Phase 2: 기획 고도화 & 레오의 인게이지먼트 해킹 (`prompt_generator.py`)
- **[MODIFY] `prompt_generator.py`**:
  - **레오의 인게이지먼트 해킹**: 대본의 마지막 아웃트로 씬에 체류시간과 댓글을 유도하는 '도발적 선택형 질문(오픈 퀘스천)' 자동 삽입.
  - **고정 댓글(Pinned Comment) 추천 생성**: 영상 업로드 시 바로 쓸 수 있는 시청자 반응 유도용 고정 댓글 텍스트 필드 추가.
  - **나노바나나 레드라인 프롬프트 연동**: 썸네일 및 씬별 첫 프레임 이미지 프롬프트(엄격한 6-Key 규격) 생성 로직 보강.

---

### Phase 3: 원소스 멀티유즈(OSMU) 마케팅 엔진 (`marketing.py`)
- **[PORT] `marketing.py`**:
  - 영상 분석 결과 또는 8초 씬 대본을 입력받아 3종 마케팅 자산 동시 생성:
    1. **Threads / X (트위터)**: 5~7개 스레드 타래 (갈고리 훅 + 핵심 내용 + 인터랙션 질문)
    2. **SEO 블로그**: 네이버/티스토리 포스팅용 정밀 마크다운 포스트
    3. **이메일 뉴스레터**: 오픈율 극대화 제목 3종 + 본문
  - 엔드포인트: `POST /api/marketing/generate`, `GET /api/marketing/history`, `GET /api/marketing/get`

---

### Phase 4: 영상 자동 제작 & 유튜브 원클릭 업로더 (`producer.py`, `uploader.py`)
- **[PORT] `producer.py`**:
  - `ffmpeg` 기반 [씬 이미지 + 8초 나레이션 MP3 + 반투명 밴드 자막(SRT/ASS)] 자동 번인 합성.
  - 씬 간 0.5초 크로스페이드 & 나레이션 발생 시 배경음 감소(오디오 덕킹).
  - FastAPI `BackgroundTasks` 기반 렌더링 진행률 추적.
- **[PORT] `uploader.py`**:
  - YouTube Data API v3 OAuth 2.0 클라이언트 (`token.json`).
  - 비디오, 썸네일, 제목, 설명, 태그, 레오의 고정댓글 자동 업로드 (`POST /api/youtube/upload`).

---

### Phase 5: FastAPI `app.py` 라우팅 및 프론트엔드(`static/`) 탭 UI 통합
- **[MODIFY] `app.py`**:
  - 신규 모듈들의 비동기 엔드포인트 및 Pydantic 스키마 등록.
  - 제로트러스트 보안 정책 미들웨어 준수.
- **[MODIFY] `static/index.html`, `static/app.js`, `static/style.css`**:
  - 5대 탭 네비게이션 적용:
    1. **트렌드 & 영상 분석**: 레오의 인기 Top 20 + URL 5단계 벤치마킹 분석
    2. **채널 빌더 & 진단**: 핸들 중복검사 + 8대 세팅 기획 + 내 채널 성과 진단
    3. **씬 기획 & 나레이션**: 8초 대본 + 레드라인 프롬프트 + 레오의 오픈퀘스천/고정댓글
    4. **영상 제작 & 업로드**: 슬롯별 미디어 업로드 + ffmpeg 합성 + 유튜브 업로드
    5. **멀티 마케팅 (OSMU)**: Threads/블로그/뉴스레터 올인원 생성 및 보관함

---

## 3. 검증 계획 (Verification Plan)
- **트렌드 조회 및 핸들 검사**: YouTube Data API Top 20 및 실제 유튜브 핸들 URL 통신 정상 확인.
- **로컬 LLM 응답 검증**: Ollama/LM Studio를 통한 마케팅 3종 및 고정 댓글 JSON 파싱 정상 확인.
- **비디오 합성 테스트**: 더미 이미지와 나레이션 mp3 합성 시 자막 번인 및 오디오 덕킹 정상 작동 확인.
- **유튜브 인증 테스트**: `token.json` 갱신 및 업로드 API 연결 상태 확인.
