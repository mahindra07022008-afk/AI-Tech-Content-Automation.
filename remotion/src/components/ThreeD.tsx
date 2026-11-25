// Real-time 3D smartphone (three.js + React Three Fiber via @remotion/three), plus a CSS-3D "lite"
// fallback for environments without WebGL. Remotion rules followed: <ThreeCanvas> with explicit
// width/height, every animation derived from useCurrentFrame() (no useFrame), deterministic textures.
import React, {useMemo} from 'react';
import {ThreeCanvas} from '@remotion/three';
import * as THREE from 'three';
import {interpolate} from 'remotion';
import {Theme, Visual} from '../types';
import {clamp, hexA, prog, smooth, snap} from '../utils';

type PP = {v: Visual; f: number; dur: number; theme: Theme; lite: boolean; fps: number};

const str = (x: unknown, d = '') => (x === undefined || x === null ? d : String(x));
const arr = <T,>(x: unknown): T[] => (Array.isArray(x) ? (x as T[]) : []);

const BOX_W = 950;
const BOX_H = 860;

export const PHONE_LAYERS_DEFAULT = ['Glass', 'Display', 'Chip (SoC)', 'Battery', 'Back + cameras'];

const roundedRect = (w: number, h: number, r: number) => {
  const s = new THREE.Shape();
  const x = -w / 2;
  const y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);
  s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);
  s.quadraticCurveTo(x, y, x + r, y);
  return s;
};

// Deterministic phone UI drawn into a canvas (used as the 3D screen texture and by the lite fallback).
export const drawScreen = (ctx: CanvasRenderingContext2D, W: number, H: number, f: number, v: Visual, theme: Theme) => {
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, '#1d4ed8');
  g.addColorStop(1, '#6d28d9');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  ctx.font = `bold ${W * 0.06}px sans-serif`;
  ctx.fillText('9:41', W * 0.08, H * 0.05);
  const screen = (v.screen as {title?: string; lines?: string[]} | undefined) ?? {};
  const title = str(screen.title, str(v.label));
  ctx.fillStyle = '#ffffff';
  ctx.font = `900 ${W * 0.13}px sans-serif`;
  ctx.fillText(title.slice(0, 14), W * 0.08, H * 0.17);
  const lines = arr<string>(screen.lines);
  lines.forEach((ln, i) => {
    const p = clamp((f - 10 - i * 12) / 12);
    if (p <= 0) return;
    const y = H * (0.25 + i * 0.12);
    ctx.globalAlpha = p;
    ctx.fillStyle = 'rgba(255,255,255,0.22)';
    ctx.beginPath();
    ctx.roundRect(W * 0.07, y, W * 0.86, H * 0.095, W * 0.04);
    ctx.fill();
    ctx.fillStyle = i % 2 ? theme.highlight : '#ffffff';
    ctx.font = `800 ${W * 0.09}px sans-serif`;
    ctx.fillText(ln.slice(0, 14), W * 0.12, y + H * 0.065);
    ctx.globalAlpha = 1;
  });
  // animated progress ring (purely decorative, no numbers)
  const ring = (f % 90) / 90;
  ctx.strokeStyle = hexA(theme.accent, 0.9);
  ctx.lineWidth = W * 0.02;
  ctx.beginPath();
  ctx.arc(W * 0.5, H * 0.86, W * 0.08, -Math.PI / 2, -Math.PI / 2 + ring * Math.PI * 2);
  ctx.stroke();
};

const ScreenMaterial: React.FC<{f: number; v: Visual; theme: Theme}> = ({f, v, theme}) => {
  const {canvas, tex} = useMemo(() => {
    const c = document.createElement('canvas');
    c.width = 512;
    c.height = 1056;
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return {canvas: c, tex: t};
  }, []);
  const ctx = canvas.getContext('2d');
  if (ctx) {
    drawScreen(ctx, canvas.width, canvas.height, f, v, theme);
    tex.needsUpdate = true;
  }
  return <meshBasicMaterial map={tex} toneMapped={false} />;
};

const Phone3DScene: React.FC<PP> = ({v, f, dur, theme}) => {
  const mode = str(v.mode, 'hero');
  const body = useMemo(() => {
    const g = new THREE.ExtrudeGeometry(roundedRect(1.62, 3.32, 0.26), {depth: 0.16, bevelEnabled: true, bevelThickness: 0.035,
      bevelSize: 0.035, bevelSegments: 6, curveSegments: 24});
    g.translate(0, 0, -0.08);
    return g;
  }, []);
  const plate = useMemo(() => new THREE.ShapeGeometry(roundedRect(1.5, 3.2, 0.2), 24), []);
  const bump = useMemo(() => {
    const g = new THREE.ExtrudeGeometry(roundedRect(0.78, 0.78, 0.2), {depth: 0.06, bevelEnabled: true, bevelThickness: 0.02,
      bevelSize: 0.02, bevelSegments: 4, curveSegments: 16});
    return g;
  }, []);
  const intro = prog(f, 0, 26, snap);
  const t = f / 30;
  let ry = interpolate(intro, [0, 1], [-1.3, -0.32]) + Math.sin(t * 0.6) * 0.08;
  let rx = 0.08 + Math.sin(t * 0.5) * 0.04;
  let camZ = 8.3;
  let camY = 0;
  // chip mode: glass + display lift away and the body slides back so the board and SoC sit in front
  const reveal = mode === 'chip' ? prog(f, 4, 30, smooth) : 0;
  const explode = mode === 'explode' ? prog(f, 12, Math.max(30, dur * 0.55), smooth) : reveal * 0.9;
  let gx = 0;
  if (mode === 'explode') {
    ry = -0.95 + Math.sin(t * 0.4) * 0.05;
    rx = 0.16;
    camZ = 8.6;
    gx = -0.75; // phone left, layer labels in the right column
  } else if (mode === 'camera') {
    ry = interpolate(prog(f, 0, 40, smooth), [0, 1], [-0.3, Math.PI + 0.35]);
    camZ = 8.4;
  } else if (mode === 'chip') {
    ry = -0.35;
    rx = 0.25;
    camZ = interpolate(prog(f, 6, 50, smooth), [0, 1], [8.5, 5.6]);
    camY = interpolate(prog(f, 6, 50, smooth), [0, 1], [0, 0.45]);
  } else if (mode === 'screen') {
    ry = interpolate(intro, [0, 1], [-0.9, 0]);
    camZ = interpolate(prog(f, 0, 60, smooth), [0, 1], [9.5, 7.6]);
  }
  const float = Math.sin(t * 1.1) * 0.06;
  const sweep = Math.sin(t * 0.9) * 4;
  const dz = (i: number) => (2 - i) * 0.55 * explode; // layer offsets along z (front = +)
  const chipGlow = mode === 'chip' || mode === 'explode' ? 0.6 + 0.4 * Math.sin(t * 4) : 0.2;
  const layerHi = mode === 'explode' ? Math.min(4, Math.floor(prog(f, 12, Math.max(30, dur * 0.7), smooth) * 5)) : -1;
  return (
    <ThreeCanvas width={BOX_W} height={BOX_H} camera={{position: [0, camY, camZ], fov: 32}} gl={{antialias: true}}>
      <ambientLight intensity={0.9} />
      <hemisphereLight args={['#dbeafe', '#1e1b4b', 0.8]} />
      <directionalLight position={[3, 4, 6]} intensity={2.4} />
      <pointLight position={[0, 1, -3]} intensity={30} color={theme.accent} distance={10} />
      <pointLight position={[sweep, 1.5, 3]} intensity={18} color={theme.accent} distance={12} />
      <pointLight position={[-3, -2, -4]} intensity={10} color={theme.primary} distance={12} />
      <group rotation={[rx, ry, 0]} position={[gx, float, 0]} scale={0.95 + 0.05 * intro}>
        {/* back + frame */}
        <mesh geometry={body} position={[0, 0, dz(4)]}>
          <meshPhysicalMaterial color="#6b7280" metalness={0.75} roughness={0.25} clearcoat={1} clearcoatRoughness={0.1}
            emissive={layerHi === 4 ? theme.accent : '#000000'} emissiveIntensity={layerHi === 4 ? 0.25 : 0} />
        </mesh>
        <group position={[0.32, 1.05, -0.12 + dz(4)]} rotation={[0, Math.PI, 0]}>
          <mesh geometry={bump}><meshPhysicalMaterial color="#9ca3af" metalness={0.85} roughness={0.2} clearcoat={1} /></mesh>
          {[[-0.17, 0.17], [0.17, 0.17], [-0.17, -0.17]].map(([x, y], i) => (
            <mesh key={i} position={[x, y, 0.09]} rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[0.12, 0.12, 0.06, 32]} />
              <meshPhysicalMaterial color="#111827" metalness={0.9} roughness={0.05} clearcoat={1} emissive={theme.accent} emissiveIntensity={0.25} />
            </mesh>
          ))}
        </group>
        {/* battery */}
        <mesh position={[0, -0.45, dz(3)]}>
          <boxGeometry args={[1.25, 1.7, 0.06]} />
          <meshStandardMaterial color={layerHi === 3 ? theme.highlight : '#64748b'} metalness={0.4} roughness={0.5} />
        </mesh>
        {/* logic board + SoC */}
        <mesh position={[0, 0.95, dz(2)]}>
          <boxGeometry args={[1.3, 1.1, 0.04]} />
          <meshStandardMaterial color="#14532d" metalness={0.2} roughness={0.7} />
        </mesh>
        <mesh position={[0, 1.0, dz(2) + 0.05]}>
          <boxGeometry args={[0.42, 0.42, 0.06]} />
          <meshStandardMaterial color="#0f172a" emissive={theme.accent} emissiveIntensity={chipGlow * (layerHi === 2 || mode === 'chip' ? 1.6 : 0.5)}
            metalness={0.6} roughness={0.3} />
        </mesh>
        {/* display (texture) */}
        <mesh geometry={plate} position={[0, reveal * 7, 0.125 + dz(1)]} visible={reveal < 0.98}>
          <ScreenMaterial f={f} v={v} theme={theme} />
        </mesh>
        {/* cover glass */}
        <mesh geometry={plate} position={[0, reveal * 7.5, 0.14 + dz(0)]} visible={reveal < 0.98}>
          <meshPhysicalMaterial color="#ffffff" transparent opacity={0.08 + (layerHi === 0 ? 0.12 : 0)} roughness={0.05}
            metalness={0} clearcoat={1} />
        </mesh>
      </group>
    </ThreeCanvas>
  );
};

// ---------------------------------------------------------------- lite (CSS 3D) fallback
const PhoneLite: React.FC<PP> = ({v, f, dur, theme}) => {
  const mode = str(v.mode, 'hero');
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  React.useLayoutEffect(() => {
    const c = canvasRef.current;
    const ctx = c?.getContext('2d');
    if (c && ctx) drawScreen(ctx, c.width, c.height, f, v, theme);
  });
  const intro = prog(f, 0, 26, snap);
  // chip mode: glass + display lift away and the body slides back so the board and SoC sit in front
  const reveal = mode === 'chip' ? prog(f, 4, 30, smooth) : 0;
  const explode = mode === 'explode' ? prog(f, 12, Math.max(30, dur * 0.55), smooth) : reveal * 0.9;
  const ry = mode === 'camera' ? interpolate(prog(f, 0, 40, smooth), [0, 1], [-15, 200]) : interpolate(intro, [0, 1], [-60, -18]);
  const layers = ['#ffffff22', 'screen', '#14532d', '#64748b', '#1f2937'];
  return (
    <div style={{position: 'absolute', inset: 0, perspective: 1600, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
      <div style={{width: 330, height: 676, position: 'relative', transformStyle: 'preserve-3d',
        transform: `rotateY(${ry}deg) rotateX(${8 + Math.sin(f / 20) * 3}deg)`}}>
        {layers.map((c, i) => (
          <div key={i} style={{position: 'absolute', inset: 0, borderRadius: 52, transform: `translateZ(${(2 - i) * 60 * explode + (2 - i) * 4}px)`,
            background: c === 'screen' ? 'transparent' : c, border: i === 4 ? `3px solid ${hexA(theme.accent, 0.5)}` : undefined,
            boxShadow: i === 4 ? `0 30px 80px rgba(0,0,0,0.6), 0 0 40px ${hexA(theme.accent, 0.25)}` : undefined, overflow: 'hidden'}}>
            {c === 'screen' && <canvas ref={canvasRef} width={330} height={676} style={{width: '100%', height: '100%', borderRadius: 48}} />}
          </div>
        ))}
      </div>
    </div>
  );
};

export const Phone3D: React.FC<PP> = (p) => {
  const mode = str(p.v.mode, 'hero');
  const layers = arr<string>(p.v.layers).length ? arr<string>(p.v.layers) : PHONE_LAYERS_DEFAULT;
  const hi = mode === 'explode' ? Math.min(layers.length - 1, Math.floor(prog(p.f, 12, Math.max(30, p.dur * 0.7), smooth) * layers.length)) : -1;
  return (
    <div style={{position: 'absolute', left: '6%', right: '6%', top: '15.5%', height: '45%'}}>
      {p.lite ? <PhoneLite {...p} /> : <Phone3DScene {...p} />}
      {mode === 'explode' && (
        <div style={{position: 'absolute', right: 0, top: '8%', display: 'flex', flexDirection: 'column', gap: 18}}>
          {layers.map((l, i) => (
            <div key={i} style={{padding: '10px 22px', borderRadius: 18, fontSize: 34, fontWeight: 800,
              background: i === hi ? hexA(p.theme.accent, 0.9) : 'rgba(255,255,255,0.08)', color: i === hi ? '#04111d' : p.theme.text,
              opacity: clamp(prog(p.f, 8 + i * 6, 10) * 1.2), transform: `translateX(${(1 - prog(p.f, 8 + i * 6, 10, snap)) * 60}px)`}}>{l}</div>
          ))}
        </div>
      )}
      {mode !== 'explode' && p.v.label ? (
        <div style={{position: 'absolute', bottom: '-2%', width: '100%', textAlign: 'center', fontSize: 46, fontWeight: 800,
          color: p.theme.text, opacity: prog(p.f, 14, 12), textShadow: '0 6px 24px rgba(0,0,0,0.8)'}}>{str(p.v.label)}</div>
      ) : null}
    </div>
  );
};
