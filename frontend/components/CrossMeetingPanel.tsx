"use client";

import { useRef, useState } from "react";
import { api, QueryResponse } from "@/lib/api";
import { useToast } from "@/lib/toast";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: QueryResponse["sources"];
}

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4 text-zinc-400" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

function SourceCard({ source }: { source: QueryResponse["sources"][number] }) {
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-xs">
      <p className="text-zinc-400 font-medium mb-0.5 truncate">{source.meeting_title}</p>
      {source.speaker && (
        <p className="text-zinc-500 mb-0.5">{source.speaker}</p>
      )}
      <p className="text-zinc-300 leading-relaxed">{source.chunk_text}</p>
      <p className="text-zinc-600 mt-1">Score: {source.score.toFixed(3)}</p>
    </div>
  );
}

function AssistantMessage({ msg }: { msg: Message }) {
  const [showSources, setShowSources] = useState(false);
  return (
    <div className="space-y-1.5">
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2.5 text-xs text-zinc-200 leading-relaxed">
        {msg.content}
      </div>
      {msg.sources && msg.sources.length > 0 && (
        <div>
          <button
            onClick={() => setShowSources((v) => !v)}
            className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
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
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.answer, sources: res.sources },
      ]);
    } catch (e) {
      addToast(`Cross-meeting query failed: ${(e as Error).message}`);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, something went wrong." },
      ]);
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
    <aside className="w-[320px] flex-shrink-0 flex flex-col h-full bg-zinc-900 border-l border-zinc-700">
      <div className="flex-shrink-0 px-4 py-4 border-b border-zinc-700">
        <p className="text-xs font-semibold text-zinc-300">Ask Across All Meetings</p>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-xs text-zinc-600 text-center mt-6">
            Ask anything across your meeting history.
          </p>
        )}
        {messages.map((msg, i) =>
          msg.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="bg-zinc-700 rounded-lg px-3 py-2 text-xs text-zinc-100 max-w-[85%]">
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
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <Spinner /> Searching…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex-shrink-0 border-t border-zinc-700 px-3 py-3 flex items-end gap-2">
        <textarea
          rows={1}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask across all meetings…"
          className="flex-1 resize-none bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500 min-h-[36px] max-h-28"
        />
        <button
          onClick={submit}
          disabled={!query.trim() || loading}
          className="px-3 py-2 text-xs rounded-lg bg-zinc-200 hover:bg-white text-zinc-900 font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
        >
          Send
        </button>
      </div>
    </aside>
  );
}
