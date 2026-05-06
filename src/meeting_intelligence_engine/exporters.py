from __future__ import annotations

import json
from pathlib import Path

from .core.schemas import TranscriptResult


def format_ts(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}.{secs:02d}.{ms:03d}".replace(".", ":", 1)


def display_speaker(segment) -> str:
    return getattr(segment, "speaker_name", None) or getattr(segment, "speaker_id")


def write_transcript_outputs(
    base_path: Path,
    transcript: TranscriptResult,
    export_srt: bool = True,
    meeting_title: str | None = None,
) -> None:
    base_path.parent.mkdir(parents=True, exist_ok=True)
    (base_path.with_suffix(".json")).write_text(
        transcript.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"[{format_ts(segment.start_time)} --> {format_ts(segment.end_time)}] {display_speaker(segment)}: {segment.text}"
        for segment in transcript.segments
    ]
    (base_path.with_suffix(".txt")).write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    write_markdown(base_path.with_suffix(".md"), transcript, meeting_title=meeting_title)
    if export_srt:
        write_srt(base_path.with_suffix(".srt"), transcript)


def write_srt(path: Path, transcript: TranscriptResult) -> None:
    blocks = []
    for index, segment in enumerate(transcript.segments, start=1):
        start = format_ts(segment.start_time).replace(".", ",")
        end = format_ts(segment.end_time).replace(".", ",")
        blocks.append(f"{index}\n{start} --> {end}\n{display_speaker(segment)}: {segment.text}")
    path.write_text("\n\n".join(blocks).strip() + "\n", encoding="utf-8")


def write_markdown(path: Path, transcript: TranscriptResult, meeting_title: str | None = None) -> None:
    lines = [f"# {meeting_title or f'Meeting {transcript.meeting_id}'}", ""]
    for segment in transcript.segments:
        lines.append(f"[{format_ts(segment.start_time)} --> {format_ts(segment.end_time)}] {display_speaker(segment)}: {segment.text}")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def read_transcript(path: Path) -> TranscriptResult:
    return TranscriptResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
