"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Segment } from "@/lib/api";
import { useToast } from "@/lib/toast";

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4 text-zinc-500" fill="none" viewBox="0 0 24 24">
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

  const speakers = useMemo(
    () => Array.from(new Set(segments.map((s) => s.speaker))),
    [segments]
  );

  const displayName = (speaker: string) => labels[speaker] ?? speaker;

  const visible = filter === "all" ? segments : segments.filter((s) => s.speaker === filter);

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-6 py-8 text-zinc-500 text-sm">
        <Spinner /> Loading transcript…
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-shrink-0 px-6 py-3 border-b border-zinc-800 flex items-center gap-3">
        <label className="text-xs text-zinc-500">Speaker</label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
        >
          <option value="all">All</option>
          {speakers.map((sp) => (
            <option key={sp} value={sp}>
              {displayName(sp)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 bg-zinc-900 z-10">
            <tr className="border-b border-zinc-700">
              <th className="text-left px-4 py-2.5 text-zinc-500 font-medium w-32">Speaker</th>
              <th className="text-left px-4 py-2.5 text-zinc-500 font-medium w-16">Start</th>
              <th className="text-left px-4 py-2.5 text-zinc-500 font-medium w-16">End</th>
              <th className="text-left px-4 py-2.5 text-zinc-500 font-medium">Text</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((seg, i) => (
              <tr key={i} className="border-b border-zinc-800 hover:bg-zinc-800/40">
                <td className="px-4 py-2.5 text-zinc-400 font-medium">{displayName(seg.speaker)}</td>
                <td className="px-4 py-2.5 text-zinc-600 font-mono">{fmtTime(seg.start)}</td>
                <td className="px-4 py-2.5 text-zinc-600 font-mono">{fmtTime(seg.end)}</td>
                <td className="px-4 py-2.5 text-zinc-200 leading-relaxed">{seg.text}</td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-zinc-600">
                  No segments found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
