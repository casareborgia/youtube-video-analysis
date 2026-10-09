# 루나 BGA C-1a 작업지시서 — 춘식 BGA 엔진·API 구현 (Veo 호출 없음)

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | `choonsik_bga.py` 엔진 + API + 테스트 구현 (Phase C-1a) |
| 프로젝트 | `유튜브 영상분석실습` (`casareborgia/youtube-video-analysis`) |
| 작성일 | 2026-10-09 |
| 상위 문서 | `작업지시서_Luna_BGA_춘식_C1.md` (4장 구현 범위, 5장 단계) — 이 문서는 그중 **C-1a 만** 상세화한 것 |
| 구현 워커 | **Antigravity** |
| 독립 검증 | **Claude Code** (6장 검증 절차) |
| 작업 브랜치 | `feat/luna-bga-engine` (`main` 에서 분기, 기준 커밋 `20a6840` 이상) |
| 비용 | **0.** 이 단계에서는 Veo 를 호출하지 않는다. 실제 호출은 C-1b 에서 사용자 승인 후 Claude Code 가 수행 |

---

## 2. 범위

**포함**
- 신규 `choonsik_bga.py` — `plan_bga_shots`, `estimate_bga_cost`, `generate_bga_clips`, `render_bga_loop`, 사용량 카운터
- `app.py` — 라우트 4개 + 요청 모델 3개
- `luna_engine.py` — 2곳만 수정 (3.2)
- `.env.example` — 변수 5개 추가
- `tests/test_choonsik_bga.py` — 신규

**제외** (C-1c 또는 범위 밖)
- `static/index.html`, `static/app.js` 는 **건드리지 않는다**
- `uploader.py`, `vega_engine.py`, `producer.py` 는 **건드리지 않는다**
- 1080p, 클립 6개, `google-flow-studio`·춘식 저장소 수정

---

## 3. 파일별 지시

### 3.1 `choonsik_bga.py` (신규, 프로젝트 루트)

상단 상수:
```python
BGA_DIR_NAME = "bga"                      # data/luna_music/<id>/bga/
BGA_CLIP_SECONDS = 8
BGA_N_SHOTS = 3
BGA_MAX_CLIPS_PER_TRACK = 3
BGA_DEFAULT_DAILY_CAP = 12                # env BGA_MAX_CLIPS_PER_DAY 로 덮어씀
BGA_XFADE_SECONDS = 1.0
BGA_POLL_INTERVAL = 10                    # 초
BGA_POLL_TIMEOUT = 300                    # 초
BGA_RATE_PER_SEC = {"720p": 0.08, "1080p": 0.10}   # USD, 무오디오, 2차 출처 — 공식 단가 아님
BGA_USAGE_FILE = os.path.join(luna_engine.DATA_DIR, "bga_usage.json")
```

**카메라·조명·그레이딩 어휘** (모듈 상수, 춘식 `producer.py` 의 Optical Mastery 를 BGA 용으로 순화):
```python
BGA_CAMERA_MOVES = [
    "very slow push-in dolly toward the focal subject",
    "slow lateral drift with gentle parallax between foreground and background",
    "slow pull-back revealing more of the scene",
]
BGA_LIGHTING = "soft volumetric light, global illumination, subtle cinematic film grain"
BGA_GRADING_BY_GENRE = {
    "lofi": "muted nostalgic warm tones", "piano": "muted nostalgic warm tones", "acoustic": "muted nostalgic warm tones",
    "ambient": "cool desaturated deep blue", "sleep": "cool desaturated deep blue", "dark-ambient": "cool desaturated deep blue",
    "synthwave": "teal and magenta neon", "citypop": "teal and magenta neon",
    "jazz": "warm amber low-key", "rnb-chill": "warm amber low-key",
}
BGA_PROMPT_SUFFIX = ("No people, no text, no logos, no camera shake, seamless slow motion suitable for looping, "
                     "start exactly from the reference image")
```
장르 키는 `vega_engine.resolve_genre_key(track["genre"])` 로 구한다(이미 있는 함수, `luna_engine.GENRE_SPECS` 키와 동일: `lofi, ambient, synthwave, sleep, jazz, piano, citypop, acoustic, rnb-chill, dark-ambient`). 매핑에 없으면 `"muted nostalgic warm tones"`.

**`plan_bga_shots(track_data, n_shots=BGA_N_SHOTS) -> list[dict]`**
1. 입력: `visual_prompt`(없으면 `story`), `genre`, `mood`, `lyria_prompt`(BPM 숫자 추출, 없으면 생략).
2. LLM 경로: `llm_client.call_llm_json(messages, max_tokens=1500, temperature=0.6)` 에 "샷 n개의 영문 Veo 프롬프트 JSON 배열 `{"shots":[{"camera":..,"prompt":..}]}`" 를 요청. 각 샷은 `BGA_CAMERA_MOVES[i]` 를 카메라로 고정하고 조명·그레이딩·접미사를 **코드에서** 덧붙인다(LLM 이 빼먹어도 보장).
3. 폴백: LLM 예외·파싱 실패·샷 수 불일치 시 템플릿만으로 결정적 생성:
   `f"{visual_prompt}. Camera: {BGA_CAMERA_MOVES[i]}. Lighting: {BGA_LIGHTING}. Color grading: {grading}. {BGA_PROMPT_SUFFIX}"`
4. 반환·저장: `[{"index": i, "camera": ..., "prompt": ..., "source": "llm"|"template"}]` → `track_data["bga"]["shots"]`, `track_data["bga"]["planned_at"]`, `luna_engine.save_track`.

**`estimate_bga_cost(n_shots=BGA_N_SHOTS, duration=BGA_CLIP_SECONDS, resolution=None) -> dict`**
- `resolution` 기본은 `os.getenv("BGA_RESOLUTION", "720p")`.
- 반환 `{"usd": round(n*duration*rate, 2), "clips": n, "seconds": n*duration, "resolution": r, "rate_per_sec": rate, "rate_source": "secondary"}`.

**사용량 카운터** — `get_today_usage() -> int`, `_increment_usage(n=1)`, `daily_cap() -> int`. 파일 `{"YYYY-MM-DD": n}`. 파일 없음·깨짐은 0 으로.

**`generate_bga_clips(track_data, shots=None, progress_cb=None, dry_run=False, client=None, sleep_fn=time.sleep) -> dict`**
1. `shots` 없으면 `track_data["bga"]["shots"]`, 그것도 없으면 `plan_bga_shots` 호출.
2. 가드 순서(**호출 전에 전부 검사**): `len(shots) > BGA_MAX_CLIPS_PER_TRACK` → `ValueError`; `get_today_usage() + len(shots) > daily_cap()` → `RuntimeError("일일 Veo 클립 상한 ...")`; `cover_file` 없음 → `FileNotFoundError`.
3. `dry_run=True`: 호출 없이 `track_data["bga"].update({"dry_run": True, "estimate": estimate_bga_cost(len(shots))})` 저장 후 반환.
4. 클라이언트: `client` 인자가 없으면 `_make_vertex_client()` — `from google import genai; genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"], location=os.getenv("GCP_VIDEO_LOCATION", "us-central1"))`. `GCP_PROJECT` 없으면 `RuntimeError("GCP_PROJECT 미설정")`. **임포트는 함수 안에서** 한다(모듈 임포트 시 google-genai 가 없어도 앱이 뜨도록).
5. 샷마다 순차:
   - `types.Image(image_bytes=open(cover).read(), mime_type=mimetypes.guess_type(cover)[0] or "image/jpeg")`
   - `types.GenerateVideosConfig(aspect_ratio="16:9", duration_seconds=8, number_of_videos=1, generate_audio=False)`; `os.getenv("BGA_RESOLUTION")=="1080p"` 일 때만 `resolution="1080p"` 추가.
   - `op = client.models.generate_videos(model=os.getenv("BGA_VEO_MODEL","veo-3.1-fast-generate-001"), prompt=shot["prompt"], image=img, config=cfg)`
   - 폴링: `while not op.done: sleep_fn(BGA_POLL_INTERVAL); op = client.operations.get(op)`; 누적 `BGA_POLL_TIMEOUT` 초과 → 샷 `status="failed", error="timeout"`.
   - 완료: `op.error` → failed; `result = op.response or op.result`; `generated_videos` 비면 `rai_media_filtered_reasons` 를 error 로 failed; `video.video_bytes` 없으면 failed("no bytes"). 성공 시 `bga/clip_<i>.mp4` 저장, `_increment_usage(1)`, `status="done"`.
   - 각 샷 결과를 `track_data["bga"]["clips"][i] = {"index", "status", "file", "url", "operation_name", "error"}` 로 기록하고 **샷마다 `save_track`** (중간 실패 시 진행 상황 보존).
6. 종료: `track_data["bga"]["generated_at"]`, `cost_estimate_usd`, `done_count`. 성공 0개면 `RuntimeError`; 1개 이상이면 정상 반환(렌더 가능 여부는 렌더가 판단).

**`render_bga_loop(track_data, with_waveform=False, upscale=True, progress_cb=None) -> dict`**
1. 입력: `status=="done"` 인 클립 파일 목록(순서대로). **2개 미만이면 `RuntimeError("BGA 클립이 2개 미만 — 켄번즈 렌더를 사용하세요")`**.
2. 길이: 각 클립 `producer.audio_duration()`(비디오도 됨) 로 측정. 오디오는 `track_data["audio_file"]`(베가 마스터본). `audio_raw` 사용 금지.
3. 루프 단위 `bga/loop_unit.mp4`:
   - n개 클립을 `xfade=transition=fade:duration=1:offset=<누적-1>` 체인으로 연결(filter_complex, 오디오 없음).
   - 이음새: 마지막 클립 끝 1초 → 첫 클립 시작 1초를 `xfade` 한 1초 브리지를 단위 **끝**에 붙이고, 단위 **앞** 1초를 `trim` 으로 제거한다. 결과 단위 길이 = `sum(len) - (n-1)*1 - 1 + 1 = sum(len) - (n-1)`. (예: 8+8+8 → 22초)
   - 구현이 복잡하면 2단계로 나눠도 된다: ① 체인 → `unit_raw.mp4`, ② `unit_raw` 의 `[last 1s][first 1s]` 로 브리지 생성 → concat → trim.
4. 최종 `video.mp4`: `ffmpeg -y -stream_loop -1 -i loop_unit.mp4 -i audio.mp3 -filter_complex "<scale>,fade=in:0:2,fade=out:<dur-3>:3[,파형 오버레이]" -map [v] -map 1:a -c:v libx264 -preset veryfast -crf 22 -c:a aac -b:a 192k -t <audio_dur> -shortest`.
   - `upscale=True` → `scale=1920:1080:flags=lanczos`; False → 원본 유지.
   - `with_waveform=True` → `luna_engine.waveform_overlay_filter(w, 180)` 로 하단 파형 오버레이(Phase B 함수 재사용, 입력 `[1:a]`).
   - drawtext 는 쓰지 않는다(이 환경 ffmpeg 에 없음).
5. 기존 `video.mp4` 가 있고 `track_data.get("video_source") != "bga"` 면 `video_cover_backup.mp4` 로 **한 번만** 복사(이미 백업이 있으면 덮어쓰지 않음).
6. 저장: `video_file`, `video_url`, `rendered_at`, `video_source="bga"`, `pop("video_stale")`, `bga["loop_unit_file"]`, `bga["rendered_at"]`. `save_track`.

### 3.2 `luna_engine.py` — 정확히 2곳
- `render_luna_video` 의 `track_data["rendered_at"] = time.time()` **바로 다음 줄**에 `track_data["video_source"] = "cover"` 추가.
- `list_tracks` 의 `"shorts": d.get("shorts"),` **바로 다음 줄**에 `"bga": d.get("bga"),` 와 `"video_source": d.get("video_source"),` 추가.
- 그 외 어떤 줄도 바꾸지 않는다. 특히 `detect_vocal_language`, `generate_music_concept`, 숏폼 함수들은 건드리지 않는다.

### 3.3 `app.py`
`class LunaShortsRenderRequest` 바로 아래에 모델 3개:
```python
class LunaBgaPlanRequest(BaseModel):
    track_id: str
class LunaBgaGenerateRequest(BaseModel):
    track_id: str
    confirm: Optional[bool] = False       # True 가 아니면 400
    dry_run: Optional[bool] = False
class LunaBgaRenderRequest(BaseModel):
    track_id: str
    with_waveform: Optional[bool] = False
    upscale: Optional[bool] = True
```
`/api/luna/shorts/render` 라우트 바로 아래에 라우트 4개 (`import choonsik_bga` 는 파일 상단 다른 엔진 임포트 옆에):

| 라우트 | 동작 |
|---|---|
| `POST /api/luna/bga/plan` | `load_track` 404 → `plan_bga_shots` → `{"shots", "estimate": estimate_bga_cost(len(shots)), "usage": {"today": get_today_usage(), "cap": daily_cap()}}` |
| `POST /api/luna/bga/generate` | `confirm` 이 `True` 가 아니면 **400** `"confirm=true 가 필요합니다 (Veo 과금)"`. 일일 상한 `RuntimeError` → **429**. 그 외 예외 500. `dry_run` 은 그대로 전달. 반환은 갱신된 track |
| `POST /api/luna/bga/render` | `render_bga_loop` → 갱신된 track. 클립 부족 `RuntimeError` → 400 |
| `GET /api/luna/bga/usage` | `{"today", "cap", "rate_source": "secondary", "estimate_per_track": estimate_bga_cost()}` |

### 3.4 `.env.example` — 8번 항목으로 추가 (값은 비움)
```
# 8. 춘식 BGA (Vertex AI Veo 3.1, 선택, 과금) — gcloud auth application-default login 필요
# GCP_PROJECT=
# GCP_VIDEO_LOCATION=us-central1
# BGA_VEO_MODEL=veo-3.1-fast-generate-001
# BGA_MAX_CLIPS_PER_DAY=12
# BGA_RESOLUTION=720p
```

### 3.5 `tests/test_choonsik_bga.py` (신규)
기존 `tests/test_luna_shorts.py` 의 관례(`unittest`, `patch.object(luna_engine, "LUNA_DIR", tmp)`, ffmpeg 는 `skipUnless`)를 따른다. 최소 아래 케이스:

| 그룹 | 케이스 |
|---|---|
| plan | LLM 예외 → 템플릿 3샷, `source=="template"`, 카메라 3종 서로 다름, 모든 prompt 에 `BGA_PROMPT_SUFFIX` 포함, `ambient` → `cool desaturated deep blue` / `citypop` → `teal and magenta neon`; LLM 이 샷 2개만 주면 템플릿으로 대체; LLM 정상 → `source=="llm"` 이고 접미사·카메라가 코드에서 보강됨 |
| cost | `estimate_bga_cost(3)["usd"] == 1.92`, `rate_source=="secondary"`; `BGA_RESOLUTION=1080p` 환경에서 2.4 |
| usage | 파일 없음 → 0; 증가 후 오늘 값; 날짜 키 분리 |
| generate | `dry_run=True` → 가짜 클라이언트 호출 0회, `bga.dry_run==True`, `estimate` 저장; 가짜 클라이언트(`generate_videos` → op(done=False) → `operations.get` 2회 후 done, `video_bytes=b"..."`) 로 3샷 → 파일 3개, usage +3, `operation_names` 3개, `sleep_fn` 호출 횟수 확인; 2번째 샷 `generated_videos=[]`+`rai_media_filtered_reasons` → 그 샷만 `failed`, 나머지 `done`; 일일 상한(usage 11, cap 12, 샷 3) → **호출 0회** 로 `RuntimeError`; 샷 4개 → `ValueError`; `GCP_PROJECT` 없음+client 없음 → `RuntimeError`; 타임아웃(항상 `done=False`, `sleep_fn` 더미) → `failed`/`timeout` |
| api | `POST /api/luna/bga/generate` `confirm` 없음 → 400, 가짜 클라이언트 **미호출**; `confirm=true, dry_run=true` → 200; 상한 초과 → 429; `GET /api/luna/bga/usage` 200 |
| render (ffmpeg) | 합성 클립 3개(각 3초, `color=` 로 색 다르게, 320x180) + 10초 사인파 음원 → `video.mp4` 길이 9.5~10.5초, `upscale=True` 1920×1080 / `False` 320×180, `video_source=="bga"`, `loop_unit.mp4` 길이 ≈ 3+3+3-2 = 7초(±0.3), 기존 `video.mp4` 가 있으면 `video_cover_backup.mp4` 생성; 클립 1개 → `RuntimeError`; `with_waveform=True` 도 성공 |
| 회귀 | `python -m unittest discover tests` 전체 통과 (현재 263개 + 신규) |

---

## 4. 작업 순서 (Antigravity)

1. `git status` / `git branch` 확인 → `main` 최신(`git pull`) → `git checkout -b feat/luna-bga-engine`.
2. `choonsik_bga.py` 작성 → `python3 -m py_compile choonsik_bga.py`.
3. `luna_engine.py` 2곳 수정 → **즉시 `python3 -m py_compile luna_engine.py`** 와 `git diff luna_engine.py` 로 변경이 **추가 3줄뿐**인지 확인.
4. `app.py` → `py_compile` → `.venv/bin/python -c "import app"`.
5. `.env.example`, 테스트 작성 → `.venv/bin/python -m unittest tests.test_choonsik_bga` → 전체 `discover tests`.
6. 보고: 변경 파일 목록, `git diff --stat`, 테스트 전문(실패 0), 수용 기준 체크. **커밋·푸시는 사용자 승인 후.** Veo 는 호출하지 않는다.

### 4.1 편집 도구 주의 (지난 세션 사고 재발 방지)
- 2026-10-09 새벽 세션에서 `replace_file_content` 로 `luna_engine.py` 145~437행을 통째로 치환하다가 위쪽 함수 `detect_vocal_language` 가 깨지고 파일이 비-UTF-8 상태가 되어 `import luna_engine` 자체가 불가능해졌다. 이번에는:
  - 기존 파일 수정은 **삽입 지점 한 줄을 anchor 로 한 최소 범위 치환**만 한다. 수십 줄 범위 치환 금지.
  - 각 편집 직후 `python3 -m py_compile <file>` 과 `git diff --stat` 로 의도한 줄 수만 바뀌었는지 확인한다.
  - 파일 읽기 도구가 `unsupported mime type` 오류를 내면 **파일이 깨진 신호**다. 즉시 `git checkout -- <file>` 로 되돌리고 다시 시작한다.
- 신규 파일(`choonsik_bga.py`, 테스트)은 한 번에 쓰되, 쓴 뒤 반드시 `py_compile`.

---

## 5. 수용 기준 (C-1a)

- [ ] `confirm != true` 면 API 어느 경로로도 Vertex 클라이언트가 만들어지지 않는다 (테스트로 증명)
- [ ] `dry_run`·트랙당 상한·일일 상한·`GCP_PROJECT` 미설정이 **호출 전에** 막힌다
- [ ] 샷 기획이 LLM 없이 결정적으로 동작하고 접미사·카메라가 항상 포함된다
- [ ] 루프 렌더가 `video.mp4` 자리에 들어가고 `video_source="bga"`, 켄번즈 백업이 남는다
- [ ] `uploader.py`, `upload_luna_to_youtube`, `vega_engine.py`, `static/` 의 diff 가 **0 줄**
- [ ] `luna_engine.py` diff 가 **추가 3줄**뿐
- [ ] 신규 테스트 + 기존 263개 전체 통과 (`.env` 없이)

---

## 6. Claude Code 검증 절차

Antigravity 보고 후 Claude Code 가 다음을 독립 수행하고 결과를 PR 설명에 남긴다.

1. `git fetch` → 해당 브랜치를 **별도 워크트리**에서 체크아웃(안티그래비티 작업 트리는 건드리지 않음).
2. `git diff main --stat` 로 변경 파일이 2절 "포함" 목록과 일치하는지, 제외 파일 diff 0 인지.
3. `luna_engine.py` diff 가 추가 3줄인지, `detect_vocal_language`·`generate_music_concept` 해시가 `main` 과 같은지(`git diff main -- luna_engine.py | grep '^[-+]' | wc -l`).
4. `.venv/bin/python -m unittest discover tests` — `.env` 없는 워크트리에서 전체 통과.
5. 정적 점검: `grep -n "genai.Client\|generate_videos" choonsik_bga.py app.py` 로 클라이언트 생성이 `generate_bga_clips` 의 가드 **뒤**에만 있는지; `grep -rn "audio_raw" choonsik_bga.py` 가 0건인지; `BGA_PROMPT_SUFFIX` 가 모든 경로에서 붙는지.
6. 가드 수동 확인: `.env` 없는 상태에서 `curl -X POST /api/luna/bga/generate -d '{"track_id":"x"}'` → 400; `{"confirm":true,"dry_run":true}` → 200 또는 404(트랙 없음) 이고 Vertex 접근 흔적 없음.
7. ffmpeg 실렌더 테스트가 skip 되지 않고 **실제로 실행**됐는지(`-v` 출력 확인).
8. 통과 시 커밋·푸시·PR(제목 `feat(luna): 춘식 BGA 엔진·API (C-1a, Veo 미호출)`), 문제 시 P0/P1/P2 로 분류해 보고하고 사용자 결정 후 재작업 지시.

## 7. 금지 사항
- Veo·Vertex 실제 호출, `google-flow` MCP 호출.
- `static/`, `uploader.py`, `vega_engine.py`, `producer.py` 수정.
- `.env` 커밋, GCP 프로젝트 ID 를 코드·예제 파일에 적는 것.
- 테스트에서 실제 네트워크 사용.
