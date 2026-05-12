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

const STATUS_CHIP: Record<Meeting["status"], string> = {
  processing: "bg-amber-50 text-amber-700",
  ready: "bg-emerald-50 text-emerald-700",
  failed: "bg-red-50 text-red-800",
};

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
  return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export default function MeetingDetail({ meeting, onDelete, onMeetingUpdated }: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-shrink-0 items-start justify-between border-b border-ink-200 px-6 py-3">
        <div>
          <h1 className="text-sm font-semibold text-ink-800">{meeting.title}</h1>
          <div className="mt-1 flex items-center gap-3 text-[11px] text-ink-400">
            <span>{formatDate(meeting.created_at)}</span>
            {meeting.duration != null && <span>{formatDuration(meeting.duration)}</span>}
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_CHIP[meeting.status]}`}>
              {meeting.status}
            </span>
          </div>
        </div>

        {confirmDelete ? (
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-ink-500">Delete this meeting?</span>
            <button
              onClick={() => {
                onDelete(meeting.id);
                setConfirmDelete(false);
              }}
              className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-800 hover:bg-red-100"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="rounded-md border border-ink-200 bg-surface px-2 py-1 text-[11px] text-ink-700 hover:bg-ink-100"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="text-[11px] text-ink-400 transition-colors hover:text-red-700"
          >
            Delete
          </button>
        )}
      </div>

      <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="h-auto flex-shrink-0 justify-start gap-1 border-b border-ink-200 bg-ink-50 px-6 py-0">
          {["overview", "transcript", "analytics", "ask"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="border-b-2 border-transparent px-4 py-2.5 text-xs capitalize text-ink-500 transition-colors hover:text-ink-700 data-[state=active]:border-brand-dark data-[state=active]:text-ink-800"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="mt-0 min-h-0 flex-1 overflow-y-auto bg-ink-50">
          <OverviewTab meetingId={meeting.id} />
        </TabsContent>
        <TabsContent value="transcript" className="mt-0 min-h-0 flex-1 overflow-hidden bg-ink-50">
          <TranscriptTab meetingId={meeting.id} />
        </TabsContent>
        <TabsContent value="analytics" className="mt-0 min-h-0 flex-1 overflow-y-auto bg-ink-50">
          <AnalyticsTab meetingId={meeting.id} />
        </TabsContent>
        <TabsContent value="ask" className="mt-0 min-h-0 flex-1 overflow-hidden bg-ink-50">
          <AskTab meetingId={meeting.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
