from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID, uuid4

from meeting_intelligence_engine.audio import normalize_audio
from meeting_intelligence_engine.config import Settings
from meeting_intelligence_engine.core.schemas import ProcessingStage, SpeakerSegment, TranscriptResult
from meeting_intelligence_engine.implementations.local_pipeline import clean_transcript_segments, max_segment_end
from meeting_intelligence_engine.services.pipeline_factory import build_pipeline


class ProgressReporter:
    def __init__(self, callback=None) -> None:
        self.callback = callback

    def update(self, stage: ProcessingStage, progress_percent: float) -> None:
        if self.callback:
            self.callback(stage, progress_percent)


def normalize_stage(source_path: Path, processed_audio_path: Path, progress: ProgressReporter) -> Path:
    progress.update(ProcessingStage.normalizing_audio, 10)
    normalize_audio(source_path, processed_audio_path)
    return processed_audio_path


def transcribe_and_diarize_stage(
    audio_path: Path,
    meeting_id: UUID,
    config: Settings,
    progress: ProgressReporter,
) -> TranscriptResult:
    started = time.monotonic()
    pipeline = build_pipeline(config)

    progress.update(ProcessingStage.loading_models, 20)
    pipeline.load()

    progress.update(ProcessingStage.transcribing, 35)
    asr_segments = pipeline.asr.transcribe(audio_path)

    progress.update(ProcessingStage.diarizing, 70)
    diarization_warning = pipeline._diarization_load_warning
    try:
        speaker_segments = pipeline.diarization.diarize(audio_path)
    except Exception as exc:
        diarization_warning = str(exc)
        speaker_segments = [SpeakerSegment(speaker_id="SPEAKER_00", start=0.0, end=max_segment_end(asr_segments))]

    progress.update(ProcessingStage.aligning, 85)
    transcript_segments = clean_transcript_segments(pipeline.alignment.align(asr_segments, speaker_segments))
    speakers = sorted({segment.speaker_id for segment in transcript_segments})
    return TranscriptResult(
        meeting_id=meeting_id or uuid4(),
        segments=transcript_segments,
        speakers=speakers,
        metadata={
            "asr_model_name": pipeline.asr.get_model_info().get("name"),
            "diarization_model_name": pipeline.diarization.get_model_info().get("name"),
            "processing_duration_seconds": round(time.monotonic() - started, 3),
            "word_count": sum(len(segment.words) for segment in transcript_segments),
            "diarization_fallback": diarization_warning is not None,
            "diarization_warning": diarization_warning,
        },
    )
