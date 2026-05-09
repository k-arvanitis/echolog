"use client";

import { useState } from "react";
import { Meeting } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import OverviewTab from "./OverviewTab";
import TranscriptTab from "./TranscriptTab";
import AnalyticsTab from "./AnalyticsTab";
import AskTab from "./AskTab";

interface Props {
  meeting: Meeting;
  onDelete: (id: string) => void;
  onMeetingUpdated?: (m: Meeting) => void;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function formatDuration(s: number) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h > 0
    ? `${h}h ${m}m ${sec}s`
    : `${m}m ${sec}s`;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export default function MeetingDetail({ meeting, onDelete, onMeetingUpdated }: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-6 py-4 border-b border-zinc-700 flex items-start justify-between flex-shrink-0">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">{meeting.title}</h1>
          <div className="flex items-center gap-3 mt-1 text-xs text-zinc-500">
            <span>{formatDate(meeting.created_at)}</span>
            {meeting.duration != null && <span>{formatDuration(meeting.duration)}</span>}
            <span
              className={`px-1.5 py-0.5 rounded border text-[10px] font-medium ${
                meeting.status === "ready"
                  ? "bg-green-900 text-green-200 border-green-700"
                  : meeting.status === "processing"
                  ? "bg-yellow-900 text-yellow-200 border-yellow-700"
                  : "bg-red-900 text-red-200 border-red-700"
              }`}
            >
              {meeting.status}
            </span>
          </div>
        </div>

        {confirmDelete ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400">Delete this meeting?</span>
            <button
              onClick={() => { onDelete(meeting.id); setConfirmDelete(false); }}
              className="px-3 py-1 text-xs rounded bg-red-900 hover:bg-red-800 text-red-100 transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="px-3 py-1 text-xs rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-200 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="text-xs text-zinc-600 hover:text-red-400 transition-colors"
          >
            Delete
          </button>
        )}
      </div>

      <Tabs defaultValue="overview" className="flex-1 flex flex-col min-h-0">
        <TabsList className="flex-shrink-0 rounded-none border-b border-zinc-700 bg-transparent px-6 justify-start gap-1 h-auto py-0">
          {["overview", "transcript", "analytics", "ask"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="capitalize text-xs px-4 py-3 rounded-none border-b-2 border-transparent data-[state=active]:border-zinc-300 data-[state=active]:text-zinc-100 text-zinc-500 hover:text-zinc-300 transition-colors bg-transparent data-[state=active]:bg-transparent"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="flex-1 overflow-y-auto min-h-0 mt-0">
          <OverviewTab meetingId={meeting.id} />
        </TabsContent>
        <TabsContent value="transcript" className="flex-1 overflow-hidden min-h-0 mt-0">
          <TranscriptTab meetingId={meeting.id} />
        </TabsContent>
        <TabsContent value="analytics" className="flex-1 overflow-y-auto min-h-0 mt-0">
          <AnalyticsTab meetingId={meeting.id} />
        </TabsContent>
        <TabsContent value="ask" className="flex-1 overflow-hidden min-h-0 mt-0">
          <AskTab meetingId={meeting.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
