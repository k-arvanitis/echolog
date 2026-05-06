from __future__ import annotations

from meeting_intelligence_engine.config import Settings
from meeting_intelligence_engine.implementations.local_pipeline import (
    GroqWhisperASR,
    LocalTranscriptionPipeline,
    PyannoteDiarization,
    TimeOverlapAlignment,
)


def build_pipeline(settings: Settings) -> LocalTranscriptionPipeline:
    return LocalTranscriptionPipeline(
        asr=GroqWhisperASR(
            api_key=settings.groq_api_key,
            model_name=settings.asr_model_name,
            language=settings.language,
            chunk_seconds=settings.asr_chunk_seconds,
        ),
        diarization=PyannoteDiarization(
            model_name=settings.diarization_model_name,
            hf_token=settings.hf_token,
        ),
        alignment=TimeOverlapAlignment(),
        device=settings.device,
    )
