---
name: telugu-tech-youtube
description: Produce faceless Telugu technology-storytelling YouTube videos end to end — topic research, fact-checked Telugu script and storyboard, Telugu voice-over (Edge TTS), original motion graphics, Roman-Telugu captions, Telugu SRT, thumbnail, SEO, quality validation, local preview, gated YouTube upload, schedule and daily report. Use for any request about this channel's videos or the commands setup, research, generate-short, generate-long, preview, publish, status, fix-errors, report.
---

# Telugu Tech YouTube agent

Project root = the repository containing this skill. All commands run from the project root with
`.venv/bin/telugu-tech <command>` (create the venv with `uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -e ".[youtube,dev]"` if missing).
MoneyPrinterTurbo (pinned commit, `vendor/MoneyPrinterTurbo`) is the render engine; its LLM provider is
`claude_code` (the logged-in `claude` CLI). Read `CLAUDE.md` for architecture and rules.

## Commands

The user invokes `/telugu-tech-youtube <command> [args]`. Map each to a real handler:

| Command | What to do |
|---|---|
| `setup` | `telugu-tech setup --webui-test`. Report every ✖. Install/repair is automatic and safe (pinned MPT commit, `uv sync` from lockfile, Noto fonts, private 127.0.0.1 config). |
| `research` | `telugu-tech research`. Then summarise the top verified candidates (title, source, date). Prefer `verified` ones; never present a single-source rumour as fact. |
| `generate-short [topic]` | See **Generate** below, kind `short` (45–60 s, 1080×1920). |
| `generate-long [topic]` | See **Generate** below, kind `long` (5–8 min, 1920×1080). Pass `generate-long`. |
| `preview [job]` | `telugu-tech preview [--job ID]`, then show the user the contact sheet (Read the jpg) and give the video path. Offer to open `final/preview.html`. |
| `publish [job]` | First `telugu-tech publish --dry-run` and show the request. Upload only if the user explicitly approves *in this conversation*: `telugu-tech publish --approve-private-upload`. Never pass `--approve-public` unless the user explicitly asks for public AND a private test upload already succeeded. OAuth (`publish --auth`) must be run by the user on their own computer. |
| `status` | `telugu-tech status` and summarise. |
| `fix-errors` | `telugu-tech fix-errors` (add `--resume-failed` to resume failed jobs from checkpoints). Report blockers verbatim with the manual step. |
| `report` | `telugu-tech report` (local markdown/json; Gmail only if authorised). |

## Generate (interactive — preferred, no extra headless LLM calls)

1. **Topic**: use the argument, or pick the best *verified* candidate from `telugu-tech research`. Check
   for duplicates: the CLI refuses topics similar to ones already used.
2. **Research the facts yourself** from primary/official sources (official blogs, docs, filings, papers,
   GitHub repos) and credible news. Record URL + publication date for each. Verify every number,
   date, name and quote; drop anything you cannot verify. Never invent news, stats, quotes or features.
3. **Write the storyboard JSON** at `data/jobs/<job-id>.storyboard.json` following
   `examples/demo_github_short.storyboard.json` exactly (schema in `telugu_tech/storyboard.py`, style guide
   in `STYLE_GUIDE` there). Rules:
   - Sections in order: hook, intro, background, turning_point, explanation, example, conclusion, cta
     (a section may span consecutive scenes).
   - `narration_te`: natural spoken Telugu, English tech terms in Latin script, short sentences, no
     bookish Telugu, no literal translation. Original writing — never copy another creator.
   - `caption_roman`: same line in casual Roman Telugu (WhatsApp style), no Telugu script.
   - Length: short ≈ 520–620 narration characters (≈ 11.5 chars/s); long ≈ 3,500–5,000.
   - Every fact → `facts[]` with `source_ids`. Visual types/icons only from the allowed lists; no logos,
     movie clips, real people's photos.
   - SEO: exactly 3 accurate titles (≤ 100 chars, no clickbait), Telugu + English descriptions,
     hashtags, keywords, pinned comment, thumbnail concept.
4. Validate: `.venv/bin/python -c "from telugu_tech.config import load_config; from telugu_tech import storyboard as s; print(s.validate(s.load('PATH'), load_config()))"` → must print `[]`.
5. Render: `telugu-tech generate-short --storyboard PATH --job-id <id>` (or `generate-long`). It
   voices each scene, auto-repairs duration via speaking rate (max ±10%; beyond that shorten/lengthen
   the script and re-run), renders, validates with ffprobe and writes everything to `data/jobs/<id>/final/`.
6. Run `preview`, inspect the contact sheet, and report: video path, duration, quality checks, titles.
   Do **not** upload unless asked.

Headless/scheduled mode (no interactive Claude): `telugu-tech generate-short --category news` picks a
verified topic and asks Claude through MoneyPrinterTurbo's `claude_code` provider, validating and
re-prompting up to 3 times. This consumes Claude subscription usage — keep it to the schedule.

## Visual engine (premium editor integration)

New videos use `engine.visual_engine` from `config/project.yaml` (`premium` = Remotion cinematic engine,
`classic` = Pillow engine). For premium storyboards follow `.claude/skills/premium-video-editor/SKILL.md`:
pick a meaningful premium visual per scene (neural_net, chart, chat_ui, code+suggestion, globe, molecule,
flow, headline…), vary `transition`/`camera`/`background`, and keep `caption_roman` word-aligned with
`narration_te` (same word count) for exact word-by-word captions. Override per run with `--engine classic|premium`.
If Remotion fails 3×, the job falls back to classic automatically (logged) — say so in the report.
Editing style is auto-selected per topic from 12 styles (`telugu_tech/styles.py`); set `"style"` in the
storyboard only when the user asks for a specific look. Shorts may be 30–60 s; aim ≈ 450–600 narration chars.

## Voice

Default `te-IN-MohanNeural` (male); `--voice shruti` → `te-IN-ShrutiNeural`. If TTS fails, run
`fix-errors`; never silently switch to a non-Telugu voice or a paid provider.

## Hard rules

- Zero extra spend: no paid APIs, no purchases, no paid MPT video sources (`--confirm-*-charge` flags are never used).
- Public publishing, scheduling and Gmail stay OFF until the user explicitly approves. Never request
  passwords, OTPs or recovery codes. Never print or commit secrets (`data/secrets/`, `.env`).
- Never skip or weaken quality validation to make something pass. If a check fails, fix the cause.
- Auth / permission / quota / billing / policy errors are blockers: stop and report with the manual step.
- Keep the WebUI on 127.0.0.1; do not expose ports.
