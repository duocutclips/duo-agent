"""Campaigns: CRUD, document import (PDF/DOCX/TXT/text/URL) and the campaign analyzer.

The analyzer never silently invents requirements. Every extracted item is labelled:

* ``confirmed`` — backed by a verbatim quote that exists in the campaign material.
* ``suggestion`` — an AI (or offline heuristic) recommendation that is *not* in the material.

When Claude is used, any "confirmed" item whose supporting quote cannot be found in the source
text is automatically downgraded to a suggestion.
"""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from .db import Database
from .errors import ExternalServiceError, ValidationError
from .llm import ClaudeClient
from .logging_setup import get_logger, log_event
from .textutil import normalize_ws, slugify

log = get_logger("campaigns")

CAMPAIGN_FIELDS = (
    "name", "platforms", "game", "url", "payout_cpm", "payout_notes", "objective", "requirements",
    "restrictions", "content_goals", "hook_examples", "reference_links", "codes", "notes",
)
PLATFORMS = {
    "tiktok": "TikTok", "instagram": "Instagram", "reels": "Instagram", "youtube": "YouTube", "shorts": "YouTube",
    "snapchat": "Snapchat", "facebook": "Facebook", "twitter": "X", "x.com": "X",
}
MAX_URL_BYTES = 5_000_000


# --------------------------------------------------------------------------- CRUD
def create_campaign(db: Database, data: dict[str, Any]) -> dict[str, Any]:
    name = normalize_ws(str(data.get("name", "")))
    if not name:
        raise ValidationError("Campaign name is required.")
    payload = {k: data[k] for k in CAMPAIGN_FIELDS if k in data}
    payload["name"] = name
    payload["slug"] = slugify(name)
    return db.insert("campaigns", payload)


def update_campaign(db: Database, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = {k: data[k] for k in CAMPAIGN_FIELDS if k in data}
    if "name" in payload:
        payload["name"] = normalize_ws(str(payload["name"]))
        if not payload["name"]:
            raise ValidationError("Campaign name cannot be empty.")
        payload["slug"] = slugify(payload["name"])
    return db.update("campaigns", campaign_id, payload)


def campaign_detail(db: Database, campaign_id: str) -> dict[str, Any]:
    c = db.get("campaigns", campaign_id)
    c["documents"] = [
        {k: d[k] for k in ("id", "kind", "name", "source", "created_at")} | {"chars": len(d["text"])}
        for d in db.list("campaign_documents", "campaign_id = ?", [campaign_id], order="created_at")
    ]
    c["media_count"] = db.scalar("SELECT COUNT(*) FROM media WHERE campaign_id = ?", [campaign_id])
    c["project_count"] = db.scalar("SELECT COUNT(*) FROM projects WHERE campaign_id = ?", [campaign_id])
    return c


def structured_campaign(db: Database, campaign_id: str) -> dict[str, Any]:
    """The structured campaign JSON shape from the specification."""
    c = db.get("campaigns", campaign_id)
    ideas = db.list("ideas", "campaign_id = ?", [campaign_id], order="position")
    media = db.list("media", "campaign_id = ?", [campaign_id], order="created_at")
    return {
        "name": c["name"],
        "game": c["game"],
        "platforms": c["platforms"],
        "objective": c["objective"],
        "requirements": c["requirements"],
        "restrictions": c["restrictions"],
        "hooks": c["hook_examples"],
        "contentIdeas": [i["title"] for i in ideas],
        "codes": c["codes"],
        "sourceAssets": [m["filename"] for m in media],
    }


# --------------------------------------------------------------------------- import
class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href and href.startswith("http"):
                self.links.append(href)
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "div", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str, list[str]]:
    p = _TextExtractor()
    p.feed(html)
    text = "\n".join(normalize_ws(line) for line in "".join(p.parts).splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, normalize_ws(p.title), p.links


def extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise ValidationError("This PDF could not be read.", detail=str(exc)) from exc
    if not text.strip():
        raise ValidationError("No text was found in this PDF. Scanned PDFs need OCR before import.")
    return text


def extract_docx(data: bytes) -> str:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ValidationError("This DOCX file could not be read.", detail=str(exc)) from exc
    lines = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(lines)


def extract_file(filename: str, data: bytes) -> tuple[str, str]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf", extract_pdf(data)
    if ext == ".docx":
        return "docx", extract_docx(data)
    if ext in (".txt", ".md", ".csv", ".json"):
        return "txt", data.decode("utf-8", errors="replace")
    if ext in (".html", ".htm"):
        return "html", html_to_text(data.decode("utf-8", errors="replace"))[0]
    raise ValidationError(f"Unsupported document type '{ext or filename}'. Use PDF, DOCX, TXT or paste the text.")


def fetch_url(url: str, timeout: float = 20.0) -> tuple[str, str]:
    """Fetch a public URL and return (title, text). No logins, no bot-evasion."""
    if not re.match(r"^https?://", url or ""):
        raise ValidationError("URL must start with http:// or https://")
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True,
                              headers={"User-Agent": "RobloxClipFactory/0.1 (campaign importer)"}) as client:
                resp = client.get(url)
            break
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            log_event(log, "url fetch retry", level=30, attempt=attempt + 1, url=url)
    else:
        raise ExternalServiceError("The URL could not be fetched.", detail=str(last_exc))
    if resp.status_code in (401, 403):
        raise ExternalServiceError(
            f"The page refused access (HTTP {resp.status_code}). It is probably private or requires login.",
            hint="Open it in your browser and paste the text instead.",
        )
    if resp.status_code >= 400:
        raise ExternalServiceError(f"The page returned HTTP {resp.status_code}.")
    if len(resp.content) > MAX_URL_BYTES:
        raise ValidationError("The page is larger than 5 MB; paste the relevant text instead.")
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype:
        return url, extract_pdf(resp.content)
    if "html" in ctype or resp.text.lstrip().startswith("<"):
        text, title, _ = html_to_text(resp.text)
        if len(text) < 40:
            raise ExternalServiceError(
                "The page had almost no readable text. It probably renders with JavaScript.",
                hint="Open it in your browser and paste the text instead.",
            )
        return title or url, text
    return url, resp.text


def add_document(db: Database, campaign_id: str, *, kind: str, name: str, text: str, source: str = "") -> dict[str, Any]:
    db.get("campaigns", campaign_id)
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise ValidationError("The document is empty.")
    doc = db.insert("campaign_documents", {"campaign_id": campaign_id, "kind": kind, "name": name or kind,
                                           "source": source, "text": text})
    if kind == "url" and source:
        c = db.get("campaigns", campaign_id)
        links = list(c["reference_links"])
        if source not in links:
            db.update("campaigns", campaign_id, {"reference_links": [*links, source]})
    return {k: doc[k] for k in ("id", "kind", "name", "source", "created_at")} | {"chars": len(doc["text"])}


def campaign_text(db: Database, campaign_id: str) -> str:
    c = db.get("campaigns", campaign_id)
    chunks = []
    manual = [
        ("Campaign", c["name"]), ("Game", c["game"]), ("Objective", c["objective"]),
        ("Requirements", "\n".join(c["requirements"])), ("Restrictions", "\n".join(c["restrictions"])),
        ("Content goals", "\n".join(c["content_goals"])), ("Hook examples", "\n".join(c["hook_examples"])),
        ("Codes", ", ".join(c["codes"])), ("Notes", c["notes"]),
    ]
    chunks.append("\n".join(f"{k}: {v}" for k, v in manual if v))
    for d in db.list("campaign_documents", "campaign_id = ?", [campaign_id], order="created_at"):
        chunks.append(f"--- {d['name']} ---\n{d['text']}")
    return "\n\n".join(chunks)


# --------------------------------------------------------------------------- analyzer
Category = Literal[
    "must_include", "must_avoid", "required_wording", "code", "cta", "platform", "length", "audience",
    "mechanic", "originality", "footage", "objective", "payout", "other",
]


class AnalysisItem(BaseModel):
    category: Category
    text: str
    status: Literal["confirmed", "suggestion"]
    quote: str = Field(default="", description="Verbatim quote from the material supporting a confirmed item")
    rationale: str = ""


class AnalysisResult(BaseModel):
    campaign_name: str = ""
    game: str = ""
    objective: str = ""
    target_audience: str = ""
    game_mechanics: list[str] = []
    platforms: list[str] = []
    recommended_min_seconds: int | None = None
    recommended_max_seconds: int | None = None
    length_is_confirmed: bool = False
    items: list[AnalysisItem] = []


_RE_RESTRICT = re.compile(r"\b(do not|don't|dont|never|avoid|must not|mustn't|not allowed|prohibited|banned|no (?:swearing|profanity|reuploads?|re-uploads?|watermarks?|other|copyrighted|music|bots?|fake|misleading|ai)|without permission|will be rejected|disqualif)", re.I)
_RE_REQUIRE = re.compile(r"\b(must|required|requirement|need to|needs to|have to|has to|should|include|mention|make sure|always|tag|use (?:the|our|code)|say)\b", re.I)
_RE_CODE = re.compile(r"\bcodes?\b\s*(?:is|:|=|-)?\s*[\"'“]?([A-Z0-9][A-Z0-9_\-]{2,})[\"'”]?")
_RE_HASHTAG = re.compile(r"(?<![\w&])#([A-Za-z][A-Za-z0-9_]{1,40})")
_RE_MENTION = re.compile(r"(?<![\w.])@([A-Za-z0-9_.]{2,30})")
_RE_QUOTED = re.compile(r"[\"“]([^\"”]{3,80})[\"”]")
_RE_CTA = re.compile(r"(link in bio|play now|play (?:it|the game) (?:now|today)|follow|subscribe|join (?:the|our)|call to action|\bcta\b|check (?:it|the game) out|search for)", re.I)
_RE_RANGE = re.compile(r"(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\s*(?:s\b|sec|secs|seconds)", re.I)
_RE_MIN = re.compile(r"(?:at least|minimum(?: of)?|min\.?|longer than|over)\s*(\d{1,3})\s*(?:s\b|sec|secs|seconds)", re.I)
_RE_MAX = re.compile(r"(?:under|max(?:imum)?(?: of)?|at most|no longer than|shorter than|less than)\s*(\d{1,3})\s*(?:s\b|sec|secs|seconds)", re.I)
_RE_PAYOUT = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s*(?:per|/)\s*(?:1[,.]?000|1k|thousand|k)\b|\$\s?(\d+(?:\.\d+)?)\s*cpm|cpm[^.\n]{0,20}?\$\s?(\d+(?:\.\d+)?)", re.I)
_RE_ORIGINAL = re.compile(r"\b(original|re-?uploads?|repost|duplicate|unique|transformative|own footage|your own)\b", re.I)
_RE_FOOTAGE = re.compile(r"\b(footage|gameplay|screen ?record|recording|clips?|b-?roll|in-game)\b", re.I)
_RE_AUDIENCE = re.compile(r"\b(audience|kids|teens|players aged|gen ?z|ages? \d|target (?:viewers|players))\b", re.I)
_RE_OBJECTIVE = re.compile(r"^(?:objective|goal|campaign goal|purpose|about)\s*[:\-]\s*(.+)$", re.I)
_RE_GAME = re.compile(r"^(?:game|roblox game|experience)\s*[:\-]\s*(.+)$", re.I)
_RE_NAME = re.compile(r"^(?:campaign|campaign name|title)\s*[:\-]\s*(.+)$", re.I)


def _statements(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*•·▪◦0123456789.) ").strip()
        if not line:
            continue
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line):
            part = part.strip()
            if len(part) >= 4:
                out.append(part)
    return out


def heuristic_analysis(text: str) -> AnalysisResult:
    """Offline rule-based extraction. Only quotes what is literally in the text."""
    res = AnalysisResult()
    seen: set[tuple[str, str]] = set()

    def add(category: str, value: str, quote: str, status: str = "confirmed", rationale: str = "") -> None:
        key = (category, value.lower())
        if key in seen:
            return
        seen.add(key)
        res.items.append(AnalysisItem(category=category, text=value, status=status, quote=quote,  # type: ignore[arg-type]
                                      rationale=rationale))

    platforms: list[str] = []
    for stmt in _statements(text):
        low = stmt.lower()
        if m := _RE_NAME.match(stmt):
            res.campaign_name = res.campaign_name or m.group(1).strip()
        if m := _RE_GAME.match(stmt):
            res.game = res.game or m.group(1).strip()
        if m := _RE_OBJECTIVE.match(stmt):
            res.objective = res.objective or m.group(1).strip()
            add("objective", m.group(1).strip(), stmt)
        for key, name in PLATFORMS.items():
            if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low) and name not in platforms:
                platforms.append(name)
        restricted = bool(_RE_RESTRICT.search(stmt))
        if restricted:
            add("must_avoid", stmt, stmt)
        elif _RE_REQUIRE.search(stmt):
            add("must_include", stmt, stmt)
        for m in _RE_CODE.finditer(stmt):
            if not restricted:
                add("code", m.group(1), stmt)
        for m in _RE_HASHTAG.finditer(stmt):
            if not restricted:
                add("required_wording", f"#{m.group(1)}", stmt)
        for m in _RE_MENTION.finditer(stmt):
            if not restricted:
                add("required_wording", f"@{m.group(1)}", stmt)
        if _RE_REQUIRE.search(stmt) and not restricted:
            for m in _RE_QUOTED.finditer(stmt):
                add("required_wording", m.group(1).strip(), stmt)
        if _RE_CTA.search(stmt) and not restricted:
            add("cta", stmt, stmt)
        if m := _RE_RANGE.search(stmt):
            res.recommended_min_seconds, res.recommended_max_seconds = int(m.group(1)), int(m.group(2))
            res.length_is_confirmed = True
            add("length", f"{m.group(1)}–{m.group(2)} seconds", stmt)
        else:
            if m := _RE_MIN.search(stmt):
                res.recommended_min_seconds = int(m.group(1))
                res.length_is_confirmed = True
                add("length", f"at least {m.group(1)} seconds", stmt)
            if m := _RE_MAX.search(stmt):
                res.recommended_max_seconds = int(m.group(1))
                res.length_is_confirmed = True
                add("length", f"at most {m.group(1)} seconds", stmt)
        if m := _RE_PAYOUT.search(stmt):
            value = next(g for g in m.groups() if g)
            add("payout", f"${value} per 1,000 views", stmt)
        if _RE_ORIGINAL.search(stmt):
            add("originality", stmt, stmt)
        if _RE_FOOTAGE.search(stmt) and (_RE_REQUIRE.search(stmt) or restricted):
            add("footage", stmt, stmt)
        if _RE_AUDIENCE.search(stmt):
            add("audience", stmt, stmt)
            res.target_audience = res.target_audience or stmt
    res.platforms = platforms
    for p in platforms:
        add("platform", p, next((s for s in _statements(text) if p.lower() in s.lower()
                                 or any(k in s.lower() for k, v in PLATFORMS.items() if v == p)), p))
    # Offline suggestions are clearly labelled as suggestions, never as requirements.
    if not res.length_is_confirmed:
        res.recommended_min_seconds, res.recommended_max_seconds = 20, 35
        add("length", "20–35 seconds", "", status="suggestion",
            rationale="Not stated in the campaign. Common range for Roblox short-form clips.")
    if not any(i.category == "cta" for i in res.items):
        add("cta", "End with a short call to action to play the game.", "", status="suggestion",
            rationale="No CTA wording found in the campaign material.")
    add("originality", "Use your own recorded gameplay and original narration; avoid reposting others' clips.", "",
        status="suggestion", rationale="Most clipping programs reject reuploads.")
    return res


def _quote_in_source(quote: str, source: str) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    q = norm(quote)
    return bool(q) and q in norm(source)


ANALYZER_SYSTEM = """You analyse brand/game clipping campaign briefs for short-form Roblox videos.
Extract what the campaign wants. Be strict about provenance:
- status "confirmed" ONLY when the material states it. Put the exact supporting sentence in `quote`, copied verbatim.
- status "suggestion" for your own recommendations (target audience guesses, mechanics to show, hooks, lengths
  not stated). Leave `quote` empty for suggestions and explain in `rationale`.
Never present a suggestion as a requirement. Categories: must_include, must_avoid, required_wording, code, cta,
platform, length, audience, mechanic, originality, footage, objective, payout, other."""


def analyze_campaign(db: Database, llm: ClaudeClient, campaign_id: str, *, use_ai: bool = True) -> dict[str, Any]:
    text = campaign_text(db, campaign_id)
    name_only = f"Campaign: {db.get('campaigns', campaign_id)['name']}"
    if len(text.strip()) < 10 or text.strip() == name_only:
        raise ValidationError("Add some campaign material (fields, pasted text or documents) before analysing.")
    warning = None
    if use_ai and llm.available:
        result = llm.structured(system=ANALYZER_SYSTEM, prompt=f"Campaign material:\n\n{text[:180_000]}",
                                schema=AnalysisResult)
        downgraded = 0
        for item in result.items:
            if item.status == "confirmed" and not _quote_in_source(item.quote, text):
                item.status = "suggestion"
                item.rationale = (item.rationale + " " if item.rationale else "") + \
                    "(Downgraded: the quoted text was not found in the campaign material.)"
                downgraded += 1
        generator = f"anthropic:{llm.settings.anthropic_model}"
        if downgraded:
            warning = f"{downgraded} item(s) Claude marked as confirmed were downgraded because their quote was not in the material."
    else:
        result = heuristic_analysis(text)
        generator = "offline-heuristic"
        if use_ai and not llm.available:
            warning = "Claude is not configured (ANTHROPIC_API_KEY missing), so the offline rule-based analyzer was used."
    analysis = result.model_dump()
    analysis["generator"] = generator
    analysis["warning"] = warning
    _apply_analysis(db, campaign_id, result)
    db.update("campaigns", campaign_id, {"analysis": analysis})
    log_event(log, "campaign analysed", campaign_id=campaign_id, generator=generator, items=len(result.items))
    return analysis


def _apply_analysis(db: Database, campaign_id: str, r: AnalysisResult) -> None:
    """Fill empty structured campaign fields from *confirmed* findings only."""
    c = db.get("campaigns", campaign_id)
    upd: dict[str, Any] = {}
    confirmed = [i for i in r.items if i.status == "confirmed"]
    if not c["game"] and r.game:
        upd["game"] = r.game
    if not c["objective"] and r.objective:
        upd["objective"] = r.objective
    if not c["platforms"] and r.platforms:
        upd["platforms"] = r.platforms
    codes = list(dict.fromkeys([*c["codes"], *[i.text for i in confirmed if i.category == "code"]]))
    if codes != c["codes"]:
        upd["codes"] = codes
    if not c["requirements"]:
        upd["requirements"] = [i.text for i in confirmed if i.category in ("must_include", "required_wording", "cta", "footage")]
    if not c["restrictions"]:
        upd["restrictions"] = [i.text for i in confirmed if i.category == "must_avoid"]
    if c["payout_cpm"] is None:
        for i in confirmed:
            if i.category == "payout" and (m := re.search(r"\d+(?:\.\d+)?", i.text)):
                upd["payout_cpm"] = float(m.group(0))
                break
    if upd:
        db.update("campaigns", campaign_id, upd)


def campaign_rules(campaign: dict[str, Any]) -> dict[str, Any]:
    """Confirmed rules used by ideas, scripts and QA."""
    analysis = campaign.get("analysis") or {}
    items = [i for i in analysis.get("items", []) if i.get("status") == "confirmed"]
    wording = [i["text"] for i in items if i["category"] == "required_wording"]
    codes = list(dict.fromkeys([*campaign.get("codes", []), *[i["text"] for i in items if i["category"] == "code"]]))
    banned_terms: list[str] = []
    for r in [*campaign.get("restrictions", []), *[i["text"] for i in items if i["category"] == "must_avoid"]]:
        for m in re.finditer(r"(?:don't|do not|never|no|avoid)\s+(?:say|mention|use|show)?\s*[\"“']([^\"”']{2,40})[\"”']", r, re.I):
            banned_terms.append(m.group(1))
    return {
        "required_phrases": list(dict.fromkeys([*wording, *codes])),
        "codes": codes,
        "banned_terms": banned_terms,
        "min_seconds": analysis.get("recommended_min_seconds") if analysis.get("length_is_confirmed") else None,
        "max_seconds": analysis.get("recommended_max_seconds") if analysis.get("length_is_confirmed") else None,
        "cta": next((i["text"] for i in items if i["category"] == "cta"), None),
    }
