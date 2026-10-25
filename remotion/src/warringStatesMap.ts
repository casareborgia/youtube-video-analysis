// 전국시대(기원전 260년 무렵) 7국 개략도 — 직접 그린 도식이다. 공개 지도를 따라 그리지 않았고 경계는 정확하지 않다(화면에 approximate 표기).
// 좌표: 가로 1000 · 세로 900, 오른쪽이 동쪽. 이웃 나라는 꼭짓점을 공유해 틈이 없다.
// id 목록은 shorts_engine.MAP_STATES 와 같아야 한다(tests/test_shorts_seal_map.py 가 확인).

export type MapState = { id: string; en: string; zh: string; points: [number, number][] };

export const MAP_VIEW = { width: 1000, height: 900 };

export const WARRING_STATES: MapState[] = [
  {
    id: "qin",
    en: "Qin",
    zh: "秦",
    points: [[20, 120], [180, 95], [330, 80], [330, 200], [380, 330], [380, 450], [340, 540], [300, 700], [300, 880], [150, 820], [20, 760], [40, 500], [20, 300]],
  },
  { id: "zhao", en: "Zhao", zh: "趙", points: [[330, 80], [470, 55], [600, 60], [620, 250], [600, 380], [470, 420], [380, 330], [330, 200]] },
  {
    id: "yan",
    en: "Yan",
    zh: "燕",
    points: [[600, 60], [760, 40], [900, 70], [960, 130], [930, 220], [880, 280], [760, 300], [620, 250]],
  },
  {
    id: "qi",
    en: "Qi",
    zh: "齊",
    points: [[760, 300], [880, 280], [940, 330], [1000, 350], [990, 420], [930, 450], [880, 520], [830, 560], [700, 480], [690, 360], [620, 250]],
  },
  { id: "wei", en: "Wei", zh: "魏", points: [[470, 420], [600, 380], [620, 250], [690, 360], [700, 480], [600, 540], [480, 520]] },
  { id: "han", en: "Han", zh: "韓", points: [[380, 450], [380, 330], [470, 420], [480, 520], [420, 580], [340, 540]] },
  {
    id: "chu",
    en: "Chu",
    zh: "楚",
    points: [
      [300, 700], [340, 540], [420, 580], [480, 520], [600, 540], [700, 480], [830, 560], [880, 520], [900, 600], [950, 700],
      [930, 800], [880, 880], [700, 870], [520, 890], [300, 880],
    ],
  },
];

// 황하(黃河) 개략선 — 장식용
export const YELLOW_RIVER: [number, number][] = [[90, 300], [250, 250], [380, 330], [470, 420], [600, 380], [700, 330], [900, 300]];

export const centroid = (pts: [number, number][]): [number, number] => {
  const x = pts.reduce((a, p) => a + p[0], 0) / pts.length;
  const y = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  return [x, y];
};

export const stateById = (id: string) => WARRING_STATES.find((s) => s.id === id);
