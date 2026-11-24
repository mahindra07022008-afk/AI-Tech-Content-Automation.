import json

import pytest

from telugu_tech import errors, research, youtube

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>X</title>
<item><title>OpenAI releases a new model</title><link>https://example.com/a</link>
<pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Hello&lt;/p&gt;</description></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>New startup raises funding</title><link rel="alternate" href="https://example.org/b"/>
<published>2026-11-22T08:00:00Z</published><summary>Funding round</summary></entry></feed>"""


def test_parse_rss_and_atom():
    a = research.parse_feed(RSS, "Example", "primary", "ai_news")
    assert a[0].sources[0].url == "https://example.com/a" and a[0].published.startswith("2026-11-23")
    assert a[0].summary == "Hello"
    b = research.parse_feed(ATOM, "Example", "news", "ai_news")
    assert b[0].sources[0].url == "https://example.org/b" and b[0].category == "startup_story"


def test_verification_rules():
    S = research.Source
    hn_only = research.Candidate("t", "", "ai_news", [S("https://blog.example.com/x", "t", "x", None, "news"),
                                                       S("https://news.ycombinator.com/item?id=1", "t", "HN", None, "community")])
    assert not hn_only.verified  # discussion links are not independent verification
    two_news = research.Candidate("t", "", "ai_news", [S("https://a.com/x", "t", "a", None, "news"),
                                                        S("https://b.com/y", "t", "b", None, "news")])
    assert two_news.verified
    primary = research.Candidate("t", "", "ai_news", [S("https://openai.com/x", "t", "OpenAI", None, "primary")])
    assert primary.verified


def test_policy_and_language_filters():
    assert research.is_blocked("find proxy configs that get you into Google")
    assert research.is_blocked("Free airdrop pump")
    assert not research.is_blocked("How transformers work")
    assert not research.mostly_latin_or_telugu("麦田：自媒体多平台发布中控")
    assert research.mostly_latin_or_telugu("GitHub అంటే ఏంటి")


def test_merge_combines_outlets():
    S = research.Source
    a = research.Candidate("Nvidia brings Jensen Huang back as CEO", "", "ai_news", [S("https://a.com/1", "", "a", None, "news")])
    b = research.Candidate("Nvidia brings back Jensen Huang as CEO", "", "ai_news", [S("https://b.com/2", "", "b", None, "news")])
    merged = research.Researcher.merge([a, b])
    assert len(merged) == 1 and merged[0].verified


class FakeResp:
    def __init__(self, code=200, text="", js=None):
        self.status_code, self.text, self._js = code, text, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_researcher_survives_failing_source(cfg, db):
    cfg.raw["research"].update({"feeds": [{"name": "Good", "url": "https://good/rss", "tier": "primary"},
                                          {"name": "Bad", "url": "https://bad/rss", "tier": "news"}],
                                "lookback_hours": 24 * 365 * 5})
    for k in ("github_trending", "hacker_news", "arxiv", "hf_daily_papers"):
        cfg.raw["research"][k] = {"enabled": False}

    def get(url, **kw):
        if "bad" in url:
            return FakeResp(403)
        return FakeResp(text=RSS)
    r = research.Researcher(cfg, db, http_get=get).run()
    assert r["stored_new"] == 1
    assert r["sources_report"]["feed:Bad"].startswith("failed")
    assert research.Researcher(cfg, db, http_get=get).run()["stored_new"] == 0  # already stored


# ---------------------------------------------------------------- youtube gates
def _job(cfg, passed=True):
    d = cfg.jobs_dir / "job1" / "final"
    d.mkdir(parents=True)
    (d / "video.mp4").write_bytes(b"\x00" * 20000)
    (d / "quality_report.json").write_text(json.dumps({"passed": passed}))
    (d / "youtube_metadata.json").write_text(json.dumps({
        "selected_title": "GitHub అంటే ఏంటి?", "titles": ["a", "b", "c"], "description": "desc", "keywords": ["github"],
        "category_id": "28", "default_language": "te", "made_for_kids": False, "contains_synthetic_media": True}))
    return d.parent


def test_upload_requires_quality_pass(cfg, db):
    with pytest.raises(errors.AgentError, match="quality"):
        youtube.upload(cfg, db, _job(cfg, passed=False), kind="short", approve_private=True)


def test_private_upload_requires_explicit_approval(cfg, db):
    with pytest.raises(errors.BlockerError, match="approval"):
        youtube.upload(cfg, db, _job(cfg), kind="short")


def test_public_is_blocked_by_default(cfg, db):
    with pytest.raises(errors.BlockerError, match="disabled"):
        youtube.upload(cfg, db, _job(cfg), kind="short", privacy="public", approve_public=True)


def test_dry_run_request_is_private_with_disclosures(cfg, db):
    r = youtube.upload(cfg, db, _job(cfg), kind="short", dry_run=True)
    st = r["request"]["status"]
    assert st["privacyStatus"] == "private" and st["containsSyntheticMedia"] is True
    assert st["selfDeclaredMadeForKids"] is False
    assert "#Shorts" in r["request"]["snippet"]["description"]


def test_youtube_disabled_blocks_real_upload(cfg, db):
    with pytest.raises(errors.BlockerError, match="youtube_enabled"):
        youtube.upload(cfg, db, _job(cfg), kind="short", approve_private=True)


def test_duplicate_upload_prevented(cfg, db):
    job = _job(cfg)
    from telugu_tech.db import sha256_file
    db.record_upload(sha256_file(job / "final" / "video.mp4"), "job1", "abc123", "private", "uploaded")
    with pytest.raises(errors.DuplicateError):
        youtube.upload(cfg, db, job, kind="short", approve_private=True)
