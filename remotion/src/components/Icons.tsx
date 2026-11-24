import React from 'react';

// Original line/solid icons drawn for this project (24x24 viewBox). No third-party icon sets or logos.
const P: Record<string, React.ReactNode> = {
  code: <path d="M8 6 2 12l6 6M16 6l6 6-6 6M14 3l-4 18" fill="none" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />,
  cloud: <path d="M7 18h10a4.5 4.5 0 0 0 .6-8.96A6 6 0 0 0 6.2 10.1 4 4 0 0 0 7 18z" />,
  users: (
    <g>
      <circle cx="9" cy="8" r="3.4" />
      <path d="M2.5 20c.6-3.8 3.3-6 6.5-6s5.9 2.2 6.5 6z" />
      <circle cx="17" cy="9" r="2.6" opacity={0.75} />
      <path d="M15.5 14.2c3.1-.4 5.6 1.6 6 5.8h-4.2" opacity={0.75} />
    </g>
  ),
  star: <path d="m12 2.5 2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6-4.9-4.6 6.6-.8z" />,
  branch: (
    <g fill="none" strokeWidth={2.2} strokeLinecap="round">
      <circle cx="6" cy="5" r="2.2" /><circle cx="6" cy="19" r="2.2" /><circle cx="18" cy="7" r="2.2" />
      <path d="M6 7.2v9.6M18 9.2c0 5-6 4-11 7.6" />
    </g>
  ),
  merge: (
    <g fill="none" strokeWidth={2.2} strokeLinecap="round">
      <circle cx="6" cy="5" r="2.2" /><circle cx="6" cy="19" r="2.2" /><circle cx="18" cy="17" r="2.2" />
      <path d="M6 7.2v9.6M7 7c1.5 6 5 8 8.8 9.6" />
    </g>
  ),
  ai: (
    <g>
      <rect x="5" y="5" width="14" height="14" rx="3" />
      <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" strokeWidth={1.8} stroke="currentColor" />
      <text x="12" y="15.2" textAnchor="middle" fontSize="7.5" fontWeight="900" fill="#0b1020" fontFamily="sans-serif">AI</text>
    </g>
  ),
  chip: (
    <g>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" strokeWidth={1.8} stroke="currentColor" />
    </g>
  ),
  brain: (
    <path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-3 3.5A3 3 0 0 0 4 15a3.5 3.5 0 0 0 5 4.5V3zm6 0a3 3 0 0 1 3 3 3 3 0 0 1 3 3.5A3 3 0 0 1 20 15a3.5 3.5 0 0 1-5 4.5V3z" />
  ),
  globe: (
    <g fill="none" strokeWidth={1.8}>
      <circle cx="12" cy="12" r="9.5" /><ellipse cx="12" cy="12" rx="4.2" ry="9.5" /><path d="M2.5 12h19M4 7h16M4 17h16" />
    </g>
  ),
  lock: <path d="M7 10V7.5a5 5 0 0 1 10 0V10h1.5v11h-13V10zm2.2 0h5.6V7.5a2.8 2.8 0 0 0-5.6 0z" />,
  rocket: <path d="M12 2c3.5 2.2 5.5 6 5.5 10.5L19.5 16l-3 2.5-1-2.5h-7l-1 2.5-3-2.5 2-3.5C6.5 8 8.5 4.2 12 2zm0 6.2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM10 19h4l-2 3z" />,
  book: <path d="M3 4.5C6 4 9 4.6 11.3 6.2V20C9 18.6 6 18 3 18.5zm18 0c-3-.5-6 .1-8.3 1.7V20c2.3-1.4 5.3-2 8.3-1.5z" />,
  bug: (
    <g>
      <ellipse cx="12" cy="13.5" rx="5" ry="6.5" /><circle cx="12" cy="5.5" r="2.8" />
      <path d="M3 9h4M3 14h4M3 19h4M17 9h4M17 14h4M17 19h4" strokeWidth={1.8} stroke="currentColor" />
    </g>
  ),
  laptop: <path d="M4 5h16v10H4zm-2 12h20l-1.5 2.5h-17z" />,
  phone: <path d="M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm1 3v12h8V5zm4 13.2a1 1 0 1 0 0 2 1 1 0 0 0 0-2z" />,
  server: (
    <g>
      <rect x="3" y="3" width="18" height="5.5" rx="1.5" /><rect x="3" y="9.5" width="18" height="5.5" rx="1.5" />
      <rect x="3" y="16" width="18" height="5.5" rx="1.5" />
    </g>
  ),
  money: <text x="12" y="18" textAnchor="middle" fontSize="18" fontWeight="900" fontFamily="sans-serif">₹</text>,
  chart: <path d="M3 21h18v-1.8H3zM5 18h3v-7H5zm5.5 0h3V6h-3zM16 18h3v-10h-3z" />,
  dna: (
    <g fill="none" strokeWidth={2} strokeLinecap="round">
      <path d="M7 2c0 6 10 6 10 10S7 16 7 22M17 2c0 6-10 6-10 10s10 4 10 10M8.5 6h7M8.5 18h7M10 12h4" />
    </g>
  ),
  spark: <path d="M12 2l2.2 6.8L21 11l-6.8 2.2L12 20l-2.2-6.8L3 11l6.8-2.2z" />,
  check: <path d="M4 12.5 9.5 18 20 6.5" fill="none" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />,
  heart: <path d="M12 21s-8.5-5.3-8.5-11.2A4.8 4.8 0 0 1 12 6.6a4.8 4.8 0 0 1 8.5 3.2C20.5 15.7 12 21 12 21z" />,
  india: (
    <g>
      <rect x="2" y="5" width="20" height="4.7" fill="#FF9933" />
      <rect x="2" y="9.7" width="20" height="4.6" fill="#FFFFFF" />
      <rect x="2" y="14.3" width="20" height="4.7" fill="#138808" />
      <circle cx="12" cy="12" r="1.8" fill="none" stroke="#000080" strokeWidth={0.7} />
    </g>
  ),
};

export const ICON_NAMES = Object.keys(P);

export const Icon: React.FC<{name: string; size: number; color: string; style?: React.CSSProperties}> = ({
  name, size, color, style,
}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} stroke={color} strokeWidth={0} style={{color, overflow: 'visible', ...style}}>
    {P[name] ?? P.spark}
  </svg>
);
