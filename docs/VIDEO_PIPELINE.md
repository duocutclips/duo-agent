# Video pipeline

## 1. Media ingestion (`media.py`)

* Video: MP4, MOV, WEBM, MKV, M4V · images: PNG, JPG, WEBP, GIF, BMP · audio: MP3, WAV, M4A, OGG, FLAC, AAC, OPUS (SFX: WAV, MP3, OGG).
* Files are **referenced in place** (no copy) unless uploaded through the browser. Identical content (SHA-256 + kind) is not imported twice.
* ffprobe metadata: duration, resolution (rotation-aware), fps, codecs, audio presence, orientation. Thumbnails: a video frame, the image, or an audio waveform.
* Music needs a licence note. SFX have a category: impact, whoosh, click, pop, success, fail, transition, notification, comedic, gameplay.

## 2. Gameplay analysis (`analysis.py`)

Frames are decoded at 4 fps, 96 px wide, grayscale; audio as mono PCM.

| Signal | Method |
|---|---|
| Motion | mean absolute difference between consecutive frames |
| Scene cuts | 32-bin luma histogram L1 distance > 0.5, or frame difference above max(30, 4 × median) |
| Black | mean brightness < 14 |
| Static | motion < 0.6 for ≥ 2 s |
| Repeated footage | 16×16 thumbnails of one-second windows closer than 3 and than 0.35 × their neighbours' distance |
| Loudness, silence | RMS dB in 0.25 s windows; silence < −45 dB |
| Audio peaks | ≥ 10 dB above 0.5 s earlier (sharp onsets only) |

Windows between cuts (1.5–4 s) become segments with a score from motion, peaks and penalties for black/static/repeated footage. Labels describe what was measured: "High action", "Sharp loud sound (possible impact/reaction)", "Calm footage (B-roll)", "Static or black (avoid)", "… repeats earlier footage". The analyzer does not claim to know game events. The best three become hook candidates. Re-analysis replaces only automatic segments; your manual segments stay.

## 3. Narration and word timings

1. `voice.py` synthesises the script: ElevenLabs `/text-to-speech/{voice}/with-timestamps` (character timings → word timings), or the offline system voice (espeak-ng / macOS `say` / Windows SAPI). Results are cached by provider + voice + model + settings + text.
2. `transcription.py` picks the best available word timings: Whisper-compatible API → local faster-whisper (if installed) → TTS alignment → **estimated alignment** (script words spread by syllables over the speech regions FFmpeg `silencedetect` finds, never across a pause).

## 4. Timeline (`timeline.py`)

A timeline is JSON validated against `packages/timeline-schema/timeline.schema.json`:

```json
{ "version": 1, "width": 1080, "height": 1920, "fps": 30, "duration": 29.23, "template_id": "roblox_secret", "seed": 1,
  "caption_style": {…}, "title_style": {…},
  "items": [
    {"type": "video", "source": "…/gameplay_a.mp4", "media_id": "…", "segment_id": "…", "src_in": 10.62, "start": 0, "end": 1.75, "fit": "blur"},
    {"type": "zoom", "start": 0.3, "duration": 1.2, "scale": 1.12, "ramp": 0.22},
    {"type": "caption", "start": 0.15, "end": 0.95, "text": "Most players walk", "words": [{"text": "Most", "start": 0.15, "end": 0.4, "emphasis": false}, …]},
    {"type": "text", "role": "title", "start": 0, "end": 1.8, "text": "…"},
    {"type": "narration", "source": "…", "start": 0.15, "volume": 1.0},
    {"type": "music", "source": "…", "volume": 0.22, "duck_to": 0.25, "fade_in": 0.6, "fade_out": 1.2, "loop": true},
    {"type": "sfx", "source": "…", "category": "whoosh", "reason": "cut", "start": 1.75, "volume": 0.55},
    {"type": "fade", "direction": "in", "start": 0, "duration": 0.15}
  ] }
```

The editor:

* Length = narration + CTA hold. Cuts fall on sentence ends, then phrase ends, then word starts, within the template's min/max shot length.
* Segments are picked with a seeded RNG: the best-scoring segment opens the video (hook), then variety is rewarded and reuse penalised (same segment, same source back-to-back, repeated footage, segments already used by other videos in the campaign).
* Zooms every N cuts and on emphasis words; SFX at the hook, cuts and emphasis words (density from the template); music chosen by seed unless set; title card from the hook and CTA card at the end.
* Video clips must be contiguous from 0 to `duration`. The UI can move cuts, shift source in-points, edit captions (timings kept or re-spread) or edit the raw JSON; every save is validated.

## 5. Rendering (`render.py`)

**Stage A: one intermediate per video item** (cached by source, in-point, length, filter graph and quality):

* `fps=30`, `tpad` to hold the last frame if the source is short, then either crop-to-fill or **blur fill** (blurred, darkened copy behind the scaled footage).
* Zoom with `zoompan` after composing the 1080×1920 frame, using a trapezoid (ramp in, hold, ramp out) expression.
* Exact frame count (`-frames:v`), no audio. Clips render in parallel.

**Stage B: composition**

* concat demuxer → fades → image overlays → ASS subtitles (`ass=captions.ass:fontsdir=fonts`, bundled font) with one event per spoken word so the active word is highlighted and slightly enlarged.
* Audio: narration delayed to its start; music looped (`-stream_loop -1`), faded, **ducked under the voice** with `sidechaincompress`; SFX delayed to their times; `amix` (no auto-normalisation) → `loudnorm I=-14` → AAC 192 kbps 48 kHz stereo.
* H.264 High, yuv420p, CRF 19 (`final`) or 24 (`draft`), `+faststart`, metadata stripped.

**Determinism.** Single-threaded x264 and filter graph, `+bitexact` flags, fixed frame counts and no timestamps: the same timeline on the same FFmpeg build produces a byte-identical file (tested). The output name contains the timeline hash, so re-rendering an unchanged timeline returns the cached file instantly.

## 6. QA (`qa.py`)

| Check | Rule |
|---|---|
| File exists, FFmpeg completed | |
| No corruption | full decode; any decoder error fails the check |
| Resolution / aspect | exactly 1080×1920, 9:16 |
| Encoding | H.264 yuv420p + AAC, 30 fps |
| Duration | timeline length ± 0.25 s, and inside confirmed campaign min/max |
| Audio, Narration | audio stream present; narration item present |
| Silence | no gap longer than 1.5 s below −50 dB (configurable in Settings) |
| Captions | caption items present |
| Black frames | none outside the intended fade windows |
| Campaign requirements, required phrases | confirmed required wording and codes appear in the script; no restricted terms |

READY only if every applicable check passes. A READY draft moves to REVIEW; approval is always manual.

## 7. Export

`exports/<campaign-slug>/concept-<NN>-<category>.mp4` with a `.txt` of the caption and hashtags. If the name exists with different content, `-v2`, `-v3`… are used; identical content re-uses the existing file. Files are copied via a `.partial` temp file and renamed, so a crash never leaves a half-written export.
