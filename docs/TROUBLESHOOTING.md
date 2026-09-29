# Troubleshooting

Start with **Settings → Integrations** (what is configured) and **Settings → Recent log events**. The full log is `logs/clipfactory.jsonl` (one JSON object per line, secrets redacted).

## The app says "Backend: not reachable" or "The local backend could not be started"

* Run the setup script again (`.\scripts\setup.ps1`): the desktop app needs `backend\.venv`.
* Installed app moved away from the checkout: set `CLIP_FACTORY_BACKEND_DIR` to the `backend` folder, and `CLIP_FACTORY_PYTHON` to its `.venv\Scripts\python.exe` if needed.
* Start the backend by hand to see the error: `cd backend; .\.venv\Scripts\python.exe -m clipfactory.server`.
* Browser development: run `npm run backend` (or `scripts/dev.sh --browser`) before opening http://localhost:1420.

## "FFmpeg was not found"

Install it (`winget install Gyan.FFmpeg`) and open a new terminal, or set `FFMPEG_PATH` and `FFPROBE_PATH` in `.env` to the full paths of `ffmpeg.exe` and `ffprobe.exe`. The FFmpeg build needs libx264 and libass (the gyan.dev and Homebrew builds have both).

## Claude / ElevenLabs / Whisper / YouTube "not configured"

Add the key to `.env` in the repository root (see `.env.example`) and restart the app. A key that is present but wrong shows "rejected the API key". Keys are never shown in the UI, so check `.env` itself.

## Narration sounds robotic

That is the free offline voice used when `ELEVENLABS_API_KEY` is missing. It is meant for drafts and timing. Add an ElevenLabs key and a voice on the Voice page.

## "This voice is not marked as authorised"

On the Voice page, tick "I own this voice or have permission to use it" for that profile. This is required for cloned voices.

## Captions are slightly early or late

Word timings came from `estimated-alignment` (shown on the project's Voice tab). Configure ElevenLabs (exact timings) or `WHISPER_API_URL`. You can also fix caption text in the Timeline tab.

## QA says NOT READY

Open **Preview & QA**; each failed row says what was measured.

* **Duration**: the narration is shorter or longer than the campaign's confirmed limits. Pick a different target length on the Script tab or edit the script.
* **No silence**: a pause longer than the limit (Settings) was found. Shorten pauses in the script or raise the limit if the campaign allows it.
* **Black frames**: the footage has black sections. Disable those segments on the Media page and rebuild the timeline.
* **Required phrases**: the script is missing a confirmed code or required wording.

## Rendering is slow

Use **Draft** quality while iterating (Settings sets the default), then render **Final** once. Unchanged timelines are cached and return instantly. Clip intermediates are reused between renders.

## Export button is disabled

Export needs the project to be **APPROVED** (Preview & QA → Send to review → Approve). This is intentional.

## A file I imported disappeared

Imports reference your original file in place. If you move or delete it, the Media page marks it missing; re-import it from the new location. Deleting media in the app never deletes your original file.

## Reset everything

Close the app and delete the `data`, `logs` and `exports` folders (exports contain your finished videos, so move them first).
