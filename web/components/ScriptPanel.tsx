"use client";

import { useState } from "react";
import type { Idea, ScriptScene } from "@/lib/types";

export function ScriptPanel({
  scenes,
  chosenIdea,
}: {
  scenes: ScriptScene[];
  chosenIdea: Idea | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-lg border border-border bg-panel/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between p-3 text-left"
      >
        <h2 className="text-sm font-semibold text-muted">
          Scene script ({scenes.length} scenes)
        </h2>
        <span className="text-xs text-muted">{open ? "▲ hide" : "▼ show"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          {chosenIdea && (
            <div className="rounded border border-accent/30 bg-accent/5 p-3 mb-3">
              <p className="text-xs uppercase tracking-wider text-muted">Chosen idea</p>
              <p className="text-sm font-semibold text-accent mt-1">{chosenIdea.title}</p>
              <p className="text-xs text-muted mt-1">{chosenIdea.logline}</p>
            </div>
          )}
          {scenes
            .sort((a, b) => a.scene_id - b.scene_id)
            .map((s) => (
              <div key={s.scene_id} className="rounded border border-border p-3 bg-background/30">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-mono text-muted">scene {s.scene_id}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-panel text-muted">
                    {s.shot_type}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-panel text-muted">
                    {s.camera_angle}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-panel text-muted">
                    {s.lighting}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-panel text-muted">
                    {s.color_grading}
                  </span>
                </div>
                <p className="text-sm text-slate-100">
                  <span className="text-muted">🎙️</span> <em>{s.narration}</em>
                </p>
                <p className="text-xs text-muted mt-2">
                  <span className="text-slate-400">🎬 visual:</span> {s.visual_prompt}
                </p>
                {s.characters.length > 0 && (
                  <p className="text-xs text-muted mt-1">
                    <span className="text-slate-400">characters:</span> {s.characters.join(", ")}
                  </p>
                )}
                <p className="text-xs text-muted mt-1">
                  <span className="text-slate-400">audio voice:</span> {s.audio_prompt}
                </p>
              </div>
            ))}
        </div>
      )}
    </section>
  );
}
