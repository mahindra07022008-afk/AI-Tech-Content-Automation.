import {Easing, interpolate, random} from 'remotion';

export const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));

// Speed-ramp style easings (fast attack, long settle) used by camera moves and reveals.
export const ramp = Easing.bezier(0.05, 0.7, 0.1, 1);
export const smooth = Easing.bezier(0.45, 0, 0.55, 1);
export const snap = Easing.bezier(0.2, 1.4, 0.4, 1); // overshoot

export const prog = (frame: number, start: number, dur: number, easing = ramp) =>
  interpolate(frame, [start, start + Math.max(1, dur)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing,
  });

export const seeded = (seed: string | number, i: number) => random(`${seed}-${i}`);

export const fit = (text: string, maxChars: number, base: number, min: number) => {
  const n = Math.max(1, text.length);
  return n <= maxChars ? base : Math.max(min, Math.round((base * maxChars) / n));
};

// Glow text-shadow stack.
export const glow = (color: string, strength = 1) =>
  `0 0 ${8 * strength}px ${color}, 0 0 ${22 * strength}px ${color}, 0 0 ${48 * strength}px ${color}88`;

export const hexA = (hex: string, a: number) => {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
};

// Simple 3D projection helpers for code-driven 3D (no WebGL needed).
export type P3 = {x: number; y: number; z: number};
export const rotY = (p: P3, a: number): P3 => ({
  x: p.x * Math.cos(a) + p.z * Math.sin(a),
  y: p.y,
  z: -p.x * Math.sin(a) + p.z * Math.cos(a),
});
export const rotX = (p: P3, a: number): P3 => ({
  x: p.x,
  y: p.y * Math.cos(a) - p.z * Math.sin(a),
  z: p.y * Math.sin(a) + p.z * Math.cos(a),
});
export const project = (p: P3, focal = 900, cx = 0, cy = 0) => {
  const s = focal / (focal + p.z);
  return {x: cx + p.x * s, y: cy + p.y * s, s};
};
