"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Segment } from "@/lib/api";
import { useToast } from "@/lib/toast";

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin text-ink-400" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

interface Props {
  meetingId: string;
}

export default function TranscriptTab({ meetingId }: Props) {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const { addToast } = useToast();

  useEffect(() => {
    setLoading(true);
    Promise.all([api.getSegments(meetingId), api.getSpeakerLabels(meetingId)])
      .then(([segs, lbls]) => {
        setSegments(segs);
        setLabels(lbls);
      })
      .catch((e) => addToast(`Failed to load transcript: ${e.message}`))
      .finally(() => setLoading(false));
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  const speakers = useMemo(() => Array.from(new Set(segments.map((s) => s.speaker))), [segments]);

  const displayName = (speaker: string) => labels[speaker] ?? speaker;

  const visible = filter === "all" ? segments : segments.filter((s) => s.speaker === filter);

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-6 py-8 text-sm text-ink-400">
        <Spinner /> Loading transcript…
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col p-3">
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-ink-200 bg-surface">
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-ink-100 px-3 py-2">
          <label className="text-[11px] text-ink-500">Speaker</label>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-md border border-ink-200 bg-ink-50 px-2 py-1 text-[11px] text-ink-700 focus:border-brand focus:outline-none"
          >
            <option value="all">All</option>
            {speakers.map((sp) => (
              <option key={sp} value={sp}>
                {displayName(sp)}
              </option>
            ))}
          </select>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="border-b border-ink-200">
                <th className="w-32 px-3 py-2 text-left font-medium text-ink-500">Speaker</th>
                <th className="w-16 px-3 py-2 text-left font-medium text-ink-500">Start</th>
                <th className="w-16 px-3 py-2 text-left font-medium text-ink-500">End</th>
                <th className="px-3 py-2 text-left font-medium text-ink-500">Text</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((seg, i) => (
                <tr key={i} className="border-b border-ink-100 hover:bg-ink-50">
                  <td className="px-3 py-2 font-medium text-ink-600">{displayName(seg.speaker)}</td>
                  <td className="px-3 py-2 font-mono text-ink-400">{fmtTime(seg.start)}</td>
                  <td className="px-3 py-2 font-mono text-ink-400">{fmtTime(seg.end)}</td>
                  <td className="px-3 py-2 leading-relaxed text-ink-800">{seg.text}</td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-8 text-center text-ink-400">
                    No segments found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
