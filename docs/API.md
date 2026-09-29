# Local HTTP API

The UI talks to the backend at `http://127.0.0.1:<port>` (8765 in development; the desktop app picks a free port). All bodies are JSON. The full, always-current schema is served at `/docs` (OpenAPI) while the backend runs.

## Authentication

When `CLIP_FACTORY_API_TOKEN` is set (the desktop app always sets a random one per launch), every `/api/*` request except `/api/health` needs the header `X-CF-Token: <token>`. Media URLs used by `<video>`/`<img>` may pass `?token=<token>` instead. Wrong or missing token → `401`. The server only listens on `127.0.0.1`, and CORS only allows the app's own origins.

## Errors

```json
{"error": {"code": "configuration_error", "message": "ElevenLabs is not configured.",
           "hint": "Add ELEVENLABS_API_KEY to .env (see .env.example) and restart.", "detail": null}}
```

| HTTP | code | When |
|---|---|---|
| 400 | `validation_error` | bad input (may include `errors: [...]`) |
| 401 | `unauthorized` | token missing or wrong |
| 404 | `not_found` | unknown id |
| 409 | `conflict` | not allowed in the current state (e.g. export before approval) |
| 422 | `media_error` | unreadable or unsupported media |
| 424 | `configuration_error` | an integration needs a key or setting |
| 500 | `render_error` / `internal_error` | FFmpeg or unexpected failure (details in `detail` and the log) |
| 502 | `external_service_error` | an AI or platform API failed after retries |

## Background jobs

Long operations return a job: `{"id", "kind", "ref", "status": "queued|running|succeeded|failed", "message", "progress": 0..1, "result", "error"}`. Poll `GET /api/jobs/{id}`. Jobs live in memory until the backend restarts.

## Endpoints

### System
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness, version, data/export/log folders |
| GET | `/api/status` | FFmpeg, Claude, ElevenLabs, system voice, transcription, YouTube configuration (never key values) |
| GET, PUT | `/api/preferences` | `default_quality` (draft/final), `max_silence_seconds`, `use_ai` |
| GET | `/api/logs?limit=200` | recent log events (already redacted) |
| POST | `/api/demo` | job: create the demo campaign with generated media and analyse it |
| POST | `/api/system/open` | open a file/folder from exports, renders or logs in the OS (other paths are refused) |

### Campaigns
| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/api/campaigns` | list / create |
| GET, PATCH, DELETE | `/api/campaigns/{id}` | read / update / delete (with its ideas, scripts, projects) |
| GET | `/api/campaigns/{id}/structured` | the campaign in the spec's structured JSON shape |
| GET | `/api/campaigns/{id}/rules` | confirmed rules used by scripts and QA |
| POST | `/api/campaigns/{id}/documents/text` | `{name, text}` pasted text |
| POST | `/api/campaigns/{id}/documents/url` | `{url}` fetch and extract a web page |
| POST | `/api/campaigns/{id}/documents/file` | multipart upload (PDF, DOCX, TXT, MD, HTML) |
| POST | `/api/campaigns/{id}/documents/path` | `{path}` read a local file (desktop) |
| GET, DELETE | `/api/documents/{id}` | extracted text / remove |
| POST | `/api/campaigns/{id}/analyze` | `{use_ai?}` confirmed requirements vs suggestions |
| GET, POST | `/api/campaigns/{id}/ideas` | list / generate `{count?, use_ai?}` |
| POST | `/api/campaigns/{id}/batch` | job: produce videos for `{idea_ids? , count?, quality?, voice_profile_id?}` + variation report |

### Ideas and scripts
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ideas/{id}/regenerate` | replace one idea with a new one of the same category |
| PATCH, DELETE | `/api/ideas/{id}` | edit / delete |
| POST | `/api/ideas/{id}/scripts` | `{target_seconds: 15|20|30|45, use_ai?}` |
| GET | `/api/scripts?campaign_id=` | list |
| GET, PUT, DELETE | `/api/scripts/{id}` | read / save `{text, target_seconds?}` / delete |
| POST | `/api/scripts/estimate` | `{text, target_seconds, campaign_id?}` → speaking time + warnings |

### Voice
| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/api/voices` | voice profiles; `{provider: system|elevenlabs, name, voice_id?, settings?, authorized}` |
| PATCH, DELETE | `/api/voices/{id}` | update settings / authorisation, delete |
| GET | `/api/voices/elevenlabs/catalog` | voices on your ElevenLabs account |
| POST | `/api/scripts/{id}/narration` | `{voice_profile_id?}` synthesise (cached) |
| GET | `/api/narrations?script_id=` | list |
| POST | `/api/narrations/{id}/transcribe` | `{prefer?}` word timestamps |

### Media and segments
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/media?kind=&campaign_id=` | library |
| GET | `/api/media/sfx-categories` | SFX categories |
| POST | `/api/media/import-path` | `{path, kind?, campaign_id?, category?, license_note?}` reference a local file |
| POST | `/api/media/upload` | multipart upload (stored as a managed copy) |
| PATCH, DELETE | `/api/media/{id}` | tags/category/licence/campaign; delete (user originals are never deleted) |
| POST | `/api/media/{id}/analyze` | job: gameplay analysis |
| GET, POST | `/api/media/{id}/segments` | list / add a manual segment `{start, end, label}` |
| PATCH, DELETE | `/api/segments/{id}` | adjust / disable / delete |
| GET | `/api/files/media/{id}`, `/api/files/thumb/{id}`, `/api/files/narration/{id}`, `/api/files/render/{project}`, `/api/files/export/{project}` | file streaming for previews (supports range requests) |

### Templates
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/templates` | built-in + user templates |
| GET, PUT, DELETE | `/api/templates/{id}` | read / save a user template (validated) / delete a user template |

### Projects (one video each)
| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/api/projects?campaign_id=` | list / create `{campaign_id, idea_id?, title?, template_id?, media_ids?}` |
| GET | `/api/projects/variation-report?ids=a,b,c` | hook, script, footage and SFX overlap between videos |
| GET, PATCH, DELETE | `/api/projects/{id}` | detail with stages / edit inputs / delete |
| POST | `/api/projects/{id}/duplicate` | copy with a new seed |
| POST, PUT | `/api/projects/{id}/script` | generate `{target_seconds?, use_ai?}` / choose `{script_id}` |
| POST | `/api/projects/{id}/voice` | narration + word timings |
| POST, PUT | `/api/projects/{id}/timeline` | build / save an edited timeline (schema-validated) |
| POST | `/api/projects/{id}/render` | job: `{quality?}` |
| POST | `/api/projects/{id}/qa` | run QA |
| POST | `/api/projects/{id}/pipeline` | job: all remaining steps through QA |
| POST | `/api/projects/{id}/status` | `{status, note?}` REVIEW / APPROVED / REJECTED (note required) / DRAFT |
| POST | `/api/projects/{id}/export` | copy to `exports/` (needs APPROVED) |
| GET | `/api/projects/{id}/publish-kit` | caption, hashtags, platform links, file |
| POST | `/api/projects/{id}/publish` | `{provider: "youtube", confirm: true, options?}` private API upload (needs EXPORTED and YOUTUBE_ACCESS_TOKEN) |
| POST | `/api/projects/{id}/mark-posted` | `{platform, post_url}` record a manual post |

### Jobs, submissions, analytics
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/jobs`, `/api/jobs/{id}` | job list / status |
| GET, POST | `/api/submissions?campaign_id=` | posts / add one |
| PATCH, DELETE | `/api/submissions/{id}` | status (PENDING, SUBMITTED, APPROVED, REJECTED, PAID), metrics, earnings, notes |
| POST | `/api/submissions/{id}/refresh-metrics` | fetch metrics from the YouTube API (YouTube uploads only) |
| GET | `/api/analytics?campaign_id=` | totals, effective CPM, groupings, small-sample note |
| GET | `/api/dashboard` | dashboard numbers and recent projects |
