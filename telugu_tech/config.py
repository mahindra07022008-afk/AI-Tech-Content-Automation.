"""Project configuration loading (YAML + .env), with validation."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "project.yaml"

REQUIRED_KEYS = [
    ("engine", "mpt_home"),
    ("voice", "primary"),
    ("video", "short"),
    ("video", "long"),
    ("captions", "latin_font"),
    ("captions", "telugu_font"),
    ("publishing", "default_privacy"),
    ("scheduler", "timezone"),
]


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Minimal .env parser (no dependency). Does not override existing env vars."""
    path = path or ROOT / ".env"
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


@dataclass
class Config:
    raw: dict[str, Any]
    path: Path
    root: Path = field(default=ROOT)

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def resolve(self, value: str | os.PathLike) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (self.root / p)

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.get("project", "data_dir", default="data"))

    @property
    def mpt_home(self) -> Path:
        env = os.environ.get("MPT_HOME", "").strip()
        return self.resolve(env or self.get("engine", "mpt_home"))

    @property
    def mpt_python(self) -> Path:
        return self.mpt_home / ".venv" / "bin" / "python"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "content_history.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.jobs_dir, self.logs_dir, self.data_dir / "research",
                  self.data_dir / "reports", self.data_dir / "assets"):
            d.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.secrets_dir, 0o700)

    def validate(self) -> list[str]:
        problems: list[str] = []
        for keys in REQUIRED_KEYS:
            if self.get(*keys) is None:
                problems.append(f"missing config key: {'.'.join(keys)}")
        if self.get("publishing", "default_privacy") not in ("private", "unlisted", "public"):
            problems.append("publishing.default_privacy must be private|unlisted|public")
        if self.get("publishing", "default_privacy") == "public" and not self.get("publishing", "allow_public"):
            problems.append("default_privacy=public but allow_public=false")
        for kind in ("short", "long"):
            v = self.get("video", kind) or {}
            if v.get("fps") != 30:
                problems.append(f"video.{kind}.fps must be 30")
            if not (0 < v.get("min_seconds", 0) < v.get("max_seconds", 0)):
                problems.append(f"video.{kind} min/max seconds invalid")
        for key in ("latin_font", "telugu_font"):
            font = self.get("captions", key)
            if font and not Path(font).is_file():
                problems.append(f"font not found: captions.{key}={font}")
        attempts = self.get("retry", "max_attempts", default=3)
        if not isinstance(attempts, int) or not 1 <= attempts <= 3:
            problems.append("retry.max_attempts must be 1..3")
        return problems


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> Config:
    load_dotenv()
    cfg_path = Path(path) if path else Path(os.environ.get("TELUGU_TECH_CONFIG", DEFAULT_CONFIG))
    with open(cfg_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if overrides:
        raw = _deep_merge(raw, overrides)
    return Config(raw=raw, path=cfg_path)


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
