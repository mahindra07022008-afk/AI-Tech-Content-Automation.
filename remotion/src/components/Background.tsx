import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Theme} from '../types';
import {hexA, seeded} from '../utils';

// Scene-specific animated backgrounds. `px`,`py` = parallax offset from the camera (moves slower than foreground).
export const Background: React.FC<{variant: string; theme: Theme; seed: number; px: number; py: number}> = ({
  variant, theme, seed, px, py,
}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps} = useVideoConfig();
  const t = frame / fps;
  const base = (
    <AbsoluteFill style={{background: `linear-gradient(170deg, ${theme.bgTop} 0%, ${theme.bgBottom} 100%)`}} />
  );
  const blobs = (
    <AbsoluteFill style={{transform: `translate(${px * 0.5}px, ${py * 0.5}px) scale(1.15)`}}>
      {[0, 1, 2].map((i) => {
        const c = [theme.primary, theme.accent, theme.highlight][i];
        const x = 50 + 30 * Math.sin(t * 0.25 + i * 2.1 + seed);
        const y = 35 + 25 * Math.cos(t * 0.2 + i * 1.7 + seed);
        return (
          <div key={i} style={{
            position: 'absolute', left: `${x}%`, top: `${y}%`, width: W * 0.9, height: W * 0.9, marginLeft: -W * 0.45,
            marginTop: -W * 0.45, borderRadius: '50%', background: `radial-gradient(circle, ${hexA(c, i === 2 ? 0.14 : 0.32)} 0%, transparent 65%)`,
            filter: 'blur(30px)',
          }} />
        );
      })}
    </AbsoluteFill>
  );
  const particles = (n: number, speed: number, depth: boolean) => (
    <AbsoluteFill style={{transform: `translate(${px * 0.8}px, ${py * 0.8}px)`}}>
      {new Array(n).fill(0).map((_, i) => {
        const z = seeded(seed + 'z', i);
        const size = depth ? 2 + z * 9 : 2 + z * 3;
        const x = (seeded(seed + 'x', i) * W + Math.sin(t * 0.5 + i) * 20) % W;
        const y = ((seeded(seed + 'y', i) * H - t * speed * (0.4 + z) * 60) % H + H) % H;
        const tw = 0.35 + 0.45 * Math.abs(Math.sin(t * (0.8 + z) + i));
        return (
          <div key={i} style={{
            position: 'absolute', left: x, top: y, width: size, height: size, borderRadius: '50%',
            background: i % 5 === 0 ? theme.highlight : theme.accent, opacity: tw * (depth ? 0.4 + z * 0.6 : 0.6),
            filter: depth && z < 0.35 ? 'blur(2px)' : undefined, boxShadow: `0 0 ${size * 2}px ${theme.accent}`,
          }} />
        );
      })}
    </AbsoluteFill>
  );

  if (variant === 'grid') {
    // Perspective tech floor scrolling toward the camera.
    return (
      <AbsoluteFill>
        {base}
        {blobs}
        <AbsoluteFill style={{perspective: 700, transform: `translate(${px}px, ${py * 0.6}px)`}}>
          <div style={{
            position: 'absolute', left: '-50%', width: '200%', top: '55%', height: '90%', transformOrigin: 'top center',
            transform: 'rotateX(72deg)',
            backgroundImage: `linear-gradient(${hexA(theme.accent, 0.45)} 2px, transparent 2px), linear-gradient(90deg, ${hexA(theme.accent, 0.45)} 2px, transparent 2px)`,
            backgroundSize: '90px 90px', backgroundPosition: `0px ${(t * 120) % 90}px`,
            maskImage: 'linear-gradient(to bottom, transparent 0%, black 30%, black 70%, transparent 100%)',
          }} />
          <div style={{position: 'absolute', left: 0, right: 0, top: '53%', height: 6, background: theme.accent, filter: 'blur(10px)', opacity: 0.8}} />
        </AbsoluteFill>
        {particles(24, 0.6, true)}
      </AbsoluteFill>
    );
  }
  if (variant === 'circuit') {
    const lines = new Array(14).fill(0).map((_, i) => {
      const y = seeded(seed + 'cy', i) * H;
      const x0 = seeded(seed + 'cx', i) * W * 0.4;
      const len = W * (0.4 + seeded(seed + 'cl', i) * 0.5);
      return {y, x0, len, i};
    });
    return (
      <AbsoluteFill>
        {base}
        {blobs}
        <svg width={W} height={H} style={{position: 'absolute', transform: `translate(${px * 0.7}px, ${py * 0.7}px)`}}>
          {lines.map(({y, x0, len, i}) => {
            const pulse = ((t * 0.35 + seeded(seed + 'cp', i)) % 1) * len;
            return (
              <g key={i}>
                <path d={`M${x0} ${y} h${len * 0.5} l40 40 h${len * 0.5}`} stroke={hexA(theme.accent, 0.18)} strokeWidth={3} fill="none" />
                <circle cx={x0 + Math.min(pulse, len * 0.5)} cy={y} r={6} fill={theme.accent} opacity={0.9} style={{filter: `drop-shadow(0 0 10px ${theme.accent})`}} />
                <circle cx={x0} cy={y} r={7} fill="none" stroke={hexA(theme.accent, 0.4)} strokeWidth={3} />
              </g>
            );
          })}
        </svg>
      </AbsoluteFill>
    );
  }
  if (variant === 'dots') {
    const cols = 18;
    const rows = 32;
    return (
      <AbsoluteFill>
        {base}
        {blobs}
        <svg width={W} height={H} style={{position: 'absolute', transform: `translate(${px * 0.6}px, ${py * 0.6}px)`}}>
          {new Array(cols * rows).fill(0).map((_, k) => {
            const c = k % cols;
            const r = Math.floor(k / cols);
            const wave = 0.5 + 0.5 * Math.sin(t * 2 - (c + r) * 0.35);
            return <circle key={k} cx={(c + 0.5) * (W / cols)} cy={(r + 0.5) * (H / rows)} r={2 + wave * 2} fill={theme.accent} opacity={0.06 + wave * 0.18} />;
          })}
        </svg>
      </AbsoluteFill>
    );
  }
  if (variant === 'space') {
    return (
      <AbsoluteFill>
        <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 40%, ${theme.bgBottom} 0%, #03050d 75%)`}} />
        {blobs}
        {particles(70, 0.15, true)}
      </AbsoluteFill>
    );
  }
  if (variant === 'particles') {
    return (
      <AbsoluteFill>
        {base}
        {blobs}
        {particles(48, 0.5, true)}
      </AbsoluteFill>
    );
  }
  // aurora (default)
  return (
    <AbsoluteFill>
      {base}
      {blobs}
      <AbsoluteFill style={{
        background: `conic-gradient(from ${t * 20}deg at 50% 120%, transparent 0deg, ${hexA(theme.primary, 0.35)} 60deg, transparent 120deg, ${hexA(theme.accent, 0.25)} 200deg, transparent 260deg)`,
        filter: 'blur(60px)', transform: `translate(${px * 0.4}px, ${py * 0.4}px)`,
      }} />
      {particles(26, 0.4, true)}
    </AbsoluteFill>
  );
};
