# 🎬 루나의 심야 서재 — 장르별 대표 BGA(시그니처 룸) 에셋 규격

이 디렉토리는 단곡·롱폼 유튜브 영상에 영구 고정으로 쓰는 장르별 심리스 루프 비디오(MP4)와 썸네일 소스(JPG)를 보관합니다.
곡 생성 시 `luna_engine.render_luna_video` 가 트랙 장르로 대표 BGA 를 찾아 음원과 합성하고(에셋이 없으면 커버 켄번즈로 폴백),
`upload_luna_to_youtube` 는 같은 장르의 썸네일을 1순위로 올립니다. 매번 Veo 로 유료 생성할 필요가 없습니다.

## 📁 장르 → 룸 매핑 (luna_engine.SIGNATURE_BGA_MAP / resolve_signature_bga 와 동기)

| 장르 키 | 매칭 키워드 | 루프 영상 | 썸네일 | 룸 컨셉 |
|---|---|---|---|---|
| lofi (핵심) | lofi, lo-fi, chillhop | `bga_lofi_study.mp4` | `thumb_lofi_cat.jpg` | 심야 책상 서재 — 앰버 스탠드, 빗방울 창, 머그잔 김 |
| piano (핵심) | piano | `bga_piano_moonlight.mp4` | `thumb_piano_cat.jpg` | 달빛 창가 피아노 — 인디고 달빛, 린넨 커튼, 캔들 |
| ambient (핵심) | ambient (dark-ambient 포함) | `bga_ambient_bedroom.mp4` | `thumb_ambient_cat.jpg` | 자정의 침실 — 딥 다크, 바닥 간접 취침등, 도시 야경 |
| sleep (핵심) | sleep, delta, meditation | `bga_sleep_sanctuary.mp4` | `thumb_sleep_cat.jpg` | 포근한 수면 안식처 |
| jazz (보관) | jazz | `bga_jazz_cafe.mp4` | `thumb_jazz_cat.jpg` | 심야 재즈 카페 |
| chill (보관) | chill, rnb, synth, city | `bga_chill_balcony.mp4` | `thumb_chill_cat.jpg` | 도심 야경 발코니 (R&B Chill·Synthwave·City Pop) |
| acoustic (보관) | acoustic, folk | `bga_acoustic_attic.mp4` | `thumb_acoustic_cat.jpg` | 햇살 다락방 서재 |

매칭되지 않는 장르는 lofi 룸으로 폴백합니다. 모든 룸에 공통으로 '잠자는 삼색 고양이'(채널 배너·프로필 동일)가 들어갑니다.

## 🛠️ 기술 규격 (Production Spec)
* **해상도**: 1920×1080 (1080p) 또는 3840×2160 (4K), 16:9 비율
* **프레임레이트**: 24fps 또는 30fps
* **길이**: 15초 ~ 20초 (시작과 끝이 부드럽게 연결되는 Seamless Loop)
* **비디오 코덱**: H.264 (libx264), yuv420p
* **오디오 스트림**: 무음(Silent) 또는 오디오 트랙 없음

---

## 🖼️ 썸네일 / 루프 소스 이미지 (배너 싱크 삼색 고양이)
* `thumb_lofi_cat.jpg` — Lo-Fi 서재 (bga_lofi_study.mp4 의 소스이자 Lo-Fi·Chill 영상 썸네일)
* `thumb_piano_cat.jpg` — 달빛 피아노 (bga_piano_moonlight.mp4 소스, Piano 썸네일)
* `thumb_ambient_cat.jpg` — 어두운 침실 (bga_ambient_bedroom.mp4 소스, Ambient/Sleep 썸네일)

* `thumb_sleep_cat.jpg` / `thumb_jazz_cat.jpg` / `thumb_chill_cat.jpg` / `thumb_acoustic_cat.jpg` — 각 룸 소스 겸 썸네일

JPG 7장은 저장소에 커밋되어 있습니다(Antigravity brain 캐시 디렉터리는 세션이 끝나면 사라질 수 있으므로 원본 사본을 여기 둠).
루프 mp4 는 gitignore 대상이며 `python scripts/generate_signature_bga_assets.py` 로 재생성합니다(기존 파일은 건너뜀, `--force` 로 덮어쓰기).
새 체크아웃에서는 이 명령을 먼저 실행해야 대표 BGA 합성이 동작합니다(없으면 커버 켄번즈 폴백).

## 📋 운영 기록
* 2026-10-11 16:00 — 3개 루프 에셋 생성(16s, 1080p30, zoompan 사인 줌 1.000→1.028→1.000)
* 2026-10-11 16:24 — 10/11~10/16 예약 영상 6편을 시그니처 BGA 로 교체 업로드(구 영상 삭제) · 1시간 컴필레이션 HzfRkSiTyeI 업로드(10/11 22:00 KST)
* 2026-10-11 17:01 — sleep/jazz/chill/acoustic 룸 4개 추가, `render_luna_video` 가 장르별 대표 BGA 를 기본 합성 경로로 사용
* 2026-10-11 17:3x — 에셋 7개 전부 limited(tv) 색범위로 재생성, 렌더러 스트림 복사 우선·`-t` 길이 고정
