"use client";

import { useEffect, useRef, useState } from "react";
import { api, ActionItem, Decision, Topic } from "@/lib/api";
import { useToast } from "@/lib/toast";

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin text-ink-400" fill="none" viewBox="0 0 24 24">
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
    Promise.all([api.getActionItems(meetingId), api.getDecisions(meetingId), api.getTopics(meetingId)])
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
      <div className="flex items-center gap-2 px-6 py-8 text-sm text-ink-400">
        <Spinner /> Loading…
      </div>
    );
  }

  const scroll = (ref: React.RefObject<HTMLDivElement | null>) =>
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div className="space-y-3 p-3">
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Action items", count: actionItems.length, ref: actionRef },
          { label: "Decisions", count: decisions.length, ref: decisionRef },
          { label: "Topics", count: topics.length, ref: topicRef },
        ].map(({ label, count, ref }) => (
          <button
            key={label}
            onClick={() => scroll(ref)}
            className="rounded-lg border border-ink-200 bg-surface p-3 text-left transition-colors hover:bg-ink-100"
          >
            <p className="text-2xl font-bold text-ink-800">{count}</p>
            <p className="mt-0.5 text-[11px] text-ink-500">{label}</p>
          </button>
        ))}
      </div>

      <div ref={actionRef} className="rounded-lg border border-ink-200 bg-surface">
        <div className="border-b border-ink-100 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Action items</p>
        </div>
        <div className="space-y-1.5 p-3">
          {actionItems.length === 0 ? (
            <p className="text-xs text-ink-400">None identified.</p>
          ) : (
            actionItems.map((item, i) => (
              <div key={i} className="rounded-md border border-ink-100 p-2.5 text-xs">
                <p className="text-ink-800">{item.text}</p>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-500">
                  {item.assignee && <span>👤 {item.assignee}</span>}
                  {item.due_date && <span>📅 {item.due_date}</span>}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div ref={decisionRef} className="rounded-lg border border-ink-200 bg-surface">
        <div className="border-b border-ink-100 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Decisions</p>
        </div>
        <div className="space-y-1.5 p-3">
          {decisions.length === 0 ? (
            <p className="text-xs text-ink-400">None identified.</p>
          ) : (
            decisions.map((d, i) => (
              <div key={i} className="rounded-md border border-ink-100 p-2.5 text-xs">
                <p className="text-ink-800">{d.text}</p>
                {d.context && <p className="mt-1 text-[11px] text-ink-500">{d.context}</p>}
              </div>
            ))
          )}
        </div>
      </div>

      <div ref={topicRef} className="rounded-lg border border-ink-200 bg-surface">
        <div className="border-b border-ink-100 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Topics</p>
        </div>
        <div className="p-3">
          {topics.length === 0 ? (
            <p className="text-xs text-ink-400">None identified.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {topics.map((t, i) => (
                <span key={i} className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] text-ink-600">
                  {t.name}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
