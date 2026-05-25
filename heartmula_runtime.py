from __future__ import annotations

"""HeartMuLa runtime glue for ComfyUI.

This node pack follows the official ``heartlib`` pipeline API at runtime while
keeping the official HeartMuLa checkpoint folder names on disk under
``ComfyUI/models/HeartMuLa``.

For Apple Silicon, ``auto`` mode prefers the split-device path supported by
``heartlib``: HeartMuLa on MPS, HeartCodec on CPU, then CPU-only fallback.
"""

import difflib
import gc
import importlib
import importlib.util
import os
import re
import shlex
import shutil
import ssl
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import folder_paths
import torch

HEARTLIB_ARCHIVE_URL = "https://codeload.github.com/HeartMuLa/heartlib/zip/refs/heads/main"
HEARTLIB_ARCHIVE_ROOT = "heartlib-main"
GEN_CONFIG_REPO = "HeartMuLa/HeartMuLaGen"
AUTO_DOWNLOAD_MUSIC_MODEL_REPO = "HeartMuLa/HeartMuLa-oss-3B"
AUTO_DOWNLOAD_CODEC_MODEL_REPO = "HeartMuLa/HeartCodec-oss"
TRANSCRIPTOR_MODEL_REPO = "HeartMuLa/HeartTranscriptor-oss"
MODEL_NAMESPACE = "HeartMuLa"
AUTO_DOWNLOAD_MODEL_VARIANT = "HeartMuLa-oss-3B"
AUTO_DOWNLOAD_CODEC_VARIANT = "HeartCodec-oss"
TRANSCRIPTOR_VARIANT = "HeartTranscriptor-oss"
VENDOR_ROOT = Path(__file__).resolve().parent / "_vendor"
HEARTLIB_SOURCE_ROOT = VENDOR_ROOT / HEARTLIB_ARCHIVE_ROOT / "src"
SUPPORTED_GENERATION_LAYOUTS = (
    ("HeartMuLa-RL-oss-3B-20260123", "HeartCodec-oss-20260123"),
    ("HeartMuLa-oss-3B-happy-new-year", "HeartCodec-oss-20260123"),
    ("HeartMuLa-oss-3B", "HeartCodec-oss"),
)

_PIPELINE_CACHE: dict[tuple[str, str, str], Any] = {}
_TRANSCRIPTOR_CACHE: dict[tuple[str, str], Any] = {}


@dataclass(frozen=True)
class RuntimeProfile:
    key: str
    label: str
    mula_device: torch.device
    codec_device: torch.device
    mula_dtype: torch.dtype
    codec_dtype: torch.dtype
    lazy_load: bool = False


@dataclass(frozen=True)
class TranscriptionProfile:
    key: str
    label: str
    device: torch.device
    dtype: torch.dtype


@dataclass(frozen=True)
class GenerationAssets:
    model_root: Path
    model_variant: str
    codec_variant: str
    model_path: Path
    codec_path: Path
    tokenizer_path: Path
    gen_config_path: Path


def build_condition_tags(
    style_tags: str,
    bpm: int,
    song_key: str,
    duration_seconds: int,
) -> str:
    raw_tags = style_tags.replace("\r\n", "\n").replace("\n", ",").split(",")
    cleaned: list[str] = []
    for tag in raw_tags:
        value = " ".join(tag.strip().split())
        if value:
            cleaned.append(value.lower())

    derived = [f"{bpm}bpm", song_key.strip().lower(), "clear vocals", "lyric forward"]
    if duration_seconds >= 120:
        derived.append("full song")
    elif duration_seconds <= 30:
        derived.append("short song")

    seen: set[str] = set()
    ordered: list[str] = []
    for tag in cleaned + derived:
        if tag not in seen:
            ordered.append(tag)
            seen.add(tag)
    return ",".join(ordered)


def build_lyrics_with_ending(lyrics: str, ending_mode: str, ending_text: str) -> str:
    base = lyrics.replace("\r\n", "\n").strip()
    if not base:
        raise ValueError("lyrics cannot be empty")

    suffix = ending_text.replace("\r\n", "\n").strip()
    if ending_mode == "none" or not suffix:
        return base

    ending_lines = [line.strip() for line in suffix.split("\n") if line.strip()]
    if ending_mode == "tag ending" and ending_lines:
        ending_lines.append(ending_lines[-1])

    ending_block = "[Outro]"
    if ending_lines:
        ending_block = ending_block + "\n" + "\n".join(ending_lines)

    if base.endswith("[Outro]"):
        return base + "\n" + "\n".join(ending_lines)
    return base + "\n\n" + ending_block


def generate_music(
    lyrics: str,
    tags: str,
    max_audio_length_ms: int,
    runtime_profile: str,
    topk: int,
    temperature: float,
    cfg_scale: float,
    keep_model_loaded: bool,
    auto_download_models: bool,
    filename_prefix: str,
    seed: int,
):
    _ensure_runtime_dependencies()
    heartlib = _import_heartlib()
    torchaudio = importlib.import_module("torchaudio")

    model_root = get_model_root()
    if auto_download_models:
        ensure_model_assets(model_root)
    generation_assets = _resolve_generation_assets(model_root)

    output_dir = Path(folder_paths.get_output_directory())
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{filename_prefix}_{uuid.uuid4().hex}.wav"

    errors: list[str] = []
    for profile in _resolve_runtime_candidates(runtime_profile):
        try:
            pipe = _get_pipeline(heartlib, generation_assets, profile, keep_model_loaded)
            with torch.inference_mode():
                pipe(
                    {"lyrics": lyrics, "tags": tags},
                    max_audio_length_ms=max_audio_length_ms,
                    save_path=str(output_path),
                    topk=topk,
                    temperature=temperature,
                    cfg_scale=cfg_scale,
                )
            waveform, sample_rate = torchaudio.load(str(output_path))
            audio_output = _normalize_audio_output(waveform, sample_rate)
            metadata = {
                "model_root": str(model_root),
                "model_variant": generation_assets.model_variant,
                "codec_variant": generation_assets.codec_variant,
                "runtime_api": "heartlib",
                "model_layout": "official_HeartMuLa_folders",
                "requested_runtime_profile": runtime_profile,
                "effective_runtime_profile": profile.label,
                "seed": seed,
                "topk": topk,
                "temperature": temperature,
                "cfg_scale": cfg_scale,
                "max_audio_length_ms": max_audio_length_ms,
                "lyrics": lyrics,
                "tags": tags,
                "output_path": str(output_path),
            }
            if not keep_model_loaded:
                _release_pipeline(profile, generation_assets)
            return audio_output, str(output_path), metadata
        except Exception as exc:
            errors.append(f"{profile.label}: {exc}")
            _release_pipeline(profile, generation_assets)
            if output_path.exists():
                output_path.unlink()

    joined_errors = " | ".join(errors)
    raise RuntimeError(f"HeartMuLa generation failed. {joined_errors}")


def compare_generated_lyrics(
    audio_input: dict[str, Any],
    expected_lyrics: str,
    runtime_profile: str,
    auto_download_models: bool,
    keep_model_loaded: bool,
    temperature_tuple: str,
    no_speech_threshold: float,
    logprob_threshold: float,
):
    _ensure_runtime_dependencies()
    heartlib = _import_heartlib()
    torchaudio = importlib.import_module("torchaudio")

    model_root = get_model_root()
    if auto_download_models:
        ensure_transcriptor_assets(model_root)
    else:
        _assert_transcriptor_assets(model_root)

    temp_dir = _get_temp_directory()
    temp_path = temp_dir / f"heartmula_transcribe_{uuid.uuid4().hex}.wav"
    waveform, sample_rate = _coerce_audio_input(audio_input)
    torchaudio.save(str(temp_path), waveform, sample_rate)

    try:
        temperature_values = _parse_temperature_tuple(temperature_tuple)
        errors: list[str] = []
        for profile in _resolve_transcription_candidates(runtime_profile):
            try:
                pipe = _get_transcriptor(heartlib, model_root, profile, keep_model_loaded)
                with torch.inference_mode():
                    result = pipe(
                        str(temp_path),
                        max_new_tokens=256,
                        num_beams=2,
                        task="transcribe",
                        condition_on_prev_tokens=False,
                        compression_ratio_threshold=1.8,
                        temperature=temperature_values,
                        logprob_threshold=logprob_threshold,
                        no_speech_threshold=no_speech_threshold,
                    )
                transcribed_text = result if isinstance(result, str) else result.get("text", str(result))
                report = _build_lyrics_report(expected_lyrics, transcribed_text, profile)
                if not keep_model_loaded:
                    _release_transcriptor(profile, model_root)
                return transcribed_text, report["sequence_ratio"], report
            except Exception as exc:
                errors.append(f"{profile.label}: {exc}")
                _release_transcriptor(profile, model_root)
        joined_errors = " | ".join(errors)
        raise RuntimeError(f"HeartMuLa transcription failed. {joined_errors}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


def get_model_root() -> Path:
    default_root = Path(folder_paths.models_dir) / MODEL_NAMESPACE
    try:
        folder_paths.add_model_folder_path(MODEL_NAMESPACE, str(default_root))
    except Exception:
        pass

    candidates: list[Path] = []
    env_override = os.environ.get("COMFYUI_HEARTMULA_MODEL_DIR")
    if env_override:
        candidates.append(Path(env_override).expanduser())
    try:
        for path in folder_paths.get_folder_paths(MODEL_NAMESPACE):
            candidates.append(Path(path).expanduser())
    except Exception:
        pass
    candidates.append(default_root)

    seen: set[str] = set()
    unique_candidates: list[Path] = []
    for candidate in candidates:
        resolved = str(candidate)
        if resolved not in seen:
            unique_candidates.append(candidate)
            seen.add(resolved)

    for candidate in unique_candidates:
        if _looks_like_model_root(candidate):
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate

    default_root.mkdir(parents=True, exist_ok=True)
    return default_root


def ensure_model_assets(model_root: Path) -> None:
    snapshot_download = importlib.import_module("huggingface_hub").snapshot_download

    if not (model_root / "gen_config.json").is_file() or not (model_root / "tokenizer.json").is_file():
        snapshot_download(
            repo_id=GEN_CONFIG_REPO,
            local_dir=str(model_root),
            allow_patterns=["gen_config.json", "tokenizer.json"],
        )

    try:
        _resolve_generation_assets(model_root)
        return
    except FileNotFoundError:
        pass

    music_dir = model_root / AUTO_DOWNLOAD_MODEL_VARIANT
    if not (music_dir / "config.json").is_file():
        snapshot_download(repo_id=AUTO_DOWNLOAD_MUSIC_MODEL_REPO, local_dir=str(music_dir))

    codec_dir = model_root / AUTO_DOWNLOAD_CODEC_VARIANT
    if not (codec_dir / "config.json").is_file():
        snapshot_download(repo_id=AUTO_DOWNLOAD_CODEC_MODEL_REPO, local_dir=str(codec_dir))

    _resolve_generation_assets(model_root)


def ensure_transcriptor_assets(model_root: Path) -> None:
    snapshot_download = importlib.import_module("huggingface_hub").snapshot_download
    transcriptor_dir = model_root / "HeartTranscriptor-oss"
    if not (transcriptor_dir / "config.json").is_file():
        snapshot_download(repo_id=TRANSCRIPTOR_MODEL_REPO, local_dir=str(transcriptor_dir))
    _assert_transcriptor_assets(model_root)


def _assert_required_models(model_root: Path) -> None:
    _resolve_generation_assets(model_root)


def _assert_transcriptor_assets(model_root: Path) -> None:
    transcriptor_config = model_root / "HeartTranscriptor-oss" / "config.json"
    if not transcriptor_config.is_file():
        transcriptor_dir = shlex.quote(str(model_root / TRANSCRIPTOR_VARIANT))
        raise FileNotFoundError(
            "Missing HeartMuLa transcriptor assets. "
            f"Expected {transcriptor_config}. Download them with: "
            f"hf download {TRANSCRIPTOR_MODEL_REPO} --local-dir {transcriptor_dir}"
        )


def _ensure_runtime_dependencies() -> None:
    required = {
        "certifi": "certifi",
        "huggingface_hub": "huggingface_hub",
        "tokenizers": "tokenizers",
        "transformers": "transformers",
        "torchaudio": "torchaudio",
        "torchtune": "torchtune",
        "numpy": "numpy",
        "einops": "einops",
        "tqdm": "tqdm",
        "vector_quantize_pytorch": "vector-quantize-pytorch",
        "soundfile": "soundfile",
    }
    missing = [package for module_name, package in required.items() if importlib.util.find_spec(module_name) is None]
    if missing:
        packages = ", ".join(sorted(missing))
        raise RuntimeError(
            "Missing Python dependencies for ComfyUI-MPC-HeartMuLa: "
            f"{packages}. Install them from this node folder with `pip install -r requirements.txt`."
        )


def _import_heartlib():
    _ensure_heartlib_source()
    return importlib.import_module("heartlib")


def _ensure_heartlib_source() -> None:
    if HEARTLIB_SOURCE_ROOT.exists():
        _prepend_to_syspath(HEARTLIB_SOURCE_ROOT)
        return

    if importlib.util.find_spec("heartlib") is not None:
        return

    VENDOR_ROOT.mkdir(parents=True, exist_ok=True)
    archive_path = VENDOR_ROOT / "heartlib-main.zip"
    extracted_root = VENDOR_ROOT / HEARTLIB_ARCHIVE_ROOT
    temp_extract_dir = Path(tempfile.mkdtemp(prefix="heartlib_extract_", dir=VENDOR_ROOT))
    try:
        _download_file(HEARTLIB_ARCHIVE_URL, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp_extract_dir)
        if extracted_root.exists():
            shutil.rmtree(extracted_root)
        shutil.move(str(temp_extract_dir / HEARTLIB_ARCHIVE_ROOT), str(extracted_root))
    finally:
        if archive_path.exists():
            archive_path.unlink()
        shutil.rmtree(temp_extract_dir, ignore_errors=True)

    _prepend_to_syspath(HEARTLIB_SOURCE_ROOT)


def _download_file(url: str, destination: Path) -> None:
    certifi = importlib.import_module("certifi")
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(url, context=context, timeout=120) as response:
        with open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle)


def _prepend_to_syspath(path: Path) -> None:
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _normalize_audio_output(waveform: torch.Tensor, sample_rate: int) -> dict[str, Any]:
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    if waveform.ndim == 2:
        waveform = waveform.unsqueeze(0)
    return {"waveform": waveform.float(), "sample_rate": sample_rate}


def _coerce_audio_input(audio_input: dict[str, Any]) -> tuple[torch.Tensor, int]:
    waveform = audio_input["waveform"]
    sample_rate = int(audio_input["sample_rate"])
    if waveform.ndim == 3:
        waveform = waveform.squeeze(0)
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    return waveform.float().cpu(), sample_rate


def _resolve_runtime_candidates(requested: str) -> list[RuntimeProfile]:
    has_mps = bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    has_cuda = torch.cuda.is_available()
    bf16_cuda = has_cuda and torch.cuda.is_bf16_supported()

    profiles = {
        "apple_silicon_fast": RuntimeProfile(
            key="apple_silicon_fast",
            label="Apple Silicon all-MPS experimental (MPS/MPS)",
            mula_device=torch.device("mps"),
            codec_device=torch.device("mps"),
            mula_dtype=torch.float16,
            codec_dtype=torch.float32,
        ),
        "apple_silicon_safe": RuntimeProfile(
            key="apple_silicon_safe",
            label="Apple Silicon recommended (MPS/CPU)",
            mula_device=torch.device("mps"),
            codec_device=torch.device("cpu"),
            mula_dtype=torch.float16,
            codec_dtype=torch.float32,
        ),
        "cuda": RuntimeProfile(
            key="cuda",
            label="CUDA",
            mula_device=torch.device("cuda"),
            codec_device=torch.device("cuda"),
            mula_dtype=torch.bfloat16 if bf16_cuda else torch.float16,
            codec_dtype=torch.float32,
        ),
        "cpu": RuntimeProfile(
            key="cpu",
            label="CPU",
            mula_device=torch.device("cpu"),
            codec_device=torch.device("cpu"),
            mula_dtype=torch.float32,
            codec_dtype=torch.float32,
        ),
    }

    if requested == "auto":
        if has_mps:
            # Prefer the split-device heartlib path on Apple Silicon: MPS for
            # HeartMuLa generation, CPU for HeartCodec stability/quality, then
            # fall back to CPU-only if MPS is unavailable or fails.
            return [profiles["apple_silicon_safe"], profiles["cpu"]]
        if has_cuda:
            return [profiles["cuda"], profiles["cpu"]]
        return [profiles["cpu"]]

    if requested.startswith("apple_silicon") and not has_mps:
        return [profiles["cpu"]]
    if requested == "cuda" and not has_cuda:
        return [profiles["cpu"]]
    return [profiles[requested]]


def _resolve_transcription_candidates(requested: str) -> list[TranscriptionProfile]:
    has_mps = bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    has_cuda = torch.cuda.is_available()

    profiles = {
        "apple_silicon": TranscriptionProfile(
            key="apple_silicon",
            label="Apple Silicon transcription (MPS)",
            device=torch.device("mps"),
            dtype=torch.float16,
        ),
        "cuda": TranscriptionProfile(
            key="cuda",
            label="CUDA transcription",
            device=torch.device("cuda"),
            dtype=torch.float16,
        ),
        "cpu": TranscriptionProfile(
            key="cpu",
            label="CPU transcription",
            device=torch.device("cpu"),
            dtype=torch.float32,
        ),
    }

    if requested == "auto":
        if has_mps:
            return [profiles["apple_silicon"], profiles["cpu"]]
        if has_cuda:
            return [profiles["cuda"], profiles["cpu"]]
        return [profiles["cpu"]]

    if requested.startswith("apple_silicon"):
        return [profiles["apple_silicon"], profiles["cpu"]] if has_mps else [profiles["cpu"]]
    if requested == "cuda":
        return [profiles["cuda"], profiles["cpu"]] if has_cuda else [profiles["cpu"]]
    return [profiles["cpu"]]


def _get_pipeline(
    heartlib: Any,
    generation_assets: GenerationAssets,
    profile: RuntimeProfile,
    keep_model_loaded: bool,
):
    cache_key = (profile.key, str(generation_assets.model_path), str(generation_assets.codec_path))
    if keep_model_loaded and cache_key in _PIPELINE_CACHE:
        return _PIPELINE_CACHE[cache_key]

    tokenizer = importlib.import_module("tokenizers").Tokenizer.from_file(
        str(generation_assets.tokenizer_path)
    )
    music_generation = importlib.import_module("heartlib.pipelines.music_generation")
    gen_config = music_generation.HeartMuLaGenConfig.from_file(str(generation_assets.gen_config_path))
    lazy_load = profile.lazy_load and profile.mula_device == profile.codec_device

    # Instantiate the official heartlib pipeline directly so we can keep
    # heartlib's runtime/device semantics while resolving released HeartMuLa
    # folder variants under a single ComfyUI model root.
    pipe = heartlib.HeartMuLaGenPipeline(
        heartmula_path=str(generation_assets.model_path),
        heartcodec_path=str(generation_assets.codec_path),
        heartmula_device=profile.mula_device,
        heartcodec_device=profile.codec_device,
        heartmula_dtype=profile.mula_dtype,
        heartcodec_dtype=profile.codec_dtype,
        lazy_load=lazy_load,
        muq_mulan=None,
        text_tokenizer=tokenizer,
        config=gen_config,
    )
    if keep_model_loaded:
        _PIPELINE_CACHE[cache_key] = pipe
    return pipe


def _get_transcriptor(heartlib: Any, model_root: Path, profile: TranscriptionProfile, keep_model_loaded: bool):
    cache_key = (profile.key, str(model_root))
    if keep_model_loaded and cache_key in _TRANSCRIPTOR_CACHE:
        return _TRANSCRIPTOR_CACHE[cache_key]

    pipe = heartlib.HeartTranscriptorPipeline.from_pretrained(
        str(model_root),
        device=profile.device,
        dtype=profile.dtype,
    )
    if keep_model_loaded:
        _TRANSCRIPTOR_CACHE[cache_key] = pipe
    return pipe


def _release_pipeline(profile: RuntimeProfile, generation_assets: GenerationAssets) -> None:
    cache_key = (profile.key, str(generation_assets.model_path), str(generation_assets.codec_path))
    pipe = _PIPELINE_CACHE.pop(cache_key, None)
    if pipe is not None:
        del pipe
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
        try:
            torch.mps.empty_cache()
        except RuntimeError:
            pass


def _release_transcriptor(profile: TranscriptionProfile, model_root: Path) -> None:
    cache_key = (profile.key, str(model_root))
    pipe = _TRANSCRIPTOR_CACHE.pop(cache_key, None)
    if pipe is not None:
        del pipe
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
        try:
            torch.mps.empty_cache()
        except RuntimeError:
            pass


def _get_temp_directory() -> Path:
    try:
        path = Path(folder_paths.get_temp_directory())
    except Exception:
        path = Path(tempfile.gettempdir()) / "comfyui_heartmula"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_temperature_tuple(value: str) -> tuple[float, ...]:
    pieces = [piece.strip() for piece in value.split(",") if piece.strip()]
    if not pieces:
        return (0.0, 0.1, 0.2, 0.4)
    return tuple(float(piece) for piece in pieces)


def _build_lyrics_report(expected_lyrics: str, transcribed_text: str, profile: TranscriptionProfile) -> dict[str, Any]:
    expected_normalized = _normalize_text_for_compare(expected_lyrics)
    transcribed_normalized = _normalize_text_for_compare(transcribed_text)
    expected_words = expected_normalized.split()
    transcribed_words = set(transcribed_normalized.split())
    matched_words = sum(1 for word in expected_words if word in transcribed_words)
    word_recall = matched_words / len(expected_words) if expected_words else 0.0
    sequence_ratio = difflib.SequenceMatcher(
        None,
        expected_normalized,
        transcribed_normalized,
    ).ratio()
    exact_match = expected_normalized == transcribed_normalized and bool(expected_normalized)
    return {
        "expected_normalized": expected_normalized,
        "transcribed_normalized": transcribed_normalized,
        "exact_match": exact_match,
        "sequence_ratio": round(sequence_ratio, 4),
        "word_recall": round(word_recall, 4),
        "matched_word_count": matched_words,
        "expected_word_count": len(expected_words),
        "effective_runtime_profile": profile.label,
        "runtime_api": "heartlib",
        "model_variant": TRANSCRIPTOR_VARIANT,
    }


def _normalize_text_for_compare(text: str) -> str:
    normalized = text.replace("\r\n", "\n").lower()
    normalized = re.sub(r"\[[^\]]+\]", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _looks_like_model_root(candidate: Path) -> bool:
    if (candidate / "gen_config.json").exists() or (candidate / TRANSCRIPTOR_VARIANT).exists():
        return True
    return any((candidate / model_variant).exists() for model_variant, _ in SUPPORTED_GENERATION_LAYOUTS)


def _resolve_generation_assets(model_root: Path) -> GenerationAssets:
    tokenizer_path = model_root / "tokenizer.json"
    gen_config_path = model_root / "gen_config.json"
    issues: list[str] = []

    if not gen_config_path.is_file():
        issues.append(f"Missing {gen_config_path}")
    if not tokenizer_path.is_file():
        issues.append(f"Missing {tokenizer_path}")

    for model_variant, codec_variant in SUPPORTED_GENERATION_LAYOUTS:
        model_path = model_root / model_variant
        codec_path = model_root / codec_variant
        model_config = model_path / "config.json"
        codec_config = codec_path / "config.json"
        if model_config.is_file() and codec_config.is_file() and not issues:
            return GenerationAssets(
                model_root=model_root,
                model_variant=model_variant,
                codec_variant=codec_variant,
                model_path=model_path,
                codec_path=codec_path,
                tokenizer_path=tokenizer_path,
                gen_config_path=gen_config_path,
            )

    issues.extend(_summarize_generation_layout_issues(model_root))
    raise FileNotFoundError(_build_generation_assets_error(model_root, issues))


def _summarize_generation_layout_issues(model_root: Path) -> list[str]:
    issues: list[str] = []
    for model_variant, codec_variant in SUPPORTED_GENERATION_LAYOUTS:
        model_config = model_root / model_variant / "config.json"
        codec_config = model_root / codec_variant / "config.json"
        if model_config.is_file() and not codec_config.is_file():
            issues.append(
                f"Found {model_variant} but missing the matching codec {codec_variant}"
            )
        if codec_config.is_file() and not model_config.is_file():
            issues.append(
                f"Found {codec_variant} but missing the matching model {model_variant}"
            )
    if not issues:
        issues.append("No compatible HeartMuLa generation model pair was found")
    return issues


def _build_generation_assets_error(model_root: Path, issues: list[str]) -> str:
    root_dir = shlex.quote(str(model_root))
    base_model_dir = shlex.quote(str(model_root / "HeartMuLa-oss-3B"))
    rl_model_dir = shlex.quote(str(model_root / "HeartMuLa-RL-oss-3B-20260123"))
    base_codec_dir = shlex.quote(str(model_root / "HeartCodec-oss"))
    codec_20260123_dir = shlex.quote(str(model_root / "HeartCodec-oss-20260123"))
    supported_pairs = "\n".join(
        f"- {model_variant} + {codec_variant}"
        for model_variant, codec_variant in SUPPORTED_GENERATION_LAYOUTS
    )
    command_block = "\n".join(
        [
            f"hf download {GEN_CONFIG_REPO} --local-dir {root_dir}",
            f"hf download HeartMuLa/HeartMuLa-oss-3B --local-dir {base_model_dir}",
            f"hf download HeartMuLa/HeartMuLa-RL-oss-3B-20260123 --local-dir {rl_model_dir}",
            f"hf download HeartMuLa/HeartCodec-oss --local-dir {base_codec_dir}",
            f"hf download HeartMuLa/HeartCodec-oss-20260123 --local-dir {codec_20260123_dir}",
        ]
    )
    issue_text = "\n".join(f"- {issue}" for issue in issues)
    return (
        f"HeartMuLa generation assets are not ready in {model_root}.\n"
        "This node pack uses the official heartlib runtime API with official "
        "HeartMuLa folder names under a shared model root.\n"
        f"{issue_text}\n\n"
        f"Supported model and codec pairs:\n{supported_pairs}\n\n"
        "Manual setup commands:\n"
        f"{command_block}\n\n"
        "If you use HeartMuLa-RL-oss-3B-20260123, you must pair it with "
        "HeartCodec-oss-20260123."
    )