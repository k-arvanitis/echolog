"use client";

import { useState } from "react";
import { Meeting } from "@/lib/api";
import UploadModal from "./UploadModal";

interface Props {
  meetings: Meeting[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onUploaded: (m: Meeting) => void;
  onMeetingUpdated: (m: Meeting) => void;
}

const STATUS_CHIP: Record<Meeting["status"], string> = {
  processing: "bg-amber-50 text-amber-700",
  ready: "bg-emerald-50 text-emerald-700",
  failed: "bg-red-50 text-red-800",
};

function StatusBadge({ status }: { status: Meeting["status"] }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_CHIP[status]}`}>
      {status}
    </span>
  );
}

function formatDuration(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function Sidebar({ meetings, selectedId, onSelect, onUploaded, onMeetingUpdated }: Props) {
  const [uploadOpen, setUploadOpen] = useState(false);

  return (
    <aside className="flex w-[260px] flex-shrink-0 flex-col border-r border-ink-200 bg-ink-50">
      <div className="flex items-center justify-between border-b border-ink-100 px-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Meetings</p>
        <span className="text-[11px] text-ink-400">{meetings.length}</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {meetings.length === 0 && <p className="px-3 py-3 text-xs text-ink-400">No meetings yet.</p>}
        {meetings.map((m) => (
          <button
            key={m.id}
            onClick={() => onSelect(m.id)}
            className={`w-full border-b border-ink-100 px-3 py-2.5 text-left transition-colors hover:bg-ink-100 ${
              selectedId === m.id ? "bg-ink-100" : ""
            }`}
          >
            <p className="truncate text-sm font-medium text-ink-800">{m.title}</p>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-[11px] text-ink-400">{formatDate(m.created_at)}</span>
              {m.duration != null && (
                <span className="text-[11px] text-ink-400">{formatDuration(m.duration)}</span>
              )}
              <StatusBadge status={m.status} />
            </div>
          </button>
        ))}
      </div>

      <div className="border-t border-ink-200 p-3">
        <button
          onClick={() => setUploadOpen(true)}
          className="w-full rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-dark"
        >
          Upload meeting
        </button>
      </div>

      {uploadOpen && (
        <UploadModal
          onClose={() => setUploadOpen(false)}
          onUploaded={(m) => {
            onUploaded(m);
            setUploadOpen(false);
          }}
          onMeetingUpdated={onMeetingUpdated}
        />
      )}
    </aside>
  );
}
