import React, { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  continueRender,
  delayRender,
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
import { loadFont } from "@remotion/fonts";
import { fitTextOnNLines } from "@remotion/layout-utils";
import { noise2D } from "@remotion/noise";
import { TransitionPresentation, TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { FlyoverScene, FlyoverTime } from "./FlyoverScene";
import { Scene3D } from "./three/Scene3D";
import { Scene3DSpec } from "./three/types";

// 한글 글꼴: Pretendard 가변 폰트(OFL). loadFont 가 받아질 때까지 렌더를 붙잡는다.
const FONT = "Pretendard";
const fontFamily = `${FONT}, "Apple SD Gothic Neo", sans-serif`;
const fontReady = loadFont({
  family: FONT,
  url: "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/woff2/PretendardVariable.woff2",
  weight: "45 920",
  format: "woff2",
});

// ── 규격 (작업계획서 5.2 안전 영역: 공통 900×1400 중앙, 상단 120·하단 300·우측 96 데드존) ──
export const SHORTS_WIDTH = 1080;
export const SHORTS_HEIGHT = 1920;
export const SHORTS_FPS = 30;
export const SAFE_ZONE = { top: 120, bottom: 300, left: 90, right: 96 };

export type ShortsMotion = "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "none";
export type ShortsTransition = "fade" | "slide" | "wipe" | "none";

export type ShortsSceneKind = "image" | "text_card" | "stat_card" | "bar_chart" | "compare" | "flyover" | "scene3d";
export type ShortsBar = { label: string; value: number; highlight?: boolean };
export type ShortsCompareRow = { label: string; from: number; to: number; unit?: string; decimals?: number };

// 씬 한 개. kind 가 image 가 아니면 이미지 없이(비용 0) 그라데이션 배경 위에 타이포·데이터 비주얼을 그린다.
export type ShortsSceneItem = {
  kind?: ShortsSceneKind; // 기본 image
  image?: string; // public/ 기준 상대 경로 (shorts/<job_id>/scene_01.png) — kind=image 일 때 필수
  seconds: number;
  motion?: ShortsMotion;
  transition?: ShortsTransition; // 이 씬으로 들어오는 전환(첫 씬은 무시). 기본 fade
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
  // flyover (3D 항공, three.js) — title 은 지명 라벨
  time_of_day?: FlyoverTime;
  seed?: number;
  // scene3d (범용 3D, three.js) — 환경·바닥·카메라·물체 조합
  scene3d?: Scene3DSpec;
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
  bgmVolume?: number; // 나레이션 중 BGM 볼륨. 기본 0.16
  bgmBoost?: number; // 발화 밖 BGM 배율(bgmVolume 의 몇 배, 최대 0.5). 기본 2.2
  accent?: string;
  brand?: string;
  transitionSeconds?: number; // 씬 전환 길이. 기본 0.4 (0 이면 컷)
  sfx?: boolean; // 효과음 팔레트(전환 whoosh·whip 교대, 숫자 착지 switch). 기본 꺼짐
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

// 안전 영역 안 글자 폭
const CONTENT_WIDTH = SHORTS_WIDTH - SAFE_ZONE.left - SAFE_ZONE.right;

// 글자 크기 측정(measureText)은 결과를 캐시하므로 글꼴이 다 받아진 뒤에만 잰다
const useFontReady = () => {
  const [ready, setReady] = useState(false);
  const [handle] = useState(() => delayRender("Pretendard 글꼴 대기"));
  useEffect(() => {
    fontReady.then(() => {
      setReady(true);
      continueRender(handle);
    });
  }, [handle]);
  return ready;
};

// maxLines 줄 안에 들어가는 가장 큰 글자 크기. 측정이 안 되면 글자 수 기준 어림값(fallback)을 쓴다.
const fitFontSize = (text: string, maxLines: number, width: number, maxFontSize: number, minFontSize: number, fallback: number) => {
  const t = text.trim();
  if (!t) return maxFontSize;
  try {
    const { fontSize } = fitTextOnNLines({ text: t, maxLines, maxBoxWidth: width, fontFamily: FONT, fontWeight: 900, maxFontSize });
    return Math.max(minFontSize, Math.floor(fontSize));
  } catch {
    return fallback;
  }
};

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
  const size = useMemo(() => fitFontSize(title, 3, CONTENT_WIDTH, 104, 56, titleFontSize(title)), [title]);
  return (
    <ContentZone>
      <div style={{ textAlign: "center", wordBreak: "keep-all", overflowWrap: "anywhere", width: "100%" }}>
        <div
          style={{
            fontSize: size,
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

// 비이미지 씬: 배경 + 종류별 콘텐츠. 들어오는 전환은 TransitionSeries 가 맡는다.
const KindScene: React.FC<{ item: ShortsSceneItem; index: number; accent: string; contentFrames: number }> = ({
  item,
  index,
  accent,
  contentFrames,
}) => {
  const frame = useCurrentFrame();
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
    <AbsoluteFill>
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
  seed: number;
}> = ({ src, motion, durationInFrames, seed }) => {
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
  // 손으로 든 카메라처럼 아주 느리게 흔들린다. 노이즈는 이웃 프레임끼리 이어져 떨리지 않고, 시드가 같으면 렌더마다 같다.
  const dx = noise2D(`x${seed}`, frame / 90, 0) * 12;
  const dy = noise2D(`y${seed}`, frame / 90, 0) * 12;
  const rot = noise2D(`r${seed}`, frame / 120, 0) * 0.4;
  return (
    <AbsoluteFill>
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          // 흔들림에 가장자리가 드러나지 않게 3% 더 키운다
          transform: `translateX(${tx}%) translate(${dx}px, ${dy}px) rotate(${rot}deg) scale(${scale * 1.03})`,
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
  // 외곽선(12px)이 바깥으로 번지는 만큼 폭을 줄여 잰다
  const fontSize = useMemo(() => fitFontSize(page.text, 2, CONTENT_WIDTH - 24, 78, 48, captionFontSize(page.text)), [page.text]);
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
  // 배너 안쪽 여백(34×2)과 왼쪽 강조선(14)을 뺀 폭에서 잰다
  const fontSize = useMemo(() => fitFontSize(text, 2, CONTENT_WIDTH - 82, 72, 48, n <= 10 ? 72 : n <= 16 ? 62 : 52), [text, n]);
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

// ── 씬 전환 (@remotion/transitions, CSS 전환만 쓴다) ─────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const presentationFor = (t: ShortsTransition, i: number): TransitionPresentation<any> | null => {
  switch (t) {
    case "none":
      return null;
    case "slide":
      return slide({ direction: i % 2 === 0 ? "from-right" : "from-left" });
    case "wipe":
      return wipe({ direction: i % 2 === 0 ? "from-top-right" : "from-top-left" });
    default:
      return fade();
  }
};

// ── 오디오 2.0 (U-2) ─────────────────────────────────────────────────────────
// 덕킹: 발화(자막 ±250ms) 앞 120ms 동안 내려가고, 끝난 뒤 300ms 동안 올라온다 (계단식 대신 램프)
const DUCK_PAD_MS = 250;
const DUCK_ATTACK_MS = 120;
const DUCK_RELEASE_MS = 300;
// 효과음: CC0 파일을 public/sfx 에 둔다 (원본 remotion.media — whoosh 1bob·whip JW_Audio(freesound), switch kenney.nl)
// peakFrames = 파일 시작부터 소리 정점까지(30fps). 정점이 화면 변화보다 1프레임 늦게 오도록 앞당겨 놓는다 (HF sound.md)
const SFX = {
  whoosh: { src: "sfx/whoosh.wav", peakFrames: 2 },
  whip: { src: "sfx/whip.wav", peakFrames: 1 },
  switch: { src: "sfx/switch.wav", peakFrames: 4 },
} as const;
const STAT_LAND_FRAME = 6 + 40; // countUp(delay 6 + dur 40) 이 끝나는 프레임

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
  bgmBoost = 2.2,
  accent = "#ffd166",
  brand = "",
  transitionSeconds = 0.4,
  sfx = false,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const fontOk = useFontReady();
  const fadeFrames = Math.max(0, Math.round(transitionSeconds * fps));
  const endTagFrames = endTag ? Math.max(1, Math.round(endTag.seconds * fps)) : 0;

  // 씬 타임라인: 씬 i 는 from 에서 시작해 다음 씬의 전환(fadeFrames) 동안 밑에 남는다.
  // TransitionSeries 는 전환 길이만큼 앞 씬과 겹치므로, 앞 씬을 그만큼 늘려 각 씬의 시작 시각(=자막 시각)을 그대로 지킨다.
  const timeline = useMemo(() => {
    const list = scenes || [];
    const transitionOf = (i: number): ShortsTransition =>
      i > 0 && fadeFrames > 0 ? list[i].transition || "fade" : "none";
    let cursor = 0;
    return list.map((s, i) => {
      const dur = Math.max(1, Math.round((Number(s.seconds) || 0) * fps));
      const from = cursor;
      cursor += dur;
      const isLast = i === list.length - 1;
      const motion: ShortsMotion = s.motion || (i % 2 === 0 ? "zoom_in" : "zoom_out");
      const nextOverlaps = !isLast && transitionOf(i + 1) !== "none";
      return {
        from,
        dur,
        // 마지막 씬은 엔드 태그까지 덮는다
        hold: dur + (isLast ? endTagFrames + 1 : nextOverlaps ? fadeFrames : 0),
        transition: transitionOf(i),
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

  // BGM 덕킹 램프: 발화 구간(자막 ±250ms, 겹치면 합침)에서는 bgmVolume, 밖에서는 bgmBoost 배(최대 0.5). 시작 0.5초·끝 1초 페이드
  const speechSpans = useMemo(() => {
    const spans: [number, number][] = [];
    [...(captions || [])]
      .sort((a, b) => a.startMs - b.startMs)
      .forEach((c) => {
        const s0 = c.startMs - DUCK_PAD_MS;
        const e0 = c.endMs + DUCK_PAD_MS;
        const last = spans[spans.length - 1];
        if (last && s0 <= last[1]) last[1] = Math.max(last[1], e0);
        else spans.push([s0, e0]);
      });
    return spans;
  }, [captions]);
  const duckAt = (ms: number) => {
    if (speechSpans.length === 0) return narrationAudio ? 1 : 0;
    let d = 0;
    for (const [s0, e0] of speechSpans) {
      if (ms >= s0 && ms <= e0) return 1;
      if (ms < s0 && s0 - ms < DUCK_ATTACK_MS) d = Math.max(d, 1 - (s0 - ms) / DUCK_ATTACK_MS);
      if (ms > e0 && ms - e0 < DUCK_RELEASE_MS) d = Math.max(d, 1 - (ms - e0) / DUCK_RELEASE_MS);
    }
    return d;
  };
  const bgmVolumeAt = (frame: number) => {
    const high = Math.min(0.5, bgmVolume * bgmBoost);
    const base = high + (bgmVolume - high) * duckAt((frame / fps) * 1000);
    const fadeIn = interpolate(frame, [0, 15], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    const fadeOut = interpolate(frame, [durationInFrames - 30, durationInFrames], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return Math.max(0, Math.min(1, base * fadeIn * fadeOut));
  };

  // 효과음 팔레트: 전환마다 whoosh·whip 교대(같은 소리 연속 금지), stat_card 는 전환 대신 숫자가 멈출 때 switch 1번 — 씬당 최대 1개.
  // 크기는 그 순간 BGM 보다 약 5dB 위(×1.8), 0.12~0.45 사이
  const sfxCues = useMemo(() => {
    if (!sfx) return [] as { key: string; from: number; src: string }[];
    const cues: { key: string; from: number; src: string }[] = [];
    let seam = 0;
    timeline.forEach((t, i) => {
      if (t.kind === "stat_card") {
        cues.push({ key: `sfx-stat-${i}`, from: t.from + STAT_LAND_FRAME + 1 - SFX.switch.peakFrames, src: SFX.switch.src });
      } else if (t.transition !== "none") {
        const snd = seam % 2 === 0 ? SFX.whoosh : SFX.whip;
        seam += 1;
        cues.push({ key: `sfx-seam-${i}`, from: t.from + Math.round(fadeFrames / 2) + 1 - snd.peakFrames, src: snd.src });
      }
    });
    return cues.map((c) => ({ ...c, from: Math.max(0, c.from) }));
  }, [sfx, timeline, fadeFrames]);
  const sfxVolumeAt = (frame: number) => Math.max(0.12, Math.min(0.45, (bgmAudio ? bgmVolumeAt(frame) : 0.2) * 1.8));

  const hookFrames = hookText ? Math.max(1, Math.round(hookSeconds * fps)) : 0;

  if (!fontOk) {
    return <AbsoluteFill style={{ backgroundColor: "#000" }} />;
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", fontFamily }}>
      {/* 1. 씬 + 전환 */}
      <TransitionSeries>
        {timeline.flatMap((t, i) => {
          const presentation = presentationFor(t.transition, i);
          return [
            presentation ? (
              <TransitionSeries.Transition
                key={`tr-${i}`}
                presentation={presentation}
                timing={linearTiming({ durationInFrames: fadeFrames })}
              />
            ) : null,
            <TransitionSeries.Sequence key={`scene-${i}`} durationInFrames={t.hold}>
              {t.kind === "image" && t.src ? (
                <SceneImage src={staticFile(t.src)} motion={t.motion} durationInFrames={t.hold} seed={i} />
              ) : t.kind === "scene3d" ? (
                <Scene3D spec={t.item.scene3d} durationInFrames={t.hold} fontFamily={fontFamily} />
              ) : t.kind === "flyover" ? (
                <FlyoverScene
                  title={t.item.title}
                  timeOfDay={t.item.time_of_day}
                  seed={t.item.seed ?? i + 1}
                  durationInFrames={t.hold}
                  contentFrames={t.dur}
                  fontFamily={fontFamily}
                  labelTop={CONTENT_TOP}
                />
              ) : (
                <KindScene item={t.item} index={i} accent={accent} contentFrames={t.dur} />
              )}
            </TransitionSeries.Sequence>,
          ].filter(Boolean);
        })}
      </TransitionSeries>

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
      {sfxCues.map((c) => (
        <Sequence key={c.key} from={c.from} durationInFrames={Math.round(fps * 0.6)} layout="none">
          <Audio src={staticFile(c.src)} volume={sfxVolumeAt(c.from)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
