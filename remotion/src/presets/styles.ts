import {StyleProfile} from '../types';

// House preset designed for faceless tech explainers. NOT derived from any specific creator's video.
// A reference-derived profile (telugu_tech/reference.py) overrides these values when supplied.
export const CINEMATIC_TECH: StyleProfile = {
  name: 'cinematic_tech',
  source: 'house-preset',
  bpm: 100,
  transitionSeconds: 0.4,
  cameraIntensity: 0.7,
  zoomRange: [1.0, 1.14],
  motionBlur: true,
  parallax: 0.6,
  beatPunch: 0.025,
  subCutSeconds: 2.4,
  caption: {template: 'pop_highlight', position: 0.7, fontSize: 74, maxWords: 3, uppercase: false},
};

// Scene-type → default camera move and background (used when the storyboard doesn't specify one).
export const CAMERA_FOR: Record<string, string> = {
  headline: 'push_in', question: 'push_in', title: 'push_in', stat: 'pull_out', chart: 'orbit',
  neural_net: 'orbit', flow: 'pan_right', timeline: 'pan_left', chat_ui: 'tilt', code: 'tilt',
  globe: 'drift', molecule: 'drift', icon_grid: 'orbit', branch_graph: 'push_in', bullets: 'pan_left',
  compare: 'push_in', outro: 'pull_out',
};

export const BACKGROUND_FOR: Record<string, string> = {
  headline: 'aurora', question: 'aurora', title: 'aurora', stat: 'grid', chart: 'grid', neural_net: 'circuit',
  flow: 'circuit', timeline: 'grid', chat_ui: 'aurora', code: 'dots', globe: 'space', molecule: 'space',
  icon_grid: 'particles', branch_graph: 'circuit', bullets: 'particles', compare: 'grid', outro: 'aurora',
};
