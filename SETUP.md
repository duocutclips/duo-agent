# Set up DuoCut Studio on your computer

About 20 minutes, once per person. Works on Windows, macOS and Linux.

## 1. Install the tools
- **Python 3.10+**: https://www.python.org/downloads/ (Windows: tick "Add python.exe to PATH" in the installer).
- **Claude Code**: follow https://code.claude.com/docs/en/setup, then run `claude` once in a terminal and sign in with your Claude Pro account. The app uses this sign-in for "Find moments".
- **Git** or **GitHub Desktop**, to download this repo and keep it in sync.
- ffmpeg is optional: if it isn't installed, the Python step below brings a bundled copy.

## 2. Get the repo
Clone `duocutclips/duo-agent` (GitHub Desktop: File › Clone repository). Both partners use the same repo so skills and the clip log stay shared.

## 3. Install the Python parts
In a terminal inside the repo folder:

```
python -m pip install -r requirements.txt
```

(macOS: use `python3` instead of `python`.)

## 4. Start the app
- **Windows:** double-click `start-windows.bat`
- **macOS:** double-click `start-mac.command` (first time: right-click › Open)
- **Any system:** `python app.py`

Your browser opens **DuoCut Studio** at http://127.0.0.1:5050. It runs only on your computer. Close the terminal window to stop it.

## 5. Make your first clips
1. **New campaign**: type a name, for example "Roblox Campaign 1".
2. **Step 1**: paste the whole campaign page (payout, rules, where footage comes from) and Save.
3. **Step 2**: upload the source video the campaign allows. For very big files, copy them into `work/<campaign>/` and refresh.
4. **Step 3**: Transcribe. The first time, it downloads the speech model (about 500 MB), so it takes longer. A 1-hour video takes roughly 5 to 15 minutes on a laptop.
5. **Step 4**: Find moments. Claude writes the campaign brief with a GO or NO-GO, picks the best moments and writes captions.
6. **Step 5**: tick the clips worth making, fix times or hooks if you want, then **Save and render ticked clips**.
7. **Clips to post**: watch each clip, copy the caption, post it yourself (by hand or with TikTok, YouTube Studio or Meta's own scheduler), then paste the post link and Save post.
8. A week later, type in views and payout. **What's working** shows which hooks and campaigns pay best.

## Using Claude Code directly
Everything the app does also works by chatting with Claude Code in this folder, for example `make clips from ep1.mp4 for roblox-campaign-1` or `run the clip-analyst skill`.

## What never happens automatically
Posting, scheduling, logging in to social accounts, joining campaigns, and anything on Whop or Content Rewards. See `approval-rules.md`.

## If something goes wrong
- **"Could not load the speech model"**: the first transcription needs internet. Try again on a normal connection.
- **"Claude Code not found"**: install it, run `claude` once to sign in, then restart the app.
- **Port already in use**: set `DUOCUT_PORT=5051` before starting, or close the other copy of the app.
- **`cublas64_12.dll is not found` (or another CUDA error)**: your PC has an NVIDIA card but not the CUDA libraries. DuoCut now switches to the CPU on its own, so this should no longer stop you; it is just slower. To force the CPU every time, set `DUOCUT_DEVICE=cpu` before starting. Only set `DUOCUT_DEVICE=cuda` if you have installed CUDA 12 and cuDNN 9.
- **The video has no talking (gameplay)**: that's fine. Analyze takes snapshots of the whole video and Claude picks moments from those.
