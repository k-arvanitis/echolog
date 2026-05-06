# Meeting Intelligence Engine — Technical Specification

> **Version:** 1.0  
> **Date:** 2026-05-04  
> **Purpose:** End-to-end technical specification for a production-grade meeting intelligence platform. This document contains architecture decisions, component requirements, data models, API contracts, and integration specifications. All implementation is left to the engineering phase.

---

## 1. Executive Summary

Build a Meeting Intelligence Engine that ingests meeting audio (file upload or Zoom bot), produces diarized transcripts, extracts structured insights (action items, decisions, topics), and enables semantic search across all meetings via RAG.

**Primary Input Sources:**
- File upload (WAV, MP3, MP4) — universal, platform-agnostic
- Zoom Bot — joins meetings via official Meeting SDK, captures raw PCM audio streams

**Core Outputs:**
- Timestamped, speaker-labeled transcripts
- Extracted action items with inferred assignees and deadlines
- Decision log with stakeholders and context
- Topic segmentation
- Cross-meeting semantic Q&A with source attribution

**Key Engineering Principle:** All ML components (ASR, diarization) must implement abstract interfaces so they can be benchmarked and swapped without pipeline changes.

---

## 2. System Architecture

### 2.1 Layer Overview

| Layer | Components | Responsibility |
|-------|-----------|---------------|
| **Client** | Web UI, API clients, Zoom Bot | User interaction and audio capture |
| **Gateway** | Nginx reverse proxy | TLS termination, rate limiting, routing |
| **API** | FastAPI (async) | REST API, auth, request validation, orchestration |
| **Workers** | Celery + Redis | Async job processing (CPU and GPU bound tasks) |
| **ML Pipeline** | ASR, Diarization, Alignment, LLM, Embeddings | Core intelligence |
| **Data** | PostgreSQL, Qdrant, Redis, S3/MinIO | Persistence, search, caching, object storage |

### 2.2 Data Flow

**File Upload Path:**
1. Client uploads audio via FastAPI
2. Audio Ingestion Worker validates format, converts to WAV 16kHz mono, stores in S3/MinIO
3. Transcript Processor Worker (GPU) runs VAD → ASR → Diarization → Alignment
4. Analytics Processor Worker (CPU/GPU) extracts action items, decisions, topics via LLM
5. Indexing Worker chunks transcript, embeds with E5-large, upserts into Qdrant
6. All structured results stored in PostgreSQL

**Zoom Bot Path:**
1. User authorizes via Zoom OAuth (OBF token flow)
2. Zoom Bot Service joins meeting via Zoom Meeting SDK
3. Raw PCM audio frames streamed to Redis Stream
4. Stream Ingestion Worker buffers audio into processable chunks
5. Same WhisperX pipeline processes chunks incrementally
6. Partial results emitted via WebSocket; final results stored on bot leave

---

## 3. Component Specifications

### 3.1 Audio Ingestion Worker

**Runtime:** CPU only
**Queue:** Celery queue: `audio.ingestion`

**Requirements:**
- Accept audio files: WAV, MP3, MP4, M4A
- Validate using FFprobe (check codec, sample rate, duration)
- Reject files > 4 hours or > 500MB
- Convert to standard format: WAV, 16kHz, mono, 16-bit PCM using FFmpeg
- Generate spectrogram or waveform preview (optional)
- Store raw original and processed audio in S3/MinIO under `meetings/{meeting_id}/`
- Update meeting status in PostgreSQL from `pending` to `ready_for_transcription`
- Push job to `transcription` queue

### 3.2 Transcript Processor Worker

**Runtime:** GPU required (NVIDIA)
**Queue:** Celery queue: `transcription`

**Pipeline Stages (in order):**

1. **Voice Activity Detection (VAD)**
   - Use Silero VAD
   - Segment audio into speech regions
   - Filter out silence > 2 seconds for efficiency

2. **ASR**
   - Use faster-whisper (large-v3) as default
   - Must be swappable via abstract interface
   - Output: word-level timestamps with confidence scores
   - Language auto-detection with fallback to English

3. **Speaker Diarization**
   - Use pyannote/segmentation-3.0 as default
   - Must be swappable via abstract interface
   - Output: speaker segments (speaker_id, start, end, confidence)
   - Handle overlapping speech gracefully

4. **Forced Alignment**
   - Map each word from ASR to a speaker segment from diarization
   - Use WhisperX alignment engine as default
   - Output unified transcript segments where each segment has one speaker and continuous text

**Output Schema (stored as JSON and in PostgreSQL):**
- meeting_id (UUID)
- segments (array):
  - speaker_id (string, e.g., SPEAKER_00)
  - start_time (float, seconds)
  - end_time (float, seconds)
  - text (string)
  - words (array):
    - text (string)
    - start (float)
    - end (float)
    - confidence (float)
- speakers (array of unique speaker_ids)
- metadata:
  - asr_model_name
  - diarization_model_name
  - processing_duration_seconds
  - word_count

**Error Handling:**
- If ASR fails → mark meeting failed, store error, notify user
- If diarization fails → fallback to single-speaker mode (label everything SPEAKER_00), log warning
- If alignment fails → use simple time-overlap heuristic, log warning

### 3.3 Analytics Processor Worker

**Runtime:** CPU or GPU (LLM inference)
**Queue:** Celery queue: `analytics`

**Tasks:**

**A. Action Item Extraction**
- Input: full transcript text with speaker labels and timestamps
- LLM: Llama 3.1 8B Instruct via vLLM
- Prompt engineering requirements:
  - Identify explicit and implicit tasks
  - Infer assignee from context (e.g., "John will handle this" → assignee: John)
  - Extract deadlines if mentioned
  - Assign priority: low, medium, high
  - Confidence score 0.0–1.0 for each extraction
- Output fields:
  - description (text)
  - assignee_inferred (string or null)
  - deadline (ISO date or null)
  - priority (enum)
  - confidence (float)
  - transcript_segment_id (reference)

**B. Decision Log Extraction**
- Input: full transcript
- LLM: Llama 3.1 8B Instruct via vLLM
- Prompt engineering requirements:
  - Extract only explicit decisions ("we decided", "let's go with", "agreed to")
  - Capture surrounding context (2–3 sentences before)
  - Identify stakeholders mentioned
  - Timestamp reference
- Output fields:
  - decision_text (text)
  - context (text)
  - stakeholders (array of strings)
  - timestamp (float, seconds into meeting)
  - confidence (float)

**C. Topic Segmentation**
- Option 1: BERTopic (unsupervised) for initial version
- Option 2: LLM-based segmentation for higher accuracy
- Requirements:
  - Break meeting into 3–10 topical segments
  - Each topic: name, start_time, end_time, keywords, confidence
  - Topics should align with natural conversation shifts

**LLM Constraints:**
- Use JSON mode / structured output / constrained decoding
- Temperature: 0.1–0.3 for extraction tasks
- Max tokens: 4096
- Implement retry logic with exponential backoff
- Validate JSON schema before saving; if invalid, retry once

### 3.4 RAG Query Engine

**Runtime:** API endpoint (FastAPI)

**Indexing Requirements:**
- Chunk transcript by speaker turns or max token limit (512 tokens)
- Preserve speaker boundaries — do not split a single speaker turn across chunks unless it exceeds token limit
- Embedding model: intfloat/e5-large-v2
  - Prefix passages with `passage: `
  - Normalize embeddings
- Vector DB: Qdrant
  - Collection: `meeting_transcripts`
  - Vector size: 1024
  - Distance: Cosine
  - Payload indices on: meeting_id, speaker_id, created_at

**Query Requirements:**
- Embed queries with `query: ` prefix
- Hybrid search approach:
  1. Semantic search in Qdrant (top 10)
  2. Optional: rerank with cross-encoder (if implemented)
  3. Filter by metadata: date range, speaker, meeting_id
- LLM generation:
  - Model: Llama 3.1 8B via vLLM
  - Context window: use top 5 chunks
  - System prompt: instruct to answer ONLY from provided context
  - If answer not in context, respond: "I don't have information about that in the meeting records."
  - Include source citations in response (meeting title, speaker, timestamp)

**Output Format:**
- answer (text)
- sources (array):
  - meeting_id
  - meeting_title
  - speaker_id
  - timestamp
  - text (source chunk)
  - score
- processing_time_ms

---

## 4. Abstract Interfaces (Contract Layer)

All ML models must implement these interfaces. The pipeline must depend only on these abstractions.

### 4.1 ASRModel Interface

Methods required:
- `load(model_path: str, device: str)` — load weights
- `transcribe(audio_path: str) -> list[dict]` — return segments with word-level timestamps
- `get_model_info() -> dict` — return name, version, parameters, backend

Expected transcribe output structure:
- list of segments, each containing:
  - text (str)
  - start (float)
  - end (float)
  - words (list): word, start, end, confidence

### 4.2 DiarizationModel Interface

Methods required:
- `load(model_path: str, device: str)` — load weights
- `diarize(audio_path: str) -> list[SpeakerSegment]` — return speaker time ranges
- `get_model_info() -> dict`

SpeakerSegment structure:
- speaker_id (str)
- start (float)
- end (float)
- confidence (float)

### 4.3 AlignmentEngine Interface

Methods required:
- `align(asr_segments: list[dict], speaker_segments: list[SpeakerSegment]) -> list[TranscriptSegment]`

TranscriptSegment structure:
- speaker_id (str)
- start (float)
- end (float)
- text (str)
- words (list of Word objects)

Word structure:
- text (str)
- start (float)
- end (float)
- confidence (float)

### 4.4 TranscriptionPipeline Interface

Methods required:
- `load()` — initialize all sub-models
- `process(audio_path: str) -> dict` — full batch processing
- `process_stream(audio_chunk: bytes) -> dict | None` — streaming partial processing
- Must expose `asr`, `diarization`, `alignment` as attributes for benchmarking

**Initial Implementation:** WhisperXTranscriptionPipeline combining WhisperXASR, PyannoteDiarization, and WhisperXAlignment.

**Future Swaps:**
- CanaryASR (NVIDIA Canary-1B)
- NeMoDiarization (NVIDIA NeMo MSDD)
- Custom alignment engine

---

## 5. Database Schema

### 5.1 PostgreSQL Tables

**users**
- id: UUID, primary key
- email: string, unique, not null
- hashed_password: string (nullable for OAuth users)
- oauth_provider: string (nullable)
- oauth_id: string (nullable)
- created_at: timestamp
- updated_at: timestamp

**meetings**
- id: UUID, primary key
- user_id: UUID, foreign key → users.id
- title: string
- source: enum (upload, zoom_bot)
- status: enum (pending, processing, completed, failed)
- audio_url: string (S3/MinIO path)
- duration_seconds: integer (nullable)
- processed_audio_url: string (nullable)
- error_message: text (nullable)
- created_at: timestamp
- completed_at: timestamp (nullable)

**transcripts**
- id: UUID, primary key
- meeting_id: UUID, foreign key → meetings.id
- speaker_id: string
- start_time: float (seconds)
- end_time: float (seconds)
- text: text
- words: JSONB (array of word objects)
- embedding_id: string (nullable, reference to Qdrant point ID)
- created_at: timestamp

**action_items**
- id: UUID, primary key
- meeting_id: UUID, foreign key → meetings.id
- transcript_segment_id: UUID, foreign key → transcripts.id (nullable)
- description: text, not null
- assignee_inferred: string (nullable)
- deadline: date (nullable)
- priority: enum (low, medium, high)
- status: enum (open, completed, cancelled)
- confidence: float
- created_at: timestamp

**decisions**
- id: UUID, primary key
- meeting_id: UUID, foreign key → meetings.id
- transcript_segment_id: UUID, foreign key → transcripts.id (nullable)
- decision_text: text, not null
- context: text (nullable)
- stakeholders: array of strings (nullable)
- timestamp: float (seconds into meeting)
- confidence: float
- created_at: timestamp

**topics**
- id: UUID, primary key
- meeting_id: UUID, foreign key → meetings.id
- topic_name: string
- start_time: float
- end_time: float
- confidence: float
- keywords: array of strings

**zoom_bot_sessions**
- id: UUID, primary key
- user_id: UUID, foreign key → users.id
- meeting_id: UUID, foreign key → meetings.id (nullable)
- zoom_meeting_id: string
- obf_token_encrypted: text (encrypt at application layer)
- status: enum (authorized, joined, streaming, left, failed)
- joined_at: timestamp (nullable)
- left_at: timestamp (nullable)
- created_at: timestamp

### 5.2 Qdrant Collection

Collection name: `meeting_transcripts`

Vector configuration:
- size: 1024
- distance: Cosine

Payload schema (indexed):
- meeting_id: keyword
- speaker_id: keyword
- start_time: float
- end_time: float
- text: text (for keyword filtering)
- created_at: datetime

---

## 6. API Specification

### 6.1 Authentication Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /auth/register | Register new user with email/password |
| POST | /auth/login | Login, return JWT access token |
| POST | /auth/zoom/oauth | Initiate Zoom OAuth flow (returns redirect URL) |
| GET | /auth/zoom/callback | Zoom OAuth callback (exchanges code for tokens) |

**Auth Requirements:**
- JWT access tokens for all protected endpoints
- Token expiry: 24 hours
- Refresh token rotation supported
- Zoom tokens encrypted at rest (AES-256)

### 6.2 Meeting Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /meetings/upload | Upload audio file (multipart/form-data). Returns meeting_id and job_id. |
| GET | /meetings | List user meetings with pagination |
| GET | /meetings/{id} | Get meeting metadata and status |
| GET | /meetings/{id}/transcript | Get full diarized transcript |
| GET | /meetings/{id}/action-items | Get extracted action items |
| GET | /meetings/{id}/decisions | Get decision log |
| GET | /meetings/{id}/topics | Get topic segmentation |
| DELETE | /meetings/{id} | Soft delete meeting and all associated data |

**Upload Endpoint Details:**
- Accept: multipart/form-data
- Fields: `file` (binary), `title` (optional string)
- Max file size: 500MB
- Accepted MIME types: audio/wav, audio/mpeg, audio/mp4, video/mp4
- Returns: meeting_id, status (pending), job_id (Celery task ID)

### 6.3 Query Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /meetings/{id}/query | RAG query scoped to single meeting |
| POST | /query | Cross-meeting RAG query |

**Query Request Body:**
- query: string (required)
- filters:
  - date_from: ISO date (optional)
  - date_to: ISO date (optional)
  - speakers: array of speaker_id strings (optional)
  - meeting_ids: array of UUIDs (optional, for /query only)
- top_k: integer (optional, default 5, max 10)

**Query Response:**
- answer: string
- sources: array of source objects
- processing_time_ms: integer

### 6.4 Zoom Bot Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /zoom/join | Trigger bot to join a meeting |
| GET | /zoom/sessions | List bot sessions for user |
| DELETE | /zoom/sessions/{id} | Force bot to leave meeting |
| WS | /zoom/{session_id}/stream | WebSocket for real-time transcript updates |

**Join Request Body:**
- meeting_id: string (Zoom meeting ID)
- display_name: string (optional, default "Meeting Assistant")

**Join Requirements:**
- User must have valid Zoom OAuth connection (OBF token)
- Bot cannot join without host present (Zoom OBF requirement)
- Rate limit: max 5 joins per hour per user

**WebSocket Events:**
- `transcript.partial` — interim transcript segment
- `transcript.final` — finalized segment after speaker alignment
- `bot.status` — joined, streaming, error, left
- `bot.error` — error details

---

## 7. Zoom Bot Integration Specification

### 7.1 OAuth Flow

1. User clicks "Connect Zoom" in UI
2. Backend generates PKCE verifier and random state, stores in Redis (expiry 10 minutes)
3. Redirect user to Zoom OAuth authorize URL with:
   - response_type=code
   - client_id
   - redirect_uri
   - state
   - scope: `meeting:read`, `user:read`
4. User authorizes app in Zoom
5. Zoom redirects to callback with `code` and `state`
6. Backend verifies state matches Redis
7. Backend exchanges code for tokens via Zoom token endpoint
8. Store: access_token, refresh_token, expires_at, obf_token
9. Encrypt tokens before saving to database

### 7.2 Bot Join & Audio Capture

1. User provides Zoom meeting ID via API
2. Backend retrieves stored OBF token for user
3. Bot service initializes Zoom Meeting SDK session
4. Bot joins meeting using:
   - meeting_number
   - user_name (configurable, default "Meeting Assistant")
   - OBF token
   - video off, audio muted (listen-only mode)
5. On successful join:
   - Subscribe to Raw Data API for audio
   - Audio format: PCM 16LE, 16kHz, mono
   - Each frame pushed to Redis Stream (`audio_stream:{session_id}`)
6. Stream Ingestion Worker consumes from Redis Stream
7. Buffer audio into 30-second chunks
8. Run WhisperX pipeline on each chunk
9. Emit partial results via WebSocket
10. On bot leave or disconnect:
    - Flush remaining audio
    - Run analytics extraction on complete transcript
    - Store final results
    - Update session status

### 7.3 Error & Edge Case Handling

| Scenario | Handling |
|----------|----------|
| Host not present | Bot polls for 2 minutes; if host absent, fail with clear error |
| Waiting room | Bot detects waiting room status; notify user to admit bot |
| Host leaves mid-meeting | Bot detects host departure; gracefully leave and finalize partial transcript |
| Network interruption | Exponential backoff retry (3 attempts), then mark session failed |
| Zoom SDK error | Log error code, notify user, mark session failed |
| Invalid OBF token | Attempt refresh once; if fails, prompt user to re-authorize |

---

## 8. RAG Architecture

### 8.1 Chunking Strategy

- Chunk by speaker turns primarily
- If a speaker turn exceeds 512 tokens, split at sentence boundary
- Overlap: last sentence of previous chunk included as context in next chunk (optional)
- Each chunk preserves: meeting_id, speaker_id, start_time, end_time

### 8.2 Embedding & Search

- Model: intfloat/e5-large-v2
- Passage prefix: `passage: ` followed by chunk text
- Query prefix: `query: ` followed by user question
- Normalize embeddings before storage and query
- Qdrant search: cosine similarity with metadata filters
- Optional reranking: cross-encoder (ms-marco-MiniLM-L-6-v2) on retrieved top 10

### 8.3 Generation

- Model: meta-llama/Meta-Llama-3.1-8B-Instruct via vLLM
- Temperature: 0.3
- Max tokens: 512
- Prompt structure:
  - System: You are a meeting intelligence assistant. Answer based ONLY on provided context.
  - Context: concatenated retrieved chunks with source markers
  - Question: user query
  - Instruction: If answer not in context, say "I don't have information about that in the meeting records."
- Post-processing: parse answer, extract sources referenced, format citations

---

## 9. Evaluation Requirements

### 9.1 Benchmarks

| Component | Metric | Target | Notes |
|-----------|--------|--------|-------|
| ASR | Word Error Rate (WER) | < 8% clean audio, < 18% noisy/overlapping | Test on AMI Corpus + custom labeled data |
| Diarization | Diarization Error Rate (DER) | < 12% | Test on AMI, ICSI, pyannote benchmarks |
| Diarization | Jaccard Error Rate (JER) | < 15% | Secondary metric |
| Action Items | F1 Score | > 0.75 | Manually annotate 50+ meetings |
| Decisions | F1 Score | > 0.80 | Manually annotate 50+ meetings |
| RAG | Answer Relevance | > 4.0 / 5.0 | Human evaluation on 100 queries |
| RAG | Faithfulness | > 0.90 | RAGAS framework or similar |
| End-to-end | Latency | < 2x meeting duration | 1-hour meeting processed in < 2 hours |
| End-to-end | Cost | < $0.10 per meeting | Open-source stack, self-hosted |

### 9.2 Open-Source Evaluation Datasets

The following public datasets must be used for benchmarking and regression testing:

| Dataset | Purpose | Size | Key Characteristics |
|---------|---------|------|---------------------|
| **AMI Meeting Corpus** | ASR WER, Diarization DER/JER | ~100 hours | Real multi-party meetings, 4 participants, close-talk + far-field mics, rich annotations including orthographic transcripts, speaker segments, word alignments |
| **ICSI Meeting Recorder Corpus** | ASR WER, Diarization DER | ~75 hours | Natural academic meetings, overlapping speech, spontaneous dialogue, includes hand-aligned transcripts |
| **Earnings-21** | ASR domain adaptation | 39 hours | Earnings call recordings, financial jargon, challenging acoustic conditions |
| **VoxConverse** | Speaker diarization | ~400 hours | Video-derived audio, multi-speaker, diverse domains, includes development set with ground-truth RTTMs |
| **DIHARD III** | Diarization robustness | ~20 hours | Challenging conditions: child speech, clinical, courtroom, broadcast — tests robustness beyond clean meeting rooms |
| **Custom Labeled Set** | Action items, Decisions, Topics | 50+ meetings | Manually annotate your own meeting recordings or use public meeting transcripts with structured labels for extraction tasks |

**Dataset Usage Requirements:**
- AMI Corpus must be the primary benchmark for ASR + diarization end-to-end
- Report WER on AMI test set (ami_test) using official split
- Report DER on AMI test set using pyannote.metrics with collar=0.25s
- For action items and decisions: if no public labeled dataset exists, create a custom evaluation set by annotating 50+ meeting transcripts from AMI or public earnings calls
- Store all evaluation datasets in `evaluation/datasets/` with clear README documenting splits and preprocessing

**Preprocessing Requirements:**
- AMI: use the "Mix-Headset" audio for realistic far-field conditions
- Convert all datasets to 16kHz mono WAV before pipeline ingestion
- For diarization evaluation, convert ground truth to RTTM format compatible with pyannote.metrics


### 9.3 Evaluation Framework

Implement automated evaluation scripts that:
- Load test datasets (AMI Corpus for ASR/diarization, custom labeled for extraction)
- Run pipeline components in isolation
- Compute metrics using standard libraries (jiwer for WER, pyannote.metrics for DER)
- Generate benchmark reports comparing current model vs. baselines
- Store results for regression tracking

---

## 10. Deployment & Infrastructure

### 10.1 Local Development

- Docker Compose with all services:
  - FastAPI app
  - Celery workers (separate CPU and GPU services)
  - PostgreSQL with pgvector extension
  - Redis
  - Qdrant
  - MinIO
- GPU worker must use NVIDIA runtime with CUDA 12.1+
- Volume mounts for model caching (avoid re-downloading)

### 10.2 Production (Kubernetes)

- API Deployment: 3 replicas, HPA on CPU 60%
- GPU Worker Deployment: KEDA scaled on Redis queue depth
- CPU Worker Deployment: HPA on CPU 70%
- PostgreSQL: StatefulSet, 1 primary + 2 read replicas
- Qdrant: StatefulSet, 3-node cluster
- Redis: Sentinel mode for high availability
- MinIO: Distributed mode
- Ingress: Nginx with TLS termination
- Monitoring: Prometheus + Grafana
- Logging: Centralized structured logging (JSON format)

### 10.3 Environment Configuration

Required environment variables:
- DATABASE_URL
- REDIS_URL
- QDRANT_URL
- MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
- VLLM_API_URL (or run vLLM as sidecar)
- ZOOM_SDK_KEY, ZOOM_SDK_SECRET
- ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
- JWT_SECRET_KEY
- ENCRYPTION_KEY (for OAuth tokens at rest)

---

## 11. Project Structure

```
meeting-intelligence-engine/
├── README.md
├── docker-compose.yml
├── .env.example
├── k8s/
│   ├── api-deployment.yaml
│   ├── worker-gpu-deployment.yaml
│   ├── worker-cpu-deployment.yaml
│   ├── postgres-statefulset.yaml
│   ├── qdrant-statefulset.yaml
│   └── ingress.yaml
├── api/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   └── routers/
│       ├── auth.py
│       ├── meetings.py
│       ├── query.py
│       └── zoom.py
├── core/
│   ├── models/
│   │   ├── base.py          # Abstract interfaces
│   │   └── schemas.py       # Pydantic request/response models
│   └── exceptions.py
├── implementations/
│   ├── whisperx_pipeline.py
│   ├── canary_asr.py        # Placeholder for future benchmark
│   └── nemo_diarization.py  # Placeholder for future benchmark
├── workers/
│   ├── celery_app.py
│   ├── audio_ingestion.py
│   ├── transcript_processor.py
│   ├── analytics_processor.py
│   └── indexing.py
├── services/
│   ├── rag_engine.py
│   ├── zoom_bot.py
│   ├── llm_service.py
│   └── encryption.py
├── evaluation/
│   ├── benchmark.py
│   ├── datasets/
│   └── reports/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docs/
    ├── architecture.md
    ├── api_reference.md
    └── deployment.md
```

---

## 12. Technology Stack

| Category | Technology | Justification |
|----------|-----------|---------------|
| API Framework | FastAPI + Uvicorn | Async Python, automatic OpenAPI docs, industry standard |
| Task Queue | Celery + Redis | Mature, supports priority queues, retries, result backends |
| ASR | faster-whisper large-v3 | Best open-source ASR, robust to noise, word-level timestamps |
| Diarization | pyannote/segmentation-3.0 | State-of-the-art DER, proven in research and production |
| Alignment | WhisperX | Handles word-to-speaker alignment automatically |
| LLM | Meta-Llama-3.1-8B-Instruct | Best open-source instruction model, JSON mode, cost-efficient |
| LLM Serving | vLLM | PagedAttention, high throughput, OpenAI-compatible API |
| Embeddings | intfloat/e5-large-v2 | MTEB benchmark leader, query/passage prefix support |
| Vector DB | Qdrant | Rust-based, fast hybrid search, metadata filtering, self-hostable |
| Relational DB | PostgreSQL + pgvector | Reliable, familiar, supports vectors for future use |
| Object Storage | MinIO | S3-compatible API, self-hostable, distributed mode |
| Zoom Integration | Zoom Meeting SDK + OBF | Official SDK, raw PCM audio access |
| Auth | JWT + OAuth2 | Standard for API security |
| Testing | pytest + httpx + locust | Unit, integration, and load testing |
| Monitoring | Prometheus + Grafana | Metrics, alerting, dashboards |
| Deployment | Docker + Kubernetes | Container orchestration, auto-scaling |

---

## 13. Development Phases

| Phase | Focus | Duration Estimate |
|-------|-------|-------------------|
| **Phase 1** | Core pipeline: file upload → ingestion → WhisperX → transcript API | 2 weeks |
| **Phase 2** | Analytics: action items, decisions, topics extraction via LLM | 1 week |
| **Phase 3** | RAG: Qdrant indexing, embedding pipeline, query API | 1 week |
| **Phase 4** | Zoom Bot: OAuth, SDK integration, streaming, WebSocket | 1 week |
| **Phase 5** | Polish: tests, benchmarks, documentation, deployment configs | 1 week |

---

## 14. Non-Functional Requirements

- **Security:** Encrypt Zoom tokens at rest (AES-256). JWT for API auth. No audio stored longer than user-configurable retention (default 90 days).
- **Privacy:** Self-hostable option. No third-party API calls for core processing (all open models).
- **Scalability:** Horizontal scaling of workers. GPU workers scaled by queue depth.
- **Observability:** Structured logs, metrics for pipeline stages, error tracking.
- **Reliability:** Celery tasks with retries, dead letter queues, idempotent operations.
- **Cost:** Target <$0.10 per meeting hour using open-source models on self-hosted GPU.

---

## 15. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Zoom OBF token requires host presence | Document clearly; design for graceful failure if host leaves |
| GPU memory limits long audio | Chunk audio into 30-minute segments; process sequentially |
| pyannote model is large (~400MB) | Load once per worker process; use model caching |
| LLM hallucination in extraction | Low temperature, JSON mode, validation layer, confidence scores |
| Speaker diarization accuracy on overlapping speech | Use pyannote segmentation-3.0 (handles overlap); document limitations |
| Teams integration not available via API | Scope to file upload + Zoom only; document Teams limitation |

---

*End of Specification*
