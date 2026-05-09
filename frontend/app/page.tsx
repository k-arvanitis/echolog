"use client";

import { useState, useEffect, useCallback } from "react";
import { api, Meeting } from "@/lib/api";
import { useToast } from "@/lib/toast";
import Sidebar from "@/components/Sidebar";
import MeetingDetail from "@/components/MeetingDetail";
import CrossMeetingPanel from "@/components/CrossMeetingPanel";

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
    <div className="flex h-screen overflow-hidden bg-[#0a0a0a]">
      {offline && !offlineDismissed && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-yellow-900 border-b border-yellow-700 text-yellow-100 px-4 py-2 flex items-center justify-between text-sm">
          <span>Backend offline — start the API server (<code className="font-mono">make api</code>)</span>
          <button
            onClick={() => setOfflineDismissed(true)}
            className="ml-4 text-yellow-200 hover:text-white"
          >
            ✕
          </button>
        </div>
      )}

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

      <main className="flex-1 min-w-0 flex flex-col overflow-hidden border-x border-zinc-700">
        {selectedMeeting ? (
          <MeetingDetail
            meeting={selectedMeeting}
            onDelete={handleDelete}
            onMeetingUpdated={(updated) =>
              setMeetings((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
            }
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">
            {meetings.length === 0 ? "No meetings yet. Upload one to get started." : "Select a meeting"}
          </div>
        )}
      </main>

      <CrossMeetingPanel />
    </div>
  );
}
