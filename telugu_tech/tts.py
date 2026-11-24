"""Telugu voice-over with Edge TTS (free), per-scene synthesis for exact scene/narration sync."""
from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import subprocess
from pathlib import Path

from .errors import AgentError, Category, retry_call

SUPPORTED_TELUGU = {"te-IN-MohanNeural", "te-IN-ShrutiNeural"}


def _ssl_context() -> ssl.SSLContext:
    """Honour SSL_CERT_FILE / REQUESTS_CA_BUNDLE (corporate or sandbox proxies) while keeping
    verification ON. edge-tts otherwise pins certifi's bundle only."""
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        path = os.environ.get(var)
        if path and Path(path).is_file():
            return ssl.create_default_context(cafile=path)
    import certifi
    return ssl.create_default_context(cafile=certifi.where())


def _patch_edge_tts():
    import edge_tts.communicate as comm
    comm._SSL_CTX = _ssl_context()
    import edge_tts
    return edge_tts


def list_telugu_voices() -> list[dict]:
    edge_tts = _patch_edge_tts()

    async def go():
        return await edge_tts.list_voices()
    try:
        voices = asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        raise AgentError(f"edge-tts voice list failed: {exc}", Category.NETWORK) from exc
    return [v for v in voices if v.get("Locale") == "te-IN"]


def verify_voices(wanted: list[str]) -> dict[str, bool]:
    names = {v["ShortName"] for v in list_telugu_voices()}
    return {w: w in names for w in wanted}


def clean_for_speech(text: str) -> str:
    """Light normalisation so English terms are read clearly."""
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("&", " and ")
    # "AI" read letter-by-letter
    text = re.sub(r"\bAI\b", "A.I.", text)
    return text


def synthesize(text: str, out_mp3: Path, voice: str, rate: str = "+0%", pitch: str = "+0Hz",
               max_attempts: int = 3) -> dict:
    """Synthesize one line; returns {'path', 'duration', 'boundaries'}. Bounded retries."""
    if not voice.startswith("te-IN-"):
        raise AgentError(f"refusing non-Telugu voice {voice}", Category.CONFIG, retryable=False)
    edge_tts = _patch_edge_tts()
    out_mp3.parent.mkdir(parents=True, exist_ok=True)

    async def go():
        comm = edge_tts.Communicate(clean_for_speech(text), voice, rate=rate, pitch=pitch,
                                    boundary="SentenceBoundary")
        boundaries = []
        with open(out_mp3, "wb") as fh:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    fh.write(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    boundaries.append({"offset": chunk["offset"] / 1e7, "duration": chunk["duration"] / 1e7,
                                       "text": chunk["text"]})
        return boundaries

    def once():
        try:
            b = asyncio.run(go())
        except Exception as exc:  # noqa: BLE001
            raise AgentError(f"edge-tts failed for voice {voice}: {type(exc).__name__}: {exc}", Category.VOICE) from exc
        if not out_mp3.is_file() or out_mp3.stat().st_size < 1000:
            raise AgentError("edge-tts returned no audio", Category.VOICE)
        return b

    boundaries = retry_call(once, max_attempts=max_attempts)
    return {"path": str(out_mp3), "duration": probe_duration(out_mp3), "boundaries": boundaries}


def probe_duration(path: Path | str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError as exc:
        raise AgentError(f"ffprobe could not read {path}", Category.SYNC) from exc


def _pct(rate: str) -> float:
    m = re.match(r"([+-]?\d+)%", rate.strip())
    return float(m.group(1)) if m else 0.0


def combine_rate(section_rate: str, global_adjust: float) -> str:
    total = max(-30.0, min(30.0, _pct(section_rate) + global_adjust))
    return f"{int(round(total)):+d}%"


def voice_scenes(storyboard: dict, out_dir: Path, cfg, voice: str | None = None, global_rate_adjust: float = 0.0,
                 log=print) -> list[dict]:
    """Synthesize every scene. Returns per-scene results (cached by text+voice+prosody)."""
    voice = voice or cfg.get("voice", "primary")
    prosody = cfg.get("voice", "prosody", default={}) or {}
    results = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, sc in enumerate(storyboard["scenes"]):
        p = prosody.get(sc["section"], {})
        rate = combine_rate(p.get("rate", cfg.get("voice", "rate", default="+0%")), global_rate_adjust)
        pitch = p.get("pitch", "+0Hz")
        key = json.dumps([sc["narration_te"], voice, rate, pitch], ensure_ascii=False)
        mp3 = out_dir / f"scene_{i + 1:03d}.mp3"
        meta = out_dir / f"scene_{i + 1:03d}.json"
        if mp3.is_file() and meta.is_file():
            cached = json.loads(meta.read_text(encoding="utf-8"))
            if cached.get("key") == key:
                results.append(cached)
                continue
        r = synthesize(sc["narration_te"], mp3, voice, rate=rate, pitch=pitch)
        r.update({"key": key, "rate": rate, "pitch": pitch, "voice": voice})
        meta.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        log(f"  voice scene {i + 1}/{len(storyboard['scenes'])}: {r['duration']:.2f}s ({rate}, {pitch})")
        results.append(r)
    return results
