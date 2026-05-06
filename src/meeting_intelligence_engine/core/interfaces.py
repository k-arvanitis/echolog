from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .schemas import ASRSegment, SpeakerSegment, TranscriptResult, TranscriptSegment


class ASRModel(ABC):
    @abstractmethod
    def load(self, model_path: str, device: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def transcribe(self, audio_path: Path) -> list[ASRSegment]:
        raise NotImplementedError

    @abstractmethod
    def get_model_info(self) -> dict:
        raise NotImplementedError


class DiarizationModel(ABC):
    @abstractmethod
    def load(self, model_path: str, device: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def diarize(self, audio_path: Path) -> list[SpeakerSegment]:
        raise NotImplementedError

    @abstractmethod
    def get_model_info(self) -> dict:
        raise NotImplementedError


class AlignmentEngine(ABC):
    @abstractmethod
    def align(self, asr_segments: list[ASRSegment], speaker_segments: list[SpeakerSegment]) -> list[TranscriptSegment]:
        raise NotImplementedError


class TranscriptionPipeline(ABC):
    asr: ASRModel
    diarization: DiarizationModel
    alignment: AlignmentEngine

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def process(self, audio_path: Path) -> TranscriptResult:
        raise NotImplementedError

    @abstractmethod
    def process_stream(self, audio_chunk: bytes) -> dict | None:
        raise NotImplementedError
