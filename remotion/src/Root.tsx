import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {Main} from './Main';
import {CINEMATIC_TECH} from './presets/styles';
import {Props} from './types';

// Default props let `remotion studio` preview the component library without Python.
const defaults: Props = {
  width: 1080,
  height: 1920,
  fps: 30,
  durationInFrames: 240,
  theme: {primary: '#7C3AED', accent: '#22D3EE', highlight: '#FACC15', bgTop: '#070B18', bgBottom: '#1E1B4B', text: '#F8FAFC', danger: '#F43F5E'},
  style: CINEMATIC_TECH,
  fonts: {display: 'TTDisplay', telugu: 'TTTelugu', mono: 'TTMono', body: 'TTDisplay'},
  scenes: [
    {id: 1, section: 'hook', start: 0, end: 4, speechStart: 0.2, speechEnd: 3.6, visual: {type: 'question', text: 'AI ante enti?', keywords: ['AI']}, transition: 'fade', camera: 'push_in', background: ''},
    {id: 2, section: 'explanation', start: 4, end: 8, speechStart: 4.1, speechEnd: 7.6, visual: {type: 'neural_net', inputLabel: 'Data', outputLabel: 'Prediction'}, transition: 'whip', camera: 'orbit', background: ''},
  ],
  words: [
    {text: 'AI', start: 0.3, end: 0.8, keyword: true, scene: 0},
    {text: 'ante', start: 0.8, end: 1.3, keyword: false, scene: 0},
    {text: 'enti?', start: 1.3, end: 2.0, keyword: false, scene: 0},
  ],
  beats: Array.from({length: 14}, (_, i) => i * 0.6),
};

const calculateMetadata: CalculateMetadataFunction<Props> = ({props}) => ({
  durationInFrames: props.durationInFrames,
  fps: props.fps,
  width: props.width,
  height: props.height,
});

export const RemotionRoot: React.FC = () => (
  <Composition id="TeluguTechShort" component={Main} defaultProps={defaults} calculateMetadata={calculateMetadata}
    durationInFrames={defaults.durationInFrames} fps={30} width={1080} height={1920} />
);
