"""Storyboard schema, validation and LLM generation (Claude via MoneyPrinterTurbo's claude_code provider)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


from .errors import AgentError, BlockerError, Category, classify

SECTIONS = ["hook", "intro", "background", "turning_point", "explanation", "example", "conclusion", "cta"]
SECTION_LABELS = {
    "hook": "Curiosity hook", "intro": "Introduction", "background": "Story background",
    "turning_point": "Discovery / turning point", "explanation": "Simple technical explanation",
    "example": "Real-world example", "conclusion": "Conclusion", "cta": "Call to action",
}
VISUAL_TYPES = {"title", "question", "timeline", "stat", "flow", "branch_graph", "icon_grid", "code",
                "bullets", "outro", "compare",
                # premium engine (Remotion) types; the classic engine renders them as titles
                "headline", "neural_net", "chart", "chat_ui", "globe", "molecule"}
ICONS = {"code", "cloud", "users", "star", "branch", "ai", "chip", "globe", "lock", "rocket", "book", "bug",
         "laptop", "phone", "merge", "server", "money", "india", "check", "heart", "brain", "chart", "dna", "spark"}
TRANSITIONS = {"fade", "slide", "zoom", "wipe", "whip", "mask", "iris", "glitch", "push"}
CAMERAS = {"", "push_in", "pull_out", "pan_left", "pan_right", "orbit", "tilt", "drift"}
BACKGROUNDS = {"", "aurora", "grid", "circuit", "dots", "space", "particles"}
CLICKBAIT = ["shocking", "you won't believe", "100% guaranteed", "secret they", "gone wrong", "must watch",
             "nobody tells", "free money", "షాకింగ్"]
TELUGU_RE = re.compile(r"[ఀ-౿]")
LATIN_RE = re.compile(r"[A-Za-z]")
# Calibrated 2026-11-24 on te-IN-MohanNeural at +0%: ≈ 11.5 chars (incl. spaces) per second of speech.
CHARS_PER_SECOND = 11.5


def telugu_ratio(text: str) -> float:
    te, la = len(TELUGU_RE.findall(text)), len(LATIN_RE.findall(text))
    return te / (te + la) if te + la else 0.0


def estimate_seconds(storyboard: dict, gap: float = 0.3) -> float:
    chars = sum(len(s.get("narration_te", "")) for s in storyboard.get("scenes", []))
    return chars / CHARS_PER_SECOND + gap * max(0, len(storyboard.get("scenes", [])) - 1)


def validate(sb: dict, cfg=None, *, strict_duration: bool = False) -> list[str]:
    """Return a list of problems (empty = valid)."""
    p: list[str] = []
    kind = sb.get("kind")
    if kind not in ("short", "long"):
        p.append("kind must be 'short' or 'long'")
    if not sb.get("topic"):
        p.append("topic missing")
    scenes = sb.get("scenes") or []
    if not scenes:
        return p + ["no scenes"]

    # --- sources and facts (never invent news / stats)
    sources = sb.get("sources") or []
    src_ids = set()
    for s in sources:
        if not str(s.get("url", "")).startswith(("http://", "https://")):
            p.append(f"source {s.get('id')} has no valid url")
        if not s.get("published"):
            p.append(f"source {s.get('id')} missing published date")
        src_ids.add(s.get("id"))
    if not sources:
        p.append("at least one source is required")
    for i, f in enumerate(sb.get("facts") or []):
        ids = f.get("source_ids") or []
        if not ids or not set(ids) <= src_ids:
            p.append(f"fact {i + 1} cites unknown/missing source ids: {ids}")

    # --- 8-part story structure, in order
    seen = [s.get("section") for s in scenes]
    for sec in seen:
        if sec not in SECTIONS:
            p.append(f"unknown section '{sec}'")
    present = [s for s in SECTIONS if s in seen]
    if present != SECTIONS:
        p.append(f"missing sections: {[s for s in SECTIONS if s not in seen]}")
    order = [SECTIONS.index(s) for s in seen if s in SECTIONS]
    if order != sorted(order):
        p.append("sections are out of order")

    for i, sc in enumerate(scenes, 1):
        nar, cap = sc.get("narration_te", ""), sc.get("caption_roman", "")
        if not nar.strip():
            p.append(f"scene {i}: empty narration")
        elif telugu_ratio(nar) < 0.4:
            p.append(f"scene {i}: narration must be mainly Telugu script (ratio {telugu_ratio(nar):.2f})")
        if not cap.strip():
            p.append(f"scene {i}: empty caption_roman")
        elif TELUGU_RE.search(cap):
            p.append(f"scene {i}: caption_roman must be Roman script only")
        v = sc.get("visual") or {}
        if v.get("type") not in VISUAL_TYPES:
            p.append(f"scene {i}: visual.type must be one of {sorted(VISUAL_TYPES)}")
        for item in v.get("items", []) if isinstance(v.get("items"), list) else []:
            if isinstance(item, dict) and item.get("icon") and item["icon"] not in ICONS:
                p.append(f"scene {i}: unknown icon '{item['icon']}'")
        if sc.get("transition", "fade") not in TRANSITIONS:
            p.append(f"scene {i}: transition must be one of {sorted(TRANSITIONS)}")
        if sc.get("camera", "") not in CAMERAS:
            p.append(f"scene {i}: camera must be one of {sorted(CAMERAS - {''})}")
        if sc.get("background", "") not in BACKGROUNDS:
            p.append(f"scene {i}: background must be one of {sorted(BACKGROUNDS - {''})}")

    # --- duration estimate (final check happens on real audio)
    if cfg is not None and kind in ("short", "long"):
        lo, hi = cfg.get("video", kind, "min_seconds"), cfg.get("video", kind, "max_seconds")
        est = estimate_seconds(sb)
        slack = 0.25 if not strict_duration else 0.0
        if est < lo * (1 - slack) or est > hi * (1 + slack):
            p.append(f"estimated narration {est:.0f}s outside {lo}-{hi}s")

    # --- SEO honesty checks
    seo = sb.get("seo") or {}
    titles = seo.get("titles") or []
    if len(titles) != 3:
        p.append("seo.titles must have exactly 3 options")
    for t in titles:
        if len(t) > 100:
            p.append(f"title too long ({len(t)} > 100): {t[:40]}…")
        if any(b in t.lower() for b in CLICKBAIT):
            p.append(f"misleading clickbait phrase in title: {t}")
    return p


def assert_valid(sb: dict, cfg=None) -> None:
    problems = validate(sb, cfg)
    if problems:
        raise AgentError("storyboard invalid:\n- " + "\n- ".join(problems), Category.CONFIG, retryable=False)


# ------------------------------------------------------------------ generation
STYLE_GUIDE = """You are the head writer of a faceless Telugu technology storytelling YouTube channel
for Telugu-speaking students, developers and beginners.

LANGUAGE RULES
- Natural, conversational spoken Telugu (like a friendly senior explaining over chai) — NOT bookish,
  NOT a literal translation from English, no unnecessary formal/Sanskritised words.
- Keep English technical terms in English (Latin script) inside the Telugu sentence: GitHub, code,
  repository, AI, open source, developer, app, server, commit.
- Short sentences, rhythm for voice-over, use commas for natural pauses. Numbers as digits.
- caption_roman = the same line in casual Roman Telugu as people type on WhatsApp
  (e.g. "GitHub ante enti? Developers andaru deenni enduku vaadutunnaru?"). No Telugu script there.

FACT RULES (critical)
- Use ONLY facts present in the provided research sources. Never invent news, numbers, quotes,
  dates, product features or people. If unsure, leave the claim out.
- Every factual claim goes into "facts" with the source ids that support it.

STRUCTURE — exactly these sections, in this order (a section may span multiple scenes for long videos):
hook, intro, background, turning_point, explanation, example, conclusion, cta.
- hook: curiosity-driven question or surprising true fact in the first 3 seconds.
- cta: natural, not pushy (e.g. ask a question for comments, follow for more tech kathalu).
- Original writing only. Never copy another creator's script.

VISUALS — each scene picks one visual "type" from:
title{headline,subline,icon}, question{text}, timeline{events:[{year,label}]},
stat{value,label}, flow{nodes:[labels]}, branch_graph{label}, icon_grid{items:[{icon,label}]},
code{lines:[...],suggestion:[...]} , bullets{items:[...]}, compare{left:{title,points},right:{title,points}}, outro{cta},
headline{text,subline,icon}, neural_net{inputLabel,outputLabel}, chart{chart:"bar"|"line",title,unit,data:[{label,value,highlight}]},
chat_ui{title,messages:[{from:"user"|"ai",text}]}, globe{label}, molecule{label}.
Optional per scene: camera (push_in|pull_out|pan_left|pan_right|orbit|tilt|drift), background
(aurora|grid|circuit|dots|space|particles), keywords:[tech terms to highlight].
Keep caption_roman word-aligned with narration_te (same number of words) for exact word-by-word sync.
Icons: code, cloud, users, star, branch, ai, chip, globe, lock, rocket, book, bug, laptop, phone,
merge, server, money, india, check, heart. On-screen labels: short English / Roman Telugu (≤ 28 chars).
transition per scene: fade | slide | zoom | wipe | whip | mask | iris | glitch | push. Never request logos, movie clips or real people's photos.

OUTPUT: one JSON object only, no markdown fences, matching:
{"schema_version":1,"kind":"short|long","topic":"...","title_te":"...",
 "sources":[{"id":"s1","url":"...","title":"...","publisher":"...","published":"YYYY-MM-DD"}],
 "facts":[{"claim":"...","source_ids":["s1"]}],
 "scenes":[{"id":1,"section":"hook","narration_te":"...","caption_roman":"...",
            "visual":{"type":"question","text":"..."},"transition":"zoom"}],
 "seo":{"titles":["3 accurate options, Telugu+English mix, <=90 chars"],
        "description_te":"...","description_en":"...","hashtags":["#Telugu", "..."],
        "keywords":["..."],"pinned_comment":"...",
        "thumbnail":{"headline":"<=4 words","subline":"<=5 words","icon":"one icon name","concept":"..."}}}
"""

LENGTH_RULES = {
    "short": "SHORT video: 45-60 seconds of narration total = about 520-620 characters of narration across 8-10 scenes.",
    "long": "LONG video: 5-8 minutes of narration = about 3,500-5,000 characters of narration across 24-40 scenes "
            "(sections may repeat consecutively, e.g. several explanation scenes).",
}


def build_prompt(topic: str, kind: str, sources: list[dict], extra: str = "") -> str:
    src = json.dumps(sources, ensure_ascii=False, indent=1)
    return (f"{STYLE_GUIDE}\n{LENGTH_RULES[kind]}\n\nTOPIC: {topic}\n\nRESEARCH SOURCES (the only allowed facts):\n"
            f"{src}\n{extra}\nReturn the JSON now.")


def extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AgentError("LLM response contained no JSON object", Category.UNKNOWN, retryable=True)
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AgentError(f"LLM returned malformed JSON: {exc}", Category.UNKNOWN, retryable=True) from exc


def call_llm(cfg, prompt: str) -> str:
    """Generate text through MoneyPrinterTurbo's configured provider (claude_code → `claude -p`)."""
    helper = cfg.root / "scripts" / "mpt_llm.py"
    py = cfg.mpt_python
    if not py.is_file():
        raise AgentError(f"MoneyPrinterTurbo venv missing: {py}", Category.DEPENDENCY,
                         fix_hint="run: telugu-tech setup")
    try:
        proc = subprocess.run([str(py), str(helper)], input=prompt, capture_output=True, text=True,
                              encoding="utf-8", cwd=cfg.mpt_home,
                              timeout=cfg.get("llm", "timeout_seconds", default=420) + 30)
    except subprocess.TimeoutExpired as exc:
        raise AgentError("LLM call timed out", Category.NETWORK) from exc
    out = (proc.stdout or "").strip().splitlines()
    payload = None
    for line in reversed(out):
        if line.startswith("{") and '"ok"' in line:
            payload = json.loads(line)
            break
    if not payload:
        raise AgentError(f"LLM helper failed: {(proc.stderr or '')[-400:]}", Category.UNKNOWN, retryable=True)
    if not payload.get("ok"):
        err = payload.get("error", "")
        exc = Exception(err)
        cat = classify(exc)
        if cat in (Category.AUTH, Category.QUOTA, Category.BILLING, Category.RATE_LIMIT) or "usage limit" in err.lower():
            raise BlockerError(f"Claude Code provider: {err[:300]}", Category.QUOTA if "limit" in err.lower() else cat,
                               fix_hint="Check `claude` login / subscription usage limits; do not switch to paid APIs.")
        raise AgentError(f"LLM error: {err[:300]}", cat if cat != Category.UNKNOWN else Category.NETWORK)
    return payload["text"]


def generate(cfg, topic: str, kind: str, sources: list[dict], max_attempts: int = 3, log=print) -> dict:
    """Ask Claude for a storyboard; feed validation errors back (bounded to 3 attempts)."""
    extra = ""
    last_problems: list[str] = []
    for attempt in range(1, min(3, max_attempts) + 1):
        text = call_llm(cfg, build_prompt(topic, kind, sources, extra))
        try:
            sb = extract_json(text)
        except AgentError as exc:
            last_problems = [str(exc)]
        else:
            sb.setdefault("kind", kind)
            sb.setdefault("topic", topic)
            last_problems = validate(sb, cfg)
            if not last_problems:
                return sb
        log(f"storyboard attempt {attempt} invalid: {last_problems[:5]}")
        extra = ("\nYOUR PREVIOUS ATTEMPT HAD THESE PROBLEMS — FIX ALL OF THEM:\n- " + "\n- ".join(last_problems))
    raise AgentError("could not obtain a valid storyboard after 3 attempts: " + "; ".join(last_problems[:6]),
                     Category.QUALITY, retryable=False)


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(sb: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")


def storyboard_markdown(sb: dict, timings: list[dict] | None = None) -> str:
    """Human-readable scene-by-scene storyboard with timestamps."""
    lines = [f"# Storyboard — {sb.get('title_te') or sb.get('topic')}", "",
             f"- Kind: **{sb.get('kind')}**  ", f"- Topic: {sb.get('topic')}", ""]
    lines += ["| # | Time | Section | Narration (Telugu) | On-screen caption (Roman) | Visual | Transition |",
              "|---|------|---------|--------------------|---------------------------|--------|------------|"]
    for i, sc in enumerate(sb["scenes"]):
        t = timings[i] if timings and i < len(timings) else None
        ts = f"{_fmt(t['start'])}–{_fmt(t['end'])}" if t else "—"
        vis = json.dumps(sc.get("visual", {}), ensure_ascii=False)
        lines.append(f"| {i + 1} | {ts} | {SECTION_LABELS.get(sc['section'], sc['section'])} | "
                     f"{sc['narration_te']} | {sc['caption_roman']} | `{vis}` | {sc.get('transition', 'fade')} |")
    lines += ["", "## Sources", ""]
    for s in sb.get("sources", []):
        lines.append(f"- [{s.get('id')}] {s.get('title')} — {s.get('publisher')} ({s.get('published')}): {s.get('url')}")
    lines += ["", "## Fact checks", ""]
    for f in sb.get("facts", []):
        lines.append(f"- {f['claim']} → {', '.join(f.get('source_ids', []))}")
    return "\n".join(lines) + "\n"


def _fmt(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"
