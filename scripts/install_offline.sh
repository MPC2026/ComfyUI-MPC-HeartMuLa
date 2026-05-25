#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./scripts/install_offline.sh [options]

Install ComfyUI-MPC-HeartMuLa using only local wheels and local model files.

Options:
  --python PATH        Python executable used by ComfyUI (default: python3)
  --comfyui-root PATH  ComfyUI root directory; models install to PATH/models/HeartMuLa
  --model-root PATH    Explicit HeartMuLa target model root
  --skip-python        Skip Python package installation
  --skip-models        Skip model copy/verification
  --help               Show this help text
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="python3"
WHEEL_DIR="$REPO_ROOT/_offline/wheels"
LOCK_FILE="$REPO_ROOT/_offline/requirements-lock.txt"
MODEL_BUNDLE_ROOT="$REPO_ROOT/_offline/models/HeartMuLa"
STRICT_OFFLINE_MARKER="$REPO_ROOT/_offline/STRICT_OFFLINE"
TARGET_MODEL_ROOT=""
COMFYUI_ROOT=""
SKIP_PYTHON=0
SKIP_MODELS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python)
            PYTHON_BIN="$2"
            shift 2
            ;;
        --comfyui-root)
            COMFYUI_ROOT="$2"
            shift 2
            ;;
        --model-root)
            TARGET_MODEL_ROOT="$2"
            shift 2
            ;;
        --skip-python)
            SKIP_PYTHON=1
            shift
            ;;
        --skip-models)
            SKIP_MODELS=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -n "$COMFYUI_ROOT" && -z "$TARGET_MODEL_ROOT" ]]; then
    TARGET_MODEL_ROOT="$COMFYUI_ROOT/models/HeartMuLa"
fi

shopt -s nullglob

module_installed() {
    local module_name="$1"
    "$PYTHON_BIN" - <<PY
import importlib.util
import sys

sys.exit(0 if importlib.util.find_spec("$module_name") is not None else 1)
PY
}

has_supported_generation_pair() {
    local root="$1"

    [[ -f "$root/HeartMuLa-RL-oss-3B-20260123/config.json" && -f "$root/HeartCodec-oss-20260123/config.json" ]] && return 0
    [[ -f "$root/HeartMuLa-oss-3B-happy-new-year/config.json" && -f "$root/HeartCodec-oss-20260123/config.json" ]] && return 0
    [[ -f "$root/HeartMuLa-oss-3B/config.json" && -f "$root/HeartCodec-oss/config.json" ]] && return 0
    return 1
}

model_root_ready() {
    local root="$1"

    [[ -f "$root/gen_config.json" ]] || return 1
    [[ -f "$root/tokenizer.json" ]] || return 1
    [[ -f "$root/HeartTranscriptor-oss/config.json" ]] || return 1
    has_supported_generation_pair "$root"
}

if [[ "$SKIP_PYTHON" -eq 0 ]]; then
    wheel_files=("$WHEEL_DIR"/*.whl)
    if [[ ${#wheel_files[@]} -eq 0 ]]; then
        echo "No local wheels were found in $WHEEL_DIR" >&2
        echo "Build the bundle on a connected machine with ./scripts/build_offline_bundle.sh first." >&2
        exit 1
    fi

    install_spec_file="$REPO_ROOT/requirements.txt"
    if [[ -f "$LOCK_FILE" ]]; then
        install_spec_file="$LOCK_FILE"
    fi

    "$PYTHON_BIN" -m pip install --no-index --find-links "$WHEEL_DIR" -r "$install_spec_file"

    if ! module_installed "torchaudio"; then
        "$PYTHON_BIN" -m pip install --no-index --find-links "$WHEEL_DIR" torchaudio
    fi

    if ! module_installed "torch"; then
        torch_wheels=("$WHEEL_DIR"/torch-*.whl)
        if [[ ${#torch_wheels[@]} -gt 0 ]]; then
            "$PYTHON_BIN" -m pip install --no-index --find-links "$WHEEL_DIR" torch
        else
            echo "torch is not installed in $PYTHON_BIN and no local torch wheel was found in $WHEEL_DIR" >&2
            echo "Use the exact ComfyUI Python environment or rebuild the bundle with --include-torch." >&2
            exit 1
        fi
    fi

    "$PYTHON_BIN" - <<'PY'
import importlib.util
import sys

required = [
    "accelerate",
    "certifi",
    "einops",
    "huggingface_hub",
    "numpy",
    "soundfile",
    "tokenizers",
    "torch",
    "torchao",
    "torchaudio",
    "torchtune",
    "tqdm",
    "transformers",
    "vector_quantize_pytorch",
]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("Missing modules after offline install: " + ", ".join(missing))
PY
fi

if [[ "$SKIP_MODELS" -eq 0 ]]; then
    if [[ -z "$TARGET_MODEL_ROOT" ]]; then
        echo "Pass --comfyui-root or --model-root so the installer knows where HeartMuLa models belong." >&2
        exit 1
    fi

    if ! model_root_ready "$TARGET_MODEL_ROOT"; then
        if [[ ! -f "$MODEL_BUNDLE_ROOT/gen_config.json" ]]; then
            echo "Target model root is incomplete and no local model bundle was found in $MODEL_BUNDLE_ROOT" >&2
            echo "Copy a prepared HeartMuLa model root into _offline/models/HeartMuLa or rebuild the bundle with --model-root." >&2
            exit 1
        fi

        mkdir -p "$TARGET_MODEL_ROOT"
        cp -R "$MODEL_BUNDLE_ROOT"/. "$TARGET_MODEL_ROOT"/
    fi

    if ! model_root_ready "$TARGET_MODEL_ROOT"; then
        echo "HeartMuLa models are still incomplete after local copy into $TARGET_MODEL_ROOT" >&2
        exit 1
    fi
fi

mkdir -p "$(dirname "$STRICT_OFFLINE_MARKER")"
printf 'strict offline enabled\n' > "$STRICT_OFFLINE_MARKER"

cat <<EOF
Offline install complete.

Python: $PYTHON_BIN
Strict offline marker: $STRICT_OFFLINE_MARKER
Model root: ${TARGET_MODEL_ROOT:-not changed}

Keep auto_download_models disabled in the nodes. Runtime network fallback paths are now blocked intentionally.
EOF