"""Original thumbnail (1280x720) and Shorts cover frame (1080x1920), drawn from code."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .visuals import Background, Theme, draw_icon, draw_text, fit, rgba, text_width


def _card(th: Theme, headline: str, subline: str, icon: str, telugu_line: str = "") -> Image.Image:
    W, H, u = th.W, th.H, th.u
    img = Background(th, seed=11).frame(4.0, zoom=1.02)
    d = ImageDraw.Draw(img, "RGBA")
    portrait = th.portrait
    # big glowing icon
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    icx, icy = (W * 0.5, H * 0.33) if portrait else (W * 0.76, H * 0.5)
    isz = (520 if portrait else 430) * u
    gd.ellipse([icx - isz * 0.62, icy - isz * 0.62, icx + isz * 0.62, icy + isz * 0.62], fill=rgba(th.primary, 0.75))
    glow = glow.filter(ImageFilter.GaussianBlur(40 * u))
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img, "RGBA")
    draw_icon(d, th, icon, icx, icy, isz * 0.8, th.highlight)
    # headline block
    if portrait:
        x0, x1, ytop = W * 0.08, W * 0.92, H * 0.56
    else:
        x0, x1, ytop = W * 0.05, W * 0.58, H * 0.16
    max_w = x1 - x0
    size, lines = fit(th, headline.upper(), max_w, int((150 if portrait else 128) * u), int(60 * u), 3)
    y = ytop
    anchor_x = (x0 + x1) / 2 if portrait else x0
    anchor = "mm" if portrait else "lm"
    for line in lines:
        draw_text(d, th, (anchor_x, y + size / 2), line, size, rgba(th.text, 1), anchor, stroke=int(8 * u),
                  stroke_fill=(0, 0, 0, 255))
        y += size * 1.08
    if subline:
        ss, sl = fit(th, subline, max_w, int((72 if portrait else 60) * u), int(34 * u), 2)
        y += 12 * u
        for line in sl:
            w = text_width(th, line, ss) + 40 * u
            bx = anchor_x - w / 2 if portrait else x0
            d.rounded_rectangle([bx, y, bx + w, y + ss * 1.35], radius=int(18 * u), fill=rgba(th.highlight, 1))
            draw_text(d, th, (bx + w / 2, y + ss * 0.68), line, ss, (15, 15, 25, 255), "mm")
            y += ss * 1.5
    if telugu_line:
        ts_, tl = fit(th, telugu_line, max_w, int((64 if portrait else 52) * u), int(30 * u), 2)
        y += 10 * u
        for line in tl:
            draw_text(d, th, (anchor_x, y + ts_ / 2), line, ts_, rgba(th.accent, 1), anchor, stroke=int(4 * u),
                      stroke_fill=(0, 0, 0, 255))
            y += ts_ * 1.3
    if th.channel:
        draw_text(d, th, (W - 30 * u, H - 40 * u), th.channel, int(34 * u), rgba(th.text, 0.9), "rm",
                  stroke=int(3 * u), stroke_fill=(0, 0, 0, 200))
    return img


def make_thumbnail(th_long: Theme, sb: dict, out: Path) -> Path:
    t = (sb.get("seo") or {}).get("thumbnail") or {}
    th = replace(th_long, W=1280, H=720)
    img = _card(th, t.get("headline", sb.get("topic", "")), t.get("subline", ""), t.get("icon", "star"),
                sb.get("title_te", ""))
    img.save(out, "JPEG", quality=92, optimize=True)  # YouTube limit: 2 MB
    return out


def make_cover(th_short: Theme, sb: dict, out: Path) -> Path:
    t = (sb.get("seo") or {}).get("thumbnail") or {}
    th = replace(th_short, W=1080, H=1920)
    img = _card(th, t.get("headline", sb.get("topic", "")), t.get("subline", ""), t.get("icon", "star"),
                sb.get("title_te", ""))
    img.save(out, "PNG", optimize=True)
    return out
