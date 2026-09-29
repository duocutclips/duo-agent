#!/usr/bin/env python3
"""DuoCut Studio: a local web app around scripts/duocut.py.

Run:  python app.py      then open http://127.0.0.1:5050

Everything stays on this computer. The app never uploads or posts anything:
posting is done by a person, by hand or with the platform's own scheduler.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
import duocut  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
PORT = int(os.environ.get("DUOCUT_PORT", "5050"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 ** 3  # 16 GB uploads
app.config["TEMPLATES_AUTO_RELOAD"] = True


# ---------- background jobs ----------

JOBS = {}

TOOL_WORDS = {"Read": "Reading", "Write": "Writing", "Edit": "Editing", "Glob": "Looking through",
              "Grep": "Searching", "Bash": "Running"}


def _friendly_tool(name, inp):
    target = inp.get("file_path") or inp.get("pattern") or inp.get("command") or ""
    target = Path(target).name if "/" in target or "\\" in target else target
    if name == "Read" and target.startswith("sheet_"):
        return f"Looking at snapshots ({target})"
    if name == "Skill":
        return f"Using the {inp.get('skill', inp.get('command', ''))} skill"
    return f"{TOOL_WORDS.get(name, name)} {target}".strip()


def _stream_json_line(job, line):
    """Turn Claude Code stream-json events into short, readable status lines."""
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return False
    t = d.get("type")
    if t == "assistant":
        for block in d.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                msg = _friendly_tool(block.get("name", ""), block.get("input", {}))
                job["status"] = msg
                job["log"].append("• " + msg)
            elif block.get("type") == "text" and block.get("text", "").strip():
                job["log"].append(block["text"].strip())
    elif t == "result":
        job["result"] = d.get("result", "")
        if d.get("is_error"):
            job["error"] = d.get("result") or "Claude stopped with an error."
    return True


def start_job(kind, slug, cmds, stream_json=False):
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "kind": kind, "slug": slug, "log": [], "done": False, "rc": None,
           "progress": None, "status": "Starting", "error": None, "result": "", "started": time.time(),
           "ended": None, "step": 0, "steps": len(cmds)}
    JOBS[jid] = job
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               HF_HUB_DISABLE_SYMLINKS_WARNING="1", HF_HUB_DISABLE_PROGRESS_BARS="1")

    def run():
        for i, cmd in enumerate(cmds):
            job["step"] = i + 1
            try:
                p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1)
            except FileNotFoundError as e:
                job["error"] = f"Could not start {Path(cmd[0]).name}: {e}"
                job["rc"] = 127
                break
            for raw in p.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                if stream_json and _stream_json_line(job, line):
                    continue
                if line.startswith("PROGRESS "):
                    try:
                        pct = int(line.split()[1])
                        job["progress"] = round(((i + pct / 100) / len(cmds)) * 100)
                    except ValueError:
                        pass
                    continue
                if line.startswith("STATUS "):
                    job["status"] = line[7:]
                    continue
                if line.startswith("ERROR "):
                    job["error"] = line[6:]
                job["log"].append(line)
                del job["log"][:-500]
            job["rc"] = p.wait()
            if job["rc"] != 0:
                job["error"] = job["error"] or explain_failure(job["log"])
                break
        job["done"] = True
        job["ended"] = time.time()
        if job["rc"] == 0:
            job["progress"] = 100

    threading.Thread(target=run, daemon=True).start()
    return jid


def explain_failure(log):
    text = "\n".join(log[-60:]).lower()
    hints = [
        (("cublas", "cudnn", "cuda"), "Your graphics card libraries aren't installed. Transcribe again: it now switches to the CPU on its own."),
        (("connection", "proxy", "resolve", "offline", "timed out"), "Something needed the internet and couldn't reach it. Check your connection and try again."),
        (("not logged in", "login", "authenticate", "/login"), "Claude Code isn't signed in. Open a terminal, run `claude`, sign in, then try again."),
        (("usage limit", "rate limit", "limit reached"), "Your Claude usage limit is reached for now. Try again after it resets."),
        (("no space left",), "Your disk is full. Free some space and try again."),
        (("moov atom", "invalid data found"), "This video file looks damaged or incomplete. Re-download it and upload again."),
        (("memoryerror", "out of memory"), "Your computer ran out of memory. Close other apps or pick a smaller speech model."),
    ]
    for keys, hint in hints:
        if any(k in text for k in keys):
            return hint
    return "Something went wrong. Open Technical details below to see what happened."


def running_job(slug):
    return next((j for j in JOBS.values() if j["slug"] == slug and not j["done"]), None)


def last_job(slug):
    js = [j for j in JOBS.values() if j["slug"] == slug]
    return js[-1] if js else None


def job_view(j):
    if not j:
        return None
    end = j["ended"] or time.time()
    return {k: j[k] for k in ("id", "kind", "done", "rc", "progress", "status", "error", "result", "step", "steps")} | {
        "log": j["log"][-200:], "elapsed": int(end - j["started"]),
        "elapsed_since_end": int(time.time() - j["ended"]) if j["ended"] else 0}


# ---------- campaign state ----------

def cdir(slug):
    d = (duocut.WORK / duocut.slugify(slug)).resolve()
    if duocut.WORK.resolve() not in d.parents:
        abort(404)
    return d


def read(p):
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except OSError:
        return ""


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def videos(d):
    if not d.exists():
        return []
    return sorted((p for p in d.iterdir() if p.suffix.lower() in VIDEO_EXT), key=lambda p: p.name)


def load_json(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def state_of(slug):
    d = cdir(slug)
    st = load_json(d / "state.json", {}) or {}
    vids = videos(d)
    spec = load_json(d / "cuts.json")
    names = [v.name for v in vids]
    source = st.get("source") if st.get("source") in names else ((spec or {}).get("source") if (spec or {}).get("source") in names else (names[0] if names else ""))
    page = read(d / "campaign.md")
    body = "\n".join(l for l in page.splitlines()
                     if not l.startswith(("# Campaign:", "Paste the full campaign page")) and l.strip() != "---")
    page_ok = len(body.strip()) > 40
    stem = Path(source).stem if source else ""
    transcript = read(d / f"{stem}.transcript.txt") if source else ""
    scan = read(d / f"{stem}.scan.txt") if source else ""
    words = 0
    wj = load_json(d / f"{stem}.words.json") if source else None
    if wj:
        words = sum(len(s.get("words", [])) for s in wj.get("segments", []))
    brief = read(d / "brief.md")
    verdict = None
    if brief:
        tail = brief[brief.lower().rfind("verdict"):] if "verdict" in brief.lower() else brief
        verdict = "NO-GO" if "NO-GO" in tail.upper() else ("GO" if re.search(r"\bGO\b", tail) else None)
    cuts = (spec or {}).get("cuts", [])
    log = [r for r in duocut.read_log() if r.get("campaign") == d.name]
    steps = [
        {"key": "page", "label": "Campaign", "done": page_ok},
        {"key": "video", "label": "Video", "done": bool(source)},
        {"key": "analyze", "label": "Analyze", "done": bool(transcript) and bool(scan)},
        {"key": "moments", "label": "Moments", "done": bool(cuts)},
        {"key": "clips", "label": "Clips", "done": bool(log)},
    ]
    current = next((s["key"] for s in steps if not s["done"]), "clips")
    sheets = sorted(p.name for p in (d / f"{stem}.scan").glob("sheet_*.jpg")) if source else []
    return {
        "slug": d.name, "dir": d, "page": page, "page_ok": page_ok, "videos": vids, "source": source,
        "source_size": fmt_size((d / source).stat().st_size) if source else "", "transcript": transcript,
        "words": words, "scan": scan, "sheets": sheets, "brief": brief, "verdict": verdict, "spec": spec,
        "cuts": cuts, "clips": log, "steps": steps, "current": current,
        "posted": sum(1 for r in log if r.get("post_url")),
    }


def campaigns():
    if not duocut.WORK.exists():
        return []
    out = []
    for d in sorted(duocut.WORK.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if d.is_dir():
            try:
                out.append(state_of(d.name))
            except Exception:  # a broken folder shouldn't break the dashboard
                continue
    return out


def claude_exe():
    return shutil.which("claude")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def totals(rows):
    views = sum(num(r.get("views_7d")) or 0 for r in rows)
    pay = sum(num(r.get("payout_usd")) or 0 for r in rows)
    return {"made": len(rows), "waiting": sum(1 for r in rows if not r.get("post_url")),
            "posted": sum(1 for r in rows if r.get("post_url")), "views": int(views), "payout": pay}


@app.context_processor
def shell_context():
    try:
        waiting = sum(1 for r in duocut.read_log() if not r.get("post_url"))
    except Exception:
        waiting = 0
    return {"waiting_count": waiting, "claude_ok": bool(claude_exe())}


@app.template_filter("k")
def kfmt(n):
    n = num(n) or 0
    return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else (f"{n / 1000:.1f}K" if n >= 1000 else f"{n:.0f}")


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch"


# ---------- pages ----------

@app.route("/")
def home():
    rows = duocut.read_log()
    return render_template("home.html", nav="home", campaigns=campaigns(), t=totals(rows), claude=claude_exe())


@app.post("/new")
def new_campaign():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("home"))
    d = cdir(name)
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "campaign.md").exists():
        (d / "campaign.md").write_text("", encoding="utf-8")
    return redirect(url_for("campaign", slug=d.name))


@app.route("/c/<slug>")
def campaign(slug):
    if not cdir(slug).exists():
        abort(404)
    s = state_of(slug)
    job = running_job(s["slug"]) or last_job(s["slug"])
    return render_template("campaign.html", nav="home", s=s, job=job_view(job), claude=claude_exe(),
                           rules=(s["spec"] or {}).get("rules", []))


@app.post("/c/<slug>/page")
def save_page(slug):
    d = cdir(slug)
    (d / "campaign.md").write_text(request.form.get("text", ""), encoding="utf-8")
    return jsonify(ok=True) if wants_json() else redirect(url_for("campaign", slug=slug))


def clean_name(filename):
    name = secure_filename(filename).lstrip("-._") or "video.mp4"
    return name


@app.post("/c/<slug>/upload")
def upload(slug):
    d = cdir(slug)
    f = request.files.get("video")
    if not f or not f.filename:
        return jsonify(ok=False, error="No file received."), 400
    name = clean_name(f.filename)
    if Path(name).suffix.lower() not in VIDEO_EXT:
        return jsonify(ok=False, error="That isn't a video file (mp4, mov, mkv, webm)."), 400
    f.save(d / name)
    set_source(d, name)
    return jsonify(ok=True, name=name) if wants_json() else redirect(url_for("campaign", slug=slug))


def set_source(d, name):
    st = load_json(d / "state.json", {}) or {}
    st["source"] = name
    (d / "state.json").write_text(json.dumps(st), encoding="utf-8")


@app.post("/c/<slug>/source")
def choose_source(slug):
    d = cdir(slug)
    name = request.form.get("video", "")
    if (d / name).exists() and Path(name).suffix.lower() in VIDEO_EXT and "/" not in name and "\\" not in name:
        # rename files that start with "-" so command-line tools don't read them as options
        if name.startswith("-"):
            new = clean_name(name)
            (d / name).rename(d / new)
            name = new
        set_source(d, name)
    return redirect(url_for("campaign", slug=slug))


def py(*args):
    return [sys.executable, "-u", "scripts/duocut.py", *args]


@app.post("/c/<slug>/analyze")
def analyze(slug):
    s = state_of(slug)
    if running_job(s["slug"]) or not s["source"]:
        return jsonify(ok=False, error="Add a video first, or wait for the current job."), 409
    src = s["source"]
    if src.startswith("-"):
        new = clean_name(src)
        (s["dir"] / src).rename(s["dir"] / new)
        set_source(s["dir"], new)
        src = new
    rel = str((s["dir"] / src).relative_to(ROOT))
    # snapshots first: they need no download, so gameplay footage is usable even if transcription fails
    cmds = [py("scan", rel), py("transcribe", rel, "--model", request.form.get("model", "small"))]
    if request.form.get("only") == "scan":
        cmds = cmds[:1]
    jid = start_job("analyze", s["slug"], cmds)
    return jsonify(ok=True, job=jid)


FIND_PROMPT = (
    "Campaign folder: work/{slug}. Source video: {video}. The transcript and the visual scan already exist "
    "(work/{slug}/{stem}.transcript.txt, work/{slug}/{stem}.scan.txt and the contact sheets in work/{slug}/{stem}.scan/). "
    "Follow the make-clips skill steps 1 and 3 only: run the campaign-brief skill (write work/{slug}/brief.md), "
    "then if the verdict is GO run the clip-finder skill and the caption-writer skill so that "
    "work/{slug}/cuts.json has source set to {video}, the campaign rules, and the cuts with captions, "
    "all with approved false. If the video has little speech, look at the contact sheets. "
    "Do not transcribe, do not render, do not post. "
    "End with one line: GO or NO-GO and how many cuts you wrote."
)


@app.post("/c/<slug>/find")
def find(slug):
    s = state_of(slug)
    exe = claude_exe()
    if running_job(s["slug"]):
        return jsonify(ok=False, error="Another job is still running for this campaign."), 409
    if not exe:
        return jsonify(ok=False, error="Claude Code isn't installed. See SETUP.md."), 400
    if not s["source"]:
        return jsonify(ok=False, error="Add a video first."), 400
    tools = ("Read,Write,Edit,Glob,Grep,Skill,"
             "Bash(python scripts/duocut.py stats),Bash(python3 scripts/duocut.py stats),"
             "Bash(python scripts/duocut.py scan:*),Bash(python3 scripts/duocut.py scan:*)")
    prompt = FIND_PROMPT.format(slug=s["slug"], video=s["source"], stem=Path(s["source"]).stem)
    cmd = [exe, "-p", prompt, "--allowedTools", tools, "--permission-mode", "acceptEdits",
           "--output-format", "stream-json", "--verbose"]
    jid = start_job("find", s["slug"], [cmd], stream_json=True)
    return jsonify(ok=True, job=jid)


@app.post("/c/<slug>/cuts")
def save_cuts(slug):
    s = state_of(slug)
    d = s["dir"]
    body = request.get_json(silent=True) or {}
    spec = s["spec"] or {"source": s["source"], "campaign": d.name, "rules": [], "cuts": []}
    old = {str(c.get("id")): c for c in spec.get("cuts", [])}
    new = []
    for i, c in enumerate(body.get("cuts", [])):
        start, end = str(c.get("start", "")).strip(), str(c.get("end", "")).strip()
        if not start or not end:
            continue
        try:
            if duocut.to_seconds(end) <= duocut.to_seconds(start):
                return jsonify(ok=False, error=f"Moment {i + 1}: the end is before the start."), 400
        except ValueError:
            return jsonify(ok=False, error=f"Moment {i + 1}: times look like 1:23.4"), 400
        cid = str(c.get("id") or "")
        merged = dict(old.get(cid, {}))
        merged.update({"id": int(cid) if cid.isdigit() else max([int(k) for k in old if k.isdigit()] + [len(new)]) + 1,
                       "start": start, "end": end, "hook_text": c.get("hook_text", "").strip(),
                       "caption": c.get("caption", "").strip(), "reframe": c.get("reframe", "blur"),
                       "approved": bool(c.get("approved"))})
        if c.get("remake"):
            merged.pop("rendered", None)
        new.append(merged)
    spec["cuts"] = new
    spec["source"] = spec.get("source") or s["source"]
    (d / "cuts.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    if body.get("render"):
        if running_job(s["slug"]):
            return jsonify(ok=False, error="Another job is still running for this campaign."), 409
        if not any(c["approved"] and not c.get("rendered") for c in new):
            return jsonify(ok=False, error="Tick at least one moment that isn't made yet."), 400
        jid = start_job("render", s["slug"], [py("cut", str((d / "cuts.json").relative_to(ROOT)))])
        return jsonify(ok=True, job=jid)
    return jsonify(ok=True)


@app.route("/job/<jid>")
def job(jid):
    j = JOBS.get(jid) or abort(404)
    return jsonify(job_view(j))


@app.route("/queue")
def queue():
    show = request.args.get("show", "todo")
    rows = list(reversed(duocut.read_log()))
    for r in rows:
        folder = duocut.QUEUE / r.get("clip_id", "")
        r["has_video"] = (folder / "final.mp4").exists()
        r["caption_text"] = read(folder / "caption.txt").strip()
        r["checklist"] = read(folder / "README.md")
    t = totals(rows)
    if show == "todo":
        rows = [r for r in rows if not r.get("post_url")]
    elif show == "posted":
        rows = [r for r in rows if r.get("post_url")]
    return render_template("queue.html", nav="queue", rows=rows, show=show, t=t)


@app.post("/clip/<clip_id>/posted")
def posted(clip_id):
    f = request.form
    duocut.update_row(clip_id, platform=f.get("platform", ""), post_url=f.get("url", "").strip(),
                      posted_by=f.get("by", "").strip())
    return jsonify(ok=True) if wants_json() else redirect(url_for("queue"))


@app.post("/clip/<clip_id>/views")
def views(clip_id):
    f = request.form
    duocut.update_row(clip_id, views_7d=f.get("views") or None, approved_views=f.get("approved") or None,
                      payout_usd=f.get("payout") or None)
    return jsonify(ok=True) if wants_json() else redirect(url_for("queue", show="posted"))


@app.route("/insights")
def insights():
    rows = duocut.read_log()
    with_views = [r for r in rows if num(r.get("views_7d")) is not None]
    groups = {}
    for r in with_views:
        g = groups.setdefault(r.get("campaign") or "?", {"clips": 0, "views": 0, "payout": 0.0})
        g["clips"] += 1
        g["views"] += num(r["views_7d"])
        g["payout"] += num(r.get("payout_usd")) or 0
    plats = {}
    for r in with_views:
        g = plats.setdefault(r.get("platform") or "?", {"clips": 0, "views": 0})
        g["clips"] += 1
        g["views"] += num(r["views_7d"])
    top = sorted(with_views, key=lambda r: num(r["views_7d"]), reverse=True)[:8]
    peak = max([num(r["views_7d"]) for r in top] + [1])
    return render_template("insights.html", nav="insights", t=totals(rows), groups=groups, plats=plats,
                           top=top, peak=peak, n=len(with_views))


# ---------- media ----------

@app.route("/media/work/<slug>/<path:name>")
def media_work(slug, name):
    d = cdir(slug)
    target = (d / name).resolve()
    if d not in target.parents:
        abort(404)
    return send_from_directory(target.parent, target.name, conditional=True)


@app.route("/media/queue/<clip_id>/final.mp4")
def media(clip_id):
    return send_from_directory(duocut.QUEUE / secure_filename(clip_id), "final.mp4", conditional=True)


@app.errorhandler(413)
def too_big(_):
    return jsonify(ok=False, error="That file is too big to upload here. Copy it into the campaign folder instead."), 413


if __name__ == "__main__":
    duocut.WORK.mkdir(exist_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    print(f"DuoCut Studio running at {url}  (close this window to stop it)")
    if not os.environ.get("DUOCUT_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
