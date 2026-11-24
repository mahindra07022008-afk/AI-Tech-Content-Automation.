// Transition presets. Each returns CSS for the INCOMING scene (p: 0→1) and the OUTGOING scene (p: 0→1).
import React from 'react';
import {clamp} from '../utils';

export type TransitionName = 'whip' | 'mask' | 'iris' | 'zoom' | 'glitch' | 'fade' | 'push';

// Legacy storyboard names → premium presets.
export const ALIASES: Record<string, TransitionName> = {
  slide: 'whip',
  wipe: 'mask',
  fade: 'fade',
  zoom: 'zoom',
  whip: 'whip',
  mask: 'mask',
  iris: 'iris',
  glitch: 'glitch',
  push: 'push',
};

export const resolveTransition = (name: string): TransitionName => ALIASES[name] ?? 'fade';

export type TStyles = {incoming: React.CSSProperties; outgoing: React.CSSProperties; blurX: number};

export const transitionStyles = (name: TransitionName, p: number, frame: number, motionBlur: boolean): TStyles => {
  const q = clamp(p);
  const inv = 1 - q;
  switch (name) {
    case 'whip': {
      // Fast horizontal whip-pan with directional motion blur peaking mid-move.
      const blur = motionBlur ? Math.sin(Math.PI * q) * 38 : 0;
      return {
        incoming: {transform: `translateX(${inv * 100}%)`},
        outgoing: {transform: `translateX(${-q * 100}%)`},
        blurX: blur,
      };
    }
    case 'push':
      return {
        incoming: {transform: `translateY(${inv * 100}%)`},
        outgoing: {transform: `translateY(${-q * 35}%) scale(${1 - 0.1 * q})`, opacity: 1 - q * 0.6},
        blurX: 0,
      };
    case 'mask': {
      // Diagonal soft mask reveal.
      const x = -40 + q * 180;
      return {
        incoming: {clipPath: `polygon(0% 0%, ${x}% 0%, ${x - 40}% 100%, 0% 100%)`},
        outgoing: {transform: `scale(${1 + 0.06 * q})`, filter: `brightness(${1 - 0.4 * q})`},
        blurX: 0,
      };
    }
    case 'iris':
      return {
        incoming: {clipPath: `circle(${q * 120}% at 50% 42%)`},
        outgoing: {transform: `scale(${1 + 0.1 * q})`, filter: `blur(${q * 6}px)`},
        blurX: 0,
      };
    case 'zoom':
      // Zoom-through: outgoing flies past camera, incoming settles from oversize.
      return {
        incoming: {transform: `scale(${1 + inv * 0.6})`, opacity: q, filter: `blur(${inv * (motionBlur ? 14 : 0)}px)`},
        outgoing: {transform: `scale(${1 + q * 0.9})`, opacity: 1 - q, filter: `blur(${q * (motionBlur ? 16 : 0)}px)`},
        blurX: 0,
      };
    case 'glitch': {
      const jitter = q < 1 ? ((frame * 37) % 23) - 11 : 0;
      const on = q < 0.85;
      return {
        incoming: {
          opacity: q < 0.15 ? 0 : q < 0.3 ? 0.5 : 1,
          transform: `translateX(${on ? jitter * 2 : 0}px)`,
          filter: on
            ? `drop-shadow(${8 * inv}px 0 0 rgba(255,0,90,0.75)) drop-shadow(${-8 * inv}px 0 0 rgba(0,240,255,0.75)) hue-rotate(${inv * 40}deg)`
            : 'none',
        },
        outgoing: {opacity: 1 - q, transform: `translateX(${-jitter}px)`},
        blurX: 0,
      };
    }
    default:
      return {
        incoming: {opacity: q, filter: `blur(${inv * 10}px)`},
        outgoing: {opacity: 1 - q * 0.8},
        blurX: 0,
      };
  }
};
