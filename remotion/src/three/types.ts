// 범용 3D 장면(scene3d) 설명 — Python scene3d_spec.normalize_scene3d 가 정리해서 넘긴다.

export type Environment3D = "sky" | "space" | "studio" | "dark";
export type Ground3D = "terrain" | "water" | "grid" | "floor" | "none";
export type Time3D = "sunrise" | "day" | "sunset" | "night";
export type CameraMove3D = "orbit" | "dolly" | "flyover" | "pan" | "static";
export type Material3D = "standard" | "metal" | "glass" | "emissive";
export type Primitive3D = "box" | "sphere" | "torus" | "cone" | "cylinder" | "icosahedron";

type Vec3 = [number, number, number];

type ObjectBase = {
  position: Vec3;
  scale: Vec3;
  spin: number; // 초당 회전(도)
  color: string;
};

export type Object3D =
  | (ObjectBase & { type: Primitive3D; material: Material3D })
  | (ObjectBase & { type: "text"; text: string; size: number })
  | (ObjectBase & { type: "bars"; items: { label: string; value: number; highlight: boolean }[]; unit: string })
  | (ObjectBase & { type: "globe"; pins: { lat: number; lon: number; label: string }[]; arcs: boolean })
  | (ObjectBase & { type: "particles"; count: number; spread: number })
  | (ObjectBase & { type: "model"; src: string });

export type Scene3DSpec = {
  environment: Environment3D;
  ground: Ground3D;
  time_of_day: Time3D;
  camera: { move: CameraMove3D; distance: number; height: number; sweep: number };
  accent: string;
  seed: number;
  objects: Object3D[];
};

export const DEFAULT_SCENE3D: Scene3DSpec = {
  environment: "studio",
  ground: "floor",
  time_of_day: "sunset",
  camera: { move: "orbit", distance: 8, height: 2.5, sweep: 40 },
  accent: "#ffd166",
  seed: 1,
  objects: [],
};
