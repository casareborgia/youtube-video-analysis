import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MAP_VIEW, WARRING_STATES, YELLOW_RIVER, centroid, stateById } from "./warringStatesMap";

// 전국시대 지도 씬(map): 지도 → 강조 나라 차례로 → 진군 화살표. 직접 그린 개략도라 'approximate' 를 함께 적는다.
// 등장 프레임 수는 shorts_review._anim_end_seconds(map) 과 맞춘다(10 + 화살표 수 × 14 + 30).
const INK = "#2a251e";
const LINE = "#8a7a5a";
const RED = "#b3261e";
const PAPER = "#efe6d2";
const MAP_W = 900;   // 지도 아래 연도 줄까지 자막 영역(1250px~) 위에서 끝나게
const SCALE = MAP_W / MAP_VIEW.width;

export type MapArrow = { from: string; to: string };

const pathOf = (pts: [number, number][]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ") + " Z";

export const MapScene: React.FC<{
  states?: string[];
  arrows?: MapArrow[];
  year?: string;
  title?: string;
  contentFrames: number;
  fontFamily: string;
}> = ({ states = [], arrows = [], year = "c. 260 BC", title, contentFrames, fontFamily }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 10 });
  const fadeOut = interpolate(frame, [contentFrames - 8, contentFrames + 4], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const zoom = interpolate(frame, [0, Math.max(1, contentFrames)], [1, 1.05], { extrapolateRight: "clamp" });
  const highlighted = new Set(states);

  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, #241f18 0%, #110f0c 70%)", opacity: fadeOut, fontFamily }}>
      {title ? (
        <div style={{ position: "absolute", top: 210, left: 90, right: 96, textAlign: "center", fontSize: 58, fontWeight: 800, color: PAPER, opacity: enter }}>
          {title}
        </div>
      ) : null}
      <svg
        width={MAP_W}
        height={MAP_VIEW.height * SCALE}
        viewBox={`0 0 ${MAP_VIEW.width} ${MAP_VIEW.height}`}
        style={{ position: "absolute", left: (1080 - MAP_W) / 2, top: 330, transform: `scale(${zoom})`, opacity: enter, overflow: "visible" }}
      >
        <defs>
          <marker id="arrowhead" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 Z" fill={RED} />
          </marker>
        </defs>
        {WARRING_STATES.map((s, i) => {
          const on = highlighted.has(s.id);
          const k = on ? Math.max(0, [...highlighted].indexOf(s.id)) : 0;
          const lit = on ? interpolate(frame, [10 + k * 6, 22 + k * 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
          return (
            <path
              key={s.id}
              d={pathOf(s.points)}
              fill={on ? `rgba(179,38,30,${0.25 + 0.5 * lit})` : INK}
              stroke={on ? `rgba(212,175,55,${0.4 + 0.6 * lit})` : LINE}
              strokeWidth={on ? 4 : 2}
              strokeLinejoin="round"
            />
          );
        })}
        <polyline
          points={YELLOW_RIVER.map((p) => p.join(",")).join(" ")}
          fill="none"
          stroke="rgba(120,160,190,0.45)"
          strokeWidth={5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {WARRING_STATES.map((s) => {
          const [x, y] = centroid(s.points);
          const on = highlighted.has(s.id);
          return (
            <g key={`l-${s.id}`}>
              <text x={x} y={y - 6} textAnchor="middle" fontSize={on ? 58 : 46} fontWeight={800} fill={on ? PAPER : "#b9ab8e"}>
                {s.en}
              </text>
              <text x={x} y={y + 40} textAnchor="middle" fontSize={on ? 36 : 30} fill={on ? "#d4af37" : "#8a7a5a"}>
                {s.zh}
              </text>
            </g>
          );
        })}
        {arrows.map((a, i) => {
          const from = stateById(a.from);
          const to = stateById(a.to);
          if (!from || !to) return null;
          const [cx1, cy1] = centroid(from.points);
          const [cx2, cy2] = centroid(to.points);
          // 나라 이름을 가리지 않게 양 끝을 22%씩 줄이고, 위로 휘게 그린다
          const x1 = cx1 + (cx2 - cx1) * 0.22;
          const y1 = cy1 + (cy2 - cy1) * 0.22;
          const x2 = cx1 + (cx2 - cx1) * 0.78;
          const y2 = cy1 + (cy2 - cy1) * 0.78;
          const mx = (x1 + x2) / 2;
          const my = (y1 + y2) / 2 - Math.hypot(x2 - x1, y2 - y1) * 0.35;
          const len = Math.hypot(x2 - x1, y2 - y1) * 1.3;
          const start = 10 + states.length * 6 + i * 14;
          const draw = interpolate(frame, [start, start + 20], [len, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          return (
            <path
              key={`a-${i}`}
              d={`M${x1},${y1} Q${mx},${my} ${x2},${y2}`}
              fill="none"
              stroke={RED}
              strokeWidth={9}
              strokeLinecap="round"
              strokeDasharray={len}
              strokeDashoffset={draw}
              markerEnd={draw < len * 0.15 ? "url(#arrowhead)" : undefined}
            />
          );
        })}
      </svg>
      <div style={{ position: "absolute", top: 330 + MAP_VIEW.height * SCALE + 14, left: 90, right: 96, display: "flex", justifyContent: "space-between", opacity: enter }}>
        <span style={{ fontSize: 36, fontWeight: 800, color: "#d4af37" }}>{year}</span>
        <span style={{ fontSize: 26, color: "#8a7a5a", letterSpacing: "0.06em" }}>approximate borders</span>
      </div>
    </AbsoluteFill>
  );
};
