# 루나(Luna) 보컬 판정 수정 · 숏폼 하이라이트 · 춘식 BGA 연계 작업지시서

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | 루나 보컬/연주곡 판정 수정, 하이라이트 숏폼 파이프라인, 춘식(Veo) BGA 연계 사전 검토 |
| 프로젝트 | `유튜브 영상분석실습` |
| 작성일 | 2026-10-09 |
| 근거 | 안티그래비티 점검 보고(2026-10-08) 및 Claude Code 코드·데이터 대조 검증 |
| 구현 워커 | Antigravity |
| 독립 검증 | Claude Code |
| 기준 파일 | `luna_engine.py`, `app.py`, `static/app.js`, `static/index.html`, `uploader.py`, `tests/` |

이 문서는 안티그래비티가 제출한 세 가지 개선안(춘식 BGA 업그레이드 / 가사·보컬 온오프 / 레오 트렌드 점검)과 추가 제안(롱폼+숏폼 동시 업로드)을 코드와 실제 생성 이력에 대조한 뒤, **착수 순서와 범위를 확정**한 지시서다. 2장의 검증 결과가 3장 이후의 작업 범위를 결정하므로 2장을 먼저 읽는다.

---

## 2. 안티그래비티 보고 검증 결과

### 2.1 가사·보컬 온오프 — 원인 진단은 맞고, 증상 서술은 과장

| 보고 내용 | 검증 결과 |
|---|---|
| `is_pure_instrumental_genre = genre_key in ("sleep", "dark-ambient")` 가 원인 | **맞음.** `luna_engine.py:197`. 하드코딩 튜플이라 `piano`·`ambient`·`jazz` 등이 auto 모드에서 전부 `should_have_lyrics = True` 로 떨어진다. |
| "순수 연주곡이어야 하는 곡들에 **모두** 가사가 강제 주입" | **과장.** `data/luna_music` 67트랙 실측: Piano 10곡 중 5곡만 가사, Cinematic Ambient 9곡 중 2곡, Deep Sleep 2곡 중 1곡. 나머지는 LLM이 스스로 `has_lyrics: false` 를 반환해 연주곡이 됐다. 즉 결과가 **운에 좌우되는 상태**이지 전부 보컬곡은 아니다. |
| 개선안 ③ "UI/API 에 `instrumental`/`vocal` 선택지 보강" | **이미 구현됨.** `static/index.html:1267-1271` 에 `auto`/`lyrics`/`instrumental` 3개 옵션이 있고 `app.py:1149` 가 받는다. 이 항목은 작업 범위에서 제외한다. |

추가로 발견한 사실 (보고서에 없음):

- `GENRE_SPECS` 에는 이미 장르별 `vocal_affinity` 필드(`none`/`optional`/`high`)가 정의돼 있는데 **판정 로직이 이 값을 읽지 않는다.** `ambient`·`sleep`·`piano`·`dark-ambient` 는 `none`, `lofi`·`synthwave`·`jazz` 는 `optional`, `citypop`·`acoustic`·`rnb-chill` 은 `high`. 수정은 튜플 확장이 아니라 **이 필드를 쓰도록 바꾸는 것**이어야 한다.
- 67트랙 전부 `meta.json` 에 `vocal_mode` 가 저장돼 있지 않다(`None`). 어떤 모드로 생성됐는지 사후 추적이 불가능하므로 저장 필드를 추가해야 한다.
- `luna_engine.py:334` 에서 `concept["has_lyrics"] = bool(parsed.get("has_lyrics") or parsed.get("lyrics"))` 로 **LLM 응답이 사용자 지정 모드를 덮어쓸 수 있다.** `vocal_mode="instrumental"` 로 요청해도 LLM 이 가사를 넣어 보내면 보컬곡이 된다.

### 2.2 레오 트렌드 분석 — 정상, 조치 불필요

보고 내용과 동일하게 확인했다. YouTube 급상승(KR, 카테고리 10) 수집, 6시간 TTL 캐시, 브리프→루나 전달 모두 정상이며 PR #13 에서 자동 스카우팅 제거·캐시 보호까지 끝났다. **이번 지시서에서는 작업 없음.**

### 2.3 춘식(Director Choonsik) Veo 3.1 BGA — 전제 조건 미충족, 착수 보류

| 보고 내용 | 검증 결과 |
|---|---|
| "16:9 프리셋을 `veo_generator.py` 에 공식 추가" | `generate_veo_clip(..., config_params)` 가 이미 `aspect_ratio` 를 받는다(기본 `9:16`). 필요한 건 신규 기능이 아니라 호출부에서 `"16:9"` 를 넘기는 것. |
| 춘식 프로젝트 현황 | `~/coding/영상생성에이전트 춘식` 은 사용자가 예전에 만들어 둔 독립 프로젝트. 검토 시점에는 GitHub 에 없었으나 2026-10-09 `casareborgia/choonsik-video-agent` (비공개) 로 업로드 완료. |
| 비용 | Veo 는 Google Cloud 과금. 이 환경에서 Veo 생성은 **아직 한 번도 검증된 적이 없다**(`google-flow` MCP 의 `flow_start_video` 미검증). |
| 중복 | `~/coding/google-flow-studio` 의 `google-flow` MCP 도 Veo 영상 생성을 담당한다. 춘식과 역할이 겹치므로 어느 쪽을 BGA 엔진으로 쓸지 먼저 정해야 한다. |

→ 4장의 **사전 조건(Phase C-0)** 을 충족한 뒤에만 코드 작업으로 넘어간다. 안티그래비티가 제안한 4개 항목(심리스 루핑, 16:9, 프롬프트 동기화, 오디오 리액티브) 중 **오디오 리액티브 비주얼라이저는 Veo 와 무관하게 FFmpeg 만으로 가능**하므로 Phase B 로 떼어낸다.

### 2.4 롱폼 + 숏폼 동시 업로드 — 타당, 비용 0 으로 구현 가능

- 루나 쪽에 숏폼 관련 코드는 전혀 없다(`grep shorts luna_engine.py` 0건).
- `uploader.upload_video` (`uploader.py:372`) 가 `pinned_comment`, `playlist_id`, `publish_at` 을 이미 지원하므로 "숏폼 설명란·고정 댓글에 롱폼 링크" 는 추가 API 없이 가능하다.
- 안티그래비티가 제시한 "방식 1(FFmpeg 블러 배경 + 중앙 커버 + 파형)" 은 외부 과금이 없다. **방식 2(춘식 Veo 세로 영상)** 는 2.3 의 보류 사유가 그대로 적용된다.

---

## 3. 착수 순서

| 순서 | Phase | 브랜치 | 비용 | 근거 |
|---|---|---|---|---|
| 1 | A. 보컬/연주곡 판정 수정 | `fix/luna-vocal-affinity` | 0 | 확인된 버그, 변경 범위 작음, 이후 모든 생성 품질에 영향 |
| 2 | B. 하이라이트 숏폼 파이프라인 | `feat/luna-shorts-highlight` | 0 (FFmpeg) | 채널 성장 직결, 외부 API 없음 |
| 3 | C. 춘식 BGA 연계 | `spike/choonsik-bga-prereq` → 사전 조건 충족 후 별도 지시서 | Veo 과금 | 2.3 참고 |

Phase A 를 머지하기 전에는 Phase B 를 시작하지 않는다. Phase C 는 C-0 결과를 사용자에게 보고하고 **별도 승인**을 받은 뒤에만 C-1 로 진행한다.

---

## 4. Phase 별 작업 지시

### Phase A — 보컬/연주곡 판정 수정 (`fix/luna-vocal-affinity`)

#### A-1. `generate_music_concept` 판정 로직 (`luna_engine.py:192-209`)

1. `is_pure_instrumental_genre` 하드코딩 튜플을 제거하고 `genre_spec.get("vocal_affinity", "optional")` 을 읽는다.
2. auto 모드 판정 규칙을 다음으로 고정한다.
   - 명시적 보컬 키워드 → 보컬
   - 명시적 연주곡 키워드 → 연주곡
   - `vocal_affinity == "none"` → 연주곡
   - `vocal_affinity == "high"` → 보컬
   - `vocal_affinity == "optional"` → **LLM 에 위임**. 단 프롬프트에 "이 장르는 보컬 유무를 곡의 성격에 따라 결정하되 `has_lyrics` 를 명시하라" 는 지침을 넣고, 응답의 `has_lyrics` 를 그대로 쓴다. (현재처럼 무조건 True 로 시작하지 않는다.)
3. 연주곡 키워드 목록에 `"연주", "독주", "솔로", "타건", "드론", "piano solo", "no vocal", "no vocals", "without vocals"` 를 추가한다. `"inst"` 는 `"instrumental"` 에 포함되므로 **부분 문자열 오탐**(예: `"instant"`, `"install"`)이 없는지 단어 경계(`\b`)로 검사하도록 바꾼다.
4. 보컬 키워드는 현행 유지하되 동일하게 단어 경계 검사로 바꾼다.

#### A-2. 사용자 지정 모드가 LLM 응답에 덮이지 않도록 (`luna_engine.py:327-334`)

- `v_mode` 가 `lyrics`/`instrumental` 로 명시된 경우: LLM 이 뭘 반환하든 `concept["has_lyrics"]` 는 `should_have_lyrics` 로 강제한다. 연주곡 강제 시 `lyrics`·`vocal_style`·`vocal_language` 를 `None` 으로 비우고, `lyria_prompt` 에 보컬 힌트 문구(`vocals`, `singing`, `lyrics`)가 들어 있으면 `_sanitize_lyria_prompt` 수준에서 제거하고 `No vocals, purely instrumental` 을 덧붙인다.
- `auto` 인 경우에만 LLM 의 `has_lyrics` 를 신뢰한다.

#### A-3. 생성 이력에 판정 근거 저장

`track_data` 에 다음 필드를 추가한다 (기존 필드는 건드리지 않는다).

```json
"vocal_mode": "auto | lyrics | instrumental",
"vocal_decision": {
  "resolved": "lyrics | instrumental",
  "reason": "explicit_mode | keyword:<matched> | affinity:none | affinity:high | llm"
}
```

`list_tracks` (`luna_engine.py:1057`) 반환에 `vocal_mode` 를 포함해 UI 목록에서 확인할 수 있게 한다.

#### A-4. UI — 자동 추천 옵션 문구 정정

`static/index.html:1268` 의 `auto` 옵션 라벨을 실제 규칙과 일치시킨다. 예: `✨ 자동 (피아노·앰비언트·수면은 연주곡, 시티팝·R&B·포크는 보컬, 로파이·재즈·신스웨이브는 곡 성격에 따라)`.

#### A-5. 테스트 — `tests/test_luna_vocal_decision.py` (신규)

LLM 호출 없이(`llm_client.call_llm_json` 모킹) 다음을 검증한다.

- 10개 장르 × `auto` → `affinity` 에 따른 기대값 (none→inst, high→lyrics, optional→LLM 응답 따름)
- `vocal_mode="instrumental"` + LLM 이 가사를 반환 → 최종 `has_lyrics=False`, `lyrics=None`, `lyria_prompt` 에 `vocals` 미포함
- `vocal_mode="lyrics"` + `genre="sleep"` → 보컬 (명시 모드가 affinity 보다 우선)
- `custom_topic="피아노 독주"` + `genre="lofi"` → 연주곡 (키워드가 affinity 보다 우선)
- `custom_topic="install guide"` → `"inst"` 오탐 없음
- `vocal_decision.reason` 값이 위 각 경로에 맞게 기록됨
- 기존 `tests/test_luna_leo_integrity.py` 회귀 통과

#### A-6. 수용 기준

- [ ] `piano`/`ambient`/`sleep`/`dark-ambient` + `auto` 로 3회 연속 생성 시 전부 연주곡
- [x] `instrumental` 명시 시 LLM 응답과 무관하게 연주곡 (단위 테스트로 검증)
- [x] 신규 트랙 `meta.json` 에 `vocal_mode`·`vocal_decision` 저장
- [x] 기존 67개 트랙 `meta.json` 은 수정하지 않음 (마이그레이션 불필요, 필드 없으면 UI 에 `—` 표시)
- [x] 신규 테스트(19개) + 기존 루나·베가 테스트 통과. `test_gemini_model_selection`·`test_account_replies` 의 실패는 `.env`(Gemini 키·Threads 토큰) 의존으로 `main` 에서도 동일하게 실패하는 기존 문제.

---

### Phase B — 하이라이트 숏폼 파이프라인 (`feat/luna-shorts-highlight`)

Phase A 머지 후 착수. **Veo·춘식 의존 없음, FFmpeg 만 사용.**

#### B-1. 하이라이트 구간 추출 — `luna_engine.extract_audio_highlight(track_data, duration=45)`

1. 입력은 **베가 마스터 결과**(`track_data["audio_file"]`, 즉 `audio.mp3`)다. `audio_raw.*` 원본을 쓰지 않는다.
2. 구간 선택 알고리즘:
   - FFmpeg `astats` 또는 `ebur128` 로 1초 단위 단기 음량(RMS/LUFS-S)을 뽑는다.
   - `duration` 초 길이의 슬라이딩 윈도우 평균이 최대인 구간을 고른다. 단 **시작 10초·끝 15초는 제외**(페이드 구간 배제).
   - 측정 실패 시 폴백: `0:45–1:30`.
3. 선택 구간에 페이드인 1초 / 페이드아웃 2초를 적용해 `data/luna_music/<id>/audio_shorts.mp3` (192k) 로 저장.
4. `track_data["shorts"] = {"start": float, "end": float, "method": "energy | fallback", "audio_file": path}` 저장. 수동 조정을 위해 `start` 를 인자로 받을 수 있게 한다(`start_override`).

#### B-2. 9:16 렌더 — `luna_engine.render_luna_shorts_video(track_data, progress_cb=None)`

1. 출력 `1080x1920`, `data/luna_music/<id>/video_shorts.mp4`, 길이 = 하이라이트 길이(**60초 미만 보장**).
2. 레이어 구성 (FFmpeg 단일 필터 그래프):
   - 배경: 커버를 1080x1920 으로 채우고 `boxblur` + 어둡게
   - 중앙: 커버 원본 비율 유지, 폭 약 85%
   - 상단: `AGENT LUNA` / 곡 제목 (`render_luna_video` 의 drawtext 규칙 재사용, 폰트 에러 시 동일한 폴백)
   - 하단: `showwaves` 또는 `showfreqs` 파형 바 (높이 ~180px, 반투명). **이 부분이 2.3 에서 언급한 "오디오 리액티브" 의 최소 구현**이며 롱폼에도 옵션으로 재사용 가능하게 함수로 뺀다.
3. `render_luna_video` 와 같은 방식으로 `track_data["shorts"]["video_file"]`, `rendered_at` 기록. 베가 재마스터 후 `video_stale` 가 서면 숏폼도 같이 stale 처리.

#### B-3. 메타데이터 — `build_luna_metadata` 확장 (`luna_engine.py:892`)

`meta["shorts"]` 블록을 추가한다.

- `title`: `{원곡 title} (Highlight) #Shorts` — 100자 제한 검사
- `description`: 첫 줄에 `🎧 3분 풀버전 👉 {longform_url}` (업로드 시점에 치환), 이어서 원곡 설명 앞 2문단, 해시태그 `#Shorts #AgentLuna #<장르태그>`
- `tags`: 원곡 태그 + `Shorts`, `YouTubeShorts`
- `pinned_comment`: 풀버전 링크 + 재생목록 링크(있으면). `sanitize_pinned_comment` 를 통과시킨다.

#### B-4. 업로드 연계 — `upload_luna_to_youtube` (`luna_engine.py:1197`)

1. 인자 `with_shorts: bool = False` 추가. 기본값 **False** (기존 호출 동작 불변).
2. `with_shorts=True` 면:
   - 롱폼 업로드 → `video_id` 확보
   - `shorts.description`/`pinned_comment` 의 플레이스홀더를 `https://youtu.be/{video_id}` 로 치환
   - `uploader.upload_video(video_shorts.mp4, ..., category_id=동일, privacy=동일, publish_at=롱폼 +10분)` 호출. **숏폼이 롱폼보다 먼저 공개되지 않도록** 한다.
   - 결과를 `track_data["shorts"]["youtube"] = {"video_id", "url", "uploaded_at"}` 에 저장
3. 숏폼 업로드가 실패해도 롱폼 결과는 유지하고 `track_data["shorts"]["upload_error"]` 에 사유를 남긴다. 롱폼 실패 시 숏폼은 시도하지 않는다.
4. 할당량: 업로드 1건 = 1600 유닛. 숏폼 동시 업로드는 하루 할당량(10,000)을 두 배로 소모한다는 경고를 UI 에 표시한다.

#### B-5. API (`app.py`)

- `POST /api/luna/shorts/extract` `{track_id, duration?, start_override?}` → B-1
- `POST /api/luna/shorts/render` `{track_id}` → B-2
- `POST /api/luna/upload` 기존 요청 모델에 `with_shorts: bool = False` 추가
- `GET /api/luna/history`(`list_tracks`) 응답에 `shorts` 블록 포함 (`/api/luna/tracks/{id}` 는 원래 없는 라우트라 history 로 대체)

#### B-6. UI (6단계 루나 탭)

- 비디오 미리보기 아래 **숏폼 패널**: `[하이라이트 추출]` → 구간 표시(`0:47–1:32`, 방식) + 시작 초 수동 입력 → `[9:16 렌더]` → 세로 미리보기 플레이어
- 업로드 폼에 `[ ] 하이라이트 숏폼 함께 업로드 (+1600 유닛)` 체크박스. `localStorage`(`luna_with_shorts`) 에 기억.
- 업로드 결과 영역에 롱폼·숏폼 링크 두 개 표시.

#### B-7. 테스트

- `tests/test_luna_shorts.py` (신규)
  - 합성 신호(앞 30초 무음, 50–95초 큰 사인파, 뒤 무음) → 하이라이트 구간이 큰 구간을 잡는지
  - 측정 실패 모킹 → 폴백 `45–90`
  - 렌더 결과 `ffprobe` 로 1080x1920, 길이 < 60초 확인 (ffmpeg 없으면 skip)
  - `with_shorts=True` 업로드: `uploader.upload_video` 모킹 → 두 번 호출, 두 번째 호출 description 에 첫 번째 video_id 포함, `publish_at` 이 롱폼보다 뒤
  - 숏폼 업로드 실패 시 롱폼 결과 보존
- 기존 `test_luna_leo_integrity.py`, `test_vega_*` 회귀

#### B-8. 수용 기준

- [x] 외부 API 호출 없이 추출·렌더 가능 (FFmpeg 만). 참고: Homebrew ffmpeg 에 `drawtext`(libfreetype) 가 없어 텍스트 레이어는 생략되고 파형+블러 배경으로 렌더됨 (롱폼도 동일한 기존 제약).
- [x] 숏폼 길이 < 60초, 1080x1920, 음원은 베가 마스터본 (ffprobe 로 검증하는 테스트 포함)
- [x] `with_shorts` 기본값 False 로 기존 업로드 흐름 불변
- [x] 숏폼 설명·고정 댓글에 롱폼 링크 자동 삽입, 숏폼 공개 시각 = 롱폼 +10분
- [x] 신규 18개(`tests/test_luna_shorts.py`) + 루나·베가·레오 기존 91개 통과. 실제 유튜브 2건 연속 업로드는 머지 후 수동 확인.

---

### Phase C — 춘식 Veo 3.1 BGA 연계

#### C-0. 사전 조건 (코드 작업 금지, 조사·보고만)

1. **춘식 프로젝트 GitHub 업로드 — ✅ 완료 (2026-10-09).** `casareborgia/choonsik-video-agent` (비공개) 에 올라가 있다. `.env`·`client_secrets.json`·`token.pickle`·`assets/`·`logs/`·venv 는 `.gitignore` 로 제외됐고, `.env.example`·`requirements.txt` 가 추가됐다. 춘식 코드를 수정할 때는 이 저장소에서 브랜치를 따서 작업한다.
2. **Veo 1회 실측.** 8초 클립 1개를 `16:9` 로 생성해 (a) 소요 시간, (b) 과금액(Cloud Billing 콘솔 수치), (c) 결과 화질을 보고한다. **사용자가 "생성해도 된다" 고 명시한 뒤에만 호출한다.**
3. **엔진 결정 — ✅ 조사 완료 (2026-10-09, 아래 C-0 결과 참고).** 결론: **`google-flow` MCP 를 BGA 엔진으로 쓰고, 춘식에서는 Optical Mastery 프롬프트 어휘만 가져온다.**
4. **루프 길이 산정 — ✅ 조사 완료 (아래 C-0 결과 참고).** 권장: 8초 클립 3개 + 1초 크로스페이드 = 약 22초 주기, 3분 곡에 8회 반복, 트랙당 Veo 호출 3회.

#### C-0 조사 결과 (2026-10-09, Claude Code)

**(3) 엔진 비교 — 춘식 `veo_generator.py` vs `google-flow` MCP**

| 기준 | 춘식 (`~/coding/영상생성에이전트 춘식`) | `google-flow` MCP (`~/coding/google-flow-studio`) |
|---|---|---|
| 호출 경로 | Gemini API (API 키, `genai.Client(api_key=)`) | Vertex AI (ADC, `us-central1`) — 프로젝트 과금·할당량·콘솔 관리 가능 |
| 모델 | `settings.py` 기본이 **`veo-3.1-lite-generate-preview`**. 코드 주석의 "Fast" 와 불일치 | `veo-3.1-fast-generate-001` 기본, 환경변수로 standard 전환 |
| 16:9 | `config_params["aspect_ratio"]` 로 가능 (기본 9:16) | `aspect_ratio="16:9"` 가 **기본값** |
| 캐릭터·스타일 일관성 | `EXTEND`(이전 클립 마지막 프레임 참조) 에 의존. **Lite 는 EXTEND 미지원** → 현재 설정대로면 8개 씬 체인이 동작하지 않을 가능성 큼 | `flow_register_character` + `flow_compile_scene_prompt`(@tag 일관성) + **Image-to-Video**(`image_path`) → **루나 앨범 커버를 첫 프레임으로 넣어 곡과 같은 톤의 영상**을 뽑을 수 있음 |
| 오디오 | `generate_audio` 파라미터가 `GenerateVideosConfig` 에 전달되지 않음(버그) | `generate_audio=False` 지정 가능 → BGA 는 루나 음원을 쓰므로 **오디오 없는 단가** 적용 |
| 비동기·상태 조회 | 동기 폴링(10초×150회 블로킹) | `flow_start_video` → `flow_check_video` 논블로킹, 작업 이름으로 재조회 가능 |
| 재시도·안전장치 | 429 시 5분 sleep ×3, 일일 생성 상한(`tracker.py`). **429 시 Playwright 로 사용자 Chrome 프로필을 열어 Google Vids 웹을 조작하는 폴백**이 켜져 있음(`USE_WEB_VIDS_FALLBACK=True`) — 서버 프로세스에서 쓰기엔 위험 | 파일 쓰기 `outputs/`·`characters/` 로 제한, 입력 이미지 경로 화이트리스트, MCP 도구에 과금 여부 어노테이션 |
| TubeInsight 연동 | 별도 venv(3.11), moviepy 의존, 패키지 구조가 쇼츠 파이프라인(`main.py`) 중심 | 이미 Claude Code 에 user 스코프 MCP 로 등록돼 있고, 순수 함수 호출(`flow_visual.FlowVisual.start_video/get_video`) 로 임포트 가능 |
| 검증 상태 | Veo 실생성 이력 있음(`assets/veo_output*.mp4`, 5월) — 단 Lite 전환 후는 불명 | Veo 미검증(이미지·텍스트만 검증) |

결론: **`google-flow` 를 엔진으로 채택.** 이유는 (a) 16:9·무오디오·Image-to-Video 가 BGA 요구와 정확히 맞고, (b) Vertex 과금을 콘솔에서 통제할 수 있으며, (c) 춘식의 Chrome 프로필 폴백은 FastAPI 서버 안에서 돌릴 수 없다. 춘식에서는 `producer.py` 의 카메라·조명·그레이딩 어휘(Optical Mastery)만 프롬프트 템플릿으로 옮긴다. 춘식 저장소 자체는 쇼츠 에이전트로 그대로 둔다.

**(4) 루프 길이·호출 횟수·비용 산정 (3분 = 180초 기준)**

Veo 3.1 Fast/Lite 는 클립당 최대 8초. 선택지:

| 안 | 구성 | 루프 주기 | 180초 반복 횟수 | Veo 호출 | 1080p 무오디오 예상 비용* |
|---|---|---|---|---|---|
| A | 8초 1개를 정·역재생(부메랑) | 16초 | 11회 | 1 | 약 $0.8 |
| **B (권장)** | 8초 3개 + 1초 `xfade` | 약 22초 | 8회 | 3 | **약 $2.4** |
| C | 8초 6개 + 1초 `xfade` | 약 43초 | 4회 | 6 | 약 $4.8 |
| D | 루프 없이 전 구간 생성 | — | 1회 | 23 | 약 $18 + 생성 대기 20분↑ |

\* 단가는 2차 출처 기준(Vertex Veo 3.1 Fast, 1080p 무오디오 ≈ $0.10/초, 오디오 포함 ≈ $0.12/초; Lite 는 Fast 의 절반 이하). **Google 공식 가격 페이지는 자동 수집이 되지 않아 확인하지 못했으므로, 정확한 금액은 (2) 실측으로 확정한다.** 출처: [benchlm.ai Veo 가격](https://benchlm.ai/media-pricing/veo), [anotherwrapper Veo 3.1 Fast](https://anotherwrapper.com/tools/llm-pricing/video-models/veo-31-fast), [Google 블로그 — Veo 3.1 Lite](https://blog.google/innovation-and-ai/technology/ai/veo-3-1-lite/), [Krea Veo 3.1 Lite API](https://www.krea.ai/docs/api-reference/video/veo-31-lite.md).

B 안을 권장하는 이유: 로파이·앰비언트 BGA 는 시청자가 화면을 응시하지 않는 장르라 22초 주기면 반복이 거슬리지 않고, 비용이 트랙당 $3 이내로 루나 1곡 생성 비용과 같은 자릿수다. 클립 3개는 같은 커버 이미지를 첫 프레임으로 한 Image-to-Video 로 뽑아 색감을 맞추고, 카메라 무빙만 다르게 지시한다(slow push-in / lateral drift / slow pull-back). 루프 이음새는 마지막 클립 끝 → 첫 클립 시작을 `xfade` 로 한 번 더 섞어 끊김을 없앤다.

**(2) Veo 1회 실측 — ✅ 완료 (2026-10-09 13:46, 사용자 승인 후 호출)**

| 항목 | 결과 |
|---|---|
| 호출 | `google-flow` `flow_start_video` — 모델 `veo-3.1-fast-generate-001`, Vertex `us-central1`, Image-to-Video(루나 `luna_1791476313` 커버 1376×768), 8초, 16:9, `generate_audio=False` |
| 소요 시간 | 시작 13:46:50 → 완료 확인 13:48:16, **약 80초** (첫 상태 확인이 90초 후라 실제는 그 이하) |
| 결과물 | `google-flow-studio/outputs/luna_bga_test_19c59d12….mp4` — **1280×720**, 24fps, H.264 2.7Mbps, 8.000초, **오디오 스트림 없음**, 2.7MB |
| 화질·톤 | 커버의 청사진·젖은 나무 테이블·빗방울 창·발코니 구도가 그대로 유지됨. 느린 푸시인, 커튼이 바람에 움직이고 빗방울이 흘러내림. 사람·텍스트 없음. 로파이/피아노 BGA 루프 소재로 적합. |
| 과금 | **실측 확정 (2026-10-11 Cloud Billing SKU 보고서)**: SKU `Veo 3 Fast Video 720p Generation`(7DE3-56E5-CE6C) 단가 **₩108.7/초 ≈ $0.079/초**(환율 1383.28). 이 8초 클립 = ₩869 ≈ $0.63 (2차 출처 추정 $0.64 와 일치). 10월 1~10일 Veo 합계 32초 = ₩3,478, 전액 프로모션 크레딧(기타 절감)으로 상쇄되어 청구액 ₩0. |

발견 사항:
- `google-flow` 의 `start_video` 는 `resolution` 을 넘기지 않아 **720p 로 생성**된다. 1080p 가 필요하면 `flow_visual.py` 의 `GenerateVideosConfig` 에 `resolution="1080p"` 를 추가해야 한다(C-1 선행 작업, `google-flow-studio` 저장소). 단가는 2차 출처 기준 약 1.25배.
- 입력 이미지는 `google-flow-studio/outputs/` 안에 있어야 하므로, C-1 에서 루나 커버를 거기로 복사하는 단계가 필요하다(또는 `FLOW_EXTRA_INPUT_DIRS` 에 `data/luna_music` 추가).
- 무오디오 지정이 실제로 반영됐다(오디오 스트림 0개) → BGA 는 무오디오 단가로 계산해도 된다.

C-0 네 항목이 모두 끝났다. B 안(8초×3, xfade) 기준 트랙당 예상 비용은 720p ≈ $1.9, 1080p ≈ $2.4.

C-0 결과를 사용자에게 보고하고 **C-1 착수 여부를 별도 승인**받는다.

#### C-1. (승인 후) 구현 범위 — 별도 지시서로 분리

승인되면 다음을 담은 지시서를 다시 쓴다: 루나 `visual_prompt`·장르·BPM → 춘식 Optical Mastery 프롬프트 바인딩, 16:9 클립 N 개 생성, FFmpeg `xfade` 루프 렌더러, B-2 의 파형 오버레이 재사용, 렌더 결과를 `render_luna_video` 와 같은 `video.mp4` 자리에 두어 업로드 코드 무수정.

---

## 5. 공통 작업 규칙

1. 작업 시작 전 `git status`, `git branch` 확인·기록. Phase 별로 3장의 브랜치를 `main` 에서 새로 딴다.
2. 베가 지시서 3~6장의 계약(`track_data.mastering`, `/api/luna/master`, DSP 규칙)을 바꾸지 않는다. 숏폼은 마스터 결과를 **읽기만** 한다.
3. 기존 API 의 요청·응답 필드를 삭제하거나 이름을 바꾸지 않는다. 새 필드는 전부 기본값이 있어야 한다.
4. 완료 시 변경 파일 목록, 테스트 결과 전문, 수용 기준 체크 상태를 보고하고 커밋·푸시 승인을 받는다.
5. 민감 정보(`token.json`, `.env`, 서비스 계정 키) 커밋 금지.

## 6. 금지 사항

- Phase A 에서 `GENRE_SPECS` 의 `vocal_affinity` 값을 바꾸지 않는다. (값 변경은 제품 결정이므로 사용자 승인 필요)
- Phase B 에서 춘식·Veo·`google-flow` MCP 를 호출하지 않는다.
- Phase C-0 에서 사용자 명시 승인 없이 Veo 를 호출하지 않는다.
- 기존 67개 트랙의 `meta.json` 을 일괄 수정하지 않는다.
- `uploader.upload_video` 의 시그니처를 바꾸지 않는다 (키워드 인자 추가만 허용).
