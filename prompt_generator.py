"""
AI Prompt Studio & AutoFlow-Pro Integration Engine with Ollama Gemma 4
유튜브 분석 결과(AI 리포트, 메타데이터, 자막, 서사 구조)를 바탕으로
Ollama Gemma 4가 주제(Topic) 기반의 씬별 시네마틱 프롬프트를 자동 생성하는 엔진입니다.
"""

import os
import re
import json
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional

OLLAMA_API_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "gemma4:latest"

# AutoFlow-Pro & Google Flow 카메라 앵글 프리셋
CAMERA_ANGLES = {
    "cinematic_wide": {
        "name": "Cinematic Wide Shot (와이드 샷)",
        "prompt": "extreme wide cinematic establishing shot, expansive composition, grand scale, deep depth of field",
        "description": "배경과 전체적인 공간감을 웅장하게 보여주는 광각 구도"
    },
    "medium_shot": {
        "name": "Medium Shot (미디엄 샷)",
        "prompt": "eye-level medium shot, balanced composition, natural perspective, cinematic subject framing",
        "description": "인물과 주변 환경의 균형을 보여주는 표준 구도"
    },
    "close_up": {
        "name": "Cinematic Close-Up (클로즈업)",
        "prompt": "tight cinematic close-up shot, intense facial focus, shallow depth of field, f/1.8 lens bokeh",
        "description": "피사체의 디테일과 감정을 강조하는 근접 구도"
    },
    "drone_orbit": {
        "name": "Drone 360 Orbit (드론 회전 샷)",
        "prompt": "sweeping high-angle drone orbit camera movement, smooth 360 rotation around subject, cinematic parallax",
        "description": "피사체 주변을 360도 회전하며 입체감을 주는 역동적 앵글"
    },
    "low_angle_hero": {
        "name": "Low-Angle Hero Shot (로우 앵글)",
        "prompt": "dramatic low-angle hero shot looking up, powerful commanding perspective, majestic imposing composition",
        "description": "웅장하고 압도적인 느낌을 주는 아래에서 위로 바라보는 앵글"
    },
    "dolly_zoom": {
        "name": "Dolly Zoom (버티고 샷)",
        "prompt": "dramatic cinematic dolly zoom vertigo effect, background warping with intense dramatic tension",
        "description": "배경 왜곡을 통해 극적인 긴장감을 연출하는 줌 효과"
    },
    "pov_action": {
        "name": "First-Person POV (1인칭 시점)",
        "prompt": "first-person point-of-view perspective, immersive dynamic motion, authentic field of view",
        "description": "주인공의 눈으로 직접 바라보는 듯한 몰입형 시점"
    }
}

# 조명 & 분위기 프리셋
LIGHTING_PRESETS = {
    "golden_hour": {
        "name": "Golden Hour (골든 아워)",
        "prompt": "bathed in warm golden hour sunlight, soft radiant rim light, long atmospheric shadows, magical dusk atmosphere"
    },
    "cyberpunk_neon": {
        "name": "Cyberpunk Neon (네온 조명)",
        "prompt": "vibrant cyberpunk neon lighting, moody cyan and magenta color palette, dark atmospheric reflections on wet asphalt"
    },
    "volumetric_fog": {
        "name": "Volumetric Fog & God Rays (신비로운 안개)",
        "prompt": "mystical volumetric fog, dramatic god rays piercing through haze, cinematic chiaroscuro contrast"
    },
    "dramatic_studio": {
        "name": "Dramatic Studio Lighting (스튜디오 조명)",
        "prompt": "professional three-point studio lighting, crisp key light, subtle fill, razor-sharp edge highlight"
    },
    "dark_documentary": {
        "name": "Dark Moody Documentary (다큐멘터리 무드)",
        "prompt": "moody investigative documentary lighting, naturalistic low-key shadows, desaturated cool tones"
    }
}

# 시각 스타일 프리셋
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
    """분석 데이터(리포트/자막/메타데이터) 기반 Ollama Gemma 4 프롬프트 생성기"""

    @staticmethod
    def get_analyzed_topics_list(data_dir: Path) -> List[Dict[str, Any]]:
        """data 폴더에 이미 분석 완료된 영상들의 주제 및 메타데이터 목록 추출"""
        topics = []
        if not data_dir.exists():
            return topics

        for meta_path in sorted(data_dir.glob("*_metadata.json")):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    
                video_id = meta.get("id", meta_path.stem.replace("_metadata", ""))
                title = meta.get("title", video_id)
                channel = meta.get("channel", "")
                
                # AI 리포트 존재 여부 및 요약 추출
                report_path = data_dir / f"{video_id}_리포트.txt"
                has_report = report_path.exists()
                report_summary = ""
                if has_report:
                    try:
                        with open(report_path, "r", encoding="utf-8") as rf:
                            lines = [l.strip() for l in rf.readlines() if l.strip() and not l.startswith("#")]
                            report_summary = " ".join(lines[:3])[:120] + "..."
                    except Exception:
                        pass
                
                # 자막 존재 여부
                srt_path = data_dir / f"{video_id}.ko.srt"
                has_srt = srt_path.exists()
                
                topics.append({
                    "video_id": video_id,
                    "title": title,
                    "channel": channel,
                    "has_report": has_report,
                    "has_srt": has_srt,
                    "report_summary": report_summary,
                    "duration": meta.get("duration_string") or meta.get("duration_formatted", ""),
                    "tags": meta.get("tags", [])[:5],
                    "topic_label": f"[{channel}] {title}"
                })
            except Exception:
                continue

        return topics

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
                    "temperature": 0.5
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

    @staticmethod
    def parse_srt(srt_content: str) -> List[Dict[str, Any]]:
        """SRT 자막 내용을 타임스탬프와 텍스트 단위로 정밀 파싱"""
        if not srt_content or not srt_content.strip():
            return []
        
        entries = []
        blocks = re.split(r'\n\s*\n', srt_content.strip())
        
        for block in blocks:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            if len(lines) < 2:
                continue
            
            time_line_idx = -1
            for idx, line in enumerate(lines):
                if "-->" in line:
                    time_line_idx = idx
                    break
            
            if time_line_idx == -1:
                continue
            
            time_line = lines[time_line_idx]
            match = re.match(r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})', time_line)
            if not match:
                continue
            
            start_time = match.group(1).replace(',', '.')[:8]
            end_time = match.group(2).replace(',', '.')[:8]
            
            text_lines = lines[time_line_idx + 1:]
            text = " ".join(text_lines)
            text = re.sub(r'<[^>]+>', '', text).strip()
            if text:
                entries.append({
                    "start": start_time,
                    "end": end_time,
                    "text": text
                })
        
        return entries

    @staticmethod
    def segment_into_scenes(
        srt_entries: List[Dict[str, Any]], 
        target_scene_count: int = 6,
        summary_text: str = ""
    ) -> List[Dict[str, Any]]:
        """자막 엔트리 또는 요약 리포트 서사를 바탕으로 N개의 씬(Scene) 분할"""
        if not srt_entries:
            sentences = [s.strip() for s in re.split(r'[.\n]+', summary_text) if len(s.strip()) > 10]
            if not sentences:
                sentences = ["영상 인트로 훅 장면", "주제 설명 및 심층 분석 전개", "핵심 하이라이트 및 클라이맥스", "인사이트 요약 및 엔딩"]
            
            scenes = []
            chunk_size = max(1, len(sentences) // target_scene_count)
            for i in range(0, min(len(sentences), target_scene_count * chunk_size), chunk_size):
                chunk = sentences[i:i+chunk_size]
                scene_text = " ".join(chunk)
                scenes.append({
                    "scene_index": len(scenes) + 1,
                    "time_range": f"Scene {len(scenes) + 1}",
                    "narration": scene_text,
                    "keywords": []
                })
            return scenes

        total = len(srt_entries)
        chunk_size = max(1, total // target_scene_count)
        
        scenes = []
        for i in range(0, total, chunk_size):
            chunk = srt_entries[i:i+chunk_size]
            if not chunk:
                continue
            
            start_time = chunk[0]["start"]
            end_time = chunk[-1]["end"]
            combined_text = " ".join([c["text"] for c in chunk])
            
            words = combined_text.split()
            cleaned_words = []
            for w in words:
                if not cleaned_words or cleaned_words[-1] != w:
                    cleaned_words.append(w)
            narration = " ".join(cleaned_words)
            
            scenes.append({
                "scene_index": len(scenes) + 1,
                "time_range": f"{start_time} ~ {end_time}",
                "narration": narration[:250],
                "keywords": []
            })
            
            if len(scenes) >= target_scene_count:
                break
                
        return scenes

    @classmethod
    def generate_batch_from_video(
        cls,
        video_id: str,
        data_dir: Path,
        model: str = "google_flow",
        scene_count: int = 6,
        angle_key: str = "cinematic_wide",
        lighting_key: str = "golden_hour",
        style_key: str = "photorealistic_8k",
        aspect_ratio: str = "16:9",
        custom_subject: str = ""
    ) -> Dict[str, Any]:
        """분석 데이터(AI 리포트, 자막, 메타데이터)를 반영하여 Ollama Gemma 4가 시네마틱 프롬프트 생성"""
        srt_file = data_dir / f"{video_id}.ko.srt"
        meta_file = data_dir / f"{video_id}_metadata.json"
        report_file = data_dir / f"{video_id}_리포트.txt"
        
        title = video_id
        srt_content = ""
        report_content = ""
        description = ""
        chapters = []
        
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    title = meta.get("title", video_id)
                    description = meta.get("description", "")
                    chapters = meta.get("chapters", [])
            except Exception:
                pass
                
        if report_file.exists():
            try:
                with open(report_file, "r", encoding="utf-8") as f:
                    report_content = f.read()
            except Exception:
                pass

        if srt_file.exists():
            try:
                with open(srt_file, "r", encoding="utf-8") as f:
                    srt_content = f.read()
            except Exception:
                pass

        # 1. 씬 분할
        srt_entries = cls.parse_srt(srt_content)
        scenes = cls.segment_into_scenes(srt_entries, target_scene_count=scene_count, summary_text=report_content or description)
        
        angle_info = CAMERA_ANGLES.get(angle_key, CAMERA_ANGLES["cinematic_wide"])
        lighting_info = LIGHTING_PRESETS.get(lighting_key, LIGHTING_PRESETS["golden_hour"])
        style_info = STYLE_PRESETS.get(style_key, STYLE_PRESETS["photorealistic_8k"])
        
        # 2. Ollama Gemma 4 프롬프트 생성 요청 구성
        system_prompt = (
            "You are a master Hollywood AI Cinematographer and Visual Storyboard Director. "
            "You are given comprehensive YouTube analysis data including AI deep report, narrative breakdown, timestamps, and scene narrations. "
            "Your mission is to transform each scene into a stunning, photorealistic, cinematic English prompt for state-of-the-art video & image generation models (Google Flow / Veo, Midjourney, Runway Gen-3, Kling). "
            "Return ONLY a pure valid JSON array of objects without commentary or markdown codeblocks."
        )

        scenes_context = []
        for s in scenes:
            scenes_context.append({
                "scene_index": s["scene_index"],
                "time_range": s["time_range"],
                "narration": s["narration"]
            })

        user_prompt = f"""
[Video Analysis Data & Topic]
- Video Title: {title}
- Target AI Model: {model}
- Target Aspect Ratio: {aspect_ratio}
- Fixed Subject Consistency: {custom_subject or "None"}
- Camera Direction: {angle_info['prompt']}
- Lighting & Mood: {lighting_info['prompt']}
- Visual Style: {style_info['prompt']}

[Extracted AI Analysis Insights & Storyline]
{report_content[:1500] if report_content else description[:800]}

[Scene Breakdowns to Convert]
{json.dumps(scenes_context, ensure_ascii=False, indent=2)}

[Output Requirements]
1. For each scene, synthesize a vivid, ultra-detailed cinematic visual prompt describing the subject action, environment, camera movement, lighting, and composition based on the analysis insights.
2. If Target AI Model is 'midjourney', append '--ar {aspect_ratio} --v 6.1 --style raw' at the end.
3. If Target AI Model is 'google_flow', format as: 'Cinematic video scene of [Subject & Action]. Camera work: [Camera movement & angle]. Lighting & Atmosphere: [Lighting details]. Style: [Render & Lens]. Aspect ratio: {aspect_ratio}.'
4. Provide 3-4 visual keyword tags in Korean for each scene.
5. Return ONLY a pure JSON array in this exact format:
[
  {{
    "scene_index": 1,
    "time_range": "00:00:00 ~ 00:00:30",
    "narration": "...",
    "keywords": ["키워드1", "키워드2", "키워드3"],
    "prompt": "Cinematic visual description in English...",
    "negative_prompt": "blurry, low quality, distorted, watermark, bad anatomy",
    "angle": "{angle_info['name']}",
    "lighting": "{lighting_info['name']}",
    "style": "{style_info['name']}",
    "aspect_ratio": "{aspect_ratio}",
    "model": "{model}"
  }}
]
"""
        # 3. Ollama Gemma 4 호출
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

        # 4. Fallback 생성 (Ollama 응답 파싱 실패 시에도 대본과 리포트 반영)
        if not generated_scenes:
            angle_keys = list(CAMERA_ANGLES.keys())
            for idx, sc in enumerate(scenes):
                cur_angle_key = angle_keys[idx % len(angle_keys)] if angle_key == "auto_variety" else angle_key
                cur_angle = CAMERA_ANGLES.get(cur_angle_key, angle_info)
                
                subject_desc = custom_subject if custom_subject else f"cinematic scene depicting {title} narrative"
                if model == "midjourney":
                    final_prompt = f"Cinematic shot of {subject_desc}, {cur_angle['prompt']}, {lighting_info['prompt']}, {style_info['prompt']} --ar {aspect_ratio} --v 6.1 --style raw"
                elif model == "runway_kling":
                    final_prompt = f"Cinematic video clip of {subject_desc}. Smooth camera movement: {cur_angle['prompt']}. Atmosphere: {lighting_info['prompt']}, {style_info['prompt']}. (Aspect ratio: {aspect_ratio})"
                else:
                    final_prompt = (
                        f"Cinematic video scene of {subject_desc}. "
                        f"Camera work: {cur_angle['prompt']}. "
                        f"Lighting & Environment: {lighting_info['prompt']}. "
                        f"Style & Render: {style_info['prompt']}. "
                        f"Aspect ratio: {aspect_ratio}."
                    )

                generated_scenes.append({
                    "scene_index": sc["scene_index"],
                    "time_range": sc["time_range"],
                    "narration": sc["narration"],
                    "keywords": ["주제분석", "시네마틱", "스토리보드"],
                    "prompt": final_prompt,
                    "negative_prompt": "blurry, low resolution, artifacts, distorted features, bad anatomy, floating text",
                    "angle": cur_angle["name"],
                    "lighting": lighting_info["name"],
                    "style": style_info["name"],
                    "aspect_ratio": aspect_ratio,
                    "model": model
                })

        return {
            "video_id": video_id,
            "title": title,
            "total_scenes": len(generated_scenes),
            "model": model,
            "aspect_ratio": aspect_ratio,
            "engine": "Ollama Gemma 4 AI",
            "has_report_applied": bool(report_content),
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
        writer.writerow(["Scene", "Time Range", "Narration", "Prompt", "Negative Prompt", "Camera Angle", "Lighting", "Style", "Aspect Ratio", "Model"])
        
        for s in scenes:
            writer.writerow([
                s.get("scene_index", ""),
                s.get("time_range", ""),
                s.get("narration", ""),
                s.get("prompt", ""),
                s.get("negative_prompt", ""),
                s.get("angle", ""),
                s.get("lighting", ""),
                s.get("style", ""),
                s.get("aspect_ratio", ""),
                s.get("model", "")
            ])
            
        return output.getvalue()
