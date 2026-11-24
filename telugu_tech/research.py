"""Topic discovery from reliable sources, with source tiers, verification and dedup.

Sources: official RSS/Atom feeds (primary), credible tech news feeds, GitHub Search API
(trending new repos), Hacker News (Algolia API), arXiv API, Hugging Face daily papers.
Nothing is invented: every candidate carries its source URL and publication date.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from .db import DB, jaccard
from .errors import AgentError, Category, ErrorLog, retry_call

CATEGORY_KEYWORDS = {
    "ai_news": ["gpt", "gemini", "claude", "llm", "model", "openai", "anthropic", "deepmind", "launch", "release"],
    "ai_tools": ["tool", "agent", "copilot", "assistant", "plugin", "api", "sdk", "app"],
    "startup_story": ["startup", "raises", "funding", "acquire", "acquisition", "ipo", "shuts down", "layoff", "founder"],
    "github_trending": ["github", "open source", "open-source", "repository", "repo"],
    "research": ["paper", "arxiv", "benchmark", "dataset", "study", "researchers"],
    "future_tech": ["quantum", "robot", "humanoid", "fusion", "brain-computer", "space", "chip", "semiconductor"],
    "how_it_works": ["how", "works", "explained", "under the hood", "architecture"],
    "tutorial": ["tutorial", "guide", "build", "automation", "step-by-step", "learn"],
    "history": ["history", "invented", "anniversary", "years ago", "origin"],
}


@dataclass
class Source:
    url: str
    title: str
    publisher: str
    published: str | None
    tier: str  # primary | news | research | repo | community

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.lower().removeprefix("www.")


@dataclass
class Candidate:
    title: str
    summary: str
    category: str
    sources: list[Source] = field(default_factory=list)
    score: float = 0.0
    published: str | None = None

    @property
    def verified(self) -> bool:
        """Verified = a primary/research/repo source, or 2+ independent non-community domains.
        (Community discussion such as Hacker News is useful signal but never counts as verification.)"""
        tiers = {s.tier for s in self.sources}
        domains = {s.domain for s in self.sources if s.tier != "community"}
        return bool(tiers & {"primary", "research", "repo"}) or len(domains) >= 2

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verified"] = self.verified
        return d


# Topics the channel must not promote (policy / safety / scams). Matched case-insensitively.
BLOCKED_TERMS = ["bypass", "proxy config", "get you into", "crack", "keygen", "pirat", "airdrop", "pump", "casino",
                 "betting", "hack account", "stealer", "phishing", "exploit kit", "ddos", "nsfw", "deepfake porn",
                 "jailbreak", "unlock region", "spoof", "cheat"]


def is_blocked(text: str) -> bool:
    t = text.lower()
    return any(b in t for b in BLOCKED_TERMS)


def mostly_latin_or_telugu(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ok = sum(1 for c in letters if c.isascii() or "\u0C00" <= c <= "\u0C7F")
    return ok / len(letters) >= 0.7


def categorize(text: str, default: str = "ai_news") -> str:
    t = text.lower()
    best, hits = default, 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        n = sum(1 for k in kws if k in t)
        if n > hits:
            best, hits = cat, n
    return best


def _clean(text: str | None, limit: int = 400) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str, publisher: str, tier: str, category: str) -> list[Candidate]:
    """Parse RSS 2.0 or Atom into candidates."""
    out: list[Candidate] = []
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item")
    if items:
        for it in items:
            title = _clean(it.findtext("title"), 200)
            link = (it.findtext("link") or "").strip()
            date = _parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"))
            if title and link:
                out.append(Candidate(title=title, summary=_clean(it.findtext("description")),
                                     category=categorize(title, category),
                                     sources=[Source(link, title, publisher, date.isoformat() if date else None, tier)],
                                     published=date.isoformat() if date else None))
    else:
        for e in root.findall("a:entry", ns):
            title = _clean(e.findtext("a:title", namespaces=ns), 200)
            # Note: Element truthiness depends on children, so compare with None explicitly.
            link_el = e.find("a:link[@rel='alternate']", ns)
            if link_el is None:
                link_el = e.find("a:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            date = _parse_date(e.findtext("a:published", namespaces=ns) or e.findtext("a:updated", namespaces=ns))
            summary = _clean(e.findtext("a:summary", namespaces=ns) or e.findtext("a:content", namespaces=ns))
            if title and link:
                out.append(Candidate(title=title, summary=summary, category=categorize(title, category),
                                     sources=[Source(link, title, publisher, date.isoformat() if date else None, tier)],
                                     published=date.isoformat() if date else None))
    return out


class Researcher:
    def __init__(self, cfg, db: DB, errlog: ErrorLog | None = None,
                 http_get: Callable[..., requests.Response] | None = None):
        self.cfg = cfg
        self.db = db
        self.errlog = errlog
        self.session = requests.Session()
        self.session.headers["User-Agent"] = cfg.get("research", "user_agent", default="TeluguTechResearch/0.1")
        self._get = http_get or self.session.get
        self.lookback = timedelta(hours=cfg.get("research", "lookback_hours", default=72))
        self.report: dict[str, str] = {}

    # -------------------------------------------------------------- http
    def _fetch(self, url: str, **kw) -> requests.Response:
        def go():
            r = self._get(url, timeout=25, **kw)
            if r.status_code == 429:
                raise AgentError(f"429 rate limited by {urlparse(url).netloc}", Category.RATE_LIMIT)
            if r.status_code >= 500:
                raise AgentError(f"{r.status_code} from {urlparse(url).netloc}", Category.NETWORK)
            if r.status_code in (401, 403):
                raise AgentError(f"{r.status_code} from {urlparse(url).netloc}", Category.PERMISSION, retryable=False)
            r.raise_for_status()
            return r
        return retry_call(go, max_attempts=self.cfg.get("retry", "max_attempts", default=3),
                          base=self.cfg.get("retry", "base_delay_seconds", default=2.0))

    def _safe(self, name: str, fn: Callable[[], list[Candidate]]) -> list[Candidate]:
        try:
            items = fn()
            self.report[name] = f"ok ({len(items)})"
            return items
        except Exception as exc:  # noqa: BLE001 - one source failing must not stop research
            self.report[name] = f"failed: {type(exc).__name__}: {str(exc)[:120]}"
            if self.errlog:
                self.errlog.record(stage=f"research:{name}", exc=exc)
            return []

    # -------------------------------------------------------------- sources
    def from_feeds(self) -> list[Candidate]:
        out: list[Candidate] = []
        cutoff = datetime.now(timezone.utc) - self.lookback
        for feed in self.cfg.get("research", "feeds", default=[]):
            def one(feed=feed):
                r = self._fetch(feed["url"], allow_redirects=True)
                items = parse_feed(r.text, feed["name"], feed.get("tier", "news"), feed.get("category", "ai_news"))
                recent = [c for c in items if not c.published or _parse_date(c.published) >= cutoff]
                for c in recent:
                    c.score = 3.0 if feed.get("tier") == "primary" else 2.0
                return recent
            out += self._safe(f"feed:{feed['name']}", one)
        return out

    def from_github(self) -> list[Candidate]:
        gh = self.cfg.get("research", "github_trending", default={}) or {}
        if not gh.get("enabled"):
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
        headers = {"Accept": "application/vnd.github+json"}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
        out: list[Candidate] = []
        for topic in gh.get("topics", ["ai"]):
            def one(topic=topic):
                r = self._fetch("https://api.github.com/search/repositories",
                                params={"q": f"topic:{topic} created:>{since}", "sort": "stars", "order": "desc",
                                        "per_page": 5}, headers=headers)
                items = []
                for repo in r.json().get("items", []):
                    title = f"{repo['full_name']}: {repo.get('description') or ''}".strip(": ")
                    items.append(Candidate(
                        title=_clean(title, 200), summary=f"⭐ {repo['stargazers_count']} stars, language "
                        f"{repo.get('language') or 'n/a'}, created {repo['created_at'][:10]}",
                        category="github_trending",
                        sources=[Source(repo["html_url"], repo["full_name"], "GitHub", repo["created_at"], "repo")],
                        score=1.0 + min(2.0, repo["stargazers_count"] / 1000), published=repo["created_at"]))
                return items
            out += self._safe(f"github:{topic}", one)
        return out

    def from_hacker_news(self) -> list[Candidate]:
        hn = self.cfg.get("research", "hacker_news", default={}) or {}
        if not hn.get("enabled"):
            return []
        since = int((datetime.now(timezone.utc) - self.lookback).timestamp())

        def one():
            r = self._fetch("https://hn.algolia.com/api/v1/search", params={
                "tags": "story", "query": "AI", "hitsPerPage": 30,
                "numericFilters": f"created_at_i>{since},points>{hn.get('min_points', 150)}"})
            items = []
            for h in r.json().get("hits", []):
                url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
                title = _clean(h.get("title"), 200)
                srcs = [Source(url, title, urlparse(url).netloc, h.get("created_at"), "news"),
                        Source(f"https://news.ycombinator.com/item?id={h['objectID']}", title, "Hacker News",
                               h.get("created_at"), "community")]
                items.append(Candidate(title=title, summary=f"{h.get('points')} points on Hacker News",
                                       category=categorize(title), sources=srcs,
                                       score=min(5.0, h.get("points", 0) / 200), published=h.get("created_at")))
            return items
        return self._safe("hacker_news", one)

    def from_arxiv(self) -> list[Candidate]:
        ax = self.cfg.get("research", "arxiv", default={}) or {}
        if not ax.get("enabled"):
            return []

        def one():
            q = " OR ".join(f"cat:{c}" for c in ax.get("categories", ["cs.AI"]))
            r = self._fetch("https://export.arxiv.org/api/query", params={
                "search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 10})
            items = parse_feed(r.text, "arXiv", "research", "research")
            for c in items:
                c.category, c.score = "research", 1.5
            return items
        return self._safe("arxiv", one)

    def from_hf_papers(self) -> list[Candidate]:
        if not (self.cfg.get("research", "hf_daily_papers", default={}) or {}).get("enabled"):
            return []

        def one():
            r = self._fetch("https://huggingface.co/api/daily_papers")
            items = []
            for p in r.json()[:10]:
                paper = p.get("paper", {})
                pid, title = paper.get("id"), _clean(paper.get("title"), 200)
                if not pid or not title:
                    continue
                items.append(Candidate(
                    title=title, summary=_clean(paper.get("summary"), 300), category="research",
                    sources=[Source(f"https://arxiv.org/abs/{pid}", title, "arXiv", paper.get("publishedAt"), "research"),
                             Source(f"https://huggingface.co/papers/{pid}", title, "Hugging Face Papers",
                                    paper.get("publishedAt"), "community")],
                    score=min(4.0, 1.0 + (paper.get("upvotes") or 0) / 30), published=paper.get("publishedAt")))
            return items
        return self._safe("hf_daily_papers", one)

    # -------------------------------------------------------------- merge / store
    @staticmethod
    def merge(cands: list[Candidate], threshold: float = 0.5) -> list[Candidate]:
        """Merge near-duplicate stories from different outlets (raises verification)."""
        merged: list[Candidate] = []
        for c in cands:
            for m in merged:
                if jaccard(c.title, m.title) >= threshold:
                    known = {s.url for s in m.sources}
                    m.sources += [s for s in c.sources if s.url not in known]
                    m.score += 0.5 * c.score
                    break
            else:
                merged.append(c)
        return merged

    def run(self, save_dir: Path | None = None) -> dict:
        cands = (self.from_feeds() + self.from_github() + self.from_hacker_news()
                 + self.from_arxiv() + self.from_hf_papers())
        rejected = [c.title for c in cands if is_blocked(f"{c.title} {c.summary}") or not mostly_latin_or_telugu(c.title)]
        cands = [c for c in cands if c.title not in rejected]
        merged = self.merge(cands)
        threshold = self.cfg.get("research", "duplicate_similarity", default=0.6)
        fresh, dupes = [], []
        for c in merged:
            c.score += 1.0 if c.verified else 0.0
            if self.db.find_similar_topic(c.title, threshold):
                dupes.append(c)
                continue
            fresh.append(c)
        fresh.sort(key=lambda c: (c.verified, c.score), reverse=True)
        fresh = fresh[: self.cfg.get("research", "max_candidates", default=40)]
        stored = 0
        for c in fresh:
            tid = self.db.add_topic(c.title, category=c.category, summary=c.summary,
                                    sources=[asdict(s) for s in c.sources], published_at=c.published,
                                    score=c.score, verified=c.verified)
            stored += tid is not None
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources_report": self.report,
            "candidates": [c.to_dict() for c in fresh],
            "skipped_duplicates": [c.title for c in dupes],
            "rejected_by_policy_or_language": rejected,
            "stored_new": stored,
        }
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            path = save_dir / f"research-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            result["file"] = str(path)
        return result
