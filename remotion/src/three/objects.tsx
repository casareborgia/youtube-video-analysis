import React, { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { continueRender, delayRender, random, spring, staticFile } from "remotion";
import { Object3D } from "./types";

// 한글 텍스트는 3D 글꼴 대신 캔버스에 Pretendard 로 그려 스프라이트로 띄운다(글꼴은 ShortsScene 이 먼저 불러 둔다)
const textTexture = (text: string, color: string, fontFamily: string, px = 160) => {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const font = `900 ${px}px ${fontFamily}`;
  ctx.font = font;
  const w = Math.max(8, Math.ceil(ctx.measureText(text).width + px * 0.6));
  const h = Math.ceil(px * 1.5);
  canvas.width = w;
  canvas.height = h;
  ctx.font = font;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.shadowColor = "rgba(0,0,0,0.65)";
  ctx.shadowBlur = px * 0.15;
  ctx.fillStyle = color;
  ctx.fillText(text, w / 2, h / 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return { tex, aspect: w / h };
};

export const TextSprite: React.FC<{ text: string; color: string; size: number; fontFamily: string; position?: [number, number, number] }> = ({
  text,
  color,
  size,
  fontFamily,
  position = [0, 0, 0],
}) => {
  const { tex, aspect } = useMemo(() => textTexture(text, color, fontFamily), [text, color, fontFamily]);
  return (
    <sprite position={position} scale={[size * aspect, size, 1]}>
      <spriteMaterial map={tex} transparent depthWrite={false} toneMapped={false} />
    </sprite>
  );
};

const geometryFor = (type: string) => {
  switch (type) {
    case "box":
      return <boxGeometry args={[1, 1, 1]} />;
    case "torus":
      return <torusGeometry args={[0.7, 0.25, 32, 96]} />;
    case "cone":
      return <coneGeometry args={[0.6, 1.2, 48]} />;
    case "cylinder":
      return <cylinderGeometry args={[0.5, 0.5, 1.2, 48]} />;
    case "icosahedron":
      return <icosahedronGeometry args={[0.7, 0]} />;
    default:
      return <sphereGeometry args={[0.6, 48, 32]} />;
  }
};

const materialFor = (material: string, color: string) => {
  switch (material) {
    case "metal":
      return <meshStandardMaterial color={color} metalness={1} roughness={0.22} />;
    case "glass":
      return <meshPhysicalMaterial color={color} transmission={1} thickness={0.6} roughness={0.05} ior={1.5} transparent />;
    case "emissive":
      return <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.2} />;
    default:
      return <meshStandardMaterial color={color} metalness={0.1} roughness={0.45} />;
  }
};

const Bars: React.FC<{ obj: Extract<Object3D, { type: "bars" }>; frame: number; fps: number; fontFamily: string; accent: string }> = ({
  obj,
  frame,
  fps,
  fontFamily,
  accent,
}) => {
  const max = Math.max(1e-6, ...obj.items.map((i) => Math.abs(i.value)));
  const w = 0.7;
  const gap = 0.35;
  const total = obj.items.length * w + (obj.items.length - 1) * gap;
  return (
    <group>
      {obj.items.map((it, i) => {
        const p = Math.max(0, spring({ frame: frame - 6 - i * 5, fps, config: { damping: 16 }, durationInFrames: 30 }));
        const h = Math.max(0.02, (Math.abs(it.value) / max) * 4 * p);
        const x = -total / 2 + w / 2 + i * (w + gap);
        const color = it.highlight ? accent : "#e5e7eb";
        const shown = Number.isInteger(it.value) ? Math.round(it.value * p).toString() : (it.value * p).toFixed(1);
        return (
          <group key={i} position={[x, 0, 0]}>
            <mesh position={[0, -0.5 + h / 2, 0]}>
              <boxGeometry args={[w, h, w]} />
              <meshStandardMaterial color={color} emissive={it.highlight ? accent : "#000000"} emissiveIntensity={it.highlight ? 0.45 : 0} roughness={0.35} />
            </mesh>
            <TextSprite text={it.label} color="#ffffff" size={0.32} fontFamily={fontFamily} position={[0, -0.85, 0.4]} />
            <TextSprite text={`${shown}${obj.unit}`} color={it.highlight ? accent : "#ffffff"} size={0.36} fontFamily={fontFamily} position={[0, -0.5 + h + 0.35, 0]} />
          </group>
        );
      })}
    </group>
  );
};

const latLon = (lat: number, lon: number, r: number) => {
  const phi = THREE.MathUtils.degToRad(90 - lat);
  const theta = THREE.MathUtils.degToRad(lon + 180);
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
};

const Globe: React.FC<{ obj: Extract<Object3D, { type: "globe" }>; frame: number; fps: number; fontFamily: string; accent: string }> = ({
  obj,
  frame,
  fps,
  fontFamily,
  accent,
}) => {
  const R = 2;
  const dots = useMemo(() => {
    // 피보나치 구면 점으로 그린 지구 (텍스처 파일 없이)
    const n = 1500;
    const pos: number[] = [];
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const th = golden * i;
      pos.push(Math.cos(th) * r * R, y * R, Math.sin(th) * r * R);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    return g;
  }, []);
  const arcs = useMemo(() => {
    if (!obj.arcs) return [];
    return obj.pins.slice(1).map((p, i) => {
      const a = latLon(obj.pins[i].lat, obj.pins[i].lon, R * 1.01);
      const b = latLon(p.lat, p.lon, R * 1.01);
      const mid = a.clone().add(b).multiplyScalar(0.5).normalize().multiplyScalar(R * (1.15 + a.distanceTo(b) * 0.12));
      return new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(a, mid, b), 64, 0.018, 6, false);
    });
  }, [obj.arcs, obj.pins]);
  // 첫 번째 핀이 카메라 쪽(+z)을 보도록 처음 각도를 맞춘다
  const first = obj.pins[0] ? latLon(obj.pins[0].lat, obj.pins[0].lon, 1) : null;
  const base = first ? -Math.atan2(first.x, first.z) : 0;
  const spin = (obj.spin || 8) * (frame / fps);
  return (
    <group rotation={[0.25, base + THREE.MathUtils.degToRad(spin), 0]}>
      <mesh>
        <sphereGeometry args={[R * 0.98, 64, 48]} />
        <meshStandardMaterial color="#0b1424" roughness={0.8} />
      </mesh>
      <points geometry={dots}>
        <pointsMaterial color={obj.color === accent ? "#9fb7d9" : obj.color} size={0.05} map={roundDot()} alphaTest={0.3} transparent />
      </points>
      <mesh>
        <sphereGeometry args={[R * 1.12, 64, 48]} />
        <meshBasicMaterial color={accent} transparent opacity={0.1} side={THREE.BackSide} blending={THREE.AdditiveBlending} />
      </mesh>
      {obj.pins.map((p, i) => {
        const pos = latLon(p.lat, p.lon, R * 1.02);
        const pulse = 1 + 0.5 * ((frame + i * 9) % 45) / 45;
        return (
          <group key={i}>
            <mesh position={pos}>
              <sphereGeometry args={[0.06, 16, 16]} />
              <meshBasicMaterial color={accent} toneMapped={false} />
            </mesh>
            <mesh position={pos} scale={pulse} onUpdate={(m) => m.lookAt(0, 0, 0)}>
              <ringGeometry args={[0.08, 0.11, 32]} />
              <meshBasicMaterial color={accent} transparent opacity={1.5 - pulse} side={THREE.DoubleSide} toneMapped={false} />
            </mesh>
            {p.label ? <TextSprite text={p.label} color="#ffffff" size={0.28} fontFamily={fontFamily} position={latLon(p.lat, p.lon, R * 1.25).toArray() as [number, number, number]} /> : null}
          </group>
        );
      })}
      {arcs.map((g, i) => {
        const p = Math.max(0, Math.min(1, spring({ frame: frame - 10 - i * 8, fps, config: { damping: 200 }, durationInFrames: 40 })));
        const count = g.index ? g.index.count : 0;
        g.setDrawRange(0, Math.floor((count * p) / 3) * 3);
        return (
          <mesh key={i} geometry={g}>
            <meshBasicMaterial color={accent} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
};

// 점을 네모 대신 둥글게 — 부드러운 원 텍스처
let dotTexture: THREE.CanvasTexture | null = null;
const roundDot = () => {
  if (dotTexture) return dotTexture;
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const ctx = c.getContext("2d") as CanvasRenderingContext2D;
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.5, "rgba(255,255,255,0.8)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  dotTexture = new THREE.CanvasTexture(c);
  return dotTexture;
};

const Particles: React.FC<{ obj: Extract<Object3D, { type: "particles" }>; frame: number; seed: number }> = ({ obj, frame, seed }) => {
  const geo = useMemo(() => {
    const pos: number[] = [];
    for (let i = 0; i < obj.count; i++) {
      pos.push(
        (random(`px-${seed}-${i}`) - 0.5) * obj.spread,
        (random(`py-${seed}-${i}`) - 0.5) * obj.spread * 0.6,
        (random(`pz-${seed}-${i}`) - 0.5) * obj.spread,
      );
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    return g;
  }, [obj.count, obj.spread, seed]);
  return (
    <points geometry={geo} rotation={[0, frame * 0.0025, 0]} position={[0, Math.sin(frame / 60) * 0.15, 0]}>
      <pointsMaterial color={obj.color} size={0.12} map={roundDot()} alphaTest={0.01} transparent opacity={0.9} depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
    </points>
  );
};

// glTF 모델: 잡 폴더(public/shorts/<id>/)의 파일을 불러와 3 단위 크기로 맞춘다. 불러올 때까지 렌더를 붙잡는다.
const Model: React.FC<{ src: string }> = ({ src }) => {
  const [scene, setScene] = useState<THREE.Object3D | null>(null);
  const [handle] = useState(() => delayRender(`3D 모델 불러오기: ${src}`));
  useEffect(() => {
    new GLTFLoader()
      .loadAsync(staticFile(src))
      .then((gltf) => {
        const obj = gltf.scene;
        const box = new THREE.Box3().setFromObject(obj);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const s = 3 / Math.max(size.x, size.y, size.z, 1e-6);
        obj.scale.setScalar(s);
        obj.position.set(-center.x * s, -center.y * s + 0.5, -center.z * s);
        setScene(obj);
        continueRender(handle);
      })
      .catch((err) => {
        // 모델 하나 때문에 영상 전체를 실패시키지 않는다
        console.warn(`3D 모델을 불러오지 못했습니다: ${src}`, err);
        continueRender(handle);
      });
  }, [src, handle]);
  return scene ? <primitive object={scene} /> : null;
};

export const SceneObject: React.FC<{ obj: Object3D; index: number; frame: number; fps: number; fontFamily: string; accent: string; seed: number }> = ({
  obj,
  index,
  frame,
  fps,
  fontFamily,
  accent,
  seed,
}) => {
  const enter = Math.max(0, Math.min(1, spring({ frame: frame - index * 4, fps, config: { damping: 18 }, durationInFrames: 20 })));
  const rotY = THREE.MathUtils.degToRad(obj.spin * (frame / fps));
  const bob = obj.type === "bars" || obj.type === "globe" || obj.type === "particles" ? 0 : Math.sin(frame / 40 + index) * 0.08;
  let body: React.ReactNode = null;
  switch (obj.type) {
    case "text":
      body = <TextSprite text={obj.text} color={obj.color} size={obj.size * 0.8} fontFamily={fontFamily} />;
      break;
    case "bars":
      body = <Bars obj={obj} frame={frame} fps={fps} fontFamily={fontFamily} accent={accent} />;
      break;
    case "globe":
      body = <Globe obj={obj} frame={frame} fps={fps} fontFamily={fontFamily} accent={accent} />;
      break;
    case "particles":
      body = <Particles obj={obj} frame={frame} seed={seed + index} />;
      break;
    case "model":
      body = <Model src={obj.src} />;
      break;
    default:
      body = (
        <mesh rotation={[0.3, 0, 0]}>
          {geometryFor(obj.type)}
          {materialFor(obj.material, obj.color)}
        </mesh>
      );
  }
  const [x, y, z] = obj.position;
  const [sx, sy, sz] = obj.scale;
  return (
    <group position={[x, y + bob, z]} rotation={[0, obj.type === "globe" ? 0 : rotY, 0]} scale={[sx * enter, sy * enter, sz * enter]}>
      {body}
    </group>
  );
};
