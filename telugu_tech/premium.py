"""Premium cinematic editing engine: Remotion (motion graphics) + FFmpeg (grade/finish).

Flow: storyboard + per-scene TTS (word boundaries) + beat-aligned timings
      → props.json → Remotion render (silent, exact duration)
      → FFmpeg grade (bloom, colour balance, contrast, vignette, grain)
      → MoneyPrinterTurbo final assembly with the mixed audio (unchanged).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .errors import AgentError, Category, retry_call

HOUSE_STYLE = {
    "name": "cinematic_tech",
    "source": "house-preset (not derived from any reference video)",
    "bpm": 100,
    "transitionSeconds": 0.4,
    "cameraIntensity": 0.7,
    "zoomRange": [1.0, 1.14],
    "motionBlur": True,
    "parallax": 0.6,
    "beatPunch": 0.025,
    "subCutSeconds": 2.4,
    "caption": {"template": "pop_highlight", "position": 0.70, "fontSize": 74, "maxWords": 3, "uppercase": False},
    "grade": {"contrast": 1.07, "saturation": 1.12, "gamma": 0.98, "shadows_teal": 0.05, "highlights_warm": 0.04,
              "bloom": 0.28, "vignette": 0.32, "grain": 3, "sharpen": 0.35},
}

PREMIUM_VISUALS = {"headline", "question", "title", "neural_net", "chart", "stat", "chat_ui", "code", "flow", "timeline",
                   "icon_grid", "bullets", "compare", "branch_graph", "globe", "molecule", "outro"}
CAMERAS = {"push_in", "pull_out", "pan_left", "pan_right", "orbit", "tilt", "drift"}
TRANSITIONS = {"whip", "mask", "iris", "zoom", "glitch", "fade", "push", "slide", "wipe"}
BACKGROUNDS = {"aurora", "grid", "circuit", "dots", "space", "particles"}
# Common Roman-Telugu words that are Latin script but not "technical keywords".
_NOT_KEYWORDS = {"ante", "oka", "mee", "lo", "ki", "ni", "tho", "ga", "ee", "aa", "inka", "kaani", "anduke", "ela", "enti",
                 "kosam", "meeda", "nunchi", "nunche", "kuda", "kooda", "ippudu", "ikkada", "akkada", "ledu", "undi"}


# ------------------------------------------------------------------ style
def load_style(cfg, profile_path: str | Path | None = None) -> dict:
    style = json.loads(json.dumps(HOUSE_STYLE))
    path = profile_path or cfg.get("premium", "style_profile", default="")
    if path:
        p = cfg.resolve(path)
        if p.is_file():
            prof = json.loads(p.read_text(encoding="utf-8"))
            for k, v in (prof.get("style") or prof).items():
                if isinstance(v, dict) and isinstance(style.get(k), dict):
                    style[k].update(v)
                elif k in style:
                    style[k] = v
            style["source"] = prof.get("source", f"profile:{p.name}")
    return style


def beat_grid(total: float, bpm: float) -> list[float]:
    step = 60.0 / bpm
    n = int(total / step) + 1
    return [round(i * step, 4) for i in range(n)]


# ------------------------------------------------------------------ words & keywords
TECH_TERMS = {
    "ai", "ml", "llm", "llms", "gpt", "api", "apis", "app", "apps", "code", "coding", "data", "dataset", "software", "hardware",
    "model", "models", "agent", "agents", "chatbot", "algorithm", "neural", "network", "cloud", "server", "database",
    "github", "git", "copilot", "python", "javascript", "typescript", "open-source", "opensource", "repository", "repo",
    "commit", "branch", "merge", "startup", "robot", "robots", "robotics", "quantum", "chip", "chips", "gpu", "cpu",
    "internet", "blockchain", "cybersecurity", "encryption", "automation", "generative", "transformer", "alphafold",
    "protein", "proteins", "dna", "nobel", "developer", "developers", "programming", "prompt", "token", "tokens",
}


def scene_keywords(scene: dict, limit: int = 3) -> set[str]:
    """Selective highlight set: explicit storyboard keywords first, then tech-lexicon words, product names
    (CamelCase), acronyms and figures (53%, 2024) from the narration. Capped so highlights stay meaningful."""
    explicit = [k.lower().strip(".,!?") for k in (scene.get("keywords") or (scene.get("visual") or {}).get("keywords") or [])]
    ranked: list[str] = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+#%-]*", scene.get("narration_te", "")):
        w = w.strip(".,")
        lw = w.lower()
        if lw in _NOT_KEYWORDS or len(w) < 2:
            continue
        prio = (0 if re.search(r"\d", w) else 1 if (re.fullmatch(r"[A-Z]{2,}", w) or re.search(r"[a-z][A-Z]", w)
                                                       or (w[0].isupper() and lw in TECH_TERMS)) else
                2 if lw in TECH_TERMS else None)
        if prio is not None and lw not in [r for _, r in ranked]:
            ranked.append((prio, lw))
    ranked = [w for _, w in sorted(ranked, key=lambda x: x[0])]
    out = list(dict.fromkeys(explicit))
    for k in ranked:
        if len(out) >= max(limit, len(explicit)):
            break
        if k not in out:
            out.append(k)
    return set(out)


def word_timeline(sb: dict, scene_audio: list[dict], timings: list[dict]) -> list[dict]:
    """Absolute word timings for the Roman captions, from Edge TTS word boundaries.

    If the Roman caption has the same word count as the spoken words, words map 1:1 (exact).
    Otherwise caption words are placed by character position along the spoken word timeline.
    """
    out: list[dict] = []
    for si, (sc, sa, tm) in enumerate(zip(sb["scenes"], scene_audio, timings)):
        caption = sc.get("caption_roman", "").split()
        if not caption:
            continue
        b = [x for x in sa.get("boundaries", []) if x.get("text")]
        shift = tm["speech_start"] - tm.get("trim", 0.0)
        spoken = [(shift + x["offset"], shift + x["offset"] + x["duration"]) for x in b]
        kws = scene_keywords(sc)
        if not spoken:  # no boundaries: even distribution over speech
            span = (tm["speech_end"] - tm["speech_start"]) / len(caption)
            spoken_c = [(tm["speech_start"] + i * span, tm["speech_start"] + (i + 1) * span) for i in range(len(caption))]
        elif len(spoken) == len(caption):
            spoken_c = spoken
        else:
            # piecewise-linear map: caption char fraction -> spoken char fraction -> time
            lens = [len(x["text"]) + 1 for x in b]
            tot = sum(lens)
            cum = [0.0]
            for L in lens:
                cum.append(cum[-1] + L / tot)
            clen = [len(w) + 1 for w in caption]
            ctot = sum(clen)
            spoken_c, acc = [], 0.0
            for L in clen:
                f0, f1 = acc / ctot, (acc + L) / ctot
                spoken_c.append((_interp_time(f0, cum, spoken), _interp_time(f1, cum, spoken)))
                acc += L
        for i, (w, (a, e)) in enumerate(zip(caption, spoken_c)):
            clean = re.sub(r"[^\w+#.-]", "", w).strip(".").lower()
            out.append({"text": w, "start": round(a, 3), "end": round(max(e, a + 0.12), 3), "scene": si,
                        "keyword": clean in kws, "pageEnd": i == len(caption) - 1})
    # enforce monotonic, non-overlapping
    for i in range(1, len(out)):
        if out[i]["start"] < out[i - 1]["start"]:
            out[i]["start"] = out[i - 1]["start"] + 0.01
        out[i - 1]["end"] = min(out[i - 1]["end"], max(out[i]["start"], out[i - 1]["start"] + 0.05))
    return out


def _interp_time(frac: float, cum: list[float], spoken: list[tuple[float, float]]) -> float:
    for k in range(len(spoken)):
        if cum[k] <= frac <= cum[k + 1]:
            a, e = spoken[k]
            r = (frac - cum[k]) / max(1e-9, cum[k + 1] - cum[k])
            return a + (e - a) * r
    return spoken[-1][1]


def caption_pages(words: list[dict], max_words: int) -> list[dict]:
    """Python mirror of Remotion's buildPages (used by quality checks)."""
    pages, cur = [], []
    for i, w in enumerate(words):
        if cur and cur[0]["scene"] != w["scene"]:
            pages.append(cur)
            cur = []
        cur.append(w)
        if w.get("pageEnd") or len(cur) >= max_words or re.search(r"[.!?,]$", w["text"]) or i == len(words) - 1:
            pages.append(cur)
            cur = []
    return [{"words": p, "start": p[0]["start"], "end": p[-1]["end"]} for p in pages if p]


# ------------------------------------------------------------------ props
def build_props(cfg, sb: dict, timings: list[dict], words: list[dict], total: float, style: dict, kind: str) -> dict:
    v = cfg.get("video", kind)
    b = cfg.get("branding")
    fps = v["fps"]
    scenes = []
    for i, (sc, tm) in enumerate(zip(sb["scenes"], timings)):
        vis = dict(sc.get("visual") or {})
        vis["keywords"] = sorted(scene_keywords(sc))
        scenes.append({
            "id": sc.get("id", i + 1), "section": sc["section"], "start": tm["start"], "end": tm["end"],
            "speechStart": tm["speech_start"], "speechEnd": tm["speech_end"], "visual": vis,
            "transition": sc.get("transition", "fade"), "camera": sc.get("camera", ""), "background": sc.get("background", ""),
            **({"tag": sc["tag"]} if sc.get("tag") else {}),
        })
    style_r = {k: style[k] for k in ("name", "source", "bpm", "transitionSeconds", "cameraIntensity", "zoomRange", "motionBlur",
                                      "parallax", "beatPunch", "subCutSeconds", "caption")}
    return {
        "width": v["width"], "height": v["height"], "fps": fps, "durationInFrames": int(round(total * fps)),
        "theme": {"primary": b["primary"], "accent": b["accent"], "highlight": b["highlight"], "bgTop": b.get("premium_bg_top", "#070B18"),
                  "bgBottom": b["bg_bottom"], "text": b["text"], "danger": "#F43F5E"},
        "style": style_r,
        "fonts": {"display": "TTDisplay", "telugu": "TTTelugu", "mono": "TTMono", "body": "TTDisplay"},
        "scenes": scenes, "words": words, "beats": beat_grid(total, style["bpm"]),
    }


# ------------------------------------------------------------------ remotion
def remotion_dir(cfg) -> Path:
    return cfg.resolve(cfg.get("premium", "remotion_dir", default="remotion"))


def find_browser(cfg) -> str | None:
    configured = cfg.get("premium", "browser_executable", default="") or os.environ.get("REMOTION_BROWSER", "")
    if configured and Path(configured).is_file():
        return configured
    for pattern in ("/opt/pw-browsers/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
                    "/opt/pw-browsers/chromium-*/chrome-linux64/chrome",
                    str(Path.home() / ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")):
        hits = sorted(Path("/").glob(pattern.lstrip("/"))) if pattern.startswith("/") else []
        if hits:
            return str(hits[-1])
    for name in ("chrome-headless-shell", "chromium", "chromium-browser", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None  # Remotion will try to download its own headless shell


def render_remotion(cfg, props: dict, out_mp4: Path, log=print) -> Path:
    rdir = remotion_dir(cfg)
    if not (rdir / "node_modules" / "@remotion" / "cli").is_dir():
        raise AgentError("Remotion not installed", Category.DEPENDENCY, fix_hint="telugu-tech setup (runs npm ci in remotion/)")
    for f in ("NotoSansDisplay-Bold.ttf", "NotoSansTelugu-Bold.ttf", "NotoSansMono-Bold.ttf"):
        if not (rdir / "public" / "fonts" / f).is_file():
            raise AgentError(f"Remotion font missing: {f}", Category.FONT, fix_hint="telugu-tech fix-errors")
    props_file = out_mp4.with_suffix(".props.json")
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    cmd = ["npx", "remotion", "render", "src/index.ts", "TeluguTechShort", str(out_mp4.resolve()),
           f"--props={props_file.resolve()}", "--codec=h264", "--crf=17", "--pixel-format=yuv420p",
           f"--concurrency={cfg.get('premium', 'concurrency', default=4)}", "--gl=swangle", "--log=error",
           "--image-format=jpeg", "--jpeg-quality=92", "--muted"]
    browser = find_browser(cfg)
    if browser:
        cmd.append(f"--browser-executable={browser}")
    env = {**os.environ, "REMOTION_DISABLE_TELEMETRY": "1"}

    def once():
        r = subprocess.run(cmd, cwd=rdir, capture_output=True, text=True, env=env,
                           timeout=cfg.get("premium", "render_timeout_seconds", default=2400))
        if r.returncode != 0 or not out_mp4.is_file():
            tail = (r.stderr or r.stdout)[-700:]
            cat = Category.DEPENDENCY if "Could not find" in tail or "ENOENT" in tail else Category.RENDER
            raise AgentError(f"Remotion render failed: {tail}", cat)
        return out_mp4

    log(f"  Remotion: {props['durationInFrames']} frames {props['width']}x{props['height']} "
        f"(browser: {Path(browser).name if browser else 'remotion-managed'})")
    return retry_call(once, max_attempts=cfg.get("retry", "max_attempts", default=3),
                      on_retry=lambda a, e, d: log(f"  Remotion attempt {a} failed; retrying in {d:.0f}s: {str(e)[:160]}"))


# ------------------------------------------------------------------ ffmpeg finishing
def grade_filter(g: dict, width: int = 1080, height: int = 1920) -> str:
    bloom = float(g.get("bloom", 0))
    parts = []
    if bloom > 0:
        # bloom computed at quarter resolution (≈16× cheaper than a full-res blur, visually identical glow)
        parts.append(f"split[a][b];[b]scale={width // 4}:{height // 4},gblur=sigma=6,eq=brightness=-0.08:saturation=1.3,"
                     f"scale={width}:{height}:flags=bicubic[g];[a][g]blend=all_mode=screen:all_opacity={bloom:.2f}")
    chain = [
        f"eq=contrast={g.get('contrast', 1.0)}:saturation={g.get('saturation', 1.0)}:gamma={g.get('gamma', 1.0)}",
        f"colorbalance=rs={-g.get('shadows_teal', 0):.3f}:bs={g.get('shadows_teal', 0):.3f}:rh={g.get('highlights_warm', 0):.3f}:bh={-g.get('highlights_warm', 0):.3f}",
    ]
    if g.get("sharpen"):
        chain.append(f"unsharp=5:5:{g['sharpen']}:5:5:0")
    if g.get("vignette"):
        chain.append(f"vignette=angle={0.2 + float(g['vignette']):.2f}")
    if g.get("grain"):
        chain.append(f"noise=alls={int(g['grain'])}:allf=t")
    chain.append("format=yuv420p")
    body = ",".join(chain)
    return f"{parts[0]},{body}" if parts else body


def grade(in_mp4: Path, out_mp4: Path, g: dict, fps: int = 30, width: int = 1080, height: int = 1920) -> Path:
    vf = grade_filter(g, width, height)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(in_mp4), "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]",
                        "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", "-an", str(out_mp4)], capture_output=True, text=True)
    if r.returncode != 0:
        raise AgentError(f"FFmpeg grading failed: {r.stderr[-400:]}", Category.RENDER)
    return out_mp4


# ------------------------------------------------------------------ sound design
def sfx_events(sb: dict, timings: list[dict]) -> list[tuple[float, str]]:
    """Restrained sound design: one transition sound per cut, ONE impact+riser for the first turning point,
    and type-specific accents (typing, ding, pop, shimmer)."""
    ev: list[tuple[float, str]] = []
    first_turn = next((i for i, sc in enumerate(sb["scenes"]) if sc["section"] == "turning_point"), None)
    for i, (sc, tm) in enumerate(zip(sb["scenes"], timings)):
        typ = (sc.get("visual") or {}).get("type", "")
        tr = sc.get("transition", "fade")
        if i > 0:
            ev.append((tm["start"], "glitch" if tr == "glitch" else "whoosh"))
        if i == first_turn and i > 0:
            ev.append((tm["start"], "impact"))
            ev.append((tm["start"], "riser"))
        if typ in ("code", "chat_ui"):
            ev.append((tm["start"] + 0.35, "typing"))
        if typ in ("stat", "chart"):
            ev.append((tm["start"] + 1.3, "ding"))
        if typ in ("headline", "question", "title", "outro", "globe", "molecule"):
            ev.append((tm["start"] + 0.15, "shimmer" if typ in ("globe", "molecule") else "pop"))
    if timings:
        ev.append((0.05, "impact"))
    return ev


def music_dropouts(sb: dict, timings: list[dict]) -> list[float]:
    return [tm["start"] for sc, tm in zip(sb["scenes"], timings) if sc["section"] == "turning_point"][:1]


# ------------------------------------------------------------------ render entry point
def render_visuals(cfg, sb: dict, timings: list[dict], words: list[dict], total: float, kind: str, work: Path,
                   style: dict, log=print) -> dict:
    props = build_props(cfg, sb, timings, words, total, style, kind)
    raw = work / "premium_raw.mp4"
    render_remotion(cfg, props, raw, log=log)
    out = work / "material.mp4"
    log("  FFmpeg: cinematic grade (bloom, colour balance, contrast, vignette, grain)")
    grade(raw, out, style.get("grade", {}), fps=props["fps"], width=props["width"], height=props["height"])
    (work / "premium_props.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"engine": "premium (Remotion + FFmpeg)", "style": style["name"], "style_source": style["source"],
            "frames": props["durationInFrames"]}
