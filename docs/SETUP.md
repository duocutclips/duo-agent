# Setup

The app has two parts that run on your computer: a Python backend (FFmpeg, AI calls, database) and a desktop window (Tauri + React). The desktop window starts and stops the backend for you.

## Requirements

| Tool | Version | Windows | macOS | Linux (Debian/Ubuntu) |
|---|---|---|---|---|
| FFmpeg (with libx264, libass) | 6+ | `winget install Gyan.FFmpeg` | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| Python | 3.10+ (3.11 tested) | `winget install Python.Python.3.11` | `brew install python@3.11` | `sudo apt install python3 python3-venv` |
| Node.js | 20+ (22 tested) | `winget install OpenJS.NodeJS.LTS` | `brew install node` | nodesource or `nvm` |
| Rust (only to run/build the desktop window) | 1.77+ | `winget install Rustlang.Rustup` | `curl https://sh.rustup.rs -sSf \| sh` | same |
| WebView | | WebView2 (preinstalled on Windows 10/11) | built in | `sudo apt install libwebkit2gtk-4.1-dev librsvg2-dev libayatana-appindicator3-dev libxdo-dev patchelf` |
| Offline draft voice (optional) | | built-in SAPI voices | built-in `say` | `sudo apt install espeak-ng` |

Windows also needs the "Desktop development with C++" workload from Visual Studio Build Tools for Rust (`winget install Microsoft.VisualStudio.2022.BuildTools`, then select that workload).

Open a **new** terminal after installing so `ffmpeg`, `node` and `cargo` are on PATH.

## Install

```powershell
git clone https://github.com/duocutclips/duo-agent.git
cd duo-agent
.\scripts\setup.ps1          # macOS/Linux: scripts/setup.sh
```

This creates `backend\.venv`, installs the backend in it, runs `npm ci` in `apps\desktop`, and copies `.env.example` to `.env`.

If PowerShell refuses to run scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Run

Run these from the `duo-agent` folder (the one with `README.md`). The first `dev.ps1` compiles the desktop window, which takes several minutes; later starts are fast.

```powershell
.\scripts\dev.ps1            # desktop window with hot reload
.\scripts\dev.ps1 -Browser   # backend + UI at http://localhost:1420 in your browser
.\scripts\demo.ps1           # command-line offline demo: renders and exports 2 videos
```

## API keys (all optional)

Edit `.env` in the repository root, then restart the app. **Settings → Integrations** shows what is configured.

| Variable | Enables | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude campaign analysis, ideas and scripts (otherwise offline rule-based generators, clearly labelled) | console.anthropic.com → API keys |
| `ANTHROPIC_MODEL` | Model choice (default `claude-opus-5-5`) | |
| `ELEVENLABS_API_KEY` | Natural narration with exact word timings | elevenlabs.io → Settings → API keys |
| `ELEVENLABS_VOICE_ID` | Default voice (or add voices on the Voice page) | ElevenLabs voice library |
| `WHISPER_API_URL`, `WHISPER_API_KEY` | Speech-to-text word timestamps for any audio (OpenAI-compatible `/audio/transcriptions`) | e.g. `https://api.openai.com/v1/audio/transcriptions` |
| `YOUTUBE_ACCESS_TOKEN` | Private uploads to your channel through the YouTube Data API | OAuth 2.0 token with the `youtube.upload` scope |
| `FFMPEG_PATH`, `FFPROBE_PATH` | Use a specific FFmpeg build | e.g. `C:\ffmpeg\bin\ffmpeg.exe` |
| `CLIP_FACTORY_DATA_DIR` | Where the database, caches and renders are stored (default `data\`) | |

Keys are read from the environment only. They are never saved in the database, never sent to the UI and redacted from logs.

Without `ELEVENLABS_API_KEY` narration uses the offline system voice (robotic; for drafts). Without any speech-to-text, word timings come from ElevenLabs when used, or are estimated from the audio (labelled `estimated-alignment`).

## Build the Windows installer

Run on the Windows PC (installers can't be cross-built from Linux):

```powershell
cd apps\desktop
npx tauri build
```

Output: `apps\desktop\src-tauri\target\release\bundle\msi\Roblox Clip Factory_0.1.0_x64_en-US.msi` and `...\bundle\nsis\Roblox Clip Factory_0.1.0_x64-setup.exe`.

The installer contains the desktop window. It uses the Python backend from the checkout it was built in (`backend\.venv`), so keep that folder. To move it, set the environment variable `CLIP_FACTORY_BACKEND_DIR` to the new `backend` folder (and `CLIP_FACTORY_PYTHON` to a specific `python.exe` if needed).

Linux: `npx tauri build --bundles deb` → `src-tauri/target/release/bundle/deb/*.deb`. macOS: `npx tauri build` → `.app` / `.dmg`.

## Where things are stored

| What | Default location |
|---|---|
| Database, media copies, caches, renders | `data\` |
| Exported videos + caption files | `exports\<campaign>\concept-NN-<category>.mp4` |
| Logs (JSON lines, secrets redacted) | `logs\clipfactory.jsonl` |
| Your custom templates | `data\templates\*.json` |

All of these are git-ignored.
