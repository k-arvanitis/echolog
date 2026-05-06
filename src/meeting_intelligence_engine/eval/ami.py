from __future__ import annotations

import csv
import json
import re
import string
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from zipfile import ZipFile

from meeting_intelligence_engine.audio import extract_audio_range, normalize_audio, probe_duration, require_ffmpeg, validate_audio
from meeting_intelligence_engine.config import Settings
from meeting_intelligence_engine.implementations.local_pipeline import GroqWhisperASR, resolve_device


FILLER_TOKENS = {
    "uh",
    "um",
    "mm",
    "hmm",
    "mhm",
    "mmhmm",
    "uhh",
    "umm",
    "ah",
    "er",
    "erm",
}
SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<value>-?\d+(?:\.\d+)?)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(?P<value>-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class TranscriptToken:
    text: str
    start_time: float
    source_file: str


@dataclass(frozen=True)
class EditCounts:
    substitutions: int
    deletions: int
    insertions: int


@dataclass(frozen=True)
class ErrorBuckets:
    deleted_fillers: int = 0
    deleted_short_words: int = 0
    inserted_short_words: int = 0
    repeated_reference_words: int = 0
    numeric_mismatches: int = 0


@dataclass(frozen=True)
class SpeechChunk:
    start: float
    end: float


@dataclass(frozen=True)
class NormalizedMetrics:
    reference_text: str
    predicted_text: str
    wer: float
    cer: float
    counts: EditCounts


@dataclass(frozen=True)
class AMIEvaluationResult:
    meeting_id: str
    reference_text: str
    predicted_text: str
    filler_light_reference_text: str
    filler_light_predicted_text: str
    wer: float
    cer: float
    filler_light_wer: float
    filler_light_cer: float
    reference_word_count: int
    predicted_word_count: int
    substitutions: int
    deletions: int
    insertions: int
    deleted_fillers: int
    deleted_short_words: int
    inserted_short_words: int
    repeated_reference_words: int
    numeric_mismatches: int
    chunk_count: int
    chunking_strategy: str
    audio_path: str
    transcript_sources: list[str]
    chunk_ranges: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvalFailure:
    meeting_id: str
    audio_path: str
    error: str


def normalize_for_wer(text: str) -> str:
    lowered = text.lower()
    table = str.maketrans("", "", string.punctuation)
    without_punctuation = lowered.translate(table)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def normalize_for_filler_light_wer(text: str) -> str:
    normalized = normalize_for_wer(text)
    tokens = normalized.split()
    compacted: list[str] = []
    previous: str | None = None
    for token in tokens:
        if token in FILLER_TOKENS:
            continue
        if token == previous:
            continue
        compacted.append(token)
        previous = token
    return " ".join(compacted)


def _levenshtein_operations(reference: list[str], hypothesis: list[str]) -> tuple[EditCounts, list[tuple[str, str | None, str | None]]]:
    rows = len(reference) + 1
    cols = len(hypothesis) + 1
    dp = [[0] * cols for _ in range(rows)]
    back: list[list[tuple[int, int, str] | None]] = [[None] * cols for _ in range(rows)]

    for i in range(1, rows):
        dp[i][0] = i
        back[i][0] = (i - 1, 0, "D")
    for j in range(1, cols):
        dp[0][j] = j
        back[0][j] = (0, j - 1, "I")

    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
                back[i][j] = (i - 1, j - 1, "M")
                continue
            substitution = (dp[i - 1][j - 1] + 1, (i - 1, j - 1, "S"))
            deletion = (dp[i - 1][j] + 1, (i - 1, j, "D"))
            insertion = (dp[i][j - 1] + 1, (i, j - 1, "I"))
            best_cost, best_back = min((substitution, deletion, insertion), key=lambda item: item[0])
            dp[i][j] = best_cost
            back[i][j] = best_back

    i = len(reference)
    j = len(hypothesis)
    substitutions = deletions = insertions = 0
    ops: list[tuple[str, str | None, str | None]] = []
    while i > 0 or j > 0:
        prev = back[i][j]
        if prev is None:
            break
        prev_i, prev_j, op = prev
        ref_token = reference[prev_i] if op in {"M", "S", "D"} and prev_i < len(reference) else None
        hyp_token = hypothesis[prev_j] if op in {"M", "S", "I"} and prev_j < len(hypothesis) else None
        ops.append((op, ref_token, hyp_token))
        i, j = prev_i, prev_j
        if op == "S":
            substitutions += 1
        elif op == "D":
            deletions += 1
        elif op == "I":
            insertions += 1
    ops.reverse()
    return EditCounts(substitutions=substitutions, deletions=deletions, insertions=insertions), ops


def word_error_rate(reference_text: str, predicted_text: str) -> tuple[float, EditCounts]:
    reference_words = reference_text.split()
    hypothesis_words = predicted_text.split()
    if not reference_words:
        return (0.0 if not hypothesis_words else 1.0), EditCounts(0, 0, len(hypothesis_words))
    counts, _ops = _levenshtein_operations(reference_words, hypothesis_words)
    wer = (counts.substitutions + counts.deletions + counts.insertions) / len(reference_words)
    return wer, counts


def _levenshtein_distance_only(reference: list[str], hypothesis: list[str]) -> int:
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)
    previous = list(range(len(hypothesis) + 1))
    for i, ref_item in enumerate(reference, start=1):
        current = [i]
        for j, hyp_item in enumerate(hypothesis, start=1):
            substitution_cost = 0 if ref_item == hyp_item else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + substitution_cost,
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference_text: str, predicted_text: str) -> float:
    reference_chars = list(reference_text)
    hypothesis_chars = list(predicted_text)
    if not reference_chars:
        return 0.0 if not hypothesis_chars else 1.0
    distance = _levenshtein_distance_only(reference_chars, hypothesis_chars)
    return distance / len(reference_chars)


def _element_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_word_files_from_dir(words_dir: Path, meeting_id: str) -> list[tuple[str, bytes]]:
    direct = words_dir / f"{meeting_id}.words.xml"
    if direct.exists():
        return [(direct.name, direct.read_bytes())]
    files = sorted(words_dir.glob(f"{meeting_id}.*.words.xml"))
    return [(path.name, path.read_bytes()) for path in files]


def _iter_word_files_from_zip(zip_path: Path, meeting_id: str) -> list[tuple[str, bytes]]:
    with ZipFile(zip_path) as archive:
        exact_name = f"words/{meeting_id}.words.xml"
        if exact_name in archive.namelist():
            return [(exact_name, archive.read(exact_name))]
        matches = sorted(
            name for name in archive.namelist() if name.startswith(f"words/{meeting_id}.") and name.endswith(".words.xml")
        )
        return [(name, archive.read(name)) for name in matches]


def _load_word_files(transcript_source: Path, meeting_id: str) -> list[tuple[str, bytes]]:
    if transcript_source.is_dir():
        words_dir = transcript_source / "words" if (transcript_source / "words").is_dir() else transcript_source
        return _iter_word_files_from_dir(words_dir, meeting_id)
    return _iter_word_files_from_zip(transcript_source, meeting_id)


def parse_ami_meeting_reference(transcript_source: Path, meeting_id: str) -> tuple[str, list[str]]:
    tokens: list[TranscriptToken] = []
    files = _load_word_files(transcript_source, meeting_id)
    if not files:
        raise FileNotFoundError(f"No AMI words transcript found for meeting {meeting_id} in {transcript_source}")
    for source_name, xml_bytes in files:
        root = ET.fromstring(xml_bytes)
        for element in root.iter():
            if _element_name(element.tag) != "w":
                continue
            text = (element.text or "").strip()
            if not text:
                continue
            start_time = float(element.attrib.get("starttime", "inf"))
            tokens.append(TranscriptToken(text=text, start_time=start_time, source_file=source_name))
    tokens.sort(key=lambda item: (item.start_time, item.source_file))
    return " ".join(token.text for token in tokens), [name for name, _ in files]


def discover_ami_meetings(audio_root: Path, transcript_source: Path) -> dict[str, tuple[Path, list[str]]]:
    meetings: dict[str, tuple[Path, list[str]]] = {}
    for audio_path in sorted(audio_root.glob("*/audio/*.Mix-Headset.wav")):
        meeting_id = audio_path.name.replace(".Mix-Headset.wav", "")
        transcript_files = _load_word_files(transcript_source, meeting_id)
        if transcript_files:
            meetings[meeting_id] = (audio_path, [name for name, _ in transcript_files])
    return meetings


def select_ami_meetings(
    audio_root: Path,
    transcript_source: Path,
    meeting_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[tuple[str, Path]]:
    discovered = discover_ami_meetings(audio_root, transcript_source)
    if meeting_ids:
        selected = [(meeting_id, discovered[meeting_id][0]) for meeting_id in meeting_ids if meeting_id in discovered]
        missing = [meeting_id for meeting_id in meeting_ids if meeting_id not in discovered]
        if missing:
            raise FileNotFoundError(f"Missing audio/transcript pairs for meetings: {', '.join(missing)}")
    else:
        selected = [(meeting_id, audio_path) for meeting_id, (audio_path, _files) in sorted(discovered.items())]
    if limit is not None:
        selected = selected[:limit]
    return selected


def detect_speech_chunks(
    audio_path: Path,
    silence_threshold_db: str = "-35dB",
    min_silence_seconds: float = 0.6,
    min_chunk_seconds: float = 1.0,
) -> list[SpeechChunk]:
    require_ffmpeg()
    duration = probe_duration(audio_path)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=noise={silence_threshold_db}:d={min_silence_seconds}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    trace = f"{proc.stdout}\n{proc.stderr}"
    silence_starts = [float(match.group("value")) for match in SILENCE_START_RE.finditer(trace)]
    silence_ends = [float(match.group("value")) for match in SILENCE_END_RE.finditer(trace)]

    chunks: list[SpeechChunk] = []
    cursor = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends, strict=False):
        if silence_start - cursor >= min_chunk_seconds:
            chunks.append(SpeechChunk(start=max(0.0, cursor), end=min(duration, silence_start)))
        cursor = max(cursor, silence_end)
    if duration - cursor >= min_chunk_seconds:
        chunks.append(SpeechChunk(start=max(0.0, cursor), end=duration))
    if not chunks:
        chunks.append(SpeechChunk(start=0.0, end=duration))
    return chunks


def _transcribe_chunks(normalized_path: Path, asr: GroqWhisperASR, chunks: list[SpeechChunk], work_dir: Path) -> str:
    texts: list[str] = []
    for index, chunk in enumerate(chunks):
        chunk_path = work_dir / f"{normalized_path.stem}.chunk{index:04d}.wav"
        extract_audio_range(normalized_path, chunk_path, chunk.start, chunk.end - chunk.start)
        segments = asr._transcribe_chunk(chunk_path, chunk.start)  # reuse the same backend offsets
        chunk_text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        if chunk_text:
            texts.append(chunk_text)
    return " ".join(texts)


def transcribe_audio_for_eval(
    audio_path: Path,
    settings: Settings,
    work_dir: Path,
    use_vad: bool = False,
) -> tuple[str, list[SpeechChunk], str]:
    validate_audio(audio_path, settings.max_upload_mb, settings.max_duration_seconds)
    work_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = work_dir / f"{audio_path.stem}.eval.wav"
    normalize_audio(audio_path, normalized_path)
    asr = GroqWhisperASR(
        api_key=settings.groq_api_key,
        model_name=settings.asr_model_name,
        language=settings.language,
        chunk_seconds=settings.asr_chunk_seconds,
    )
    asr.load("", resolve_device(settings.device))
    if use_vad:
        chunks = detect_speech_chunks(normalized_path)
        return _transcribe_chunks(normalized_path, asr, chunks, work_dir), chunks, "silencedetect_vad"
    segments = asr.transcribe(normalized_path)
    duration = probe_duration(normalized_path)
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip()), [SpeechChunk(0.0, duration)], "fixed_chunking"


def _score_normalization(reference_text: str, predicted_text: str, normalizer) -> NormalizedMetrics:
    reference_normalized = normalizer(reference_text)
    predicted_normalized = normalizer(predicted_text)
    wer, counts = word_error_rate(reference_normalized, predicted_normalized)
    cer = character_error_rate(reference_normalized, predicted_normalized)
    return NormalizedMetrics(
        reference_text=reference_normalized,
        predicted_text=predicted_normalized,
        wer=wer,
        cer=cer,
        counts=counts,
    )


def _analyze_error_buckets(reference_text: str, predicted_text: str) -> ErrorBuckets:
    reference_tokens = reference_text.split()
    predicted_tokens = predicted_text.split()
    _counts, ops = _levenshtein_operations(reference_tokens, predicted_tokens)
    deleted_fillers = 0
    deleted_short_words = 0
    inserted_short_words = 0
    repeated_reference_words = 0
    numeric_mismatches = 0
    prev_ref: str | None = None
    for op, ref_token, hyp_token in ops:
        if op == "D" and ref_token:
            if ref_token in FILLER_TOKENS:
                deleted_fillers += 1
            if len(ref_token) <= 2:
                deleted_short_words += 1
            if prev_ref == ref_token:
                repeated_reference_words += 1
        elif op == "I" and hyp_token and len(hyp_token) <= 2:
            inserted_short_words += 1
        elif op == "S" and ref_token and hyp_token and (ref_token.isdigit() or hyp_token.isdigit()):
            numeric_mismatches += 1
        if ref_token is not None:
            prev_ref = ref_token
    return ErrorBuckets(
        deleted_fillers=deleted_fillers,
        deleted_short_words=deleted_short_words,
        inserted_short_words=inserted_short_words,
        repeated_reference_words=repeated_reference_words,
        numeric_mismatches=numeric_mismatches,
    )


def evaluate_ami_meeting(
    meeting_id: str,
    audio_path: Path,
    transcript_source: Path,
    settings: Settings,
    work_dir: Path,
    use_vad: bool = False,
) -> AMIEvaluationResult:
    reference_text_raw, transcript_sources = parse_ami_meeting_reference(transcript_source, meeting_id)
    predicted_text_raw, chunks, chunking_strategy = transcribe_audio_for_eval(audio_path, settings, work_dir / meeting_id, use_vad=use_vad)
    raw_metrics = _score_normalization(reference_text_raw, predicted_text_raw, normalize_for_wer)
    filler_light_metrics = _score_normalization(reference_text_raw, predicted_text_raw, normalize_for_filler_light_wer)
    buckets = _analyze_error_buckets(raw_metrics.reference_text, raw_metrics.predicted_text)
    return AMIEvaluationResult(
        meeting_id=meeting_id,
        reference_text=raw_metrics.reference_text,
        predicted_text=raw_metrics.predicted_text,
        filler_light_reference_text=filler_light_metrics.reference_text,
        filler_light_predicted_text=filler_light_metrics.predicted_text,
        wer=raw_metrics.wer,
        cer=raw_metrics.cer,
        filler_light_wer=filler_light_metrics.wer,
        filler_light_cer=filler_light_metrics.cer,
        reference_word_count=len(raw_metrics.reference_text.split()),
        predicted_word_count=len(raw_metrics.predicted_text.split()),
        substitutions=raw_metrics.counts.substitutions,
        deletions=raw_metrics.counts.deletions,
        insertions=raw_metrics.counts.insertions,
        deleted_fillers=buckets.deleted_fillers,
        deleted_short_words=buckets.deleted_short_words,
        inserted_short_words=buckets.inserted_short_words,
        repeated_reference_words=buckets.repeated_reference_words,
        numeric_mismatches=buckets.numeric_mismatches,
        chunk_count=len(chunks),
        chunking_strategy=chunking_strategy,
        audio_path=str(audio_path),
        transcript_sources=transcript_sources,
        chunk_ranges=[f"{chunk.start:.2f}-{chunk.end:.2f}" for chunk in chunks],
    )


def evaluate_ami_meetings(
    audio_root: Path,
    transcript_source: Path,
    settings: Settings,
    meeting_ids: list[str] | None = None,
    limit: int | None = None,
    work_dir: Path | None = None,
    use_vad: bool = False,
) -> list[AMIEvaluationResult]:
    work_dir = work_dir or settings.data_dir / "eval"
    selected = select_ami_meetings(audio_root, transcript_source, meeting_ids=meeting_ids, limit=limit)

    results: list[AMIEvaluationResult] = []
    for meeting_id, audio_path in selected:
        results.append(
            evaluate_ami_meeting(
                meeting_id=meeting_id,
                audio_path=audio_path,
                transcript_source=transcript_source,
                settings=settings,
                work_dir=work_dir,
                use_vad=use_vad,
            )
        )
    return results


def average_wer(results: list[AMIEvaluationResult]) -> float:
    if not results:
        return 0.0
    return sum(result.wer for result in results) / len(results)


def average_filler_light_wer(results: list[AMIEvaluationResult]) -> float:
    if not results:
        return 0.0
    return sum(result.filler_light_wer for result in results) / len(results)


def write_eval_csv(results: list[AMIEvaluationResult], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(results[0]).keys()) if results else list(AMIEvaluationResult.__dataclass_fields__.keys())
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def write_eval_json(results: list[AMIEvaluationResult], output_path: Path) -> None:
    write_eval_json_with_failures(results, output_path, failures=[])


def write_eval_json_with_failures(
    results: list[AMIEvaluationResult],
    output_path: Path,
    failures: list[EvalFailure],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "average_wer": average_wer(results),
        "average_filler_light_wer": average_filler_light_wer(results),
        "completed_meetings": len(results),
        "failed_meetings": len(failures),
        "results": [asdict(result) for result in results],
        "failures": [asdict(failure) for failure in failures],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
