"""YouTube SEO package: titles, bilingual description, hashtags, keywords, chapters, pinned comment."""
from __future__ import annotations

import json
from pathlib import Path

from .storyboard import CLICKBAIT, SECTION_LABELS

BASE_TAGS = ["#Telugu", "#TeluguTech", "#TechTelugu"]
MAX_DESC = 5000
MAX_TAGS_CHARS = 500


def _fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters(sb: dict, timings: list[dict]) -> list[tuple[str, str]]:
    """YouTube chapters: first at 0:00, ≥3 chapters, each ≥10 s (long videos only)."""
    out: list[tuple[float, str]] = []
    last_section = None
    for sc, tm in zip(sb["scenes"], timings):
        if sc["section"] != last_section:
            label = sc.get("chapter") or SECTION_LABELS.get(sc["section"], sc["section"])
            if not out or tm["start"] - out[-1][0] >= 10:
                out.append((0.0 if not out else tm["start"], label))
            last_section = sc["section"]
    return [(_fmt(t), label) for t, label in out] if len(out) >= 3 else []


def build(sb: dict, timings: list[dict], cfg, kind: str) -> dict:
    seo = dict(sb.get("seo") or {})
    titles = [t.strip() for t in seo.get("titles", [])][:3]
    hashtags = []
    for h in BASE_TAGS + seo.get("hashtags", []) + (["#Shorts"] if kind == "short" else []):
        h = "#" + h.lstrip("#").replace(" ", "")
        if h.lower() not in {x.lower() for x in hashtags}:
            hashtags.append(h)
    hashtags = hashtags[:12]  # YouTube ignores all hashtags if > 60; keep it tidy
    keywords, total = [], 0
    for k in seo.get("keywords", []):
        if total + len(k) + 1 > MAX_TAGS_CHARS:
            break
        keywords.append(k)
        total += len(k) + 1
    chaps = chapters(sb, timings) if kind == "long" else []
    src_lines = [f"• {s.get('title')} — {s.get('publisher')} ({s.get('published')}): {s.get('url')}"
                 for s in sb.get("sources", [])]
    parts = [seo.get("description_te", "").strip(), "", seo.get("description_en", "").strip(), ""]
    if chaps:
        parts += ["⏱️ Chapters"] + [f"{t} {label}" for t, label in chaps] + [""]
    parts += ["📚 Sources / ఆధారాలు"] + src_lines + [""]
    parts += ["ℹ️ ఈ వీడియోలో AI-generated Telugu voice-over మరియు computer-generated visuals ఉపయోగించాం. "
              "Facts అన్నీ పైన ఇచ్చిన sources నుంచి verify చేశాం.",
              "This video uses an AI-generated voice and programmatically generated visuals; all facts are "
              "checked against the sources above.", "", " ".join(hashtags)]
    description = "\n".join(parts)[:MAX_DESC]
    warnings = []
    for t in titles:
        if len(t) > 100:
            warnings.append(f"title > 100 chars: {t}")
        if any(c in t.lower() for c in CLICKBAIT):
            warnings.append(f"clickbait phrase: {t}")
    if len(titles) != 3:
        warnings.append("need exactly 3 title options")
    return {
        "titles": titles,
        "selected_title": titles[0] if titles else sb.get("topic", ""),
        "description": description,
        "hashtags": hashtags,
        "keywords": keywords,
        "pinned_comment": seo.get("pinned_comment", ""),
        "chapters": chaps,
        "thumbnail_concept": (seo.get("thumbnail") or {}).get("concept", ""),
        "category_id": cfg.get("publishing", "category_id", default="28"),
        "default_language": cfg.get("publishing", "default_language", default="te"),
        "made_for_kids": cfg.get("publishing", "made_for_kids", default=False),
        "contains_synthetic_media": cfg.get("publishing", "contains_synthetic_media", default=True),
        "warnings": warnings,
    }


def save(meta: dict, out_dir: Path) -> dict[str, str]:
    j = out_dir / "youtube_metadata.json"
    j.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out_dir / "youtube_metadata.md"
    md.write_text("\n".join([
        "# YouTube metadata", "", "## Title options", *[f"{i + 1}. {t}" for i, t in enumerate(meta["titles"])], "",
        "## Description", "", "```", meta["description"], "```", "", "## Hashtags", " ".join(meta["hashtags"]), "",
        "## Keywords", ", ".join(meta["keywords"]), "", "## Pinned comment", meta["pinned_comment"], "",
        "## Thumbnail concept", meta["thumbnail_concept"], "",
        "## Audience & disclosure",
        f"- Made for kids: {meta['made_for_kids']}",
        f"- Altered/synthetic content disclosure: {meta['contains_synthetic_media']}", ""]), encoding="utf-8")
    return {"json": str(j), "markdown": str(md)}
