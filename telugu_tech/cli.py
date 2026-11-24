"""telugu-tech CLI — command handlers behind the /telugu-tech-youtube skill."""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import doctor, pipeline, report, research, scheduler, storyboard as sbmod, youtube
from .config import load_config
from .db import DB
from .errors import AgentError, Category, ErrorLog, redact

STORY_CATEGORIES = {"story", "startup_story", "history", "how_it_works", "github_trending", "future_tech", "tutorial"}
NEWS_CATEGORIES = {"ai_news", "ai_tools", "research"}


def _ctx(args):
    cfg = load_config(args.config)
    cfg.ensure_dirs()
    return cfg, DB(cfg.db_path)


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _latest_job(cfg, db: DB, job_id: str | None) -> Path:
    if job_id:
        p = cfg.jobs_dir / job_id
    else:
        rows = [r for r in db.jobs(limit=20) if (cfg.jobs_dir / r["job_id"] / "final" / "video.mp4").is_file()]
        if not rows:
            raise AgentError("no finished job found — run generate-short first", Category.ASSET)
        p = cfg.jobs_dir / rows[0]["job_id"]
    if not p.is_dir():
        raise SystemExit(f"job not found: {p}")
    return p


# ------------------------------------------------------------------ setup
def cmd_setup(args):
    cfg, db = _ctx(args)
    res = doctor.Doctor(cfg, fix=True).run(network=not args.offline)
    for r in res:
        mark = "✔" if r["ok"] else ("✖ BLOCKER" if r["blocker"] else "✖")
        extra = f"  [repaired: {r['repaired']}]" if r["repaired"] else ""
        print(f"{mark} {r['check']}: {r['detail']}{extra}")
    if args.webui_test:
        print("WebUI:", _webui_smoke(cfg))
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks OK")
    return 1 if any(r["blocker"] for r in bad) else 0


def _webui_smoke(cfg, port: int = 8501) -> str:
    """Start the MoneyPrinterTurbo WebUI bound to 127.0.0.1, probe it, stop it."""
    import urllib.request
    py = cfg.mpt_python
    proc = subprocess.Popen([str(py), "-m", "streamlit", "run", "webui/Main.py", "--server.address", "127.0.0.1",
                             "--server.port", str(port), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                            cwd=cfg.mpt_home, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            time.sleep(1)
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                        f"http://127.0.0.1:{port}/_stcore/health", timeout=3) as r:
                    if r.status == 200:
                        return f"OK — served on http://127.0.0.1:{port} (localhost only), health=200"
            except OSError:
                continue
        return "FAILED — no health response in 60s"
    finally:
        proc.terminate()
        proc.wait(timeout=20)


def cmd_webui(args):
    cfg, _ = _ctx(args)
    print(f"Starting MoneyPrinterTurbo WebUI on http://127.0.0.1:{args.port} (private; Ctrl+C to stop)")
    return subprocess.call([str(cfg.mpt_python), "-m", "streamlit", "run", "webui/Main.py", "--server.address", "127.0.0.1",
                            "--server.port", str(args.port), "--server.headless", "true",
                            "--browser.gatherUsageStats", "false"], cwd=cfg.mpt_home)


# ------------------------------------------------------------------ research
def cmd_research(args):
    cfg, db = _ctx(args)
    r = research.Researcher(cfg, db, ErrorLog(cfg.logs_dir / "errors.jsonl")).run(save_dir=cfg.data_dir / "research")
    print(f"Sources: {json.dumps(r['sources_report'], indent=1)}")
    print(f"\nNew candidates stored: {r['stored_new']}  (duplicates skipped: {len(r['skipped_duplicates'])})")
    for c in r["candidates"][: args.top]:
        flag = "✔ verified" if c["verified"] else "? single-source"
        src = c["sources"][0]
        print(f"- [{c['category']}] {c['title'][:110]}\n    {flag} | {src['publisher']} | {src.get('published') or 'n/a'} | {src['url']}")
    print(f"\nSaved: {r.get('file')}")
    return 0


# ------------------------------------------------------------------ generate
def _pick_topic(db: DB, category: str | None):
    cats = STORY_CATEGORIES if category == "story" else NEWS_CATEGORIES if category in ("news", "ai_news") else None
    rows = [r for r in db.candidate_topics(limit=100) if r["verified"]]
    if cats:
        rows = [r for r in rows if r["category"] in cats] or rows
    return rows[0] if rows else None


def cmd_generate(args, kind: str):
    cfg, db = _ctx(args)
    if args.resume:
        row = db.get_job(args.resume)
        if not row:
            raise SystemExit(f"unknown job {args.resume}")
        res = pipeline.run(cfg, db, kind=row["kind"], topic=row["topic"], job_id=row["job_id"], redo_from=args.redo_from,
                           visual_engine=getattr(args, "engine", None), style_profile=getattr(args, "style_profile", None))
        _print(res)
        return 0 if res["quality_passed"] else 2
    sources: list[dict] = [{"id": f"s{i + 1}", "url": u, "title": u, "publisher": "", "published": "user-provided"}
                           for i, u in enumerate(args.source or [])]
    topic, topic_id = args.topic, None
    if args.storyboard:
        sb = sbmod.load(args.storyboard)
        topic = topic or sb.get("topic")
    elif not topic:
        row = _pick_topic(db, args.category)
        if not row:
            raise SystemExit("No verified topic available — run `research` first or pass --topic with --source URLs.")
        topic, topic_id = row["title"], row["id"]
        srcs = json.loads(row["sources"])
        sources = [{"id": f"s{i + 1}", **s} for i, s in enumerate(srcs)]
        if row["summary"]:
            sources[0]["summary"] = row["summary"]
    elif not sources:
        raise SystemExit("For headless generation pass --source URL(s) with --topic (facts must come from sources), "
                         "or let Claude Code write a storyboard and pass --storyboard.")
    dup = db.find_similar_topic(topic, cfg.get("research", "duplicate_similarity", default=0.6))
    if dup and not args.allow_duplicate:
        raise SystemExit(f"Duplicate topic: similar to already-used '{dup['title']}' (use --allow-duplicate to override)")
    voice = {"mohan": cfg.get("voice", "primary"), "shruti": cfg.get("voice", "alternate")}.get(args.voice, args.voice)
    res = pipeline.run(cfg, db, kind=kind, topic=topic, storyboard_path=args.storyboard, sources=sources,
                       job_id=args.job_id, voice=voice, visual_engine=getattr(args, "engine", None),
                       style_profile=getattr(args, "style_profile", None))
    if topic_id:
        db.set_topic_status(topic_id, "used")
    else:
        db.add_topic(topic, category="manual", status="used", verified=True,
                     sources=(sbmod.load(args.storyboard).get("sources") if args.storyboard else sources))
    _print(res)
    return 0 if res["quality_passed"] else 2


# ------------------------------------------------------------------ preview
def cmd_preview(args):
    cfg, db = _ctx(args)
    job = _latest_job(cfg, db, args.job)
    final = job / "final"
    timings = json.loads((job / "timings.json").read_text())
    sb = json.loads((job / "storyboard.json").read_text(encoding="utf-8"))
    meta = json.loads((final / "youtube_metadata.json").read_text(encoding="utf-8"))
    qa = json.loads((final / "quality_report.json").read_text(encoding="utf-8"))
    # contact sheet from the ACTUAL rendered file at each scene's midpoint
    from PIL import Image
    thumbs = []
    for i, tm in enumerate(timings):
        t = (tm["start"] + tm["end"]) / 2
        out = final / f".frame_{i:02d}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(final / "video.mp4"), "-frames:v", "1",
                        "-vf", "scale=270:-2", str(out)], check=True)
        thumbs.append(Image.open(out).copy())
        out.unlink()
    w, h = thumbs[0].size
    cols = min(5, len(thumbs))
    rows = -(-len(thumbs) // cols)
    sheet = Image.new("RGB", (w * cols, h * rows), (10, 10, 20))
    for i, im in enumerate(thumbs):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet_path = final / "contact_sheet.jpg"
    sheet.save(sheet_path, quality=88)
    checks = "".join(f"<li class='{'ok' if c['passed'] else 'bad'}'>{'✔' if c['passed'] else '✖'} {html.escape(c['check'])}"
                     f" — <small>{html.escape(str(c['detail']))}</small></li>" for c in qa["checks"])
    page = f"""<!doctype html><meta charset=utf-8><title>Preview — {html.escape(job.name)}</title>
<style>body{{font-family:system-ui,'Noto Sans Telugu';background:#0b1020;color:#e2e8f0;max-width:1100px;margin:auto;padding:16px}}
video{{max-height:80vh;border-radius:12px}} .ok{{color:#86efac}} .bad{{color:#fca5a5}} pre{{white-space:pre-wrap;background:#111827;padding:12px;border-radius:8px}}
img{{max-width:100%;border-radius:8px}}</style>
<h1>{html.escape(meta['selected_title'])}</h1><p>Status: <b>LOCAL PREVIEW ONLY — not uploaded</b></p>
<video src="video.mp4" controls></video>
<h2>Quality: {'PASS' if qa['passed'] else 'FAIL'}</h2><ul>{checks}</ul>
<h2>Title options</h2><ol>{''.join(f'<li>{html.escape(t)}</li>' for t in meta['titles'])}</ol>
<h2>Description</h2><pre>{html.escape(meta['description'])}</pre>
<h2>Pinned comment</h2><pre>{html.escape(meta['pinned_comment'])}</pre>
<h2>Thumbnail & cover</h2><img src="thumbnail.jpg"><br><img src="cover_short.png" style="max-height:600px">
<h2>Scenes</h2><img src="contact_sheet.jpg">
<p>Storyboard: storyboard.md · Subtitles: subtitles.te.srt, subtitles.te-Latn.srt · Licences: licenses.json</p>"""
    (final / "preview.html").write_text(page, encoding="utf-8")
    print(f"Video:         {final / 'video.mp4'}  ({qa['duration']:.1f}s, quality {'PASS' if qa['passed'] else 'FAIL'})")
    print(f"Preview page:  {final / 'preview.html'}")
    print(f"Contact sheet: {sheet_path}")
    print(f"Thumbnail:     {final / 'thumbnail.jpg'}\nCover:         {final / 'cover_short.png'}")
    print(f"Metadata:      {final / 'youtube_metadata.md'}\nStoryboard:    {final / 'storyboard.md'}")
    print(f"Scenes: {len(sb['scenes'])}; title: {meta['selected_title']}")
    return 0


# ------------------------------------------------------------------ publish
def cmd_publish(args):
    cfg, db = _ctx(args)
    if args.auth:
        youtube.authorize(cfg, interactive=True)
        print("YouTube authorized; token stored with 600 permissions in data/secrets/.")
        return 0
    job = _latest_job(cfg, db, args.job)
    kind = db.get_job(job.name)["kind"] if db.get_job(job.name) else "short"
    res = youtube.upload(cfg, db, job, kind=kind, privacy=args.privacy, approve_private=args.approve_private_upload,
                         approve_public=args.approve_public, publish_at=args.publish_at, dry_run=args.dry_run)
    _print(res)
    return 0


# ------------------------------------------------------------------ status
def cmd_status(args):
    cfg, db = _ctx(args)
    mpt_ok = cfg.mpt_python.is_file()
    print("== Telugu Tech Storytelling AI Agent ==")
    print(f"Engine: MoneyPrinterTurbo {'installed' if mpt_ok else 'MISSING'} at {cfg.mpt_home}")
    print(f"LLM: {cfg.get('llm', 'provider')} (claude CLI: {shutil.which('claude') or 'not found'})")
    from .premium import find_browser, remotion_dir
    rem_ok = (remotion_dir(cfg) / "node_modules" / "@remotion" / "cli").is_dir()
    print(f"Visual engine: {cfg.get('engine', 'visual_engine', default='classic')} | Remotion {'installed' if rem_ok else 'MISSING'}"
          f" | browser {'found' if find_browser(cfg) else 'not found'} | style profile: "
          f"{cfg.get('premium', 'style_profile', default='') or 'house preset (cinematic_tech)'}")
    print(f"Voice: {cfg.get('voice', 'primary')} / alt {cfg.get('voice', 'alternate')}")
    a = youtube.auth_status(cfg)
    print(f"YouTube: enabled={cfg.get('publishing', 'youtube_enabled')} client_secret={a['client_secrets_present']} "
          f"token={a['token_present']} allow_public={cfg.get('publishing', 'allow_public')}")
    print(f"Scheduler: enabled={cfg.get('scheduler', 'enabled')} (timezone {cfg.get('scheduler', 'timezone')})")
    for r in scheduler.upcoming(cfg):
        print(f"  - {r['name']}: next {r['next_run']} [{'on' if r['enabled'] else 'off'}]")
    print("\nRecent jobs:")
    for r in db.jobs(limit=args.limit):
        print(f"  {r['job_id']}  {r['kind']:<5} {r['status']:<9} stage={r['stage']}")
    print("\nVideos:")
    for v in db.videos(args.limit):
        up = db.upload_for_hash(v["sha256"])
        print(f"  {v['job_id']}  {v['duration']:.1f}s quality={'PASS' if v['quality_passed'] else 'FAIL'} "
              f"upload={'https://youtu.be/' + up['youtube_id'] if up else 'none'}\n    {v['path']}")
    errs = ErrorLog(cfg.logs_dir / "errors.jsonl").entries()
    blockers = [e for e in errs if e.get("blocker")]
    print(f"\nErrors logged: {len(errs)} (repaired {sum(1 for e in errs if e.get('repaired'))}, blockers {len(blockers)})")
    for e in blockers[-5:]:
        print(f"  BLOCKER [{e['category']}] {e['message'][:140]}")
    return 0


# ------------------------------------------------------------------ fix-errors
def cmd_fix_errors(args):
    cfg, db = _ctx(args)
    print("Running diagnostics with safe automatic repairs…")
    res = doctor.Doctor(cfg, fix=True).run(network=not args.offline)
    for r in res:
        if not r["ok"] or r["repaired"]:
            print(f"{'✔' if r['ok'] else '✖'} {r['check']}: {r['detail']}" + (f" [repaired: {r['repaired']}]" if r["repaired"] else ""))
    failed = db.jobs(status="failed", limit=10)
    blocked = db.jobs(status="blocked", limit=10)
    for b in blocked:
        print(f"⛔ {b['job_id']} is BLOCKED (auth/permission/quota/billing/policy) — needs your action; not retried.")
    for j in failed:
        if not args.resume_failed:
            print(f"↻ {j['job_id']} failed at stage {j['stage']} — re-run with --resume-failed to resume from checkpoint")
            continue
        print(f"↻ resuming {j['job_id']} from checkpoint (completed stages are reused)…")
        try:
            r = pipeline.run(cfg, db, kind=j["kind"], topic=j["topic"], job_id=j["job_id"])
            ErrorLog(cfg.logs_dir / "errors.jsonl").record(stage="resume", message=f"job {j['job_id']} resumed OK",
                                                           job_id=j["job_id"], repaired=True, repair_action="resumed from checkpoint")
            print(f"  ✔ completed, quality {'PASS' if r['quality_passed'] else 'FAIL'}")
        except AgentError as exc:
            print(f"  ✖ still failing [{exc.category.value}]: {redact(str(exc))[:200]}")
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks OK; failed jobs {len(failed)}, blocked {len(blocked)}")
    return 0


# ------------------------------------------------------------------ report
def cmd_report(args):
    cfg, db = _ctx(args)
    if args.gmail_auth:
        print("Gmail token saved:", report.gmail_auth(cfg))
        return 0
    r = report.build(cfg, db, args.day)
    paths = report.save_local(cfg, r)
    print(report.to_markdown(r))
    print(f"Saved locally: {paths['markdown']}")
    if cfg.get("reporting", "gmail_enabled", default=False):
        try:
            print("Gmail sent, id:", report.send_gmail(cfg, r))
        except AgentError as exc:
            print(f"Gmail not sent ({exc.category.value}): {exc} — report kept locally.")
    return 0


# ------------------------------------------------------------------ schedule
def cmd_schedule(args):
    cfg, db = _ctx(args)
    cli = shutil.which("telugu-tech") or str(Path(sys.executable).with_name("telugu-tech"))
    if args.action == "show":
        _print(scheduler.upcoming(cfg))
        print("\nCrontab block that `install` would add (only after approval):\n" + scheduler.crontab_block(cfg, cli))
    elif args.action == "install":
        print(scheduler.install(cfg, cli, approve=args.approve))
    elif args.action == "uninstall":
        print("removed" if scheduler.uninstall() else "nothing to remove")
    elif args.action == "tick":
        state_f = cfg.data_dir / "scheduler_state.json"
        state = json.loads(state_f.read_text()) if state_f.is_file() else {}
        for job in scheduler.due_jobs(cfg, state):
            print(f"running {job['name']} scheduled for {job['scheduled_for']}")
            state[job["name"]] = job["scheduled_for"]
            state_f.write_text(json.dumps(state))
            _run_scheduled(cfg, db, job)
    elif args.action == "run-job":
        job = next((j for j in cfg.get("scheduler", "jobs") if j["name"] == args.name), None)
        if not job:
            raise SystemExit(f"unknown job {args.name}")
        _run_scheduled(cfg, db, job)
    return 0


def cmd_premium(args):
    """/premium-video-editor commands."""
    cfg, db = _ctx(args)
    from . import reference
    if args.action == "analyze-reference":
        if not args.video:
            print("BLOCKED: no reference MP4 supplied. Instagram/TikTok links need a logged-in browser, so this tool "
                  "does not download them. Save the reel yourself (from your own account or with the creator's "
                  "permission) and run:\n  telugu-tech premium analyze-reference --video /path/to/reference.mp4", file=sys.stderr)
            return 3
        prof = reference.analyze(args.video, cfg.data_dir / "styles", args.name)
        print(Path(prof["files"]["report"]).read_text(encoding="utf-8"))
        print(f"Style profile: {prof['files']['profile']}")
        if args.activate:
            _set_yaml_value(cfg.path, "  style_profile:", f'  style_profile: "{os.path.relpath(prof["files"]["profile"], cfg.root)}"')
            print("Activated as premium.style_profile in config/project.yaml")
        return 0
    if args.action == "generate":
        ns = argparse.Namespace(**{**vars(args), "engine": "premium"})
        return cmd_generate(ns, "long" if args.long else "short")
    if args.action == "preview":
        return cmd_preview(argparse.Namespace(config=args.config, job=args.job))
    if args.action == "fix-errors":
        d = doctor.Doctor(cfg, fix=True)
        d.smoke = True
        res = d.run(network=not args.offline)
        for r in res:
            if not r["ok"] or r["repaired"] or "Remotion" in r["check"] or "Chrome" in r["check"] or "node" in r["check"]:
                print(f"{'✔' if r['ok'] else '✖'} {r['check']}: {r['detail']}" + (f" [repaired: {r['repaired']}]" if r["repaired"] else ""))
        for j in db.jobs(status="failed", limit=10):
            print(f"↻ resuming {j['job_id']} with the premium engine from its checkpoint…")
            try:
                r = pipeline.run(cfg, db, kind=j["kind"], topic=j["topic"], job_id=j["job_id"], visual_engine="premium")
                print(f"  ✔ quality {'PASS' if r['quality_passed'] else 'FAIL'}")
            except AgentError as exc:
                print(f"  ✖ [{exc.category.value}] {redact(str(exc))[:200]}")
        return 0
    if args.action == "report":
        rows = []
        for j in db.jobs(limit=30):
            cp = db.checkpoint(j["job_id"])
            eng = cp.get("visuals", {}).get("engine", "")
            if not eng:
                continue
            qa_f = cfg.jobs_dir / j["job_id"] / "final" / "quality_report.json"
            qa = json.loads(qa_f.read_text(encoding="utf-8")) if qa_f.is_file() else {}
            props_f = cfg.jobs_dir / j["job_id"] / "premium_props.json"
            props = json.loads(props_f.read_text(encoding="utf-8")) if props_f.is_file() else {}
            ev_f = cfg.jobs_dir / j["job_id"] / "sfx_events.json"
            rows.append({"job": j["job_id"], "engine": eng, "style": cp.get("visuals", {}).get("style_source", "—"),
                         "duration": qa.get("duration"), "quality": "PASS" if qa.get("passed") else "FAIL" if qa else "—",
                         "failed": [c["check"] for c in qa.get("checks", []) if not c["passed"]],
                         "transitions": sorted({s.get("transition") for s in props.get("scenes", [])}),
                         "cameras": sorted({s.get("camera") for s in props.get("scenes", [])}),
                         "visuals": [s["visual"]["type"] for s in props.get("scenes", [])],
                         "sfx": sorted({e[1] for e in json.loads(ev_f.read_text())}) if ev_f.is_file() else [],
                         "caption_words": len(props.get("words", []))})
        out = cfg.data_dir / "reports" / "premium-report.json"
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        for r in rows:
            print(f"- {r['job']}: {r['engine']} | style {r['style']} | {r['duration'] or 0:.1f}s | quality {r['quality']}"
                  + (f" (failed: {', '.join(r['failed'])})" if r["failed"] else ""))
            if r["visuals"]:
                print(f"    visuals: {', '.join(r['visuals'])}\n    transitions: {', '.join(r['transitions'])} | "
                      f"cameras: {', '.join(r['cameras'])} | sfx: {', '.join(r['sfx'])} | caption words: {r['caption_words']}")
        print(f"Saved: {out}")
        return 0
    return 1


def _set_yaml_value(path: Path, prefix: str, new_line: str) -> None:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    lines = [new_line + "   # set by premium analyze-reference" if l.startswith(prefix) else l for l in lines]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_scheduled(cfg, db, job):
    ns = argparse.Namespace(config=None, topic=None, storyboard=None, source=None, category=job.get("category"),
                            allow_duplicate=False, voice="mohan", job_id=None, resume=None, redo_from=None)
    research.Researcher(cfg, db, ErrorLog(cfg.logs_dir / "errors.jsonl")).run(save_dir=cfg.data_dir / "research")
    kind = "long" if job["command"] == "generate-long" else "short"
    try:
        cmd_generate(ns, kind)
        if cfg.get("scheduler", "auto_upload_private", default=False):
            youtube.upload(cfg, db, _latest_job(cfg, db, None), kind=kind, privacy="private", approve_private=True)
    finally:
        r = report.build(cfg, db)
        report.save_local(cfg, r)


# ------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="telugu-tech", description="Telugu Tech Storytelling AI Agent")
    p.add_argument("--config", default=None, help="path to project.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="install/repair MoneyPrinterTurbo, fonts, config; run diagnostics")
    s.add_argument("--offline", action="store_true")
    s.add_argument("--webui-test", action="store_true", help="start MPT WebUI on 127.0.0.1 briefly and probe it")

    s = sub.add_parser("research", help="discover & verify fresh topics")
    s.add_argument("--top", type=int, default=12)

    for name in ("generate-short", "generate-long"):
        s = sub.add_parser(name, help=f"produce a {name.split('-')[1]} video end to end")
        s.add_argument("--topic")
        s.add_argument("--storyboard", help="storyboard JSON (e.g. written by Claude Code in-session)")
        s.add_argument("--source", action="append", help="source URL for headless generation (repeatable)")
        s.add_argument("--category", default=None, help="news|story|<category> when auto-picking a topic")
        s.add_argument("--voice", default="mohan", help="mohan|shruti|<edge voice id>")
        s.add_argument("--job-id")
        s.add_argument("--resume", help="resume a job id from its checkpoint")
        s.add_argument("--redo-from", choices=pipeline.STAGES, help="with --resume: recompute this stage and later ones")
        s.add_argument("--allow-duplicate", action="store_true")
        s.add_argument("--engine", choices=["premium", "classic"], help="visual engine (default: engine.visual_engine)")
        s.add_argument("--style-profile", help="style profile JSON (from `premium analyze-reference`)")

    s = sub.add_parser("preview", help="local preview page + contact sheet from the rendered file")
    s.add_argument("--job")

    s = sub.add_parser("publish", help="YouTube upload (private by default; requires explicit approval)")
    s.add_argument("--job")
    s.add_argument("--auth", action="store_true", help="run the OAuth consent flow (on your own computer)")
    s.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    s.add_argument("--approve-private-upload", action="store_true")
    s.add_argument("--approve-public", action="store_true")
    s.add_argument("--publish-at", help="RFC3339 time for scheduled publishing (requires allow_scheduling)")
    s.add_argument("--dry-run", action="store_true", help="validate gates & show the API request without uploading")

    s = sub.add_parser("status", help="system, jobs, uploads, blockers, schedule")
    s.add_argument("--limit", type=int, default=10)

    s = sub.add_parser("fix-errors", help="diagnose, auto-repair safe problems, resume failed jobs")
    s.add_argument("--offline", action="store_true")
    s.add_argument("--resume-failed", action="store_true")

    s = sub.add_parser("report", help="daily report (local; Gmail if authorized)")
    s.add_argument("--day")
    s.add_argument("--gmail-auth", action="store_true")

    s = sub.add_parser("schedule", help="show/install/uninstall the IST schedule, or tick/run-job")
    s.add_argument("action", choices=["show", "install", "uninstall", "tick", "run-job"])
    s.add_argument("name", nargs="?")
    s.add_argument("--approve", action="store_true")

    s = sub.add_parser("premium", help="premium cinematic editor: analyze-reference | generate | preview | fix-errors | report")
    s.add_argument("action", choices=["analyze-reference", "generate", "preview", "fix-errors", "report"])
    s.add_argument("--video", help="reference MP4 (analyze-reference)")
    s.add_argument("--name", help="name for the style profile")
    s.add_argument("--activate", action="store_true", help="make the analysed profile the default premium style")
    s.add_argument("--long", action="store_true", help="generate a long video instead of a Short")
    s.add_argument("--topic")
    s.add_argument("--storyboard")
    s.add_argument("--source", action="append")
    s.add_argument("--category", default=None)
    s.add_argument("--voice", default="mohan")
    s.add_argument("--job-id")
    s.add_argument("--job", help="job for preview")
    s.add_argument("--resume")
    s.add_argument("--redo-from", choices=pipeline.STAGES)
    s.add_argument("--allow-duplicate", action="store_true")
    s.add_argument("--style-profile")
    s.add_argument("--offline", action="store_true")

    s = sub.add_parser("webui", help="run MoneyPrinterTurbo WebUI on 127.0.0.1")
    s.add_argument("--port", type=int, default=8501)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "setup": cmd_setup, "research": cmd_research, "preview": cmd_preview, "publish": cmd_publish,
        "status": cmd_status, "fix-errors": cmd_fix_errors, "report": cmd_report, "schedule": cmd_schedule,
        "webui": cmd_webui, "premium": cmd_premium,
        "generate-short": lambda a: cmd_generate(a, "short"), "generate-long": lambda a: cmd_generate(a, "long"),
    }
    try:
        return handlers[args.cmd](args) or 0
    except AgentError as exc:
        kind = "BLOCKER" if exc.is_blocker else "ERROR"
        print(f"{kind} [{exc.category.value}]: {redact(str(exc))}", file=sys.stderr)
        if exc.fix_hint:
            print(f"  → {exc.fix_hint}", file=sys.stderr)
        return 3 if exc.is_blocker else 1


if __name__ == "__main__":
    sys.exit(main())
