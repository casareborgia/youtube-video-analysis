# 유튜브 링크 하나로 완전 분석 — 0원 (LM Studio Gemma 4 연동)
# 사용법: python3 analyze.py "https://youtu.be/영상ID"
import sys, os, re, json, subprocess, urllib.request
from pathlib import Path

def sh(args):
    return subprocess.run(args, capture_output=True, text=True).stdout

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else input("유튜브 링크: ").strip()
    match = re.search(r'(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})', url)
    if not match:
        print("❌ 유효한 유튜브 링크나 영상 ID를 찾을 수 없습니다.")
        return
    vid = match.group(1)

    data_dir = Path("./data")
    data_dir.mkdir(exist_ok=True)

    print(f"\n==================================================")
    print(f"🎬 영상 분석 시작: {vid} (https://youtu.be/{vid})")
    print(f"==================================================")

    print("1/4 메타데이터 수집 중...")
    raw_meta = sh(["yt-dlp", "--skip-download", "--dump-json", "https://youtu.be/" + vid])
    if not raw_meta:
        print("❌ 메타데이터를 가져오지 못했습니다.")
        return
    meta = json.loads(raw_meta)
    info = {k: meta.get(k) for k in ["title","channel","channel_follower_count",
            "view_count","like_count","comment_count","duration_string","upload_date"]}

    print("2/4 자막 추출 및 정제 중...")
    srt_base = str(data_dir / vid)
    sh(["yt-dlp", "--skip-download", "--write-auto-subs", "--sub-langs", "ko",
        "--convert-subs", "srt", "-o", srt_base, "https://youtu.be/" + vid])
    
    transcript = "(자막 없음)"
    srt_path = data_dir / f"{vid}.ko.srt"
    if srt_path.exists():
        try:
            seen = []
            for l in open(srt_path, encoding="utf-8").read().splitlines():
                l = l.strip()
                if not l or l.isdigit() or "-->" in l: continue
                if not seen or seen[-1] != l: seen.append(l)
            transcript = " ".join(seen)
        except Exception as e:
            transcript = f"(자막 읽기 실패: {str(e)})"

    print("3/4 댓글 수집 및 정렬 중...")
    c_base = str(data_dir / f"{vid}_c")
    sh(["yt-dlp", "--skip-download", "--write-comments",
        "--extractor-args", "youtube:max_comments=200", "-o", c_base, "https://youtu.be/" + vid])
    
    comments = []
    c_info_path = data_dir / f"{vid}_c.info.json"
    if c_info_path.exists():
        try:
            cs = json.load(open(c_info_path, encoding="utf-8")).get("comments") or []
            cs.sort(key=lambda c: c.get("like_count") or 0, reverse=True)
            comments = ["[" + str(c.get("like_count",0)) + "개 추천] " + (c.get("text") or "").replace("\n", " ")[:120] for c in cs[:15]]
        except Exception:
            pass

    # 1. 자막 스마트 정제 (문맥 훼손 없는 노이즈 제거)
    cleaned_transcript = re.sub(r'\[(?:음악|박수|노래|한숨)\]|\>\>', ' ', transcript)
    cleaned_transcript = re.sub(r'\s+', ' ', cleaned_transcript).strip()
    if len(cleaned_transcript) > 4000:
        cleaned_transcript = cleaned_transcript[:4000]

    # 2. 설명란 정제
    desc_lines = []
    for l in (meta.get("description") or "").splitlines():
        l_str = l.strip()
        if not l_str or l_str.startswith("http") or l_str.startswith("www."): continue
        if "인스타그램" in l_str or "페이스북" in l_str or "트위터" in l_str or "협찬문의" in l_str: continue
        desc_lines.append(l_str)
    cleaned_desc = "\n".join(desc_lines)[:600]

    # 3. 챕터 정보
    chapters = meta.get("chapters", [])
    chapters_str = "\n".join([f"- {c.get('title')}" for c in chapters[:10]]) if chapters else "(챕터 정보 없음)"

    # 4. 고품질 프롬프트 구성
    prompt = (
        "아래 유튜브 영상을 다각도로 심층 분석하여 최고 수준의 분석 리포트를 작성해줘.\n\n"
        "[영상 메타데이터]\n" + json.dumps(info, ensure_ascii=False, indent=2) + "\n\n"
        "[영상 설명란]\n" + (cleaned_desc or "(설명 없음)") + "\n\n"
        "[챕터 타임라인]\n" + chapters_str + "\n\n"
        "[자막 전문 흐름]\n" + cleaned_transcript + "\n\n"
        "[시청자 상위 댓글 여론]\n" + ("\n".join(comments[:12]) if comments else "(댓글 없음)") + "\n\n"
        "--- 반드시 아래 5가지 목차에 따라 심도 있는 분석과 구체적인 액션 플랜을 1번부터 5번 끝까지 완성해주세요 ---\n"
        "## 1. 제목·훅 구조 분석\n"
        "- 클릭을 유발한 심리적 트리거와 제목 키워드 분석\n"
        "- 영상 초반 이탈을 막은 인트로 훅(Hook) 설계 원리\n\n"
        "## 2. 전개 방식 (단계별 서사 구조)\n"
        "- 도입 → 전개 → 절정 → 결말의 단계별 빌드업 메커니즘\n"
        "- 시청 지속 시간을 극대화한 완급 조절 및 연출 특징\n\n"
        "## 3. 핵심 메시지 및 인사이트\n"
        "- 영상이 관객에게 남기는 궁극적인 메시지와 철학/본질\n"
        "- 단순 정보 나열을 넘어선 고유의 콘텐츠적 가치\n\n"
        "## 4. 댓글 여론 특징 및 시청자 반응\n"
        "- 시청자들이 가장 감탄하거나 공감한 포인트 분석\n"
        "- 댓글 반응을 통해 본 채널 팬덤의 특성과 몰입 요인\n\n"
        "## 5. 내 채널/콘텐츠에 적용할 점 3가지 (구체적 실행 방안)\n"
        "- **전략 1 (기획/제목/썸네일):** 내 채널에 바로 적용할 수 있는 구체적인 실행 계획\n"
        "- **전략 2 (연출/스토리텔링):** 시청 유지율을 높이기 위한 실전 연출 방안\n"
        "- **전략 3 (팬덤 구축/확장):** 댓글 참여 및 충성 구독자를 만드는 실행 방안"
    )

    print("4/4 로컬 AI (Ollama/LM Studio: gemma4) 고품질 심층 분석 리포트 생성 중...")
    report = ""
    # 1. Ollama 시도 (Thinking 토큰 감안하여 num_ctx 16384, num_predict 4096 설정)
    try:
        ollama_data = json.dumps({
            "model": "gemma4:latest",
            "messages": [
                {
                    "role": "system", 
                    "content": (
                        "당신은 대한민국 최고의 유튜브 콘텐츠 전략가이자 심층 영상 분석가입니다.\n"
                        "주어진 영상의 메타데이터, 자막 흐름, 시청자 댓글 여론을 다각도로 분석하여 매우 전문적이고 깊이 있는 리포트를 작성하세요.\n"
                        "형식적인 요약에 그치지 말고, 영상의 본질적인 흥행 원리와 구체적인 시사점을 담아 아래 5가지 목차를 1번부터 5번 끝까지 완벽하게 작성해야 합니다."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "options": {
                "num_ctx": 16384,
                "num_predict": 4096,
                "temperature": 0.6
            },
            "stream": False
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=ollama_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            if "message" in res_json and "content" in res_json["message"]:
                report = res_json["message"]["content"]
    except Exception:
        pass

    # 2. LM Studio 폴백
    if not report:
        try:
            lm_data = json.dumps({
                "model": "google/gemma-4-e4b",
                "messages": [
                    {
                        "role": "system", 
                        "content": (
                            "당신은 대한민국 최고의 유튜브 콘텐츠 전략가이자 심층 영상 분석가입니다.\n"
                            "주어진 영상의 메타데이터, 자막 흐름, 시청자 댓글 여론을 다각도로 분석하여 매우 전문적이고 깊이 있는 리포트를 작성하세요.\n"
                            "형식적인 요약에 그치지 말고, 영상의 본질적인 흥행 원리와 구체적인 시사점을 담아 아래 5가지 목차를 1번부터 5번 끝까지 완벽하게 작성해야 합니다."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.6,
                "max_tokens": 4096
            }).encode("utf-8")

            req = urllib.request.Request(
                "http://127.0.0.1:1234/v1/chat/completions",
                data=lm_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=300) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                report = res_json["choices"][0]["message"]["content"]
        except Exception as e:
            report = f"(로컬 AI 서버 연결 실패: {str(e)})\n아래 프롬프트를 다른 AI 모델에 직접 입력하실 수 있습니다)\n\n" + prompt

    report_file = data_dir / f"{vid}_리포트.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    # 기본 메타데이터 JSON도 함께 저장
    metadata_json_path = data_dir / f"{vid}_metadata.json"
    with open(metadata_json_path, "w", encoding="utf-8") as f:
        meta["transcript_summary"] = transcript[:1000]
        meta["ai_report_generated"] = True
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\n" + "="*50)
    print("📋 [AI 영상 분석 리포트]")
    print("="*50)
    print(report)
    print("="*50)
    print(f"💾 리포트 파일 저장 완료: {report_file.resolve()}")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
