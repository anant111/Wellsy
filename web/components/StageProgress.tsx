"use client";

import { useEffect, useState } from "react";
import { StatusPill } from "./StatusPill";
import { stageLabel } from "./MediaPreview";
import { getScript } from "@/lib/api";
import type { Job, JobStage, ScriptScene, StageName } from "@/lib/types";

interface Props {
  job: Job;
  stages: JobStage[];
}

/** Build the ordered stage list with their statuses. v2 pipeline:
 *  research → scenes → N images → 1 continuous clip (extension chain)
 *  → compose → self-score. Per-scene audio rows only when audio_mode=gemini_tts. */
function buildStageRows(job: Job, stages: JobStage[], script?: ScriptScene[]): Array<{ name: StageName; index: number; status: string; error?: string; outputPath?: string }> {
  // Scene count is now decided by the model (variable-duration per scene).
  // Prefer the actual scene count from the script; fall back to a 6s-per-scene
  // estimate for jobs that haven't generated scenes yet.
  const expectedScenes = script && script.length > 0
    ? script.length
    : Math.max(1, Math.ceil(job.duration / 6));
  const useGeminiTts = (job.audio_mode ?? "veo_native") === "gemini_tts";

  const rows: Array<{ name: StageName; index: number; status: string; error?: string; outputPath?: string }> = [];

  const pushRow = (name: StageName, index: number, realIndex = 0) => {
    const s = stages.find((x) => x.name === name && x.stage_index === realIndex);
    rows.push({
      name, index,
      status: s?.status ?? (job.status === "running" ? "pending" : "skipped"),
      outputPath: s?.output_path,
      error: s?.error,
    });
  };

  pushRow("research", 0);
  pushRow("scenes", 0);

  for (let i = 1; i <= expectedScenes; i++) {
    pushRow("image", i, i);
  }
  // Clip: now a single continuous row, not N
  pushRow("clip", 0, 0);

  if (useGeminiTts) {
    for (let i = 1; i <= expectedScenes; i++) {
      pushRow("audio", i, i);
    }
  }

  pushRow("compose", 0);
  pushRow("score", 0);

  return rows;
}

export function StageProgress({ job, stages }: Props) {
  const [script, setScript] = useState<ScriptScene[] | null>(null);
  // Poll the script endpoint so we know the per-scene duration breakdown.
  useEffect(() => {
    let cancel = false;
    const load = () => {
      getScript(job.id)
        .then((d) => { if (!cancel && d?.scenes?.length) setScript(d.scenes); })
        .catch(() => { /* 404 = not generated yet, fine */ });
    };
    load();
    const t = setInterval(load, 4000);
    return () => { cancel = true; clearInterval(t); };
  }, [job.id]);

  const rows = buildStageRows(job, stages, script ?? undefined);

  // Per-scene duration breakdown (only when the script is available)
  const durationBreakdown = script && script.length > 0
    ? script.map((s) => `${s.duration_seconds ?? 6}s`).join(" + ") + ` = ${
        script.reduce((a, s) => a + (s.duration_seconds ?? 6), 0)
      }s`
    : null;

  return (
    <div className="space-y-2">
      {durationBreakdown && (
        <div className="rounded-md border border-border bg-bg/40 px-3 py-2 text-[11px] text-muted">
          <span className="text-slate-300 font-medium">Per-scene timing:</span> {durationBreakdown}
          <span className="ml-2 text-[10px]">(target {job.duration}s, will trim)</span>
        </div>
      )}
      <div className="space-y-1.5">
        {rows.map((row) => {
          const isCurrent = job.current_stage === row.name && row.status === "running";
          return (
            <div
              key={`${row.name}-${row.index}`}
              className={`flex items-center gap-3 px-3 py-2 rounded-md border ${
                isCurrent
                  ? "border-accent bg-accent/5"
                  : "border-border bg-panel/50"
              }`}
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm">{stageLabel(row.name, row.index)}</p>
                {row.error && <p className="text-xs text-rose-400 truncate">{row.error}</p>}
              </div>
              <StatusPill status={row.status} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
