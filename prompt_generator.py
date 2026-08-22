"""
AI Prompt Studio & AutoFlow-Pro Integration Engine
유튜브 영상 분석 데이터(자막 SRT, 메타데이터, AI 리포트)를 기반으로
Google Flow (Veo/Imagen), Midjourney, Runway, Kling AI 등에 최적화된
고품질 시네마틱 영상/이미지 프롬프트를 자동 생성하는 엔진입니다.
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# 주요 시네마틱/비주얼 번역 및 강화 사전
VISUAL_KEYWORD_MAP = {
    "인공지능": "advanced artificial intelligence interface, glowing holographic neural network",
    "AI": "futuristic AI system, neon circuit board, high-tech cyberspace data stream",
    "기술": "cutting-edge futuristic technology, sleek industrial design, glowing fiber optics",
    "로봇": "sleek autonomous humanoid robot, polished chrome and carbon fiber texture",
    "미래": "cyberpunk metropolis at night, neon-lit skyscrapers, flying vehicles in distance",
    "우주": "vast deep space, cosmic nebula with vibrant colors, starry galaxy background",
    "자연": "lush untouched cinematic nature landscape, towering ancient trees, morning mist",
    "도시": "bustling urban metropolis, glass architecture, cinematic reflections on wet pavement",
    "연구": "high-tech research laboratory, clean white aesthetics, illuminated microscope slides",
    "비밀": "mysterious dimly lit underground archive, dusty shafts of light through old windows",
    "데이터": "abstract digital data streams, floating numbers and glowing particles in 3D space",
    "음악": "atmospheric soundstage, vintage analog synthesizers with glowing vacuum tubes",
    "회의": "modern glass boardroom, executive brainstorming session, cinematic shallow depth of field",
    "스마트폰": "sleek modern smartphone with glowing holographic display floating above screen",
    "컴퓨터": "multi-monitor hacker workstation, dark room illuminated by neon blue monitor glow",
    "밤": "atmospheric midnight atmosphere, deep moody shadows, ambient city lights",
    "새벽": "serene early dawn, soft pastel sky, gentle golden rim lighting",
    "노을": "dramatic crimson sunset, silhouettes against vibrant orange and purple sky",
    "바다": "crystal clear turquoise ocean waves, dramatic sea foam crashing on volcanic rocks",
    "산": "majestic snow-capped mountain peaks, dramatic clouds rolling over rugged terrain",
    "숲": "mystical dense ancient forest, god rays filtering through lush canopy, mossy ground",
    "인터뷰": "cinematic documentary interview setup, dramatic key lighting, blurred bokeh backdrop",
    "발표": "keynote presentation on grand dark stage, single powerful spotlight on speaker",
    "경고": "dramatic flashing red alarm lights, dark futuristic corridor, tense atmosphere",
    "성공": "triumphant celebration, golden confetti drifting in slow motion, warm celebratory glow"
}

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

# 모델별 출력 최적화 포맷터
SUPPORTED_MODELS = {
    "google_flow": {
        "name": "Google Flow (Veo 2/3, Imagen 3/4)",
        "description": "AutoFlow-Pro 최적화 서술형 시네마틱 프롬프트",
        "ratio_param": lambda r: f"Aspect ratio: {r}",
        "default_aspect": "16:9"
    },
    "midjourney": {
        "name": "Midjourney v6.1",
        "description": "파라미터(--ar, --v 6.1, --style raw) 자동 추가",
        "ratio_param": lambda r: f"--ar {r.replace(':', ':')} --v 6.1 --style raw --q 2",
        "default_aspect": "16:9"
    },
    "runway_kling": {
        "name": "Runway Gen-3 / Kling AI / Luma",
        "description": "비디오 생성용 모션 및 물리 인터랙션 강조 프롬프트",
        "ratio_param": lambda r: f"Camera motion enabled, {r}",
        "default_aspect": "16:9"
    }
}

class PromptGenerator:
    """유튜브 분석 데이터를 AI 영상 생성 프롬프트로 변환하는 생성기"""

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
            
            # 타임코드 라인 찾기
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
            
            # HTML 태그 등 제거
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
        """자막 엔트리를 내용 및 시간 흐름에 따라 N개의 씬(Scene)으로 분할"""
        if not srt_entries:
            # 자막이 없는 경우 요약 텍스트를 문장 단위로 분할
            sentences = [s.strip() for s in re.split(r'[.\n]+', summary_text) if len(s.strip()) > 10]
            if not sentences:
                sentences = ["영상 인트로 장면", "주제 설명 및 핵심 내용 전개", "핵심 하이라이트 및 클라이맥스", "엔딩 및 마무리"]
            
            scenes = []
            chunk_size = max(1, len(sentences) // target_scene_count)
            for i in range(0, min(len(sentences), target_scene_count * chunk_size), chunk_size):
                chunk = sentences[i:i+chunk_size]
                scene_text = " ".join(chunk)
                scenes.append({
                    "scene_index": len(scenes) + 1,
                    "time_range": f"Scene {len(scenes) + 1}",
                    "narration": scene_text,
                    "keywords": PromptGenerator.extract_keywords(scene_text)
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
            
            # 중복 단어 정리
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
                "keywords": PromptGenerator.extract_keywords(narration)
            })
            
            if len(scenes) >= target_scene_count:
                break
                
        return scenes

    @staticmethod
    def extract_keywords(text: str) -> List[str]:
        """텍스트에서 시각화에 적합한 핵심 명사/키워드 추출"""
        found_keywords = []
        for kr_key in VISUAL_KEYWORD_MAP.keys():
            if kr_key in text:
                found_keywords.append(kr_key)
        
        # 키워드가 부족한 경우 일반 명사형 단어 추출
        if len(found_keywords) < 2:
            tokens = re.findall(r'[가-힣]{2,}', text)
            stopwords = {"이것", "저것", "우리가", "그리고", "하지만", "때문에", "대한", "통해", "어떤", "가장", "정말", "매우"}
            for t in tokens:
                if t not in stopwords and t not in found_keywords:
                    found_keywords.append(t)
                if len(found_keywords) >= 4:
                    break
                    
        return found_keywords[:4]

    @classmethod
    def build_prompt_for_scene(
        cls,
        scene: Dict[str, Any],
        video_title: str = "",
        model: str = "google_flow",
        angle_key: str = "cinematic_wide",
        lighting_key: str = "golden_hour",
        style_key: str = "photorealistic_8k",
        aspect_ratio: str = "16:9",
        custom_subject: str = ""
    ) -> Dict[str, Any]:
        """씬 데이터와 모디파이어를 결합하여 최종 프롬프트 생성"""
        
        # 1. 피사체 및 비주얼 요소 구성
        visual_elements = []
        for kw in scene.get("keywords", []):
            if kw in VISUAL_KEYWORD_MAP:
                visual_elements.append(VISUAL_KEYWORD_MAP[kw])
        
        if not visual_elements:
            visual_elements.append("dramatic cinematic scene capturing the core essence")
        
        subject_desc = ", ".join(visual_elements)
        if custom_subject:
            subject_desc = f"{custom_subject}, {subject_desc}"
        
        # 2. 모디파이어 적용
        angle = CAMERA_ANGLES.get(angle_key, CAMERA_ANGLES["cinematic_wide"])
        lighting = LIGHTING_PRESETS.get(lighting_key, LIGHTING_PRESETS["golden_hour"])
        style = STYLE_PRESETS.get(style_key, STYLE_PRESETS["photorealistic_8k"])
        
        # 3. 모델별 프롬프트 구조화
        if model == "midjourney":
            core_prompt = f"Cinematic shot of {subject_desc}, {angle['prompt']}, {lighting['prompt']}, {style['prompt']}"
            final_prompt = f"{core_prompt} --ar {aspect_ratio} --v 6.1 --style raw"
            negative_prompt = "--no blurry, low quality, distorted anatomy, text, watermark, bad hands"
        
        elif model == "runway_kling":
            core_prompt = f"Cinematic video clip: {subject_desc}. Smooth camera movement: {angle['prompt']}. Atmosphere: {lighting['prompt']}, {style['prompt']}."
            final_prompt = f"{core_prompt} (Aspect Ratio: {aspect_ratio}, Motion strength: 5, 4k ultra-high definition)"
            negative_prompt = "static, jittery motion, blurry artifacts, distorted faces, watermark"
            
        else:  # google_flow (Default - AutoFlow Pro / Veo / Imagen 3)
            # Google Flow / AutoFlow-Pro 친화적 구조: [Subject & Action] + [Camera & Angle] + [Lighting & Style] + [Aspect Ratio]
            final_prompt = (
                f"Cinematic video scene of {subject_desc}. "
                f"Camera work: {angle['prompt']}. "
                f"Lighting & Environment: {lighting['prompt']}. "
                f"Style & Render: {style['prompt']}. "
                f"Aspect ratio: {aspect_ratio}."
            )
            negative_prompt = "blurry, low resolution, artifacts, distorted features, bad anatomy, floating text"

        return {
            "scene_index": scene["scene_index"],
            "time_range": scene["time_range"],
            "narration": scene["narration"],
            "keywords": scene.get("keywords", []),
            "prompt": final_prompt,
            "negative_prompt": negative_prompt,
            "angle": angle["name"],
            "lighting": lighting["name"],
            "style": style["name"],
            "aspect_ratio": aspect_ratio,
            "model": model
        }

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
        """영상 ID의 분석 파일(SRT, JSON, 리포트)을 로드하여 전체 씬 배치 프롬프트 세트 생성"""
        srt_file = data_dir / f"{video_id}.ko.srt"
        meta_file = data_dir / f"{video_id}_metadata.json"
        report_file = data_dir / f"{video_id}_리포트.txt"
        
        title = video_id
        srt_content = ""
        summary_text = ""
        
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    title = meta.get("title", video_id)
                    summary_text = meta.get("description", "")
            except Exception:
                pass
                
        if srt_file.exists():
            try:
                with open(srt_file, "r", encoding="utf-8") as f:
                    srt_content = f.read()
            except Exception:
                pass
                
        if report_file.exists() and not summary_text:
            try:
                with open(report_file, "r", encoding="utf-8") as f:
                    summary_text = f.read()
            except Exception:
                pass

        # 1. 자막 파싱 및 씬 분할
        srt_entries = cls.parse_srt(srt_content)
        scenes = cls.segment_into_scenes(srt_entries, target_scene_count=scene_count, summary_text=summary_text)
        
        # 앵글 다양성 부여를 위한 앵글 시퀀스 (단일 앵글이 아니면 씬마다 자연스럽게 변경)
        angle_keys = list(CAMERA_ANGLES.keys())
        
        # 2. 씬별 프롬프트 생성
        generated_scenes = []
        for idx, sc in enumerate(scenes):
            # 사용자가 특정 앵글을 지정하지 않았거나 'auto_variety'일 경우 앵글 순환
            cur_angle = angle_key
            if angle_key == "auto_variety":
                cur_angle = angle_keys[idx % len(angle_keys)]
                
            prompt_data = cls.build_prompt_for_scene(
                scene=sc,
                video_title=title,
                model=model,
                angle_key=cur_angle,
                lighting_key=lighting_key,
                style_key=style_key,
                aspect_ratio=aspect_ratio,
                custom_subject=custom_subject
            )
            generated_scenes.append(prompt_data)
            
        return {
            "video_id": video_id,
            "title": title,
            "total_scenes": len(generated_scenes),
            "model": model,
            "aspect_ratio": aspect_ratio,
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
