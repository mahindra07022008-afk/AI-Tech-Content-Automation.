"""SQLite content-history database: topics, jobs/checkpoints, videos, uploads, errors, usage."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    category TEXT,
    summary TEXT,
    sources TEXT NOT NULL DEFAULT '[]',      -- JSON [{url,title,publisher,published,tier}]
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    score REAL DEFAULT 0,
    verified INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'candidate' -- candidate|selected|used|rejected
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                       -- short|long
    topic TEXT NOT NULL,
    topic_id INTEGER,
    status TEXT NOT NULL,                     -- running|failed|completed|blocked
    stage TEXT,
    checkpoint TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    duration REAL,
    quality_passed INTEGER DEFAULT 0,
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_sha256 TEXT NOT NULL UNIQUE,
    job_id TEXT,
    youtube_id TEXT,
    privacy TEXT,
    status TEXT NOT NULL,                     -- uploaded|failed|dry_run
    detail TEXT,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    service TEXT NOT NULL,
    units REAL NOT NULL,
    cost_usd REAL NOT NULL DEFAULT 0,
    note TEXT
);
"""

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "for", "and", "on", "with", "is", "are", "how", "why", "what",
    "new", "its", "by", "from", "at", "as", "your", "you", "this", "that", "now",
    "అంటే", "ఏంటి", "ఎందుకు", "ఎలా", "ఈ", "ఒక",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFC", text.lower())
    words = re.findall(r"[\wఀ-౿]+", text)
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def fingerprint(text: str) -> str:
    return hashlib.sha1(" ".join(sorted(tokens(text))).encode()).hexdigest()


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------ topics
    def find_similar_topic(self, title: str, threshold: float = 0.6,
                           statuses: Iterable[str] = ("selected", "used")) -> sqlite3.Row | None:
        statuses = tuple(statuses)
        q = f"SELECT * FROM topics WHERE status IN ({','.join('?' * len(statuses))})"
        best, best_score = None, 0.0
        for row in self.conn.execute(q, statuses):
            s = jaccard(title, row["title"])
            if s >= threshold and s > best_score:
                best, best_score = row, s
        return best

    def add_topic(self, title: str, *, category: str = "", summary: str = "", sources: list[dict] | None = None,
                  published_at: str | None = None, score: float = 0.0, verified: bool = False,
                  status: str = "candidate") -> int | None:
        """Insert a topic; returns id, or None if an identical fingerprint exists."""
        fp = fingerprint(title)
        try:
            cur = self.conn.execute(
                "INSERT INTO topics(title,fingerprint,category,summary,sources,published_at,discovered_at,score,verified,status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (title, fp, category, summary, json.dumps(sources or [], ensure_ascii=False), published_at,
                 now_iso(), score, int(verified), status))
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def set_topic_status(self, topic_id: int, status: str) -> None:
        self.conn.execute("UPDATE topics SET status=? WHERE id=?", (status, topic_id))
        self.conn.commit()

    def get_topic(self, topic_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()

    def candidate_topics(self, category: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
        q = "SELECT * FROM topics WHERE status='candidate'"
        args: list[Any] = []
        if category:
            q += " AND category=?"
            args.append(category)
        q += " ORDER BY verified DESC, score DESC, discovered_at DESC LIMIT ?"
        args.append(limit)
        return list(self.conn.execute(q, args))

    def topics_since(self, iso_ts: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM topics WHERE discovered_at>=? ORDER BY score DESC", (iso_ts,)))

    # ------------------------------------------------------------ jobs / checkpoints
    def create_job(self, job_id: str, kind: str, topic: str, topic_id: int | None = None) -> None:
        ts = now_iso()
        self.conn.execute(
            "INSERT OR IGNORE INTO jobs(job_id,kind,topic,topic_id,status,stage,checkpoint,created_at,updated_at)"
            " VALUES (?,?,?,?, 'running', NULL, '{}', ?, ?)", (job_id, kind, topic, topic_id, ts, ts))
        self.conn.commit()

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()

    def checkpoint(self, job_id: str) -> dict:
        row = self.get_job(job_id)
        return json.loads(row["checkpoint"]) if row else {}

    def mark_stage(self, job_id: str, stage: str, data: dict | None = None, status: str = "running") -> None:
        cp = self.checkpoint(job_id)
        cp[stage] = {"done": True, "at": now_iso(), **(data or {})}
        self.conn.execute("UPDATE jobs SET checkpoint=?, stage=?, status=?, updated_at=? WHERE job_id=?",
                          (json.dumps(cp, ensure_ascii=False), stage, status, now_iso(), job_id))
        self.conn.commit()

    def clear_stages(self, job_id: str, stages: list[str]) -> None:
        cp = {k: v for k, v in self.checkpoint(job_id).items() if k not in stages}
        self.conn.execute("UPDATE jobs SET checkpoint=?, updated_at=? WHERE job_id=?",
                          (json.dumps(cp, ensure_ascii=False), now_iso(), job_id))
        self.conn.commit()

    def set_job_status(self, job_id: str, status: str, stage: str | None = None) -> None:
        self.conn.execute("UPDATE jobs SET status=?, stage=COALESCE(?, stage), updated_at=? WHERE job_id=?",
                          (status, stage, now_iso(), job_id))
        self.conn.commit()

    def jobs(self, status: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if status:
            return list(self.conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                                          (status, limit)))
        return list(self.conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)))

    # ------------------------------------------------------------ videos / uploads
    def add_video(self, job_id: str, kind: str, path: str, sha: str, duration: float, quality_passed: bool,
                  meta: dict | None = None) -> None:
        # one current video per job: a re-render replaces the job's previous record
        self.conn.execute("DELETE FROM videos WHERE job_id=? AND sha256<>?", (job_id, sha))
        self.conn.execute(
            "INSERT INTO videos(job_id,kind,path,sha256,duration,quality_passed,meta,created_at) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(sha256) DO UPDATE SET quality_passed=excluded.quality_passed, meta=excluded.meta, path=excluded.path",
            (job_id, kind, path, sha, duration, int(quality_passed), json.dumps(meta or {}, ensure_ascii=False), now_iso()))
        self.conn.commit()

    def videos(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM videos ORDER BY created_at DESC LIMIT ?", (limit,)))

    def video_for_job(self, job_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM videos WHERE job_id=? ORDER BY created_at DESC", (job_id,)).fetchone()

    def upload_for_hash(self, sha: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM uploads WHERE video_sha256=? AND status='uploaded'", (sha,)).fetchone()

    def record_upload(self, sha: str, job_id: str, youtube_id: str | None, privacy: str, status: str,
                      detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO uploads(video_sha256,job_id,youtube_id,privacy,status,detail,uploaded_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(video_sha256) DO UPDATE SET youtube_id=excluded.youtube_id, privacy=excluded.privacy,"
            " status=excluded.status, detail=excluded.detail, uploaded_at=excluded.uploaded_at",
            (sha, job_id, youtube_id, privacy, status, detail, now_iso()))
        self.conn.commit()

    def uploads(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM uploads ORDER BY uploaded_at DESC LIMIT ?", (limit,)))

    # ------------------------------------------------------------ usage / cost
    def add_usage(self, service: str, units: float, cost_usd: float = 0.0, note: str = "") -> None:
        self.conn.execute("INSERT INTO usage(day,service,units,cost_usd,note) VALUES (?,?,?,?,?)",
                          (datetime.now(timezone.utc).date().isoformat(), service, units, cost_usd, note))
        self.conn.commit()

    def usage_for_day(self, day: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT service, SUM(units) AS units, SUM(cost_usd) AS cost FROM usage WHERE day=? GROUP BY service", (day,)))
