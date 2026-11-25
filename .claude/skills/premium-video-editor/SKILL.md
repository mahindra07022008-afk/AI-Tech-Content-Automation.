---
name: premium-video-editor
description: Cinematic premium editing for the Telugu Tech channel — Remotion motion graphics (camera moves with speed ramps, whip/mask/iris/zoom/glitch transitions with motion blur, parallax, 3D globe/molecule, animated tech UIs, charts, glow kinetic typography, word-by-word Roman-Telugu captions with highlighted keywords) + FFmpeg grading + beat-synced cuts and synthesized SFX. Use for /premium-video-editor analyze-reference | generate | preview | fix-errors | report, or whenever the user wants a "cinematic", "premium", "real editing" or reference-styled video.
---

# Premium video editor

Works on top of the `telugu-tech-youtube` agent (same storyboard, voice, research, SEO, publishing).
Run everything from the project root with `.venv/bin/telugu-tech`. Read `CLAUDE.md` first.

Engine: `remotion/` (Remotion 4.0.540 pinned, React components in `remotion/src`) renders the visuals
from `props.json` written by `telugu_tech/premium.py`; FFmpeg grades them; MoneyPrinterTurbo assembles
the final MP4 with the mixed audio; `telugu_tech/quality.py` validates the real file.

## Commands

| Command | Handler |
|---|---|
| `analyze-reference [video]` | `telugu-tech premium analyze-reference --video PATH [--name N] [--activate]`. Needs a **local MP4**. If the user only gives an Instagram/TikTok/YouTube link, do **not** scrape or log in: ask them to save the clip themselves (own account or creator's permission) and share the file. Never invent an analysis. Summarise the report (pacing, motion, grade, caption band, tempo) and the derived style. |
| `generate [topic]` | Same workflow as `telugu-tech-youtube generate` (research → verified facts → storyboard JSON), then `telugu-tech premium generate --storyboard PATH --job-id ID [--style NAME] [--fps 60] [--style-profile P] [--long]`. |
| `preview [job]` | `telugu-tech premium preview --job ID`, then Read `final/contact_sheet.jpg` and inspect it yourself before reporting. Send the MP4/contact sheet to the user. |
| `fix-errors` | `telugu-tech premium fix-errors` — repairs Remotion deps (`npm ci` from lockfile), fonts, browser detection, runs a smoke still render and resumes failed jobs from checkpoints. Report blockers verbatim. |
| `report` | `telugu-tech premium report` — engine, style source, visuals/transitions/cameras/SFX used, caption words, quality per job. |

## Writing storyboards for the premium engine

Use the same schema as `examples/demo_ai_future_premium.storyboard.json` (validated by `telugu_tech/storyboard.py`):

- **Visual must show the meaning of the line**: `headline` (kinetic glow text), `neural_net` (how AI learns),
  `chart` (bar/line with real data only), `stat` (one sourced number), `chat_ui` (assistant conversation),
  `code` (+ `suggestion` lines = AI autocomplete), `flow` (process steps), `timeline`, `icon_grid`
  (floating 3D cards), `globe` / `molecule` (code-driven 3D), `branch_graph`, `compare`, `bullets`, `outro`.
- Per scene choose `transition` (whip, mask, iris, zoom, glitch, push, fade), `camera` (push_in, pull_out,
  pan_left, pan_right, orbit, tilt, drift) and `background` (aurora, grid, circuit, dots, space, particles).
  Vary them, but use glitch/whip sparingly (≤ 2 each per Short); restraint beats effect overload.
- `caption_roman` must have **the same number of words** as `narration_te` → exact word-by-word sync
  from Edge TTS word boundaries. Optional `keywords` list picks the highlighted tech terms (max ~3/scene).
- Short = 45–60 s: ≈ 560–600 narration characters over 8–10 scenes (beat-aligned cuts add ~0.3 s/scene).
- Never put logos, real people, creator footage or unlicensed music in visuals.

## Editing styles (12) — `telugu_tech/styles.py`

`cinematic_documentary`, `product_3d`, `retro_pixel`, `kinetic_typography`, `holo_hud`, `product_launch`,
`ai_news`, `code_explainer`, `parallax_25d`, `isometric`, `glassmorphism`, `infographic`.
Leave `style` out of the storyboard to auto-select (topic keywords + visual types + source types, with a
penalty for styles used in the last 3 videos), or set it / pass `--style NAME`. Pick visuals that suit the
style: `phone3d` (modes hero | explode | chip | camera | screen) for product_3d/product_launch,
`pixel_scene` (title | crt | network | globe | unlock | phone | server | rocket; uppercase A–Z 0–9 text, ≤ 21
chars) for retro_pixel, `iso_stack` (layers) for isometric, charts/stats for infographic, code/flow for
code_explainer. Say which style a video used and whether it was auto-selected.

Render profiles: `full` (WebGL: three.js/R3F + PixiJS through swangle) → automatic `lite` re-render
(CSS-3D phone, canvas-2D pixels) → classic engine. `--fps 60` gives a 60 fps master (direct FFmpeg mux,
because MoneyPrinterTurbo is 30 fps-only). Shorts are 30–60 s.

Remotion 3D rules (from remotion-dev/skills `3d.md`; install their skills with `npx remotion skills add`):
wrap 3D in `<ThreeCanvas width height>` with lights, animate only with `useCurrentFrame()`, never use R3F
`useFrame()`, and set `layout="none"` on any `<Sequence>` inside the canvas. Pixi/Canvas scenes must be pure
functions of the frame (seed noise per frame) so parallel tabs render identical frames.

## Verify loop (always, before reporting)

After every render: `premium preview` → Read `final/contact_sheet.jpg` and also grab frames at 0.5 s, 1.5 s
and mid-transition (`ffmpeg -ss T -i final/video.mp4 -frames:v 1`). Look for clipped text, overlapping
labels, empty scenes, unreadable captions and anything the automatic checks can't see. Fix the component or
storyboard, re-render from `--redo-from visuals`, and re-check. The quality gate also checks audio presence,
flashing (≤ 3 flashes/s), hook timing (first word ≤ 0.6 s), caption fit per caption template, sync and duration.

## Style profiles

Default = house preset `cinematic_tech` (telugu_tech/premium.py `HOUSE_STYLE`; mirrored in
`remotion/src/presets/styles.ts`). A reference analysis produces `data/styles/ref-*.json` that overrides
bpm, pacing (sub-cut interval, transition length), camera intensity, motion blur, caption position and
grade. Apply with `--style-profile` or make it default with `--activate`. Say which style a video used.

## Effect inventory (reusable components)

`remotion/src/components`: `Camera.tsx` (speed-ramped moves, beat punch, beat-aligned punch-in reframes,
parallax output), `Background.tsx` (6 animated scene backgrounds), `Visuals.tsx` (all visual types),
`Captions.tsx` (word-by-word templates: pop_highlight, karaoke_line), `Icons.tsx` (original SVG icons);
`remotion/src/presets/transitions.ts` (whip with SVG directional motion blur, mask, iris, zoom-through,
glitch RGB split, push, fade). Sound: `telugu_tech/audio.py` `SFX_LIBRARY` (whoosh, impact, riser, glitch,
typing, pop, ding, shimmer — all synthesised) + `shape_music` (intro filter sweep, pre-hit drop-out).
Finish: `premium.grade_filter` (bloom, teal/warm balance, contrast, sharpen, vignette, grain).

## Rules

- Free/local only (Remotion is free for individuals and companies ≤ 3 people; note this if the user is a larger company).
- Keep YouTube/OAuth/scheduler/publishing config untouched; never upload without explicit approval.
- Quality gate must pass (duration, 1080×1920@30, loudness, decode, no blank/frozen scenes, captions in
  safe area, word sync, sources, licences). Fix causes; never weaken checks.
- If Remotion fails 3×, the pipeline falls back to the classic engine and logs it — report that honestly.
