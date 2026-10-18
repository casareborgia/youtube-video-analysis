# 쇼츠(9:16) 생성 자동화 작업계획서 — 유튜브 쇼츠 · 인스타 릴스

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | 주제 → 9:16 쇼츠 자동 생성 → 유튜브 쇼츠 · 인스타그램 릴스 발행 파이프라인 |
| 프로젝트 | `유튜브 영상분석실습` (`casareborgia/youtube-video-analysis`) |
| 작성일 | 2026-10-19 |
| 참고 레포 | [casareborgia/remotion](https://github.com/casareborgia/remotion) (remotion-dev 포크, 2026-10-18 시점) · [casareborgia/hyperframes](https://github.com/casareborgia/hyperframes) (heygen-com 포크, 2026-10-18 시점) · [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage) (2026-10-16 시점) |
| 선행 | 루나 숏폼 Phase B 머지(`luna_engine.render_luna_shorts_video`), Remotion 스파이크 C-1b/C-1c 머지(`remotion/` + `choonsik_bga.render_bga_remotion`, `BGA_RENDERER` 옵션) |
| 1차 목표 플랫폼 | **유튜브 쇼츠 우선**(기존 `uploader.py` 재사용). 인스타그램 릴스는 유튜브 파이프라인 안정화 후 2차 |
| 대상 채널 | **루나(Luna Maestro)와 별개의 신규 채널**(사용자 보유 비즈니스 계정). 쇼츠 발행은 항상 채널을 명시 지정하며 루나 채널은 가드로 차단 |
| 범위 밖 | 틱톡 발행, 실사 토킹헤드 자막(얼굴 없는 채널), Veo 세로 영상(비용 승인 후 별도) |

이 문서는 참고 레포 3개를 실제로 클론해 읽고(2장), 현재 시스템에서 그대로 쓸 수 있는 자산을 대조한 뒤(3장), **무엇을 가져오고 무엇을 가져오지 않을지**(4장)와 단계별 작업(7장)을 확정한 계획서다. 코드 변경은 아직 없다.

---

## 2. 참고 레포 검토 결론

### 2.1 Remotion (`casareborgia/remotion`) — 이미 쓰고 있는 컴포지터, 자막·세로 템플릿만 추가로 가져온다

- 포크는 업스트림 `remotion-dev/remotion` 최신과 동일(2026-10-18 머지 커밋). 프로젝트 `remotion/`은 **4.0.534** 고정이며 메인 체크아웃에 `node_modules` 설치돼 있다. 라이선스는 개인·3인 이하 무료(5.0 변경 예고 — 업그레이드 시 재확인).
- 쇼츠에 바로 쓸 수 있는 패키지·템플릿:

| 패키지 | 용도 | 비고 |
|---|---|---|
| `@remotion/captions` | `Caption{text,startMs,endMs}` 표준 타입, `parseSrt`, **`createTikTokStyleCaptions`**(단어 토큰을 페이지로 묶음) | 단어 단위 하이라이트 자막의 데이터 모델로 채택 |
| `packages/template-tiktok` | 9:16 1080×1920, 페이지당 단어 하이라이트, `fitText` 로 폭 맞춤, 하단 350px 여백 | `ShortsScene` 컴포지션의 자막 레이어 설계 참고 |
| `packages/template-audiogram` | 커버 + 파형 + 자막 (오디오 → 영상) | 루나 뮤직 쇼츠 2.0 참고 |
| `@remotion/transitions` | 씬 간 전환(`<TransitionSeries>`) | 기존 ffmpeg xfade 대체 |
| `@remotion/install-whisper-cpp` | 단어 타임스탬프 ASR | Qwen 보이스클론처럼 타이밍이 없는 음성에만 폴백으로 사용 |
| `@remotion/google-fonts` NotoSansKR | 한글 타이포 | `LunaBga.tsx` 에서 이미 사용 중 |

- 이 Mac 의 Homebrew ffmpeg 에는 `drawtext` 가 없어 ffmpeg 경로는 imageio 번들로 대체되고 있다(C-1b 기록). **텍스트가 핵심인 쇼츠(훅 문구·자막)는 Remotion 이 ffmpeg 보다 확실히 유리**하다 — C-1b 결론과 같다.

### 2.2 HyperFrames (`casareborgia/hyperframes`) — 런타임은 들이지 않고, 설계 지식만 가져온다

- HeyGen 의 HTML → MP4 렌더러(Apache-2.0, Node 22+). 포크는 업스트림 최신(2026-10-18). 21개 에이전트 스킬이 핵심 자산이다.
- 두 번째 렌더 런타임으로 추가하지 않는 이유: (a) Remotion 이 이미 설치·래핑·테스트돼 있고, (b) OpenMontage 조차 "클립 팩토리는 Remotion 단어 자막 번인에 의존하므로 HyperFrames 금지" 로 못 박았으며(`skills/pipelines/clip-factory/compose-director.md`), (c) Python 프로젝트에 Node 툴체인을 두 벌 두는 비용이 크다.
- 가져올 것(지식·절차):

| 스킬 | 가져오는 것 |
|---|---|
| `music-to-video` | **비트 그리드 분석기**(`scripts/analyze-beatgrid.py`, librosa 기반: 에너지 구간·온셋·hard_stop·key_moment·BPM) 의 산출 구조. 루나 뮤직 쇼츠에서 **비트에 맞춰 컷·줌 펄스**를 넣는 S-5 의 설계 근거. 코드는 Apache-2.0 이라 참고 구현 가능하나 프로젝트에는 작은 Python 분석기를 새로 쓴다 |
| `faceless-explainer` | 얼굴 없는 설명 쇼츠의 브리프 → 스토리보드 → 프레임 → 렌더 승인 게이트 순서 |
| `hyperframes-creative` | 안전 영역·타이포 프리셋 개념 |

- 가져오지 않을 것: `embedded-captions`(토킹헤드 전용 매트 합성 — 이 채널에 얼굴 영상이 없음), `hyperframes` CLI/스튜디오 전부.

### 2.3 OpenMontage (`calesthio/OpenMontage`) — 파이프라인 규격과 플랫폼 스펙을 가져오되 코드는 복사하지 않는다

- "에이전트가 오케스트레이터, Python 은 도구" 구조. **AGPL-3.0** 이므로 코드 복사·벤더링은 하지 않고(이 프로젝트는 MIT), 아래 규격을 **재작성**한다.
- 가져올 것:

| 원천 | 가져오는 것 | 반영 위치 |
|---|---|---|
| `lib/media_profiles.py` | 플랫폼 프로필: YouTube Shorts 1080×1920 30fps CRF20 ≤60초, Instagram Reels ≤90초·≤250MB, caption srt | `shorts_engine.PLATFORM_PROFILES` (5장) |
| `skills/creative/short-form.md` | 안전 영역(공통 900×1400 중앙, 하단 300px 데드존), 훅 0.5초 내 텍스트, 1~3초마다 시각 변화, 자막 42px+ 굵게 2줄, 음성 -14 LUFS / -1 dBTP, 길이별 대본 글자 수 | 쇼츠 컨셉 팩 규칙(`concept_packs.py`) + Remotion 레이아웃 상수 |
| `skills/core/subtitle-sync.md` | 세로 자막은 큐당 3~4단어, 줄당 20자 이하, 최소 0.5초 노출 | 자막 페이지 생성 규칙(한글은 줄당 12~14자로 조정) |
| `pipeline_defs/clip-factory.yaml` | 단계 분리(idea → script → scene_plan → assets → edit → compose → publish), 단계별 **사람 승인 게이트**, 렌더 결과를 ffprobe 로 검증하는 `render_report`, 플랫폼별 export 디렉터리 | `shorts_engine` 의 잡 상태 머신과 QC(7장 S-2) |
| `tools/video/remotion_caption_burn.py` | 단어 자막 → Remotion props → 렌더, Remotion 없으면 ffmpeg `subtitles` 폴백 | `shorts_engine.render()` 의 폴백 구조(기존 `render_bga` 의 `BGA_RENDERER` 패턴과 동일) |
| `tools/publishers/export_bundle.py` | 네트워크 발행 전에 **플랫폼별 폴더 + 메타데이터 JSON + 캡션 txt** 로 묶는 단계 | S-3 export 번들 — 릴스 API 연동 전에도 수동 업로드 가능 |
| `remotion-composer/src/components/CaptionOverlay.tsx` | `WordCaption{word,startMs,endMs,pageBreakAfter}` + CJK 용 `wordSeparator=""` | 한글 자막 페이지 분리 규칙(어절 단위, 절 경계에서 강제 개행) |

- 가져오지 않을 것: Backlot 보드, 25개 영상 생성 프로바이더, 3D/Blender, 스톡 코퍼스 검색. 쇼츠 1차 범위에 필요 없다.

---

## 3. 현재 시스템에서 그대로 쓰는 자산

| 자산 | 위치 | 쇼츠에서의 역할 |
|---|---|---|
| 9:16 씬 기획 | `prompt_generator.py:252` (`is_vertical` 구도 규칙), `scene_store.build_plan(aspect_ratio)` | 쇼츠 스토리보드 입력. 씬 수·초 수만 쇼츠 규격으로 제한 |
| 9:16 해상도 맵·합성 | `producer.RESOLUTIONS["9:16"]`, `producer.build_video` (9:16 자막 16자·폰트 축소 분기 있음) | **ffmpeg 폴백 렌더러** |
| Gemini 씬 이미지 | `producer.generate_images` (나노바나나, 9:16 가능) | 씬 비주얼(스틸 + 켄번즈) |
| TTS | `tts_service.py` edge-tts(무료) / Qwen3-TTS(클론) | 나레이션. edge-tts 는 `WordBoundary` 이벤트로 **단어 타임스탬프를 공짜로** 얻을 수 있음(현재는 `comm.save()` 만 써서 버리고 있음) |
| 루나 음원·베가 마스터 | `luna_engine`, `vega_engine` (-14 LUFS) | BGM, 뮤직 쇼츠 원천. 트랙 73개 보유 |
| 루나 숏폼 Phase B | `luna_engine.extract_audio_highlight` / `render_luna_shorts_video` / `upload_luna_to_youtube(with_shorts)` | 뮤직 쇼츠 1.0 — S-5 에서 Remotion 으로 교체 |
| 시그니처 BGA·썸네일 | `data/bga_assets/`, `scripts/generate_signature_bga_assets.py` | 뮤직 쇼츠 배경 루프 |
| Remotion 프로젝트 | `remotion/` (`LunaBga` 1920×1080), `choonsik_bga.render_bga_remotion` 래퍼, `tests/test_choonsik_bga_remotion.py` (subprocess 모킹 패턴) | `ShortsScene` 컴포지션을 같은 프로젝트에 추가 |
| 유튜브 업로드 | `uploader.upload_video(publish_at, pinned_comment, playlist_id, thumbnail_path)` | 쇼츠 업로드(9:16·≤60초면 자동으로 쇼츠 분류) |
| 메타 Graph 컨테이너 패턴 | `threads_client.create_media_container → publish_media_container` | 인스타그램 릴스 API 가 **완전히 같은 2단계 구조** — 클라이언트 설계 복제 |
| 예약·드라이런·승인 모달 | `scheduler_service.py`(SQLite 리스), `socialConfirmModal` | 릴스 발행의 안전장치 재사용 |
| 레드라인/첫 프레임 JSON | `prompt_generator.get_fixed_redline_*` | 쇼츠 썸네일(세로) 프롬프트 |

---

## 4. 아키텍처 결정

1. **컴포지터는 Remotion 하나, ffmpeg 는 폴백.** `remotion/src/ShortsScene.tsx` (1080×1920, 30fps) 를 추가하고, Python `shorts_engine.render()` 가 `npx remotion render` 를 subprocess 로 부른다(`render_bga_remotion` 과 동일 구조, `SHORTS_RENDERER=remotion|ffmpeg`, 기본 `remotion`, 미설치·실패 시 `producer.build_video` 9:16 폴백). HyperFrames 런타임은 넣지 않는다.
2. **오케스트레이션은 Python(`shorts_engine.py`)**, 승인 게이트는 웹 UI. OpenMontage 처럼 LLM 에이전트가 파이프라인을 모는 구조는 쓰지 않는다 — 이 프로젝트는 로컬 LLM 이 JSON 을 반환하고 코드가 진행하는 구조이고, 그 방식이 283개 테스트로 검증돼 있다.
3. **자막 타이밍 원천 우선순위**: ① edge-tts `WordBoundary`(정확·무료) → ② Qwen 음성은 글자 수 비례 분배(근사) → ③ 옵션으로 whisper.cpp(`@remotion/install-whisper-cpp`) 정밀 타이밍. 쇼츠 기본 성우는 edge-tts 로 두고, 클론 보이스를 고르면 ②·③ 로 내려간다.
4. **쇼츠 포맷 3종**(비용 0 또는 이미지 비용만):

| 포맷 | 입력 | 비주얼 | 비용 |
|---|---|---|---|
| F1 **정보형 씬 쇼츠** | 주제 (3단계 씬 기획 9:16, 3~6씬 × 5~8초) | Gemini 스틸 + 켄번즈/줌 펄스 + 상단 훅 + 단어 자막 + 엔드 태그 | Gemini 이미지 3~7장/편 |
| F2 **루나 뮤직 쇼츠 2.0** | 루나 트랙 (하이라이트 45~58초) | 시그니처 BGA 루프 또는 커버 블러 + 가사 오버레이 + 스펙트럼 + 비트 줌 펄스 | 0 |
| F3 **롱폼 리컷** *(후순위)* | 기존 `final.mp4` + 씬 기획서 타임코드 | 씬 1~2개 추출 → 16:9 → 9:16 센터크롭/블러필 + 자막 재번인 | 0 |

5. **발행은 플랫폼 어댑터 2개.** 유튜브는 기존 `uploader`, 인스타그램은 신규 `instagram_client.py`(Graph API). 두 어댑터 앞에 공통 **export 번들**(플랫폼별 폴더 + `metadata.json` + `caption.txt`) 을 두어 API 가 막혀도 수동 업로드가 가능하게 한다.
6. **인스타그램 릴스의 구조적 제약**: Graph API 는 `video_url` 을 **메타 서버가 받아갈 수 있는 공개 URL** 로 요구한다. 이 서버는 `127.0.0.1` 바인딩이라 직접 못 준다. 선택지는 9장 결정 사항 ①.

---

## 5. 산출물 규격

### 5.1 플랫폼 프로필 (`shorts_engine.PLATFORM_PROFILES`)

| 프로필 | 해상도 | fps | 코덱 | CRF | 길이 상한 | 용량 상한 | 비고 |
|---|---|---|---|---|---|---|---|
| `youtube_shorts` | 1080×1920 | 30 | H.264 High + AAC | 20 | **60초**(파이프라인 상한; 유튜브 자체는 더 허용) | — | 9:16·≤60초면 쇼츠 자동 분류, 제목 `#Shorts` 선택 |
| `instagram_reels` | 1080×1920 | 30 | H.264 + AAC | 20 | 90초(피드 노출 권장) | 250MB | 공개 URL 필요, 일일 발행 한도 존재 — 구현 전 문서 재확인 |

비트레이트 8~15Mbps VBR, `yuv420p`, 오디오 48kHz. 동일 렌더 1본을 두 플랫폼에 공용(길이는 60초 이하로 맞춤).

### 5.2 레이아웃 안전 영역 (1080×1920)

- 공통 안전 영역 **900×1400 중앙**. 상단 120px·하단 300px·우측 96px 에는 텍스트 금지(플랫폼 UI 가 덮음).
- 훅 문구: 상단 안전 영역 안(y ≈ 200~420px), 3~5어절, 등장 0.3초 이내, 노출 2~4초.
- 자막: 하단 350px 위(y ≈ 1250~1500px), 2줄 이하, 줄당 한글 12~14자, 굵은 NotoSansKR 64~80px, 검정 스트로크 또는 반투명 박스, **현재 단어 하이라이트 색**(컨셉 팩 액센트).
- 엔드 태그: 마지막 2초, 채널명 + CTA(구독/풀버전 링크 안내).

### 5.3 오디오

- 나레이션 피크 -12~-14dB, BGM -22~-26dB(나레이션 구간 덕킹 — 기존 producer 덕킹 재사용), 최종 **-14 LUFS / -1 dBTP**(베가 분석 함수로 측정만 하고 초과 시 `loudnorm` 1패스).
- 음성은 0.2초 이내 시작(무음 인트로 금지), BGM 즉시 시작.

### 5.4 잡 데이터 모델 (`data/shorts/<shorts_id>/job.json`)

```json
{
  "shorts_id": "shorts_1760000000_주제슬러그",
  "format": "scene | music | recut",
  "source": {"plan_id": "...", "track_id": null},
  "status": "planned | assets | rendered | qc_passed | exported | published | failed",
  "storyboard": {
    "hook_text": "...", "scenes": [{"scene_num": 1, "seconds": 6.0, "narration": "...", "image": "...", "motion": "zoom_in"}],
    "end_tag": {"text": "...", "seconds": 2.0}
  },
  "captions": [{"text": "단어", "startMs": 0, "endMs": 320}],
  "caption_source": "edge_tts | proportional | whisper",
  "audio": {"narration": "...", "bgm": "...", "lufs": -14.1, "true_peak": -1.0},
  "render": {"renderer_used": "remotion | ffmpeg", "file": "final_9x16.mp4", "elapsed_sec": 0, "probe": {"width": 1080, "height": 1920, "duration": 42.3, "fps": 30, "size_bytes": 0}},
  "qc": {"passed": true, "checks": ["duration<=60", "1080x1920", "audio_present", "first_frame_not_black", "lufs_within_1db"]},
  "metadata": {"youtube": {"title": "", "description": "", "tags": [], "pinned_comment": ""}, "instagram": {"caption": "", "hashtags": []}},
  "publish": {"youtube": {"video_id": null, "publish_at": null}, "instagram": {"media_id": null, "permalink": null}}
}
```

---

## 6. 착수 순서

| 순서 | 단계 | 브랜치 | 비용 | 의존 |
|---|---|---|---|---|
| 1 | S-1 Remotion `ShortsScene` 컴포지션 + Python 래퍼 | `feat/shorts-remotion-composition` | 0 | 없음 |
| 2 | S-2 `shorts_engine` 파이프라인(F1 정보형) + API + UI 패널 | `feat/shorts-pipeline` | Gemini 이미지 | S-1 |
| 3 | S-3 유튜브 쇼츠 발행 + export 번들 | `feat/shorts-publish-youtube` | 유튜브 할당량 1,600/편 | S-2 |
| 4 | S-6 자동화 루틴(트렌드 → 쇼츠 → 예약) | `feat/shorts-autopilot` | 이미지 + 할당량 | S-3 |
| 5 | S-4 인스타그램 릴스 발행 *(2차)* | `feat/instagram-reels-publish` | 호스팅 방식에 따라 | S-3, 결정 ① |
| 6 | S-5 루나 뮤직 쇼츠 2.0(F2) *(루나 채널용, 별도 판단)* | `feat/luna-shorts-remotion` | 0 | S-1 |
| 7 | S-7 롱폼 리컷(F3) *(선택)* | `feat/shorts-recut` | 0 | S-1 |

2026-10-19 사용자 결정: **유튜브부터 진행**하고, 쇼츠는 루나와 별개의 신규 채널에서 운영한다. 따라서 S-1 → S-2 → S-3 → S-6 이 1차 경로이고, S-4(릴스)·S-5(루나 뮤직 쇼츠)는 그 뒤로 미룬다. 각 단계는 PR 1개, 머지 전 다음 단계 시작 금지(기존 규칙).

---

## 7. 단계별 작업 지시

### S-1. Remotion `ShortsScene` 컴포지션 + Python 래퍼 (`feat/shorts-remotion-composition`)

1. `remotion/src/ShortsScene.tsx` 신규, `Root.tsx` 에 `Composition id="ShortsScene"` 등록(1080×1920, 30fps, `calculateMetadata` 로 길이 = props 합).
   - props: `{scenes[], hookText, endTag, captions[], captionStyle, narrationAudio, bgmAudio, bgmVolume, accent, brand}`.
   - 레이어(아래→위): 씬 이미지(`<Img>` + `interpolate` 줌/팬, `motion: zoom_in|zoom_out|pan_left|pan_right`) → 씬 전환(`@remotion/transitions` fade 0.4초) → 자막(`createTikTokStyleCaptions` 로 페이지화, 현재 단어 하이라이트, `fitText` 폭 맞춤) → 훅 텍스트(spring 등장) → 엔드 태그 → `<Audio>` 2개(나레이션, BGM `volume` 콜백으로 덕킹).
   - 한글 자막: `@remotion/captions` 의 `Caption[]` 은 공백 기준으로 단어를 나누므로 Python 쪽에서 **어절 단위 토큰 + 절 경계 `pageBreakAfter`** 를 미리 만들어 보낸다(OpenMontage `CaptionOverlay` 의 CJK 처리 방식).
   - 안전 영역 상수는 5.2 그대로. 폰트는 `@remotion/google-fonts/NotoSansKR` 700.
2. `remotion/package.json` 에 `@remotion/captions`, `@remotion/transitions`, `@remotion/layout-utils` 를 **4.0.534 로 고정** 추가. `node_modules`·`out/` 은 계속 `.gitignore`.
3. `shorts_engine.py` 신규 — 이 단계에서는 렌더 함수만:
   - `render_shorts_remotion(job, progress_cb=None, timeout=900, runner=subprocess.run)`: props JSON → `npx remotion render src/index.ts ShortsScene <out> --props` → `job["render"]` 기록. `node_modules` 없으면 `RuntimeError("Remotion 미설치")`.
   - `render_shorts_ffmpeg(job)`: `producer.build_video` 9:16 경로 호출(자막은 ffmpeg `subtitles`/drawtext 폴백, 훅 텍스트는 생략될 수 있음을 `warnings` 에 기록).
   - `render_shorts(job, renderer=None)`: `SHORTS_RENDERER` 읽어 분기, Remotion 실패 시 ffmpeg 폴백 + `renderer_used` 기록(`choonsik_bga.render_bga` 와 동일 패턴).
   - `probe_video(path)`: ffprobe 로 width/height/duration/fps/size/audio 유무.
4. 테스트 `tests/test_shorts_remotion.py`: subprocess 모킹으로 props 구성·폴백·미설치 경로 검증(Node 없이 통과). `remotion/node_modules` 있을 때만 `npx remotion compositions` 스모크.
5. 수용 기준
   - [x] 합성 입력(색 이미지 3장 + 사인파 나레이션 12초 + 사인파 BGM)으로 1080×1920 30fps 렌더 성공, 자막(어절 하이라이트)·훅·엔드 태그 프레임 확인
   - [x] 렌더 시간 실측(2026-10-19, M시리즈 Mac): **20초 쇼츠 → Remotion 11.3초**, ffmpeg 폴백 1.2초. 30초 기준 약 17초 예상
   - [x] `LunaBga`·`choonsik_bga.py`·`uploader.py` diff 0, 기존 테스트 전부 통과(393개)

6. 구현 메모(2026-10-19, `feat/shorts-remotion-composition`)
   - 의존성은 `@remotion/captions` 4.0.534 만 명시 추가했다. `@remotion/transitions`·`layout-utils` 는 크로스페이드(Sequence 겹침 + opacity)와 글자 수 기반 폰트 크기로 대체해 넣지 않았다.
   - ffmpeg 폴백은 `producer.build_video` 를 호출하지 않고 `shorts_engine.render_shorts_ffmpeg` 로 독립 구현했다(켄번즈 → xfade → 나레이션·BGM 사이드체인 덕킹 → libass SRT). 씬 시작 시각은 Remotion 과 동일한 절대 시각을 유지한다. 훅·엔드 태그·어절 하이라이트는 생략되고 `warnings` 에 기록된다.
   - 자막 토큰 규약: 새 어절은 `text` 앞에 공백 1칸, 문장 끝 `pageBreakAfter: true`. 단어 타이밍이 없을 때는 `proportional_captions` 로 글자 수 비례 분배.
   - 잡 폴더 밖의 오디오·이미지는 `data/shorts/<id>/` 안으로 복사한 뒤 `remotion/public/shorts` 심볼릭 링크로 읽는다.

### S-2. `shorts_engine` 파이프라인 F1 + API + UI (`feat/shorts-pipeline`)

1. **쇼츠 컨셉 팩** `concept_packs.py` 에 `shorts_info`(정보형) 추가: 서사 골격 `훅(1씬, ≤2초 텍스트) → 핵심 1 → 핵심 2 → 반전/근거 → CTA`, 씬당 5~8초, 총 **30~58초**, 길이별 글자 수(30초 ≈ 70~80어절, 60초 ≈ 125~150어절; 한국어는 초당 5.2자 기준으로 환산), 훅 문구 3~5어절 별도 필드, 엔드 태그 문구. 기존 `prompt_generator` 의 9:16 분기(`is_vertical`) 를 그대로 타되 `scene_count` 상한 6.
2. `shorts_engine.build_job_from_plan(plan_id, platform_targets)`: 씬 기획서(9:16) → `job.json`(5.4). 씬 길이 합이 60초를 넘으면 마지막 씬부터 줄이고 경고.
3. **단어 타이밍 TTS**: `tts_service.synthesize_edge_tts_single` 에 `with_word_boundaries=True` 옵션 추가 — `comm.stream()` 으로 `WordBoundary` 이벤트(offset/duration, 100ns 단위) 를 모아 `captions[]` 반환. 기존 호출부 동작 불변. Qwen 경로는 `proportional_captions(text, audio_duration)` 로 글자 수 비례 분배. 선택 옵션 `SHORTS_CAPTION_ASR=whisper` 면 `@remotion/install-whisper-cpp` 로 재정렬(1차 범위 밖, 훅만 남김).
4. 이미지: `producer.generate_images(plan, slots)` 9:16 호출 재사용. 편당 이미지 수 상한 `SHORTS_MAX_IMAGES_PER_JOB`(기본 7), 일일 상한 `SHORTS_MAX_IMAGES_PER_DAY`(기본 40, `data/shorts_usage.json` — `bga_usage.json` 과 같은 방식).
5. 오디오: 씬별 나레이션 이어붙이기(기존 `merge_audio_files`), BGM 은 루나 트랙 중 `vocal_mode=instrumental` 인 것에서 선택(없으면 무음). `vega_engine` 분석으로 LUFS 측정, 벗어나면 `loudnorm` 1패스.
6. QC(`qc_job`): duration ≤ 60, 1080×1920, 오디오 스트림 존재, 첫 프레임 평균 밝기 > 임계(블랙 오프닝 금지), LUFS ±1dB. 실패 항목은 `job["qc"]["checks"]` 에 남기고 상태 `failed`.
7. API(`app.py`): `POST /api/shorts/jobs {plan_id, platforms[]}` → 생성, `POST /api/shorts/jobs/{id}/build` (BackgroundTasks, 진행률 이미지 40% / 음성 20% / 렌더 40%), `GET /api/shorts/jobs/{id}`, `GET /api/shorts/jobs`, `DELETE`. 모든 경로에 `_safe()` 식 ID 검증.
8. UI: 4단계 탭 하단에 **쇼츠 패널** — 기획서 선택(9:16 만 노출) → `[쇼츠 잡 생성]` → 스토리보드 카드(훅/씬/엔드 태그 편집 가능) → `[빌드]` 진행률 → 세로 미리보기 플레이어 + QC 결과 배지. 이미지 생성 전 **예상 비용·장수 확인 모달**(기존 BGA 승인 모달 재사용).
9. 테스트 `tests/test_shorts_engine.py`: 잡 생성·60초 컷·단어 타이밍 파싱(edge-tts 모킹)·비례 분배·QC 판정·일일 상한. ffmpeg 있으면 ffprobe 검증.
10. 수용 기준
    - [ ] 주제 1개 → 외부 API 는 Gemini 이미지만 호출해 쇼츠 1편 완성(LLM 은 로컬)
    - [ ] edge-tts 성우로 만든 편은 `caption_source=edge_tts`, 자막이 발화와 ±150ms 안에서 맞음(샘플 5단어 수동 확인)
    - [ ] QC 통과본만 `qc_passed`, 실패 사유 UI 표시
    - [ ] 기존 4단계 롱폼 빌드 흐름 diff 0

### S-3. 유튜브 쇼츠 발행 + export 번들 (`feat/shorts-publish-youtube`)

1. `shorts_engine.build_metadata(job)`: 로컬 LLM 으로 제목 후보 3(≤100자, 선택적 `#Shorts`), 설명(첫 줄 훅 + 해시태그 3~5), 태그(≤30), 고정 댓글(인게이지먼트 질문 — 기존 `pinned_comment` 규칙), 인스타 캡션(≤2,200자, 해시태그 ≤30). 파싱 실패 시 템플릿 폴백 + `is_fallback`.
2. `export_bundle(job)`: `data/shorts/<id>/export/{youtube,instagram}/` 에 `final_9x16.mp4`(하드링크), `metadata.json`, `caption.txt`, `thumbnail.jpg`(세로 썸네일 — 첫 프레임 또는 레드라인 이미지). 상태 `exported`.
3. `publish_youtube(job, channel_id, privacy, publish_at, playlist_id)`: `uploader.upload_video` 호출(category 27 또는 기획서 값, `pinned_comment`, `thumbnail_path`). 결과 `job["publish"]["youtube"]`. 할당량 경고(1,600 유닛/편) UI 표시.
   - **채널 가드**: `channel_id` 는 필수 인자이며 `uploader.get_active_channel_id()` 로 암묵 대체하지 않는다. 기본값은 `SHORTS_YOUTUBE_CHANNEL_ID`(.env) 이고, 값이 `LUNA_YOUTUBE_CHANNEL_ID`(루나 채널) 와 같으면 발행을 거부한다. 현재 연결된 채널은 「영상에이전트」와 「Luna Maestro」 두 개이며, 신규 비즈니스 채널은 S-3 착수 시 `[채널 추가 연결]` 로 연결한다.
4. 예약: `publish_at` 지정 시 기존 규칙대로 `private` + `publishAt`. 롱폼이 있는 주제면 숏폼 설명 첫 줄에 롱폼 링크(루나 Phase B 의 플레이스홀더 치환 재사용).
5. API `POST /api/shorts/jobs/{id}/export`, `POST /api/shorts/jobs/{id}/publish/youtube`. UI 에 채널 선택·공개 범위·예약 시각·재생목록.
6. 테스트: `uploader.upload_video` 모킹 — 호출 인자(9:16 파일, 제목 길이, 고정 댓글), export 폴더 구조, 메타 폴백.
7. 수용 기준
   - [ ] 실제 업로드 1건을 **비공개**로 올려 유튜브 스튜디오에서 쇼츠로 분류되는지 확인(사용자 수동)
   - [ ] export 번들만으로 인스타 앱에서 수동 업로드 가능한 구성

### S-4. 인스타그램 릴스 발행 (`feat/instagram-reels-publish`)

사전 조건(사용자): 인스타그램 **프로페셔널(비즈니스/크리에이터) 계정**을 페이스북 페이지에 연결, Meta 앱에 Instagram Graph API 추가, 콘텐츠 발행 권한(현행 명칭은 구현 시 문서로 확정) 포함 **장기 토큰** 발급. 토큰은 `.env`(`IG_USER_ID`, `IG_ACCESS_TOKEN`) 또는 설정 모달에만 저장(커밋 금지).

1. `instagram_client.py` 신규 — `threads_client.py` 와 같은 골격:
   - `create_reels_container(video_url, caption, share_to_feed=True, cover_url=None)` → `POST /{ig_user_id}/media?media_type=REELS`
   - `wait_container(container_id)` → `GET /{id}?fields=status_code` 를 `FINISHED` 까지 폴링(타임아웃 5분, `ERROR`/`EXPIRED` 시 사유)
   - `publish_container(container_id)` → `POST /{ig_user_id}/media_publish` → `media_id`, `permalink`
   - `refresh_long_lived_token()`, `get_publishing_limit()`(일일 한도 조회), 모든 쓰기 기본 `dry_run=True`
2. **미디어 호스팅 어댑터** `media_host.py`: `publish_public_url(file) -> url`, `revoke(url)`. 구현체는 결정 ① 에 따라 `S3/R2 presigned`(권장) 또는 `tunnel`. 발행 완료 후 URL 회수(revoke).
3. `shorts_engine.publish_instagram(job)`: 호스팅 → 컨테이너 → 대기 → 발행 → `job["publish"]["instagram"]`. 실패해도 유튜브 결과는 유지.
4. 안전장치: `socialConfirmModal`(플랫폼·계정·건수 명시) 통과 시에만 `confirm_live=true`; 일일 발행 한도 로컬 카운터; 길이 > 90초·용량 > 250MB 면 발행 전 차단.
5. UI: 7단계 탭 "계정 연결 관리" 에 인스타그램 카드(토큰 등록/해제·만료일·한도), 쇼츠 패널에 `[릴스 발행]` 버튼.
6. 테스트: HTTP 모킹으로 2단계 흐름·폴링·에러 코드 매핑·드라이런 기본값. 실제 발행 1건은 사용자 승인 후 수동.
7. 수용 기준
   - [ ] 드라이런으로 요청 페이로드가 정확히 구성됨(토큰 로그 노출 0)
   - [ ] 실제 릴스 1건 발행 후 `permalink` 저장(사용자 승인 후)
   - [ ] 호스팅 URL 이 발행 후 회수됨

### S-5. 루나 뮤직 쇼츠 2.0 (`feat/luna-shorts-remotion`)

1. `remotion/src/MusicShorts.tsx`(또는 `ShortsScene` 의 `format=music` 분기): 배경 = 시그니처 BGA 루프(`data/bga_assets` 또는 트랙 `bga/loop_unit.mp4`) 9:16 센터크롭, 없으면 커버 블러; 중앙 커버; 가사 오버레이(트랙 `lyrics` 를 줄 단위로, 타이밍은 하이라이트 구간 내 균등 분배 — 보컬곡만); 하단 스펙트럼(`LunaBga` 의 `visualizeAudio` 코드 재사용); **비트 줌 펄스**.
2. `shorts_engine.analyze_beats(audio_path)`: librosa 로 BPM·비트 시각·에너지 구간·온셋 밀도(HyperFrames `analyze-beatgrid.py` 의 산출 구조를 축소 재구현). `librosa` 는 선택 의존성 — 없으면 펄스 없이 렌더. `requirements.txt` 에 주석으로 선택 표기.
3. `luna_engine.render_luna_shorts_video` 에 `renderer` 분기 추가(기본 `remotion`, 실패 시 기존 ffmpeg 그래프). 기존 함수 시그니처·반환 불변.
4. `upload_luna_to_youtube(with_shorts=True)` 는 그대로, `with_reels` 는 S-4 완료 후 옵션으로 추가.
5. 테스트: 비트 분석(합성 120BPM 클릭 트랙), 보컬/연주곡에 따른 가사 레이어 유무, 폴백.
6. 수용 기준
   - [ ] 보유 트랙 1개로 58초 뮤직 쇼츠 렌더, 가사 줄이 하이라이트 구간에 맞춰 표시
   - [ ] `tests/test_luna_shorts.py` 18개 회귀 통과

### S-6. 자동화 루틴 (`feat/shorts-autopilot`)

1. `services/` 에 `shorts_routine.py`: 트렌드 스카우트 추천 주제 → 쇼츠 컨셉 팩으로 씬 기획 → 잡 생성·빌드·QC → export → **예약 업로드 큐 등록**(유튜브 `publish_at` 분산: 하루 N편, 시간대 설정). 자율 오퍼레이터 루틴(`api/autonomous_routes.py`) 의 `outbox` 승인 흐름을 그대로 타서 **기본은 승인 후 발행**.
2. 예산 가드: 일일 이미지 상한·업로드 할당량 잔량(편당 1,600) 검사, 초과 시 큐만 쌓고 발행 보류.
3. UI: 자율 오퍼레이터 탭에 "쇼츠 루틴" 카드(주제 수·시간대·플랫폼·자동 승인 여부).
4. 수용 기준: 드라이런으로 하루 3편 큐 생성 → 승인 → 예약 업로드 등록까지 모킹 테스트 통과.

### S-7. 롱폼 리컷 F3 *(선택)* (`feat/shorts-recut`)

씬 기획서 타임코드 + 기존 `final.mp4` 에서 훅 점수(LLM) 가 높은 씬 1~2개 추출 → 16:9 → 9:16 센터크롭(블러필 옵션) → 기존 나레이션 자막을 단어 타이밍으로 재번인 → 쇼츠 잡으로 편입. OpenMontage `clip-factory` 의 "클립마다 독립, 하나 실패해도 배치 계속" 규칙 적용.

---

## 7b. 비용 0 경로 — 씬 종류(2026-10-19 추가, `feat/shorts-scene-kinds`)

사용자 요청("비용을 최대한 줄이는 방안")에 따라 **이미지 없는 씬 종류**를 `ShortsScene` 에 넣었다. 근거는 HyperFrames `faceless-explainer`(모든 비주얼을 타이포·추상·도표로), OpenMontage `remotion-composer` 의 TextCard·StatCard·BarChart·ComparisonCard 규격(재작성), Remotion 모션그래픽 템플릿이다.

| `kind` | 그리는 것 | 필드 |
|---|---|---|
| `image` | 기존 켄번즈 이미지 | `image`, `motion` |
| `text_card` | 큰 제목 + 액센트 부제 + 밑줄 등장 | `title`, `subtitle` |
| `stat_card` | 숫자 카운트업 + 단위 + 설명 | `value`, `unit`, `prefix`, `decimals`, `title`, `label` |
| `bar_chart` | 가로 막대 성장(강조 막대 액센트) | `title`, `unit`, `decimals`, `bars[{label,value,highlight}]` |
| `compare` | 전→후 카드(전 값 취소선, 후 값 카운트) | `title`, `rows[{label,from,to,unit,decimals}]` |

- 배경은 팔레트 6종 그라데이션 + 느리게 떠다니는 글로우 + 미세 격자(`palette` 로 지정). 정지 슬라이드 느낌을 피하려고 모든 종류에 등장·카운트 애니메이션을 넣었다.
- 씬 본래 길이가 끝나면 콘텐츠만 먼저 사라져 크로스페이드·엔드 태그와 글자가 겹치지 않는다.
- ffmpeg 폴백에서는 비이미지 씬이 단색 배경으로 대체되고 `warnings` 에 기록된다.
- **권장 조합**: 비용 0 씬을 기본으로, 편당 히어로 씬 1개만 무료 스톡(Pexels/Pixabay, S-2 이후 검토) 또는 저가 모델(`gemini-2.5-flash-image`, 장당 약 $0.04)로.
- 실측: 어사이드 AI 동향 「Gemini 4 Argon」 사례를 6씬(텍스트 2·막대 1·숫자 1·비교 2) 52.9초로 조립, Remotion 렌더 28~33초, **생성 비용 0원** (`data/shorts/shorts_argon_ai_trend/`, 조립 스크립트 `scripts/build_argon_shorts.py`).
- 나노바나나 가용성 확인(2026-10-19): Gemini 키 유효, 이 키로 `nano-banana-pro-preview`·`gemini-2.5-flash-image`·`gemini-3.1-flash-image`·`gemini-3.1-flash-lite-image`·`gemini-nano-banana-2.1` 이 `generateContent` 모델로 노출됨. `gemini-2.5-flash-image` 9:16 1장 실측: 768×1344 PNG, 9.3초, 출력 토큰 1,290(장당 약 $0.04). 최종본 v3 는 3번 씬(Spot)만 이 이미지로 교체하고 나머지 5씬은 0원 씬 — **편당 약 60원**.
- 남은 일: 나레이션 어절 타이밍(edge-tts 7.3.1 `boundary="WordBoundary"`)은 S-2 가 `tts_service` 에 정식 반영, 업로드는 S-3.

## 8. 비용·한도

| 항목 | 단위 | 비고 |
|---|---|---|
| Gemini 이미지(나노바나나) | 편당 0~7장 | 유일한 생성 비용. 7b 의 씬 종류를 쓰면 0장도 가능. 일일 상한 40장 기본 |
| 로컬 LLM | 0 | 기획·메타데이터 |
| edge-tts | 0 | 단어 타임스탬프 포함 |
| Remotion 렌더 | 0 (CPU 시간) | 30초 쇼츠 예상 1~2분(S-1 에서 실측) |
| 유튜브 업로드 | 1,600 유닛/편(일 10,000) | 롱폼+쇼츠 동시 업로드 시 하루 3편 상한 |
| 인스타 릴스 | API 일일 발행 한도 + 호스팅 비용(R2/S3 수 KB 단위 과금, 사실상 0) | |
| Veo 세로 영상 | 미포함 | 별도 승인·지시서(C 계열) |

---

## 9. 사용자 결정 필요 사항

| # | 결정 | 선택지 | 권장 |
|---|---|---|---|
| ① | 릴스 발행용 **공개 URL 호스팅** | (a) Cloudflare R2 또는 S3 공개/서명 URL (b) cloudflared/ngrok 임시 터널 (c) 기존 Playwright 프로필로 웹 업로드 | **보류** — 유튜브 안정화 후 S-4 착수 시 결정. 권장은 (a) |
| ② | 쇼츠 기본 성우 | edge-tts(단어 타이밍 정확) vs Qwen 클론(타이밍 근사) | **확정: edge-tts 기본**, 클론은 옵션 |
| ③ | 착수 순서 | | **확정: 유튜브 우선** (S-1 → S-2 → S-3 → S-6). S-4·S-5 는 후순위 |
| ④ | Gemini 이미지 일일 상한 | 기본 40장 | **확정: 40장** (운영 편수에 따라 조정) |
| ⑤ | 쇼츠 길이 정책 | 30초 고정 / 30~58초 가변 | **확정: 가변(30~58초)** |
| ⑥ | **쇼츠 채널** | 신규 비즈니스 계정 채널 (루나와 별개) | **확정**. 채널 ID·컨셉(주제·톤·채널명)은 S-2 컨셉 팩 설계 전에 알려 주실 것 |

---

## 10. 금지 사항

- OpenMontage 코드 복사·벤더링(AGPL-3.0). 규격·절차만 재작성한다.
- `remotion/` 패키지 버전 상향(4.0.534 고정 유지, 5.0 라이선스 변경 전 재검토).
- `producer.build_video`·`render_luna_shorts_video`·`uploader.upload_video` 기존 시그니처 변경(추가만).
- 인스타·유튜브 **실제 발행을 드라이런 없이** 수행하는 코드 경로. 모든 쓰기 기본 `dry_run=True`.
- 토큰·`.env`·`data/shorts/`·`node_modules`·`out/` 커밋.
- Veo·Vertex 호출(이 계획 범위 밖).

---

## 11. 검증 계획

- 단위: 각 단계 테스트는 Node·ffmpeg·네트워크 없이 통과(subprocess·HTTP 모킹). 실행은 `.venv/bin/python -m unittest discover tests`.
- 통합(ffmpeg·Remotion 있을 때): 합성 입력으로 S-1 렌더 1회, ffprobe 로 1080×1920·30fps·≤60초·오디오 확인, 렌더 시간 기록.
- E2E(사용자 승인 후 1회씩): 주제 1개 → F1 쇼츠 → 유튜브 비공개 업로드 → 쇼츠 분류 확인; 릴스 1건 발행 → permalink 확인.
- 회귀: 기존 테스트 전체(루나·베가·BGA·소셜) 통과, 롱폼 빌드·업로드 흐름 diff 0.

---

## 12. 출처

- Remotion 포크: https://github.com/casareborgia/remotion — `packages/captions`(`create-tiktok-style-captions.ts`), `packages/template-tiktok`, `packages/template-audiogram`, `LICENSE.md`
- HyperFrames 포크: https://github.com/casareborgia/hyperframes — `skills/music-to-video/SKILL.md`, `skills/music-to-video/scripts/analyze-beatgrid.py`, `skills/embedded-captions/SKILL.md`, `LICENSE`(Apache-2.0)
- OpenMontage: https://github.com/calesthio/OpenMontage — `lib/media_profiles.py`, `skills/creative/short-form.md`, `skills/core/subtitle-sync.md`, `pipeline_defs/clip-factory.yaml`, `skills/pipelines/clip-factory/*.md`, `tools/video/remotion_caption_burn.py`, `tools/publishers/export_bundle.py`, `remotion-composer/src/components/CaptionOverlay.tsx`, `LICENSE`(AGPL-3.0)
- 이 저장소: `작업지시서_Luna_BGA_C1b_실생성_Remotion.md`(Remotion 채택 기준·실측), `작업지시서_Luna_보컬판정_숏폼_BGA.md`(Phase B 숏폼), `choonsik_bga.py`(`render_bga_remotion`, `BGA_RENDERER`), `threads_client.py`(컨테이너 2단계 발행)
- Instagram Graph API 콘텐츠 발행(릴스 컨테이너 → 상태 폴링 → 발행, 공개 `video_url` 요구, 일일 발행 한도): 구현 전 Meta 개발자 문서에서 권한명·길이·한도 수치를 재확인한다.
