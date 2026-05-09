"use client";

import { useEffect, useState } from "react";
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

export default function AnalyticsTab({ meetingId }: Props) {
  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const { addToast } = useToast();

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
      .catch((e) => addToast(`Failed to load analytics: ${e.message}`))
      .finally(() => setLoading(false));
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-6 py-8 text-zinc-500 text-sm">
        <Spinner /> Loading…
      </div>
    );
  }

  return (
    <div className="px-6 py-6 space-y-10">
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Action Items", count: actionItems.length },
          { label: "Decisions", count: decisions.length },
          { label: "Topics", count: topics.length },
        ].map(({ label, count }) => (
          <div
            key={label}
            className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 text-center"
          >
            <p className="text-3xl font-bold text-zinc-100">{count}</p>
            <p className="text-xs text-zinc-500 mt-1">{label}</p>
          </div>
        ))}
      </div>

      <section>
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider mb-4">
          Action Items
        </h2>
        {actionItems.length === 0 ? (
          <p className="text-xs text-zinc-600">None identified.</p>
        ) : (
          <div className="space-y-3">
            {actionItems.map((item, i) => (
              <div key={i} className="flex gap-3">
                <span className="flex-shrink-0 text-xs text-zinc-600 font-mono w-5 mt-0.5">{i + 1}.</span>
                <div>
                  <p className="text-sm text-zinc-200">{item.text}</p>
                  <div className="flex items-center gap-3 mt-1 text-xs text-zinc-500">
                    {item.assignee && <span>Assignee: {item.assignee}</span>}
                    {item.due_date && <span>Due: {item.due_date}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider mb-4">
          Decisions
        </h2>
        {decisions.length === 0 ? (
          <p className="text-xs text-zinc-600">None identified.</p>
        ) : (
          <div className="space-y-4">
            {decisions.map((d, i) => (
              <div key={i} className="border-l-2 border-zinc-700 pl-4">
                <p className="text-sm text-zinc-200">{d.text}</p>
                {d.context && (
                  <p className="text-xs text-zinc-500 mt-1.5 italic">{d.context}</p>
                )}
                {d.stakeholders && d.stakeholders.length > 0 && (
                  <p className="text-xs text-zinc-600 mt-1">
                    Stakeholders: {d.stakeholders.join(", ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider mb-4">
          Topics Covered
        </h2>
        {topics.length === 0 ? (
          <p className="text-xs text-zinc-600">None identified.</p>
        ) : (
          <div className="space-y-2">
            {topics.map((t, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="px-3 py-1 rounded-full bg-zinc-800 border border-zinc-700 text-xs text-zinc-300">
                  {t.name}
                </span>
                {t.start_time != null && t.end_time != null && (
                  <span className="text-xs text-zinc-600 font-mono">
                    {Math.floor(t.start_time / 60)}:{String(Math.floor(t.start_time % 60)).padStart(2, "0")}
                    {" – "}
                    {Math.floor(t.end_time / 60)}:{String(Math.floor(t.end_time % 60)).padStart(2, "0")}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
