"""Reference-video analysis → reusable style profile for the premium editor.

Everything is measured from a real MP4 that the user supplies (we never invent an analysis):
pacing (scene cuts, shot length), motion energy, colour (brightness, contrast, saturation, warmth,
palette), caption band position, loudness and music tempo. The derived profile reproduces the
*general techniques* (pacing, energy, grade, caption placement) with our own original visuals —
it never copies the reference's footage, music, text or graphics.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .errors import AgentError, Category


def _probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AgentError(f"not a readable video: {path}", Category.ASSET)
    info = json.loads(r.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not v:
        raise AgentError("reference has no video stream", Category.ASSET)
    num, den = (v.get("avg_frame_rate") or "0/1").split("/")
    return {"duration": float(info["format"].get("duration", 0)), "width": v["width"], "height": v["height"],
            "fps": round(float(num) / float(den or 1), 3) if float(den or 1) else 0.0,
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}


def scene_cuts(path: Path, threshold: float = 0.32) -> list[float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", f"scale=180:-2,select='gt(scene,{threshold})',showinfo",
                        "-an", "-f", "null", "-"], capture_output=True, text=True)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def _frames(path: Path, fps: float = 5, w: int = 90, h: int = 160) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    n = a.size // (w * h * 3)
    return a[: n * w * h * 3].reshape(n, h, w, 3).astype(np.float32) / 255.0


def _kmeans(x: np.ndarray, k: int = 5, iters: int = 12, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    c = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab = ((x[:, None, :] - c[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            if (lab == j).any():
                c[j] = x[lab == j].mean(0)
    counts = np.bincount(lab, minlength=k)
    return c, counts


def colour_stats(frames: np.ndarray) -> dict:
    rgb = frames.reshape(-1, 3)
    y = 0.2126 * rgb[:, 0] + 0.7152 * rgb[:, 1] + 0.0722 * rgb[:, 2]
    mx, mn = rgb.max(1), rgb.min(1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    sample = rgb[np.random.default_rng(1).choice(len(rgb), min(20000, len(rgb)), replace=False)]
    cents, counts = _kmeans(sample, 5)
    order = np.argsort(-counts)
    palette = ["#%02x%02x%02x" % tuple(int(v * 255) for v in cents[i]) for i in order]
    return {"brightness": float(y.mean()), "contrast": float(y.std()), "saturation": float(sat.mean()),
            "warmth": float((rgb[:, 0] - rgb[:, 2]).mean()), "palette": palette,
            "palette_share": [round(float(counts[i] / counts.sum()), 3) for i in order]}


def motion_energy(frames: np.ndarray) -> dict:
    g = frames.mean(-1)
    d = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2)) if len(g) > 1 else np.zeros(1)
    return {"mean": float(d.mean()), "p90": float(np.percentile(d, 90)), "still_ratio": float((d < 0.004).mean())}


def caption_band(frames: np.ndarray) -> dict:
    """Estimate where captions live: bands whose amount of bright, low-saturation (white text) pixels
    changes most often — captions change every 1-2 s, titles/graphics far less often."""
    mx, mn = frames.max(-1), frames.min(-1)
    white = (mx > 0.82) & ((mx - mn) < 0.18)
    bands = 20
    h = white.shape[1]
    ratio = np.stack([white[:, int(b * h / bands):int((b + 1) * h / bands)].mean(axis=(1, 2)) for b in range(bands)], 1)
    change = np.abs(np.diff(ratio, axis=0)).mean(0) if len(ratio) > 1 else ratio.mean(0)
    mean = ratio.mean(0)
    # relative change: thin caption text changes often; big static titles have more white but change rarely
    rel = np.where(mean > 5e-4, change / (mean + 2e-3), 0.0)
    lower = slice(bands // 4, bands - 1)
    b = int(np.argmax(rel[lower])) + lower.start
    return {"band_center": round((b + 0.5) / bands, 3), "band_scores": [round(float(x), 3) for x in rel]}


def change_events(frames: np.ndarray, fps: float = 5) -> list[float]:
    """Hard cuts AND soft transitions: peaks in frame difference (≥ 0.8 s apart)."""
    g = frames.mean(-1)
    if len(g) < 3:
        return []
    d = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
    thr = max(d.mean() + 2 * d.std(), 0.02)
    ev, last = [], -1e9
    for i, x in enumerate(d):
        t = (i + 1) / fps
        if x > thr and t - last >= 0.8:
            ev.append(round(t, 2))
            last = t
    return ev


def audio_stats(path: Path) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    lra = re.findall(r"LRA:\s+([\d.]+) LU", r.stderr)
    sr = 11025
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    bpm = None
    if len(x) > sr * 6:
        hop, win = 256, 1024
        n = (len(x) - win) // hop
        frames = np.stack([x[k * hop:k * hop + win] * np.hanning(win) for k in range(n)])
        mag = np.abs(np.fft.rfft(frames, axis=1))
        freqs = np.fft.rfftfreq(win, 1 / sr)
        low = (freqs >= 30) & (freqs <= 85)  # kick/sub band: below typical narrator pitch, robust to speech
        flux = np.maximum(0, np.diff(mag[:, low], axis=0)).sum(1)
        flux = (flux - flux.mean()) / (flux.std() + 1e-9)
        ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
        fr = sr / hop
        lags = np.arange(len(ac)) / fr
        valid = (lags >= 0.25) & (lags <= 1.5)
        if valid.any():
            bpm = 60 / lags[valid][np.argmax(ac[valid])]
            while bpm < 80:
                bpm *= 2
            while bpm > 160:
                bpm /= 2
            bpm = round(float(bpm), 1)
    return {"integrated_lufs": float(i[-1]) if i else None, "lra": float(lra[-1]) if lra else None, "bpm_estimate": bpm}


def derive_style(a: dict) -> dict:
    """Map measurements → premium style profile (general techniques only)."""
    clamp = lambda v, lo, hi: max(lo, min(hi, v))  # noqa: E731
    # pacing: hard cuts if present, otherwise soft transitions/visual changes
    shot = a["pacing"]["avg_shot_seconds"] if a["pacing"]["cuts"] >= 3 else a["pacing"]["avg_change_interval_seconds"]
    shot = shot or 3.0
    me = a["motion"]["mean"]
    c = a["colour"]
    bpm = a["audio"].get("bpm_estimate") or 100
    return {
        "bpm": int(round(clamp(bpm, 80, 140))),
        "transitionSeconds": round(clamp(0.2 + 0.06 * shot, 0.25, 0.6), 2),
        "subCutSeconds": round(clamp(shot, 1.2, 4.0), 2),
        "cameraIntensity": round(clamp(me / 0.03, 0.3, 1.0), 2),
        "beatPunch": round(clamp(me / 0.03 * 0.03, 0.0, 0.045), 3),
        "motionBlur": me > 0.012,
        "caption": {"position": round(clamp(a["caption_band"]["band_center"], 0.6, 0.76), 3)},
        "grade": {
            "saturation": round(clamp(c["saturation"] / 0.35, 0.85, 1.3), 2),
            "contrast": round(clamp(c["contrast"] / 0.22, 0.95, 1.2), 2),
            "gamma": round(clamp(0.45 / max(c["brightness"], 0.05), 0.85, 1.15), 2),
            "highlights_warm": round(clamp(c["warmth"] * 0.4, -0.06, 0.08), 3),
            "shadows_teal": round(clamp(-c["warmth"] * 0.4 + 0.03, 0.0, 0.08), 3),
        },
    }


def analyze(path: str | Path, out_dir: Path, name: str | None = None) -> dict:
    path = Path(path)
    if not path.is_file():
        raise AgentError(f"reference video not found: {path}", Category.ASSET,
                         fix_hint="download the reference yourself (from your own account/with permission) and pass the MP4 path")
    info = _probe(path)
    cuts = scene_cuts(path)
    shots = np.diff([0.0, *cuts, info["duration"]]) if info["duration"] else np.array([0.0])
    frames = _frames(path)
    changes = change_events(frames)
    a = {
        "file": path.name, "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "video": info,
        "pacing": {"cuts": len(cuts), "cut_times": [round(c, 2) for c in cuts[:200]],
                   "avg_shot_seconds": round(float(shots.mean()), 2) if len(shots) else None,
                   "median_shot_seconds": round(float(np.median(shots)), 2) if len(shots) else None,
                   "cuts_per_10s": round(len(cuts) / max(info["duration"], 1e-6) * 10, 2),
                   "visual_changes": len(changes),
                   "avg_change_interval_seconds": round(info["duration"] / max(1, len(changes) + 1), 2)},
        "motion": motion_energy(frames), "colour": colour_stats(frames), "caption_band": caption_band(frames),
        "audio": audio_stats(path) if info["has_audio"] else {"integrated_lufs": None, "lra": None, "bpm_estimate": None},
    }
    a["aspect"] = "9:16" if info["height"] > info["width"] else "16:9" if info["width"] > info["height"] else "1:1"
    style = derive_style(a)
    name = name or re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-") or "reference"
    profile = {"name": f"ref-{name}", "source": f"reference:{path.name}", "analysis": a, "style": style,
               "note": "Derived from measured pacing/colour/motion/audio of the user's reference; apply with original content only."}
    out_dir.mkdir(parents=True, exist_ok=True)
    pj = out_dir / f"ref-{name}.json"
    pj.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    md = out_dir / f"ref-{name}.md"
    md.write_text(report_markdown(profile), encoding="utf-8")
    profile["files"] = {"profile": str(pj), "report": str(md)}
    return profile


def report_markdown(p: dict) -> str:
    a, s = p["analysis"], p["style"]
    v = a["video"]
    return "\n".join([
        f"# Reference analysis — {a['file']}", "",
        f"- Video: {v['width']}×{v['height']} ({a['aspect']}), {v['fps']} fps, {v['duration']:.1f}s, audio={v['has_audio']}",
        f"- Pacing: {a['pacing']['cuts']} cuts, avg shot {a['pacing']['avg_shot_seconds']}s "
        f"(median {a['pacing']['median_shot_seconds']}s), {a['pacing']['cuts_per_10s']} cuts/10s; "
        f"{a['pacing']['visual_changes']} visual changes incl. soft transitions (every ~{a['pacing']['avg_change_interval_seconds']}s)",
        f"- Motion energy: mean {a['motion']['mean']:.4f}, p90 {a['motion']['p90']:.4f}, still ratio {a['motion']['still_ratio']:.2f}",
        f"- Colour: brightness {a['colour']['brightness']:.2f}, contrast {a['colour']['contrast']:.2f}, "
        f"saturation {a['colour']['saturation']:.2f}, warmth {a['colour']['warmth']:+.3f}",
        f"- Palette: {', '.join(a['colour']['palette'])}",
        f"- Caption band (estimate): {a['caption_band']['band_center']:.2f} of frame height",
        f"- Audio: {a['audio'].get('integrated_lufs')} LUFS, LRA {a['audio'].get('lra')}, tempo ≈ {a['audio'].get('bpm_estimate')} BPM",
        "", "## Derived style (applied with original visuals/music only)", "```json", json.dumps(s, indent=2), "```",
        "", "Limits: typography, specific graphics and transition *types* can't be measured reliably from pixels; "
        "they come from the house preset unless you describe them.", ""])
