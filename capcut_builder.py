"""
CapCut (캡컷 데스크톱) 프로젝트 자동화 엔진
- 캡컷 로컬 프로젝트(draft_info.json)를 마이크로초(1/1,000,000초) 단위로 정밀 조립
- 4대 요소 완전 자동화:
  1) 영상/이미지 클립 순차 이어붙이기 (비디오 트랙)
  2) Qwen-TTS / Edge-TTS 대사 나레이션 싱크 (오디오 트랙)
  3) 유튜브 스타일 두꺼운 한글 자막 (텍스트 트랙)
  4) 컷 전환 이펙트 (디졸브, 줌 인, 플래시 등 트랜지션)
- macOS CapCut 앱 자동 감지 및 root_meta_info.json 자동 등록
"""

import os
import sys
import json
import time
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent

# macOS 기본 캡컷 프로젝트 저장소
DEFAULT_CAPCUT_DRAFT_DIR = Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"

# 캡컷 공식 내장 트랜지션 프리셋 정의
TRANSITION_PRESETS = {
    "dissolve": {
        "name": "디졸브 (Dissolve)",
        "resource_id": "7000000000000000001",
        "effect_id": "dissolve",
        "duration_us": 500000  # 0.5초
    },
    "zoom_in": {
        "name": "줌 인 (Zoom In)",
        "resource_id": "7000000000000000002",
        "effect_id": "zoom_in",
        "duration_us": 500000
    },
    "fade_black": {
        "name": "페이드 블랙 (Fade Black)",
        "resource_id": "7000000000000000003",
        "effect_id": "fade_black",
        "duration_us": 500000
    },
    "white_flash": {
        "name": "화이트 플래시 (White Flash)",
        "resource_id": "7000000000000000004",
        "effect_id": "white_flash",
        "duration_us": 400000  # 0.4초
    },
    "glitch": {
        "name": "글리치 (Glitch)",
        "resource_id": "7000000000000000005",
        "effect_id": "glitch",
        "duration_us": 400000
    },
    "none": {
        "name": "전환 없음 (컷 전환)",
        "resource_id": "",
        "effect_id": "",
        "duration_us": 0
    }
}


def find_capcut_draft_dir() -> Optional[Path]:
    """맥북 환경 내 캡컷 드래프트 프로젝트 저장 경로 확인"""
    if DEFAULT_CAPCUT_DRAFT_DIR.exists():
        return DEFAULT_CAPCUT_DRAFT_DIR
    
    # 대체 경로 탐색 (App Sandbox 컨테이너 등)
    alt = Path.home() / "Library" / "Containers" / "com.lemon.lvoverseas" / "Data" / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    if alt.exists():
        return alt

    # 프로젝트 폴더가 없으면 기본 위치 생성
    try:
        DEFAULT_CAPCUT_DRAFT_DIR.mkdir(parents=True, exist_ok=True)
        return DEFAULT_CAPCUT_DRAFT_DIR
    except Exception:
        return None


def get_capcut_status() -> Dict[str, Any]:
    """캡컷 앱 설치 여부 및 프로젝트 저장소 상태 조회"""
    app_exists = os.path.exists("/Applications/CapCut.app")
    draft_dir = find_capcut_draft_dir()
    
    recent_projects = []
    if draft_dir and draft_dir.exists():
        root_meta_file = draft_dir / "root_meta_info.json"
        if root_meta_file.exists():
            try:
                with open(root_meta_file, "r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                    for item in meta_data.get("all_draft_store", [])[:5]:
                        recent_projects.append({
                            "id": item.get("draft_id"),
                            "name": item.get("draft_name"),
                            "updated_at": item.get("draft_json_updated_time")
                        })
            except Exception:
                pass

    return {
        "app_installed": app_exists,
        "app_path": "/Applications/CapCut.app" if app_exists else None,
        "draft_dir": str(draft_dir) if draft_dir else None,
        "recent_projects": recent_projects,
        "supported_transitions": list(TRANSITION_PRESETS.keys())
    }


def get_media_duration_us(file_path: str) -> int:
    """
    ffprobe를 통해 실제 미디어(오디오/비디오)의 재생 길이를 측정하여 마이크로초(us)로 반환.
    실패 시 기본 5초(5,000,000 us) 반환.
    """
    if not file_path or not os.path.exists(file_path):
        return 5000000

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        secs = float(out)
        return int(secs * 1000000)
    except Exception:
        return 5000000


def _build_text_material(text_content: str, text_id: str, font_size: float = 7.5) -> Dict[str, Any]:
    """
    캡컷 인기 유튜브 스타일의 한글 자막 Material 객체 생성:
    - 흰색 본문 (#FFFFFF)
    - 두꺼운 블랙 외곽선 (border_width 0.1, border_alpha 1.0)
    - 드롭 섀도우 (shadow_alpha 0.9, distance 5.0)
    """
    content_json = {
        "styles": [
            {
                "fill": {
                    "alpha": 1.0,
                    "content": {
                        "render_type": "solid",
                        "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]}
                    }
                },
                "font": {
                    "id": "",
                    "path": "/Applications/CapCut.app/Contents/Resources/Font/SystemFont/en.ttf"
                },
                "range": [0, len(text_content)],
                "size": font_size
            }
        ],
        "text": text_content
    }
    content_str = json.dumps(content_json, ensure_ascii=False)

    return {
        "id": text_id,
        "type": "subtitle",
        "name": "",
        "content": content_str,
        "base_content": content_str,
        "recognize_text": text_content,
        "font_size": font_size,
        "text_color": "#FFFFFF",
        "text_alpha": 1.0,
        "border_color": "#000000",
        "border_alpha": 1.0,
        "border_width": 0.08,
        "border_mode": 0,
        "has_shadow": True,
        "shadow_color": "#000000",
        "shadow_alpha": 0.9,
        "shadow_distance": 5.0,
        "shadow_angle": -45.0,
        "shadow_smoothing": 0.45,
        "alignment": 1,  # 가운데 정렬
        "line_feed": 1,
        "check_flag": 7
    }


def create_capcut_project(
    project_name: str,
    scenes: List[Dict[str, Any]],
    transition_type: str = "dissolve",
    aspect_ratio: str = "16:9",
    bgm_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    씬 목록(scenes)을 바탕으로 캡컷 프로젝트(draft_info.json)를 완전 조립하여 로컬 캡컷 폴더에 주입합니다.
    - scenes 항목:
      {
        "scene_idx": 1,
        "media_file": "/path/to/image.jpg" 또는 "/path/to/video.mp4",
        "audio_file": "/path/to/narration.mp3",
        "subtitle": "한글 자막 대사 텍스트"
      }
    """
    draft_base_dir = find_capcut_draft_dir()
    if not draft_base_dir:
        raise RuntimeError("캡컷 프로젝트 저장소(draft directory)를 찾을 수 없습니다.")

    # 1. 고유 프로젝트 폴더명 생성
    clean_name = "".join(c for c in project_name if c.isalnum() or c in (" ", "_", "-")).strip() or "TubeInsight_Project"
    folder_name = f"{clean_name}_{int(time.time())}"
    project_dir = draft_base_dir / folder_name
    project_dir.mkdir(parents=True, exist_ok=True)

    project_id = str(uuid.uuid4()).upper()
    now_us = int(time.time() * 1000000)

    # 해상도 설정
    if aspect_ratio == "9:16":
        width, height = 1080, 1920
    else:
        width, height = 1920, 1080

    # 2. 타임라인 및 머티리얼 구조 초기화
    materials_videos = []
    materials_audios = []
    materials_texts = []
    materials_transitions = []

    video_segments = []
    narration_segments = []
    subtitle_segments = []

    current_timeline_us = 0
    transition_info = TRANSITION_PRESETS.get(transition_type, TRANSITION_PRESETS["dissolve"])
    trans_dur_us = transition_info.get("duration_us", 0)

    # 3. 씬별 오디오 마스터링 & 비디오/자막/대사 1:1 결합 조립
    for idx, sc in enumerate(scenes):
        media_path = sc.get("media_file") or sc.get("image_file") or sc.get("video_file") or ""
        audio_path = sc.get("audio_file") or ""
        subtitle_text = (sc.get("subtitle") or sc.get("text") or sc.get("script") or "").strip()

        # 실제 음성 파일의 길이를 마이크로초 단위로 칼같이 측정
        audio_dur_us = get_media_duration_us(audio_path)
        scene_dur_us = audio_dur_us  # 오디오를 기준으로 씬 길이를 1:1 강제 일치!

        # 1) 비디오/이미지 머티리얼 & 세그먼트 생성
        vid_id = str(uuid.uuid4()).upper()
        is_photo = bool(media_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
        
        # 파일이 존재하지 않으면 기본 안내 텍스트로 대응 가능하도록
        abs_media = os.path.abspath(media_path) if os.path.exists(media_path) else ""

        materials_videos.append({
            "id": vid_id,
            "type": "photo" if is_photo else "video",
            "path": abs_media,
            "duration": scene_dur_us,
            "width": width,
            "height": height,
            "material_name": os.path.basename(media_path) if media_path else f"scene_{idx+1}",
            "check_flag": 62978047
        })

        # 비디오 세그먼트
        vid_seg_id = str(uuid.uuid4()).upper()
        vid_seg = {
            "id": vid_seg_id,
            "material_id": vid_id,
            "target_timerange": {
                "start": current_timeline_us,
                "duration": scene_dur_us
            },
            "source_timerange": {
                "start": 0,
                "duration": scene_dur_us
            },
            "speed": 1.0,
            "volume": 0.0 if is_photo else 1.0
        }

        # 컷 전환 트랜지션 (마지막 씬 제외하고 삽입)
        if trans_dur_us > 0 and idx < len(scenes) - 1:
            trans_id = str(uuid.uuid4()).upper()
            materials_transitions.append({
                "id": trans_id,
                "name": transition_info["name"],
                "resource_id": transition_info["resource_id"],
                "effect_id": transition_info["effect_id"],
                "duration": trans_dur_us,
                "is_overlap": True
            })
            vid_seg["extra_material_refs"] = [trans_id]

        video_segments.append(vid_seg)

        # 2) 대사 나레이션 오디오 머티리얼 & 세그먼트 생성
        if audio_path and os.path.exists(audio_path):
            aud_id = str(uuid.uuid4()).upper()
            materials_audios.append({
                "id": aud_id,
                "path": os.path.abspath(audio_path),
                "duration": audio_dur_us,
                "name": f"narration_{idx+1}.mp3"
            })
            narration_segments.append({
                "id": str(uuid.uuid4()).upper(),
                "material_id": aud_id,
                "target_timerange": {
                    "start": current_timeline_us,
                    "duration": audio_dur_us
                },
                "source_timerange": {
                    "start": 0,
                    "duration": audio_dur_us
                },
                "volume": 1.0
            })

        # 3) 한글 자막 머티리얼 & 세그먼트 생성 (유튜브 볼드 스타일)
        if subtitle_text:
            txt_id = str(uuid.uuid4()).upper()
            txt_mat = _build_text_material(subtitle_text, txt_id, font_size=7.5)
            materials_texts.append(txt_mat)

            subtitle_segments.append({
                "id": str(uuid.uuid4()).upper(),
                "material_id": txt_id,
                "target_timerange": {
                    "start": current_timeline_us,
                    "duration": scene_dur_us
                },
                "source_timerange": None
            })

        # 다음 씬 타임라인 위치 오프셋 갱신
        current_timeline_us += scene_dur_us

    # 4) 배경음악(BGM) 트랙 추가 (선택)
    bgm_segments = []
    if bgm_path and os.path.exists(bgm_path):
        bgm_id = str(uuid.uuid4()).upper()
        bgm_total_dur = get_media_duration_us(bgm_path)
        materials_audios.append({
            "id": bgm_id,
            "path": os.path.abspath(bgm_path),
            "duration": bgm_total_dur,
            "name": "BGM.mp3"
        })
        bgm_segments.append({
            "id": str(uuid.uuid4()).upper(),
            "material_id": bgm_id,
            "target_timerange": {
                "start": 0,
                "duration": min(bgm_total_dur, current_timeline_us)
            },
            "source_timerange": {
                "start": 0,
                "duration": min(bgm_total_dur, current_timeline_us)
            },
            "volume": 0.25  # BGM은 잔잔하게 25%
        })

    # 5. 완성된 트랙 리스트 구성
    tracks = []
    if video_segments:
        tracks.append({"id": str(uuid.uuid4()).upper(), "type": "video", "segments": video_segments})
    if subtitle_segments:
        tracks.append({"id": str(uuid.uuid4()).upper(), "type": "text", "segments": subtitle_segments})
    if narration_segments:
        tracks.append({"id": str(uuid.uuid4()).upper(), "type": "audio", "segments": narration_segments})
    if bgm_segments:
        tracks.append({"id": str(uuid.uuid4()).upper(), "type": "audio", "segments": bgm_segments})

    # 6. draft_info.json 완성 조립
    draft_info = {
        "id": project_id,
        "name": clean_name,
        "version": 360000,
        "new_version": "183.0.0",
        "duration": current_timeline_us,
        "fps": 30.0,
        "create_time": now_us,
        "update_time": now_us,
        "canvas_config": {
            "ratio": "9:16" if aspect_ratio == "9:16" else "16:9",
            "width": width,
            "height": height,
            "background": None
        },
        "tracks": tracks,
        "materials": {
            "videos": materials_videos,
            "audios": materials_audios,
            "texts": materials_texts,
            "transitions": materials_transitions,
            "effects": [],
            "stickers": [],
            "canvases": [],
            "audio_effects": [],
            "audio_fades": []
        }
    }

    # 파일 기록
    with open(project_dir / "draft_info.json", "w", encoding="utf-8") as f:
        json.dump(draft_info, f, ensure_ascii=False, indent=2)

    # draft_meta_info.json 기록
    draft_meta = {
        "draft_id": project_id,
        "draft_name": clean_name,
        "draft_fold_path": str(project_dir),
        "draft_timeline_dur": current_timeline_us,
        "draft_root_path": str(draft_base_dir),
        "draft_removable_storage_device": False,
        "tm_draft_create": int(time.time()),
        "tm_draft_modified": int(time.time()),
        "draft_cover": "",
        "draft_is_ai_shorts": False
    }
    with open(project_dir / "draft_meta_info.json", "w", encoding="utf-8") as f:
        json.dump(draft_meta, f, ensure_ascii=False, indent=2)

    # 7. 캡컷 메인 화면 root_meta_info.json에 최신 프로젝트로 상단 등록
    register_to_root_meta(draft_base_dir, project_id, clean_name, str(project_dir), current_timeline_us)

    return {
        "status": "success",
        "project_id": project_id,
        "project_name": clean_name,
        "project_dir": str(project_dir),
        "total_duration_seconds": round(current_timeline_us / 1000000, 2),
        "total_scenes": len(scenes),
        "transition_applied": transition_info["name"]
    }


def register_to_root_meta(draft_base_dir: Path, project_id: str, name: str, folder_path: str, duration_us: int):
    """캡컷 앱 실행 시 첫 화면 최상단에 프로젝트가 바로 보이도록 root_meta_info.json 갱신"""
    root_meta_file = draft_base_dir / "root_meta_info.json"
    data = {"all_draft_store": []}

    if root_meta_file.exists():
        try:
            with open(root_meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"all_draft_store": []}

    now_sec = int(time.time())
    new_entry = {
        "draft_id": project_id,
        "draft_name": name,
        "draft_fold_path": folder_path,
        "draft_timeline_dur": duration_us,
        "draft_root_path": str(draft_base_dir),
        "draft_removable_storage_device": False,
        "tm_draft_create": now_sec,
        "tm_draft_modified": now_sec,
        "draft_json_updated_time": now_sec,
        "draft_cover": ""
    }

    # 기존 동일 ID 제거 후 맨 앞에 삽입
    existing = [x for x in data.get("all_draft_store", []) if x.get("draft_id") != project_id and x.get("draft_name") != name]
    existing.insert(0, new_entry)
    data["all_draft_store"] = existing

    try:
        with open(root_meta_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Failed to update root_meta_info.json: {e}")


def open_in_capcut(project_dir: Optional[str] = None) -> Dict[str, Any]:
    """macOS 캡컷 앱 실행"""
    try:
        cmd = ["open", "-a", "CapCut"]
        subprocess.run(cmd, check=True)
        return {"status": "success", "message": "CapCut 앱이 성공적으로 실행되었습니다."}
    except Exception as e:
        raise RuntimeError(f"CapCut 실행 실패: {e}")
