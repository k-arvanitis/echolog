const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8001";

export interface Meeting {
  id: string;
  title: string;
  status: "processing" | "ready" | "failed";
  created_at: string;
  duration?: number;
}

export interface Segment {
  speaker: string;
  start: number;
  end: number;
  text: string;
}

export interface Transcript {
  segments: Segment[];
  text?: string;
}

export interface ActionItem {
  text: string;
  assignee?: string;
  due_date?: string;
}

export interface Decision {
  text: string;
  context?: string;
  stakeholders?: string[];
}

export interface Topic {
  name: string;
  start_time?: number;
  end_time?: number;
}

export interface QuerySource {
  meeting_title: string;
  chunk_text: string;
  score: number;
  speaker?: string;
}

export interface QueryResponse {
  answer: string;
  sources: QuerySource[];
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function mapStatus(raw: string): Meeting["status"] {
  if (raw === "completed") return "ready";
  if (raw === "failed") return "failed";
  return "processing";
}

interface RawMeeting {
  id: string;
  title: string;
  status: string;
  created_at: string;
  duration_seconds?: number | null;
}

function normalizeMeeting(raw: RawMeeting): Meeting {
  return {
    id: raw.id,
    title: raw.title,
    status: mapStatus(raw.status),
    created_at: raw.created_at,
    duration: raw.duration_seconds ?? undefined,
  };
}

interface RawSegment {
  speaker_name?: string | null;
  speaker_id?: string;
  display_speaker?: string;
  start_time: number;
  end_time: number;
  text: string;
}

function normalizeSegment(raw: RawSegment): Segment {
  return {
    speaker: raw.display_speaker || raw.speaker_name || raw.speaker_id || "Unknown",
    start: raw.start_time,
    end: raw.end_time,
    text: raw.text,
  };
}

interface RawSpeakerLabel {
  speaker_id: string;
  speaker_name?: string | null;
}

function normalizeSpeakerLabels(raws: RawSpeakerLabel[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of raws) {
    if (r.speaker_name) out[r.speaker_id] = r.speaker_name;
  }
  return out;
}

interface RawActionItem {
  description: string;
  assignee_inferred?: string | null;
  deadline?: string | null;
}

interface RawDecision {
  decision_text: string;
  context?: string | null;
  stakeholders?: string[] | null;
}

interface RawTopic {
  topic_name: string;
  start_time?: number | null;
  end_time?: number | null;
}

interface RawQueryResponse {
  answer: string;
  sources: {
    meeting_title?: string | null;
    content?: string | null;
    score: number;
    speakers?: string[] | null;
  }[];
}

function normalizeQueryResponse(raw: RawQueryResponse): QueryResponse {
  return {
    answer: raw.answer,
    sources: raw.sources.map((s) => ({
      meeting_title: s.meeting_title ?? "Unknown meeting",
      chunk_text: s.content ?? "",
      score: s.score,
      speaker: s.speakers && s.speakers.length > 0 ? s.speakers.join(", ") : undefined,
    })),
  };
}

export const api = {
  health: () => apiFetch<{ status: string }>("/health"),

  listMeetings: () => apiFetch<RawMeeting[]>("/meetings").then((rs) => rs.map(normalizeMeeting)),

  getMeeting: (id: string) =>
    apiFetch<RawMeeting>(`/meetings/${id}`).then(normalizeMeeting),

  deleteMeeting: (id: string) =>
    fetch(`${BASE}/meetings/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    }),

  uploadMeeting: (file: File, title: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title);
    return fetch(`${BASE}/meetings/upload`, { method: "POST", body: fd }).then(
      async (r) => {
        if (!r.ok) {
          const t = await r.text().catch(() => r.statusText);
          throw new Error(t);
        }
        const raw = await r.json();
        // Upload returns {meeting_id, status, job_id} — fetch the full row.
        if (raw.meeting_id) return api.getMeeting(raw.meeting_id);
        return normalizeMeeting(raw);
      }
    );
  },

  getTranscript: (id: string) =>
    apiFetch<Transcript>(`/meetings/${id}/transcript`),

  getSegments: (id: string) =>
    apiFetch<RawSegment[]>(`/meetings/${id}/segments`).then((rs) => rs.map(normalizeSegment)),

  getSpeakerLabels: (id: string) =>
    apiFetch<RawSpeakerLabel[]>(`/meetings/${id}/speaker-labels`).then(normalizeSpeakerLabels),

  getActionItems: (id: string) =>
    apiFetch<RawActionItem[]>(`/meetings/${id}/action-items`).then((rs) =>
      rs.map((r) => ({
        text: r.description,
        assignee: r.assignee_inferred ?? undefined,
        due_date: r.deadline ?? undefined,
      }))
    ),

  getDecisions: (id: string) =>
    apiFetch<RawDecision[]>(`/meetings/${id}/decisions`).then((rs) =>
      rs.map((r) => ({
        text: r.decision_text,
        context: r.context ?? undefined,
        stakeholders: r.stakeholders ?? undefined,
      }))
    ),

  getTopics: (id: string) =>
    apiFetch<RawTopic[]>(`/meetings/${id}/topics`).then((rs) =>
      rs.map((r) => ({
        name: r.topic_name,
        start_time: r.start_time ?? undefined,
        end_time: r.end_time ?? undefined,
      }))
    ),

  queryMeeting: (id: string, query: string, top_k = 5) =>
    apiFetch<RawQueryResponse>(`/meetings/${id}/query`, {
      method: "POST",
      body: JSON.stringify({ query, top_k }),
    }).then(normalizeQueryResponse),

  queryCross: (query: string, top_k = 5) =>
    apiFetch<RawQueryResponse>("/query", {
      method: "POST",
      body: JSON.stringify({ query, top_k }),
    }).then(normalizeQueryResponse),
};
