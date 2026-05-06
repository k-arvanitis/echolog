from __future__ import annotations

import time
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
from uuid import UUID, uuid4

from meeting_intelligence_engine.audio import split_audio
from meeting_intelligence_engine.core.interfaces import AlignmentEngine, ASRModel, DiarizationModel, TranscriptionPipeline
from meeting_intelligence_engine.core.schemas import ASRSegment, SpeakerSegment, TranscriptResult, TranscriptSegment, Word


class ModelError(RuntimeError):
    pass


def resolve_device(device: str) -> str:
    import torch

    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise ModelError("CUDA was requested, but torch.cuda.is_available() is false")
    if device not in {"cuda", "cpu"}:
        raise ModelError("device must be cuda, cpu, or auto")
    return device


class GroqWhisperASR(ASRModel):
    def __init__(
        self,
        api_key: str | None,
        model_name: str = "whisper-large-v3",
        language: str | None = None,
        chunk_seconds: int = 600,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.language = language
        self.chunk_seconds = chunk_seconds
        self.client = None

    def load(self, model_path: str | None = None, device: str = "auto") -> None:
        from groq import Groq

        if not self.api_key:
            raise ModelError("Missing GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key)

    def transcribe(self, audio_path: Path) -> list[ASRSegment]:
        if self.client is None:
            raise ModelError("ASR model is not loaded")
        with tempfile.TemporaryDirectory(prefix="mie-groq-asr-") as tmp:
            chunks = split_audio(audio_path, Path(tmp), self.chunk_seconds)
            segments: list[ASRSegment] = []
            for chunk in chunks:
                segments.extend(self._transcribe_chunk(chunk.path, chunk.offset_seconds))
            return segments

    def _transcribe_chunk(self, audio_path: Path, offset_seconds: float) -> list[ASRSegment]:
        with audio_path.open("rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                file=(audio_path.name, audio_file.read()),
                model=self.model_name,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
                language=self.language,
                temperature=0.0,
            )
        raw_segments = read_response_attr(response, "segments", [])
        raw_words = read_response_attr(response, "words", [])
        words = [
            Word(
                text=str(read_response_attr(word, "word", "")).strip(),
                start=offset_seconds + float(read_response_attr(word, "start", 0.0)),
                end=offset_seconds + float(read_response_attr(word, "end", 0.0)),
                confidence=1.0,
            )
            for word in raw_words
            if str(read_response_attr(word, "word", "")).strip()
        ]
        segments: list[ASRSegment] = []
        for raw_segment in raw_segments:
            start = offset_seconds + float(read_response_attr(raw_segment, "start", 0.0))
            end = offset_seconds + float(read_response_attr(raw_segment, "end", start))
            segment_words = [word for word in words if word.start >= start and word.end <= end]
            text = str(read_response_attr(raw_segment, "text", "")).strip()
            segments.append(ASRSegment(text=text, start=start, end=end, words=segment_words))
        if not segments:
            text = str(read_response_attr(response, "text", "")).strip()
            end = words[-1].end if words else 0.0
            segments.append(ASRSegment(text=text, start=0.0, end=end, words=words))
        return segments

    def get_model_info(self) -> dict:
        return {"name": self.model_name, "backend": "groq"}


class NullDiarization(DiarizationModel):
    def load(self, model_path: str, device: str) -> None:
        return None

    def diarize(self, audio_path: Path) -> list[SpeakerSegment]:
        return []

    def get_model_info(self) -> dict:
        return {"name": "single-speaker-fallback", "backend": "none"}


def read_response_attr(value: object, name: str, default: object) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


@contextmanager
def trusted_torch_load() -> Iterator[None]:
    import torch

    original_load = torch.load

    def load_with_trusted_pickles(*args, **kwargs):
        kwargs["weights_only"] = False
        return original_load(*args, **kwargs)

    torch.load = load_with_trusted_pickles
    try:
        yield
    finally:
        torch.load = original_load


class PyannoteDiarization(DiarizationModel):
    def __init__(self, model_name: str = "pyannote/speaker-diarization-3.1", hf_token: str | None = None) -> None:
        self.model_name = model_name
        self.hf_token = hf_token
        self.device = "auto"
        self.pipeline = None

    def load(self, model_path: str | None = None, device: str = "auto") -> None:
        import torch
        from pyannote.audio import Pipeline

        self.device = resolve_device(device)
        with trusted_torch_load():
            try:
                self.pipeline = Pipeline.from_pretrained(model_path or self.model_name, token=self.hf_token)
            except TypeError:
                self.pipeline = Pipeline.from_pretrained(model_path or self.model_name, use_auth_token=self.hf_token)
            if self.device == "cuda":
                self.pipeline.to(torch.device("cuda"))
            self.pipeline({"waveform": torch.zeros(1, 16000), "sample_rate": 16000})

    def diarize(self, audio_path: Path) -> list[SpeakerSegment]:
        if self.pipeline is None:
            raise ModelError("Diarization model is not loaded")
        output = self.pipeline(str(audio_path))
        diarization = getattr(output, "exclusive_speaker_diarization", output)
        speaker_segments: list[SpeakerSegment] = []
        for turn, _track, speaker in diarization.itertracks(yield_label=True):
            speaker_segments.append(
                SpeakerSegment(
                    speaker_id=str(speaker),
                    start=float(turn.start),
                    end=float(turn.end),
                    confidence=1.0,
                )
            )
        return speaker_segments

    def get_model_info(self) -> dict:
        return {"name": self.model_name, "backend": "pyannote.audio"}


class TimeOverlapAlignment(AlignmentEngine):
    def align(self, asr_segments: list[ASRSegment], speaker_segments: list[SpeakerSegment]) -> list[TranscriptSegment]:
        if not speaker_segments:
            return [
                TranscriptSegment(speaker_id="SPEAKER_00", start_time=s.start, end_time=s.end, text=s.text, words=s.words)
                for s in asr_segments
            ]

        transcript: list[TranscriptSegment] = []
        for asr_segment in asr_segments:
            words_by_speaker: dict[str, list[Word]] = {}
            for word in asr_segment.words:
                speaker = best_speaker_for_range(word.start, word.end, speaker_segments)
                words_by_speaker.setdefault(speaker, []).append(word)

            if not words_by_speaker:
                speaker = best_speaker_for_range(asr_segment.start, asr_segment.end, speaker_segments)
                transcript.append(
                    TranscriptSegment(
                        speaker_id=speaker,
                        start_time=asr_segment.start,
                        end_time=asr_segment.end,
                        text=asr_segment.text,
                        words=[],
                    )
                )
                continue

            if len(words_by_speaker) == 1:
                speaker, words = next(iter(words_by_speaker.items()))
                transcript.append(
                    TranscriptSegment(
                        speaker_id=speaker,
                        start_time=asr_segment.start,
                        end_time=asr_segment.end,
                        text=asr_segment.text,
                        words=words,
                    )
                )
                continue

            ordered_words = [word for words_for_speaker in words_by_speaker.values() for word in words_for_speaker]
            ordered_words.sort(key=lambda item: item.start)
            current_speaker = best_speaker_for_range(ordered_words[0].start, ordered_words[0].end, speaker_segments)
            current_words: list[Word] = []
            for word in ordered_words:
                speaker = best_speaker_for_range(word.start, word.end, speaker_segments)
                if speaker != current_speaker and current_words:
                    transcript.append(make_transcript_segment(current_speaker, current_words))
                    current_words = []
                current_speaker = speaker
                current_words.append(word)
            if current_words:
                transcript.append(make_transcript_segment(current_speaker, current_words))
        return merge_adjacent_segments(transcript)


class LocalTranscriptionPipeline(TranscriptionPipeline):
    def __init__(self, asr: ASRModel, diarization: DiarizationModel, alignment: AlignmentEngine, device: str = "auto") -> None:
        self.asr = asr
        self.diarization = diarization
        self.alignment = alignment
        self.device = device
        self._loaded = False
        self._diarization_load_warning: str | None = None

    def load(self) -> None:
        resolved_device = resolve_device(self.device)
        self.asr.load("", resolved_device)
        try:
            self.diarization.load("", resolved_device)
        except Exception as exc:
            self._diarization_load_warning = str(exc)
            self.diarization = NullDiarization()
            self.diarization.load("", resolved_device)
        self._loaded = True

    def process(self, audio_path: Path, meeting_id: UUID | None = None) -> TranscriptResult:
        if not self._loaded:
            self.load()
        started = time.monotonic()
        asr_segments = self.asr.transcribe(audio_path)
        diarization_warning = self._diarization_load_warning
        try:
            speaker_segments = self.diarization.diarize(audio_path)
        except Exception as exc:
            diarization_warning = str(exc)
            speaker_segments = [SpeakerSegment(speaker_id="SPEAKER_00", start=0.0, end=max_segment_end(asr_segments))]
        transcript_segments = clean_transcript_segments(self.alignment.align(asr_segments, speaker_segments))
        speakers = sorted({segment.speaker_id for segment in transcript_segments})
        return TranscriptResult(
            meeting_id=meeting_id or uuid4(),
            segments=transcript_segments,
            speakers=speakers,
            metadata={
                "asr_model_name": self.asr.get_model_info().get("name"),
                "diarization_model_name": self.diarization.get_model_info().get("name"),
                "processing_duration_seconds": round(time.monotonic() - started, 3),
                "word_count": sum(len(segment.words) for segment in transcript_segments),
                "diarization_fallback": diarization_warning is not None,
                "diarization_warning": diarization_warning,
            },
        )

    def process_stream(self, audio_chunk: bytes) -> dict | None:
        raise NotImplementedError("Streaming transcription is planned for the Zoom phase")


def best_speaker_for_range(start: float, end: float, speaker_segments: list[SpeakerSegment]) -> str:
    overlaps = Counter()
    for segment in speaker_segments:
        overlap = max(0.0, min(end, segment.end) - max(start, segment.start))
        if overlap > 0:
            overlaps[segment.speaker_id] += overlap
    if overlaps:
        return overlaps.most_common(1)[0][0]
    nearest = min(speaker_segments, key=lambda segment: min(abs(start - segment.end), abs(end - segment.start)))
    return nearest.speaker_id


def make_transcript_segment(speaker_id: str, words: list[Word]) -> TranscriptSegment:
    return TranscriptSegment(
        speaker_id=speaker_id,
        start_time=words[0].start,
        end_time=words[-1].end,
        text=" ".join(word.text for word in words).strip(),
        words=words,
    )


def merge_adjacent_segments(segments: list[TranscriptSegment], gap_seconds: float = 0.75) -> list[TranscriptSegment]:
    merged: list[TranscriptSegment] = []
    for segment in segments:
        if merged and merged[-1].speaker_id == segment.speaker_id and segment.start_time - merged[-1].end_time <= gap_seconds:
            previous = merged[-1]
            previous.end_time = segment.end_time
            previous.text = f"{previous.text} {segment.text}".strip()
            previous.words.extend(segment.words)
        else:
            merged.append(segment)
    return merged


def clean_transcript_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    cleaned = [segment for segment in segments if segment.text.strip()]
    if not cleaned:
        return []

    result: list[TranscriptSegment] = []
    index = 0
    while index < len(cleaned):
        segment = cleaned[index]
        next_segment = cleaned[index + 1] if index + 1 < len(cleaned) else None
        if next_segment and is_tiny_leading_fragment(segment, next_segment):
            next_segment.start_time = segment.start_time
            next_segment.text = f"{segment.text.strip()} {next_segment.text.strip()}".strip()
            next_segment.words = segment.words + next_segment.words
            index += 1
            continue
        result.append(segment)
        index += 1
    return merge_adjacent_segments(result)


def is_tiny_leading_fragment(segment: TranscriptSegment, next_segment: TranscriptSegment) -> bool:
    if segment.speaker_id == next_segment.speaker_id:
        return False
    if next_segment.start_time - segment.end_time > 0.35:
        return False
    text = segment.text.strip()
    return segment.end_time - segment.start_time <= 0.5 and len(text.split()) == 1 and len(text) <= 3


def max_segment_end(segments: list[ASRSegment]) -> float:
    if not segments:
        return 0.0
    return max(segment.end for segment in segments)
