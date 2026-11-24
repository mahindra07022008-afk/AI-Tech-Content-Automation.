"""Audio: original procedural music & SFX, narration timeline, ducking, loudness normalisation.

All music/SFX are synthesised here from code (no samples), so the channel owns them outright —
no copyright claims, no third-party licence. A licence manifest entry is written for each file.
"""
from __future__ import annotations

import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from .errors import AgentError, Category

SR = 48000


# ------------------------------------------------------------------ io helpers
def decode(path: str | Path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 via ffmpeg."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise AgentError(f"ffmpeg decode failed for {path}: {r.stderr[-300:]!r}", Category.SYNC)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: str | Path, data: np.ndarray, sr: int = SR) -> None:
    data = np.clip(data, -1.0, 1.0)
    if data.ndim == 1:
        data = data[:, None]
    pcm = (data * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------ narration timeline
def build_narration(scene_audio: list[dict], out_wav: Path, gap: float, lead_in: float = 0.25,
                    tail: float = 0.9, beat: float | None = None, max_wait: float = 0.7) -> list[dict]:
    """Concatenate scene clips with gaps; returns timings [{start,end,speech_start,speech_end,trim}] per scene.

    Scene i visually spans [start_i, start_{i+1}) so visuals cover the gap after its line.
    With ``beat`` (seconds), every scene start is pushed to the next beat of the music grid
    (waiting at most ``max_wait`` extra), so cuts/transitions land on the beat.
    """
    pieces, timings = [np.zeros(int(lead_in * SR), np.float32)], []
    t = lead_in
    for i, sa in enumerate(scene_audio):
        raw = decode(sa["path"])
        clip, trim = _trim_silence(raw, return_offset=True)
        dur = len(clip) / SR
        start = t if i else 0.0  # first scene starts at 0 (covers lead-in)
        pieces.append(clip)
        t += dur
        speech_start = t - dur
        g = gap if i < len(scene_audio) - 1 else tail
        if beat and i < len(scene_audio) - 1:
            target = t + g
            aligned = np.ceil(target / beat - 1e-6) * beat
            if aligned - target <= max_wait:
                g = aligned - t
        pieces.append(np.zeros(int(round(g * SR)), np.float32))
        t = (sum(len(x) for x in pieces)) / SR
        timings.append({"start": round(start, 3), "speech_start": round(speech_start, 3),
                        "speech_end": round(speech_start + dur, 3), "end": round(t, 3), "trim": round(trim, 4)})
    write_wav(out_wav, np.concatenate(pieces))
    return timings


def _trim_silence(x: np.ndarray, thresh: float = 0.008, pad: float = 0.04, return_offset: bool = False):
    idx = np.where(np.abs(x) > thresh)[0]
    if not len(idx):
        return (x, 0.0) if return_offset else x
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(x), idx[-1] + int(pad * SR))
    return (x[a:b], a / SR) if return_offset else x[a:b]


# ------------------------------------------------------------------ music synthesis
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _chord(root: str, minor: bool, octave: int = 4) -> list[int]:
    r = 12 * (octave + 1) + NOTE[root]
    return [r, r + (3 if minor else 4), r + 7, r + 12]


def _env(n: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n, np.float32)
    a, r = min(n, int(attack * SR)), min(n, int(release * SR))
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    # FFT brick-ish lowpass with soft roll-off (fast, vectorised).
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(spec, n=len(x)).astype(np.float32)


def synth_music(seconds: float, out_wav: Path, seed: int = 7, bpm: float = 96.0, mood: str = "curious") -> dict:
    """Original ambient-tech bed: pads + bass + soft pluck arpeggio + light kick/hat. Loops seamlessly."""
    rng = np.random.default_rng(seed)
    progressions = {
        "curious": [("A", True), ("F", False), ("C", False), ("G", False)],
        "uplifting": [("C", False), ("G", False), ("A", True), ("F", False)],
        "serious": [("D", True), ("A#", False), ("F", False), ("C", False)],
    }
    prog = progressions.get(mood, progressions["curious"])
    beat = 60.0 / bpm
    bar = 4 * beat
    loop_len = int(bar * len(prog) * 2 * SR)  # 8 bars
    L = np.zeros((loop_len, 2), np.float32)
    t_bar = np.arange(int(bar * SR)) / SR

    for rep in range(2):
        for ci, (root, minor) in enumerate(prog):
            off = int(((rep * len(prog)) + ci) * bar * SR)
            notes = _chord(root, minor, 3)
            # pad: detuned additive saw (6 harmonics), stereo spread
            pad = np.zeros((len(t_bar), 2), np.float32)
            for k, m in enumerate(notes[:3]):
                for side, det in ((0, -0.08), (1, 0.08)):
                    hz = midi_hz(m + det)
                    wave_ = sum(np.sin(2 * np.pi * hz * h * t_bar) / h for h in range(1, 7))
                    pad[:, side] += 0.05 * wave_.astype(np.float32)
            pad *= _env(len(t_bar), 0.6, 0.6)[:, None]
            pad[:, 0] = _lowpass(pad[:, 0], 1400)
            pad[:, 1] = _lowpass(pad[:, 1], 1400)
            L[off:off + len(t_bar)] += pad
            # bass on beats 1 and 3
            for b in (0, 2):
                n = int(beat * 1.8 * SR)
                tb = np.arange(n) / SR
                bass = 0.16 * np.sin(2 * np.pi * midi_hz(notes[0] - 12) * tb) * np.exp(-tb * 2.2)
                s = off + int(b * beat * SR)
                L[s:s + n] += bass[:, None].astype(np.float32)
            # pluck arpeggio, 8th notes, gentle random pattern
            arp = notes + [notes[1] + 12]
            for e in range(8):
                if rng.random() < 0.25:
                    continue
                n = int(beat * 0.5 * SR)
                tb = np.arange(n) / SR
                hz = midi_hz(arp[rng.integers(0, len(arp))] + 12)
                tri = 2 * np.abs(2 * ((hz * tb) % 1) - 1) - 1
                pl = 0.045 * tri * np.exp(-tb * 9)
                s = off + int(e * beat * 0.5 * SR)
                pan = 0.3 + 0.4 * rng.random()
                L[s:s + n, 0] += (pl * (1 - pan)).astype(np.float32)
                L[s:s + n, 1] += (pl * pan).astype(np.float32)
            # kick on 1 & 3, hat on off-beats
            for b in range(4):
                s = off + int(b * beat * SR)
                if b in (0, 2):
                    n = int(0.25 * SR)
                    tb = np.arange(n) / SR
                    f = 45 + 75 * np.exp(-tb * 30)
                    kick = 0.22 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tb * 14)
                    L[s:s + n] += kick[:, None].astype(np.float32)
                n = int(0.05 * SR)
                hs = s + int(beat * 0.5 * SR)
                hat = rng.standard_normal(n).astype(np.float32)
                hat = (hat - np.convolve(hat, np.ones(4) / 4, "same")) * 0.03 * np.exp(-np.arange(n) / SR * 80)
                L[hs:hs + n] += hat[:, None]

    total = int((seconds + 1.0) * SR)
    reps = int(np.ceil(total / loop_len))
    out = np.tile(L, (reps, 1))[:total]
    fade_in, fade_out = int(1.5 * SR), int(2.5 * SR)
    out[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    out[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    out /= max(1e-6, np.abs(out).max()) / 0.89
    write_wav(out_wav, out)
    return {"path": str(out_wav), "seconds": seconds, "bpm": bpm, "mood": mood, "seed": seed,
            "license": "Original procedural composition generated by telugu_tech.audio (owned by channel; no third-party material)"}


# ------------------------------------------------------------------ sfx
def sfx_whoosh(dur: float = 0.55, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    out = np.zeros(n, np.float32)
    y = 0.0
    for i in range(n):  # time-varying one-pole lowpass = rising sweep
        p = i / n
        a = 0.02 + 0.5 * np.sin(np.pi * p) ** 2
        y += a * (noise[i] - y)
        out[i] = y
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 2
    return (out * env * 0.5).astype(np.float32)


def sfx_pop(freq: float = 880.0) -> np.ndarray:
    n = int(0.18 * SR)
    t = np.arange(n) / SR
    return (0.35 * np.sin(2 * np.pi * freq * t * (1 + 0.5 * np.exp(-t * 40))) * np.exp(-t * 28)).astype(np.float32)


def sfx_ding() -> np.ndarray:
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    return (0.25 * (np.sin(2 * np.pi * 1318.5 * t) + 0.5 * np.sin(2 * np.pi * 1975.5 * t)) * np.exp(-t * 5)).astype(np.float32)


def sfx_impact() -> np.ndarray:
    """Cinematic low boom: pitched-down sine sweep + noise thump."""
    n = int(1.4 * SR)
    t = np.arange(n) / SR
    f = 38 + 70 * np.exp(-t * 9)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.6)
    rng = np.random.default_rng(5)
    thump = _lowpass(rng.standard_normal(n).astype(np.float32), 300) * np.exp(-t * 18)
    return (0.55 * body + 0.6 * thump).astype(np.float32)


def sfx_riser(dur: float = 1.6) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(9)
    noise = rng.standard_normal(n).astype(np.float32)
    swept = np.zeros(n, np.float32)
    y = 0.0
    for i in range(n):  # rising one-pole lowpass
        a = 0.01 + 0.35 * (i / n) ** 2
        y += a * (noise[i] - y)
        swept[i] = y
    tone = np.sin(2 * np.pi * np.cumsum(200 + 900 * (t / dur) ** 2) / SR) * 0.15
    env = (t / dur) ** 2
    return ((swept * 0.6 + tone) * env * 0.6).astype(np.float32)


def sfx_glitch(seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(0.32 * SR)
    out = np.zeros(n, np.float32)
    pos = 0
    while pos < n:
        seg = int(rng.integers(400, 2400))
        f = rng.choice([220, 440, 880, 1760, 3520])
        t = np.arange(min(seg, n - pos)) / SR
        sq = np.sign(np.sin(2 * np.pi * f * t)) * 0.12 if rng.random() < 0.6 else rng.standard_normal(len(t)) * 0.1
        out[pos:pos + len(t)] = sq
        pos += seg + int(rng.integers(0, 600))
    return out


def sfx_typing(dur: float = 1.5, seed: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    t = 0.0
    while t < dur - 0.05:
        k = int(t * SR)
        m = int(0.018 * SR)
        click = rng.standard_normal(m).astype(np.float32) * np.exp(-np.arange(m) / SR * 400) * 0.25
        click = click - np.convolve(click, np.ones(6) / 6, "same")
        out[k:k + m] += click[: n - k]
        t += 0.06 + rng.random() * 0.09
    return out


def sfx_shimmer() -> np.ndarray:
    n = int(1.1 * SR)
    t = np.arange(n) / SR
    out = sum(np.sin(2 * np.pi * f * t + p) * np.exp(-t * d) for f, p, d in
              ((2637, 0, 4), (3136, 1, 5), (3951, 2, 6), (5274, 3, 7))) * 0.06
    return (out * np.minimum(1, t * 30)).astype(np.float32)


SFX_LIBRARY = {
    # name: (generator, description) — all synthesised here, owned by the channel
    "whoosh": "filtered-noise swoosh for transitions",
    "pop": "short pitched pop for element reveals",
    "ding": "bell for stats/numbers",
    "impact": "cinematic low boom for hooks/turning points",
    "riser": "noise+tone riser building into a turning point",
    "glitch": "digital stutter for glitch transitions",
    "typing": "keyboard clicks for code/chat UIs",
    "shimmer": "high sparkle for glow reveals",
}


def build_sfx_track(events: list[tuple[float, str]], seconds: float, out_wav: Path) -> None:
    track = np.zeros(int((seconds + 2) * SR), np.float32)
    cache = {"whoosh": sfx_whoosh(), "pop": sfx_pop(), "ding": sfx_ding(), "impact": sfx_impact(),
             "riser": sfx_riser(), "glitch": sfx_glitch(), "typing": sfx_typing(), "shimmer": sfx_shimmer()}
    for at, kind in events:
        clip = cache[kind]
        lead = len(clip) // 2 if kind == "whoosh" else len(clip) if kind == "riser" else 0  # riser ends ON the hit
        s = max(0, int(at * SR) - lead)
        e = min(len(track), s + len(clip))
        track[s:e] += clip[: e - s]
    write_wav(out_wav, track[: int(seconds * SR) + SR // 2])


def shape_music(music_wav: Path, *, intro_sweep: float = 2.5, dropouts: list[float] | None = None,
                beat: float = 0.6) -> None:
    """Cinematic arrangement on top of the synthesised bed: low-pass sweep opening the intro and
    one-beat drop-outs before big moments (the impact SFX then lands in the space)."""
    import wave as _w
    with _w.open(str(music_wav)) as w:
        ch, n = w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32).reshape(-1, ch) / 32768.0
    out = data.copy()
    k = int(intro_sweep * SR)
    if k > 0:
        for c in range(ch):
            lp = _lowpass(data[:k, c], 500)
            mix = np.linspace(1, 0, k) ** 1.5
            out[:k, c] = lp * mix + data[:k, c] * (1 - mix)
    for d in dropouts or []:
        a, b = int(max(0, d - beat) * SR), int(d * SR)
        if b > a:
            env = np.ones(b - a, np.float32)
            r = min(len(env), int(0.08 * SR))
            env[:] = 0.12
            env[:r] = np.linspace(1, 0.12, r)
            out[a:b] *= env[:, None]
    write_wav(music_wav, out)


# ------------------------------------------------------------------ mixing
def measure_loudness(path: str | Path) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        raise AgentError("loudness measurement failed", Category.SYNC)
    return json.loads(m.group(0))


def mix(voice_wav: Path, music_wav: Path | None, sfx_wav: Path | None, out_wav: Path, *, music_db: float = -20,
        ducking: bool = True, target_lufs: float = -14.0, true_peak: float = -1.5) -> dict:
    """Voice clean-up + ducked music + SFX, then two-pass loudnorm. Output 48 kHz stereo WAV."""
    inputs = ["-i", str(voice_wav)]
    chains = ["[0:a]highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=5:release=90:makeup=2,"
              "aformat=channel_layouts=stereo,asplit=2[v][vsc]"]
    mixes = ["[v]"]
    idx = 1
    if music_wav:
        inputs += ["-i", str(music_wav)]
        chains.append(f"[{idx}:a]volume={music_db}dB,aformat=channel_layouts=stereo[m0]")
        if ducking:
            chains.append("[m0][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=450:makeup=1[m]")
        else:
            chains.append("[m0]anull[m]")
            chains[0] = chains[0].replace(",asplit=2[v][vsc]", "[v]")
        mixes.append("[m]")
        idx += 1
    else:
        chains[0] = chains[0].replace(",asplit=2[v][vsc]", "[v]")
    if sfx_wav:
        inputs += ["-i", str(sfx_wav)]
        chains.append(f"[{idx}:a]volume=-9dB,aformat=channel_layouts=stereo[s]")
        mixes.append("[s]")
    chains.append(f"{''.join(mixes)}amix=inputs={len(mixes)}:duration=first:normalize=0[pre]")
    pre = out_wav.with_suffix(".pre.wav")
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains), "-map", "[pre]",
           "-ar", str(SR), str(pre)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise AgentError(f"audio mix failed: {r.stderr[-400:]}", Category.SYNC)
    m = measure_loudness(pre)
    ln = (f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(pre), "-af", f"{ln},aresample={SR}",
                        "-ar", str(SR), str(out_wav)], capture_output=True, text=True)
    if r.returncode != 0:
        raise AgentError(f"loudnorm failed: {r.stderr[-400:]}", Category.SYNC)
    pre.unlink(missing_ok=True)
    final = measure_loudness(out_wav)
    return {"path": str(out_wav), "integrated_lufs": float(final["input_i"]), "true_peak_db": float(final["input_tp"]),
            "lra": float(final["input_lra"])}
