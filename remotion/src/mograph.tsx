// A/B 시험 C(spike/shorts-quality-ab): 이미지 없이 코드로 그리는 모션그래픽 씬
// 연출 규칙 출처(코드 이식 없음, 규칙·수치만 참고):
//  - cth9191/animate STORY·FORMATS·FRAME: 처음부터 끝까지 같은 주인공 하나, "한 문장 장치"(트렌드마다 빛줄기 하나), 목소리가 시계(단어에 맞춰 동작),
//    아이디어는 글자 대신 행동으로, 씬마다 작은 생명(눈 깜빡임·숨쉬기)
//  - howseen-ai/claude-motion-design: 색 범람은 원인이 되는 물체(주인공)에서 시작해 가장 먼 모서리까지 0.3~0.35초, 스프링 감쇠비 0.72 이상
//  - bangtutorial/bang-motion: 배경은 늘 움직이고 두 겹 이상, 화면 글자 대신 아이콘, 주인공 60% 이상 등장
//  - JohnHeibel/ClaudeAnimationBase: 예비동작·팔로스루, 표정은 갑자기 바뀌지 않게, 소품은 손(몸)에 닿게
import React from "react";
import { AbsoluteFill, interpolate, random, useCurrentFrame } from "remotion";
import type { TransitionPresentation, TransitionPresentationComponentProps } from "@remotion/transitions";
import { popScale, V } from "./variety";

export type MographArt = "hook" | "agent" | "multimodal" | "video" | "local" | "coding" | "trust" | "cta";
export type MographSpec = { art: MographArt; bg: string; cuesMs: number[] };

const cl = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const prog = (f: number, start: number, dur: number) => cl((f - start) / Math.max(1, dur));
const eio = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const eob = (t: number) => {
  const c1 = 1.4;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
};
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

// 트렌드별 색 — 주인공의 빛줄기·카드 그림자·격자 칸이 같은 색을 쓴다(animate: 색은 한 가지 의미만)
export const ITEM_COLORS = ["#ff3d7f", "#4fc3ff", "#ffb347", "#5ee0a0", "#c56bff", "#ffe14d"];
const INK = V.ink;
const PAPER = "#fffaf0";

// 씬별 주인공 자리(x, y, 크기). 글자 영역(위 진행 표시 ~420, 아래 자막 ~1440) 사이에 둔다
export const POSES: Record<MographArt, [number, number, number]> = {
  hook: [370, 1040, 1.05],
  agent: [515, 1010, 1.12],
  multimodal: [515, 1010, 1.2],
  video: [410, 1090, 1.0],
  local: [515, 998, 1.1],
  coding: [680, 1070, 1.0],
  trust: [515, 1010, 1.0],
  cta: [515, 1300, 0.62],
};

// ── 주인공 ─────────────────────────────────────────────────────────────────
type Mood = "happy" | "wow" | "focus";
const Hero: React.FC<{
  x: number; y: number; s: number; frame: number; rays: { at: number; color: string }[];
  mood: Mood; look: [number, number]; squash: number; tilt: number;
}> = ({ x, y, s, frame, rays, mood, look, squash, tilt }) => {
  const R = 130;
  const blink = (frame + 23) % 84 < 3 || (frame + 61) % 151 < 3;
  const eyeRy = mood === "wow" ? 27 : blink ? 3 : 22;
  const eyeRx = mood === "wow" ? 19 : 16;
  const bob = Math.sin((frame / 30) * Math.PI) * 7;
  const angles = [-150, -126, -102, -78, -54, -30];
  return (
    <g transform={`translate(${x} ${y + bob}) rotate(${tilt}) scale(${s})`}>
      {rays.map((r, k) => {
        if (frame < r.at) return null;
        const p = popScale(frame, r.at, 8, 0, 1.3);
        const a = (angles[k] * Math.PI) / 180;
        const r0 = R + 18;
        const r1 = R + 18 + 58 * p;
        return (
          <g key={k}>
            <line x1={Math.cos(a) * r0} y1={Math.sin(a) * r0} x2={Math.cos(a) * r1} y2={Math.sin(a) * r1}
              stroke={INK} strokeWidth={26} strokeLinecap="round" />
            <line x1={Math.cos(a) * r0} y1={Math.sin(a) * r0} x2={Math.cos(a) * r1} y2={Math.sin(a) * r1}
              stroke={r.color} strokeWidth={14} strokeLinecap="round" />
          </g>
        );
      })}
      <g transform={`translate(0 ${R}) scale(${1 + squash} ${1 - squash}) translate(0 ${-R})`}>
        <ellipse cx={0} cy={R + 14} rx={R * 0.8} ry={16} fill="rgba(0,0,0,0.25)" />
        <circle r={R} fill={V.fill} stroke={INK} strokeWidth={10} />
        <path d={`M ${-R * 0.62} ${-R * 0.45} A ${R * 0.75} ${R * 0.75} 0 0 1 ${-R * 0.1} ${-R * 0.78}`} stroke="#fff6c2" strokeWidth={14} fill="none" strokeLinecap="round" />
        <circle cx={-70} cy={34} r={18} fill="#ff8fb1" opacity={0.7} />
        <circle cx={70} cy={34} r={18} fill="#ff8fb1" opacity={0.7} />
        {[-42, 42].map((ex) => (
          <g key={ex}>
            <ellipse cx={ex + look[0] * 6} cy={-18 + look[1] * 6} rx={eyeRx} ry={eyeRy} fill={INK} />
            {eyeRy > 6 ? <circle cx={ex + look[0] * 6 + 5} cy={-26 + look[1] * 6} r={5} fill="#fff" /> : null}
          </g>
        ))}
        {mood === "wow" ? (
          <ellipse cx={0} cy={44} rx={18} ry={22} fill={INK} />
        ) : mood === "focus" ? (
          <path d="M -22 44 L 22 44" stroke={INK} strokeWidth={9} strokeLinecap="round" />
        ) : (
          <path d="M -30 34 Q 0 66 30 34" stroke={INK} strokeWidth={9} fill="none" strokeLinecap="round" />
        )}
      </g>
    </g>
  );
};

export type MographEntry = { from: number; dur: number; art: MographArt; cues: number[] };

// 주인공은 씬 위 한 층에서 계속 그린다 — 세계가 바뀌어도 주인공은 그대로(animate match-position)
export const HeroLayer: React.FC<{ entries: MographEntry[]; rayFrames: number[]; endFrame: number }> = ({ entries, rayFrames, endFrame }) => {
  const frame = useCurrentFrame();
  if (!entries.length) return null;
  let i = 0;
  entries.forEach((e, k) => {
    if (frame >= e.from) i = k;
  });
  const e = entries[i];
  const f = frame - e.from;
  const [tx, ty, ts] = POSES[e.art];
  const [px, py, ps] = i > 0 ? POSES[entries[i - 1].art] : [tx, ty, ts];
  const m = eio(prog(f, 0, 14));
  let x = lerp(px, tx, m);
  let y = lerp(py, ty, m);
  let s = lerp(ps, ts, m);
  let squash = 0;
  let tilt = Math.sin(frame / 22) * 2;
  let mood: Mood = "happy";
  let look: [number, number] = [0, 0];
  const c = e.cues;
  const near = (cf: number, a: number, b: number) => f >= cf - a && f <= cf + b;

  switch (e.art) {
    case "hook": {
      // 등장: 0.2초 쪼그렸다가(예비동작) 튀어나옴
      const appear = popScale(frame, 6, 10, 0, 1.15);
      s *= appear;
      if (c[1] !== undefined) {
        const lean = interpolate(f, [c[1] - 6, c[1], c[1] + 10], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        x += 46 * lean;
        tilt += 10 * lean;
        if (near(c[1], 2, 12)) mood = "wow";
      }
      look = [1, 0];
      break;
    }
    case "agent":
      look = c.length ? [Math.cos(((f * 0.12 - 140) * Math.PI) / 180) * 0.6, -0.4] : [0, 0];
      if (c.some((cf) => near(cf, 0, 10))) mood = "focus";
      break;
    case "multimodal": {
      const k = c.findIndex((cf) => near(cf, 4, 8));
      if (k >= 0) {
        mood = "wow";
        squash = 0.06 * Math.sin(prog(f, c[k] - 4, 12) * Math.PI);
      }
      break;
    }
    case "video":
      look = [1, -0.3];
      if (c[2] !== undefined && near(c[2], 0, 10)) mood = "wow";
      break;
    case "local":
      if (c[0] !== undefined) {
        // 쪼그림(예비동작) → 포물선 점프 → 착지 찌그러짐(팔로스루)
        const pre = interpolate(f, [c[0] - 6, c[0]], [0, 0.12], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        const air = prog(f, c[0], 16);
        const land = interpolate(f, [c[0] + 16, c[0] + 19, c[0] + 26], [0, 0.14, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        squash = f < c[0] ? pre : air < 1 ? -0.08 : land;
        if (air > 0 && air < 1) y -= Math.sin(air * Math.PI) * 170;
      }
      look = [0.4, -0.5];
      break;
    case "coding":
      look = [-1, -0.4];
      if (c[1] !== undefined && f >= c[1] && f < (c[2] ?? 1e9)) mood = "focus";
      break;
    case "trust":
      look = [0, -0.6];
      if (c[0] !== undefined && near(c[0], 0, 20)) mood = "wow";
      break;
    case "cta":
      tilt += Math.sin(frame / 6) * 6;
      look = [0, -1];
      break;
  }
  const rays = rayFrames.map((at, k) => ({ at, color: ITEM_COLORS[k % ITEM_COLORS.length] }));
  const fade = interpolate(frame, [endFrame - 8, endFrame], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <svg width={1080} height={1920} viewBox="0 0 1080 1920">
        <Hero x={x} y={y} s={s} frame={frame} rays={rays} mood={mood} look={look} squash={squash} tilt={tilt} />
      </svg>
    </AbsoluteFill>
  );
};

// ── 배경: 단색 + 주인공 뒤 빛 + 천천히 떠다니는 도형 + 점 격자(두 겹, 늘 움직임) ─────────────────
const Backdrop: React.FC<{ bg: string; seed: string; glowAt: [number, number]; frame: number; gradientTo?: string }> = ({ bg, seed, glowAt, frame, gradientTo }) => {
  const shapes = Array.from({ length: 9 }, (_, k) => {
    const rx = random(`${seed}-x-${k}`);
    const ry = random(`${seed}-y-${k}`);
    const kind = Math.floor(random(`${seed}-k-${k}`) * 3);
    const size = 40 + random(`${seed}-s-${k}`) * 90;
    const px = rx * 1080 + Math.sin(frame / (70 + k * 9) + k) * 30;
    const py = 200 + ry * 1500 + Math.cos(frame / (80 + k * 7) + k) * 40 - frame * 0.25;
    return { kind, size, px, py, rot: frame * (k % 2 ? 0.4 : -0.3) };
  });
  return (
    <AbsoluteFill style={{ background: gradientTo ? `linear-gradient(180deg, ${bg} 0%, ${gradientTo} 100%)` : bg }}>
      <svg width={1080} height={1920} viewBox="0 0 1080 1920">
        <defs>
          <radialGradient id={`glow-${seed}`}>
            <stop offset="0%" stopColor="#ffffff" stopOpacity={0.22} />
            <stop offset="100%" stopColor="#ffffff" stopOpacity={0} />
          </radialGradient>
          <pattern id={`dots-${seed}`} width={54} height={54} patternUnits="userSpaceOnUse" patternTransform={`translate(${(frame * 0.4) % 54} ${(frame * 0.25) % 54})`}>
            <circle cx={4} cy={4} r={3} fill="#ffffff" opacity={0.09} />
          </pattern>
        </defs>
        <rect width={1080} height={1920} fill={`url(#dots-${seed})`} />
        <circle cx={glowAt[0]} cy={glowAt[1]} r={520 + Math.sin(frame / 25) * 20} fill={`url(#glow-${seed})`} />
        {shapes.map((sh, k) => (
          <g key={k} transform={`translate(${sh.px} ${((sh.py % 1920) + 1920) % 1920}) rotate(${sh.rot})`} opacity={0.16}>
            {sh.kind === 0 ? <circle r={sh.size / 2} fill="#fff" /> : sh.kind === 1 ? (
              <circle r={sh.size / 2} fill="none" stroke="#fff" strokeWidth={10} />
            ) : (
              <path d={`M ${-sh.size / 2} 0 H ${sh.size / 2} M 0 ${-sh.size / 2} V ${sh.size / 2}`} stroke="#fff" strokeWidth={12} strokeLinecap="round" />
            )}
          </g>
        ))}
      </svg>
    </AbsoluteFill>
  );
};

// ── 소품 그리기 도우미 ─────────────────────────────────────────────────────────
const Card: React.FC<{ x: number; y: number; s: number; w?: number; h?: number; shadow: string; children?: React.ReactNode; fill?: string; r?: number }> = ({
  x, y, s, w = 150, h = 150, shadow, children, fill = PAPER, r = 28,
}) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <rect x={-w / 2} y={-h / 2 + 12} width={w} height={h} rx={r} fill={shadow} />
    <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={r} fill={fill} stroke={INK} strokeWidth={8} />
    {children}
  </g>
);

const Check: React.FC<{ x: number; y: number; s: number; r?: number }> = ({ x, y, s, r = 30 }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <circle r={r} fill={V.done} stroke={INK} strokeWidth={6} />
    <path d={`M ${-r * 0.45} 0 L ${-r * 0.1} ${r * 0.35} L ${r * 0.5} ${-r * 0.35}`} stroke={INK} strokeWidth={8} fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </g>
);

const Pictogram: React.FC<{ x: number; y: number; s: number; color?: string; lean?: number }> = ({ x, y, s, color = "#ffffff", lean = 0 }) => (
  <g transform={`translate(${x} ${y}) rotate(${lean}) scale(${s})`}>
    <circle cx={0} cy={-120} r={52} fill={color} stroke={INK} strokeWidth={8} />
    <rect x={-70} y={-62} width={140} height={170} rx={60} fill={color} stroke={INK} strokeWidth={8} />
  </g>
);

const MiniScene: React.FC<{ x: number; y: number; w: number; h: number; k: number }> = ({ x, y, w, h, k }) => {
  const sky = ["#4fc3ff", "#ffb347", "#c56bff", "#5ee0a0"][k % 4];
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={10} fill={sky} />
      <circle cx={w * 0.22} cy={-h * 0.18} r={h * 0.14} fill="#fff3a8" />
      <path d={`M ${-w / 2} ${h / 2} L ${-w * 0.15} ${-h * 0.05} L ${w * 0.1} ${h * 0.2} L ${w * 0.3} ${0} L ${w / 2} ${h / 2} Z`} fill={INK} opacity={0.75} />
    </g>
  );
};

// ── 씬별 그림 (f = 씬 안 프레임, c = 단어 큐 프레임) ─────────────────────────────────────
const ArtHook: React.FC<{ f: number; c: number[] }> = ({ f, c }) => {
  const appear = c[0] !== undefined ? popScale(f, c[0], 10, 0, 1.15) : 1;
  const bump = c[1] !== undefined ? interpolate(f, [c[1] - 6, c[1], c[1] + 10], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  const spark = c[1] !== undefined ? popScale(f, c[1], 10, 0, 1.3) * interpolate(f, [c[1] + 14, c[1] + 26], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  return (
    <g>
      <Pictogram x={720 - 40 * bump} y={1110} s={appear} lean={-10 * bump} />
      {spark > 0.01 ? (
        <g transform={`translate(550 990) scale(${spark})`}>
          {Array.from({ length: 8 }, (_, k) => {
            const a = (k / 8) * Math.PI * 2;
            return <line key={k} x1={Math.cos(a) * 30} y1={Math.sin(a) * 30} x2={Math.cos(a) * 90} y2={Math.sin(a) * 90} stroke={k % 2 ? V.fill : V.pop} strokeWidth={14} strokeLinecap="round" />;
          })}
        </g>
      ) : null}
    </g>
  );
};

const ICON = {
  search: <g><circle cx={-12} cy={-12} r={34} fill="none" stroke={INK} strokeWidth={12} /><path d="M 14 14 L 44 44" stroke={INK} strokeWidth={14} strokeLinecap="round" /></g>,
  calendar: <g><rect x={-46} y={-40} width={92} height={84} rx={12} fill="none" stroke={INK} strokeWidth={10} /><rect x={-46} y={-40} width={92} height={22} rx={8} fill={V.pop} />
    {[0, 1, 2].map((r) => [0, 1, 2].map((q) => <circle key={`${r}${q}`} cx={-26 + q * 26} cy={0 + r * 18} r={5} fill={INK} />))}</g>,
  code: <g><path d="M -22 -32 L -50 0 L -22 32 M 22 -32 L 50 0 L 22 32" stroke={INK} strokeWidth={12} fill="none" strokeLinecap="round" strokeLinejoin="round" /><path d="M 8 -40 L -8 40" stroke={V.pop} strokeWidth={10} strokeLinecap="round" /></g>,
  doc: <g><rect x={-40} y={-50} width={80} height={100} rx={10} fill="#fff" stroke={INK} strokeWidth={8} />{[0, 1, 2, 3].map((k) => <rect key={k} x={-26} y={-32 + k * 20} width={k === 3 ? 30 : 52} height={8} rx={4} fill={INK} />)}</g>,
  image: <g><rect x={-50} y={-40} width={100} height={80} rx={10} fill="#4fc3ff" stroke={INK} strokeWidth={8} /><circle cx={20} cy={-14} r={12} fill="#fff3a8" /><path d="M -50 40 L -16 0 L 8 24 L 24 10 L 50 40 Z" fill={INK} /></g>,
  wave: <g>{[-36, -18, 0, 18, 36].map((x, k) => <rect key={k} x={x - 6} y={-[18, 36, 48, 30, 14][k]} width={12} height={[18, 36, 48, 30, 14][k] * 2} rx={6} fill={INK} />)}</g>,
  film: <g><rect x={-50} y={-38} width={100} height={76} rx={8} fill={INK} />{[-36, -12, 12, 36].map((x) => <g key={x}><rect x={x - 6} y={-32} width={12} height={10} rx={2} fill="#fff" /><rect x={x - 6} y={22} width={12} height={10} rx={2} fill="#fff" /></g>)}<rect x={-30} y={-16} width={60} height={32} rx={4} fill="#ffb347" /></g>,
};

const ArtAgent: React.FC<{ f: number; c: number[]; hx: number; hy: number }> = ({ f, c, hx, hy }) => {
  const icons = [ICON.search, ICON.calendar, ICON.code];
  const base = [-150, -30, 90];
  const spin = f * 0.12;
  return (
    <g>
      {icons.map((icon, k) => {
        const cue = c[k];
        if (cue === undefined || f < cue - 4) return null;
        const fly = eob(prog(f, cue - 4, 12));
        const a = ((base[k] + spin) * Math.PI) / 180;
        const x = lerp(hx, hx + Math.cos(a) * 300, fly);
        const y = lerp(hy, hy + Math.sin(a) * 280, fly);
        return (
          <g key={k}>
            <line x1={hx} y1={hy} x2={x} y2={y} stroke="#fff" strokeOpacity={0.5} strokeWidth={6} strokeDasharray="14 14" strokeDashoffset={-f * 2} />
            <Card x={x} y={y} s={popScale(f, cue - 4, 10)} shadow={ITEM_COLORS[0]}>{icon}</Card>
            {f >= cue + 14 ? <Check x={x + 62} y={y - 62} s={popScale(f, cue + 14, 8, 0, 1.3)} /> : null}
          </g>
        );
      })}
    </g>
  );
};

const ArtMultimodal: React.FC<{ f: number; c: number[]; hx: number; hy: number }> = ({ f, c, hx, hy }) => {
  const items = [
    { icon: ICON.doc, from: [190, 560], color: "#ffffff" },
    { icon: ICON.image, from: [840, 560], color: "#4fc3ff" },
    { icon: ICON.wave, from: [190, 1340], color: "#ffb347" },
    { icon: ICON.film, from: [840, 1340], color: "#ff3d7f" },
  ];
  const done = c.length ? c[c.length - 1] + 18 : 1e9;
  return (
    <g>
      {items.map((it, k) => {
        const cue = c[k];
        if (cue === undefined) return null;
        const t = prog(f, cue - 6, 14);
        const e = eio(t);
        // 바깥으로 부푼 곡선을 따라 주인공에게 빨려 든다
        const cx = (it.from[0] + hx) / 2 + (it.from[0] < hx ? -120 : 120);
        const cy = (it.from[1] + hy) / 2;
        const x = (1 - e) * (1 - e) * it.from[0] + 2 * (1 - e) * e * cx + e * e * hx;
        const y = (1 - e) * (1 - e) * it.from[1] + 2 * (1 - e) * e * cy + e * e * hy;
        const s = popScale(f, 6 + k * 4, 8) * (t < 0.75 ? 1 : 1 - (t - 0.75) / 0.25);
        const idle = t === 0 ? Math.sin((f + k * 11) / 9) * 8 : 0;
        const ring = prog(f, cue + 8, 14);
        return (
          <g key={k}>
            {t < 1 ? <Card x={x} y={y + idle} s={Math.max(0, s)} w={150} h={150} shadow={it.color}>{it.icon}</Card> : null}
            {ring > 0 && ring < 1 ? <circle cx={hx} cy={hy} r={150 + ring * 160} fill="none" stroke={it.color} strokeWidth={14 * (1 - ring)} opacity={1 - ring} /> : null}
          </g>
        );
      })}
      {f >= done ? items.map((it, k) => {
        const a = (f * 3 + k * 90) * (Math.PI / 180);
        return <circle key={`o${k}`} cx={hx + Math.cos(a) * 205} cy={hy + Math.sin(a) * 190} r={16 * popScale(f, done + k * 2, 8)} fill={it.color} stroke={INK} strokeWidth={5} />;
      }) : null}
    </g>
  );
};

const ArtVideo: React.FC<{ f: number; c: number[] }> = ({ f, c }) => {
  const [cPaper, cClap, cSnap, cSound, cFilm] = c;
  const paperIn = cPaper !== undefined ? popScale(f, cPaper, 8) : 0;
  const toClap = cClap !== undefined ? eio(prog(f, cClap, 10)) : 0;
  const clapS = cClap !== undefined ? popScale(f, cClap + 6, 8) : 0;
  const arm = cSnap !== undefined ? interpolate(f, [cSnap - 3, cSnap, cSnap + 4, cSnap + 7], [-30, 0, -4, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : -30;
  const CX = 720;
  const CY = 900;
  return (
    <g>
      {paperIn > 0 && toClap < 1 ? (
        <g opacity={1 - toClap}>
          <Card x={lerp(515, CX, toClap)} y={lerp(640, CY, toClap)} s={paperIn * (1 - 0.6 * toClap)} w={240} h={300} shadow={ITEM_COLORS[2]} r={16}>
            {[0, 1, 2, 3].map((k) => (
              <rect key={k} x={-90} y={-100 + k * 50} height={16} rx={8} fill={INK} width={180 * (k === 3 ? 0.55 : 1) * prog(f, (cPaper ?? 0) + 4 + k * 5, 8)} />
            ))}
          </Card>
        </g>
      ) : null}
      {cFilm !== undefined && f >= cFilm - 2 ? (
        <g transform={`translate(${1100 - eio(prog(f, cFilm - 2, 14)) * 560 - Math.max(0, f - cFilm - 12) * 5} 600)`}>
          <rect x={-40} y={-95} width={1400} height={190} fill={INK} />
          {Array.from({ length: 6 }, (_, k) => (
            <g key={k}>
              {Array.from({ length: 4 }, (_, h) => <rect key={h} x={k * 230 + h * 54} y={-86} width={26} height={14} rx={3} fill="#fff" />)}
              {Array.from({ length: 4 }, (_, h) => <rect key={`b${h}`} x={k * 230 + h * 54} y={72} width={26} height={14} rx={3} fill="#fff" />)}
              <MiniScene x={k * 230 + 95} y={0} w={200} h={120} k={k} />
            </g>
          ))}
        </g>
      ) : null}
      {clapS > 0 ? (
        <g transform={`translate(${CX} ${CY}) scale(${clapS})`}>
          <rect x={-110} y={-40} width={220} height={150} rx={14} fill="#26203a" stroke={INK} strokeWidth={8} />
          <rect x={-90} y={0} width={180} height={18} rx={9} fill="#fff" opacity={0.5} />
          <rect x={-90} y={40} width={120} height={18} rx={9} fill="#fff" opacity={0.5} />
          <g transform={`translate(-110 -40) rotate(${arm})`}>
            <rect x={0} y={-42} width={220} height={42} rx={8} fill="#fff" stroke={INK} strokeWidth={8} />
            {[0, 1, 2, 3].map((k) => <path key={k} d={`M ${20 + k * 52} -42 L ${44 + k * 52} -42 L ${24 + k * 52} 0 L ${0 + k * 52} 0 Z`} fill={INK} />)}
          </g>
        </g>
      ) : null}
      {cSound !== undefined && f >= cSound ? (
        <g transform={`translate(${CX + 10} ${CY + 170})`}>
          {Array.from({ length: 7 }, (_, k) => {
            const h = 20 + Math.abs(Math.sin(f / 4 + k * 1.3)) * 50;
            return <rect key={k} x={-105 + k * 32} y={-h / 2} width={20} height={h * popScale(f, cSound + k, 6)} rx={10} fill={ITEM_COLORS[2]} stroke={INK} strokeWidth={5} />;
          })}
        </g>
      ) : null}
    </g>
  );
};

const ArtLocal: React.FC<{ f: number; c: number[] }> = ({ f, c }) => {
  const [cHop, cNet, cNo, cMac, cDraw] = c;
  const rise = eob(prog(f, 2, 14));
  const led = cHop !== undefined && f >= cHop + 16 ? 0.6 + 0.4 * Math.sin(f / 5) : 0.2;
  const wifiS = cNet !== undefined ? popScale(f, cNet, 8) : 0;
  const slash = cNo !== undefined ? prog(f, cNo, 8) : 0;
  const glow = cMac !== undefined ? interpolate(f, [cMac, cMac + 6, cMac + 20], [0, 1, 0.3], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  return (
    <g>
      <g transform={`translate(515 ${1222 + (1 - rise) * 500})`}>
        <rect x={-210} y={-70} width={420} height={140} rx={40} fill="#c9ced8" stroke={INK} strokeWidth={9} />
        <rect x={-210} y={-70} width={420} height={44} rx={30} fill="#e6e9ef" />
        <rect x={-150} y={20} width={300} height={10} rx={5} fill="#9aa1ae" />
        <circle cx={168} cy={24} r={9} fill={V.done} opacity={led} />
        {glow > 0 ? <rect x={-230} y={-90} width={460} height={180} rx={56} fill="none" stroke={V.fill} strokeWidth={10} opacity={glow} /> : null}
      </g>
      {wifiS > 0 ? (
        <g transform={`translate(850 900) scale(${wifiS})`}>
          <circle r={86} fill="#fff" stroke={INK} strokeWidth={8} />
          {[0, 1, 2].map((k) => <path key={k} d={`M ${-22 - k * 16} ${8 - k * 14} Q 0 ${-16 - k * 26} ${22 + k * 16} ${8 - k * 14}`} stroke={INK} strokeWidth={10} fill="none" strokeLinecap="round" />)}
          <circle cx={0} cy={26} r={9} fill={INK} />
          {slash > 0 ? <path d={`M -60 -60 L ${-60 + 120 * slash} ${-60 + 120 * slash}`} stroke={V.pop} strokeWidth={18} strokeLinecap="round" /> : null}
        </g>
      ) : null}
      {cDraw !== undefined
        ? [0, 1, 2].map((k) => {
            const t = eob(prog(f, cDraw + k * 4, 12));
            if (t <= 0) return null;
            const tx = [300, 515, 730][k];
            const ty = [640, 580, 640][k];
            return (
              <g key={k} transform={`rotate(${[-8, 0, 8][k]} ${lerp(515, tx, t)} ${lerp(1150, ty, t)})`}>
                <Card x={lerp(515, tx, t)} y={lerp(1150, ty, t)} s={popScale(f, cDraw + k * 4, 8)} w={190} h={150} shadow={ITEM_COLORS[3]} r={10}>
                  <MiniScene x={0} y={0} w={160} h={120} k={k + 1} />
                </Card>
              </g>
            );
          })
        : null}
    </g>
  );
};

const ArtCoding: React.FC<{ f: number; c: number[] }> = ({ f, c }) => {
  const [cTalk, cCode, cApp, cTest] = c;
  const bubble = cTalk !== undefined ? popScale(f, cTalk, 8) : 0;
  const panel = cCode !== undefined ? popScale(f, cCode, 8) : 0;
  const morph = cApp !== undefined ? eio(prog(f, cApp, 12)) : 0;
  const w = lerp(360, 270, morph);
  const h = lerp(420, 520, morph);
  const PX = 300;
  const PY = 820;
  const bars = [0.8, 0.55, 0.7, 0.4, 0.65, 0.5];
  return (
    <g>
      {bubble > 0 ? (
        <g transform={`translate(760 850) scale(${bubble})`}>
          <path d="M -90 -50 H 90 Q 110 -50 110 -30 V 30 Q 110 50 90 50 H -40 L -80 84 L -70 50 H -90 Q -110 50 -110 30 V -30 Q -110 -50 -90 -50 Z" fill="#fff" stroke={INK} strokeWidth={8} />
          {[-40, 0, 40].map((x, k) => <circle key={k} cx={x} cy={Math.sin(f / 4 + k) * 6} r={12} fill={INK} />)}
        </g>
      ) : null}
      {panel > 0 ? (
        <g transform={`translate(${PX} ${PY}) scale(${panel})`}>
          <rect x={-w / 2} y={-h / 2 + 12} width={w} height={h} rx={lerp(24, 46, morph)} fill={ITEM_COLORS[4]} />
          <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={lerp(24, 46, morph)} fill={morph > 0.5 ? PAPER : "#1b1433"} stroke={INK} strokeWidth={9} />
          {morph < 0.5
            ? bars.map((b, k) => (
                <rect key={k} x={-w / 2 + 36 + (k % 3 === 1 ? 30 : 0)} y={-h / 2 + 50 + k * 56} height={20} rx={10}
                  width={(w - 90) * b * prog(f, (cCode ?? 0) + 4 + k * 6, 8)} fill={[V.pop, "#4fc3ff", V.fill, V.done, "#c56bff", "#fff"][k]} opacity={1 - morph * 2} />
              ))
            : (
              <g opacity={(morph - 0.5) * 2}>
                <rect x={-w / 2 + 24} y={-h / 2 + 28} width={w - 48} height={56} rx={14} fill={ITEM_COLORS[4]} />
                {[0, 1, 2].map((k) => (
                  <g key={k} transform={`translate(0 ${-h / 2 + 130 + k * 96}) scale(${popScale(f, (cApp ?? 0) + 8 + k * 3, 8)})`}>
                    <rect x={-w / 2 + 24} y={-36} width={w - 48} height={72} rx={14} fill="#fff" stroke={INK} strokeWidth={6} />
                    <circle cx={-w / 2 + 64} cy={0} r={20} fill={[V.pop, "#4fc3ff", V.fill][k]} />
                    <rect x={-w / 2 + 98} y={-10} width={w - 160} height={20} rx={10} fill={INK} opacity={0.7} />
                  </g>
                ))}
                <rect x={-80} y={h / 2 - 84} width={160} height={52} rx={26} fill={V.pop} stroke={INK} strokeWidth={6} />
              </g>
            )}
        </g>
      ) : null}
      {cTest !== undefined ? [0, 1, 2].map((k) => (f >= cTest + k * 5 ? <Check key={k} x={505} y={640 + k * 92} s={popScale(f, cTest + k * 5, 8, 0, 1.3)} r={34} /> : null)) : null}
    </g>
  );
};

const ArtTrust: React.FC<{ f: number; c: number[] }> = ({ f, c }) => {
  const [cShield, cWin] = c;
  const people = [[230, 1250], [345, 1300], [685, 1300], [800, 1250]];
  const draw = cShield !== undefined ? prog(f, cShield, 18) : 0;
  const L = 2000;
  const fillOp = cShield !== undefined ? interpolate(f, [cShield + 14, cShield + 24], [0, 0.22], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  const shield = "M 515 690 C 640 750 720 750 770 740 C 790 980 720 1170 515 1290 C 310 1170 240 980 260 740 C 310 750 390 750 515 690 Z";
  return (
    <g>
      {people.map(([x, y], k) => <Pictogram key={k} x={x} y={y} s={0.62 * popScale(f, 4 + k * 3, 8)} color={["#ffffff", "#ffe1ec", "#e0f4ff", "#fff3d6"][k]} />)}
      {draw > 0 ? (
        <g>
          <path d={shield} fill={V.done} opacity={fillOp} />
          <path d={shield} fill="none" stroke={INK} strokeWidth={30} strokeDasharray={L} strokeDashoffset={L * (1 - draw)} strokeLinejoin="round" />
          <path d={shield} fill="none" stroke={V.done} strokeWidth={16} strokeDasharray={L} strokeDashoffset={L * (1 - draw)} strokeLinejoin="round" />
        </g>
      ) : null}
      {cShield !== undefined && f >= cShield + 16 ? <Check x={515} y={700} s={popScale(f, cShield + 16, 8, 0, 1.3)} r={44} /> : null}
      {cWin !== undefined && f >= cWin ? (
        <g transform={`translate(820 640) rotate(${f * 1.5}) scale(${popScale(f, cWin, 10, 0, 1.25)})`}>
          <path d="M 0 -70 L 20 -22 L 70 -20 L 30 12 L 44 62 L 0 34 L -44 62 L -30 12 L -70 -20 L -20 -22 Z" fill={V.fill} stroke={INK} strokeWidth={8} strokeLinejoin="round" />
        </g>
      ) : null}
    </g>
  );
};

const ArtCta: React.FC<{ f: number; c: number[] }> = ({ f, c }) => {
  const cm = c[0];
  if (cm === undefined || f < cm) return null;
  return (
    <g transform={`translate(720 1230) scale(${popScale(f, cm, 8, 0, 1.2)})`}>
      <path d="M -80 -50 H 80 Q 100 -50 100 -30 V 26 Q 100 46 80 46 H -20 L -60 80 L -50 46 H -80 Q -100 46 -100 26 V -30 Q -100 -50 -80 -50 Z" fill="#fff" stroke={INK} strokeWidth={8} />
      <path d="M 0 22 C -40 -4 -30 -36 0 -18 C 30 -36 40 -4 0 22 Z" fill={V.pop} />
    </g>
  );
};

// ── 씬 하나: 배경 + 소품. 강조어 순간(punchAt)에 세계만 살짝 다가간다(주인공은 그대로) ────────────
export const MographScene: React.FC<{ spec: MographSpec; cues: number[]; contentFrames: number; punchAt?: number[]; index: number }> = ({
  spec, cues, contentFrames, punchAt = [], index,
}) => {
  const f = useCurrentFrame();
  const [hx, hy] = POSES[spec.art];
  const breathe = 1 + 0.012 * Math.sin(f / 45);
  const punch = punchAt.reduce((acc, p) => acc + 0.05 * (1 - Math.pow(1 - cl((f - p) / 4), 3)), 0);
  const fadeOut = interpolate(f, [contentFrames - 6, contentFrames + 6], [1, 0.0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  let art: React.ReactNode = null;
  switch (spec.art) {
    case "hook": art = <ArtHook f={f} c={cues} />; break;
    case "agent": art = <ArtAgent f={f} c={cues} hx={hx} hy={hy} />; break;
    case "multimodal": art = <ArtMultimodal f={f} c={cues} hx={hx} hy={hy} />; break;
    case "video": art = <ArtVideo f={f} c={cues} />; break;
    case "local": art = <ArtLocal f={f} c={cues} />; break;
    case "coding": art = <ArtCoding f={f} c={cues} />; break;
    case "trust": art = <ArtTrust f={f} c={cues} />; break;
    case "cta": art = <ArtCta f={f} c={cues} />; break;
  }
  return (
    <AbsoluteFill>
      <Backdrop bg={spec.bg} seed={`m${index}`} glowAt={[hx, hy]} frame={f} gradientTo={spec.art === "cta" ? "#ff6f91" : undefined} />
      <AbsoluteFill style={{ transform: `scale(${breathe * (1 + punch)})`, transformOrigin: `${hx}px ${hy}px`, opacity: spec.art === "cta" ? 1 : fadeOut }}>
        <svg width={1080} height={1920} viewBox="0 0 1080 1920">{art}</svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ── 주인공에서 번지는 전환: 다음 세계가 주인공 몸에서 원으로 퍼져 가장 먼 모서리까지(claude-motion-design flood) ─────
const HeroFlood: React.FC<TransitionPresentationComponentProps<{ x: number; y: number }>> = ({ children, presentationDirection, presentationProgress: p, passedProps }) => {
  if (presentationDirection === "exiting") return <AbsoluteFill>{children}</AbsoluteFill>;
  const { x, y } = passedProps;
  const far = Math.max(...[[0, 0], [1080, 0], [0, 1920], [1080, 1920]].map(([cx, cy]) => Math.hypot(cx - x, cy - y))) * 1.05;
  const e = 1 - Math.pow(1 - p, 3);
  const r = 120 + (far - 120) * e;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ clipPath: `circle(${r}px at ${x}px ${y}px)` }}>{children}</AbsoluteFill>
      {p < 1 ? (
        <svg width={1080} height={1920} style={{ position: "absolute", inset: 0 }}>
          <circle cx={x} cy={y} r={r} fill="none" stroke="#ffffff" strokeOpacity={0.8 * (1 - p)} strokeWidth={18} />
        </svg>
      ) : null}
    </AbsoluteFill>
  );
};
export const heroFlood = (x: number, y: number): TransitionPresentation<{ x: number; y: number }> => ({ component: HeroFlood, props: { x, y } });

// 씬 그림의 효과음 — 화면에 원인이 있는 순간만(HF sound.md, brag sfx-analysis 의 고역 위험 낮은 소리)
export type CueSound = "bong" | "drop2" | "drop3" | "click" | "clap" | "land" | "glass" | "key1" | "key2";
export const artSounds = (art: MographArt, cues: number[]): { at: number; snd: CueSound; vol: number }[] => {
  const out: { at: number; snd: CueSound; vol: number }[] = [];
  const c = cues;
  switch (art) {
    case "hook":
      if (c[0] !== undefined) out.push({ at: c[0] + 2, snd: "drop3", vol: 0.3 });
      if (c[1] !== undefined) out.push({ at: c[1] + 1, snd: "bong", vol: 0.4 });
      break;
    case "agent":
      c.slice(0, 3).forEach((cf, k) => {
        out.push({ at: cf, snd: "drop2", vol: 0.28 });
        out.push({ at: cf + 15, snd: k % 2 ? "key2" : "click", vol: 0.3 });
      });
      break;
    case "multimodal":
      c.slice(0, 4).forEach((cf, k) => out.push({ at: cf + 8, snd: k % 2 ? "drop3" : "bong", vol: 0.32 }));
      break;
    case "video":
      if (c[0] !== undefined) out.push({ at: c[0] + 2, snd: "drop2", vol: 0.28 });
      if (c[2] !== undefined) out.push({ at: c[2], snd: "clap", vol: 0.5 });
      if (c[4] !== undefined) out.push({ at: c[4], snd: "drop3", vol: 0.25 });
      break;
    case "local":
      if (c[0] !== undefined) out.push({ at: c[0] + 17, snd: "land", vol: 0.45 });
      if (c[1] !== undefined) out.push({ at: c[1] + 2, snd: "drop2", vol: 0.28 });
      if (c[2] !== undefined) out.push({ at: c[2] + 2, snd: "click", vol: 0.35 });
      if (c[4] !== undefined) [0, 1, 2].forEach((k) => out.push({ at: c[4] + k * 4 + 3, snd: k % 2 ? "drop3" : "drop2", vol: 0.26 }));
      break;
    case "coding":
      if (c[0] !== undefined) out.push({ at: c[0] + 2, snd: "drop2", vol: 0.26 });
      if (c[1] !== undefined) [0, 1, 2, 3, 4, 5].forEach((k) => out.push({ at: c[1] + 4 + k * 6, snd: k % 2 ? "key2" : "key1", vol: 0.22 }));
      if (c[2] !== undefined) out.push({ at: c[2] + 6, snd: "bong", vol: 0.32 });
      if (c[3] !== undefined) [0, 1, 2].forEach((k) => out.push({ at: c[3] + k * 5 + 2, snd: "click", vol: 0.3 }));
      break;
    case "trust":
      if (c[0] !== undefined) out.push({ at: c[0] + 18, snd: "glass", vol: 0.32 });
      if (c[1] !== undefined) out.push({ at: c[1] + 3, snd: "bong", vol: 0.3 });
      break;
    case "cta":
      if (c[0] !== undefined) out.push({ at: c[0] + 3, snd: "drop2", vol: 0.3 });
      break;
  }
  return out;
};
