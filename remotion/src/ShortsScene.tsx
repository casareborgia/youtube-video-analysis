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

export type ShortsSceneKind = "image" | "text_card" | "stat_card" | "bar_chart" | "compare";
export type ShortsBar = { label: string; value: number; highlight?: boolean };
export type ShortsCompareRow = { label: string; from: number; to: number; unit?: string; decimals?: number };

// 씬 한 개. kind 가 image 가 아니면 이미지 없이(비용 0) 그라데이션 배경 위에 타이포·데이터 비주얼을 그린다.
export type ShortsSceneItem = {
  kind?: ShortsSceneKind; // 기본 image
  image?: string; // public/ 기준 상대 경로 (shorts/<job_id>/scene_01.png) — kind=image 일 때 필수
  seconds: number;
  motion?: ShortsMotion;
  palette?: number; // 비이미지 씬 배경 팔레트 인덱스(기본: 씬 순서)
  // text_card
  title?: string;
  subtitle?: string;
  // stat_card
  value?: number;
  unit?: string;
  prefix?: string;
  decimals?: number;
  label?: string;
  // bar_chart
  bars?: ShortsBar[];
  // compare
  rows?: ShortsCompareRow[];
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

// ── 비이미지 씬 공통: 배경·카운트업·콘텐츠 영역 ─────────────────────────────
// 콘텐츠 영역은 훅 배너(상단 ~520px)와 자막(하단 ~1250px 이하) 사이에 둔다.
const CONTENT_TOP = 560;
const CONTENT_BOTTOM = SAFE_ZONE.bottom + 430;

const PALETTES: Array<[string, string, string]> = [
  ["#0b1026", "#1b2a4a", "#4f8cff"],
  ["#140b26", "#3a1f4f", "#c56bff"],
  ["#061f1f", "#0f3d3e", "#2fd4c1"],
  ["#1f1206", "#4a2a1b", "#ffb347"],
  ["#071a10", "#1f3f2a", "#5fe08a"],
  ["#0a0a1c", "#2b1b4a", "#ff6b9d"],
];

const easeOutCubic = (x: number) => 1 - Math.pow(1 - x, 3);

const countUp = (frame: number, target: number, delay = 6, dur = 40) =>
  target * easeOutCubic(Math.min(1, Math.max(0, (frame - delay) / dur)));

const fmt = (v: number, decimals = 0) =>
  v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

const GradientBackdrop: React.FC<{ palette: number }> = ({ palette }) => {
  const frame = useCurrentFrame();
  const [c1, c2, glow] = PALETTES[((palette % PALETTES.length) + PALETTES.length) % PALETTES.length];
  const drift = Math.sin(frame / 90) * 60;
  const drift2 = Math.cos(frame / 110) * 80;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(160deg, ${c1} 0%, ${c2} 100%)` }}>
      <div
        style={{
          position: "absolute",
          left: 540 + drift - 520,
          top: 700 + drift2 - 520,
          width: 1040,
          height: 1040,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${glow}55 0%, ${glow}00 62%)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 140 - drift2 - 380,
          top: 1500 - drift - 380,
          width: 760,
          height: 760,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${glow}33 0%, ${glow}00 65%)`,
        }}
      />
      {/* 미세한 격자: 정지 슬라이드 느낌을 줄이는 질감 */}
      <AbsoluteFill
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px)",
          backgroundSize: "90px 90px",
          backgroundPosition: `${drift}px ${drift2}px`,
        }}
      />
    </AbsoluteFill>
  );
};

const ContentZone: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill
    style={{
      paddingTop: CONTENT_TOP,
      paddingBottom: CONTENT_BOTTOM,
      paddingLeft: SAFE_ZONE.left,
      paddingRight: SAFE_ZONE.right,
      justifyContent: "center",
      alignItems: "center",
      fontFamily,
      color: "white",
    }}
  >
    {children}
  </AbsoluteFill>
);

const titleFontSize = (text: string) => {
  const n = text.replace(/\s+/g, "").length;
  if (n <= 8) return 104;
  if (n <= 14) return 92;
  if (n <= 22) return 76;
  return 64;
};

const TextCardScene: React.FC<{ item: ShortsSceneItem; accent: string }> = ({ item, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 18, stiffness: 120 }, durationInFrames: 18 });
  const sub = spring({ frame: frame - 8, fps, config: { damping: 20 }, durationInFrames: 18 });
  const title = item.title || "";
  return (
    <ContentZone>
      <div style={{ textAlign: "center", wordBreak: "keep-all", overflowWrap: "anywhere", width: "100%" }}>
        <div
          style={{
            fontSize: titleFontSize(title),
            fontWeight: 900,
            lineHeight: 1.18,
            textShadow: "0 8px 30px rgba(0,0,0,0.55)",
            transform: `translateY(${interpolate(enter, [0, 1], [40, 0])}px)`,
            opacity: enter,
          }}
        >
          {title}
        </div>
        {item.subtitle ? (
          <div
            style={{
              marginTop: 34,
              fontSize: 42,
              fontWeight: 600,
              color: accent,
              letterSpacing: "0.02em",
              opacity: Math.max(0, sub),
              transform: `translateY(${interpolate(Math.max(0, sub), [0, 1], [20, 0])}px)`,
            }}
          >
            {item.subtitle}
          </div>
        ) : null}
        <div style={{ margin: "40px auto 0", width: interpolate(enter, [0, 1], [0, 160]), height: 8, borderRadius: 4, backgroundColor: accent }} />
      </div>
    </ContentZone>
  );
};

const StatCardScene: React.FC<{ item: ShortsSceneItem; accent: string }> = ({ item, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 16, stiffness: 110 }, durationInFrames: 18 });
  const target = Number(item.value) || 0;
  const v = countUp(frame, target);
  return (
    <ContentZone>
      <div style={{ textAlign: "center", width: "100%", wordBreak: "keep-all" }}>
        {item.title ? <div style={{ fontSize: 44, fontWeight: 700, color: "rgba(255,255,255,0.85)", marginBottom: 26 }}>{item.title}</div> : null}
        <div style={{ transform: `scale(${interpolate(enter, [0, 1], [0.8, 1])})`, opacity: enter }}>
          <span style={{ fontSize: 96, fontWeight: 900, color: accent, verticalAlign: "top", marginRight: 10 }}>{item.prefix || ""}</span>
          <span style={{ fontSize: 220, fontWeight: 900, color: accent, lineHeight: 1, textShadow: `0 0 50px ${accent}55` }}>
            {fmt(v, item.decimals || 0)}
          </span>
          <span style={{ fontSize: 84, fontWeight: 800, color: accent, marginLeft: 12 }}>{item.unit || ""}</span>
        </div>
        {item.label ? <div style={{ marginTop: 30, fontSize: 48, fontWeight: 700, lineHeight: 1.3, whiteSpace: "pre-line" }}>{item.label}</div> : null}
      </div>
    </ContentZone>
  );
};

const BarChartScene: React.FC<{ item: ShortsSceneItem; accent: string }> = ({ item, accent }) => {
  const frame = useCurrentFrame();
  const bars = item.bars || [];
  const max = Math.max(1, ...bars.map((b) => Number(b.value) || 0));
  const decimals = item.decimals ?? 0;
  return (
    <ContentZone>
      <div style={{ width: "100%" }}>
        {item.title ? <div style={{ fontSize: 50, fontWeight: 800, marginBottom: 44, textAlign: "center", wordBreak: "keep-all" }}>{item.title}</div> : null}
        {bars.map((b, i) => {
          const delay = 6 + i * 10;
          const p = easeOutCubic(Math.min(1, Math.max(0, (frame - delay) / 40)));
          const val = (Number(b.value) || 0) * p;
          const w = (val / max) * 100;
          const color = b.highlight ? accent : "rgba(255,255,255,0.55)";
          return (
            <div key={i} style={{ marginBottom: 34, opacity: Math.min(1, Math.max(0, (frame - delay + 6) / 10)) }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 40, fontWeight: b.highlight ? 900 : 600, marginBottom: 12, color: b.highlight ? "white" : "rgba(255,255,255,0.8)" }}>
                <span>{b.label}</span>
                <span style={{ color }}>{fmt(val, decimals)}{item.unit || ""}</span>
              </div>
              <div style={{ height: 34, borderRadius: 17, backgroundColor: "rgba(255,255,255,0.12)", overflow: "hidden" }}>
                <div style={{ width: `${w}%`, height: "100%", borderRadius: 17, backgroundColor: color, boxShadow: b.highlight ? `0 0 30px ${accent}88` : undefined }} />
              </div>
            </div>
          );
        })}
      </div>
    </ContentZone>
  );
};

const CompareScene: React.FC<{ item: ShortsSceneItem; accent: string }> = ({ item, accent }) => {
  const frame = useCurrentFrame();
  const rows = item.rows || [];
  return (
    <ContentZone>
      <div style={{ width: "100%" }}>
        {item.title ? <div style={{ fontSize: 50, fontWeight: 800, marginBottom: 40, textAlign: "center", wordBreak: "keep-all" }}>{item.title}</div> : null}
        {rows.map((r, i) => {
          const delay = 6 + i * 14;
          const p = easeOutCubic(Math.min(1, Math.max(0, (frame - delay) / 40)));
          const from = Number(r.from) || 0;
          const to = Number(r.to) || 0;
          const cur = from + (to - from) * p;
          const d = r.decimals ?? 0;
          return (
            <div
              key={i}
              style={{
                marginBottom: 36,
                padding: "26px 30px",
                borderRadius: 24,
                backgroundColor: "rgba(0,0,0,0.28)",
                border: "2px solid rgba(255,255,255,0.1)",
                opacity: Math.min(1, Math.max(0, (frame - delay + 8) / 12)),
                transform: `translateY(${(1 - Math.min(1, Math.max(0, (frame - delay + 8) / 12))) * 24}px)`,
              }}
            >
              <div style={{ fontSize: 38, fontWeight: 600, color: "rgba(255,255,255,0.8)", marginBottom: 10, wordBreak: "keep-all" }}>{r.label}</div>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 26 }}>
                <span style={{ fontSize: 72, fontWeight: 700, color: "rgba(255,255,255,0.45)", textDecoration: "line-through", textDecorationThickness: 5 }}>
                  {fmt(from, d)}{r.unit || ""}
                </span>
                <span style={{ fontSize: 60, color: accent }}>→</span>
                <span style={{ fontSize: 112, fontWeight: 900, color: accent, lineHeight: 1, textShadow: `0 0 40px ${accent}55` }}>
                  {fmt(cur, d)}
                  <span style={{ fontSize: 56, marginLeft: 6 }}>{r.unit || ""}</span>
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </ContentZone>
  );
};

// 비이미지 씬: 배경 + 종류별 콘텐츠. 이미지 씬과 같은 페이드인 규칙을 따른다.
const KindScene: React.FC<{ item: ShortsSceneItem; index: number; accent: string; fadeInFrames: number; contentFrames: number }> = ({
  item,
  index,
  accent,
  fadeInFrames,
  contentFrames,
}) => {
  const frame = useCurrentFrame();
  const opacity =
    fadeInFrames > 0
      ? interpolate(frame, [0, fadeInFrames], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
      : 1;
  // 씬 본래 길이가 끝나면(다음 씬 크로스페이드·엔드 태그 구간) 콘텐츠만 먼저 걷어 글자가 겹치지 않게 한다
  const contentOpacity = interpolate(frame, [contentFrames - 8, contentFrames + 4], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const palette = item.palette ?? index;
  let body: React.ReactNode = null;
  switch (item.kind) {
    case "stat_card":
      body = <StatCardScene item={item} accent={accent} />;
      break;
    case "bar_chart":
      body = <BarChartScene item={item} accent={accent} />;
      break;
    case "compare":
      body = <CompareScene item={item} accent={accent} />;
      break;
    default:
      body = <TextCardScene item={item} accent={accent} />;
  }
  return (
    <AbsoluteFill style={{ opacity }}>
      <GradientBackdrop palette={palette} />
      <AbsoluteFill style={{ opacity: contentOpacity }}>{body}</AbsoluteFill>
    </AbsoluteFill>
  );
};

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
        src: s.image || "",
        kind: (s.kind || "image") as ShortsSceneKind,
        item: s,
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
          {t.kind === "image" && t.src ? (
            <SceneImage src={staticFile(t.src)} motion={t.motion} durationInFrames={t.hold} fadeInFrames={i === 0 ? 0 : fadeFrames} />
          ) : (
            <KindScene item={t.item} index={i} accent={accent} fadeInFrames={i === 0 ? 0 : fadeFrames} contentFrames={t.dur} />
          )}
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
