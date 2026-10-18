import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {
  Caption,
  TikTokPage,
  createTikTokStyleCaptions,
} from "@remotion/captions";
import { loadFont } from "@remotion/google-fonts/NotoSansKR";

const { fontFamily } = loadFont("normal", {
  weights: ["500", "700", "900"],
  subsets: ["korean", "latin"],
  ignoreTooManyRequestsWarning: true,
});

// ── 규격 (작업계획서 5.2 안전 영역: 공통 900×1400 중앙, 상단 120·하단 300·우측 96 데드존) ──
export const SHORTS_WIDTH = 1080;
export const SHORTS_HEIGHT = 1920;
export const SHORTS_FPS = 30;
export const SAFE_ZONE = { top: 120, bottom: 300, left: 90, right: 96 };

export type ShortsMotion = "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "none";

export type ShortsSceneItem = {
  image: string; // public/ 기준 상대 경로 (shorts/<job_id>/scene_01.png)
  seconds: number;
  motion?: ShortsMotion;
};

// Python 쪽이 만든 어절 토큰. text 는 새 어절이면 앞에 공백 하나를 붙여 보낸다(@remotion/captions 규약).
export type ShortsCaption = {
  text: string;
  startMs: number;
  endMs: number;
  pageBreakAfter?: boolean;
};

export type ShortsEndTag = {
  text: string;
  subtext?: string;
  seconds: number;
};

export type ShortsSceneProps = {
  jobId: string;
  scenes: ShortsSceneItem[];
  hookText?: string;
  hookSeconds?: number;
  endTag?: ShortsEndTag | null;
  captions?: ShortsCaption[];
  captionPageMs?: number; // 한 페이지에 묶을 발화 길이(ms). 기본 1200
  narrationAudio?: string | null;
  bgmAudio?: string | null;
  bgmVolume?: number; // 나레이션 중 BGM 볼륨. 기본 0.16, 비발화 구간은 2.2배(최대 0.5)
  accent?: string;
  brand?: string;
  transitionSeconds?: number; // 씬 크로스페이드. 기본 0.4
};

export const totalSecondsOf = (p: {
  scenes?: ShortsSceneItem[];
  endTag?: ShortsEndTag | null;
}): number => {
  const scenes = (p.scenes || []).reduce((acc, s) => acc + (Number(s.seconds) || 0), 0);
  const tag = p.endTag ? Number(p.endTag.seconds) || 0 : 0;
  return scenes + tag;
};

const msToFrames = (ms: number, fps: number) => Math.round((ms / 1000) * fps);

// ── 씬 이미지 (켄번즈) ──────────────────────────────────────────────────────
const SceneImage: React.FC<{
  src: string;
  motion: ShortsMotion;
  durationInFrames: number;
  fadeInFrames: number;
}> = ({ src, motion, durationInFrames, fadeInFrames }) => {
  const frame = useCurrentFrame();
  const t = Math.min(1, Math.max(0, frame / Math.max(1, durationInFrames)));
  let scale = 1;
  let tx = 0;
  switch (motion) {
    case "zoom_in":
      scale = 1 + 0.12 * t;
      break;
    case "zoom_out":
      scale = 1.12 - 0.12 * t;
      break;
    case "pan_left":
      scale = 1.12;
      tx = 3 - 6 * t; // % 단위: 오른쪽에서 왼쪽으로
      break;
    case "pan_right":
      scale = 1.12;
      tx = -3 + 6 * t;
      break;
    default:
      scale = 1;
  }
  const opacity =
    fadeInFrames > 0
      ? interpolate(frame, [0, fadeInFrames], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 1;
  return (
    <AbsoluteFill style={{ opacity }}>
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `translateX(${tx}%) scale(${scale})`,
        }}
      />
    </AbsoluteFill>
  );
};

// ── 자막 페이지 (틱톡식 어절 하이라이트) ──────────────────────────────────────
const captionFontSize = (text: string) => {
  const n = text.replace(/\s+/g, "").length;
  if (n <= 12) return 78;
  if (n <= 20) return 68;
  if (n <= 28) return 58;
  return 50;
};

const CaptionPage: React.FC<{ page: TikTokPage; accent: string }> = ({ page, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 6 });
  const timeInMs = page.startMs + (frame / fps) * 1000;
  const fontSize = captionFontSize(page.text);
  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingLeft: SAFE_ZONE.left,
        paddingRight: SAFE_ZONE.right,
        paddingBottom: SAFE_ZONE.bottom + 70,
      }}
    >
      <div
        style={{
          fontFamily,
          fontSize,
          fontWeight: 900,
          lineHeight: 1.22,
          textAlign: "center",
          color: "white",
          WebkitTextStroke: "12px rgba(0,0,0,0.92)",
          paintOrder: "stroke fill",
          wordBreak: "keep-all",
          overflowWrap: "anywhere",
          transform: `scale(${interpolate(enter, [0, 1], [0.88, 1])}) translateY(${interpolate(enter, [0, 1], [24, 0])}px)`,
          textShadow: "0 6px 18px rgba(0,0,0,0.6)",
        }}
      >
        {page.tokens.map((tok, i) => {
          const active = tok.fromMs <= timeInMs && timeInMs < tok.toMs;
          return (
            <span
              key={`${tok.fromMs}-${i}`}
              style={{
                display: "inline",
                whiteSpace: "pre",
                color: active ? accent : "white",
              }}
            >
              {tok.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ── 훅 문구 (상단 안전 영역) ──────────────────────────────────────────────────
const HookBanner: React.FC<{ text: string; accent: string; durationInFrames: number }> = ({
  text,
  accent,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 160 }, durationInFrames: 12 });
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const n = text.replace(/\s+/g, "").length;
  const fontSize = n <= 10 ? 72 : n <= 16 ? 62 : 52;
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <div
        style={{
          position: "absolute",
          top: SAFE_ZONE.top + 90,
          left: 0,
          width: "100%",
          boxSizing: "border-box",
          paddingLeft: SAFE_ZONE.left,
          paddingRight: SAFE_ZONE.right,
          textAlign: "center",
          transform: `scale(${interpolate(enter, [0, 1], [0.7, 1])}) translateY(${interpolate(enter, [0, 1], [30, 0])}px)`,
        }}
      >
        <div
          style={{
            display: "inline-block",
            fontFamily,
            fontSize,
            fontWeight: 900,
            lineHeight: 1.2,
            color: "white",
            textAlign: "center",
            padding: "22px 34px",
            borderRadius: 18,
            backgroundColor: "rgba(10,10,14,0.62)",
            borderLeft: `14px solid ${accent}`,
            boxShadow: "0 10px 30px rgba(0,0,0,0.45)",
            wordBreak: "keep-all",
            overflowWrap: "anywhere",
            maxWidth: SHORTS_WIDTH - SAFE_ZONE.left - SAFE_ZONE.right,
          }}
        >
          {text}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ── 엔드 태그 ────────────────────────────────────────────────────────────────
const EndTag: React.FC<{ tag: ShortsEndTag; brand: string; accent: string }> = ({ tag, brand, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fade = interpolate(frame, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const pop = spring({ frame, fps, config: { damping: 16, stiffness: 140 }, durationInFrames: 14 });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: `rgba(0,0,0,${0.62 * fade})`,
        justifyContent: "center",
        alignItems: "center",
        paddingLeft: SAFE_ZONE.left,
        paddingRight: SAFE_ZONE.right,
        paddingBottom: SAFE_ZONE.bottom * 0.6,
        opacity: fade,
      }}
    >
      <div style={{ transform: `scale(${interpolate(pop, [0, 1], [0.8, 1])})`, textAlign: "center", fontFamily }}>
        {brand ? (
          <div style={{ fontSize: 34, letterSpacing: "0.28em", fontWeight: 700, color: accent, marginBottom: 26, textTransform: "uppercase" }}>
            {brand}
          </div>
        ) : null}
        <div style={{ fontSize: 76, fontWeight: 900, color: "white", lineHeight: 1.2, wordBreak: "keep-all", textShadow: "0 6px 18px rgba(0,0,0,0.7)" }}>
          {tag.text}
        </div>
        {tag.subtext ? (
          <div style={{ fontSize: 38, fontWeight: 500, color: "rgba(230,232,240,0.9)", marginTop: 22, wordBreak: "keep-all" }}>
            {tag.subtext}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ── 메인 컴포지션 ─────────────────────────────────────────────────────────────
export const ShortsScene: React.FC<ShortsSceneProps> = ({
  scenes,
  hookText,
  hookSeconds = 3,
  endTag = null,
  captions = [],
  captionPageMs = 1200,
  narrationAudio = null,
  bgmAudio = null,
  bgmVolume = 0.16,
  accent = "#ffd166",
  brand = "",
  transitionSeconds = 0.4,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const fadeFrames = Math.max(0, Math.round(transitionSeconds * fps));
  const endTagFrames = endTag ? Math.max(1, Math.round(endTag.seconds * fps)) : 0;

  // 씬 타임라인: 다음 씬이 fadeFrames 동안 위에 겹쳐 페이드인 → 크로스페이드
  const timeline = useMemo(() => {
    let cursor = 0;
    return (scenes || []).map((s, i) => {
      const dur = Math.max(1, Math.round((Number(s.seconds) || 0) * fps));
      const from = cursor;
      cursor += dur;
      const isLast = i === (scenes || []).length - 1;
      const motion: ShortsMotion = s.motion || (i % 2 === 0 ? "zoom_in" : "zoom_out");
      return {
        from,
        dur,
        // 다음 씬의 페이드인 동안 밑에 남아 있어야 하고, 마지막 씬은 엔드 태그까지 덮는다
        hold: dur + (isLast ? endTagFrames + 1 : fadeFrames),
        motion,
        src: s.image,
      };
    });
  }, [scenes, fps, fadeFrames, endTagFrames]);

  const pages = useMemo(() => {
    if (!captions || captions.length === 0) return [] as TikTokPage[];
    const caps: Caption[] = captions.map((c) => ({
      text: c.text,
      startMs: c.startMs,
      endMs: c.endMs,
      timestampMs: null,
      confidence: null,
      ...(c.pageBreakAfter ? { pageBreakAfter: true } : {}),
    }));
    return createTikTokStyleCaptions({ captions: caps, combineTokensWithinMilliseconds: captionPageMs }).pages;
  }, [captions, captionPageMs]);

  // BGM 덕킹: 자막(발화) 구간 ±250ms 안에서는 bgmVolume, 밖에서는 2.2배(최대 0.5). 끝 1초 페이드아웃
  const bgmVolumeAt = (frame: number) => {
    const ms = (frame / fps) * 1000;
    let speaking = false;
    if (captions && captions.length > 0) {
      speaking = captions.some((c) => ms >= c.startMs - 250 && ms <= c.endMs + 250);
    } else if (narrationAudio) {
      speaking = true;
    }
    const base = speaking ? bgmVolume : Math.min(0.5, bgmVolume * 2.2);
    const fadeIn = interpolate(frame, [0, 15], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    const fadeOut = interpolate(frame, [durationInFrames - 30, durationInFrames], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return Math.max(0, Math.min(1, base * fadeIn * fadeOut));
  };

  const hookFrames = hookText ? Math.max(1, Math.round(hookSeconds * fps)) : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", fontFamily }}>
      {/* 1. 씬 이미지 + 크로스페이드 */}
      {timeline.map((t, i) => (
        <Sequence key={`scene-${i}`} from={t.from} durationInFrames={t.hold} layout="none">
          <SceneImage src={staticFile(t.src)} motion={t.motion} durationInFrames={t.hold} fadeInFrames={i === 0 ? 0 : fadeFrames} />
        </Sequence>
      ))}

      {/* 2. 가독성용 상·하단 그라데이션 */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.55) 0px, rgba(0,0,0,0) 520px, rgba(0,0,0,0) 1200px, rgba(0,0,0,0.62) 1920px)",
        }}
      />

      {/* 3. 자막 페이지 */}
      {pages.map((page, i) => {
        const from = msToFrames(page.startMs, fps);
        const dur = Math.max(1, msToFrames(Number.isFinite(page.durationMs) ? page.durationMs : 1000, fps));
        return (
          <Sequence key={`cap-${i}`} from={from} durationInFrames={dur} layout="none">
            <CaptionPage page={page} accent={accent} />
          </Sequence>
        );
      })}

      {/* 4. 훅 문구 (첫 0.5초 안에 등장) */}
      {hookText ? (
        <Sequence from={0} durationInFrames={hookFrames} layout="none">
          <HookBanner text={hookText} accent={accent} durationInFrames={hookFrames} />
        </Sequence>
      ) : null}

      {/* 5. 엔드 태그 */}
      {endTag ? (
        <Sequence from={Math.max(0, durationInFrames - endTagFrames)} durationInFrames={endTagFrames} layout="none">
          <EndTag tag={endTag} brand={brand} accent={accent} />
        </Sequence>
      ) : null}

      {/* 6. 오디오 */}
      {narrationAudio ? <Audio src={staticFile(narrationAudio)} /> : null}
      {bgmAudio ? <Audio src={staticFile(bgmAudio)} loop volume={bgmVolumeAt} /> : null}
    </AbsoluteFill>
  );
};
