"""Shiji Files 자동 루틴 (launchd 에서 실행, LLM 미사용).

  comments  매일: 예약 공개된 Shiji 쇼츠가 YouTube 에서 public 이 되면 원문 댓글을 단다(고정은 Studio 수동).
  prep      매주 일요일: 채널 조회수 스냅샷 + 아직 렌더 안 된 Shiji 잡을 ComfyUI 로 빌드한다.
            업로드는 하지 않는다 — 사람이 결과를 보고 허락한 뒤 올린다.

공통: 결과는 logs/shiji_routine.log 에 한 줄씩, 끝나면 macOS 알림. --dry-run 은 바꾸지 않고 할 일만 보여 준다.
"""
import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.getcwd() if os.path.exists(os.path.join(os.getcwd(), "shorts_engine.py")) else \
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SHIJI_CHANNEL_ID = "UC0o0PWB665I9q7ZTmLOcBwQ"
SERVER = "http://127.0.0.1:8765"
COMFY_URL = "http://127.0.0.1:8188"
COMFY_DIR = os.path.expanduser("~/ComfyUI-Installs/LeeSeungJUN/ComfyUI")
COMFY_PATHS = os.path.expanduser(
    "~/Library/Application Support/Comfy Desktop/instance-model-paths/inst-1792756541591.yaml")
BUILD_TIMEOUT_S = 40 * 60
LOG = os.path.join(ROOT, "logs", "shiji_routine.log")
OUT = os.path.join(ROOT, "output", "shiji_channel_analysis")


def log(msg: str) -> None:
    line = f"{dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def notify(title: str, msg: str) -> None:
    msg = msg.replace('"', "'")[:200]
    subprocess.run(["/usr/bin/osascript", "-e", f'display notification "{msg}" with title "{title}"'],
                   capture_output=True)


def shiji_jobs() -> list:
    jobs = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "shorts", "*", "job.json"))):
        try:
            j = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if j.get("concept_key") == "shorts_shiji":
            jobs.append(j)
    return jobs


def _yt():
    import uploader
    return uploader._service(uploader._creds(SHIJI_CHANNEL_ID))


# ---------------------------------------------------------------- comments
def pending_comment_jobs(jobs: list) -> list:
    out = []
    for j in jobs:
        pub = (j.get("publish") or {}).get("youtube") or {}
        if pub.get("video_id") and pub.get("channel_id") == SHIJI_CHANNEL_ID and not pub.get("comment_posted") \
                and pub.get("comment_pending"):
            out.append(j)
    return out


def run_comments(dry_run: bool) -> int:
    import shorts_engine
    import shorts_publish
    todo = pending_comment_jobs(shiji_jobs())
    if not todo:
        log("comments: 대기 중인 원문 댓글 없음")
        return 0
    yt = _yt()
    ids = [j["publish"]["youtube"]["video_id"] for j in todo]
    status = {v["id"]: v["status"]["privacyStatus"]
              for v in yt.videos().list(part="status", id=",".join(ids)).execute().get("items", [])}
    posted, waiting, failed = [], [], []
    for j in todo:
        pub = j["publish"]["youtube"]
        vid = pub["video_id"]
        if status.get(vid) != "public":
            waiting.append(f"{vid}({status.get(vid, 'missing')})")
            continue
        if dry_run:
            posted.append(f"{vid}(dry-run)")
            continue
        pub["privacy"] = "public"
        shorts_engine.save_job(j)
        try:
            j = shorts_publish.post_original_comment(j)
        except Exception as e:  # noqa: BLE001 — 한 편 실패가 다른 편을 막지 않게
            failed.append(f"{vid}: {e}")
            continue
        (posted if j["publish"]["youtube"].get("comment_posted") else failed).append(vid)
    log(f"comments: posted={','.join(posted) or '-'} waiting={','.join(waiting) or '-'} failed={'; '.join(failed) or '-'}")
    if posted and not dry_run:
        notify("Shiji Files 원문 댓글", f"{len(posted)}편 등록 — Studio 에서 고정하세요: {', '.join(posted)}")
    if failed:
        notify("Shiji Files 원문 댓글 실패", "; ".join(failed))
        return 1
    return 0


# ---------------------------------------------------------------- prep
def snapshot(today: str) -> str:
    yt = _yt()
    ch = yt.channels().list(part="statistics,contentDetails", id=SHIJI_CHANNEL_ID).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    vids = []
    for k in range(0, len(ids), 50):
        vids += yt.videos().list(part="snippet,statistics,status", id=",".join(ids[k:k + 50])).execute()["items"]
    rows = []
    for v in sorted(vids, key=lambda v: v["snippet"]["publishedAt"]):
        st, s = v["status"], v["statistics"]
        rows.append({"id": v["id"], "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                     "privacy": st["privacyStatus"], "publishAt": st.get("publishAt"),
                     "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                     "comments": int(s.get("commentCount", 0))})
    os.makedirs(OUT, exist_ok=True)
    json.dump({"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "channel": ch["statistics"], "videos": rows},
              open(os.path.join(OUT, f"snapshot_{today}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = [f"# Shiji Files 스냅샷 {today} (Data API, 조회수만)", "",
          f"구독 {ch['statistics'].get('subscriberCount')} · 누적 조회 {ch['statistics'].get('viewCount')}", "",
          "| 공개(UTC) | 제목 | 상태 | 조회 | 좋아요 |", "|---|---|---|---|---|"]
    for r in rows:
        if r["privacy"] == "public" or r["publishAt"]:
            md.append(f"| {(r['publishAt'] or r['published'])[:10]} | {r['title']} | {r['privacy']} | {r['views']} | {r['likes']} |")
    path = os.path.join(OUT, f"snapshot_{today}.md")
    open(path, "w", encoding="utf-8").write("\n".join(md) + "\n")
    return path


def _http(method: str, path: str, body=None, base=SERVER, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def comfy_up() -> bool:
    try:
        _http("GET", "/system_stats", base=COMFY_URL, timeout=5)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_comfy():
    """헤드리스로 띄우고 Popen 을 돌려준다(이 루틴이 띄운 것만 끈다)."""
    logf = open(os.path.join(ROOT, "logs", "shiji_comfy.log"), "a")
    p = subprocess.Popen([".venv/bin/python", "main.py", "--port", "8188", "--extra-model-paths-config", COMFY_PATHS],
                         cwd=COMFY_DIR, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(120):
        if comfy_up():
            return p
        if p.poll() is not None:
            raise RuntimeError(f"ComfyUI 가 바로 종료됨(rc={p.returncode}) — logs/shiji_comfy.log")
        time.sleep(2)
    p.terminate()
    raise RuntimeError("ComfyUI 가 4분 안에 뜨지 않음")


def unrendered_jobs(jobs: list) -> list:
    return [j for j in jobs
            if not ((j.get("publish") or {}).get("youtube") or {}).get("video_id")
            and not (j.get("render") or {}).get("file")
            and j.get("status") not in ("assets", "rendering")]


def build_one(sid: str, voice_id: str) -> dict:
    r = _http("POST", f"/api/shorts/jobs/{sid}/build", {"renderer": "remotion", "voice_id": voice_id})
    if r.get("status") != "started":
        raise RuntimeError(f"빌드 시작 안 됨: {r.get('status')} {r.get('message') or r.get('detail') or ''}")
    t0 = time.time()
    time.sleep(5)
    while time.time() - t0 < BUILD_TIMEOUT_S:
        d = _http("GET", f"/api/shorts/jobs/{sid}")
        if not d.get("building"):
            return d["data"]
        time.sleep(15)
    raise RuntimeError("빌드 시간 초과(40분)")


def run_prep(dry_run: bool) -> int:
    today = dt.date.today().isoformat()
    try:
        snap = snapshot(today) if not dry_run else "(dry-run: 스냅샷 생략)"
    except Exception as e:  # noqa: BLE001 — 스냅샷 실패해도 렌더는 진행
        snap = f"스냅샷 실패: {e}"
    todo = unrendered_jobs(shiji_jobs())
    log(f"prep: snapshot={snap} jobs={','.join(j['shorts_id'] for j in todo) or '-'}")
    if not todo or dry_run:
        notify("Shiji Files 주간 준비", f"렌더할 잡 {len(todo)}편{' (dry-run)' if dry_run else ''} · {os.path.basename(snap)}")
        return 0
    try:
        _http("GET", "/api/shorts/usage", timeout=10)
    except Exception as e:  # noqa: BLE001
        log(f"prep: 서버 응답 없음 {e}")
        notify("Shiji Files 주간 준비 실패", "8765 서버 응답 없음 — luna-server 확인")
        return 1
    comfy = None if comfy_up() else start_comfy()
    done, failed = [], []
    try:
        for j in todo:
            sid = j["shorts_id"]
            try:
                res = build_one(sid, j.get("voice_id") or "edge_andrew_en")
            except Exception as e:  # noqa: BLE001
                failed.append(f"{sid}: {e}")
                continue
            dur = ((res.get("render") or {}).get("probe") or {}).get("duration")
            if res.get("status") == "qc_passed":
                done.append(f"{sid}({dur:.1f}s)" if dur else sid)
            else:
                failed.append(f"{sid}: status={res.get('status')} {res.get('error') or ''}")
    finally:
        if comfy is not None:
            comfy.terminate()
            try:
                comfy.wait(timeout=30)
            except subprocess.TimeoutExpired:
                comfy.kill()
    log(f"prep: done={','.join(done) or '-'} failed={'; '.join(failed) or '-'}")
    notify("Shiji Files 주간 준비",
           f"렌더 {len(done)}편 완료{f', 실패 {len(failed)}편' if failed else ''} — 검수 후 업로드 허락 필요")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["comments", "prep"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        return run_comments(a.dry_run) if a.mode == "comments" else run_prep(a.dry_run)
    except Exception as e:  # noqa: BLE001
        log(f"{a.mode}: error {type(e).__name__}: {e}")
        notify(f"Shiji Files {a.mode} 실패", str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
