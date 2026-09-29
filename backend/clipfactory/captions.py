"""Caption generation (timeline layer) and ASS subtitle rendering.

Captions are built from word timestamps into short phrases and stored as ``caption`` items on the
timeline. They are only burned in during the final render (via libass); source footage is never
modified.
"""

from __future__ import annotations

import re
from typing import Any

EMPHASIS_WORDS = {"never", "secret", "rare", "fastest", "best", "worst", "stop", "free", "new", "hidden",
                  "insane", "only", "every", "nobody", "everyone", "wait", "watch", "look", "one", "first"}


def is_emphasis(word: str, extra: set[str]) -> bool:
    core = re.sub(r"[^\w#@]", "", word)
    if not core:
        return False
    return (core.lower() in EMPHASIS_WORDS or core.lower() in extra or any(ch.isdigit() for ch in core)
            or (core.isupper() and len(core) > 1))


def build_caption_items(words: list[dict[str, Any]], *, max_words: int = 3, offset: float = 0.0,
                        emphasis_terms: list[str] | None = None, max_gap: float = 0.35) -> list[dict[str, Any]]:
    """Group words into short phrases: break on punctuation, pauses and ``max_words``."""
    extra = {t.lower() for term in (emphasis_terms or []) for t in re.findall(r"[\w#@]+", term)}
    items: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def flush() -> None:
        if not cur:
            return
        items.append({
            "type": "caption",
            "start": round(cur[0]["start"], 3),
            "end": round(cur[-1]["end"], 3),
            "text": " ".join(w["text"] for w in cur),
            "words": list(cur),
        })
        cur.clear()

    for i, w in enumerate(words):
        text = str(w.get("word") or w.get("text") or "").strip()
        if not text:
            continue
        entry = {"text": text, "start": round(float(w["start"]) + offset, 3), "end": round(float(w["end"]) + offset, 3),
                 "emphasis": is_emphasis(text, extra)}
        if cur and entry["start"] - cur[-1]["end"] > max_gap:
            flush()
        cur.append(entry)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if len(cur) >= max_words or re.search(r"[.!?,;:]$", text) or nxt is None:
            flush()
    # Hold each caption until the next one starts (avoids flicker), capped at +0.6s.
    for a, b in zip(items, items[1:], strict=False):
        a["end"] = round(min(b["start"], a["end"] + 0.6), 3)
    if items:
        items[-1]["end"] = round(items[-1]["end"] + 0.4, 3)
    return items


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(items: list[dict[str, Any]], caption_style: dict[str, Any], title_style: dict[str, Any],
              width: int = 1080, height: int = 1920) -> str:
    cs = caption_style
    font = cs.get("font", "DejaVu Sans")
    align = {"lower_third": 2, "center": 5, "top": 8}.get(cs.get("position", "lower_third"), 2)
    margin_v = int(cs.get("margin_v", 560)) if align != 5 else 0
    bold = -1 if cs.get("bold", True) else 0
    ts = title_style
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{int(cs.get('size', 86))},{_ass_color(cs.get('primary', '#FFFFFF'))},{_ass_color(cs.get('highlight', '#FFE14D'))},{_ass_color(cs.get('stroke', '#000000'))},{_ass_color('#000000', 96)},{bold},0,0,0,100,100,0,0,1,{cs.get('stroke_width', 7)},{cs.get('shadow', 3)},{align},70,70,{margin_v},1
Style: Title,{font},{int(ts.get('size', 78))},{_ass_color(ts.get('primary', '#FFFFFF'))},{_ass_color(ts.get('primary', '#FFFFFF'))},{_ass_color(ts.get('box', '#101014'), 40)},{_ass_color('#000000', 128)},-1,0,0,0,100,100,0,0,3,18,0,8,80,80,{int(ts.get('margin_v', 260))},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    hi = _ass_color(cs.get("highlight", "#FFE14D"))
    base = _ass_color(cs.get("primary", "#FFFFFF"))
    upper = bool(cs.get("uppercase", True))
    lines: list[str] = []
    for it in sorted(items, key=lambda x: x["start"]):
        if it["type"] == "text":
            txt = _esc(it["text"].upper() if upper else it["text"])
            fade = r"{\fad(120,120)}"
            lines.append(f"Dialogue: 2,{_ts(it['start'])},{_ts(it['end'])},Title,,0,0,0,,{fade}{txt}")
            continue
        if it["type"] != "caption":
            continue
        words = it.get("words") or []
        if not words or not cs.get("word_emphasis", True):
            txt = _esc(it["text"].upper() if upper else it["text"])
            lines.append(f"Dialogue: 1,{_ts(it['start'])},{_ts(it['end'])},Caption,,0,0,0,,{txt}")
            continue
        # One event per active word: the whole phrase is visible, the spoken word is highlighted
        # and popped; emphasis words stay highlighted.
        for i, w in enumerate(words):
            start = it["start"] if i == 0 else w["start"]
            end = words[i + 1]["start"] if i + 1 < len(words) else it["end"]
            if end - start < 0.01:
                continue
            parts = []
            for j, other in enumerate(words):
                t = _esc(other["text"].upper() if upper else other["text"])
                if j == i:
                    parts.append(rf"{{\c{hi}\fscx112\fscy112}}{t}{{\c{base}\fscx100\fscy100}}")
                elif other.get("emphasis"):
                    parts.append(rf"{{\c{hi}}}{t}{{\c{base}}}")
                else:
                    parts.append(t)
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(lines) + "\n"
