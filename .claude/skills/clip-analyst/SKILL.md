---
name: clip-analyst
description: Weekly review of clip performance that updates examples/winning-hooks.md and proposes edits to clip-finder. Use when a person asks what is working, or from the weekly routine.
---

# Clip analyst

1. Run `python scripts/duocut.py stats`. If fewer than 10 clips have views, say so and stop.
2. Read `data/clip-log.csv`. Compare the top and bottom 20% by `views_7d` (and `approved_views` where filled):
   hook type (number, question, claim, story, reaction), hook length, clip length, campaign, platform, and whether Claude's `score` predicted the result.
3. Rewrite `examples/winning-hooks.md`: the 10 best hooks with their views, then 3-5 patterns in plain words ("hooks with a dollar figure averaged 2.3x the views").
4. If a pattern is clear across 20+ clips, propose one small edit to `.claude/skills/clip-finder/SKILL.md` and show it as a diff for a person to accept.
5. Report: clips posted this week, views, approved payout, payout per hour if `data/hours.csv` exists, and the one change to try next week.

Only edit `examples/winning-hooks.md` by yourself. Skill edits wait for a person.
