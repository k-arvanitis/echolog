# Echolog — Audio Meeting Intelligence

**Echolog turns meeting audio into a queryable knowledge base** — speaker-attributed transcripts, structured action items and decisions, and grounded answers with citations across every meeting you've ever recorded. Measured: **94% faithfulness on a 50-question RAG eval; 25% raw WER on 30 AMI multi-speaker meetings; 0 failed transcriptions across the corpus**.

Built for teams that record every meeting and want institutional memory — not one-off summaries. Echolog's primary surface is **cross-meeting retrieval**: ask a question, get a grounded answer drawn from your entire meeting history.

**Who this is for:** Engineering teams, ops managers, and any organization running regular internal meetings that need durable, searchable institutional memory.

[![Echolog CI](https://github.com/k-arvanitis/echolog/actions/workflows/ci.yml/badge.svg)](https://github.com/k-arvanitis/echolog/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js%2014-000000?style=for-the-badge&logo=next.js&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?style=for-the-badge&logo=qdrant&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9?style=for-the-badge)

---

## Demo

https://github.com/user-attachments/assets/3a30c241-c184-4693-8f59-bd3534810cf4

| Analytics — action items, decisions, topics | Ask — grounded answers with citations |
|---|---|
| ![Analytics tab](assets/analytics.png) | ![Ask tab](assets/ask.png) |

---

**The problem.** Meetings contain the highest-value information in any organization — decisions made, owners assigned, blockers raised — but it's locked inside hour-long audio. Action items get lost in the recording. The same questions get re-asked weeks later. New hires can't catch up on the last three months of decisions. Existing meeting-intelligence tools stop at "transcribe one file and summarize it" — they don't accumulate.

**What Echolog does.** Ingests meeting audio end-to-end: ASR (Groq Whisper), diarization (pyannote 3.1), segment repair, rule-based + LLM speaker naming, structured analytics extraction (action items, decisions, topics), and markdown indexing into Qdrant with hybrid (dense + BM25) retrieval. Every processed meeting joins a shared store you can query across.

**How you use it.** Drop in an mp3 → watch it process → browse the auto-extracted analytics → ask a question scoped to that meeting (drill-down) or across every meeting you've ever uploaded (the primary surface). Answers are grounded in retrieved transcript chunks with explicit `[Source N]` citations; the model refuses to answer when evidence is missing.

---

## Architecture

```
┌──────────────────────────┐                 ┌──────────────────────────────────┐
│   Next.js 14 frontend    │                 │   FastAPI backend (uvicorn)      │
│   (TypeScript + Tailwind)│                 │                                  │
│                          │                 │  POST /meetings/upload           │
│  Sidebar ────────────────┼── fetch + poll ─►  GET  /meetings/{id}             │
│  MeetingDetail (tabs)    │                 │  POST /query        (cross)      │
│  CrossMeetingPanel       │                 │  POST /meetings/{id}/query       │
└──────────────────────────┘                 └──────────────┬───────────────────┘
                                                            │
                                       ┌────────────────────┴───────────────────┐
                                       ▼                                        ▼
                              ┌─────────────────┐                  ┌───────────────────────┐
                              │  PostgreSQL     │                  │  Redis (Celery broker)│
                              │  meeting state  │                  └──────────┬────────────┘
                              │  transcripts    │                             │
                              │  analytics      │                             ▼
                              └─────────────────┘            ┌──────────────────────────────┐
                                       ▲                     │   Celery worker              │
                                       │                     │   transcribe · analytics ·   │
                                       └─────────────────────┤   indexing                   │
                                                             └──────────────┬───────────────┘
                                                                            │
                              ┌────────────────────┬───────────────────┬────┴──────────────┐
                              ▼                    ▼                   ▼                   ▼
                       ┌────────────┐      ┌────────────┐      ┌─────────────┐    ┌─────────────────┐
                       │ Groq       │      │ pyannote   │      │ Groq chat   │    │ Ollama embed +  │
                       │ Whisper    │      │ diarization│      │ llama-3.1/3 │    │ Qdrant (hybrid) │
                       └────────────┘      └────────────┘      └─────────────┘    └─────────────────┘
```

End-to-end pipeline (Mermaid for GitHub renderers):

```mermaid
flowchart TD
    A[upload audio] --> B[validate + normalize<br/>ffprobe / ffmpeg]
    B --> C[ASR — Groq Whisper]
    C --> D[diarization — pyannote]
    D --> E[alignment + segment repair]
    E --> F[speaker label resolution<br/>rules → LLM fallback]
    F --> G[transcript exports<br/>json / txt / srt / md]
    G --> H[analytics extraction<br/>action items · decisions · topics]
    H --> I[markdown indexing<br/>Ollama embeddings → Qdrant]
    I --> J[cross-meeting query<br/>RRF fusion → grounded answer + citations]
```

The pipeline runs as Celery tasks behind the API; the frontend polls until the meeting's status flips to `ready`. The same retrieval layer serves both per-meeting (drill-down) and cross-meeting (primary) queries — the only difference is a Qdrant payload filter.

---

## Key Engineering Decisions

**Cross-corpus retrieval as the primary surface — not per-meeting summary.** Most meeting-intelligence demos stop at transcribing and summarizing a single file. Echolog assumes meeting value compounds over time: every processed meeting goes into one shared store, and `POST /query` searches all of them via hybrid (dense + BM25, fused with RRF) retrieval. Per-meeting queries exist as drill-downs but are the secondary mode — the right-pane chat in the UI is always cross-corpus.

**Grounded answers with refusal — not summarization.** The RAG prompt (`prompts.RAG_ANSWER_SYSTEM`) is constrained to retrieved transcript context only, must produce `[Source N]` inline citations, and must respond *"I don't have information about that"* when evidence is absent. Enforced in the prompt and measured by the eval harness: faithfulness 94%. The LLM never hallucinates an owner or a decision the transcripts don't support.

**Conservative speaker naming.** Rule-based pass first (deterministic self-introduction parsing: "Hi, I'm Alice"), LLM fallback only for unresolved speakers with explicit text evidence. Names are validated against a stopword + word-shape filter (1–3 alphabetic tokens, uppercase-first, no common English words) and deduplicated — if the LLM assigns the same name to multiple speaker IDs, all are dropped. The product fails worse if it puts a real name on the wrong speaker than if it leaves `SPEAKER_03`.

**Speaker-turn-aware chunking with paragraph snapping.** Markdown transcripts have each speaker turn as its own paragraph. The chunker splits on `\n\n` boundaries, and after overlap, chunk starts snap forward to the next paragraph or sentence break — so retrieved sources displayed in the citations panel never start mid-word or mid-sentence. Visible UX win when the user expands "Show 5 sources" on an answer.

**Two-stage cleanup of diarization artifacts.** Rule-based segment repair (`services/segment_repairs.py`) fixes broken intros and leading-fragment misattribution before LLM speaker-naming runs. The repair rules target the two most common pyannote failure modes documented in the eval — cheap, predictable, easy to inspect. Doesn't generalize as broadly as a learned correction layer would, but the failure modes it covers are the most common.

**Batch-first with Celery + polling.** ASR + diarization + analytics on a 30-minute meeting take minutes, not milliseconds. Sync would lock the API; WebSocket streaming adds complexity for no UX win at this scale. The frontend polls every 3 s during processing and 30 s for the meetings list. The tradeoff is documented, not hidden.

**Swap-friendly ML interfaces.** ASR and diarization sit behind abstract interfaces in `core/interfaces.py` so they can be benchmarked and swapped without pipeline changes. The current concrete implementations (Groq Whisper, pyannote 3.1) are one of several plausible combinations — the eval harness is the contract.

---

## Design Decisions

**Hybrid retrieval (RRF) over pure dense.** Transcript markdown contains exact terms — names, ticket IDs, project codenames, jargon — that dense-only search misses under paraphrase. BM25 handles keyword precision; the dense model handles intent. Qdrant runs both in a single prefetch query with built-in RRF fusion — no learned weighting required, no manual reranking step.

**Local embeddings (Ollama `nomic-embed-text`) over a hosted API.** No PII leaves the machine, no per-token cost, no rate limit during indexing. Slower than hosted (~100 ms per embed vs. ~20 ms), but the indexing pipeline runs in a Celery worker and the latency is hidden behind status polling.

**Markdown as the canonical transcript format.** `.md` files are inspectable in any editor, diff cleanly in git, and preserve speaker turns as natural paragraph boundaries. The chunker leverages those boundaries directly — no custom parser required. JSON, SRT, and TXT exports are derived from the same canonical state, so they can never disagree.

**Custom name validator over trusting the LLM.** The speaker-naming LLM occasionally hallucinates assignees from transcript phrases ("Going To Update", "In Line"). A post-processing validator (`speaker_labels._looks_like_person_name`) enforces: 1–3 tokens, alphabetic + uppercase-first, no common English stopwords / modals / fillers. The same validator is reused to scrub action-item assignees and decision stakeholders. Belt and suspenders against LLM drift.

**Celery + Postgres over an in-process job queue.** Persisted job state means a worker crash mid-meeting doesn't lose the upload — a fresh worker resumes from the database checkpoint. One extra dependency (Redis) for a property the API would otherwise have to fake.

**Next.js 14 over server-rendered FastAPI templates.** Cleaner separation between the Python pipeline and the TypeScript UX. The API stays JSON-only and headless. The original FastAPI static UI is still served at `/` as a backend-only smoke test (so the pipeline can be exercised without the frontend running at all).

---

## Tech Stack

| Component | Technology | Why, not the alternative |
|---|---|---|
| ASR | Groq `whisper-large-v3` | Over local WhisperX: hosted inference is 10× faster for batch use with no GPU dependency. Less decoding control, but AMI eval shows the quality is acceptable (25% raw WER on multi-speaker mix-headset audio) |
| Diarization | `pyannote/speaker-diarization-3.1` | Over WhisperX's built-in diarization: pyannote 3.1 is the strongest open baseline on AMI. Trade is HF license gating + GPU dependency for this single stage |
| Vector store | Qdrant 1.17 | Over pgvector: Qdrant runs dense + sparse in a single prefetch query with built-in RRF fusion; pgvector requires two separate queries and manual reranking. Over Chroma: no native BM25 support |
| Dense embeddings | Ollama `nomic-embed-text` (768-dim) | Over hosted (OpenAI ada-002, Cohere): no PII leaves the machine, no per-token cost, no quota during eval reruns. ~100 ms per embed vs. ~20 ms hosted — hidden behind the indexing worker |
| Sparse encoder | Qdrant `bm25` | Required for hybrid: transcripts contain exact terms (names, IDs, jargon) dense search misses under paraphrase |
| Analytics LLM | Groq `llama-3.1-8b-instant` | Over a 70B model for structured extraction: 8B is fast enough to iterate prompts, and bounded JSON extraction doesn't need 70B-class reasoning |
| Answer LLM | Groq `llama-3.3-70b-versatile` | Over the 8B: synthesizing a grounded answer across 5 retrieved chunks needs the larger model. Eval shows the quality delta is real |
| Eval judge | OpenAI `gpt-4.1-mini` via RAGAS | Over self-judge with the answer model: independent judge prevents the system from grading its own work |
| API | FastAPI + Pydantic | Typed JSON, async-friendly, painless multipart upload |
| Background jobs | Celery + Redis | Over in-process queue: persisted job state survives worker restarts mid-meeting |
| Relational store | PostgreSQL 16 | Durable meeting metadata, transcripts, analytics, job state |
| Frontend | Next.js 14 + Tailwind | Over single-file React app: file-based routing is overkill here but dev ergonomics + Tailwind v3 design tokens are worth it |
| Package manager | `uv` | Over pip: 10× faster installs, lockfile-first, integrated venv management |

---

## Two Query Modes

### `POST /query` — cross-meeting (primary surface)

Hybrid retrieval over the entire meeting store, restricted by nothing. The right-pane chat in the UI. Answers are grounded in chunks drawn from any subset of meetings.

```bash
curl -X POST http://127.0.0.1:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What did we decide about performance issues last quarter?","top_k":5}'
```

### `POST /meetings/{id}/query` — single-meeting (drill-down)

Same pipeline, Qdrant payload filter restricts retrieval to one meeting. Used by the Ask tab on a meeting detail page for focused review.

Both modes return the same shape: `{"answer", "sources": [{meeting_title, content, score, speakers, start_time, end_time}], "processing_time_ms"}`.

The value compounds the more meetings you store: cross-meeting retrieval has more context to fuse, and the same query that returns nothing useful from one meeting returns a real answer once five related meetings exist.

---

## Privacy & Data

- All audio processing is local. Only ASR (Groq) and analytics + answer generation (Groq) hit hosted services. Transcripts and embeddings stay on the machine.
- Embeddings run on local Ollama; vectors and full transcript text live in the local Qdrant instance.
- Retention is configurable: `MIE_DEFAULT_RETENTION_DAYS=90` (default). `POST /privacy/cleanup-expired` deletes meetings past their deadline.
- Raw audio can be purged after processing via `POST /meetings/{id}/privacy/purge-raw-audio` while keeping transcripts and analytics.
- This repo is a runnable prototype, not a fully compliant enterprise deployment. Auth, encryption-at-rest, audit logging, and consent capture are explicitly out of scope for this version — see [Known Limitations](#known-limitations).

---

## Setup

### Prerequisites

> **TL;DR.** All infrastructure (Postgres, Redis, Qdrant) runs in Docker. The only host-level dependencies are Docker, `uv`, Node 18, and Ollama — plus a Groq API key and Hugging Face token for the gated diarization model.

- Python 3.12, [`uv`](https://docs.astral.sh/uv/)
- Node.js ≥ 18, `npm`
- Docker + Docker Compose (Postgres / Redis / Qdrant)
- `ffmpeg` + `ffprobe` (audio normalization)
- Ollama (local dense embeddings)
- Hugging Face account — accept `pyannote/speaker-diarization-3.1` gating; provide `HF_TOKEN`
- Groq API key (Whisper ASR + analytics + answer LLM)
- OpenAI API key (RAG eval judge only — optional if you don't run eval)

> ⚠️ **Hugging Face gating required.** Accept the model license at [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) before the first run. Without this, the pipeline fails with a 401.

### Install
```bash
git clone https://github.com/k-arvanitis/echolog && cd echolog
uv sync --extra dev
cd frontend && npm install && cd ..
cp .env.example .env && $EDITOR .env
ollama pull nomic-embed-text
```

---

## Quick Start

```bash
make stack     # Postgres + Redis + Qdrant + worker + api + ui in tmux (recommended)
# — or run them in separate terminals:
make infra-up  # Postgres + Redis + Qdrant
make api       # FastAPI on :8001
make worker    # Celery worker
make ui        # Next.js on :3003

make test      # 31 tests, all external services mocked
make lint      # ruff check + ruff format --check
make eval-ami  # AMI WER eval (English forced)
make eval-rag  # RAG QA eval over the 50-question fixture
```

Open `http://localhost:3003` for the UI; interactive API docs at `http://localhost:8001/docs`.

---

## Example Questions

The cross-meeting Ask panel handles questions across your meeting history; the per-meeting Ask tab restricts retrieval to one meeting.

**Per-meeting**
```
What action items were assigned and to whom?
What was decided about the roadmap?
Why does the team want to revamp the kickoff format?
```

**Cross-meeting**
```
What did we decide about parking?
When did we first discuss the training issue?
Which meetings mentioned customer churn?
What action items were assigned to Jason in the last quarter?
Did we already agree on the rollout plan?
```

---

## Configuration

All env vars in one place: `src/meeting_intelligence_engine/config.py`. Frontend reads `NEXT_PUBLIC_API_URL` from `frontend/.env.local`.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** ASR + analytics + answer LLM |
| `OPENAI_API_KEY` | — | RAG eval judge only |
| `HF_TOKEN` | — | **Required.** Pyannote model download |
| `MIE_API_PORT` | `8001` | FastAPI port |
| `MIE_API_KEY` | — | If set, side-effecting / paid-API endpoints require `X-API-Key` header. Blank = open local dev |
| `MIE_CORS_ALLOW_ORIGINS` | `["http://localhost:3003","http://127.0.0.1:3003"]` | JSON list of allowed frontend origins |
| `MIE_ASR_MODEL_NAME` | `whisper-large-v3` | Groq Whisper model |
| `MIE_ASR_CHUNK_SECONDS` | `600` | Max seconds per ASR chunk |
| `MIE_DIARIZATION_MODEL_NAME` | `pyannote/speaker-diarization-3.1` | Diarization model |
| `MIE_LANGUAGE` | `en` | Force ASR language; `null` to auto-detect |
| `MIE_ANALYTICS_MODEL_NAME` | `llama-3.1-8b-instant` | Structured extraction model |
| `MIE_RAG_MODEL_NAME` | `llama-3.3-70b-versatile` | Answer generation model |
| `MIE_MAX_UPLOAD_MB` | `500` | Upload size cap |
| `MIE_MAX_DURATION_SECONDS` | `14400` | Reject audio longer than 4 hours |
| `MIE_DEFAULT_RETENTION_DAYS` | `90` | Default retention; `null` to disable |
| `MIE_DELETE_RAW_AUDIO_AFTER_PROCESSING` | `false` | Auto-purge raw audio once transcripts exist |
| `DATABASE_URL` | `postgresql+psycopg://mie:mie@localhost:55432/mie` | Postgres DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker |
| `QDRANT_URL` | `http://localhost:6333` | Vector store |
| `QDRANT_COLLECTION` | `meeting_transcript_md` | Collection name |
| `DENSE_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `DENSE_DIM` | `768` | Embedding dimensionality |
| `SPARSE_MODEL` | `Qdrant/bm25` | Sparse encoder for hybrid retrieval |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8001` | Frontend → backend URL (set in `frontend/.env.local`) |

See `.env.example` for the full list with placeholder values.

---

## Evaluation

### ASR — AMI Meeting Corpus (Mix-Headset)

Run on **30 / 30** AMI mix-headset meetings — multi-speaker, overlap, interruptions, conversational speech. The closest open benchmark to Echolog's real input.

| Metric | Result |
|---|---|
| mean raw WER | **24.99%** |
| mean filler-light WER | **20.65%** |
| failed meetings | **0 / 30** |
| best (`ES2016b`) | 19.22% raw / 15.20% filler-light |
| worst (`ES2005a`) | 35.34% raw / 31.32% filler-light |

`filler-light WER` strips obvious fillers (`uh`, `um`, `mm`) and immediate duplicates. Reported as a secondary metric because filler-heavy AMI annotations inflate raw WER without reflecting downstream usability.

These numbers are higher than clean single-speaker benchmarks because this is **mixed multi-speaker headset audio**, not isolated speech. Even at 25% raw WER, the transcripts preserve enough signal for retrieval and analytics extraction — which is what the RAG eval measures next.

```bash
make eval-ami
```

### RAG — fixed QA set, RAGAS judge

Run on a **50-question, 5-meeting** QA fixture (`eval/rag_qa/`), judged by `gpt-4.1-mini` via RAGAS.

| Metric | Score |
|---|---|
| faithfulness | **94.0%** |
| answer relevancy \* | 74.3% |
| context precision | 78.2% |
| context recall | 83.0% |

> \* Answer relevancy is bounded by meeting conversations being unstructured — questions spanning multiple meetings return partial matches by design. Echolog is tuned to prefer narrow, correct retrieval over broad, noisy retrieval.

**Reading the scores.** Faithfulness (94%) is the primary signal: Echolog answers from retrieved evidence and refuses when it can't, rather than hallucinating decisions or owners.

All prompts live in `prompts.py` behind a `PROMPT_VERSION`; eval output records it (and runtime logs do too), so a quality number is always tied to the prompt that produced it.

```bash
make eval-rag
```

---

## Failure Modes

| Failure | Behaviour |
|---|---|
| Diarization splits a sentence across two speakers | `services/segment_repairs.py` — extend the rule set; check the broken-intro and leading-fragment patterns |
| Speaker stays as `SPEAKER_03` | No self-introduction in audio. `services/speaker_labels.py` LLM fallback only fires with clear textual evidence; insert manual labels via DB if needed |
| LLM returns malformed analytics JSON | `services/analytics.py` sanitize-and-coerce step runs automatically; topic-only fallback fires if the generic pass returns no topics |
| Cross-meeting query returns nothing | Index never built or Ollama unreachable. Run `uv run mie-ingest-md --recreate data/meetings`; check the Qdrant collection exists |
| Frontend can't reach backend | Toast: *"Backend offline — start the API server (`make api`)"*. API not running, or `MIE_CORS_ALLOW_ORIGINS` doesn't include the frontend origin |
| Transcript is wrong language | Whisper auto-detected the wrong locale. Set `MIE_LANGUAGE=en` and re-process |
| Pyannote 401 on first run | `HF_TOKEN` missing or hasn't accepted `pyannote/speaker-diarization-3.1` license |

---

## Tests

```bash
make test
```

**31 tests**, no external services required — Groq, Qdrant, Ollama, ffmpeg, and the FastAPI surface are all mocked. CI runs `ruff check`, `ruff format --check`, and `pytest` on every push.

| Path | What it tests |
|---|---|
| `tests/unit/test_pipeline.py` | Chunking, segment repair, analytics sanitizer, speaker-label validator, name-validator edge cases |
| `tests/unit/test_eval.py` | WER scoring + RAG metric helpers |
| `tests/integration/test_api.py` | FastAPI endpoints — upload, query, delete, retention, privacy purge |
| `tests/conftest.py` | `make_app` fixture (fresh app + temp SQLite per test) |

---

## API

Interactive docs (OpenAPI / Swagger): `http://localhost:8001/docs`.

```text
GET    /health
GET    /                              ← FastAPI static UI (smoke testing)

POST   /meetings/upload               ← multipart {file, title}                  · guarded
GET    /meetings                      ← list
GET    /meetings/{id}
DELETE /meetings/{id}                                                            · guarded
GET    /meetings/{id}/transcript
GET    /meetings/{id}/segments
GET    /meetings/{id}/speaker-labels
GET    /meetings/{id}/artifacts/{json|txt|srt|md}
GET    /meetings/{id}/action-items
GET    /meetings/{id}/decisions
GET    /meetings/{id}/topics

POST   /meetings/{id}/query           ← single-meeting RAG                        · guarded
POST   /query                         ← cross-meeting RAG                         · guarded

POST   /meetings/{id}/retention                ← {retention_days}                 · guarded
POST   /meetings/{id}/privacy/purge-raw-audio                                     · guarded
POST   /privacy/cleanup-expired                                                   · guarded
GET    /privacy/settings
```

`· guarded` endpoints require an `X-API-Key: <MIE_API_KEY>` header **when `MIE_API_KEY` is set** — they cause side effects or call paid APIs. With no key configured (local-dev default) the guard is a no-op.

Manual full rebuild of the markdown index:

```bash
uv run mie-ingest-md --recreate data/meetings
```

---

## Project Structure

```
echolog/
├── src/meeting_intelligence_engine/
│   ├── api/                   # FastAPI: main.py (app factory + lifespan + error handler),
│   │                          #   routes/ (meetings, query, privacy, system),
│   │                          #   deps.py (DI: session, API-key guard), schemas.py
│   ├── api/static/            # Built-in static UI (smoke testing)
│   ├── workers/               # Celery tasks: transcribe, analytics, indexing
│   ├── services/              # Pipeline stages: meetings, analytics,
│   │                          #   speaker labels, segment repairs
│   ├── rag/                   # Chunking, embeddings, ingestion, query
│   ├── eval/                  # AMI WER + RAG eval harnesses
│   ├── core/                  # Pydantic schemas, abstract interfaces
│   ├── implementations/       # Concrete ASR + diarization adapters
│   ├── audio.py / db.py / models.py / config.py / cli.py / exporters.py / prompts.py
│   └── __init__.py
├── frontend/                  # Next.js 14 app router
│   ├── app/                   # layout.tsx, page.tsx, globals.css
│   ├── components/            # Sidebar, MeetingDetail, *Tab, CrossMeetingPanel
│   ├── lib/api.ts             # Typed fetch + backend → frontend shape mapping
│   └── lib/toast.tsx          # Lightweight toast system
├── tests/
│   ├── unit/                  # Pure logic: chunking, alignment, eval scoring, analytics
│   ├── integration/           # FastAPI app + DB + ffmpeg, all external services mocked
│   └── conftest.py            # `make_app` fixture (fresh app against temp SQLite)
├── eval/
│   ├── rag_qa/                # 50-question RAG fixture
│   └── results/               # Eval outputs — published headline JSONs tracked
├── assets/                    # demo.mp4 + analytics.png + ask.png for the README
├── .github/workflows/ci.yml   # ruff check + ruff format --check + pytest on every push
├── Dockerfile / .dockerignore # Multi-stage runtime image (non-root) for API + worker
├── docker-compose.yml         # Postgres / Redis / Qdrant
├── Makefile                   # infra / api / worker / ui / stack / test / lint / docker-build / eval-*
├── pyproject.toml             # uv-managed, pinned Python ≥ 3.12, ruff config inline
└── .env.example
```

---

## Known Limitations

- **Single-tenant prototype.** Multi-tenant auth and workspace isolation are out of scope for this version. The optional `MIE_API_KEY` header guard is a coarse stopgap on side-effecting / paid-API endpoints; the Next.js UI doesn't send it, so enabling it currently locks the UI out of upload/query/delete.
- **No live capture.** Batch upload only. Zoom / Meet / Teams bot integration is in the spec but not wired up.
- **Diarization fragility.** Overlapping speech, remote-call compression, and inconsistent mic quality degrade segmentation. Repair heuristics catch the most common cases but are not a learned correction layer.
- **Speaker naming requires self-introduction.** If no one says *"this is Alice"* on the call, the rule pass leaves `SPEAKER_03` and the LLM fallback won't fire without clear textual evidence. Nicknames and indirect references aren't normalized.
- **Filler-heavy AMI annotations.** Raw WER is harsher than what the transcripts actually look like to a reader. Filler-light WER reported as a secondary metric for that reason.
- **No schema migrations.** `db.py` runs a small idempotent column-add shim on startup; Alembic is the next step.
- **Object storage / production deployment not packaged.** Repo is a runnable prototype on a single machine. HTTPS, reverse proxy, encryption at rest, KMS-managed keys, formal audit logging, participant consent capture, and PII redaction are deliberate next-product concerns — not hidden gaps.

---

## Contact

- GitHub: https://github.com/k-arvanitis
- LinkedIn: https://www.linkedin.com/in/konstantinos-arvanitis-0248b3246/
- Email: konstantinos.arvanitis@outlook.com
