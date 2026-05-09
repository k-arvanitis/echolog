"use client";

import { useCallback, useRef, useState } from "react";
import { api, Meeting } from "@/lib/api";

interface Props {
  onClose: () => void;
  onUploaded: (m: Meeting) => void;
  onMeetingUpdated: (m: Meeting) => void;
}

const ACCEPTED_EXT = ".mp3,.mp4,.wav,.m4a,.ogg";

type Phase = "idle" | "uploading" | "processing" | "ready" | "failed";

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4 text-zinc-400" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

export default function UploadModal({ onClose, onUploaded, onMeetingUpdated }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleFile = (f: File) => {
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
    setError(null);
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [title]); // eslint-disable-line react-hooks/exhaustive-deps

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
  };

  const startUpload = async () => {
    if (!file || !title.trim()) return;
    setPhase("uploading");
    setError(null);
    try {
      const meeting = await api.uploadMeeting(file, title.trim());
      onUploaded(meeting);
      setPhase("processing");

      pollRef.current = setInterval(async () => {
        try {
          const updated = await api.getMeeting(meeting.id);
          onMeetingUpdated(updated);
          if (updated.status !== "processing") {
            clearInterval(pollRef.current!);
            setPhase(updated.status as Phase);
            if (updated.status === "ready") {
              setTimeout(onClose, 800);
            }
          }
        } catch {
          // keep polling
        }
      }, 3000);
    } catch (e) {
      setPhase("failed");
      setError((e as Error).message);
    }
  };

  const phaseLabel: Record<Phase, string> = {
    idle: "Upload",
    uploading: "Uploading…",
    processing: "Processing…",
    ready: "Ready!",
    failed: "Retry",
  };

  const busy = phase === "uploading" || phase === "processing";
  const canUpload = !!file && title.trim().length > 0 && !busy && phase !== "ready";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg w-[480px] p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-zinc-100">Upload Meeting</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200 text-lg leading-none">✕</button>
        </div>

        <div
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors mb-4 ${
            dragging ? "border-zinc-400 bg-zinc-800" : "border-zinc-700 hover:border-zinc-500"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXT}
            className="hidden"
            onChange={onFileChange}
          />
          {file ? (
            <div>
              <p className="text-sm font-medium text-zinc-100">{file.name}</p>
              <p className="text-xs text-zinc-500 mt-1">{(file.size / 1_048_576).toFixed(1)} MB</p>
            </div>
          ) : (
            <div>
              <p className="text-sm text-zinc-400">Drag & drop or click to browse</p>
              <p className="text-xs text-zinc-600 mt-1">mp3, mp4, wav, m4a, ogg</p>
            </div>
          )}
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-zinc-400 mb-1">Title</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Meeting title"
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
          />
        </div>

        {error && (
          <p className="text-xs text-red-400 mb-3">{error}</p>
        )}

        {phase === "processing" && (
          <div className="flex items-center gap-2 text-xs text-yellow-400 mb-3">
            <Spinner />
            <span>Processing audio — this may take a few minutes…</span>
          </div>
        )}

        {phase === "ready" && (
          <p className="text-xs text-green-400 mb-3">Meeting is ready!</p>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={startUpload}
            disabled={!canUpload}
            className="px-4 py-2 text-sm rounded bg-zinc-200 hover:bg-white text-zinc-900 font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {busy && <Spinner />}
            {phaseLabel[phase]}
          </button>
        </div>
      </div>
    </div>
  );
}
