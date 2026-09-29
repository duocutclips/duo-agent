# Architecture

```
┌──────────────────────── Tauri desktop shell (Rust) ────────────────────────┐
│  starts `python -m clipfactory.server` on a free 127.0.0.1 port with a       │
│  random per-launch token; kills it on exit (backend also exits if the shell   │
│  dies). Exposes `backend_config` (url + token) and the native file dialog.    │
│ ┌──────────────── React UI (apps/desktop/src) ────────────────┐             │
│ │ pages → api.ts (fetch + X-CF-Token) → polling /api/jobs/{id} │             │
│ └─────────────────────────────┬────────────────────────────────┘             │
└───────────────────────────────┼──────────────────────────────────────────────┘
                                │ HTTP JSON, loopback only
┌───────────────────────────────▼──── Python backend (backend/clipfactory) ────┐
│ server.py (FastAPI routes, token check, CORS for app origins only)           │
│ jobs.py (2 worker threads: render, pipeline, batch, media analysis, demo)     │
│                                                                              │
│ campaigns.py  ideas.py  scriptgen.py      ← llm.py (Anthropic SDK)           │
│ voice.py (ElevenLabs / system TTS)  transcription.py (Whisper API /          │
│   faster-whisper / TTS alignment / estimated alignment)                      │
│ media.py  analysis.py (numpy signals)  timeline.py  captions.py              │
│ render.py (FFmpeg)  qa.py  projects.py (workflow)  variations.py             │
│ tracker.py (submissions, analytics)  publishing.py (manual, YouTube API)     │
│ db.py (SQLite, migrations)  config.py  logging_setup.py  errors.py           │
└──────────────────────────────────────────────────────────────────────────────┘
        │ subprocess                     │ HTTPS (only when keys are set)
      FFmpeg / ffprobe            Anthropic · ElevenLabs · Whisper · YouTube
```

## Why a local HTTP backend

Media work (FFmpeg orchestration, numpy analysis, PDF/DOCX parsing, AI SDKs) is simpler and easier to test in Python. The UI talks to it over loopback HTTP, which also lets the same UI run in a normal browser for development and automated UI tests. The per-launch token stops other local programs and web pages from using the API.

## Repository layout

| Path | Contents |
|---|---|
| `apps/desktop/src` | React 19 + TypeScript UI: `pages/`, `components/`, `api.ts`, `platform.ts` (Tauri vs browser) |
| `apps/desktop/src-tauri` | Rust shell, `tauri.conf.json` (CSP, bundle), capabilities (core + dialog only) |
| `backend/clipfactory` | Python package (see diagram) |
| `packages/timeline-schema` | JSON Schema for timelines: the contract between editor, UI and renderer |
| `templates/` | Built-in editing templates (JSON) |
| `assets/fonts` | Caption font (DejaVu Sans Bold) and its licence |
| `tests/backend` | pytest: unit, integration (mocked HTTP), rendering, one full end-to-end run |
| `tests/ui` | Browser smoke test of every page against a live backend |
| `scripts/` | setup, dev, demo, check, ui-smoke (bash + PowerShell) |

## Data model (SQLite)

`campaigns` (structured brief + analysis JSON) → `campaign_documents` (extracted text) · `ideas` · `scripts` · `media` (videos, images, audio, SFX, music; unique by SHA-256 + kind) → `segments` (auto + manual) · `voice_profiles` → `narrations` (audio + word timings) · `projects` (one video: idea, script, narration, media, template, seed, timeline JSON, render path, QA report, status, history) · `submissions` (post URL, status, metrics, earnings) · `settings` (preferences).

Schema changes go through numbered migrations in `db.py` (`PRAGMA user_version`).

## Project workflow

```
Campaign → Idea → Script → Voice → Footage → Timeline → Preview → QA → Export → Publishing → Analytics
```

Each step stores its output on the project. Changing an input clears everything downstream (a new script clears the narration, timeline, render and QA) and moves a reviewed video back to DRAFT, so an approved video always matches what was reviewed. `run_pipeline` reuses finished steps.

Status machine:

```
DRAFT → REVIEW (needs QA READY) → APPROVED → EXPORTED → POSTED → SUBMITTED
          ↘ REJECTED (needs a note) → DRAFT
```

Nothing moves past REVIEW without a person clicking Approve.

## AI providers and honesty rules

* Every provider reports availability (`/api/status`). Missing keys raise `ConfigurationError` (HTTP 424) with the variable to set.
* Offline generators are labelled `offline-heuristic`; estimated word timings are labelled `estimated-alignment`.
* The campaign analyzer only keeps an item as *confirmed* if its quote is found in the source text. Claude's "confirmed" items without a real quote are downgraded to suggestions, and the UI says so.
* Novelty and compliance scores are computed locally, not self-reported by a model.
* Structured outputs use `client.messages.parse` with Pydantic models; refusals and truncated outputs are reported as errors, not silently used.

## Errors and logging

All errors are `AppError` subclasses mapped to HTTP status codes with `{error: {code, message, hint, detail}}`. External calls have timeouts and retries with backoff (HTTP 429/5xx). FFmpeg calls have timeouts and include the tail of stderr on failure. Logs are JSON lines in `logs/`; a formatter redacts secret env values, bearer tokens and `key/token/password` fields before writing.
