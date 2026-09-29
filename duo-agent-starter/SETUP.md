# Set up the DuoCut clip agent on your computer

About 30 minutes, once per person. Works on Windows, macOS and Linux.

## 1. Install the tools
- **Python 3.10+**: https://www.python.org/downloads/ (Windows: tick "Add python.exe to PATH").
- **Claude Code**: follow https://code.claude.com/docs/en/setup and sign in with your Claude Pro account.
- **Git** (optional but recommended): https://git-scm.com/downloads
- **ffmpeg**: optional. If you don't install it, step 3 installs a bundled copy through pip.

## 2. Make the repo yours
1. Create a **private** GitHub repo called `duo-agent`.
2. Copy everything in this folder into it (including the hidden `.claude/` folder and `.gitignore`), commit and push.
3. The other partner clones it. You both work in the same repo, so skills and the clip log stay shared.

## 3. Install the Python parts
In a terminal inside the repo:

```
python -m pip install -r requirements.txt
```

The first `transcribe` run downloads the Whisper speech model (small = about 500 MB). After that it works offline.

## 4. First run (about 20 minutes)
1. Open the repo in Claude Code (`claude` in the terminal, or the desktop app's Code tab).
2. Say: `make a work folder for the campaign "<campaign name>"`. Paste the campaign page into `work/<campaign>/campaign.md`.
3. Put the source video the campaign allows into that folder.
4. Say: `make clips from <video file> for <campaign>`.
5. Claude writes the brief, transcribes, and shows you a numbered list of moments. Reply with the numbers you want.
6. Clips appear in `queue/clips/<clip id>/final.mp4` with `caption.txt` and a posting checklist.
7. Watch, post by hand (or with TikTok, YouTube or Meta's own scheduler), then tell Claude the link:
   `posted <clip id> on tiktok: <url>`.
8. Once a week: `log views` for each clip (Claude updates `data/clip-log.csv`) and `what's working?` for the analyst.

## Speed notes
- Transcribing a 1-hour video with the `small` model takes roughly 5 to 15 minutes on a laptop CPU; `base` is faster and a bit less accurate.
- Rendering a 30-second clip takes well under a minute on most laptops.

## What never happens automatically
Posting, scheduling, logging in to social accounts, joining campaigns, and anything on Whop or Content Rewards. See `approval-rules.md`.
