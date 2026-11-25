import React from 'react';
import {AbsoluteFill, continueRender, delayRender, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {Background} from './components/Background';
import {cameraTransform} from './components/Camera';
import {Captions} from './components/Captions';
import {IsoStack, StyleOverlay} from './components/Overlays';
import {PixelScene} from './components/Pixel';
import {Phone3D} from './components/ThreeD';
import {VisualView} from './components/Visuals';
import {BACKGROUND_FOR, CAMERA_FOR} from './presets/styles';
import {resolveTransition, transitionStyles} from './presets/transitions';
import {Props, Scene} from './types';
import {clamp, hexA, prog} from './utils';

const FONT_FILES: Record<string, string> = {
  TTDisplay: 'fonts/NotoSansDisplay-Bold.ttf',
  TTTelugu: 'fonts/NotoSansTelugu-Bold.ttf',
  TTMono: 'fonts/NotoSansMono-Bold.ttf',
  TTSerif: 'fonts/NotoSerifDisplay-Bold.ttf',
};

// Style typography: display (default), serif (documentary), mono (code / HUD / pixel). Telugu glyphs fall back to TTTelugu.
export const fontStack = (p: Props) => {
  const lead = p.style.font === 'serif' ? 'TTSerif' : p.style.font === 'mono' ? p.fonts.mono : p.fonts.display;
  return `${lead}, ${p.fonts.telugu}, sans-serif`;
};

const useFonts = () => {
  const [handle] = React.useState(() => delayRender('fonts'));
  React.useEffect(() => {
    Promise.all(Object.entries(FONT_FILES).map(async ([family, file]) => {
      const face = new FontFace(family, `url(${staticFile(file)})`);
      await face.load();
      (document.fonts as unknown as {add: (f: FontFace) => void}).add(face);
    })).then(() => continueRender(handle)).catch((e) => {
      console.error('font load failed', e);
      continueRender(handle);
    });
  }, [handle]);
};

const SECTION_TAG: Record<string, string> = {
  background: 'THE STORY', turning_point: 'TURNING POINT', explanation: 'HOW IT WORKS', example: 'REAL EXAMPLE', conclusion: 'TAKEAWAY',
};

const SceneView: React.FC<{scene: Scene; next?: Scene; index: number; p: Props; sceneFrames: number}> = ({scene, next, index, p, sceneFrames}) => {
  const frame = useCurrentFrame(); // local to the Sequence
  const {fps} = useVideoConfig();
  const tr = Math.round(p.style.transitionSeconds * fps);
  const keywords = (scene.visual.keywords as string[] | undefined) ?? [];
  const beatsInScene = p.beats.filter((b) => b >= scene.start && b < scene.end && Math.round(b * p.style.bpm / 60) % 4 === 0);
  const cam = cameraTransform(scene.camera || CAMERA_FOR[scene.visual.type] || 'push_in', frame, sceneFrames, fps, p.style, beatsInScene, scene.start);

  // incoming transition (first tr frames) and outgoing (frames after the scene's own end, while the next scene enters)
  const inName = resolveTransition(scene.transition);
  const inP = index === 0 ? 1 : prog(frame, 0, tr);
  const incoming = index === 0 ? {} : transitionStyles(inName, inP, frame, p.style.motionBlur).incoming;
  const inBlur = index === 0 ? 0 : transitionStyles(inName, inP, frame, p.style.motionBlur).blurX;
  let outgoing: React.CSSProperties = {};
  let outBlur = 0;
  if (next && frame >= sceneFrames) {
    const op = prog(frame, sceneFrames, tr);
    const ts = transitionStyles(resolveTransition(next.transition), op, frame, p.style.motionBlur);
    outgoing = ts.outgoing;
    outBlur = ts.blurX;
  }
  const blurX = Math.max(inBlur, outBlur);
  const filterId = `whip-${index}`;
  const style: React.CSSProperties = {...incoming, ...outgoing};
  if (blurX > 0.5) style.filter = `${style.filter ?? ''} url(#${filterId})`.trim();
  const tag = scene.tag ?? SECTION_TAG[scene.section];
  const tagP = prog(frame, 6, 10);
  // light sweep on hooks / turning points
  const sweep = (scene.section === 'hook' || scene.section === 'turning_point') ? prog(frame, 4, 22) : 1;
  // simulated depth of field: defocused background + a short rack-focus on the subject at scene start
  const dof = !!p.style.dof;
  const rack = dof && index > 0 ? (1 - prog(frame, 0, 12)) * 6 : 0;
  const lite = p.profile === 'lite';
  const vt = scene.visual.type;
  const visual =
    vt === 'phone3d' ? <Phone3D v={scene.visual} f={frame} dur={sceneFrames} theme={p.theme} lite={lite} fps={fps} />
      : vt === 'pixel_scene' ? <PixelScene v={scene.visual} f={frame} theme={p.theme} lite={lite} />
        : vt === 'iso_stack' ? <IsoStack v={scene.visual} f={frame} theme={p.theme} />
          : <VisualView v={scene.visual} f={frame} dur={sceneFrames} theme={p.theme} fonts={{display: p.fonts.display, mono: p.fonts.mono}}
              keywords={keywords} fontKind={p.style.font} />;
  return (
    <AbsoluteFill style={style}>
      <svg width={0} height={0} style={{position: 'absolute'}}>
        <filter id={filterId} x="-20%" y="0%" width="140%" height="100%">
          <feGaussianBlur stdDeviation={`${blurX} 0`} />
        </filter>
      </svg>
      <AbsoluteFill style={{filter: dof ? 'blur(3px)' : undefined, transform: dof ? 'scale(1.03)' : undefined}}>
        <Background variant={scene.background || BACKGROUND_FOR[scene.visual.type] || 'aurora'} theme={p.theme} seed={index * 7 + 3} px={cam.px} py={cam.py} />
      </AbsoluteFill>
      <AbsoluteFill style={{transform: cam.transform, transformOrigin: '50% 38%', filter: rack > 0.2 ? `blur(${rack.toFixed(2)}px)` : undefined}}>
        {visual}
      </AbsoluteFill>
      {vt === 'outro' && p.channel ? (
        <div style={{position: 'absolute', top: '56%', width: '100%', textAlign: 'center', fontSize: 50, fontWeight: 900, color: p.theme.accent,
          opacity: prog(frame, 16, 12), letterSpacing: 2}}>{p.channel}</div>
      ) : null}
      {tag && (
        <div style={{position: 'absolute', top: '7.5%', width: '100%', display: 'flex', justifyContent: 'center', opacity: tagP * clamp(1 - (frame - sceneFrames) / 6)}}>
          <div style={{padding: '12px 30px', borderRadius: 40, background: hexA(p.theme.primary, 0.85), color: p.theme.text, fontSize: 32, fontWeight: 900,
            letterSpacing: 4, border: `2px solid ${hexA(p.theme.accent, 0.6)}`, transform: `translateY(${(1 - tagP) * -20}px)`}}>{tag}</div>
        </div>
      )}
      {sweep < 1 && (
        <AbsoluteFill style={{background: `linear-gradient(105deg, transparent ${sweep * 140 - 40}%, rgba(255,255,255,0.18) ${sweep * 140 - 25}%, transparent ${sweep * 140 - 10}%)`}} />
      )}
    </AbsoluteFill>
  );
};

export const Main: React.FC<Props> = (p) => {
  useFonts();
  const {fps} = useVideoConfig();
  const tr = Math.round(p.style.transitionSeconds * fps);
  const font = fontStack(p);
  const capFont = p.style.caption.template === 'pixel_block' ? `${p.fonts.mono}, ${p.fonts.telugu}, sans-serif` : `${p.fonts.display}, ${p.fonts.telugu}, sans-serif`;
  return (
    <AbsoluteFill style={{background: p.theme.bgTop, fontFamily: font, color: p.theme.text}}>
      {p.scenes.map((s, i) => {
        const from = Math.round(s.start * fps);
        const to = i === p.scenes.length - 1 ? p.durationInFrames : Math.round(s.end * fps);
        const extra = i < p.scenes.length - 1 ? tr : 0;
        return (
          <Sequence key={i} from={from} durationInFrames={Math.max(1, to - from + extra)} layout="none">
            <SceneView scene={s} next={p.scenes[i + 1]} index={i} p={p} sceneFrames={to - from} />
          </Sequence>
        );
      })}
      {p.style.overlay && p.style.overlay !== 'none' ? <StyleOverlay name={p.style.overlay} theme={p.theme} dateLabel={p.dateLabel} /> : null}
      <Captions words={p.words} style={p.style.caption} theme={p.theme} font={capFont} />
    </AbsoluteFill>
  );
};
