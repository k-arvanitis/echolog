"use client";

import { useRef, useState } from "react";
import { api, QueryResponse } from "@/lib/api";
import { useToast } from "@/lib/toast";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: QueryResponse["sources"];
}

function SourceCard({ source }: { source: QueryResponse["sources"][number] }) {
  return (
    <div className="rounded-md border border-ink-200 bg-surface px-2.5 py-2 text-[11px]">
      <p className="mb-0.5 truncate font-medium text-ink-700">{source.meeting_title}</p>
      {source.speaker && <p className="mb-0.5 text-ink-500">{source.speaker}</p>}
      <p className="leading-relaxed text-ink-600">{source.chunk_text}</p>
      <p className="mt-1 font-mono text-ink-400">Score: {source.score.toFixed(3)}</p>
    </div>
  );
}

function AssistantMessage({ msg }: { msg: Message }) {
  const [showSources, setShowSources] = useState(false);
  return (
    <div className="flex flex-col items-start space-y-1.5">
      <div className="whitespace-pre-wrap rounded-2xl border border-ink-200 bg-surface px-4 py-2 text-xs leading-relaxed text-ink-800">
        {msg.content}
      </div>
      {msg.sources && msg.sources.length > 0 && (
        <div className="w-full">
          <button
            onClick={() => setShowSources((v) => !v)}
            className="text-[11px] text-brand-dark hover:underline"
          >
            {showSources ? "Hide" : "Show"} {msg.sources.length} source{msg.sources.length !== 1 ? "s" : ""}
          </button>
          {showSources && (
            <div className="mt-1.5 space-y-1.5">
              {msg.sources.map((s, i) => (
                <SourceCard key={i} source={s} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function CrossMeetingPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const { addToast } = useToast();

  const submit = async () => {
    const q = query.trim();
    if (!q || loading) return;
    setQuery("");
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setLoading(true);
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);

    try {
      const res = await api.queryCross(q);
      setMessages((prev) => [...prev, { role: "assistant", content: res.answer, sources: res.sources }]);
    } catch (e) {
      addToast(`Cross-meeting query failed: ${(e as Error).message}`);
      setMessages((prev) => [...prev, { role: "assistant", content: "Sorry, something went wrong." }]);
    } finally {
      setLoading(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <aside className="flex w-[320px] flex-shrink-0 flex-col border-l border-ink-200 bg-ink-50">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-ink-100 px-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Ask across all meetings</p>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <p className="mt-6 text-center text-xs text-ink-400">Ask anything across your meeting history.</p>
        )}
        {messages.map((msg, i) =>
          msg.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-brand px-4 py-2 text-xs text-white">
                {msg.content}
              </div>
            </div>
          ) : (
            <div key={i}>
              <AssistantMessage msg={msg} />
            </div>
          )
        )}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-ink-400">
            <span className="h-2 w-12 animate-pulse rounded-full bg-ink-200" /> Searching…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex flex-shrink-0 items-end gap-2 border-t border-ink-200 px-3 py-3">
        <textarea
          rows={1}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask across all meetings…"
          className="max-h-28 min-h-[36px] flex-1 resize-none rounded-md border border-ink-200 bg-ink-50 px-3 py-2 text-xs text-ink-800 placeholder-ink-400 focus:border-brand focus:outline-none"
        />
        <button
          onClick={submit}
          disabled={!query.trim() || loading}
          className="flex-shrink-0 rounded-md bg-brand px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </aside>
  );
}
