# AI-Tech-Content-Automation — Telugu Tech Storytelling AI Agent

Faceless **Telugu technology-storytelling** YouTube pipeline: research → fact-checked Telugu script →
Telugu voice-over → original motion graphics → Roman-Telugu captions + Telugu SRT → thumbnail & SEO →
quality validation → local preview → (approved) private YouTube upload → schedule → daily report.

- **Render engine:** [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (MIT), pinned commit, installed into `vendor/`.
- **LLM:** your existing Claude subscription via MoneyPrinterTurbo's official `claude_code` provider
  (runs the logged-in `claude` CLI headless; no API key). Interactively, Claude Code writes the storyboard itself.
- **Voice:** Microsoft Edge TTS `te-IN-MohanNeural` (default) / `te-IN-ShrutiNeural` — free.
- **Visuals & music:** generated from code (no stock footage, no third-party music) → no licence risk.
- **Cost:** ₹0 beyond the Claude subscription. Nothing paid is enabled.

## Quick start (Linux/macOS)

```bash
# prerequisites: git, ffmpeg, uv (https://docs.astral.sh/uv/), claude CLI logged in
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[youtube,dev]"
sudo apt-get install -y fonts-noto-core     # Telugu fonts (macOS: install Noto Sans Telugu and set paths in config)
.venv/bin/telugu-tech setup --webui-test    # clones+installs MoneyPrinterTurbo, writes private config, checks everything
.venv/bin/pytest -q                         # test suite
```

## Commands (also available as `/telugu-tech-youtube <command>` inside Claude Code)

| Command | Purpose |
|---|---|
| `telugu-tech setup [--webui-test]` | Install/repair engine, fonts, config; diagnostics; WebUI smoke test on 127.0.0.1 |
| `telugu-tech research` | Fresh topics from official blogs, news, GitHub, HN, arXiv, HF papers; verified + deduped |
| `telugu-tech generate-short --storyboard FILE` | 45–60 s, 1080×1920 Short from a storyboard (or `--category news` / `--topic … --source URL` headless) |
| `telugu-tech generate-long …` | 5–8 min, 1920×1080 video with chapters |
| `telugu-tech preview [--job ID]` | Local `preview.html`, contact sheet from the real file, metadata |
| `telugu-tech publish --dry-run` | Show the exact YouTube API request and gate results |
| `telugu-tech publish --approve-private-upload` | Private upload (after you approve) |
| `telugu-tech status` | Engine, gates, jobs, videos, uploads, blockers, next schedule |
| `telugu-tech fix-errors [--resume-failed]` | Diagnose, auto-repair safe issues, resume failed jobs from checkpoints |
| `telugu-tech report` | Daily report (local; Gmail if authorised) |
| `telugu-tech schedule show\|install --approve\|uninstall` | IST schedule (07:00 news Short, 22:00 story Short, optional weekly long) |
| `telugu-tech webui` | MoneyPrinterTurbo WebUI on 127.0.0.1 only |

Outputs per job: `data/jobs/<job-id>/final/` → `video.mp4`, `thumbnail.jpg`, `cover_short.png`,
`subtitles.te.srt`, `subtitles.te-Latn.srt`, `youtube_metadata.{json,md}`, `storyboard.md`,
`quality_report.json`, `licenses.json`, `preview.html`.

## Premium cinematic editor (`/premium-video-editor`)

Remotion (pinned 4.0.540) + FFmpeg on top of the same pipeline:
- **Camera:** speed-ramped push/pull/pan/orbit/tilt/drift, beat punches, beat-aligned punch-in reframes, parallax.
- **Transitions:** whip-pan with directional motion blur, diagonal mask, iris, zoom-through, glitch RGB split, push and fade.
- **Graphics:** kinetic glow typography, neural network, animated bar/line charts and counters, chat UI, code editor with AI autocomplete, flow diagrams, timeline, floating 3D cards, and code-driven 3D globe and protein.
- **Backgrounds:** six animated, scene-specific backgrounds.
- **Captions:** word-by-word Roman-Telugu captions timed from Edge TTS word boundaries, with highlighted tech keywords.
- **Sound:** synthesised SFX (whoosh, impact, riser, glitch, typing, pop, ding, shimmer). The music is arranged with an intro filter sweep and a drop-out before the turning point, and cuts land on the beat.
- **Finish:** an FFmpeg grade adds bloom, teal/warm balance, contrast, sharpening, vignette and grain. No watermark or badge is added.

```bash
cd remotion && npm ci && cd ..                         # or: telugu-tech premium fix-errors
telugu-tech premium analyze-reference --video ref.mp4 --activate   # optional: learn pacing/grade from YOUR reference MP4
telugu-tech premium generate --storyboard examples/demo_ai_future_premium.storyboard.json --job-id my-short
telugu-tech premium preview --job my-short
telugu-tech premium report
```
Remotion licence: free for individuals and companies with up to 3 employees (larger companies need a company licence).

### 12 editing styles (auto-selected per topic)

| Style | Built for | Signature |
|---|---|---|
| `cinematic_documentary` | history / founder stories | serif type, film light-leaks, slow camera, depth of field |
| `product_3d` | devices & hardware | **real-time 3D phone** (three.js + React Three Fiber via `@remotion/three`) |
| `retro_pixel` | tech history | **PixiJS pixel art**, original 5×7 bitmap font, CRT scanlines |
| `kinetic_typography` | punchy ideas | fast word-slams, 2-word captions, beat punches |
| `holo_hud` | security / future tech | HUD brackets, rotating rings, scan line, cyan palette |
| `product_launch` | launches | spotlight sweeps, studio backdrop, deep vignette |
| `ai_news` | AI news | "AI NEWS" tag + date, house cinematic look |
| `code_explainer` | GitHub repos, coding | terminal overlay, mono type, code/flow visuals |
| `parallax_25d` | journeys / layers | strong parallax depth layers, rack focus |
| `isometric` | architecture / stacks | isometric grid + `iso_stack` blocks |
| `glassmorphism` | apps / UI | glass panels, blurred colour blobs, glass-pill captions |
| `infographic` | numbers / reports | flat grid, charts & counters |

Selection (`telugu_tech/styles.py`) scores topic keywords, the storyboard's visual types and source types,
and penalises styles used in the last 3 videos (no samey output). Force one with `--style NAME` or a
`"style"` field in the storyboard. If the WebGL 3D/pixel profile fails, the job re-renders with the
**lite profile** (CSS-3D phone, canvas-2D pixels) and, if that fails too, the classic engine — each step logged.
`--fps 60` renders a 60 fps master (MoneyPrinterTurbo is 30 fps-only, so 60 fps uses the logged FFmpeg mux).
Rollback: see [docs/ROLLBACK.md](docs/ROLLBACK.md).

## Safety defaults (change only with intent)

`config/project.yaml`: `publishing.youtube_enabled: false`, `allow_public: false`, `allow_scheduling: false`,
`scheduler.enabled: false`, `reporting.gmail_enabled: false`. Secrets live in `data/secrets/` (mode 700,
gitignored). Logs are redacted. WebUI binds to 127.0.0.1.

## Manual steps that only you can do

### 1. YouTube upload (optional)
1. In [Google Cloud Console](https://console.cloud.google.com/): create a project → enable **YouTube Data API v3**
   (free quota 10,000 units/day; one upload ≈ 1,600 + captions 400).
2. OAuth consent screen: *External*, add yourself as a **test user**; scopes `youtube.upload`, `youtube.force-ssl`.
3. Credentials → *Create OAuth client ID* → **Desktop app** → download JSON to `data/secrets/client_secret.json`.
4. On **your own computer** (a browser is needed): `telugu-tech publish --auth` and sign in on Google's page.
   (Never share passwords/OTPs with anyone or any tool.)
5. Set `publishing.youtube_enabled: true`, run `telugu-tech publish --dry-run`, then
   `telugu-tech publish --approve-private-upload`. Check the private video in YouTube Studio.
6. Only after a good private test: set `allow_public: true` and use `--privacy public --approve-public` yourself.
   Unverified API projects may have uploads locked private until Google's audit — that is a Google policy, not a bug.

### 2. Gmail daily report (optional)
Enable the **Gmail API** in the same project, run `telugu-tech report --gmail-auth` on your computer, set
`REPORT_EMAIL_TO` in `.env` and `reporting.gmail_enabled: true`.

### 3. Scheduler activation
Needs a machine that is on at 07:00/22:00 IST with the `claude` CLI logged in. Set `scheduler.enabled: true`,
then `telugu-tech schedule install --approve` (adds one `*/5` crontab line; jobs are evaluated in
Asia/Kolkata by the tool itself, so the server timezone does not matter). Headless script generation uses
your Claude subscription limits — the subscription is not unlimited.

GitHub Actions is intentionally **not** used: runners have no logged-in Claude subscription, and storing
YouTube OAuth tokens in CI would widen the attack surface.

## Licences
Code: this repo. Engine: MoneyPrinterTurbo (MIT). Motion graphics: Remotion (Remotion License, free for individuals/≤3-person companies). Fonts: Noto (SIL OFL 1.1). Music/SFX/visuals: generated
by this project. Voice: Microsoft Edge neural TTS (synthetic voice; disclosed as AI-generated).
