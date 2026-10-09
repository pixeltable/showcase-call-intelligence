"""WhisperX transcription and diarization, with the parameters of Pixeltable's built-in UDF."""

from __future__ import annotations

from typing import Any

from app.config import settings

_model_cache: dict[tuple[str, str, str], Any] = {}
_alignment_cache: dict[tuple[str, str, str | None], tuple[Any, dict]] = {}
_diarization_cache: dict[tuple[str, str | None], Any] = {}


def _device_and_compute() -> tuple[str, str]:
    return "cpu", "int8"


def _lookup_transcription_model(model: str, device: str, compute_type: str) -> Any:
    import whisperx

    key = (model, device, compute_type)
    if key not in _model_cache:
        _model_cache[key] = whisperx.load_model(model, device, compute_type=compute_type)
    return _model_cache[key]


def _lookup_alignment_model(language_code: str, device: str, model_name: str | None) -> tuple[Any, dict]:
    import whisperx

    key = (language_code, device, model_name)
    if key not in _alignment_cache:
        _alignment_cache[key] = whisperx.load_align_model(
            language_code=language_code, device=device, model_name=model_name
        )
    return _alignment_cache[key]


def _lookup_diarization_model(device: str, model_name: str | None) -> Any:
    from whisperx.diarize import DiarizationPipeline

    key = (device, model_name)
    if key not in _diarization_cache:
        token = settings.hf_token.strip()
        if not token or token in {"hf-your-token-here", "hf_..."}:
            raise RuntimeError("HF_TOKEN is required for WhisperX diarization")
        kwargs: dict[str, Any] = {"device": device, "token": token}
        if model_name is not None:
            kwargs["model_name"] = model_name
        _diarization_cache[key] = DiarizationPipeline(**kwargs)
    return _diarization_cache[key]


def transcribe_diarize(audio_path: str) -> dict[str, Any]:
    """Run WhisperX with diarization: the same steps as pixeltable.functions.whisperx.transcribe."""
    import whisperx

    device, compute_type = _device_and_compute()
    model = _lookup_transcription_model(settings.whisperx_model, device, compute_type)
    audio_array = whisperx.load_audio(audio_path)
    result: dict[str, Any] = model.transcribe(audio_array, batch_size=16)

    alignment_model, metadata = _lookup_alignment_model(result["language"], device, None)
    result = whisperx.align(result["segments"], alignment_model, metadata, audio_array, device)

    diarization_model = _lookup_diarization_model(device, settings.whisperx_diarization_model)
    diarization_segments = diarization_model(audio_array, num_speakers=2)
    result = whisperx.assign_word_speakers(diarization_segments, result)
    return result
