# 유튜브 분석 데이터 기반 신규 콘텐츠 & 8초 비디오 프롬프트 생성기
import sys, os, json, re, urllib.request, urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

def call_llm(messages, max_tokens=4096, max_continues=3):
    # LM Studio / Ollama 자동 감지 공용 클라이언트 사용 (llm_client.py)
    import llm_client
    return llm_client.call_llm(messages, max_tokens=max_tokens, temperature=0.75, max_continues=max_continues)

def load_reference_knowledge():
    knowledge = []
    
    # 1. Load ws1Clj0vOAM report & transcript
    ws_report_path = os.path.join(BASE_DIR, "ws1Clj0vOAM_리포트.txt")
    if os.path.exists(ws_report_path):
        ws_rep = open(ws_report_path, encoding="utf-8").read()
        knowledge.append(f"[레퍼런스 분석 데이터: 168만 조회수 난지도 영상]\n{ws_rep[:3500]}")

    ws_sub_path = os.path.join(BASE_DIR, "ws1Clj0vOAM_자막전문.txt")
    if os.path.exists(ws_sub_path):
        ws_sub = open(ws_sub_path, encoding="utf-8").read()
        knowledge.append(f"[레퍼런스 자막 대본 발췌]\n{ws_sub[:2000]}")

    return "\n\n".join(knowledge)

def generate_video_content(topic, num_scenes=10, progress_callback=None):
    """
    주제(topic)를 받아 분석 데이터의 성공 공식을 적용하여
    1. 제목 (3가지 훅 공식 후보)
    2. 설명란 (SEO & 타임스탬프)
    3. 8초 단위 씬별 자막 나레이션 (00:00~00:08, 00:08~00:16...)
    4. 각 8초 씬별 AI 영상 생성 프롬프트 (영문 프롬프트, 카메라 워크, 조명, 화풍)
    를 생성합니다.
    """
    knowledge = load_reference_knowledge()

    # Step 1: Title & Description
    if progress_callback: progress_callback("meta", "1/3 제목 및 디스크립션 훅 기획 중...")
    print(f"1/3 '{topic}' 주제의 유튜브 제목 & 디스크립션 기획 중...")
    
    p1 = f"""당신은 대한민국 최고의 유튜브 지식/다큐멘터리 콘텐츠 총괄 디렉터입니다.
우리가 보유한 168만 조회수 영상의 흥행 분석 데이터(낭만 vs 현실의 극적 대비 훅, 구체적 수치 제시, 해결 불가능한 딜레마 구조)를 100% 흡수하여, 새로운 주제에 대한 콘텐츠를 완벽히 기획해야 합니다.

[성공 공식 레퍼런스 지식]
{knowledge}

[새로운 영상 기획 주제]
"{topic}"

작성 요청 사항:
1. **유튜브 제목 후보 3가지**:
   - 후보 1 (충격 대비형 훅: [낭만적 대상] vs [냉혹한 진실])
   - 후보 2 (스케일/수치 압도형 훅: [정밀 수치] + [공학적 위기])
   - 후보 3 (실패/난제 선언형 훅: [권위 있는 주체]는 결국 [실패]했습니다)
   - 최종 추천 제목 및 선정 이유
2. **유튜브 설명란 (Description)**:
   - 시청자의 호기심을 극대화하는 3줄 요약 줄거리
   - 핵심 시사점 및 전문성 강조 문구
   - 채널 구독 & 알림 설정 유도 CTA
"""
    meta_output = call_llm([{"role": "user", "content": p1}], max_tokens=3500)

    # Step 2 & 3: 8-second scenes, script, and Video Prompts
    if progress_callback: progress_callback("scenes", "2/3 8초 단위 씬별 자막 대본 및 타임스탬프 설계 중...")
    print(f"2/3 8초 단위 씬별 타임스탬프 자막 대본 생성 중 (총 {num_scenes}개 씬 = {num_scenes*8}초)...")

    p2 = f"""앞서 기획한 제목과 세계관을 바탕으로, 영상을 실제로 제작하기 위한 **8초 단위 씬별 나레이션 대본과 타임스탬프**를 작성해주세요.

우리는 AI 비디오 생성 툴(Runway Gen-3, Kling, Luma Dream Machine, Sora)로 **1개에 정확히 8초짜리 영상**을 생성하여 이어붙일 것입니다.
따라서 총 {num_scenes}개의 씬(총 {num_scenes*8}초 분량)을 정확히 8초 단위로 쪼개어, 각 8초 동안 나레이터가 자연스럽게 발화할 수 있는 자막 대본을 작성해주세요.

[전개 구조 5단계 마스터 플롯 적용]:
- 씬 1~2 (00:00 ~ 00:16): 도입부 (The Setup - 낭만적 기대 & 충격적 반전)
- 씬 3~4 (00:16 ~ 00:32): 갈등 심화 (The Crisis - 스케일의 압도 & 문제의 본질)
- 씬 5~6 (00:32 ~ 00:48): 난제 제시 (The Dilemma - 왜 치우거나 해결할 수 없는지 공학적 딜레마)
- 씬 7~8 (00:48 ~ 01:04): 해결 시도 (The Response - 역발상의 정밀 공학적 해법과 구체적 수치)
- 씬 9~10 (01:04 ~ 01:20): 결론 & 여운 (The Critique - 씁쓸한 현실의 통찰 & 깊은 여운)

각 씬마다 아래 형식으로 작성하세요:
- **씬 N (MM:SS ~ MM:SS)**: [핵심 감정/단계]
- **나레이션 자막**: "8초 동안 읽을 수 있는 한 문장 대본 (약 35~45자)"
- **자막 연출 의도**: (간략한 설명)
"""
    scenes_output = call_llm([
        {"role": "user", "content": p1},
        {"role": "assistant", "content": meta_output},
        {"role": "user", "content": p2}
    ], max_tokens=4096)

    # Step 3: AI Video Generation Prompts (Midjourney / Runway / Kling)
    if progress_callback: progress_callback("prompts", "3/3 8초 비디오 생성용 AI 프롬프트 (카메라/조명/디테일) 작성 중...")
    print("3/3 각 씬별 8초 비디오 생성용 AI 영상 프롬프트(Runway/Kling/Sora용) 작성 중...")

    p3 = f"""이제 각 8초짜리 씬에 완벽히 매칭되는 **AI 비디오 생성용 영문 프롬프트 (Video Generation Prompt)**를 작성해주세요.

각 씬(총 {num_scenes}개)마다 영상 생성 AI(Runway Gen-3 Alpha, Kling AI, Luma Dream Machine, Sora, Midjourney)에 바로 붙여넣어 고화질 시네마틱 8초 클립을 생성할 수 있도록 작성하세요.

각 씬별 프롬프트 구성 요소:
1. **Scene Prompt (English)**: 고화질 사실적 시네마틱 묘사 (8k, photorealistic, cinematic documentary style, hyper-detailed, masterpiece)
2. **Camera Movement & Angle**: (예: Drone aerial top-down view slowly descending, Slow cinematic push-in shot, Macro close-up tilt up, Smooth tracking shot)
3. **Lighting & Atmosphere**: (예: Moody volumetric lighting, golden hour mist, dramatic shadowy atmosphere, industrial grim realism)
4. **한국어 비주얼 가이드**: 영상 편집자가 한눈에 이해할 수 있는 화면 구도 설명

모든 씬(씬 1부터 씬 {num_scenes}까지)을 빠짐없이 완결해주세요.
"""
    prompts_output = call_llm([
        {"role": "user", "content": p1},
        {"role": "assistant", "content": meta_output},
        {"role": "user", "content": p2},
        {"role": "assistant", "content": scenes_output},
        {"role": "user", "content": p3}
    ], max_tokens=4096)

    # Combine into full markdown document
    full_document = (
        f"# 🎬 [{topic}] 8초 씬 기반 유튜브 콘텐츠 종합 기획서\n\n"
        f"## 1. 최적화된 유튜브 제목 & 설명란 (Title & SEO Description)\n\n"
        f"{meta_output.strip()}\n\n"
        f"---\n\n"
        f"## 2. 8초 단위 씬별 타임스탬프 & 나레이션 자막 대본 (8-Sec Timestamped Script)\n\n"
        f"{scenes_output.strip()}\n\n"
        f"---\n\n"
        f"## 3. 씬별 AI 비디오 생성 프롬프트 가이드 (8-Sec Video AI Prompts)\n\n"
        f"{prompts_output.strip()}\n"
    )

    # Save to output/ folder (루트에 생성물이 쌓이지 않도록 분리)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_topic = re.sub(r'[\/\\:*?"<>|]', '_', topic)[:30]
    out_file = os.path.join(OUTPUT_DIR, f"{safe_topic}_콘텐츠기획.txt")
    open(out_file, "w", encoding="utf-8").write(full_document)

    # Parse scenes for structured JSON
    structured_scenes = parse_scenes_and_prompts(scenes_output, prompts_output, num_scenes)

    result_json = {
        "topic": topic,
        "meta_text": meta_output,
        "scenes_text": scenes_output,
        "prompts_text": prompts_output,
        "full_document": full_document,
        "structured_scenes": structured_scenes,
        "file_path": out_file
    }

    out_json = os.path.join(OUTPUT_DIR, f"{safe_topic}_콘텐츠기획.json")
    open(out_json, "w", encoding="utf-8").write(json.dumps(result_json, ensure_ascii=False, indent=2))

    return result_json

def parse_scenes_and_prompts(scenes_text, prompts_text, num_scenes):
    """
    텍스트에서 씬별 타임코드, 자막, 프롬프트를 추출하여 구조화된 리스트로 반환
    """
    scenes = []
    
    for i in range(1, num_scenes + 1):
        start_sec = (i - 1) * 8
        end_sec = i * 8
        start_str = f"{start_sec//60:02d}:{start_sec%60:02d}"
        end_str = f"{end_sec//60:02d}:{end_sec%60:02d}"
        time_range = f"{start_str} ~ {end_str}"

        # Find scene subtitle — 실패 시 더미 문구 대신 빈 값 유지 (더미가 TTS로 녹음되는 것 방지)
        scene_sub = ""

        # 1. Search in markdown table lines
        found_in_table = False
        for line in scenes_text.splitlines():
            line_str = line.strip()
            if line_str.startswith('|') and (f'씬 {i}*' in line_str or f'씬 {i} ' in line_str or f'씬 {i}|' in line_str or f'씬 {i}**' in line_str or f'씬{i}' in line_str):
                parts = [p.strip() for p in line_str.split('|') if p.strip()]
                # Typically parts: ['씬 1', '[00:00 ~ 00:08]', '도입 (The Setup)', '"국가 최고 기밀..."', '연출 의도']
                for part in parts:
                    if (part.startswith('"') and part.endswith('"') and len(part) > 10) or ('"' in part and len(part) > 15):
                        scene_sub = re.sub(r'[*_#`"]', '', part).strip()
                        found_in_table = True
                        break
                if not found_in_table and len(parts) >= 4:
                    # fallback to 4th column
                    scene_sub = re.sub(r'[*_#`"]', '', parts[3]).strip()
                    found_in_table = True
                break

        # 2. Search in block format
        if not found_in_table:
            sub_match = re.search(rf'씬\s*{i}[^\n]*\n([\s\S]*?)(?=씬\s*{i+1}|\Z)', scenes_text)
            if sub_match:
                sub_body = sub_match.group(1).strip()
                quote_match = re.search(r'"([^"]{5,})"', sub_body)
                if quote_match:
                    scene_sub = quote_match.group(1).strip()
                else:
                    lines = [l.replace('*', '').replace('#', '').strip() for l in sub_body.splitlines() if l.strip() and not l.strip().startswith('|')]
                    if lines:
                        scene_sub = lines[0]

        # Clean scene_sub
        scene_sub = re.sub(r'^[\s\|:"]+|[\s\|:"]+$', '', scene_sub).strip()

        # Find prompt
        prompt_en = f"Cinematic documentary footage, hyper-detailed, 8k, photorealistic, smooth slow motion, cinematic lighting --ar 16:9"
        camera_info = "Slow cinematic push-in shot"
        prompt_match = re.search(rf'씬\s*{i}[^\n]*\n([\s\S]*?)(?=씬\s*{i+1}|\Z)', prompts_text)
        if prompt_match:
            p_body = prompt_match.group(1).strip()
            en_match = re.search(r'(?:Scene Prompt|Prompt|프롬프트)[^:\n]*:\s*([^\n]+)', p_body, re.IGNORECASE)
            if en_match:
                prompt_en = en_match.group(1).replace('*', '').strip()
            cam_match = re.search(r'(?:Camera|카메라)[^:\n]*:\s*([^\n]+)', p_body, re.IGNORECASE)
            if cam_match:
                camera_info = cam_match.group(1).replace('*', '').strip()

        scenes.append({
            "scene_num": i,
            "time_range": time_range,
            "subtitle": scene_sub,
            "parse_ok": bool(scene_sub),
            "prompt_en": prompt_en,
            "camera": camera_info
        })
        
    return scenes

if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "지하 50층 비밀 벙커의 진실"
    res = generate_video_content(topic, num_scenes=10)
    print("\n" + "="*60)
    print(f"✅ [{topic}] 콘텐츠 기획 & 8초 비디오 프롬프트 생성 완료!")
    print("="*60)
    print(res["full_document"][:1800])
    print("\n... (전체 내용 저장 완료)")
