# 사운드 엔지니어 베가(Vega) 마스터링 에이전트 작업지시서

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | 에이전트 루나 음원 파이프라인에 사운드 엔지니어 베가(마스터링 에이전트) 추가 |
| 프로젝트 | `유튜브 영상분석실습` (TubeInsight AI) |
| 작성일 | 2026-10-06 |
| 작업 브랜치 | `feat/vega-mastering-agent` (PR #4, `main` 에 머지) → 후속 과제는 `main` 에서 `feat/vega-*` |
| 기준 구현 | `vega_engine.py`(신규), `luna_engine.py`, `app.py`, `static/index.html`, `static/app.js`, `tests/test_vega_engine.py`, `requirements.txt` |
| 참고 레포 | [Tanzil-Ahmed/mixmaster-ai](https://github.com/Tanzil-Ahmed/mixmaster-ai) (구조 참고, 코드 미복사) · [Esgr0bar/MasterIA](https://github.com/Esgr0bar/MasterIA) (GPL-3.0, 아이디어만 참고) |
| 최종 목표 | 루나가 만든 완곡 음원을 유튜브 업로드 규격(-14 LUFS / -1 dBTP)에 맞게 자동 마스터링하고, 원본·결과를 A/B 비교하며 프롬프트로 재마스터링할 수 있게 한다 |

이 문서는 **1단계(마스터링) 구현이 완료된 상태**를 기준으로 쓴 지시서다. 3장은 이미 구현된 내용의 명세이고, 7장은 안티그래비티(Antigravity)가 이어서 작업할 후속 과제다. 7장을 작업할 때는 3~6장의 계약(데이터 모델·API·DSP 규칙)을 바꾸지 않는 것을 원칙으로 한다.

## 2. 배경과 제품 원칙

현재 루나 파이프라인은 다음 세 단계다.

1. **레오**: 트렌드 분석 → 장르·무드·프롬프트 브리프 생성
2. **루나**: Lyria 3 작곡 (실패 시 ffmpeg 로컬 신스) → `audio.mp3`
3. **렌더링·업로드**: 앨범 커버 + 켄번즈 영상 합성 → 유튜브 업로드

Lyria 출력은 트랙마다 음량·톤 밸런스가 들쭉날쭉하고, 유튜브는 업로드 음원을 -14 LUFS 기준으로 정규화한다. 그래서 2와 3 사이에 **베가**를 넣어 모든 트랙을 같은 규격으로 다듬는다.

```
1. 레오 (트렌드 → 프롬프트)
2. 루나 (Lyria 작곡 → audio.mp3)
   ★ 베가 (분석 → 결정 → DSP → audio_mastered.wav)   ← 이번 작업
3. 렌더링 (audio_file 을 그대로 사용) → 유튜브 업로드
```

설계 원칙은 프로젝트 전체 원칙을 그대로 따른다.

1. **점진적 저하** — pedalboard 등 의존성이 없거나 LLM 호출이 실패해도 루나 파이프라인은 멈추지 않는다. 마스터링만 건너뛰거나 프리셋으로 대체한다.
2. **원본 보존** — 원본은 `audio_raw.*` 로 한 번 보존하고 결과는 별도 파일에 쓴다. 재마스터링은 항상 원본에서 다시 시작해 열화가 누적되지 않는다.
3. **범위 제한된 AI 결정** — LLM이 정하는 모든 수치는 Pydantic 스키마의 `ge`/`le` 범위를 통과해야만 적용한다. 범위를 벗어나면 그 결정 전체를 버리고 프리셋을 쓴다.
4. **기존 코드 무수정 연동** — 렌더링과 업로드는 `track_data["audio_file"]`을 읽는다. 베가가 이 값을 바꾸는 것만으로 이후 단계가 마스터 결과를 쓴다.
5. **로컬 처리** — 오디오는 로컬에서 처리하고 외부로 전송하지 않는다. LLM에는 숫자 측정값만 보낸다.

## 3. 구현 완료 명세 (1단계)

### 3.1 모듈 구조 — `vega_engine.py`

mixmaster-ai 의 `analyze → decide → process → write` 4단계 구조를 참고하되 이 프로젝트에 맞게 새로 구현했다.

| 함수 | 역할 | 비고 |
|---|---|---|
| `is_available()` / `availability_report()` | 의존성 설치 여부, 설치 안내 | pedalboard · pyloudnorm · soundfile · scipy |
| `load_audio(path)` | 음원 → `(channels, samples)` float32 | soundfile 우선, 실패 시 ffmpeg 디코딩. 모노는 스테레오로 복제. **샘플레이트는 원본 유지**(리샘플링 없음) |
| `analyze(audio, sr)` | 측정값 13종 (아래 3.3) | librosa 없이 numpy/scipy/pyloudnorm 만 사용 |
| `decide(analysis, genre, mood, prompt, use_llm, genre_spec)` | `MasteringDecisions` 결정 | 반환 `(decisions, source, note)`; `source` = `"llm"` 또는 `"preset"` |
| `decide_with_meta(...)` | `decide()` + LLM 호출 메타 | 네 번째 값 `{backend, model, attempted}` — 실제로 응답한 모델 |
| `process(audio, sr, decisions)` | DSP 체인 적용 | 반환 `(float32 결과, 처리 로그)` |
| `write_audio(audio, sr, path, bit_depth)` | 24bit WAV 저장 | 입력과 같은 샘플레이트로 저장 (Lyria 는 44.1kHz) |
| `master_track(track_data, prompt, use_llm, luna_dir, genre_spec, progress_cb)` | 위 전체를 묶어 루나 `track_data` 를 갱신 | **예외를 밖으로 던지지 않는다** |
| `preset_for_genre(genre)` / `describe_presets()` | 장르별 프리셋 | 10개 장르 + `default` |

### 3.2 DSP 체인과 규칙

```
corrective_eq → compressor → tonal_eq → saturator → M/S stereo_image
  → 음량 매칭 (target_lufs)  → 리미터 (ceiling_dbtp)  → 트루피크 재검증 → LUFS 하향 재보정
```

반드시 지켜야 하는 규칙:

- **음량 매칭은 리미터 앞에서 한다.** mixmaster-ai 는 리미터 뒤에서 음량을 맞춰 피크가 다시 넘치는 결함이 있었다. 베가는 리미터 앞에서 게인을 맞추고, 리미터 뒤에서는 **아래로만** 보정한다.
- **pedalboard `Limiter` 를 쓰지 않는다.** 실측 결과 내부적으로 약 +5 dB 메이크업 게인을 더하고 0 dBFS 까지 클립한다. 대신 `Compressor(ratio=20, attack_ms=0.1)` 를 브릭월 리미터로 쓴다.
- **트루피크는 채널별로 잰다.** 채널을 합쳐 재면 한쪽만 큰 신호에서 최대 6 dB 낮게 나온다. `_true_peak_dbtp()` 는 채널별 4배 오버샘플링 후 최대값을 쓴다.
- **EQ 는 pedalboard 바이쿼드 필터**(`PeakFilter`, `LowShelfFilter`, `HighShelfFilter`, `HighpassFilter`, `LowpassFilter`)를 쓴다. 필터 결과를 원음에 더하는 방식(위상 문제)은 금지.
- **새츄레이터는 `tanh(drive)` 로 정규화**해 질감만 더하고 음량은 바꾸지 않는다. `mix=0` 또는 `drive=0` 이면 입력을 그대로 돌려준다.
- **M/S 이미저**는 `mono_low_hz` 이하 사이드 성분을 제거해 저음을 모노로 만든 뒤 `width` 를 곱한다.
- 오디오 배열은 항상 `(channels, samples)`, 입출력 float32, 내부 연산 float64, pedalboard 호출 전 `[-1, 1]` 클립.
- **리샘플링하지 않는다.** 원본 샘플레이트(Lyria 44.1kHz)로 처리·저장한다. 유튜브는 44.1kHz 를 그대로 받으며, 변환은 음질 손실만 남긴다.
- 피크가 `SILENCE_FLOOR(1e-6)` 미만이면 무음으로 보고 DSP 를 건너뛴다.
- 샘플레이트는 하드코딩하지 않고 항상 인자로 넘긴다.

### 3.3 측정값 (`analyze` 반환 키)

| 키 | 의미 | 결정 규칙에서의 쓰임 |
|---|---|---|
| `integrated_lufs` | 체감 음량 (ITU-R BS.1770, pyloudnorm) | 목표 대비 게인 계산 |
| `true_peak_dbtp` | 채널별 4× 오버샘플 트루피크 | 이미 -1 초과면 ceiling 을 -1 이하로 |
| `rms_db`, `peak_db`, `crest_factor_db` | 레벨·펀치 | `crest < 8` 이면 이미 압축된 소리 → ratio ≤ 2 |
| `dynamic_range_db` | 프레임 RMS 90/10 백분위 차 | 다이내믹 보존 판단 |
| `rms_sub_db` / `rms_low_db` / `rms_mid_db` / `rms_high_db` | <60 / 60–250 / 250–4k / >4k Hz 대역 RMS | 톤 밸런스 (머드·하시 판단) |
| `spectral_centroid_hz`, `spectral_flatness` | 밝기 / 노이즈성 | 톤 EQ 방향 |
| `stereo_width` | side RMS / mid RMS | `> 0.6` 이면 더 넓히지 않음 |
| `low_end_correlation` | 120 Hz 이하 L/R 상관계수 | `< 0.7` 이면 `mono_low_hz ≥ 120` |
| `duration_seconds`, `sample_rate`, `channels`, `is_silent` | 기본 정보 | |

### 3.4 스키마 (`MasteringDecisions`)

| 필드 | 범위 |
|---|---|
| `corrective_eq.bands[]`, `tonal_eq.bands[]` (최대 8개) | `frequency` 20–20000 Hz, `gain_db` -12–+6, `q` 0.1–10, `filter_type` ∈ low_shelf/high_shelf/peak/high_pass/low_pass |
| `compressor` | `threshold_db` -60–0, `ratio` 1–10, `attack_ms` 0.1–100, `release_ms` 10–1000, `makeup_gain_db` 0–12 |
| `saturator` | `drive_db` 0–12, `mix` 0–1, `mode` ∈ tape/tube/clip |
| `stereo_image` | `width` 0–2, `mono_low_hz` 20–300 |
| `limiter` | `ceiling_dbtp` -3–-0.1, `release_ms` 50–500 |
| `target_lufs` | -24–-8 |
| `reasoning` | 한국어 2~3문장 |

### 3.5 장르별 프리셋 (`GENRE_MASTER_PRESETS`)

| 장르 | 목표 LUFS | ceiling | 특징 |
|---|---|---|---|
| lofi | -14 | -1.0 | 테이프 새츄 0.35, 9 kHz -2 dB (따뜻함) |
| ambient | -16 | -1.0 | ratio 1.5, width 1.2, 10 kHz +1 (공기감) |
| synthwave | -12 | -1.0 | ratio 3.0, 250 Hz 머드 컷, 저·고역 +1.5 |
| sleep | -18 | -1.5 | ratio 1.3, 8 kHz -3, 새츄 없음 |
| jazz | -14 | -1.0 | ratio 1.8, 3 kHz +1 프레즌스 |
| piano | -16 | -1.0 | ratio 1.6, 다이내믹 보존 |
| citypop | -12 | -1.0 | 3 kHz +1.5 보컬, 9 kHz +1.5 광택 |
| acoustic | -14 | -1.0 | 400 Hz 박시함 컷 |
| rnb-chill | -12 | -1.0 | 60 Hz +2 서브, 3 kHz +1.5 보컬 |
| dark-ambient | -16 | -1.0 | width 1.3, mono_low 90 |
| default | -14 | -1.0 | 중립 |

유튜브가 -14 LUFS 로 정규화하므로 비트 중심 장르도 -12 를 넘기지 않는다. LLM은 이 프리셋을 "출발점"으로 받아 측정값이 뒷받침하는 항목만 ±2 LU 안에서 조정한다.

### 3.6 LLM 결정 경로

- `llm_client.call_llm_json()` 을 통해 Gemini 또는 로컬 LLM(LM Studio/Ollama)을 호출한다. 프로젝트 공통 경로이며 Anthropic API 를 직접 쓰지 않는다.
- 온도 0.2, 시스템 프롬프트에 체인 순서와 판단 규칙(3.3 우측 열)을 명시한다.
- 응답이 JSON 이 아니거나 스키마 범위를 벗어나면 **프리셋으로 전체 대체**하고 `mastering.note` 에 사유를 적는다. 일부만 가져오지 않는다.
- **결정한 모델을 기록한다.** `llm_client.last_call_info()` 는 마지막 `call_llm()` 에서 *실제로 응답한* 백엔드·모델을 돌려준다(Gemini 실패 → 로컬 폴백도 반영, 호출 실패 시 None). 베가는 이 값을 `mastering.decision_backend` / `decision_model` 에 남긴다. LLM 응답이 범위 검증에서 떨어져 프리셋을 썼다면 `decision_model` 은 None 이고 호출했던 모델은 `llm_attempted` 에 남는다.
- 무음 입력이면 LLM 을 호출하지 않는다.

### 3.7 데이터 모델 — `track_data` 추가 필드

```jsonc
{
  "audio_file":     ".../luna_music/<id>/audio_mastered.wav",   // ← 마스터 결과로 교체됨 (렌더·업로드가 이 값을 사용)
  "audio_url":      "/data/luna_music/<id>/audio_mastered.wav",
  "audio_raw_file": ".../luna_music/<id>/audio_raw.mp3",        // 원본 보존 (한 번만 복사)
  "audio_raw_url":  "/data/luna_music/<id>/audio_raw.mp3",
  "audio_preview_file": ".../luna_music/<id>/audio_mastered_preview.mp3",  // 웹 미리듣기용 192k MP3 (1.2.0+)
  "audio_preview_url":  "/data/luna_music/<id>/audio_mastered_preview.mp3", // 인코딩 실패 시 두 키 모두 없음 → UI 는 WAV 로 폴백
  "video_stale":    true,                                       // 재마스터 후 기존 영상이 구버전이면 true, 재렌더 시 제거
  "mastering": {
    "status": "done" | "failed" | "skipped",
    "agent": "베가 (Vega)", "engine_version": "1.2.0",
    "decision_source": "llm" | "preset",
    "decision_backend": "gemini" | "lmstudio" | "ollama" | null,   // decision_source == "llm" 일 때만
    "decision_model": "gemini-3.8-flash" | null,                    // 실제로 결정을 내린 모델
    "llm_attempted": {"backend": ..., "model": ..., "attempted": true} | null,  // LLM 을 불렀지만 프리셋으로 대체된 경우
    "note": "폴백 사유 등 (미리듣기 MP3 실패 사유도 여기에 덧붙는다)",
    "preview_file": ".../audio_mastered_preview.mp3" | null,
    "prompt": "사용자 지시",
    "genre": "lofi", "target_lufs": -14.0, "ceiling_dbtp": -1.0,
    "before": { ...analyze() 결과 }, "after": { ...analyze() 결과 },
    "decisions": { ...MasteringDecisions }, "reasoning": "LLM/프리셋 사유",
    "process_log": { "loudness_gain_db": -1.8, "true_peak_trim_db": ..., "post_limiter_trim_db": ... },
    "output_file": "...", "sample_rate": 44100, "bit_depth": 24,   // sample_rate 는 원본 그대로
    "elapsed_seconds": 2.3, "processed_at": 1759760000.0
    // status != done 이면: "reason", (skipped 시) "install_hint"
  }
}
```

### 3.8 API

| 메서드·경로 | 요청 | 응답 | 설명 |
|---|---|---|---|
| `GET /api/vega/status` | — | `{available, agent, engine_version, missing_reason, install_hint, auto_master_enabled, presets[]}` | 가용성·프리셋 요약 |
| `POST /api/luna/master` | `{track_id, prompt?, use_llm?=true}` | 갱신된 `track_data` | 기존 트랙 (재)마스터링. 404 트랙 없음, 503 의존성 없음 |
| `POST /api/luna/generate` | 기존 필드 + `master_audio?=true`, `mastering_prompt?` | 기존과 동일 | 생성 직후 자동 마스터링 |

환경변수 `VEGA_AUTO_MASTER=0` 이면 생성 시 자동 마스터링을 끈다(기본 켜짐).

### 3.9 프론트엔드 (6단계 루나 탭)

- 오디오 플레이어 아래 **베가 패널**(`#vegaPanel`): 상태 배지(완료·`AI 결정 · <모델명>`/장르 프리셋, 건너뜀, 실패), 전후 측정값(LUFS·트루피크·크레스트·스테레오 폭), 결정 사유, 재렌더 필요 경고.
- 보관함 목록(`/api/luna/history`)도 `mastering`, `audio_raw_url`, `video_stale` 을 내려주므로, 보관함에서 곡을 골라도 패널이 보인다.
- **A/B 버튼**: `A · 원본` / `B · 마스터` — 재생 위치를 유지한 채 `audio_raw_url` ↔ `audio_preview_url`(없으면 `audio_url`) 전환. 원본·마스터 모두 MP3 라 로딩 속도가 같다.
- 플레이어 기본 소스도 `audio_preview_url || audio_url`. 4단계 영상 제작의 배경음악 선택과 렌더·업로드는 계속 WAV(`audio_url`/`audio_file`)를 쓴다.
- **전후 비교 차트**(`#vegaSpectrumSection`, 7.1): `mastering.before/after` 의 4대역 RMS·LUFS·트루피크를 행마다 원본(회색)/마스터(청록) 가로 막대로 그린다. 공통 dB 축(+3 ~ 최소값 기준 12dB 단위), LUFS 행에 목표(`target_lufs`)·트루피크 행에 한도(`ceiling_dbtp`) 노란 세로선, 0 dBTP 빨간선, 0 초과 피크는 빨간 막대. 텍스트는 CSS px 라 패널 폭(약 300px)에서도 읽힌다. 외부 라이브러리 없음.
- **생성 폼 마스터링 옵션 (7.3)**: 음원 길이/영상 화질 아래 "베가 자동 마스터링 (유튜브 -14 LUFS 규격)" 체크박스(`#lunaMasterAudioCheck`, 기본 켜짐)와 "마스터링 지시 (선택)" 입력란(`#lunaMasteringPromptInput`). 체크 해제 시 지시 입력란 비활성화. 체크 상태만 `localStorage`(`vega_master_audio`)에 기억하고 **지시문은 기억하지 않는다**(이전 곡의 지시가 다른 장르의 새 곡에 조용히 적용되는 것을 막기 위해; 생성 성공 시 입력란을 비운다).
- **재마스터 프리셋 토글 (7.3)**: 패널 재마스터 영역에 "프리셋만 적용 (AI 판단 없음, 비용 0)" 토글(`#vegaPresetOnlyCheck`, `use_llm = !checked`, 기본 꺼짐). 토글 시 프롬프트 입력란이 비활성화되며 `POST /api/luna/master` 호출 시 `use_llm: false`가 전송된다. `localStorage`(`vega_preset_only`)에 상태 기억.
- **재마스터**: 프롬프트 입력 후 `POST /api/luna/master` 호출, 결과로 뷰 갱신.
- `mastering` 필드가 없는 과거 트랙은 패널을 숨긴다.

### 3.10 테스트 — `tests/test_vega_engine.py`

합성 사인파만 쓰고 LLM 은 mock 한다. 실행: `python -m unittest tests.test_vega_engine`

- 스키마·프리셋: 10개 장르 모두 유효, 범위 밖 값 거부, 수면 < 비트 장르 음량
- 결정: 프리셋 전용 모드, LLM 실패/범위 초과 → 프리셋 폴백, 유효 응답 채택, 무음 시 LLM 미호출
- DSP: 측정값 유한성, 채널별 트루피크, 4개 장르에서 목표 LUFS ±(0.5/1.5) 및 ceiling 준수, 조용한 입력 증폭, 무음·0.1초·풀스케일 엣지
- 오케스트레이션: 원본 보존·`audio_file` 교체, 재마스터 시 원본에서 재시작(열화 누적 없음), 음원 없음 → `failed` 유지, LLM 실패 중에도 `done`
- 비활성 경로: 의존성 없을 때 `skipped` 와 설치 안내
- API: `/api/vega/status`, 없는 트랙 404, 생성 요청 필드

### 3.11 실제 음원 검증 결과 (2026-10-07)

Lyria 3.5 로 생성한 lofi 곡 *Blue Hour Reverie* (180초, 44.1kHz) 를 베가와 **독립된 ffmpeg EBU R128 측정기**로 검증했다.

| 항목 | 원본 | 마스터 | 렌더 영상(AAC 192k) |
|---|---|---|---|
| 통합 음량 | -11.6 LUFS | -14.0 LUFS | -14.0 LUFS |
| 트루피크 | +0.3 dBFS | -2.0 dBFS | -2.3 dBFS |
| 풀스케일 클리핑 샘플 | 62 | 0 | — |
| LRA | 11.9 LU | 8.2 LU | 8.1 LU |

- 널 테스트: 음량만 맞춘 원본 대비 잔차 -10.3 dB (게인만 바꿨다면 -60 dB 이하) → 실제 DSP 처리 확인
- 대역 변화(음량 매칭 후): <30Hz -3.3 dB (HPF), 10–16kHz +1.8 dB (shelf +1 + 새츄 배음). 250Hz -0.8 dB 컷은 새츄레이션 배음에 묻혀 측정되지 않음
- 시간 정렬 오차 0 샘플, NaN 0, 길이 동일
- 재마스터 지시 "저음을 더 단단하고 풍성하게, 고역은 부드럽게" → LLM 이 120Hz +2.2 / 8.5kHz -2.5 로 결정, 실측 서브 +1.6 dB · 고역 -1.6 dB, 음량은 -14.0 유지, 원본에서 재시작 확인

## 4. 참고 레포 분석 요약과 적용 판단

| 항목 | mixmaster-ai | MasterIA | 베가 적용 |
|---|---|---|---|
| 실제 오디오 처리 | ✅ pedalboard/scipy 체인 | ❌ 제안 텍스트만 | mixmaster 구조 채택 |
| AI 역할 | Claude 가 측정값+프롬프트로 수치 결정(forced tool) | 학습 데이터 없는 ML 모델 | `llm_client` 경유 JSON 결정 + 스키마 검증 |
| 믹싱 | 보컬·반주 **별도 파일** 필요 | — | Lyria 는 합쳐진 스테레오만 제공 → 1단계 제외 |
| 결함 | 음량 매칭이 리미터 뒤 / TP 합산 측정 / 쉘빙 EQ 위상 | 실행 불가(존재하지 않는 import, 폐기된 TF API) | 세 가지 모두 수정해 구현 |
| 라이선스 | README 는 Apache-2.0 이라 하나 LICENSE 파일 없음 | **GPL-3.0** | 어느 쪽 코드도 복사하지 않음 |

## 5. 운영 규칙

1. 베가가 실패하면 로그에 `[Vega] 마스터링 실패` 가 남고 원본으로 렌더·업로드가 진행된다. 업로드 전 패널 상태 배지를 확인한다.
2. 재마스터 후에는 영상이 구버전이므로 `video_stale` 경고가 뜬다. **업로드 전 반드시 비디오 재렌더**한다.
3. 프롬프트는 음향 지시만 쓴다(예: "저음 단단하게", "고역 부드럽게", "-14 LUFS 스트리밍용"). 장르 변경·작곡 지시는 루나 쪽 기능이다.
4. 의존성 설치: `pip install -r requirements.txt` (pedalboard · pyloudnorm · soundfile · scipy 포함). Python 3.14 macOS arm64 휠 확인됨.

## 6. 수용 기준 (1단계)

- [x] 루나 생성 직후 자동 마스터링되고 `track_data.mastering.status == "done"`
- [x] 결과 트루피크 ≤ ceiling, LUFS 는 목표 +0.5 / -1.5 LU 이내 (합성 신호 기준 4개 장르 검증)
- [x] 원본 `audio_raw.*` 보존, 재마스터는 원본에서 재시작
- [x] LLM 실패·범위 초과 시 프리셋으로 자동 대체, 파이프라인 중단 없음
- [x] 의존성 미설치 시 `skipped` 로 건너뛰고 루나는 정상 동작
- [x] 렌더·업로드 코드 수정 없이 마스터 결과 사용
- [x] A/B 비교·재마스터 UI
- [x] 기존 `tests/test_luna_leo_integrity.py` 통과

## 7. 안티그래비티 후속 작업 (2단계 이후)

아래 과제는 3장의 계약을 유지한 채 **각각 별도 브랜치**로 진행한다. 우선순위 순. 작업 전에 7.0 을 먼저 끝낸다.

### 7.0 착수 전 준비 (필수)

**① 기준 브랜치** — 베가 1단계는 PR #4 로 `main` 에 머지되어 있다. 항상 최신 `main` 에서 시작한다.

```bash
git checkout main
git pull origin main
git checkout -b feat/vega-preview-mp3      # 과제별 브랜치명은 7.1~7.5 참고
```

**② 실행 환경**

| 항목 | 내용 |
|---|---|
| Python | 3.11 이상 (3.14 에서 검증) |
| 의존성 | `pip install -r requirements.txt` — `pedalboard`, `pyloudnorm`, `soundfile`, `scipy` 포함 |
| ffmpeg | `brew install ffmpeg` (디코딩·렌더링·독립 측정에 사용) |
| Gemini 키 | `.env` 의 `GEMINI_API_KEY`. 없으면 베가는 장르 프리셋으로 동작하고, **단위 테스트는 키 없이 통과**한다 |

설치 확인:

```bash
python -c "import vega_engine, json; print(json.dumps(vega_engine.availability_report(), ensure_ascii=False))"
# "available": true 가 나와야 한다
```

**③ 서버 실행**

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8765
# 8765 가 사용 중이면 다른 포트 사용. 6단계 [레오 ✕ 루나 음악 스튜디오] 탭에서 확인
```

`GET /api/vega/status` 의 `available`, `engine_version`(현재 `1.2.0`), `auto_master_enabled` 로 상태를 확인할 수 있다.

**④ 테스트와 기존 실패**

```bash
python -m unittest tests.test_vega_engine tests.test_luna_leo_integrity   # 반드시 전부 통과
python -m unittest discover -s tests -p 'test_*.py'                       # 전체 회귀
```

전체 실행 시 아래 **5건은 베가와 무관한 기존 실패**다. 원인 파악·수정은 이 작업 범위가 아니므로 건드리지 않는다. 이 5건 외에 새 실패가 생기면 그것은 회귀다.

| 테스트 | 원인 |
|---|---|
| `test_gemini_model_selection` 2건 | Gemini 키가 있어야 통과 (환경 의존) |
| `test_social_store` 3건 (`schema_initialization`, `v1_to_v2_migration`, `migration_from_preexisting_db`) | 테스트가 스키마 v2 를 기대하나 코드는 v3 (테스트 미갱신) |
| (간헐) `test_account_replies` | 실제 Threads/X 인증 필요 |

**⑤ 실제 음원 검증 방법** — DSP 를 바꾸는 과제(7.2, 7.4, 7.5)는 합성 신호 테스트에 더해 실제 곡으로도 확인한다. 베가 내부 측정이 아닌 **ffmpeg EBU R128 독립 측정**을 기준으로 삼는다.

```bash
D=data/luna_music/<track_id>
for f in audio_raw.mp3 audio_mastered.wav; do
  echo "== $f"
  ffmpeg -hide_banner -nostats -i "$D/$f" -af ebur128=peak=true -f null - 2>&1 \
    | grep -E "^\s+(I|LRA|Peak):"
done
```

합격 기준: 통합 음량 `I` 가 `mastering.target_lufs` ±0.5 LU, 트루피크 `Peak` 가 `mastering.ceiling_dbtp` 이하. 렌더 후 `video.mp4` 에도 같은 명령(`-vn` 추가)을 돌려 영상 오디오가 같은 기준을 지키는지 본다.

**⑥ 비용 주의** — 새 곡 생성은 Lyria(작곡)·Imagen(커버)·Gemini(기획) 크레딧을 쓴다. 검증은 **보관함의 기존 곡을 재마스터**(`POST /api/luna/master`, Gemini flash 1회)하는 방식을 우선하고, 새 곡 생성은 꼭 필요할 때만 한다. 렌더링은 ffmpeg 만 쓰므로 비용이 없다.

**⑦ 데이터 보호** — `data/luna_music/` 는 `.gitignore` 대상이다. 커밋하지 않는다. 각 트랙의 `audio_raw.*` 는 재마스터의 원본이므로 삭제·덮어쓰기 금지.

### 7.1 [P1] 전후 스펙트럼 비교 그래프 — `feat/vega-spectrum-compare` ✅ 완료
- `mastering.before/after` 의 4대역 RMS(`rms_sub/low/mid/high_db`)와 LUFS·TP 를 베가 패널에 막대 그래프로 시각화한다.
- 외부 차트 라이브러리 없이 CSS/SVG 로 구현한다(CSP: `script-src 'self' cdnjs` 만 허용).
- 범위: `static/index.html`, `static/app.js`, `static/style.css`. 백엔드 변경 없음.
- 구현 메모: 처음 구현은 가로 560px 짜리 SVG 한 장이었는데, 실제 패널 폭 299px 에서 0.44배로 축소되어 글자가 3.5~4.6px 로 렌더링됐다(실측). 리뷰에서 **텍스트는 CSS px, 막대만 퍼센트**인 가로 막대 행(grid) 방식으로 바꿨다. 교훈: 고정 viewBox SVG 에 텍스트를 넣으면 좁은 컨테이너에서 읽을 수 없으니, 항상 실제 패널 폭에서 렌더 크기를 재 본다.
- 추가: LUFS 변화량 단위 LU, 목표 LUFS·트루피크 한도 세로선, 원본 피크 0 dBTP 초과도 빨간 표시, 축 하한을 데이터에 맞춰 자동 확장(수면 장르 -45 이하 대응).

### 7.2 [P1] 마스터 결과 MP3 미리듣기 파일 — `feat/vega-preview-mp3` ✅ 완료 (engine 1.2.0)
- 24bit WAV(3분 ≈ 47 MB)는 A/B 전환이 느릴 수 있다. `master_track` 끝에서 ffmpeg(libmp3lame)로 `audio_mastered_preview.mp3`(192k)를 추가 생성하고 `audio_preview_url` 로 노출한다.
- 렌더·업로드·측정은 계속 WAV(`audio_file`)를 쓴다. 미리듣기만 MP3.
- 인코딩 실패 시 마스터링은 그대로 성공 처리하고, 이전 미리듣기 키·파일을 제거해 UI 가 WAV 로 폴백하게 한다. 사유는 `mastering.note` 에 남는다.
- 실측 (Etched in Plaster, 180초): WAV 47.2 MB → MP3 4.3 MB, 음량 -14.0 → -14.2 LUFS, 피크 -2.7 → -2.9 dBFS, 전체 마스터링 8초.
- 테스트: 생성·URL 노출·WAV 유지, 인코더 단독, 실패 시 폴백 3건.

### 7.3 [P2] 마스터링 프리셋 선택·토글 UI — `feat/vega-preset-selector` ✅ 완료
- 생성 폼에 "베가 자동 마스터링" 체크박스(`master_audio`)와 마스터링 지시 입력(`mastering_prompt`)을 추가 (기본 켜짐, 체크 해제 시 지시 입력 비활성화, 체크 상태만 localStorage 연동).
- 리뷰 보완: 지시문 localStorage 기억 제거(곡 간 오염 방지), 생성 성공 시 지시 입력란 초기화, localStorage 읽기도 try/catch. 실측: 폼 폭 542px·패널 폭 307px 안에서 넘침 없음, 프리셋 모드 재마스터 6초·Gemini 호출 0회, 체크 해제 시 요청 body 에 `master_audio:false` 전송 확인.
- 재마스터 패널에 "프리셋만 적용"(`use_llm=false`) 옵션 추가 (토글 켜짐 시 지시 입력 비활성화, localStorage 연동).
- `POST /api/luna/generate` 및 `POST /api/luna/master` 호출 바디 연동 완료.
- `VegaUiAssetsTests` 단위 테스트에 새 요소 ID 검사 추가 및 전체 45개 테스트 통과 유지.

### 7.4 [P2] 피드백 로그와 프리셋 자동 보정 — `feat/vega-feedback-loop`
- MasterIA 의 "사용자 피드백 학습" 아이디어를 가볍게 적용한다. A/B 에서 사용자가 최종 선택한 쪽(원본/마스터)과 재마스터 프롬프트를 `data/luna_music/vega_feedback.jsonl` 에 기록한다.
- 장르별로 최근 N건의 `decisions` 중앙값을 계산해 프리셋을 ±1 LU, ±1 dB 범위 안에서만 보정하는 `suggest_preset_adjustment(genre)` 를 추가한다. **자동 적용은 하지 않고** 제안값만 패널에 보여준다.
- ML 모델·외부 학습은 도입하지 않는다.

### 7.5 [P3] 믹싱 단계 (보컬·반주 분리) — `feat/vega-stem-mixing`
- 가사가 있는 트랙(`has_lyrics`)에 한해 Demucs(`htdemucs`)로 보컬/반주를 분리한 뒤, 보컬 체인(게이트 → EQ → 컴프 → 리버브)과 반주 밸런스를 조정하고 다시 합쳐 마스터링한다.
- PyTorch 의존성이 크고 3분 곡에 수십 초가 걸리므로 **선택 설치·선택 실행**으로 설계한다(`VEGA_STEM_MIXING=1`). 미설치 시 현재 마스터링만 수행.
- 스키마는 `MixDecisions` 를 새로 추가하되 3.4 와 같은 범위 원칙을 따른다.

### 7.6 [P3] 레퍼런스 트랙 매칭 — 보류
- `matchering` 은 GPL-3.0 이므로 프로젝트 라이선스(MIT) 와 충돌한다. 도입하려면 별도 프로세스 호출 방식과 라이선스 검토가 선행되어야 한다. 현재는 보류.

### 7.7 공통 작업 규칙
1. 작업 전 `git status`, `git branch` 확인 후 **최신 `main` 에서** `feat/vega-*` 브랜치 생성 (7.0 ①).
2. `vega_engine.py` 의 공개 함수 시그니처와 `track_data.mastering` 키는 **추가만 허용, 변경·삭제 금지**.
3. 새 DSP 함수는 먼저 Pydantic 스키마(범위 포함)를 추가한 뒤 구현한다. 매직 넘버 금지.
4. 테스트는 `unittest`, 합성 신호만 사용, LLM 은 mock. DSP 테스트는 shape·dtype·`|x| ≤ 1`·유한성 네 가지를 항상 단언한다.
5. 작업 후 `python -m unittest tests.test_vega_engine tests.test_luna_leo_integrity` 통과를 확인하고 변경 요약과 함께 사용자 승인을 받은 뒤 커밋·푸시한다.
6. 음원·토큰·`.env` 는 커밋하지 않는다(`data/luna_music/*` 은 이미 `.gitignore`).

## 8. 금지 사항

- pedalboard `Limiter` 사용 (게인 추가·0 dBFS 클립)
- 리미터 뒤에서 음량을 **올리는** 보정
- 채널 합산 신호로 트루피크 측정
- LLM 결정값을 스키마 검증 없이 적용하거나 일부만 선택 적용
- 원본 `audio_raw.*` 덮어쓰기, 마스터 결과 위에 재마스터링
- mixmaster-ai / MasterIA 코드 복사(라이선스 불명확·GPL)
- 오디오 파일을 외부 API 로 전송
