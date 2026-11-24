import json
import shutil
from pathlib import Path

import pytest

from telugu_tech.config import load_config
from telugu_tech.db import DB

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo_github_short.storyboard.json"


@pytest.fixture
def cfg(tmp_path):
    c = load_config(overrides={"project": {"data_dir": str(tmp_path / "data")}})
    c.ensure_dirs()
    return c


@pytest.fixture
def db(cfg):
    d = DB(cfg.db_path)
    yield d
    d.close()


@pytest.fixture
def demo_sb():
    return json.loads(DEMO.read_text(encoding="utf-8"))


def need_ffmpeg():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
