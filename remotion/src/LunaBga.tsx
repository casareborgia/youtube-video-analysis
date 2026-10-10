import React from "react";
import {
  Audio,
  interpolate,
  Loop,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useAudioData, visualizeAudio } from "@remotion/media-utils";
import { loadFont } from "@remotion/google-fonts/NotoSansKR";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "600", "700"],
  subsets: ["korean", "latin"],
  ignoreTooManyRequestsWarning: true,
});

export type LunaBgaProps = {
  trackId: string;
  loopUnit: string;
  loopUnitSeconds: number;
  audio: string;
  durationSeconds: number;
  title: string;
  subtitle: string;
  accent?: string;
  spectrum?: boolean;
};

export const LunaBga: React.FC<LunaBgaProps> = ({
  loopUnit,
  loopUnitSeconds = 22.0,
  audio,
  title,
  subtitle,
  accent = "#a5b4fc",
  spectrum = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // 페이드인 2초(60프레임), 페이드아웃 3초(90프레임)
  const fadeIn = interpolate(frame, [0, 60], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    frame,
    [Math.max(0, durationInFrames - 90), durationInFrames],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }
  );
  const containerOpacity = fadeIn * fadeOut;

  // 오디오 데이터 시각화
  const audioSrc = staticFile(audio);
  const audioData = useAudioData(audioSrc);

  // visualizeAudio 는 선형 주파수 빈을 돌려줘 저역(왼쪽 몇 개)에 에너지가 몰린다.
  // 256빈을 뽑아 로그 간격으로 48개 막대에 재배분하고, 각 구간은 최대값을 취한다.
  const BAR_COUNT = 48;
  let visualization: number[] = [];
  if (spectrum && audioData) {
    const rawVisual = visualizeAudio({
      audioData,
      frame,
      fps,
      numberOfSamples: 256,
      optimizeFor: "speed",
    });
    const minBin = 2; // DC·초저역 제외
    const maxBin = rawVisual.length - 1;
    const ratio = Math.log(maxBin / minBin) / BAR_COUNT;
    for (let i = 0; i < BAR_COUNT; i++) {
      const lo = Math.floor(minBin * Math.exp(ratio * i));
      const hi = Math.max(lo + 1, Math.floor(minBin * Math.exp(ratio * (i + 1))));
      let peak = 0;
      for (let b = lo; b < Math.min(hi, rawVisual.length); b++) {
        peak = Math.max(peak, rawVisual[b]);
      }
      // 선형 진폭은 고역이 1e-3 수준이라 그대로 그리면 바닥에 붙는다 → dB 스케일(-60~0 dB → 0~1)
      const db = 20 * Math.log10(Math.max(peak, 1e-6));
      visualization.push(Math.min(1, Math.max(0, (db + 60) / 60)));
    }
  }

  const loopFrames = Math.max(1, Math.round(loopUnitSeconds * fps));

  return (
    <div
      style={{
        width: 1920,
        height: 1080,
        backgroundColor: "#000",
        position: "relative",
        overflow: "hidden",
        fontFamily,
        opacity: containerOpacity,
      }}
    >
      {/* 1. 배경 루프 비디오 */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
        }}
      >
        <Loop durationInFrames={loopFrames}>
          <OffthreadVideo
            src={staticFile(loopUnit)}
            muted
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
            }}
          />
        </Loop>
      </div>

      {/* 배경 살짝 어둡게 오버레이 (가독성 향상) */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          backgroundColor: "rgba(0, 0, 0, 0.25)",
        }}
      />

      {/* 2. 오디오 트랙 */}
      <Audio src={audioSrc} />

      {/* 3. 상단 타이포그래피 */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: 0,
          width: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          textShadow: "0 2px 10px rgba(0, 0, 0, 0.8), 0 4px 20px rgba(0, 0, 0, 0.6)",
        }}
      >
        <div
          style={{
            fontSize: 22,
            letterSpacing: "0.25em",
            fontWeight: 600,
            color: "rgba(255, 255, 255, 0.9)",
            marginBottom: 12,
            textTransform: "uppercase",
          }}
        >
          AGENT LUNA
        </div>
        <div
          style={{
            fontSize: 48,
            fontWeight: 700,
            color: accent,
            letterSpacing: "0.02em",
            marginBottom: 8,
            maxWidth: 1600,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontSize: 24,
            fontWeight: 400,
            color: "rgba(220, 225, 235, 0.85)",
            letterSpacing: "0.05em",
          }}
        >
          {subtitle}
        </div>
      </div>

      {/* 4. 하단 오디오 스펙트럼 */}
      {spectrum && visualization.length > 0 && (
        <div
          style={{
            position: "absolute",
            bottom: 60,
            left: 200,
            right: 200,
            height: 180,
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            gap: 6,
          }}
        >
          {visualization.map((val, idx) => {
            const barHeight = Math.min(180, Math.max(4, val * 180));
            return (
              <div
                key={idx}
                style={{
                  flex: 1,
                  height: barHeight,
                  backgroundColor: accent,
                  opacity: 0.75,
                  borderRadius: "3px 3px 0 0",
                  boxShadow: `0 0 10px ${accent}66`,
                }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};
