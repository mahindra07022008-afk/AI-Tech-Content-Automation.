import React from 'react';
import {spring, useVideoConfig} from 'remotion';
import {Theme, Visual} from '../types';
import {clamp, glow, hexA, P3, prog, project, ramp, rotX, rotY, seeded, smooth, snap} from '../utils';
import {Icon} from './Icons';

type VP = {v: Visual; f: number; dur: number; theme: Theme; fonts: {display: string; mono: string}; keywords: string[]; fontKind?: string};

const str = (x: unknown, d = '') => (x === undefined || x === null ? d : String(x));
const arr = <T,>(x: unknown): T[] => (Array.isArray(x) ? (x as T[]) : []);

const glass = (theme: Theme, a = 1): React.CSSProperties => ({
  background: `linear-gradient(145deg, rgba(255,255,255,${0.12 * a}), rgba(255,255,255,${0.03 * a}))`,
  border: `2px solid ${hexA(theme.accent, 0.45 * a)}`,
  boxShadow: `0 20px 60px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.15), 0 0 40px ${hexA(theme.accent, 0.15 * a)}`,
  backdropFilter: 'blur(6px)',
  borderRadius: 28,
});

const Box: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
  <div style={{position: 'absolute', left: '6%', right: '6%', top: '15.5%', height: '45%', ...style}}>{children}</div>
);

// ---------------------------------------------------------------- kinetic typography
const Headline: React.FC<VP> = ({v, f, theme, keywords, fontKind}) => {
  const {fps} = useVideoConfig();
  const text = str(v.text ?? v.headline);
  const words = text.split(/\s+/).filter(Boolean);
  const kw = new Set(keywords.map((k) => k.toLowerCase()));
  // monospace / serif glyphs are wider than the display face: scale so long headlines never touch the edges
  const fontScale = fontKind === 'mono' ? 0.78 : fontKind === 'serif' ? 0.92 : 1;
  const size = (text.length > 26 ? 92 : text.length > 16 ? 110 : 128) * fontScale;
  const icon = str(v.icon);
  const isQ = v.type === 'question' || text.trim().endsWith('?');
  return (
    <Box style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center'}}>
      {icon && (
        <div style={{transform: `scale(${spring({frame: f, fps, config: {damping: 11}})}) translateY(${Math.sin(f / 12) * 8}px)`, marginBottom: 40,
          filter: `drop-shadow(0 0 30px ${theme.accent})`}}>
          <Icon name={icon} size={230} color={theme.accent} />
        </div>
      )}
      {isQ && !icon && (
        <div style={{fontSize: 260, fontWeight: 900, color: theme.accent, lineHeight: 1, textShadow: glow(theme.accent, 1.2),
          transform: `scale(${0.9 + 0.08 * Math.sin(f / 6)}) rotate(${Math.sin(f / 20) * 6}deg)`, opacity: prog(f, 0, 12), marginBottom: 20}}>?</div>
      )}
      {/* 84% max width: camera push-in + beat punch can zoom ~1.15×, this keeps zoomed text inside the safe area */}
      <div style={{fontSize: size, fontWeight: 900, lineHeight: 1.08, letterSpacing: -1.5, display: 'flex', flexWrap: 'wrap', justifyContent: 'center',
        gap: '0 26px', maxWidth: '84%'}}>
        {words.map((w, i) => {
          const start = 4 + i * 5;
          const p = prog(f, start, 9, snap);
          const blur = (1 - clamp(prog(f, start, 7))) * 14;
          const isK = kw.has(w.replace(/[?!.,:]/g, '').toLowerCase());
          return (
            <span key={i} style={{display: 'inline-block', opacity: clamp(p * 1.5), transform: `scale(${2.2 - 1.2 * p}) translateY(${(1 - p) * -30}px)`,
              filter: `blur(${blur}px)`, color: isK ? theme.highlight : theme.text, textShadow: isK ? glow(theme.highlight, 0.9) : `0 6px 30px rgba(0,0,0,0.6)`}}>
              {w}
            </span>
          );
        })}
      </div>
      {v.subline ? (
        <div style={{marginTop: 34, fontSize: 52, fontWeight: 700, color: theme.accent, opacity: prog(f, 10 + words.length * 5, 12),
          transform: `translateY(${(1 - prog(f, 10 + words.length * 5, 12)) * 30}px)`, textShadow: glow(theme.accent, 0.5)}}>{str(v.subline)}</div>
      ) : null}
    </Box>
  );
};

// ---------------------------------------------------------------- neural network
const NeuralNet: React.FC<VP> = ({v, f, theme}) => {
  const layers = arr<number>(v.layers).length ? arr<number>(v.layers) : [3, 5, 5, 2];
  const W = 920;
  const H = 820;
  const nodes = layers.map((n, li) => new Array(n).fill(0).map((_, ni) => ({
    x: 80 + (li * (W - 160)) / (layers.length - 1), y: 70 + ((ni + 0.5) * (H - 140)) / n,
  })));
  const edges: {a: {x: number; y: number}; b: {x: number; y: number}; li: number; k: number}[] = [];
  nodes.forEach((layer, li) => {
    if (li < nodes.length - 1) layer.forEach((a) => nodes[li + 1].forEach((b) => edges.push({a, b, li, k: edges.length})));
  });
  return (
    <Box>
      <svg viewBox={`0 0 ${W} ${H + 90}`} style={{width: '100%', height: '100%', overflow: 'visible'}}>
        <defs>
          <filter id="nglow"><feGaussianBlur stdDeviation="6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {edges.map(({a, b, li, k}) => {
          const p = prog(f, 8 + li * 10, 14, smooth);
          return <line key={k} x1={a.x} y1={a.y} x2={a.x + (b.x - a.x) * p} y2={a.y + (b.y - a.y) * p} stroke={hexA(theme.accent, 0.28)} strokeWidth={2.5} />;
        })}
        {edges.filter((_, k) => k % 3 === 0).map(({a, b, k}) => {
          const t = ((f / 30) * 1.2 + seeded('np', k)) % 1;
          const on = f > 40;
          return on ? <circle key={`p${k}`} cx={a.x + (b.x - a.x) * t} cy={a.y + (b.y - a.y) * t} r={6} fill={theme.highlight} filter="url(#nglow)" /> : null;
        })}
        {nodes.map((layer, li) => layer.map((n, ni) => {
          const p = prog(f, li * 10 + ni * 2, 10, snap);
          const pulse = 1 + 0.12 * Math.sin(f / 5 + li + ni);
          return <circle key={`${li}-${ni}`} cx={n.x} cy={n.y} r={22 * p * pulse} fill={li === 0 ? theme.accent : li === layers.length - 1 ? theme.highlight : theme.primary}
            stroke={theme.text} strokeWidth={3} filter="url(#nglow)" />;
        }))}
        <text x={80} y={H + 50} textAnchor="middle" fill={theme.accent} fontSize={44} fontWeight={800} opacity={prog(f, 20, 10)}>{str(v.inputLabel, 'Data')}</text>
        <text x={W - 80} y={H + 50} textAnchor="middle" fill={theme.highlight} fontSize={44} fontWeight={800} opacity={prog(f, 40, 10)}>{str(v.outputLabel, 'Output')}</text>
      </svg>
    </Box>
  );
};

// ---------------------------------------------------------------- charts & stats
const Chart: React.FC<VP> = ({v, f, theme}) => {
  const data = arr<{label: string; value: number; highlight?: boolean}>(v.data);
  const max = Math.max(1, ...data.map((d) => d.value));
  const unit = str(v.unit);
  const kind = str(v.chart, 'bar');
  if (kind === 'line') {
    const W = 900;
    const H = 640;
    const pts = data.map((d, i) => ({x: 60 + (i * (W - 120)) / Math.max(1, data.length - 1), y: H - 60 - (d.value / max) * (H - 160)}));
    const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ');
    const p = prog(f, 6, 40, smooth);
    return (
      <Box>
        <div style={{fontSize: 54, fontWeight: 800, color: theme.text, textAlign: 'center', marginBottom: 20, opacity: prog(f, 0, 10)}}>{str(v.title)}</div>
        <svg viewBox={`0 0 ${W} ${H}`} style={{width: '100%', height: '78%'}}>
          <path d={`${path} L${pts[pts.length - 1]?.x},${H - 60} L60,${H - 60} Z`} fill={hexA(theme.accent, 0.18 * p)} />
          <path d={path} fill="none" stroke={theme.accent} strokeWidth={10} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - p}
            style={{filter: `drop-shadow(0 0 14px ${theme.accent})`}} />
          {pts.map((q, i) => (
            <g key={i} opacity={clamp((p * data.length - i) * 2)}>
              <circle cx={q.x} cy={q.y} r={14} fill={theme.highlight} />
              {v.hideValues ? null : (
                <text x={q.x} y={q.y - 30} textAnchor="middle" fill={theme.text} fontSize={40} fontWeight={800}>{data[i].value}{unit}</text>
              )}
              <text x={q.x} y={H - 10} textAnchor="middle" fill={hexA(theme.text, 0.8)} fontSize={34} fontWeight={700}>{data[i].label}</text>
            </g>
          ))}
        </svg>
      </Box>
    );
  }
  return (
    <Box style={{display: 'flex', flexDirection: 'column'}}>
      <div style={{fontSize: 54, fontWeight: 800, color: theme.text, textAlign: 'center', opacity: prog(f, 0, 10)}}>{str(v.title)}</div>
      <div style={{flex: 1, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', gap: 50, padding: '30px 20px 0'}}>
        {data.map((d, i) => {
          const p = prog(f, 8 + i * 8, 26, ramp);
          const c = d.highlight ? theme.highlight : theme.accent;
          return (
            <div key={i} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', width: `${70 / Math.max(1, data.length)}%`, height: '100%', justifyContent: 'flex-end'}}>
              <div style={{fontSize: 64, fontWeight: 900, color: c, textShadow: glow(c, 0.6), marginBottom: 14}}>{Math.round(d.value * p)}{unit}</div>
              <div style={{width: '100%', height: `${(d.value / max) * 72 * p}%`, borderRadius: '22px 22px 6px 6px',
                background: `linear-gradient(180deg, ${c}, ${hexA(c, 0.35)})`, boxShadow: `0 0 40px ${hexA(c, 0.6)}`}} />
              <div style={{fontSize: 40, fontWeight: 700, color: theme.text, marginTop: 16, textAlign: 'center'}}>{d.label}</div>
            </div>
          );
        })}
      </div>
    </Box>
  );
};

const Stat: React.FC<VP> = ({v, f, theme}) => {
  const value = str(v.value);
  const m = value.match(/^([^\d]*)([\d.,]+)(.*)$/);
  const p = prog(f, 2, 40, ramp);
  let shown = value;
  if (m) {
    const target = parseFloat(m[2].replace(/,/g, ''));
    const dec = m[2].includes('.') ? m[2].split('.')[1].length : 0;
    const n = target * p;
    const body = m[2].includes(',') ? Math.round(n).toLocaleString('en-US') : n.toFixed(dec); // keep thousands separators
    shown = `${m[1]}${body}${m[3]}`;
  }
  const R = 330;
  return (
    <Box style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}}>
      <div style={{position: 'relative', width: R * 2, height: R * 2}}>
        <svg width={R * 2} height={R * 2} style={{position: 'absolute', transform: 'rotate(-90deg)'}}>
          <circle cx={R} cy={R} r={R - 20} stroke="rgba(255,255,255,0.08)" strokeWidth={26} fill="none" />
          <circle cx={R} cy={R} r={R - 20} stroke={theme.accent} strokeWidth={26} fill="none" strokeLinecap="round" pathLength={1}
            strokeDasharray={1} strokeDashoffset={1 - p * clamp(Number(v.ring ?? 1))} style={{filter: `drop-shadow(0 0 18px ${theme.accent})`}} />
        </svg>
        <div style={{position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: shown.length > 6 ? 150 : 190, fontWeight: 900, color: theme.highlight, textShadow: glow(theme.highlight, 1)}}>{shown}</div>
      </div>
      <div style={{fontSize: 56, fontWeight: 800, color: theme.text, marginTop: 30, textAlign: 'center', opacity: prog(f, 20, 12),
        transform: `translateY(${(1 - prog(f, 20, 12)) * 30}px)`}}>{str(v.label)}</div>
    </Box>
  );
};

// ---------------------------------------------------------------- tech interfaces
const ChatUI: React.FC<VP> = ({v, f, theme}) => {
  const msgs = arr<{from: string; text: string}>(v.messages);
  let t0 = 6;
  return (
    <Box style={{display: 'flex', justifyContent: 'center'}}>
      <div style={{...glass(theme), width: '82%', height: '100%', padding: 40, display: 'flex', flexDirection: 'column', gap: 26,
        transform: `rotateY(${-8 + 6 * prog(f, 0, 60, smooth)}deg) rotateX(6deg)`, transformStyle: 'preserve-3d'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 18, marginBottom: 10}}>
          <div style={{width: 64, height: 64, borderRadius: 32, background: theme.primary, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <Icon name="ai" size={44} color={theme.text} />
          </div>
          <div style={{fontSize: 40, fontWeight: 800, color: theme.text}}>{str(v.title, 'AI Assistant')}</div>
        </div>
        {msgs.map((m, i) => {
          const ai = m.from !== 'user';
          const start = t0;
          const typing = ai ? 16 : 0;
          const chars = Math.max(0, Math.floor((f - start - typing) * 1.6));
          t0 += typing + Math.ceil(m.text.length / 1.6) + 10;
          const appear = prog(f, start, 8, snap);
          if (f < start) return null;
          return (
            <div key={i} style={{alignSelf: ai ? 'flex-start' : 'flex-end', maxWidth: '82%', padding: '22px 28px', borderRadius: 28,
              background: ai ? 'rgba(255,255,255,0.1)' : `linear-gradient(135deg, ${theme.primary}, ${theme.accent})`,
              color: theme.text, fontSize: 40, fontWeight: 600, lineHeight: 1.3, transform: `scale(${appear})`,
              transformOrigin: ai ? 'left bottom' : 'right bottom'}}>
              {ai && f < start + typing ? <span style={{letterSpacing: 6}}>{'•'.repeat(1 + (Math.floor(f / 5) % 3))}</span> : m.text.slice(0, ai ? chars : undefined)}
            </div>
          );
        })}
      </div>
    </Box>
  );
};

const Code: React.FC<VP> = ({v, f, theme, fonts}) => {
  const lines = arr<string>(v.lines);
  const suggestion = arr<string>(v.suggestion);
  // Auto-fit: monospace glyphs are ~0.6em wide; keep the longest line (+2-char gutter) inside the
  // panel's ~776px text area (with margin for the 3D tilt) so code is never clipped.
  const longest = Math.max(1, ...[...lines, ...suggestion].map((l) => l.length));
  const fs = Math.min(46, Math.floor(776 / ((longest + 2) * 0.6)));
  let budget = Math.max(0, (f - 8) * 1.4);
  const accepted = f > 8 + (lines.join('').length / 1.4) + 30;
  return (
    <Box style={{display: 'flex', justifyContent: 'center', alignItems: 'center'}}>
      <div style={{...glass(theme), width: '96%', padding: '30px 34px', fontFamily: fonts.mono,
        transform: `rotateX(${14 - 10 * prog(f, 0, 60, smooth)}deg) rotateY(-10deg)`, transformStyle: 'preserve-3d'}}>
        <div style={{display: 'flex', gap: 14, marginBottom: 26}}>
          {['#ff5f56', '#ffbd2e', '#27c93f'].map((c) => <div key={c} style={{width: 22, height: 22, borderRadius: 11, background: c}} />)}
          <div style={{marginLeft: 20, color: hexA(theme.text, 0.6), fontSize: 34, fontFamily: fonts.display, overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1}}>{str(v.filename, 'main.py')}</div>
        </div>
        {lines.map((line, i) => {
          const shown = line.slice(0, Math.max(0, Math.floor(budget)));
          budget -= line.length + 3;
          const comment = line.trim().startsWith('#') || line.trim().startsWith('//');
          return (
            <div key={i} style={{fontSize: fs, lineHeight: 1.55, color: comment ? '#94a3b8' : theme.text, whiteSpace: 'pre'}}>
              <span style={{color: hexA(theme.text, 0.3), marginRight: 24}}>{String(i + 1).padStart(2, ' ')}</span>{shown}
              {budget > -line.length - 3 && budget <= 0 && Math.floor(f / 8) % 2 === 0 ? <span style={{background: theme.highlight}}>&nbsp;</span> : null}
            </div>
          );
        })}
        {suggestion.map((line, i) => (
          <div key={`s${i}`} style={{fontSize: fs, lineHeight: 1.55, whiteSpace: 'pre', color: accepted ? theme.accent : hexA(theme.text, 0.35),
            opacity: budget > 0 ? 1 : 0, textShadow: accepted ? glow(theme.accent, 0.4) : undefined}}>
            <span style={{color: hexA(theme.text, 0.3), marginRight: 24}}>{String(lines.length + i + 1).padStart(2, ' ')}</span>{line}
          </div>
        ))}
        {suggestion.length > 0 && budget > 0 && (
          <div style={{marginTop: 22, fontSize: 36, color: accepted ? theme.highlight : hexA(theme.text, 0.6), fontFamily: fonts.display, fontWeight: 700}}>
            {accepted ? '✓ AI suggestion accepted' : 'AI suggestion · press Tab'}
          </div>
        )}
      </div>
    </Box>
  );
};

// ---------------------------------------------------------------- diagrams
const Flow: React.FC<VP> = ({v, f, theme}) => {
  const nodes = arr<string | {label: string; icon?: string}>(v.nodes).map((n) => (typeof n === 'string' ? {label: n} : n));
  const n = Math.max(1, nodes.length);
  return (
    <Box style={{display: 'flex', flexDirection: 'column', justifyContent: 'space-between', alignItems: 'center'}}>
      {nodes.map((node, i) => {
        const p = prog(f, i * 14, 12, snap);
        const beam = prog(f, i * 14 + 8, 10, smooth);
        const travel = ((f - i * 14) / 24) % 1;
        return (
          <React.Fragment key={i}>
            <div style={{...glass(theme, p), width: '78%', minHeight: 130, display: 'flex', alignItems: 'center', gap: 30, padding: '0 40px',
              transform: `scale(${p}) translateZ(${(1 - p) * -200}px)`, opacity: clamp(p * 1.4)}}>
              <Icon name={node.icon ?? ['spark', 'brain', 'check', 'rocket', 'star'][i % 5]} size={76} color={i === n - 1 ? theme.highlight : theme.accent} />
              <div style={{fontSize: 52, fontWeight: 800, color: theme.text}}>{node.label}</div>
            </div>
            {i < n - 1 && (
              <div style={{position: 'relative', width: 10, flex: 1, minHeight: 30}}>
                <div style={{position: 'absolute', inset: 0, background: hexA(theme.accent, 0.5), transform: `scaleY(${beam})`, transformOrigin: 'top', borderRadius: 5}} />
                {beam >= 1 && <div style={{position: 'absolute', left: -8, top: `${travel * 100}%`, width: 26, height: 26, borderRadius: 13,
                  background: theme.highlight, boxShadow: `0 0 24px ${theme.highlight}`}} />}
              </div>
            )}
          </React.Fragment>
        );
      })}
    </Box>
  );
};

const Timeline: React.FC<VP> = ({v, f, theme}) => {
  const ev = arr<{year: string; label: string}>(v.events);
  const line = prog(f, 0, 10 + ev.length * 10, smooth);
  return (
    <Box>
      <div style={{position: 'absolute', left: '24%', top: 0, bottom: 0, width: 10, background: hexA(theme.accent, 0.8), transform: `scaleY(${line})`,
        transformOrigin: 'top', borderRadius: 5, boxShadow: `0 0 20px ${theme.accent}`}} />
      {ev.map((e, i) => {
        const p = prog(f, 6 + i * 10, 12, snap);
        const top = `${((i + 0.5) / ev.length) * 100}%`;
        return (
          <div key={i} style={{position: 'absolute', top, left: 0, right: 0, display: 'flex', alignItems: 'center', transform: `translateY(-50%) translateX(${(1 - p) * 80}px)`, opacity: clamp(p)}}>
            <div style={{width: '21%', textAlign: 'right', fontSize: 58, fontWeight: 900, color: theme.highlight, textShadow: glow(theme.highlight, 0.5)}}>{e.year}</div>
            <div style={{width: 46, height: 46, borderRadius: 23, margin: '0 30px 0 2.6%', background: theme.highlight, boxShadow: `0 0 26px ${theme.highlight}`}} />
            <div style={{flex: 1, fontSize: 48, fontWeight: 700, color: theme.text}}>{e.label}</div>
          </div>
        );
      })}
    </Box>
  );
};

const IconGrid: React.FC<VP> = ({v, f, theme}) => {
  const items = arr<{icon: string; label: string}>(v.items).slice(0, 6);
  return (
    <Box style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 36, perspective: 1200}}>
      {items.map((it, i) => {
        const p = prog(f, i * 7, 12, snap);
        const bob = Math.sin(f / 14 + i * 1.3) * 10;
        return (
          <div key={i} style={{...glass(theme, p), display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 18,
            transform: `translateY(${bob}px) rotateY(${(i % 2 ? -1 : 1) * (14 - 14 * p + 6)}deg) rotateX(6deg) scale(${p})`, opacity: clamp(p)}}>
            <Icon name={it.icon} size={130} color={i % 3 === 2 ? theme.highlight : theme.accent} style={{filter: `drop-shadow(0 0 18px ${theme.accent})`}} />
            <div style={{fontSize: 44, fontWeight: 800, color: theme.text, textAlign: 'center', padding: '0 16px'}}>{it.label}</div>
          </div>
        );
      })}
    </Box>
  );
};

const Bullets: React.FC<VP> = ({v, f, theme}) => {
  const items = arr<string>(v.items);
  return (
    <Box style={{display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 34, left: '10%', right: '8%'}}>
      {items.map((it, i) => {
        const p = prog(f, i * 10, 12, snap);
        return (
          <div key={i} style={{...glass(theme, p), display: 'flex', alignItems: 'center', gap: 28, padding: '26px 34px',
            transform: `translateX(${(1 - p) * -160}px)`, opacity: clamp(p)}}>
            <Icon name="check" size={64} color={theme.highlight} />
            <div style={{fontSize: 50, fontWeight: 800, color: theme.text}}>{it}</div>
          </div>
        );
      })}
    </Box>
  );
};

const Compare: React.FC<VP> = ({v, f, theme}) => {
  const sides = [v.left as {title: string; points: string[]}, v.right as {title: string; points: string[]}];
  return (
    <Box style={{display: 'flex', flexDirection: 'column', gap: 40}}>
      {sides.map((s, i) => {
        const p = prog(f, i * 12, 14, snap);
        return (
          <div key={i} style={{...glass(theme, p), flex: 1, padding: 34, transform: `translateX(${(1 - p) * (i ? 200 : -200)}px)`, opacity: clamp(p)}}>
            <div style={{fontSize: 56, fontWeight: 900, color: i ? theme.highlight : theme.accent}}>{s?.title}</div>
            {(s?.points ?? []).slice(0, 3).map((pt, j) => <div key={j} style={{fontSize: 42, color: theme.text, marginTop: 14}}>• {pt}</div>)}
          </div>
        );
      })}
    </Box>
  );
};

const BranchGraph: React.FC<VP> = ({v, f, theme}) => {
  const p = prog(f, 0, 60, smooth);
  const labels = (v.labels as Record<string, string>) ?? {};
  const mainX = 330;
  const featX = 640;
  const ys = [80, 230, 380, 530, 680, 820];
  return (
    <Box>
      <svg viewBox="0 0 960 900" style={{width: '100%', height: '100%'}}>
        <line x1={mainX} y1={ys[0]} x2={mainX} y2={ys[0] + (ys[5] - ys[0]) * p} stroke={theme.accent} strokeWidth={14} strokeLinecap="round" />
        <path d={`M${mainX},${ys[1]} C${featX},${ys[1] + 40} ${featX},${ys[2]} ${featX},${ys[2]} L${featX},${ys[3]} C${featX},${ys[4] - 40} ${mainX},${ys[4] - 20} ${mainX},${ys[4]}`}
          fill="none" stroke={theme.highlight} strokeWidth={12} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - prog(f, 12, 50, smooth)} />
        {ys.map((y, i) => <circle key={i} cx={mainX} cy={y} r={30 * prog(f, i * 8, 10, snap)} fill={theme.accent} stroke={theme.text} strokeWidth={5} />)}
        {[ys[2], ys[3]].map((y, i) => <circle key={`f${i}`} cx={featX} cy={y} r={30 * prog(f, 26 + i * 10, 10, snap)} fill={theme.highlight} stroke={theme.text} strokeWidth={5} />)}
        <text x={mainX - 60} y={ys[0] + 14} textAnchor="end" fill={theme.accent} fontSize={46} fontWeight={800}>{labels.main ?? 'main'}</text>
        <text x={featX + 60} y={ys[2] + 14} fill={theme.highlight} fontSize={46} fontWeight={800} opacity={prog(f, 26, 10)}>{labels.feature ?? 'feature'}</text>
        <text x={mainX - 60} y={ys[4] + 14} textAnchor="end" fill={theme.text} fontSize={46} fontWeight={800} opacity={prog(f, 50, 10)}>{labels.merge ?? 'merge'}</text>
      </svg>
    </Box>
  );
};

// ---------------------------------------------------------------- code-driven 3D
const Globe: React.FC<VP> = ({v, f, theme}) => {
  const N = 420;
  const R = 360;
  const a = f / 30 * 0.45;
  const pts: {x: number; y: number; s: number; z: number; i: number}[] = [];
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const th = i * 2.399963;
    const p: P3 = {x: Math.cos(th) * r * R, y: y * R, z: Math.sin(th) * r * R};
    const q = rotX(rotY(p, a), -0.35);
    const pr = project(q, 1100, 480, 450);
    pts.push({...pr, z: q.z, i});
  }
  pts.sort((m, n) => n.z - m.z);
  const pings = [17, 133, 260, 341, 77];
  const appear = prog(f, 0, 18, snap);
  return (
    <Box>
      <svg viewBox="0 0 960 960" style={{width: '100%', height: '100%', transform: `scale(${appear})`}}>
        <circle cx={480} cy={450} r={R * 1.02} fill={hexA(theme.primary, 0.12)} stroke={hexA(theme.accent, 0.35)} strokeWidth={3} />
        {pts.map((p) => {
          const front = p.z < 0;
          const hot = pings.includes(p.i);
          const r = (hot ? 10 : 4.2) * p.s;
          return <circle key={p.i} cx={p.x} cy={p.y} r={r} fill={hot ? theme.highlight : theme.accent} opacity={front ? (hot ? 1 : 0.85) : 0.18} />;
        })}
        <text x={480} y={920} textAnchor="middle" fill={theme.text} fontSize={50} fontWeight={800} opacity={prog(f, 12, 10)}>{str(v.label)}</text>
      </svg>
    </Box>
  );
};

const Molecule: React.FC<VP> = ({v, f, theme}) => {
  // Protein-like backbone: helix + coil, rotating in 3D with depth-sorted atoms (perspective projection).
  const N = 90;
  const atoms: P3[] = [];
  for (let i = 0; i < N; i++) {
    const t = i / N;
    const helix = i < 50;
    const ang = i * (helix ? 0.62 : 0.31);
    const rad = helix ? 120 : 220 + 40 * Math.sin(i * 0.4);
    atoms.push({x: Math.cos(ang) * rad + (helix ? -90 : 80), y: -330 + t * 660, z: Math.sin(ang) * rad + 30 * Math.sin(i * 1.7)});
  }
  const a = f / 30 * 0.7;
  const proj = atoms.map((p, i) => {
    const q = rotX(rotY(p, a), 0.25);
    return {...project(q, 1200, 480, 470), z: q.z, i};
  });
  const built = Math.floor(prog(f, 0, 45, smooth) * N);
  const order = [...proj].sort((m, n) => n.z - m.z);
  return (
    <Box>
      <svg viewBox="0 0 960 980" style={{width: '100%', height: '100%'}}>
        {proj.slice(0, built).map((p, i) => (i > 0 ? (
          <line key={`b${i}`} x1={proj[i - 1].x} y1={proj[i - 1].y} x2={p.x} y2={p.y} stroke={hexA(i < 50 ? theme.accent : theme.highlight, 0.7)} strokeWidth={8 * p.s} strokeLinecap="round" />
        ) : null))}
        {order.filter((p) => p.i < built).map((p) => (
          <circle key={p.i} cx={p.x} cy={p.y} r={15 * p.s} fill={p.i < 50 ? theme.accent : theme.highlight} opacity={0.55 + 0.45 * clamp((300 - p.z) / 600)}
            style={{filter: `drop-shadow(0 0 ${8 * p.s}px ${theme.accent})`}} />
        ))}
        <text x={480} y={960} textAnchor="middle" fill={theme.text} fontSize={48} fontWeight={800} opacity={prog(f, 20, 10)}>{str(v.label)}</text>
      </svg>
    </Box>
  );
};

const Outro: React.FC<VP> = ({v, f, theme}) => {
  const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 10}});
  return (
    <Box style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center'}}>
      <div style={{transform: `scale(${s}) rotate(${Math.sin(f / 10) * 4}deg)`, filter: `drop-shadow(0 0 40px ${theme.highlight})`}}>
        <Icon name={str(v.icon, 'rocket')} size={260} color={theme.highlight} />
      </div>
      <div style={{fontSize: 88, fontWeight: 900, color: theme.text, marginTop: 40, textShadow: glow(theme.accent, 0.6), opacity: prog(f, 8, 12),
        transform: `translateY(${(1 - prog(f, 8, 12, snap)) * 40}px)`}}>{str(v.cta)}</div>
    </Box>
  );
};

const REGISTRY: Record<string, React.FC<VP>> = {
  headline: Headline, question: Headline, title: Headline, neural_net: NeuralNet, chart: Chart, stat: Stat,
  chat_ui: ChatUI, code: Code, flow: Flow, timeline: Timeline, icon_grid: IconGrid, bullets: Bullets,
  compare: Compare, branch_graph: BranchGraph, globe: Globe, molecule: Molecule, outro: Outro,
};

export const VISUAL_TYPES = Object.keys(REGISTRY);

export const VisualView: React.FC<VP> = (props) => {
  const C = REGISTRY[props.v.type] ?? Headline;
  return <C {...props} />;
};

