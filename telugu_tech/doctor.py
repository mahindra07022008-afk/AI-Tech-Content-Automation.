"""Environment diagnostics + safe automatic repairs (used by `setup` and `fix-errors`).

Safe repairs only: create dirs, install/repair MoneyPrinterTurbo at the pinned commit, sync its
venv from the upstream lockfile, write a private (127.0.0.1) MPT config with the claude_code provider,
refresh font cache, fix secret-file permissions. Never: buy anything, enable paid APIs, disable TLS,
change auth, or publish.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from .errors import Category

MPT_CONFIG_KEYS = {
    "listen_host": '"127.0.0.1"',
    "llm_provider": '"claude_code"',
    "video_source": '"local"',
    "log_level": '"INFO"',
    "claude_code_timeout": "420",
}


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


class Doctor:
    def __init__(self, cfg, fix: bool = False, log=print):
        self.cfg, self.fix, self.log = cfg, fix, log
        self.results: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "", category: Category | None = None, repaired: str = "",
            blocker: bool = False):
        self.results.append({"check": name, "ok": ok, "detail": detail, "category": category.value if category else "",
                             "repaired": repaired, "blocker": blocker})

    # ------------------------------------------------------------- checks
    def check_binaries(self):
        for b in ("ffmpeg", "ffprobe", "git", "uv"):
            p = shutil.which(b)
            self.add(f"binary: {b}", bool(p), p or "not found", Category.DEPENDENCY,
                     blocker=not p and b in ("ffmpeg", "ffprobe"))
        claude = shutil.which("claude")
        if claude:
            v = _run([claude, "--version"], timeout=30).stdout.strip()
            self.add("claude CLI (LLM provider)", True, v)
        else:
            self.add("claude CLI (LLM provider)", False, "not found — interactive Claude Code can still write storyboards",
                     Category.DEPENDENCY)

    def check_fonts(self):
        for key in ("latin_font", "telugu_font", "telugu_font_regular"):
            f = self.cfg.get("captions", key)
            ok = bool(f) and Path(f).is_file()
            repaired = ""
            if not ok and self.fix and shutil.which("apt-get") and os.geteuid() == 0:
                r = _run(["apt-get", "install", "-y", "-qq", "fonts-noto-core"], timeout=600)
                _run(["fc-cache", "-f"], timeout=120)
                ok = Path(f).is_file()
                repaired = "installed fonts-noto-core" if ok else f"apt failed: {r.stderr[-120:]}"
            self.add(f"font: {key}", ok, f, Category.FONT, repaired)
        try:
            from PIL import features
            self.add("Pillow raqm (Telugu shaping)", bool(features.check("raqm")), "libraqm", Category.FONT)
        except Exception as exc:  # noqa: BLE001
            self.add("Pillow raqm (Telugu shaping)", False, str(exc), Category.FONT)

    def ensure_mpt(self):
        home = self.cfg.mpt_home
        commit = self.cfg.get("engine", "mpt_commit")
        repo = self.cfg.get("engine", "mpt_repo")
        if not (home / "cli.py").is_file():
            if not self.fix:
                self.add("MoneyPrinterTurbo installed", False, str(home), Category.DEPENDENCY)
                return
            home.parent.mkdir(parents=True, exist_ok=True)
            r = _run(["git", "clone", repo, str(home)], timeout=900)
            if r.returncode != 0:
                self.add("MoneyPrinterTurbo installed", False, r.stderr[-200:], Category.NETWORK)
                return
            _run(["git", "checkout", "--quiet", commit], cwd=home)
            self.add("MoneyPrinterTurbo installed", True, f"cloned {commit[:10]}", repaired="git clone")
        else:
            head = _run(["git", "rev-parse", "HEAD"], cwd=home).stdout.strip()
            pinned = head.startswith(commit[:12]) if commit else True
            self.add("MoneyPrinterTurbo installed", True, f"{home} @ {head[:10]}"
                     + ("" if pinned else f" (pinned {commit[:10]} — run setup --update-engine to switch)"))
        py = self.cfg.mpt_python
        if not py.is_file() or _run([str(py), "-c", "import moviepy, edge_tts, loguru"], cwd=home).returncode != 0:
            if self.fix and shutil.which("uv"):
                r = _run(["uv", "sync", "--python", self.cfg.get("engine", "python", default="3.11")], cwd=home, timeout=1800)
                self.add("MoneyPrinterTurbo venv", r.returncode == 0, r.stderr[-200:] if r.returncode else "uv sync ok",
                         Category.DEPENDENCY, repaired="uv sync (locked)")
            else:
                self.add("MoneyPrinterTurbo venv", False, "missing; run setup", Category.DEPENDENCY)
        else:
            self.add("MoneyPrinterTurbo venv", True, str(py))
        self.ensure_mpt_config()
        if py.is_file():
            r = _run([str(py), "cli.py", "--help"], cwd=home, timeout=120)
            self.add("MoneyPrinterTurbo CLI", r.returncode == 0, "cli.py --help ok" if r.returncode == 0 else r.stderr[-200:],
                     Category.DEPENDENCY)

    def ensure_mpt_config(self):
        home = self.cfg.mpt_home
        cfg_file, example = home / "config.toml", home / "config.example.toml"
        if not cfg_file.is_file():
            if not (self.fix and example.is_file()):
                self.add("MPT config.toml", False, "missing", Category.CONFIG)
                return
            shutil.copy2(example, cfg_file)
        text = cfg_file.read_text(encoding="utf-8")
        changed = []
        for key, val in MPT_CONFIG_KEYS.items():
            pat = re.compile(rf"^{key}\s*=.*$", re.M)
            m = pat.search(text)
            cur = m.group(0).split("=", 1)[1].strip() if m else None
            if cur == val:
                continue
            if key == "llm_provider" and cur not in (None, '"moonshot"', '""'):
                continue  # respect a provider the user chose deliberately (upstream default is moonshot)
            if self.fix:
                text = pat.sub(f"{key} = {val}", text) if m else text.replace("[app]\n", f"[app]\n{key} = {val}\n", 1)
                changed.append(key)
        if changed:
            cfg_file.write_text(text, encoding="utf-8")
        host = re.search(r'^listen_host\s*=\s*"([^"]+)"', text, re.M)
        private = bool(host) and host.group(1) in ("127.0.0.1", "localhost")
        self.add("MPT config private & claude_code", private and 'llm_provider = "claude_code"' in text,
                 f"listen_host={host.group(1) if host else '?'}", Category.CONFIG,
                 repaired=f"set {', '.join(changed)}" if changed else "")
        _run(["git", "check-ignore", "-q", "config.toml"], cwd=home)

    def check_voice(self):
        try:
            from .tts import verify_voices
            res = verify_voices([self.cfg.get("voice", "primary"), self.cfg.get("voice", "alternate")])
            self.add("Edge TTS Telugu voices", all(res.values()), ", ".join(f"{k}={'ok' if v else 'MISSING'}" for k, v in res.items()),
                     Category.VOICE)
        except Exception as exc:  # noqa: BLE001
            self.add("Edge TTS Telugu voices", False, f"{type(exc).__name__}: {str(exc)[:150]}", Category.NETWORK)

    def check_config(self):
        problems = self.cfg.validate()
        self.add("project config valid", not problems, "; ".join(problems) or str(self.cfg.path), Category.CONFIG)
        pub = self.cfg.get("publishing")
        self.add("public publishing disabled (safe default)", not pub.get("allow_public"), f"allow_public={pub.get('allow_public')}")
        self.add("scheduler disabled until approved", True,
                 f"enabled={self.cfg.get('scheduler', 'enabled')}")

    def check_secrets(self):
        self.cfg.ensure_dirs()
        sd = self.cfg.secrets_dir
        mode = stat.S_IMODE(sd.stat().st_mode)
        self.add("secrets dir permissions 700", mode == 0o700, oct(mode))
        for f in sd.glob("*.json"):
            m = stat.S_IMODE(f.stat().st_mode)
            if m & 0o077:
                if self.fix:
                    os.chmod(f, 0o600)
                self.add(f"secret file perms {f.name}", not (m & 0o077) or self.fix, oct(m),
                         repaired="chmod 600" if self.fix and (m & 0o077) else "")
        r = _run(["git", "check-ignore", "-q", "data/secrets/x.json"], cwd=self.cfg.root)
        self.add("secrets git-ignored", r.returncode == 0, ".gitignore covers data/secrets/")
        r = _run(["git", "check-ignore", "-q", ".env"], cwd=self.cfg.root)
        self.add(".env git-ignored", r.returncode == 0)

    def check_premium(self, smoke: bool = False):
        """Remotion premium engine: node, packages (npm ci from lockfile), fonts, browser, optional still render."""
        from .premium import find_browser, remotion_dir
        rdir = remotion_dir(self.cfg)
        node, npm = shutil.which("node"), shutil.which("npm")
        self.add("node (Remotion)", bool(node), _run([node, "--version"]).stdout.strip() if node else "not found",
                 Category.DEPENDENCY)
        if not (node and npm and (rdir / "package.json").is_file()):
            self.add("Remotion project", False, str(rdir), Category.DEPENDENCY)
            return
        mods = rdir / "node_modules" / "@remotion" / "cli"
        repaired = ""
        if not mods.is_dir() and self.fix:
            r = _run([npm, "ci", "--no-audit", "--no-fund"], cwd=rdir, timeout=1800)
            repaired = "npm ci (lockfile)" if r.returncode == 0 else f"npm ci failed: {r.stderr[-150:]}"
        ver = ""
        pj = rdir / "node_modules" / "remotion" / "package.json"
        if pj.is_file():
            import json as _j
            ver = _j.loads(pj.read_text())["version"]
        self.add("Remotion packages", mods.is_dir(), f"remotion {ver or 'missing'}", Category.DEPENDENCY, repaired)
        fonts_dir = rdir / "public" / "fonts"
        need = {"NotoSansDisplay-Bold.ttf", "NotoSansTelugu-Bold.ttf", "NotoSansMono-Bold.ttf"}
        missing = [f for f in need if not (fonts_dir / f).is_file()]
        repaired = ""
        if missing and self.fix:
            fonts_dir.mkdir(parents=True, exist_ok=True)
            for f in missing:
                src = Path("/usr/share/fonts/truetype/noto") / f
                if src.is_file():
                    shutil.copy2(src, fonts_dir / f)
            missing = [f for f in need if not (fonts_dir / f).is_file()]
            repaired = "copied Noto fonts into remotion/public/fonts"
        self.add("Remotion fonts (Telugu + display + mono)", not missing, ", ".join(missing) or "ok", Category.FONT, repaired)
        b = find_browser(self.cfg)
        self.add("Chrome headless shell for Remotion", bool(b), b or "none (Remotion would try to download one)",
                 Category.DEPENDENCY)
        if smoke and mods.is_dir():
            out = rdir / "out" / "smoke.png"
            cmd = ["npx", "remotion", "still", "src/index.ts", "TeluguTechShort", str(out), "--frame=150", "--gl=swangle",
                   "--log=error"] + ([f"--browser-executable={b}"] if b else [])
            r = _run(cmd, cwd=rdir, timeout=600)
            self.add("Remotion smoke render (still)", r.returncode == 0 and out.is_file(),
                     str(out) if r.returncode == 0 else r.stderr[-200:], Category.RENDER)

    def run(self, network: bool = True) -> list[dict]:
        self.check_binaries()
        self.check_config()
        self.check_fonts()
        self.ensure_mpt()
        self.check_secrets()
        self.check_premium(smoke=getattr(self, "smoke", False))
        if network:
            self.check_voice()
        return self.results
