# Meeting Intelligence Engine

Turn company meetings into a searchable memory layer.

This project ingests meeting audio, produces speaker-attributed transcripts, extracts structured decisions and action items, and indexes the resulting knowledge so a team can ask questions across **all prior meetings**, not just one transcript at a time.

The main product idea is simple:

- every meeting gets saved;
- every meeting becomes queryable;
- the company builds an internal memory of what was discussed, decided, assigned, and repeated over time.

Per-meeting query still exists, but it is a drill-down tool. The primary value is the **shared meeting store** and the ability to ask questions across the whole corpus.

## What It Does

- uploads audio through API or UI;
- validates and normalizes media with `ffprobe` and `ffmpeg`;
- transcribes with Groq Whisper;
- diarizes speakers with `pyannote`;
- repairs common alignment artifacts in broken speaker turns;
- resolves speaker names where the transcript explicitly supports them;
- exports transcripts as `json`, `txt`, `srt`, and `md`;
- extracts structured:
  - action items
  - decisions
  - topics
- stores data in PostgreSQL;
- indexes transcript Markdown in Qdrant with local embeddings;
- answers questions across all meetings or within a single meeting.

## Product Framing

This is not just a transcript viewer.

It is a backend for a company knowledge product where teams can ask questions like:

- What did we decide about parking?
- When did we first discuss the training issue?
- Which meetings mentioned customer churn?
- What action items were assigned to Jason in the last quarter?
- Did we already agree on the rollout plan?

The current repo already demonstrates that workflow end to end.

## Current Scope

Implemented:

- FastAPI API and UI
- Celery + Redis background processing
- PostgreSQL persistence
- Qdrant-based transcript RAG
- local Ollama embeddings (`nomic-embed-text`)
- Groq analytics extraction
- cross-meeting query
- per-meeting query

Not implemented yet:

- auth / multi-tenant ownership
- Zoom bot / live streaming
- object storage like S3 / MinIO
- production deployment stack

## Architecture

```text
upload
-> normalize audio
-> ASR
-> diarization
-> alignment
-> segment repair
-> speaker labeling
-> transcript export
-> analytics extraction
-> markdown indexing
-> query across the meeting store
```

```mermaid
flowchart LR
    U[User / Team] --> UI[FastAPI UI + API]
    UI --> PG[(PostgreSQL)]
    UI --> RQ[(Redis / Celery Broker)]
    UI --> Q[(Qdrant)]

    UI --> UP[Upload Meeting Audio]
    UP --> W1[Transcription Worker]
    W1 --> N1[Normalize Audio]
    N1 --> A1[Groq Whisper ASR]
    A1 --> D1[Pyannote Diarization]
    D1 --> AL[Alignment + Segment Repair]
    AL --> SL[Speaker Label Resolution]
    SL --> T[(Transcript Artifacts)]
    SL --> PG

    T --> W2[Analytics Worker]
    W2 --> AX[Structured Extraction]
    AX --> PG

    T --> W3[Indexing Worker]
    W3 --> E1[Ollama Embeddings]
    E1 --> Q

    UI --> CQ[Cross-meeting Query]
    CQ --> Q
    CQ --> AA[Answer Generation]
    AA --> U
```

System components:

- API/UI: FastAPI
- background jobs: Celery + Redis
- relational storage: PostgreSQL
- vector storage: Qdrant
- embeddings: Ollama `nomic-embed-text`
- ASR: Groq Whisper
- diarization: pyannote
- analytics / answer generation: Groq chat models

## Evaluation

The current ASR benchmark is run on the **AMI Meeting Corpus Mix-Headset** setup, which is the closest fit to the product target here: one mixed meeting recording with multiple speakers, overlap, interruptions, and conversational speech.

Final full-corpus result on **30/30 meetings**:

- mean **raw WER**: **24.99%**
- mean **filler-light WER**: **20.65%**
- failed meetings: **0**

Best / worst meetings:

- best: `ES2016b` -> `19.22%` raw WER, `15.20%` filler-light WER
- worst: `ES2005a` -> `35.34%` raw WER, `31.32%` filler-light WER

`filler-light WER` is reported as a secondary conversational metric. It removes obvious fillers such as `uh`, `um`, and `mm`, plus immediate duplicate tokens, to reduce mismatch between usable ASR output and filler-heavy manual annotations. Raw WER remains the main benchmark.

These numbers are materially higher than clean single-speaker benchmarks for a simple reason: this is **mixed multi-speaker meeting audio**, not isolated headset speech. Overlap, turn-taking, disfluencies, and annotation mismatch all make raw word-level scoring harsher. Even when raw WER is imperfect, the resulting transcripts are still often good enough to preserve the main discussion content for retrieval, action extraction, and cross-meeting search.

## Batch-First Design

This system is intentionally built as a **batch pipeline**, not a live meeting copilot.

That tradeoff is deliberate:

- full-meeting context improves transcription cleanup, speaker attribution, analytics extraction, and retrieval quality;
- long-running steps like diarization, transcript repair, structured extraction, and indexing fit naturally in background workers;
- the product goal is durable meeting memory, not low-latency live assistance.

Current behavior:

- uploads are accepted immediately by the API;
- background workers process transcription, analytics, and indexing asynchronously;
- queries run synchronously against the stored meeting corpus after processing completes.

This means the system is optimized for **accuracy and post-meeting knowledge capture** over real-time response.

## Query Model

There are two query modes:

1. **Cross-meeting query**
   - asks over the entire meeting store
   - this is the main product behavior

2. **Single-meeting query**
   - restricts retrieval to one meeting
   - useful for inspection, debugging, or focused review

In practice, if a company uses this system properly, they keep saving meetings and the value compounds over time because the retrievable context grows.

## Failure Modes

This project handles noisy meeting data reasonably well, but it is still an imperfect pipeline. The main failure modes are known and documented.

### Speaker diarization

The hardest failures come from speaker segmentation:

- short interruptions can be split into the wrong speaker turn;
- adjacent sentences may be broken across two speakers;
- overlapping speech and crosstalk reduce diarization quality;
- remote-call audio, compression artifacts, and inconsistent microphone quality make segmentation worse.

The repo includes repair heuristics for common cases such as:

- broken self-introductions split across adjacent segments;
- short leading sentence fragments that really belong to the previous speaker turn.

Those repairs improve output quality, but they are still heuristics and not a full learned correction layer.

### Speaker naming

Speaker naming is conservative by design:

- deterministic self-introduction parsing runs first;
- LLM fallback is used only for unresolved speakers;
- conflicting or truncated evidence is intentionally ignored rather than over-labeled.

Known limitations:

- no self-introduction means the system may keep `SPEAKER_XX`;
- nicknames, aliases, and indirect references are not fully normalized;
- diarization mistakes upstream can still make a correct name land on the wrong region unless a repair rule catches it.

### Analytics extraction

Structured extraction is stronger than free-form summarization, but still has failure cases:

- decision context may be too sparse if the source exchange is fragmented;
- action items can be inferred too broadly when speakers are vague;
- topic boundaries depend on timestamp quality and discussion coherence;
- the LLM sometimes returns malformed or overly sparse JSON, which is why the pipeline now sanitizes and enriches the response.

To reduce brittleness, the pipeline:

- forces JSON-only structured output;
- validates and coerces fields before persistence;
- runs a topic-only fallback pass when the generic analytics pass returns no topics;
- fills missing decision context and stakeholders from nearby transcript lines where possible.

### Retrieval and query

Cross-meeting retrieval is useful, but not infallible:

- if the transcript is wrong, retrieval inherits the error;
- relevant context can be missed if the chunk boundary is awkward;
- answer quality depends on the retrieved transcript evidence, not hidden knowledge.

The system is designed to answer from stored meeting context only. When evidence is weak, the right behavior is an incomplete answer rather than a confident invention.

## Production Considerations

This repo processes meeting audio and transcripts that may contain sensitive company information, personal data, or internal decisions.

The current implementation is a strong engineering prototype, but it should not be presented as a fully compliant enterprise deployment yet.

For production use, the next layer should include:

- authentication and access control;
- encryption in transit and at rest;
- retention and deletion policies for raw audio, transcripts, and derived analytics;
- participant consent and recording disclosure mechanisms;
- audit logging for uploads, queries, and deletions;
- PII handling or redaction where required by the company or jurisdiction.

In other words: the core AI pipeline is implemented, but privacy, governance, and compliance controls still need to be added deliberately rather than implied.

## Remaining Gaps

The current repo is a strong end-to-end prototype, but it is not a finished production product yet.

The main remaining gaps are:

- auth and workspace ownership;
- production deployment hardening;
- stricter privacy and compliance controls;
- more operational observability and admin controls.

Concretely, a production version should still add:

- user login and company/workspace isolation;
- HTTPS, reverse proxying, and production deployment documentation;
- encryption and stronger auditability guarantees;
- more explicit governance around retention, deletion, and sensitive data access.

## Required Services

- `uv`
- `ffmpeg`
- `ffprobe`
- PostgreSQL
- Redis
- Qdrant
- Ollama with `nomic-embed-text`
- `make` (optional, but recommended)

## Environment

Use `.env` or copy from `.env.example`.

Required secrets:

```dotenv
GROQ_API_KEY=
HF_TOKEN=
```

Key runtime settings:

```dotenv
MIE_API_PORT=8001
DATABASE_URL=postgresql+psycopg://mie:mie@localhost:55432/mie
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=meeting_transcript_md
DENSE_MODEL=nomic-embed-text
MIE_ANALYTICS_ENABLED=true
MIE_RAG_ENABLED=true
MIE_ANALYTICS_MODEL_NAME=llama-3.1-8b-instant
MIE_RAG_MODEL_NAME=llama-3.1-8b-instant
```

The Hugging Face account behind `HF_TOKEN` must have accepted the gated `pyannote/speaker-diarization-3.1` terms.

## Install

```bash
uv sync --extra dev
```

## Run Locally

Start infrastructure:

```bash
make infra-up
ollama pull nomic-embed-text
```

Start the worker:

```bash
make worker
```

Start the API and UI:

```bash
make api
```

Or start infrastructure, worker, and API together in a tmux session:

```bash
make stack
tmux attach -t mie_stack
```

Open:

```text
http://127.0.0.1:8001
```

## CLI

```bash
uv run meeting-transcribe --input samples/Product-Team-Meeting.mp3 --output-dir outputs
```

Useful local commands:

```bash
make test
make lint
make eval-ami
make clean-eval
```

## Data Layout

Meeting artifacts are stored locally under:

```text
data/meetings/{meeting_id}/
```

Typical output:

```text
data/meetings/{meeting_id}/raw/
data/meetings/{meeting_id}/processed/
data/meetings/{meeting_id}/transcript/transcript.json
data/meetings/{meeting_id}/transcript/transcript.txt
data/meetings/{meeting_id}/transcript/transcript.srt
data/meetings/{meeting_id}/transcript/transcript.md
```

RAG indexes transcript Markdown from:

```text
data/meetings/{meeting_id}/transcript/transcript.md
data/md/**/*.md
```

## API

Core endpoints:

- `GET /`
- `GET /health`
- `POST /meetings/upload`
- `GET /meetings`
- `GET /meetings/{meeting_id}`
- `DELETE /meetings/{meeting_id}`
- `GET /meetings/{meeting_id}/transcript`
- `GET /meetings/{meeting_id}/segments`
- `GET /meetings/{meeting_id}/speaker-labels`
- `GET /meetings/{meeting_id}/artifacts/json`
- `GET /meetings/{meeting_id}/artifacts/txt`
- `GET /meetings/{meeting_id}/artifacts/srt`
- `GET /meetings/{meeting_id}/artifacts/md`
- `GET /meetings/{meeting_id}/action-items`
- `GET /meetings/{meeting_id}/decisions`
- `GET /meetings/{meeting_id}/topics`
- `POST /meetings/{meeting_id}/query`
- `POST /query`
- `POST /knowledge/query`

Upload example:

```bash
curl -F "file=@samples/voice-sample.mp3" \
  -F "title=Voice Sample" \
  http://127.0.0.1:8001/meetings/upload
```

Cross-meeting query example:

```bash
curl -X POST http://127.0.0.1:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What did we decide about performance?","top_k":5}'
```

Single-meeting query example:

```bash
curl -X POST http://127.0.0.1:8001/meetings/{meeting_id}/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What did they decide about performance?","top_k":5}'
```

Manual full rebuild of the Markdown index:

```bash
uv run mie-ingest-md --recreate data/meetings data/md
```

## Why It Is Strong Portfolio Material

It shows real systems work, not a toy demo:

- multimodal ingestion
- asynchronous AI pipeline orchestration
- transcript repair and speaker attribution
- structured extraction
- vector search
- full-stack API/UI integration
- iterative quality improvements on noisy real outputs

## Test

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
```
