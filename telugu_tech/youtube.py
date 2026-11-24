"""YouTube Data API v3 publishing — official API only, OAuth (installed app), private by default.

Safety gates (all must pass):
  1. quality report passed for this video
  2. no previous successful upload with the same SHA-256 (duplicate guard)
  3. private upload needs --approve-private-upload (explicit human approval per run)
  4. public/unlisted needs publishing.allow_public=true + --approve-public + a prior successful private upload
  5. scheduling (publishAt) needs publishing.allow_scheduling=true + approval
  6. enough daily quota left (tracked locally; default 10,000 units/day, upload ≈ 1,600)
Never asks for passwords/OTP: the human signs in on Google's own consent page.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from .db import DB, sha256_file
from .errors import AgentError, BlockerError, Category, DuplicateError, retry_call

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]  # force-ssl needed for captions upload
CAPTION_COST, THUMB_COST = 400, 50


def _paths(cfg) -> tuple[Path, Path]:
    secrets = cfg.resolve(os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE", "data/secrets/client_secret.json"))
    token = cfg.resolve(os.environ.get("YOUTUBE_TOKEN_FILE", "data/secrets/youtube_token.json"))
    return secrets, token


def auth_status(cfg) -> dict:
    secrets, token = _paths(cfg)
    return {"client_secrets_present": secrets.is_file(), "token_present": token.is_file(),
            "client_secrets_file": str(secrets), "token_file": str(token)}


def authorize(cfg, *, interactive: bool = False):
    """Return authorized credentials, refreshing if needed. Interactive consent only when asked."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise AgentError("google client libraries missing", Category.DEPENDENCY,
                         fix_hint="uv pip install -e '.[youtube]'") from exc
    secrets, token = _paths(cfg)
    creds = None
    if token.is_file():
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            raise BlockerError(f"YouTube token refresh failed: {type(exc).__name__}", Category.AUTH,
                               fix_hint="re-run: telugu-tech publish --auth") from exc
    elif interactive:
        if not secrets.is_file():
            raise BlockerError(f"OAuth client file not found: {secrets}", Category.AUTH,
                               fix_hint="Create a Desktop OAuth client in Google Cloud Console (YouTube Data API v3 "
                                        "enabled) and save the JSON to that path.")
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
        # Binds to 127.0.0.1 only; you complete sign-in on Google's own page.
        creds = flow.run_local_server(host="localhost", bind_addr="127.0.0.1", port=0, open_browser=True)
    else:
        raise BlockerError("YouTube is not authorized yet", Category.AUTH, fix_hint="run: telugu-tech publish --auth")
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(token, stat.S_IRUSR | stat.S_IWUSR)
    return creds


def quota_used_today(db: DB) -> float:
    day = datetime.now(timezone.utc).date().isoformat()
    return sum(r["units"] for r in db.usage_for_day(day) if r["service"] == "youtube")


def build_request(meta: dict, privacy: str, publish_at: str | None, kind: str) -> dict:
    title = meta["selected_title"]
    if kind == "short" and "#shorts" not in (title + meta["description"]).lower():
        meta = {**meta, "description": meta["description"] + "\n#Shorts"}
    status = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": bool(meta.get("made_for_kids", False)),
        "containsSyntheticMedia": bool(meta.get("contains_synthetic_media", True)),
        "embeddable": True,
        "license": "youtube",
    }
    if publish_at:
        status["privacyStatus"] = "private"  # API requirement for scheduled publishing
        status["publishAt"] = publish_at
    return {
        "snippet": {
            "title": title[:100],
            "description": meta["description"][:5000],
            "tags": meta.get("keywords", [])[:30],
            "categoryId": str(meta.get("category_id", "28")),
            "defaultLanguage": meta.get("default_language", "te"),
            "defaultAudioLanguage": meta.get("default_language", "te"),
        },
        "status": status,
    }


def check_gates(cfg, db: DB, job_dir: Path, *, privacy: str, approve_private: bool, approve_public: bool,
                publish_at: str | None) -> tuple[Path, str, dict, dict]:
    video = job_dir / "final" / "video.mp4"
    qa_path = job_dir / "final" / "quality_report.json"
    meta_path = job_dir / "final" / "youtube_metadata.json"
    if not video.is_file() or not meta_path.is_file():
        raise AgentError(f"no finished video in {job_dir}", Category.ASSET)
    qa = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.is_file() else {"passed": False}
    if not qa.get("passed"):
        raise AgentError("quality validation has not passed for this video — refusing to upload", Category.QUALITY,
                         retryable=False)
    sha = sha256_file(video)
    prev = db.upload_for_hash(sha)
    if prev:
        raise DuplicateError(f"already uploaded as https://youtu.be/{prev['youtube_id']} ({prev['privacy']})")
    if privacy not in ("private", "unlisted", "public"):
        raise AgentError("privacy must be private|unlisted|public", Category.CONFIG, retryable=False)
    if privacy == "private" and not approve_private:
        raise BlockerError("private upload needs explicit approval", Category.PERMISSION,
                           fix_hint="re-run with --approve-private-upload after reviewing the preview")
    if privacy in ("public", "unlisted"):
        if not cfg.get("publishing", "allow_public", default=False) or not approve_public:
            raise BlockerError(f"{privacy} publishing is disabled", Category.PERMISSION,
                               fix_hint="set publishing.allow_public: true AND pass --approve-public (after a private test)")
        if not any(u["status"] == "uploaded" for u in db.uploads()):
            raise BlockerError("public publishing requires a successful private test upload first", Category.PERMISSION)
    if publish_at and not cfg.get("publishing", "allow_scheduling", default=False):
        raise BlockerError("scheduled publishing is disabled", Category.PERMISSION,
                           fix_hint="set publishing.allow_scheduling: true after approving")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return video, sha, meta, qa


def upload(cfg, db: DB, job_dir: Path, *, kind: str, privacy: str = "private", approve_private: bool = False,
           approve_public: bool = False, publish_at: str | None = None, dry_run: bool = False, log=print) -> dict:
    video, sha, meta, _ = check_gates(cfg, db, job_dir, privacy=privacy, approve_private=approve_private or dry_run,
                                      approve_public=approve_public, publish_at=publish_at)
    body = build_request(meta, privacy, publish_at, kind)
    srt_te = job_dir / "final" / "subtitles.te.srt"
    thumb = job_dir / "final" / "thumbnail.jpg"
    cost = cfg.get("publishing", "upload_cost_units", default=1600) + (CAPTION_COST if srt_te.is_file() else 0) + \
        (THUMB_COST if kind == "long" and thumb.is_file() else 0)
    limit = cfg.get("publishing", "daily_quota_units", default=10000)
    if dry_run:
        return {"dry_run": True, "request": body, "estimated_quota_units": cost, "sha256": sha}
    if not cfg.get("publishing", "youtube_enabled", default=False):
        raise BlockerError("publishing.youtube_enabled is false", Category.PERMISSION,
                           fix_hint="set publishing.youtube_enabled: true in config/project.yaml once OAuth is set up")
    if quota_used_today(db) + cost > limit:
        raise BlockerError(f"daily YouTube quota would be exceeded ({quota_used_today(db)}+{cost} > {limit})", Category.QUOTA)
    creds = authorize(cfg)
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    def do_upload():
        req = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 << 20, resumable=True))
        resp = None
        try:
            while resp is None:
                status, resp = req.next_chunk()
                if status:
                    log(f"  upload {int(status.progress() * 100)}%")
        except HttpError as exc:
            reason = str(exc)
            code = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", 0)
            if "quota" in reason.lower():
                raise BlockerError(f"YouTube quota: {reason[:200]}", Category.QUOTA) from exc
            if int(code or 0) in (401, 403):
                raise BlockerError(f"YouTube auth/permission: {reason[:200]}", Category.PERMISSION) from exc
            if int(code or 0) >= 500 or int(code or 0) == 429:
                raise AgentError(f"YouTube transient error {code}", Category.UPLOAD) from exc
            raise AgentError(f"YouTube upload rejected: {reason[:200]}", Category.UPLOAD, retryable=False) from exc
        return resp

    try:
        resp = retry_call(do_upload, max_attempts=cfg.get("retry", "max_attempts", default=3))
    except AgentError as exc:
        db.record_upload(sha, job_dir.name, None, privacy, "failed", str(exc)[:300])
        raise
    vid = resp["id"]
    db.record_upload(sha, job_dir.name, vid, body["status"]["privacyStatus"], "uploaded", json.dumps(body["status"]))
    db.add_usage("youtube", cfg.get("publishing", "upload_cost_units", default=1600), 0.0, f"videos.insert {vid}")
    extras = {}
    if srt_te.is_file():
        try:
            yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "te", "name": "తెలుగు"}},
                                 media_body=MediaFileUpload(str(srt_te), mimetype="application/octet-stream")).execute()
            db.add_usage("youtube", CAPTION_COST, 0.0, f"captions.insert {vid}")
            extras["captions"] = "uploaded"
        except Exception as exc:  # noqa: BLE001 - non-fatal, reported
            extras["captions"] = f"failed: {type(exc).__name__}"
    if kind == "long" and thumb.is_file():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
            db.add_usage("youtube", THUMB_COST, 0.0, f"thumbnails.set {vid}")
            extras["thumbnail"] = "set"
        except Exception as exc:  # noqa: BLE001 - needs a verified channel; reported
            extras["thumbnail"] = f"failed: {type(exc).__name__} (custom thumbnails need a verified channel)"
    return {"youtube_id": vid, "url": f"https://youtu.be/{vid}", "privacy": body["status"]["privacyStatus"], **extras}
