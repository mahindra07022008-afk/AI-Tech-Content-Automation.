import React from 'react';
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {StyleProfile} from '../types';
import {ramp} from '../utils';

// Virtual camera: speed-ramped moves, beat punches and beat-aligned punch-in reframes.
export const cameraTransform = (
  preset: string, frame: number, dur: number, fps: number, style: StyleProfile, beatsInScene: number[], sceneStart: number,
) => {
  const k = style.cameraIntensity;
  const p = interpolate(frame, [0, Math.max(1, dur)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ramp});
  const [z0, z1] = style.zoomRange;
  const zr = (z1 - z0) * k;
  let scale = 1;
  let tx = 0;
  let ty = 0;
  let rx = 0;
  let ry = 0;
  switch (preset) {
    case 'pull_out': scale = z0 + zr * (1 - p) + 0.02; break;
    case 'pan_left': tx = interpolate(p, [0, 1], [50, -50]) * k; scale = 1.06; break;
    case 'pan_right': tx = interpolate(p, [0, 1], [-50, 50]) * k; scale = 1.06; break;
    case 'orbit': ry = interpolate(p, [0, 1], [-10, 10]) * k; rx = 5 * k; scale = 1.02 + 0.04 * p; break;
    case 'tilt': rx = interpolate(p, [0, 1], [16, 2]) * k; ry = -6 * k; scale = 1 + 0.05 * p; break;
    case 'drift': tx = Math.sin(frame / fps * 0.6) * 20 * k; ty = Math.cos(frame / fps * 0.5) * 16 * k; scale = 1.02; break;
    default: scale = z0 + zr * p; // push_in
  }
  // Beat punch: short scale bump on downbeats.
  let punch = 0;
  for (const b of beatsInScene) {
    const d = frame - (b - sceneStart) * fps;
    if (d >= 0 && d < 10) punch += style.beatPunch * Math.exp(-d / 3);
  }
  // Punch-in reframes (hard "cuts" between framings) on beats, for long scenes.
  let reframe = 1;
  let rox = 0;
  if (style.subCutSeconds > 0 && dur / fps > style.subCutSeconds * 1.6) {
    const cutFrames = beatsInScene
      .map((b) => Math.round((b - sceneStart) * fps))
      .filter((f) => f > style.subCutSeconds * fps * 0.8 && f < dur - fps * 0.8);
    const chosen: number[] = [];
    for (const f of cutFrames) if (!chosen.length || f - chosen[chosen.length - 1] >= style.subCutSeconds * fps) chosen.push(f);
    const idx = chosen.filter((f) => frame >= f).length;
    if (idx % 2 === 1) { reframe = 1.09; rox = idx % 4 === 1 ? -26 : 26; }
  }
  const s = (scale + punch) * reframe;
  return {
    transform: `perspective(1400px) translate(${tx + rox}px, ${ty}px) rotateX(${rx}deg) rotateY(${ry}deg) scale(${s})`,
    px: -(tx + rox) * style.parallax,
    py: -ty * style.parallax,
  };
};

export const useSceneEase = (start: number, dur: number) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return interpolate(frame, [start * fps, (start + dur) * fps], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic),
  });
};
