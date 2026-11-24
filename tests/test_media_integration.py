"""Integration tests: real FFmpeg encoding, rendering and validation on tiny inputs."""
import subprocess

import pytest

from telugu_tech import audio, quality, visuals
from telugu_tech.visuals import theme_from_cfg

from .conftest import need_ffmpeg

pytestmark = pytest.mark.integration


def test_music_and_mix_hit_loudness_target(cfg, tmp_path):
    need_ffmpeg()
    voice = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-af",
                    "volume=0.5", "-ar", "48000", str(voice)], check=True)
    m = audio.synth_music(6, tmp_path / "music.wav", seed=1)
    assert "Original" in m["license"]
    audio.build_sfx_track([(1.0, "whoosh"), (2.0, "pop"), (3.0, "ding")], 6, tmp_path / "sfx.wav")
    res = audio.mix(voice, tmp_path / "music.wav", tmp_path / "sfx.wav", tmp_path / "out.wav")
    assert -15.0 <= res["integrated_lufs"] <= -13.0
    assert res["true_peak_db"] <= -1.0


def test_render_and_validate_small_video(cfg, demo_sb, tmp_path):
    need_ffmpeg()
    cfg.raw["video"]["short"].update({"width": 270, "height": 480, "min_seconds": 2, "max_seconds": 10})
    sb = dict(demo_sb, scenes=demo_sb["scenes"][:2])
    timings = [{"start": 0.0, "speech_start": 0.1, "speech_end": 1.4, "end": 1.5},
               {"start": 1.5, "speech_start": 1.6, "speech_end": 2.9, "end": 3.0}]
    th = theme_from_cfg(cfg, "short")
    mat = visuals.render_video(th, sb, timings, 3.0, tmp_path / "m.mp4", workers=2, preset="ultrafast", log=lambda *_: None)
    a = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-af", "volume=0.2",
                    "-ar", "48000", "-ac", "2", str(a)], check=True)
    out = tmp_path / "final.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(mat), "-i", str(a), "-c:v", "copy", "-c:a", "aac", "-shortest",
                    str(out)], check=True)
    qa = quality.validate_video(out, cfg, "short", sb=sb, timings=timings, theme=th)
    by = {c["check"]: c for c in qa["checks"]}
    assert by["resolution"]["passed"] and by["frame rate 30 fps"]["passed"]
    assert by["full decode (playback) without errors"]["passed"]
    assert by["visual timeline matches audio"]["passed"]
    assert by["captions inside safe margins (≤2 lines)"]["passed"]
    assert by["Telugu font covers all glyphs"]["passed"]
    assert not by["loudness -16..-12 LUFS"]["passed"]  # quiet test tone is correctly flagged


def test_mixed_script_runs_use_correct_fonts(cfg):
    th = theme_from_cfg(cfg, "short")
    kinds = [k for _, k in visuals.runs("GitHub అంటే → code", th.latin)]
    assert kinds == ["latin", "te", "latin", "sym", "latin"]
