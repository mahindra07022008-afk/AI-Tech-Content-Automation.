"""MoneyPrinterTurbo render engine wrapper (primary) + explicit FFmpeg fallback."""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

from .errors import AgentError, Category, ErrorLog, retry_call


def _mpt_task_id(job_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"telugu-tech/{job_id}"))


def render_with_mpt(cfg, *, job_id: str, material_mp4: Path, audio_wav: Path, script_text: str, kind: str,
                    out_mp4: Path, log=print) -> dict:
    """Let MoneyPrinterTurbo assemble the final video from our scene-timed material + mixed audio.

    Material is one continuous clip whose length equals the narration, sequential concat and no MPT
    transitions, so MPT preserves frame timing (verified: frame diff ≈ encoding noise only).
    """
    mpt = cfg.mpt_home
    py = cfg.mpt_python
    if not py.is_file():
        raise AgentError(f"MoneyPrinterTurbo not installed at {mpt}", Category.DEPENDENCY, fix_hint="telugu-tech setup")
    task_id = _mpt_task_id(job_id)
    aspect = "9:16" if kind == "short" else "16:9"
    cmd = [str(py), "cli.py",
           "--video-script", script_text[:4000],
           "--video-language", "te-IN",
           "--video-source", "local", "--video-materials", str(material_mp4.resolve()),
           "--video-concat-mode", "sequential", "--video-transition-mode", "none",
           "--video-clip-duration", str(int(cfg.get("video", kind, "max_seconds")) + 30),
           "--video-aspect", aspect, "--video-fit-mode", "cover",
           "--custom-audio-file", str(audio_wav.resolve()),
           "--bgm-type", "none", "--no-subtitle-enabled",
           "--n-threads", str(cfg.get("video", "render_workers", default=4)),
           "--task-id", task_id]

    def once():
        r = subprocess.run(cmd, cwd=mpt, capture_output=True, text=True,
                           timeout=cfg.get("engine", "render_timeout_seconds", default=1800))
        result_line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("{") and '"task_id"' in l), None)
        if r.returncode != 0 or not result_line:
            tail = (r.stderr or r.stdout)[-600:]
            raise AgentError(f"MoneyPrinterTurbo render failed (exit {r.returncode}): {tail}", Category.RENDER)
        res = json.loads(result_line)
        videos = (res.get("result") or {}).get("videos") or []
        if not videos or not Path(videos[0]).is_file():
            raise AgentError("MoneyPrinterTurbo reported no video file", Category.RENDER)
        return res

    res = retry_call(once, max_attempts=cfg.get("retry", "max_attempts", default=3),
                     on_retry=lambda a, e, d: log(f"  MPT attempt {a} failed, retrying in {d:.0f}s: {str(e)[:120]}"))
    src = Path(res["result"]["videos"][0])
    shutil.copy2(src, out_mp4)
    return {"engine": "MoneyPrinterTurbo", "mpt_task_id": task_id, "mpt_output": str(src)}


def render_with_ffmpeg(*, material_mp4: Path, audio_wav: Path, out_mp4: Path) -> dict:
    """Fallback mux (used only if MPT fails 3x and engine.ffmpeg_fallback is true; always logged)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(material_mp4), "-i", str(audio_wav), "-map", "0:v:0",
                        "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest",
                        "-movflags", "+faststart", str(out_mp4)], capture_output=True, text=True)
    if r.returncode != 0:
        raise AgentError(f"ffmpeg fallback mux failed: {r.stderr[-300:]}", Category.RENDER)
    return {"engine": "ffmpeg-fallback"}


def render_final(cfg, *, job_id: str, material_mp4: Path, audio_wav: Path, script_text: str, kind: str, out_mp4: Path,
                 errlog: ErrorLog | None = None, log=print) -> dict:
    fps = int(cfg.get("video", kind, "fps", default=30))
    if fps != 30:
        # MoneyPrinterTurbo writes at a fixed 30 fps (app/services/video.py: fps = 30); a 60 fps master
        # would be resampled, so high-frame-rate renders are muxed directly with FFmpeg instead.
        log(f"  {fps} fps master: MoneyPrinterTurbo is 30 fps-only → direct FFmpeg mux (no re-encode of video)")
        return {**render_with_ffmpeg(material_mp4=material_mp4, audio_wav=audio_wav, out_mp4=out_mp4),
                "reason": "MoneyPrinterTurbo outputs 30 fps only"}
    try:
        return render_with_mpt(cfg, job_id=job_id, material_mp4=material_mp4, audio_wav=audio_wav,
                               script_text=script_text, kind=kind, out_mp4=out_mp4, log=log)
    except AgentError as exc:
        if exc.category is not Category.RENDER or not cfg.get("engine", "ffmpeg_fallback", default=True):
            raise
        res = render_with_ffmpeg(material_mp4=material_mp4, audio_wav=audio_wav, out_mp4=out_mp4)
        if errlog:
            errlog.record(stage="render", exc=exc, job_id=job_id, repaired=True,
                          repair_action="MoneyPrinterTurbo failed 3x; used FFmpeg fallback mux")
        log("  ⚠ MoneyPrinterTurbo failed; used FFmpeg fallback (logged).")
        return res
