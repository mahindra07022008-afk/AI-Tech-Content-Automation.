// Style overlays (drawn above scene visuals, below captions) + isometric stack visual.
// All frame-driven and deterministic. Overlays never show numbers or text that could read as facts.
import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Theme, Visual} from '../types';
import {clamp, hexA, prog, snap} from '../utils';

export const StyleOverlay: React.FC<{name: string; theme: Theme; dateLabel?: string}> = ({name, theme, dateLabel}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps} = useVideoConfig();
  const t = frame / fps;
  switch (name) {
    case 'film': {
      // documentary film look: gate weave, soft light leak sweeping occasionally
      const leak = (t % 9) / 9;
      return (
        <AbsoluteFill style={{pointerEvents: 'none'}}>
          <AbsoluteFill style={{background: `radial-gradient(ellipse at ${leak * 140 - 20}% 20%, rgba(255,170,90,${0.18 * Math.sin(Math.PI * leak)}) 0%, transparent 45%)`,
            mixBlendMode: 'screen'}} />
          <AbsoluteFill style={{boxShadow: 'inset 0 0 220px rgba(0,0,0,0.65)'}} />
        </AbsoluteFill>
      );
    }
    case 'studio':
      return (
        <AbsoluteFill style={{pointerEvents: 'none'}}>
          <div style={{position: 'absolute', left: '15%', right: '15%', top: '56%', height: 120, borderRadius: '50%',
            background: `radial-gradient(ellipse, ${hexA(theme.accent, 0.35)} 0%, transparent 70%)`, filter: 'blur(20px)'}} />
          <AbsoluteFill style={{background: `linear-gradient(${100 + Math.sin(t * 0.5) * 20}deg, transparent 40%, rgba(255,255,255,0.05) 50%, transparent 60%)`}} />
        </AbsoluteFill>
      );
    case 'crt':
      return (
        <AbsoluteFill style={{pointerEvents: 'none', boxShadow: 'inset 0 0 180px rgba(0,0,0,0.7)',
          background: 'repeating-linear-gradient(0deg, rgba(0,0,0,0.10) 0px, rgba(0,0,0,0.10) 2px, transparent 2px, transparent 6px)'}} />
      );
    case 'hud': {
      const c = theme.accent;
      const s = 90;
      const ring = (t * 40) % 360;
      return (
        <AbsoluteFill style={{pointerEvents: 'none'}}>
          {[[0, 0, 0], [1, 0, 90], [1, 1, 180], [0, 1, 270]].map(([x, y, r], i) => (
            <div key={i} style={{position: 'absolute', left: x ? undefined : 40, right: x ? 40 : undefined, top: y ? undefined : 120,
              bottom: y ? 300 : undefined, width: s, height: s, borderTop: `4px solid ${c}`, borderLeft: `4px solid ${c}`,
              transform: `rotate(${r}deg)`, opacity: 0.75}} />
          ))}
          <svg width={W} height={H} style={{position: 'absolute', opacity: 0.35}}>
            <circle cx={W / 2} cy={H * 0.38} r={W * 0.42} fill="none" stroke={c} strokeWidth={2} strokeDasharray="12 18"
              transform={`rotate(${ring} ${W / 2} ${H * 0.38})`} />
            <circle cx={W / 2} cy={H * 0.38} r={W * 0.36} fill="none" stroke={c} strokeWidth={1} strokeDasharray="4 10"
              transform={`rotate(${-ring * 1.5} ${W / 2} ${H * 0.38})`} />
          </svg>
          <div style={{position: 'absolute', left: 0, right: 0, top: `${((t * 0.12) % 1) * 100}%`, height: 3,
            background: `linear-gradient(90deg, transparent, ${hexA(c, 0.6)}, transparent)`}} />
          <div style={{position: 'absolute', left: 60, top: 70, color: c, fontSize: 26, letterSpacing: 6, fontWeight: 800, opacity: 0.8}}>
            ● LIVE · SCAN
          </div>
        </AbsoluteFill>
      );
    }
    case 'launch': {
      const sweep = (t * 0.35) % 1;
      return (
        <AbsoluteFill style={{pointerEvents: 'none'}}>
          <AbsoluteFill style={{background: `conic-gradient(from ${-30 + sweep * 60}deg at 50% -10%, transparent 0deg, rgba(255,255,255,0.10) 8deg, transparent 16deg)`}} />
          <AbsoluteFill style={{boxShadow: 'inset 0 0 260px rgba(0,0,0,0.85)'}} />
        </AbsoluteFill>
      );
    }
    case 'news': {
      const p = prog(frame, 0, 14, snap);
      return (
        <AbsoluteFill style={{pointerEvents: 'none'}}>
          <div style={{position: 'absolute', left: 50, top: 70, display: 'flex', gap: 14, alignItems: 'center',
            transform: `translateX(${(1 - p) * -300}px)`}}>
            <div style={{background: '#ef4444', color: 'white', fontWeight: 900, fontSize: 30, padding: '8px 18px', borderRadius: 10,
              letterSpacing: 3}}>AI NEWS</div>
            {dateLabel ? <div style={{color: theme.text, fontWeight: 700, fontSize: 28, opacity: 0.85}}>{dateLabel}</div> : null}
          </div>
        </AbsoluteFill>
      );
    }
    case 'terminal':
      return (
        <AbsoluteFill style={{pointerEvents: 'none'}}>
          <div style={{position: 'absolute', left: 50, top: 70, color: theme.accent, fontSize: 30, fontWeight: 800, opacity: 0.85}}>
            {'>_'} <span style={{opacity: Math.floor(t * 2) % 2 ? 1 : 0}}>█</span>
          </div>
        </AbsoluteFill>
      );
    case 'depth': {
      // 2.5D depth layers: near (blurred, fast) and far (sharp, slow) floating shapes
      return (
        <AbsoluteFill style={{pointerEvents: 'none'}}>
          {new Array(7).fill(0).map((_, i) => {
            const near = i % 2 === 0;
            const x = ((i * 0.17 + t * (near ? 0.05 : 0.015)) % 1.2) * W - 100;
            const y = H * (0.1 + ((i * 0.29) % 0.8));
            const s = near ? 140 : 40;
            return <div key={i} style={{position: 'absolute', left: x, top: y, width: s, height: s, borderRadius: near ? 40 : '50%',
              background: hexA(i % 3 ? theme.accent : theme.primary, near ? 0.18 : 0.35), filter: near ? 'blur(14px)' : 'blur(1px)'}} />;
          })}
        </AbsoluteFill>
      );
    }
    case 'glass':
      return (
        <AbsoluteFill style={{pointerEvents: 'none', background: 'linear-gradient(160deg, rgba(255,255,255,0.06), transparent 40%)'}} />
      );
    case 'grid':
      return (
        <AbsoluteFill style={{pointerEvents: 'none', opacity: 0.5,
          backgroundImage: `linear-gradient(${hexA(theme.accent, 0.08)} 1px, transparent 1px), linear-gradient(90deg, ${hexA(theme.accent, 0.08)} 1px, transparent 1px)`,
          backgroundSize: '54px 54px'}} />
      );
    default:
      return null;
  }
};

// ---------------------------------------------------------------- isometric stack visual
const iso = (x: number, y: number, z: number) => ({px: (x - y) * 0.866, py: (x + y) * 0.5 - z});

export const IsoStack: React.FC<{v: Visual; f: number; theme: Theme}> = ({v, f, theme}) => {
  const layers = (Array.isArray(v.layers) ? (v.layers as string[]) : ['Users', 'App', 'API', 'Database']).slice(0, 5);
  const n = layers.length;
  const S = 150; // block half-size
  const Hh = 46; // block height
  const gap = 26;
  const cx = 300;
  const base = 650;
  const colors = [theme.accent, theme.primary, theme.highlight, '#34d399', '#f472b6'];
  return (
    <div style={{position: 'absolute', left: '6%', right: '6%', top: '15.5%', height: '45%'}}>
      <svg viewBox="0 0 950 860" style={{width: '100%', height: '100%'}}>
        {layers.map((label, i) => {
          const p = prog(f, 4 + i * 10, 14, snap);
          const z = i * (Hh + gap) + (1 - clamp(p)) * -160;
          const corners = [iso(-S, -S, z + Hh), iso(S, -S, z + Hh), iso(S, S, z + Hh), iso(-S, S, z + Hh)];
          const top = corners.map((c) => `${cx + c.px},${base + c.py}`).join(' ');
          const l = [iso(-S, S, z + Hh), iso(S, S, z + Hh), iso(S, S, z), iso(-S, S, z)].map((c) => `${cx + c.px},${base + c.py}`).join(' ');
          const r = [iso(S, -S, z + Hh), iso(S, S, z + Hh), iso(S, S, z), iso(S, -S, z)].map((c) => `${cx + c.px},${base + c.py}`).join(' ');
          const col = colors[i % colors.length];
          const lab = iso(S, -S, z + Hh / 2); // right-most corner of the block
          return (
            <g key={i} opacity={clamp(p * 1.5)}>
              <polygon points={l} fill={hexA(col, 0.55)} />
              <polygon points={r} fill={hexA(col, 0.35)} />
              <polygon points={top} fill={hexA(col, 0.9)} stroke="rgba(255,255,255,0.5)" strokeWidth={2} />
              <line x1={cx + lab.px + 8} y1={base + lab.py} x2={cx + lab.px + 60} y2={base + lab.py} stroke={hexA(theme.text, 0.6)} strokeWidth={3} />
              <text x={cx + lab.px + 70} y={base + lab.py + 14} fill={theme.text} fontSize={42} fontWeight={800}>{label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};
