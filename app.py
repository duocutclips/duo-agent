#!/usr/bin/env python3
"""DuoCut Studio: a local web app around scripts/duocut.py.

Run:  python app.py      then open http://127.0.0.1:5050

Everything stays on this computer. The app never uploads or posts anything:
posting is done by a person, by hand or with the platform's own scheduler.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
import duocut  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
PORT = int(os.environ.get("DUOCUT_PORT", "5050"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 ** 3  # 8 GB uploads

# ---------- background jobs ----------

JOBS = {}


def start_job(kind, slug, cmd):
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "kind": kind, "slug": slug, "log": [], "done": False, "rc": None}
    JOBS[jid] = job

    def run():
        try:
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", bufsize=1)
            for line in p.stdout:
                job["log"].append(line.rstrip())
                del job["log"][:-400]
            job["rc"] = p.wait()
        except FileNotFoundError as e:
            job["log"].append(f"Could not start: {e}")
            job["rc"] = 127
        job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return jid


def running_job(slug):
    return next((j for j in JOBS.values() if j["slug"] == slug and not j["done"]), None)


def last_job(slug):
    js = [j for j in JOBS.values() if j["slug"] == slug]
    return js[-1] if js else None


# ---------- campaign helpers ----------

def cdir(slug):
    d = (duocut.WORK / duocut.slugify(slug)).resolve()
    if duocut.WORK.resolve() not in d.parents:
        abort(404)
    return d


def campaigns():
    if not duocut.WORK.exists():
        return []
    return sorted([d.name for d in duocut.WORK.iterdir() if d.is_dir()])


def videos(d):
    return sorted(p.name for p in d.iterdir() if p.suffix.lower() in VIDEO_EXT) if d.exists() else []


def load_cuts(d):
    p = d / "cuts.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"error": "cuts.json is not valid JSON", "cuts": []}
    return None


def claude_exe():
    return shutil.which("claude")


def read(p):
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ---------- pages ----------

@app.route("/")
def home():
    rows = duocut.read_log()
    waiting = [r for r in rows if not r.get("post_url")]
    return render_page(HOME, campaigns=campaigns(), waiting=len(waiting),
                                  total=len(rows), claude=claude_exe(), title="Campaigns")


@app.post("/new")
def new_campaign():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("home"))
    d = cdir(name)
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "campaign.md").exists():
        (d / "campaign.md").write_text(duocut.BRIEF_TEMPLATE.format(name=name), encoding="utf-8")
    return redirect(url_for("campaign", slug=d.name))


@app.route("/c/<slug>")
def campaign(slug):
    d = cdir(slug)
    if not d.exists():
        abort(404)
    vids = videos(d)
    spec = load_cuts(d)
    src = (spec or {}).get("source") or (vids[0] if vids else "")
    transcript = d / Path(src).with_suffix(".transcript.txt").name if src else None
    return render_page(CAMPAIGN, title=slug, slug=slug, page_text=read(d / "campaign.md"),
        brief=read(d / "brief.md"), vids=vids, src=src,
        has_transcript=bool(transcript and transcript.exists()),
        transcript=read(transcript)[:4000] if transcript else "", spec=spec,
        job=running_job(slug) or last_job(slug), claude=claude_exe(),
        clips=[r for r in duocut.read_log() if r.get("campaign") == slug])


@app.post("/c/<slug>/page")
def save_page(slug):
    d = cdir(slug)
    (d / "campaign.md").write_text(request.form.get("text", ""), encoding="utf-8")
    return redirect(url_for("campaign", slug=slug) + "#page")


@app.post("/c/<slug>/upload")
def upload(slug):
    d = cdir(slug)
    f = request.files.get("video")
    if f and f.filename:
        name = secure_filename(f.filename)
        if Path(name).suffix.lower() in VIDEO_EXT:
            f.save(d / name)
    return redirect(url_for("campaign", slug=slug) + "#video")


@app.post("/c/<slug>/transcribe")
def transcribe(slug):
    d = cdir(slug)
    video = secure_filename(request.form.get("video", ""))
    if running_job(slug) or not (d / video).exists():
        return redirect(url_for("campaign", slug=slug))
    cmd = [sys.executable, "-u", "scripts/duocut.py", "transcribe", str((d / video).relative_to(ROOT)),
           "--model", request.form.get("model", "small")]
    start_job("transcribe", slug, cmd)
    return redirect(url_for("campaign", slug=slug) + "#job")


FIND_PROMPT = (
    "Campaign folder: work/{slug}. Source video: {video}. The transcript already exists. "
    "Follow the make-clips skill steps 1 and 3 only: run the campaign-brief skill (write work/{slug}/brief.md), "
    "then if the verdict is GO run the clip-finder skill and the caption-writer skill so that "
    "work/{slug}/cuts.json has source set to {video}, the campaign rules, and 6 to 10 cuts with captions, "
    "all with approved false. Do not transcribe, do not render, do not post. "
    "End with one line: GO or NO-GO and how many cuts you wrote."
)


@app.post("/c/<slug>/find")
def find(slug):
    d = cdir(slug)
    video = secure_filename(request.form.get("video", ""))
    exe = claude_exe()
    if running_job(slug) or not exe or not (d / video).exists():
        return redirect(url_for("campaign", slug=slug))
    tools = "Read,Write,Edit,Glob,Grep,Bash(python scripts/duocut.py stats),Bash(python3 scripts/duocut.py stats)"
    cmd = [exe, "-p", FIND_PROMPT.format(slug=d.name, video=video),
           "--allowedTools", tools, "--permission-mode", "acceptEdits"]
    start_job("find", slug, cmd)
    return redirect(url_for("campaign", slug=slug) + "#job")


@app.post("/c/<slug>/cuts")
def save_cuts(slug):
    d = cdir(slug)
    spec = load_cuts(d) or {"source": request.form.get("source", ""), "campaign": d.name, "rules": [], "cuts": []}
    f = request.form
    ids = f.getlist("id")
    new = []
    for i, cid in enumerate(ids):
        old = next((c for c in spec.get("cuts", []) if str(c.get("id")) == cid), {})
        start, end = f.getlist("start")[i].strip(), f.getlist("end")[i].strip()
        if not start or not end:
            continue
        c = dict(old)
        c.update({"id": int(cid) if cid.isdigit() else i + 1, "start": start, "end": end,
                  "hook_text": f.getlist("hook_text")[i].strip(), "caption": f.getlist("caption")[i].strip(),
                  "reframe": f.getlist("reframe")[i], "approved": f"approve-{cid}" in f})
        new.append(c)
    spec["cuts"] = new
    if f.get("source"):
        spec["source"] = f["source"]
    (d / "cuts.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    if f.get("action") == "render" and not running_job(slug):
        start_job("render", slug, [sys.executable, "-u", "scripts/duocut.py", "cut",
                                   str((d / "cuts.json").relative_to(ROOT))])
        return redirect(url_for("campaign", slug=slug) + "#job")
    return redirect(url_for("campaign", slug=slug) + "#cuts")


@app.route("/job/<jid>")
def job(jid):
    j = JOBS.get(jid) or abort(404)
    return jsonify({k: j[k] for k in ("kind", "done", "rc", "log")})


@app.route("/queue")
def queue():
    rows = list(reversed(duocut.read_log()))
    for r in rows:
        folder = duocut.QUEUE / r.get("clip_id", "")
        r["has_video"] = (folder / "final.mp4").exists()
        r["caption_text"] = read(folder / "caption.txt").strip()
        r["checklist"] = read(folder / "README.md")
    return render_page(QUEUE, title="Clips", rows=rows)


@app.post("/clip/<clip_id>/posted")
def posted(clip_id):
    duocut.update_row(clip_id, platform=request.form.get("platform", ""), post_url=request.form.get("url", ""),
                      posted_by=request.form.get("by", ""))
    return redirect(url_for("queue") + "#" + clip_id)


@app.post("/clip/<clip_id>/views")
def views(clip_id):
    f = request.form
    duocut.update_row(clip_id, views_7d=f.get("views") or None, approved_views=f.get("approved") or None,
                      payout_usd=f.get("payout") or None)
    return redirect(url_for("queue") + "#" + clip_id)


@app.route("/stats")
def stats():
    r = subprocess.run([sys.executable, "scripts/duocut.py", "stats"], cwd=ROOT, capture_output=True, text=True)
    return render_page(STATS, title="What's working", out=r.stdout or r.stderr)


@app.route("/media/queue/<clip_id>/final.mp4")
def media(clip_id):
    return send_from_directory(duocut.QUEUE / secure_filename(clip_id), "final.mp4")


# ---------- templates ----------

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ title }} · DuoCut Studio</title>
<style>
:root{--bg:#f3f4f2;--panel:#fff;--ink:#16191c;--muted:#5b646c;--line:#d6dbde;--accent:#0b6e6a;--soft:#ddefed;--warn:#b86a00;--warnsoft:#fbebd3}
@media (prefers-color-scheme:dark){:root{--bg:#101416;--panel:#171d20;--ink:#e4eaec;--muted:#9aa6ae;--line:#2e393f;--accent:#4fc2bb;--soft:#16312f;--warn:#f0a640;--warnsoft:#3a2a12}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;gap:18px;align-items:center;padding:12px 20px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
header b{font-size:17px}header a{color:var(--muted);text-decoration:none}header a:hover{color:var(--ink)}
main{max-width:1100px;margin:0 auto;padding:24px 16px 80px;display:grid;gap:18px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;display:grid;gap:10px;min-width:0}
h1{margin:0;font-size:26px}h2{margin:0;font-size:18px}.step{color:var(--accent);font:600 12px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.06em}
.muted{color:var(--muted)}a{color:var(--accent)}
input,select,textarea,button{font:inherit;color:inherit}input,select,textarea{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 9px;min-width:0}
textarea{width:100%;min-height:200px;font:13px/1.45 ui-monospace,monospace}
button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:8px 14px;cursor:pointer;font-weight:600}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--accent)}button:disabled{opacity:.45;cursor:not-allowed}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
pre{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:12px;font:12.5px/1.45 ui-monospace,monospace;max-height:420px;overflow:auto;margin:0}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:980px}td.t{width:96px}td.cap{width:30%}td,th{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}
th{font:600 11px ui-monospace,monospace;text-transform:uppercase;color:var(--muted)}td input,td textarea,td select{width:100%}td textarea{min-height:60px}
.note{background:var(--warnsoft);border:1px solid var(--warn);border-radius:6px;padding:10px 12px}
.clip{display:grid;grid-template-columns:240px minmax(0,1fr);gap:18px}@media(max-width:700px){.clip{grid-template-columns:1fr}}
video{width:100%;border-radius:6px;background:#000;aspect-ratio:9/16}
.pill{display:inline-block;font:600 11px ui-monospace,monospace;padding:3px 7px;border-radius:4px;background:var(--soft);color:var(--accent)}
.pill.warn{background:var(--warnsoft);color:var(--warn)}
</style></head><body>
<header><b>DuoCut Studio</b><a href="/">Campaigns</a><a href="/queue">Clips to post</a><a href="/stats">What's working</a></header>
<main>@@BODY@@</main></body></html>"""

HOME = """<h1>Campaigns</h1>
{% if not claude %}<div class="note">Claude Code isn't installed or isn't on your PATH, so "Find moments" is off.
Install it from code.claude.com/docs/en/setup, sign in, then restart this app. Everything else works.</div>{% endif %}
<div class="panel"><h2>New campaign</h2>
<form method="post" action="/new" class="row"><input name="name" placeholder="Roblox Campaign 1" required style="flex:1">
<button>Create</button></form></div>
<div class="panel"><h2>Your campaigns</h2>
{% for c in campaigns %}<div><a href="/c/{{ c }}">{{ c }}</a></div>{% else %}<p class="muted">None yet.</p>{% endfor %}</div>
<div class="panel"><h2>Clips</h2><p>{{ waiting }} of {{ total }} clips are waiting to be posted. <a href="/queue">Open the queue</a></p></div>"""

CAMPAIGN = """<div><span class="step">Campaign</span><h1>{{ slug }}</h1></div>
{% if job %}<div class="panel" id="job" data-job="{{ job.id }}" data-done="{{ 1 if job.done else 0 }}"><h2>{{ {'transcribe':'Transcribing','find':'Claude is reading the campaign and finding moments','render':'Rendering clips'}[job.kind] }}
<span class="pill{{ ' warn' if job.done and job.rc else '' }}" id="jobstate">{{ 'running' if not job.done else ('done' if job.rc == 0 else 'failed') }}</span></h2>
<pre id="joblog">{{ job.log|join('\\n') }}</pre></div>{% endif %}

<div class="panel" id="page"><span class="step">Step 1</span><h2>Paste the campaign page</h2>
<p class="muted">Copy everything from the Whop or Content Rewards campaign page: payout, rules, where the footage comes from.</p>
<form method="post" action="/c/{{ slug }}/page"><textarea name="text">{{ page_text }}</textarea><div class="row" style="margin-top:8px"><button>Save</button></div></form></div>

<div class="panel" id="video"><span class="step">Step 2</span><h2>Add the source video</h2>
<p class="muted">Only footage the campaign allows. Big files: copy them straight into <code>work/{{ slug }}/</code> instead and refresh.</p>
<form method="post" action="/c/{{ slug }}/upload" enctype="multipart/form-data" class="row"><input type="file" name="video" accept="video/*" required><button>Upload</button></form>
{% if vids %}<p>In this campaign: {{ vids|join(', ') }}</p>{% endif %}</div>

<div class="panel"><span class="step">Step 3</span><h2>Transcribe</h2>
{% if vids %}<form method="post" action="/c/{{ slug }}/transcribe" class="row">
<select name="video">{% for v in vids %}<option {{ 'selected' if v == src }}>{{ v }}</option>{% endfor %}</select>
<select name="model"><option value="base">base (fast)</option><option value="small" selected>small (default)</option><option value="medium">medium (accents, music)</option></select>
<button {{ 'disabled' if job and not job.done }}>{{ 'Transcribe again' if has_transcript else 'Transcribe' }}</button></form>
<p class="muted">The first run downloads the speech model (about 500 MB for small). After that it works offline.</p>
{% if transcript %}<details><summary>Transcript preview</summary><pre>{{ transcript }}</pre></details>{% endif %}
{% else %}<p class="muted">Add a video first.</p>{% endif %}</div>

<div class="panel"><span class="step">Step 4</span><h2>Find moments with Claude</h2>
<p class="muted">Claude writes the campaign brief (rules, payout, GO or NO-GO), picks 6 to 10 moments and writes captions. Uses your Claude Code sign-in.</p>
{% if not claude %}<div class="note">Claude Code not found. Install it, sign in, and restart the app.</div>
{% elif has_transcript %}<form method="post" action="/c/{{ slug }}/find" class="row"><input type="hidden" name="video" value="{{ src }}">
<button {{ 'disabled' if job and not job.done }}>Find moments</button></form>
{% else %}<p class="muted">Transcribe first.</p>{% endif %}
{% if brief %}<details open><summary>Campaign brief</summary><pre>{{ brief }}</pre></details>{% endif %}</div>

<div class="panel" id="cuts"><span class="step">Step 5</span><h2>Pick the clips to make</h2>
{% if spec and spec.error %}<div class="note">{{ spec.error }}</div>{% endif %}
<p class="muted">Tick the ones worth making, fix times or hooks if needed, then render. Times look like 12:03.4.</p>
<form method="post" action="/c/{{ slug }}/cuts"><input type="hidden" name="source" value="{{ src }}">
<div class="tbl"><table><tr><th>Make</th><th>Start</th><th>End</th><th>Hook on screen</th><th>Post caption</th><th>Frame</th><th>Score · why</th></tr>
{% for c in (spec.cuts if spec else []) %}<tr>
<td><input type="hidden" name="id" value="{{ c.id }}"><input type="checkbox" name="approve-{{ c.id }}" {{ 'checked' if c.approved }} {{ 'disabled' if c.rendered }}>
{% if c.rendered %}<span class="pill">made</span>{% endif %}</td>
<td class="t"><input name="start" value="{{ c.start }}"></td><td class="t"><input name="end" value="{{ c.end }}"></td>
<td><textarea name="hook_text">{{ c.hook_text or '' }}</textarea></td><td class="cap"><textarea name="caption">{{ c.caption or '' }}</textarea></td>
<td><select name="reframe"><option value="blur" {{ 'selected' if (c.reframe or spec.reframe or 'blur') == 'blur' }}>full + blur</option><option value="crop" {{ 'selected' if c.reframe == 'crop' }}>crop center</option></select></td>
<td>{{ c.score or '' }} <span class="muted">{{ c.why or '' }}</span></td></tr>{% endfor %}
{% set nid = ((spec.cuts|map(attribute='id')|max) if spec and spec.cuts else 0) + 1 %}
<tr><td><input type="hidden" name="id" value="{{ nid }}"><input type="checkbox" name="approve-{{ nid }}"> <span class="muted">new</span></td>
<td class="t"><input name="start" placeholder="0:00"></td><td class="t"><input name="end" placeholder="0:30"></td>
<td><textarea name="hook_text"></textarea></td><td class="cap"><textarea name="caption"></textarea></td>
<td><select name="reframe"><option value="blur">full + blur</option><option value="crop">crop center</option></select></td><td class="muted">add your own</td></tr>
</table></div>
<div class="row" style="margin-top:10px"><button class="ghost" name="action" value="save">Save</button>
<button name="action" value="render" {{ 'disabled' if (job and not job.done) or not src }}>Save and render ticked clips</button></div></form></div>

{% if clips %}<div class="panel"><span class="step">Step 6</span><h2>Review and post</h2>
<p>{{ clips|length }} clips made for this campaign. <a href="/queue">Open the clips queue</a> to watch, copy captions and log posts.</p></div>{% endif %}
<script>
const j=document.getElementById('job');
if(j&&j.dataset.done==='0'){const log=document.getElementById('joblog');
 const t=setInterval(async()=>{const r=await fetch('/job/'+j.dataset.job);const d=await r.json();
  log.textContent=d.log.join('\\n');log.scrollTop=log.scrollHeight;
  if(d.done){clearInterval(t);location.reload();}},1500);}
</script>"""

QUEUE = """<h1>Clips to post</h1>
<div class="note">You post each clip yourself, by hand or with TikTok, YouTube Studio or Meta's own scheduler. Watch it all the way through first.</div>
{% for r in rows %}<div class="panel clip" id="{{ r.clip_id }}">
<div>{% if r.has_video %}<video controls preload="metadata" src="/media/queue/{{ r.clip_id }}/final.mp4"></video>{% else %}<p class="muted">Video file missing.</p>{% endif %}</div>
<div style="display:grid;gap:10px;align-content:start;min-width:0">
<div><span class="step">{{ r.campaign }}</span><h2>{{ r.hook or r.clip_id }}</h2><span class="muted">{{ r.clip_id }} · {{ r.start }} to {{ r.end }}</span>
{% if r.post_url %} <span class="pill">posted on {{ r.platform }}</span>{% else %} <span class="pill warn">not posted</span>{% endif %}</div>
<div><b>Caption</b><pre id="cap-{{ loop.index }}">{{ r.caption_text }}</pre>
<button class="ghost" type="button" onclick="copyCap('cap-{{ loop.index }}',this)">Copy caption</button></div>
<details><summary>Posting checklist and campaign rules</summary><pre>{{ r.checklist }}</pre></details>
<form method="post" action="/clip/{{ r.clip_id }}/posted" class="row"><select name="platform">
{% for p in ['tiktok','youtube','instagram','x'] %}<option {{ 'selected' if r.platform == p }}>{{ p }}</option>{% endfor %}</select>
<input name="url" placeholder="Link to the post" value="{{ r.post_url }}" style="flex:1"><input name="by" placeholder="Who posted" value="{{ r.posted_by }}" size="10"><button class="ghost">Save post</button></form>
<form method="post" action="/clip/{{ r.clip_id }}/views" class="row"><span class="muted">Views after 7 days, approved views, payout:</span><input name="views" placeholder="Views after 7 days" value="{{ r.views_7d }}" size="14">
<input name="approved" placeholder="Approved views" value="{{ r.approved_views }}" size="12"><input name="payout" placeholder="Payout $" value="{{ r.payout_usd }}" size="8"><button class="ghost">Save numbers</button></form>
</div></div>{% else %}<p class="muted">No clips yet. Make some from a campaign.</p>{% endfor %}
<script>
function copyCap(id,b){const t=document.getElementById(id).textContent;
 navigator.clipboard.writeText(t).then(()=>{b.textContent='Copied';setTimeout(()=>b.textContent='Copy caption',1500)})
 .catch(()=>{const r=document.createRange();r.selectNodeContents(document.getElementById(id));const s=getSelection();s.removeAllRanges();s.addRange(r);});}
</script>"""

STATS = """<h1>What's working</h1><div class="panel"><pre>{{ out }}</pre>
<p class="muted">For the full weekly review, ask Claude Code: "run the clip-analyst skill".</p></div>"""


def render_page(body, **ctx):
    return render_template_string(PAGE.replace("@@BODY@@", body), **ctx)


if __name__ == "__main__":
    duocut.WORK.mkdir(exist_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    print(f"DuoCut Studio running at {url}  (Ctrl+C to stop)")
    if not os.environ.get("DUOCUT_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
