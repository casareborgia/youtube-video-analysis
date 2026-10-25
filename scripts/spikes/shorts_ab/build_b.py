"""A/B 시험: A 에 강조어를 넣어 다시 렌더(공정 비교), B = 같은 음성·이미지 + 예능 룩·진행 표시·보상 무음·효과음."""
import copy, json, os, shutil, subprocess, sys

WT = sys.argv[1]
sys.path.insert(0, WT)
os.chdir(WT)
import shorts_engine as se  # noqa: E402

EMPH = ["여섯", "에이전트", "멀티모달", "영상", "로컬", "코딩", "신뢰와", "기대되나요?"]
ITEMS = ["AI 에이전트", "멀티모달", "AI 영상 생성", "로컬 AI", "AI 코딩", "신뢰와 안전"]
SILENCE_MS = 600
PAYOFF = 7


def finish(job, label):
    se.render_shorts(job, renderer="remotion")
    se.normalize_loudness(job)
    se.qc_job(job)
    if job.get("status") == "qc_passed":
        se.run_review(job)
    se.save_job(job)
    r = job.get("review") or {}
    print(label, job.get("status"), "LUFS", job["audio"].get("lufs"), "TP", job["audio"].get("true_peak"),
          "render", job["render"].get("elapsed_sec"), "s", "review", r.get("counts"))
    for f in r.get("findings", []):
        print("   ", f["level"], f["code"], f.get("t"), f["message"])


# ── A: 강조어만 넣고 다시 렌더 ──
a = se.load_job("shorts_ab_ai_trend_A")
for s, w in zip(a["storyboard"]["scenes"], EMPH):
    s["emphasis"] = w
if "--skip-a" not in sys.argv:
    finish(a, "A")

# ── B ──
b = copy.deepcopy(a)
b["shorts_id"] = "shorts_ab_ai_trend_B"
for k in ("render", "qc", "review", "lint"):
    b.pop(k, None)
da, db = se.job_dir(a["shorts_id"]), se.job_dir(b["shorts_id"], create=True)
for fn in os.listdir(da):
    if fn.endswith((".png", ".mp3")) and fn != "narration.mp3":
        shutil.copy2(os.path.join(da, fn), db)

scenes = b["storyboard"]["scenes"]
cut_ms = int(round(sum(float(s["seconds"]) for s in scenes[:PAYOFF]) * 1000))
ff = se.producer.ffmpeg_path()
narr_b = os.path.join(db, "narration.mp3")
T = cut_ms / 1000
subprocess.run([ff, "-y", "-v", "error", "-i", a["audio"]["narration"], "-filter_complex",
                f"[0:a]atrim=0:{T},asetpts=N/SR/TB[p1];[0:a]atrim={T},asetpts=N/SR/TB[p2];"
                f"anullsrc=r=24000:cl=mono,atrim=0:{SILENCE_MS / 1000}[z];[p1][z][p2]concat=n=3:v=0:a=1[o]",
                "-map", "[o]", "-ar", "24000", "-ac", "1", narr_b], check=True)
b["audio"]["narration"] = narr_b
b["audio"]["bgm"] = os.path.join(db, "bgm_prepared.mp3")
scenes[PAYOFF - 1]["seconds"] = round(float(scenes[PAYOFF - 1]["seconds"]) + SILENCE_MS / 1000, 2)
scenes[PAYOFF]["transition"] = "none"   # 무음 뒤 보상은 하드컷 한 번(animate: 모프 사이 하드컷은 보상의 슬램 하나)
for c in b["captions"]:
    if c["startMs"] >= cut_ms:
        c["startMs"] += SILENCE_MS
        c["endMs"] += SILENCE_MS
intro_ms = next(c["startMs"] for c in b["captions"] if "여섯" in c["text"])

_orig = se.build_remotion_props


def props_b(job):
    p = _orig(job)
    p.update({"look": "variety",
              "thread": {"items": ITEMS, "firstScene": 1, "introAtMs": intro_ms, "gatherScene": PAYOFF},
              "payoff": {"scene": PAYOFF, "silenceMs": SILENCE_MS}})
    return p


se.build_remotion_props = props_b
se.save_job(b)
finish(b, "B")
