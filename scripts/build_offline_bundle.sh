#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./scripts/build_offline_bundle.sh [options]

Create the local asset bundle used by the offline installer.
The wheel bundle is taken from the selected Python environment's installed
runtime versions so the offline target matches the source ComfyUI runtime.

Options:
  --python PATH        Python executable to use for pip download (default: python3)
  --bundle-root PATH   Bundle root to populate (default: ./_offline)
  --model-root PATH    Existing HeartMuLa model root to copy into the bundle
  --include-torch      Download a torch wheel that matches the selected Python env
  --skip-torchaudio    Skip downloading a torchaudio wheel from the selected Python env
  --help               Show this help text
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="python3"
BUNDLE_ROOT="$REPO_ROOT/_offline"
WHEEL_DIR="$BUNDLE_ROOT/wheels"
MODEL_BUNDLE_ROOT="$BUNDLE_ROOT/models/HeartMuLa"
LOCK_FILE="$BUNDLE_ROOT/requirements-lock.txt"
MODEL_SOURCE=""
INCLUDE_TORCH=0
INCLUDE_TORCHAUDIO=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python)
            PYTHON_BIN="$2"
            shift 2
            ;;
        --bundle-root)
            BUNDLE_ROOT="$2"
            WHEEL_DIR="$BUNDLE_ROOT/wheels"
            MODEL_BUNDLE_ROOT="$BUNDLE_ROOT/models/HeartMuLa"
            shift 2
            ;;
        --model-root)
            MODEL_SOURCE="$2"
            shift 2
            ;;
        --include-torch)
            INCLUDE_TORCH=1
            shift
            ;;
        --skip-torchaudio)
            INCLUDE_TORCHAUDIO=0
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

mkdir -p "$WHEEL_DIR" "$BUNDLE_ROOT/models"

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

copy_model_bundle() {
    local src="$1"
    local dst="$2"

    rm -rf "$dst"
    if cp -cR "$src" "$dst" 2>/dev/null; then
        return 0
    fi

    cp -R "$src" "$dst"
}

write_runtime_lockfile() {
    HEARTMULA_INCLUDE_TORCH="$INCLUDE_TORCH" HEARTMULA_INCLUDE_TORCHAUDIO="$INCLUDE_TORCHAUDIO" "$PYTHON_BIN" - "$LOCK_FILE" <<'PY'
from importlib import metadata, util
import os
from pathlib import Path
import sys

pairs = [
    ("accelerate", "accelerate"),
    ("certifi", "certifi"),
    ("einops", "einops"),
    ("huggingface_hub", "huggingface_hub"),
    ("numpy", "numpy"),
    ("soundfile", "soundfile"),
    ("tokenizers", "tokenizers"),
]

if os.environ.get("HEARTMULA_INCLUDE_TORCH") == "1":
    pairs.append(("torch", "torch"))

if os.environ.get("HEARTMULA_INCLUDE_TORCHAUDIO") == "1":
    pairs.append(("torchaudio", "torchaudio"))

pairs.extend(
    [
        ("torchao", "torchao"),
        ("torchtune", "torchtune"),
        ("tqdm", "tqdm"),
        ("transformers", "transformers"),
        ("vector_quantize_pytorch", "vector-quantize-pytorch"),
    ]
)

missing = []
lines = []
for module_name, package_name in pairs:
    if util.find_spec(module_name) is None:
        missing.append(package_name)
        continue
    version = metadata.version(package_name)
    lines.append(f"{package_name}=={version}")

if missing:
    raise SystemExit(
        "Selected Python is missing required runtime packages: " + ", ".join(missing)
    )

Path(sys.argv[1]).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

download_installed_wheel() {
    local module_name="$1"
    local package_name="$2"

    local version
    version="$($PYTHON_BIN - <<PY
import importlib
import importlib.util

if importlib.util.find_spec("$module_name") is None:
    print("")
else:
    module = importlib.import_module("$module_name")
    print(getattr(module, "__version__", ""))
PY
)"

    if [[ -z "$version" ]]; then
        echo "Skipping $package_name wheel download because $module_name is not installed in $PYTHON_BIN"
        return
    fi

    "$PYTHON_BIN" -m pip download --only-binary=:all: --dest "$WHEEL_DIR" "$package_name==$version"
}

write_runtime_lockfile
"$PYTHON_BIN" -m pip download --only-binary=:all: --dest "$WHEEL_DIR" -r "$LOCK_FILE"

if [[ "$INCLUDE_TORCHAUDIO" -eq 1 ]]; then
    download_installed_wheel "torchaudio" "torchaudio"
fi

if [[ "$INCLUDE_TORCH" -eq 1 ]]; then
    download_installed_wheel "torch" "torch"
fi

if [[ -n "$MODEL_SOURCE" ]]; then
    if ! model_root_ready "$MODEL_SOURCE"; then
        echo "Model source is missing required HeartMuLa assets: $MODEL_SOURCE" >&2
        echo "Expected gen_config.json, tokenizer.json, HeartTranscriptor-oss/config.json, and one supported model+codec pair." >&2
        exit 1
    fi

    copy_model_bundle "$MODEL_SOURCE" "$MODEL_BUNDLE_ROOT"
fi

WHEEL_COUNT="$(find "$WHEEL_DIR" -maxdepth 1 -type f | wc -l | tr -d ' ')"
MODEL_STATE="not included"
if [[ -d "$MODEL_BUNDLE_ROOT" ]]; then
    MODEL_STATE="$MODEL_BUNDLE_ROOT"
fi

cat > "$BUNDLE_ROOT/bundle-manifest.txt" <<EOF
Created: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Python: $PYTHON_BIN
Wheel directory: $WHEEL_DIR
Wheel count: $WHEEL_COUNT
Included torch wheel: $INCLUDE_TORCH
Included torchaudio wheel: $INCLUDE_TORCHAUDIO
Locked package list: $LOCK_FILE
Model bundle: $MODEL_STATE
EOF

cat <<EOF
Offline bundle ready.

Wheels: $WHEEL_DIR
Models: $MODEL_STATE
Locked package list: $LOCK_FILE
Manifest: $BUNDLE_ROOT/bundle-manifest.txt

Next step on the offline machine:
  ./scripts/install_offline.sh --python /path/to/comfyui/python --comfyui-root /path/to/ComfyUI
EOF