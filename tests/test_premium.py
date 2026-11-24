import copy
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from telugu_tech import audio, premium, quality, reference, storyboard

from .conftest import ROOT, need_ffmpeg

PREMIUM_DEMO = ROOT / "examples" / "demo_ai_future_premium.storyboard.json"


@pytest.fixture
def prem_sb():
    return json.loads(PREMIUM_DEMO.read_text(encoding="utf-8"))


def test_premium_demo_storyboard_valid(cfg, prem_sb):
    assert storyboard.validate(prem_sb, cfg) == []
    for sc in prem_sb["scenes"]:  # word-aligned captions → exact word sync
        assert len(sc["narration_te"].split()) == len(sc["caption_roman"].split())


def test_storyboard_rejects_unknown_camera(cfg, prem_sb):
    sb = copy.deepcopy(prem_sb)
    sb["scenes"][0]["camera"] = "crane_shot"
    assert any("camera must be" in p for p in storyboard.validate(sb, cfg))


def test_word_timeline_one_to_one_uses_tts_boundaries():
    sb = {"scenes": [{"narration_te": "AI అంటే data", "caption_roman": "AI ante data", "section": "hook"}]}
    sa = [{"boundaries": [{"offset": 0.30, "duration": 0.3, "text": "AI"}, {"offset": 0.70, "duration": 0.3, "text": "అంటే"},
                          {"offset": 1.10, "duration": 0.4, "text": "data"}]}]
    tm = [{"start": 0.0, "speech_start": 1.0, "speech_end": 2.4, "end": 2.6, "trim": 0.25}]
    w = premium.word_timeline(sb, sa, tm)
    assert [x["text"] for x in w] == ["AI", "ante", "data"]
    assert w[0]["start"] == pytest.approx(1.05)  # speech_start - trim + offset
    assert w[0]["keyword"] and not w[1]["keyword"] and w[2]["keyword"]
    assert w[-1]["pageEnd"]


def test_word_timeline_proportional_when_counts_differ():
    sb = {"scenes": [{"narration_te": "ఒకటి రెండు", "caption_roman": "okati rendu moodu naalugu", "section": "hook"}]}
    sa = [{"boundaries": [{"offset": 0.0, "duration": 0.5, "text": "ఒకటి"}, {"offset": 0.6, "duration": 0.5, "text": "రెండు"}]}]
    tm = [{"start": 0.0, "speech_start": 0.0, "speech_end": 1.1, "end": 1.4, "trim": 0.0}]
    w = premium.word_timeline(sb, sa, tm)
    assert len(w) == 4
    assert all(w[i]["start"] <= w[i + 1]["start"] for i in range(3))
    assert w[-1]["end"] <= 1.1 + 1e-6


def test_keywords_are_selective_and_prioritised(prem_sb):
    kws = [premium.scene_keywords(sc) for sc in prem_sb["scenes"]]
    assert all(len(k) <= 3 for k in kws)
    assert {"80%", "copilot", "github"} == kws[6]
    assert "comment" not in kws[8] and "build" not in kws[8]


def test_props_and_sfx(cfg, prem_sb):
    timings, t = [], 0.0
    for _ in prem_sb["scenes"]:
        timings.append({"start": t, "speech_start": t + 0.1, "speech_end": t + 5.5, "end": t + 6.0, "trim": 0.0})
        t += 6.0
    style = premium.load_style(cfg)
    props = premium.build_props(cfg, prem_sb, timings, [], t, style, "short")
    assert props["durationInFrames"] == 54 * 30 and props["width"] == 1080 and props["height"] == 1920
    assert props["beats"][1] == pytest.approx(0.6)
    assert props["scenes"][3]["visual"]["type"] == "molecule"
    ev = premium.sfx_events(prem_sb, timings)
    kinds = {k for _, k in ev}
    assert {"whoosh", "impact", "riser", "typing", "glitch"} <= kinds


def test_grade_filter_contains_cinematic_stages():
    f = premium.grade_filter(premium.HOUSE_STYLE["grade"])
    for part in ("gblur", "blend=all_mode=screen", "colorbalance", "eq=contrast", "vignette", "noise", "format=yuv420p"):
        assert part in f


def test_style_profile_override(cfg, tmp_path):
    p = tmp_path / "ref.json"
    p.write_text(json.dumps({"source": "reference:x.mp4", "style": {"bpm": 120, "caption": {"position": 0.66},
                                                                     "grade": {"saturation": 1.2}}}))
    s = premium.load_style(cfg, p)
    assert s["bpm"] == 120 and s["caption"]["position"] == 0.66 and s["caption"]["maxWords"] == 3
    assert s["grade"]["saturation"] == 1.2 and s["grade"]["bloom"] == premium.HOUSE_STYLE["grade"]["bloom"]
    assert s["source"] == "reference:x.mp4"


def test_caption_fit_check(cfg):
    style = premium.load_style(cfg)
    ok_words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.3, "scene": 0, "keyword": False, "pageEnd": i == 2}
                for i, t in enumerate(["Simple", "ga", "cheppalante"])]
    assert quality.premium_caption_fit(ok_words, style, cfg, "short")[0]
    bad = [{"text": "Supercalifragilisticexpialidociouslylonger", "start": 0, "end": 1, "scene": 0, "keyword": False, "pageEnd": True}]
    assert not quality.premium_caption_fit(bad, style, cfg, "short")[0]


def test_derive_style_from_measurements():
    a = {"pacing": {"avg_shot_seconds": 1.5, "cuts": 20, "avg_change_interval_seconds": 1.5},
         "motion": {"mean": 0.03}, "colour": {"saturation": 0.42, "contrast": 0.25, "brightness": 0.4, "warmth": 0.05},
         "caption_band": {"band_center": 0.72}, "audio": {"bpm_estimate": 124}}
    s = reference.derive_style(a)
    assert s["bpm"] == 124 and s["subCutSeconds"] == 1.5 and s["motionBlur"] is True
    assert s["caption"]["position"] == 0.72 and 0.95 <= s["grade"]["contrast"] <= 1.2


# ---------------------------------------------------------------- integration (real ffmpeg)
@pytest.mark.integration
def test_beat_aligned_narration(tmp_path):
    need_ffmpeg()
    clips = []
    for i, d in enumerate((1.13, 0.87, 1.5)):
        p = tmp_path / f"c{i}.wav"
        t = np.arange(int(d * audio.SR)) / audio.SR
        audio.write_wav(p, 0.3 * np.sin(2 * np.pi * 220 * t))
        clips.append({"path": str(p)})
    tm = audio.build_narration(clips, tmp_path / "n.wav", gap=0.15, beat=0.6)
    for x in tm[1:]:
        assert abs(x["start"] / 0.6 - round(x["start"] / 0.6)) < 0.01  # every cut on a beat
    assert all(x["speech_end"] <= x["end"] for x in tm)


@pytest.mark.integration
def test_reference_analyzer_detects_cuts_and_static(tmp_path):
    need_ffmpeg()
    v = tmp_path / "ref.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=270x480:d=2:r=30", "-f", "lavfi",
                    "-i", "color=c=blue:s=270x480:d=2:r=30", "-f", "lavfi", "-i", "testsrc2=s=270x480:d=2:r=30",
                    "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-pix_fmt", "yuv420p", str(v)], check=True)
    prof = reference.analyze(v, tmp_path / "styles", "synthetic")
    a = prof["analysis"]
    assert a["pacing"]["cuts"] == 2 and a["aspect"] == "9:16"
    assert Path(prof["files"]["profile"]).is_file() and "bpm" in prof["style"]
    st = quality.static_segments(v)
    assert st["longest_static_seconds"] >= 1.5  # solid colour segments are frozen


@pytest.mark.integration
def test_cinematic_sfx_library_renders(tmp_path):
    need_ffmpeg()
    events = [(0.2, k) for k in audio.SFX_LIBRARY]
    audio.build_sfx_track(events, 3.0, tmp_path / "sfx.wav")
    x = audio.decode(tmp_path / "sfx.wav")
    assert np.abs(x).max() > 0.05 and len(x) >= 3 * audio.SR
