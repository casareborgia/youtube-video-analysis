import React, { useEffect, useMemo, useState } from "react";
import { AbsoluteFill, continueRender, delayRender, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";
import { fitTextOnNLines } from "@remotion/layout-utils";

// 원문 인장 씬(seal): 책 인장 → 한자 원문을 세로로 한 자씩 → 자체 영어 번역 → 출전.
// 한자 글꼴: Noto Serif TC 900 부분 글꼴(OFL, scripts/build_seal_font.py). 글꼴에 없는 글자는 shorts_review 가 P0 로 막는다.
// 등장 프레임 수는 shorts_review.SEAL_STAMP_FRAMES·SEAL_CHAR_FRAMES 와 맞춘다.
export const SEAL_STAMP_FRAMES = 14;
export const SEAL_CHAR_FRAMES = 4;
const SEAL_FONT = "NotoSerifTCSeal";
const SEAL_RED = "#b3261e";
const PAPER = "#efe6d2";
const sealFontReady = loadFont({ family: SEAL_FONT, url: staticFile("fonts/NotoSerifTC-Seal.woff2"), weight: "900", format: "woff2" });

// 출전 책 → 인장 글자
const BOOK_GLYPH: [RegExp, string][] = [
  [/^shiji/i, "史"],
  [/^zhanguo/i, "策"],
  [/^han\s*feizi/i, "韓"],
  [/^sunzi|^sun\s*tzu/i, "孫"],
];
const bookGlyph = (source?: string) => BOOK_GLYPH.find(([re]) => re.test((source || "").trim()))?.[1] || "史";

const isMark = (c: string) => !/[\p{L}\p{N}]/u.test(c);

// 세로 단 나누기: 문장부호에서 구절을 끊고(부호는 찍지 않는다 — 인장에는 표점이 없다), 구절이 4자를 넘으면 고르게 나눈다.
// 예) 將在軍，君命有所不受 → [將在軍][君命有][所不受], 此奇貨可居 → [此奇貨][可居]
export const SEAL_COLUMN_MAX = 4;
export const sealColumns = (hanzi: string): string[][] => {
  const cols: string[][] = [];
  const phrases = Array.from(hanzi)
    .reduce<string[][]>(
      (acc, c) => {
        if (isMark(c)) acc.push([]);
        else acc[acc.length - 1].push(c);
        return acc;
      },
      [[]],
    )
    .filter((p) => p.length);
  for (const p of phrases) {
    const k = Math.ceil(p.length / SEAL_COLUMN_MAX);
    const base = Math.floor(p.length / k);
    let extra = p.length % k;
    let at = 0;
    for (let i = 0; i < k; i++) {
      const n = base + (extra > 0 ? 1 : 0);
      extra -= 1;
      cols.push(p.slice(at, at + n));
      at += n;
    }
  }
  return cols;
};
const HANZI_TOP = 390;
const HANZI_HEIGHT = 580; // 번역(1010px~)과 겹치지 않는 높이
const HANZI_WIDTH = 880;

export const SealScene: React.FC<{
  hanzi?: string;
  translation?: string;
  source?: string;
  contentFrames: number;
  fontFamily: string;
  latinFont: string;
}> = ({ hanzi = "", translation = "", source = "", contentFrames, fontFamily, latinFont }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const [ready, setReady] = useState(false);
  const [handle] = useState(() => delayRender("인장 글꼴 대기"));
  useEffect(() => {
    sealFontReady.then(() => {
      setReady(true);
      continueRender(handle);
    });
  }, [handle]);

  const columns = useMemo(() => sealColumns(hanzi), [hanzi]);
  const letters = columns.reduce((a, c) => a + c.length, 0);
  const longest = Math.max(1, ...columns.map((c) => c.length));
  const size = Math.floor(Math.min(140, HANZI_HEIGHT / (longest * 1.08), HANZI_WIDTH / (Math.max(1, columns.length) * 1.3)));

  const stamp = spring({ frame, fps, config: { damping: 11, stiffness: 180 }, durationInFrames: SEAL_STAMP_FRAMES });
  const textStart = SEAL_STAMP_FRAMES + letters * SEAL_CHAR_FRAMES;
  const trans = spring({ frame: frame - textStart, fps, config: { damping: 200 }, durationInFrames: 12 });
  const fadeOut = interpolate(frame, [contentFrames - 8, contentFrames + 4], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const transSize = useMemo(() => {
    const t = translation.trim();
    if (!t || !ready) return 50;
    try {
      const { fontSize } = fitTextOnNLines({ text: t, maxLines: 3, maxBoxWidth: 880, fontFamily: latinFont, fontWeight: 600, maxFontSize: 54 });
      return Math.max(36, Math.floor(fontSize));
    } catch {
      return 44;
    }
  }, [translation, ready, latinFont]);

  if (!ready) return <AbsoluteFill style={{ backgroundColor: "#0e0c0a" }} />;

  let letterIndex = -1;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #2a241c 0%, #14110d 62%, #0a0907 100%)", opacity: fadeOut }}>
      {/* 책 인장 */}
      <div
        style={{
          position: "absolute",
          top: 210,
          left: (1080 - 132) / 2,
          width: 132,
          height: 132,
          borderRadius: 10,
          backgroundColor: SEAL_RED,
          boxShadow: `inset 0 0 0 7px ${SEAL_RED}, inset 0 0 0 11px ${PAPER}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: `${SEAL_FONT}, serif`,
          fontSize: 92,
          color: PAPER,
          transform: `scale(${interpolate(stamp, [0, 1], [1.8, 1])}) rotate(${interpolate(stamp, [0, 1], [-8, -3])}deg)`,
          opacity: interpolate(stamp, [0, 0.25, 1], [0, 1, 1]),
        }}
      >
        {bookGlyph(source)}
      </div>

      {/* 원문 — 세로 단, 오른쪽 단부터 읽는다 */}
      <div
        style={{
          position: "absolute",
          top: HANZI_TOP,
          left: (1080 - HANZI_WIDTH) / 2,
          width: HANZI_WIDTH,
          height: HANZI_HEIGHT,
          display: "flex",
          flexDirection: "row-reverse",
          justifyContent: "center",
          alignItems: "flex-start",
          gap: size * 0.3,
          fontFamily: `${SEAL_FONT}, serif`,
          fontSize: size,
          lineHeight: 1.08,
          color: PAPER,
          textShadow: "0 6px 24px rgba(0,0,0,0.6)",
        }}
      >
        {columns.map((col, ci) => (
          <div key={ci} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            {col.map((c, i) => {
              letterIndex += 1;
              const at = SEAL_STAMP_FRAMES + letterIndex * SEAL_CHAR_FRAMES;
              const o = interpolate(frame, [at, at + 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              return (
                <span key={i} style={{ opacity: o, transform: `translateY(${interpolate(o, [0, 1], [-12, 0])}px)` }}>
                  {c}
                </span>
              );
            })}
          </div>
        ))}
      </div>

      {/* 자체 번역 + 출전 */}
      <div style={{ position: "absolute", top: 1010, left: 100, right: 100, textAlign: "center", opacity: trans }}>
        <div style={{ fontFamily: latinFont, fontWeight: 600, fontSize: transSize, lineHeight: 1.22, color: "#f5efe2" }}>
          {translation ? `“${translation}”` : ""}
        </div>
        {source ? (
          <div style={{ marginTop: 18, fontFamily, fontWeight: 700, fontSize: 34, letterSpacing: "0.08em", color: "#d4af37" }}>
            — {source}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
