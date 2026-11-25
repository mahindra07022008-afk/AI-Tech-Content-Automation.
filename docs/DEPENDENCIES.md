# Dependency audit — premium style engine (Nov 2026)

Each candidate was checked for licence, install scripts, security advisories and compatibility with
Remotion 4.0.540 before integration. Versions are pinned exactly in `remotion/package.json` and locked by
`remotion/package-lock.json` (`npm ci`).

| Candidate | Decision | Version | Licence | Notes |
|---|---|---|---|---|
| remotion, @remotion/cli | kept (already used) | 4.0.540 | Remotion License | Free for individuals and companies with ≤3 employees; larger companies need a company licence. |
| @remotion/three | **added** | 4.0.540 | MIT | `<ThreeCanvas>` keeps three.js frame-accurate under Remotion's renderer. |
| three | **added** | 0.186.1 | MIT | 3D smartphone (`ThreeD.tsx`). |
| @react-three/fiber | **added** | 9.8.2 | MIT | Supports React 19 (peer `react >=19 <19.4`); @remotion/three peer-depends on it. |
| pixi.js | **added** | 8.22.0 | MIT | Pixel-art scenes (`Pixel.tsx`), loaded with a dynamic import only when a pixel scene is used. |
| remotion-dev/skills | rules followed, text **not copied** | — | no licence file | Its 3D rules are applied in code: `<ThreeCanvas width height>`, animation only from `useCurrentFrame()`, never `useFrame()`, `<Sequence layout="none">` inside the canvas. Install the official skills with `npx remotion skills add` if wanted. |
| iart-ai/motion-skills | ideas only, nothing installed | — | MIT | It promotes a paid service, which is not used. Its render-then-check loop matches our contact-sheet review (`premium preview`). |
| Motion Canvas | **not installed** | — | — | Remotion already covers this; a second renderer would add weight with no gain. |
| HyperFrames | **not installed** | — | — | Not required; Remotion covers HTML-to-video. |

Evidence (re-run before commit):

- `npm audit` → **found 0 vulnerabilities**.
- Install scripts in the lockfile: only `node_modules/esbuild` (Remotion's bundler; downloads its platform binary).
- `telugu-tech premium fix-errors` (doctor with the smoke test) → all packages present at the pinned versions; the
  WebGL smoke test (three.js phone still + Pixi pixel still) passes with the pre-installed Chrome headless shell and
  `--gl=swangle`.
- `tests/test_styles.py::test_pinned_frontend_dependencies_and_glyphs` fails if any of these dependencies is unpinned.

No paid APIs, no model/asset downloads, no network access at render time. All fonts are Noto (SIL OFL 1.1);
the pixel font, music, SFX, 3D models and pixel art are generated in code.
