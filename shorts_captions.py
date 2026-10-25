"""쇼츠 자막 그룹핑·강조어 (작업계획서_영상생성_업그레이드 6장 U-3).

shorts_engine(렌더 props)과 shorts_review(린트)가 함께 쓴다. 이 모듈은 둘 중 어느 것도 import 하지 않는다.

근거: HyperFrames skills/hyperframes/references/captions.md (Apache-2.0) — 에너지별 그룹 크기, 문장 끝·150ms 이상 쉼에서 끊기,
0초에 바로 띄우지 않기(0.1~0.3초 뒤), 그룹마다 강제 종료. 한국어는 어절을 단어로 본다.
"""

import re
from typing import Callable, List, Optional

ENERGY_WORDS = {"high": 3, "normal": 4, "calm": 5}   # 한 그룹 최대 어절 수 (HF: 2~3 / 3~5 / 4~6)
DEFAULT_ENERGY = "normal"
PAUSE_BREAK_MS = 150          # 이 이상 쉬면 그룹을 끊는다
CAPTION_MIN_START_MS = 150    # 첫 자막은 이보다 일찍 띄우지 않는다
CAPTION_HOLD_MS = 300         # 그룹 마지막 어절이 끝난 뒤 이만큼만 남기고 지운다(다음 그룹이 더 늦게 오더라도)
GROUPED_PAGE_MS = 60000       # 그룹 경계(pageBreakAfter)로만 끊도록 @remotion/captions 의 시간 창을 크게 둔다

_SENTENCE_END = re.compile(r"[.?!。…]$")
_NUMBER = re.compile(r"\d[\d.,]*")


def _is_new_word(tok: dict, first: bool) -> bool:
    return first or str(tok.get("text") or "").startswith(" ")


def group_captions(captions: List[dict], energy: str = DEFAULT_ENERGY) -> List[dict]:
    """어절 토큰 → 그룹 끝 토큰에 pageBreakAfter 를 단 새 목록(원본 불변). 씬 끝에 달린 pageBreakAfter 는 그대로 둔다.

    끊는 곳: 문장부호로 끝나는 어절 뒤, 다음 어절까지 150ms 이상 쉬는 곳, 어절 수 상한.
    상한에서 끊었을 때 다음 그룹이 한 어절만 남는 경우(바로 뒤가 쉼·씬 끝)는 그 어절까지 붙여 외톨이를 막는다.
    """
    cap = ENERGY_WORDS.get(energy, ENERGY_WORDS[DEFAULT_ENERGY])
    toks = [dict(c) for c in captions or []]
    n = len(toks)
    # 씬 끝 표시(원래 pageBreakAfter)를 기억해 두고 새로 계산한다
    scene_end = [bool(t.get("pageBreakAfter")) for t in toks]
    words_in_group = 0

    def boundary_after(j: int) -> bool:
        """j 토큰 뒤가 문장·쉼·씬 경계인가."""
        if j >= n - 1 or scene_end[j]:
            return True
        if _SENTENCE_END.search(str(toks[j].get("text") or "").strip()):
            return True
        return int(toks[j + 1]["startMs"]) - int(toks[j]["endMs"]) >= PAUSE_BREAK_MS

    for i, t in enumerate(toks):
        if _is_new_word(t, words_in_group == 0):
            words_in_group += 1
        brk = boundary_after(i)
        if not brk and words_in_group >= cap:
            # 다음 어절 하나만 남고 바로 경계라면 붙인다
            nxt = i + 1   # 다음 어절의 마지막 토큰까지 (경계를 넘지 않는다 — 씬 첫 토큰은 앞 공백이 없다)
            while nxt + 1 < n and not boundary_after(nxt) and not _is_new_word(toks[nxt + 1], False):
                nxt += 1
            brk = not boundary_after(nxt)
            if not brk:
                continue   # 다음 토큰까지 이어 붙이고, 그 뒤 경계에서 끊긴다
        t["pageBreakAfter"] = bool(brk)
        if brk:
            words_in_group = 0
    for t in toks:
        if not t.get("pageBreakAfter"):
            t.pop("pageBreakAfter", None)
    return toks


def caption_groups(captions: List[dict], energy: str = DEFAULT_ENERGY) -> List[dict]:
    """화면에 실제로 뜨는 그룹: [{"startMs","endMs","hideMs","words"}]. hideMs 는 다음 그룹 시작과 마지막 어절+300ms 중 이른 쪽."""
    groups, cur = [], None
    for t in group_captions(captions, energy):
        if cur is None:
            cur = {"startMs": int(t["startMs"]), "endMs": int(t["endMs"]), "words": 0}
        cur["endMs"] = int(t["endMs"])
        if str(t.get("text") or "").startswith(" ") or cur["words"] == 0:
            cur["words"] += 1
        if t.get("pageBreakAfter"):
            groups.append(cur)
            cur = None
    if cur:
        groups.append(cur)
    for i, g in enumerate(groups):
        nxt = groups[i + 1]["startMs"] if i + 1 < len(groups) else None
        hide = g["endMs"] + CAPTION_HOLD_MS
        g["hideMs"] = min(hide, nxt) if nxt is not None else hide
    if groups and groups[0]["startMs"] < CAPTION_MIN_START_MS:
        groups[0]["startMs"] = CAPTION_MIN_START_MS
    return groups


def number_emphasis(narration: str) -> str:
    """숫자가 들어간 첫 어절(조사·단위 포함, 끝 문장부호 제외). 없으면 ""."""
    for w in str(narration or "").split():
        if _NUMBER.search(w):
            return w.strip(".,?!…·\"'()[]")
    return ""


def _norm(text: Optional[str]) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


def valid_emphasis(word: str, narration: str) -> bool:
    nw = _norm(word)
    return 2 <= len(nw) <= 20 and nw in _norm(narration)


def pick_emphasis_words(scenes: List[dict], llm: Optional[Callable] = None) -> List[dict]:
    """씬마다 강조할 핵심어 1개를 고른다. 이미 emphasis 가 있는 씬은 건드리지 않는다.

    llm(narrations) -> [word|""...] 가 주어지면 먼저 쓰고(숫자·고유명사 우선 지시), 대본에 그대로 없는 답은 버린다.
    그다음 숫자 어절, 그것도 없으면 강조 없음. 각 씬에 emphasis_source = llm | number | none.
    """
    todo = [s for s in scenes if "emphasis" not in s]
    answers: List[str] = []
    if todo and llm:
        try:
            answers = list(llm([s.get("narration") or "" for s in todo]) or [])
        except Exception:
            answers = []
    for i, s in enumerate(todo):
        narration = s.get("narration") or ""
        word = str(answers[i]).strip() if i < len(answers) and answers[i] else ""
        if word and valid_emphasis(word, narration):
            s["emphasis"], s["emphasis_source"] = word, "llm"
            continue
        num = number_emphasis(narration)
        if num and valid_emphasis(num, narration):
            s["emphasis"], s["emphasis_source"] = num, "number"
        else:
            s["emphasis"], s["emphasis_source"] = "", "none"
    return scenes


def mark_emphasis(captions: List[dict], scenes: List[dict]) -> List[dict]:
    """씬 시간 구간 안에서 그 씬 emphasis 와 맞는 첫 어절 토큰에 emphasis=True 를 단 새 목록."""
    out = [dict(c) for c in captions or []]
    start = 0
    for s in scenes:
        end = start + int(round(float(s.get("seconds") or 0) * 1000))
        target = _norm(s.get("emphasis"))
        if target:
            for c in out:
                if start <= int(c["startMs"]) < end:
                    nt = _norm(c.get("text"))
                    if nt and (target in nt or (len(nt) >= 2 and nt in target)):
                        c["emphasis"] = True
                        break
        start = end
    return out
