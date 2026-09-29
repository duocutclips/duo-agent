from __future__ import annotations

import io
from dataclasses import dataclass

import docx
import pytest

from clipfactory import campaigns as C
from clipfactory.campaigns import AnalysisItem, AnalysisResult
from clipfactory.errors import ConfigurationError, ValidationError
from clipfactory.samples import DEMO_BRIEF


def _by_cat(analysis: dict, cat: str, status: str = "confirmed") -> list[dict]:
    return [i for i in analysis["items"] if i["category"] == cat and i["status"] == status]


def test_offline_analysis_confirms_only_what_the_brief_says(db, llm):
    c = C.create_campaign(db, {"name": "Demo"})
    C.add_document(db, c["id"], kind="text", name="brief", text=DEMO_BRIEF)
    a = C.analyze_campaign(db, llm, c["id"])
    assert a["generator"] == "offline-heuristic"
    assert "not configured" in (a["warning"] or "")
    assert any("HEIST50" in i["text"] for i in _by_cat(a, "code"))
    assert a["recommended_min_seconds"] == 20 and a["recommended_max_seconds"] == 40 and a["length_is_confirmed"]
    # every confirmed item quotes the source material
    for item in a["items"]:
        if item["status"] == "confirmed":
            assert item["quote"] and C._quote_in_source(item["quote"], DEMO_BRIEF), item
        else:
            assert item["rationale"], item
    # suggestions are never promoted: the brief has a CTA and length, so no suggestion for those
    assert not _by_cat(a, "length", "suggestion")
    rules = C.campaign_rules(db.get("campaigns", c["id"]))
    assert "HEIST50" in rules["codes"] and rules["min_seconds"] == 20 and rules["max_seconds"] == 40
    updated = db.get("campaigns", c["id"])
    assert updated["payout_cpm"] == 1.5
    assert updated["restrictions"], "confirmed restrictions fill the structured field"


def test_missing_information_becomes_labelled_suggestions(db, llm):
    c = C.create_campaign(db, {"name": "Vague"})
    C.add_document(db, c["id"], kind="text", name="brief", text="Make fun clips about our obby game please.")
    a = C.analyze_campaign(db, llm, c["id"])
    length = [i for i in a["items"] if i["category"] == "length"]
    assert length and all(i["status"] == "suggestion" for i in length)
    assert not a["length_is_confirmed"]
    assert C.campaign_rules(db.get("campaigns", c["id"]))["min_seconds"] is None


@dataclass
class FakeSettings:
    anthropic_model: str = "claude-test"


class FakeLLM:
    available = True
    settings = FakeSettings()

    def structured(self, **_kw):
        return AnalysisResult(
            campaign_name="X", game="Seed Heist Simulator", objective="", target_audience="", game_mechanics=[], platforms=[],
            recommended_min_seconds=None, recommended_max_seconds=None, length_is_confirmed=False,
            items=[AnalysisItem(category="code", text="HEIST50", status="confirmed", quote="Include the creator code HEIST50"),
                   AnalysisItem(category="must_include", text="Show a dragon", status="confirmed",
                                quote="You must show the golden dragon")])


def test_llm_confirmed_items_without_a_real_quote_are_downgraded(db):
    c = C.create_campaign(db, {"name": "Demo"})
    C.add_document(db, c["id"], kind="text", name="brief", text=DEMO_BRIEF)
    a = C.analyze_campaign(db, FakeLLM(), c["id"])  # type: ignore[arg-type]
    statuses = {i["text"]: i["status"] for i in a["items"]}
    assert statuses == {"HEIST50": "confirmed", "Show a dragon": "suggestion"}
    assert "downgraded" in a["warning"]


def test_unconfigured_claude_raises_clear_configuration_error(llm):
    assert not llm.available
    with pytest.raises(ConfigurationError) as e:
        llm.structured(system="s", prompt="p", schema=AnalysisResult)
    assert "ANTHROPIC_API_KEY" in (e.value.hint or "")


def test_extract_txt_docx_pdf():
    kind, text = C.extract_file("brief.txt", b"Use code ABC")
    assert kind == "txt" and "ABC" in text

    d = docx.Document()
    d.add_paragraph("Mention the code DOCX42 in every video.")
    buf = io.BytesIO()
    d.save(buf)
    kind, text = C.extract_file("brief.docx", buf.getvalue())
    assert kind == "docx" and "DOCX42" in text

    kind, text = C.extract_file("brief.pdf", _tiny_pdf("Use code PDF77"))
    assert kind == "pdf" and "PDF77" in text

    with pytest.raises(ValidationError):
        C.extract_file("brief.exe", b"MZ")


def test_html_to_text_strips_scripts_and_keeps_links():
    text, title, links = C.html_to_text("<html><title>Camp</title><script>var x=1</script><p>Hello <a href='https://a.b/c'>x</a></p></html>")
    assert title == "Camp" and "Hello" in text and "var x" not in text and "https://a.b/c" in links


def test_empty_campaign_cannot_be_analysed(db, llm):
    c = C.create_campaign(db, {"name": "Empty"})
    with pytest.raises(ValidationError):
        C.analyze_campaign(db, llm, c["id"])


def _tiny_pdf(text: str) -> bytes:
    """Minimal valid one-page PDF with a text object (xref offsets computed)."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out
