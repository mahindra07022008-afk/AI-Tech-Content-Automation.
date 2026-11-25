"""Editing-style registry (12 styles) + automatic style selection.

Python is the source of truth for every style's parameters; `remotion/src/presets/editStyles.ts`
implements each style's look (overlays, typography, backgrounds) keyed by the same name.
Every style keeps the channel's brand colours, Roman-Telugu captions and safe areas, so videos look
consistent across styles while still feeling different per topic.
"""
from __future__ import annotations

import copy
import re

# Shared defaults (house "cinematic_tech" behaviour); each style overrides what it needs.
BASE = {
    "bpm": 100, "transitionSeconds": 0.4, "cameraIntensity": 0.7, "zoomRange": [1.0, 1.14], "motionBlur": True,
    "parallax": 0.6, "beatPunch": 0.025, "subCutSeconds": 2.4, "dof": False, "overlay": "none",
    "font": "display", "background": "", "transitions": ["whip", "mask", "zoom", "iris", "push", "fade", "glitch"],
    "caption": {"template": "pop_highlight", "position": 0.70, "fontSize": 74, "maxWords": 3, "uppercase": False},
    "grade": {"contrast": 1.07, "saturation": 1.12, "gamma": 0.98, "shadows_teal": 0.05, "highlights_warm": 0.04,
              "bloom": 0.28, "vignette": 0.32, "grain": 3, "sharpen": 0.35},
    "theme": {},
    "music_mood": "uplifting",
}

STYLES: dict[str, dict] = {
    "cinematic_documentary": {
        "label": "Cinematic technology documentary",
        "bpm": 84, "cameraIntensity": 0.45, "beatPunch": 0.0, "subCutSeconds": 3.2, "dof": True, "overlay": "film",
        "font": "serif", "transitions": ["fade", "mask", "zoom", "iris"],
        "grade": {"contrast": 1.1, "saturation": 0.95, "shadows_teal": 0.07, "highlights_warm": 0.06, "bloom": 0.22,
                  "vignette": 0.45, "grain": 4},
        "theme": {"accent": "#F59E0B", "highlight": "#FDE68A", "bgTop": "#05070D", "bgBottom": "#17202B"},
        "music_mood": "serious",
    },
    "product_3d": {
        "label": "Real-time 3D product animation",
        "bpm": 96, "cameraIntensity": 0.5, "dof": True, "overlay": "studio", "background": "studio",
        "transitions": ["zoom", "iris", "fade", "push"],
        "grade": {"contrast": 1.06, "saturation": 1.05, "bloom": 0.3, "vignette": 0.38, "grain": 2},
        "theme": {"accent": "#38BDF8", "highlight": "#F8FAFC", "bgTop": "#05060A", "bgBottom": "#111827"},
    },
    "retro_pixel": {
        "label": "Retro pixel-art storytelling",
        "bpm": 120, "transitionSeconds": 0.3, "cameraIntensity": 0.25, "motionBlur": False, "beatPunch": 0.0,
        "subCutSeconds": 0, "overlay": "crt", "font": "mono", "background": "pixel",
        "transitions": ["push", "mask", "fade"],
        "caption": {"template": "pixel_block", "uppercase": True, "fontSize": 64},
        "grade": {"contrast": 1.05, "saturation": 1.15, "bloom": 0.12, "vignette": 0.25, "grain": 0, "sharpen": 0.0},
        "theme": {"primary": "#6D28D9", "accent": "#34D399", "highlight": "#FBBF24", "bgTop": "#0B0F1A", "bgBottom": "#1B1440"},
        "music_mood": "curious",
    },
    "kinetic_typography": {
        "label": "Kinetic typography",
        "bpm": 112, "cameraIntensity": 0.8, "beatPunch": 0.035, "subCutSeconds": 1.8, "overlay": "none",
        "transitions": ["whip", "push", "zoom", "mask"],
        "caption": {"maxWords": 2, "fontSize": 84},
        "grade": {"contrast": 1.12, "saturation": 1.1, "bloom": 0.2},
    },
    "holo_hud": {
        "label": "Futuristic holographic HUD",
        "bpm": 104, "overlay": "hud", "font": "mono", "background": "dots",
        "transitions": ["glitch", "iris", "mask", "zoom"],
        "caption": {"template": "hud_bracket"},
        "grade": {"contrast": 1.08, "saturation": 1.18, "bloom": 0.38, "shadows_teal": 0.08, "highlights_warm": 0.0},
        "theme": {"primary": "#0E7490", "accent": "#22D3EE", "highlight": "#A7F3D0", "bgTop": "#020617", "bgBottom": "#082F49"},
    },
    "product_launch": {
        "label": "Premium product launch",
        "bpm": 98, "cameraIntensity": 0.55, "dof": True, "overlay": "launch", "background": "studio",
        "transitions": ["iris", "zoom", "fade", "mask"],
        "grade": {"contrast": 1.12, "saturation": 1.0, "bloom": 0.35, "vignette": 0.5, "grain": 2},
        "theme": {"accent": "#E5E7EB", "highlight": "#FACC15", "bgTop": "#000000", "bgBottom": "#0F172A"},
        "music_mood": "serious",
    },
    "ai_news": {
        "label": "AI technology news motion graphics",
        "overlay": "news", "transitions": ["whip", "mask", "zoom", "iris", "push", "glitch"],
    },
    "code_explainer": {
        "label": "Animated programming & technical explainer",
        "bpm": 100, "cameraIntensity": 0.5, "overlay": "terminal", "font": "mono", "background": "dots",
        "transitions": ["push", "mask", "whip", "fade"],
        "grade": {"saturation": 1.05, "bloom": 0.2},
        "theme": {"accent": "#4ADE80", "highlight": "#FACC15", "bgTop": "#050A07", "bgBottom": "#0F1F17"},
        "music_mood": "curious",
    },
    "parallax_25d": {
        "label": "2.5D parallax animation",
        "cameraIntensity": 0.85, "parallax": 1.0, "dof": True, "overlay": "depth", "background": "particles",
        "transitions": ["zoom", "push", "fade", "mask"],
    },
    "isometric": {
        "label": "Smooth isometric animation",
        "cameraIntensity": 0.4, "beatPunch": 0.015, "overlay": "none", "background": "iso",
        "transitions": ["push", "mask", "fade", "zoom"],
        "grade": {"contrast": 1.04, "saturation": 1.08, "bloom": 0.15, "vignette": 0.2},
        "theme": {"accent": "#60A5FA", "highlight": "#F472B6", "bgTop": "#0B1026", "bgBottom": "#1E2A5A"},
    },
    "glassmorphism": {
        "label": "Glassmorphism motion graphics",
        "cameraIntensity": 0.5, "dof": True, "overlay": "glass", "background": "glass",
        "transitions": ["fade", "iris", "zoom", "push"],
        "caption": {"template": "glass_pill"},
        "grade": {"contrast": 1.02, "saturation": 1.15, "bloom": 0.3, "vignette": 0.2, "grain": 2},
        "theme": {"primary": "#8B5CF6", "accent": "#F0ABFC", "highlight": "#FDE047", "bgTop": "#1E1B4B", "bgBottom": "#701A75"},
    },
    "infographic": {
        "label": "Infographic & data visualization",
        "cameraIntensity": 0.35, "beatPunch": 0.015, "overlay": "grid", "background": "grid",
        "transitions": ["push", "mask", "fade", "zoom"],
        "grade": {"contrast": 1.05, "saturation": 1.08, "bloom": 0.15, "vignette": 0.2, "grain": 1},
        "theme": {"accent": "#2DD4BF", "highlight": "#FB923C", "bgTop": "#0A0F1E", "bgBottom": "#13213D"},
    },
}

# Visual types each style is built around (used for selection scoring and storyboard guidance).
PREFERRED_VISUALS = {
    "cinematic_documentary": {"timeline", "headline", "globe", "molecule", "stat"},
    "product_3d": {"phone3d", "stat", "compare"},
    "retro_pixel": {"pixel_scene", "timeline"},
    "kinetic_typography": {"headline", "question", "bullets"},
    "holo_hud": {"globe", "neural_net", "stat", "flow"},
    "product_launch": {"phone3d", "headline", "stat"},
    "ai_news": {"headline", "neural_net", "chat_ui", "stat", "icon_grid"},
    "code_explainer": {"code", "flow", "branch_graph", "chat_ui"},
    "parallax_25d": {"icon_grid", "headline", "flow"},
    "isometric": {"iso_stack", "flow"},
    "glassmorphism": {"chat_ui", "icon_grid", "bullets", "compare"},
    "infographic": {"chart", "stat", "compare", "timeline"},
}

KEYWORDS = {
    "cinematic_documentary": ["history", "story", "invented", "founder", "documentary", "kathalu"],
    "product_3d": ["smartphone", "phone", "device", "chip", "camera", "battery", "gadget", "hardware"],
    "retro_pixel": ["history", "first", "1970", "1980", "1990", "retro", "invented", "origin", "years ago", "web", "website"],
    "kinetic_typography": ["quote", "myth", "facts", "lessons"],
    "holo_hud": ["security", "cyber", "shield", "hack", "defense", "future", "robot", "space"],
    "product_launch": ["launch", "unveil", "introduces", "announced", "release", "new model"],
    "ai_news": ["ai", "openai", "gemini", "claude", "model", "llm", "agent", "news"],
    "code_explainer": ["github", "repo", "repos", "code", "open-source", "open source", "python", "javascript", "rust", "cli",
                       "developer", "tool"],
    "parallax_25d": ["journey", "layers", "universe"],
    "isometric": ["architecture", "stack", "server", "cloud", "infrastructure", "pipeline", "datacenter"],
    "glassmorphism": ["app", "assistant", "ui", "design", "productivity"],
    "infographic": ["percent", "%", "data", "survey", "report", "statistics", "growth", "market"],
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get_style(name: str) -> dict:
    if name not in STYLES:
        raise KeyError(f"unknown style '{name}' (choose from {sorted(STYLES)})")
    s = _merge(BASE, {k: v for k, v in STYLES[name].items() if k != "label"})
    s["name"] = name
    s["label"] = STYLES[name]["label"]
    s["source"] = "style-preset"
    return s


def score_styles(sb: dict, recent: list[str] | None = None) -> list[tuple[float, str]]:
    """Score every style for a storyboard: topic keywords + the visual types it uses, minus a
    repetition penalty for styles used in the most recent videos (avoids samey output)."""
    text = (sb.get("topic", "") + " " + " ".join(s.get("narration_te", "") + " " + s.get("caption_roman", "")
                                                 for s in sb.get("scenes", []))).lower()
    visuals = [((s.get("visual") or {}).get("type") or "") for s in sb.get("scenes", [])]
    recent = recent or []
    scores = []
    for name in STYLES:
        kw = sum(1.0 for k in KEYWORDS[name] if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", text))
        vis = sum(1.0 for v in visuals if v in PREFERRED_VISUALS[name]) / max(1, len(visuals)) * 6
        signature = 4.0 if (("phone3d" in visuals and name in ("product_3d", "product_launch")) or
                            ("pixel_scene" in visuals and name == "retro_pixel") or
                            ("iso_stack" in visuals and name == "isometric")) else 0.0
        # source signal: stories built on GitHub repos read best as programming explainers
        repo_src = any(src.get("tier") == "repo" for src in sb.get("sources", []))
        source_bonus = 3.0 if (repo_src and name == "code_explainer") else 0.0
        penalty = 2.0 * sum(1 for r in recent[:3] if r == name)
        scores.append((round(kw * 0.6 + vis + signature + source_bonus - penalty, 3), name))
    return sorted(scores, reverse=True)


def auto_select(sb: dict, recent: list[str] | None = None) -> str:
    """Explicit `style` in the storyboard wins; otherwise the best-scoring style."""
    if sb.get("style"):
        get_style(sb["style"])  # validates
        return sb["style"]
    return score_styles(sb, recent)[0][1]
