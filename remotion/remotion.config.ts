import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
// flyover(3D 항공) 씬의 three.js(WebGL)를 헤드리스 렌더에서 그리기 위한 GPU 백엔드
Config.setChromiumOpenGlRenderer("angle");
