// Props contract between the Python orchestrator (telugu_tech/premium.py) and the Remotion renderer.

export type Visual = {type: string; [key: string]: unknown};

export type Scene = {
  id: number;
  section: string;
  start: number; // seconds (scene visual start, beat-aligned)
  end: number; // seconds
  speechStart: number;
  speechEnd: number;
  visual: Visual;
  transition: string; // transition INTO this scene
  camera: string;
  background: string;
  tag?: string;
};

export type Word = {
  text: string;
  start: number;
  end: number;
  keyword: boolean;
  scene: number;
  pageEnd?: boolean; // last word of a caption page
};

export type CaptionStyle = {
  template: 'pop_highlight' | 'karaoke_line' | 'bold_center' | 'pixel_block' | 'hud_bracket' | 'glass_pill';
  position: number; // 0..1 vertical centre of caption block
  fontSize: number; // px at 1080 width
  maxWords: number;
  uppercase: boolean;
};

export type StyleProfile = {
  name: string;
  source: string; // "house-preset" or "reference:<file>"
  bpm: number;
  transitionSeconds: number;
  cameraIntensity: number; // 0..1
  zoomRange: [number, number];
  motionBlur: boolean;
  parallax: number; // 0..1
  beatPunch: number; // 0..0.05 scale bump on downbeats
  subCutSeconds: number; // 0 disables punch-in reframes inside long scenes
  caption: CaptionStyle;
  // editing-style extensions (optional for backwards compatibility)
  overlay?: string; // film | studio | crt | hud | launch | news | terminal | depth | glass | grid | none
  font?: string; // display | serif | mono
  dof?: boolean; // simulated depth of field (background defocus + rack focus)
};

export type Theme = {
  primary: string;
  accent: string;
  highlight: string;
  bgTop: string;
  bgBottom: string;
  text: string;
  danger: string;
};

export type Props = {
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  theme: Theme;
  style: StyleProfile;
  scenes: Scene[];
  words: Word[];
  beats: number[];
  fonts: {display: string; telugu: string; mono: string; body: string; serif?: string};
  profile?: 'full' | 'lite'; // lite = no WebGL (CSS/canvas fallbacks for 3D and pixel scenes)
  channel?: string;
  dateLabel?: string;
};
