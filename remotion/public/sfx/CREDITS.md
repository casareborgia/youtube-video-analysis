# 효과음 출처 (모두 CC0 — 출처 표기 의무 없음, 기록용)

`@remotion/sfx` 가 원격(https://remotion.media/*.wav)으로 가리키던 파일을 오프라인 렌더를 위해 그대로 내려받아 둔 것이다.

| 파일 | 원본 | 라이선스 |
|---|---|---|
| `whoosh.wav` | "Woosh" by 1bob — freesound.org/s/831936 | CC0 |
| `whip.wav` | "SWSH_Badminton Racquet_Recording_01_JW Audio" by JW_Audio — freesound.org/s/838766 | CC0 |
| `switch.wav` | "UI Audio - Switch 35" by kenney.nl | CC0 |

정점 위치(30fps 기준, `ShortsScene.tsx` 의 `SFX.peakFrames`): whoosh 70ms(2프레임), whip 20ms(1프레임), switch 120ms(4프레임).

## 2026-10-25 A/B 시험(spike/shorts-quality-ab)에서 추가 — kenney.nl, 모두 CC0

latent-spaces/brag 레포 `skills/brag/assets/sfx` 에 묶여 온 Kenney 팩(Interface Sounds·Impact Sounds·UI Audio)의 ogg 를 48kHz 스테레오 wav 로 바꾼 것. 고른 기준은 brag `sfx-analysis` 의 고역 위험 낮은 소리.

| 파일 | 원본 | 쓰임 | 정점(30fps) |
|---|---|---|---|
| `k_bong.wav` | interface/bong_001 | 항목 켜짐·흡수 | 0 |
| `k_drop2.wav` · `k_drop3.wav` | interface/drop_002 · drop_003 | 팝·카드 등장 | 0 |
| `k_click.wav` | interface/click_003 | 점 등장·체크 | 0 |
| `k_punch.wav` | impact/impactPunch_heavy_000 | 보상 타격(가장 큼) | 1 |
| `k_bell.wav` | impact/impactBell_heavy_000 | 보상 여운 | 0 |
| `k_clap.wav` | impact/impactPlank_medium_000 | 박수판 | 0 |
| `k_land.wav` | impact/impactSoft_medium_001 | 착지 | 0 |
| `k_glass.wav` | impact/impactGlass_light_001 | 방패 완성 | 0 |
| `k_key1.wav` · `k_key2.wav` | keyboard/keypress-003 · keypress-007 | 타자 | 0 |
