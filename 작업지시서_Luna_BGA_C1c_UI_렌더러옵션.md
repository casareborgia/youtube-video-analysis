# 루나 BGA C-1c 작업지시서 — UI 패널 + 렌더러 옵션(ffmpeg 기본 / Remotion 선택·폴백)

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | 6단계 루나 탭 "3.7단계 춘식 BGA" 패널, `BGA_RENDERER` 디스패처·폴백, 프롬프트 접미사 보강 |
| 프로젝트 | `유튜브 영상분석실습` (`casareborgia/youtube-video-analysis`) |
| 작성일 | 2026-10-11 |
| 선행 | C-1a(PR #21), C-1b-1 실생성(PR #23), C-1b-2 Remotion 스파이크(PR #27) 머지 완료. 기준 커밋 `adb9f79` 이상 |
| 구현 워커 | **Antigravity** |
| 독립 검증 | **Claude Code** (7장) |
| 작업 브랜치 | `feat/luna-bga-ui` |
| 비용 | **0.** Veo·Vertex·Remotion 실렌더를 테스트에서 호출하지 않는다. UI 수동 확인은 이미 생성된 `luna_1791476313` 의 클립·루프 단위로 한다(재생성 금지) |

### C-1b-3 비교 결과(이 지시서의 전제)

| | ffmpeg `render_bga_loop` | Remotion `render_bga_remotion` |
|---|---|---|
| 렌더 시간(176초 곡) | 19.5초 | 112~124초 |
| 타이포 | 없음(`drawtext` 미지원 빌드) | 제목·한글 부제 ✅ |
| 스펙트럼 | `showwaves` 띠 | 로그·dB 막대 ✅ |
| 의존성 | ffmpeg | Node + 1GB `node_modules` + Chrome |

→ **기본 렌더러는 ffmpeg 유지, Remotion 은 선택 옵션.** Remotion 이 실패(미설치·타임아웃·오류)하면 ffmpeg 로 자동 폴백하고 그 사실을 기록한다.

---

## 2. 범위

**포함**
- `choonsik_bga.py`: 디스패처 `render_bga`, Remotion 결과 채택(`_promote_remotion_output`), 프롬프트 접미사 보강, `remotion_available()`
- `app.py`: `/api/luna/bga/render` 에 `renderer` 인자, `/api/luna/bga/usage` 에 `remotion_available`·`default_renderer`
- `luna_engine.py`: **수정 없음** (`list_tracks` 는 이미 `bga`/`video_source` 를 내려준다)
- `static/index.html`, `static/app.js`: 3.7단계 패널, 상태 배지, 보관함 카드 배지
- `.env.example`: `BGA_RENDERER=ffmpeg`
- `tests/test_choonsik_bga.py` 보강, `tests/test_choonsik_bga_ui.py` 신규

**제외**
- `render_bga_loop`, `render_bga_remotion`, `generate_bga_clips` 본문 수정 (호출만 한다)
- `remotion/` 컴포지션 수정, `uploader.py`, `vega_engine.py`, `producer.py`
- 1080p, 6클립, xfade 길이 변경(설정값 노출만 허용, 4.1 참고)

---

## 3. 백엔드

### 3.1 `choonsik_bga.py`

**접미사 보강** (C-1b-1 발견: 클립 상단 모서리 얼룩)
```python
BGA_PROMPT_SUFFIX = ("No people, no text, no logos, no camera shake, clean lens, no vignette, no lens condensation, "
                     "seamless slow motion suitable for looping, start exactly from the reference image")
```
기존 테스트는 `BGA_PROMPT_SUFFIX in prompt` 로 검사하므로 그대로 통과해야 한다.

**`remotion_available() -> bool`** — `os.path.isdir(os.path.join(REMOTION_DIR, "node_modules"))`.

**`default_renderer() -> str`** — `os.getenv("BGA_RENDERER", "ffmpeg").lower()`; `"remotion"` 이 아니면 전부 `"ffmpeg"` 으로 정규화.

**`_promote_remotion_output(track_data) -> dict`** — Remotion 결과를 업로드 대상(`video.mp4`)으로 채택한다.
1. `bga.remotion.file` 없으면 `RuntimeError`.
2. 기존 `video.mp4` 가 있고 `video_source` 가 `"cover"`(또는 없음)면 `video_cover_backup.mp4` 로 **한 번만** 백업(이미 있으면 유지) — `render_bga_loop` 와 같은 규칙.
3. `shutil.copy(video_remotion.mp4 → video.mp4)` (원본 `video_remotion.mp4` 는 비교용으로 남긴다).
4. `video_file`/`video_url`/`rendered_at` 갱신, `video_source = "bga-remotion"`, `pop("video_stale")`, `save_track`.

**`render_bga(track_data, renderer=None, with_waveform=False, upscale=True, progress_cb=None) -> dict`** — 유일한 진입점.
```
renderer = (renderer or default_renderer()).lower()
bga["renderer_requested"] = renderer
if renderer == "remotion":
    try:
        if not remotion_available(): raise RuntimeError("Remotion 미설치")
        track = render_bga_loop(...)          # loop_unit.mp4 가 없으면 먼저 만든다 (이미 있어도 재실행 — 20초, 멱등)
        track = render_bga_remotion(track, progress_cb=progress_cb)
        track = _promote_remotion_output(track)
        bga["renderer_used"] = "remotion"; bga.pop("fallback_reason", None)
    except Exception as e:
        bga["fallback_reason"] = f"{type(e).__name__}: {str(e)[:200]}"
        track = render_bga_loop(track, with_waveform=with_waveform, upscale=upscale, progress_cb=progress_cb)
        bga["renderer_used"] = "ffmpeg"
else:
    track = render_bga_loop(...)
    bga["renderer_used"] = "ffmpeg"; bga.pop("fallback_reason", None)
save_track; return track
```
- `render_bga_loop` 가 2개 미만 클립으로 `RuntimeError` 를 내면 폴백하지 않고 그대로 올린다(클립 부족은 렌더러 문제가 아님). 구현은 "Remotion 경로의 예외 중 메시지에 `2개 미만` 이 포함되면 재-raise".
- Remotion 경로에서 `render_bga_loop` 를 먼저 부르는 이유: Remotion 은 `loop_unit.mp4` 를 입력으로 쓰고, 폴백 시 `video.mp4` 가 ffmpeg 결과로 이미 있어야 하기 때문.

### 3.2 `app.py`
- `LunaBgaRenderRequest` 에 `renderer: Optional[str] = None` 추가. 값은 `ffmpeg|remotion|None`; 그 외 문자열은 400.
- `/api/luna/bga/render` 는 `choonsik_bga.render_bga(track, renderer=req.renderer, with_waveform=..., upscale=...)` 를 호출. 기존 `"2개 미만"` → 400 매핑 유지.
- `/api/luna/bga/render-remotion` 은 **그대로 둔다**(비교용 `video_remotion.mp4` 만 만들고 채택하지 않는 경로).
- `/api/luna/bga/usage` 응답에 `"remotion_available": bool`, `"default_renderer": str` 추가.

### 3.3 `.env.example` 8번 블록에 한 줄
```
# BGA_RENDERER=ffmpeg   # remotion 으로 바꾸면 타이포·스펙트럼 포함 렌더(약 2분), 실패 시 ffmpeg 폴백
```

---

## 4. 프론트엔드

### 4.1 `static/index.html` — 3.7단계 패널
숏폼 패널(`#lunaShortsPanel`) **바로 아래**, 업로드 섹션 **위**에 추가. 기존 요소 ID 는 바꾸지 않는다.

```html
<div id="lunaBgaPanel" style="display:none; ...(숏폼 패널과 같은 카드 스타일, 색은 #c084fc 계열)">
  헤더: "🎬 3.7단계: 춘식 BGA (Veo 루프 배경 영상)" + 우측 <span id="lunaBgaUsage">오늘 0/12 · 트랙당 ≈ $1.92</span>
  행1: <button id="btnLunaBgaPlan">샷 기획 (무료)</button>
       <button id="btnLunaBgaGenerate" disabled>Veo 클립 생성 (과금)</button>
       <span id="lunaBgaGenStatus"></span>
  <div id="lunaBgaShots" style="display:none"> 샷 3개: 카메라 라벨 + 프롬프트(접기/펼치기, 기본 접힘) </div>
  <div id="lunaBgaClips" style="display:none; display:flex; gap:8px"> 클립별 <video width=240 muted controls> + 상태 배지(대기/완료/실패:사유) </div>
  행2: 렌더러 <select id="lunaBgaRendererSelect"><option value="ffmpeg">ffmpeg (빠름, 20초)</option><option value="remotion">Remotion (타이포·스펙트럼, 약 2분)</option></select>
       <label><input type="checkbox" id="lunaBgaWaveformCheck"> 파형 오버레이(ffmpeg)</label>
       <button id="btnLunaBgaRender" disabled>루프 렌더 → video.mp4</button>
  <div id="lunaBgaRenderNote" style="font-size:.74rem"></div>   ← 폴백 사유 등
</div>
```
- `#lunaBgaUsage` 는 패널이 보일 때 `GET /api/luna/bga/usage` 로 채운다. `remotion_available=false` 면 Remotion 옵션을 `disabled` 하고 라벨에 "(미설치)" 를 붙인다. `default_renderer` 를 초기 선택값으로.
- 기존 `[2. 비디오 렌더링]`(`#btnRenderLunaVideo`) 라벨 뒤에 작은 글씨로 "(커버 켄번즈)" 를 덧붙인다. 버튼 ID·동작은 그대로.
- `#lunaStatusBadge` 옆에 `<span id="lunaVideoSourceBadge">` 를 두고 `video_source` 에 따라 `커버 켄번즈 / 🎬 BGA (ffmpeg) / 🎬 BGA (Remotion)` 표시.

### 4.2 `static/app.js`
- `renderLunaTrackView(track)` 끝에 `renderLunaBgaPanel(track)` 호출(숏폼과 같은 패턴). 패널은 `track.audio_url` 이 있으면 표시.
- `renderLunaBgaPanel`:
  - `track.bga.shots` 있으면 샷 목록 표시 + 생성 버튼 활성화.
  - `track.bga.clips` 있으면 클립 카드(status `done` 만 `<video src=url>`, `failed` 는 사유). `done` 2개 이상이면 렌더 버튼 활성화.
  - `track.bga.renderer_used`/`fallback_reason` 이 있으면 `#lunaBgaRenderNote` 에 "Remotion 실패 → ffmpeg 로 렌더됨: <사유>" 또는 "Remotion 렌더 채택됨".
  - `#lunaVideoSourceBadge` 갱신.
- 핸들러
  - 기획: `POST /api/luna/bga/plan` → 응답의 `shots`·`estimate`·`usage` 로 패널 갱신. `currentLunaTrack.bga = {...(currentLunaTrack.bga||{}), shots}`.
  - 생성: `window.confirm(\`Veo 클립 ${n}개를 생성합니다. 예상 비용 $${usd} (오늘 ${today}/${cap}). 진행할까요?\`)` 가 true 일 때만 `POST /api/luna/bga/generate {track_id, confirm:true}`. 요청이 3~4분 걸리므로 버튼 스피너 + `#lunaBgaGenStatus` 에 "생성 중 (샷당 약 1분)…" 표시. 응답(갱신된 track)으로 `currentLunaTrack` 교체 → `renderLunaTrackView`. 429 는 "오늘 상한 도달" 안내.
  - 렌더: `POST /api/luna/bga/render {track_id, renderer, with_waveform, upscale:true}` → 갱신된 track 으로 `renderLunaTrackView` (기존 비디오 플레이어가 새 `video.mp4` 를 보여준다. 캐시 회피를 위해 `?t=<rendered_at>` 쿼리 추가) + `loadLunaHistory()`.
  - 렌더러 선택·파형 체크는 `localStorage`(`luna_bga_renderer`, `luna_bga_waveform`) 에 기억.
- 보관함 카드(`lunaHistoryList.innerHTML = tracks.map(...)`)에 `t.video_source === 'bga' || 'bga-remotion'` 이면 `🎬 BGA` 배지.

---

## 5. 테스트

### 5.1 `tests/test_choonsik_bga.py` 보강
| 케이스 | 기대 |
|---|---|
| `default_renderer()` | env 없음→`ffmpeg`; `BGA_RENDERER=REMOTION`→`remotion`; `=foo`→`ffmpeg` |
| `render_bga(renderer="ffmpeg")` | `render_bga_loop` 만 호출(모킹), `renderer_used=="ffmpeg"`, `fallback_reason` 없음 |
| `render_bga(renderer="remotion")` 정상 | `render_bga_loop`→`render_bga_remotion`→`_promote_remotion_output` 순서 호출, `renderer_used=="remotion"`, `video_source=="bga-remotion"`, `video.mp4` 내용이 `video_remotion.mp4` 와 같음, `video_remotion.mp4` 보존 |
| `render_bga(renderer="remotion")` 폴백 | `render_bga_remotion` 이 `RuntimeError("Remotion 미설치")` → `render_bga_loop` 결과 유지, `renderer_used=="ffmpeg"`, `fallback_reason` 에 "미설치" 포함 |
| `remotion_available()=False` | 호출 전에 폴백 (`render_bga_remotion` 미호출) |
| 클립 부족 | `render_bga_loop` 가 `RuntimeError("...2개 미만...")` → 폴백 없이 그대로 전파 |
| `_promote_remotion_output` 백업 | `video_source=="cover"` 인 `video.mp4` → `video_cover_backup.mp4` 생성, 두 번째 호출에서 덮어쓰지 않음; `video_source=="bga"` 면 백업 안 함 |
| API `render` | `renderer:"foo"`→400; `renderer:"remotion"` 이 `render_bga` 에 전달(모킹) |
| API `usage` | `remotion_available`·`default_renderer` 키 존재 |
| 접미사 | `BGA_PROMPT_SUFFIX` 에 `clean lens` 포함, 기존 plan 테스트 통과 |

### 5.2 `tests/test_choonsik_bga_ui.py` (신규, `tests/test_vega_engine.py` 의 프론트 자산 문자열 검사 패턴을 따른다)
- `index.html` 에 ID 존재: `lunaBgaPanel, lunaBgaUsage, btnLunaBgaPlan, btnLunaBgaGenerate, lunaBgaShots, lunaBgaClips, lunaBgaRendererSelect, lunaBgaWaveformCheck, btnLunaBgaRender, lunaBgaRenderNote, lunaVideoSourceBadge`
- 기존 ID 유지: `btnRenderLunaVideo, lunaShortsPanel, btnUploadLunaYt, lunaWithShortsCheck`
- `app.js` 에 `renderLunaBgaPanel`, `/api/luna/bga/plan`, `/api/luna/bga/generate`, `/api/luna/bga/render`, `confirm: true`, `window.confirm`(또는 `confirm(`), `luna_bga_renderer` 문자열 존재
- `node --check static/app.js` 종료 코드 0 (`shutil.which("node")` 없으면 skip)

### 5.3 회귀
`.venv/bin/python -m unittest discover tests` 전체 통과(현재 327개 + 신규). `.env` 없는 환경에서도 통과해야 한다.

---

## 6. 작업 순서 (Antigravity)

1. `git status`/`git branch` → `git checkout main && git pull` → `git checkout -b feat/luna-bga-ui`.
2. `choonsik_bga.py` 추가분 → `py_compile` → `git diff --stat`(기존 함수 본문이 바뀌지 않았는지 `git diff choonsik_bga.py | grep '^-'` 가 접미사 상수 2줄 외에 없어야 함).
3. `app.py` → `py_compile` → `.venv/bin/python -c "import app"`.
4. `index.html` → `app.js` → `node --check static/app.js`.
5. 테스트 작성·실행 → 전체 discover.
6. **수동 확인**(서버 `./run.sh` 또는 `uvicorn app:app --port 8765`): 루나 탭에서 `Bleeding Blueprints` 선택 → 패널에 기존 샷 3개·클립 3개·사용량이 보이는지 → 렌더러 `ffmpeg` 로 [루프 렌더] → 플레이어 갱신·배지 `🎬 BGA (ffmpeg)` → 렌더러 `remotion` 으로 한 번 더 → 약 2분 뒤 배지 `🎬 BGA (Remotion)`, `video.mp4` 가 타이포 포함본으로 바뀜. **[Veo 클립 생성] 버튼은 누르지 않는다**(과금). `window.confirm` 창이 뜨는지까지만 확인하고 취소.
7. 보고: `git diff --stat`, 테스트 전문, 6번 수동 확인 결과(스크린샷 또는 설명), 8장 체크. **커밋·푸시 금지** — Claude Code 가 검증 후 PR.

### 6.1 편집 주의 (재발 방지)
- 기존 파일은 anchor 한 줄 기준 **최소 범위 삽입**만. `app.js` 는 3,600줄이 넘으니 `renderLunaShortsPanel` 정의 뒤, `btnUploadLunaYt` 핸들러 앞처럼 **명확한 anchor** 를 잡고, 편집 직후 `node --check`.
- 편집 직후 `py_compile`/`node --check` + `git diff --stat`. 읽기 도구가 `unsupported mime type` 을 내면 파일 파손 신호 → `git checkout -- <file>`.

---

## 7. Claude Code 검증 절차
1. 변경분을 별도 워크트리로 복사(안티그래비티 트리 불변). 변경 파일이 2장 "포함" 목록과 일치, `luna_engine.py`·`remotion/`·`uploader.py` diff 0.
2. `choonsik_bga.py` 에서 삭제된 줄이 접미사 상수 외에 없는지(`git diff | grep '^-'`).
3. `.env` 없는 워크트리에서 전체 테스트 통과, `node --check`.
4. 디스패처 정적 점검: Remotion 경로 예외 처리에 `2개 미만` 재-raise 가 있는지, `_promote` 가 `video_remotion.mp4` 를 삭제하지 않는지, `render_bga_loop`/`render_bga_remotion` 본문 무변경.
5. 수동: 서버 띄워 패널 렌더·배지·usage 표시, `ffmpeg` 렌더 1회(20초), `remotion` 렌더 1회(2분) 후 `video.mp4` 가 `video_remotion.mp4` 와 동일 바이트인지, 폴백 테스트는 `BGA_RENDERER=remotion` + `node_modules` 를 임시 이름 변경해 `fallback_reason` 이 기록되는지(끝나면 복구).
6. 통과 시 커밋·푸시·PR(`feat(luna): 춘식 BGA UI 패널 + 렌더러 옵션 (C-1c)`), 문제 시 P0/P1/P2 보고.

## 8. 수용 기준
- [ ] 기본값(`BGA_RENDERER` 미설정) 동작이 C-1a 와 동일(ffmpeg)
- [ ] `renderer=remotion` 성공 시 `video.mp4` 가 Remotion 결과로 교체되고 `video_source="bga-remotion"`, 실패 시 ffmpeg 결과 + `fallback_reason`
- [ ] Veo 생성 버튼은 `window.confirm` 승인 없이는 요청을 보내지 않음(테스트는 문자열 검사, 수동 확인으로 보완)
- [ ] 기존 켄번즈 렌더·숏폼·업로드 버튼 동작 불변(ID 유지, 기존 테스트 통과)
- [ ] `luna_engine.py`·`remotion/`·`uploader.py` diff 0
- [ ] 전체 테스트 통과, `node --check` 통과

## 9. 금지 사항
- 테스트·수동 확인에서 `POST /api/luna/bga/generate` 를 `confirm:true` 로 호출(과금). `dry_run:true` 는 허용.
- `render_bga_loop`·`render_bga_remotion`·`generate_bga_clips` 본문, `remotion/` 컴포지션 수정.
- 기존 UI 요소 ID 변경·삭제. `.env`·`node_modules` 커밋.
