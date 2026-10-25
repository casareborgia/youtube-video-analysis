import React, { useMemo } from "react";
import * as THREE from "three";
import { random } from "remotion";
import { LOOKS, Look, SIZE, SkyDome, makeRiver, makeTerrain } from "../FlyoverScene";
import { Environment3D, Ground3D, Time3D } from "./types";

// 지형(6000 단위)을 물체 크기(수 단위)에 맞추는 비율 — 지형 1/100 축소
export const TERRAIN_SCALE = 0.01;

const NIGHT: Look = { elevation: -8, turbidity: 2, rayleigh: 0.4, exposure: 0.9, fog: "#0b1430", sun: "#9db4ff", ground: "#101527", water: "#24406e", hue: 0.62 };

export const lookFor = (time: Time3D): Look => (time === "night" ? NIGHT : LOOKS[time]);

// 해는 카메라 진행 방향(+x, 방위각 π/2)의 옆에 둔다 — 정면이면 하늘이 하얗게 날아간다
const SUN_AZIMUTH = Math.PI / 2 + Math.PI * 0.4;

const Stars: React.FC<{ seed: number; count?: number }> = ({ seed, count = 1800 }) => {
  const geo = useMemo(() => {
    const pos: number[] = [];
    for (let i = 0; i < count; i++) {
      const u = random(`star-u-${seed}-${i}`) * 2 - 1;
      const th = random(`star-t-${seed}-${i}`) * Math.PI * 2;
      const r = 400 + random(`star-r-${seed}-${i}`) * 200;
      const s = Math.sqrt(1 - u * u);
      pos.push(r * s * Math.cos(th), r * u, r * s * Math.sin(th));
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    return g;
  }, [seed, count]);
  return (
    <points geometry={geo}>
      <pointsMaterial color="#ffffff" size={1.6} sizeAttenuation={false} transparent opacity={0.85} />
    </points>
  );
};

export const toneExposure = (env: Environment3D, time: Time3D) => (env === "sky" ? lookFor(time).exposure : 1.0);

// 환경: 배경·하늘·조명·안개
export const Environment: React.FC<{ env: Environment3D; time: Time3D; accent: string; seed: number }> = ({ env, time, accent, seed }) => {
  if (env === "sky") {
    const look = lookFor(time);
    const sunDir = new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - Math.max(look.elevation, 2)), SUN_AZIMUTH);
    return (
      <>
        {time === "night" ? (
          <>
            <color attach="background" args={["#060a1c"]} />
            <Stars seed={seed} />
          </>
        ) : (
          <SkyDome look={look} azimuth={SUN_AZIMUTH} />
        )}
        <fog attach="fog" args={[look.fog, 14, 62]} />
        <hemisphereLight args={[look.sun, look.ground, time === "night" ? 0.5 : 1.3]} />
        <directionalLight position={[sunDir.x * 30, sunDir.y * 30 + 9, sunDir.z * 30]} intensity={time === "night" ? 0.8 : 2.6} color={look.sun} />
      </>
    );
  }
  if (env === "space") {
    return (
      <>
        <color attach="background" args={["#03040a"]} />
        <Stars seed={seed} />
        <ambientLight intensity={0.35} />
        <directionalLight position={[6, 4, 5]} intensity={2.2} color="#ffffff" />
        <pointLight position={[-6, -2, 4]} intensity={30} color={accent} distance={30} />
      </>
    );
  }
  if (env === "dark") {
    return (
      <>
        <color attach="background" args={["#05060a"]} />
        <fog attach="fog" args={["#05060a", 10, 40]} />
        <ambientLight intensity={0.25} />
        <pointLight position={[0, 6, 4]} intensity={60} color={accent} distance={40} />
        <pointLight position={[-5, 3, -4]} intensity={25} color="#7c8cff" distance={30} />
        <directionalLight position={[3, 8, 6]} intensity={0.8} />
      </>
    );
  }
  // studio: 3점 조명
  return (
    <>
      <color attach="background" args={["#1a1d26"]} />
      <fog attach="fog" args={["#1a1d26", 14, 45]} />
      <ambientLight intensity={0.35} />
      <spotLight position={[5, 9, 6]} angle={0.5} penumbra={0.6} intensity={180} color="#fff4e6" />
      <directionalLight position={[-6, 4, 3]} intensity={0.9} color="#a9c1ff" />
      <pointLight position={[0, 3, -6]} intensity={40} color={accent} distance={25} />
    </>
  );
};

const Terrain: React.FC<{ seed: number; time: Time3D }> = ({ seed, time }) => {
  const look = lookFor(time);
  const terrain = useMemo(() => makeTerrain(seed, look.hue), [seed, look.hue]);
  const river = useMemo(() => makeRiver(seed), [seed]);
  return (
    <group scale={TERRAIN_SCALE}>
      <mesh geometry={terrain}>
        <meshStandardMaterial vertexColors roughness={0.95} />
      </mesh>
      <mesh geometry={river}>
        <meshStandardMaterial color={look.water} roughness={0.3} metalness={0} emissive={look.water} emissiveIntensity={0.2} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
};

// 물결: 매 프레임 정점 높이를 사인 합으로 다시 계산한다(프레임 번호만으로 정해져 렌더마다 같다)
const Water: React.FC<{ frame: number; color: string }> = ({ frame, color }) => {
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(80, 80, 120, 120);
    g.rotateX(-Math.PI / 2);
    return g;
  }, []);
  const pos = geo.attributes.position as THREE.BufferAttribute;
  const t = frame / 30;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const z = pos.getZ(i);
    pos.setY(i, 0.18 * Math.sin(x * 0.6 + t * 1.4) + 0.12 * Math.sin(z * 0.9 - t * 1.1) + 0.06 * Math.sin((x + z) * 1.7 + t * 2.3));
  }
  pos.needsUpdate = true;
  geo.computeVertexNormals();
  return (
    <mesh geometry={geo} position={[0, -0.6, 0]}>
      <meshStandardMaterial color={color} roughness={0.25} metalness={0.1} emissive={color} emissiveIntensity={0.12} />
    </mesh>
  );
};

const Grid: React.FC<{ accent: string }> = ({ accent }) => {
  const grid = useMemo(() => {
    const g = new THREE.GridHelper(120, 120, accent, accent);
    const m = g.material as THREE.Material;
    m.transparent = true;
    m.opacity = 0.45;
    return g;
  }, [accent]);
  return <primitive object={grid} position={[0, -0.5, 0]} />;
};

const Floor: React.FC<{ env: Environment3D }> = ({ env }) => (
  <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.5, 0]}>
    <planeGeometry args={[200, 200]} />
    <meshStandardMaterial color={env === "studio" ? "#2a2f3a" : "#14161c"} roughness={0.55} metalness={0.25} />
  </mesh>
);

export const Ground: React.FC<{ ground: Ground3D; env: Environment3D; time: Time3D; accent: string; seed: number; frame: number }> = ({
  ground,
  env,
  time,
  accent,
  seed,
  frame,
}) => {
  if (ground === "terrain") return <Terrain seed={seed} time={time} />;
  if (ground === "water") return <Water frame={frame} color={env === "sky" ? lookFor(time).water : "#1f4e7a"} />;
  if (ground === "grid") return <Grid accent={accent} />;
  if (ground === "floor") return <Floor env={env} />;
  return null;
};

// flyover 카메라가 지형과 같은 축척으로 강을 따라가도록 내보낸다
export const terrainSize = SIZE * TERRAIN_SCALE;
