import React, { useMemo } from "react";
import * as THREE from "three";
import { ImprovedNoise } from "three/examples/jsm/math/ImprovedNoise.js";
import { Sky } from "three/examples/jsm/objects/Sky.js";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { ThreeCanvas } from "@remotion/three";
import { useThree } from "@react-three/fiber";

// 3D 항공(flyover) 씬 — 원본 three.js 애드온(ImprovedNoise 지형 · Sky 하늘)으로 그리는 비용 0 씬.
// 모든 움직임은 useCurrentFrame 으로 계산한다(useFrame·Clock 같은 실시간 시계를 쓰면 렌더마다 결과가 달라진다).

export type FlyoverTime = "sunrise" | "day" | "sunset";

export type Look = {
  elevation: number; // 해 높이(도)
  turbidity: number;
  rayleigh: number;
  exposure: number;
  fog: string;
  sun: string;
  ground: string;
  water: string;
  hue: number; // 지형 색상(HSL hue) 기준
};

export const LOOKS: Record<FlyoverTime, Look> = {
  sunrise: { elevation: 6, turbidity: 7, rayleigh: 2.6, exposure: 0.75, fog: "#f1bf93", sun: "#ffcf9e", ground: "#5a5470", water: "#4f7fb8", hue: 0.24 },
  day: { elevation: 38, turbidity: 2.2, rayleigh: 1.8, exposure: 0.55, fog: "#c3daef", sun: "#fff6e6", ground: "#4f5f70", water: "#4f8fca", hue: 0.27 },
  sunset: { elevation: 7, turbidity: 6, rayleigh: 2.2, exposure: 0.75, fog: "#f0a46e", sun: "#ffb370", ground: "#544a5e", water: "#476fa6", hue: 0.22 },
};

export const SIZE = 6000;
const SEG = 160;
const RIVER_HALF = 150; // 강 반폭
// 강 중심선(z)이 x 를 따라 굽이친다 — 지형 골짜기·강물·카메라가 모두 이 곡선을 따른다
export const riverZ = (x: number, seed: number) => 260 * Math.sin(x / 760 + seed) + 90 * Math.sin(x / 290 + seed * 2.1);

// webgl_geometry_terrain 예제처럼 옥타브를 겹친 펄린 노이즈. seed 로 노이즈 단면을 바꿔 씬마다 다른 지형을 만든다.
export const makeTerrain = (seed: number, hue: number) => {
  // seed 는 노이즈 단면과 강 굽이를 함께 바꾼다
  const noise = new ImprovedNoise();
  const n = SEG + 1;
  const data = new Float32Array(n * n);
  const zSlice = 1.7 + seed * 3.13;
  let quality = 1;
  for (let o = 0; o < 4; o++) {
    for (let i = 0; i < n * n; i++) {
      data[i] += Math.abs(noise.noise((i % n) / quality, Math.floor(i / n) / quality, zSlice) * quality * 1.6);
    }
    quality *= 4;
  }
  const g = new THREE.PlaneGeometry(SIZE, SIZE, SEG, SEG);
  g.rotateX(-Math.PI / 2);
  const pos = g.attributes.position;
  const colors: number[] = [];
  const c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    // 강가에서 산으로 완만하게 올라가도록 smoothstep (절벽처럼 솟지 않게)
    const d = Math.abs(pos.getZ(i) - riverZ(pos.getX(i), seed));
    const v = Math.min(1, Math.max(0, (d - RIVER_HALF * 1.1) / (RIVER_HALF * 4)));
    const valley = v * v * (3 - 2 * v);
    const h = data[i] * 2.1 * valley;
    pos.setY(i, h);
    const k = Math.min(h, 320) / 320;
    c.setHSL(hue - k * 0.12, 0.38 + k * 0.1, 0.2 + k * 0.28);
    colors.push(c.r, c.g, c.b);
  }
  g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  g.computeVertexNormals();
  return g;
};

// 강물: 중심선을 따라가는 리본 메시
export const makeRiver = (seed: number) => {
  const steps = 240;
  const verts: number[] = [];
  const idx: number[] = [];
  for (let k = 0; k <= steps; k++) {
    const x = -SIZE / 2 + (SIZE * k) / steps;
    const z = riverZ(x, seed);
    const wobble = 1 + 0.25 * Math.sin(x / 180 + seed);
    verts.push(x, 6, z - RIVER_HALF * wobble, x, 6, z + RIVER_HALF * wobble);
    if (k < steps) {
      const a = k * 2;
      idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
};

const River: React.FC<{ seed: number; color: string }> = ({ seed, color }) => {
  const geo = useMemo(() => makeRiver(seed), [seed]);
  return (
    <mesh geometry={geo}>
      {/* 비출 환경맵이 없으면 금속 재질은 검게 나오므로 비금속 + 약한 자체광으로 물빛을 낸다 */}
      <meshStandardMaterial color={color} roughness={0.3} metalness={0} emissive={color} emissiveIntensity={0.2} side={THREE.DoubleSide} />
    </mesh>
  );
};

const Terrain: React.FC<{ seed: number; hue: number }> = ({ seed, hue }) => {
  const geo = useMemo(() => makeTerrain(seed, hue), [seed, hue]);
  return (
    <mesh geometry={geo}>
      <meshStandardMaterial vertexColors roughness={0.95} />
    </mesh>
  );
};

export const SkyDome: React.FC<{ look: Look; azimuth: number }> = ({ look, azimuth }) => {
  const sky = useMemo(() => {
    const s = new Sky();
    s.scale.setScalar(20000);
    return s;
  }, []);
  const u = sky.material.uniforms;
  u.turbidity.value = look.turbidity;
  u.rayleigh.value = look.rayleigh;
  u.mieCoefficient.value = 0.004;
  u.mieDirectionalG.value = 0.82;
  u.sunPosition.value.setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - look.elevation), azimuth);
  return <primitive object={sky} />;
};

// 카메라: 강(+x 방향)을 따라 낮게 미끄러지듯 난다. side(+1/-1)로 강의 어느 쪽 둑 위를 날지 정한다.
const Camera: React.FC<{ t: number; side: number; seed: number }> = ({ t, side, seed }) => {
  const { camera } = useThree();
  const along = interpolate(t, [0, 1], [-1300, 900]);
  const offset = interpolate(t, [0, 1], [320, 120]) * side;
  camera.position.set(along, interpolate(t, [0, 1], [620, 430]), riverZ(along, seed) + offset);
  const ahead = along + 1100;
  camera.lookAt(ahead, 20, riverZ(ahead, seed));
  return null;
};

const PlaceLabel: React.FC<{ text: string; contentFrames: number; fontFamily: string; top: number }> = ({ text, contentFrames, fontFamily, top }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame: frame - 6, fps, config: { damping: 18 }, durationInFrames: 16 });
  const exit = interpolate(frame, [contentFrames - 8, contentFrames + 4], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ alignItems: "center", opacity: Math.max(0, enter) * exit }}>
      <div
        style={{
          marginTop: top,
          padding: "14px 30px",
          borderRadius: 999,
          backgroundColor: "rgba(10,12,18,0.55)",
          color: "white",
          fontFamily,
          fontSize: 44,
          fontWeight: 800,
          letterSpacing: "0.02em",
          transform: `translateY(${interpolate(Math.max(0, enter), [0, 1], [18, 0])}px)`,
          boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
        }}
      >
        📍 {text}
      </div>
    </AbsoluteFill>
  );
};

export const FlyoverScene: React.FC<{
  title?: string;
  timeOfDay?: FlyoverTime;
  seed?: number;
  durationInFrames: number;
  contentFrames: number;
  fontFamily: string;
  labelTop: number;
}> = ({ title, timeOfDay = "sunset", seed = 1, durationInFrames, contentFrames, fontFamily, labelTop }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const look = LOOKS[timeOfDay] || LOOKS.sunset;
  const t = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {
    easing: Easing.inOut(Easing.cubic),
    extrapolateRight: "clamp",
  });
  const side = seed % 2 === 0 ? -1 : 1;
  // 해는 진행 방향(+x, 방위각 π/2)의 옆(약 70°)에 둔다 — 정면이면 하늘이 하얗게 날아가고, 뒤면 정면 하늘이 탁해진다
  const sunAzimuth = Math.PI / 2 + Math.PI * 0.4 * side;
  const sunDir = new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - look.elevation), sunAzimuth);
  return (
    <AbsoluteFill style={{ backgroundColor: look.fog }}>
      <ThreeCanvas
        width={width}
        height={height}
        camera={{ fov: 55, near: 1, far: 30000 }}
        gl={{ toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: look.exposure }}
      >
        <SkyDome look={look} azimuth={sunAzimuth} />
        <fog attach="fog" args={[look.fog, 1400, 6200]} />
        <hemisphereLight args={[look.sun, look.ground, 1.3]} />
        <directionalLight position={[sunDir.x * 3000, sunDir.y * 3000 + 900, sunDir.z * 3000]} intensity={2.6} color={look.sun} />
        <Camera t={t} side={side} seed={seed} />
        <Terrain seed={seed} hue={look.hue} />
        <River seed={seed} color={look.water} />
      </ThreeCanvas>
      {title ? <PlaceLabel text={title} contentFrames={contentFrames} fontFamily={fontFamily} top={labelTop} /> : null}
    </AbsoluteFill>
  );
};
