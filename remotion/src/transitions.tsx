// 원인 있는 전환 4종 (U-3). HyperFrames skills/hyperframes/references/motion.md "Transitions with a cause" 의
// 수치를 Remotion TransitionPresentation 으로 다시 만든 것 (코드 이식 아님).
import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import type { TransitionPresentation, TransitionPresentationComponentProps } from "@remotion/transitions";

type Empty = Record<string, never>;
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// 줌스루: 나가는 씬이 블러와 함께 크게 밀려 들어가고, 들어오는 씬이 살짝 작은 데서 선명해지며 자리 잡는다
const ZoomThrough: React.FC<TransitionPresentationComponentProps<Empty>> = ({ children, presentationDirection, presentationProgress: p }) => {
  if (presentationDirection === "exiting") {
    return (
      <AbsoluteFill
        style={{
          transform: `scale(${interpolate(p, [0, 1], [1, 1.6], clamp)})`,
          filter: `blur(${interpolate(p, [0, 1], [0, 12], clamp)}px)`,
          opacity: interpolate(p, [0.4, 1], [1, 0], clamp),
        }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill
      style={{
        transform: `scale(${interpolate(p, [0, 1], [0.85, 1], clamp)})`,
        filter: `blur(${interpolate(p, [0, 1], [10, 0], clamp)}px)`,
        opacity: interpolate(p, [0, 0.5], [0, 1], clamp),
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

// 색 범람: 가운데서 색 원이 먼저 퍼지고, 그 뒤를 따라 다음 씬이 원 모양으로 드러난다
const ColorFlood: React.FC<TransitionPresentationComponentProps<{ color: string }>> = ({
  children,
  presentationDirection,
  presentationProgress: p,
  passedProps,
}) => {
  if (presentationDirection === "exiting") return <AbsoluteFill>{children}</AbsoluteFill>;
  const flood = interpolate(p, [0, 0.7], [0, 130], clamp);
  const reveal = interpolate(p, [0.3, 1], [0, 130], clamp);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ backgroundColor: passedProps.color, clipPath: `circle(${flood}% at 50% 50%)` }} />
      <AbsoluteFill style={{ clipPath: `circle(${reveal}% at 50% 50%)` }}>{children}</AbsoluteFill>
    </AbsoluteFill>
  );
};

// 휩: 화면 전체를 빠르게 밀어내고(나가는 씬 0 → -100%) 다음 씬이 반대편에서 밀려 들어온다. 번짐은 가운데서 가장 크고
// 착지 직전에 선명해진다. 두 씬이 항상 화면을 나눠 채워서 첫 프레임에 다음 씬이 확 덮이는 일이 없다
// (처음 버전은 들어오는 씬이 35% 지점에서 불투명하게 시작해 한 프레임에 화면 65% 가 바뀌었다 — U-4 seam_jump 로 발견)
const Whip: React.FC<TransitionPresentationComponentProps<{ direction: 1 | -1 }>> = ({
  children,
  presentationDirection,
  presentationProgress: p,
  passedProps,
}) => {
  const d = passedProps.direction;
  const eased = interpolate(p, [0, 1], [0, 1], { ...clamp, easing: (t) => t * t * (3 - 2 * t) });
  const blur = interpolate(p, [0, 0.5, 0.85, 1], [0, 18, 6, 0], clamp);
  const x = presentationDirection === "exiting" ? -100 * d * eased : 100 * d * (1 - eased);
  return <AbsoluteFill style={{ transform: `translateX(${x}%)`, filter: `blur(${blur}px)` }}>{children}</AbsoluteFill>;
};

// 딥컷: 나가는 씬이 40% 어두워진 뒤 바로 컷 — 의도한 컷으로 읽히게
const Dip: React.FC<TransitionPresentationComponentProps<Empty>> = ({ children, presentationDirection, presentationProgress: p }) => {
  if (presentationDirection === "exiting") {
    return <AbsoluteFill style={{ filter: `brightness(${interpolate(p, [0, 0.75], [1, 0.6], clamp)})` }}>{children}</AbsoluteFill>;
  }
  return <AbsoluteFill style={{ opacity: p >= 0.75 ? 1 : 0 }}>{children}</AbsoluteFill>;
};

export const zoomThrough = (): TransitionPresentation<Empty> => ({ component: ZoomThrough, props: {} as Empty });
export const colorFlood = (color: string): TransitionPresentation<{ color: string }> => ({ component: ColorFlood, props: { color } });
export const whip = (direction: 1 | -1): TransitionPresentation<{ direction: 1 | -1 }> => ({ component: Whip, props: { direction } });
export const dip = (): TransitionPresentation<Empty> => ({ component: Dip, props: {} as Empty });

// 전환별 길이(초). fade·slide·wipe 는 컴포지션의 transitionSeconds 를 쓴다
export const TRANSITION_SECONDS: Partial<Record<string, number>> = {
  zoom_through: 0.45,
  color_flood: 0.5,
  whip: 0.25,
  dip: 0.14,
  hero_flood: 0.35,
};
