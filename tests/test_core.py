import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from telugu_tech import errors, scheduler, seo, storyboard, subtitles
from telugu_tech.db import fingerprint, jaccard
from telugu_tech.transliterate import has_telugu, to_roman


# ---------------------------------------------------------------- errors
def test_redaction_removes_secrets():
    s = ("Authorization: Bearer abc.def access_token=ya29.SECRET refresh_token: 1//0gABCDEFGHIJKLMNOPQRSTUV "
         "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 api_key=sk-1234567890abcdefXYZ")
    out = errors.redact(s)
    for leaked in ("abc.def", "ya29.SECRET", "1//0gABCDEFGHIJKLMNOPQRSTUV", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
                   "sk-1234567890abcdefXYZ"):
        assert leaked not in out


@pytest.mark.parametrize("msg,cat", [
    ("HTTP 429 Too Many Requests", errors.Category.RATE_LIMIT),
    ("quotaExceeded", errors.Category.QUOTA),
    ("401 Unauthorized", errors.Category.AUTH),
    ("Connection reset by peer", errors.Category.NETWORK),
    ("402 payment required", errors.Category.BILLING),
])
def test_classification(msg, cat):
    assert errors.classify(Exception(msg)) is cat


def test_retry_is_bounded_to_three_with_backoff():
    calls, sleeps = [], []

    def boom():
        calls.append(1)
        raise errors.AgentError("temporary network failure", errors.Category.NETWORK)

    with pytest.raises(errors.AgentError):
        errors.retry_call(boom, max_attempts=10, sleep=sleeps.append)  # 10 is clamped to 3
    assert len(calls) == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]


def test_blockers_are_never_retried():
    calls = []

    def blocked():
        calls.append(1)
        raise errors.BlockerError("token revoked", errors.Category.AUTH)

    with pytest.raises(errors.BlockerError):
        errors.retry_call(blocked, sleep=lambda _: None)
    assert len(calls) == 1


def test_retry_recovers_from_transient(tmp_path):
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 2:
            raise errors.AgentError("503", errors.Category.NETWORK)
        return "ok"

    assert errors.retry_call(flaky, sleep=lambda _: None) == "ok"
    log = errors.ErrorLog(tmp_path / "e.jsonl")
    log.record(stage="x", exc=Exception("password=hunter2"), repaired=True, repair_action="retried")
    assert "hunter2" not in log.path.read_text()


# ---------------------------------------------------------------- db / dedupe
def test_topic_dedupe(db):
    assert db.add_topic("GitHub అంటే ఏంటి? Developers GitHub ఎందుకు", status="used") is not None
    assert db.add_topic("GitHub అంటే ఏంటి? Developers GitHub ఎందుకు", status="used") is None  # same fingerprint
    assert db.find_similar_topic("Developers GitHub ఎందుకు? GitHub అంటే ఏంటి") is not None
    assert db.find_similar_topic("How quantum chips work") is None
    assert fingerprint("The new GitHub") == fingerprint("github")
    assert jaccard("git branch merge", "merge branch git") == 1.0


def test_checkpoints_and_upload_records(db):
    db.create_job("j1", "short", "t")
    db.mark_stage("j1", "voice", {"rate_adjust": 4})
    assert db.checkpoint("j1")["voice"]["rate_adjust"] == 4
    db.record_upload("abc", "j1", "vid1", "private", "uploaded")
    assert db.upload_for_hash("abc")["youtube_id"] == "vid1"
    assert db.upload_for_hash("zzz") is None


# ---------------------------------------------------------------- storyboard
def test_demo_storyboard_is_valid(cfg, demo_sb):
    assert storyboard.validate(demo_sb, cfg) == []


def test_storyboard_catches_structure_and_fact_problems(cfg, demo_sb):
    sb = copy.deepcopy(demo_sb)
    sb["scenes"] = [s for s in sb["scenes"] if s["section"] != "turning_point"]
    sb["scenes"][0]["caption_roman"] = "GitHub అంటే"
    sb["facts"].append({"claim": "made up", "source_ids": ["s99"]})
    sb["seo"]["titles"][0] = "SHOCKING GitHub secret"
    problems = " | ".join(storyboard.validate(sb, cfg))
    assert "missing sections" in problems
    assert "Roman script only" in problems
    assert "unknown/missing source ids" in problems
    assert "clickbait" in problems


def test_storyboard_rejects_english_only_narration(cfg, demo_sb):
    sb = copy.deepcopy(demo_sb)
    sb["scenes"][1]["narration_te"] = "GitHub is a home for code where every version is safe."
    assert any("mainly Telugu" in p for p in storyboard.validate(sb, cfg))


def test_extract_json_from_fenced_llm_output():
    assert storyboard.extract_json('Sure!\n```json\n{"a": 1}\n```')["a"] == 1
    with pytest.raises(errors.AgentError):
        storyboard.extract_json("no json here")


def test_storyboard_markdown_has_timestamps(demo_sb):
    t = [{"start": i * 6.0, "end": i * 6.0 + 6} for i in range(len(demo_sb["scenes"]))]
    md = storyboard.storyboard_markdown(demo_sb, t)
    assert "00:06.00" in md and "Sources" in md


# ---------------------------------------------------------------- transliteration
def test_transliteration_casual():
    assert to_roman("తెలుగు") == "thelugu"
    assert to_roman("కథ") == "katha"
    assert to_roman("GitHub అంటే") == "GitHub ante"
    assert not has_telugu(to_roman("ప్రపంచం మొత్తం"))


# ---------------------------------------------------------------- scheduler
def test_next_run_in_ist(cfg):
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 11, 24, 6, 59, tzinfo=ist)
    assert scheduler.next_run("0 7 * * *", now) == datetime(2026, 11, 24, 7, 0, tzinfo=ist)
    assert scheduler.next_run("0 22 * * *", now).hour == 22
    assert scheduler.next_run("0 10 * * 0", now).weekday() == 6  # Sunday


def test_scheduler_disabled_by_default(cfg):
    ist = ZoneInfo("Asia/Kolkata")
    assert scheduler.due_jobs(cfg, {}, datetime(2026, 11, 24, 7, 3, tzinfo=ist)) == []
    with pytest.raises(errors.BlockerError):
        scheduler.install(cfg, "/x/telugu-tech", approve=True)  # enabled=false


def test_due_jobs_when_enabled(cfg):
    cfg.raw["scheduler"]["enabled"] = True
    ist = ZoneInfo("Asia/Kolkata")
    due = scheduler.due_jobs(cfg, {}, datetime(2026, 11, 24, 7, 3, tzinfo=ist))
    assert [d["name"] for d in due] == ["morning_news_short"]
    state = {"morning_news_short": due[0]["scheduled_for"]}
    assert scheduler.due_jobs(cfg, state, datetime(2026, 11, 24, 7, 8, tzinfo=ist)) == []
    assert scheduler.due_jobs(cfg, {}, datetime(2026, 11, 24, 9, 0, tzinfo=ist)) == []  # past grace window
    assert "*/5 * * * *" in scheduler.crontab_block(cfg, "/x/telugu-tech")


# ---------------------------------------------------------------- subtitles / seo
def test_srt_timestamps_and_cues(demo_sb, tmp_path):
    assert subtitles.ts(3723.456) == "01:02:03,456"
    t, timings = 0.0, []
    for _ in demo_sb["scenes"]:
        timings.append({"start": t, "speech_start": t + 0.1, "speech_end": t + 5.5, "end": t + 6})
        t += 6
    cues = subtitles.telugu_cues(demo_sb, timings)
    assert all(a < b for a, b, _ in cues)
    p = subtitles.write_srt(cues, tmp_path / "x.srt")
    assert subtitles.parse_srt(p)[0][2] == cues[0][2]
    roman = subtitles.roman_cues(demo_sb, timings)
    assert not any(has_telugu(c[2]) for c in roman)


def test_seo_package(cfg, demo_sb):
    timings = [{"start": i * 40.0, "end": i * 40.0 + 40} for i in range(len(demo_sb["scenes"]))]
    short = seo.build(demo_sb, timings, cfg, "short")
    assert len(short["titles"]) == 3 and "#Shorts" in short["hashtags"]
    assert "Sources" in short["description"] and demo_sb["sources"][0]["url"] in short["description"]
    assert short["contains_synthetic_media"] is True and short["made_for_kids"] is False
    assert short["warnings"] == []
    long = seo.build(demo_sb, timings, cfg, "long")
    assert long["chapters"][0][0] == "0:00" and len(long["chapters"]) >= 3


def test_caption_chunks_keep_every_word_in_order():
    from telugu_tech.visuals import caption_chunks
    scene = {"caption_roman": "Ante GitHub kevalam storage kaadu, prapancham kalisi panichese vedika."}  # 9 words → 4+5
    tm = {"start": 0.0, "speech_start": 0.0, "speech_end": 4.0, "end": 4.3}
    chunks = caption_chunks(scene, tm)
    assert [w for c in chunks for w in c["words"]] == scene["caption_roman"].split()
    assert all(chunks[i]["end"] <= chunks[i + 1]["start"] + 1e-9 for i in range(len(chunks) - 1))
    assert chunks[-1]["end"] <= tm["end"]
