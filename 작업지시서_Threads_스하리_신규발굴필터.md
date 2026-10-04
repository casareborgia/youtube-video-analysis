# Threads 스하리 신규 발굴 필터 작업지시서

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 작업명 | Threads 스하리 신규 발굴 모드 및 기존 관계 자동 제외 |
| 프로젝트 | `유튜브 영상분석실습` |
| 작성일 | 2026-10-04 |
| 작업 브랜치 | `docs/engagement-new-audience-filter` |
| 기준 구현 | `services/engagement_discovery.py`, `engagement_automation.py`, `social_store.py`, `app.py`, `static/index.html`, `static/app.js` |
| 최종 목표 | 스하리 탐색 쿼터를 신규 계정에 우선 사용하고, 기존 팔로워·기존 상호작용 계정·내 계정은 탐색 및 실행 단계에서 자동 제외 |

이 문서는 현재 구현을 기준으로 한 개발 지시서다. “기존 팔로워 제외”는 Threads 공식 API가 실제 팔로워 계정 전체를 제공하는지에 따라 정확도가 달라지므로, 확인 가능한 관계 신호를 누적해 제외하는 방식으로 구현한다.

## 2. 배경과 제품 원칙

스하리 탭의 목적은 기존 관계 관리가 아니라 신규 계정 발견과 첫 상호작용이다. 따라서 기본 동작은 다음과 같아야 한다.

1. 신규 발굴 모드를 기본으로 활성화한다.
2. 내 계정, 이미 스하리를 실행한 계정, 내 게시물에 댓글·답글을 남긴 계정, 내가 답글을 보낸 계정은 후보에서 제외한다.
3. 같은 계정의 다른 게시물이 발견되어도 계정 단위로 제외한다.
4. 탐색 단계에서 걸러졌더라도 실행 직전에 다시 검사한다.
5. 기존 관계 관리는 댓글·답글 관리 탭에서 처리한다.
6. 판별 근거가 없는 계정을 “팔로워가 아님”으로 단정하지 않는다. UI에는 `신규 후보` 또는 `기존 관계 신호 없음`으로 표시한다.

## 3. 현재 구현 분석

### 3.1 이미 구현된 기능

- `EngagementDiscoveryService.discover_targets()`가 Threads/X 후보를 발굴한다.
- Threads 후보는 내 최근 게시물의 답글 작성자와 정적 시드 목록을 섞어 만든다.
- 본인 사용자명과 동일한 후보는 제외한다.
- `social_dedup_keys`를 이용해 일부 중복 동작을 확인한다.
- `/api/engagement/discover`가 탐색 목록을 반환한다.
- `/api/engagement/auto-run`이 선택 대상에 좋아요·리포스트·팔로우를 실행한다.
- 스하리 UI에서 플랫폼, 주제, 인원수, 동작을 선택하고 드라이런 또는 실제 실행을 요청할 수 있다.
- `engagement_events`와 일일 한도 로직이 실제 실행의 중복과 과다 실행을 제한한다.
- 댓글·답글 서비스가 댓글 작성자의 `username`을 수집하며, 답글 작업의 `content_payload.author`에 작성자 정보를 저장한다.

### 3.2 현재 요구사항과의 격차

| 구분 | 현재 동작 | 문제 | 필요한 변경 |
|---|---|---|---|
| 중복 판정 단위 | `like + post_id` 중심 | 같은 계정의 다른 글은 다시 후보가 됨 | 플랫폼·실행 계정·대상 계정 단위 관계 판정 추가 |
| 상호작용 범위 | 탐색 시 좋아요 완료 여부만 확인 | 팔로우, 리포스트, 답글 이력이 제외 근거에 반영되지 않음 | 모든 관계 형성 액션을 합산 |
| 댓글 작성자 | 내 글의 댓글 작성자를 후보로 추가 | 기존 인맥을 신규 후보로 다시 노출 | 신규 발굴 모드에서는 제외 신호로 사용 |
| 시드 보충 | 후보 부족 시 시드 목록을 바로 추가 | 앞 단계의 중복·본인·관계 필터를 우회 | 모든 후보를 하나의 공통 필터에 통과시킨 뒤 제한 수 적용 |
| API 옵션 | 제외 옵션 없음 | UI 선택을 서버가 검증할 수 없음 | `exclude_existing_relationships`와 `actor_account_id` 추가 |
| 클라이언트 지정 대상 | `auto-run`에 전달된 목록을 그대로 실행 | 탐색 필터를 우회해 기존 관계 계정에 실행 가능 | 실행 직전 서버 재검증 및 제외 결과 반환 |
| 제외 사유 | 반환하지 않음 | 사용자가 왜 빠졌는지 확인할 수 없음 | 사유 코드와 집계값 반환 |
| 팔로워 데이터 | 영속 캐시 없음 | 재시작 후 댓글·관계 신호를 일관되게 활용하기 어려움 | 관계 캐시 테이블과 갱신 서비스 추가 |
| 테스트 | 정상 탐색과 드라이런 위주 | 계정 단위 제외, 시드 우회, 실행 직전 차단을 검증하지 않음 | 단위·API·회귀 테스트 추가 |

### 3.3 반드시 수정할 현재 결함

`discover_targets()`의 현재 흐름은 먼저 후보를 일부 필터링한 다음, 부족한 수를 `ACTIVE_THREADS_SEED_TARGETS`에서 다시 채운다. 보충 단계에서는 본인·상호작용 여부를 재검사하지 않으므로 제외 대상이 다시 들어갈 수 있다. 후보 원천별로 따로 필터하지 말고, 모든 원천을 합친 후 공통 판정기를 한 번 적용해야 한다.

또한 현재 `target_id`는 `post_id`를 우선 사용하며 `action="like"`만 조회한다. 이 방식은 게시물 중복 방지에는 일부 효과가 있지만 기존 관계 계정 제외에는 맞지 않는다. 계정 관계용 키와 게시물 액션용 키를 분리해야 한다.

## 4. 외부 API 제약과 판단 기준

Meta Threads 공식 API에서 확인 가능한 답글 작성자와 인사이트는 활용하되, 팔로워 수치와 팔로워 계정 목록을 같은 것으로 취급하지 않는다. 구현 시작 시 공식 문서를 다시 확인하고 다음 순서로 판단한다.

1. 공식 API에 인증 계정의 팔로워 사용자 목록 엔드포인트가 실제로 제공되고 앱 권한으로 사용 가능하면, 커서 페이지네이션으로 동기화한다.
2. 팔로워 수치만 제공되고 사용자 목록은 제공되지 않으면, 전체 팔로워를 완전 판별한다고 표시하지 않는다.
3. 공식 API로 얻을 수 없는 목록을 비공식 엔드포인트 호출이나 보호 장치 우회로 수집하지 않는다.
4. 웹 보조 방식이 필요하면 사용자가 명시적으로 활성화한 전용 브라우저 세션에서만 사용하고, 로그인·CAPTCHA·보안 확인을 우회하지 않는다.

구현 및 검토 기준 문서:

- Meta 공식 Threads API 문서 컬렉션: <https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api>
- Meta 공식 Threads 답글 목록 요청 예시: <https://www.postman.com/meta/threads/request/2oj5hld/get-a-list-of-all-a-user-s-replies>

## 5. 목표 사용자 흐름

1. 사용자가 스하리 탭을 연다.
2. `기존 팔로워 및 기존 상호작용 유저 제외 (신규 발굴 모드)`가 기본 선택되어 있다.
3. 사용자가 주제와 발굴 인원수를 선택하고 탐색한다.
4. 서버는 모든 후보 원천을 수집하고 본인·기존 관계·기존 실행·중복 계정을 제거한다.
5. UI는 최종 후보 수와 제외 집계를 표시한다. 예: `12명 확인 · 기존 관계 5명 제외 · 중복 2명 제외 · 신규 후보 5명`.
6. 각 후보 카드에는 `신규 후보`, `이전 상호작용 없음`, `탐색 경로`를 표시한다.
7. 사용자가 드라이런을 실행하면 서버가 같은 정책으로 다시 검사한다.
8. 실제 실행 직전에도 다시 검사하고, 그 사이 관계 신호가 생긴 계정은 `skipped_existing_relationship`로 건너뛴다.
9. 제외 모드를 끈 경우 UI와 확인 대화상자에 기존 관계 계정이 포함될 수 있음을 표시한다.

## 6. 관계 판정 정책

### 6.1 식별자 정규화

관계 판정은 화면 표시명 대신 안정적인 계정 식별자를 우선 사용한다.

- 우선순위: 플랫폼 사용자 ID → 소문자로 정규화한 사용자명
- 사용자명은 앞의 `@` 제거, 앞뒤 공백 제거, 소문자 변환
- 플랫폼을 키에 반드시 포함
- Threads와 X의 같은 사용자명은 서로 다른 계정으로 처리
- 내 계정의 사용자 ID와 사용자명을 모두 보관해 본인 계정 제외에 사용

### 6.2 제외 신호

신규 발굴 모드에서 아래 신호 중 하나라도 있으면 제외한다.

| 우선순위 | 제외 사유 코드 | 조건 | 기본 보존 기간 |
|---|---|---|---|
| 1 | `self_account` | 대상이 실행 계정 본인 | 영구 |
| 2 | `known_follower` | 공식 API 또는 사용자가 가져온 신뢰 가능한 목록에서 팔로워로 확인 | 마지막 확인 후 30일, 재동기화 시 갱신 |
| 3 | `followed_or_following` | 팔로우 성공 이력 또는 현재 팔로우 관계 확인 | 영구 또는 관계 재확인 시 갱신 |
| 4 | `engaged_before` | 좋아요·리포스트·답글·팔로우 성공 이력 존재 | 기본 영구 |
| 5 | `commented_on_my_content` | 내 게시물의 댓글·답글 작성자로 확인 | 마지막 상호작용 후 180일 |
| 6 | `replied_by_me` | 내가 해당 사용자의 댓글에 답글을 보낸 이력 | 기본 영구 |
| 7 | `blocked_or_suppressed` | 수동 제외, 차단, 오류 누적 등 운영 제외 목록 | 해제 전까지 |
| 8 | `duplicate_candidate` | 같은 탐색 결과에 같은 계정이 여러 번 등장 | 해당 탐색 요청 |

실패한 액션과 드라이런은 `engaged_before`로 승격하지 않는다. `reserved`는 동시 실행 방지를 위해 실행 중에는 제외하되, 실패로 종료되면 예약 관계 신호를 제거한다.

### 6.3 판정 결과 모델

내부 판정기는 다음 형태의 결과를 반환한다.

```json
{
  "excluded": true,
  "reason": "engaged_before",
  "evidence": ["follow:success", "reply:success"],
  "last_seen_at": 1791043200
}
```

외부 API 응답에는 개인정보를 과도하게 노출하지 않고 `reason`, `last_seen_at` 정도만 반환한다. 토큰, 쿠키, 원문 댓글 전문은 제외 통계에 포함하지 않는다.

## 7. 데이터 모델 변경

`social_store.py`의 스키마 버전을 올리고 다음 테이블을 추가한다.

```sql
CREATE TABLE social_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    actor_account_id TEXT NOT NULL,
    target_account_key TEXT NOT NULL,
    target_user_id TEXT,
    target_username TEXT,
    relationship_type TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'observed',
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(platform, actor_account_id, target_account_key, relationship_type, source)
);

CREATE INDEX idx_social_relationship_lookup
ON social_relationships(platform, actor_account_id, target_account_key, relationship_type);
```

필수 저장소 메서드:

- `upsert_relationship(...)`
- `list_relationships(...)`
- `get_relationship_evidence(...)`
- `has_existing_relationship(...)`
- `expire_relationships(now_ts)`
- `suppress_account(...)`
- `unsuppress_account(...)`

기존 `social_dedup_keys`는 액션 멱등성 보장에 계속 사용한다. 관계 판정 목적으로 문자열 접두사를 검색하는 방식은 사용하지 않는다. 기존 `engagement_events`의 성공 이력은 마이그레이션 시 `engaged_before` 관계로 백필한다. `social_jobs`의 답글 작업에서 대상 작성자를 신뢰할 수 있게 얻을 수 있는 경우 `replied_by_me`로 백필하되, 작성자 정보가 없는 행은 추측하지 않는다.

## 8. 서비스 구현 지시

### 8.1 관계 판정 서비스 추가

`services/social_relationship_service.py`를 추가한다.

책임:

- 계정 식별자 정규화
- 여러 관계 신호의 조회와 우선순위 판정
- 댓글·답글 수집 결과를 관계 캐시에 반영
- 스하리 성공 결과를 관계 캐시에 반영
- 만료된 관찰 신호 정리
- 제외 사유와 증거 반환

이 서비스는 HTTP 호출을 직접 수행하지 않는다. 공식 API 동기화는 별도 어댑터가 담당하고, 서비스는 정규화된 관계 이벤트만 받는다.

### 8.2 `EngagementDiscoveryService` 개편

`discover_targets()`에 다음 인자를 추가한다.

```python
def discover_targets(
    platform: str = "threads",
    topic: str = "스하리",
    limit: int = 10,
    exclude_existing_relationships: bool = True,
    actor_account_id: str = "",
) -> DiscoveryResult:
```

구현 순서:

1. 모든 후보 원천에서 요청 제한보다 넉넉하게 후보를 수집한다.
2. 후보별 플랫폼·계정 키를 정규화한다.
3. 본인 계정을 제거한다.
4. 동일 계정의 여러 게시물은 최신 또는 관련도 높은 게시물 하나만 남긴다.
5. 신규 발굴 모드이면 관계 판정 서비스를 호출한다.
6. 게시물 단위 액션 중복도 확인한다.
7. 필터를 통과한 후보에만 점수를 매기고 정렬한다.
8. 마지막에 `limit`을 적용한다.
9. 후보가 부족하더라도 필터를 우회해 채우지 않는다.

반환값에는 다음 정보를 포함한다.

```json
{
  "targets": [],
  "summary": {
    "scanned": 14,
    "included": 5,
    "excluded": 9,
    "excluded_by_reason": {
      "self_account": 1,
      "engaged_before": 4,
      "commented_on_my_content": 2,
      "duplicate_candidate": 2
    },
    "relationship_data_fresh_at": 1791043200
  }
}
```

기존 호출부 호환이 필요하면 내부에 `targets`만 반환하는 래퍼를 두거나 모든 호출부를 한 번에 명시적으로 변경한다. 조용히 반환 타입을 바꾸어 기존 테스트와 UI를 깨지 않는다.

### 8.3 후보 원천 수정

- 내 게시물의 댓글 작성자는 신규 후보 원천에서 제거하고 `commented_on_my_content` 관계 신호 입력으로 전환한다.
- 정적 시드 목록은 개발·데모 모드에서만 사용한다.
- 실제 운영 모드에서 정적 시드를 “실시간 피드”로 표시하지 않는다.
- 정적 시드의 URL과 게시물 ID가 실제 유효한지 보장할 수 없으므로 실제 실행 대상으로 자동 선택하지 않는다.
- 후보 원천이 없을 때는 빈 목록과 명확한 사유를 반환한다.

### 8.4 실행 직전 재검증

`/api/engagement/auto-run`은 클라이언트가 보낸 `targets`를 신뢰하지 않는다.

- `exclude_existing_relationships=true`이면 각 대상을 서버에서 다시 판정한다.
- 제외 대상은 실행 서비스에 넘기지 않는다.
- 결과에 `skipped_existing_relationship`과 사유 코드를 포함한다.
- 모든 대상이 제외되면 성공 응답 안에 `processed=0`, `skipped=N`을 반환한다.
- 실제 성공한 `follow`, `like`, `repost`, `reply`만 관계 테이블에 반영한다.
- 부분 실패 시 성공 대상만 반영한다.

## 9. API 변경

### 9.1 탐색 API

`GET /api/engagement/discover`

추가 쿼리:

- `exclude_existing_relationships: bool = true`
- `actor_account_id: str | None`

응답에 `summary`를 추가한다. 기존 `targets`, `count`, `platform`, `topic`은 유지한다.

### 9.2 자동 실행 API

`AutoEngagementRunRequest`에 다음 필드를 추가한다.

```python
exclude_existing_relationships: bool = True
```

서버는 실제 실행과 드라이런 모두 같은 관계 정책을 적용한다. UI가 옵션을 보내지 않아도 기본값은 `true`다.

### 9.3 관계 동기화 및 상태 API

필요한 경우 다음 API를 추가한다.

- `POST /api/engagement/relationships/sync`: 공식 API와 댓글 이력에서 관계 캐시 갱신
- `GET /api/engagement/relationships/status`: 마지막 동기화 시각, 원천별 계정 수, 오류 상태
- `POST /api/engagement/relationships/suppress`: 수동 제외 계정 등록
- `DELETE /api/engagement/relationships/suppress/{account_key}`: 수동 제외 해제

동기화는 읽기 작업이며 실제 스하리 액션을 수행하지 않는다.

## 10. UI 변경

`static/index.html`의 1단계 탐색 영역에 다음 체크박스를 추가한다.

```text
[✓] 기존 팔로워 및 기존 상호작용 유저 제외 (신규 발굴 모드)
```

요구사항:

- 기본 선택, 설정 유지 시 로컬 환경 설정에 저장
- 도움말: `확인 가능한 팔로워·댓글·답글·스하리 이력을 기준으로 제외합니다.`
- “기존 팔로워를 100% 판별” 같은 표현 사용 금지
- 탐색 결과 위에 스캔 수, 포함 수, 사유별 제외 수 표시
- 후보 카드에 `신규 후보` 배지 표시
- 관계 데이터가 오래됐으면 `관계 정보 마지막 갱신: ...` 표시
- 옵션을 끄면 경고색 안내와 실행 확인창에 `기존 관계 계정 포함 가능` 표시
- 실제 API 오류를 빈 신규 후보 목록으로 위장하지 말고 오류 상태를 별도로 표시

`static/app.js`는 탐색과 실행 요청 모두에 `exclude_existing_relationships`를 포함한다. 프런트에서만 필터하지 않는다.

## 11. 파일별 작업 범위

| 파일 | 작업 |
|---|---|
| `services/engagement_discovery.py` | 후보 원천 통합, 계정 단위 중복 제거, 관계 판정 적용, 요약 반환, 시드 우회 제거 |
| `services/social_relationship_service.py` | 신규 관계 판정·캐시 서비스 |
| `social_store.py` | 스키마 마이그레이션, 관계 CRUD·조회·만료 메서드 |
| `engagement_automation.py` | 성공 액션의 관계 이벤트 기록, 실패·예약 정리 |
| `reply_service.py` | 댓글 작성자와 성공한 답글 대상을 관계 캐시에 반영 |
| `app.py` | 요청 모델, 탐색/실행 API, 선택적 동기화 API 변경 |
| `static/index.html` | 신규 발굴 모드 체크박스, 제외 집계·갱신 상태 영역 |
| `static/app.js` | 옵션 전달, 응답 요약 렌더링, 실행 결과의 제외 사유 표시 |
| `tests/test_engagement_discovery.py` | 계정 단위 필터와 API 계약 테스트 확장 |
| `tests/test_social_relationship_service.py` | 관계 판정 우선순위·만료·정규화 테스트 추가 |
| `tests/test_social_ui_integration.py` | UI 기본값과 요청 필드 연결 검증 |
| `README.md` | 기능 범위, 정확도, 공식 API 제약, 운영 방법 기록 |

## 12. 테스트 지시

### 12.1 저장소·서비스 단위 테스트

- 같은 대상 계정의 다른 `post_id`가 하나만 남는다.
- 좋아요 성공 이력이 있는 계정은 다른 게시물로 발견되어도 제외된다.
- 팔로우·리포스트·답글 성공 이력도 제외된다.
- 실패와 드라이런 이력만 있는 계정은 제외되지 않는다.
- 내 게시물에 댓글을 단 계정은 신규 발굴 모드에서 제외된다.
- 옵션이 `false`이면 기존 관계 계정도 후보로 남는다.
- 사용자명의 대소문자, 앞의 `@`, 공백 차이로 필터를 우회할 수 없다.
- Threads와 X의 같은 사용자명은 서로 섞이지 않는다.
- 만료 전/후 관계 신호가 정책대로 판정된다.
- 시드 보충 단계가 제외 필터를 우회하지 않는다.
- 본인 계정은 옵션과 무관하게 항상 제외된다.

### 12.2 API 테스트

- 탐색 API 기본값이 `exclude_existing_relationships=true`다.
- 응답의 `count`가 `targets` 길이와 일치한다.
- `summary.scanned = summary.included + summary.excluded`가 성립한다.
- 자동 실행에 직접 주입한 기존 관계 대상도 서버에서 차단된다.
- 모든 대상이 제외된 요청은 외부 액션을 호출하지 않는다.
- 실제 성공 대상만 관계 테이블에 추가된다.
- 관계 판정 오류 시 실제 실행은 안전하게 중단하고 명확한 오류를 반환한다.

### 12.3 회귀 테스트

- 기존 드라이런, 승인 확인, 일일 한도, 멱등성 테스트가 계속 통과한다.
- 댓글·답글 목록과 답글 발행 흐름이 깨지지 않는다.
- 기존 `/api/engagement/discover` 응답의 핵심 필드는 유지된다.
- 토큰과 사용자 인증정보가 API 응답, 로그, 테스트 픽스처에 노출되지 않는다.

외부 계정 라이브 테스트는 별도 승인 후 소수 대상에만 수행한다. 자동 테스트는 가짜 어댑터와 임시 SQLite DB를 사용한다.

## 13. 인수 조건

다음 조건을 모두 충족해야 완료로 본다.

1. 신규 발굴 모드가 UI와 서버에서 기본 활성화된다.
2. 계정 단위 관계 판정이 게시물 단위 멱등성과 분리된다.
3. 좋아요·리포스트·팔로우·답글·댓글 작성자 신호가 관계 판정에 반영된다.
4. 모든 후보 원천이 같은 필터를 통과하며 후보 보충 로직이 필터를 우회하지 않는다.
5. 클라이언트 지정 대상도 실행 직전에 서버가 재검증한다.
6. 제외된 대상 수와 사유가 API와 UI에 표시된다.
7. 공식 API로 확인할 수 없는 팔로워를 확정적으로 판별한다고 표시하지 않는다.
8. 정적 시드가 운영 화면에서 실시간 사용자로 표시되거나 실제 자동 실행되지 않는다.
9. 관련 단위·API·회귀 테스트가 통과한다.
10. `.env`, 토큰, 쿠키, 브라우저 프로필 등 민감정보가 Git 스테이징에 포함되지 않는다.

## 14. 작업 순서와 보고 기준

1. Git 상태와 브랜치를 확인한다.
2. 공식 Threads API의 현재 권한과 팔로워 목록 제공 여부를 다시 확인해 결과를 기록한다.
3. 저장소 스키마와 관계 판정 서비스를 먼저 구현한다.
4. 탐색 서비스를 공통 필터 파이프라인으로 개편한다.
5. 실행 직전 재검증과 성공 이벤트 기록을 연결한다.
6. API와 UI를 연결한다.
7. 단위·API·회귀 테스트를 실행한다.
8. 변경 파일, 마이그레이션 내용, 테스트 결과, 남은 API 제약을 보고한다.
9. 사용자 승인 전에는 commit, push, merge를 실행하지 않는다.

작업 중 기존 미커밋 변경과 충돌하거나 덮어쓸 가능성이 생기면 임의로 해결하지 않고 사용자에게 대상 파일과 충돌 내용을 먼저 보고한다.
