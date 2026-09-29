// DuoCut Studio front end. Plain JS, no build step.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function toast(msg, ms = 2200) {
  const t = $("#toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), ms);
}

async function post(url, data, json = false) {
  const opts = { method: "POST", headers: { "X-Requested-With": "fetch" } };
  if (json) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(data);
  } else {
    opts.body = data instanceof FormData ? data : new URLSearchParams(data);
  }
  const r = await fetch(url, opts);
  let body = {};
  try { body = await r.json(); } catch (_) { /* not json */ }
  if (!r.ok || body.ok === false) throw new Error(body.error || `Request failed (${r.status})`);
  return body;
}

// ---------- time helpers ----------
function toSec(t) {
  const parts = String(t).trim().split(":").map(Number);
  if (parts.some(isNaN)) return NaN;
  return parts.reduce((a, p) => a * 60 + p, 0);
}
function fmt(s) {
  s = Math.max(0, s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = (s % 60).toFixed(1).padStart(4, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${String(m).padStart(2, "0")}:${sec}`;
}
function dur(s) { return s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`; }

// ---------- jobs ----------
const JOB_TITLES = {
  analyze: "Analyzing the video",
  find: "Claude is reading the campaign and finding moments",
  render: "Rendering your clips",
};

function renderJob(j) {
  const box = $("#jobbox");
  if (!box || !j) return;
  const running = !j.done;
  const failed = j.done && j.rc !== 0;
  if (j.done && !failed && j.elapsed_since_end > 60) { box.innerHTML = ""; return; }
  const pct = j.progress;
  const indet = running && (pct === null || pct === undefined);
  const title = failed ? "That didn't work" : running ? JOB_TITLES[j.kind] || "Working" : "Done";
  const feed = (j.kind === "find" ? j.log.filter((l) => l.startsWith("• ")).slice(-6) : []).map((l) => `<span>${esc(l)}</span>`).join("");
  box.innerHTML = `
    <div class="job ${failed ? "err" : j.done ? "ok" : ""}">
      <div class="row between">
        <div class="row">${running ? '<span class="spin"></span>' : failed ? '<span class="chip err">Failed</span>' : '<span class="chip done">Done</span>'}
          <span class="status">${esc(title)}</span></div>
        <span class="faint mono" style="font-size:12px">${dur(j.elapsed)}${j.steps > 1 ? ` · part ${j.step} of ${j.steps}` : ""}</span>
      </div>
      ${running || !failed ? `<div class="meter ${indet ? "indet" : ""}"><i style="width:${pct || 0}%"></i></div>` : ""}
      <div class="muted">${esc(failed ? j.error : j.done ? (j.result ? j.result.split("\n").slice(-1)[0] : "Finished.") : j.status)}</div>
      ${feed ? `<div class="feed">${feed}</div>` : ""}
      ${j.kind === "find" && running ? '<div class="faint" style="font-size:12.5px">This usually takes 1 to 4 minutes. You can leave this page open and do something else.</div>' : ""}
      <details class="tech"><summary>Technical details</summary><pre>${esc(j.log.join("\n") || "No output yet.")}</pre></details>
    </div>`;
}

function watchJob(id, { reload = true } = {}) {
  if (!id) return;
  const tick = async () => {
    let j;
    try { j = await (await fetch(`/job/${id}`)).json(); } catch (_) { return setTimeout(tick, 2500); }
    renderJob(j);
    if (!j.done) return setTimeout(tick, 1200);
    if (j.rc === 0) {
      toast(j.kind === "render" ? "Clips ready" : j.kind === "find" ? "Moments ready" : "Analysis done");
      if (reload) setTimeout(() => (location.href = location.pathname + (j.kind === "render" ? "#clips" : j.kind === "find" ? "#moments" : "#moments")), 700);
    }
    $$("button[data-busy]").forEach((b) => (b.disabled = false));
  };
  tick();
}

function startedJob(id) {
  $$("#analyzeform button, #findbtn, #renderbtn").forEach((b) => b.setAttribute("disabled", ""));
  $("#jobbox").scrollIntoView({ behavior: "smooth", block: "start" });
  watchJob(id);
}

// ---------- campaign page ----------
function initCampaign() {
  const D = window.DUO;
  const base = `/c/${D.slug}`;

  // open the step a stepper link points at
  $$(".stepper a").forEach((a) => a.addEventListener("click", () => { const d = $("#" + a.dataset.open); if (d) d.open = true; }));
  if (location.hash) { const d = $(location.hash); if (d && d.tagName === "DETAILS") d.open = true; }

  if (D.job) {
    renderJob(D.job);
    if (!D.job.done) watchJob(D.job.id);
  }

  // 1. campaign page
  $("#pageform")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await post(`${base}/page`, new FormData(e.target));
      toast("Campaign page saved");
      setTimeout(() => location.reload(), 500);
    } catch (err) { toast(err.message, 4000); }
  });

  // 2. upload with progress
  const drop = $("#drop"), file = $("#file");
  if (drop) {
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
    file.addEventListener("change", () => file.files[0] && upload(file.files[0]));
  }
  function upload(f) {
    const bar = $("#upbar"), txt = $("#uptext");
    bar.style.display = "block";
    const fd = new FormData();
    fd.append("video", f);
    const x = new XMLHttpRequest();
    x.open("POST", `${base}/upload`);
    x.setRequestHeader("X-Requested-With", "fetch");
    x.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const p = Math.round((e.loaded / e.total) * 100);
      $("i", bar).style.width = p + "%";
      txt.textContent = `Uploading ${f.name}: ${p}% of ${(e.total / 1048576).toFixed(0)} MB`;
    };
    x.onload = () => {
      let r = {};
      try { r = JSON.parse(x.responseText); } catch (_) { /* ignore */ }
      if (x.status === 200 && r.ok) { txt.textContent = "Uploaded"; toast("Video added"); location.hash = "analyze"; setTimeout(() => location.reload(), 400); }
      else txt.textContent = r.error || `Upload failed (${x.status})`;
    };
    x.onerror = () => (txt.textContent = "Upload failed. Is the app still running?");
    x.send(fd);
  }

  // 3. analyze
  $("#analyzeform")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    if (e.submitter?.name === "only") fd.append("only", "scan");
    try { const r = await post(`${base}/analyze`, fd); startedJob(r.job); } catch (err) { toast(err.message, 4000); }
  });

  // 4. find moments
  $("#findbtn")?.addEventListener("click", async (e) => {
    if (e.currentTarget.dataset.replace === "1" && dirty && !window.confirmReplace) {
      toast("Save or render your picks first: finding again replaces this list", 4000);
      window.confirmReplace = true;
      return;
    }
    try { const r = await post(`${base}/find`, {}); startedJob(r.job); } catch (err) { toast(err.message, 4000); }
  });

  // moments editor
  let cuts = (D.cuts || []).map((c) => ({ ...c }));
  let dirty = false;
  const list = $("#moments-list");
  const src = D.source ? `/media/work/${D.slug}/${encodeURIComponent(D.source)}` : "";

  function markDirty() { dirty = true; const d = $("#dirty"); if (d) d.textContent = "· unsaved changes"; updateCount(); }
  function updateCount() {
    const n = cuts.filter((c) => c.approved && (!c.rendered || c.remake)).length;
    const pc = $("#pickcount"); if (pc) pc.textContent = n;
    const rb = $("#renderbtn"); if (rb && !rb.hasAttribute("data-locked")) rb.textContent = n ? `Render ${n} clip${n > 1 ? "s" : ""}` : "Render picked clips";
  }

  function card(c, i) {
    const s = toSec(c.start), e = toSec(c.end), len = e - s;
    const made = c.rendered && !c.remake;
    return `
    <div class="moment ${c.approved && !made ? "picked" : ""} ${made ? "made" : ""}" data-i="${i}">
      <div class="stack" style="gap:8px">
        <div class="player">${src ? `<video preload="metadata" src="${src}#t=${isNaN(s) ? 0 : s}" data-s="${s}" data-e="${e}"></video>` : ""}
          <span class="len">${isNaN(len) ? "?" : dur(len)}</span></div>
        <div class="row"><button class="small ghost" type="button" data-act="play">▶ Preview</button>
          <span class="faint mono" style="font-size:12px">${esc(c.start)} → ${esc(c.end)}</span></div>
      </div>
      <div class="stack" style="gap:10px">
        <div class="row between">
          <div class="row">${c.score ? `<span class="score">${esc(c.score)}<small>/10</small></span>` : '<span class="chip">Added by hand</span>'}
            ${made ? `<span class="chip done">Made</span>` : ""}</div>
          ${made
            ? `<button class="small ghost" type="button" data-act="remake">Make again</button>`
            : `<label class="pick"><input type="checkbox" data-f="approved" ${c.approved ? "checked" : ""}> Make this clip</label>`}
        </div>
        ${c.why ? `<p class="why">${esc(c.why)}</p>` : ""}
        <label class="field">Hook on screen (first 3 seconds)
          <input data-f="hook_text" value="${esc(c.hook_text)}" placeholder="Short and specific, 8 words max"></label>
        <label class="field">Post caption
          <textarea data-f="caption" rows="3" placeholder="Caption, required tags and hashtags">${esc(c.caption)}</textarea></label>
        <div class="row between">
          <div class="times">
            <span class="faint" style="font-size:12.5px">Start</span>
            <button class="icon" type="button" data-nudge="start" data-d="-0.5">−½s</button>
            <input class="time" data-f="start" value="${esc(c.start)}">
            <button class="icon" type="button" data-nudge="start" data-d="0.5">+½s</button>
            <span class="faint" style="font-size:12.5px;margin-left:8px">End</span>
            <button class="icon" type="button" data-nudge="end" data-d="-0.5">−½s</button>
            <input class="time" data-f="end" value="${esc(c.end)}">
            <button class="icon" type="button" data-nudge="end" data-d="0.5">+½s</button>
          </div>
          <div class="seg" role="radiogroup" aria-label="Framing">
            <label><input type="radio" name="rf${i}" value="blur" data-f="reframe" ${c.reframe !== "crop" ? "checked" : ""}><span>Full frame</span></label>
            <label><input type="radio" name="rf${i}" value="crop" data-f="reframe" ${c.reframe === "crop" ? "checked" : ""}><span>Crop to center</span></label>
          </div>
        </div>
      </div>
    </div>`;
  }

  function draw() {
    if (!list) return;
    list.innerHTML = cuts.length ? cuts.map(card).join("") : "";
    updateCount();
  }

  list?.addEventListener("input", (e) => {
    const el = e.target, m = el.closest(".moment");
    if (!m || !el.dataset.f) return;
    const c = cuts[+m.dataset.i];
    c[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value;
    if (el.dataset.f === "approved") m.classList.toggle("picked", el.checked);
    markDirty();
  });
  list?.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const m = b.closest(".moment"), c = cuts[+m.dataset.i];
    if (b.dataset.nudge) {
      const k = b.dataset.nudge, v = toSec(c[k]);
      if (isNaN(v)) return;
      c[k] = fmt(v + parseFloat(b.dataset.d));
      $(`input[data-f="${k}"]`, m).value = c[k];
      markDirty();
    } else if (b.dataset.act === "play") {
      const v = $("video", m); if (!v) return;
      const s = toSec(c.start), en = toSec(c.end);
      v.currentTime = s;
      v.play();
      v.ontimeupdate = () => { if (v.currentTime >= en) { v.pause(); v.currentTime = s; } };
    } else if (b.dataset.act === "remake") {
      c.remake = true; c.approved = true; markDirty(); draw();
    }
  });
  $("#addmoment")?.addEventListener("click", () => {
    cuts.push({ id: "", start: "00:00.0", end: "00:20.0", hook_text: "", caption: "", reframe: "blur", approved: true });
    markDirty(); draw();
    list.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  async function save(render) {
    try {
      const r = await post(`${base}/cuts`, { cuts, render }, true);
      dirty = false; const d = $("#dirty"); if (d) d.textContent = "";
      if (render && r.job) { toast("Rendering started"); startedJob(r.job); }
      else { toast("Saved"); if (!render) setTimeout(() => location.reload(), 400); }
    } catch (err) { toast(err.message, 4500); }
  }
  $("#savecuts")?.addEventListener("click", () => save(false));
  $("#renderbtn")?.addEventListener("click", () => save(true));
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  draw();
}

// ---------- clips queue ----------
function initQueue() {
  $$("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    const text = $("#" + b.dataset.copy).textContent;
    try { await navigator.clipboard.writeText(text); toast("Caption copied"); }
    catch (_) {
      const r = document.createRange(); r.selectNodeContents($("#" + b.dataset.copy));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r); toast("Press Ctrl+C to copy");
    }
  }));
  $$("form[data-ajax]").forEach((f) => f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await post(f.action, new FormData(f)); toast(f.dataset.ajax); setTimeout(() => location.reload(), 600); }
    catch (err) { toast(err.message, 4000); }
  }));
}
