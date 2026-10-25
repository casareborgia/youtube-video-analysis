"""A/B 시험 C: B 와 같은 음성·자막·진행 표시·보상 무음, 이미지 8장만 코드로 그린 모션그래픽 씬으로 바꾼다. 비용 0."""
import copy, json, os, shutil, sys

WT = sys.argv[1]
PROPS_ONLY = "--props-only" in sys.argv
sys.path.insert(0, WT)
os.chdir(WT)
import shorts_engine as se  # noqa: E402

ITEMS = ["AI 에이전트", "멀티모달", "AI 영상 생성", "로컬 AI", "AI 코딩", "신뢰와 안전"]
PAYOFF = 7
ARTS = ["hook", "agent", "multimodal", "video", "local", "coding", "trust", "cta"]
BGS = ["#2a1457", "#1f3a8a", "#0f5f63", "#7a2357", "#1d2f5c", "#1f5c3c", "#4b2380", "#2a1457"]
# 씬마다 그림이 맞춰 움직일 단어(나레이션 순서대로) — animate: 목소리가 시계
CUE_WORDS = [["직접", "동료가"], ["검색부터", "예약과", "코드"], ["글과", "그림", "목소리와", "영상을"],
             ["문장", "몇", "분", "소리까지", "영상이"], ["로컬", "인터넷", "없이", "맥미니", "그렸습니다"],
             ["말로", "설명하면", "앱을", "테스트까지"], ["믿을", "경쟁력이"], ["댓글로"]]

b = se.load_job("shorts_ab_ai_trend_B")
c = copy.deepcopy(b)
c["shorts_id"] = "shorts_ab_ai_trend_C"
for k in ("render", "qc", "review", "lint"):
    c.pop(k, None)
db, dc = se.job_dir(b["shorts_id"]), se.job_dir(c["shorts_id"], create=True)
for fn in os.listdir(db):
    if fn.endswith((".png", ".mp3")):
        shutil.copy2(os.path.join(db, fn), dc)
c["audio"]["narration"] = os.path.join(dc, "narration.mp3")
c["audio"]["bgm"] = os.path.join(dc, "bgm_prepared.mp3")

scenes = c["storyboard"]["scenes"]
starts, t = [], 0
for s in scenes:
    starts.append(int(round(t * 1000)))
    t += float(s["seconds"])
ends = starts[1:] + [int(round(t * 1000))]
caps = c["captions"]


def cues_for(i):
    out, pos = [], 0
    window = [cp for cp in caps if starts[i] <= cp["startMs"] < ends[i]]
    for w in CUE_WORDS[i]:
        for j in range(pos, len(window)):
            if w in window[j]["text"]:
                out.append(window[j]["startMs"])
                pos = j + 1
                break
        else:
            print(f"  ! 씬 {i} 단어 못 찾음: {w}")
    return out


intro_ms = next(cp["startMs"] for cp in caps if "여섯" in cp["text"])
_orig = se.build_remotion_props


def props_c(job):
    p = _orig(job)
    for i, sc in enumerate(p["scenes"]):
        sc.pop("image", None)
        sc["kind"] = "mograph"
        sc["mograph"] = {"art": ARTS[i], "bg": BGS[i], "cuesMs": cues_for(i)}
        if i > 0:
            sc["transition"] = "none" if i == PAYOFF else "hero_flood"
    p.update({"look": "variety",
              "thread": {"items": ITEMS, "firstScene": 1, "introAtMs": intro_ms, "gatherScene": PAYOFF},
              "payoff": {"scene": PAYOFF, "silenceMs": 600}})
    return p


se.build_remotion_props = props_c
se.save_job(c)
if PROPS_ONLY:
    p = props_c(c)
    with open(os.path.join(dc, "remotion_props.json"), "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    for i, sc in enumerate(p["scenes"]):
        print(i, sc["mograph"]["art"], sc["mograph"]["cuesMs"])
    sys.exit(0)

se.render_shorts(c, renderer="remotion")
se.normalize_loudness(c)
se.qc_job(c)
if c.get("status") == "qc_passed":
    se.run_review(c)
se.save_job(c)
r = c.get("review") or {}
print("C", c.get("status"), "LUFS", c["audio"].get("lufs"), "TP", c["audio"].get("true_peak"),
      "render", c["render"].get("elapsed_sec"), "s", "review", r.get("counts"))
for fnd in r.get("findings", []):
    print("   ", fnd["level"], fnd["code"], fnd.get("t"), fnd["message"])
