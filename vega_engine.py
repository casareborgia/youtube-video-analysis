"""
사운드 엔지니어 베가 (Vega) — 에이전트 루나 완곡 음원 마스터링 엔진
======================================================================

루나가 만든 음원(Lyria 3 / 로컬 신스)을 유튜브 업로드 규격에 맞게 다듬는 마스터링 에이전트.
레오(트렌드) → 루나(작곡) → **베가(마스터링)** → 렌더링 → 업로드 순서로 동작한다.

파이프라인 (mixmaster-ai 의 analyze → decide → process → write 구조를 참고해 재구현):

    load_audio()  →  analyze()  →  decide()  →  process()  →  write_audio()
       ffmpeg/sf      측정 13종     LLM/프리셋      DSP 체인     24bit WAV (원본 샘플레이트)

설계 원칙
- 외부 LLM 결정이 실패하면 장르별 프리셋으로 자동 대체한다 (점진적 저하).
- 모든 DSP 파라미터는 Pydantic 스키마의 ge/le 범위를 통과해야만 적용한다.
- 원본 음원은 `audio_raw.*` 로 항상 보존하고, 결과는 `audio_mastered.wav` 로 쓴다.
- 처리 체인은 EQ → 컴프레서 → 톤 EQ → 새츄레이터 → M/S 이미저 → **음량 매칭 → 리미터** 순서다.
  (리미터 뒤에서 음량을 올리면 피크가 다시 넘치므로 음량 매칭을 리미터 앞에 둔다)
- 오디오 배열은 항상 (channels, samples) 형태, 저장은 float32, 내부 연산은 float64.
- pedalboard / pyloudnorm / soundfile / scipy 가 없으면 마스터링만 건너뛰고 나머지 파이프라인은 그대로 동작한다.
"""

import os
import json
import math
import time
import shutil
import subprocess
from typing import Literal, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field, ValidationError

import llm_client

# ── 선택 의존성 로드 (없으면 베가만 비활성화) ────────────────────────────────
_IMPORT_ERROR = ""
try:
    import soundfile as sf
    import pyloudnorm
    from scipy.signal import butter, sosfiltfilt, resample_poly, welch
    from pedalboard import (
        Pedalboard, Compressor, Gain,
        PeakFilter, LowShelfFilter, HighShelfFilter, HighpassFilter, LowpassFilter,
    )
    VEGA_AVAILABLE = True
except Exception as _e:  # pragma: no cover - 환경 의존
    VEGA_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

AGENT_NAME = "베가 (Vega)"
ENGINE_VERSION = "1.1.0"
MASTER_BIT_DEPTH = 24               # 샘플레이트는 원본 그대로 유지한다 (Lyria 출력은 44.1kHz, 변환하면 음질만 손해)
SILENCE_FLOOR = 1e-6                # 이 이하 피크면 무음으로 간주하고 처리 생략
MASTERED_FILENAME = "audio_mastered.wav"
RAW_FILENAME_PREFIX = "audio_raw"


def is_available() -> bool:
    return VEGA_AVAILABLE


def availability_report() -> dict:
    return {
        "available": VEGA_AVAILABLE,
        "agent": AGENT_NAME,
        "engine_version": ENGINE_VERSION,
        "missing_reason": _IMPORT_ERROR if not VEGA_AVAILABLE else "",
        "install_hint": "" if VEGA_AVAILABLE else "pip install pedalboard pyloudnorm soundfile scipy",
    }


# ══════════════════════════════════════════════════════════════════════════
# 1. 스키마 — 모든 파라미터는 범위를 가진다 (LLM 이 엉뚱한 값을 내도 소리가 망가지지 않게)
# ══════════════════════════════════════════════════════════════════════════

class EQBand(BaseModel):
    frequency: float = Field(..., ge=20.0, le=20000.0)
    gain_db: float = Field(0.0, ge=-12.0, le=6.0)
    q: float = Field(0.7, ge=0.1, le=10.0)
    filter_type: Literal["low_shelf", "high_shelf", "peak", "high_pass", "low_pass"]


class EQSettings(BaseModel):
    bands: list[EQBand] = Field(default_factory=list, max_length=8)
    label: str = ""


class CompressorSettings(BaseModel):
    threshold_db: float = Field(..., ge=-60.0, le=0.0)
    ratio: float = Field(..., ge=1.0, le=10.0)
    attack_ms: float = Field(..., ge=0.1, le=100.0)
    release_ms: float = Field(..., ge=10.0, le=1000.0)
    makeup_gain_db: float = Field(0.0, ge=0.0, le=12.0)


class SaturatorSettings(BaseModel):
    drive_db: float = Field(0.0, ge=0.0, le=12.0)
    mix: float = Field(0.0, ge=0.0, le=1.0)
    mode: Literal["tape", "tube", "clip"] = "tape"


class StereoImageSettings(BaseModel):
    width: float = Field(1.0, ge=0.0, le=2.0)
    mono_low_hz: float = Field(120.0, ge=20.0, le=300.0)


class LimiterSettings(BaseModel):
    ceiling_dbtp: float = Field(-1.0, ge=-3.0, le=-0.1)
    release_ms: float = Field(150.0, ge=50.0, le=500.0)


class MasteringDecisions(BaseModel):
    corrective_eq: EQSettings
    compressor: CompressorSettings
    tonal_eq: EQSettings
    saturator: SaturatorSettings
    stereo_image: StereoImageSettings
    limiter: LimiterSettings
    target_lufs: float = Field(-14.0, ge=-24.0, le=-8.0)
    reasoning: str = ""


# ══════════════════════════════════════════════════════════════════════════
# 2. 장르별 마스터링 프리셋 — LLM 결정의 출발점이자 실패 시 폴백
#    유튜브는 -14 LUFS 기준으로 음량을 정규화하므로 그 이상 키워도 이득이 없다.
#    수면·명상은 더 조용하게, 비트 중심 장르는 조금 더 단단하게 잡는다.
# ══════════════════════════════════════════════════════════════════════════

def _eq(label, *bands):
    return {"label": label, "bands": [
        {"frequency": f, "gain_db": g, "q": q, "filter_type": t} for (f, g, q, t) in bands
    ]}


def _comp(th, ratio, att, rel, makeup=0.0):
    return {"threshold_db": th, "ratio": ratio, "attack_ms": att, "release_ms": rel, "makeup_gain_db": makeup}


def _sat(drive, mix, mode="tape"):
    return {"drive_db": drive, "mix": mix, "mode": mode}


def _img(width, mono_low):
    return {"width": width, "mono_low_hz": mono_low}


def _lim(ceiling=-1.0, release=150.0):
    return {"ceiling_dbtp": ceiling, "release_ms": release}


GENRE_MASTER_PRESETS: dict[str, dict] = {
    "lofi": {
        "corrective_eq": _eq("서브 럼블 제거", (30, 0, 0.7, "high_pass")),
        "compressor": _comp(-18, 2.0, 30, 250),
        "tonal_eq": _eq("따뜻한 로파이 톤", (120, 1.5, 0.7, "low_shelf"), (9000, -2.0, 0.7, "high_shelf")),
        "saturator": _sat(3.0, 0.35, "tape"),
        "stereo_image": _img(1.05, 120),
        "limiter": _lim(),
        "target_lufs": -14.0,
        "reasoning": "로파이 기본 프리셋: 테이프 새츄레이션으로 질감을 더하고 고역을 살짝 눌러 아날로그 따뜻함을 유지한다.",
    },
    "ambient": {
        "corrective_eq": _eq("초저역 정리", (25, 0, 0.7, "high_pass")),
        "compressor": _comp(-20, 1.5, 50, 400),
        "tonal_eq": _eq("공기감", (10000, 1.0, 0.7, "high_shelf")),
        "saturator": _sat(1.0, 0.15, "tube"),
        "stereo_image": _img(1.2, 100),
        "limiter": _lim(),
        "target_lufs": -16.0,
        "reasoning": "앰비언트 기본 프리셋: 다이내믹을 최대한 보존하고 넓은 공간감과 공기감을 살린다.",
    },
    "synthwave": {
        "corrective_eq": _eq("머드 정리", (30, 0, 0.7, "high_pass"), (250, -2.0, 1.2, "peak")),
        "compressor": _comp(-16, 3.0, 10, 150),
        "tonal_eq": _eq("레트로 펀치", (80, 1.5, 0.7, "low_shelf"), (8000, 1.5, 0.7, "high_shelf")),
        "saturator": _sat(3.0, 0.3, "tape"),
        "stereo_image": _img(1.25, 120),
        "limiter": _lim(),
        "target_lufs": -12.0,
        "reasoning": "신스웨이브 기본 프리셋: 드라이브 비트에 맞춰 단단하게 압축하고 저역·고역을 함께 들어 올린다.",
    },
    "sleep": {
        "corrective_eq": _eq("초저역 정리", (25, 0, 0.7, "high_pass")),
        "compressor": _comp(-24, 1.3, 60, 500),
        "tonal_eq": _eq("자극 억제", (8000, -3.0, 0.7, "high_shelf")),
        "saturator": _sat(0.0, 0.0, "tape"),
        "stereo_image": _img(1.1, 100),
        "limiter": _lim(-1.5, 300),
        "target_lufs": -18.0,
        "reasoning": "수면·명상 기본 프리셋: 음량을 낮게 유지하고 고역 자극을 줄여 장시간 청취 피로를 막는다.",
    },
    "jazz": {
        "corrective_eq": _eq("럼블 제거", (30, 0, 0.7, "high_pass")),
        "compressor": _comp(-18, 1.8, 25, 300),
        "tonal_eq": _eq("프레즌스·공기감", (3000, 1.0, 1.0, "peak"), (10000, 1.0, 0.7, "high_shelf")),
        "saturator": _sat(1.5, 0.2, "tube"),
        "stereo_image": _img(1.1, 100),
        "limiter": _lim(),
        "target_lufs": -14.0,
        "reasoning": "재즈 기본 프리셋: 어쿠스틱 다이내믹을 살리면서 피아노·베이스의 존재감을 가볍게 보강한다.",
    },
    "piano": {
        "corrective_eq": _eq("초저역 정리", (25, 0, 0.7, "high_pass")),
        "compressor": _comp(-20, 1.6, 30, 350),
        "tonal_eq": _eq("공기감", (10000, 1.0, 0.7, "high_shelf")),
        "saturator": _sat(1.0, 0.1, "tube"),
        "stereo_image": _img(1.1, 100),
        "limiter": _lim(),
        "target_lufs": -16.0,
        "reasoning": "피아노 솔로 기본 프리셋: 여린 터치의 다이내믹을 보존하고 과한 압축을 피한다.",
    },
    "citypop": {
        "corrective_eq": _eq("머드 정리", (30, 0, 0.7, "high_pass"), (300, -1.5, 1.2, "peak")),
        "compressor": _comp(-16, 2.5, 15, 200),
        "tonal_eq": _eq("보컬 프레즌스·광택", (90, 1.0, 0.7, "low_shelf"), (3000, 1.5, 1.0, "peak"), (9000, 1.5, 0.7, "high_shelf")),
        "saturator": _sat(2.5, 0.3, "tape"),
        "stereo_image": _img(1.2, 120),
        "limiter": _lim(),
        "target_lufs": -12.0,
        "reasoning": "시티팝 기본 프리셋: 보컬이 앞으로 나오도록 3kHz 를 보강하고 80년대 광택을 위해 고역을 연다.",
    },
    "acoustic": {
        "corrective_eq": _eq("박시함 정리", (35, 0, 0.7, "high_pass"), (400, -1.5, 1.2, "peak")),
        "compressor": _comp(-18, 1.8, 25, 300),
        "tonal_eq": _eq("공기감", (10000, 1.0, 0.7, "high_shelf")),
        "saturator": _sat(1.5, 0.2, "tube"),
        "stereo_image": _img(1.1, 110),
        "limiter": _lim(),
        "target_lufs": -14.0,
        "reasoning": "어쿠스틱 기본 프리셋: 기타 바디의 박시한 중저역을 정리하고 현의 공기감을 살린다.",
    },
    "rnb-chill": {
        "corrective_eq": _eq("초저역 정리", (25, 0, 0.7, "high_pass")),
        "compressor": _comp(-16, 2.5, 20, 200),
        "tonal_eq": _eq("서브·보컬·광택", (60, 2.0, 0.7, "low_shelf"), (3000, 1.5, 1.0, "peak"), (9000, 1.0, 0.7, "high_shelf")),
        "saturator": _sat(2.0, 0.25, "tube"),
        "stereo_image": _img(1.15, 120),
        "limiter": _lim(),
        "target_lufs": -12.0,
        "reasoning": "R&B 칠 기본 프리셋: 808 서브를 단단히 받치고 보컬 대역을 앞으로 당긴다.",
    },
    "dark-ambient": {
        "corrective_eq": _eq("DC 제거", (20, 0, 0.7, "high_pass")),
        "compressor": _comp(-22, 1.5, 50, 450),
        "tonal_eq": _eq("어두운 톤", (8000, -1.0, 0.7, "high_shelf")),
        "saturator": _sat(1.0, 0.15, "tape"),
        "stereo_image": _img(1.3, 90),
        "limiter": _lim(),
        "target_lufs": -16.0,
        "reasoning": "다크 앰비언트 기본 프리셋: 초저역 펄스를 보존하고 넓은 스테레오로 심해의 공간감을 만든다.",
    },
    "default": {
        "corrective_eq": _eq("럼블 제거", (30, 0, 0.7, "high_pass")),
        "compressor": _comp(-18, 2.0, 25, 250),
        "tonal_eq": _eq("중립", (10000, 0.5, 0.7, "high_shelf")),
        "saturator": _sat(1.5, 0.2, "tape"),
        "stereo_image": _img(1.1, 120),
        "limiter": _lim(),
        "target_lufs": -14.0,
        "reasoning": "범용 스트리밍 프리셋: 유튜브 정규화 기준(-14 LUFS)에 맞춘 중립적 마스터.",
    },
}


def preset_for_genre(genre: str) -> MasteringDecisions:
    raw = GENRE_MASTER_PRESETS.get((genre or "").lower().strip(), GENRE_MASTER_PRESETS["default"])
    return MasteringDecisions.model_validate(raw)


def describe_presets() -> list[dict]:
    return [
        {"genre": g, "target_lufs": p["target_lufs"], "ceiling_dbtp": p["limiter"]["ceiling_dbtp"], "summary": p["reasoning"]}
        for g, p in GENRE_MASTER_PRESETS.items()
    ]


# ══════════════════════════════════════════════════════════════════════════
# 3. 오디오 입출력
# ══════════════════════════════════════════════════════════════════════════

def _ffmpeg_decode(src: str, dst_wav: str):
    """soundfile 이 못 읽는 포맷을 float WAV 로 디코딩한다. 샘플레이트는 원본 그대로 둔다 (-ar 미지정)."""
    cmd = ["ffmpeg", "-y", "-i", src, "-vn", "-ac", "2", "-c:a", "pcm_f32le", dst_wav]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not os.path.exists(dst_wav):
        raise RuntimeError(f"ffmpeg 디코딩 실패: {res.stderr.decode(errors='ignore')[-300:]}")


def load_audio(path: str) -> Tuple[np.ndarray, int]:
    """음원을 (channels, samples) float32 로 읽는다. soundfile 이 못 읽는 포맷은 ffmpeg 로 디코딩한다."""
    if not VEGA_AVAILABLE:
        raise RuntimeError("베가 의존성이 설치되지 않았습니다: " + _IMPORT_ERROR)
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception:
        tmp = path + ".vega_decode.wav"
        _ffmpeg_decode(path, tmp)
        try:
            data, sr = sf.read(tmp, dtype="float32", always_2d=True)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    audio = np.ascontiguousarray(data.T.astype(np.float32))  # (ch, n)
    if audio.shape[0] == 1:
        audio = np.stack([audio[0], audio[0]])
    elif audio.shape[0] > 2:
        audio = audio[:2]
    return audio, int(sr)


def write_audio(audio: np.ndarray, sample_rate: int, path: str, bit_depth: int = MASTER_BIT_DEPTH) -> str:
    subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}.get(bit_depth, "PCM_24")
    out = np.clip(audio, -1.0, 1.0).astype(np.float32)
    sf.write(path, out.T, sample_rate, subtype=subtype)
    return path


# ══════════════════════════════════════════════════════════════════════════
# 4. 분석 — 결정에 필요한 측정값 13종
# ══════════════════════════════════════════════════════════════════════════

def _db(x: float) -> float:
    return float(20.0 * math.log10(max(float(x), 1e-12)))


def _band_rms_db(mono: np.ndarray, sr: int, low: Optional[float], high: Optional[float]) -> float:
    nyq = sr / 2.0
    sig = mono
    if high is not None:
        sos = butter(4, min(high, nyq * 0.99), btype="low", fs=sr, output="sos")
        sig = sosfiltfilt(sos, sig)
    if low is not None:
        sos = butter(4, max(low, 1.0), btype="high", fs=sr, output="sos")
        sig = sosfiltfilt(sos, sig)
    return _db(np.sqrt(np.mean(sig ** 2) + 1e-24))


def _integrated_lufs(audio: np.ndarray, sr: int) -> float:
    try:
        meter = pyloudnorm.Meter(sr)
        v = float(meter.integrated_loudness(audio.T.astype(np.float64)))
        return v if np.isfinite(v) else -70.0
    except Exception:
        return -70.0


def _true_peak_dbtp(audio: np.ndarray) -> float:
    """채널별 4배 오버샘플링 후 최대 절대값. 채널을 합쳐 재면 실제보다 낮게 나오므로 반드시 채널별로 잰다."""
    peak = 0.0
    for ch in range(audio.shape[0]):
        up = resample_poly(audio[ch].astype(np.float64), 4, 1)
        peak = max(peak, float(np.max(np.abs(up))) if up.size else 0.0)
    return _db(peak)


def analyze(audio: np.ndarray, sr: int) -> dict:
    """(channels, samples) float 배열을 받아 마스터링 결정에 쓰는 측정값 사전을 돌려준다."""
    x = audio.astype(np.float64)
    mono = np.mean(x, axis=0)
    n = mono.size
    peak = float(np.max(np.abs(x))) if n else 0.0

    result = {
        "duration_seconds": round(n / sr, 2) if sr else 0.0,
        "sample_rate": sr,
        "channels": int(x.shape[0]),
    }
    if peak < SILENCE_FLOOR or n < 64:
        result.update({
            "is_silent": True, "rms_db": -120.0, "peak_db": -120.0, "crest_factor_db": 0.0,
            "dynamic_range_db": 0.0, "integrated_lufs": -70.0, "true_peak_dbtp": -120.0,
            "rms_sub_db": -120.0, "rms_low_db": -120.0, "rms_mid_db": -120.0, "rms_high_db": -120.0,
            "spectral_centroid_hz": 0.0, "spectral_flatness": 0.0, "stereo_width": 0.0, "low_end_correlation": 1.0,
        })
        return result

    rms = float(np.sqrt(np.mean(mono ** 2)))
    rms_db = _db(rms)
    peak_db = _db(peak)

    # 프레임 RMS 90/10 백분위 차이 = 체감 다이내믹 레인지
    frame, hop = 2048, 512
    if n >= frame:
        idx = np.arange(0, n - frame + 1, hop)
        frames = np.lib.stride_tricks.as_strided(
            mono, shape=(idx.size, frame), strides=(mono.strides[0] * hop, mono.strides[0]))
        frame_db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-12)
        dyn_range = float(np.percentile(frame_db, 90) - np.percentile(frame_db, 10))
    else:
        dyn_range = 0.0

    # 스펙트럼 특성 (Welch PSD 기반 — 전체 FFT 보다 가볍다)
    nperseg = min(4096, n)
    freqs, psd = welch(mono, fs=sr, nperseg=nperseg)
    psd = np.maximum(psd, 1e-20)
    centroid = float(np.sum(freqs * psd) / np.sum(psd))
    flatness = float(np.exp(np.mean(np.log(psd))) / np.mean(psd))

    # 스테레오 특성
    if x.shape[0] >= 2:
        mid = (x[0] + x[1]) * 0.5
        side = (x[0] - x[1]) * 0.5
        mid_rms = float(np.sqrt(np.mean(mid ** 2)) + 1e-12)
        side_rms = float(np.sqrt(np.mean(side ** 2)))
        width = side_rms / mid_rms
        sos = butter(4, min(120.0, sr * 0.49), btype="low", fs=sr, output="sos")
        l_lo, r_lo = sosfiltfilt(sos, x[0]), sosfiltfilt(sos, x[1])
        denom = float(np.sqrt(np.sum(l_lo ** 2) * np.sum(r_lo ** 2)))
        low_corr = float(np.sum(l_lo * r_lo) / denom) if denom > 1e-12 else 1.0
    else:
        width, low_corr = 0.0, 1.0

    result.update({
        "is_silent": False,
        "rms_db": round(rms_db, 2),
        "peak_db": round(peak_db, 2),
        "crest_factor_db": round(peak_db - rms_db, 2),
        "dynamic_range_db": round(dyn_range, 2),
        "integrated_lufs": round(_integrated_lufs(x, sr), 2),
        "true_peak_dbtp": round(_true_peak_dbtp(x), 2),
        "rms_sub_db": round(_band_rms_db(mono, sr, None, 60), 2),
        "rms_low_db": round(_band_rms_db(mono, sr, 60, 250), 2),
        "rms_mid_db": round(_band_rms_db(mono, sr, 250, 4000), 2),
        "rms_high_db": round(_band_rms_db(mono, sr, 4000, None), 2),
        "spectral_centroid_hz": round(centroid, 1),
        "spectral_flatness": round(flatness, 4),
        "stereo_width": round(width, 3),
        "low_end_correlation": round(low_corr, 3),
    })
    return result


# ══════════════════════════════════════════════════════════════════════════
# 5. 결정 — LLM(Gemini/로컬)이 프리셋을 출발점으로 수치를 조정, 실패 시 프리셋 그대로
# ══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
    "당신은 20년 경력의 마스터링 엔지니어 '베가'입니다. "
    "유튜브 음악 채널에 업로드할 완곡 음원의 마스터링 파라미터를 결정합니다.\n"
    "처리 체인 순서: corrective_eq → compressor → tonal_eq → saturator → stereo_image → 음량 매칭(target_lufs) → limiter.\n"
    "규칙:\n"
    "- 반드시 주어진 JSON 스키마 형식으로만 응답하고, 모든 값은 스키마의 최소/최대 범위 안에 둔다.\n"
    "- 제공된 장르 프리셋을 출발점으로 삼고, 측정값이 뒷받침하는 항목만 조정한다. 근거 없는 큰 변화는 금지.\n"
    "- corrective_eq 는 문제 해결(럼블, 머드, 하시), tonal_eq 는 캐릭터(따뜻함, 공기감, 프레즌스).\n"
    "- 유튜브는 -14 LUFS 로 정규화하므로 target_lufs 는 장르 프리셋 ±2 LU 안에서 정한다. 수면·명상은 -16 ~ -19.\n"
    "- crest_factor_db < 8 이면 이미 압축된 소리이므로 ratio 는 2.0 이하, threshold 는 높게.\n"
    "- stereo_width > 0.6 이면 width 를 1.1 이상으로 더 넓히지 않는다.\n"
    "- low_end_correlation < 0.7 이면 mono_low_hz 를 120 이상으로 유지한다.\n"
    "- true_peak_dbtp 가 이미 -1 을 넘었다면 limiter.ceiling_dbtp 는 -1.0 이하로.\n"
    "- reasoning 에는 왜 그렇게 정했는지 한국어 2~3문장으로 쓴다."
)


def _llm_messages(analysis: dict, genre: str, mood: str, prompt: str,
                  preset: MasteringDecisions, genre_spec: Optional[dict]) -> list:
    spec_txt = ""
    if genre_spec:
        spec_txt = f"\n장르 사운드 스펙: {genre_spec.get('sound_texture', '')} / {genre_spec.get('instruments', '')}"
    user = (
        f"장르: {genre} / 무드: {mood}{spec_txt}\n"
        f"제작자 요청: {prompt or '(없음 — 장르 기본 방향 유지)'}\n\n"
        f"측정값:\n{json.dumps(analysis, ensure_ascii=False, indent=1)}\n\n"
        f"장르 프리셋(출발점):\n{preset.model_dump_json(indent=1)}\n\n"
        f"JSON 스키마:\n{json.dumps(MasteringDecisions.model_json_schema(), ensure_ascii=False)}\n\n"
        "위 스키마를 만족하는 JSON 객체 하나만 출력하세요."
    )
    return [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _llm_call_meta() -> dict:
    """llm_client 가 방금 실제로 쓴 백엔드·모델. (Gemini 실패 → 로컬 폴백도 반영된다)"""
    try:
        info = llm_client.last_call_info() or {}
    except Exception:
        info = {}
    return {"backend": info.get("backend"), "model": info.get("model")}


def decide_with_meta(analysis: dict, genre: str = "default", mood: str = "", prompt: str = "",
                     use_llm: bool = True, genre_spec: Optional[dict] = None
                     ) -> Tuple[MasteringDecisions, str, str, dict]:
    """
    decide() 와 같지만 네 번째 값으로 LLM 호출 메타를 함께 돌려준다.
      meta = {"backend": "gemini"|"lmstudio"|"ollama"|None, "model": str|None, "attempted": bool}
      LLM 응답이 범위 검증에서 떨어져 프리셋을 썼어도, 호출한 모델은 meta 에 남는다.
    """
    preset = preset_for_genre(genre)
    no_call = {"backend": None, "model": None, "attempted": False}
    if analysis.get("is_silent"):
        return preset, "preset", "무음 입력 — 프리셋 유지", no_call
    if not use_llm:
        return preset, "preset", "프리셋 전용 모드", no_call

    meta = {"backend": None, "model": None, "attempted": True}
    try:
        parsed, raw = llm_client.call_llm_json(
            _llm_messages(analysis, genre, mood, prompt, preset, genre_spec),
            max_tokens=2048, temperature=0.2,
        )
        meta.update(_llm_call_meta())
        if not isinstance(parsed, dict):
            raise ValueError("LLM 응답에서 JSON 객체를 찾지 못함")
        decisions = MasteringDecisions.model_validate(parsed)
        if not decisions.reasoning:
            decisions.reasoning = "LLM 결정 (사유 미제공)"
        return decisions, "llm", "", meta
    except ValidationError as e:
        return preset, "preset", f"LLM 값이 허용 범위를 벗어나 프리셋으로 대체: {str(e)[:160]}", meta
    except Exception as e:
        return preset, "preset", f"LLM 호출 실패로 프리셋으로 대체: {str(e)[:160]}", meta


def decide(analysis: dict, genre: str = "default", mood: str = "", prompt: str = "",
           use_llm: bool = True, genre_spec: Optional[dict] = None) -> Tuple[MasteringDecisions, str, str]:
    """
    반환: (decisions, source, note)
      source = "llm" | "preset"
      note   = 폴백 사유 등 사람이 읽을 메모
    모델명까지 필요하면 decide_with_meta() 를 쓴다.
    """
    decisions, source, note, _meta = decide_with_meta(analysis, genre, mood, prompt, use_llm, genre_spec)
    return decisions, source, note


# ══════════════════════════════════════════════════════════════════════════
# 6. 처리 — DSP 체인
# ══════════════════════════════════════════════════════════════════════════

def _run_board(audio64: np.ndarray, sr: int, plugins: list) -> np.ndarray:
    if not plugins:
        return audio64
    board = Pedalboard(plugins)
    x = np.clip(audio64, -1.0, 1.0).astype(np.float32)
    return board(x, sr).astype(np.float64)


def _eq_plugins(eq: EQSettings, sr: int) -> list:
    plugins = []
    for b in eq.bands:
        f = float(min(b.frequency, sr * 0.45))
        if b.filter_type == "peak":
            plugins.append(PeakFilter(cutoff_frequency_hz=f, gain_db=b.gain_db, q=b.q))
        elif b.filter_type == "low_shelf":
            plugins.append(LowShelfFilter(cutoff_frequency_hz=f, gain_db=b.gain_db, q=b.q))
        elif b.filter_type == "high_shelf":
            plugins.append(HighShelfFilter(cutoff_frequency_hz=f, gain_db=b.gain_db, q=b.q))
        elif b.filter_type == "high_pass":
            plugins.append(HighpassFilter(cutoff_frequency_hz=f))
        elif b.filter_type == "low_pass":
            plugins.append(LowpassFilter(cutoff_frequency_hz=f))
    return plugins


def _apply_saturator(x: np.ndarray, sat: SaturatorSettings) -> np.ndarray:
    if sat.mix <= 0.0 or sat.drive_db <= 0.0:
        return x
    drive = 10 ** (sat.drive_db / 20.0)
    norm = math.tanh(drive)  # 드라이브로 커진 레벨을 되돌려 음량 변화 없이 질감만 남긴다
    if sat.mode == "tape":
        wet = np.tanh(x * drive) / norm
    elif sat.mode == "tube":
        wet = np.where(x >= 0, np.tanh(x * drive), np.tanh(x * drive * 0.7) / 0.7) / norm
    else:
        wet = np.clip(x * drive, -1.0, 1.0)
    return x * (1.0 - sat.mix) + wet * sat.mix


def _apply_ms_image(x: np.ndarray, sr: int, img: StereoImageSettings) -> np.ndarray:
    if x.shape[0] < 2:
        return x
    mid = (x[0] + x[1]) * 0.5
    side = (x[0] - x[1]) * 0.5
    sos = butter(4, min(img.mono_low_hz, sr * 0.45), btype="low", fs=sr, output="sos")
    side = side - sosfiltfilt(sos, side)   # 저역 사이드 성분 제거 → 저음은 모노로
    side = side * img.width
    return np.stack([mid + side, mid - side])


def process(audio: np.ndarray, sr: int, d: MasteringDecisions) -> Tuple[np.ndarray, dict]:
    """마스터링 체인을 적용하고 (결과 float32, 처리 로그) 를 돌려준다."""
    x = audio.astype(np.float64)
    log = {}
    if np.max(np.abs(x)) < SILENCE_FLOOR:
        return audio.astype(np.float32), {"skipped": "silent"}

    x = _run_board(x, sr, _eq_plugins(d.corrective_eq, sr))
    x = _run_board(x, sr, [
        Compressor(threshold_db=d.compressor.threshold_db, ratio=d.compressor.ratio,
                   attack_ms=d.compressor.attack_ms, release_ms=d.compressor.release_ms),
        Gain(gain_db=d.compressor.makeup_gain_db),
    ])
    x = _run_board(x, sr, _eq_plugins(d.tonal_eq, sr))
    x = _apply_saturator(x, d.saturator)
    x = _apply_ms_image(x, sr, d.stereo_image)

    # 음량 매칭을 리미터 *앞* 에서 — 뒤에서 올리면 피크가 다시 넘친다
    pre_lufs = _integrated_lufs(x, sr)
    gain_db = 0.0
    if pre_lufs > -69.0:
        gain_db = float(np.clip(d.target_lufs - pre_lufs, -24.0, 24.0))
        x = x * (10 ** (gain_db / 20.0))
    log["loudness_gain_db"] = round(gain_db, 2)

    # 리미터 단계.
    # pedalboard.Limiter 는 내부적으로 약 +5dB 메이크업 게인을 더하고 0 dBFS 까지 클립하므로 (실측) 쓰지 않는다.
    # 대신 ratio 20 / attack 0.1ms 컴프레서를 브릭월 리미터로 쓰고, 트루피크와 LUFS 를 다시 재서 보정한다.
    lim_threshold = d.limiter.ceiling_dbtp - 0.3   # 인터샘플 피크 여유
    x = _run_board(x, sr, [Compressor(threshold_db=lim_threshold, ratio=20.0,
                                      attack_ms=0.1, release_ms=d.limiter.release_ms)])
    tp = _true_peak_dbtp(x)
    if tp > d.limiter.ceiling_dbtp:
        trim = d.limiter.ceiling_dbtp - tp
        x = x * (10 ** (trim / 20.0))
        log["true_peak_trim_db"] = round(trim, 2)

    # 리미팅으로 체감 음량이 목표보다 커졌으면 아래로만 되돌린다 (위로 올리면 피크가 다시 넘친다)
    post_lufs = _integrated_lufs(x, sr)
    if post_lufs > -69.0 and post_lufs > d.target_lufs + 0.2:
        trim = d.target_lufs - post_lufs
        x = x * (10 ** (trim / 20.0))
        log["post_limiter_trim_db"] = round(trim, 2)

    return np.clip(x, -1.0, 1.0).astype(np.float32), log


# ══════════════════════════════════════════════════════════════════════════
# 7. 오케스트레이션 — 루나 트랙 하나를 받아 마스터링하고 track_data 를 갱신
# ══════════════════════════════════════════════════════════════════════════

def _preserve_raw(track_dir: str, audio_path: str) -> str:
    """원본을 audio_raw.<ext> 로 한 번만 보존하고 그 경로를 돌려준다."""
    ext = os.path.splitext(audio_path)[1] or ".mp3"
    raw_path = os.path.join(track_dir, RAW_FILENAME_PREFIX + ext)
    if os.path.abspath(audio_path) == os.path.abspath(raw_path):
        return raw_path
    if not os.path.exists(raw_path):
        shutil.copy2(audio_path, raw_path)
    return raw_path


def _url_for(track_id: str, filename: str) -> str:
    return f"/data/luna_music/{track_id}/{filename}"


def master_track(track_data: dict, prompt: str = "", use_llm: bool = True,
                 luna_dir: Optional[str] = None, genre_spec: Optional[dict] = None,
                 progress_cb=None) -> dict:
    """
    루나 track_data 를 받아 마스터링을 수행하고 같은 dict 를 갱신해 돌려준다.
    - 성공: audio_file / audio_url 이 마스터 결과로 바뀌고 audio_raw_* 에 원본이 남는다.
    - 실패·미설치: 원본을 그대로 두고 track_data["mastering"]["status"] 에 사유를 적는다. 예외를 밖으로 던지지 않는다.
    """
    def step(pct, msg):
        if progress_cb:
            progress_cb("mastering", msg, pct)
        print(f"[{pct}%] [Vega] {msg}")

    track_id = track_data.get("track_id") or f"luna_{int(time.time())}"
    genre = (track_data.get("genre") or "default").lower()
    mood = track_data.get("mood") or ""
    started = time.time()

    if not VEGA_AVAILABLE:
        track_data["mastering"] = {
            "status": "skipped", "agent": AGENT_NAME, "engine_version": ENGINE_VERSION,
            "reason": "의존성 미설치: " + _IMPORT_ERROR, "install_hint": availability_report()["install_hint"],
        }
        step(100, "의존성이 없어 마스터링을 건너뜁니다 (원본 유지).")
        return track_data

    try:
        if luna_dir is None:
            import luna_engine  # 지연 import — 순환 참조 방지
            luna_dir = luna_engine.LUNA_DIR
        track_dir = os.path.join(luna_dir, track_id)
        os.makedirs(track_dir, exist_ok=True)

        # 원본 소스 결정: 이미 보존된 raw 가 있으면 그것을, 아니면 현재 audio_file 을 raw 로 보존
        source = track_data.get("audio_raw_file")
        if not source or not os.path.exists(source):
            current = track_data.get("audio_file") or os.path.join(track_dir, "audio.mp3")
            if not os.path.exists(current):
                raise FileNotFoundError(f"마스터링할 음원이 없습니다: {current}")
            source = _preserve_raw(track_dir, current)
        track_data["audio_raw_file"] = source
        track_data["audio_raw_url"] = _url_for(track_id, os.path.basename(source))

        step(10, "원본 음원 로드 및 분석 중...")
        audio, sr = load_audio(source)
        before = analyze(audio, sr)

        step(35, "장르·측정값 기반 마스터링 파라미터 결정 중...")
        decisions, source_kind, note, llm_meta = decide_with_meta(
            before, genre, mood, prompt, use_llm=use_llm, genre_spec=genre_spec)

        step(55, f"DSP 체인 적용 중 (EQ → 컴프 → 새츄레이션 → 이미저 → {decisions.target_lufs:.0f} LUFS → 리미터)...")
        mastered, proc_log = process(audio, sr, decisions)

        step(85, "24bit WAV 저장 및 결과 검증 중...")
        out_path = os.path.join(track_dir, MASTERED_FILENAME)
        write_audio(mastered, sr, out_path, MASTER_BIT_DEPTH)
        after = analyze(mastered, sr)

        track_data["audio_file"] = out_path
        track_data["audio_url"] = _url_for(track_id, MASTERED_FILENAME)
        track_data["mastering"] = {
            "status": "done",
            "agent": AGENT_NAME,
            "engine_version": ENGINE_VERSION,
            "decision_source": source_kind,
            # 실제로 결정을 내린 모델. 프리셋을 썼으면 None, LLM 을 호출했다가 떨어졌으면 llm_attempted 에 남는다.
            "decision_backend": llm_meta.get("backend") if source_kind == "llm" else None,
            "decision_model": llm_meta.get("model") if source_kind == "llm" else None,
            "llm_attempted": llm_meta if (llm_meta.get("attempted") and source_kind != "llm") else None,
            "note": note,
            "prompt": prompt or "",
            "genre": genre,
            "target_lufs": decisions.target_lufs,
            "ceiling_dbtp": decisions.limiter.ceiling_dbtp,
            "before": before,
            "after": after,
            "decisions": decisions.model_dump(),
            "reasoning": decisions.reasoning,
            "process_log": proc_log,
            "output_file": out_path,
            "sample_rate": sr,
            "bit_depth": MASTER_BIT_DEPTH,
            "elapsed_seconds": round(time.time() - started, 1),
            "processed_at": time.time(),
        }
        who = llm_meta.get("model") if source_kind == "llm" else "장르 프리셋"
        step(100, f"마스터링 완료: {before['integrated_lufs']} → {after['integrated_lufs']} LUFS, "
                  f"TP {after['true_peak_dbtp']} dBTP ({who})")
    except Exception as e:
        track_data["mastering"] = {
            "status": "failed", "agent": AGENT_NAME, "engine_version": ENGINE_VERSION,
            "reason": str(e)[:300], "processed_at": time.time(),
        }
        step(100, f"마스터링 실패 — 원본 음원을 그대로 사용합니다: {str(e)[:120]}")
    return track_data
