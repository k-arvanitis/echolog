# OWNERSHIP — explaining Recall cold

A study guide for walking through this project in an interview or review. Not user docs.
The goal: be able to draw the system, justify every choice, and know exactly where each
behaviour lives.

---

## 1. The 30-second pitch

> Recall turns a company's meeting audio into a searchable memory layer. Upload audio →
> you get a speaker-attributed transcript, extracted action items / decisions / topics, and
> a chat that answers questions **across every meeting in the corpus**, grounded in the
> retrieved transcript text with `[Source N]` citations. The cross-meeting search is the
> point — per-meeting Q&A is just a drill-down.

Why it's not a toy: it's batch-job-backed (Celery), it has real evals on real audio
(AMI corpus WER, RAGAS faithfulness on a fixed QA set), the ML stages sit behind swappable
interfaces, and the answer path is constrained-and-cited, not "summarize the transcript".

---

## 2. The mental model (draw this)

```
Next.js UI ──HTTP/JSON──> FastAPI ──> Postgres   (meeting + segment + analytics state)
                              │
                              ├──> Redis ──> Celery worker ──> Groq Whisper (ASR)
                              │                              ├─> pyannote (diarization)
                              │                              ├─> Groq chat (analytics + answer)
                              │                              └─> Ollama embeddings ─> Qdrant
                              └──> Qdrant   (hybrid dense+BM25 retrieval, RRF fusion)
```

- **FastAPI is headless and synchronous-fast.** It writes a `Meeting` row, drops a Celery
  task, and returns. Everything slow happens in the worker. The UI polls `GET /meetings/{id}`
  until `status` leaves `processing`.
- **Three Celery tasks, chained:** `transcribe → analytics → indexing`. Each retries with
  backoff; a permanent failure marks the meeting `failed` with an error message.
- **Two data stores on purpose:** Postgres is the source of truth for meeting state and
  transcript segments; Qdrant holds the chunked transcript *markdown* with dense + sparse
  vectors for retrieval. They're rebuildable from the transcript exports on disk.

---

## 3. The processing pipeline, stage by stage

`upload → validate/normalize → ASR → diarization → align + repair → speaker labels → exports → analytics → index`

1. **Validate + normalize** (`audio.py`) — `ffprobe` for duration/size limits, `ffmpeg` to a
   canonical wav. Rejects > `MIE_MAX_DURATION_SECONDS` / `MIE_MAX_UPLOAD_MB`.
2. **ASR** — `GroqWhisperASR` (`implementations/local_pipeline.py`), chunked at
   `MIE_ASR_CHUNK_SECONDS`. Behind the `ASR` interface in `core/interfaces.py`.
3. **Diarization** — `PyannoteDiarization`. If the model fails to load or run, the pipeline
   degrades to a single `SPEAKER_00` span instead of crashing (logged, recorded in metadata).
4. **Alignment** — `TimeOverlapAlignment` maps ASR segments onto diarization spans by time overlap.
5. **Segment repair** (`services/segment_repairs.py`) — rule-based fixes for two specific
   diarizer failure modes: broken intros and leading-fragment misattribution. Deliberately
   *not* a learned model — cheap, predictable, inspectable.
6. **Speaker label resolution** (`services/speaker_labels.py`) — deterministic
   self-introduction parsing first ("hi, this is Alice" → `SPEAKER_02 = Alice`); an LLM
   fallback runs *only* for still-unresolved speakers and *only* with clear textual evidence.
   Conservative by design: leaving `SPEAKER_03` beats putting the wrong name on a turn.
7. **Exports** (`exporters.py`) — json / txt / srt / md written to disk; the markdown is what
   gets indexed.
8. **Analytics** (`services/analytics.py`) — Groq `llama-3.1-8b-instant` extracts action items,
   decisions, topics as JSON. Output is sanitized/coerced; if the generic pass yields no topics
   a topic-only fallback pass runs. Malformed JSON → empty result, logged, not fatal.
9. **Indexing** (`rag/`) — markdown split into section chunks tagged with speakers + time
   spans; Ollama `nomic-embed-text` (768-dim) dense vectors + Qdrant BM25 sparse vectors;
   upserted into the `meeting_transcript_md` collection with a `meeting_id` payload.

---

## 4. The retrieval / answer path

`question → dense embed + sparse embed → Qdrant RRF fusion → top-k chunks → Groq llama-3.3 (constrained) → answer + citations`

- **Hybrid, fused with RRF.** Dense for semantics, BM25 for exact terms (names, project
  codenames). RRF (`FusionQuery` in Qdrant) needs no weight tuning — it ranks by reciprocal
  rank across both lists.
- **Single retrieve-then-answer step.** No agent loop. The corpus is narrow and uniform
  (transcript markdown), so iterative tool use buys nothing and makes the system harder to
  evaluate and easier to hide reasoning errors in.
- **The answer is constrained.** The system prompt (`prompts.RAG_ANSWER_SYSTEM`) forces the
  model to answer *only* from the provided chunks, cite `[Source N]`, and emit the exact
  "I don't have information about that…" string when evidence is missing. If the Groq call
  itself fails, it falls back to returning the raw retrieved chunk text rather than nothing.
- **Two modes, one pipeline:** `POST /query` (whole corpus, the right-pane chat) and
  `POST /meetings/{id}/query` (same path + a Qdrant payload filter on `meeting_id`).

---

## 5. The decisions you must be able to defend

(The README's "Key Engineering Decisions" table is the full version; these are the ones
most likely to be probed.)

- **Why Celery, not async FastAPI?** ASR + diarization + analytics on a 30-min meeting is
  minutes of wall-clock, much of it GPU/3rd-party-bound. A sync endpoint would tie up workers
  and time out. WebSocket streaming was considered — adds real complexity for no UX win at
  this scale; polling a status field is enough.
- **Why hybrid + RRF instead of pure dense?** Meeting transcripts are full of literal tokens
  (people's names, "Q3", "the Madrid deal") that dense embeddings blur. BM25 nails those; RRF
  merges without me hand-tuning a dense/sparse weight.
- **Why rules-first speaker naming?** The product's worst failure is attributing a quote to
  the wrong real person. Deterministic parsing of self-introductions is safe; the LLM only
  fills gaps when the text clearly says who's speaking. Anonymous label > confident wrong name.
- **Why store transcripts in *two* places (Postgres rows + Qdrant markdown)?** Postgres is the
  queryable source of truth for the app (segments, timings, speaker names, status). Qdrant
  holds a *chunked, vectorized* view for retrieval. Both are derived from the on-disk exports,
  so the index is disposable — `mie-ingest-md --recreate` rebuilds it.
- **Why `prompts.py` + `PROMPT_VERSION`?** Every LLM call logs the version; the eval output
  records it. A quality number (faithfulness 0.94) is always traceable to the exact prompt
  that produced it. Committed results are `PROMPT_VERSION = 2026-05-11`.
- **Why SecretStr in config?** All API keys are `pydantic.SecretStr` so they don't leak into
  logs / `repr` / tracebacks; call sites pull the value via `settings.secret("groq_api_key")`.
- **Why the `X-API-Key` guard is "coarse" (and why that's honest, not lazy):** it gates
  side-effecting / paid-API endpoints when `MIE_API_KEY` is set, no-ops when it isn't. It is
  *not* user auth — there's no multi-tenancy — and the Next.js UI doesn't send it, so turning
  it on currently locks the UI out of upload/query/delete. That trade-off is documented in
  "Known Limitations" rather than hidden.

---

## 6. The evals — know the numbers and the caveats

- **ASR / AMI Meeting Corpus, Mix-Headset, 30/30 meetings:** mean raw WER **24.99%**, mean
  filler-light WER **20.65%**, 0 failures. It's *higher* than clean single-speaker benchmarks
  because this is overlapping multi-speaker conference audio — the product's real input shape.
  Filler-light WER strips `uh/um/mm` + immediate duplicates because AMI's manual annotations
  are filler-heavy in a way that inflates raw WER without hurting downstream usability.
  Harness: `eval/ami.py`, run with `make eval-ami`.
- **RAG / fixed 50-question, 5-meeting QA set, judged by `gpt-4.1-mini` via RAGAS:**
  faithfulness **94.0%**, answer relevancy 74.3%, context precision 78.2%, context recall 83.0%.
  Headline is **faithfulness** — the system answers from evidence and refuses otherwise. The
  config is tuned toward cleaner evidence (better precision, slightly worse recall) on purpose:
  for a meeting-memory product, narrow-correct beats broad-noisy. Harness: `eval/rag.py`,
  run with `make eval-rag`. Committed JSONs are in `eval/results/` (slimmed — verbatim
  transcripts / retrieved contexts stripped).

---

## 7. "Where would you change X?" cheat-sheet

| Asked to… | Go to |
|---|---|
| add a new ASR or diarization backend | implement the interface in `core/interfaces.py`, add an adapter in `implementations/`, wire it in `services/pipeline_factory.py` |
| change chunking | `rag/` (chunking module) + re-run `mie-ingest-md --recreate` |
| tune retrieval (top-k, fusion, filters) | `rag/query.py` |
| change an LLM prompt | `prompts.py` — bump `PROMPT_VERSION`, re-run the relevant eval |
| add an API endpoint | `api/routes/<domain>.py`; request models in `api/schemas.py`; guard with `Depends(require_api_key)` if it has side effects |
| add a background step | new task in `workers/`, chain it in `services/meetings.py` |
| add a config knob | `config.py` only (one source of truth) + document in `.env.example` and the README config table |
| handle a new diarizer failure pattern | add a rule in `services/segment_repairs.py` |
| add real auth / multi-tenancy | currently out of scope — the honest answer is "the `X-API-Key` guard is a stopgap; real auth means per-workspace isolation in the data model and the query filters, plus the UI sending credentials" |

---

## 8. Things to say before you're asked (shows judgement)

- "The index is disposable; the on-disk transcript exports + Postgres are the real state."
- "RAG degrades gracefully — no Qdrant, no embeddings, the API still serves transcripts and
  analytics; it just disables cross-meeting query."
- "Errors are caught per stage — one bad meeting doesn't crash a batch run; it gets marked
  `failed` with the reason."
- "The frontend collapses the backend's `pending/processing/completed/failed` to three UI
  states (`processing/ready/failed`) because the UI only cares: working, done, broken."
- "It's a single-machine prototype. Object storage, HTTPS, encryption-at-rest, consent
  capture, Alembic migrations — all explicitly out of scope, listed as next-product work, not
  pretended to exist."
