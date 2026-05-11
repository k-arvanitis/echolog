from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.eval.ami import (
    EvalFailure,
    average_filler_light_wer,
    average_wer,
    evaluate_ami_meeting,
    save_ami_transcript_artifacts,
    select_ami_meetings,
    write_eval_csv,
    write_eval_json_with_failures,
)
from meeting_intelligence_engine.logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Groq ASR against AMI manual word transcripts.")
    parser.add_argument("--audio-root", type=Path, default=Path("eval/data/amicorpus"))
    parser.add_argument("--transcripts", type=Path, default=Path("eval/data/ami_public_manual_1.6.2.zip"))
    parser.add_argument("--meeting-id", action="append", dest="meeting_ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--csv", type=Path, default=Path("eval/results/ami_eval_results.csv"))
    parser.add_argument("--json", type=Path, default=Path("eval/results/ami_eval_results.json"))
    parser.add_argument("--work-dir", type=Path, default=settings.data_dir / "eval")
    parser.add_argument("--vad", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument(
        "--save-transcripts",
        action="store_true",
        help=(
            "After evaluating each meeting run the full transcription pipeline "
            "(ASR + diarization + speaker labels) and save transcript artefacts "
            "(json, md, txt, srt) to "
            "{data_dir}/meetings/{meeting_id}/transcript/."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        selected = select_ami_meetings(
            audio_root=args.audio_root,
            transcript_source=args.transcripts,
            meeting_ids=args.meeting_ids,
            limit=args.limit,
        )
        if not selected:
            print("No AMI meeting pairs found.", file=sys.stderr)
            return 1
        results = []
        failures: list[EvalFailure] = []
        total = len(selected)
        for index, (meeting_id, audio_path) in enumerate(selected, start=1):
            print(f"[{index}/{total}] {meeting_id} start", flush=True)
            try:
                result = evaluate_ami_meeting(
                    meeting_id=meeting_id,
                    audio_path=audio_path,
                    transcript_source=args.transcripts,
                    settings=settings,
                    work_dir=args.work_dir,
                    use_vad=args.vad,
                )
                results.append(result)
                write_eval_csv(results, args.csv)
                write_eval_json_with_failures(results, args.json, failures)
                print(
                    f"[{index}/{total}] {meeting_id} done "
                    f"wer={result.wer:.4f} filler_light_wer={result.filler_light_wer:.4f} cer={result.cer:.4f}",
                    flush=True,
                )
                if args.save_transcripts:
                    try:
                        save_ami_transcript_artifacts(
                            meeting_id=meeting_id,
                            work_dir=args.work_dir,
                            settings=settings,
                        )
                    except Exception as exc:
                        print(
                            f"[{index}/{total}] {meeting_id} transcript save failed: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
            except Exception as exc:
                failure = EvalFailure(meeting_id=meeting_id, audio_path=str(audio_path), error=str(exc))
                failures.append(failure)
                write_eval_csv(results, args.csv)
                write_eval_json_with_failures(results, args.json, failures)
                print(f"[{index}/{total}] {meeting_id} failed error={exc}", file=sys.stderr, flush=True)
                if args.stop_on_error:
                    raise
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"meetings={len(results)} failed={len(failures)} average_wer={average_wer(results):.4f} "
        f"average_filler_light_wer={average_filler_light_wer(results):.4f}"
    )
    for result in results:
        print(
            f"{result.meeting_id} wer={result.wer:.4f} filler_light_wer={result.filler_light_wer:.4f} "
            f"cer={result.cer:.4f} chunks={result.chunk_count} strategy={result.chunking_strategy}"
        )
    print(args.csv)
    print(args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
