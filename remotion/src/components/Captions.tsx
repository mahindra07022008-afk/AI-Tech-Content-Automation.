import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {CaptionStyle, Theme, Word} from '../types';
import {clamp, glow, prog, snap} from '../utils';

// Solid dark outline from layered shadows (text-stroke + paint-order is not reliable in headless Chrome).
const outline = (r: number) =>
  [0, 45, 90, 135, 180, 225, 270, 315]
    .map((a) => `${(Math.cos((a * Math.PI) / 180) * r).toFixed(1)}px ${(Math.sin((a * Math.PI) / 180) * r).toFixed(1)}px 0 rgba(0,0,0,0.92)`)
    .join(', ');

// Word-by-word animated Roman-Telugu captions with highlighted technical keywords.
// Pages (groups of ≤ maxWords) are built in Python so timing and layout checks share one source.
type Page = {words: Word[]; start: number; end: number};

export const buildPages = (words: Word[], maxWords: number): Page[] => {
  const pages: Page[] = [];
  let cur: Word[] = [];
  const flush = () => {
    if (cur.length) pages.push({words: cur, start: cur[0].start, end: cur[cur.length - 1].end});
    cur = [];
  };
  words.forEach((w, i) => {
    if (cur.length && (cur[0].scene !== w.scene)) flush();
    cur.push(w);
    if (w.pageEnd || cur.length >= maxWords || /[.!?,]$/.test(w.text) || i === words.length - 1) flush();
  });
  for (let i = 0; i < pages.length; i++) {
    const next = pages[i + 1];
    pages[i].end = next ? Math.min(next.start, pages[i].end + 0.6) : pages[i].end + 0.6;
  }
  return pages;
};

export const Captions: React.FC<{words: Word[]; style: CaptionStyle; theme: Theme; font: string}> = ({words, style, theme, font}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const t = frame / fps;
  const pages = React.useMemo(() => buildPages(words, style.maxWords), [words, style.maxWords]);
  const page = pages.find((p) => t >= p.start && t < p.end);
  if (!page) return null;
  const pf = Math.round(page.start * fps);
  const enter = prog(frame, pf, 6, snap);
  const scale = width / 1080;
  return (
    <div style={{position: 'absolute', left: width * 0.07, width: width * 0.8, top: height * style.position, transform: `translateY(-50%) scale(${0.9 + 0.1 * enter})`,
      display: 'flex', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'center', gap: `${12 * scale}px ${30 * scale}px`, fontFamily: font,
      fontSize: style.fontSize * scale, fontWeight: 900, lineHeight: 1.12, textAlign: 'center', opacity: clamp(enter * 1.5)}}>
      {page.words.map((w, i) => {
        const wf = Math.round(w.start * fps);
        const active = t >= w.start && t < w.end + 0.05;
        const spoken = t >= w.start;
        const pop = prog(frame, wf, 5, snap);
        const color = w.keyword ? theme.accent : active ? theme.highlight : theme.text;
        const text = style.uppercase ? w.text.toUpperCase() : w.text;
        return (
          <span key={i} style={{display: 'inline-block', color, opacity: style.template === 'karaoke_line' ? (spoken ? 1 : 0.45) : spoken ? 1 : 0,
            transform: `scale(${spoken ? (active ? 1.06 : 1) * (0.7 + 0.3 * pop) : 0.7}) translateY(${(1 - pop) * 18 * scale}px)`,
            textShadow: `${outline(4 * scale)}, ${w.keyword ? glow(theme.accent, 0.7) : active ? glow(theme.highlight, 0.45) : '0 8px 22px rgba(0,0,0,0.9)'}`}}>
            {text}
          </span>
        );
      })}
    </div>
  );
};
