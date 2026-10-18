"""어사이드 AI 동향 최신 사례(Gemini 4 Argon) → 60초 쇼츠 — S-1 엔진으로 수동 조립한 1회성 참고 스크립트.

S-2(자동 파이프라인) 전에 "기획서 없이 엔진만으로 쇼츠 1편을 끝까지 만들면 어떤 단계가 필요한가" 를 기록해 둔 것이다.
저장소 루트에서 실행한다:

    .venv/bin/python scripts/build_argon_shorts.py tts                      # edge-tts 나레이션 + 어절 타이밍 → job.json
    .venv/bin/python scripts/build_argon_shorts.py preview [bgm.mp3]        # 색 배경 플레이스홀더 렌더(싱크 확인, 비용 0)
    .venv/bin/python scripts/build_argon_shorts.py render0 [bgm.mp3]        # 타이포·데이터 씬으로 재조립 렌더(비용 0)
    .venv/bin/python scripts/build_argon_shorts.py images                   # (과금) Gemini 씬 이미지 — 사용자 승인 후에만
    .venv/bin/python scripts/build_argon_shorts.py render [bgm.mp3]         # images 결과로 최종 렌더

실측(2026-10-19): tts 6씬 52.9초, render0 Remotion 28~33초·비용 0원, 3번 씬만 gemini-2.5-flash-image 1장(768×1344, 9.3초) 교체한 v3 가 최종본.
"""
import asyncio, json, os, subprocess, sys, time, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 저장소 루트
import edge_tts
import shorts_engine as se
import producer

SID = "shorts_argon_ai_trend"
VOICE = "ko-KR-InJoonNeural"; RATE = "+6%"
D = se.job_dir(SID, create=True)
FF = producer.ffmpeg_path()

STORY = {
    "hook_text": "로봇이 스스로 연습한다?",
    "end_tag": {"text": "구독하고 다음 AI 동향 보기", "subtext": "어사이드 AI 브리핑 · 출처 GeekNews", "seconds": 2.0},
    "scenes": [
        {"narration": "로봇이 시뮬레이션에서 스스로 연습하고 실제로 움직입니다. 구글 제미나이 4 아르곤 이야기입니다.",
         "motion": "zoom_in",
         "subject": "a sleek humanoid robot standing in a dark lab, a glowing holographic copy of itself practicing the same pose beside it, cinematic rim light, deep navy and amber"},
        {"narration": "공간 추론 시험 ERQA에서 87퍼센트. 클로드 오퍼스와 GPT-6보다 앞섰습니다.",
         "motion": "pan_left",
         "subject": "minimal editorial bar chart made of three glowing vertical glass bars of different heights on a dark desk, the tallest bar amber, soft studio light, no labels"},
        {"narration": "보스턴다이내믹스 스팟은 세 다리로 균형을 잡고, 페달을 밟아 캔을 버렸습니다.",
         "motion": "zoom_out",
         "subject": "a yellow quadruped robot dog balancing on three legs, pressing a pedal trash can with one front foot, holding a soda can with its arm, modern kitchen, photoreal"},
        {"narration": "영상 한 편, 손그림 한 장이면 물리 시뮬레이션 쌍둥이를 만들어 냅니다.",
         "motion": "pan_right",
         "subject": "split composition: left a hand-drawn pencil sketch of a robot throwing a ball at stacked boxes, right the same scene rendered as a glossy 3D physics simulation, wireframe transition in the middle"},
        {"narration": "시뮬레이션으로 학습한 로봇은 성공률이 56에서 75퍼센트로, 작업 시간은 35초에서 24초로 줄었습니다.",
         "motion": "zoom_in",
         "subject": "two robotic arms tidying party props on a table, a translucent rising arrow graphic floating above, clean product-shot lighting, teal and amber accents"},
        {"narration": "레고 옮기기는 세 번 만에 59초에서 17초로. 로봇 시대, 어디까지 왔을까요?",
         "motion": "zoom_out",
         "subject": "a small desktop robot arm placing a LEGO brick into a wooden box, three ghosted afterimages of the arm showing faster motion, warm desk lamp light, shallow depth of field"},
    ],
}

async def tts_scene(i, text):
    out = os.path.join(D, f"narr_{i:02d}.mp3")
    comm = edge_tts.Communicate(text, voice=VOICE, rate=RATE, boundary="WordBoundary")
    audio = bytearray(); words = []
    async for ch in comm.stream():
        if ch["type"] == "audio": audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append({"text": ch["text"], "startMs": ch["offset"] // 10000, "endMs": (ch["offset"] + ch["duration"]) // 10000})
    with open(out, "wb") as f: f.write(audio)
    return out, words

def step_tts():
    scenes = []
    cursor_ms = 0; captions = []
    for i, sc in enumerate(STORY["scenes"], 1):
        mp3, words = asyncio.run(tts_scene(i, sc["narration"]))
        dur = producer.audio_duration(mp3) or 0
        # 씬 길이 = 나레이션 + 여운 0.7초, 최소 5초, 0.1초 단위
        sec = max(5.0, round(dur + 0.7, 1))
        for k, w in enumerate(words):
            tok = {"text": (" " if k > 0 else "") + w["text"], "startMs": cursor_ms + w["startMs"], "endMs": cursor_ms + w["endMs"]}
            if k == len(words) - 1: tok["pageBreakAfter"] = True
            captions.append(tok)
        scenes.append({"scene_num": i, "seconds": sec, "motion": sc["motion"], "narration": sc["narration"], "audio": mp3, "audio_sec": dur, "subject": sc["subject"]})
        cursor_ms += int(sec * 1000)
        print(f"씬 {i}: 음성 {dur:.2f}s → 씬 {sec}s, 어절 {len(words)}개")
    total = sum(s["seconds"] for s in scenes) + STORY["end_tag"]["seconds"]
    print(f"총 길이 {total:.1f}s (상한 60)")
    # 나레이션을 씬 길이에 맞춰 무음 패딩 후 이어붙임 → narration.mp3
    parts = []
    for s in scenes:
        parts.append(f"-i {s['audio']}")
    fc = ";".join(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur={s['seconds']}[a{i}]" for i, s in enumerate(scenes))
    fc += ";" + "".join(f"[a{i}]" for i in range(len(scenes))) + f"concat=n={len(scenes)}:v=0:a=1[a]"
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error"]
    for s in scenes: cmd += ["-i", s["audio"]]
    cmd += ["-filter_complex", fc, "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "192k", os.path.join(D, "narration.mp3")]
    subprocess.run(cmd, check=True)
    job = {
        "shorts_id": SID, "format": "scene", "status": "planned",
        "source": {"routine": "AI_TREND", "outbox_job_id": 85, "title": "Google, Gemini 4 Argon의 로봇 제어와 시뮬레이션 활용 사례 공개", "url": "https://news.hada.io/topic?id=35326"},
        "storyboard": {"hook_text": STORY["hook_text"], "hook_seconds": 3.0,
                       "scenes": [{k: v for k, v in s.items() if k in ("scene_num", "seconds", "motion", "narration", "subject")} for s in scenes],
                       "end_tag": STORY["end_tag"]},
        "captions": captions, "caption_source": "edge_tts",
        "audio": {"narration": os.path.join(D, "narration.mp3"), "bgm": None, "bgm_volume": 0.14},
        "brand": "ASIDE AI BRIEF", "accent": "#ffd166",
    }
    se.save_job(job)
    print("job.json 저장, 총 어절", len(captions), "narration.mp3", producer.audio_duration(os.path.join(D, "narration.mp3")))

if __name__ == "__main__" and sys.argv[1] == "tts":
    step_tts()

PALETTE = ["0x1b2a4a", "0x3a1f4f", "0x0f3d3e", "0x4a2a1b", "0x1f3f2a", "0x2b1b4a"]

def step_preview():
    """Gemini 호출 없이 색 배경 플레이스홀더로 렌더 — 자막 싱크·길이 확인용."""
    job = se.load_job(SID)
    for s in job["storyboard"]["scenes"]:
        i = s["scene_num"]; p = os.path.join(D, f"placeholder_{i:02d}.png")
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c={PALETTE[(i-1) % len(PALETTE)]}:s=1080x1920:d=1",
                        "-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1",
                        "-filter_complex", "[1:v]format=rgba,colorchannelmixer=aa=0.18[t];[0:v][t]overlay,format=rgb24",
                        "-frames:v", "1", p], check=True)
        s["image"] = p
    job["audio"]["bgm"] = sys.argv[2] if len(sys.argv) > 2 else None
    job = se.render_shorts(job, renderer="remotion")
    r = job["render"]; print("PREVIEW", r["renderer_used"], r["elapsed_sec"], r.get("probe"))

def step_render():
    """data/renders/<plan_id>/scene_XX.* 의 Gemini 이미지로 최종 렌더."""
    job = se.load_job(SID)
    plan_id = job["image_plan_id"]
    rd = producer.render_dir(plan_id)
    for s in job["storyboard"]["scenes"]:
        i = s["scene_num"]
        cands = [os.path.join(rd, f"scene_{i:02d}{ext}") for ext in (".png", ".jpg")]
        img = next((c for c in cands if os.path.exists(c)), None)
        if not img: raise SystemExit(f"씬 {i} 이미지 없음: {cands}")
        s["image"] = img
    if len(sys.argv) > 2: job["audio"]["bgm"] = sys.argv[2]
    job = se.render_shorts(job, renderer="remotion")
    r = job["render"]; print("FINAL", r["renderer_used"], r["elapsed_sec"], r.get("probe"), r.get("fallback_reason"))

if __name__ == "__main__" and sys.argv[1] in ("preview", "render"):
    {"preview": step_preview, "render": step_render}[sys.argv[1]]()

def step_images():
    """Gemini(나노바나나) 9:16 씬 이미지 6장 — 사용자 승인 후에만 실행. producer.generate_images 재사용."""
    job = se.load_job(SID)
    plan_id = f"scenes_{int(time.time())}_argon_shorts"
    scenes = []
    for s in job["storyboard"]["scenes"]:
        block = {
            "scene": {
                "subject": s["subject"],
                "format": "vertical 9:16 mobile composition, main subject in the central 60% of the frame, generous clean space at the top and bottom for overlays",
                "lighting": "cinematic, high contrast, one warm amber accent light",
                "mood": "futuristic, precise, calm",
            },
            "text_layer": [],
        }
        scenes.append({"scene_num": s["scene_num"], "image_prompt_json": block, "subtitle": s["narration"]})
    plan = {"plan_id": plan_id, "aspect_ratio": "9:16", "concept_key": "info_breakdown", "structured_scenes": scenes, "thumbnail_prompt": None}
    def prog(stage, msg, pct): print(f"[{pct}%] {msg}")
    res = producer.generate_images(plan, slots=[s["scene_num"] for s in scenes], progress=prog)
    print("generated:", res["generated"], "errors:", res["errors"])
    job["image_plan_id"] = plan_id
    se.save_job(job)
    print("plan_id", plan_id, "→", producer.render_dir(plan_id))

if __name__ == "__main__" and sys.argv[1] == "images":
    step_images()

KIND_SCENES = [
    {"kind": "text_card", "title": "로봇이 스스로 연습한다", "subtitle": "Google · Gemini 4 Argon", "palette": 0},
    {"kind": "bar_chart", "title": "ERQA 공간 추론 벤치마크", "unit": "%", "decimals": 1, "palette": 1,
     "bars": [{"label": "Gemini 4 Argon", "value": 87, "highlight": True}, {"label": "Claude Opus 5.5", "value": 82.3}, {"label": "GPT-6 Astra", "value": 81}]},
    {"kind": "stat_card", "title": "Boston Dynamics Spot", "value": 18, "unit": "자유도", "label": "다리 12 + 팔 6을 한 번에 제어\n세 다리로 균형 → 페달 밟고 캔 버리기", "palette": 2},
    {"kind": "text_card", "title": "영상 1편 · 손그림 1장 → 물리 시뮬레이션", "subtitle": "Real2Sim 디지털 트윈", "palette": 3},
    {"kind": "compare", "title": "시뮬레이션 데이터로 학습한 결과", "palette": 4,
     "rows": [{"label": "실제 로봇 성공률", "from": 56, "to": 75, "unit": "%"}, {"label": "작업 완료 시간", "from": 35, "to": 24, "unit": "초"}]},
    {"kind": "compare", "title": "LEGO 옮기기 · 세 번의 자기 개선", "palette": 5,
     "rows": [{"label": "첫 시도 → 세 번째 시도", "from": 58.9, "to": 17.4, "unit": "초", "decimals": 1}]},
]

def step_render0():
    """이미지 없이(비용 0) 타이포·데이터 씬으로 재조립해 렌더."""
    job = se.load_job(SID)
    scenes = job["storyboard"]["scenes"]
    assert len(scenes) == len(KIND_SCENES)
    for s, k in zip(scenes, KIND_SCENES):
        s.pop("image", None)
        s.update(k)
    job["audio"]["bgm"] = sys.argv[2] if len(sys.argv) > 2 else None
    job["audio"]["bgm_volume"] = 0.14
    job["format"] = "scene"
    job["cost_krw"] = 0
    job = se.render_shorts(job, renderer="remotion")
    r = job["render"]; print("RENDER0", r["renderer_used"], r["elapsed_sec"], r.get("probe"), r.get("fallback_reason"))

if __name__ == "__main__" and sys.argv[1] == "render0":
    step_render0()
