"use client";

import { useState, useEffect, useCallback } from "react";
import { api, Meeting } from "@/lib/api";
import { useToast } from "@/lib/toast";
import Sidebar from "@/components/Sidebar";
import MeetingDetail from "@/components/MeetingDetail";
import CrossMeetingPanel from "@/components/CrossMeetingPanel";
import ThemeToggle from "@/components/ThemeToggle";

export default function Home() {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [offlineDismissed, setOfflineDismissed] = useState(false);
  const { addToast } = useToast();

  const loadMeetings = useCallback(async () => {
    try {
      const data = await api.listMeetings();
      setMeetings(data);
      setOffline(false);
      if (!selectedId) {
        const first = data.find((m) => m.status === "ready") ?? data[0];
        if (first) setSelectedId(first.id);
      }
    } catch {
      setOffline(true);
    }
  }, [selectedId]);

  useEffect(() => {
    loadMeetings();
    const interval = setInterval(loadMeetings, 30_000);
    return () => clearInterval(interval);
  }, [loadMeetings]);

  const handleDelete = async (id: string) => {
    try {
      await api.deleteMeeting(id);
      setMeetings((prev) => prev.filter((m) => m.id !== id));
      if (selectedId === id) setSelectedId(null);
      addToast("Meeting deleted.", "info");
    } catch (e) {
      addToast(`Delete failed: ${(e as Error).message}`);
    }
  };

  const selectedMeeting = meetings.find((m) => m.id === selectedId) ?? null;

  return (
    <div className="flex h-screen flex-col bg-ink-50">
      <header className="flex flex-shrink-0 items-center justify-between border-b border-ink-200 bg-surface px-6 py-3">
        <span className="text-xl font-bold tracking-tight text-ink-800">Echolog</span>
        <div className="flex items-center gap-3">
          <span className="hidden text-[11px] text-ink-400 sm:inline">Audio Meeting Intelligence</span>
          <ThemeToggle />
        </div>
      </header>

      {offline && !offlineDismissed && (
        <div className="flex items-center justify-between border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          <span>
            <strong>Backend offline</strong> — start the API server (<code className="font-mono">make api</code>)
          </span>
          <button
            onClick={() => setOfflineDismissed(true)}
            className="ml-4 text-amber-700 hover:text-amber-900"
          >
            ✕
          </button>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          meetings={meetings}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onUploaded={(m) => {
            setMeetings((prev) => [m, ...prev.filter((x) => x.id !== m.id)]);
            setSelectedId(m.id);
          }}
          onMeetingUpdated={(updated) =>
            setMeetings((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
          }
        />

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {selectedMeeting ? (
            <MeetingDetail
              meeting={selectedMeeting}
              onDelete={handleDelete}
              onMeetingUpdated={(updated) =>
                setMeetings((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
              }
            />
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-ink-400">
              {meetings.length === 0 ? "No meetings yet. Upload one to get started." : "Select a meeting"}
            </div>
          )}
        </main>

        <CrossMeetingPanel />
      </div>
    </div>
  );
}
