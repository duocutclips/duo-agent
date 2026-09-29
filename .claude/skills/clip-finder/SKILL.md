---
name: clip-finder
description: Find the best 20-60 second moments in a transcript and write them to cuts.json, ranked by hook strength. Use inside make-clips after the transcript exists, or when a person asks for clip ideas from a video.
---

# Clip finder

Read, in this order:
1. `work/<campaign>/brief.md`: the rules win over everything below.
2. `examples/winning-hooks.md` if it exists: past hooks that performed, from the clip-analyst.
3. `work/<campaign>/<video>.transcript.txt`: lines look like `[12:03.4 - 12:09.8] text`.
4. `work/<campaign>/<video>.scan.txt` if it exists: the loudest and busiest 5-second windows, plus a list of
   contact sheets in `work/<campaign>/<video>.scan/`. Each sheet is 16 snapshots, each stamped with its time.

**Footage with little or no speech** (gameplay, reactions, music, raw game footage): if the transcript says
"no speech found" or has fewer than about 40 words per minute of video, pick moments from what you can see.
Open the contact sheets (they are images; read them), start from the highest-energy windows in the scan,
and look for: a clear before/after, a surprise or fail, a win, a chase or fight, a big reveal, a funny moment,
or the most visually striking thing the campaign wants to show. Clips of 12-30 seconds suit gameplay best.
The `hook_text` does all the talking here, so make it specific ("Day 99 and the monster is STILL outside").
In `why`, say which snapshot times you saw.

Find 6 to 10 moments (fewer if the video is short) that:
- Start on a hook: the first sentence alone makes someone stop scrolling (a bold claim, a question, a number, conflict, a confession, a strong reaction). Never start mid-sentence or on "so", "and", "um".
- Stand alone: a stranger understands it without the rest of the video.
- End on a payoff or a line that lands, not mid-thought. 20-60 seconds; 25-40 is the sweet spot.
- Don't overlap each other.

Use the transcript timestamps. Start 0.2 s before the first word and end 0.3 s after the last word.

Write `work/<campaign>/cuts.json` (keep `rules` and `campaign` if they're already there):

```json
{
  "source": "<video file name>",
  "campaign": "<campaign>",
  "rules": ["..."],
  "reframe": "blur",
  "cuts": [
    {"id": 1, "start": "12:03.2", "end": "12:41.0",
     "hook_text": "He lost $2M in one night",
     "score": 8,
     "why": "Opens on a number, story resolves at 12:38",
     "approved": false}
  ]
}
```

- `hook_text`: on-screen text for the first 3 seconds, 8 words max, no emoji unless the campaign uses them. It should add curiosity, not repeat the first line.
- `score`: 1-10, your honest guess. The analyst compares your scores with real views later, so don't inflate them.
- `reframe`: `"blur"` (whole frame over a blurred background, safe default) or `"crop"` for a single person centered on camera; per cut you can set `"crop"` plus `"x_center"` from 0 (left) to 1 (right).
- Sort by score, highest first. Leave `approved` false: a person picks.
