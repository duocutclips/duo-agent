"""Command line entry points.

    python -m clipfactory.cli serve            # start the local API (what the desktop app does)
    python -m clipfactory.cli demo [--videos N] [--quality draft|final]
                                               # offline end-to-end demo: campaign -> videos -> QA -> export
    python -m clipfactory.cli status           # show FFmpeg / integration configuration
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import load_settings


def cmd_status(_: argparse.Namespace) -> int:
    from .ffmpeg import check_binaries
    from .llm import ClaudeClient
    from .transcription import status as stt
    from .voice import providers_status

    s = load_settings()
    print(json.dumps({"data_dir": str(s.data_dir), "ffmpeg": check_binaries(s.ffmpeg, s.ffprobe),
                      "llm": ClaudeClient(s).status(), "voice": providers_status(s), "transcription": stt(s)}, indent=2))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from . import projects as P
    from .campaigns import analyze_campaign
    from .db import Database
    from .ideas import generate_ideas
    from .llm import ClaudeClient
    from .logging_setup import setup_logging
    from .qa import format_report
    from .samples import create_demo
    from .variations import variation_report

    s = load_settings(Path(args.data_dir) if args.data_dir else None)
    setup_logging(s.logs_dir)
    db = Database(s.db_path)
    llm = ClaudeClient(s)
    t0 = time.monotonic()
    print("1/5 Creating demo campaign with generated footage, SFX and music...")
    demo = create_demo(db, s)
    cid = demo["campaign"]["id"]
    print("2/5 Analysing campaign...")
    analysis = analyze_campaign(db, llm, cid, use_ai=not args.offline)
    print(f"    generator: {analysis['generator']}; {len(analysis['items'])} items "
          f"({sum(1 for i in analysis['items'] if i['status'] == 'confirmed')} confirmed)")
    print("3/5 Generating ideas...")
    ideas = generate_ideas(db, llm, cid, use_ai=not args.offline)["ideas"]
    print("4/5 Producing videos...")
    ok = True
    pids = []
    for idea in ideas[: args.videos]:
        p = P.create_project(db, cid, idea_id=idea["id"])
        pids.append(p["id"])
        print(f"  - {idea['category']}: {idea['title']}")
        p = P.run_pipeline(db, s, llm, p["id"], use_ai=not args.offline, quality=args.quality,
                           progress=lambda m, f: print(f"      {m}", flush=True) if m.startswith(("Writing", "Generating", "Building", "Rendering", "Running")) and "clip" not in m else None)
        print("\n".join("      " + ln for ln in format_report(p["qa"]).splitlines()))
        if p["qa"]["overall"] != "READY":
            ok = False
            continue
        if args.export:
            P.transition(db, p["id"], "APPROVED", note="demo auto-approval (--export flag)")
            p = P.export_project(db, s, p["id"])
            print(f"      exported: {p['export_path']}")
    print("5/5 Variation report:")
    print(json.dumps(variation_report(db, pids), indent=2))
    print(f"Done in {time.monotonic() - t0:.1f}s. Data: {s.data_dir}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipfactory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="start the local API server")
    sub.add_parser("status", help="show configuration status")
    d = sub.add_parser("demo", help="offline end-to-end demo")
    d.add_argument("--videos", type=int, default=2)
    d.add_argument("--quality", choices=["draft", "final"], default="final")
    d.add_argument("--data-dir", default=None)
    d.add_argument("--offline", action="store_true", help="never call AI services even if keys are configured")
    d.add_argument("--export", action="store_true", help="auto-approve READY demo videos and export them (demo only)")
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        from .server import main as serve

        serve()
        return 0
    if args.cmd == "status":
        return cmd_status(args)
    return cmd_demo(args)


if __name__ == "__main__":
    sys.exit(main())
