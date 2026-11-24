"""End-to-end job pipeline with per-stage checkpoints (resumable) and bounded self-repair."""
from __future__ import annotations

import json
import re
import shutil
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

from . import audio, engine, quality, seo, storyboard as sbmod, subtitles, thumbnail, tts, visuals
from .db import DB, sha256_file
from .errors import AgentError, Category, ErrorLog

# Max global speaking-rate change the auto-repair may apply (beyond this the script must change).
MAX_RATE_REPAIR = 10.0
STAGES = ["storyboard", "voice", "audio", "visuals", "render", "subtitles", "thumbnail", "seo", "licenses", "quality"]


def new_job_id(kind: str, topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:32] or "topic"
    return f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{kind}-{slug}"


class Job:
    def __init__(self, cfg, db: DB, job_id: str, kind: str, topic: str, log=print):
        self.cfg, self.db, self.job_id, self.kind, self.topic, self.log = cfg, db, job_id, kind, topic, log
        self.dir = cfg.jobs_dir / job_id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "final").mkdir(exist_ok=True)
        self.errlog = ErrorLog(cfg.logs_dir / "errors.jsonl")
        db.create_job(job_id, kind, topic)

    def path(self, name: str) -> Path:
        return self.dir / name

    def done(self, stage: str) -> bool:
        return bool(self.db.checkpoint(self.job_id).get(stage, {}).get("done"))

    def mark(self, stage: str, **data):
        self.db.mark_stage(self.job_id, stage, data)
        (self.dir / "checkpoint.json").write_text(json.dumps(self.db.checkpoint(self.job_id), ensure_ascii=False, indent=2),
                                                  encoding="utf-8")


def run(cfg, db: DB, *, kind: str, topic: str, storyboard_path: str | None = None, sources: list[dict] | None = None,
        job_id: str | None = None, voice: str | None = None, redo_from: str | None = None, log=print) -> dict:
    job_id = job_id or new_job_id(kind, topic)
    job = Job(cfg, db, job_id, kind, topic, log)
    if redo_from:
        if redo_from not in STAGES:
            raise AgentError(f"--redo-from must be one of {STAGES}", Category.CONFIG, retryable=False)
        db.clear_stages(job_id, STAGES[STAGES.index(redo_from):])
        log(f"redoing stages from '{redo_from}' (earlier checkpoints reused)")
    t0 = time.time()
    try:
        result = _run(job, storyboard_path, sources or [], voice)
        db.set_job_status(job_id, "completed", "quality")
        result["elapsed_seconds"] = round(time.time() - t0, 1)
        (job.dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    except AgentError as exc:
        job.errlog.record(stage=db.get_job(job_id)["stage"] or "start", exc=exc, job_id=job_id)
        db.set_job_status(job_id, "blocked" if exc.is_blocker else "failed")
        raise
    except Exception as exc:
        job.errlog.record(stage=db.get_job(job_id)["stage"] or "start", exc=exc, job_id=job_id)
        db.set_job_status(job_id, "failed")
        raise


def _run(job: Job, storyboard_path: str | None, sources: list[dict], voice: str | None) -> dict:
    cfg, log, kind = job.cfg, job.log, job.kind
    sb_file = job.path("storyboard.json")

    # 1 ── storyboard
    if not (job.done("storyboard") and sb_file.is_file()):
        log("① storyboard")
        if storyboard_path:
            sb = sbmod.load(storyboard_path)
        else:
            sb = sbmod.generate(cfg, job.topic, kind, sources, log=log)
        sb["kind"] = kind
        sbmod.assert_valid(sb, cfg)
        sbmod.save(sb, sb_file)
        job.mark("storyboard", scenes=len(sb["scenes"]))
    sb = sbmod.load(sb_file)

    # 2 ── voice (per scene) with automatic duration repair via speaking rate
    vdir = job.path("voice")
    lo, hi = cfg.get("video", kind, "min_seconds"), cfg.get("video", kind, "max_seconds")
    gap = cfg.get("voice", "scene_gap_seconds", default=0.3)
    adjust = float(job.db.checkpoint(job.job_id).get("voice", {}).get("rate_adjust", 0.0))
    voice = voice or cfg.get("voice", "primary")
    if not job.done("voice"):
        log(f"② voice-over ({voice})")
        for attempt in range(3):
            scene_audio = tts.voice_scenes(sb, vdir, cfg, voice=voice, global_rate_adjust=adjust, log=log)
            est = sum(_trimmed(a) for a in scene_audio) + gap * (len(scene_audio) - 1) + 0.25 + 0.9
            if lo <= est <= hi:
                break
            # aim just inside the limit (smallest change keeps delivery natural)
            target = min(max(est, lo + 2.5), hi - 2.5)
            need = (est / target - 1) * 100  # % faster (+) or slower (-)
            new_adjust = max(-MAX_RATE_REPAIR, min(MAX_RATE_REPAIR, adjust + need))
            log(f"  duration {est:.1f}s outside {lo}-{hi}s → rate adjust {adjust:+.0f}% → {new_adjust:+.0f}%")
            if abs(new_adjust - adjust) < 0.5:
                break
            job.errlog.record(stage="voice", exc=AgentError(f"narration {est:.1f}s outside {lo}-{hi}s", Category.SYNC),
                              job_id=job.job_id, repaired=True, repair_action=f"speaking rate adjusted to {new_adjust:+.0f}%")
            adjust = new_adjust
        if not lo <= est <= hi:
            raise AgentError(f"narration is {est:.1f}s even after rate repair (limit ±{MAX_RATE_REPAIR:.0f}% to keep delivery natural); script must be "
                             f"{'shortened' if est > hi else 'lengthened'}", Category.QUALITY, retryable=False)
        job.mark("voice", voice=voice, rate_adjust=adjust, estimated_seconds=round(est, 2))
    scene_audio = tts.voice_scenes(sb, vdir, cfg, voice=voice, global_rate_adjust=adjust, log=lambda *_: None)

    # 3 ── audio timeline, original music, sfx, mix
    timings_file = job.path("timings.json")
    final_audio = job.path("final_audio.wav")
    if not (job.done("audio") and final_audio.is_file() and timings_file.is_file()):
        log("③ audio: narration timeline + original music + SFX + ducking + loudnorm")
        narr = job.path("narration.wav")
        timings = audio.build_narration(scene_audio, narr, gap=gap)
        total = timings[-1]["end"]
        music = job.path("music.wav")
        mood = "uplifting" if kind == "short" else "curious"
        music_meta = audio.synth_music(total, music, seed=zlib.crc32(job.job_id.encode()) % 1000, mood=mood)
        events = [(tm["start"], "whoosh") for tm in timings[1:]]
        events += [(tm["start"] + 1.2, "ding") for sc, tm in zip(sb["scenes"], timings) if sc["visual"]["type"] == "stat"]
        events += [(tm["start"] + 0.1, "pop") for sc, tm in zip(sb["scenes"], timings)
                   if sc["visual"]["type"] in ("title", "outro")]
        sfx = job.path("sfx.wav")
        if cfg.get("music", "sfx", default=True):
            audio.build_sfx_track(events, total, sfx)
        mixed = audio.mix(narr, music, sfx if sfx.is_file() else None, final_audio,
                          music_db=cfg.get("music", "bgm_db_under_voice", default=-20),
                          ducking=cfg.get("music", "ducking", default=True),
                          target_lufs=cfg.get("voice", "target_lufs", default=-14.0),
                          true_peak=cfg.get("voice", "true_peak_db", default=-1.5))
        timings_file.write_text(json.dumps(timings, indent=1), encoding="utf-8")
        (job.path("music.json")).write_text(json.dumps(music_meta, indent=1), encoding="utf-8")
        job.mark("audio", total_seconds=round(total, 3), **{k: v for k, v in mixed.items() if k != "path"})
    timings = json.loads(timings_file.read_text())
    total = timings[-1]["end"]
    (job.path("storyboard.md")).write_text(sbmod.storyboard_markdown(sb, timings), encoding="utf-8")

    th = visuals.theme_from_cfg(cfg, kind)
    # 4 ── visuals
    material = job.path("material.mp4")
    if not (job.done("visuals") and material.is_file()):
        log("④ visuals: motion graphics + kinetic captions")
        visuals.render_video(th, sb, timings, total, material, fps=cfg.get("video", kind, "fps"),
                             workers=cfg.get("video", "render_workers", default=4),
                             transition=cfg.get("video", "transition_seconds", default=0.45),
                             words_per_chunk=cfg.get("captions", "words_per_chunk", default=4),
                             crf=cfg.get("video", "crf", default=20), preset=cfg.get("video", "preset", default="medium"),
                             log=log)
        job.mark("visuals", frames=int(round(total * cfg.get("video", kind, "fps"))))

    # 5 ── final render through MoneyPrinterTurbo
    final_mp4 = job.path("final/video.mp4")
    if not (job.done("render") and final_mp4.is_file()):
        log("⑤ render: MoneyPrinterTurbo final assembly")
        script_text = " ".join(s["narration_te"] for s in sb["scenes"])
        info = engine.render_final(cfg, job_id=job.job_id, material_mp4=material, audio_wav=final_audio,
                                   script_text=script_text, kind=kind, out_mp4=final_mp4, errlog=job.errlog, log=log)
        job.mark("render", **info)

    # 6 ── subtitles
    srt_te, srt_ro = job.path("final/subtitles.te.srt"), job.path("final/subtitles.te-Latn.srt")
    if not job.done("subtitles"):
        log("⑥ subtitles: Telugu Unicode + Roman Telugu SRT")
        subtitles.write_srt(subtitles.telugu_cues(sb, timings), srt_te)
        subtitles.write_srt(subtitles.roman_cues(sb, timings, cfg.get("captions", "words_per_chunk", default=4)), srt_ro)
        job.mark("subtitles")

    # 7 ── thumbnail + cover
    thumb, cover = job.path("final/thumbnail.jpg"), job.path("final/cover_short.png")
    if not job.done("thumbnail"):
        log("⑦ thumbnail + Shorts cover")
        thumbnail.make_thumbnail(visuals.theme_from_cfg(cfg, "long"), sb, thumb)
        thumbnail.make_cover(visuals.theme_from_cfg(cfg, "short"), sb, cover)
        job.mark("thumbnail")

    # 8 ── seo
    if not job.done("seo"):
        log("⑧ SEO metadata")
        meta = seo.build(sb, timings, cfg, kind)
        seo.save(meta, job.path("final"))
        job.mark("seo", warnings=meta["warnings"])
    meta = json.loads(job.path("final/youtube_metadata.json").read_text(encoding="utf-8"))

    # 9 ── licence / source manifest
    lic = job.path("final/licenses.json")
    if not job.done("licenses"):
        music_meta = json.loads(job.path("music.json").read_text())
        manifest = {
            "job_id": job.job_id,
            "assets": [
                {"asset": "visuals (all frames, icons, diagrams, typography)", "source": "telugu_tech.visuals (generated)",
                 "license": "Original work, owned by channel"},
                {"asset": "background music", "source": "telugu_tech.audio.synth_music", "license": music_meta["license"]},
                {"asset": "sound effects", "source": "telugu_tech.audio (synthesised)", "license": "Original work, owned by channel"},
                {"asset": "voice-over", "source": f"Microsoft Edge TTS ({voice})",
                 "license": "Synthetic neural TTS voice (not a clone of a real person); disclosed as AI voice"},
                {"asset": "fonts", "source": "Noto Sans / Noto Sans Telugu (Google, Ubuntu fonts-noto-core)",
                 "license": "SIL Open Font License 1.1"},
                {"asset": "render engine", "source": "MoneyPrinterTurbo (harry0703)", "license": "MIT"},
            ],
            "sources": sb.get("sources", []),
            "facts": sb.get("facts", []),
            "copyright_review": "No third-party footage, music, logos, or creator content used.",
        }
        lic.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        job.mark("licenses")

    # 10 ── quality validation on the real file
    log("⑩ quality validation")
    qa = quality.validate_video(final_mp4, cfg, kind, sb=sb, timings=timings, theme=th, srt_files=[srt_te, srt_ro],
                                licenses=lic)
    if meta.get("warnings"):
        qa["checks"].append({"check": "SEO honesty (no clickbait, 3 titles ≤100)", "passed": False,
                             "detail": "; ".join(meta["warnings"])})
        qa["passed"] = False
    else:
        qa["checks"].append({"check": "SEO honesty (no clickbait, 3 titles ≤100)", "passed": True, "detail": "ok"})
    job.path("final/quality_report.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    job.mark("quality", passed=qa["passed"])
    sha = sha256_file(final_mp4)
    job.db.add_video(job.job_id, kind, str(final_mp4), sha, qa["duration"], qa["passed"], {"title": meta["selected_title"]})
    shutil.copy2(sb_file, job.path("final/storyboard.json"))
    shutil.copy2(job.path("storyboard.md"), job.path("final/storyboard.md"))
    if not qa["passed"]:
        failed = [c for c in qa["checks"] if not c["passed"]]
        job.errlog.record(stage="quality", exc=AgentError(f"quality checks failed: {failed}", Category.QUALITY),
                          job_id=job.job_id)
    return {"job_id": job.job_id, "video": str(final_mp4), "sha256": sha, "duration": qa["duration"],
            "quality_passed": qa["passed"], "thumbnail": str(thumb), "cover": str(cover),
            "subtitles": [str(srt_te), str(srt_ro)], "metadata": str(job.path("final/youtube_metadata.md")),
            "storyboard": str(job.path("final/storyboard.md")), "quality_report": str(job.path("final/quality_report.json"))}


def _trimmed(sa: dict) -> float:
    # trimmed speech length ≈ duration minus edge silence (edge-tts adds ~0.1-0.2s)
    return max(0.0, sa["duration"] - 0.15)
