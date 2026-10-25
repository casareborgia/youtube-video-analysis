// A/B 시험(spike/shorts-quality-ab): "예능 자막" 룩과 영상 전체를 관통하는 진행 표시(스레드)
// 근거 — mg-styles-15 18-hanazi(MIT): 채움+굵은 테두리+색 그림자 3겹 글자, 0→1.15→1.0 약 8프레임 팝, 소리보다 2~3프레임 늦게, 머무는 동안 가벼운 흔들림
//        cth9191/animate STORY·FORMATS(MIT): 눈이 붙잡을 상수 하나, 보상 직전 무음 뒤 가장 큰 타격, 끝은 시작이 바뀐 모습
// 코드는 옮기지 않고 규칙·수치만 참고해 Remotion 으로 새로 작성했다.
import React from "react";
import { AbsoluteFill, interpolate, staticFile, useCurrentFrame } from "remotion";
import { TikTokPage } from "@remotion/captions";
import { loadFont } from "@remotion/fonts";

export type ShortsLook = "default" | "variety";

// 예능 자막 글꼴: Jua(주아) — 둥글고 굵은 한 굵기 글꼴(SIL OFL 1.1, google/fonts ofl/jua). 기본 룩에서는 읽지 않는다
export const VARIETY_FONT = "Jua";
let varietyFontPromise: Promise<void> | null = null;
export const loadVarietyFont = () => {
  varietyFontPromise =
    varietyFontPromise || loadFont({ family: VARIETY_FONT, url: staticFile("fonts/Jua-Regular.ttf"), weight: "400", format: "truetype" });
  return varietyFontPromise;
};
export const varietyFamily = `${VARIETY_FONT}, Pretendard, "Apple SD Gothic Neo", sans-serif`;

// 목록형 영상의 진행 표시. items[k] 는 씬 firstScene + k 에서 켜지고, gatherScene 에서 한데 모인다.
export type ShortsThread = {
  items: string[];
  firstScene: number;
  introAtMs?: number; // 빈 점들이 처음 나타나는 시각(훅에서 개수를 말하는 순간)
  gatherScene?: number;
};

// 보상 씬: 그 직전 silenceMs 동안 BGM 을 거의 끄고, 씬 첫 프레임에 영상에서 가장 큰 타격음
export type ShortsPayoff = { scene: number; silenceMs: number };

export const V = {
  ink: "#1d0b33",
  fill: "#ffe14d",
  pop: "#ff3d7f",
  violet: "#7a2cff",
  done: "#5ee0a0",
};

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

// from → over → 1 팝 (frames 프레임). 소리보다 2프레임 늦게 시작하는 건 호출부가 delay 로 준다
export const popScale = (frame: number, delay = 0, frames = 8, from = 0, over = 1.15) =>
  interpolate(frame - delay, [0, frames * 0.6, frames], [from, over, 1], clamp);

// 3겹 예능 글자: 채움 + 굵은 어두운 테두리(paint-order 로 바깥에만) + 색 그림자 + 바닥 그림자
export const varietyText = (size: number, fill = V.fill, shadow = V.pop): React.CSSProperties => ({
  fontFamily: varietyFamily,
  fontSize: size,
  fontWeight: 400, // Jua 는 한 굵기뿐 — 900 을 주면 가짜 굵기로 번진다
  color: fill,
  WebkitTextStroke: `${Math.round(size * 0.16)}px ${V.ink}`,
  paintOrder: "stroke fill",
  textShadow: `0 ${Math.round(size * 0.09)}px 0 ${shadow}, 0 ${Math.round(size * 0.16)}px ${Math.round(size * 0.25)}px rgba(0,0,0,0.45)`,
  lineHeight: 1.12,
  whiteSpace: "pre",
});

// ── 훅: 글자마다 2프레임 엇갈려 튀어 오르는 제목 + 뒤에서 도는 방사선 ───────────────────────────
export const VarietyHook: React.FC<{ text: string; durationInFrames: number; fontFamily: string; top: number }> = ({
  text,
  durationInFrames,
  fontFamily,
  top,
}) => {
  const frame = useCurrentFrame();
  const words = text.trim().split(/\s+/);
  // 마지막 어절(보통 "6가지")을 둘째 줄에 크게
  const line1 = words.slice(0, -1).join(" ");
  const line2 = words[words.length - 1] || "";
  const exit = interpolate(frame, [durationInFrames - 6, durationInFrames], [1, 0], clamp);
  const exitScale = interpolate(frame, [durationInFrames - 6, durationInFrames], [1, 0.6], clamp);
  const burst = popScale(frame, 2 + line1.length * 2, 10, 0, 1.2);
  const wobble = Math.sin(frame / 6) * 1.2;
  const chars = (s: string, offset: number, size: number, fill: string, shadow: string) =>
    [...s].map((ch, i) => {
      const d = 2 + (offset + i) * 2;
      const y = interpolate(frame - d, [0, 5, 8], [-70, 8, 0], clamp);
      return (
        <span key={`${offset}-${i}`} style={{ display: "inline-block", transform: `translateY(${y}px) scale(${popScale(frame, d)})`, ...varietyText(size, fill, shadow) }}>
          {ch}
        </span>
      );
    });
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <div style={{ position: "absolute", top, left: 0, width: "100%", textAlign: "center", fontFamily, transform: `scale(${exitScale}) rotate(${-4 + wobble * 0.3}deg)` }}>
        <svg width={760} height={760} viewBox="-380 -380 760 760"
          style={{ position: "absolute", left: 540 - 380, top: 190 - 380, transform: `scale(${burst}) rotate(${frame * 0.8}deg)`, opacity: 0.9 }}>
          {Array.from({ length: 18 }, (_, k) => {
            const a = (k / 18) * Math.PI * 2;
            return <line key={k} x1={Math.cos(a) * 150} y1={Math.sin(a) * 150} x2={Math.cos(a) * 340} y2={Math.sin(a) * 340}
              stroke={k % 2 ? V.fill : V.pop} strokeWidth={k % 2 ? 14 : 22} strokeLinecap="round" />;
          })}
        </svg>
        <div style={{ position: "relative" }}>{chars(line1, 0, 104, "#ffffff", V.violet)}</div>
        <div style={{ position: "relative", marginTop: 6 }}>{chars(line2, line1.length, 170, V.fill, V.pop)}</div>
      </div>
    </AbsoluteFill>
  );
};

// ── 자막: 그룹마다 팝, 강조어는 노란 3겹 글자로 크게·기울여 말하는 순간 한 번 더 튄다 ───────────────
export const VarietyCaptionPage: React.FC<{
  page: TikTokPage;
  emphasisFrom: Set<number>;
  offsetMs: number;
  durationInFrames: number;
  fontFamily: string;
  fontSize: number;
  bottom: number;
  padX: [number, number];
  fps: number;
}> = ({ page, emphasisFrom, offsetMs, durationInFrames, fontFamily, fontSize, bottom, padX, fps }) => {
  const frame = useCurrentFrame();
  const timeInMs = page.startMs + offsetMs + (frame / fps) * 1000;
  const enter = popScale(frame, 2, 7, 0.55, 1.12);
  const exit = interpolate(frame, [durationInFrames - 4, durationInFrames], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingLeft: padX[0], paddingRight: padX[1], paddingBottom: bottom, opacity: exit }}>
      <div style={{ fontFamily, textAlign: "center", wordBreak: "keep-all", overflowWrap: "anywhere", transform: `scale(${enter})`, lineHeight: 1.25 }}>
        {page.tokens.map((tok, i) => {
          const active = tok.fromMs <= timeInMs && timeInMs < tok.toMs;
          const strong = emphasisFrom.has(tok.fromMs);
          const local = ((timeInMs - tok.fromMs) / 1000) * fps;
          // 강조어는 글자 크기 자체를 키워 자리를 차지하게 하고(이웃을 덮지 않게), 말하는 순간 1.12배로만 한 번 더 튄다
          const sScale = strong && local >= 0 ? popScale(local, 2, 8, 1, 1.12) : 1;
          const base = varietyText(strong ? fontSize * 1.18 : fontSize, active || strong ? V.fill : "#ffffff", strong ? V.pop : V.violet);
          return (
            <span key={`${tok.fromMs}-${i}`} style={{
              ...base,
              display: "inline-block",
              transformOrigin: "50% 70%",
              transform: strong ? `scale(${sScale}) rotate(${-4 + Math.sin(frame / 7) * 1.2}deg)` : undefined,
              margin: strong ? "0 0.14em" : undefined,
            }}>
              {tok.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ── 스레드: 위쪽 진행 점 N개(지금 항목은 크게) + 이름 스티커 → 보상 씬에서 2열 격자로 모임 ─────────
export type ThreadTimes = { introFrame: number; itemFrames: number[]; gatherFrame: number | null; endFrame: number };

export const ThreadLayer: React.FC<{ thread: ShortsThread; times: ThreadTimes; fontFamily: string; safeTop: number; rowCenterX: number; dim?: boolean }> = ({
  thread,
  times,
  fontFamily,
  safeTop,
  rowCenterX,
  dim = true,
}) => {
  const frame = useCurrentFrame();
  const n = thread.items.length;
  if (frame < times.introFrame) return null;
  let cur = -1;
  times.itemFrames.forEach((f, k) => {
    if (frame >= f) cur = k;
  });
  const gathering = times.gatherFrame !== null && frame >= times.gatherFrame;
  const g = gathering ? frame - (times.gatherFrame as number) : 0;
  const DOT = 66;
  const GAP = 28;
  const rowW = n * DOT + (n - 1) * GAP;
  const rowY = safeTop + 40;
  const dotX = (k: number) => rowCenterX - rowW / 2 + k * (DOT + GAP) + DOT / 2;
  const fade = interpolate(frame, [times.endFrame - 8, times.endFrame], [1, 0], clamp);

  if (gathering) {
    // 2열 격자. 각 칸은 위 점 자리에서 날아와 1.4 → 1.0 으로 꽂힌다(2프레임 엇갈림)
    const cellW = 420;
    const cellH = 150;
    const gx = (k: number) => rowCenterX + (k % 2 === 0 ? -cellW / 2 - 12 : cellW / 2 + 12);
    const gy = (k: number) => 600 + Math.floor(k / 2) * (cellH + 28);
    return (
      <AbsoluteFill style={{ opacity: fade, fontFamily }}>
        {dim ? <AbsoluteFill style={{ backgroundColor: `rgba(12,6,24,${interpolate(g, [0, 4], [0, 0.5], clamp)})` }} /> : null}
        {thread.items.map((name, k) => {
          const d = k * 2;
          const p = interpolate(g - d, [0, 6], [0, 1], clamp);
          const x = interpolate(p, [0, 1], [dotX(k), gx(k)]);
          const y = interpolate(p, [0, 1], [rowY + DOT / 2, gy(k) + cellH / 2]);
          const s = interpolate(g - d, [0, 4, 7], [0.3, 1.4, 1], clamp);
          const rot = (k % 2 === 0 ? -3 : 3) + Math.sin((frame + k * 9) / 8) * 1.5;
          return (
            <div key={k} style={{
              position: "absolute", left: x - cellW / 2, top: y - cellH / 2, width: cellW, height: cellH,
              transform: `scale(${s}) rotate(${rot}deg)`, borderRadius: 34, backgroundColor: "#ffffff",
              border: `8px solid ${V.ink}`, boxShadow: `0 12px 0 ${k % 2 ? V.violet : V.pop}`,
              display: "flex", alignItems: "center", gap: 18, padding: "0 22px", boxSizing: "border-box",
            }}>
              <div style={{ flex: "0 0 auto", width: 76, height: 76, borderRadius: 38, backgroundColor: V.pop, border: `6px solid ${V.ink}`,
                color: "#fff", fontSize: 46, fontWeight: 400, display: "flex", alignItems: "center", justifyContent: "center" }}>{k + 1}</div>
              <div style={{ fontSize: name.length >= 6 ? 46 : 54, fontWeight: 400, color: V.ink, whiteSpace: "nowrap", lineHeight: 1.1 }}>{name}</div>
            </div>
          );
        })}
      </AbsoluteFill>
    );
  }

  const name = cur >= 0 ? thread.items[cur] : "";
  const since = cur >= 0 ? frame - times.itemFrames[cur] : 0;
  return (
    <AbsoluteFill style={{ opacity: fade, fontFamily }}>
      {thread.items.map((_, k) => {
        const appear = popScale(frame, times.introFrame + 2 + k * 2, 8);
        const isCur = k === cur;
        const done = k < cur;
        const lit = isCur ? popScale(since, 2, 8, 0.6, 1.3) : 1;
        const size = isCur ? DOT * 1.25 : DOT;
        return (
          <div key={k} style={{
            position: "absolute", left: dotX(k) - size / 2, top: rowY + DOT / 2 - size / 2, width: size, height: size, borderRadius: size / 2,
            transform: `scale(${appear * lit})`, boxSizing: "border-box",
            border: `6px solid ${V.ink}`, backgroundColor: isCur ? V.pop : done ? V.done : "rgba(255,255,255,0.92)",
            boxShadow: isCur ? `0 0 0 6px ${V.fill}, 0 8px 0 ${V.ink}` : `0 6px 0 ${V.ink}`,
            color: isCur ? "#fff" : V.ink, fontSize: isCur ? 46 : 36, fontWeight: 400,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>{k + 1}</div>
        );
      })}
      {cur >= 0 ? (
        <div style={{ position: "absolute", top: rowY + DOT + 44, left: 0, width: rowCenterX * 2, textAlign: "center" }}>
          <span style={{
            display: "inline-block", ...varietyText(84),
            transform: `scale(${popScale(since, 3, 8)}) rotate(${-3 + Math.sin(frame / 7) * 1.2}deg)`,
          }}>{name}</span>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
