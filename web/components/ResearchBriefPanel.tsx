"use client";

import { useState } from "react";
import type { ResearchBrief } from "@/lib/types";

export function ResearchBriefPanel({ brief }: { brief: ResearchBrief }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-lg border border-border bg-panel/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between p-3 text-left"
      >
        <h2 className="text-sm font-semibold text-muted">Research brief</h2>
        <span className="text-xs text-muted">{open ? "▲ hide" : "▼ show"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3 text-sm">
          <Field label="Topic" value={brief.topic} />
          <Field label="Audience" value={brief.audience} />
          <Field label="Tone" value={brief.tone} />
          <div>
            <p className="text-xs uppercase tracking-wider text-muted mb-1">Key points</p>
            <ul className="list-disc list-inside space-y-1">
              {brief.key_points.map((kp, i) => (
                <li key={i} className="text-slate-200">{kp}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-muted mb-1">Hook ideas</p>
            <ul className="list-disc list-inside space-y-1">
              {brief.hook_ideas.map((h, i) => (
                <li key={i} className="text-slate-200 italic">{h}</li>
              ))}
            </ul>
          </div>
          <Field label="Call to action" value={brief.call_to_action} />
        </div>
      )}
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wider text-muted mb-1">{label}</p>
      <p className="text-slate-200">{value}</p>
    </div>
  );
}
