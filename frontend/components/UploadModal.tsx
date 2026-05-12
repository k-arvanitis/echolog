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
    <svg className="h-4 w-4 animate-spin text-ink-400" fill="none" viewBox="0 0 24 24">
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40">
      <div className="w-[480px] rounded-lg border border-ink-200 bg-surface p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink-800">Upload meeting</h2>
          <button onClick={onClose} className="text-lg leading-none text-ink-400 hover:text-ink-700">
            ✕
          </button>
        </div>

        <div
          onDrop={onDrop}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onClick={() => inputRef.current?.click()}
          className={`mb-4 cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
            dragging ? "border-brand bg-ink-100" : "border-ink-200 hover:border-ink-300"
          }`}
        >
          <input ref={inputRef} type="file" accept={ACCEPTED_EXT} className="hidden" onChange={onFileChange} />
          {file ? (
            <div>
              <p className="text-sm font-medium text-ink-800">{file.name}</p>
              <p className="mt-1 text-[11px] text-ink-400">{(file.size / 1_048_576).toFixed(1)} MB</p>
            </div>
          ) : (
            <div>
              <p className="text-sm text-ink-600">Drag &amp; drop or click to browse</p>
              <p className="mt-1 text-[11px] text-ink-400">mp3, mp4, wav, m4a, ogg</p>
            </div>
          )}
        </div>

        <div className="mb-4">
          <label className="mb-1 block text-[11px] font-medium text-ink-500">Title</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Meeting title"
            className="w-full rounded-md border border-ink-200 bg-ink-50 px-3 py-2 text-sm text-ink-800 placeholder-ink-400 focus:border-brand focus:outline-none"
          />
        </div>

        {error && (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">{error}</div>
        )}

        {phase === "processing" && (
          <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <Spinner />
            <span>Processing audio — this may take a few minutes…</span>
          </div>
        )}

        {phase === "ready" && (
          <div className="mb-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
            Meeting is ready!
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md border border-ink-200 bg-surface px-3 py-1.5 text-xs text-ink-700 hover:bg-ink-100"
          >
            Cancel
          </button>
          <button
            onClick={startUpload}
            disabled={!canUpload}
            className="flex items-center gap-2 rounded-md bg-brand px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy && <Spinner />}
            {phaseLabel[phase]}
          </button>
        </div>
      </div>
    </div>
  );
}
