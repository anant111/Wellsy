"use client";

import { useEffect, useState } from "react";
import { resolveScore } from "@/lib/api";
import type { SelfScore } from "@/lib/types";

interface Props {
  jobId: string;
  score: SelfScore;
  threshold: number;
  autoAcceptSeconds: number;
}

const AXIS_META: { key: keyof SelfScore; label: string; emoji: string; what: string; goodSign: string }[] = [
  {
    key: "hook",
    label: "Hook",
    emoji: "🎣",
    what: "Do the first 1-2 seconds grab the viewer and make them keep watching?",
    goodSign: "Movement, contrast, an unexpected visual, or a bold voiceover line that lands in <2s.",
  },
  {
    key: "story",
    label: "Story",
    emoji: "📖",
    what: "Is there a clear narrative arc: setup → tension → resolution across the whole video?",
    goodSign: "A clear before/after, a problem that's introduced and answered, or a question that builds to a payoff.",
  },
  {
    key: "momentum",
    label: "Momentum",
    emoji: "⚡",
    what: "Does the pacing keep you watching without dead air, repetition, or jarring jumps?",
    goodSign: "Each scene flows into the next, cuts feel motivated, and the energy stays consistent (or escalates).",
  },
  {
    key: "emotional_linkage",
    label: "Emotional linkage",
    emoji: "🔗",
    what: "Does the emotional thread (visual + voice + music) carry the viewer from one scene to the next?",
    goodSign: "You feel the same mood or escalating mood throughout — no whiplash between scenes.",
  },
  {
    key: "closing",
    label: "Closing",
    emoji: "🎬",
    what: "Does the ending deliver the call to action and feel like a satisfying conclusion (not a hard stop)?",
    goodSign: "The CTA is clear, the final frame resolves the visual story, and the video doesn't end mid-action.",
  },
];

function scoreColor(s: number, threshold: number): string {
  if (s >= 8) return "bg-emerald-500";
  if (s >= threshold) return "bg-amber-500";
  return "bg-rose-500";
}

function AxisRow({
  meta,
  value,
  threshold,
}: { meta: typeof AXIS_META[number]; value: number; threshold: number }) {
  const [open, setOpen] = useState(false);
  const pct = Math.max(0, Math.min(100, value * 10));
  const below = value < threshold;
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 text-xs text-left"
        aria-expanded={open}
        aria-label={`${meta.label} — ${value} out of 10. Click to see what this means.`}
      >
        <div className="w-32 text-muted flex items-center gap-1.5">
          <span>{meta.emoji}</span>
          <span className={below ? "text-rose-300" : "text-slate-200"}>{meta.label}</span>
        </div>
        <div className="flex-1 h-2 rounded-full bg-bg overflow-hidden border border-border">
          <div
            className={`h-full ${scoreColor(value, threshold)} transition-all`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className={`w-8 text-right tabular-nums ${below ? "text-rose-300" : "text-emerald-300"}`}>
          {value}/10
        </div>
        <span className="text-muted text-[10px]">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="ml-[8.5rem] mt-1 text-[11px] text-muted leading-relaxed bg-bg/50 border border-border rounded p-2">
          <p>
            <strong className="text-slate-200">What this measures:</strong> {meta.what}
          </p>
          <p className="mt-1">
            <strong className="text-emerald-300">A 8+ looks like:</strong> {meta.goodSign}
          </p>
        </div>
      )}
    </div>
  );
}

/** Self-score panel shown when the pipeline pauses to ask the user
 *  whether to accept the Gemini-generated self-score or retry. */
export function SelfScorePanel({ jobId, score, threshold, autoAcceptSeconds }: Props) {
  const [secondsLeft, setSecondsLeft] = useState(autoAcceptSeconds);
  const [action, setAction] = useState<"accept" | "retry" | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (action) return;
    if (secondsLeft <= 0) {
      handleAction("accept");
      return;
    }
    const t = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secondsLeft, action]);

  async function handleAction(a: "accept" | "retry") {
    if (action || submitting) return;
    setAction(a);
    setSubmitting(true);
    try {
      await resolveScore(jobId, a);
    } catch (e) {
      alert((e as Error).message);
      setAction(null);
    } finally {
      setSubmitting(false);
    }
  }

  if (action) {
    return (
      <section className="rounded-lg border border-accent/50 bg-accent/10 p-4">
        <p className="text-sm text-accent">
          {action === "accept" ? "✓ Score accepted." : "↻ Re-generating with feedback…"}
        </p>
      </section>
    );
  }

  const scoringFailed = score.one_line_verdict?.toLowerCase().includes("scoring failed");
  const closingTip = score.closing != null && score.closing < 5
    ? "The closing landed low. On retry, the model will be told to make the final scene 7-8s with a settled hold and an explicit CTA. If you 'Try again', the entire clip chain will regenerate."
    : null;

  return (
    <section className="rounded-lg border border-indigo-700/50 bg-indigo-900/10 p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-indigo-200">
          ✨ Self-score review
        </h2>
        <span className="text-xs text-indigo-300/80">
          auto-accepting in {secondsLeft}s
        </span>
      </div>
      <p className="text-[11px] text-muted mb-3">
        Gemini watched the final video and graded it on 5 axes. Click any
        axis to see what it means. You can accept and post, or try again to
        regenerate with feedback.
      </p>

      {/* 5-axis bars */}
      <div className="space-y-2 mb-4">
        {AXIS_META.map(({ key, ...meta }) => {
          const v = (score[key] as number) ?? 0;
          return <AxisRow key={key} meta={meta as typeof AXIS_META[number]} value={v} threshold={threshold} />;
        })}
      </div>

      <div className="flex items-baseline justify-between mb-3">
        <div className="text-xs text-muted">
          Total: <span className="text-slate-200 font-medium">{score.total}/50</span>
          {" · "}
          Threshold: <span className="text-slate-200">{threshold}/axis</span>
        </div>
      </div>

      {scoringFailed ? (
        <div className="text-xs text-amber-300/90 mb-4 bg-amber-900/20 border border-amber-700/40 rounded p-2">
          ⚠ Gemini could not analyse the video in this run (transient Files API
          state). The 5/5/5/5/5 default is a neutral placeholder. You can
          still accept the video, or "Try again" to re-upload and re-score.
        </div>
      ) : (
        <>
          {score.one_line_strength && (
            <p className="text-xs text-emerald-300/90 mb-1">
              <strong>Strength:</strong> {score.one_line_strength}
            </p>
          )}
          {score.one_line_verdict && (
            <p className="text-xs text-amber-300/90 mb-4">
              <strong>What to fix first:</strong> {score.one_line_verdict}
            </p>
          )}
        </>
      )}

      {closingTip && !scoringFailed && (
        <div className="rounded-md border border-rose-700/40 bg-rose-900/20 p-2 mb-3 text-[11px] text-rose-200/90">
          <strong>💡 Tip for retry:</strong> {closingTip}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => handleAction("accept")}
          disabled={submitting}
          className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-2 rounded-md disabled:opacity-50"
        >
          ✓ Accept — publish
        </button>
        <button
          onClick={() => handleAction("retry")}
          disabled={submitting}
          className="flex-1 bg-rose-700 hover:bg-rose-600 text-white text-sm font-medium px-4 py-2 rounded-md disabled:opacity-50"
        >
          ↻ Try again — regenerate
        </button>
      </div>
      <p className="text-[10px] text-muted mt-2">
        Note: "Try again" fully re-runs the clip + compose + score stages
        (research and scenes are kept). It typically takes 1-3 minutes.
      </p>
    </section>
  );
}
