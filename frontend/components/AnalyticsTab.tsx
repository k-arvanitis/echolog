"use client";

import { useEffect, useState } from "react";
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

function fmtRange(start: number, end: number) {
  const f = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  return `${f(start)} – ${f(end)}`;
}

export default function AnalyticsTab({ meetingId }: Props) {
  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const { addToast } = useToast();

  useEffect(() => {
    setLoading(true);
    Promise.all([api.getActionItems(meetingId), api.getDecisions(meetingId), api.getTopics(meetingId)])
      .then(([a, d, t]) => {
        setActionItems(a);
        setDecisions(d);
        setTopics(t);
      })
      .catch((e) => addToast(`Failed to load analytics: ${e.message}`))
      .finally(() => setLoading(false));
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-6 py-8 text-sm text-ink-400">
        <Spinner /> Loading…
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Action items", count: actionItems.length },
          { label: "Decisions", count: decisions.length },
          { label: "Topics", count: topics.length },
        ].map(({ label, count }) => (
          <div key={label} className="rounded-lg border border-ink-200 bg-surface p-3 text-center">
            <p className="text-2xl font-bold text-ink-800">{count}</p>
            <p className="mt-0.5 text-[11px] text-ink-500">{label}</p>
          </div>
        ))}
      </div>

      <section className="rounded-lg border border-ink-200 bg-surface">
        <div className="border-b border-ink-100 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Action items</p>
        </div>
        <div className="space-y-2 p-3">
          {actionItems.length === 0 ? (
            <p className="text-xs text-ink-400">None identified.</p>
          ) : (
            actionItems.map((item, i) => (
              <div key={i} className="flex gap-3 text-xs">
                <span className="mt-0.5 w-5 flex-shrink-0 font-mono text-ink-400">{i + 1}.</span>
                <div>
                  <p className="text-ink-800">{item.text}</p>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-500">
                    {item.assignee && <span>Assignee: {item.assignee}</span>}
                    {item.due_date && <span>Due: {item.due_date}</span>}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-lg border border-ink-200 bg-surface">
        <div className="border-b border-ink-100 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Decisions</p>
        </div>
        <div className="space-y-2 p-3">
          {decisions.length === 0 ? (
            <p className="text-xs text-ink-400">None identified.</p>
          ) : (
            decisions.map((d, i) => (
              <div key={i} className="border-l-2 border-ink-200 pl-3 text-xs">
                <p className="text-ink-800">{d.text}</p>
                {d.context && <p className="mt-0.5 italic text-ink-500">{d.context}</p>}
                {d.stakeholders && d.stakeholders.length > 0 && (
                  <p className="mt-0.5 text-[11px] text-ink-400">Stakeholders: {d.stakeholders.join(", ")}</p>
                )}
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-lg border border-ink-200 bg-surface">
        <div className="border-b border-ink-100 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Topics covered</p>
        </div>
        <div className="space-y-1.5 p-3">
          {topics.length === 0 ? (
            <p className="text-xs text-ink-400">None identified.</p>
          ) : (
            topics.map((t, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] text-ink-600">{t.name}</span>
                {t.start_time != null && t.end_time != null && (
                  <span className="font-mono text-[11px] text-ink-400">{fmtRange(t.start_time, t.end_time)}</span>
                )}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
