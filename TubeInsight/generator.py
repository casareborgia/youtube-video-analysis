# 분석 데이터 기반 신규 콘텐츠 기획 — 8초 씬 대본 · AI 영상 프롬프트 · 나노바나나 레드라인 이미지 프롬프트
import os
import re
import json
import time
import glob

import llm_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PLANS_DIR = os.path.join(DATA_DIR, "plans")
ANALYSES_DIR = os.path.join(DATA_DIR, "analyses")
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge")
os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
os.makedirs(PLANS_DIR, exist_ok=True)

DEFAULT_REFERENCE_ID = "ws1Clj0vOAM"
SCENE_SECONDS = 8          # 기본값 — 기획별로 scene_seconds 로 덮어씀 (쇼츠 8초 / 미드폼 15초 / 롱폼 20초)
CHUNK_SIZE = 8             # 씬이 많을 때 LLM 호출을 나누는 단위 (출력 잘림 방지)


def narration_bounds(secs):
    """씬 길이(초)에 맞는 나레이션 글자 수 (하한, 상한, 경고 기준). 실측 TTS 속도 약 7자/초 기준."""
    return int(secs * 5.2), int(secs * 6.6), int(secs * 8.5)

STAGE_NAMES = [
    ("도입", "The Setup — 기대를 심고 곧바로 반전으로 시선을 붙잡음"),
    ("갈등", "The Crisis — 문제의 스케일과 본질을 구체적 수치로 보여줌"),
    ("난제", "The Dilemma — 왜 쉽게 해결할 수 없는지 딜레마 제시"),
    ("반전", "The Response — 역발상 해법과 구체적 근거"),
    ("여운", "The Critique — 현실에 대한 통찰과 질문으로 마무리"),
]

DEFAULT_REDLINE_STYLE = {
    "base": "realistic 3D render, miniature diorama, matte materials, soft studio lighting, soft ambient occlusion",
    "figures": "faceless white mannequin workers in white protective suits",
    "annotation": "thin red engineering-diagram overlay, single red color, technical manual aesthetic",
}
DEFAULT_REDLINE_CONSTRAINTS = [
    "모든 텍스트는 정확한 철자로",
    "지정한 텍스트 외 어떤 글자도 넣지 말 것",
    "주석선은 실제 대상을 정확히 가리킬 것",
]

ASPECT_GUIDE = {
    "16:9": "16:9 가로 롱폼 — 와이드 시네마틱 구도, 좌우 여백을 활용한 단면·부감 컷어웨이",
    "9:16": "9:16 세로 쇼츠 — 피사체를 화면 중앙 세로축에 배치, 상단은 훅 문구·하단은 자막 공간을 비워 둠, high-angle/isometric",
}


# ── 유틸 ────────────────────────────────────────────────────────────────

def _llm(messages, max_tokens=4096):
    return llm_client.call_llm(messages, max_tokens=max_tokens, temperature=0.75)


def _llm_json(messages, max_tokens=4096):
    return llm_client.call_llm_json(messages, max_tokens=max_tokens, temperature=0.5)


def _time_range(i, secs=SCENE_SECONDS):
    s, e = (i - 1) * secs, i * secs
    return f"{s // 60:02d}:{s % 60:02d} ~ {e // 60:02d}:{e % 60:02d}"


def stage_plan(num_scenes):
    """씬 수에 맞춰 5단계 플롯을 씬 번호 구간으로 배분합니다. 예) 6씬 → 1 / 2 / 3-4 / 5 / 6"""
    plan = []
    for k, (name, desc) in enumerate(STAGE_NAMES):
        start = round(k * num_scenes / 5) + 1
        end = round((k + 1) * num_scenes / 5)
        if end < start:
            end = start
        plan.append({"name": name, "desc": desc, "start": start, "end": min(end, num_scenes)})
    return plan


def stage_for_scene(plan, i):
    for st in plan:
        if st["start"] <= i <= st["end"]:
            return st["name"]
    return plan[-1]["name"]


def safe_name(text, limit=30):
    return re.sub(r'[\/\\:*?"<>|]', "_", text or "").strip()[:limit] or "plan"


def clean_text_for_label(text):
    cleaned = re.sub(r"['\"\[\]\(\)\{\}\*\#\_\~]", "", text or "").strip()
    words = cleaned.split()
    return (" ".join(words[:2]) if len(words) >= 2 else cleaned)[:10]


def list_plans():
    items = []
    for path in glob.glob(os.path.join(PLANS_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            items.append({
                "plan_id": d.get("plan_id") or os.path.splitext(os.path.basename(path))[0],
                "topic": d.get("topic"),
                "num_scenes": len(d.get("structured_scenes") or []),
                "aspect_ratio": d.get("aspect_ratio"),
                "reference_title": (d.get("reference") or {}).get("title"),
                "has_audio": bool((d.get("audio_data") or {}).get("full_audio_url")),
                "created_at": d.get("created_at") or os.path.getmtime(path),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["created_at"] or 0, reverse=True)
    return items


def load_plan(plan_id):
    path = os.path.join(PLANS_DIR, f"{safe_name(plan_id, 120)}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def update_scene_subtitle(plan, scene_num, subtitle):
    """씬 나레이션을 바꾸고 기획서 텍스트(scenes_text/prompts_text/full_document)도 함께 갱신합니다."""
    sc = next((s for s in plan.get("structured_scenes", []) if int(s.get("scene_num")) == int(scene_num)), None)
    if sc is None:
        raise ValueError("해당 씬을 찾을 수 없습니다.")
    new = re.sub(r"\s+", " ", subtitle or "").strip().strip('"')
    if not new:
        raise ValueError("나레이션이 비어 있습니다.")
    old = sc.get("subtitle") or ""
    sc.setdefault("original_subtitle", old)
    sc["subtitle"] = new
    sc["parse_ok"] = True
    sc["length_warning"] = len(new) > NARRATION_MAX_CHARS
    sc["edited"] = True
    old_scenes_text = plan.get("scenes_text") or ""
    plan["scenes_text"] = render_scenes_md(plan["structured_scenes"])
    plan["prompts_text"] = render_prompts_md(plan["structured_scenes"], plan.get("aspect_ratio") or "16:9")
    if old_scenes_text and old_scenes_text in (plan.get("full_document") or ""):
        plan["full_document"] = plan["full_document"].replace(old_scenes_text, plan["scenes_text"])
    if old and old in (plan.get("full_document") or ""):
        plan["full_document"] = plan["full_document"].replace(old, new)
    return sc


def save_plan(plan):
    path = os.path.join(PLANS_DIR, f"{plan['plan_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    with open(os.path.join(PLANS_DIR, f"{plan['plan_id']}.md"), "w", encoding="utf-8") as f:
        f.write(plan["full_document"])
    return path


def list_style_guides():
    """data/knowledge/ 의 .md/.txt 문서 목록 (② 스타일 가이드 드롭다운용)."""
    items = []
    for f in sorted(os.listdir(KNOWLEDGE_DIR)):
        if f.lower().endswith((".md", ".txt")):
            path = os.path.join(KNOWLEDGE_DIR, f)
            items.append({"name": f, "chars": os.path.getsize(path)})
    return items


def load_style_guide(name):
    """스타일 가이드 문서 내용 (앞 3,500자). 없으면 None."""
    if not name:
        return None
    safe = os.path.basename(name)
    path = os.path.join(KNOWLEDGE_DIR, safe)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()[:3500]


# ── 레퍼런스(벤치마크 영상) 지식 ───────────────────────────────────────

def load_reference_knowledge(reference_id=None):
    """분석해 둔 영상의 리포트·자막을 레퍼런스로 사용합니다. 없으면 기본 샘플(난지도 영상)."""
    for vid in [reference_id, DEFAULT_REFERENCE_ID]:
        if not vid:
            continue
        path = os.path.join(ANALYSES_DIR, f"{vid}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if not d.get("ai_ok", True):
            continue
        info = d.get("info") or {}
        views = info.get("view_count") or 0
        knowledge = (
            f"[벤치마크 영상] {info.get('title')} — {info.get('channel')} · 조회수 {views:,}\n\n"
            f"[흥행 분석 리포트 발췌]\n{(d.get('report') or '')[:3500]}\n\n"
            f"[자막 대본 발췌 — 말투·호흡 참고]\n{(d.get('transcript') or '')[:1500]}"
        )
        return knowledge, {"id": vid, "title": info.get("title"), "channel": info.get("channel"), "view_count": views}
    return "(레퍼런스 분석 데이터 없음 — 일반적인 지식 다큐 공식을 적용)", None


# ── 1단계: 제목·설명란 ───────────────────────────────────────────────────

META_SCHEMA = """{
  "titles": [
    {"type": "대비형", "title": "제목 후보", "reason": "선정 이유 한 줄"},
    {"type": "수치형", "title": "제목 후보", "reason": "..."},
    {"type": "선언형", "title": "제목 후보", "reason": "..."}
  ],
  "recommended": {"title": "최종 추천 제목", "reason": "추천 이유"},
  "description": {
    "summary": "시청자 호기심을 끄는 3줄 줄거리(줄바꿈 포함)",
    "insight": "핵심 시사점·전문성 강조 문구",
    "cta": "구독·알림 유도 문구",
    "hashtags": ["#태그1", "#태그2", "#태그3", "#태그4", "#태그5"]
  }
}"""


def step_meta(topic, knowledge):
    prompt = (
        "당신은 유튜브 지식·다큐 콘텐츠 기획자입니다. 아래 벤치마크 영상의 흥행 공식(제목 훅 구조, 전개 방식, 시청자 반응 포인트)을 "
        "새 주제에 적용해 제목과 설명란을 기획해주세요.\n\n"
        f"[벤치마크 분석 데이터]\n{knowledge}\n\n"
        f"[새 영상 주제]\n\"{topic}\"\n\n"
        "제목 후보 3개는 서로 다른 훅 유형(대비형 / 수치형 / 선언형)으로 작성하고, 사실이 아닌 수치를 지어내지 마세요.\n"
        "반드시 아래 형식의 JSON 하나만 출력하세요 (설명 문장 금지):\n" + META_SCHEMA
    )
    data, raw = _llm_json([{"role": "user", "content": prompt}], max_tokens=2000)
    meta = _sanitize_meta(data, topic)
    return meta, prompt, raw


def _sanitize_meta(d, topic):
    d = d if isinstance(d, dict) else {}
    titles = []
    for t in (d.get("titles") or [])[:3]:
        if isinstance(t, dict) and t.get("title"):
            titles.append({"type": str(t.get("type") or "")[:10], "title": str(t["title"])[:80], "reason": str(t.get("reason") or "")[:200]})
    if not titles:
        titles = [{"type": "기본", "title": topic, "reason": "AI 응답을 해석하지 못해 주제를 그대로 사용"}]
    rec = d.get("recommended") if isinstance(d.get("recommended"), dict) else {}
    desc = d.get("description") if isinstance(d.get("description"), dict) else {}
    return {
        "titles": titles,
        "recommended": {"title": str(rec.get("title") or titles[0]["title"])[:80], "reason": str(rec.get("reason") or "")[:300]},
        "description": {
            "summary": str(desc.get("summary") or "")[:600],
            "insight": str(desc.get("insight") or "")[:400],
            "cta": str(desc.get("cta") or "")[:200],
            "hashtags": [("#" + str(h).lstrip("#"))[:20] for h in (desc.get("hashtags") or []) if str(h).strip()][:8],
        },
    }


def render_meta_md(meta):
    lines = ["### 제목 후보"]
    for i, t in enumerate(meta["titles"], 1):
        lines.append(f"{i}. **{t['title']}** _({t['type']})_ — {t['reason']}")
    lines.append(f"\n**✅ 최종 추천:** {meta['recommended']['title']}\n\n{meta['recommended']['reason']}")
    d = meta["description"]
    lines.append("\n### 설명란 (Description)\n")
    lines.append(d["summary"])
    if d["insight"]:
        lines.append("\n" + d["insight"])
    if d["cta"]:
        lines.append("\n" + d["cta"])
    if d["hashtags"]:
        lines.append("\n" + " ".join(d["hashtags"]))
    return "\n".join(lines)


def description_plain(meta):
    d = meta["description"]
    parts = [d["summary"], d["insight"], d["cta"], " ".join(d["hashtags"])]
    return "\n\n".join(p for p in parts if p)


# ── 2단계: 8초 씬 대본 ──────────────────────────────────────────────────

def step_scenes(topic, meta, knowledge, num_scenes, plan, secs=SCENE_SECONDS):
    """씬이 많으면(>CHUNK_SIZE) 구간을 나눠 여러 번 호출해 이어 붙입니다 (출력 잘림 방지)."""
    lo, hi, _mx = narration_bounds(secs)
    stage_lines = "\n".join(
        f"- 씬 {st['start']}" + (f"~{st['end']}" if st['end'] != st['start'] else "") +
        f" ({_time_range(st['start'], secs).split(' ~ ')[0]} ~ {_time_range(st['end'], secs).split(' ~ ')[1]}): {st['name']} — {st['desc']}"
        for st in plan
    )
    sent_hint = "한 문장" if secs <= 10 else ("2문장" if secs <= 16 else "2~3문장")
    schema = (
        '{\n  "scenes": [\n'
        f'    {{"scene_num": 1, "stage": "도입", "emotion": "핵심 감정/역할", '
        f'"narration": "{secs}초 안에 읽히는 {sent_hint} ({lo}~{hi}자)", "direction": "자막·연출 의도 한 줄"}}\n'
        "  ]\n}"
    )
    all_scenes, raws, prev_tail = [], [], ""
    for cs in range(1, num_scenes + 1, CHUNK_SIZE):
        ce = min(cs + CHUNK_SIZE - 1, num_scenes)
        part_note = f"이번 요청에서는 **씬 {cs}~{ce}만** 작성하세요 (전체 {num_scenes}씬 중)." if num_scenes > CHUNK_SIZE else ""
        cont = f"\n[바로 앞 씬({cs-1})의 나레이션 — 자연스럽게 이어서]\n\"{prev_tail}\"\n" if prev_tail else ""
        prompt = (
            f"영상 제목은 \"{meta['recommended']['title']}\"입니다. 이 영상을 **{secs}초 씬 {num_scenes}개**(총 {num_scenes * secs}초, 약 {num_scenes * secs // 60}분)로 제작합니다.\n"
            f"각 씬 {secs}초 동안 나레이터가 자연스럽게 읽을 한국어 나레이션을 작성해주세요. {part_note}\n\n"
            f"[벤치마크 영상의 말투·구조 참고]\n{knowledge[:2500]}\n\n"
            f"[주제] \"{topic}\"\n\n[5단계 플롯 배분 — 반드시 이 구간대로]\n{stage_lines}\n{cont}\n"
            "규칙:\n"
            f"- scene_num은 {cs}부터 {ce}까지 빠짐없이\n"
            f"- narration은 {lo}~{hi}자 {sent_hint} ({secs}초 안에 읽혀야 함). {hi + 5}자를 넘기지 말 것\n"
            "- 앞 씬과 자연스럽게 이어지고, 구체적 수치·대비·질문으로 리텐션을 유지\n"
            "- 사실이 아닌 수치를 지어내지 말 것. 불확실하면 '약', '추정'으로 표현\n\n"
            "반드시 아래 형식의 JSON 하나만 출력하세요:\n" + schema
        )
        data, raw = _llm_json([{"role": "user", "content": prompt}], max_tokens=4096)
        raws.append(raw)
        part = _sanitize_scenes(data, ce - cs + 1, plan, offset=cs - 1, secs=secs)
        if part is None:
            part = _legacy_parse_scenes(raw, ce - cs + 1, plan, offset=cs - 1, secs=secs)
        all_scenes += part
        prev_tail = next((s["subtitle"] for s in reversed(part) if s["subtitle"]), prev_tail)
    return all_scenes, "\n\n".join(raws)


def _sanitize_scenes(d, num_scenes, plan, offset=0, secs=SCENE_SECONDS):
    if not isinstance(d, dict):
        return None
    raw_list = d.get("scenes")
    if not isinstance(raw_list, list) or not raw_list:
        return None
    _lo, _hi, mx = narration_bounds(secs)
    by_num = {}
    for idx, item in enumerate(raw_list, 1):
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("scene_num") or (idx + offset))
        except Exception:
            n = idx + offset
        by_num[n] = item
    scenes = []
    for i in range(1 + offset, num_scenes + offset + 1):
        item = by_num.get(i) or by_num.get(i - offset) or {}
        narration = re.sub(r"\s+", " ", str(item.get("narration") or item.get("subtitle") or "")).strip().strip('"')
        scenes.append({
            "scene_num": i,
            "time_range": _time_range(i, secs),
            "seconds": secs,
            "stage": str(item.get("stage") or stage_for_scene(plan, i))[:8],
            "emotion": str(item.get("emotion") or "")[:40],
            "subtitle": narration,
            "direction": str(item.get("direction") or "")[:200],
            "parse_ok": bool(narration),
            "length_warning": len(narration) > mx,
        })
    if sum(1 for s in scenes if s["parse_ok"]) == 0:
        return None
    return scenes


def _scene_block(text, i):
    """서술형 응답에서 '씬 N' 또는 'Scene N' 블록을 잘라냅니다."""
    head = r"(?:씬|Scene|SCENE|scene)\s*0?%d(?!\d)"
    m = re.search(rf"{head % i}[^\n]*\n([\s\S]*?)(?={head % (i + 1)}|\Z)", text)
    return m.group(1) if m else ""


def _table_row_cells(text, i):
    """마크다운 표에서 '씬 i' 행의 셀 목록 (없으면 [])."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [re.sub(r"[*_`]", "", c).strip() for c in line.strip("|").split("|")]
        if cells and re.fullmatch(rf"(?:씬|Scene|SCENE|scene)\s*0?{i}", cells[0].strip()):
            return cells
    return []


def _legacy_parse_scenes(text, num_scenes, plan, offset=0, secs=SCENE_SECONDS):
    scenes = []
    for i in range(1 + offset, num_scenes + offset + 1):
        narration = ""
        cells = _table_row_cells(text, i)
        if cells:
            quoted = [c for c in cells if re.search(r"[\"“].{8,}[\"”]", c)]
            pick = quoted[0] if quoted else max(cells[1:], key=len, default="")
            narration = pick.strip().strip('"“”').strip()
        if not narration:
            body = _scene_block(text or "", i)
            q = re.search(r"[\"“]([^\"”]{8,})[\"”]", body)
            if q:
                narration = q.group(1).strip()
            else:
                for line in body.splitlines():
                    line = re.sub(r"[*_#`|]", "", line).strip()
                    if len(line) > 10 and not line.startswith(("-", ":")):
                        narration = line
                        break
        scenes.append({
            "scene_num": i, "time_range": _time_range(i, secs), "seconds": secs, "stage": stage_for_scene(plan, i), "emotion": "",
            "subtitle": narration, "direction": "", "parse_ok": bool(narration),
            "length_warning": len(narration) > narration_bounds(secs)[2],
        })
    return scenes


def render_scenes_md(scenes):
    lines = ["| 씬 | 시간 | 단계 | 나레이션 | 연출 의도 |", "|---|---|---|---|---|"]
    for s in scenes:
        warn = " ⚠️" if s.get("length_warning") else ""
        lines.append(f"| {s['scene_num']} | {s['time_range']} | {s['stage']} | {s['subtitle'] or '(대본 없음)'}{warn} | {s['direction']} |")
    return "\n".join(lines)


# ── 2.5단계: 나레이션 교정 (오타·맞춤법만, 의미·길이 유지) ────────────────

def step_proofread(scenes):
    """LLM에게 오타·맞춤법·띄어쓰기·어색한 표현만 최소 수정하게 하고, 원문과 너무 달라진 결과는 버립니다."""
    import difflib
    targets = [s for s in scenes if s.get("parse_ok")]
    if not targets:
        return scenes, ""
    targets = targets[:40]
    listing = "\n".join(f'{s["scene_num"]}. "{s["subtitle"]}"' for s in targets)
    prompt = (
        "다음은 유튜브 나레이션 대본입니다. 각 문장의 **오타, 맞춤법, 띄어쓰기, 명백히 어색하거나 말이 안 되는 단어**만 최소한으로 고쳐주세요.\n"
        "규칙: 의미·문체·길이(±5자)를 유지하고, 문장을 새로 쓰지 말 것. 고칠 것이 없으면 원문 그대로 반환.\n\n"
        f"{listing}\n\n"
        "반드시 아래 형식의 JSON 하나만 출력하세요:\n"
        '{"scenes": [{"scene_num": 1, "narration": "교정된 문장"}]}'
    )
    try:
        data, raw = llm_client.call_llm_json([{"role": "user", "content": prompt}], max_tokens=2500, temperature=0.2)
    except Exception as e:
        print(f"  ⚠️ 교정 단계 건너뜀: {e}")
        return scenes, ""
    fixed = {}
    for item in (data or {}).get("scenes", []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and item.get("narration"):
            try:
                fixed[int(item.get("scene_num"))] = re.sub(r"\s+", " ", str(item["narration"])).strip().strip('"')
            except Exception:
                pass
    changed = 0
    for s in scenes:
        new = fixed.get(s["scene_num"])
        if not new or new == s["subtitle"]:
            continue
        ratio = difflib.SequenceMatcher(None, s["subtitle"], new).ratio()
        if ratio >= 0.6 and abs(len(new) - len(s["subtitle"])) <= 12:
            s["original_subtitle"] = s["subtitle"]
            s["subtitle"] = new
            s["proofread"] = True
            s["length_warning"] = len(new) > NARRATION_MAX_CHARS
            changed += 1
    print(f"  ✓ 나레이션 교정: {changed}개 문장 수정")
    return scenes, raw or ""


# ── 3단계: AI 영상 프롬프트 ─────────────────────────────────────────────

def step_video_prompts(topic, scenes, aspect_ratio):
    if len(scenes) > CHUNK_SIZE:
        raws = []
        for cs in range(0, len(scenes), CHUNK_SIZE):
            _, raw = _step_video_prompts_chunk(topic, scenes[cs:cs + CHUNK_SIZE], aspect_ratio)
            raws.append(raw)
        return scenes, "\n\n".join(raws)
    return _step_video_prompts_chunk(topic, scenes, aspect_ratio)


def _step_video_prompts_chunk(topic, scenes, aspect_ratio):
    scene_text = "\n".join(f"- Scene {s['scene_num']} [{s['stage']}]: \"{s['subtitle']}\"" for s in scenes)
    ar_guide = ("vertical 9:16 composition, subject centered on the vertical axis, leave headroom for on-screen captions"
                if aspect_ratio == "9:16" else "wide 16:9 cinematic composition")
    schema = (
        '{\n  "scenes": [\n'
        '    {"scene_num": 1, "visual_prompt": "English, 40-70 words, photorealistic cinematic documentary description of what is on screen", '
        '"camera": "camera movement & angle (English)", "lighting": "lighting & atmosphere (English)", '
        '"sfx": "physical sound effects & ambience only (English)", "guide_ko": "한국어 비주얼·효과음 연출 가이드 한 줄"}\n'
        "  ]\n}"
    )
    prompt = (
        f"주제 \"{topic}\"의 8초 씬 {len(scenes)}개에 대해, AI 비디오 생성 툴(Runway Gen-3, Kling, Luma, Sora)에 바로 붙여넣을 영문 프롬프트를 작성해주세요.\n\n"
        f"[씬별 나레이션]\n{scene_text}\n\n"
        f"[화면 비율] {aspect_ratio} — {ar_guide}\n\n"
        "규칙:\n"
        "- visual_prompt는 나레이션 내용을 시각화하되 텍스트·자막·로고는 화면에 넣지 말 것 (no on-screen text)\n"
        "- 인물이 나오면 말하지 않는 모습으로 (silent characters, closed mouths, no talking heads)\n"
        "- sfx에는 사람 목소리·대사·음악·BGM을 절대 포함하지 말고 현장 효과음·앰비언스만 기술\n"
        f"- scene_num은 {scenes[0]['scene_num']}부터 {scenes[-1]['scene_num']}까지 빠짐없이\n\n"
        "반드시 아래 형식의 JSON 하나만 출력하세요:\n" + schema
    )
    data, raw = _llm_json([{"role": "user", "content": prompt}], max_tokens=4096)
    by_num = {}
    if isinstance(data, dict) and isinstance(data.get("scenes"), list):
        items = [it for it in data["scenes"] if isinstance(it, dict)]
        for idx, item in enumerate(items, 1):
            try:
                by_num[int(item.get("scene_num") or idx)] = item
            except Exception:
                by_num[idx] = item
        # 모델이 청크 안에서 1부터 다시 센 경우 → 순서대로 실제 씬 번호에 매핑
        expected = [s["scene_num"] for s in scenes]
        if not any(n in by_num for n in expected) and len(items) >= len(expected) * 0.5:
            by_num = {expected[i]: items[i] for i in range(min(len(expected), len(items)))}
    if not by_num:
        by_num = _legacy_parse_prompts(raw, len(scenes))
    for s in scenes:
        item = by_num.get(s["scene_num"]) or {}
        _apply_prompt(s, item, topic, aspect_ratio)
    return scenes, raw


def _legacy_parse_prompts(text, num_scenes):
    out = {}
    for i in range(1, num_scenes + 1):
        body = _scene_block(text or "", i)
        if not body:
            continue

        def grab(pattern):
            m = re.search(rf"(?:{pattern})[^:\n|]*[:|]\s*\**\s*([^\n|]+)", body, re.IGNORECASE)
            return m.group(1).replace("*", "").strip(" \"'") if m else ""

        out[i] = {
            "visual_prompt": grab(r"Scene Prompt|Visual|Prompt|프롬프트"),
            "camera": grab(r"Camera|카메라"),
            "lighting": grab(r"Lighting|조명"),
            "sfx": grab(r"Sound Effects|Sound|SFX|효과음|사운드"),
            "guide_ko": grab(r"가이드|Guide"),
        }
    return out


def _strip_audio_negations(text):
    return re.sub(r"(?:absolutely\s+)?(?:zero|no)\s+(?:human\s+)?(?:voice|vocal|speech|talking|dialogue|singing|whispering|narration|bgm|music|soundtrack)[^.;,]*[.;,]?",
                  "", text or "", flags=re.IGNORECASE).strip(" .,;")


def _apply_prompt(s, item, topic, aspect_ratio):
    visual = re.sub(r"\s+", " ", str(item.get("visual_prompt") or "")).strip(" \"'")
    visual = re.sub(r"\[Audio:[^\]]*\]", "", visual, flags=re.IGNORECASE).strip(" .")
    camera = str(item.get("camera") or "").strip(" \"'") or "Slow cinematic push-in"
    lighting = str(item.get("lighting") or "").strip(" \"'")
    sfx = _strip_audio_negations(str(item.get("sfx") or "")) or "ambient environmental sound, low-frequency room tone"
    guide = str(item.get("guide_ko") or "").strip()
    prompt_ok = bool(visual)
    if not visual:
        visual = (f"Photorealistic cinematic documentary shot illustrating: {s['subtitle'] or topic}. "
                  "Hyper-detailed, 8k, dramatic realism, no on-screen text")
    ar_clause = "vertical 9:16 framing" if aspect_ratio == "9:16" else "wide 16:9 framing"
    full = (
        f"{visual}. {ar_clause}. Camera: {camera}."
        + (f" Lighting: {lighting}." if lighting else "")
        + f" Audio: {sfx}. (SFX and ambience only — no voice, no speech, no dialogue, no music, no BGM, no on-screen text)"
        + f" --ar {aspect_ratio} --no voice, speech, dialogue, singing, music, bgm, text, watermark"
    )
    s.update({
        "visual_prompt": visual, "camera": camera, "lighting": lighting, "sfx": sfx, "guide_ko": guide,
        "prompt_en": full, "prompt_ok": prompt_ok,
    })


def render_prompts_md(scenes, aspect_ratio):
    lines = [f"> 화면 비율 `{aspect_ratio}` · 오디오는 효과음만(보이스·BGM 없음)\n"]
    for s in scenes:
        lines.append(f"#### 씬 {s['scene_num']} ({s['time_range']}) — {s['stage']}")
        lines.append(f"- 나레이션: \"{s['subtitle']}\"")
        lines.append(f"- **Prompt**: {s['prompt_en']}")
        if s.get("guide_ko"):
            lines.append(f"- 연출 가이드: {s['guide_ko']}")
        lines.append("")
    return "\n".join(lines)


# ── 4단계: 나노바나나 레드라인 이미지 프롬프트 ──────────────────────────

def step_redline(topic, scenes, aspect_ratio, guide_text=None):
    if len(scenes) > CHUNK_SIZE:
        thumbnail, raws = None, []
        for ci, cs in enumerate(range(0, len(scenes), CHUNK_SIZE)):
            th, raw = _step_redline_chunk(topic, scenes[cs:cs + CHUNK_SIZE], aspect_ratio, guide_text, want_thumbnail=(ci == 0))
            if ci == 0:
                thumbnail = th
            raws.append(raw)
        return thumbnail, "\n\n".join(raws)
    return _step_redline_chunk(topic, scenes, aspect_ratio, guide_text, want_thumbnail=True)


def _step_redline_chunk(topic, scenes, aspect_ratio, guide_text=None, want_thumbnail=True):
    scene_text = "\n".join(f"- 씬 {s['scene_num']}: \"{s['subtitle'] or topic}\"" for s in scenes)
    schema = """{
  "thumbnail": {
    "scene": {"subject": "피사체와 상황 묘사 (한국어)", "view": "cutaway cross-section / isometric 45 / aerial view"},
    "annotation_layer": [
      {"type": "leader_line", "style": "red dotted, end dot", "target": "대상", "label": "라벨(10자 이내)"},
      {"type": "dimension_line", "position": "left edge, vertical", "value": "실제 수치"}
    ],
    "text_layer": [
      {"text": "핵심 훅 문구(10자 이내)", "position": "center", "font": "bold Korean gothic", "color": "red", "size": "large"}
    ]
  },
  "scenes": [
    {"scene_num": 1,
     "scene": {"subject": "씬1 피사체 묘사", "view": "isometric 45 / slightly elevated"},
     "annotation_layer": [{"type": "leader_line", "style": "red dotted, end dot", "target": "대상", "label": "라벨"}],
     "text_layer": [{"text": "키워드 1개 또는 빈 배열", "position": "bottom", "font": "bold Korean gothic", "color": "white", "size": "medium"}]}
  ]
}"""
    guide_block = f"\n[스타일 가이드 문서 — 아래 원칙을 우선 적용]\n{guide_text}\n" if guide_text else ""
    prompt = (
        "당신은 나노바나나(Gemini Image) '레드라인 공학 주석' 스타일 이미지 프롬프트 디자이너입니다. "
        "주제와 씬별 나레이션을 바탕으로 썸네일 1장과 씬별 첫 프레임 이미지의 scene / annotation_layer / text_layer를 설계해주세요.\n\n"
        f"[주제] \"{topic}\"\n[종횡비] {aspect_ratio} — {ASPECT_GUIDE.get(aspect_ratio, '')}\n[씬별 나레이션]\n{scene_text}\n{guide_block}\n"
        "규칙:\n"
        "1. 썸네일: 3D 디오라마 단면/부감 + 빨간 점선 리더선·라벨 + 치수선 + 굵은 고딕 헤더. 텍스트 2~3개, 문구당 10자 이내\n"
        "2. 씬 첫 프레임: 영상 변환 시 글자가 뭉개지므로 text_layer는 최대 1개(핵심 단어) 또는 빈 배열. 텍스트 위치는 반드시 상단(top) — 하단은 자막이 들어갈 자리이므로 비워 둘 것. 대신 annotation_layer(leader_line, dimension_line, route_trace, angle_arc, bracket)를 풍부하게\n"
        "3. 수치는 나레이션에 실제로 언급된 값만 사용 (지어내기 금지)\n"
        "4. 모든 label·text는 10자 이내 한국어\n"
        f"5. scenes는 씬 {scenes[0]['scene_num']}부터 {scenes[-1]['scene_num']}까지 빠짐없이" + ("" if want_thumbnail else " (thumbnail은 이번엔 생략 가능)") + "\n\n"
        "반드시 아래 형식의 JSON 하나만 출력하세요:\n" + schema
    )
    data, raw = _llm_json([{"role": "user", "content": prompt}], max_tokens=4096)
    parsed = data if isinstance(data, dict) else {}

    thumbnail = sanitize_redline_block(
        parsed.get("thumbnail"), aspect_ratio, is_thumbnail=True,
        default_subject=f"{topic}의 핵심 상황과 구조적 위기", default_label=topic[:10], default_text=topic[:10],
    )
    raw_map = {}
    for item in (parsed.get("scenes") or []) if isinstance(parsed.get("scenes"), list) else []:
        if isinstance(item, dict) and "scene_num" in item:
            try:
                raw_map[int(item["scene_num"])] = item
            except Exception:
                pass
    for s in scenes:
        kw = clean_text_for_label(s["subtitle"] or topic)
        block = sanitize_redline_block(
            raw_map.get(s["scene_num"]), aspect_ratio, is_thumbnail=False,
            default_subject=f"{topic} — 씬 {s['scene_num']}: {s['subtitle'] or topic}",
            default_label=kw[:8] or "핵심구간", default_text=kw[:8],
        )
        s["image_prompt_json"] = block
        s["image_prompt_raw"] = json.dumps(block, ensure_ascii=False, indent=2)
        s["image_prompt_ok"] = s["scene_num"] in raw_map
    return thumbnail, raw


def sanitize_redline_block(raw_block, aspect_ratio="16:9", is_thumbnail=False, default_subject="", default_label="", default_text=""):
    """format/style/constraints는 코드에서 고정 주입, scene/annotation/text는 검증·보정."""
    scene_block = {
        "subject": default_subject or "3D 디오라마 장면",
        "view": "cutaway cross-section, slightly elevated" if is_thumbnail else "isometric 45°, detailed view",
    }
    if isinstance(raw_block, dict) and isinstance(raw_block.get("scene"), dict):
        rs = raw_block["scene"]
        if rs.get("subject"):
            scene_block["subject"] = str(rs["subject"]).strip()[:300]
        if rs.get("view"):
            scene_block["view"] = str(rs["view"]).strip()[:100]

    ann_list = []
    if isinstance(raw_block, dict) and isinstance(raw_block.get("annotation_layer"), list):
        for ann in raw_block["annotation_layer"]:
            if isinstance(ann, dict) and ann.get("type"):
                clean = {k: (str(v)[:10] if k in ("label", "value") else str(v)[:80]) for k, v in ann.items() if v not in (None, "")}
                ann_list.append(clean)
    if not ann_list:
        ann_list = [{"type": "leader_line", "style": "red dotted, end dot", "target": "핵심 구조물", "label": (default_label or "주요지점")[:10]}]
        if is_thumbnail:
            ann_list.append({"type": "dimension_line", "position": "left edge, vertical", "value": "위험구간"})

    text_list = []
    if isinstance(raw_block, dict) and isinstance(raw_block.get("text_layer"), list):
        for t in raw_block["text_layer"]:
            if isinstance(t, dict) and t.get("text"):
                pos = str(t.get("position") or ("center" if is_thumbnail else "top"))[:40]
                if not is_thumbnail and "bottom" in pos.lower():
                    pos = "top"  # 하단은 자막 자리 — 씬 이미지 텍스트는 상단으로
                text_list.append({
                    "text": str(t["text"])[:10],
                    "position": pos,
                    "font": str(t.get("font") or "bold Korean gothic")[:40],
                    "color": str(t.get("color") or ("red" if is_thumbnail else "white"))[:20],
                    "size": str(t.get("size") or ("large" if is_thumbnail else "medium"))[:10],
                })
    if not is_thumbnail:
        text_list = text_list[:1]
    elif not text_list and default_text:
        text_list = [{"text": default_text[:10], "position": "center", "font": "bold Korean gothic", "color": "red", "size": "large"}]

    return {
        "format": {"aspect_ratio": aspect_ratio, "resolution": "2K"},
        "style": dict(DEFAULT_REDLINE_STYLE),
        "scene": scene_block,
        "annotation_layer": ann_list,
        "text_layer": text_list,
        "constraints": list(DEFAULT_REDLINE_CONSTRAINTS),
    }


# ── 전체 파이프라인 ───────────────────────────────────────────────────────

def generate_video_content(topic, num_scenes=10, aspect_ratio="16:9", reference_id=None, style_guide=None, scene_seconds=SCENE_SECONDS, progress_callback=None):
    """
    주제 → ① 제목·설명란 ② 8초 씬 대본 ③ AI 영상 프롬프트 ④ 레드라인 이미지 프롬프트
    모든 단계는 JSON 응답을 요구하고 코드에서 검증합니다 (정규식 파싱은 예비 경로).
    """
    num_scenes = max(2, min(int(num_scenes), 40))
    scene_seconds = max(6, min(int(scene_seconds or SCENE_SECONDS), 30))
    aspect_ratio = aspect_ratio if aspect_ratio in ASPECT_GUIDE else "16:9"

    def step(key, msg):
        if progress_callback:
            progress_callback(key, msg)
        print(msg)

    knowledge, reference = load_reference_knowledge(reference_id)
    plan = stage_plan(num_scenes)

    step("meta", "1/4 제목 후보와 설명란 기획 중...")
    meta, _, meta_raw = step_meta(topic, knowledge)

    step("scenes", f"2/4 {scene_seconds}초 씬 {num_scenes}개 나레이션 대본 작성 중 (총 약 {num_scenes * scene_seconds // 60}분 {num_scenes * scene_seconds % 60}초)...")
    scenes, scenes_raw = step_scenes(topic, meta, knowledge, num_scenes, plan, secs=scene_seconds)

    step("proofread", "2/4 나레이션 오타·맞춤법 교정 중...")
    scenes, proof_raw = step_proofread(scenes)

    step("prompts", f"3/4 씬별 AI 영상 프롬프트 작성 중 ({aspect_ratio})...")
    scenes, prompts_raw = step_video_prompts(topic, scenes, aspect_ratio)

    guide_text = load_style_guide(style_guide)
    step("redline", "4/4 썸네일·첫 프레임 레드라인 이미지 프롬프트 설계 중..." + (f" (가이드: {style_guide})" if guide_text else ""))
    thumbnail, redline_raw = step_redline(topic, scenes, aspect_ratio, guide_text=guide_text)

    meta_text = render_meta_md(meta)
    scenes_text = render_scenes_md(scenes)
    prompts_text = render_prompts_md(scenes, aspect_ratio)
    thumb_raw = json.dumps(thumbnail, ensure_ascii=False, indent=2)

    ref_line = f"> 벤치마크: **{reference['title']}** (조회수 {reference['view_count']:,})\n\n" if reference else ""
    redline_section = (
        f"> 종횡비 `{aspect_ratio}` · 해상도 `2K` · 스타일 `3D Miniature Diorama + Red Engineering Annotation`\n\n"
        f"### 4-1. 썸네일 프롬프트\n\n```json\n{thumb_raw}\n```\n\n### 4-2. 씬별 첫 프레임 프롬프트\n\n"
        + "\n".join(f"#### 씬 {s['scene_num']} ({s['time_range']})\n- 나레이션: \"{s['subtitle']}\"\n\n```json\n{s['image_prompt_raw']}\n```\n" for s in scenes)
    )
    full_document = (
        f"# 🎬 [{topic}] 8초 씬 기반 유튜브 콘텐츠 기획서\n\n{ref_line}"
        f"## 1. 제목 & 설명란\n\n{meta_text}\n\n---\n\n"
        f"## 2. {scene_seconds}초 씬별 나레이션 대본 (총 {num_scenes}씬 · {num_scenes * scene_seconds}초)\n\n{scenes_text}\n\n---\n\n"
        f"## 3. 씬별 AI 영상 프롬프트\n\n{prompts_text}\n\n---\n\n"
        f"## 4. 나노바나나 레드라인 이미지 프롬프트\n\n{redline_section}"
    )

    plan_id = f"{safe_name(topic)}_{time.strftime('%Y%m%d-%H%M%S')}"
    backend = llm_client.detect_backend()
    result = {
        "plan_id": plan_id,
        "topic": topic,
        "aspect_ratio": aspect_ratio,
        "num_scenes": num_scenes,
        "scene_seconds": scene_seconds,
        "reference": reference,
        "style_guide": style_guide if guide_text else None,
        "meta": meta,
        "meta_text": meta_text,
        "description_plain": description_plain(meta),
        "scenes_text": scenes_text,
        "prompts_text": prompts_text,
        "thumbnail_prompt": thumbnail,
        "thumbnail_prompt_raw": thumb_raw,
        "structured_scenes": scenes,
        "full_document": full_document,
        "quality": {
            "scenes_parsed": sum(1 for s in scenes if s["parse_ok"]),
            "prompts_parsed": sum(1 for s in scenes if s.get("prompt_ok")),
            "images_parsed": sum(1 for s in scenes if s.get("image_prompt_ok")),
            "length_warnings": [s["scene_num"] for s in scenes if s.get("length_warning")],
        },
        "raw": {"meta": meta_raw, "scenes": scenes_raw, "proofread": proof_raw, "prompts": prompts_raw, "redline": redline_raw},
        "llm": {"backend": backend["name"], "model": backend["model"]} if backend else None,
        "created_at": time.time(),
    }
    result["file_path"] = save_plan(result)
    return result


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "지하 50층 비밀 벙커의 진실"
    ar = sys.argv[2] if len(sys.argv) > 2 else "16:9"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    res = generate_video_content(topic, num_scenes=n, aspect_ratio=ar)
    print("\n" + "=" * 60)
    print(f"✅ [{topic}] 기획 완료 → data/plans/{res['plan_id']}.json  품질: {res['quality']}")
    print(res["full_document"][:1500])
