import React, { useEffect, useMemo } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { ThreeCanvas } from "@remotion/three";
import { useThree } from "@react-three/fiber";
import { riverZ } from "../FlyoverScene";
import { DEFAULT_SCENE3D, Environment3D, Scene3DSpec } from "./types";
import { Environment, Ground, TERRAIN_SCALE, toneExposure } from "./world";
import { SceneObject } from "./objects";

// 범용 3D 장면(scene3d) — 환경·바닥·카메라·물체를 조합해 그린다. 모든 움직임은 useCurrentFrame 기준.

// 금속·유리 재질이 비출 주변광: 원본 애드온 RoomEnvironment 를 PMREM 으로 구워 scene.environment 에 건다.
// 하늘·지형 장면에서 세게 걸면 지형이 허옇게 뜨므로 환경마다 세기를 다르게 준다.
const ENV_INTENSITY: Record<Environment3D, number> = { sky: 0.15, space: 0.6, studio: 1.0, dark: 0.5 };

const EnvMap: React.FC<{ env: Environment3D }> = ({ env }) => {
  const { gl, scene } = useThree();
  // 첫 프레임부터 반영되도록 렌더 중에 바로 건다 (useEffect 로 걸면 장면 첫 프레임의 금속·유리가 검게 나온다)
  const rt = useMemo(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const target = pmrem.fromScene(new RoomEnvironment(), 0.04);
    pmrem.dispose();
    return target;
  }, [gl]);
  scene.environment = rt.texture;
  scene.environmentIntensity = ENV_INTENSITY[env];
  useEffect(() => () => {
    scene.environment = null;
    rt.dispose();
  }, [scene, rt]);
  return null;
};

const CameraRig: React.FC<{ spec: Scene3DSpec; t: number; focusY: number; aspect: number }> = ({ spec, t, focusY, aspect }) => {
  const { camera } = useThree();
  const { move, height: h, sweep } = spec.camera;
  // 세로 화면은 가로 시야가 좁아 물체가 잘리므로 거리를 늘린다 (가로 화면 기준으로 쓴 거리를 그대로 써도 되게)
  const d = spec.camera.distance * (aspect < 1 ? 1 / Math.sqrt(aspect) : 1);
  const a0 = THREE.MathUtils.degToRad(20);
  if (move === "flyover") {
    // 지형과 같은 축척(1/100)으로 강을 따라 난다
    const along = interpolate(t, [0, 1], [-13, 9]);
    const z = (x: number) => riverZ(x / TERRAIN_SCALE, spec.seed) * TERRAIN_SCALE;
    camera.position.set(along, interpolate(t, [0, 1], [6.2, 4.3]), z(along) + interpolate(t, [0, 1], [3.2, 1.2]));
    camera.lookAt(along + 11, 0.2, z(along + 11));
    return null;
  }
  if (move === "dolly") {
    const dd = interpolate(t, [0, 1], [d * 1.35, d * 0.85]);
    camera.position.set(Math.sin(a0) * dd, h, Math.cos(a0) * dd);
  } else if (move === "pan") {
    const x = interpolate(t, [0, 1], [-d * 0.45, d * 0.45]);
    camera.position.set(x, h, d);
    camera.lookAt(x * 0.3, focusY, 0);
    return null;
  } else if (move === "static") {
    camera.position.set(Math.sin(a0) * d, h, Math.cos(a0) * d);
  } else {
    const a = a0 + THREE.MathUtils.degToRad(sweep * t);
    camera.position.set(Math.sin(a) * d, h, Math.cos(a) * d);
  }
  camera.lookAt(0, focusY, 0);
  return null;
};

export const Scene3D: React.FC<{ spec?: Scene3DSpec | null; durationInFrames: number; fontFamily: string }> = ({ spec, durationInFrames, fontFamily }) => {
  const s = spec || DEFAULT_SCENE3D;
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const t = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], { easing: Easing.inOut(Easing.cubic), extrapolateRight: "clamp" });
  const focusY = s.objects.some((o) => o.type === "bars") ? 1.2 : 0.6;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <ThreeCanvas
        width={width}
        height={height}
        camera={{ fov: 50, near: 0.1, far: 30000 }}
        gl={{ toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: toneExposure(s.environment, s.time_of_day) }}
      >
        <EnvMap env={s.environment} />
        <Environment env={s.environment} time={s.time_of_day} accent={s.accent} seed={s.seed} />
        <Ground ground={s.ground} env={s.environment} time={s.time_of_day} accent={s.accent} seed={s.seed} frame={frame} />
        {s.objects.map((o, i) => (
          <SceneObject key={i} obj={o} index={i} frame={frame} fps={fps} fontFamily={fontFamily} accent={s.accent} seed={s.seed} />
        ))}
        <CameraRig spec={s} t={t} focusY={focusY} aspect={width / height} />
      </ThreeCanvas>
    </AbsoluteFill>
  );
};
