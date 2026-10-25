"""A/B 시험 A: 기존 「AI 트렌드 2026」 잡을 현재 엔진(U-1~U-4) 그대로 다시 만든다. 이미지 재사용, 비용 0."""
import copy, json, os, sys

WT, MAIN = sys.argv[1], sys.argv[2]
sys.path.insert(0, WT)
os.chdir(WT)
import shorts_engine as se  # noqa: E402

SRC = os.path.join(MAIN, "data/shorts/shorts_1792854578_AI_트렌드_2026/job.json")
BGM = os.path.join(MAIN, "data/luna_music/luna_1791097568/audio.mp3")
src = json.load(open(SRC, encoding="utf-8"))

job = copy.deepcopy(src)
job["shorts_id"] = "shorts_ab_ai_trend_A"
for k in ("render", "qc", "publish", "captions", "review", "lint", "progress", "error", "warnings", "metadata"):
    job.pop(k, None)
job["audio"] = {"bgm_track_id": "luna_1791097568"}
job["sfx"] = True
for s in job["storyboard"]["scenes"]:
    for k in ("narration_file", "narration_seconds", "caption_source", "transition", "emphasis"):
        s.pop(k, None)
se.save_job(job)


def picker(_tid=None):
    return {"track_id": "luna_1791097568", "file": BGM, "title": "Breezy Velocity"}


out = se.build_job(job, options={"renderer": "remotion"}, progress_cb=lambda st, m, p: print(f"[{st} {p}%] {m}", flush=True),
                   bgm_picker=picker)
print("STATUS", out.get("status"), out.get("error"))
print("RENDER", (out.get("render") or {}).get("file"), (out.get("render") or {}).get("elapsed_sec"))
print("AUDIO", {k: out["audio"].get(k) for k in ("lufs", "true_peak", "bgm_volume", "bgm_offset")})
print("REVIEW", json.dumps({k: (out.get("review") or {}).get(k) for k in ("counts", "needs_review")}, ensure_ascii=False))
for f in (out.get("review") or {}).get("findings", []):
    print("  ", f["level"], f["code"], f.get("t"), f["message"])
