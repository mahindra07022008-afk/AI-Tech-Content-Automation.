# Telugu Tech Storytelling AI Agent — project guide for Claude Code

Faceless Telugu technology-storytelling YouTube pipeline. The `/telugu-tech-youtube` skill
(`.claude/skills/telugu-tech-youtube/SKILL.md`) is the entry point for all channel work.

## Layout

```
config/project.yaml        all settings (safe defaults: private, scheduler off, no paid services)
telugu_tech/               python package (CLI: `.venv/bin/telugu-tech`)
  cli.py                   command handlers: setup research generate-short generate-long preview
                           publish status fix-errors report schedule webui
  research.py              RSS (official blogs + news), GitHub search, HN, arXiv, HF papers → verified candidates
  storyboard.py            storyboard schema, validation (8-part structure, Telugu ratio, sources), LLM generation
  tts.py                   Edge TTS Telugu voices, per-scene synthesis, section prosody
  audio.py                 narration timeline, original procedural music + SFX, ducking, 2-pass loudnorm
  visuals.py               classic motion-graphics engine (Pillow+raqm → FFmpeg), captions, transitions
  premium.py               PREMIUM engine: word timings, keywords, beat grid, props → Remotion render, FFmpeg grade, SFX plan
  reference.py             reference MP4 analysis (cuts, motion, colour, caption band, loudness, tempo) → style profile
  engine.py                MoneyPrinterTurbo final assembly (primary) + logged FFmpeg fallback
  subtitles.py             Telugu Unicode + Roman Telugu SRT
  thumbnail.py / seo.py    thumbnail, Shorts cover, titles/description/hashtags/chapters
  quality.py               ffprobe/ffmpeg validation of the real output file
  youtube.py               YouTube Data API v3 (OAuth, private-by-default, gates, dedupe by SHA-256, quota)
  scheduler.py             Asia/Kolkata schedule evaluated in Python; one */5 crontab tick (disabled by default)
  report.py                daily report (local; Gmail API if authorised)
  doctor.py                diagnostics + safe auto-repair
  errors.py / db.py        error taxonomy, redaction, bounded retries; SQLite history & checkpoints
scripts/mpt_llm.py         bridge: runs inside MPT's venv, calls MPT's claude_code provider
remotion/                  Remotion 4.0.540 project (pinned, package-lock.json): src/components (Camera, Background,
                           Visuals, Captions, Icons), src/presets (transitions, styles). node_modules + fonts gitignored.
.claude/skills/premium-video-editor/  /premium-video-editor skill (analyze-reference, generate, preview, fix-errors, report)
examples/                  demo storyboard (GitHub explainer Short)
tests/                     pytest suite (`.venv/bin/pytest -q`; integration tests need ffmpeg)
vendor/MoneyPrinterTurbo/  render engine, pinned commit, gitignored (installed by `telugu-tech setup`)
data/                      jobs, DB, logs, reports, secrets — gitignored
```

## Pipeline (per job, resumable via checkpoints in SQLite + `data/jobs/<id>/checkpoint.json`)

storyboard → voice (per scene, duration auto-repair ±10% rate) → audio mix → visuals → MPT render →
subtitles → thumbnail → SEO → licence manifest → quality validation. Outputs in `data/jobs/<id>/final/`.

Why MPT gets one pre-timed material clip: scenes are timed from real narration audio; MPT is called
with `--video-source local`, sequential concat, no transitions, custom audio and BGM off, which was
verified to preserve frame timing. Captions are burned in by our engine (Roman Telugu) because MPT
subtitles would be Telugu script from the narration.

Premium engine (`engine.visual_engine: premium`): scene starts are snapped to the music beat grid,
Edge TTS word boundaries give exact word-by-word caption timing (keep `caption_roman` word-aligned with
`narration_te`), Remotion renders silent 1080×1920 motion graphics from `premium_props.json`, FFmpeg
applies the grade (bloom, colour balance, contrast, vignette, grain). Fallback to classic is automatic
and logged. Style = house preset unless a reference profile (`data/styles/ref-*.json`) is supplied.

## Rules

- Facts only from recorded sources (URL + date); every claim in `facts[]` cites `source_ids`.
- No paid services; never use MPT `--confirm-*-charge` flags. Assets must be original or properly
  licensed; record them in `final/licenses.json`.
- Publishing: private only, and only with `--approve-private-upload` after the user approves.
  Public/scheduling require config flags + explicit approval + a prior private test.
- Never commit secrets; `data/`, `.env`, `vendor/` are gitignored. Logs go through `errors.redact`.
- Don't weaken `quality.py` or `storyboard.validate` to get a pass.
- Network note (cloud sandboxes): Edge TTS uses `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` when set, so
  TLS-inspecting proxies work without disabling verification.

## Dev

```
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -e ".[youtube,dev]"
.venv/bin/telugu-tech setup
.venv/bin/pytest -q
```
