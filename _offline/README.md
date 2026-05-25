# Offline Bundle Layout

Use this folder when you want the custom node to install and run without any network access on the target machine.

Expected local bundle layout:

- `_offline/wheels/` for Python wheels used by the ComfyUI Python environment
- `_offline/models/HeartMuLa/` for the final on-disk HeartMuLa model root

Recommended flow:

1. On a connected machine, populate `_offline/wheels/` and optionally `_offline/models/HeartMuLa/` with `./scripts/build_offline_bundle.sh`.
2. Move the whole repository folder to the offline machine.
3. Place the repo in `ComfyUI/custom_nodes/ComfyUI-MPC-HeartMuLa`.
4. Run `./scripts/install_offline.sh --python /path/to/comfyui/python --comfyui-root /path/to/ComfyUI`.

Notes:

- `./scripts/install_offline.sh` creates `_offline/STRICT_OFFLINE` locally so runtime will reject network fallback paths.
- Actual wheels and model weights are ignored by git on purpose so they do not get committed accidentally.
- Extension Manager installs are not the offline path because they still depend on network access to fetch the repository.