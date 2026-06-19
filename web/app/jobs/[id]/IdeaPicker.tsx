"use client";

import { useEffect, useState } from "react";
import { selectIdea } from "@/lib/api";
import type { Idea } from "@/lib/types";

interface Props {
  jobId: string;
  ideas: Idea[];
  autoPickSeconds: number;
}

/** 3-card idea picker with a 30s auto-pick countdown. */
export function IdeaPicker({ jobId, ideas, autoPickSeconds }: Props) {
  const [secondsLeft, setSecondsLeft] = useState(autoPickSeconds);
  const [picked, setPicked] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Countdown — fires auto-pick when it hits 0
  useEffect(() => {
    if (picked) return;
    if (secondsLeft <= 0) {
      const defaultIdea = ideas[0]?.id ?? "idea-1";
      handlePick(defaultIdea);
      return;
    }
    const t = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secondsLeft, picked]);

  async function handlePick(ideaId: string) {
    if (picked || submitting) return;
    setPicked(ideaId);
    setSubmitting(true);
    try {
      await selectIdea(jobId, ideaId);
    } catch (e) {
      alert((e as Error).message);
      setPicked(null);
    } finally {
      setSubmitting(false);
    }
  }

  if (!picked && ideas[0]) {
    const defaultTitle = ideas[0].title;
    return (
      <section className="rounded-lg border border-amber-700/50 bg-amber-900/10 p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-amber-200">
            Choose a creative direction
          </h2>
          {!picked && (
            <span className="text-xs text-amber-300/80">
              auto-picking <em>{defaultTitle}</em> in {secondsLeft}s
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {ideas.map((idea) => {
            const isPicked = picked === idea.id;
            return (
              <button
                key={idea.id}
                disabled={!!picked || submitting}
                onClick={() => handlePick(idea.id)}
                className={`text-left p-4 rounded-lg border transition-colors ${
                  isPicked
                    ? "border-accent bg-accent/15"
                    : picked
                    ? "border-border bg-panel/40 opacity-50"
                    : "border-border bg-panel hover:border-accent hover:bg-panel/80"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold text-white">
                    {idea.title}
                  </p>
                  <span className="text-[10px] uppercase tracking-wider text-muted">
                    {idea.id}
                  </span>
                </div>
                <p className="text-xs text-muted mt-2 leading-relaxed">
                  {idea.logline}
                </p>
                <p className="text-xs mt-3">
                  <em className="text-slate-300">{idea.tone}</em>
                </p>
                <p className="text-xs mt-2 text-muted">
                  <span className="text-slate-400">Hook:</span> {idea.hook_angle}
                </p>
                <p className="text-xs mt-2 text-muted italic">
                  {idea.visual_seed}
                </p>
              </button>
            );
          })}
        </div>
      </section>
    );
  }

  // Already picked — show confirmation
  const chosen = ideas.find((i) => i.id === picked);
  return (
    <section className="rounded-lg border border-accent/50 bg-accent/10 p-4">
      <p className="text-sm text-accent">
        ✓ Selected: <strong>{chosen?.title ?? picked}</strong>. Pipeline
        is resuming…
      </p>
    </section>
  );
}
