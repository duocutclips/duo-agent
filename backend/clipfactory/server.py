"""Local HTTP API (127.0.0.1 only) used by the desktop UI."""

from __future__ import annotations

import hmac
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from . import campaigns as C
from . import projects as P
from . import tracker as T
from .analysis import analyze_media, list_segments
from .config import Settings, load_settings
from .db import Database
from .errors import AppError, ConflictError, NotFoundError, ValidationError
from .ffmpeg import check_binaries
from .ideas import generate_ideas, regenerate_idea
from .jobs import JobManager
from .llm import ClaudeClient
from .logging_setup import get_logger, log_event, redact, setup_logging
from .media import SFX_CATEGORIES, delete_media, import_media
from .publishing import YouTubePublisher, publishers, require_exported
from .samples import create_demo
from .scriptgen import TARGETS, analyze_script, generate_script, save_script
from .templates import delete_template, get_template, list_templates, save_template
from .transcription import status as stt_status
from .transcription import transcribe_narration
from .variations import generate_batch, variation_report
from .voice import (
    ElevenLabs,
    create_voice_profile,
    ensure_default_voice,
    generate_narration,
    providers_status,
)

log = get_logger("server")
PREF_DEFAULTS: dict[str, Any] = {"default_quality": "final", "max_silence_seconds": 1.5, "use_ai": True}
ALLOWED_ORIGINS = ["http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost", "http://tauri.localhost",
                   "https://tauri.localhost", "http://localhost:4173", "http://127.0.0.1:4173"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    setup_logging(settings.logs_dir)
    db = Database(settings.db_path)
    llm = ClaudeClient(settings)
    jobs = JobManager()
    ensure_default_voice(db)
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        jobs.shutdown()

    app = FastAPI(title="Roblox Clip Factory API", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.db, app.state.llm, app.state.jobs = settings, db, llm, jobs
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def auth(request: Request, call_next: Any) -> Any:
        token = settings.api_token
        if token and request.url.path.startswith("/api/") and request.method != "OPTIONS" and request.url.path != "/api/health":
            supplied = request.headers.get("x-cf-token") or request.query_params.get("token")
            if not hmac.compare_digest(supplied or "", token):
                return JSONResponse({"error": {"code": "unauthorized", "message": "Missing or invalid API token."}}, status_code=401)
        return await call_next(request)

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        log_event(log, "request failed", level=30, code=exc.code, message=exc.message, detail=exc.detail)
        body = exc.to_dict()
        if body.get("detail"):
            body["detail"] = redact(str(body["detail"]))  # e.g. an upstream error echoing a request
        return JSONResponse({"error": body}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log_event(log, "unhandled error", level=40, traceback=traceback.format_exc())
        return JSONResponse({"error": {"code": "internal_error", "message": "Unexpected error. Details were written to the log.",
                                       "detail": redact(f"{type(exc).__name__}: {exc}")[:500]}}, status_code=500)

    def body_str(data: dict[str, Any], key: str, required: bool = True) -> str:
        v = data.get(key)
        if required and (v is None or str(v).strip() == ""):
            raise ValidationError(f"'{key}' is required.")
        return str(v or "")

    # ------------------------------------------------------------------ system
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
                "data_dir": str(settings.data_dir), "exports_dir": str(settings.exports_dir),
                "logs_dir": str(settings.logs_dir), "schema_version": db.schema_version}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        yt_ok, yt_msg = YouTubePublisher(settings).available()
        return {"ffmpeg": check_binaries(settings.ffmpeg, settings.ffprobe), "llm": llm.status(),
                "voice": providers_status(settings), "transcription": stt_status(settings),
                "publishing": {"manual": {"configured": True}, "youtube": {"configured": yt_ok, "message": yt_msg}}}

    @app.get("/api/preferences")
    def get_prefs() -> dict[str, Any]:
        return PREF_DEFAULTS | db.get_setting("preferences", {})

    def pref(key: str) -> Any:
        return get_prefs().get(key, PREF_DEFAULTS[key])

    @app.put("/api/preferences")
    def put_prefs(data: dict[str, Any]) -> dict[str, Any]:
        prefs = get_prefs() | {k: v for k, v in data.items() if k in ("default_quality", "max_silence_seconds", "use_ai")}
        if prefs["default_quality"] not in ("draft", "final"):
            raise ValidationError("default_quality must be draft or final.")
        if not isinstance(prefs["max_silence_seconds"], (int, float)) or not 0.5 <= prefs["max_silence_seconds"] <= 10:
            raise ValidationError("max_silence_seconds must be between 0.5 and 10.")
        prefs["use_ai"] = bool(prefs["use_ai"])
        db.set_setting("preferences", prefs)
        return prefs

    @app.get("/api/logs")
    def logs(limit: int = 200) -> list[dict[str, Any]]:
        f = settings.logs_dir / "clipfactory.jsonl"
        if not f.is_file():
            return []
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-min(limit, 2000):]
        out = []
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out

    @app.post("/api/demo")
    def demo() -> dict[str, Any]:
        return jobs.submit("demo", lambda progress: _demo(progress), ref="demo")

    def _demo(progress: Any) -> dict[str, Any]:
        progress("Generating sample footage, sound effects and music", 0.1)
        res = create_demo(db, settings)
        if res["created"]:
            progress("Analysing the demo brief", 0.9)
            C.analyze_campaign(db, llm, res["campaign"]["id"], use_ai=bool(pref("use_ai")))
        return {"campaign_id": res["campaign"]["id"], "created": res["created"]}

    @app.post("/api/system/open")
    def open_path(data: dict[str, Any]) -> dict[str, Any]:
        target = Path(body_str(data, "path")).resolve()
        allowed = [settings.exports_dir.resolve(), settings.renders_dir.resolve(), settings.logs_dir.resolve()]
        if not any(target == a or a in target.parents for a in allowed):
            raise ValidationError("Only files in the exports, renders or logs folders can be opened from the app.")
        if not target.exists():
            raise NotFoundError("That file or folder no longer exists.")
        if platform.system() == "Windows":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": str(target)}

    # ------------------------------------------------------------------ campaigns
    @app.get("/api/campaigns")
    def campaigns() -> list[dict[str, Any]]:
        return [C.campaign_detail(db, c["id"]) for c in db.list("campaigns")]

    @app.post("/api/campaigns")
    def create_campaign(data: dict[str, Any]) -> dict[str, Any]:
        c = C.create_campaign(db, data)
        return C.campaign_detail(db, c["id"])

    @app.get("/api/campaigns/{cid}")
    def get_campaign(cid: str) -> dict[str, Any]:
        return C.campaign_detail(db, cid)

    @app.patch("/api/campaigns/{cid}")
    def patch_campaign(cid: str, data: dict[str, Any]) -> dict[str, Any]:
        C.update_campaign(db, cid, data)
        return C.campaign_detail(db, cid)

    @app.delete("/api/campaigns/{cid}")
    def delete_campaign(cid: str) -> dict[str, Any]:
        db.delete("campaigns", cid)
        return {"deleted": cid}

    @app.get("/api/campaigns/{cid}/structured")
    def structured(cid: str) -> dict[str, Any]:
        return C.structured_campaign(db, cid)

    @app.get("/api/campaigns/{cid}/rules")
    def rules(cid: str) -> dict[str, Any]:
        return C.campaign_rules(db.get("campaigns", cid))

    @app.post("/api/campaigns/{cid}/documents/text")
    def add_text(cid: str, data: dict[str, Any]) -> dict[str, Any]:
        return C.add_document(db, cid, kind="text", name=data.get("name") or "Pasted text", text=body_str(data, "text"))

    @app.post("/api/campaigns/{cid}/documents/url")
    def add_url(cid: str, data: dict[str, Any]) -> dict[str, Any]:
        url = body_str(data, "url")
        title, text = C.fetch_url(url, timeout=min(30.0, settings.http_timeout))
        return C.add_document(db, cid, kind="url", name=title[:120], text=text, source=url)

    @app.post("/api/campaigns/{cid}/documents/file")
    async def add_file(cid: str, file: UploadFile = File(...)) -> dict[str, Any]:
        data = await file.read()
        if len(data) > 25_000_000:
            raise ValidationError("Documents must be smaller than 25 MB.")
        kind, text = C.extract_file(file.filename or "document", data)
        return C.add_document(db, cid, kind=kind, name=file.filename or kind, text=text)

    @app.post("/api/campaigns/{cid}/documents/path")
    def add_path(cid: str, data: dict[str, Any]) -> dict[str, Any]:
        p = Path(body_str(data, "path"))
        if not p.is_file():
            raise ValidationError(f"File not found: {p}")
        kind, text = C.extract_file(p.name, p.read_bytes())
        return C.add_document(db, cid, kind=kind, name=p.name, text=text, source=str(p))

    @app.get("/api/documents/{doc_id}")
    def get_doc(doc_id: str) -> dict[str, Any]:
        return db.get("campaign_documents", doc_id)

    @app.delete("/api/documents/{doc_id}")
    def del_doc(doc_id: str) -> dict[str, Any]:
        db.delete("campaign_documents", doc_id)
        return {"deleted": doc_id}

    @app.post("/api/campaigns/{cid}/analyze")
    def analyze(cid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return C.analyze_campaign(db, llm, cid, use_ai=bool((data or {}).get("use_ai", pref("use_ai"))))

    @app.get("/api/campaigns/{cid}/ideas")
    def ideas(cid: str) -> list[dict[str, Any]]:
        db.get("campaigns", cid)
        return db.list("ideas", "campaign_id = ?", [cid], order="position")

    @app.post("/api/campaigns/{cid}/ideas")
    def gen_ideas(cid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        d = data or {}
        return generate_ideas(db, llm, cid, count=int(d.get("count", 10)), use_ai=bool(d.get("use_ai", pref("use_ai"))),
                              replace=bool(d.get("replace", True)))

    @app.post("/api/ideas/{iid}/regenerate")
    def regen(iid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return regenerate_idea(db, llm, iid, use_ai=bool((data or {}).get("use_ai", pref("use_ai"))))

    @app.patch("/api/ideas/{iid}")
    def patch_idea(iid: str, data: dict[str, Any]) -> dict[str, Any]:
        allowed = {k: v for k, v in data.items() if k in ("selected", "title", "hook", "concept", "cta", "script_angle")}
        return db.update("ideas", iid, allowed)

    @app.delete("/api/ideas/{iid}")
    def delete_idea(iid: str) -> dict[str, Any]:
        db.delete("ideas", iid)
        return {"deleted": iid}

    @app.post("/api/campaigns/{cid}/batch")
    def batch(cid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        d = data or {}
        db.get("campaigns", cid)
        return jobs.submit("batch", lambda progress: generate_batch(
            db, settings, llm, cid, idea_ids=d.get("idea_ids"), count=int(d.get("count", 3)),
            use_ai=bool(d.get("use_ai", pref("use_ai"))), quality=d.get("quality", pref("default_quality")),
            voice_profile_id=d.get("voice_profile_id"), progress=progress), ref=cid)

    # ------------------------------------------------------------------ scripts
    @app.get("/api/scripts")
    def scripts(campaign_id: str | None = None) -> list[dict[str, Any]]:
        if campaign_id:
            return db.list("scripts", "campaign_id = ?", [campaign_id])
        return db.list("scripts")

    @app.post("/api/ideas/{iid}/scripts")
    def new_script(iid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        d = data or {}
        return generate_script(db, llm, iid, int(d.get("target_seconds", 30)), use_ai=bool(d.get("use_ai", pref("use_ai"))))

    @app.get("/api/scripts/{sid}")
    def get_script(sid: str) -> dict[str, Any]:
        s = db.get("scripts", sid)
        return s | {"sentences": analyze_script(s["text"], s["target_seconds"])["sentences"]}

    @app.put("/api/scripts/{sid}")
    def put_script(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        return save_script(db, sid, body_str(data, "text"), data.get("target_seconds"))

    @app.post("/api/scripts/estimate")
    def estimate(data: dict[str, Any]) -> dict[str, Any]:
        target = int(data.get("target_seconds", 30))
        if target not in TARGETS:
            raise ValidationError(f"Target must be one of {TARGETS}.")
        rules = C.campaign_rules(db.get("campaigns", data["campaign_id"])) if data.get("campaign_id") else None
        return analyze_script(str(data.get("text", "")), target, rules)

    @app.delete("/api/scripts/{sid}")
    def delete_script(sid: str) -> dict[str, Any]:
        db.delete("scripts", sid)
        return {"deleted": sid}

    # ------------------------------------------------------------------ voice
    @app.get("/api/voices")
    def voices() -> list[dict[str, Any]]:
        return db.list("voice_profiles", order="created_at")

    @app.post("/api/voices")
    def add_voice(data: dict[str, Any]) -> dict[str, Any]:
        return create_voice_profile(db, data)

    @app.patch("/api/voices/{vid}")
    def patch_voice(vid: str, data: dict[str, Any]) -> dict[str, Any]:
        cur = db.get("voice_profiles", vid)
        upd = {k: v for k, v in data.items() if k in ("name", "voice_id", "authorized", "notes")}
        if "settings" in data:
            upd["settings"] = {**cur["settings"], **data["settings"]}
        return db.update("voice_profiles", vid, upd)

    @app.delete("/api/voices/{vid}")
    def delete_voice(vid: str) -> dict[str, Any]:
        db.delete("voice_profiles", vid)
        return {"deleted": vid}

    @app.get("/api/voices/elevenlabs/catalog")
    def eleven_catalog() -> list[dict[str, Any]]:
        return ElevenLabs(settings).list_voices()

    @app.post("/api/scripts/{sid}/narration")
    def narrate(sid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        n = generate_narration(db, settings, sid, (data or {}).get("voice_profile_id"))
        return transcribe_narration(db, settings, n["id"]) | {"cached": n["cached"]}

    @app.get("/api/narrations")
    def narrations(script_id: str | None = None) -> list[dict[str, Any]]:
        return db.list("narrations", "script_id = ?", [script_id]) if script_id else db.list("narrations")

    @app.post("/api/narrations/{nid}/transcribe")
    def transcribe(nid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return transcribe_narration(db, settings, nid, prefer=(data or {}).get("prefer"))

    # ------------------------------------------------------------------ media
    @app.get("/api/media")
    def media(kind: str | None = None, campaign_id: str | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if campaign_id:
            where.append("campaign_id = ?")
            params.append(campaign_id)
        rows = db.list("media", " AND ".join(where), params)
        for r in rows:
            r["segment_count"] = db.scalar("SELECT COUNT(*) FROM segments WHERE media_id = ?", [r["id"]])
            r["missing"] = not Path(r["path"]).is_file()
        return rows

    @app.get("/api/media/sfx-categories")
    def sfx_categories() -> list[str]:
        return list(SFX_CATEGORIES)

    @app.post("/api/media/import-path")
    def import_path(data: dict[str, Any]) -> dict[str, Any]:
        return import_media(db, settings, Path(body_str(data, "path")), kind=data.get("kind"), copy=bool(data.get("copy", False)),
                            campaign_id=data.get("campaign_id"), category=data.get("category"),
                            license_note=data.get("license_note", ""))

    @app.post("/api/media/upload")
    async def upload(file: UploadFile = File(...), kind: str | None = Form(None), campaign_id: str | None = Form(None),
                     category: str | None = Form(None), license_note: str = Form("")) -> dict[str, Any]:
        suffix = Path(file.filename or "upload").suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=settings.cache_dir) as tmp:
            while chunk := await file.read(1024 * 1024):
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        try:
            return import_media(db, settings, tmp_path, kind=kind or None, copy=True, campaign_id=campaign_id or None,
                                category=category or None, license_note=license_note, display_name=file.filename)
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.patch("/api/media/{mid}")
    def patch_media(mid: str, data: dict[str, Any]) -> dict[str, Any]:
        upd = {k: v for k, v in data.items() if k in ("category", "tags", "campaign_id", "license_note", "filename")}
        if "category" in upd and upd["category"] and db.get("media", mid)["kind"] == "sfx" and upd["category"] not in SFX_CATEGORIES:
            raise ValidationError("Unknown sound-effect category.")
        return db.update("media", mid, upd)

    @app.delete("/api/media/{mid}")
    def del_media(mid: str) -> dict[str, Any]:
        delete_media(db, settings, mid)
        return {"deleted": mid}

    @app.post("/api/media/{mid}/analyze")
    def analyze_mid(mid: str) -> dict[str, Any]:
        db.get("media", mid)
        return jobs.submit("analysis", lambda progress: analyze_media(db, settings, mid), ref=mid)

    @app.get("/api/media/{mid}/segments")
    def segments(mid: str) -> list[dict[str, Any]]:
        return list_segments(db, mid)

    @app.post("/api/media/{mid}/segments")
    def add_segment(mid: str, data: dict[str, Any]) -> dict[str, Any]:
        m = db.get("media", mid)
        start, end = float(data.get("start", -1)), float(data.get("end", -1))
        if not (0 <= start < end <= float(m["duration"] or 0) + 0.01):
            raise ValidationError("Segment must satisfy 0 ≤ start < end ≤ clip duration.")
        return db.insert("segments", {"media_id": mid, "start": round(start, 3), "end": round(end, 3),
                                      "label": data.get("label") or "Manual selection", "kind": data.get("kind", "manual"),
                                      "score": float(data.get("score", 0.8)), "confidence": 1.0,
                                      "tags": data.get("tags", ["manual"]), "source": "manual"})

    @app.patch("/api/segments/{sid}")
    def patch_segment(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        seg = db.get("segments", sid)
        m = db.get("media", seg["media_id"])
        upd = {k: v for k, v in data.items() if k in ("start", "end", "label", "enabled", "score", "tags")}
        start, end = float(upd.get("start", seg["start"])), float(upd.get("end", seg["end"]))
        if not (0 <= start < end <= float(m["duration"] or 0) + 0.01):
            raise ValidationError("Segment must satisfy 0 ≤ start < end ≤ clip duration.")
        if "start" in upd or "end" in upd:
            upd["source"] = "manual"
        return db.update("segments", sid, upd)

    @app.delete("/api/segments/{sid}")
    def del_segment(sid: str) -> dict[str, Any]:
        db.delete("segments", sid)
        return {"deleted": sid}

    # ------------------------------------------------------------------ files
    def _file(path: str | None, what: str) -> FileResponse:
        if not path or not Path(path).is_file():
            raise NotFoundError(f"{what} file not found.")
        return FileResponse(path)

    @app.get("/api/files/media/{mid}")
    def media_file(mid: str) -> FileResponse:
        return _file(db.get("media", mid)["path"], "Media")

    @app.get("/api/files/thumb/{mid}")
    def thumb_file(mid: str) -> FileResponse:
        return _file(db.get("media", mid).get("thumbnail"), "Thumbnail")

    @app.get("/api/files/narration/{nid}")
    def narration_file(nid: str) -> FileResponse:
        return _file(db.get("narrations", nid)["audio_path"], "Narration")

    @app.get("/api/files/render/{pid}")
    def render_file(pid: str) -> FileResponse:
        return _file(db.get("projects", pid)["render_path"], "Render")

    @app.get("/api/files/export/{pid}")
    def export_file(pid: str) -> FileResponse:
        return _file(db.get("projects", pid)["export_path"], "Export")

    # ------------------------------------------------------------------ templates
    @app.get("/api/templates")
    def templates() -> list[dict[str, Any]]:
        return list_templates(settings)

    @app.get("/api/templates/{tid}")
    def template(tid: str) -> dict[str, Any]:
        return get_template(settings, tid)

    @app.put("/api/templates/{tid}")
    def put_template(tid: str, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("id") != tid:
            raise ValidationError("Template id in the body must match the URL.")
        return save_template(settings, data)

    @app.delete("/api/templates/{tid}")
    def del_template(tid: str) -> dict[str, Any]:
        delete_template(settings, tid)
        return {"deleted": tid}

    # ------------------------------------------------------------------ projects
    @app.get("/api/projects")
    def projects(campaign_id: str | None = None) -> list[dict[str, Any]]:
        rows = db.list("projects", "campaign_id = ?", [campaign_id], order="updated_at DESC") if campaign_id \
            else db.list("projects", order="updated_at DESC")
        return [{k: v for k, v in r.items() if k != "timeline"} | {"stages": P.stages(db, r),
                "ready": bool(r["qa"] and r["qa"].get("overall") == "READY")} for r in rows]

    @app.post("/api/projects")
    def new_project(data: dict[str, Any]) -> dict[str, Any]:
        return P.create_project(db, body_str(data, "campaign_id"), idea_id=data.get("idea_id"), title=data.get("title"),
                                template_id=data.get("template_id"), media_ids=data.get("media_ids"))

    @app.get("/api/projects/variation-report")
    def var_report(ids: str) -> dict[str, Any]:
        return variation_report(db, [i for i in ids.split(",") if i])

    @app.get("/api/projects/{pid}")
    def project(pid: str) -> dict[str, Any]:
        return P.project_detail(db, pid)

    @app.patch("/api/projects/{pid}")
    def patch_project(pid: str, data: dict[str, Any]) -> dict[str, Any]:
        return P.update_project(db, pid, data)

    @app.delete("/api/projects/{pid}")
    def del_project(pid: str) -> dict[str, Any]:
        db.delete("projects", pid)
        return {"deleted": pid}

    @app.post("/api/projects/{pid}/duplicate")
    def dup(pid: str) -> dict[str, Any]:
        return P.duplicate_project(db, pid)

    @app.post("/api/projects/{pid}/script")
    def proj_script(pid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        d = data or {}
        P.step_script(db, llm, pid, d.get("target_seconds"), bool(d.get("use_ai", pref("use_ai"))))
        return P.project_detail(db, pid)

    @app.put("/api/projects/{pid}/script")
    def proj_set_script(pid: str, data: dict[str, Any]) -> dict[str, Any]:
        return P.set_script(db, pid, body_str(data, "script_id"))

    @app.post("/api/projects/{pid}/voice")
    def proj_voice(pid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        P.step_voice(db, settings, pid, (data or {}).get("voice_profile_id"))
        return P.project_detail(db, pid)

    @app.post("/api/projects/{pid}/timeline")
    def proj_timeline(pid: str) -> dict[str, Any]:
        P.step_timeline(db, settings, pid)
        return P.project_detail(db, pid)

    @app.put("/api/projects/{pid}/timeline")
    def proj_save_timeline(pid: str, data: dict[str, Any]) -> dict[str, Any]:
        P.save_timeline(db, pid, data)
        return P.project_detail(db, pid)

    @app.post("/api/projects/{pid}/render")
    def proj_render(pid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        db.get("projects", pid)
        quality = (data or {}).get("quality", pref("default_quality"))
        return jobs.submit("render", lambda progress: P.step_render(db, settings, pid, quality, progress), ref=pid)

    @app.post("/api/projects/{pid}/qa")
    def proj_qa(pid: str) -> dict[str, Any]:
        P.step_qa(db, settings, pid)
        return P.project_detail(db, pid)

    @app.post("/api/projects/{pid}/pipeline")
    def proj_pipeline(pid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        d = data or {}
        db.get("projects", pid)
        return jobs.submit("pipeline", lambda progress: P.run_pipeline(
            db, settings, llm, pid, target_seconds=d.get("target_seconds"), use_ai=bool(d.get("use_ai", pref("use_ai"))),
            voice_profile_id=d.get("voice_profile_id"), quality=d.get("quality", pref("default_quality")), progress=progress), ref=pid)

    @app.post("/api/projects/{pid}/status")
    def proj_status(pid: str, data: dict[str, Any]) -> dict[str, Any]:
        return P.transition(db, pid, body_str(data, "status"), str(data.get("note", "")))

    @app.post("/api/projects/{pid}/export")
    def proj_export(pid: str) -> dict[str, Any]:
        return P.export_project(db, settings, pid)

    @app.get("/api/projects/{pid}/publish-kit")
    def kit(pid: str) -> dict[str, Any]:
        return P.publish_kit(db, pid)

    @app.post("/api/projects/{pid}/publish")
    def publish(pid: str, data: dict[str, Any]) -> dict[str, Any]:
        p = db.get("projects", pid)
        video = require_exported(p)
        pubs = publishers(settings, P.PLATFORM_URLS)
        provider = body_str(data, "provider")
        if provider not in pubs:
            raise ValidationError(f"Unknown publisher '{provider}'.")
        pub = pubs[provider]
        ok, msg = pub.available()
        if not ok:
            raise ConflictError(f"{pub.platform} publishing is not configured.", hint=msg)
        if provider != "youtube" or not data.get("confirm"):
            if provider == "youtube":
                raise ValidationError("Confirm the upload explicitly (confirm=true). Uploads are private by default.")
            return pub.publish(video, p["caption_text"], p["hashtags"])
        result = pub.publish(video, p["caption_text"], p["hashtags"], data.get("options"))
        T.create_submission(db, {"project_id": pid, "platform": pub.platform, "post_url": result["post_url"],
                                 "status": "PENDING", "metrics_source": f"youtube:{result['post_id']}"})
        P.transition(db, pid, "POSTED", note=f"Uploaded via YouTube API ({result['privacy']})")
        return result

    @app.post("/api/projects/{pid}/mark-posted")
    def mark_posted(pid: str, data: dict[str, Any]) -> dict[str, Any]:
        p = db.get("projects", pid)
        require_exported(p)
        sub = T.create_submission(db, {"project_id": pid, "platform": body_str(data, "platform"),
                                       "post_url": body_str(data, "post_url"), "status": "PENDING"})
        if p["status"] == "EXPORTED":
            P.transition(db, pid, "POSTED", note=data.get("post_url", ""))
        return {"project": P.project_detail(db, pid), "submission": sub}

    # ------------------------------------------------------------------ jobs
    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return jobs.list()

    @app.get("/api/jobs/{jid}")
    def job(jid: str) -> dict[str, Any]:
        j = jobs.get(jid)
        if not j:
            raise NotFoundError("Job not found (jobs are kept in memory until the app restarts).")
        return j

    # ------------------------------------------------------------------ submissions / analytics
    @app.get("/api/submissions")
    def subs(campaign_id: str | None = None) -> list[dict[str, Any]]:
        return T.analytics(db, campaign_id)["rows"]

    @app.post("/api/submissions")
    def new_sub(data: dict[str, Any]) -> dict[str, Any]:
        return T.create_submission(db, data)

    @app.patch("/api/submissions/{sid}")
    def patch_sub(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        return T.update_submission(db, sid, data)

    @app.delete("/api/submissions/{sid}")
    def del_sub(sid: str) -> dict[str, Any]:
        db.delete("submissions", sid)
        return {"deleted": sid}

    @app.post("/api/submissions/{sid}/refresh-metrics")
    def refresh(sid: str) -> dict[str, Any]:
        s = db.get("submissions", sid)
        src = s["metrics_source"] or ""
        if not src.startswith("youtube:"):
            raise ConflictError("Metrics for this post are entered manually (no official API connected for it).")
        m = YouTubePublisher(settings).get_metrics(src.split(":", 1)[1])
        return T.update_submission(db, sid, {"views": m["views"], "likes": m["likes"], "comments": m["comments"]})

    @app.get("/api/analytics")
    def analytics(campaign_id: str | None = None) -> dict[str, Any]:
        return T.analytics(db, campaign_id)

    @app.get("/api/dashboard")
    def dash() -> dict[str, Any]:
        return T.dashboard(db)


    return app


def _pid_alive(pid: int) -> bool:
    if platform.system() == "Windows":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return bool(kernel32.WaitForSingleObject(handle, 0) == 0x102)  # WAIT_TIMEOUT = still running
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch_parent(pid: int, interval: float = 2.0) -> None:
    """Exit when the desktop shell that started us is gone (e.g. killed), so no backend is orphaned."""
    def loop() -> None:
        while True:
            time.sleep(interval)
            if not _pid_alive(pid):
                log_event(log, "desktop shell exited; stopping backend", parent_pid=pid)
                os._exit(0)

    threading.Thread(target=loop, name="parent-watch", daemon=True).start()


def main() -> None:
    import uvicorn

    settings = load_settings()
    parent = os.environ.get("CLIP_FACTORY_PARENT_PID", "")
    if parent.isdigit():
        watch_parent(int(parent))
    app = create_app(settings)
    log_event(log, "starting server", host=settings.host, port=settings.port, data_dir=str(settings.data_dir))
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
