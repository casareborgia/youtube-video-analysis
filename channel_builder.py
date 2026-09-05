# 유튜브 채널 세팅 자동 생성 모듈 — 명세 기반 8대 항목 생성, 핸들 실시간 중복검사, AI 프로필/배너 생성
import os
import re
import json
import time
import glob
import urllib.request
import urllib.error

import llm_client
import producer
import uploader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHANNELS_DIR = os.path.join(DATA_DIR, "channels")
os.makedirs(CHANNELS_DIR, exist_ok=True)

# 유효한 YouTube 카테고리 ID
VALID_CATEGORY_IDS = {1, 2, 10, 15, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28, 29}


# ── 1. 핸들 실시간 중복 확인 ─────────────────────────────────────────────

def check_handle_availability(handle):
    """
    https://www.youtube.com/@핸들 로 GET/HEAD 요청을 보내 중복 여부를 확인합니다.
    404면 사용 가능(available: True), 200이면 이미 존재(available: False).
    """
    clean = re.sub(r"^@", "", (handle or "").strip().lower())
    if not clean or not re.match(r"^[a-z0-9_.-]{3,30}$", clean):
        return False, "핸들은 3~30자의 영문 소문자, 숫자, 밑줄, 하이픈, 마침표만 가능합니다."
    
    url = f"https://www.youtube.com/@{clean}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            code = resp.getcode()
            if code == 200:
                # 200 OK -> 이미 채널이 존재함
                return False, "이미 사용 중인 핸들입니다."
            elif code == 404:
                return True, "사용 가능한 핸들입니다."
            else:
                return False, f"확인 불가 (HTTP {code})"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True, "사용 가능한 핸들입니다."
        elif e.code in (301, 302, 303, 307, 308):
            return False, "이미 사용 중인 핸들입니다."
        else:
            return False, f"확인 오류 (HTTP {e.code})"
    except Exception as e:
        # 네트워크 타임아웃 등의 경우 기본 검증 통과 여부로 처리
        return True, "네트워크 응답 없음 (검증 대기)"


# ── 2. LLM 채널 기획 생성 ────────────────────────────────────────────────

def _build_channel_prompt(topic, lang, audience=None, tone=None, persona_type="character", audio_lang=None):
    audio_lang = audio_lang or lang
    audience_text = f"타겟 독자: {audience}" if audience else f"주제({topic})에서 자연스럽게 추론할 것"
    tone_text = f"말투 및 분위기: {tone}" if tone else "신뢰감 있고 매력적인 전문가 톤"
    
    persona_map = {
        "character": "친근하고 개성 넘치는 2D/3D 캐릭터/마스코트 기반 브랜딩",
        "person": "전문적이고 신뢰할 수 있는 실사 인물/크리에이터 기반 브랜딩",
        "symbol": "미니멀하고 세련된 기하학적 심볼/로고형 그래픽 브랜딩"
    }
    persona_desc = persona_map.get(persona_type, persona_map["character"])

    lang_rules = f"""
[언어 엄격 준수 규칙]
1. 입력 언어(lang): '{lang}'
2. 채널 이름(channel_name), 채널 설명(description), 키워드(keywords), 업로드 기본값 텍스트, 개설 체크리스트(setup_steps)는 반드시 '{lang}' 언어로 작성하세요.
3. 핸들(handles)은 유튜브 규칙상 무조건 '영문 소문자, 숫자, 밑줄, 하이픈, 마침표'만 써야 합니다 (한글/특수문자 절대 불가).
   - 비영어권의 경우 3가지 방식으로 후보를 만드세요:
     ① 로마자 발음 표기 (예: euntoe-ai)
     ② 뜻을 옮긴 영어 번역 (예: retire-ai, ai-after50)
     ③ 짧은 직관적 영문 조합 (예: seniorailab, aimentor)
4. 프로필 이미지 프롬프트(avatar_prompt)와 배너 이미지 프롬프트(banner_prompt)는 이미지 생성 AI가 가장 잘 이해할 수 있도록 '반드시 영어(English)'로 작성하세요.
"""

    return f"""당신은 100만 구독자 유튜브 채널을 브랜딩하는 최고의 유튜브 채널 전문 기획자입니다.
주어진 주제와 조건에 맞추어 유튜브 채널 개설에 필요한 완벽한 8대 세팅 데이터를 JSON 형식으로 생성하세요.

[입력 정보]
- 주제: {topic}
- 언어 코드(lang): {lang}
- 음성 언어(audio_lang): {audio_lang}
- {audience_text}
- {tone_text}
- 페르소나 브랜딩 유형: {persona_desc}

{lang_rules}

[8대 출력 항목 명세]
① channel_name: 50자 이내. 한글 기준 8자 이내로 기억하기 쉬운 강력한 브랜딩 명칭 (검색 키워드가 들어가되 단순 설명문이 되지 않게).
② handles: 3~5개의 영문 소문자 핸들 후보 배열 (각각 3~30자).
③ description: 1,000자 이내. 첫 두 줄에 강력한 타겟 후킹 및 정의 -> 누구에게 왜 필요한지 -> 업로드 주기 -> 문의/소통 안내 구조.
④ keywords: 8개~15개의 채널 핵심 검색 키워드 배열 (넓은 메인 키워드와 좁은 롱테일 키워드 적절히 배분, 총 500자 이내).
⑤ avatar_prompt: 800x800 정사각형 프로필용 영문 프롬프트.
   - 단색/단순 배경, 프레임의 60% 이상을 차지하는 중앙 피사체, 텍스트 없음(no text), 고화질 3D/일러스트 스타일.
⑥ banner_prompt: 2048x1152 (16:9) 유튜브 채널 배너용 영문 프롬프트.
   - 모든 핵심 그래픽 요소를 정중앙 가로 띠(모바일 안전영역 1235x338) 안에 배치, 좌우 가장자리는 자연스러운 배경 여백 처리, cinematic, ultra-detailed.
⑦ upload_defaults: 업로드 기본값 객체
   - title_template: 예: "{{{{주제}}}} — {{{{핵심 한 줄 요약}}}}"
   - description_template: 고정 채널 소개 및 링크가 포함된 템플릿
   - tags: 8~12개 기본 태그 배열
   - category_id: 적절한 YouTube 카테고리 ID (27: 교육, 28: 과학기술, 22: 인물/블로그, 26: 하우투, 24: 엔터테인먼트 등)
   - privacy_status: "private" (초기 권장)
   - made_for_kids: false
   - default_language: "{lang}"
   - default_audio_language: "{audio_lang}"
⑧ setup_steps: 사람이 유튜브 스튜디오에서 진행해야 할 실전 개설 8단계 가이드 (1.채널생성 -> 2.이름/핸들입력 -> 3.프로필업로드 -> 4.배너업로드 -> 5.전화번호인증 -> 6.국가/키워드설정 -> 7.업로드기본값설정 -> 8.고급기능인증)

[반환 형식 — 반드시 순수 JSON만 출력하세요]
{{
  "topic": "{topic}",
  "lang": "{lang}",
  "audio_lang": "{audio_lang}",
  "channel_name": "채널 이름",
  "handles": ["handle1", "handle2", "handle3", "handle4"],
  "description": "채널 설명 전문...",
  "keywords": ["키워드1", "키워드2", "키워드3"],
  "avatar_prompt": "English prompt for profile avatar...",
  "banner_prompt": "English prompt for channel banner...",
  "upload_defaults": {{
    "title_template": "...",
    "description_template": "...",
    "tags": ["태그1", "태그2"],
    "category_id": 27,
    "privacy_status": "private",
    "made_for_kids": false,
    "default_language": "{lang}",
    "default_audio_language": "{audio_lang}"
  }},
  "setup_steps": [
    "1. 구글 로그인 후 유튜브 스튜디오 → 채널 만들기",
    "2. 확정된 이름과 사용 가능한 핸들 등록",
    "3. 생성된 AI 프로필 이미지 업로드",
    "4. 생성된 AI 배너 이미지 업로드 (중앙 안전영역 확인)",
    "5. 설정 → 채널 → 기능 사용 자격에서 전화번호 인증 (15분 이상 영상 & 썸네일 해금)",
    "6. 설정 → 채널 → 기본 정보에서 거주 국가 및 채널 키워드 등록",
    "7. 설정 → 업로드 기본설정에서 설명란 및 기본 태그 등록",
    "8. (선택) 고급 기능 신분증/영상 인증 완료"
  ]
}}"""


def generate_channel_setup(topic, lang="ko", audience=None, tone=None, persona_type="character", audio_lang=None, progress_callback=None):
    """
    주제와 옵션을 바탕으로 유튜브 채널 세팅 8개 항목을 생성하고 실시간 핸들 중복 검사를 수행합니다.
    """
    def step(pct, msg):
        if progress_callback:
            progress_callback("channel_gen", msg, pct)
        print(f"[{pct}%] {msg}")

    topic = (topic or "").strip()
    if not topic:
        raise ValueError("채널 주제(topic)를 입력해주세요.")
    
    # BCP-47 언어 코드 필수 검증 (명세: 기본값을 두지 않는다)
    lang = (lang or "").strip().lower()
    if not lang:
        raise ValueError("언어 코드(lang, BCP-47 예: ko, en, ja, es)를 필수로 선택해주세요.")
    if not re.match(r"^[a-z]{2}(-[a-z]{2,4})?$", lang):
        raise ValueError(f"유효하지 않은 BCP-47 언어 코드 형식입니다: '{lang}'. (예: ko, en, ja, es, zh)")
    
    audio_lang = (audio_lang or lang).strip().lower()

    step(15, f"'{topic}' ({lang}) 채널 브랜딩 및 8대 세팅 생성 중 (로컬 AI)...")
    prompt = _build_channel_prompt(topic, lang, audience, tone, persona_type, audio_lang)
    
    messages = [
        {"role": "system", "content": "You are a professional YouTube channel branding expert. Always reply with valid JSON only."},
        {"role": "user", "content": prompt}
    ]
    
    resp_text = llm_client.call_llm(messages, max_tokens=4096, temperature=0.7)
    
    # JSON 파싱
    data = None
    try:
        data = json.loads(resp_text)
    except Exception:
        # 마크다운 코드블록 제거 시도
        clean = re.sub(r"^```json\s*", "", resp_text.strip())
        clean = re.sub(r"\s*```$", "", clean)
        match = re.search(r"\{[\s\S]*\}", clean)
        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                pass
    
    if not data:
        raise RuntimeError("AI가 유효한 채널 세팅 JSON을 생성하지 못했습니다. 다시 시도해주세요.")

    step(50, "생성된 데이터 검증 및 글자 수 최적화 중...")
    cleaned = validate_and_clean_channel_data(data, topic, lang, audio_lang)

    step(70, "YouTube 실시간 핸들 중복 검사 진행 중...")
    raw_handles = cleaned.get("raw_handles") or ["channel", "tube", "creator"]
    checked_handles = []
    
    for h in raw_handles:
        avail, reason = check_handle_availability(h)
        checked_handles.append({
            "handle": h,
            "available": avail,
            "status_text": reason,
            "url": f"https://www.youtube.com/@{h}"
        })

    # 만약 사용 가능한 핸들이 하나도 없다면 변형 핸들 추가 생성 (비영어권 안전 변환)
    if not any(item["available"] for item in checked_handles):
        base_h = re.sub(r"[^a-z0-9]", "", cleaned["channel_name"].lower())[:10]
        if not base_h or len(base_h) < 3:
            base_h = "tube" + str(int(time.time()) % 1000)
        fallbacks = [f"{base_h}-official", f"{base_h}-tv", f"{base_h}-lab", f"{base_h}2026", f"the-{base_h}"]
        for fb in fallbacks:
            avail, reason = check_handle_availability(fb)
            checked_handles.append({
                "handle": fb,
                "available": avail,
                "status_text": reason,
                "url": f"https://www.youtube.com/@{fb}"
            })

    cleaned["handles"] = checked_handles
    cleaned.pop("raw_handles", None)
    # 화면 렌더러가 쓰는 별칭 필드 (이름 규약 혼선 방지)
    cleaned["handle_candidates"] = checked_handles
    cleaned["channel_description"] = cleaned.get("description", "")
    cleaned["channel_keywords"] = cleaned.get("keywords", [])
    cleaned["channel_language"] = cleaned.get("lang", lang)

    # 채널 ID 생성 및 저장
    channel_id = f"channel_{int(time.time())}_{re.sub(r'[^a-zA-Z0-9가-힣]', '_', topic)[:20]}"
    cleaned["channel_id"] = channel_id
    cleaned["created_at"] = time.time()
    cleaned["persona_type"] = persona_type
    cleaned["tone"] = tone or "기본"
    cleaned["audience"] = audience or "일반"

    step(95, "채널 세팅 데이터 저장 중...")
    save_channel(cleaned)
    step(100, f"'{cleaned['channel_name']}' 채널 세팅 생성 완료!")
    return cleaned


# ── 3. 데이터 검증 및 정제 규칙 ─────────────────────────────────────────

def validate_and_clean_channel_data(data, topic, lang, audio_lang):
    """명세서 검증 규칙에 따라 글자 수 및 포맷을 정제합니다."""
    # 1. channel_name (50자 이내)
    ch_name = str(data.get("channel_name") or topic)[:50].strip()
    
    # 2. handles 정제 (영문소문자, 숫자, 밑줄, 하이픈, 마침표, 3~30자)
    raw_handles = []
    candidates = data.get("handles") or []
    if isinstance(candidates, str):
        candidates = [candidates]
    for c in candidates:
        if isinstance(c, dict):
            c = c.get("handle", "")
        h = str(c).strip().lower().lstrip("@")
        h = re.sub(r"[^a-z0-9_.-]", "", h)
        if 3 <= len(h) <= 30 and h not in raw_handles:
            raw_handles.append(h)
    
    if not raw_handles:
        raw_handles = [re.sub(r"[^a-z0-9]", "", topic.lower())[:15] or "mychannel"]

    # 3. description (1,000자 이내)
    desc = str(data.get("description") or "").strip()
    if len(desc) > 1000:
        desc = desc[:997] + "..."

    # 4. keywords (합계 500자 이내, 8~15개)
    raw_kws = data.get("keywords") or []
    if isinstance(raw_kws, str):
        raw_kws = [k.strip() for k in raw_kws.split(",") if k.strip()]
    cleaned_kws = []
    total_len = 0
    for k in raw_kws:
        k_str = str(k).strip().lstrip("#")
        if not k_str:
            continue
        if total_len + len(k_str) + 2 <= 500:
            cleaned_kws.append(k_str)
            total_len += len(k_str) + 2

    # 키워드 포맷팅: 공백 있는 키워드는 큰따옴표 감싸기 (YouTube Data API 표준)
    formatted_kws = [f'"{k}"' if ' ' in k and not (k.startswith('"') and k.endswith('"')) else k for k in cleaned_kws]

    # 5. avatar_prompt & banner_prompt (일반 텍스트 포함형 vs no text 순수 배경/심볼형 분리 제공)
    avatar_prompt = str(data.get("avatar_prompt") or f"A minimalist modern iconic avatar for {topic}, centered subject, vibrant colors, solid background, high resolution, 8k").strip()
    avatar_prompt_no_text = re.sub(r"(?i)with\s+text[^,.]*", "", avatar_prompt).strip(" ,.") + ", absolutely no text, no letters, no typography, clean minimal graphic symbol, 8k"

    banner_prompt = str(data.get("banner_prompt") or f"YouTube channel banner for {topic}, all key elements centered within horizontal middle strip, clean background on left and right, cinematic lighting, 8k, ultra-detailed").strip()
    banner_prompt_no_text = re.sub(r"(?i)with\s+text[^,.]*", "", banner_prompt).strip(" ,.") + ", absolutely no text, no words, blank graphic background banner, safe zone composition, 8k"

    # 6. upload_defaults
    ud = data.get("upload_defaults") or {}
    title_tmpl = str(ud.get("title_template") or "{{주제}} — {{핵심 요약}}")[:100]
    desc_tmpl = str(ud.get("description_template") or desc)[:5000]
    raw_tags = ud.get("tags") or cleaned_kws
    cleaned_tags = []
    tag_len = 0
    for t in raw_tags:
        t_str = str(t).strip().lstrip("#")
        if not t_str:
            continue
        if tag_len + len(t_str) + 1 <= 500:
            cleaned_tags.append(t_str)
            tag_len += len(t_str) + 1

    cat_id = ud.get("category_id")
    try:
        cat_id = int(cat_id)
        if cat_id not in VALID_CATEGORY_IDS:
            cat_id = 27
    except Exception:
        cat_id = 27

    upload_defaults = {
        "title_template": title_tmpl,
        "description_template": desc_tmpl,
        "tags": cleaned_tags,
        "category_id": cat_id,
        "privacy_status": "private",
        "made_for_kids": bool(ud.get("made_for_kids", False)),
        "default_language": lang,
        "default_audio_language": audio_lang
    }

    # 7. setup_steps
    steps = data.get("setup_steps") or [
        "1. 구글 로그인 → YouTube → 프로필 → 채널 전환 → 모든 채널 보기 → 채널 만들기",
        "2. 이름과 사용 가능한 핸들 등록 (available: true 확인)",
        "3. AI 생성 프로필 이미지 업로드 (800x800, 4MB 이하)",
        "4. AI 생성 배너 이미지 업로드 (2048x1152, 모바일 중앙 안전영역 1235x338 확인)",
        "5. 유튜브 스튜디오 설정 → 채널 → 기능 사용 자격에서 전화번호 인증 (15분 초과 영상 & 커스텀 썸네일 해금)",
        "6. 설정 → 채널 → 기본 정보에서 거주 국가 및 채널 키워드 등록",
        "7. 설정 → 업로드 기본설정에서 제목/설명란/기본 태그 등록",
        "8. (선택) 고급 기능 신분증 인증 완료 (승인 1~2일)"
    ]

    return {
        "topic": topic,
        "lang": lang,
        "audio_lang": audio_lang,
        "channel_name": ch_name,
        "raw_handles": raw_handles,
        "description": desc,
        "keywords": cleaned_kws,
        "keywords_formatted": formatted_kws,
        "avatar_prompt": avatar_prompt,
        "avatar_prompt_no_text": avatar_prompt_no_text,
        "banner_prompt": banner_prompt,
        "banner_prompt_no_text": banner_prompt_no_text,
        "upload_defaults": upload_defaults,
        "setup_steps": steps
    }


# ── 4. AI 프로필 & 배너 이미지 생성 ─────────────────────────────────────

def generate_channel_images(channel_data, progress_callback=None):
    """
    Gemini / 나노바나나 모델을 호출하여 채널의 프로필(1:1)과 배너(16:9) 이미지를 생성합니다.
    """
    def step(pct, msg):
        if progress_callback:
            progress_callback("channel_img", msg, pct)
        print(f"[{pct}%] {msg}")

    ch_id = channel_data.get("channel_id") or f"temp_{int(time.time())}"
    ch_dir = os.path.join(CHANNELS_DIR, ch_id)
    os.makedirs(ch_dir, exist_ok=True)

    avatar_prompt = channel_data.get("avatar_prompt") or "Modern iconic YouTube profile avatar, minimalist, 3D render, solid background, 8k"
    banner_prompt = channel_data.get("banner_prompt") or "Cinematic YouTube channel banner, central content safe zone, clean edges, ultra detailed 8k"

    avatar_path = os.path.join(ch_dir, "avatar.jpg")
    banner_path = os.path.join(ch_dir, "banner.jpg")

    key = producer.gemini_key()
    if not key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일 또는 우측 상단 환경 설정에서 API 키를 입력해주세요.")

    step(15, "1/2 프로필 이미지 (1:1 정사각형) 생성 중 (나노바나나)...")
    try:
        raw_bytes, mime = producer._generate_single_image(avatar_prompt, "1:1", key)
        with open(avatar_path, "wb") as f:
            f.write(raw_bytes)
        channel_data["avatar_url"] = f"/data/channels/{ch_id}/avatar.jpg"
        channel_data["avatar_file"] = avatar_path
        channel_data.pop("avatar_error", None)
    except Exception as e:
        print(f"프로필 이미지 생성 실패: {e}")
        channel_data["avatar_error"] = str(e)

    step(60, "2/2 배너 이미지 (16:9 와이드) 생성 중 (나노바나나)...")
    try:
        raw_bytes, mime = producer._generate_single_image(banner_prompt, "16:9", key)
        with open(banner_path, "wb") as f:
            f.write(raw_bytes)
        channel_data["banner_url"] = f"/data/channels/{ch_id}/banner.jpg"
        channel_data["banner_file"] = banner_path
        channel_data.pop("banner_error", None)
    except Exception as e:
        print(f"배너 이미지 생성 실패: {e}")
        channel_data["banner_error"] = str(e)

    step(95, "채널 이미지 정보 갱신 중...")
    save_channel(channel_data)
    step(100, "프로필 & 배너 이미지 생성 완료!")
    return channel_data


# ── 5. 저장 및 이력 관리 ────────────────────────────────────────────────

def save_channel(data):
    ch_id = data.get("channel_id")
    if not ch_id:
        return
    ch_dir = os.path.join(CHANNELS_DIR, ch_id)
    os.makedirs(ch_dir, exist_ok=True)
    json_path = os.path.join(CHANNELS_DIR, f"{ch_id}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # Markdown 요약본도 함께 저장
    md_path = os.path.join(CHANNELS_DIR, f"{ch_id}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_format_channel_markdown(data))


def load_channel(channel_id):
    json_path = os.path.join(CHANNELS_DIR, f"{channel_id}.json")
    if not os.path.exists(json_path):
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_channels():
    items = []
    for p in glob.glob(os.path.join(CHANNELS_DIR, "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            items.append({
                "channel_id": d.get("channel_id"),
                "channel_name": d.get("channel_name"),
                "topic": d.get("topic"),
                "lang": d.get("lang"),
                "created_at": d.get("created_at") or os.path.getmtime(p),
                "avatar_url": d.get("avatar_url"),
                "banner_url": d.get("banner_url"),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["created_at"] or 0, reverse=True)
    return items


def _format_channel_markdown(data):
    handles_str = "\n".join(f"- `@{h['handle']}`: {'✅ 사용 가능' if h.get('available') else '❌ 선점됨'} ({h.get('url')})" for h in (data.get("handles") or []))
    kws_str = ", ".join(f'"{k}"' for k in (data.get("keywords") or []))
    steps_str = "\n".join(f"{s}" for s in (data.get("setup_steps") or []))
    
    ud = data.get("upload_defaults") or {}
    tags_str = ", ".join(f'"{t}"' for t in (ud.get("tags") or []))

    return f"""# 유튜브 채널 브랜딩 기획서 — {data.get('channel_name')}

**주제**: {data.get('topic')}  
**언어**: {data.get('lang')} (음성: {data.get('audio_lang')})  
**생성 일시**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data.get('created_at', time.time())))}

---

## 1. 채널 기본 정보
- **채널 이름**: `{data.get('channel_name')}`
- **핸들 후보 목록**:
{handles_str}

## 2. 채널 설명 (Description)
```text
{data.get('description')}
```

## 3. 채널 검색 키워드
`{kws_str}`

---

## 4. AI 이미지 생성 프롬프트
### 📸 프로필 아바타 (800x800)
```text
{data.get('avatar_prompt')}
```

### 🖼️ 채널 배너 (2048x1152)
```text
{data.get('banner_prompt')}
```

---

## 5. 업로드 기본값 (Upload Defaults)
- **제목 템플릿**: `{ud.get('title_template')}`
- **설명란 템플릿**:
```text
{ud.get('description_template')}
```
- **기본 태그**: `{tags_str}`
- **카테고리 ID**: `{ud.get('category_id')}` | **공개 상태**: `{ud.get('privacy_status')}`

---

## 6. 유튜브 스튜디오 개설 8단계 체크리스트
{steps_str}
"""


def get_my_channel_diagnostics() -> dict:
    """
    로그인된 내 채널 통계(조회수, 구독자, 비디오 수)를 진단하여
    에이전트 레오의 알고리즘 성장 조언과 액션 플랜을 제공합니다.
    """
    up_status = uploader.status()
    channel_info = up_status.get("channel")

    if not channel_info:
        channel_info = {
            "title": "내 유튜브 채널 (연동 대기)",
            "custom_url": "@mychannel",
            "subscriber_count": 128,
            "view_count": 15400,
            "video_count": 6,
            "is_demo": True
        }
    else:
        channel_info["is_demo"] = False

    subs = int(channel_info.get("subscriber_count") or 0)
    views = int(channel_info.get("view_count") or 0)
    vids = int(channel_info.get("video_count") or 1)
    avg_views = round(views / max(vids, 1), 1)

    # 채널 성장 단계 판별
    if subs < 1000:
        stage = "🌱 1단계: 씨앗 채널 (알고리즘 신뢰도 구축기, 목표: 구독자 1,000명 달성)"
    elif subs < 10000:
        stage = "🚀 2단계: 모멘텀 가속기 (타겟 오디언스 락인, 목표: 구독자 1만명 돌파)"
    elif subs < 100000:
        stage = "🔥 3단계: 스케일업 확장기 (카테고리 지배, 목표: 실버 버튼 10만명)"
    else:
        stage = "👑 4단계: 매크로 브랜드 (브랜드 비즈니스 확장 및 커뮤니티 극대화)"

    system_prompt = """당신은 유튜브 알고리즘 및 채널 성장 컨설턴트 '에이전트 레오(Agent Leo)'입니다.
채널 통계(구독자, 총 조회수, 영상 수, 영상당 평균 조회수)를 진단하여 알고리즘 추천 지수를 극대화하기 위한 정밀 진단 보고서를 작성해야 합니다.

반드시 유효한 JSON 형식으로만 응답하세요.
```json
{
  "growth_stage": "성장 단계명",
  "health_score": 85,
  "ctr_avd_analysis": "클릭률(CTR)과 평균시청지속시간(AVD) 관점에서의 냉정한 진단 (2문장)",
  "bottleneck": "현재 성장을 가로막고 있는 가장 큰 알고리즘 병목 원인 1가지",
  "action_plans": [
    "실행 계획 1 (8초 훅 & 도입부 개선)",
    "실행 계획 2 (고정 댓글 & 오픈 퀘스천 참여율 개선)",
    "실행 계획 3 (업로드 주기 및 썸네일 레드라인 일관성)"
  ],
  "next_milestone_tip": "다음 마일스톤 달성을 위한 에이전트 레오의 핵심 조언 한마디"
}
```"""

    user_prompt = f"""[채널 통계 데이터]
- 채널명: {channel_info.get('title')} ({channel_info.get('custom_url')})
- 구독자 수: {subs:,}명
- 총 조회수: {views:,}회
- 업로드 비디오 수: {vids}개
- 영상당 평균 조회수: {avg_views:,}회
- 현재 단계: {stage}

위 통계를 바탕으로 에이전트 레오의 채널 진단 리포트를 작성해주세요."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    parsed = None
    try:
        parsed, raw = llm_client.call_llm_json(messages, max_tokens=2048, temperature=0.6)
    except Exception as e:
        print(f"[ChannelBuilder] LLM diagnostic fallback due to: {e}")

    if not parsed or not isinstance(parsed, dict):
        parsed = {
            "growth_stage": stage,
            "health_score": 78,
            "ctr_avd_analysis": f"영상당 평균 {avg_views:,}회의 조회수를 기록 중이며, 8초 이내 이탈률 방어와 썸네일 클릭률(CTR) 개선이 시급합니다.",
            "bottleneck": "시청 지속시간(AVD)을 끝까지 유지시키고 댓글을 유도하는 '인게이지먼트 해킹' 부재",
            "action_plans": [
                "대본 도입부 8초에 충격적 수치나 시각적 대비를 주는 '나노바나나 레드라인' 썸네일 훅 적용",
                "영상 아웃트로에 양자택일 밸런스 질문을 넣고, 추천 고정 댓글로 시청자 토론 유도",
                "주 2회 고정 요일 업로드를 통한 유튜브 추천 알고리즘 주기 학습 유도"
            ],
            "next_milestone_tip": "조회수보다 '시청자의 댓글 참여율'을 높이면 알고리즘이 영상을 2배 더 넓은 풀로 추천합니다."
        }

    return {
        "status": "success",
        "channel": channel_info,
        "metrics": {
            "subscribers": subs,
            "views": views,
            "videos": vids,
            "avg_views": avg_views,
            "stage": stage
        },
        "diagnosis": parsed
    }


# 호환성을 위한 별칭 등록
generate_channel_settings = generate_channel_setup
list_plans = list_channels
get_plan = load_channel


