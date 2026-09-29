---
name: make-clips
description: Run the whole DuoCut clip pipeline for one campaign and one source video, from brief to finished clips in the approval queue. Use when a person says "make clips", names a campaign, or drops a new source video in work/.
---

# Make clips (the DuoCut run)

The pipeline has four stops. Two of them wait for a person. Never skip a stop.

1. **Brief** → run the `campaign-brief` skill on `work/<campaign>/campaign.md`.
   If the verdict is NO-GO, stop and say why.
2. **Analyze** → if `work/<campaign>/<video>.transcript.txt` does not exist, run
   `python scripts/duocut.py transcribe work/<campaign>/<video>` (use `--model medium` for music, accents or noisy audio).
   If `work/<campaign>/<video>.scan.txt` does not exist, run `python scripts/duocut.py scan work/<campaign>/<video>`.
   The scan makes contact sheets and a loudness/action timeline, which matter most for gameplay with little talking.
3. **Moments** → run the `clip-finder` skill. It writes `work/<campaign>/cuts.json` with every cut set to `"approved": false`.
   Then run `caption-writer` to fill each cut's `caption`.
   **Stop here.** Show the person a numbered list: time range, hook text, score, one-line why. Ask which numbers to make.
4. **Render** → set `"approved": true` only on the numbers the person picked, then run
   `python scripts/duocut.py cut work/<campaign>/cuts.json`.
   Tell the person the clips are in `queue/clips/` and each folder's README has the posting checklist.

The person watches each clip, fixes anything in CapCut if needed, and posts it by hand or with the platform's own scheduler.
After posting they (or you, when they give you the link) run `python scripts/duocut.py posted <clip_id> <platform> <url>`.

Never upload, post, schedule, or log in to TikTok, YouTube, Instagram, Whop or Content Rewards.
