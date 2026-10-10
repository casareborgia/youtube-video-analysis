# 루나 BGA C-1b 계획서 — 실생성 1트랙 + Remotion 컴포지터 스파이크

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | Veo 클립 실생성(1트랙) + 루프 렌더 결과 확인 + Remotion 기반 컴포지터 비교 스파이크 |
| 프로젝트 | `유튜브 영상분석실습` (`casareborgia/youtube-video-analysis`) |
| 작성일 | 2026-10-10 |
| 선행 | C-1a 머지 완료 (PR #21, `choonsik_bga.py` + `/api/luna/bga/*`) |
| 검토 레포 | [remotion-dev/remotion](https://github.com/remotion-dev/remotion) v4.0.534 |
| 구현 워커 | C-1b-1 **Claude Code**(과금 호출은 사용자 승인 후) · C-1b-2 **Antigravity** · C-1b-3 Claude Code 검증·비교 |
| 비용 | C-1b-1 에서만 Veo 과금 ≈ $1.9 (720p 무오디오 24초, 2차 출처 단가). C-1b-2 는 0 |

---

## 2. Remotion 검토 결론

### 2.1 무엇인가
React 컴포넌트로 영상을 정의하고 헤드리스 브라우저로 프레임을 렌더하는 도구. `npx create-video@latest` 로 시작, `npx remotion render <entry> <composition> <out>` 로 출력. 현재 4.0.534, 직원 3명 이하·개인은 **무료**(상업 이용 포함), 4명 이상 영리 법인은 Company License. 5.0 에서 라이선스 변경 예고 — 업그레이드 시 재확인. 출처: [README](https://github.com/remotion-dev/remotion), [LICENSE.md](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md).

### 2.2 이 프로젝트에 맞는 부분 / 안 맞는 부분

| 관점 | 평가 |
|---|---|
| **타이포그래피** | ✅ 이 Mac 의 ffmpeg 에 `drawtext` 가 없어 롱폼·숏폼 모두 제목이 빠진 채 렌더되고 있다. Remotion 은 웹폰트(`@remotion/google-fonts`, Noto Sans KR)로 한글 제목·부제를 그린다. **가장 확실한 이득.** |
| **오디오 리액티브** | ✅ `useAudioData` + `visualizeAudio(numberOfSamples, optimizeFor:"speed")` 로 프레임별 스펙트럼 배열을 받아 막대·글로우를 그린다. ffmpeg `showwaves` 보다 디자인 자유도가 높다. 3분 mp3 는 전체를 메모리에 올리므로 `optimizeFor:"speed"` 필수, 필요 시 `useWindowedAudioData`(WAV 전용). 출처: [visualize-audio](https://www.remotion.dev/docs/visualize-audio) |
| **루프** | ✅ `<Loop durationInFrames>` 가 반복을 담당하고 `times` 기본 `Infinity`. 클립 간 크로스페이드는 `<Sequence>` 겹침 + `interpolate` 로 opacity 를 섞는다. 출처: [loop](https://www.remotion.dev/docs/loop) |
| **9:16 재활용** | ✅ 같은 컴포지션에서 `width/height` 만 바꿔 숏폼 변형을 낼 수 있다(C-1c 이후 후보). |
| **렌더 속도** | ⚠️ 공식 "분당 렌더 시간" 수치가 없다. 3분 30fps = 5,400프레임을 브라우저로 그린다. 영상 삽입은 `<OffthreadVideo>`(ffmpeg 프레임 추출)가 안전하지만 문서상 "최적화 안 됨"이고 `@remotion/media` `<Video>` 가 권장. **반드시 실측**해야 한다. 출처: [performance](https://remotion.dev/docs/performance) |
| **툴체인** | ⚠️ Python/FastAPI 프로젝트에 Node 25 + React + 헤드리스 Chrome 이 추가된다(머신에 Node 25.9, npm 11.12, Chrome 설치 확인). 서버에서 `npx remotion render` 를 subprocess 로 부르는 구조가 되며, 설치 용량과 콜드스타트가 늘어난다. |
| **안정성** | ⚠️ ffmpeg 경로는 이미 테스트 283개로 검증돼 있다. Remotion 은 새 실패 지점(브라우저, 폰트 로딩, 메모리)이 생긴다. |

### 2.3 결정
- **ffmpeg xfade 루프(C-1a)를 기본 렌더러로 유지**한다. 실생성 검증(C-1b-1)은 코드 변경 없이 그대로 진행.
- Remotion 은 **"컴포지터 레이어" 스파이크**로만 들인다: 입력은 C-1a 가 만든 `bga/loop_unit.mp4` + 베가 마스터본 + 메타, 출력은 `video_remotion.mp4`(기존 `video.mp4` 를 덮지 않음). 제목 타이포·스펙트럼·페이드를 React 로 그리고, **렌더 시간·화질을 ffmpeg 경로와 나란히 비교**한 뒤 채택 여부를 정한다.
- 채택 기준(3장 C-1b-3): 3분 1080p 렌더가 **10분 이내**이고, 결과가 ffmpeg 버전보다 시각적으로 명백히 나으며, 실패 시 ffmpeg 로 자동 폴백되는 경우에만 `BGA_RENDERER=remotion` 옵션으로 켠다. 기본값은 계속 `ffmpeg`.

---

## 3. 단계

### C-1b-1. Veo 실생성 + ffmpeg 루프 렌더 (Claude Code, 코드 변경 없음)
1. 메인 체크아웃 `.env` 에 `GCP_PROJECT`, `GCP_VIDEO_LOCATION=us-central1` 확인(커밋 금지).
2. 트랙: C-0 실측에 쓴 `luna_1791476313` *Bleeding Blueprints* (커버 톤 검증됨).
3. `POST /api/luna/bga/plan` → 샷 3개 프롬프트·예상 비용을 사용자에게 보여주고 **명시 승인**.
4. `POST /api/luna/bga/generate {confirm:true}` → 클립 3개 → `POST /api/luna/bga/render {with_waveform:true}` → `video.mp4`.
5. 기록(7장): 샷별 소요 시간, 성공/필터 여부, `loop_unit.mp4` 길이, 이음새 체감, 렌더 시간, 실제 과금액(Cloud Billing 반영 후).
6. 결과 영상은 업로드하지 않고 사용자 확인용으로만 둔다(업로드는 사용자 결정).

### C-1b-2. Remotion 컴포지터 스파이크 (Antigravity) — 프롬프트는 `안티그래비티_프롬프트_C1b_Remotion.md`
- 브랜치 `feat/luna-bga-remotion-spike`. 비용 0. Veo·Vertex 호출 금지.
- 산출물:
  - `remotion/` 하위 프로젝트(`package.json` 고정 버전 `4.0.534`, `src/Root.tsx`, `src/LunaBga.tsx`, `src/index.ts`, `tsconfig.json`, `remotion.config.ts`, `public/luna` → `../../data/luna_music` 심볼릭 링크). `node_modules/`·`out/` 은 `.gitignore`.
  - 컴포지션 `LunaBga`(1920×1080, 30fps, 길이는 props 로): 루프 단위 영상(`<Loop>` + `<OffthreadVideo>`), 상단 타이포(제목·부제, Noto Sans KR), 하단 스펙트럼(`visualizeAudio` 64샘플, `optimizeFor:"speed"`), 페이드인 2초/아웃 3초, `<Audio>` 로 베가 마스터본.
  - Python 래퍼 `choonsik_bga.render_bga_remotion(track_data, progress_cb=None, timeout=1800)`: `npx remotion render` subprocess, `--props` JSON, 출력 `video_remotion.mp4`, `track["bga"]["remotion"] = {file,url,elapsed_sec,rendered_at}`; `node_modules` 없으면 `RuntimeError("Remotion 미설치")`.
  - API `POST /api/luna/bga/render-remotion {track_id}` (0 비용).
  - 테스트: 래퍼는 subprocess 모킹으로(Node 없이) 검증; Node 스모크(`npx remotion compositions`)는 `remotion/node_modules` 있을 때만.
  - `choonsik_bga.py` 의 기존 함수·`render_bga_loop` 는 **수정하지 않는다**(추가만).
- 벤치마크: `luna_1791476313` 의 `loop_unit.mp4`(C-1b-1 산출) 로 3분 1080p 렌더 → 소요 시간·CPU·결과 크기 보고. C-1b-1 이 끝나기 전에는 **합성 클립(ffmpeg `color`/`testsrc` 3×8초)** 으로 먼저 돌려 파이프라인을 완성한다.

### C-1b-3. 비교·결정 (Claude Code)
- 같은 트랙으로 `video.mp4`(ffmpeg) vs `video_remotion.mp4` 를 나란히 비교: 렌더 시간, 파일 크기, 타이포·스펙트럼 품질, 루프 이음새, 오디오 싱크.
- 2.3 채택 기준 충족 시 `BGA_RENDERER` 옵션과 폴백을 C-1c 범위에 넣고, 미충족 시 스파이크를 `remotion/` 폴더째 보존만 하고 기본 경로는 ffmpeg 로 확정.

---

## 4. 수용 기준

**C-1b-1**
- [ ] 클립 3개 중 2개 이상 성공, `loop_unit.mp4` ≈ 22초(성공 3개 기준), `video.mp4` 길이 = 음원 길이
- [ ] `bga_usage.json` 오늘 값 = 성공 클립 수, `video_source == "bga"`, `video_cover_backup.mp4` 존재
- [ ] 실제 과금액을 7장에 기록

**C-1b-2**
- [ ] `remotion/` 이 독립 설치·렌더 가능(`npm ci && npx remotion render ...`), 저장소에 `node_modules` 없음
- [ ] 합성 클립으로 1분 렌더 성공, 결과 1920×1080 30fps, 오디오 포함
- [ ] 래퍼·API 가 Node 없이도 임포트·테스트 통과(`RuntimeError` 경로), 기존 283개 테스트 통과
- [ ] `render_bga_loop`·`uploader.py`·`static/` diff 0
- [ ] 3분 렌더 벤치마크 수치 보고

---

## 5. 금지 사항
- C-1b-2 에서 Veo·Vertex·google-flow 호출.
- `video.mp4` 덮어쓰기(Remotion 출력은 `video_remotion.mp4`).
- Remotion 을 기본 렌더러로 바꾸는 것(C-1b-3 결정 전).
- `node_modules`, `out/`, `.env`, GCP 프로젝트 ID 커밋.

## 6. 참고 출처
- Remotion README: https://github.com/remotion-dev/remotion
- License: https://github.com/remotion-dev/remotion/blob/main/LICENSE.md
- `<Loop>`: https://www.remotion.dev/docs/loop
- `visualizeAudio()`: https://www.remotion.dev/docs/visualize-audio
- Performance: https://remotion.dev/docs/performance
- `<OffthreadVideo>`: https://www.remotion.dev/docs/offthreadvideo

## 7. C-1b-1 실측 결과 (작성 예정)

## 8. C-1b-3 비교 결과 (작성 예정)
