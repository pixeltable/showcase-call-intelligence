# Compare fixture attribution

## Call-center audio (committed in repo)

| File | Description |
|------|-------------|
| `billing-inquiry-speech.wav` | Synthetic two-speaker billing inquiry (~6s) |
| `cancellation-request.wav` | Synthetic two-speaker cancellation / retention call |

These WAVs are mono 16 kHz PCM, generated for local demo and parity testing.

## Sales audio (committed in repo)

| File | Description |
|------|-------------|
| `sales-discovery.wav` | Synthetic two-speaker sales discovery call (objections, demo follow-up) |

Generated via [`scripts/generate_fixture_audio.py`](../../scripts/generate_fixture_audio.py) (macOS `say` + ffmpeg).

## Interview audio (committed in repo)

| File | Description |
|------|-------------|
| `interview-behavioral.wav` | Synthetic two-speaker behavioral interview Q&A |

Generated via [`scripts/generate_fixture_audio.py`](../../scripts/generate_fixture_audio.py).

## Podcast audio (derived)

| File | Source |
|------|--------|
| `podcast-excerpt-audio.wav` | First 45s of `lex-fridman-excerpt.mp4`, extracted via [`scripts/prepare_fixture_media.py`](../../scripts/prepare_fixture_media.py) |

## Video (downloaded via `scripts/fetch_fixtures.py`)

Sourced from the [Pixeltable documentation resources](https://github.com/pixeltable/pixeltable/tree/main/docs/resources):

| Local file | Upstream |
|------------|----------|
| `pursuit-happiness-video.mp4` | `The-Pursuit-of-Happiness-Video-Extract.mp4` |
| `lex-fridman-excerpt.mp4` | `audio-transcription-demo/Lex-Fridman-Podcast-430-Excerpt-0.mp4` |
| `travel-briefing.mp4` | `audio-transcription-demo/Lex-Fridman-Podcast-430-Excerpt-1.mp4` |

URLs and SHA256 checksums are pinned in [`sources.json`](sources.json).

## Derived video copies (prepared, gitignored)

Unique filenames for compare seed state keys; same bytes as upstream clips:

| Local file | Copied from | Used as |
|------------|-------------|---------|
| `sales-demo-video.mp4` | `pursuit-happiness-video.mp4` | Sales vertical video fixture |
| `interview-session.mp4` | `travel-briefing.mp4` | Interview vertical video fixture |

Created via [`scripts/prepare_fixture_media.py`](../../scripts/prepare_fixture_media.py).

Manifest metadata (`agent_id`, `queue`, `vertical`, etc.) is fictional — the UI maps metadata slots per vertical profile even when underlying clip content differs.

## Seed manifest

The canonical 10-fixture vertical matrix lives in [`manifest.json`](manifest.json): at least one audio and one video per vertical (`call_center`, `sales`, `podcast`, `interview`).

## Removed

- `billing-call.mp4` — too short (~32 KB) and produced empty transcripts.
- `bangkok-scene.mp4` — video-only (no audio track); Reference ffmpeg extraction failed.
- `account-verification.wav` — orphan local asset, not in the seed manifest.
