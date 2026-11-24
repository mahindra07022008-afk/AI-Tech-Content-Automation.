"""Rule-based Telugu Unicode → casual Roman Telugu (fallback when caption_roman is missing).

Produces the informal spelling Telugu viewers type daily ("GitHub ante enti?"), not ISO 15919.
Latin-script words (English tech terms) pass through unchanged.
"""
from __future__ import annotations

VOWELS = {
    "అ": "a", "ఆ": "aa", "ఇ": "i", "ఈ": "ee", "ఉ": "u", "ఊ": "oo", "ఋ": "ru", "ౠ": "roo",
    "ఎ": "e", "ఏ": "e", "ఐ": "ai", "ఒ": "o", "ఓ": "o", "ఔ": "au",
}
SIGNS = {
    "ా": "aa", "ి": "i", "ీ": "ee", "ు": "u", "ూ": "oo", "ృ": "ru", "ౄ": "roo",
    "ె": "e", "ే": "e", "ై": "ai", "ొ": "o", "ో": "o", "ౌ": "au",
}
CONSONANTS = {
    "క": "k", "ఖ": "kh", "గ": "g", "ఘ": "gh", "ఙ": "ng",
    "చ": "ch", "ఛ": "chh", "జ": "j", "ఝ": "jh", "ఞ": "gn",
    "ట": "t", "ఠ": "th", "డ": "d", "ఢ": "dh", "ణ": "n",
    "త": "th", "థ": "th", "ద": "d", "ధ": "dh", "న": "n",
    "ప": "p", "ఫ": "ph", "బ": "b", "భ": "bh", "మ": "m",
    "య": "y", "ర": "r", "ఱ": "r", "ల": "l", "ళ": "l", "వ": "v",
    "శ": "sh", "ష": "sh", "స": "s", "హ": "h", "ౘ": "ts", "ౙ": "dz",
}
VIRAMA, ANUSVARA, VISARGA, CANDRABINDU = "్", "ం", "ః", "ఁ"
DIGITS = {chr(0x0C66 + i): str(i) for i in range(10)}


def to_roman(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch in CONSONANTS:
            base = CONSONANTS[ch]
            if nxt == VIRAMA:
                out.append(base)
                i += 2
                continue
            if nxt in SIGNS:
                out.append(base + SIGNS[nxt])
                i += 2
                continue
            out.append(base + "a")
            i += 1
            continue
        if ch in VOWELS:
            out.append(VOWELS[ch])
        elif ch == ANUSVARA:
            # ం before labials sounds like m, otherwise n (casual spelling)
            following = text[i + 1] if i + 1 < n else ""
            out.append("m" if following in ("ప", "బ", "భ", "మ", "ఫ") or not following.strip() else "n")
        elif ch == VISARGA:
            out.append("h")
        elif ch == CANDRABINDU:
            out.append("n")
        elif ch in DIGITS:
            out.append(DIGITS[ch])
        elif ch in SIGNS or ch == VIRAMA:
            out.append(SIGNS.get(ch, ""))
        else:
            out.append(ch)
        i += 1
    roman = "".join(out)
    # Casual readability: word-final "am" from ం is commonly written "am" (e.g. "samayam"); keep.
    return roman


def has_telugu(text: str) -> bool:
    return any("ఀ" <= c <= "౿" for c in text)
