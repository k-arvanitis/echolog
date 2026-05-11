from __future__ import annotations

from pathlib import Path

from meeting_intelligence_engine.eval.ami import (
    SpeechChunk,
    detect_speech_chunks,
    evaluate_ami_meeting,
    normalize_for_filler_light_wer,
    normalize_for_wer,
    parse_ami_meeting_reference,
    word_error_rate,
)


def test_normalize_for_wer_lowercases_strips_punctuation_and_normalizes_spaces() -> None:
    assert normalize_for_wer(" Hello,   WORLD! I've\tarrived. ") == "hello world ive arrived"


def test_normalize_for_filler_light_wer_removes_fillers_and_immediate_duplicates() -> None:
    assert normalize_for_filler_light_wer("Uh hello hello mm there") == "hello there"


def test_parse_ami_meeting_reference_merges_speaker_files_in_time_order(tmp_path: Path) -> None:
    words_dir = tmp_path / "words"
    words_dir.mkdir()
    (words_dir / "ES2005a.A.words.xml").write_text(
        """
        <nite:root xmlns:nite="http://nite.sourceforge.net/">
          <w starttime="0.50" endtime="0.70">hello</w>
          <w starttime="1.20" endtime="1.40">again</w>
        </nite:root>
        """,
        encoding="utf-8",
    )
    (words_dir / "ES2005a.B.words.xml").write_text(
        """
        <nite:root xmlns:nite="http://nite.sourceforge.net/">
          <w starttime="0.80" endtime="1.00">there</w>
          <w starttime="1.50" endtime="1.70">friend</w>
        </nite:root>
        """,
        encoding="utf-8",
    )

    text, sources = parse_ami_meeting_reference(tmp_path, "ES2005a")

    assert text == "hello there again friend"
    assert sources == ["ES2005a.A.words.xml", "ES2005a.B.words.xml"]


def test_word_error_rate_returns_expected_counts() -> None:
    wer, counts = word_error_rate("hello there friend", "hello friend")

    assert wer == 1 / 3
    assert counts.deletions == 1
    assert counts.insertions == 0
    assert counts.substitutions == 0


def test_detect_speech_chunks_builds_ranges_from_silencedetect(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"RIFF")

    monkeypatch.setattr("meeting_intelligence_engine.eval.ami.require_ffmpeg", lambda: None)
    monkeypatch.setattr("meeting_intelligence_engine.eval.ami.probe_duration", lambda _path: 10.0)

    class _Proc:
        stdout = ""
        stderr = "[silencedetect @ x] silence_start: 2.0\n[silencedetect @ x] silence_end: 3.0\n[silencedetect @ x] silence_start: 8.0\n[silencedetect @ x] silence_end: 8.5\n"

    monkeypatch.setattr("meeting_intelligence_engine.eval.ami.subprocess.run", lambda *args, **kwargs: _Proc())

    chunks = detect_speech_chunks(audio_path)

    assert [(round(chunk.start, 1), round(chunk.end, 1)) for chunk in chunks] == [(0.0, 2.0), (3.0, 8.0), (8.5, 10.0)]


class _StubSettings:
    max_upload_mb = 500
    max_duration_seconds = 14_400
    groq_api_key = "test"
    asr_model_name = "whisper-large-v3"
    language = None
    asr_chunk_seconds = 600
    device = "cpu"

    def secret(self, name: str) -> str | None:
        return getattr(self, name)


def test_evaluate_ami_meeting_uses_normalized_reference_and_prediction(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "ES2005a.Mix-Headset.wav"
    audio_path.write_bytes(b"RIFF")
    words_dir = tmp_path / "words"
    words_dir.mkdir()
    (words_dir / "ES2005a.A.words.xml").write_text(
        """
        <nite:root xmlns:nite="http://nite.sourceforge.net/">
          <w starttime="0.10" endtime="0.20">Hello</w>
          <w starttime="0.20" endtime="0.30">world</w>
          <w starttime="0.30" endtime="0.40">!</w>
        </nite:root>
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr("meeting_intelligence_engine.eval.ami.validate_audio", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr(
        "meeting_intelligence_engine.eval.ami.normalize_audio", lambda source, target: target.write_bytes(b"RIFF")
    )
    monkeypatch.setattr("meeting_intelligence_engine.eval.ami.resolve_device", lambda device: device)
    monkeypatch.setattr(
        "meeting_intelligence_engine.eval.ami.detect_speech_chunks", lambda *_args, **_kwargs: [SpeechChunk(0.0, 1.0)]
    )
    monkeypatch.setattr("meeting_intelligence_engine.eval.ami.probe_duration", lambda _path: 1.0)
    monkeypatch.setattr(
        "meeting_intelligence_engine.eval.ami.extract_audio_range",
        lambda source, target, start, duration: target.write_bytes(b"RIFF"),
    )

    class _StubASR:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def load(self, *_args):
            return None

        def _transcribe_chunk(self, _audio_path, _offset):
            class Segment:
                text = "Hello, world."

            return [Segment()]

    monkeypatch.setattr("meeting_intelligence_engine.eval.ami.GroqWhisperASR", _StubASR)

    result = evaluate_ami_meeting(
        meeting_id="ES2005a",
        audio_path=audio_path,
        transcript_source=tmp_path,
        settings=_StubSettings(),
        work_dir=tmp_path / "work",
        use_vad=True,
    )

    assert result.reference_text == "hello world"
    assert result.predicted_text == "hello world"
    assert result.wer == 0.0
    assert result.filler_light_wer == 0.0
    assert result.chunking_strategy == "silencedetect_vad"
