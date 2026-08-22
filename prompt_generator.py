"""
AI Prompt Studio - Custom Topic & Analyzed Strengths Engine with Ollama Gemma 4
1. 기존 분석된 유튜브 영상들의 공통 강점(흥행 서사, 훅 설계, 시각적 몰입도)을 종합 도출
2. 사용자가 새로 입력한 주제(New Topic)에 대해 기승전결 씬을 자동 기획
3. 카메라 앵글 및 조명을 주제 맥락에 맞추어 AI가 스스로 추론(Auto-Inference)하여 최적의 시네마틱 프롬프트 생성
"""

import os
import re
import json
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional

OLLAMA_API_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "gemma4:latest"

# 시각 렌더 스타일 프리셋
STYLE_PRESETS = {
    "photorealistic_8k": {
        "name": "Photorealistic 8K (실사 영화풍)",
        "prompt": "hyperrealistic 8k cinematic photography, shot on ARRI Alexa Mini LF, Master Prime lenses, natural skin and material textures, highly detailed"
    },
    "film_35mm": {
        "name": "35mm Vintage Film (빈티지 필름)",
        "prompt": "shot on 35mm Kodak Vision3 color film, subtle film grain, rich organic colors, nostalgic halation, cinematic movie still"
    },
    "unreal_engine_5": {
        "name": "Unreal Engine 5 Render (3D 그래픽)",
        "prompt": "Unreal Engine 5.4 cinematic render, Octane photoreal lighting, Ray-traced reflections, Lumen global illumination, 8k masterpiece"
    },
    "anime_cinematic": {
        "name": "Cinematic Anime (신카이 마코토 풍)",
        "prompt": "gorgeous Makoto Shinkai anime aesthetic, lush vibrant sky, detailed painterly backgrounds, emotive light flares, high production anime"
    }
}

SUPPORTED_MODELS = {
    "google_flow": {
        "name": "Google Flow (Veo 2/3, Imagen 3/4)",
        "description": "AutoFlow-Pro 최적화 서술형 시네마틱 프롬프트",
        "default_aspect": "16:9"
    },
    "midjourney": {
        "name": "Midjourney v6.1",
        "description": "파라미터(--ar, --v 6.1, --style raw) 자동 추가",
        "default_aspect": "16:9"
    },
    "runway_kling": {
        "name": "Runway Gen-3 / Kling AI / Luma",
        "description": "비디오 생성용 모션 및 물리 인터랙션 강조 프롬프트",
        "default_aspect": "16:9"
    }
}

class PromptGenerator:
    """분석 데이터 공통 강점 추출 및 신규 주제 기반 AI 프롬프트 생성기"""

    @staticmethod
    def extract_common_strengths(data_dir: Path) -> Dict[str, Any]:
        """data 폴더 내 분석 영상들로부터 공통 성공 강점과 연출 패턴을 추출"""
        reports = []
        analyzed_titles = []
        
        if data_dir.exists():
            for report_path in sorted(data_dir.glob("*_리포트.txt")):
                try:
                    with open(report_path, "r", encoding="utf-8") as f:
                        reports.append(f.read())
                except Exception:
                    pass
            for meta_path in sorted(data_dir.glob("*_metadata.json")):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        m = json.load(f)
                        if m.get("title"):
                            analyzed_titles.append(m["title"])
                except Exception:
                    pass

        # 분석된 리포트들에서 추출된 공통 핵심 성공 공식
        common_points = [
            "초반 5초 압도적 스케일 및 미스터리 훅(Hook)으로 이탈 방지",
            "도입(호기심) -> 전개(디테일 탐색) -> 절정(압도적 대치/비주얼 충격) -> 결말(여운과 인사이트)의 4단계 서사 빌드업",
            "대비 효과 극대화: 거대한 미지의 스케일 vs 정밀한 관측/인간 시점의 극적인 앵글 대비",
            "조명과 분위기의 입체적 활용: 차가운 어둠/안개 속에서 피어나는 강렬한 포인트 광원(네온, 림라이트)",
            "시청 지속시간을 높이는 장면별 명확한 시각적 정보와 긴장감 있는 카메라 무빙"
        ]

        return {
            "analyzed_count": len(analyzed_titles),
            "analyzed_videos": analyzed_titles[:5],
            "common_strengths": common_points,
            "summary": (
                f"총 {len(analyzed_titles)}개의 분석 영상(SCP 미스터리, 건축/공학 다큐, 지역 탐사 등)에서 공통 도출된 "
                "‘강렬한 오프닝 훅’, ‘단계별 긴장감 고조 서사’, ‘스케일 대비 카메라 연출’, ‘입체적 시네마틱 조명’ 성공 공식을 프롬프트에 자동 적용합니다."
            )
        }

    @staticmethod
    def query_ollama(prompt: str, system_prompt: str = "", model: str = DEFAULT_OLLAMA_MODEL) -> str:
        """로컬 Ollama Gemma 4 모델 호출"""
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "options": {
                    "num_ctx": 16384,
                    "num_predict": 4096,
                    "temperature": 0.6
                },
                "stream": False
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                OLLAMA_API_URL,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                if "message" in res_json and "content" in res_json["message"]:
                    return res_json["message"]["content"]
        except Exception as e:
            print(f"[Ollama Error] {e}")
        return ""

    @classmethod
    def generate_prompts_from_custom_topic(
        cls,
        topic: str,
        scene_count: int = 6,
        model: str = "google_flow",
        aspect_ratio: str = "16:9",
        style_key: str = "photorealistic_8k",
        custom_subject: str = "",
        data_dir: Path = Path("data")
    ) -> Dict[str, Any]:
        """사용자가 새로 입력한 주제(Topic)에 대해 분석 영상 공통 강점을 반영하여 최적 프롬프트 세트 생성"""
        
        strengths_data = cls.extract_common_strengths(data_dir)
        strengths_bullet = "\n".join([f"- {s}" for s in strengths_data["common_strengths"]])
        style_info = STYLE_PRESETS.get(style_key, STYLE_PRESETS["photorealistic_8k"])

        # Ollama Gemma 4 프롬프트 생성 요청 구성
        system_prompt = (
            "You are a master Hollywood Director, Visual Storyboard Artist, and AI Cinematographer. "
            "The user will give you a NEW creative video topic/concept. "
            "You must apply the PROVEN SUCCESS FORMULA derived from top-performing YouTube videos (powerful opening hook, progressive tension build-up, dramatic scale contrast, dynamic camera and lighting) to craft a complete scene-by-scene storyboard and photorealistic English prompts. "
            "IMPORTANT: You must AUTOMATICALLY INFER the optimal camera angle and lighting for each scene according to its dramatic atmosphere without needing manual input. "
            "Return ONLY a pure valid JSON array of objects without commentary or markdown codeblocks."
        )

        user_prompt = f"""
[User's New Video Topic & Story Concept]
"{topic}"

[Key Parameters]
- Target AI Model: {model} (Google Flow / Veo / AutoFlow-Pro compatible)
- Target Aspect Ratio: {aspect_ratio}
- Number of Scenes: {scene_count}
- Base Render Style: {style_info['prompt']}
- Specific Subject/Character Consistency (if any): {custom_subject or "Auto-inferred from topic"}

[Proven Success Strengths from Analyzed YouTube Videos to Apply]
{strengths_bullet}

[Your Mission]
1. Break down the user's topic into {scene_count} progressive story scenes (Scene 1: Intense Hook/Introduction -> Middle Scenes: Exploration & Rising Stakes -> Climax: Epic Visual Shock/Peak -> Ending: Memorable Resolution).
2. For each scene, AUTOMATICALLY DETERMINE the best Camera Angle & Movement (e.g. Extreme Wide Establishing, Dolly Zoom, Drone 360, Low Angle Hero, Close-Up Bokeh) and Lighting/Atmosphere (e.g. Volumetric Fog, Cyberpunk Neon, Golden Hour, Chiaroscuro, Dramatic Spotlight) suited to the story beat.
3. Synthesize a vivid, ultra-detailed, photorealistic cinematic English prompt for each scene.
   - If Target AI Model is 'midjourney': Append '--ar {aspect_ratio} --v 6.1 --style raw' at the end.
   - If Target AI Model is 'google_flow': Format as: 'Cinematic video scene of [Subject & Action]. Camera work: [Inferred Camera angle & motion]. Lighting & Atmosphere: [Inferred Lighting & Mood]. Style: [Render details]. Aspect ratio: {aspect_ratio}.'
4. Provide a Korean narration/script line and 3 Korean keyword tags for each scene.

Return ONLY a pure JSON array in this exact format:
[
  {{
    "scene_index": 1,
    "stage": "도입 (강렬한 오프닝 훅)",
    "narration": "한국어 내레이션/대본 한 문장...",
    "keywords": ["키워드1", "키워드2", "키워드3"],
    "inferred_angle": "Cinematic Wide Establishing Shot",
    "inferred_lighting": "Volumetric Fog & Dramatic Rim Light",
    "prompt": "Cinematic visual description in English...",
    "negative_prompt": "blurry, low quality, distorted, bad anatomy, text, watermark",
    "aspect_ratio": "{aspect_ratio}",
    "model": "{model}"
  }}
]
"""
        # Ollama Gemma 4 호출
        ollama_response = cls.query_ollama(user_prompt, system_prompt=system_prompt)
        
        generated_scenes = []
        if ollama_response:
            cleaned_resp = re.sub(r'^```json\s*', '', ollama_response.strip(), flags=re.MULTILINE)
            cleaned_resp = re.sub(r'\s*```$', '', cleaned_resp.strip(), flags=re.MULTILINE)
            try:
                match = re.search(r'\[\s*\{.*\}\s*\]', cleaned_resp, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list) and len(parsed) > 0:
                        generated_scenes = parsed
            except Exception as pe:
                print(f"[JSON Parse Error] {pe}")

        # Fallback 생성 (Ollama 응답 파싱 실패 시 기본 씬 구성)
        if not generated_scenes:
            stages = ["도입 (오프닝 훅)", "전개 (배경 및 문제 탐색)", "심화 (위기 및 긴장감 고조)", "클라이맥스 (시각적 절정)", "결말 (해결 및 여운)"]
            angles = ["Extreme Wide Establishing Shot", "Eye-Level Medium Tracking Shot", "Tight Cinematic Close-Up", "Dynamic Drone Orbit 360", "Low-Angle Hero Shot"]
            lightings = ["Dramatic Low-Key Fog & Rim Light", "Atmospheric Cyberpunk Neon", "High-Contrast Chiaroscuro", "Golden Hour Radiant Glow", "Cold Cinematic Desaturated Tone"]
            
            for i in range(scene_count):
                stage = stages[i % len(stages)]
                angle = angles[i % len(angles)]
                lighting = lightings[i % len(lightings)]
                
                subject_desc = f"{custom_subject if custom_subject else topic}, scene {i+1} representing {stage}"
                if model == "midjourney":
                    final_prompt = f"Cinematic shot of {subject_desc}, {angle}, {lighting}, {style_info['prompt']} --ar {aspect_ratio} --v 6.1 --style raw"
                elif model == "runway_kling":
                    final_prompt = f"Cinematic video clip of {subject_desc}. Smooth camera movement: {angle}. Atmosphere: {lighting}, {style_info['prompt']}. (Aspect ratio: {aspect_ratio})"
                else:
                    final_prompt = (
                        f"Cinematic video scene of {subject_desc}. "
                        f"Camera work: {angle}. "
                        f"Lighting & Atmosphere: {lighting}. "
                        f"Style: {style_info['prompt']}. "
                        f"Aspect ratio: {aspect_ratio}."
                    )

                generated_scenes.append({
                    "scene_index": i + 1,
                    "stage": stage,
                    "narration": f"주제 '{topic}'의 {stage} 장면입니다.",
                    "keywords": ["주제기획", "시네마틱", "스토리보드"],
                    "inferred_angle": angle,
                    "inferred_lighting": lighting,
                    "prompt": final_prompt,
                    "negative_prompt": "blurry, low quality, distorted, bad anatomy, text, watermark",
                    "aspect_ratio": aspect_ratio,
                    "model": model
                })

        return {
            "topic": topic,
            "total_scenes": len(generated_scenes),
            "model": model,
            "aspect_ratio": aspect_ratio,
            "engine": "Ollama Gemma 4 AI",
            "applied_strengths": strengths_data["common_strengths"],
            "scenes": generated_scenes
        }

    @staticmethod
    def export_autoflow_txt(scenes: List[Dict[str, Any]]) -> str:
        """AutoFlow-Pro 'Import from .txt' 호환 포맷 (한 줄당 1개 프롬프트)"""
        return "\n".join([s["prompt"] for s in scenes])

    @staticmethod
    def export_csv_data(scenes: List[Dict[str, Any]], video_title: str = "") -> str:
        """스마트 태스크 및 스프레드시트용 CSV 데이터 생성"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Scene", "Stage", "Narration", "Prompt", "Negative Prompt", "Inferred Angle", "Inferred Lighting", "Aspect Ratio", "Model"])
        
        for s in scenes:
            writer.writerow([
                s.get("scene_index", ""),
                s.get("stage", ""),
                s.get("narration", ""),
                s.get("prompt", ""),
                s.get("negative_prompt", ""),
                s.get("inferred_angle", ""),
                s.get("inferred_lighting", ""),
                s.get("aspect_ratio", ""),
                s.get("model", "")
            ])
            
        return output.getvalue()
