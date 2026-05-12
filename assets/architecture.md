# Architecture diagrams

GitHub renders the Mermaid blocks below. To export a PNG for slides, paste the
source into <https://mermaid.live> or use the Mermaid CLI:

```bash
npx -y @mermaid-js/mermaid-cli -i assets/architecture.md -o assets/architecture.png
```

## System

```mermaid
flowchart LR
    UI["Next.js UI<br/>:3000"] -- "HTTP / JSON" --> API["FastAPI<br/>:8001"]
    API --> PG[("PostgreSQL<br/>meeting state")]
    API --> RDS[("Redis<br/>Celery broker")]
    API --> QD[("Qdrant<br/>hybrid retrieval")]
    RDS --> W["Celery worker<br/>transcribe · analytics · indexing"]
    W -- "ASR" --> GW["Groq Whisper"]
    W -- "diarization" --> PY["pyannote"]
    W -- "analytics + answer" --> GC["Groq chat<br/>llama-3.1 / 3.3"]
    W -- "embed" --> OL["Ollama<br/>nomic-embed-text"]
    W --> PG
    OL --> QD
```

## Processing pipeline

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

## Retrieval (cross-meeting query)

```mermaid
flowchart LR
    Q[user question] --> DE["dense embed<br/>nomic-embed-text"]
    Q --> SP["sparse embed<br/>Qdrant BM25"]
    DE --> RRF{{"RRF fusion<br/>(Qdrant)"}}
    SP --> RRF
    RRF --> TK["top-k transcript<br/>markdown chunks"]
    TK --> LLM["Groq llama-3.3<br/>answer constrained to context"]
    LLM --> OUT["grounded answer<br/>+ [Source N] citations"]
```
