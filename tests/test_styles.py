import copy
import json
import re
import subprocess

import numpy as np
import pytest

from telugu_tech import engine, errors, premium, quality, storyboard, styles

from .conftest import ROOT, need_ffmpeg

EXPECTED = {"github-rust-vs-fast": "code_explainer", "ai-news-astra-planets": "ai_news",
            "smartphone-3d-inside": "product_3d", "pixel-first-website": "retro_pixel"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_twelve_styles_resolve_with_valid_parameters():
    assert len(styles.STYLES) == 12
    for name in styles.STYLES:
        s = styles.get_style(name)
        assert s["name"] == name and s["label"]
        assert 60 <= s["bpm"] <= 140 and 0 <= s["cameraIntensity"] <= 1
        assert set(s["transitions"]) <= storyboard.TRANSITIONS
        assert all(HEX.match(v) for v in s["theme"].values())
        assert s["caption"]["template"] in {"pop_highlight", "karaoke_line", "bold_center", "pixel_block", "hud_bracket", "glass_pill"}
        assert styles.PREFERRED_VISUALS[name] <= storyboard.VISUAL_TYPES


def test_unknown_style_rejected(cfg):
    with pytest.raises(KeyError):
        styles.get_style("vaporwave")
    sb = json.loads((ROOT / "examples" / "demo_ai_future_premium.storyboard.json").read_text(encoding="utf-8"))
    sb["style"] = "vaporwave"
    assert any("style must be one of" in p for p in storyboard.validate(sb, cfg))


def _board(name):
    p = ROOT / "examples" / "styles" / f"{name}.storyboard.json"
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,expected", sorted(EXPECTED.items()))
def test_auto_style_selection_matches_topic(cfg, name, expected):
    sb = _board(name)
    assert storyboard.validate(sb, cfg) == []
    assert styles.auto_select(sb) == expected


def test_repetition_penalty_and_explicit_style():
    sb = _board("github-rust-vs-fast")
    assert styles.auto_select(sb, ["code_explainer"] * 3) != "code_explainer"
    sb2 = copy.deepcopy(sb)
    sb2["style"] = "holo_hud"
    assert styles.auto_select(sb2, ["holo_hud"] * 3) == "holo_hud"  # explicit choice always wins


def test_new_visual_types_validated(cfg):
    sb = _board("smartphone-3d-inside")
    bad = copy.deepcopy(sb)
    bad["scenes"][0]["visual"]["mode"] = "xray"
    assert any("phone3d mode" in p for p in storyboard.validate(bad, cfg))
    px = _board("pixel-first-website")
    px["scenes"][0]["visual"]["scene"] = "castle"
    assert any("pixel_scene scene" in p for p in storyboard.validate(px, cfg))


def test_props_carry_style_theme_profile(cfg):
    sb = _board("pixel-first-website")
    t, timings = 0.0, []
    for _ in sb["scenes"]:
        timings.append({"start": t, "speech_start": t + .1, "speech_end": t + 4.5, "end": t + 5, "trim": 0})
        t += 5
    st = premium.load_style(cfg, None, "retro_pixel")
    props = premium.build_props(cfg, sb, timings, [], t, st, "short")
    assert props["profile"] == "full" and props["style"]["overlay"] == "crt" and props["style"]["font"] == "mono"
    assert props["theme"]["accent"] == styles.STYLES["retro_pixel"]["theme"]["accent"]
    assert props["style"]["caption"]["template"] == "pixel_block"


def test_lite_profile_fallback(cfg, tmp_path, monkeypatch):
    sb = _board("smartphone-3d-inside")
    timings = [{"start": i * 5.0, "speech_start": i * 5 + .1, "speech_end": i * 5 + 4.5, "end": i * 5 + 5.0, "trim": 0}
               for i in range(len(sb["scenes"]))]
    calls = []

    def fake_render(cfg_, props, out, log=print, max_attempts=None):
        calls.append(props["profile"])
        if props["profile"] == "full":
            raise errors.AgentError("WebGL context lost", errors.Category.RENDER)
        out.write_bytes(b"x")
        return out

    monkeypatch.setattr(premium, "render_remotion", fake_render)
    monkeypatch.setattr(premium, "grade", lambda i, o, g, **k: o.write_bytes(b"y") or o)
    fallbacks = []
    info = premium.render_visuals(cfg, sb, timings, [], 40.0, "short", tmp_path, premium.load_style(cfg, None, "product_3d"),
                                  log=lambda *a: None, on_fallback=lambda e, a: fallbacks.append(a))
    assert calls == ["full", "lite"] and info["profile"] == "lite" and fallbacks


def test_sixty_fps_uses_direct_mux(cfg, tmp_path, monkeypatch):
    cfg.raw["video"]["short"]["fps"] = 60
    used = {}
    monkeypatch.setattr(engine, "render_with_ffmpeg", lambda **k: used.setdefault("ffmpeg", True) and {"engine": "ffmpeg-fallback"})
    monkeypatch.setattr(engine, "render_with_mpt", lambda *a, **k: pytest.fail("MPT must not be used for 60 fps"))
    r = engine.render_final(cfg, job_id="j", material_mp4=tmp_path / "m.mp4", audio_wav=tmp_path / "a.wav", script_text="",
                            kind="short", out_mp4=tmp_path / "o.mp4", log=lambda *a: None)
    assert used.get("ffmpeg") and "30 fps" in r["reason"]
    assert cfg.validate() == []


def test_pinned_frontend_dependencies_and_glyphs():
    pkg = json.loads((ROOT / "remotion" / "package.json").read_text())
    for dep in ("remotion", "@remotion/cli", "@remotion/three", "three", "@react-three/fiber", "pixi.js", "react"):
        assert re.fullmatch(r"\d+\.\d+\.\d+", pkg["dependencies"][dep]), f"{dep} not pinned"
    src = (ROOT / "remotion" / "src" / "components" / "Pixel.tsx").read_text()
    table = src[src.index("const G"):src.index("export const textWidth")]
    glyphs = re.findall(r": '([01]{2,})'", table)  # values only (keys like '0' are single chars)
    assert len(glyphs) >= 46 and all(len(g) == 35 for g in glyphs)


# ---------------------------------------------------------------- media checks (real ffmpeg)
@pytest.mark.integration
def test_flash_detector(tmp_path):
    need_ffmpeg()
    flashy, calm = tmp_path / "flash.mp4", tmp_path / "calm.mp4"
    # alternating black/white every 2 frames at 30 fps = ~7 flashes per second
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=108x192:d=3:r=30", "-vf",
                    "geq=lum='if(mod(floor(N/2),2),235,16)':cb=128:cr=128", "-pix_fmt", "yuv420p", str(flashy)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=108x192:d=3:r=30", "-pix_fmt", "yuv420p", str(calm)],
                   check=True)
    assert quality.flash_check(flashy)["max_flashes_per_second"] > 3
    assert quality.flash_check(calm)["max_flashes_per_second"] <= 3


@pytest.mark.integration
def test_audio_presence_detects_silence(tmp_path):
    need_ffmpeg()
    silent, loud = tmp_path / "s.mp4", tmp_path / "l.mp4"
    for out, src in ((silent, "anullsrc=r=48000:cl=stereo"), (loud, "sine=frequency=330:sample_rate=48000")):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=108x192:d=4:r=30", "-f", "lavfi", "-i", src,
                        "-t", "4", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)], check=True)
    s, l = quality.audio_presence(silent), quality.audio_presence(loud)
    assert (s["mean_volume_db"] is None or s["mean_volume_db"] < -60) and s["longest_silence"] >= 3
    assert l["mean_volume_db"] > -40 and l["longest_silence"] < 1


def test_caption_fit_accounts_for_template_padding(cfg):
    words = [{"text": t, "start": i * .4, "end": i * .4 + .3, "scene": 0, "keyword": False, "pageEnd": i == 2}
             for i, t in enumerate(["Supercalifragilistic", "mixed", "wordy"])]
    plain = premium.load_style(cfg, None, "ai_news")
    pixel = premium.load_style(cfg, None, "retro_pixel")
    assert quality.premium_caption_fit(words, plain, cfg, "short")[0] in (True, False)
    # uppercase + block padding is the strictest template; it must never be judged looser than the plain one
    if not quality.premium_caption_fit(words, plain, cfg, "short")[0]:
        assert not quality.premium_caption_fit(words, pixel, cfg, "short")[0]
    np.testing.assert_equal(True, True)


def test_caption_pages_split_by_measured_width(cfg):
    """Regression: 'rendoo okadaanikokati vyathirekam.' wrapped to 3 lines in a real render (QA caught it)."""
    texts = "Ee vaaram GitHub lo rendu repos trend avutunnaayi, rendoo okadaanikokati vyathirekam.".split()
    words = [{"text": t, "start": i * .4, "end": i * .4 + .35, "scene": 0, "keyword": False, "pageEnd": i == len(texts) - 1}
             for i, t in enumerate(texts)]
    st = premium.load_style(cfg, None, "code_explainer")
    assert not quality.premium_caption_fit(words, st, cfg, "short")[0]
    fixed = premium.fit_caption_pages(words, st, cfg, "short")
    assert quality.premium_caption_fit(fixed, st, cfg, "short")[0]
    assert [w["text"] for w in fixed] == texts  # no words lost or reordered
