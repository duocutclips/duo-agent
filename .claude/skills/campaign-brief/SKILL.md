---
name: campaign-brief
description: Turn a pasted Whop or Content Rewards campaign page into a one-page brief with the rules, payout, allowed footage and a GO/NO-GO. Use when a person pastes a campaign, runs make-clips, or asks whether to join a campaign.
---

# Campaign brief

Input: `work/<campaign>/campaign.md` (a person pastes the campaign page into it; `python scripts/duocut.py new "<name>"` creates the folder).

Write `work/<campaign>/brief.md`:

1. **Payout**: rate per 1,000 views, per-post payouts, minimum views to qualify, budget left and campaign age if shown. Campaigns in their first 48 hours are the least crowded.
2. **Rules**: allowed platforms, required tags, mentions, links or sounds, caption rules, minimum and maximum length, banned edits, whether AI captions or AI voice are allowed, account requirements.
3. **Footage**: exactly where source video may come from. If the page doesn't say, write "ask the campaign owner" and make the verdict NO-GO until a person confirms.
4. **Estimate**: use the median `approved_views` for this platform from `python scripts/duocut.py stats` (or 1,000 views per clip if there is no history yet). Expected payout per clip = views x 0.75 / 1,000 x rate. Say how many clips a person can review and post per hour (start with 6).
5. **Verdict**: GO or NO-GO and one sentence why.

Also write the rules as a short list into `work/<campaign>/cuts.json` under `"rules"` (create the file with `{"source": "", "campaign": "<campaign>", "rules": [...], "cuts": []}` if it doesn't exist), so every clip's README repeats them.

Never join a campaign, connect an account or accept terms yourself.
