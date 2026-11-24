"""Quality validation of the ACTUAL rendered output (ffprobe/ffmpeg), captions, fonts, sources, licences."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import ImageFont

from .subtitles import parse_srt
from .visuals import Theme, caption_chunks, caption_layout


def ffprobe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    return json.loads(r.stdout)


def _fps(rate: str) -> float:
    try:
        a, b = rate.split("/")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return 0.0


def decode_check(path: Path) -> tuple[bool, str]:
    """Full decode pass — proves the file plays end to end."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    errs = r.stderr.strip()
    return r.returncode == 0 and not errs, errs[-300:]


def loudness(path: Path) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    s = r.stderr
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", s)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", s)
    return {"integrated_lufs": float(i[-1]) if i else None, "true_peak_dbfs": float(tp[-1]) if tp else None}


def black_frames(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.06", "-an",
                        "-f", "null", "-"], capture_output=True, text=True)
    return sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", r.stderr))


def font_covers(font_path: str, text: str) -> bool:
    """True if the font has real glyphs (not .notdef) for every Telugu character."""
    try:
        from fontTools.ttLib import TTFont  # optional
        cmap = TTFont(font_path).getBestCmap()
        return all(ord(c) in cmap for c in set(text) if "\u0C00" <= c <= "\u0C7F")
    except ImportError:
        f = ImageFont.truetype(font_path, 40)
        notdef = f.getmask("\uFFFF").getbbox()
        for c in set(text):
            if "\u0C00" <= c <= "\u0C7F" and not ("\u0C3E" <= c <= "\u0C56" or c in "\u0C4D\u0C02\u0C03\u0C01\u0C00"):
                if f.getmask(c).getbbox() == notdef:
                    return False
        return True


def validate_video(path: Path, cfg, kind: str, *, sb: dict | None = None, timings: list[dict] | None = None,
                   theme: Theme | None = None, srt_files: list[Path] | None = None, licenses: Path | None = None) -> dict:
    v = cfg.get("video", kind)
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    info = ffprobe(path) if path.is_file() else {}
    add("file exists & non-empty", path.is_file() and path.stat().st_size > 10_000, str(path))
    vs = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    au = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    if vs:
        s = vs[0]
        add("resolution", (s["width"], s["height"]) == (v["width"], v["height"]),
            f"{s['width']}x{s['height']} (want {v['width']}x{v['height']})")
        ar = s["width"] / s["height"]
        add("aspect ratio", abs(ar - (9 / 16 if kind == "short" else 16 / 9)) < 0.01, f"{ar:.4f}")
        fps = _fps(s.get("avg_frame_rate", "0/1"))
        add("frame rate 30 fps", abs(fps - v["fps"]) < 0.05, f"{fps:.3f}")
        add("video codec H.264 yuv420p", s.get("codec_name") == "h264" and s.get("pix_fmt") == "yuv420p",
            f"{s.get('codec_name')} {s.get('pix_fmt')}")
    else:
        add("video stream present", False)
    add("container MP4", "mp4" in info.get("format", {}).get("format_name", ""), info.get("format", {}).get("format_name", ""))
    add("audio stream AAC", bool(au) and au[0].get("codec_name") == "aac", au[0].get("codec_name") if au else "none")
    add("duration in range", v["min_seconds"] <= dur <= v["max_seconds"], f"{dur:.2f}s (want {v['min_seconds']}-{v['max_seconds']})")

    if path.is_file():
        ok, err = decode_check(path)
        add("full decode (playback) without errors", ok, err or "clean")
        ld = loudness(path)
        li, tp = ld["integrated_lufs"], ld["true_peak_dbfs"]
        add("loudness -16..-12 LUFS", li is not None and -16.5 <= li <= -11.5, f"{li} LUFS")
        add("no clipping (true peak ≤ -1.0 dBFS)", tp is not None and tp <= -1.0, f"{tp} dBFS")
        bf = black_frames(path)
        add("no long black segments", bf < 1.0, f"{bf:.2f}s black")

    if sb is not None and timings is not None:
        last_end = timings[-1]["end"] if timings else 0
        add("visual timeline matches audio", abs(last_end - dur) < 0.25, f"timeline {last_end:.2f}s vs file {dur:.2f}s")
        srcs = sb.get("sources") or []
        add("sources recorded with URLs + dates", bool(srcs) and all(s.get("url") and s.get("published") for s in srcs),
            f"{len(srcs)} sources")
        add("every fact cites a source", all(f.get("source_ids") for f in sb.get("facts", [])), f"{len(sb.get('facts', []))} facts")
    if theme is not None and sb is not None and timings is not None:
        bx0, by0, bx1, by1 = theme.caption_box
        worst = None
        ok = True
        for sc, tm in zip(sb["scenes"], timings):
            for c in caption_chunks(sc, tm, cfg.get("captions", "words_per_chunk", default=4)):
                _, lines, _, box = caption_layout(theme, c["words"])
                if len(lines) > 2 or box[0] < bx0 - 1 or box[2] > bx1 + 1 or box[1] < by0 - 1 or box[3] > by1 + 1:
                    ok, worst = False, (c["words"], box)
        add("captions inside safe margins (≤2 lines)", ok, "all chunks fit" if ok else f"overflow: {worst}")
        all_text = " ".join(s["narration_te"] + " " + str(s.get("visual")) for s in sb["scenes"]) + sb.get("title_te", "")
        add("Telugu font covers all glyphs", font_covers(theme.telugu, all_text), Path(theme.telugu).name)
    for srt in srt_files or []:
        try:
            cues = parse_srt(srt)
            mono = all(a < b for a, b, _ in cues) and all(cues[i][1] <= cues[i + 1][0] + 1e-3 for i in range(len(cues) - 1))
            add(f"SRT valid & synced: {srt.name}", bool(cues) and mono and cues[-1][1] <= dur + 0.05,
                f"{len(cues)} cues, last ends {cues[-1][1]:.2f}s" if cues else "no cues")
        except Exception as exc:  # noqa: BLE001
            add(f"SRT valid: {srt.name}", False, str(exc))
    if licenses is not None:
        try:
            lic = json.loads(licenses.read_text(encoding="utf-8"))
            add("licence manifest covers all assets", bool(lic.get("assets")) and all(a.get("license") for a in lic["assets"]),
                f"{len(lic.get('assets', []))} assets")
        except (OSError, json.JSONDecodeError) as exc:
            add("licence manifest", False, str(exc))
    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "duration": dur, "checks": checks}
