# ComfyUI-MPC-HeartMuLa

![ComfyUI-MPC-HeartMuLa hero](assets/hero-banner.svg)

ComfyUI custom nodes for HeartMuLa music generation with a workflow surface built around the controls you asked for: tags, BPM, song key, duration, lyrics, optional outro or tag ending, and lyric compliance checking after generation.

![Example workflow preview](assets/workflow-preview.svg)

## What this package does

- Uses the best currently released open HeartMuLa stack for music quality and lyric controllability:
  - `HeartMuLa-oss-3B-happy-new-year`
  - `HeartCodec-oss-20260123`
- Targets Apple Silicon well by default.
  - `auto` tries MPS for both model and codec first.
  - If that fails, it falls back to MPS for HeartMuLa and CPU for HeartCodec.
- Saves lossless `.wav` output in the ComfyUI output folder.
- Auto-downloads the required model assets into `ComfyUI/models/HeartMuLa` on first use.

## Quick Start

1. Install from the ComfyUI Extension Manager or clone into `custom_nodes`.
2. Install Python requirements using the same Python that launches ComfyUI.
3. Import `workflows/heartmula_simple_song_workflow.json`.
4. Edit the lyrics, tags, BPM, song key, and duration inside `HeartMuLa Song Spec`.
5. Run the workflow.
6. Review the generated `.wav` and the lyric compliance report.

## Important note on model size

HeartMuLa mentions an internal 7B model, but the open-source 7B checkpoint is not released yet. The largest public option today is the 3B line, and the recommended quality preset is `HeartMuLa-oss-3B-happy-new-year`.

## Installation

### Extension Manager

![Extension Manager install overview](assets/extension-manager-preview.svg)

Once this repository is pushed to GitHub, install it from the ComfyUI Extension Manager by repository URL:

`https://github.com/MPC2026/ComfyUI-MPC-HeartMuLa.git`

The node pack already has the standard custom-node entrypoints and a `requirements.txt` for dependency installation.

Extension Manager path:

1. Open ComfyUI.
2. Open `Manager`.
3. Open `Custom Nodes` or `Install via Git URL`, depending on your manager version.
4. Paste `https://github.com/MPC2026/ComfyUI-MPC-HeartMuLa.git`.
5. Install the node.
6. Restart ComfyUI.
7. Install Python requirements if your manager did not do it automatically.

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

### Import the included workflow

1. Start ComfyUI after installing the node.
2. Drag `workflows/heartmula_simple_song_workflow.json` onto the canvas.
3. Or use the workflow load/import menu and select that file.
4. Run the workflow once to let the models download.

### First run

1. Import the included workflow or add the three spec-based nodes manually.
2. Leave `runtime_profile` on `auto` for Apple Silicon.
3. Run the workflow once.
4. Wait for the model download to finish on the first run.
5. Find the generated `.wav` in your ComfyUI output folder.
6. Read the lyric compliance score and report on the final node.

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
- `song_spec` for simple linked workflows

### `HeartMuLa Generate From Spec`

Uses the `song_spec` output from `HeartMuLa Song Spec` so you can keep the workflow to a single connected generation path.

Returns:

- `AUDIO`
- saved file path
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

### `HeartMuLa Lyrics Compliance From Spec`

Consumes `song_spec` directly so the compliance check automatically compares against the same lyrics used to generate the song.

## Recommended simple workflow

`HeartMuLa Song Spec` -> `HeartMuLa Generate From Spec` -> `HeartMuLa Lyrics Compliance From Spec`

Use the included workflow JSON if you want the fastest start. The older `Generate Music` and `Lyrics Compliance` nodes are still there for more manual setups.

Included example workflow:

- `workflows/heartmula_simple_song_workflow.json`

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