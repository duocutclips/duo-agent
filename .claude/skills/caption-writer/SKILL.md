---
name: caption-writer
description: Write the post caption for each cut in cuts.json following the campaign's tag and link rules. Use inside make-clips after clip-finder, or when a person asks for captions.
---

# Caption writer

For each cut in `work/<campaign>/cuts.json`, add a `caption` field:
- Line 1: a short line that makes people watch to the end (a question or a tease, under 80 characters). Don't repeat the hook text word for word.
- Then every tag, mention, link or hashtag the campaign rules require, exactly as written in the brief.
- Then 2-4 relevant hashtags. No more than 5 hashtags in total.
- No claims the clip doesn't back up, no fake urgency, nothing that impersonates the creator.

If a rule says captions differ per platform, write `caption_tiktok`, `caption_youtube`, `caption_instagram` instead.
