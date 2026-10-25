"""H-0: Argon 1~3씬(27초)을 HyperFrames 컴포지션으로 생성 — H-1 의 '템플릿 + 변수' 방식 시험."""
import html, json, sys
from pathlib import Path

proj = Path(sys.argv[1])
caps = json.loads((proj / "assets/captions.json").read_text())
HOOK = "로봇이 스스로 연습한다?"
ACCENT = "#ffd166"
SCENES = [(0.0, 9.4), (9.4, 18.0), (18.0, 25.0)]
END = (25.0, 27.0)
TOTAL = 27.0
XF = 0.4  # 크로스페이드

# 자막 페이지: 페이지 시작부터 1.2초 안 토큰 묶기, pageBreakAfter 에서 강제로 끊기
pages, cur = [], None
for c in caps:
    s, e = c["startMs"] / 1000, c["endMs"] / 1000
    if cur is None or s - cur["start"] >= 1.2 or cur.get("brk"):
        cur = {"start": s, "end": e, "words": []}
        pages.append(cur)
    cur["words"].append({"t": c["text"].strip(), "s": s, "e": e})
    cur["end"] = e
    cur["brk"] = bool(c.get("pageBreakAfter"))
for i, p in enumerate(pages):
    p["hide"] = pages[i + 1]["start"] if i + 1 < len(pages) else p["end"] + 0.3

# BGM 덕킹: 발화(±0.25초) 중 0.14, 그 밖 0.308(=0.14×2.2), 시작 0.5초 페이드인·끝 1초 페이드아웃 (Remotion 과 같은 규칙)
spans = []
for c in caps:
    s, e = c["startMs"] / 1000 - 0.25, c["endMs"] / 1000 + 0.25
    if spans and s <= spans[-1][1]:
        spans[-1][1] = max(spans[-1][1], e)
    else:
        spans.append([s, e])
LO, HI = 0.14, 0.308
pts = [{"t": 0, "v": 0}, {"t": 0.5, "v": HI}]
for s, e in spans:
    s, e = max(0.5, s), min(TOTAL - 1, e)
    if e <= s:
        continue
    pts += [{"t": round(max(0.5, s - 0.1), 3), "v": HI}, {"t": round(s, 3), "v": LO},
            {"t": round(e, 3), "v": LO}, {"t": round(min(TOTAL - 1, e + 0.1), 3), "v": HI}]
pts += [{"t": TOTAL - 1, "v": HI}, {"t": TOTAL, "v": 0}]
pts = sorted({p["t"]: p for p in pts}.values(), key=lambda p: p["t"])
automation = html.escape(json.dumps({"version": 1, "lanes": [{"target": "volume", "points": pts}]}), quote=True)

bars = [("Gemini 4 Argon", 87.0, True), ("Claude Opus 5.5", 82.3, False), ("GPT-6 Astra", 81.0, False)]

cap_html = []
for i, p in enumerate(pages):
    words = "".join(f'<span class="w" id="p{i}w{j}">{html.escape(w["t"])}</span> ' for j, w in enumerate(p["words"]))
    cap_html.append(f'<div class="cap" id="cap{i}">{words.strip()}</div>')

bar_html = "".join(
    f'<div class="bar-row" id="bar{i}"><div class="bar-head"><span class="{"hl" if hl else ""}">{html.escape(l)}</span>'
    f'<span class="bar-val" id="barv{i}" style="color:{ACCENT if hl else "rgba(255,255,255,.55)"}">0.0%</span></div>'
    f'<div class="bar-track"><div class="bar-fill" id="barf{i}" style="background:{ACCENT if hl else "rgba(255,255,255,.55)"}"></div></div></div>'
    for i, (l, v, hl) in enumerate(bars))

js_pages = json.dumps([{"start": p["start"], "hide": p["hide"], "words": [[w["s"]] for w in p["words"]]} for p in pages])
js_bars = json.dumps([v for _, v, _ in bars])

out = f'''<!doctype html>
<html lang="ko" data-resolution="portrait">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080, height=1920" />
<script src="assets/gsap.min.js"></script>
<style>
@font-face {{ font-family: "Pretendard"; src: url("assets/PretendardVariable.woff2") format("woff2"); font-weight: 45 920; }}
:root {{ --accent: {ACCENT}; --ink: #fff; --font: "Pretendard", sans-serif; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: 1080px; height: 1920px; overflow: hidden; background: #000; }}
#root {{ position: relative; width: 1080px; height: 1920px; font-family: var(--font); color: var(--ink); word-break: keep-all; }}
.clip {{ position: absolute; inset: 0; }}
.bg0 {{ background: radial-gradient(120% 80% at 30% 20%, #2a3f6e 0%, #1b2a4a 45%, #0b1222 100%); }}
.bg1 {{ background: radial-gradient(120% 80% at 70% 25%, #5a2f72 0%, #3a1f4f 45%, #150b1f 100%); }}
.zone {{ position: absolute; left: 90px; right: 96px; top: 120px; bottom: 300px; display: flex; flex-direction: column; justify-content: center; }}
.title {{ font-weight: 900; line-height: 1.15; letter-spacing: -0.02em; text-align: center; }}
.sub {{ margin-top: 28px; font-size: 42px; font-weight: 700; color: var(--accent); text-align: center; }}
.uline {{ margin: 34px auto 0; height: 8px; width: 220px; border-radius: 4px; background: var(--accent); transform-origin: left center; }}
#hook {{ position: absolute; top: 150px; left: 70px; right: 70px; padding: 26px 30px; border-radius: 24px; background: rgba(0,0,0,.55); border: 3px solid var(--accent); text-align: center; font-weight: 900; z-index: 5; }}
.bar-title {{ font-size: 50px; font-weight: 800; text-align: center; margin-bottom: 44px; }}
.bar-row {{ margin-bottom: 34px; }}
.bar-head {{ display: flex; justify-content: space-between; font-size: 40px; font-weight: 600; margin-bottom: 12px; color: rgba(255,255,255,.8); }}
.bar-head .hl {{ color: #fff; font-weight: 900; }}
.bar-track {{ height: 34px; border-radius: 17px; background: rgba(255,255,255,.12); overflow: hidden; }}
.bar-fill {{ height: 100%; width: 0%; border-radius: 17px; }}
#img3 {{ position: absolute; inset: 0; background: url("assets/scene3.png") center/cover no-repeat; transform-origin: 50% 50%; }}
#endtag {{ display: flex; flex-direction: column; align-items: center; justify-content: center; background: radial-gradient(100% 70% at 50% 45%, #1f3f2a 0%, #0b140e 100%); }}
#endtag .t {{ font-size: 76px; font-weight: 900; text-align: center; padding: 0 90px; line-height: 1.2; }}
#endtag .s {{ margin-top: 22px; font-size: 38px; font-weight: 500; color: rgba(230,232,240,.9); }}
#caps {{ position: absolute; left: 0; right: 0; bottom: 420px; height: 0; z-index: 6; }}
.cap {{ position: absolute; left: 0; right: 0; bottom: 0; text-align: center; padding: 0 110px; font-weight: 900; line-height: 1.25; text-shadow: 0 6px 18px rgba(0,0,0,.85), 0 0 4px rgba(0,0,0,.9); opacity: 0; visibility: hidden; }}
.cap .w.on {{ color: var(--accent); }}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{TOTAL}" data-width="1080" data-height="1920">
  <audio id="narr" src="assets/narration_25s.mp3" data-start="0" data-duration="25" data-volume="1" data-track-index="10"></audio>
  <audio id="bgm" src="assets/bgm.mp3" data-start="0" data-duration="{TOTAL}" data-volume="1" data-automation="{automation}" data-track-index="11"></audio>

  <div id="s1" class="clip bg0" data-start="0" data-duration="{SCENES[0][1] + XF}" data-track-index="0">
    <div class="zone"><div class="title" id="t1">로봇이 스스로 연습한다</div><div class="sub" id="st1">Google · Gemini 4 Argon</div><div class="uline" id="ul1"></div></div>
  </div>
  <div id="s2" class="clip bg1" data-start="{SCENES[1][0]}" data-duration="{SCENES[1][1] - SCENES[1][0] + XF}" data-track-index="1">
    <div class="zone"><div class="bar-title">ERQA 공간 추론 벤치마크</div>{bar_html}</div>
  </div>
  <div id="s3" class="clip" data-start="{SCENES[2][0]}" data-duration="{SCENES[2][1] - SCENES[2][0] + XF}" data-track-index="2" style="overflow:hidden">
    <div id="img3"></div>
  </div>
  <div id="endtag" class="clip" data-start="{END[0]}" data-duration="{END[1] - END[0]}" data-track-index="3">
    <div class="t" id="et">구독하고 다음 AI 동향 보기</div><div class="s">어사이드 AI 브리핑 · 출처 GeekNews</div>
  </div>
  <div id="hook" class="clip" data-start="0" data-duration="3" data-track-index="4" style="inset:auto; top:150px; left:70px; right:70px;">{html.escape(HOOK)}</div>
  <div id="caps" class="clip" data-start="0" data-duration="25" data-track-index="5" data-track-kind="captions" style="inset:auto; left:0; right:0; bottom:420px;">
    {"".join(cap_html)}
  </div>
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
const fit = (el, maxWidth, base, min) => {{
  const r = window.__hyperframes && window.__hyperframes.fitTextFontSize
    ? window.__hyperframes.fitTextFontSize(el.textContent, {{ fontFamily: "Pretendard", fontWeight: 900, maxWidth, baseFontSize: base, minFontSize: min }})
    : {{ fontSize: base }};
  el.style.fontSize = r.fontSize + "px";
}};
fit(document.getElementById("t1"), 894 * 2.6, 104, 56);   // 최대 3줄 근사
fit(document.getElementById("hook"), 800 * 1.9, 72, 48);
document.querySelectorAll(".cap").forEach(c => fit(c, 860 * 1.9, 78, 48));

// 씬 사이 크로스페이드 (들어오는 씬이 위에서 0.4초 동안 나타난다)
[["#s2", {SCENES[1][0]}], ["#s3", {SCENES[2][0]}], ["#endtag", {END[0]}]].forEach(([id, t]) => tl.fromTo(id, {{ opacity: 0 }}, {{ opacity: 1, duration: {XF}, ease: "none" }}, t));

// 훅: 튀어 들어와 착지 후 정지, 끝에서 사라짐
// 첫 프레임(피드 썸네일)부터 훅이 보이게: 0초에 이미 불투명, 크기만 살짝 튄다
tl.fromTo("#hook", {{ opacity: 1, scale: 0.92 }}, {{ opacity: 1, scale: 1, duration: 0.4, ease: "back.out(1.8)" }}, 0);
tl.to("#hook", {{ opacity: 0, duration: 0.25, ease: "power2.in" }}, 2.75);

// 씬 1: 제목 → 부제 → 밑줄
tl.fromTo("#t1", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }}, 0.1);
tl.fromTo("#st1", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power3.out" }}, 0.38);
tl.fromTo("#ul1", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.6, ease: "power2.out" }}, 0.55);
tl.to("#s1 .zone", {{ opacity: 0, duration: 0.3 }}, {SCENES[0][1] - 0.27});

// 씬 2: 막대가 차례로 자라며 값이 올라간다 (seek 해도 같은 값이 나오도록 proxy 를 트윈)
const vals = {js_bars};
vals.forEach((v, i) => {{
  const t0 = {SCENES[1][0]} + 0.2 + i * 0.33;
  tl.fromTo("#bar" + i, {{ opacity: 0 }}, {{ opacity: 1, duration: 0.33, ease: "none" }}, t0 - 0.2);
  tl.fromTo("#barf" + i, {{ width: "0%" }}, {{ width: (v / Math.max(...vals) * 100) + "%", duration: 1.33, ease: "power3.out" }}, t0);
  const p = {{ v: 0 }};
  tl.fromTo(p, {{ v: 0 }}, {{ v, duration: 1.33, ease: "power3.out", onUpdate: () => {{ document.getElementById("barv" + i).textContent = p.v.toFixed(1) + "%"; }} }}, t0);
}});
tl.to("#s2 .zone", {{ opacity: 0, duration: 0.3 }}, {SCENES[1][1] - 0.27});

// 씬 3: 켄번즈 줌 인
tl.fromTo("#img3", {{ scale: 1.0 }}, {{ scale: 1.12, duration: {SCENES[2][1] - SCENES[2][0] + XF}, ease: "none" }}, {SCENES[2][0]});

// 엔드 태그
tl.fromTo("#et", {{ opacity: 0, scale: 0.9 }}, {{ opacity: 1, scale: 1, duration: 0.45, ease: "back.out(1.6)" }}, {END[0] + 0.1});

// 자막: 페이지 한 장씩, 현재 어절 강조, 페이지마다 강제 종료
const pages = {js_pages};
pages.forEach((p, i) => {{
  const id = "#cap" + i;
  tl.set(id, {{ visibility: "visible" }}, p.start);
  tl.fromTo(id, {{ opacity: 0, y: 12 }}, {{ opacity: 1, y: 0, duration: 0.2, ease: "power2.out" }}, p.start);
  p.words.forEach((w, j) => {{
    tl.set("#p" + i + "w" + j, {{ className: "w on" }}, w[0]);
    if (j > 0) tl.set("#p" + i + "w" + (j - 1), {{ className: "w" }}, w[0]);   // 지금 말하는 어절만 강조
  }});
  tl.to(id, {{ opacity: 0, duration: 0.12, ease: "power2.in" }}, p.hide - 0.12);
  tl.set(id, {{ opacity: 0, visibility: "hidden" }}, p.hide);
}});

window.__timelines["main"] = tl;
tl.seek(0);
</script>
</body>
</html>
'''
(proj / "index.html").write_text(out)
print(f"pages={len(pages)} automation_points={len(pts)} bytes={len(out)}")
