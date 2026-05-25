# ComfyUI-MPC-HeartMuLa

ComfyUI custom nodes for HeartMuLa music generation with a workflow surface built around the controls you asked for: tags, BPM, song key, duration, lyrics, and optional outro or tag ending.

## What this package does

- Uses the best currently released open HeartMuLa stack for music quality and lyric controllability:
  - `HeartMuLa-oss-3B-happy-new-year`
  - `HeartCodec-oss-20260123`
- Targets Apple Silicon well by default.
  - `auto` tries MPS for both model and codec first.
  - If that fails, it falls back to MPS for HeartMuLa and CPU for HeartCodec.
- Saves lossless `.wav` output in the ComfyUI output folder.
- Auto-downloads the required model assets into `ComfyUI/models/HeartMuLa` on first use.

## Important note on model size

HeartMuLa mentions an internal 7B model, but the open-source 7B checkpoint is not released yet. The largest public option today is the 3B line, and the recommended quality preset is `HeartMuLa-oss-3B-happy-new-year`.

## Installation

### Extension Manager

Once this repository is pushed to GitHub, install it from the ComfyUI Extension Manager by repository URL:

`https://github.com/MPC2026/ComfyUI-MPC-HeartMuLa.git`

The node pack already has the standard custom-node entrypoints and a `requirements.txt` for dependency installation.

### Simple custom node install

1. Close ComfyUI.
2. Open a terminal and go to your ComfyUI folder.
3. Go into `custom_nodes`.
4. Clone this repo so the final folder is `ComfyUI/custom_nodes/ComfyUI-MPC-HeartMuLa`.
5. Activate the exact Python environment you use to start ComfyUI.
6. From this node folder, run `pip install -r requirements.txt`.
7. Start ComfyUI again.
8. Search for `HeartMuLa` in the node picker.

Example:

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/MPC2026/ComfyUI-MPC-HeartMuLa.git
cd ComfyUI-MPC-HeartMuLa
pip install -r requirements.txt
```

If your ComfyUI launcher uses a bundled Python, use that Python for the install command instead of system `pip`.

### First run

1. Add `HeartMuLa Song Spec`.
2. Add `HeartMuLa Generate Music`.
3. Connect `lyrics`, `tags`, and `max_audio_length_ms` from the spec node into the generate node.
4. Leave `runtime_profile` on `auto` for Apple Silicon.
5. Run the workflow once.
6. Wait for the model download to finish on the first run.
7. Find the generated `.wav` in your ComfyUI output folder.

## First-run downloads

The first generation run downloads these public assets automatically:

- `HeartMuLa/HeartMuLaGen`
- `HeartMuLa/HeartMuLa-oss-3B-happy-new-year`
- `HeartMuLa/HeartCodec-oss-20260123`
- `HeartMuLa/HeartTranscriptor-oss` when you use lyric compliance checking

They are stored under `ComfyUI/models/HeartMuLa` using the directory names expected by the official `heartlib` pipeline.

## Nodes

### `HeartMuLa Song Spec`

Builds generation-ready lyrics and comma-separated tags from:

- raw lyrics
- style tags
- BPM
- song key
- duration
- optional outro or tag ending

Outputs:

- formatted lyrics
- effective tags
- `max_audio_length_ms`
- metadata JSON

### `HeartMuLa Generate Music`

Runs HeartMuLa generation and returns:

- `AUDIO`
- saved file path
- metadata JSON

### `HeartMuLa Lyrics Compliance`

Transcribes generated audio with HeartTranscriptor and compares it against your intended lyrics.

Returns:

- transcribed lyrics
- similarity score
- exact match boolean
- report JSON

## Recommended simple workflow

`HeartMuLa Song Spec` -> `HeartMuLa Generate Music` -> `HeartMuLa Lyrics Compliance`

Use the first node for prompt construction, the second node for generation, and the third node to check how closely the vocals follow the written lyrics.

## Apple Silicon defaults

For a 2026 MacBook Pro M5 Max with 128 GB RAM, the defaults are tuned toward quality first without forcing a fragile setup:

- `runtime_profile = auto`
- `keep_model_loaded = true`
- `cfg_scale = 1.8`
- `.wav` output

## Lyric adherence and prompt behavior

HeartMuLa currently accepts only `lyrics` and comma-separated `tags` as conditioning inputs. This package maps BPM and song key into tags and appends an optional `[Outro]` block when requested.

Two limits come from upstream HeartMuLa itself:

- text is lowercased internally by the official pipeline
- exact lyric reproduction is improved but still model-limited rather than guaranteed

This node pack biases toward lyric clarity by adding `clear vocals` and `lyric forward` tags to the generated prompt.

The lyric compliance node helps you measure that gap after generation instead of guessing.