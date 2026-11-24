"""Error classification, redaction, bounded retries and error logging."""
from __future__ import annotations

import functools
import json
import random
import re
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


class Category(str, Enum):
    DEPENDENCY = "missing_dependency"
    CONFIG = "invalid_config"
    NETWORK = "network_failure"
    AUTH = "authentication"
    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    BILLING = "billing"
    POLICY = "policy"
    FONT = "telugu_font"
    VOICE = "voice_generation"
    ASSET = "missing_asset"
    SYNC = "audio_sync"
    RENDER = "video_render"
    UPLOAD = "upload"
    DUPLICATE = "duplicate"
    QUALITY = "quality_validation"
    UNKNOWN = "unknown"


RETRYABLE = {Category.NETWORK, Category.RATE_LIMIT, Category.VOICE, Category.RENDER, Category.UPLOAD}
# Never retried or auto-fixed: must be reported to the human.
BLOCKERS = {Category.AUTH, Category.PERMISSION, Category.QUOTA, Category.BILLING, Category.POLICY}


class AgentError(Exception):
    def __init__(self, message: str, category: Category = Category.UNKNOWN, *,
                 fix_hint: str = "", retryable: bool | None = None):
        super().__init__(message)
        self.category = category
        self.fix_hint = fix_hint
        self.retryable = category in RETRYABLE if retryable is None else retryable

    @property
    def is_blocker(self) -> bool:
        return self.category in BLOCKERS


class BlockerError(AgentError):
    """Requires human action (auth, permission, billing, policy, quota)."""

    def __init__(self, message: str, category: Category = Category.AUTH, *, fix_hint: str = ""):
        super().__init__(message, category, fix_hint=fix_hint, retryable=False)


class DuplicateError(AgentError):
    def __init__(self, message: str):
        super().__init__(message, Category.DUPLICATE, retryable=False)


# ---------------------------------------------------------------- redaction
_REDACT_PATTERNS = [
    (re.compile(r"(?i)(authorization:\s*(?:bearer|token|basic)\s+)[^\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(access_token|refresh_token|client_secret|api_key|apikey|token|password|secret)"
                r"(\"?\s*[:=]\s*\"?)[^\s\"',}]+"), r"\1\2[REDACTED]"),
    (re.compile(r"\bya29\.[0-9A-Za-z_\-]+"), "[REDACTED_GOOGLE_TOKEN]"),
    (re.compile(r"\b1//[0-9A-Za-z_\-]{20,}"), "[REDACTED_REFRESH_TOKEN]"),
    (re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"), "[REDACTED_ANTHROPIC_KEY]"),
]


def redact(text: object) -> str:
    s = str(text)
    for pattern, repl in _REDACT_PATTERNS:
        s = pattern.sub(repl, s)
    return s


# ---------------------------------------------------------------- classification
_CLASSIFIERS: list[tuple[re.Pattern, Category]] = [
    (re.compile(r"(?i)quotaExceeded|dailyLimitExceeded|quota"), Category.QUOTA),
    (re.compile(r"(?i)billing|payment required|\b402\b"), Category.BILLING),
    (re.compile(r"(?i)invalid_grant|unauthori[sz]ed|\b401\b|not logged in|login required|invalid credentials"), Category.AUTH),
    (re.compile(r"(?i)forbidden|\b403\b|permission denied|insufficientPermissions"), Category.PERMISSION),
    (re.compile(r"(?i)rate.?limit|too many requests|\b429\b"), Category.RATE_LIMIT),
    (re.compile(r"(?i)policy|community guidelines|copyright strike"), Category.POLICY),
    (re.compile(r"(?i)timed? ?out|connection (reset|refused|aborted)|temporar|name resolution|"
                r"ClientConnector|ConnectionError|\b50[234]\b|network"), Category.NETWORK),
    (re.compile(r"(?i)no module named|command not found|not installed|No such file or directory: '(ffmpeg|ffprobe|claude)"),
     Category.DEPENDENCY),
    (re.compile(r"(?i)font|glyph"), Category.FONT),
    (re.compile(r"(?i)edge.?tts|NoAudioReceived|voice"), Category.VOICE),
]


def classify(exc: BaseException) -> Category:
    if isinstance(exc, AgentError):
        return exc.category
    if isinstance(exc, (ModuleNotFoundError, ImportError)):
        return Category.DEPENDENCY
    if isinstance(exc, FileNotFoundError):
        return Category.ASSET
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return Category.NETWORK
    msg = f"{type(exc).__name__}: {exc}"
    for pattern, cat in _CLASSIFIERS:
        if pattern.search(msg):
            return cat
    return Category.UNKNOWN


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, AgentError):
        return exc.retryable
    return classify(exc) in RETRYABLE


# ---------------------------------------------------------------- retry
def backoff_delays(max_attempts: int = 3, base: float = 2.0, cap: float = 30.0, jitter: bool = True) -> list[float]:
    """Delays *between* attempts: max_attempts-1 values, exponential, capped."""
    delays = []
    for i in range(max(0, max_attempts - 1)):
        d = min(cap, base * (2 ** i))
        if jitter:
            d = d * (0.75 + random.random() * 0.5)
        delays.append(d)
    return delays


def retry_call(fn: Callable[[], T], *, max_attempts: int = 3, base: float = 2.0, cap: float = 30.0,
               on_retry: Callable[[int, BaseException, float], None] | None = None,
               sleep: Callable[[float], None] = time.sleep) -> T:
    """Run fn with bounded exponential backoff. Max attempts is hard-capped at 3."""
    max_attempts = max(1, min(3, max_attempts))
    delays = backoff_delays(max_attempts, base, cap)
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if isinstance(exc, KeyboardInterrupt) or not is_retryable(exc) or attempt == max_attempts:
                raise
            delay = delays[attempt - 1]
            if on_retry:
                on_retry(attempt, exc, delay)
            sleep(delay)
    raise last  # pragma: no cover


def retrying(**kw):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            return retry_call(lambda: fn(*a, **k), **kw)
        return wrapper
    return deco


# ---------------------------------------------------------------- logging
class ErrorLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, stage: str, exc: BaseException | None = None, message: str = "",
               job_id: str | None = None, repaired: bool = False, repair_action: str = "") -> dict:
        cat = classify(exc) if exc else Category.UNKNOWN
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "job_id": job_id,
            "stage": stage,
            "category": cat.value,
            "blocker": cat in BLOCKERS,
            "message": redact(message or (f"{type(exc).__name__}: {exc}" if exc else "")),
            "fix_hint": redact(getattr(exc, "fix_hint", "")),
            "repaired": repaired,
            "repair_action": redact(repair_action),
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
