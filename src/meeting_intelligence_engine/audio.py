from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass


SUPPORTED_SUFFIXES = {".wav", ".mp3", ".mp4", ".m4a"}


class AudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioChunk:
    path: Path
    offset_seconds: float


def require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise AudioError(f"Missing required executable(s): {', '.join(missing)}")


def validate_audio(path: Path, max_size_mb: int, max_duration_seconds: int) -> float:
    require_ffmpeg()
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise AudioError(f"Unsupported audio format: {path.suffix}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise AudioError(f"Audio file is {size_mb:.1f}MB; maximum is {max_size_mb}MB")
    duration = probe_duration(path)
    if duration > max_duration_seconds:
        raise AudioError(f"Audio duration is {duration:.1f}s; maximum is {max_duration_seconds}s")
    return duration


def probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise AudioError(f"Unsupported or unreadable audio file: {path}") from exc


def normalize_audio(source: Path, target: Path, sample_rate: int = 16000) -> None:
    require_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-sample_fmt",
        "s16",
        "-vn",
        str(target),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        raise AudioError(f"ffmpeg failed for {source}: {detail}") from exc


def split_audio(source: Path, work_dir: Path, chunk_seconds: int) -> list[AudioChunk]:
    duration = probe_duration(source)
    if duration <= chunk_seconds:
        return [AudioChunk(path=source, offset_seconds=0.0)]
    chunks: list[AudioChunk] = []
    start = 0.0
    index = 0
    while start < duration:
        target = work_dir / f"{source.stem}.part{index:04d}.wav"
        extract_audio_range(source, target, start, min(chunk_seconds, duration - start))
        chunks.append(AudioChunk(path=target, offset_seconds=start))
        start += chunk_seconds
        index += 1
    return chunks


def extract_audio_range(source: Path, target: Path, start: float, duration: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-acodec",
        "copy",
        str(target),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        raise AudioError(f"ffmpeg split failed for {source}: {detail}") from exc
