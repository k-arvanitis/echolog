# Recall — Meeting Intelligence Engine

[![CI](https://github.com/k-arvanitis/recall-mie/actions/workflows/ci.yml/badge.svg)](https://github.com/k-arvanitis/recall-mie/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js%2014-000000?style=for-the-badge&logo=next.js&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-FF4136?style=for-the-badge&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9?style=for-the-badge)

> Turn company meetings into a searchable memory layer.

Upload meeting audio → get speaker-attributed transcripts, structured action items and decisions, and the ability to ask questions across **every meeting you've ever recorded**, not just one transcript at a time.

The product idea is intentionally narrow:

- every meeting gets saved;
- every meeting becomes queryable;
- the company builds an internal memory of what was discussed, decided, assigned, and repeated.

Per-meeting query exists as a drill-down. The primary value is the **shared meeting store** and cross-corpus retrieval.

---

## Demo

> Screenshots and a video walkthrough will be added here.

The app is a three-pane shell:

- **Left**: meeting list with status badges (processing / ready / failed) and an upload button.
- **Center**: tabbed meeting detail — Overview, Transcript, Analytics, Ask.
- **Right**: persistent cross-meeting chat that searches the entire corpus.

Example questions the app handles end to end:

- "What did we decide about parking?"
- "When did we first discuss the training issue?"
- "Which meetings mentioned customer churn?"
- "What action items were assigned to Jason in the last quarter?"
- "Did we already agree on the rollout plan?"

---

## Why this is different

Most meeting-intelligence demos stop at "transcribe one file and summarize it." Recall is built around the assumption that meeting value compounds over time:

- **Cross-corpus retrieval is the primary surface**, not an afterthought. Hybrid (dense + BM25, fused with RRF) over transcript markdown.
- **Grounded answers, not summaries.** The LLM is constrained to the retrieved transcript context with explicit `[Source N]` citations; it must say "I don't have information about that" when evidence is missing. This is enforced by prompt and validated by the eval harness (faithfulness 94%).
- **Real evals on real meeting audio.** WER measured on 30/30 AMI Meeting Corpus mix-headset meetings; RAG metrics measured on a fixed 50-question, 5-meeting QA set with an LLM-as-judge (GPT-4.1-mini via RAGAS).
- **Two-stage cleanup of diarization artifacts.** Rule-based segment repair fixes broken intros and split sentences before LLM speaker-naming runs as a fallback. Naming is conservative by design — it would rather leave `SPEAKER_03` than guess.
- **Batch-first by design.** Long ASR / diarization / indexing runs sit in Celery workers behind the API; the UI polls until ready. The tradeoff is documented, not hidden.
- **Swap-friendly ML interfaces.** ASR and diarization sit behind abstract interfaces in `core/interfaces.py` so they can be benchmarked and swapped without pipeline changes.

---

## Architecture

```text
┌──────────────┐         ┌────────────────┐
│  Next.js UI  │◄──────► │   FastAPI      │
│  (port 3000) │  HTTP   │   (port 8001)  │
└──────────────┘         └───────┬────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
   ┌─────────┐            ┌────────────┐          ┌─────────────┐
   │ Postgres│            │   Redis    │          │   Qdrant    │
   │ (state) │            │  (broker)  │          │ (retrieval) │
   └─────────┘            └─────┬──────┘          └──────▲──────┘
                                │                        │
                                ▼                        │
                       ┌──────────────────┐              │
                       │  Celery worker   │              │
                       │                  │              │
                       │  • transcribe    │              │
                       │  • analytics     │              │
                       │  • indexing  ────┼──► Ollama ───┘
                       └──────────────────┘    embeddings
                              │
                              ├──► Groq Whisper (ASR)
                              ├──► pyannote (diarization)
                              └──► Groq chat (analytics + answer)
```

End-to-end flow:

```text
upload audio
  → validate + normalize (ffprobe / ffmpeg)
  → ASR (Groq Whisper)
  → diarization (pyannote)
  → alignment + segment repair
  → speaker label resolution (rules → LLM fallback)
  → transcript exports (json / txt / srt / md)
  → analytics extraction (action items, decisions, topics)
  → markdown indexing (Ollama embeddings → Qdrant)
  → cross-meeting query (RRF fusion → grounded answer + citations)
```

---

## Key Engineering Decisions

| Decision | Options considered | Choice | Why / tradeoff |
|---|---|---|---|
| **Retrieval strategy** | Pure dense, pure BM25, dense + sparse with RRF, agentic RAG | Dense (`nomic-embed-text`) + sparse (Qdrant BM25) fused with RRF, single retrieve-then-answer step | Corpus is narrow and uniform (transcript markdown). RRF gives the lexical recall of BM25 + the semantic recall of dense without weight tuning. Skipped agentic RAG: no tool use needed, easier to evaluate, harder to hide reasoning errors behind agent loops. |
| **Chunking** | Fixed-size, sentence, semantic, speaker-turn aware | Markdown-section chunks tagged with speakers and time spans | Inspectable in raw form, preserves turn boundaries that the LLM uses to attribute citations. Tradeoff: chunks vary in length, occasionally truncating long discussions. |
| **Speaker attribution** | LLM-only naming, rules-only naming, hybrid | Rules first (deterministic self-introduction parsing), LLM fallback only for unresolved speakers | Conservative naming: prefers `SPEAKER_03` over a wrong guess. The product fails worse if it puts a real name on the wrong speaker than if it leaves an anonymous label. |
| **Segment repair** | Trust diarizer output, learned correction, rule-based heuristics | Rule-based heuristics for two specific failure modes (broken intros, leading-fragment misattribution) | Cheap, predictable, easy to inspect. Doesn't generalize as broadly as a learned model would, but the failure modes it targets are the most common ones in our eval. |
| **Async vs sync pipeline** | Sync API, async with Celery, streaming with WebSockets | Celery + Redis with frontend polling | ASR + diarization + analytics on a 30-minute meeting takes minutes, not milliseconds. Sync would lock the API; streaming adds complexity for no UX win at this scale. |
| **Frontend** | Server-rendered FastAPI templates, single-page Next.js, separate React app behind FastAPI | Next.js 14 App Router, talking to FastAPI over CORS | Cleaner separation between pipeline (Python) and UX (TypeScript). Lets the API stay JSON-only and headless. The original FastAPI static UI is still served at `/` for backend-only smoke testing. |
| **Status enum mapping** | Mirror backend states in UI, collapse to UI-friendly states | Backend keeps `pending/processing/completed/failed`, frontend collapses to `processing/ready/failed` | Backend states are useful for debugging (`pending` ≠ `processing`) but the UI only needs three: still working, done, broken. |
| **Privacy controls** | None / opt-in / always-on | Optional retention deadlines, optional raw-audio purge after processing | Audio is the most sensitive artifact; transcripts are derived. Lets the operator delete raw audio while keeping searchable text. |

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| API | FastAPI + Pydantic | Typed JSON APIs, async-friendly, painless file upload. |
| Frontend | Next.js 14 (App Router), Tailwind CSS, TypeScript | Standard modern frontend stack, three-pane shell with no router needed. |
| Background jobs | Celery + Redis | Long-running ASR / indexing should not block the API. |
| Relational store | PostgreSQL 16 | Durable meeting metadata, transcripts, analytics, job state. |
| Vector store | Qdrant 1.17 | Hybrid (dense + sparse) retrieval with RRF fusion built in. Easy local deploy. |
| Embeddings | Ollama `nomic-embed-text` (768-dim) | Fully local dense embeddings. Tradeoff: slower than hosted, but no PII leaves the machine. |
| ASR | Groq `whisper-large-v3` | Strong Whisper baseline, no local serving burden. Tradeoff: less decoding control than a local WhisperX stack. |
| Diarization | `pyannote/speaker-diarization-3.1` | Strong open diarization baseline. Tradeoff: HF gating, GPU dependency. |
| Analytics + answer generation | Groq `llama-3.1-8b-instant` (analytics), `llama-3.3-70b-versatile` (answer) | Fast, structured-JSON friendly, cheap to iterate on prompts. |
| Eval judge | OpenAI `gpt-4.1-mini` via RAGAS | Independent judge for faithfulness / context precision / context recall / answer relevancy. |
| Package manager | `uv` | Fast, reproducible Python installs; `uv.lock` checked in. |

---

## Evaluation

### ASR — AMI Meeting Corpus (Mix-Headset)

Run on **30 / 30** meetings in the AMI mix-headset configuration — multi-speaker, overlap, interruptions, conversational speech. This is the closest open benchmark to the product's real input shape.

| Metric | Result |
|---|---|
| mean raw WER | **24.99%** |
| mean filler-light WER | **20.65%** |
| failed meetings | **0 / 30** |
| best meeting (`ES2016b`) | 19.22% raw WER, 15.20% filler-light |
| worst meeting (`ES2005a`) | 35.34% raw WER, 31.32% filler-light |

`filler-light WER` strips obvious fillers (`uh`, `um`, `mm`) and immediate duplicates before scoring. Reported as a secondary metric because filler-heavy manual annotations of conversational speech inflate raw WER without reflecting downstream usability.

These numbers are higher than clean single-speaker benchmarks because **this is mixed multi-speaker audio**, not isolated headset speech. Even at 25% raw WER, the resulting transcripts preserve enough signal for retrieval, action extraction, and cross-meeting search — which is what the eval harness measures next.

Run it:

```bash
make eval-ami
```

### RAG — fixed QA set, RAGAS judge

Run on a **50-question, 5-meeting** QA fixture in `eval/rag_qa/`, judged by `gpt-4.1-mini` via RAGAS.

| Metric | Score |
|---|---|
| faithfulness | **94.0%** |
| answer relevancy | 74.3% |
| context precision | 78.2% |
| context recall | 83.0% |

The headline number is **faithfulness** — the system answers from retrieved evidence and refuses when it can't, instead of confidently inventing decisions or owners. The retrieval config is intentionally tuned toward cleaner evidence (better precision, slightly worse recall) because for a meeting-memory product, narrow correct retrieval beats noisy broad retrieval.

Run it:

```bash
make eval-rag
```

---

## Privacy & Data

- All raw audio is processed locally; only ASR (Groq) and analytics/answer generation (Groq) are hosted services. Transcripts and embeddings stay on the machine.
- Embeddings are computed by **local** Ollama; vectors and full transcript text live in the local Qdrant instance.
- Retention is configurable: `MIE_DEFAULT_RETENTION_DAYS=90` (default). `POST /privacy/cleanup-expired` deletes meetings past their retention deadline.
- Raw audio can be purged after processing via `POST /meetings/{id}/privacy/purge-raw-audio` while keeping transcripts and analytics.
- This repo is a strong engineering prototype, not a fully compliant enterprise deployment. Auth, encryption-at-rest, audit logging, and consent capture are explicitly out of scope for this version (see [Out of Scope](#out-of-scope)).

---

## Quickstart

```bash
# 1. clone + install Python deps
git clone https://github.com/k-arvanitis/recall-mie.git && cd recall-mie
uv sync --extra dev

# 2. install frontend deps
cd frontend && npm install && cd ..

# 3. configure secrets (GROQ_API_KEY, OPENAI_API_KEY, HF_TOKEN)
cp .env.example .env && $EDITOR .env

# 4. start Postgres / Redis / Qdrant + pull local embedding model
make infra-up
ollama pull nomic-embed-text

# 5. run worker, API, and frontend in a tmux session
make stack
tmux attach -t mie_stack
```

Open `http://localhost:3000` for the Recall UI.
The FastAPI backend lives at `http://localhost:8001` (Swagger docs at `/docs`).

---

## Prerequisites

| Tool | Minimum version | Purpose |
|---|---|---|
| Python | 3.12 | Backend runtime |
| `uv` | latest | Python package management |
| Node.js | 18 | Frontend runtime |
| `npm` | 9+ | Frontend package management |
| Docker + Docker Compose | latest | Postgres / Redis / Qdrant |
| `ffmpeg` + `ffprobe` | 4.x | Audio normalization |
| Ollama | latest | Local dense embeddings |
| Hugging Face account | — | Accept `pyannote/speaker-diarization-3.1` gating; provide `HF_TOKEN` |
| Groq API key | — | Whisper ASR + analytics + answer LLM |
| OpenAI API key | — | RAG eval judge only (optional if you don't run eval) |

---

## Configuration

All env vars in one place: `src/meeting_intelligence_engine/config.py`. Frontend reads `NEXT_PUBLIC_API_URL` from `frontend/.env.local`.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** ASR + analytics + answer LLM. |
| `OPENAI_API_KEY` | — | RAG eval judge. Not needed at runtime. |
| `HF_TOKEN` | — | **Required.** Pyannote model download. |
| `MIE_API_PORT` | `8001` | FastAPI port. |
| `MIE_CORS_ALLOW_ORIGINS` | `["http://localhost:3000","http://127.0.0.1:3000"]` | JSON list of allowed frontend origins. |
| `MIE_ASR_MODEL_NAME` | `whisper-large-v3` | Groq Whisper model. |
| `MIE_ASR_CHUNK_SECONDS` | `600` | Max seconds per ASR chunk. |
| `MIE_DIARIZATION_MODEL_NAME` | `pyannote/speaker-diarization-3.1` | Diarization model. |
| `MIE_LANGUAGE` | `en` | Force ASR language; `null` to auto-detect. |
| `MIE_ANALYTICS_MODEL_NAME` | `llama-3.1-8b-instant` | Structured extraction model. |
| `MIE_RAG_MODEL_NAME` | `llama-3.3-70b-versatile` | Answer generation model. |
| `MIE_MAX_UPLOAD_MB` | `500` | Upload size cap. |
| `MIE_MAX_DURATION_SECONDS` | `14400` | Reject audio longer than 4 hours. |
| `MIE_DEFAULT_RETENTION_DAYS` | `90` | Default retention; `null` to disable. |
| `MIE_DELETE_RAW_AUDIO_AFTER_PROCESSING` | `false` | Auto-purge raw audio once transcripts exist. |
| `DATABASE_URL` | `postgresql+psycopg://mie:mie@localhost:55432/mie` | Postgres DSN. |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker. |
| `QDRANT_URL` | `http://localhost:6333` | Vector store. |
| `QDRANT_COLLECTION` | `meeting_transcript_md` | Collection name. |
| `DENSE_MODEL` | `nomic-embed-text` | Ollama embedding model. |
| `DENSE_DIM` | `768` | Embedding dimensionality. |
| `SPARSE_MODEL` | `Qdrant/bm25` | Sparse encoder for hybrid retrieval. |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8001` | Frontend → backend URL (set in `frontend/.env.local`). |

See `.env.example` for the full list with safe placeholder values.

---

## Project Structure

```text
recall-mie/
├── src/meeting_intelligence_engine/
│   ├── api/main.py            # FastAPI app (CORS, endpoints, lifespan)
│   ├── api/static/            # Built-in static UI (smoke testing)
│   ├── workers/               # Celery tasks: transcribe, analytics, indexing
│   ├── services/              # Pipeline stages: meetings, analytics,
│   │                          #   speaker labels, segment repairs
│   ├── rag/                   # Chunking, embeddings, ingestion, query
│   ├── eval/                  # AMI WER + RAG eval harnesses
│   ├── core/                  # Pydantic schemas, abstract interfaces
│   ├── implementations/       # Concrete ASR + diarization adapters
│   ├── audio.py / db.py / models.py / config.py / cli.py / exporters.py
│   └── __init__.py
├── frontend/                  # Next.js 14 app router
│   ├── app/                   # layout.tsx, page.tsx, globals.css
│   ├── components/            # Sidebar, MeetingDetail, *Tab, CrossMeetingPanel
│   ├── lib/api.ts             # Typed fetch + backend → frontend shape mapping
│   └── lib/toast.tsx          # Lightweight toast system
├── tests/                     # 29 tests, all external services mocked
├── eval/
│   ├── rag_qa/                # 50-question RAG fixture
│   └── results/               # Eval outputs (gitignored)
├── .github/workflows/ci.yml   # Ruff + pytest on every push
├── docker-compose.yml         # Postgres / Redis / Qdrant
├── Makefile                   # infra / api / worker / frontend / stack / test / lint / eval-*
├── pyproject.toml             # uv-managed, pinned Python ≥ 3.12
└── .env.example
```

---

## Two Query Modes

1. **Cross-meeting query** — `POST /query`. Hybrid retrieval over the entire meeting store. The right-pane chat in the UI. Primary product surface.
2. **Single-meeting query** — `POST /meetings/{id}/query`. Same pipeline, restricted to one meeting via Qdrant payload filter. Drill-down for inspection or focused review.

In practice, the value compounds the more meetings you store, because cross-meeting retrieval has more context to work with.

---

## API

```text
GET    /health
GET    /                              ← FastAPI static UI (smoke testing)

POST   /meetings/upload               ← multipart {file, title}
GET    /meetings                      ← list
GET    /meetings/{id}
DELETE /meetings/{id}
GET    /meetings/{id}/transcript
GET    /meetings/{id}/segments
GET    /meetings/{id}/speaker-labels
GET    /meetings/{id}/artifacts/{json|txt|srt|md}
GET    /meetings/{id}/action-items
GET    /meetings/{id}/decisions
GET    /meetings/{id}/topics

POST   /meetings/{id}/query           ← single-meeting RAG
POST   /query                         ← cross-meeting RAG

POST   /meetings/{id}/retention                ← {retention_days}
POST   /meetings/{id}/privacy/purge-raw-audio
POST   /privacy/cleanup-expired
GET    /privacy/settings
```

Cross-meeting query example:

```bash
curl -X POST http://127.0.0.1:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What did we decide about performance?","top_k":5}'
```

Response shape:

```json
{
  "answer": "...",
  "sources": [
    {
      "meeting_title": "...",
      "meeting_id": "...",
      "content": "...",
      "score": 0.83,
      "speakers": ["Alice"],
      "start_time": 142.7,
      "end_time": 198.3
    }
  ],
  "processing_time_ms": 1820
}
```

Manual full rebuild of the markdown index:

```bash
uv run mie-ingest-md --recreate data/meetings data/md
```

---

## CLI

```bash
# transcribe a single file end to end
uv run meeting-transcribe \
  --input samples/Product-Team-Meeting.mp3 \
  --output-dir outputs

# evaluation
uv run mie-eval-ami --csv eval/results/ami.csv --json eval/results/ami.json
uv run mie-eval-rag --qa-file eval/rag_qa/all_meetings_qa.json --output eval/results/rag.json
```

---

## Tests

```bash
make test     # pytest, 29 tests, all external services mocked
make lint     # ruff
```

CI runs both on every push to `main` and every PR.

---

## Known Limitations

- **Single-tenant.** No auth, no workspace isolation. Anyone with API access can read every meeting.
- **No live capture.** Batch upload only; Zoom-bot integration is in the spec but not wired up.
- **Diarization fragility.** Overlapping speech, remote-call compression, and inconsistent mic quality degrade segmentation. Repair heuristics catch the most common cases but are not a learned correction layer.
- **Speaker naming requires self-introduction.** If no one says "this is Alice", the rule-based pass leaves `SPEAKER_03`. The LLM fallback only fires when there's clear textual evidence; nicknames and indirect references aren't normalized.
- **Filler-heavy AMI annotations.** Raw WER is harsher than what the transcripts actually look like to a reader. We report filler-light WER as a secondary metric for that reason.
- **Object storage / production deployment** not packaged. Repo is a runnable prototype on a single machine.

---

## Failure Modes

| What breaks | Symptom | Where to look |
|---|---|---|
| Diarization splits a sentence across two speakers | Transcript has fragments attributed to the wrong person | `services/segment_repairs.py` — extend the rule set; check for the broken-intro and leading-fragment patterns |
| Speaker stays as `SPEAKER_03` | No self-introduction in the audio | `services/speaker_labels.py` — LLM fallback only fires with clear textual evidence; inject manual labels via DB if needed |
| LLM returns malformed JSON for analytics | Empty action items / decisions for a meeting | `services/analytics.py` — sanitize-and-coerce step; topic-only fallback pass runs if the generic pass returns no topics |
| Cross-meeting query returns nothing | Index never built or Ollama unreachable | Check `MIE_RAG_ENABLED`, run `mie-ingest-md --recreate data/meetings data/md`, verify Qdrant collection exists |
| Frontend can't reach backend | Toast: "Backend offline — start the API server" | API not running, or `MIE_CORS_ALLOW_ORIGINS` doesn't include the frontend origin |
| Transcript is wrong language | Whisper auto-detected the wrong locale | Set `MIE_LANGUAGE=en` (or your target) and re-process |
| Pyannote download fails | 401 on first run | `HF_TOKEN` missing or hasn't accepted `pyannote/speaker-diarization-3.1` model card |

---

## Out of Scope

The current repo is a strong end-to-end prototype. The items below are deliberate next-product concerns, not hidden gaps:

- authentication and workspace isolation;
- HTTPS, reverse proxy, production deployment hardening;
- encryption at rest, KMS-managed keys, formal audit logging;
- participant consent capture and recording disclosure;
- PII redaction beyond manual retention controls;
- Zoom / Meet / Teams live-capture bots;
- object storage (S3 / MinIO) instead of local filesystem.

---

## Contact

- GitHub: [k-arvanitis](https://github.com/k-arvanitis)
- Email: konstantinos.arvanitis@outlook.com
