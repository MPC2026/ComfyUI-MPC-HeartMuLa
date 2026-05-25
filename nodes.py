from __future__ import annotations

import json
import random
from typing import Any

import torch

from .heartmula_runtime import build_condition_tags
from .heartmula_runtime import build_lyrics_with_ending
from .heartmula_runtime import compare_generated_lyrics
from .heartmula_runtime import generate_music


SONG_KEY_OPTIONS = [
    "C major",
    "G major",
    "D major",
    "A major",
    "E major",
    "B major",
    "F# major",
    "C# major",
    "F major",
    "Bb major",
    "Eb major",
    "Ab major",
    "Db major",
    "Gb major",
    "Cb major",
    "A minor",
    "E minor",
    "B minor",
    "F# minor",
    "C# minor",
    "G# minor",
    "D# minor",
    "A# minor",
    "D minor",
    "G minor",
    "C minor",
    "F minor",
    "Bb minor",
    "Eb minor",
    "Ab minor",
]


class HeartMuLaSongSpec:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lyrics": (
                    "STRING",
                    {
                        "default": "[Verse]\nWrite your lyrics here",
                        "multiline": True,
                    },
                ),
                "style_tags": (
                    "STRING",
                    {
                        "default": "anthemic,pop,clear vocals",
                        "multiline": True,
                    },
                ),
                "bpm": ("INT", {"default": 120, "min": 40, "max": 240, "step": 1}),
                "song_key": (SONG_KEY_OPTIONS, {"default": "C major"}),
                "duration_seconds": (
                    "INT",
                    {"default": 60, "min": 10, "max": 600, "step": 5},
                ),
                "ending_mode": (
                    ["none", "outro", "tag ending"],
                    {"default": "none"},
                ),
                "ending_text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING", "HEARTMULA_SPEC")
    RETURN_NAMES = (
        "lyrics",
        "tags",
        "max_audio_length_ms",
        "metadata_json",
        "song_spec",
    )
    FUNCTION = "build"
    CATEGORY = "HeartMuLa"

    def build(
        self,
        lyrics: str,
        style_tags: str,
        bpm: int,
        song_key: str,
        duration_seconds: int,
        ending_mode: str,
        ending_text: str,
    ):
        effective_lyrics = build_lyrics_with_ending(lyrics, ending_mode, ending_text)
        effective_tags = build_condition_tags(style_tags, bpm, song_key, duration_seconds)
        metadata = {
            "bpm": bpm,
            "song_key": song_key.strip(),
            "duration_seconds": duration_seconds,
            "ending_mode": ending_mode,
            "effective_tags": effective_tags,
            "effective_lyrics": effective_lyrics,
        }
        song_spec = {
            "lyrics": effective_lyrics,
            "tags": effective_tags,
            "max_audio_length_ms": duration_seconds * 1000,
            "metadata": metadata,
        }
        return (
            effective_lyrics,
            effective_tags,
            duration_seconds * 1000,
            json.dumps(metadata, indent=2, ensure_ascii=True),
            song_spec,
        )


class HeartMuLaGenerateFromSpec:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "song_spec": ("HEARTMULA_SPEC",),
                "runtime_profile": (
                    [
                        "auto",
                        "apple_silicon_fast",
                        "apple_silicon_safe",
                        "cuda",
                        "cpu",
                    ],
                    {"default": "auto"},
                ),
                "seed": (
                    "INT",
                    {"default": 0, "min": -1, "max": 2147483647, "step": 1},
                ),
                "topk": ("INT", {"default": 50, "min": 1, "max": 200, "step": 1}),
                "temperature": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.1, "max": 2.0, "step": 0.05},
                ),
                "cfg_scale": (
                    "FLOAT",
                    {"default": 1.8, "min": 1.0, "max": 6.0, "step": 0.1},
                ),
                "keep_model_loaded": ("BOOLEAN", {"default": True}),
                "auto_download_models": ("BOOLEAN", {"default": False}),
                "filename_prefix": ("STRING", {"default": "heartmula_song"}),
            }
        }

    RETURN_TYPES = ("AUDIO", "STRING", "STRING")
    RETURN_NAMES = ("audio_output", "filepath", "metadata_json")
    FUNCTION = "generate"
    CATEGORY = "HeartMuLa"

    def generate(
        self,
        song_spec,
        runtime_profile: str,
        seed: int,
        topk: int,
        temperature: float,
        cfg_scale: float,
        keep_model_loaded: bool,
        auto_download_models: bool,
        filename_prefix: str,
    ):
        if seed >= 0:
            random.seed(seed)
            torch.manual_seed(seed)

        audio_output, output_path, metadata = generate_music(
            lyrics=song_spec["lyrics"],
            tags=song_spec["tags"],
            max_audio_length_ms=int(song_spec["max_audio_length_ms"]),
            runtime_profile=runtime_profile,
            topk=topk,
            temperature=temperature,
            cfg_scale=cfg_scale,
            keep_model_loaded=keep_model_loaded,
            auto_download_models=auto_download_models,
            filename_prefix=filename_prefix,
            seed=seed,
        )
        combined_metadata = {
            "song_spec": song_spec,
            "generation": metadata,
        }
        return (audio_output, output_path, json.dumps(combined_metadata, indent=2, ensure_ascii=True))


class HeartMuLaGenerateMusic:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lyrics": (
                    "STRING",
                    {
                        "default": "[Verse]\nWrite your lyrics here",
                        "multiline": True,
                        "defaultInput": True,
                    },
                ),
                "tags": (
                    "STRING",
                    {
                        "default": "anthemic,pop,clear vocals,120bpm,c major",
                        "multiline": True,
                        "defaultInput": True,
                    },
                ),
                "max_audio_length_ms": (
                    "INT",
                    {
                        "default": 60000,
                        "min": 10000,
                        "max": 600000,
                        "step": 1000,
                        "defaultInput": True,
                    },
                ),
                "runtime_profile": (
                    [
                        "auto",
                        "apple_silicon_fast",
                        "apple_silicon_safe",
                        "cuda",
                        "cpu",
                    ],
                    {"default": "auto"},
                ),
                "seed": (
                    "INT",
                    {"default": 0, "min": -1, "max": 2147483647, "step": 1},
                ),
                "topk": ("INT", {"default": 50, "min": 1, "max": 200, "step": 1}),
                "temperature": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.1, "max": 2.0, "step": 0.05},
                ),
                "cfg_scale": (
                    "FLOAT",
                    {"default": 1.8, "min": 1.0, "max": 6.0, "step": 0.1},
                ),
                "keep_model_loaded": ("BOOLEAN", {"default": True}),
                "auto_download_models": ("BOOLEAN", {"default": False}),
                "filename_prefix": ("STRING", {"default": "heartmula_song"}),
            }
        }

    RETURN_TYPES = ("AUDIO", "STRING", "STRING")
    RETURN_NAMES = ("audio_output", "filepath", "metadata_json")
    FUNCTION = "generate"
    CATEGORY = "HeartMuLa"

    def generate(
        self,
        lyrics: str,
        tags: str,
        max_audio_length_ms: int,
        runtime_profile: str,
        seed: int,
        topk: int,
        temperature: float,
        cfg_scale: float,
        keep_model_loaded: bool,
        auto_download_models: bool,
        filename_prefix: str,
    ):
        if seed >= 0:
            random.seed(seed)
            torch.manual_seed(seed)

        audio_output, output_path, metadata = generate_music(
            lyrics=lyrics,
            tags=tags,
            max_audio_length_ms=max_audio_length_ms,
            runtime_profile=runtime_profile,
            topk=topk,
            temperature=temperature,
            cfg_scale=cfg_scale,
            keep_model_loaded=keep_model_loaded,
            auto_download_models=auto_download_models,
            filename_prefix=filename_prefix,
            seed=seed,
        )
        return (audio_output, output_path, json.dumps(metadata, indent=2, ensure_ascii=True))


class HeartMuLaLyricsCompliance:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_input": ("AUDIO",),
                "expected_lyrics": (
                    "STRING",
                    {
                        "default": "[Verse]\nWrite the lyrics you expect here",
                        "multiline": True,
                        "defaultInput": True,
                    },
                ),
                "runtime_profile": (
                    [
                        "auto",
                        "apple_silicon_fast",
                        "apple_silicon_safe",
                        "cuda",
                        "cpu",
                    ],
                    {"default": "auto"},
                ),
                "auto_download_models": ("BOOLEAN", {"default": False}),
                "keep_model_loaded": ("BOOLEAN", {"default": True}),
                "temperature_tuple": ("STRING", {"default": "0.0,0.1,0.2,0.4"}),
                "no_speech_threshold": (
                    "FLOAT",
                    {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.05},
                ),
                "logprob_threshold": (
                    "FLOAT",
                    {"default": -1.0, "min": -5.0, "max": 5.0, "step": 0.1},
                ),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "BOOLEAN", "STRING")
    RETURN_NAMES = (
        "transcribed_lyrics",
        "similarity_score",
        "exact_match",
        "report_json",
    )
    FUNCTION = "compare"
    CATEGORY = "HeartMuLa"

    def compare(
        self,
        audio_input,
        expected_lyrics: str,
        runtime_profile: str,
        auto_download_models: bool,
        keep_model_loaded: bool,
        temperature_tuple: str,
        no_speech_threshold: float,
        logprob_threshold: float,
    ):
        transcribed_lyrics, similarity_score, report = compare_generated_lyrics(
            audio_input=audio_input,
            expected_lyrics=expected_lyrics,
            runtime_profile=runtime_profile,
            auto_download_models=auto_download_models,
            keep_model_loaded=keep_model_loaded,
            temperature_tuple=temperature_tuple,
            no_speech_threshold=no_speech_threshold,
            logprob_threshold=logprob_threshold,
        )
        return (
            transcribed_lyrics,
            similarity_score,
            bool(report.get("exact_match", False)),
            json.dumps(report, indent=2, ensure_ascii=True),
        )


class HeartMuLaLyricsComplianceFromSpec:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_input": ("AUDIO",),
                "song_spec": ("HEARTMULA_SPEC",),
                "runtime_profile": (
                    [
                        "auto",
                        "apple_silicon_fast",
                        "apple_silicon_safe",
                        "cuda",
                        "cpu",
                    ],
                    {"default": "auto"},
                ),
                "auto_download_models": ("BOOLEAN", {"default": False}),
                "keep_model_loaded": ("BOOLEAN", {"default": True}),
                "temperature_tuple": ("STRING", {"default": "0.0,0.1,0.2,0.4"}),
                "no_speech_threshold": (
                    "FLOAT",
                    {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.05},
                ),
                "logprob_threshold": (
                    "FLOAT",
                    {"default": -1.0, "min": -5.0, "max": 5.0, "step": 0.1},
                ),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "BOOLEAN", "STRING")
    RETURN_NAMES = (
        "transcribed_lyrics",
        "similarity_score",
        "exact_match",
        "report_json",
    )
    FUNCTION = "compare"
    CATEGORY = "HeartMuLa"

    def compare(
        self,
        audio_input,
        song_spec,
        runtime_profile: str,
        auto_download_models: bool,
        keep_model_loaded: bool,
        temperature_tuple: str,
        no_speech_threshold: float,
        logprob_threshold: float,
    ):
        transcribed_lyrics, similarity_score, report = compare_generated_lyrics(
            audio_input=audio_input,
            expected_lyrics=song_spec["lyrics"],
            runtime_profile=runtime_profile,
            auto_download_models=auto_download_models,
            keep_model_loaded=keep_model_loaded,
            temperature_tuple=temperature_tuple,
            no_speech_threshold=no_speech_threshold,
            logprob_threshold=logprob_threshold,
        )
        report = {"song_spec": song_spec, "compliance": report}
        return (
            transcribed_lyrics,
            similarity_score,
            bool(report["compliance"].get("exact_match", False)),
            json.dumps(report, indent=2, ensure_ascii=True),
        )


NODE_CLASS_MAPPINGS: dict[str, Any] = {
    "HeartMuLaSongSpec": HeartMuLaSongSpec,
    "HeartMuLaGenerateMusic": HeartMuLaGenerateMusic,
    "HeartMuLaGenerateFromSpec": HeartMuLaGenerateFromSpec,
    "HeartMuLaLyricsCompliance": HeartMuLaLyricsCompliance,
    "HeartMuLaLyricsComplianceFromSpec": HeartMuLaLyricsComplianceFromSpec,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HeartMuLaSongSpec": "HeartMuLa Song Spec",
    "HeartMuLaGenerateMusic": "HeartMuLa Generate Music",
    "HeartMuLaGenerateFromSpec": "HeartMuLa Generate From Spec",
    "HeartMuLaLyricsCompliance": "HeartMuLa Lyrics Compliance",
    "HeartMuLaLyricsComplianceFromSpec": "HeartMuLa Lyrics Compliance From Spec",
}