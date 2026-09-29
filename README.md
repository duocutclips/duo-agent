# Roblox Clip Factory

A desktop app for producing short vertical Roblox videos for clipping campaigns (Whop, Content Rewards and similar), from the campaign brief to a tracked post.

```
Campaign brief → requirements → 10 ideas → hook + script → AI voice → gameplay analysis → automatic edit
→ captions, zooms, SFX, music → QA → your approval → export → manual (or API) posting → views and earnings tracking
```

Everything runs locally. Nothing is posted anywhere without you approving, exporting and posting it yourself.

## What it does

| Area | What you get |
|---|---|
| Campaigns | Import briefs from PDF, DOCX, TXT, pasted text or a URL. The analyzer separates **confirmed requirements** (quoted from the brief) from **AI suggestions**, and never invents requirements. |
| Ideas | 10 deliberately different concepts (discovery, secret, challenge, progression, mistake, tutorial, rare item, funny moment, comparison, surprising mechanic) with locally computed novelty and compliance scores. Regenerate any one. |
| Scripts | 15/20/30/45 s scripts in spoken style: hook first, short sentences, payoff, CTA. Live speaking-time estimate and warnings (too long, missing required wording, restricted terms). |
| Voice | ElevenLabs narration with word timestamps and a cache (the same text + voice + settings is never paid for twice). Voices must be marked as yours or authorised. Free offline voice for drafts. |
| Gameplay analysis | Scene cuts, motion, audio peaks, silence, black/static frames and repeated footage from signal processing. Segments are labelled by what was measured ("High action", "Sharp loud sound"), never by guessed meaning. Adjust or add segments yourself. |
| Automatic edit | Cuts on sentence boundaries, best segment as the hook, punch-in zooms, caption layer with word highlight, SFX at cuts and emphasis, music with ducking under the voice, title and CTA cards. Stored as an editable timeline JSON. |
| Rendering | Deterministic FFmpeg pipeline to 1080×1920 30 fps H.264/AAC MP4, loudness-normalised. Same timeline → byte-identical file. |
| Templates | Editing styles are JSON data (pacing, zooms, caption look, SFX density, music). Five built-ins; edit copies in the app. |
| QA | Resolution, aspect, codecs, duration vs. campaign limits, audio, narration, silence gaps, black frames, corruption (full decode), captions, required phrases. READY or NOT READY. |
| Approval | DRAFT → REVIEW → APPROVED → EXPORTED → POSTED → SUBMITTED (or REJECTED with a note). Export needs approval. |
| Export | `exports/<campaign>/concept-01-discovery.mp4` plus a caption `.txt`. Never overwrites. |
| Publishing | Copy caption and hashtags, open the platform, open the file, record the post link. Optional private YouTube upload through the official API. No browser automation. |
| Tracking | Views, likes, comments, shares, saves, submission status and earnings per post; analytics by hook, template and category, with a clear note when the sample is too small to draw conclusions. |

## Quick start

Windows (PowerShell):

```powershell
winget install Gyan.FFmpeg OpenJS.NodeJS.LTS Python.Python.3.11 Rustlang.Rustup
git clone https://github.com/duocutclips/duo-agent.git
cd duo-agent
scripts\setup.ps1
scripts\dev.ps1            # opens the desktop app
```

macOS / Linux:

```bash
scripts/setup.sh
scripts/dev.sh             # desktop app;  scripts/dev.sh --browser  for the UI in a browser
```

In the app, click **Create demo campaign** on the Dashboard to get generated sample gameplay, SFX and music, then on **Ideas** tick a few ideas and press **Produce selected videos**, or open a project and press **Run full pipeline**.

No API keys are needed to try it. Add them to `.env` (copy `.env.example`) to enable Claude, ElevenLabs, Whisper and YouTube. See [docs/SETUP.md](docs/SETUP.md).

Offline demo from the command line (renders and exports two videos):

```bash
scripts/demo.sh            # Windows: scripts\demo.ps1
```

## Documentation

* [Setup](docs/SETUP.md): install, API keys, building the Windows installer
* [Architecture](docs/ARCHITECTURE.md): how the pieces fit
* [Video pipeline](docs/VIDEO_PIPELINE.md): analysis, timeline, rendering, QA
* [API](docs/API.md): the local HTTP API used by the UI
* [Development](docs/DEVELOPMENT.md): tests, quality gate, conventions
* [Troubleshooting](docs/TROUBLESHOOTING.md)
* [Implementation plan](docs/IMPLEMENTATION_PLAN.md)

## Rules the app follows

* API keys only come from environment variables or `.env`; they are never stored in the database, shown in the UI or written to logs.
* No CAPTCHA bypass, fingerprint spoofing, anti-bot evasion, fake accounts, credential scraping or stealth automation.
* Only official platform APIs; manual posting is the default.
* Music needs a licence note on import; voices need an explicit ownership/permission confirmation.
