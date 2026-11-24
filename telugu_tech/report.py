"""Daily report: saved locally always; e-mailed via Gmail API only if authorized and enabled."""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import DB
from .errors import AgentError, BlockerError, Category, ErrorLog
from .scheduler import upcoming

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def build(cfg, db: DB, day: str | None = None) -> dict:
    tz = ZoneInfo(cfg.get("project", "timezone", default="Asia/Kolkata"))
    now = datetime.now(tz)
    day = day or now.date().isoformat()
    start = datetime.fromisoformat(day).replace(tzinfo=tz).astimezone(timezone.utc).isoformat(timespec="seconds")
    end = (datetime.fromisoformat(day).replace(tzinfo=tz) + timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds")
    topics = [dict(r) for r in db.topics_since(start) if r["discovered_at"] < end]
    jobs = [dict(r) for r in db.jobs(limit=200) if start <= r["updated_at"] < end]
    videos = [dict(r) for r in db.videos(200) if start <= r["created_at"] < end]
    uploads = [dict(r) for r in db.uploads(200) if start <= r["uploaded_at"] < end]
    errors = [e for e in ErrorLog(cfg.logs_dir / "errors.jsonl").entries() if start <= e["ts"] < end]
    vid_rows = []
    for v in videos:
        job_dir = cfg.jobs_dir / v["job_id"]
        qa_file = job_dir / "final" / "quality_report.json"
        qa = json.loads(qa_file.read_text(encoding="utf-8")) if qa_file.is_file() else {}
        lic = job_dir / "final" / "licenses.json"
        up = next((u for u in db.uploads(500) if u["video_sha256"] == v["sha256"]), None)
        vid_rows.append({
            "job_id": v["job_id"], "kind": v["kind"], "path": v["path"], "duration": v["duration"],
            "rendering": "rendered", "quality_passed": bool(v["quality_passed"]),
            "failed_checks": [c["check"] for c in qa.get("checks", []) if not c["passed"]],
            "copyright_review": "original assets only; manifest present" if lic.is_file() else "MISSING manifest",
            "publishing": (up["status"] + f" ({up['privacy']})") if up else "not uploaded (local preview only)",
            "youtube_url": f"https://youtu.be/{up['youtube_id']}" if up and up["youtube_id"] else None,
        })
    usage = [dict(r) for r in db.usage_for_day(datetime.fromisoformat(start).date().isoformat())]
    blockers = sorted({f"{e['category']}: {e['message'][:120]}" for e in errors if e.get("blocker")})
    nxt = upcoming(cfg)
    return {
        "day": day, "generated_at": now.isoformat(timespec="seconds"),
        "topics_researched": [{"title": t["title"], "category": t["category"], "verified": bool(t["verified"]),
                               "sources": [s["url"] for s in json.loads(t["sources"])][:3]} for t in topics[:25]],
        "jobs": [{"job_id": j["job_id"], "kind": j["kind"], "status": j["status"], "stage": j["stage"]} for j in jobs],
        "uploads": [{"job_id": u["job_id"], "youtube_id": u["youtube_id"], "privacy": u["privacy"], "status": u["status"]} for u in uploads],
        "videos": vid_rows,
        "errors_detected": [e for e in errors if not e.get("repaired")],
        "errors_repaired": [e for e in errors if e.get("repaired")],
        "remaining_blockers": blockers,
        "api_usage": usage,
        "additional_cost_usd": round(sum(u.get("cost") or 0 for u in usage), 2),
        "next_scheduled_task": nxt[0] if nxt else None,
        "scheduler_enabled": cfg.get("scheduler", "enabled", default=False),
    }


def to_markdown(r: dict) -> str:
    L = [f"# Telugu Tech daily report — {r['day']}", "", f"_Generated {r['generated_at']}_", ""]
    L += [f"## Topics researched ({len(r['topics_researched'])})"]
    L += [f"- [{'✔' if t['verified'] else '?'}] ({t['category']}) {t['title']} — {', '.join(t['sources'][:1])}"
          for t in r["topics_researched"]] or ["- none"]
    L += ["", f"## Videos generated ({len(r['videos'])})", "",
          "| Job | Kind | File | Duration | Quality | Copyright/sources | Publishing | URL |",
          "|---|---|---|---|---|---|---|---|"]
    for v in r["videos"]:
        q = "PASS" if v["quality_passed"] else "FAIL: " + ", ".join(v["failed_checks"])
        L.append(f"| {v['job_id']} | {v['kind']} | `{v['path']}` | {v['duration']:.1f}s | {q} | {v['copyright_review']} | "
                 f"{v['publishing']} | {v['youtube_url'] or '—'} |")
    L += ["", f"## Errors detected ({len(r['errors_detected'])})"]
    L += [f"- {e['ts']} [{e['category']}] {e['stage']}: {e['message'][:160]}" for e in r["errors_detected"]] or ["- none"]
    L += ["", f"## Errors repaired automatically ({len(r['errors_repaired'])})"]
    L += [f"- {e['ts']} [{e['category']}] {e['repair_action']}" for e in r["errors_repaired"]] or ["- none"]
    L += ["", "## Remaining blockers"] + ([f"- {b}" for b in r["remaining_blockers"]] or ["- none"])
    L += ["", "## API usage & cost"]
    L += [f"- {u['service']}: {u['units']} units" for u in r["api_usage"]] or ["- no metered API usage recorded"]
    L += [f"- Additional spend: ${r['additional_cost_usd']:.2f} (Edge TTS, research APIs, rendering: free/local; "
          "LLM via existing Claude subscription)"]
    n = r["next_scheduled_task"]
    L += ["", "## Next scheduled task",
          f"- {n['name']} at {n['next_run']} ({'ENABLED' if n['enabled'] else 'disabled — awaiting approval'})" if n else "- none"]
    return "\n".join(L) + "\n"


def save_local(cfg, r: dict) -> dict:
    out = cfg.resolve(cfg.get("reporting", "local_dir", default="data/reports"))
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / f"report-{r['day']}.md", out / f"report-{r['day']}.json"
    md.write_text(to_markdown(r), encoding="utf-8")
    js.write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"markdown": str(md), "json": str(js)}


def send_gmail(cfg, r: dict) -> str:
    """Send via Gmail API (gmail.send scope) using a token the user created with consent."""
    if not cfg.get("reporting", "gmail_enabled", default=False):
        raise BlockerError("Gmail reporting disabled (reporting.gmail_enabled=false)", Category.PERMISSION)
    to = os.environ.get("REPORT_EMAIL_TO", "").strip()
    token = cfg.resolve(os.environ.get("GMAIL_TOKEN_FILE", "data/secrets/gmail_token.json"))
    if not to or not token.is_file():
        raise BlockerError("Gmail not authorized (missing REPORT_EMAIL_TO or gmail token)", Category.AUTH,
                           fix_hint="run: telugu-tech report --gmail-auth (uses your Google OAuth client)")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build as gbuild
    except ImportError as exc:
        raise AgentError("google client libraries missing", Category.DEPENDENCY) from exc
    creds = Credentials.from_authorized_user_file(str(token), GMAIL_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise BlockerError("Gmail token invalid", Category.AUTH)
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = f"Telugu Tech daily report — {r['day']}"
    msg.set_content(to_markdown(r))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = gbuild("gmail", "v1", credentials=creds, cache_discovery=False).users().messages().send(
        userId="me", body={"raw": raw}).execute()
    return sent.get("id", "")


def gmail_auth(cfg) -> Path:
    from google_auth_oauthlib.flow import InstalledAppFlow
    secrets = cfg.resolve(os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE", "data/secrets/client_secret.json"))
    if not secrets.is_file():
        raise BlockerError(f"OAuth client file not found: {secrets}", Category.AUTH)
    creds = InstalledAppFlow.from_client_secrets_file(str(secrets), GMAIL_SCOPES).run_local_server(
        host="localhost", bind_addr="127.0.0.1", port=0)
    token = cfg.resolve(os.environ.get("GMAIL_TOKEN_FILE", "data/secrets/gmail_token.json"))
    token.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(token, 0o600)
    return token
