"""Daily schedule (Asia/Kolkata). Disabled until approved; installs a user crontab only on request."""
from __future__ import annotations

import shlex
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .errors import BlockerError, Category

MARK_BEGIN, MARK_END = "# >>> telugu-tech scheduler >>>", "# <<< telugu-tech scheduler <<<"


def _field(expr: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
        if a < lo or b > hi or a > b:
            raise ValueError(f"cron field out of range: {expr}")
        out.update(range(a, b + 1, step))
    return out


def parse_cron(expr: str) -> tuple[set[int], ...]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron needs 5 fields: {expr!r}")
    mi, h, dom, mon, dow = parts
    dows = {d % 7 for d in _field(dow, 0, 7)}
    return _field(mi, 0, 59), _field(h, 0, 23), _field(dom, 1, 31), _field(mon, 1, 12), dows


def next_run(expr: str, after: datetime) -> datetime:
    mi, h, dom, mon, dow = parse_cron(expr)
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        cron_dow = (t.weekday() + 1) % 7  # cron: 0 = Sunday
        if t.minute in mi and t.hour in h and t.day in dom and t.month in mon and cron_dow in dow:
            return t
        t += timedelta(minutes=1)
    raise ValueError(f"no run within a year for {expr}")


def upcoming(cfg, now: datetime | None = None) -> list[dict]:
    tz = ZoneInfo(cfg.get("scheduler", "timezone", default="Asia/Kolkata"))
    now = (now or datetime.now(tz)).astimezone(tz)
    rows = []
    for job in cfg.get("scheduler", "jobs", default=[]):
        enabled = cfg.get("scheduler", "enabled", default=False) and job.get("enabled", True)
        rows.append({"name": job["name"], "cron": job["cron"], "command": job["command"],
                     "category": job.get("category"), "enabled": bool(enabled),
                     "next_run": next_run(job["cron"], now).isoformat()})
    return sorted(rows, key=lambda r: r["next_run"])


def prev_run(expr: str, at: datetime) -> datetime | None:
    """Most recent scheduled minute <= at (searches back 8 days)."""
    mi, h, dom, mon, dow = parse_cron(expr)
    t = at.replace(second=0, microsecond=0)
    for _ in range(8 * 24 * 60):
        if t.minute in mi and t.hour in h and t.day in dom and t.month in mon and (t.weekday() + 1) % 7 in dow:
            return t
        t -= timedelta(minutes=1)
    return None


def due_jobs(cfg, state: dict, now: datetime | None = None, grace_minutes: int = 30) -> list[dict]:
    """Jobs whose latest scheduled time (Asia/Kolkata) is within the grace window and not yet run.

    Evaluated in the configured timezone inside Python, so it works with any system cron
    (Debian/Ubuntu cron ignores CRON_TZ) and any server timezone.
    """
    if not cfg.get("scheduler", "enabled", default=False):
        return []
    tz = ZoneInfo(cfg.get("scheduler", "timezone", default="Asia/Kolkata"))
    now = (now or datetime.now(tz)).astimezone(tz)
    out = []
    for job in cfg.get("scheduler", "jobs", default=[]):
        if not job.get("enabled", True):
            continue
        p = prev_run(job["cron"], now)
        if p is None or (now - p) > timedelta(minutes=grace_minutes):
            continue
        if state.get(job["name"]) == p.isoformat():
            continue
        out.append({**job, "scheduled_for": p.isoformat()})
    return out


def crontab_block(cfg, cli_path: str) -> str:
    root = shlex.quote(str(cfg.root))
    tick = (f"*/5 * * * * cd {root} && {shlex.quote(cli_path)} schedule tick "
            f">> {root}/data/logs/scheduler.log 2>&1")
    tz = cfg.get("scheduler", "timezone", default="Asia/Kolkata")
    return "\n".join([MARK_BEGIN, f"# jobs are evaluated in {tz} by `schedule tick`", tick, MARK_END]) + "\n"


def install(cfg, cli_path: str, *, approve: bool) -> str:
    if not cfg.get("scheduler", "enabled", default=False) or not approve:
        raise BlockerError("scheduler activation needs scheduler.enabled: true AND --approve", Category.PERMISSION)
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = current.stdout if current.returncode == 0 else ""
    if MARK_BEGIN in existing:  # replace only our block, keep the user's other entries
        pre, rest = existing.split(MARK_BEGIN, 1)
        post = rest.split(MARK_END, 1)[1] if MARK_END in rest else ""
        existing = pre + post.lstrip("\n")
    new = existing.rstrip("\n") + ("\n" if existing.strip() else "") + crontab_block(cfg, cli_path)
    r = subprocess.run(["crontab", "-"], input=new, text=True, capture_output=True)
    if r.returncode != 0:
        raise BlockerError(f"crontab install failed: {r.stderr.strip()}", Category.PERMISSION)
    return new


def uninstall() -> bool:
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if current.returncode != 0 or MARK_BEGIN not in current.stdout:
        return False
    pre, rest = current.stdout.split(MARK_BEGIN, 1)
    post = rest.split(MARK_END, 1)[1] if MARK_END in rest else ""
    subprocess.run(["crontab", "-"], input=(pre + post.lstrip("\n")), text=True, check=True)
    return True
