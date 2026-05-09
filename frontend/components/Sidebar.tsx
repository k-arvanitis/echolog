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

function StatusBadge({ status }: { status: Meeting["status"] }) {
  const cls = {
    processing: "bg-yellow-900 text-yellow-200 border-yellow-700",
    ready: "bg-green-900 text-green-200 border-green-700",
    failed: "bg-red-900 text-red-200 border-red-700",
  }[status];
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${cls}`}>
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
    <aside className="w-[260px] flex-shrink-0 flex flex-col h-full bg-zinc-900 border-r border-zinc-700">
      <div className="px-4 py-4 border-b border-zinc-700">
        <span className="text-base font-bold tracking-tight text-white">Recall</span>
      </div>

      <div className="px-4 pt-3 pb-1">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-500">Meetings</p>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {meetings.length === 0 && (
          <p className="px-4 py-3 text-xs text-zinc-500">No meetings yet.</p>
        )}
        {meetings.map((m) => (
          <button
            key={m.id}
            onClick={() => onSelect(m.id)}
            className={`w-full text-left px-4 py-3 border-b border-zinc-800 hover:bg-zinc-800 transition-colors ${
              selectedId === m.id ? "bg-zinc-800" : ""
            }`}
          >
            <p className="text-sm font-medium text-zinc-100 truncate">{m.title}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[11px] text-zinc-500">{formatDate(m.created_at)}</span>
              {m.duration != null && (
                <span className="text-[11px] text-zinc-500">{formatDuration(m.duration)}</span>
              )}
              <StatusBadge status={m.status} />
            </div>
          </button>
        ))}
      </div>

      <div className="p-4 border-t border-zinc-700">
        <button
          onClick={() => setUploadOpen(true)}
          className="w-full py-2 px-3 rounded bg-zinc-700 hover:bg-zinc-600 text-sm text-zinc-100 transition-colors"
        >
          Upload Meeting
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
