# 루나 BGA(배경 영상) — 춘식 디렉터 연계 작업지시서 (Phase C-1)

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | 루나 완곡용 Veo 3.1 루프 배경 영상(BGA) 생성 파이프라인 |
| 프로젝트 | `유튜브 영상분석실습` |
| 작성일 | 2026-10-09 |
| 선행 문서 | `작업지시서_Luna_보컬판정_숏폼_BGA.md` Phase C-0 (조사·실측 완료, PR #18) |
| 구현 워커 | Antigravity |
| 독립 검증 | Claude Code |
| 비용 | **Veo 과금 발생** — 트랙당 클립 3개, 720p 무오디오 기준 약 $1.9 (2차 출처 단가). 실제 호출은 명시 승인 단계에서만 |
| 해상도 결정 | **720p 로 진행** (사용자 결정 2026-10-09). 1080p 는 후속 옵션 |

이 문서는 C-0 결론(엔진 = Vertex AI Veo 3.1 Fast, 루프 = 8초 클립 3개 + 1초 크로스페이드, 커버 Image-to-Video)을 그대로 구현 범위로 옮긴 것이다. 춘식은 별도 저장소(`casareborgia/choonsik-video-agent`)의 쇼츠 에이전트로 그대로 두고, TubeInsight 안에는 **춘식의 연출 어휘만 빌린 BGA 디렉터 모듈**을 새로 만든다.

---

## 2. 목표와 원칙

1. 루나 트랙 1개 → 커버 이미지를 첫 프레임으로 한 **16:9 Veo 클립 3개** → ffmpeg 크로스페이드 루프 → 완곡 길이의 `video.mp4`.
2. **업로드 코드 무수정.** 결과물은 기존 켄번즈 렌더와 같은 자리(`data/luna_music/<id>/video.mp4`, `track["video_file"]`)에 둔다. 숏폼(Phase B)·업로드는 그대로 동작한다.
3. **비용 가드가 코드에 있어야 한다.** 호출 전 예상 비용 표시, `confirm` 없이는 호출 불가, 트랙당 클립 상한, 일일 클립 상한, 드라이런 모드.
4. 켄번즈 렌더는 **폴백으로 유지**한다. BGA 가 없거나 실패해도 기존 흐름이 끊기지 않는다.
5. 외부 저장소(`google-flow-studio`)를 임포트하지 않는다. Vertex 호출 코드는 그 저장소의 `flow_visual.py` `start_video/get_video` 를 **참고해 TubeInsight 안에 작게 다시 쓴다**(의존성은 이미 있는 `google-genai`). 이유: `outputs/` 입력 경로 제한과 별도 `.env` 를 피하기 위함.

---

## 3. C-0 에서 확정된 전제

| 항목 | 값 | 근거 |
|---|---|---|
| 인증 | Vertex AI ADC (`gcloud auth application-default login` 완료 상태), 프로젝트 `southern-engine-495314-p2`, 리전 `us-central1` | 실측 성공 |
| 모델 | `veo-3.1-fast-generate-001` | 실측 성공, 약 80초/클립 |
| 입력 | 루나 커버(1376×768 JPG) Image-to-Video, 8초, 16:9, `generate_audio=False` | 실측에서 커버 구도·톤 유지 확인, 오디오 스트림 0개 확인 |
| 출력 | 1280×720 24fps H.264, `video_bytes` 로 직접 수신 | 실측 |
| 루프 | 클립 3개 × 8초, 1초 `xfade` → 약 22초 주기, 3분 곡 8회 반복 | C-0 (4) B 안 |

---

## 4. 구현 범위

### 4.1 모듈 `choonsik_bga.py` (신규)

```
plan_bga_shots(track_data, n_shots=3) -> list[dict]        # 비용 0
estimate_bga_cost(n_shots, duration=8, resolution="720p") -> dict
generate_bga_clips(track_data, shots, progress_cb=None, dry_run=False, client=None) -> track_data   # 과금
render_bga_loop(track_data, with_waveform=False, progress_cb=None) -> track_data   # ffmpeg
```

**`plan_bga_shots`** — 트랙의 `visual_prompt`·`genre`·`mood`·`lyria_prompt`(BPM) 로 샷 3개의 Veo 프롬프트를 만든다.
- 춘식 Optical Mastery 어휘를 **BGA 용으로 순화**해서 쓴다. 쇼츠용 "Dolly zoom / Low-angle hero shot / High-contrast Cyberpunk" 은 배경 영상에 맞지 않는다.
  - 카메라(샷별 고정): ① `very slow push-in dolly` ② `slow lateral drift, parallax on foreground` ③ `slow pull-back revealing the scene`
  - 조명: `soft volumetric light`, `subtle cinematic film grain`, `global illumination`
  - 그레이딩(장르별 기본): lofi/piano/acoustic → `muted nostalgic warm`, ambient/sleep/dark-ambient → `cool desaturated deep blue`, synthwave/citypop → `teal and magenta neon`, jazz/rnb-chill → `warm amber low-key`
  - 공통 제약(모든 샷 끝에 고정 문구): `No people, no text, no logos, no camera shake, seamless slow motion suitable for looping, start exactly from the reference image`
- LLM(`llm_client.call_llm_json`) 으로 `visual_prompt` 를 샷 3개로 전개하되, **LLM 실패 시 위 템플릿만으로 결정적 프롬프트를 만든다**(테스트는 이 경로로 검증).
- 반환: `[{"index": 0, "camera": "...", "prompt": "..."}, ...]`. `track["bga"]["shots"]` 에 저장.

**`estimate_bga_cost`** — `n × duration × 단가`. 단가는 상수 `BGA_RATE_PER_SEC = {"720p": 0.08, "1080p": 0.10}`(무오디오, 2차 출처) 에 두고 docstring 에 "공식 단가 아님, Cloud Billing 으로 확정" 을 명시. 반환 `{"usd": float, "clips": n, "seconds": n*duration, "rate_source": "secondary"}`.

**`generate_bga_clips`** — Vertex 호출.
- 클라이언트: `genai.Client(vertexai=True, project=os.getenv("GCP_PROJECT"), location=os.getenv("GCP_VIDEO_LOCATION", "us-central1"))`. 환경변수 없으면 `RuntimeError("GCP_PROJECT 미설정")`. `client` 인자로 주입 가능(테스트용).
- 입력 이미지: `track["cover_file"]` 바이트를 `types.Image(image_bytes=..., mime_type=...)` 로 직접 전달 → 파일 복사 불필요.
- 설정: `types.GenerateVideosConfig(aspect_ratio="16:9", duration_seconds=8, number_of_videos=1, generate_audio=False)`. `resolution` 은 넣지 않는다(720p 결정). 1080p 옵션은 환경변수 `BGA_RESOLUTION=1080p` 일 때만 `resolution="1080p"` 추가.
- 순차 실행. 샷마다 `operations.get` 폴링 **10초 간격, 최대 5분**. 완료 시 `data/luna_music/<id>/bga/clip_<i>.mp4` 저장. `video_bytes` 가 없고 `uri` 만 오면 실패로 처리하고 사유 기록(실측에서는 바이트로 왔음).
- 안전 필터로 비면(`rai_media_filtered_reasons`) 해당 샷만 실패 표시하고 다음 샷 진행. 성공 클립이 **2개 이상**이면 렌더 가능으로 본다.
- **비용 가드**
  - `dry_run=True` → 호출 없이 `shots`·`estimate` 만 기록하고 반환.
  - 트랙당 상한 `BGA_MAX_CLIPS_PER_TRACK=3`(상수). 재생성 요청도 이 안에서.
  - 일일 상한 `BGA_MAX_CLIPS_PER_DAY`(env, 기본 12). 카운터 `data/bga_usage.json`(`{"YYYY-MM-DD": n}`). 초과 시 호출 전에 `RuntimeError`.
  - `track["bga"]["cost_estimate_usd"]`, `operation_names`, `generated_at`, 샷별 `status`(`done|failed|skipped`)·`error` 기록.

**`render_bga_loop`** — ffmpeg 만.
1. 성공 클립 n개(2~3)를 `xfade=transition=fade:duration=1` 로 이어 **루프 단위** `bga/loop_unit.mp4` 생성. 이음새(마지막→첫 클립)도 끊기지 않도록 **단위 끝 1초와 시작 1초를 한 번 더 xfade** 해 주기 끝에서 처음으로 자연스럽게 넘어가게 한다(구현: `[last][first]xfade` 로 만든 1초 브리지를 단위 끝에 붙이고 단위 시작 1초를 잘라냄).
2. `ffmpeg -stream_loop -1 -i loop_unit.mp4 -i audio.mp3 ... -shortest` 로 완곡 길이에 맞춘다. 출력은 `scale=1920:1080`(720p 업스케일, `flags=lanczos`) — 유튜브 1080p 트랙 확보 목적, 원본 화질이 늘지는 않음을 docstring 에 명시. 720p 그대로 두는 옵션 `upscale=False`.
3. 오버레이: `fade in 2s / out 3s`, 선택적으로 Phase B 의 `waveform_overlay_filter()` 하단 파형(`with_waveform`), 타이틀 drawtext(없으면 기존과 같이 생략).
4. 오디오는 **베가 마스터본** `track["audio_file"]`. `audio_raw` 금지.
5. 결과를 `video.mp4` 에 쓰고 `track["video_file"]`, `video_url`, `rendered_at` 갱신, `video_stale` 해제, **`track["video_source"] = "bga"`** 기록(켄번즈는 `"cover"`). 기존 `video.mp4` 가 있으면 `video_cover_backup.mp4` 로 한 번 보존.
6. 클립이 2개 미만이면 `RuntimeError` — 호출부가 켄번즈 폴백을 안내한다.

### 4.2 `luna_engine.py` 변경 (최소)
- `render_luna_video` 끝에 `track_data["video_source"] = "cover"` 한 줄 추가.
- `list_tracks` 반환에 `"bga": d.get("bga")`, `"video_source": d.get("video_source")` 추가.
- 베가 재마스터로 `video_stale` 가 서는 경로([app.py `/api/luna/master`](app.py))는 그대로 — BGA 렌더도 같은 플래그를 본다.

### 4.3 API (`app.py`)

| 라우트 | 바디 | 비용 | 동작 |
|---|---|---|---|
| `POST /api/luna/bga/plan` | `{track_id}` | 0 | 샷 3개 프롬프트 + 예상 비용 반환·저장 |
| `POST /api/luna/bga/generate` | `{track_id, confirm: bool, dry_run?: bool}` | **과금** | `confirm != true` 면 400. 샷이 없으면 먼저 `plan`. 일일 상한 초과 시 429 |
| `POST /api/luna/bga/render` | `{track_id, with_waveform?: bool, upscale?: bool}` | 0 | 루프 렌더 → `video.mp4` |
| `GET /api/luna/bga/usage` | — | 0 | 오늘 생성 클립 수 / 상한 |

환경변수(`.env.example` 에 추가, 값은 비움): `GCP_PROJECT`, `GCP_VIDEO_LOCATION=us-central1`, `BGA_VEO_MODEL=veo-3.1-fast-generate-001`, `BGA_MAX_CLIPS_PER_DAY=12`, `BGA_RESOLUTION=720p`.

### 4.4 UI (6단계 루나 탭)
- 비디오 플레이어 위에 **"3.7단계: 춘식 BGA (Veo 루프 배경)"** 패널.
  - `[샷 기획 (무료)]` → 샷 3개 카메라·프롬프트 미리보기 + **예상 비용 `$1.9` 와 오늘 사용량 `n/12`** 표시.
  - `[Veo 클립 생성 (과금)]` → 브라우저 `confirm()` 으로 금액 재확인 후 `confirm: true` 전송. 진행 중 샷별 상태(대기/생성 중/완료/실패) 표시. 완료 클립은 작은 `<video>` 3개로 미리보기.
  - `[루프 렌더 → video.mp4]` (파형 오버레이 체크박스) → 기존 비디오 플레이어가 갱신되고 상태 배지 `BGA 렌더 완료`.
  - 기존 `[2. 비디오 렌더링]`(켄번즈) 버튼은 그대로 두고 라벨에 "(커버 켄번즈)" 를 덧붙인다. 두 렌더 모두 같은 `video.mp4` 를 덮어쓰며, 현재 어느 쪽인지 `video_source` 로 배지 표시.
- 보관함 카드에 `🎬 BGA` 배지(`video_source === "bga"`).

### 4.5 테스트 `tests/test_choonsik_bga.py`
LLM·Vertex 는 전부 모킹. ffmpeg 는 있을 때만 실제 실행.
- `plan_bga_shots`: LLM 실패 → 템플릿 3샷, 카메라 3종이 서로 다름, 공통 제약 문구 포함, 장르별 그레이딩 매핑.
- `estimate_bga_cost(3)` → `usd≈1.92`, `rate_source=="secondary"`.
- `generate_bga_clips`: `dry_run` 은 클라이언트 호출 0회. 가짜 클라이언트로 3회 호출·폴링·파일 저장·`operation_names` 기록. 2번째 샷 안전 필터 → `failed` 표시, 나머지 진행. 일일 상한 도달 → 호출 전 예외. `confirm` 없는 API 호출 → 400.
- `render_bga_loop`(ffmpeg): 합성 클립 3개(3초, 색 다름) + 10초 사인파 음원 → 출력 길이 ≈ 10초, 1920×1080(업스케일) 또는 1280×720(`upscale=False`), `video_source=="bga"`, 기존 `video.mp4` 백업 생성. 클립 1개 → 예외.
- 회귀: `test_luna_leo_integrity`, `test_luna_shorts`, `test_luna_vocal_decision`, `test_vega_*` 통과. **업로드 코드 diff 0 줄** 확인.

---

## 5. 단계와 승인 지점

| 단계 | 브랜치 | 내용 | 비용 | 승인 |
|---|---|---|---|---|
| C-1a | `feat/luna-bga-engine` | `choonsik_bga.py` 전부 + API + 테스트. **실제 Veo 호출 없이** 드라이런·모킹으로 완료 | 0 | 완료 보고 후 PR |
| C-1b | (C-1a 머지 후, 코드 변경 없음) | 트랙 1개로 실제 `generate`(클립 3개, ≈$1.9) → 루프 렌더 → 결과 확인 | 약 $1.9 | **호출 전 사용자 명시 승인** |
| C-1c | `feat/luna-bga-ui` | UI 패널·배지·사용량 표시 | 0 | 완료 보고 후 PR |

C-1b 결과(실제 과금액, 루프 이음새 자연스러움, 커버 톤 유지)를 문서 7장에 기록한다. 이음새가 거슬리면 C 안(클립 6개)으로 가기 전에 xfade 길이(1→2초)를 먼저 조정한다.

---

## 6. 수용 기준

- [ ] `confirm: true` 없이는 어떤 경로로도 Veo 가 호출되지 않는다 (API 테스트)
- [ ] 드라이런·일일 상한·트랙당 상한이 코드에 있고 테스트로 검증된다
- [ ] 샷 기획은 LLM 없이도 결정적으로 동작한다
- [ ] 루프 렌더 결과가 `video.mp4` 자리에 들어가고 `uploader.py`·`upload_luna_to_youtube` 는 수정되지 않는다
- [ ] 켄번즈 렌더·숏폼·업로드 기존 테스트 전부 통과
- [ ] C-1b: 트랙 1개 실생성 → 루프 영상 유튜브 업로드까지 기존 버튼으로 완료, 실제 과금액 기록

## 7. C-1b 실측 결과 (작성 예정)

## 8. 금지 사항
- `confirm` 가드·상한을 우회하는 코드 경로를 만들지 않는다.
- `google-flow-studio`·춘식 저장소 코드를 복사해 오되 임포트하지 않는다. 두 저장소를 수정하지 않는다.
- `audio_raw.*` 를 입력으로 쓰지 않는다. 베가 계약(`track_data.mastering`, `/api/luna/master`)을 바꾸지 않는다.
- `.env` 와 GCP 프로젝트 ID 를 커밋하지 않는다(`.env.example` 은 빈 값).
- 1080p 전환, 클립 6개(C 안), Lyria 스템 믹싱은 이 지시서 범위 밖이다.
