"""SRT generation: Telugu Unicode (from narration) and Roman Telugu (from captions)."""
from __future__ import annotations

import re
from pathlib import Path

from .visuals import caption_chunks


def ts(sec: float) -> str:
    sec = max(0.0, sec)
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_telugu(text: str, max_chars: int = 42) -> list[str]:
    """Split narration into subtitle-sized phrases at punctuation, then by length."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?,;:।])\s+", text) if p.strip()]
    out: list[str] = []
    for p in parts:
        while len(p) > max_chars:
            cut = p.rfind(" ", 0, max_chars)
            cut = cut if cut > 10 else max_chars
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def telugu_cues(storyboard: dict, timings: list[dict]) -> list[tuple[float, float, str]]:
    cues = []
    for sc, tm in zip(storyboard["scenes"], timings):
        phrases = _split_telugu(sc["narration_te"])
        total = sum(len(p) for p in phrases) or 1
        t, s0, s1 = tm["speech_start"], tm["speech_start"], tm["speech_end"]
        for p in phrases:
            d = (s1 - s0) * len(p) / total
            cues.append((t, t + d, p))
            t += d
    return cues


def roman_cues(storyboard: dict, timings: list[dict], words_per_chunk: int = 4) -> list[tuple[float, float, str]]:
    return [(c["start"], c["end"], " ".join(c["words"]))
            for sc, tm in zip(storyboard["scenes"], timings) for c in caption_chunks(sc, tm, words_per_chunk)]


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> Path:
    lines = []
    for i, (a, b, text) in enumerate(cues, 1):
        lines += [str(i), f"{ts(a)} --> {ts(b)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    def sec(s: str) -> float:
        h, m, rest = s.split(":")
        s_, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s_) + int(ms) / 1000
    cues = []
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        rows = block.strip().splitlines()
        if len(rows) >= 3 and "-->" in rows[1]:
            a, b = [x.strip() for x in rows[1].split("-->")]
            cues.append((sec(a), sec(b), "\n".join(rows[2:])))
    return cues
