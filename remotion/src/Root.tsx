import React from "react";
import { Composition } from "remotion";
import { LunaBga, LunaBgaProps } from "./LunaBga";
import {
  ShortsScene,
  ShortsSceneProps,
  SHORTS_FPS,
  SHORTS_HEIGHT,
  SHORTS_WIDTH,
  totalSecondsOf,
} from "./ShortsScene";

const defaultProps: LunaBgaProps = {
  trackId: "luna_demo",
  loopUnit: "luna/luna_demo/bga/loop_unit.mp4",
  loopUnitSeconds: 22.0,
  audio: "luna/luna_demo/audio.mp3",
  durationSeconds: 180.0,
  title: "루나의 심야 서재 BGA",
  subtitle: "Midnight Chill & Synthwave BGM",
  accent: "#a5b4fc",
  spectrum: true,
};

const shortsDefaultProps: ShortsSceneProps = {
  jobId: "shorts_demo",
  scenes: [
    { image: "shorts/shorts_demo/scene_01.png", seconds: 6, motion: "zoom_in" },
    { image: "shorts/shorts_demo/scene_02.png", seconds: 6, motion: "pan_left" },
    { image: "shorts/shorts_demo/scene_03.png", seconds: 6, motion: "zoom_out" },
  ],
  hookText: "이거 모르면 손해봅니다",
  hookSeconds: 3,
  endTag: { text: "구독하고 다음 편 보기", subtext: "매일 1편, 60초 지식", seconds: 2 },
  captions: [],
  narrationAudio: "shorts/shorts_demo/narration.mp3",
  bgmAudio: null,
  bgmVolume: 0.16,
  accent: "#ffd166",
  brand: "SHORTS LAB",
  transitionSeconds: 0.4,
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="LunaBga"
        component={LunaBga}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={defaultProps}
        calculateMetadata={async ({ props }) => {
          const durSec = Number(props.durationSeconds) || 180.0;
          return {
            durationInFrames: Math.max(1, Math.round(durSec * 30)),
            fps: 30,
            width: 1920,
            height: 1080,
            props,
          };
        }}
      />
      <Composition
        id="ShortsScene"
        component={ShortsScene}
        fps={SHORTS_FPS}
        width={SHORTS_WIDTH}
        height={SHORTS_HEIGHT}
        defaultProps={shortsDefaultProps}
        calculateMetadata={async ({ props }) => {
          const total = totalSecondsOf(props);
          return {
            durationInFrames: Math.max(1, Math.round(total * SHORTS_FPS)),
            fps: SHORTS_FPS,
            width: SHORTS_WIDTH,
            height: SHORTS_HEIGHT,
            props,
          };
        }}
      />
    </>
  );
};
