import React from "react";
import { Composition } from "remotion";
import { LunaBga, LunaBgaProps } from "./LunaBga";

const defaultProps: LunaBgaProps = {
  trackId: "luna_demo",
  loopUnit: "luna/luna_demo/bga/loop_unit.mp4",
  loopUnitSeconds: 22.0,
  audio: "luna/luna_demo/audio.mp3",
  durationSeconds: 180.0,
  title: "Agent Luna BGA",
  subtitle: "Midnight Chill & Synthwave BGM",
  accent: "#a5b4fc",
  spectrum: true,
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
    </>
  );
};
