"""Generated sample media and a demo campaign so the app works immediately, offline, with no API keys.

Everything is synthesised with FFmpeg's lavfi sources (no downloaded or copyrighted material):
* 3 "gameplay" clips (MP4 landscape, WEBM landscape, MOV portrait) with deliberate high-action,
  calm, static, black and repeated sections so the analyser has something real to find.
* a sound-effect set covering every category, and a royalty-free generated music loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .analysis import analyze_media
from .campaigns import add_document, create_campaign
from .config import Settings
from .db import Database
from .ffmpeg import run_ffmpeg
from .media import import_media

DEMO_BRIEF = """Campaign: Seed Heist Simulator — Launch Clips (DEMO)
Game: Seed Heist Simulator
Objective: Get new players to try Seed Heist Simulator on Roblox during launch week.
Platforms: TikTok, Instagram Reels and YouTube Shorts.
Payout: $1.50 per 1,000 views, paid through the campaign dashboard.

Requirements:
- Videos must be 20-40 seconds long.
- You must mention the game name "Seed Heist Simulator" in the voiceover or captions.
- Include the creator code HEIST50 so viewers get the launch bonus.
- Add the hashtag #SeedHeist to your post caption.
- Use your own gameplay footage recorded in the game.
- End with a call to action telling viewers to play now.

Restrictions:
- Do not show other Roblox games.
- Do not use copyrighted music.
- No swearing or misleading claims about free Robux.
- Reuploads of other creators' clips will be rejected.

Content ideas we like: rare seed drops, stealing strategy, fastest progression, beginner mistakes.
Target audience: Roblox players aged 10-16 who like simulator and tycoon games.
"""

DEMO_NOTES = """Hook examples from the brand:
"I stole the rarest seed in the game."
"Nobody knows this Seed Heist trick."
"""

SFX_SPECS: dict[str, tuple[str, float]] = {
    "impact": ("0.9*sin(2*PI*(60+140*exp(-18*t))*t)*exp(-7*t)+0.25*(random(0)*2-1)*exp(-30*t)", 0.6),
    "whoosh": ("0.5*(random(0)*2-1)*sin(PI*t/0.45)*sin(PI*t/0.45)", 0.45),
    "click": ("0.8*sin(2*PI*2400*t)*exp(-120*t)", 0.08),
    "pop": ("0.8*sin(2*PI*(900-500*t/0.12)*t)*exp(-25*t)", 0.14),
    "success": ("0.35*(sin(2*PI*523*t)*lt(t,0.12)+sin(2*PI*659*t)*between(t,0.12,0.24)+sin(2*PI*784*t)*between(t,0.24,0.6))*exp(-2*(t-0.24)*gt(t,0.24))", 0.6),
    "fail": ("0.4*sin(2*PI*(440-260*t/0.6)*t)*exp(-2.5*t)", 0.6),
    "transition": ("0.35*(random(0)*2-1)*(t/0.5)*(t/0.5)+0.3*sin(2*PI*(200+900*t)*t)*(t/0.5)", 0.5),
    "notification": ("0.4*(sin(2*PI*880*t)*lt(t,0.12)+sin(2*PI*1320*t)*between(t,0.14,0.4))*exp(-4*t)", 0.4),
    "comedic": ("0.5*sin(2*PI*(300+150*sin(2*PI*12*t))*t)*exp(-3*t)", 0.5),
    "gameplay": ("0.4*(sin(2*PI*988*t)*lt(t,0.07)+sin(2*PI*1319*t)*between(t,0.07,0.25))*exp(-6*t)", 0.25),
}


def _gameplay_a(ffmpeg: str, out: Path) -> None:
    """24 s, 1920x1080 MP4 with moderate/static/high-action/black/repeated/scrolling sections."""
    font = "fontcolor=white:fontsize=64:box=1:boxcolor=black@0.5:boxborderw=12"
    graph = (
        "[0:v]drawtext=text='SEED FARM':x=60:y=60:" + font + ",split=2[s1][s1b];"
        "[1:v]drawtext=text='SHOP (idle)':x=(w-tw)/2:y=(h-th)/2:" + font + "[s2];"
        "[2:v]scale=1920:1080:flags=neighbor,drawtext=text='HEIST!':x=60:y=60:" + font + "[s3];"
        "[3:v]null[s4];"
        "[s1b]trim=0:4,setpts=PTS-STARTPTS[s5];"
        "[4:v]scale=1920:1080:flags=neighbor,drawtext=text='ESCAPE':x=60:y=60:" + font + "[s6];"
        "[s1][s2][s3][s4][s5][s6]concat=n=6:v=1:a=0,format=yuv420p[v];"
        "[5:a]volume=1[a]"
    )
    audio = ("0.25*sin(2*PI*220*t)*(lt(t,6)+between(t,15,19))"
             "+0.5*sin(2*PI*330*t)*between(t,9,14)*(0.4+0.6*gt(mod(t,1),0.8))"
             "+0.15*sin(2*PI*262*t)*between(t,19,24)"
             "+0.6*(random(0)*2-1)*between(t,11.5,11.8)")
    run_ffmpeg(ffmpeg, [
        "-y",
        "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=6",
        "-f", "lavfi", "-i", "color=c=0x2d6a4f:s=1920x1080:r=30:d=3",
        "-f", "lavfi", "-i", "life=s=480x270:r=30:mold=10:ratio=0.35:death_color=#101010:life_color=#ffcc00,trim=0:5",
        "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=30:d=1",
        "-f", "lavfi", "-i", "cellauto=s=480x270:r=30:rule=110:scroll=1,trim=0:5",
        "-f", "lavfi", "-i", f"aevalsrc='{audio}':s=48000:d=24",
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(out),
    ], what="Generating sample gameplay A", timeout=300)


def _gameplay_b(ffmpeg: str, out: Path) -> None:
    """12 s, 1280x720 WEBM (VP9/Opus): mandelbrot zoom (smooth motion) + moving boxes."""
    run_ffmpeg(ffmpeg, [
        "-y", "-f", "lavfi", "-i", "mandelbrot=s=1280x720:r=30,trim=0:6,setpts=PTS-STARTPTS",
        "-f", "lavfi", "-i", "color=c=0x1b263b:s=1280x720:r=30:d=6",
        "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*196*t)*(0.5+0.5*sin(2*PI*0.5*t))':s=48000:d=12",
        "-filter_complex",
        "[1:v]drawtext=text='RARE SEED DROP':x=(w-tw)/2:y=h-120:fontcolor=white:fontsize=56[bg];"
        "color=c=0xffd60a:s=160x160:r=30:d=6[box1];color=c=0xef476f:s=90x90:r=30:d=6[box2];"
        "[bg][box1]overlay=x='mod(t*420,1120)':y=300[b1];[b1][box2]overlay=x='1100-mod(t*300,1100)':y=120[b];"
        "[0:v][b]concat=n=2:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "1M",
        "-c:a", "libopus", "-b:a", "96k", "-shortest", str(out),
    ], what="Generating sample gameplay B", timeout=300)


def _gameplay_c(ffmpeg: str, out: Path) -> None:
    """10 s, 1080x1920 portrait MOV: vertical phone-style recording."""
    run_ffmpeg(ffmpeg, [
        "-y", "-f", "lavfi", "-i", "testsrc=s=1080x1920:r=30:d=10",
        "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*440*t)*gt(mod(t,2),1.6)':s=48000:d=10",
        "-vf", "hue=h=t*36,drawtext=text='PORTRAIT RUN':x=(w-tw)/2:y=200:fontcolor=white:fontsize=80:box=1:boxcolor=black@0.5",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
    ], what="Generating sample gameplay C", timeout=300)


def generate_sfx(ffmpeg: str, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for cat, (expr, dur) in SFX_SPECS.items():
        ext = "ogg" if cat in ("pop", "comedic") else "mp3" if cat in ("whoosh", "notification") else "wav"
        path = out_dir / f"{cat}.{ext}"
        if not path.exists():
            codec = ["-c:a", "libvorbis"] if ext == "ogg" else ["-c:a", "libmp3lame", "-q:a", "4"] if ext == "mp3" else []
            run_ffmpeg(ffmpeg, ["-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={dur}", "-ac", "2", *codec, str(path)],
                       what=f"Generating SFX {cat}", timeout=60)
        files[cat] = path
    return files


def generate_music(ffmpeg: str, out: Path) -> Path:
    """16 s royalty-free loop: four-chord progression with a soft pulse."""
    if out.exists():
        return out
    chords = [(261.63, 329.63, 392.0), (220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66)]
    terms = []
    for i, (a, b, c) in enumerate(chords):
        env = f"between(mod(t,16),{i * 4},{i * 4 + 4})*(0.6+0.4*exp(-3*mod(t,0.6)))"
        terms.append(f"{env}*(sin(2*PI*{a}*t)+sin(2*PI*{b}*t)+0.8*sin(2*PI*{c}*t)+0.5*sin(2*PI*{a / 2}*t))")
    expr = "0.09*(" + "+".join(terms) + ")"
    run_ffmpeg(ffmpeg, ["-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d=16", "-ac", "2",
                        "-c:a", "libmp3lame", "-q:a", "4", str(out)], what="Generating music loop", timeout=120)
    return out


def generate_sample_media(settings: Settings) -> dict[str, Any]:
    d = settings.data_dir / "samples"
    d.mkdir(parents=True, exist_ok=True)
    clips = {"gameplay_a.mp4": _gameplay_a, "gameplay_b.webm": _gameplay_b, "gameplay_c.mov": _gameplay_c}
    paths = {}
    for name, fn in clips.items():
        p = d / name
        if not p.exists():
            fn(settings.ffmpeg, p)
        paths[name] = p
    sfx = generate_sfx(settings.ffmpeg, d / "sfx")
    music = generate_music(settings.ffmpeg, d / "music_loop.mp3")
    brief = d / "demo_brief.txt"
    brief.write_text(DEMO_BRIEF, encoding="utf-8")
    return {"clips": paths, "sfx": sfx, "music": music, "brief": brief}


def create_demo(db: Database, settings: Settings, *, analyze: bool = True) -> dict[str, Any]:
    """Create (or return) the demo campaign with imported footage, SFX and music."""
    existing = db.list("campaigns", "slug = ?", ["seed-heist-simulator-launch-clips-demo"])
    if existing:
        return {"campaign": existing[0], "created": False}
    files = generate_sample_media(settings)
    campaign = create_campaign(db, {"name": "Seed Heist Simulator — Launch Clips (DEMO)",
                                    "notes": "Demo campaign with generated sample media. Safe to delete.",
                                    "hook_examples": ["I stole the rarest seed in the game.", "Nobody knows this Seed Heist trick."],
                                    "content_goals": ["rare seed drops", "stealing strategy", "fastest progression",
                                                      "beginner mistakes"]})
    try:
        add_document(db, campaign["id"], kind="txt", name="demo_brief.txt", text=files["brief"].read_text(encoding="utf-8"))
        add_document(db, campaign["id"], kind="text", name="Pasted notes", text=DEMO_NOTES)
        media = [import_media(db, settings, p, campaign_id=campaign["id"]) for p in files["clips"].values()]
        sfx = [import_media(db, settings, p, kind="sfx", category=cat, license_note="Generated by Roblox Clip Factory")
               for cat, p in files["sfx"].items()]
        music = import_media(db, settings, files["music"], kind="music",
                             license_note="Generated by Roblox Clip Factory (royalty-free)", display_name="Demo loop (generated)")
        if analyze:
            for m in media:
                analyze_media(db, settings, m["id"])
    except Exception:
        db.delete("campaigns", campaign["id"])  # never leave a half-built demo behind
        raise
    return {"campaign": db.get("campaigns", campaign["id"]), "media": media, "sfx": sfx, "music": music, "created": True}
