# 안티그래비티에게 보낼 프롬프트 — C-1b-2 Remotion 컴포지터 스파이크

아래 블록을 그대로 복사해 안티그래비티에 붙여 넣으면 됩니다.

---

프로젝트 `/Users/leeseungjun/coding/유튜브 영상분석실습` (FastAPI + Python 3.14, `.venv/bin/python`, 테스트 `python -m unittest discover tests`) 에서 **Remotion 컴포지터 스파이크(C-1b-2)** 를 구현해 주세요. 상세 계획은 `작업지시서_Luna_BGA_C1b_실생성_Remotion.md` 3장 C-1b-2 와 4·5장을 따르고, 이 메시지가 그 요약입니다.

## 시작 전
1. `git status` / `git branch` 확인 → `git checkout main && git pull` → `git checkout -b feat/luna-bga-remotion-spike`.
2. `choonsik_bga.py` 를 읽어 `render_bga_loop` 가 만드는 `data/luna_music/<id>/bga/loop_unit.mp4` 와 `track["bga"]` 구조를 파악하세요. **이 함수와 기존 함수들은 수정하지 않습니다(추가만).**
3. Node 25.9 / npm 11.12 / Chrome 이 머신에 있습니다. Remotion 버전은 **4.0.534 로 고정**합니다.

## 만들 것

### A. `remotion/` 하위 프로젝트
- `remotion/package.json`: `remotion`, `@remotion/cli`, `@remotion/media-utils`, `@remotion/google-fonts`, `react`, `react-dom`, `typescript` — 전부 **정확한 버전 고정**(`^` 금지). `scripts`: `"render": "remotion render src/index.ts LunaBga"`, `"compositions": "remotion compositions src/index.ts"`.
- `remotion/tsconfig.json`, `remotion/remotion.config.ts`(`Config.setVideoImageFormat("jpeg")`, `Config.setConcurrency` 는 기본), `remotion/src/index.ts`(`registerRoot`), `remotion/src/Root.tsx`, `remotion/src/LunaBga.tsx`.
- `remotion/public/luna` → `../../data/luna_music` **심볼릭 링크** (`staticFile("luna/<track_id>/...")` 로 접근). 링크 자체는 커밋해도 되지만 `data/` 내용은 커밋되지 않도록 `.gitignore` 를 확인하세요.
- 루트 `.gitignore` 에 `remotion/node_modules/`, `remotion/out/` 추가.

### B. 컴포지션 `LunaBga`
props(JSON, `--props` 로 전달):
```json
{
  "trackId": "luna_1791476313",
  "loopUnit": "luna/luna_1791476313/bga/loop_unit.mp4",
  "loopUnitSeconds": 22.0,
  "audio": "luna/luna_1791476313/audio.mp3",
  "durationSeconds": 180.0,
  "title": "Bleeding Blueprints",
  "subtitle": "빗물에 번진 청사진 · Emotional Piano Solo",
  "accent": "#a5b4fc",
  "spectrum": true
}
```
- `Root.tsx` 의 `<Composition>` 은 `calculateMetadata` 로 `durationInFrames = round(durationSeconds * 30)`, `fps: 30`, `width: 1920`, `height: 1080`.
- 배경: `<Loop durationInFrames={round(loopUnitSeconds*30)}>` 안에 `<OffthreadVideo src={staticFile(loopUnit)} muted />`. 루프 단위 자체가 이미 이음새 처리가 돼 있으니 추가 크로스페이드는 넣지 않습니다.
- 오디오: `<Audio src={staticFile(audio)} />`.
- 스펙트럼(`spectrum` 일 때): `useAudioData(staticFile(audio))` → 데이터 없으면 `null` 반환 가드 → `visualizeAudio({audioData, frame, fps, numberOfSamples: 64, optimizeFor: "speed"})` → 하단 막대 64개(높이 0~180px, `accent` 색, 반투명). 저역이 과도하게 크므로 `Math.pow(v, 0.6)` 정도로 눌러 주세요.
- 타이포: `@remotion/google-fonts/NotoSansKR` 로드. 상단 중앙에 `AGENT LUNA`(작게, 흰색 90%)와 `title`(크게, accent), 아래 `subtitle`(작게, 회색). 글자 그림자로 가독성 확보.
- 전체 페이드: `interpolate(frame, [0, 60], [0, 1])` 인, 마지막 90프레임 아웃. `extrapolateLeft/Right: "clamp"`.

### C. Python 래퍼 — `choonsik_bga.py` 끝에 추가
```python
REMOTION_DIR = os.path.join(luna_engine.BASE_DIR, "remotion")

def render_bga_remotion(track_data, progress_cb=None, timeout=1800, runner=subprocess.run) -> dict:
```
- 전제 검사(순서대로): `remotion/node_modules` 없음 → `RuntimeError("Remotion 미설치: cd remotion && npm ci")`; `bga.loop_unit_file` 없음 → `RuntimeError("loop_unit.mp4 없음 — render_bga_loop 를 먼저 실행")`; 오디오 `track["audio_file"]` 없음 → `FileNotFoundError`.
- props 는 B 의 형식으로 만들고(제목은 `track["title"]` 을 `(` 기준으로 영문/한글 분리, 부제는 `한글 부제 · genre`), `loopUnitSeconds` 는 `producer.audio_duration(loop_unit)`, `durationSeconds` 는 음원 길이.
- 실행: `runner(["npx", "remotion", "render", "src/index.ts", "LunaBga", <out>, "--props", json.dumps(props), "--log", "error"], cwd=REMOTION_DIR, timeout=timeout, capture_output=True, text=True)`. 출력 파일은 `data/luna_music/<id>/video_remotion.mp4`. **`video.mp4` 를 절대 덮지 않습니다.**
- 성공 시 `track["bga"]["remotion"] = {"file", "url", "elapsed_sec", "rendered_at"}` 저장(`luna_engine.save_track`). 실패 시 stderr 마지막 300자를 담은 `RuntimeError`.
- `runner` 인자는 테스트 주입용입니다.

### D. API — `app.py`, `/api/luna/bga/usage` 아래
`POST /api/luna/bga/render-remotion {track_id}` → 404(트랙 없음) / 503(`"미설치"` 포함 RuntimeError) / 400(`"loop_unit"` 포함) / 500(그 외). 성공 시 갱신된 track 반환.

### E. 테스트 — `tests/test_choonsik_bga_remotion.py` (신규)
Node 없이 통과해야 합니다.
- `node_modules` 없음 → `RuntimeError` 에 "미설치" 포함, `runner` 미호출.
- `node_modules` 가짜 디렉터리 + `loop_unit` 없음 → "loop_unit" 포함 `RuntimeError`.
- 정상: 가짜 `runner` 가 출력 파일을 만들고 `returncode=0` → `bga.remotion.file` 존재, props JSON 에 `trackId`/`durationSeconds`/`loopUnitSeconds` 포함, `cwd` 가 `remotion/`, 출력 경로가 `video_remotion.mp4`.
- `returncode=1` → `RuntimeError` 에 stderr 일부 포함.
- API: 404 / 503 / 200 경로.
- Node 스모크(선택): `remotion/node_modules` 가 실제로 있을 때만 `npx remotion compositions src/index.ts` 가 `LunaBga` 를 출력하는지(`skipUnless`).

### F. 합성 클립으로 end-to-end 1회
`data/luna_music/` 에 **임시 트랙 폴더** `luna_remotion_smoke/` 를 만들어: ffmpeg `testsrc2=s=1280x720:d=8` 로 클립 3개 → 기존 `render_bga_loop` 로 `loop_unit.mp4` 생성(음원은 `sine` 60초) → `render_bga_remotion` 실행 → `video_remotion.mp4` 가 1920×1080, 30fps, 약 60초, 오디오 포함인지 `ffprobe` 로 확인. 소요 시간을 기록하고 **끝나면 임시 폴더를 삭제**합니다.

### G. 벤치마크 보고
F 의 1분 렌더 시간과, 가능하면 `npx remotion benchmark` 결과(최적 concurrency)를 보고에 포함하세요. 3분 실트랙 벤치마크는 C-1b-1(Claude Code)이 `luna_1791476313/bga/loop_unit.mp4` 를 만든 뒤 제가 돌립니다 — 그 폴더가 이미 있으면 그걸로 돌려도 됩니다.

## 하지 말 것
- Veo / Vertex / `google-flow` MCP 호출. `GCP_*` 환경변수 사용.
- `render_bga_loop`, `generate_bga_clips`, `plan_bga_shots`, `uploader.py`, `vega_engine.py`, `static/` 수정.
- `video.mp4` 덮어쓰기. `node_modules`·`out/`·`.env` 커밋. 버전 `^`/`~` 사용.
- 기존 파일 편집 시 수십 줄 범위 치환. 편집 직후 `python3 -m py_compile <file>` 와 `git diff --stat` 으로 의도한 줄만 바뀌었는지 확인. 파일 읽기 도구가 `unsupported mime type` 을 내면 파일이 깨진 신호이니 `git checkout -- <file>` 로 즉시 복구.

## 완료 보고 형식
1. `git diff --stat` (예상: `.gitignore`, `app.py`, `choonsik_bga.py` 추가분, `remotion/` 신규, `tests/test_choonsik_bga_remotion.py`)
2. `.venv/bin/python -m unittest discover tests` 전문 (실패 0)
3. F 의 ffprobe 출력과 렌더 소요 시간, `npm ci` 설치 용량(`du -sh remotion/node_modules`)
4. 4장 C-1b-2 수용 기준 체크
5. **커밋·푸시는 하지 않고** 보고만 합니다. Claude Code 가 검증 후 PR 을 올립니다.
