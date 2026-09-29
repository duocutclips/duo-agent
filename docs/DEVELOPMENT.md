# Development

## Day to day

```bash
scripts/dev.sh --browser     # backend on :8765 + Vite dev server on :1420 (open in a browser)
scripts/dev.sh               # the same UI inside the Tauri window
cd apps/desktop && npm run backend   # only the backend
```

The UI detects whether it runs inside Tauri (`platform.ts`). In a browser it uses `VITE_API_URL` (default `http://127.0.0.1:8765`) and `VITE_API_TOKEN` (default none).

Command-line tools:

```bash
cd backend
.venv/bin/python -m clipfactory.cli status                  # what is configured
.venv/bin/python -m clipfactory.cli demo --videos 3 --quality draft --data-dir /tmp/cf --offline --export
```

## Quality gate

```bash
scripts/check.sh             # ruff, mypy, all backend tests, tsc, eslint, vitest, vite build, secret scan
scripts/check.sh --fast      # skip rendering tests
scripts/check.sh --bundle    # also build the desktop installer
scripts/ui-smoke.sh [shots/] # every page in Chromium against a live backend (needs the demo data)
```

Windows: `.\scripts\check.ps1 [-Fast] [-Bundle]`.

| Layer | Tool | Where |
|---|---|---|
| Python lint / format rules | ruff (`E F W I B UP SIM`, line length 110) | `backend/pyproject.toml` |
| Python types | mypy (`check_untyped_defs`) | |
| Python tests | pytest; `-m "not slow"` skips FFmpeg rendering | `tests/backend` |
| TypeScript | `tsc -b` strict | `apps/desktop/tsconfig.json` |
| TS lint | eslint 9 + typescript-eslint + react-hooks | `apps/desktop/eslint.config.js` |
| UI unit tests | vitest + Testing Library (jsdom) | `apps/desktop/src/**/*.test.ts(x)` |
| UI smoke | playwright-core + Chromium | `tests/ui/smoke.mjs` |

## Tests

| File | Covers |
|---|---|
| `test_campaigns.py` | analyzer (confirmed vs suggestion, quote verification, LLM downgrade), rules, PDF/DOCX/TXT/HTML extraction |
| `test_content.py` | duration estimation, 10 distinct ideas and scores, regenerate, scripts for every target, script warnings |
| `test_timeline_captions.py` | caption grouping and emphasis, ASS output, cut points, timeline build/validation/determinism |
| `test_media_db_templates.py` | metadata for MP4/MOV/WEBM/images/audio, dedupe, deletion safety, persistence, templates, export naming |
| `test_integrations.py` | ElevenLabs (mocked HTTP, cache, auth), voice authorisation, Whisper (mocked), estimated alignment, YouTube (mocked), manual publisher, unconfigured providers |
| `test_security_tracker.py` | log redaction, API token, key leakage, restricted file opening, structured errors, `.gitignore`, approval rules, analytics |
| `test_render_e2e.py` (slow) | real render + output spec + QA + byte-identical re-render; QA failing bad files; full end-to-end run through the HTTP API from demo brief to tracked post |

External services are never called in tests: every secret env var is blanked in `conftest.py`, and HTTP clients take an `httpx` transport so tests inject `httpx.MockTransport`.

## Conventions

* Backend errors: raise an `AppError` subclass with a user-facing `message`, an actionable `hint`, and technical `detail`.
* Log with `log_event(logger, "message", key=value)`; never log request bodies that may contain keys.
* Anything that takes more than a second or two is a job (`jobs.submit`) and the UI shows `JobBar`.
* The timeline schema is the contract: change `packages/timeline-schema/timeline.schema.json`, `timeline.py`, `render.py` and `types.ts` together.
* New DB columns: add a migration to `MIGRATIONS` in `db.py`; never edit an old one.
* UI: no placeholder buttons. A feature that needs configuration shows why it is unavailable.

## Adding an AI provider or publisher

* LLM: `llm.ClaudeClient.structured()` returns a validated Pydantic object; add a schema model next to the feature.
* Voice: implement `synthesize(text, voice_id, settings, out_base) -> (audio_path, words)` and register it in `voice.generate_narration`.
* Publisher: subclass `publishing.SocialPublisher` (`available`, `publish`, `get_status`, `get_metrics`) using the platform's official API only, and add it in `publishers()`.
