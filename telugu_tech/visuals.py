"""Original motion-graphics engine (Pillow + FFmpeg).

Every visual is drawn from code: gradients, particles, icons, diagrams, kinetic typography and
captions. No stock footage, logos or third-party images are needed, so there are no licence risks.
Scenes are timed from the real narration audio, so visuals stay in sync with the voice-over.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .errors import AgentError, Category

TELUGU_RUN = re.compile(r"[ఀ-౿‌‍]+")
SECTION_TAGS = {"background": "THE STORY", "turning_point": "TURNING POINT", "explanation": "HOW IT WORKS",
                "example": "REAL EXAMPLE", "conclusion": "TAKEAWAY"}


# ------------------------------------------------------------------ easing / colour
def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return a if x < a else b if x > b else x


def ease_out(p: float) -> float:
    p = clamp(p)
    return 1 - (1 - p) ** 3


def ease_in_out(p: float) -> float:
    p = clamp(p)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_back(p: float) -> float:
    p = clamp(p)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgba(c: tuple[int, int, int], a: float) -> tuple[int, int, int, int]:
    return (c[0], c[1], c[2], int(255 * clamp(a)))


def lerp_c(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ------------------------------------------------------------------ fonts / text
@lru_cache(maxsize=256)
def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, max(8, int(size)), layout_engine=ImageFont.Layout.RAQM)
    except OSError as exc:
        raise AgentError(f"font not loadable: {path}", Category.FONT) from exc


@dataclass
class Theme:
    W: int
    H: int
    latin: str
    telugu: str
    telugu_regular: str
    primary: tuple
    accent: tuple
    highlight: tuple
    bg_top: tuple
    bg_bottom: tuple
    text: tuple
    channel: str
    margin_x: float
    safe_top: float
    safe_bottom: float

    @property
    def portrait(self) -> bool:
        return self.H > self.W

    @property
    def u(self) -> float:
        return min(self.W, self.H) / 1080.0

    @property
    def visual_box(self) -> tuple[int, int, int, int]:
        W, H = self.W, self.H
        if self.portrait:
            return int(W * 0.07), int(H * 0.17), int(W * 0.93), int(H * 0.58)
        return int(W * 0.08), int(H * 0.15), int(W * 0.92), int(H * 0.74)

    @property
    def caption_box(self) -> tuple[int, int, int, int]:
        """Region captions must stay inside (safe area)."""
        W, H = self.W, self.H
        x0, x1 = int(W * self.margin_x), int(W * (1 - self.margin_x))
        if self.portrait:
            x1 = int(W * (1 - max(self.margin_x, 0.13)))  # Shorts like/comment column
            return x0, int(H * 0.60), x1, int(H * (1 - self.safe_bottom))
        return x0, int(H * 0.76), x1, int(H * (1 - self.safe_bottom))


def theme_from_cfg(cfg, kind: str) -> Theme:
    v = cfg.get("video", kind)
    b = cfg.get("branding")
    c = cfg.get("captions")
    return Theme(W=v["width"], H=v["height"], latin=c["latin_font"], telugu=c["telugu_font"],
                 telugu_regular=c.get("telugu_font_regular", c["telugu_font"]),
                 primary=hex_rgb(b["primary"]), accent=hex_rgb(b["accent"]), highlight=hex_rgb(b["highlight"]),
                 bg_top=hex_rgb(b["bg_top"]), bg_bottom=hex_rgb(b["bg_bottom"]), text=hex_rgb(b["text"]),
                 channel=cfg.get("project", "channel_name", default=""), margin_x=c["safe_margin_x"],
                 safe_top=c["safe_top"], safe_bottom=c["safe_bottom_short"] if kind == "short" else c["safe_bottom_long"])


SYMBOL_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


@lru_cache(maxsize=4096)
def _latin_has(latin_path: str, ch: str) -> bool:
    f = font(latin_path, 40)
    return ch.isspace() or f.getmask(ch).getbbox() != f.getmask("\uFFFF").getbbox()


def runs(text: str, latin_path: str | None = None) -> list[tuple[str, str]]:
    """Split into (segment, script) runs, script in {"te", "latin", "sym"}, so every glyph
    comes from a font that actually contains it (raqm does no automatic fallback)."""
    out: list[tuple[str, str]] = []
    for ch in text:
        if TELUGU_RUN.match(ch):
            kind = "te"
        elif latin_path and not _latin_has(latin_path, ch) and Path(SYMBOL_FONT).is_file():
            kind = "sym"
        else:
            kind = "latin"
        if out and out[-1][1] == kind:
            out[-1] = (out[-1][0] + ch, kind)
        else:
            out.append((ch, kind))
    return out


def _font_for(th: "Theme", kind: str, size: int):
    return font(th.telugu if kind == "te" else SYMBOL_FONT if kind == "sym" else th.latin, size)


def text_width(th: Theme, text: str, size: int) -> float:
    return sum(_font_for(th, k, size).getlength(seg) for seg, k in runs(text, th.latin))


def draw_text(d: ImageDraw.ImageDraw, th: Theme, xy, text: str, size: int, fill, anchor: str = "lm",
              stroke: int = 0, stroke_fill=None) -> tuple[float, float]:
    """Draw mixed Telugu/Latin text. anchor: l/m/r + m(baseline-middle approximated)."""
    w = text_width(th, text, size)
    x, y = xy
    if anchor[0] == "m":
        x -= w / 2
    elif anchor[0] == "r":
        x -= w
    # vertical: place baseline so that text is centred around y (approx using latin metrics)
    asc, desc = font(th.latin, size).getmetrics()
    base = y + (asc - desc) / 2 if anchor[1] == "m" else y
    for seg, k in runs(text, th.latin):
        f = _font_for(th, k, size)
        d.text((x, base), seg, font=f, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=stroke_fill)
        x += f.getlength(seg)
    return w, size


def wrap(th: Theme, text: str, size: int, max_w: float) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if text_width(th, trial, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(th: Theme, text: str, max_w: float, size: int, min_size: int, max_lines: int = 2) -> tuple[int, list[str]]:
    while size > min_size:
        lines = wrap(th, text, size, max_w)
        if len(lines) <= max_lines and all(text_width(th, l, size) <= max_w for l in lines):
            return size, lines
        size = int(size * 0.92)
    return min_size, wrap(th, text, min_size, max_w)


# ------------------------------------------------------------------ icons (original vector drawings)
def draw_icon(d: ImageDraw.ImageDraw, th: Theme, name: str, cx: float, cy: float, s: float, col, alpha: float = 1.0):
    c = rgba(col, alpha)
    w = max(2, int(s * 0.07))
    h = s / 2
    if name == "code":
        draw_text(d, th, (cx, cy), "</>", int(s * 0.55), c, "mm")
    elif name == "cloud":
        for dx, dy, r in ((-0.22, 0.05, 0.22), (0.05, -0.08, 0.28), (0.28, 0.07, 0.2)):
            d.ellipse([cx + dx * s - r * s, cy + dy * s - r * s, cx + dx * s + r * s, cy + dy * s + r * s], fill=c)
        d.rounded_rectangle([cx - 0.42 * s, cy + 0.02 * s, cx + 0.46 * s, cy + 0.27 * s], radius=0.12 * s, fill=c)
    elif name == "users":
        for dx, sc in ((-0.2, 0.85), (0.2, 0.85), (0, 1.0)):
            r = 0.13 * s * sc
            x = cx + dx * s
            d.ellipse([x - r, cy - 0.22 * s - r, x + r, cy - 0.22 * s + r], fill=c)
            d.pieslice([x - 0.24 * s * sc, cy - 0.02 * s, x + 0.24 * s * sc, cy + 0.42 * s * sc], 180, 360, fill=c)
    elif name == "star":
        pts = []
        for k in range(10):
            r = h * (0.95 if k % 2 == 0 else 0.42)
            a = -math.pi / 2 + k * math.pi / 5
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(pts, fill=c)
    elif name in ("branch", "merge"):
        x0, x1 = cx - 0.18 * s, cx + 0.2 * s
        d.line([x0, cy - 0.38 * s, x0, cy + 0.38 * s], fill=c, width=w)
        if name == "branch":
            d.line([x0, cy + 0.05 * s, x1, cy - 0.2 * s], fill=c, width=w)
            pts = [(x0, cy - 0.38 * s), (x0, cy + 0.38 * s), (x1, cy - 0.25 * s)]
        else:
            d.line([x1, cy - 0.38 * s, x1, cy - 0.05 * s, x0, cy + 0.2 * s], fill=c, width=w, joint="curve")
            pts = [(x0, cy - 0.38 * s), (x0, cy + 0.38 * s), (x1, cy - 0.38 * s)]
        for px, py in pts:
            r = 0.1 * s
            d.ellipse([px - r, py - r, px + r, py + r], fill=c)
    elif name in ("ai", "chip"):
        q = 0.3 * s
        for k in range(-2, 3):
            o = k * 0.12 * s
            for (ax, ay, bx, by) in ((cx + o, cy - q, cx + o, cy - q - 0.12 * s), (cx + o, cy + q, cx + o, cy + q + 0.12 * s),
                                     (cx - q, cy + o, cx - q - 0.12 * s, cy + o), (cx + q, cy + o, cx + q + 0.12 * s, cy + o)):
                d.line([ax, ay, bx, by], fill=c, width=w)
        d.rounded_rectangle([cx - q, cy - q, cx + q, cy + q], radius=0.08 * s, fill=c)
        draw_text(d, th, (cx, cy), "AI" if name == "ai" else "CPU", int(s * (0.26 if name == "ai" else 0.18)),
                  rgba(th.bg_top, alpha), "mm")
    elif name == "globe":
        d.ellipse([cx - h * 0.9, cy - h * 0.9, cx + h * 0.9, cy + h * 0.9], outline=c, width=w)
        d.ellipse([cx - h * 0.4, cy - h * 0.9, cx + h * 0.4, cy + h * 0.9], outline=c, width=w)
        d.line([cx - h * 0.9, cy, cx + h * 0.9, cy], fill=c, width=w)
        d.line([cx, cy - h * 0.9, cx, cy + h * 0.9], fill=c, width=w)
    elif name == "lock":
        d.arc([cx - 0.22 * s, cy - 0.42 * s, cx + 0.22 * s, cy + 0.02 * s], 180, 360, fill=c, width=w * 2)
        d.line([cx - 0.22 * s, cy - 0.2 * s, cx - 0.22 * s, cy - 0.05 * s], fill=c, width=w * 2)
        d.line([cx + 0.22 * s, cy - 0.2 * s, cx + 0.22 * s, cy - 0.05 * s], fill=c, width=w * 2)
        d.rounded_rectangle([cx - 0.32 * s, cy - 0.06 * s, cx + 0.32 * s, cy + 0.4 * s], radius=0.06 * s, fill=c)
    elif name == "rocket":
        d.polygon([(cx, cy - 0.45 * s), (cx + 0.16 * s, cy - 0.1 * s), (cx + 0.16 * s, cy + 0.22 * s),
                   (cx - 0.16 * s, cy + 0.22 * s), (cx - 0.16 * s, cy - 0.1 * s)], fill=c)
        d.polygon([(cx - 0.16 * s, cy + 0.02 * s), (cx - 0.32 * s, cy + 0.3 * s), (cx - 0.16 * s, cy + 0.22 * s)], fill=c)
        d.polygon([(cx + 0.16 * s, cy + 0.02 * s), (cx + 0.32 * s, cy + 0.3 * s), (cx + 0.16 * s, cy + 0.22 * s)], fill=c)
        d.polygon([(cx - 0.09 * s, cy + 0.26 * s), (cx + 0.09 * s, cy + 0.26 * s), (cx, cy + 0.48 * s)],
                  fill=rgba(th.highlight, alpha))
    elif name == "book":
        d.polygon([(cx, cy - 0.28 * s), (cx - 0.42 * s, cy - 0.36 * s), (cx - 0.42 * s, cy + 0.3 * s), (cx, cy + 0.38 * s)], fill=c)
        d.polygon([(cx + 0.03 * s, cy - 0.28 * s), (cx + 0.42 * s, cy - 0.36 * s), (cx + 0.42 * s, cy + 0.3 * s),
                   (cx + 0.03 * s, cy + 0.38 * s)], fill=c)
    elif name == "bug":
        for k in (-1, 0, 1):
            d.line([cx - 0.4 * s, cy + k * 0.15 * s, cx + 0.4 * s, cy + k * 0.15 * s], fill=c, width=w)
        d.ellipse([cx - 0.22 * s, cy - 0.3 * s, cx + 0.22 * s, cy + 0.38 * s], fill=c)
        d.ellipse([cx - 0.13 * s, cy - 0.45 * s, cx + 0.13 * s, cy - 0.2 * s], fill=c)
    elif name == "laptop":
        d.rounded_rectangle([cx - 0.36 * s, cy - 0.32 * s, cx + 0.36 * s, cy + 0.14 * s], radius=0.04 * s, outline=c, width=w)
        d.polygon([(cx - 0.46 * s, cy + 0.22 * s), (cx + 0.46 * s, cy + 0.22 * s), (cx + 0.38 * s, cy + 0.14 * s),
                   (cx - 0.38 * s, cy + 0.14 * s)], fill=c)
    elif name == "phone":
        d.rounded_rectangle([cx - 0.2 * s, cy - 0.42 * s, cx + 0.2 * s, cy + 0.42 * s], radius=0.07 * s, outline=c, width=w)
        d.ellipse([cx - 0.04 * s, cy + 0.28 * s, cx + 0.04 * s, cy + 0.36 * s], fill=c)
    elif name == "server":
        for k in range(3):
            y = cy - 0.36 * s + k * 0.26 * s
            d.rounded_rectangle([cx - 0.38 * s, y, cx + 0.38 * s, y + 0.2 * s], radius=0.04 * s, outline=c, width=w)
            d.ellipse([cx + 0.22 * s, y + 0.07 * s, cx + 0.28 * s, y + 0.13 * s], fill=c)
    elif name == "money":
        d.ellipse([cx - h * 0.9, cy - h * 0.9, cx + h * 0.9, cy + h * 0.9], outline=c, width=w)
        draw_text(d, th, (cx, cy), "₹", int(s * 0.55), c, "mm")
    elif name == "india":
        for k, col2 in enumerate(((255, 153, 51), (255, 255, 255), (19, 136, 8))):
            y = cy - 0.3 * s + k * 0.2 * s
            d.rectangle([cx - 0.42 * s, y, cx + 0.42 * s, y + 0.2 * s], fill=rgba(col2, alpha))
        d.ellipse([cx - 0.08 * s, cy - 0.08 * s, cx + 0.08 * s, cy + 0.08 * s], outline=rgba((0, 0, 128), alpha), width=max(2, w // 2))
    elif name == "check":
        d.line([cx - 0.3 * s, cy, cx - 0.08 * s, cy + 0.24 * s, cx + 0.34 * s, cy - 0.26 * s], fill=c, width=w * 2, joint="curve")
    elif name == "heart":
        r = 0.2 * s
        d.ellipse([cx - 2 * r, cy - 1.5 * r, cx, cy + 0.5 * r], fill=c)
        d.ellipse([cx, cy - 1.5 * r, cx + 2 * r, cy + 0.5 * r], fill=c)
        d.polygon([(cx - 1.95 * r, cy - 0.3 * r), (cx + 1.95 * r, cy - 0.3 * r), (cx, cy + 2 * r)], fill=c)
    else:
        d.ellipse([cx - h * 0.5, cy - h * 0.5, cx + h * 0.5, cy + h * 0.5], fill=c)


# ------------------------------------------------------------------ background
class Background:
    def __init__(self, th: Theme, seed: int = 3):
        self.th = th
        W, H = th.W, th.H
        self.big = self._gradient(int(W * 1.12), int(H * 1.12))
        rng = np.random.default_rng(seed)
        self.particles = [(rng.random(), rng.random(), 0.5 + rng.random(), rng.random() * math.tau,
                           2 + rng.random() * 4) for _ in range(46)]

    def _gradient(self, w: int, h: int) -> Image.Image:
        th = self.th
        y = np.linspace(0, 1, h)[:, None]
        x = np.linspace(0, 1, w)[None, :]
        t = np.clip(0.75 * y + 0.25 * x, 0, 1)[..., None]
        top, bot = np.array(th.bg_top, np.float32), np.array(th.bg_bottom, np.float32)
        img = top * (1 - t) + bot * t
        # soft brand-coloured glow blobs
        for (gx, gy, rad, col, strength) in ((0.85, 0.15, 0.45, th.primary, 0.35), (0.1, 0.8, 0.5, th.accent, 0.18)):
            dist = np.sqrt(((x - gx) * (w / h)) ** 2 + (y - gy) ** 2)
            g = np.clip(1 - dist / rad, 0, 1) ** 2 * strength
            img = img * (1 - g[..., None]) + np.array(col, np.float32) * g[..., None]
        base = Image.fromarray(img.astype(np.uint8), "RGB")
        d = ImageDraw.Draw(base, "RGBA")
        step = int(90 * self.th.u)
        for gx in range(0, w, step):
            d.line([gx, 0, gx, h], fill=(255, 255, 255, 9), width=1)
        for gy in range(0, h, step):
            d.line([0, gy, w, gy], fill=(255, 255, 255, 9), width=1)
        return base

    def frame(self, t: float, zoom: float = 1.0) -> Image.Image:
        th = self.th
        W, H = th.W, th.H
        bw, bh = self.big.size
        # slow drift + zoom (dynamic camera)
        cw, ch = W / zoom, H / zoom
        ox = (bw - cw) / 2 + math.sin(t * 0.13) * (bw - cw) * 0.35
        oy = (bh - ch) / 2 + math.cos(t * 0.11) * (bh - ch) * 0.35
        img = self.big.resize((W, H), Image.BILINEAR, box=(ox, oy, ox + cw, oy + ch))
        d = ImageDraw.Draw(img, "RGBA")
        for (px, py, sp, ph, r) in self.particles:
            x = (px * W + math.sin(t * 0.4 * sp + ph) * 30 * th.u) % W
            y = (py * H - t * 18 * sp * th.u) % H
            a = 0.25 + 0.25 * math.sin(t * sp + ph)
            rr = r * th.u
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=rgba(th.accent, a))
        return img


# ------------------------------------------------------------------ scene renderers
def _panel(d, box, th: Theme, a: float, radius: float = 28):
    d.rounded_rectangle(box, radius=int(radius * th.u), fill=(255, 255, 255, int(16 * a)),
                        outline=rgba(th.accent, 0.35 * a), width=max(1, int(2 * th.u)))


def render_scene_layer(d: ImageDraw.ImageDraw, th: Theme, scene: dict, lt: float, dur: float):
    """Draw a scene's visual at local time lt (seconds since scene start)."""
    v = scene.get("visual") or {}
    typ = v.get("type", "title")
    if typ in ("headline", "neural_net", "chart", "chat_ui", "globe", "molecule"):  # premium-only types
        v = {"type": "title", "headline": v.get("text") or v.get("title") or v.get("label") or v.get("headline", ""),
             "subline": v.get("subline", ""), "icon": {"neural_net": "ai", "chart": "chart", "chat_ui": "ai",
                                                       "globe": "globe", "molecule": "dna"}.get(typ, v.get("icon", "spark"))}
        typ = "title"
    x0, y0, x1, y1 = th.visual_box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bw, bh = x1 - x0, y1 - y0
    u = th.u
    intro = ease_out(lt / 0.6)
    outro = 1 - ease_in_out((lt - (dur - 0.35)) / 0.35) if dur > 1 else 1.0
    A = intro * outro

    tag = SECTION_TAGS.get(scene.get("section"))
    if tag:
        tw = text_width(th, tag, int(30 * u)) + 44 * u
        ty = y0 - 34 * u
        d.rounded_rectangle([cx - tw / 2, ty - 26 * u, cx + tw / 2, ty + 26 * u], radius=int(26 * u),
                            fill=rgba(th.primary, 0.9 * A))
        draw_text(d, th, (cx, ty), tag, int(30 * u), rgba(th.text, A), "mm")

    if typ == "title":
        icon = v.get("icon")
        s = 210 * u * ease_back(lt / 0.7)
        if icon:
            draw_icon(d, th, icon, cx, y0 + bh * 0.28, max(1, s), th.accent, A)
        size, lines = fit(th, v.get("headline", ""), bw * 0.95, int(96 * u), int(48 * u))
        ly = y0 + bh * (0.58 if icon else 0.4)
        for i, line in enumerate(lines):
            p = ease_out((lt - 0.15 - 0.12 * i) / 0.5)
            draw_text(d, th, (cx, ly + i * size * 1.15 + (1 - p) * 40 * u), line, size, rgba(th.text, p * outro), "mm",
                      stroke=int(3 * u), stroke_fill=rgba(th.bg_top, p * outro))
        if v.get("subline"):
            p = ease_out((lt - 0.5) / 0.5)
            ssize, slines = fit(th, v["subline"], bw * 0.9, int(48 * u), int(30 * u))
            for i, line in enumerate(slines):
                draw_text(d, th, (cx, ly + len(lines) * size * 1.15 + 20 * u + i * ssize * 1.2), line, ssize,
                          rgba(th.accent, p * outro), "mm")

    elif typ == "question":
        size, lines = fit(th, v.get("text", ""), bw * 0.92, int(92 * u), int(46 * u), max_lines=3)
        words_total = sum(len(l.split()) for l in lines)
        k = 0
        start_y = cy - (len(lines) - 1) * size * 0.6 + 60 * u
        for i, line in enumerate(lines):
            words = line.split()
            x = cx - text_width(th, line, size) / 2
            for w in words:
                p = ease_back((lt - 0.08 * k) / 0.45)
                col = th.highlight if w.strip("?!.,").lower() in {"github", "git", "ai", "code", "developers"} else th.text
                ww = text_width(th, w + " ", size)
                draw_text(d, th, (x, start_y + i * size * 1.2 - (1 - clamp(p)) * 30 * u), w, size, rgba(col, clamp(p) * outro),
                          "lm", stroke=int(3 * u), stroke_fill=rgba(th.bg_top, clamp(p) * outro))
                x += ww
                k += 1
        pulse = 1 + 0.06 * math.sin(lt * 5)
        qa = ease_out((lt - 0.08 * words_total) / 0.4) * outro
        draw_text(d, th, (cx, y0 + bh * 0.16), "?", int(170 * u * pulse), rgba(th.accent, qa * 0.9), "mm")

    elif typ == "timeline":
        events = v.get("events", [])[:6]
        n = max(1, len(events))
        line_p = ease_in_out(lt / (0.4 + 0.5 * n))
        if th.portrait:
            lx = x0 + bw * 0.2
            ya, yb = y0 + 30 * u, y1 - 30 * u
            d.line([lx, ya, lx, ya + (yb - ya) * line_p], fill=rgba(th.accent, A), width=int(8 * u))
            for i, ev in enumerate(events):
                p = ease_back((lt - 0.3 - 0.45 * i) / 0.45)
                y = ya + (yb - ya) * (i + 0.5) / n
                r = 20 * u * clamp(p, 0, 1.3)
                d.ellipse([lx - r, y - r, lx + r, y + r], fill=rgba(th.highlight, A))
                pa = clamp(p) * outro
                draw_text(d, th, (lx - 40 * u, y), str(ev.get("year", "")), int(46 * u), rgba(th.highlight, pa), "rm")
                lsize, llines = fit(th, str(ev.get("label", "")), bw * 0.62, int(44 * u), int(28 * u))
                for j, l in enumerate(llines):
                    draw_text(d, th, (lx + 44 * u + (1 - clamp(p)) * 40 * u, y + (j - (len(llines) - 1) / 2) * lsize * 1.15),
                              l, lsize, rgba(th.text, pa), "lm")
        else:
            ly = cy
            xa, xb = x0 + 40 * u, x1 - 40 * u
            d.line([xa, ly, xa + (xb - xa) * line_p, ly], fill=rgba(th.accent, A), width=int(8 * u))
            for i, ev in enumerate(events):
                p = ease_back((lt - 0.3 - 0.45 * i) / 0.45)
                x = xa + (xb - xa) * (i + 0.5) / n
                r = 20 * u * clamp(p, 0, 1.3)
                d.ellipse([x - r, ly - r, x + r, ly + r], fill=rgba(th.highlight, A))
                pa = clamp(p) * outro
                draw_text(d, th, (x, ly - 70 * u), str(ev.get("year", "")), int(50 * u), rgba(th.highlight, pa), "mm")
                lsize, llines = fit(th, str(ev.get("label", "")), (xb - xa) / n * 0.95, int(36 * u), int(24 * u), 3)
                for j, l in enumerate(llines):
                    draw_text(d, th, (x, ly + 70 * u + j * lsize * 1.2), l, lsize, rgba(th.text, pa), "mm")

    elif typ == "stat":
        value = str(v.get("value", ""))
        m = re.match(r"^([^\d]*)([\d.,]+)(.*)$", value)
        p = ease_out(lt / 1.4)
        if m:
            pre, num, suf = m.groups()
            target = float(num.replace(",", ""))
            shown = target * p
            dec = len(num.split(".")[1]) if "." in num else 0
            txt = f"{pre}{shown:,.{dec}f}{suf}" if "," in num else f"{pre}{shown:.{dec}f}{suf}"
        else:
            txt = value
        R = min(bw, bh) * 0.36
        ry = cy - bh * 0.06
        d.arc([cx - R, ry - R, cx + R, ry + R], 0, 360, fill=(255, 255, 255, int(25 * A)), width=int(16 * u))
        d.arc([cx - R, ry - R, cx + R, ry + R], -90, -90 + 360 * p, fill=rgba(th.accent, A), width=int(16 * u))
        size, _ = fit(th, txt, R * 1.6, int(150 * u), int(60 * u), 1)
        draw_text(d, th, (cx, ry), txt, size, rgba(th.highlight, A), "mm", stroke=int(3 * u), stroke_fill=rgba(th.bg_top, A))
        lsize, llines = fit(th, v.get("label", ""), bw * 0.9, int(48 * u), int(30 * u))
        la = ease_out((lt - 0.6) / 0.5) * outro
        for j, l in enumerate(llines):
            draw_text(d, th, (cx, ry + R + 60 * u + j * lsize * 1.2), l, lsize, rgba(th.text, la), "mm")

    elif typ == "flow":
        nodes = v.get("nodes", [])[:5]
        n = max(1, len(nodes))
        for i, label in enumerate(nodes):
            p = ease_back((lt - 0.55 * i) / 0.5)
            pa = clamp(p) * outro
            if th.portrait:
                nh = min(150 * u, bh / n * 0.62)
                y = y0 + (bh) * (i + 0.5) / n
                box = [cx - bw * 0.4, y - nh / 2, cx + bw * 0.4, y + nh / 2]
                if i < n - 1:
                    ap = ease_in_out((lt - 0.55 * i - 0.35) / 0.4)
                    ya, yb = y + nh / 2 + 6 * u, y + bh / n - nh / 2 - 6 * u
                    ye = ya + (yb - ya) * ap
                    d.line([cx, ya, cx, ye], fill=rgba(th.accent, A), width=int(7 * u))
                    if ap > 0.95:
                        d.polygon([(cx - 18 * u, ye - 18 * u), (cx + 18 * u, ye - 18 * u), (cx, ye + 4 * u)], fill=rgba(th.accent, A))
            else:
                nw = min(330 * u, bw / n * 0.75)
                x = x0 + bw * (i + 0.5) / n
                box = [x - nw / 2, cy - 90 * u, x + nw / 2, cy + 90 * u]
                if i < n - 1:
                    ap = ease_in_out((lt - 0.55 * i - 0.35) / 0.4)
                    xa, xb = x + nw / 2 + 6 * u, x + bw / n - nw / 2 - 6 * u
                    xe = xa + (xb - xa) * ap
                    d.line([xa, cy, xe, cy], fill=rgba(th.accent, A), width=int(7 * u))
                    if ap > 0.95:
                        d.polygon([(xe - 18 * u, cy - 18 * u), (xe - 18 * u, cy + 18 * u), (xe + 4 * u, cy)], fill=rgba(th.accent, A))
            if p <= 0:
                continue
            sc = clamp(p, 0, 1.15)
            bx0, by0, bx1, by1 = box
            mx, my = (bx0 + bx1) / 2, (by0 + by1) / 2
            box = [mx - (mx - bx0) * sc, my - (my - by0) * sc, mx + (bx1 - mx) * sc, my + (by1 - my) * sc]
            d.rounded_rectangle(box, radius=int(24 * u), fill=rgba(th.primary, 0.85 * pa),
                                outline=rgba(th.accent, pa), width=int(3 * u))
            size, lines = fit(th, str(label), (box[2] - box[0]) * 0.88, int(46 * u), int(24 * u))
            for j, l in enumerate(lines):
                draw_text(d, th, (mx, my + (j - (len(lines) - 1) / 2) * size * 1.15), l, size, rgba(th.text, pa), "mm")

    elif typ == "branch_graph":
        # Animated version-control graph: main line, feature branch, commits, merge.
        p = lt / max(1.0, dur - 0.4)
        main_c, feat_c = th.accent, th.highlight
        if th.portrait:
            X_main, X_feat = cx - bw * 0.18, cx + bw * 0.2
            ys = [y0 + bh * f for f in (0.06, 0.21, 0.36, 0.51, 0.66, 0.80)]
            pos_main = [(X_main, y) for y in ys]
            pos_feat = [(X_feat, ys[2]), (X_feat, ys[3])]
        else:
            Y_main, Y_feat = cy + bh * 0.12, cy - bh * 0.18
            xs = [x0 + bw * f for f in (0.06, 0.24, 0.42, 0.6, 0.78, 0.94)]
            pos_main = [(x, Y_main) for x in xs]
            pos_feat = [(xs[2], Y_feat), (xs[3], Y_feat)]
        seq = [("m", 0), ("m", 1), ("f", 0), ("f", 1), ("merge", 4), ("m", 5)]
        lw = int(9 * u)
        R = 22 * u
        shown = int(clamp(p * 1.15) * len(seq) + 0.0001)
        for i in range(1, len(pos_main)):
            if ("m", i) in seq[:shown] or (i == 4 and ("merge", 4) in seq[:shown]) or (i in (2, 3) and shown >= 3):
                d.line([pos_main[i - 1], pos_main[i]], fill=rgba(main_c, A), width=lw)
        if shown >= 3:
            d.line([pos_main[1], pos_feat[0]], fill=rgba(feat_c, A), width=lw)
        if shown >= 4:
            d.line([pos_feat[0], pos_feat[1]], fill=rgba(feat_c, A), width=lw)
        if shown >= 5:
            d.line([pos_feat[1], pos_main[4]], fill=rgba(feat_c, A), width=lw)
        for k, (kind, idx) in enumerate(seq[:shown]):
            pt = pos_feat[idx] if kind == "f" else pos_main[idx]
            col = feat_c if kind == "f" else main_c
            age = clamp((p * 1.15 * len(seq) - k) / 1.0)
            r = R * ease_back(age)
            d.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=rgba(col, A), outline=rgba(th.text, A), width=int(3 * u))
        for i in (2, 3):
            if shown >= 2:
                pt = pos_main[i]
                d.ellipse([pt[0] - R * 0.8, pt[1] - R * 0.8, pt[0] + R * 0.8, pt[1] + R * 0.8], fill=rgba(main_c, A))
        lab = v.get("label", "")
        labels = v.get("labels", {"main": "main", "feature": "feature", "merge": "merge"})
        fs = int(36 * u)
        if th.portrait:
            draw_text(d, th, (pos_main[0][0] - 40 * u, pos_main[0][1]), labels.get("main", "main"), fs, rgba(main_c, A), "rm")
            if shown >= 3:
                draw_text(d, th, (pos_feat[0][0] + 40 * u, pos_feat[0][1]), labels.get("feature", "feature"), fs, rgba(feat_c, A), "lm")
            if shown >= 5:
                draw_text(d, th, (pos_main[4][0] - 40 * u, pos_main[4][1]), labels.get("merge", "merge"), fs, rgba(th.text, A), "rm")
        else:
            draw_text(d, th, (pos_main[0][0], pos_main[0][1] + 60 * u), labels.get("main", "main"), fs, rgba(main_c, A), "mm")
            if shown >= 3:
                draw_text(d, th, (pos_feat[0][0], pos_feat[0][1] - 60 * u), labels.get("feature", "feature"), fs, rgba(feat_c, A), "mm")
            if shown >= 5:
                draw_text(d, th, (pos_main[4][0], pos_main[4][1] + 60 * u), labels.get("merge", "merge"), fs, rgba(th.text, A), "mm")
        if lab:
            size, lines = fit(th, lab, bw * 0.9, int(44 * u), int(28 * u))
            for j, l in enumerate(lines):
                draw_text(d, th, (cx, y0 + bh * 0.92 + j * size * 1.15 if th.portrait else y0 + 10 * u + j * size * 1.15), l, size,
                          rgba(th.text, A), "mm")

    elif typ == "icon_grid":
        items = v.get("items", [])[:6]
        n = max(1, len(items))
        cols = 2 if th.portrait else min(3, n)
        if th.portrait and n == 3:
            cols = 3
        rows = math.ceil(n / cols)
        cw, chh = bw / cols, bh / rows
        for i, it in enumerate(items):
            r_, c_ = divmod(i, cols)
            ix, iy = x0 + cw * (c_ + 0.5), y0 + chh * (r_ + 0.5)
            p = ease_back((lt - 0.3 * i) / 0.5)
            pa = clamp(p) * outro
            if p <= 0:
                continue
            sc = clamp(p, 0, 1.12)
            hw, hh = cw * 0.44 * sc, chh * 0.44 * sc
            _panel(d, [ix - hw, iy - hh, ix + hw, iy + hh], th, pa)
            isz = min(cw, chh) * 0.42 * sc
            draw_icon(d, th, it.get("icon", "star"), ix, iy - hh * 0.22, isz, th.accent, pa)
            size, lines = fit(th, it.get("label", ""), hw * 1.8, int(38 * u), int(22 * u))
            for j, l in enumerate(lines):
                draw_text(d, th, (ix, iy + hh * 0.55 + j * size * 1.1), l, size, rgba(th.text, pa), "mm")

    elif typ == "code":
        lines = v.get("lines", [])[:8]
        _panel(d, [x0, y0, x1, y1], th, A, 22)
        d.rounded_rectangle([x0, y0, x1, y0 + 56 * u], radius=int(22 * u), fill=(0, 0, 0, int(90 * A)))
        for k, col in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse([x0 + (30 + k * 36) * u - 11 * u, y0 + 28 * u - 11 * u, x0 + (30 + k * 36) * u + 11 * u, y0 + 28 * u + 11 * u],
                      fill=rgba(col, A))
        fsz = int(min(46 * u, (bh - 100 * u) / max(6, len(lines)) * 0.72))
        chars_per_s = 32
        budget = max(0.0, lt - 0.4) * chars_per_s
        mono = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
        f = font(mono if Path(mono).is_file() else th.latin, fsz)
        y = y0 + 90 * u
        for li, line in enumerate(lines):
            if budget <= 0:
                break
            shown = line[: int(budget)]
            budget -= len(line) + 4
            col = th.accent if line.lstrip().startswith(("$", "git", "#", "//")) else th.text
            if line.lstrip().startswith(("#", "//")):
                col = (148, 163, 184)
            d.text((x0 + 36 * u, y), shown, font=f, fill=rgba(col, A), anchor="lm")
            if 0 < budget < len(line) + 4 or li == len(lines) - 1:
                if int(lt * 2.5) % 2 == 0:
                    cxp = x0 + 36 * u + f.getlength(shown) + 6 * u
                    d.rectangle([cxp, y - fsz * 0.45, cxp + fsz * 0.5, y + fsz * 0.45], fill=rgba(th.highlight, A))
            y += fsz * 1.45

    elif typ == "bullets":
        items = v.get("items", [])[:5]
        n = max(1, len(items))
        for i, it in enumerate(items):
            p = ease_out((lt - 0.45 * i) / 0.45)
            pa = p * outro
            y = y0 + bh * (i + 0.5) / n
            off = (1 - p) * 120 * u
            draw_icon(d, th, "check", x0 + 50 * u - off, y, 70 * u, th.highlight, pa)
            size, lines = fit(th, str(it), bw - 140 * u, int(50 * u), int(28 * u))
            for j, l in enumerate(lines):
                draw_text(d, th, (x0 + 110 * u - off, y + (j - (len(lines) - 1) / 2) * size * 1.15), l, size, rgba(th.text, pa), "lm")

    elif typ == "compare":
        sides = [v.get("left", {}), v.get("right", {})]
        for i, sd in enumerate(sides):
            p = ease_back((lt - 0.5 * i) / 0.5)
            pa = clamp(p) * outro
            if th.portrait:
                box = [x0, y0 + i * bh / 2 + 10 * u, x1, y0 + (i + 1) * bh / 2 - 10 * u]
            else:
                box = [x0 + i * bw / 2 + 12 * u, y0, x0 + (i + 1) * bw / 2 - 12 * u, y1]
            off = (1 - clamp(p)) * 80 * u * (1 if i else -1)
            box = [box[0] + off, box[1], box[2] + off, box[3]]
            _panel(d, box, th, pa)
            bcx = (box[0] + box[2]) / 2
            draw_text(d, th, (bcx, box[1] + 55 * u), sd.get("title", ""), int(50 * u), rgba(th.highlight if i else th.accent, pa), "mm")
            pts = sd.get("points", [])[:3]
            for j, pt in enumerate(pts):
                size, lines = fit(th, f"• {pt}", (box[2] - box[0]) * 0.86, int(38 * u), int(24 * u), 1)
                draw_text(d, th, (bcx, box[1] + 125 * u + j * size * 1.5), lines[0], size, rgba(th.text, pa), "mm")
        vs = ease_back((lt - 0.9) / 0.4)
        if vs > 0:
            r = 46 * u * clamp(vs, 0, 1.2)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba(th.primary, outro))
            draw_text(d, th, (cx, cy), "VS", int(40 * u * clamp(vs, 0, 1.2)), rgba(th.text, outro), "mm")

    elif typ == "outro":
        p = ease_back(lt / 0.6)
        draw_icon(d, th, v.get("icon", "heart"), cx, y0 + bh * 0.25, 220 * u * clamp(p, 0, 1.15), th.highlight, A)
        size, lines = fit(th, v.get("cta", ""), bw * 0.92, int(72 * u), int(40 * u))
        for j, l in enumerate(lines):
            draw_text(d, th, (cx, y0 + bh * 0.55 + j * size * 1.2), l, size, rgba(th.text, A), "mm",
                      stroke=int(3 * u), stroke_fill=rgba(th.bg_top, A))
        if th.channel:
            ca = ease_out((lt - 0.5) / 0.5) * outro
            draw_text(d, th, (cx, y0 + bh * 0.88), th.channel, int(52 * u), rgba(th.accent, ca), "mm")


# ------------------------------------------------------------------ captions
def caption_chunks(scene: dict, timing: dict, words_per_chunk: int = 4) -> list[dict]:
    """Split the Roman caption into word chunks timed across the scene's speech."""
    words = scene.get("caption_roman", "").split()
    if not words:
        return []
    groups = [words[i:i + words_per_chunk] for i in range(0, len(words), words_per_chunk)]
    # merge a tiny trailing group
    if len(groups) > 1 and len(groups[-1]) == 1:
        # NB: `groups[-2] += groups.pop()` would resolve the index before pop() and clobber the wrong group
        tail = groups.pop()
        groups[-1] = groups[-1] + tail
    total_chars = sum(len(w) + 1 for w in words)
    s0, s1 = timing["speech_start"], timing["speech_end"]
    t = s0
    out = []
    for g in groups:
        chars = sum(len(w) + 1 for w in g)
        dur = (s1 - s0) * chars / total_chars
        out.append({"start": t, "end": t + dur, "words": g})
        t += dur
    out[-1]["end"] = max(out[-1]["end"], timing["end"] - 0.02)
    return out


def caption_layout(th: Theme, words: list[str]) -> tuple[int, list[list[str]], list[float], tuple[float, float, float, float]]:
    """Return font size, lines (as word lists), line widths and the caption background box."""
    bx0, by0, bx1, by1 = th.caption_box
    max_w = (bx1 - bx0) - 60 * th.u
    size = int((68 if th.portrait else 58) * th.u)
    while True:
        lines: list[list[str]] = []
        cur: list[str] = []
        for w in words:
            trial = cur + [w]
            if cur and text_width(th, " ".join(trial), size) > max_w:
                lines.append(cur)
                cur = [w]
            else:
                cur = trial
        if cur:
            lines.append(cur)
        widths = [text_width(th, " ".join(l), size) for l in lines]
        if (len(lines) <= 2 and max(widths) <= max_w) or size <= 30 * th.u:
            break
        size = int(size * 0.92)
    lh = size * 1.25
    h = lh * len(lines) + 34 * th.u
    w = max(widths) + 60 * th.u
    cy = (by0 + by1) / 2 if th.portrait else by0 + h / 2 + 4 * th.u
    box = ((bx0 + bx1) / 2 - w / 2, cy - h / 2, (bx0 + bx1) / 2 + w / 2, cy + h / 2)
    return size, lines, widths, box


def draw_caption(d: ImageDraw.ImageDraw, th: Theme, chunk: dict, t: float):
    p_in = ease_out((t - chunk["start"]) / 0.18)
    size, lines, widths, box = caption_layout(th, chunk["words"])
    slide = (1 - p_in) * 18 * th.u
    d.rounded_rectangle([box[0], box[1] + slide, box[2], box[3] + slide], radius=int(22 * th.u),
                        fill=(5, 8, 20, int(185 * p_in)))
    nwords = sum(len(l) for l in lines)
    prog = clamp((t - chunk["start"]) / max(0.01, chunk["end"] - chunk["start"]))
    active = min(nwords - 1, int(prog * nwords))
    lh = size * 1.25
    k = 0
    for li, line in enumerate(lines):
        x = (box[0] + box[2]) / 2 - widths[li] / 2
        y = box[1] + 17 * th.u + lh * (li + 0.5) + slide
        for w in line:
            col = th.highlight if k == active else th.text
            draw_text(d, th, (x, y), w, size, rgba(col, p_in), "lm", stroke=int(2 * th.u), stroke_fill=(0, 0, 0, int(200 * p_in)))
            x += text_width(th, w + " ", size)
            k += 1


# ------------------------------------------------------------------ compositor
class Compositor:
    def __init__(self, th: Theme, storyboard: dict, timings: list[dict], total: float, transition: float = 0.45,
                 words_per_chunk: int = 4):
        self.th = th
        self.sb = storyboard
        self.scenes = storyboard["scenes"]
        self.timings = timings
        self.total = total
        self.tr = transition
        self.bg = Background(th)
        self.chunks = [c for sc, tm in zip(self.scenes, timings) for c in caption_chunks(sc, tm, words_per_chunk)]

    def scene_index(self, t: float) -> int:
        for i, tm in enumerate(self.timings):
            if t < tm["end"]:
                return i
        return len(self.timings) - 1

    def _scene_frame(self, i: int, t: float) -> Image.Image:
        tm = self.timings[i]
        dur = tm["end"] - tm["start"]
        lt = t - tm["start"]
        zoom = 1.0 + 0.05 * ease_in_out(lt / max(dur, 0.1))
        img = self.bg.frame(t, zoom=zoom)
        d = ImageDraw.Draw(img, "RGBA")
        render_scene_layer(d, self.th, self.scenes[i], lt, dur)
        return img

    def frame(self, t: float) -> Image.Image:
        i = self.scene_index(t)
        img = self._scene_frame(i, t)
        # transition into the next scene around the boundary
        half = self.tr / 2
        if i + 1 < len(self.scenes) and t > self.timings[i]["end"] - half:
            p = ease_in_out((t - (self.timings[i]["end"] - half)) / self.tr)
            img = self._transition(img, self._scene_frame(i + 1, max(t, self.timings[i + 1]["start"])),
                                   self.scenes[i + 1].get("transition", "fade"), p)
        elif i > 0 and t < self.timings[i]["start"] + half:
            p = ease_in_out((t - (self.timings[i]["start"] - half)) / self.tr)
            img = self._transition(self._scene_frame(i - 1, min(t, self.timings[i - 1]["end"] - 1e-3)), img,
                                   self.scenes[i].get("transition", "fade"), p)
        d = ImageDraw.Draw(img, "RGBA")
        self._chrome(d, t)
        for c in self.chunks:
            if c["start"] <= t < c["end"]:
                draw_caption(d, self.th, c, t)
                break
        return img

    def _transition(self, a: Image.Image, b: Image.Image, kind: str, p: float) -> Image.Image:
        W, H = self.th.W, self.th.H
        if kind == "slide":
            out = Image.new("RGB", (W, H))
            off = int(W * p)
            out.paste(a, (-off, 0))
            out.paste(b, (W - off, 0))
            return out
        if kind == "zoom":
            s = 1 + 0.25 * p
            cw, ch = W / s, H / s
            za = a.resize((W, H), Image.BILINEAR, box=((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2))
            return Image.blend(za, b, p)
        if kind == "wipe":
            mask = Image.new("L", (W, H), 0)
            md = ImageDraw.Draw(mask)
            x = (W + H) * p
            md.polygon([(0, 0), (x, 0), (x - H, H), (0, H)], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(12))
            return Image.composite(b, a, mask)
        return Image.blend(a, b, p)

    def _chrome(self, d: ImageDraw.ImageDraw, t: float):
        th = self.th
        u = th.u
        # progress bar (top) + channel badge inside safe area
        d.rectangle([0, 0, th.W * clamp(t / self.total), int(8 * u)], fill=rgba(th.accent, 0.9))
        if th.channel:
            x = th.W * th.margin_x
            y = th.H * th.safe_top - (30 * u if th.portrait else 50 * u)
            w = text_width(th, th.channel, int(30 * u)) + 70 * u
            d.rounded_rectangle([x, y - 26 * u, x + w, y + 26 * u], radius=int(26 * u), fill=(0, 0, 0, 110))
            d.ellipse([x + 16 * u, y - 10 * u, x + 36 * u, y + 10 * u], fill=rgba(th.highlight, 1))
            draw_text(d, th, (x + 50 * u, y), th.channel, int(30 * u), rgba(th.text, 0.95), "lm")


# ------------------------------------------------------------------ parallel rendering
def _worker(args):
    th, sb, timings, total, tr, wpc, fps, f0, f1, out, crf, preset = args
    comp = Compositor(th, sb, timings, total, tr, wpc)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{th.W}x{th.H}", "-r", str(fps),
           "-i", "-", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-r", str(fps), "-g", str(fps * 2), str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in range(f0, f1):
            proc.stdin.write(comp.frame(f / fps).tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed: {err[-400:]}")
    return str(out)


def render_video(th: Theme, sb: dict, timings: list[dict], total: float, out_mp4: Path, *, fps: int = 30,
                 workers: int = 4, transition: float = 0.45, words_per_chunk: int = 4, crf: int = 20,
                 preset: str = "medium", log=print) -> Path:
    """Render the silent motion-graphics track (exact length = total seconds)."""
    n = int(round(total * fps))
    workers = max(1, min(workers, mp.cpu_count(), n // fps or 1))
    bounds = [round(i * n / workers) for i in range(workers + 1)]
    parts = [out_mp4.with_name(f"{out_mp4.stem}.part{i}.mp4") for i in range(workers)]
    jobs = [(th, sb, timings, total, transition, words_per_chunk, fps, bounds[i], bounds[i + 1], parts[i], crf, preset)
            for i in range(workers)]
    log(f"  rendering {n} frames at {th.W}x{th.H} with {workers} workers…")
    ctx = mp.get_context("fork")
    try:
        with ctx.Pool(workers) as pool:
            pool.map(_worker, jobs)
    except Exception as exc:  # noqa: BLE001
        raise AgentError(f"frame rendering failed: {exc}", Category.RENDER) from exc
    lst = out_mp4.with_suffix(".concat.txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                        str(out_mp4)], capture_output=True, text=True)
    if r.returncode != 0:
        raise AgentError(f"concat failed: {r.stderr[-300:]}", Category.RENDER)
    for p in parts:
        p.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    return out_mp4


def snapshot(th: Theme, sb: dict, timings: list[dict], total: float, t: float, path: Path) -> Path:
    Compositor(th, sb, timings, total).frame(t).save(path)
    return path
