# Roblox Clip Factory — Implementation Plan

Written 2026-09-29, before implementation, after inspecting the build environment.

## 1. Environment inspection (build container)

| Item | Found | Notes |
|---|---|---|
| OS | Ubuntu 24.04.4 LTS, x86_64, Linux 6.18 | Cloud build container. The end user runs **Windows**. |
| Python | 3.11.15 (`uv` available) | Backend uses a venv at `backend/.venv`. |
| Node / npm / pnpm / yarn | 22.22.2 / 10.9.7 / 10.33.0 / 1.22.22 | npm is used (no extra tooling needed on Windows). |
| Rust / Cargo | rustc 1.94.1 / cargo 1.94.1 | Required by Tauri. |
| FFmpeg | **Not installed** initially → installed `ffmpeg 6.1.1` via apt | Has libx264, aac, libass (`ass`/`subtitles`), `drawtext`, `zoompan`, `sidechaincompress`, `loudnorm`, `blackdetect`, `silencedetect`, `scdet`. |
| Tauri Linux deps | Not installed → installed `libwebkit2gtk-4.1-dev`, `librsvg2-dev`, `libayatana-appindicator3-dev`, `libxdo-dev`, `patchelf`, `xvfb` | webkit2gtk 2.52.6. |
| Offline TTS | `espeak-ng 1.51` installed via apt | Used only by the offline demo voice provider. |
| Git | repo exists, remote `origin = github.com/duocutclips/duo-agent`, branch `claude/roblox-clip-factory-vjc77w` | Commits are signed by the container; pushing goes to the feature branch, never `main`. |
| Network | npm, PyPI, crates.io reachable through the proxy | No API keys for Anthropic, ElevenLabs or Whisper. |
| Browser tooling | Chromium + Playwright preinstalled | Used for a UI smoke test against the web build. |

Consequences:

* The desktop bundle can only be **built for Linux** in this container. Windows build steps are documented in `docs/SETUP.md` but not executed here.
* All AI integrations must degrade to clear configuration errors; the demo must run fully offline using generated media and the offline heuristics / espeak voice.

## 2. Architecture decisions

```
apps/desktop/           Tauri 2 shell + React 19 + TypeScript + Vite UI
  src/                  React app (pages, components, API client)
  src-tauri/            Rust shell: starts/stops the Python backend, passes a per-launch API token
backend/                Python package `clipfactory`
  clipfactory/          domain modules + FastAPI app (127.0.0.1 only)
packages/timeline-schema/  JSON Schema for the timeline (shared contract between UI and renderer)
templates/              Data-driven editing templates (*.json)
assets/                 Bundled static assets (fonts note, placeholder docs); generated media is NOT committed
tests/backend/          pytest unit + integration + end-to-end tests
tests/ui/               Playwright smoke test of the UI against a live backend
scripts/                dev/check/demo scripts (bash + PowerShell)
docs/                   documentation
```

Why a local HTTP backend instead of Tauri commands in Rust: all media work (FFmpeg orchestration, analysis with numpy, PDF/DOCX parsing, AI SDKs) is far simpler and better tested in Python. The Tauri shell spawns `python -m clipfactory.server` bound to `127.0.0.1` with a random token; the UI sends that token on every request. The same UI also runs in a normal browser for development and automated UI testing.

Key design choices:

* **SQLite** via the standard library, versioned migrations in `db.py`, JSON columns for flexible structures.
* **Providers with explicit availability.** `llm.py` (Anthropic SDK), `voice.py` (ElevenLabs / system TTS), `transcription.py` (Whisper-compatible HTTP endpoint / local faster-whisper if installed / script alignment). Each exposes `status()` so the UI can show what is configured. Missing keys raise `ConfigurationError` with the variable name to set.
* **Offline fallbacks are labelled, never disguised.** Heuristic campaign extraction marks items as *confirmed* only when quoted from the source text; heuristic ideas/scripts are labelled `generator: offline-heuristic`. Estimated word timings from script alignment are labelled `method: estimated-alignment`, not "transcription".
* **Timeline is the single source of truth for rendering.** A flat list of typed items (`video`, `zoom`, `fade`, `caption`, `text`, `image`, `narration`, `music`, `sfx`), validated against `packages/timeline-schema/timeline.schema.json`.
* **Deterministic renderer.** Two-stage FFmpeg pipeline: (1) each video item → normalised 1080×1920/30fps intermediate (crop or blurred-fill, zoom via `zoompan`), (2) concat + final composition (ASS captions/text via libass, image overlays, fades, narration + looped music with sidechain ducking + SFX, loudness normalisation) → H.264/AAC MP4 with `+faststart`. Single-threaded x264 encodes and filtering (clips are rendered in parallel instead), `bitexact` flags and no timestamps in metadata so the same timeline renders byte-identical output on the same FFmpeg build (verified by a test).
* **Captions are a layer.** Generated as an ASS file at render time from caption items; source footage is never modified.
* **QA** uses ffprobe + `blackdetect` + `silencedetect` + a full decode, and checks campaign-required phrases against the narration script.
* **Human approval.** Status machine `DRAFT → REVIEW → APPROVED → EXPORTED → POSTED → SUBMITTED` (+ `REJECTED`). Export requires APPROVED; publishing requires EXPORTED. Nothing is published automatically.
* **Publishing** uses a `SocialPublisher` abstraction. Only a manual provider (copy caption / hashtags / open platform / open file) is enabled by default. A YouTube Data API provider is implemented behind explicit credentials (unverified without credentials, tested with a mocked HTTP layer). No browser automation of social platforms.
* **Logging**: JSON lines in `logs/`, with a redaction filter for known secret variables and token patterns.

## 3. Delivery order

1. Environment + plan (this document).
2. Backend core: config, logging, errors, DB, FFmpeg runner/probe, sample media generator.
3. Vertical slice: campaign → analyzer → ideas → script → voice (offline) → media import → analysis → timeline → render → QA → export. Verified with an end-to-end pytest.
4. FastAPI server exposing every feature.
5. React UI for all sidebar sections, then the Tauri shell.
6. Remaining features: templates editor, SFX/music library, variations, submissions, analytics, publishing abstraction.
7. Documentation.
8. Quality gate: install, typecheck (mypy + tsc), lint (ruff + eslint), unit/integration/e2e tests, frontend build, `tauri build` (Linux .deb), demo render + validation, UI smoke test.
9. Git review (status/diff/secret scan), commit, push to the feature branch, draft PR.

## 4. Risks and mitigations

| Risk | Mitigation |
|---|---|
| No API keys in the build environment | Offline heuristic generators + espeak voice; AI paths return typed configuration errors; LLM/TTS/STT clients unit-tested against mocked HTTP. |
| Windows-specific behaviour (paths, fonts, ffmpeg discovery, SAPI voice) cannot be run here | Paths via `pathlib`, FFmpeg located via `FFMPEG_PATH`/`PATH`, font file passed explicitly to libass via `fontsdir`, Windows SAPI voice implemented but flagged as untested here. |
| Tauri AppImage bundling downloads tools from GitHub | Build `.deb` bundle on Linux; document Windows `msi`/`nsis` build. |
| Rendering time in tests | Tests render short (3–8 s) clips with `veryfast` preset. |

## 5. Changes made during implementation

* x264 frame threading produced a few differing pixels between identical renders, so encodes became single-threaded and clip intermediates render in parallel (found by the determinism test).
* `assets/` holds only the bundled caption font (DejaVu Sans Bold, with its licence). Demo footage, SFX and music are generated at runtime by `samples.py`, never committed.
* The desktop shell passes its process id to the backend, which exits if the shell dies, so no backend process is orphaned.
