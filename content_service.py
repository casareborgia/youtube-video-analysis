"""콘텐츠 생성, 검토 및 편집 가능한 초안(Draft) 관리 모듈.

작업지시서 Phase 3 요구사항 충족:
- marketing.generate_threads_x() 결과를 통합 초안 모델(social_jobs, social_job_items)로 변환
- 플랫폼 표준화 (threads, x 표준화 및 twitter 호환 매핑)
- 플랫폼별 길이 제한 (Threads: 500자, X: 280자) 및 빈 콘텐츠 서버 검증
- 단일 게시물 및 타래(Thread) 편집 가능한 초안 저장/수정
- 댓글·답글 초안 생성 함수 (원문, 게시물 맥락, 선택 톤 입력)
- 초안을 발행 요청(publish payload)으로 손실 없이 변환
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import llm_client
import social_store

# 플랫폼별 최대 글자수 제한
PLATFORM_CHAR_LIMITS = {
    "threads": 500,
    "x": 280,
}

SUPPORTED_PLATFORMS = {"threads", "x"}

REPLY_TONE_PROMPTS = {
    "friendly": "친근하고 따뜻하며 공감대를 형성하는 구어체 톤",
    "professional": "전문적이고 신뢰감 넘치며 객관적인 인사이트를 제공하는 비즈니스 톤",
    "witty": "센스 있고 위트 넘치며 스크롤을 멈추게 하는 유쾌한 톤",
    "empathetic": "상대방의 고민과 상황에 깊이 공감하고 위로와 지지를 전하는 톤",
    "contrarian": "정중하지만 기존 통념을 깨는 색다른 관점을 제시하여 토론을 유도하는 톤",
}


def normalize_platform(platform: str) -> str:
    """플랫폼 명칭 표준화 ('twitter' -> 'x', 소문자 트림)"""
    plat = (platform or "").strip().lower()
    if plat == "twitter":
        plat = "x"
    if plat not in SUPPORTED_PLATFORMS:
        raise ValueError(f"지원되지 않는 플랫폼입니다: '{platform}'. (지원 플랫폼: threads, x)")
    return plat


def validate_post_content(platform: str, text: str) -> str:
    """
    게시물 내용 유효성 검증.
    - 빈 콘텐츠(공백 포함) 차단
    - 플랫폼별 최대 글자수 초과 차단
    """
    plat = normalize_platform(platform)
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError(f"{plat.upper()} 게시물 본문은 비어 있을 수 없습니다.")

    limit = PLATFORM_CHAR_LIMITS[plat]
    char_count = len(clean_text)
    if char_count > limit:
        raise ValueError(
            f"{plat.upper()} 게시물 글자수 제한을 초과했습니다 (최대: {limit}자, 현재: {char_count}자)."
        )
    return clean_text


def create_draft_from_marketing(
    marketing_data: Dict[str, Any],
    actor_account_id: str,
    dry_run: bool = True,
    store: Optional[social_store.SocialStore] = None,
) -> Dict[str, Any]:
    """
    marketing.generate_threads_x() 생성 결과를 통합 초안(social_jobs + social_job_items)으로 변환 및 저장.
    """
    raw_platform = marketing_data.get("platform", "threads")
    platform = normalize_platform(raw_platform)

    raw_posts = marketing_data.get("posts", [])
    if not raw_posts:
        raise ValueError("초안 생성을 위한 posts 항목이 비어 있습니다.")

    validated_items: List[Dict[str, Any]] = []
    for idx, p in enumerate(raw_posts):
        text = p.get("text", "") if isinstance(p, dict) else str(p)
        clean = validate_post_content(platform, text)
        validated_items.append({
            "item_index": idx,
            "content": clean,
            "media_url": p.get("media_url", "") if isinstance(p, dict) else "",
            "status": "pending",
        })

    is_thread = len(validated_items) > 1
    st = store or social_store.SocialStore()

    content_payload = {
        "topic": marketing_data.get("topic", ""),
        "summary": marketing_data.get("summary", ""),
        "hook_formula": marketing_data.get("hook_formula", ""),
        "hook_score": marketing_data.get("hook_score", 0),
        "hashtags": marketing_data.get("hashtags", []),
        "item_count": len(validated_items),
        "format": "thread" if is_thread else "single",
        "source": "marketing_generator",
    }

    job = st.create_job(
        platform=platform,
        job_type="publish",
        actor_account_id=actor_account_id,
        dry_run=dry_run,
        content_payload=content_payload,
    )
    job_id = job["job_id"]

    st.add_job_items(job_id, validated_items)
    items = st.get_job_items(job_id)

    return {
        "job": job,
        "items": items,
    }


def create_manual_draft(
    platform: str,
    posts: List[str],
    actor_account_id: str,
    dry_run: bool = True,
    topic: str = "",
    store: Optional[social_store.SocialStore] = None,
) -> Dict[str, Any]:
    """사용자 직접 입력 단일/타래 초안 생성"""
    plat = normalize_platform(platform)
    if not posts:
        raise ValueError("게시물 목록이 비어 있습니다.")

    validated_items: List[Dict[str, Any]] = []
    for idx, text in enumerate(posts):
        clean = validate_post_content(plat, text)
        validated_items.append({
            "item_index": idx,
            "content": clean,
            "media_url": "",
            "status": "pending",
        })

    is_thread = len(validated_items) > 1
    st = store or social_store.SocialStore()

    job = st.create_job(
        platform=plat,
        job_type="publish",
        actor_account_id=actor_account_id,
        dry_run=dry_run,
        content_payload={
            "topic": topic,
            "item_count": len(validated_items),
            "format": "thread" if is_thread else "single",
            "source": "manual_entry",
        },
    )
    job_id = job["job_id"]
    st.add_job_items(job_id, validated_items)
    items = st.get_job_items(job_id)

    return {"job": job, "items": items}


def update_draft_item(
    job_id: str,
    item_index: int,
    new_content: str,
    store: Optional[social_store.SocialStore] = None,
) -> Dict[str, Any]:
    """초안(draft) 상태인 작업 항목 내용 수정"""
    st = store or social_store.SocialStore()
    job = st.get_job(job_id)
    if not job:
        raise ValueError(f"존재하지 않는 작업 ID입니다: {job_id}")

    if job["status"] != "draft":
        raise social_store.InvalidStateTransitionError(
            f"draft 상태의 초안만 내용을 수정할 수 있습니다 (현재: {job['status']})."
        )

    clean = validate_post_content(job["platform"], new_content)
    st.update_job_item(job_id=job_id, item_index=item_index, status="pending")

    # DB social_job_items의 content 갱신
    with st._connect() as conn:
        conn.execute(
            "UPDATE social_job_items SET content = ? WHERE job_id = ? AND item_index = ?",
            (clean, job_id, item_index),
        )

    items = st.get_job_items(job_id)
    return {"job": job, "items": items}


def generate_reply_draft(
    platform: str,
    original_post: str,
    post_context: Optional[str] = None,
    tone: str = "friendly",
    audience: Optional[str] = None,
) -> Dict[str, Any]:
    """
    원문, 게시물 맥락, 선택 톤을 기반으로 SNS 댓글·답글 초안 생성.
    """
    plat = normalize_platform(platform)
    clean_orig = (original_post or "").strip()
    if not clean_orig:
        raise ValueError("원문 게시물(original_post)은 비어 있을 수 없습니다.")

    tone_guide = REPLY_TONE_PROMPTS.get(tone, REPLY_TONE_PROMPTS["friendly"])
    limit = PLATFORM_CHAR_LIMITS[plat]

    system_prompt = f"""당신은 SNS 인게이지먼트 및 소통 전문 매니저입니다.
사용자가 제공한 원문 게시물(또는 댓글)에 대해 진정성 있고 소통을 활성화할 수 있는 최적의 답글(Reply)을 작성하세요.

[규칙]
1. 플랫폼: {plat.upper()} (최대 글자수: {limit}자 엄격 준수)
2. 톤앤매너: {tone_guide}
3. 절대 단순한 기계적 반응(예: '감사합니다')에 그치지 말고, 맥락에 맞는 추가 질문이나 핵심 공감을 담아 대화를 이어가세요.
4. 반드시 아래 JSON 형식으로만 응답하세요.
{{
  "reply": "작성된 답글 내용",
  "tone": "{tone}",
  "reasoning": "이 답글을 제안한 이유"
}}"""

    user_msg = f"[원문 게시물/댓글]\n{clean_orig[:1500]}\n"
    if post_context:
        user_msg += f"\n[게시물 배경 맥락]\n{post_context[:1000]}\n"
    if audience:
        user_msg += f"\n[대상 청중/페르소나]\n{audience}\n"

    try:
        data, _raw = llm_client.call_llm_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=1024,
            temperature=0.7,
        )
        reply_text = data.get("reply", "").strip() if isinstance(data, dict) else ""
        if not reply_text:
            reply_text = _fallback_reply_text(clean_orig, plat, tone)
    except Exception:
        reply_text = _fallback_reply_text(clean_orig, plat, tone)

    # 글자수 초과 시 안전 절삭
    if len(reply_text) > limit:
        reply_text = reply_text[: limit - 3] + "..."

    return {
        "platform": plat,
        "reply": reply_text,
        "tone": tone,
        "char_count": len(reply_text),
        "max_limit": limit,
    }


def _fallback_reply_text(original: str, platform: str, tone: str) -> str:
    """LLM 실패 시 기본 생성 답글"""
    if tone == "professional":
        return f"좋은 인사이트 공유 감사드립니다. 공유해주신 내용 중 핵심 포인트에 깊이 공감합니다! ({platform.upper()})"
    elif tone == "witty":
        return f"이건 저장해두고 계속 봐야겠네요! 핵심을 제대로 짚으셨습니다 👍"
    else:
        return f"공감 가는 좋은 글이네요! 덕분에 많이 배우고 갑니다 😊"


def convert_draft_to_publish_request(
    job_id: str,
    approve: bool = True,
    store: Optional[social_store.SocialStore] = None,
) -> Dict[str, Any]:
    """
    초안(draft)을 승인 및 발행 요청 페이로드(publish payload)로 손실 없이 변환.
    Phase 3 완료 조건 충족.
    """
    st = store or social_store.SocialStore()
    job = st.get_job(job_id)
    if not job:
        raise ValueError(f"존재하지 않는 작업 ID: {job_id}")

    items = st.get_job_items(job_id)
    if not items:
        raise ValueError(f"작업에 하위 항목이 없습니다: {job_id}")

    # 승인 처리
    if approve and job["status"] == "draft":
        job = st.transition_job_status(job_id, "approved")

    posts = [item["content"] for item in items]
    # 모든 항목 유효성 재확인
    for p in posts:
        validate_post_content(job["platform"], p)

    return {
        "job_id": job_id,
        "platform": job["platform"],
        "actor_account_id": job["actor_account_id"],
        "job_type": job["job_type"],
        "dry_run": bool(job["dry_run"]),
        "status": job["status"],
        "approved_at": job["approved_at"],
        "posts": posts,
        "items": items,
        "content_payload": job["content_payload"],
    }
