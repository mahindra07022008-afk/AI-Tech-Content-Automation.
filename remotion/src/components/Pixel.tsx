// Retro pixel-art scenes. Pixel content is drawn procedurally into a 135×240 canvas (8× → 1080×1920
// box region) with an original 5×7 bitmap font; PixiJS uploads it as a nearest-filtered texture and adds
// CRT scanlines (TilingSprite), a retro ColorMatrix and frame-seeded noise. Lite profile = canvas-2D
// with CSS pixelated scaling. Everything is a pure function of the frame (deterministic renders).
import React, {useLayoutEffect, useRef, useState} from 'react';
import {cancelRender, continueRender, delayRender} from 'remotion';
import {Theme, Visual} from '../types';

const VW = 135;
const VH = 120; // pixel canvas for the visual box (box is ~950×860 → 7× scale)
const SCALE = 7;

// ---------------------------------------------------------------- 5×7 bitmap font (original)
const G: Record<string, string> = {
  A: '01110100011000111111100011000110001', B: '11110100011000111110100011000111110', C: '01110100011000010000100001000101110',
  D: '11110100011000110001100011000111110', E: '11111100001000011110100001000011111', F: '11111100001000011110100001000010000',
  G: '01110100011000010111100011000101111', H: '10001100011000111111100011000110001', I: '01110001000010000100001000010001110',
  J: '00111000100001000010000101001001100', K: '10001100101010011000101001001010001', L: '10000100001000010000100001000011111',
  M: '10001110111010110101100011000110001', N: '10001110011010110011100011000110001', O: '01110100011000110001100011000101110',
  P: '11110100011000111110100001000010000', Q: '01110100011000110001101011001001101', R: '11110100011000111110101001001010001',
  S: '01111100001000001110000010000111110', T: '11111001000010000100001000010000100', U: '10001100011000110001100011000101110',
  V: '10001100011000110001100010101000100', W: '10001100011000110101101011010101010', X: '10001100010101000100010101000110001',
  Y: '10001100010101000100001000010000100', Z: '11111000010001000100010001000011111',
  '0': '01110100011001110101110011000101110', '1': '00100011000010000100001000010001110', '2': '01110100010000100010001000100011111',
  '3': '11111000100010000010000011000101110', '4': '00010001100101010010111110001000010', '5': '11111100001111000001000011000101110',
  '6': '00110010001000011110100011000101110', '7': '11111000010001000100010000100001000', '8': '01110100011000101110100011000101110',
  '9': '01110100011000101111000010001001100', ' ': '00000000000000000000000000000000000', '.': '00000000000000000000000000110001100',
  ',': '00000000000000000000001100010001000', '!': '00100001000010000100001000000000100', '?': '01110100010000100010001000000000100',
  ':': '00000011000110000000011000110000000', '-': '00000000000000011111000000000000000', '/': '00001000010001000100010001000010000',
  "'": '00100001000100000000000000000000000', '+': '00000001000010011111001000010000000', '#': '01010010101111101010111110101001010',
};

export const textWidth = (s: string, sc = 1) => s.length * 6 * sc - sc;

export const drawText = (ctx: CanvasRenderingContext2D, s: string, x: number, y: number, color: string, sc = 1, shadow?: string) => {
  const up = s.toUpperCase();
  for (let k = 0; k < up.length; k++) {
    const g = G[up[k]] ?? G['?'];
    for (let r = 0; r < 7; r++) for (let c = 0; c < 5; c++) {
      if (g[r * 5 + c] !== '1') continue;
      if (shadow) {
        ctx.fillStyle = shadow;
        ctx.fillRect(x + (k * 6 + c) * sc + sc, y + r * sc + sc, sc, sc);
      }
      ctx.fillStyle = color;
      ctx.fillRect(x + (k * 6 + c) * sc, y + r * sc, sc, sc);
    }
  }
};

const rect = (ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, c: string) => {
  ctx.fillStyle = c;
  ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
};

const hash = (n: number) => {
  const x = Math.sin(n * 127.1) * 43758.5453;
  return x - Math.floor(x);
};

// ---------------------------------------------------------------- scenes
export const PIXEL_SCENES = ['title', 'crt', 'network', 'globe', 'unlock', 'phone', 'server', 'rocket'];

export const drawPixelScene = (ctx: CanvasRenderingContext2D, f: number, v: Visual, theme: Theme) => {
  const scene = String(v.scene ?? 'title');
  const text = String(v.text ?? '');
  const year = String(v.year ?? '');
  ctx.imageSmoothingEnabled = false;
  // dithered sky
  for (let y = 0; y < VH; y++) {
    const band = Math.floor((y / VH) * 4);
    const c = ['#0b1026', '#141a3a', '#1d1b4f', '#2a1f5e'][band];
    rect(ctx, 0, y, VW, 1, c);
    if (y % 2 === 0 && band < 3) for (let x = (y / 2) % 2; x < VW; x += 2) if ((y + x) % 4 === 0) rect(ctx, x, y, 1, 1, '#1d2550');
  }
  // twinkling stars
  for (let i = 0; i < 26; i++) {
    const sx = Math.floor(hash(i) * VW);
    const sy = Math.floor(hash(i + 50) * VH * 0.55);
    if ((Math.floor(f / 8) + i) % 5 !== 0) rect(ctx, sx, sy, 1, 1, i % 4 ? '#cbd5e1' : theme.highlight);
  }
  const ground = (c1: string, c2: string) => {
    rect(ctx, 0, VH - 16, VW, 16, c1);
    for (let x = 0; x < VW; x += 4) rect(ctx, x + ((f >> 3) % 4), VH - 16, 2, 1, c2);
  };
  const blink = Math.floor(f / 10) % 2 === 0;
  const typed = (s: string, start: number, speed = 1.2) => s.slice(0, Math.max(0, Math.floor((f - start) * speed)));

  if (scene === 'title') {
    ground('#14532d', '#22c55e');
    const sc = year.length > 4 ? 3 : 4;
    const yw = textWidth(year, sc);
    const bounce = f < 12 ? Math.round((12 - f) * 1.5) : 0;
    drawText(ctx, year, Math.round((VW - yw) / 2), 24 - bounce, theme.highlight, sc, '#000000');
    const t = typed(text, 14, 0.8);
    const lines = wrap(t, 20);
    lines.forEach((ln, i) => drawText(ctx, ln, Math.round((VW - textWidth(ln)) / 2), 62 + i * 10, '#e2e8f0', 1, '#000000'));
  } else if (scene === 'crt') {
    ground('#3f2a14', '#7c4a1e');
    rect(ctx, 20, 88, 95, 6, '#7c4a1e'); // desk
    rect(ctx, 30, 30, 75, 56, '#cbd5e1'); // monitor case
    rect(ctx, 34, 34, 67, 44, '#052e16'); // screen
    rect(ctx, 60, 86, 15, 4, '#94a3b8');
    rect(ctx, 38, 92, 60, 6, '#e2e8f0'); // keyboard
    for (let k = 0; k < 10; k++) rect(ctx, 40 + k * 6, 93, 4, 2, '#94a3b8');
    const lines = wrap(text || 'HELLO WORLD', 10);
    let budget = Math.max(0, Math.floor((f - 6) * 0.7));
    lines.slice(0, 4).forEach((ln, i) => {
      const shown = ln.slice(0, budget);
      budget -= ln.length;
      drawText(ctx, shown, 37, 37 + i * 9, '#4ade80');
      if (shown.length < ln.length && budget <= 0 && blink) rect(ctx, 37 + shown.length * 6, 37 + i * 9, 5, 7, '#4ade80');
    });
  } else if (scene === 'network') {
    ground('#1e293b', '#334155');
    const nodes = [[20, 40], [110, 34], [66, 62], [24, 92], [108, 90]];
    const edges = [[0, 2], [1, 2], [2, 3], [2, 4], [0, 1], [3, 4]];
    edges.forEach(([a, b], k) => {
      const [x1, y1] = nodes[a];
      const [x2, y2] = nodes[b];
      const steps = Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1));
      const shown = Math.min(steps, Math.max(0, (f - k * 6) * 2));
      for (let s = 0; s < shown; s += 2) rect(ctx, x1 + ((x2 - x1) * s) / steps, y1 + ((y2 - y1) * s) / steps, 1, 1, '#64748b');
      if (shown >= steps) {
        const p = ((f + k * 9) % 30) / 30;
        rect(ctx, x1 + (x2 - x1) * p - 1, y1 + (y2 - y1) * p - 1, 3, 3, theme.highlight);
      }
    });
    nodes.forEach(([x, y], i) => {
      if (f < i * 5) return;
      rect(ctx, x - 7, y - 6, 14, 10, '#cbd5e1');
      rect(ctx, x - 5, y - 4, 10, 6, i === 2 ? theme.accent : '#1e3a8a');
      rect(ctx, x - 3, y + 4, 6, 2, '#94a3b8');
    });
    if (text) drawText(ctx, text.slice(0, 21), Math.round((VW - textWidth(text.slice(0, 21))) / 2), 8, '#e2e8f0', 1, '#000000');
  } else if (scene === 'globe') {
    const cx = 67;
    const cy = 58;
    const R = 34;
    const rot = f * 0.6;
    for (let y = -R; y <= R; y++) for (let x = -R; x <= R; x++) {
      if (x * x + y * y > R * R) continue;
      const lon = Math.floor((x + rot) / 6);
      const lat = Math.floor(y / 6);
      const land = hash(lon * 7 + lat * 13) > 0.58;
      rect(ctx, cx + x, cy + y, 1, 1, land ? '#16a34a' : '#1d4ed8');
    }
    const lit = Math.min(14, Math.floor(f / 6));
    for (let i = 0; i < lit; i++) {
      const a = hash(i + 7) * Math.PI * 2;
      const r = hash(i + 19) * (R - 4);
      const px = cx + Math.cos(a) * r;
      const py = cy + Math.sin(a) * r * 0.9;
      rect(ctx, px - 1, py - 1, 3, 3, (f + i * 3) % 12 < 6 ? theme.highlight : '#fde68a');
    }
    if (text) drawText(ctx, text.slice(0, 21), Math.round((VW - textWidth(text.slice(0, 21))) / 2), 102, '#e2e8f0', 1, '#000000');
  } else if (scene === 'unlock') {
    ground('#14532d', '#22c55e');
    const open = Math.min(1, Math.max(0, (f - 14) / 14));
    const lx = 50;
    const ly = 46;
    const sh = Math.round(open * 12);
    rect(ctx, lx + 6, ly - 18 - sh, 4, 18, '#cbd5e1');
    rect(ctx, lx + 26, ly - 18 + (open > 0.5 ? -sh : 0), 4, open > 0.5 ? 6 : 18, '#cbd5e1');
    rect(ctx, lx + 6, ly - 22 - sh, 24, 4, '#cbd5e1');
    rect(ctx, lx, ly, 36, 30, theme.highlight);
    rect(ctx, lx + 15, ly + 9, 6, 10, '#78350f');
    if (open >= 1) for (let i = 0; i < 18; i++) {
      const a = hash(i) * Math.PI * 2;
      const d = ((f - 28) * 1.5) % 40;
      rect(ctx, 68 + Math.cos(a) * d, 60 + Math.sin(a) * d, 2, 2, i % 3 ? theme.accent : '#f472b6');
    }
    if (text) drawText(ctx, text.slice(0, 21), Math.round((VW - textWidth(text.slice(0, 21))) / 2), 92, '#e2e8f0', 1, '#000000');
  } else if (scene === 'phone') {
    ground('#1e293b', '#334155');
    rect(ctx, 44, 14, 47, 86, '#0f172a');
    rect(ctx, 46, 16, 43, 82, '#e2e8f0');
    rect(ctx, 48, 20, 39, 6, '#cbd5e1');
    drawText(ctx, 'WWW', 50, 30, theme.primary);
    for (let i = 0; i < 5; i++) if (f > 10 + i * 6) rect(ctx, 50, 42 + i * 8, 20 + ((i * 7) % 15), 4, i % 2 ? '#94a3b8' : '#475569');
    if (blink) rect(ctx, 52, 88, 30, 4, theme.accent);
    if (text) drawText(ctx, text.slice(0, 21), Math.round((VW - textWidth(text.slice(0, 21))) / 2), 4, '#e2e8f0', 1, '#000000');
  } else if (scene === 'server') {
    ground('#111827', '#1f2937');
    for (let r = 0; r < 3; r++) {
      rect(ctx, 30 + r * 27, 30, 22, 70, '#334155');
      for (let u = 0; u < 7; u++) {
        rect(ctx, 32 + r * 27, 33 + u * 9, 18, 6, '#1e293b');
        if ((Math.floor(f / 4) + u + r * 3) % 4 !== 0) rect(ctx, 46 + r * 27, 35 + u * 9, 2, 2, u % 2 ? theme.accent : '#22c55e');
      }
    }
    if (text) drawText(ctx, text.slice(0, 21), Math.round((VW - textWidth(text.slice(0, 21))) / 2), 10, '#e2e8f0', 1, '#000000');
  } else if (scene === 'rocket') {
    ground('#14532d', '#22c55e');
    const lift = Math.max(0, f - 12) * 1.2;
    const ry = 70 - lift;
    rect(ctx, 62, ry, 10, 26, '#e2e8f0');
    rect(ctx, 64, ry - 6, 6, 6, '#e2e8f0');
    rect(ctx, 66, ry - 8, 2, 2, '#e2e8f0');
    rect(ctx, 64, ry + 6, 6, 5, theme.accent);
    rect(ctx, 57, ry + 18, 5, 8, '#f43f5e');
    rect(ctx, 72, ry + 18, 5, 8, '#f43f5e');
    for (let i = 0; i < 6; i++) rect(ctx, 63 + ((f + i) % 3) * 2, ry + 26 + i * 3, 3, 3, i < 2 ? '#fde68a' : i < 4 ? '#fb923c' : '#94a3b8');
    if (text) drawText(ctx, text.slice(0, 21), Math.round((VW - textWidth(text.slice(0, 21))) / 2), 108, '#e2e8f0', 1, '#000000');
  }
};

const wrap = (s: string, n: number) => {
  const words = s.split(/\s+/);
  const out: string[] = [];
  let cur = '';
  for (const w of words) {
    if ((cur + ' ' + w).trim().length > n && cur) {
      out.push(cur);
      cur = w;
    } else cur = (cur + ' ' + w).trim();
  }
  if (cur) out.push(cur);
  return out;
};

// ---------------------------------------------------------------- renderers
type PXP = {v: Visual; f: number; theme: Theme; lite: boolean};

const PixelCanvas2D: React.FC<PXP> = ({v, f, theme}) => {
  const src = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const ctx = src.current?.getContext('2d');
    if (ctx) drawPixelScene(ctx, f, v, theme);
  });
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <canvas ref={src} width={VW} height={VH} style={{width: VW * SCALE, height: VH * SCALE, imageRendering: 'pixelated',
        position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', borderRadius: 18}} />
      <div style={{position: 'absolute', left: '50%', top: '50%', width: VW * SCALE, height: VH * SCALE, transform: 'translate(-50%,-50%)',
        borderRadius: 18, background: 'repeating-linear-gradient(0deg, rgba(0,0,0,0.22) 0px, rgba(0,0,0,0.22) 2px, transparent 2px, transparent 7px)'}} />
    </div>
  );
};

const PixelPixi: React.FC<PXP> = ({v, f, theme}) => {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<{render: (frame: number) => void; destroy: () => void} | null>(null);
  const frameRef = useRef(f);
  frameRef.current = f;
  const [handle] = useState(() => delayRender('pixi-init', {timeoutInMilliseconds: 60000}));
  useLayoutEffect(() => {
    let cancelled = false;
    (async () => {
      const PIXI = await import('pixi.js');
      const app = new PIXI.Application();
      await app.init({width: VW * SCALE, height: VH * SCALE, backgroundAlpha: 0, preference: 'webgl', autoStart: false,
        antialias: false, preserveDrawingBuffer: true, resolution: 1});
      if (cancelled) {
        app.destroy(true);
        return;
      }
      app.ticker.stop();
      const canvas = document.createElement('canvas');
      canvas.width = VW;
      canvas.height = VH;
      const ctx = canvas.getContext('2d')!;
      const tex = PIXI.Texture.from(canvas);
      tex.source.scaleMode = 'nearest';
      const sprite = new PIXI.Sprite(tex);
      sprite.scale.set(SCALE);
      // CRT scanlines: 1×7 texture (2px dark + 5px clear) tiled over the scene
      const sl = document.createElement('canvas');
      sl.width = 1;
      sl.height = 7;
      const slc = sl.getContext('2d')!;
      slc.fillStyle = 'rgba(0,0,0,0.28)';
      slc.fillRect(0, 0, 1, 2);
      const scan = new PIXI.TilingSprite({texture: PIXI.Texture.from(sl), width: VW * SCALE, height: VH * SCALE});
      const cm = new PIXI.ColorMatrixFilter();
      cm.contrast(0.18, false);
      cm.saturate(0.15, true);
      const noise = new PIXI.NoiseFilter({noise: 0.06, seed: 0.5});
      sprite.filters = [cm, noise];
      app.stage.addChild(sprite, scan);
      host.current?.appendChild(app.canvas);
      Object.assign(app.canvas.style, {borderRadius: '18px', position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)'});
      const render = (frame: number) => {
        drawPixelScene(ctx, frame, v, theme);
        tex.source.update();
        noise.seed = ((frame * 9301 + 49297) % 233280) / 233280; // deterministic grain per frame
        app.render();
      };
      state.current = {render, destroy: () => app.destroy(true)};
      render(frameRef.current);
      continueRender(handle);
    })().catch((e) => cancelRender(e));
    return () => {
      cancelled = true;
      state.current?.destroy();
      state.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useLayoutEffect(() => {
    state.current?.render(f);
  }, [f]);
  return <div ref={host} style={{position: 'absolute', inset: 0}} />;
};

export const PixelScene: React.FC<PXP> = (p) => (
  <div style={{position: 'absolute', left: '6%', right: '6%', top: '15.5%', height: '45%'}}>
    {p.lite ? <PixelCanvas2D {...p} /> : <PixelPixi {...p} />}
  </div>
);
