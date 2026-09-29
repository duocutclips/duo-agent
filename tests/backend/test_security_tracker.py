"""Security (tokens, redaction, file access), approval workflow rules and analytics."""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipfactory import projects as P
from clipfactory import tracker as T
from clipfactory.errors import ConflictError, ValidationError
from clipfactory.logging_setup import get_logger, log_event, redact, setup_logging
from clipfactory.server import create_app

REPO = Path(__file__).resolve().parents[2]


def test_redaction_of_values_and_patterns(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_live_supersecretvalue")
    text = redact("key sk_live_supersecretvalue; Authorization: Bearer abc.def.ghi; api_key=zzz123456 ?token=qqq999")
    assert "supersecret" not in text and "abc.def.ghi" not in text and "zzz123456" not in text and "qqq999" not in text
    assert redact("sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA").count("AAAA") == 0


def test_log_file_never_contains_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0123456789")
    setup_logging(tmp_path / "logs")
    log = get_logger("test")
    log_event(log, "calling with sk-ant-test-0123456789", api_key="sk-ant-test-0123456789", nested={"password": "hunter22"},
              url="https://x.test/?token=abcdef123")
    for h in logging.getLogger("clipfactory").handlers:
        h.flush()
    content = (tmp_path / "logs" / "clipfactory.jsonl").read_text()
    assert "0123456789" not in content and "hunter22" not in content and "abcdef123" not in content
    line = json.loads(content.strip().splitlines()[-1])
    assert line["ctx"]["api_key"] == "[REDACTED]"


def test_api_requires_token_when_configured(settings):
    app = create_app(dataclasses.replace(settings, api_token="t0ken-abc"))
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200  # liveness only, no data
        r = c.get("/api/campaigns")
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        assert c.get("/api/campaigns", headers={"X-CF-Token": "wrong"}).status_code == 401
        assert c.get("/api/campaigns", headers={"X-CF-Token": "t0ken-abc"}).status_code == 200
        assert c.get("/api/campaigns?token=t0ken-abc").status_code == 200


def test_status_reports_configuration_without_leaking_keys(settings):
    s = dataclasses.replace(settings, anthropic_api_key="sk-ant-shouldnotleak")
    with TestClient(create_app(s)) as c:
        body = c.get("/api/status").text
        assert "shouldnotleak" not in body
        st = json.loads(body)
        assert st["llm"]["configured"] is True and st["voice"]["elevenlabs"]["configured"] is False


def test_system_open_is_restricted(settings, tmp_path):
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/system/open", json={"path": str(tmp_path)})
        assert r.status_code == 400
        r = c.post("/api/system/open", json={"path": "/etc/passwd"})
        assert r.status_code == 400


def test_errors_are_structured_json(settings):
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/projects/does-not-exist")
        assert r.status_code == 404 and set(r.json()["error"]) >= {"code", "message"}
        r = c.post("/api/campaigns/nope/analyze")
        assert r.status_code == 404
        r = c.put("/api/preferences", json={"default_quality": "ultra"})
        assert r.status_code == 400


def test_gitignore_blocks_secrets_and_outputs():
    gi = (REPO / ".gitignore").read_text()
    for pattern in (".env", "node_modules", ".venv", "data/", "logs/", "exports/", "*.mp4", "target/", "dist/"):
        assert pattern in gi, pattern
    assert (REPO / ".env.example").is_file()
    assert "ANTHROPIC_API_KEY=" in (REPO / ".env.example").read_text()


def _project(db):
    c = db.insert("campaigns", {"name": "C", "slug": "c", "platforms": ["TikTok"], "payout_cpm": 2.0})
    return db.insert("projects", {"campaign_id": c["id"], "title": "V", "template_id": "roblox_story", "status": "DRAFT",
                                  "media_ids": [], "hashtags": [], "history": [], "seed": 1})


def test_approval_workflow_rules(db, settings):
    p = _project(db)
    with pytest.raises(ConflictError):
        P.transition(db, p["id"], "REVIEW")  # QA must be READY first
    with pytest.raises(ConflictError):
        P.transition(db, p["id"], "APPROVED")  # cannot skip review
    db.update("projects", p["id"], {"qa": {"overall": "READY", "checks": [], "failed": []}})
    P.transition(db, p["id"], "REVIEW")
    with pytest.raises(ValidationError):
        P.transition(db, p["id"], "REJECTED")  # a note is required
    P.transition(db, p["id"], "REJECTED", note="Hook too slow")
    P.transition(db, p["id"], "DRAFT")
    with pytest.raises(ConflictError):
        P.export_project(db, settings, p["id"])  # export needs approval
    got = db.get("projects", p["id"])
    assert [h["event"] for h in got["history"]][-3:] == ["DRAFT → REVIEW", "REVIEW → REJECTED", "REJECTED → DRAFT"]


def test_analytics_totals_and_small_sample_warning(db):
    p = _project(db)
    s1 = T.create_submission(db, {"project_id": p["id"], "platform": "TikTok", "post_url": "https://t.test/1", "views": 10000,
                                  "likes": 500})
    T.create_submission(db, {"project_id": p["id"], "platform": "YouTube", "post_url": "https://y.test/1", "views": 2000,
                             "earnings": 10.0})
    a = T.analytics(db)
    assert a["totals"]["views"] == 12000 and a["totals"]["posts"] == 2 and a["totals"]["videos"] == 1
    assert a["totals"]["earnings"] == 20.0 + 10.0  # 10k views at $2 CPM (estimated) + entered $10
    assert a["sample_note"] and a["best_hook"] is None and a["best_template"] is None
    with pytest.raises(ValidationError):
        T.update_submission(db, s1["id"], {"views": -1})
    with pytest.raises(ValidationError):
        T.create_submission(db, {"project_id": p["id"], "platform": "TikTok", "post_url": "javascript:alert(1)"})
    with pytest.raises(ValidationError):
        T.update_submission(db, s1["id"], {"status": "WON"})
