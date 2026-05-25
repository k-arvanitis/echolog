from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

TIMESTAMP_LINE_RE = re.compile(
    r"\[(?P<start>\d{2}:\d{2}:\d{2}\.\d{3}) --> (?P<end>\d{2}:\d{2}:\d{2}\.\d{3})\]\s+(?P<speaker>[^:\n]+):"
)


@dataclass
class MdChunk:
    id: str
    source: str
    content: str
    start_char: int
    end_char: int
    meeting_id: str | None
    meeting_title: str
    start_time: float | None
    end_time: float | None
    speakers: list[str]


def discover_markdown_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".md":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
    return sorted(set(files))


def recursive_chunks(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[tuple[str, int, int]]:
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        hard_end = min(start + chunk_size, len(text))
        end = best_split(text, start, hard_end)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append((chunk, start, end))
        if end >= len(text):
            break
        next_start = max(0, end - overlap)
        snap_para = text.find("\n\n", next_start, end)
        if snap_para != -1:
            next_start = snap_para + 2
        else:
            snap_sentence = text.find(". ", next_start, end)
            if snap_sentence != -1:
                next_start = snap_sentence + 2
            else:
                next_start = end
        start = next_start
    return chunks


def best_split(text: str, start: int, hard_end: int) -> int:
    window = text[start:hard_end]
    for separator, min_pos in [("\n\n", 200), ("\n", 400), (". ", 600), (" ", 800)]:
        index = window.rfind(separator)
        if index >= min_pos:
            return start + index + len(separator)
    return hard_end


def parse_ts(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)


def infer_meeting_metadata(file_path: Path) -> tuple[str | None, str]:
    meeting_id = None
    title = file_path.stem
    if len(file_path.parts) >= 4 and file_path.parts[-4] == "meetings":
        meeting_id = file_path.parts[-3]
    return meeting_id, title


def infer_title_from_text(text: str, fallback: str) -> str:
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    if first_line.startswith("# "):
        return first_line[2:].strip() or fallback
    return fallback


def extract_chunk_metadata(content: str) -> tuple[float | None, float | None, list[str]]:
    starts: list[float] = []
    ends: list[float] = []
    speakers: list[str] = []
    for match in TIMESTAMP_LINE_RE.finditer(content):
        starts.append(parse_ts(match.group("start")))
        ends.append(parse_ts(match.group("end")))
        speaker = match.group("speaker")
        if speaker not in speakers:
            speakers.append(speaker)
    return (starts[0] if starts else None, ends[-1] if ends else None, speakers)


def chunk_markdown_files(paths: list[Path], chunk_size: int = 1200, overlap: int = 150) -> list[dict]:
    chunks: list[MdChunk] = []
    for file_path in discover_markdown_files(paths):
        text = file_path.read_text(encoding="utf-8")
        meeting_id, meeting_title = infer_meeting_metadata(file_path)
        meeting_title = infer_title_from_text(text, meeting_title)
        for index, (content, start, end) in enumerate(recursive_chunks(text, chunk_size, overlap), start=1):
            start_time, end_time, speakers = extract_chunk_metadata(content)
            chunks.append(
                MdChunk(
                    id=str(uuid5(NAMESPACE_URL, f"{file_path.resolve()}::{index}::{start}:{end}")),
                    source=str(file_path),
                    content=content,
                    start_char=start,
                    end_char=end,
                    meeting_id=meeting_id,
                    meeting_title=meeting_title,
                    start_time=start_time,
                    end_time=end_time,
                    speakers=speakers,
                )
            )
    return [asdict(chunk) for chunk in chunks]
