"""Render one real frame per editing style (signature visual + caption template) into a contact sheet.

Usage:  .venv/bin/python scripts/style_gallery.py [--out data/reports/style_gallery.jpg] [--lite]
Each style is rendered through the same Remotion composition and props builder the pipeline uses,
so this is a quick visual regression check for all 12 styles (~15–30 s per style on 4 cores).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from telugu_tech import premium, styles  # noqa: E402
from telugu_tech.config import load_config  # noqa: E402

SIGNATURE = {
    "cinematic_documentary": {"type": "timeline", "events": [{"year": "1989", "label": "Idea"}, {"year": "1991", "label": "Launch"},
                                                              {"year": "1993", "label": "Open to all"}]},
    "product_3d": {"type": "phone3d", "mode": "hero", "label": "Inside your phone", "screen": {"title": "Hello!", "lines": ["Chip", "Battery"]}},
    "retro_pixel": {"type": "pixel_scene", "scene": "crt", "text": "HELLO WORLD"},
    "kinetic_typography": {"type": "headline", "text": "Small ideas, big impact", "keywords": ["ideas"]},
    "holo_hud": {"type": "globe", "label": "Network shield"},
    "product_launch": {"type": "phone3d", "mode": "screen", "label": "Launch day", "screen": {"title": "New!", "lines": ["Faster", "Smarter"]}},
    "ai_news": {"type": "neural_net", "inputLabel": "Data", "outputLabel": "Answer"},
    "code_explainer": {"type": "code", "filename": "app.py", "lines": ["def greet(name):"], "suggestion": ["    return f'Namaste {name}'"]},
    "parallax_25d": {"type": "icon_grid", "items": [{"icon": "cloud", "label": "Cloud"}, {"icon": "ai", "label": "AI"},
                                                     {"icon": "phone", "label": "Apps"}, {"icon": "lock", "label": "Security"}]},
    "isometric": {"type": "iso_stack", "layers": ["Users", "App", "API", "Database"]},
    "glassmorphism": {"type": "chat_ui", "title": "Assistant", "messages": [{"from": "user", "text": "Explain AI?"},
                                                                            {"from": "ai", "text": "Patterns from data!"}]},
    "infographic": {"type": "chart", "chart": "bar", "title": "Sample chart", "unit": "%",
                    "data": [{"label": "A", "value": 40}, {"label": "B", "value": 75, "highlight": True}, {"label": "C", "value": 55}]},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/reports/style_gallery.jpg")
    ap.add_argument("--lite", action="store_true", help="render the no-WebGL lite profile")
    args = ap.parse_args()
    cfg = load_config()
    rdir = premium.remotion_dir(cfg)
    work = rdir / "out" / "gallery"
    work.mkdir(parents=True, exist_ok=True)
    browser = premium.find_browser(cfg)
    tiles = []
    for name in styles.STYLES:
        st = premium.load_style(cfg, None, name)
        sb = {"topic": f"gallery {name}", "scenes": [
            {"id": 1, "section": "hook", "narration_te": "", "caption_roman": "", "visual": {"type": "headline", "text": st["label"]},
             "transition": "fade"},
            {"id": 2, "section": "explanation", "narration_te": "", "caption_roman": "", "visual": SIGNATURE[name], "transition": "fade"}]}
        timings = [{"start": 0, "speech_start": 0, "speech_end": 1.8, "end": 2.0}, {"start": 2.0, "speech_start": 2.0, "speech_end": 5.8, "end": 6.0}]
        words = [{"text": t, "start": 3.0 + i * 0.25, "end": 3.2 + i * 0.25, "scene": 1, "keyword": i == 1, "pageEnd": i == 2}
                 for i, t in enumerate(["Telugu", "Tech", "Kathalu"])]
        props = premium.build_props(cfg, sb, timings, words, 6.0, st, "short")
        props["profile"] = "lite" if args.lite else "full"
        pf = work / f"{name}.json"
        pf.write_text(json.dumps(props))
        png = work / f"{name}.png"
        cmd = ["npx", "remotion", "still", "src/index.ts", "TeluguTechShort", str(png), "--frame=110", f"--props={pf}",
               "--gl=swangle", "--log=error"] + ([f"--browser-executable={browser}"] if browser else [])
        r = subprocess.run(cmd, cwd=rdir, capture_output=True, text=True, timeout=600)
        ok = r.returncode == 0 and png.is_file()
        print(f"{'✔' if ok else '✖'} {name}" + ("" if ok else f": {(r.stderr or r.stdout)[-200:]}"), flush=True)
        tiles.append((name, png if ok else None))
    tw, th = 270, 480
    sheet = Image.new("RGB", (tw * 6, (th + 34) * 2), (10, 10, 20))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(rdir / "public" / "fonts" / "NotoSansDisplay-Bold.ttf"), 20)
    for i, (name, png) in enumerate(tiles):
        x, y = (i % 6) * tw, (i // 6) * (th + 34)
        if png:
            sheet.paste(Image.open(png).convert("RGB").resize((tw, th)), (x, y + 34))
        d.text((x + 8, y + 6), name, fill=(250, 204, 21) if png else (244, 63, 94), font=font)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=90)
    print(f"gallery: {out}")
    return 0 if all(p for _, p in tiles) else 1


if __name__ == "__main__":
    raise SystemExit(main())
