"use client";

import { useEffect, useRef, useState } from "react";
import { api, ActionItem, Decision, Topic } from "@/lib/api";
import { useToast } from "@/lib/toast";

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4 text-zinc-500" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

interface Props {
  meetingId: string;
}

export default function OverviewTab({ meetingId }: Props) {
  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const { addToast } = useToast();

  const actionRef = useRef<HTMLDivElement>(null);
  const decisionRef = useRef<HTMLDivElement>(null);
  const topicRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.getActionItems(meetingId),
      api.getDecisions(meetingId),
      api.getTopics(meetingId),
    ])
      .then(([a, d, t]) => {
        setActionItems(a);
        setDecisions(d);
        setTopics(t);
      })
      .catch((e) => addToast(`Failed to load overview: ${e.message}`))
      .finally(() => setLoading(false));
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-6 py-8 text-zinc-500 text-sm">
        <Spinner /> Loading…
      </div>
    );
  }

  const scroll = (ref: React.RefObject<HTMLDivElement | null>) =>
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div className="px-6 py-6 space-y-8">
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Action Items", count: actionItems.length, ref: actionRef },
          { label: "Decisions", count: decisions.length, ref: decisionRef },
          { label: "Topics", count: topics.length, ref: topicRef },
        ].map(({ label, count, ref }) => (
          <button
            key={label}
            onClick={() => scroll(ref)}
            className="bg-zinc-900 border border-zinc-700 rounded-lg p-4 text-left hover:border-zinc-500 transition-colors"
          >
            <p className="text-2xl font-bold text-zinc-100">{count}</p>
            <p className="text-xs text-zinc-500 mt-0.5">{label}</p>
          </button>
        ))}
      </div>

      <div ref={actionRef}>
        <h3 className="text-sm font-semibold text-zinc-300 mb-3">Action Items</h3>
        {actionItems.length === 0 ? (
          <p className="text-xs text-zinc-600">None identified.</p>
        ) : (
          <div className="space-y-2">
            {actionItems.map((item, i) => (
              <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3">
                <p className="text-sm text-zinc-200">{item.text}</p>
                <div className="flex items-center gap-3 mt-1.5 text-xs text-zinc-500">
                  {item.assignee && <span>👤 {item.assignee}</span>}
                  {item.due_date && <span>📅 {item.due_date}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div ref={decisionRef}>
        <h3 className="text-sm font-semibold text-zinc-300 mb-3">Decisions</h3>
        {decisions.length === 0 ? (
          <p className="text-xs text-zinc-600">None identified.</p>
        ) : (
          <div className="space-y-2">
            {decisions.map((d, i) => (
              <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3">
                <p className="text-sm text-zinc-200">{d.text}</p>
                {d.context && <p className="text-xs text-zinc-500 mt-1.5">{d.context}</p>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div ref={topicRef}>
        <h3 className="text-sm font-semibold text-zinc-300 mb-3">Topics</h3>
        {topics.length === 0 ? (
          <p className="text-xs text-zinc-600">None identified.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {topics.map((t, i) => (
              <span
                key={i}
                className="px-3 py-1 rounded-full bg-zinc-800 border border-zinc-700 text-xs text-zinc-300"
              >
                {t.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
