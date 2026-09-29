#!/usr/bin/env python3
"""DuoCut clip pipeline.

Claude drives this through the skills in .claude/skills/. A person can also run it by hand:

  python scripts/duocut.py new <campaign>                 # work folder + brief template
  python scripts/duocut.py transcribe <video>             # word timings + readable transcript
  python scripts/duocut.py cut <cuts.json>                # render approved cuts into queue/clips/
  python scripts/duocut.py posted <clip_id> <platform> <url>
  python scripts/duocut.py views <clip_id> <views_7d> [approved_views] [payout_usd]
  python scripts/duocut.py stats                          # what is working, for the clip-analyst skill

Nothing here uploads or posts anything.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
QUEUE = ROOT / "queue" / "clips"
LOG = ROOT / "data" / "clip-log.csv"
LOG_FIELDS = ["date", "clip_id", "campaign", "source", "start", "end", "hook", "score",
              "platform", "posted_by", "post_url", "views_7d", "approved_views", "payout_usd", "notes"]

W, H = 1080, 1920


# ---------- helpers ----------

def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("ffmpeg not found. Install it (https://ffmpeg.org) or run: pip install imageio-ffmpeg")


def to_seconds(t):
    """Accept 83.4, "83.4", "1:23.4" or "00:01:23.4"."""
    if isinstance(t, (int, float)):
        return float(t)
    parts = [float(p) for p in str(t).strip().split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def stamp(s):
    m, sec = divmod(max(s, 0), 60)
    h, m = divmod(int(m), 60)
    return f"{h:02d}:{m:02d}:{sec:04.1f}" if h else f"{m:02d}:{sec:04.1f}"


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "campaign"


def read_log():
    if not LOG.exists():
        return []
    with LOG.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_log(rows):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LOG_FIELDS})


# ---------- new ----------

BRIEF_TEMPLATE = """# Campaign: {name}

Paste the full campaign page below this line, then ask Claude to run the campaign-brief skill.

---
"""


def cmd_new(a):
    d = WORK / slugify(a.campaign)
    d.mkdir(parents=True, exist_ok=True)
    brief = d / "campaign.md"
    if not brief.exists():
        brief.write_text(BRIEF_TEMPLATE.format(name=a.campaign), encoding="utf-8")
    print(f"Work folder: {d}\nPut the source video in it and paste the campaign page into {brief.name}.")


# ---------- transcribe ----------

def cmd_transcribe(a):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("Run: pip install faster-whisper")
    src = Path(a.video)
    model = WhisperModel(a.model, device="auto", compute_type="int8")
    segments, info = model.transcribe(str(src), word_timestamps=True, vad_filter=True,
                                      language=a.language)
    segs = []
    for s in segments:
        segs.append({
            "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
            "words": [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
                      for w in (s.words or []) if w.word.strip()],
        })
        print(f"  [{stamp(s.start)}] {s.text.strip()}", flush=True)
    out = src.with_suffix(".words.json")
    out.write_text(json.dumps({"source": src.name, "language": info.language,
                               "duration": round(info.duration, 2), "segments": segs},
                              ensure_ascii=False), encoding="utf-8")
    txt = src.with_suffix(".transcript.txt")
    txt.write_text(render_transcript(segs), encoding="utf-8")
    print(f"\nWrote {out.name} and {txt.name}")


def render_transcript(segs):
    """One line per segment with a timestamp Claude can quote back into cuts.json."""
    return "\n".join(f"[{stamp(s['start'])} - {stamp(s['end'])}] {s['text']}" for s in segs) + "\n"


# ---------- captions ----------

def ass_escape(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def ass_time(s):
    s = max(s, 0)
    h = int(s // 3600)
    m = int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def group_words(words, max_words=3, max_gap=0.6):
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["s"] - cur[-1]["e"] > max_gap
                    or re.search(r"[.!?,;:]$", cur[-1]["w"])):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words, clip_len, hook_text=None, hook_secs=3.0, handle="@duocutclips",
              font="Arial", upper=True):
    """Word-by-word captions, current word highlighted, plus an optional hook banner."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,620,1
Style: Hook,{font},64,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,260,1
Style: Handle,{font},34,&H99FFFFFF,&H99FFFFFF,&H99000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,2,40,40,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    hi = "{\\c&H00E5FF&}"   # yellow (ASS colours are BGR)
    norm = "{\\c&HFFFFFF&}"
    groups = group_words(words)
    for gi, g in enumerate(groups):
        nxt = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else None
        for i, w in enumerate(g):
            start = w["s"]
            end = g[i + 1]["s"] if i + 1 < len(g) else max(w["e"], w["s"] + 0.2)
            if i + 1 == len(g) and nxt is not None and nxt - end < 0.7:
                end = nxt  # hold the line through short pauses so captions don't flicker
            parts = []
            for j, x in enumerate(g):
                t = ass_escape(x["w"].upper() if upper else x["w"])
                parts.append(f"{hi}{t}{norm}" if j == i else t)
            ev.append(f"Dialogue: 1,{ass_time(start)},{ass_time(min(end, clip_len))},Cap,,0,0,0,,{' '.join(parts)}")
    if hook_text:
        ev.append(f"Dialogue: 2,{ass_time(0)},{ass_time(min(hook_secs, clip_len))},Hook,,0,0,0,,{ass_escape(hook_text)}")
    if handle:
        ev.append(f"Dialogue: 0,{ass_time(0)},{ass_time(clip_len)},Handle,,0,0,0,,{ass_escape(handle)}")
    return header + "\n".join(ev) + "\n"


def words_in_range(words_json, start, end):
    out = []
    for seg in words_json["segments"]:
        for w in seg["words"]:
            if w["s"] >= start - 0.05 and w["e"] <= end + 0.25:
                out.append({"w": w["w"], "s": round(w["s"] - start, 3), "e": round(min(w["e"], end) - start, 3)})
    return out


# ---------- cut ----------

def video_filter(mode, x_center):
    if mode == "blur":
        return (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,setsar=1[bg];"
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,ass=captions.ass[v]")
    if mode == "crop":
        return (f"[0:v]scale=-2:{H},crop={W}:{H}:(iw-{W})*{x_center}:0,setsar=1,ass=captions.ass[v]")
    sys.exit(f"Unknown reframe mode: {mode} (use blur or crop)")


def cmd_cut(a):
    cuts_path = Path(a.cuts)
    spec = json.loads(cuts_path.read_text(encoding="utf-8"))
    src = (cuts_path.parent / spec["source"]).resolve()
    if not src.exists():
        sys.exit(f"Source video not found: {src}")
    words_path = src.with_suffix(".words.json")
    words_json = json.loads(words_path.read_text(encoding="utf-8")) if words_path.exists() else None
    if words_json is None:
        print(f"No {words_path.name}: clips will have no captions. Run transcribe first.")
    campaign = slugify(spec.get("campaign", cuts_path.parent.name))
    todo = [c for c in spec["cuts"] if c.get("approved") and not c.get("rendered")]
    if not todo:
        sys.exit('No cuts marked "approved": true that are not rendered yet.')
    ff = ffmpeg_exe()
    rows = read_log()
    today = dt.date.today().isoformat()
    for c in todo:
        start, end = to_seconds(c["start"]), to_seconds(c["end"])
        if end <= start:
            print(f"  skip cut {c.get('id')}: end is before start")
            continue
        length = end - start
        n = sum(1 for r in rows if r.get("campaign") == campaign) + 1
        clip_id = f"{today}-{campaign}-{n:02d}"
        out = QUEUE / clip_id
        out.mkdir(parents=True, exist_ok=True)
        words = words_in_range(words_json, start, end) if words_json else []
        (out / "captions.ass").write_text(
            build_ass(words, length, c.get("hook_text"), float(c.get("hook_secs", 3)),
                      spec.get("handle", "@duocutclips"), spec.get("font", "Arial")),
            encoding="utf-8")
        mode = c.get("reframe", spec.get("reframe", "blur"))
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src),
               "-filter_complex", video_filter(mode, float(c.get("x_center", 0.5))),
               "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", a.preset, "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
               "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
               "-movflags", "+faststart", "final.mp4"]
        print(f"  rendering {clip_id} ({stamp(start)} to {stamp(end)}, {length:.1f}s, {mode})", flush=True)
        r = subprocess.run(cmd, cwd=out, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-2000:])
            sys.exit(f"ffmpeg failed on cut {c.get('id')}")
        (out / "caption.txt").write_text(c.get("caption", "").strip() + "\n", encoding="utf-8")
        (out / "README.md").write_text(checklist(clip_id, c, spec, stamp(start), stamp(end)), encoding="utf-8")
        rows.append({"date": today, "clip_id": clip_id, "campaign": campaign, "source": spec["source"],
                     "start": stamp(start), "end": stamp(end), "hook": c.get("hook_text", ""),
                     "score": c.get("score", "")})
        c["rendered"] = clip_id
    write_log(rows)
    cuts_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. Review the clips in {QUEUE.relative_to(ROOT)}/ before posting.")


def checklist(clip_id, c, spec, s, e):
    rules = spec.get("rules", [])
    lines = [f"# {clip_id}", "", f"Source: {spec['source']} from {s} to {e}",
             f"Hook: {c.get('hook_text', '')}", f"Why: {c.get('why', '')}", "",
             "## Before posting (a person does this)", "",
             "- [ ] Watched the whole clip with sound",
             "- [ ] Captions are correct (names, numbers, slang)",
             "- [ ] Nothing in it breaks the campaign rules below",
             "- [ ] Caption and required tags copied from caption.txt",
             "- [ ] Posted by hand or with the platform's own scheduler",
             f"- [ ] Logged: python scripts/duocut.py posted {clip_id} <platform> <url>", ""]
    if rules:
        lines += ["## Campaign rules", ""] + [f"- {r}" for r in rules] + [""]
    return "\n".join(lines)


# ---------- tracking ----------

def update_row(clip_id, **fields):
    rows = read_log()
    hit = [r for r in rows if r.get("clip_id") == clip_id]
    if not hit:
        sys.exit(f"No clip {clip_id} in {LOG.relative_to(ROOT)}")
    hit[0].update({k: v for k, v in fields.items() if v is not None})
    write_log(rows)
    print(f"Updated {clip_id}")


def cmd_posted(a):
    update_row(a.clip_id, platform=a.platform, post_url=a.url, posted_by=a.by or os.environ.get("DUOCUT_USER", ""))


def cmd_views(a):
    update_row(a.clip_id, views_7d=a.views, approved_views=a.approved, payout_usd=a.payout)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def cmd_stats(a):
    rows = [r for r in read_log() if num(r.get("views_7d")) is not None]
    if not rows:
        print("No clips with views logged yet.")
        return
    print(f"{len(rows)} clips with views logged\n")
    by = {}
    for r in rows:
        for key in ("campaign", "platform"):
            by.setdefault((key, r.get(key) or "?"), []).append(r)
    for (key, val), rs in sorted(by.items()):
        v = [num(r["views_7d"]) for r in rs]
        pay = sum(num(r.get("payout_usd")) or 0 for r in rs)
        print(f"{key:9} {val:28} clips {len(rs):3}  median views {sorted(v)[len(v)//2]:>9,.0f}  payout ${pay:,.2f}")
    top = sorted(rows, key=lambda r: num(r["views_7d"]), reverse=True)
    print("\nTop 5 hooks:")
    for r in top[:5]:
        print(f"  {num(r['views_7d']):>9,.0f}  {r.get('hook','')}  ({r['clip_id']})")
    if len(top) > 10:
        print("\nBottom 5 hooks:")
        for r in top[-5:]:
            print(f"  {num(r['views_7d']):>9,.0f}  {r.get('hook','')}  ({r['clip_id']})")
    scored = [r for r in rows if num(r.get("score")) is not None]
    if len(scored) >= 5:
        hi = [num(r["views_7d"]) for r in scored if num(r["score"]) >= 8]
        lo = [num(r["views_7d"]) for r in scored if num(r["score"]) < 8]
        if hi and lo:
            print(f"\nClaude score 8+: avg {sum(hi)/len(hi):,.0f} views ({len(hi)} clips); "
                  f"under 8: avg {sum(lo)/len(lo):,.0f} ({len(lo)} clips)")


def main():
    p = argparse.ArgumentParser(description="DuoCut clip pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new"); s.add_argument("campaign"); s.set_defaults(f=cmd_new)
    s = sub.add_parser("transcribe"); s.add_argument("video")
    s.add_argument("--model", default="small", help="tiny, base, small, medium, large-v3 (bigger = slower, better)")
    s.add_argument("--language", default=None); s.set_defaults(f=cmd_transcribe)
    s = sub.add_parser("cut"); s.add_argument("cuts")
    s.add_argument("--preset", default="medium"); s.set_defaults(f=cmd_cut)
    s = sub.add_parser("posted"); s.add_argument("clip_id"); s.add_argument("platform"); s.add_argument("url")
    s.add_argument("--by"); s.set_defaults(f=cmd_posted)
    s = sub.add_parser("views"); s.add_argument("clip_id"); s.add_argument("views")
    s.add_argument("approved", nargs="?"); s.add_argument("payout", nargs="?"); s.set_defaults(f=cmd_views)
    s = sub.add_parser("stats"); s.set_defaults(f=cmd_stats)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
