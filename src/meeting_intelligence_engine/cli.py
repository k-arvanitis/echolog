from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meeting_intelligence_engine.audio import normalize_audio, validate_audio
from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.exporters import write_transcript_outputs
from meeting_intelligence_engine.logging_config import configure_logging
from meeting_intelligence_engine.services.pipeline_factory import build_pipeline
from meeting_intelligence_engine.services.segment_repairs import repair_intro_fragments
from meeting_intelligence_engine.services.speaker_labels import apply_speaker_labels, infer_speaker_labels


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe a meeting with Groq Whisper ASR and pyannote diarization.")
    parser.add_argument("--input", required=True, type=Path, help="Path to WAV, MP3, MP4, or M4A audio.")
    parser.add_argument("--output-dir", default=settings.output_dir, type=Path)
    parser.add_argument("--title", default=None)
    parser.add_argument("--no-srt", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        duration = validate_audio(args.input, settings.max_upload_mb, settings.max_duration_seconds)
        work_dir = settings.data_dir / "cli" / args.input.stem
        processed_audio = work_dir / "audio.wav"
        normalize_audio(args.input, processed_audio)
        pipeline = build_pipeline(settings)
        transcript = pipeline.process(processed_audio)
        repair_intro_fragments(transcript)
        apply_speaker_labels(transcript, infer_speaker_labels(transcript, settings))
        transcript.metadata["duration_seconds"] = round(duration, 3)
        output_base = args.output_dir / args.input.stem
        write_transcript_outputs(output_base, transcript, export_srt=not args.no_srt)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(output_base.with_suffix(".json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
