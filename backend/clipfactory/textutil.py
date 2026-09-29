"""Text helpers: slugs, sentence splitting, speaking-duration estimates."""

from __future__ import annotations

import re
import unicodedata

WORDS_PER_MINUTE = 165.0  # energetic short-form narration
SENTENCE_PAUSE = 0.28
COMMA_PAUSE = 0.12

_NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
    60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety",
}


def slugify(text: str, max_len: int = 60) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    slug = slug[:max_len].strip("-")
    return slug or "untitled"


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str) -> list[str]:
    text = normalize_ws(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text)
    return [p.strip() for p in parts if p.strip()]


def number_word_count(n: int) -> int:
    """Approximate number of spoken words for an integer (e.g. 1500 -> 'one thousand five hundred')."""
    if n < 0:
        return 1 + number_word_count(-n)
    if n < 20 or (n < 100 and n % 10 == 0):
        return 1
    if n < 100:
        return 2
    count = 0
    for scale, _name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= scale:
            count += number_word_count(n // scale) + 1
            n %= scale
    if n:
        count += number_word_count(n)
    return count


def spoken_words(text: str) -> list[str]:
    """Words as they would be spoken; numbers are expanded to their approximate word count."""
    out: list[str] = []
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’,.%$]*", text):
        core = tok.strip(",.")
        digits = core.replace(",", "").replace("$", "").rstrip("%")
        if digits.isdigit() and len(digits) < 13:
            n = number_word_count(int(digits)) + (1 if core.endswith("%") or core.startswith("$") else 0)
            out.extend([core] * n)
        else:
            out.append(core)
    return out


def estimate_speech_seconds(text: str, wpm: float = WORDS_PER_MINUTE) -> float:
    words = spoken_words(text)
    if not words:
        return 0.0
    seconds = len(words) / (wpm / 60.0)
    sentences = max(0, len(split_sentences(text)) - 1)
    commas = text.count(",") + text.count(";") + text.count(" - ") + text.count("—")
    seconds += sentences * SENTENCE_PAUSE + commas * COMMA_PAUSE
    return round(seconds, 2)


def count_syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 1
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n)


def tokens(text: str) -> set[str]:
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "it", "this", "that", "you",
            "your", "i", "my", "with", "at", "be", "are", "was", "how", "what", "why", "if", "so", "but", "just"}
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in stop and len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def contains_phrase(haystack: str, needle: str) -> bool:
    """Case/punctuation-insensitive phrase containment."""
    def norm(s: str) -> str:
        return " " + re.sub(r"[^a-z0-9#@]+", " ", s.lower()).strip() + " "
    n = norm(needle).strip()
    return bool(n) and f" {n} " in norm(haystack)
