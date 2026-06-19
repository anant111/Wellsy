"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { cancelJob, deleteJob, retryJob } from "@/lib/api";
import type { Job } from "@/lib/types";

export function JobActions({ job, onAction }: { job: Job; onAction?: () => void }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function withBusy(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      onAction?.();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const isRunning = job.status === "running";
  const isAwaiting = job.status === "awaiting_idea" || job.status === "awaiting_score";
  const isDone = job.status === "succeeded" || job.status === "failed" || job.status === "canceled";

  return (
    <div className="flex items-center gap-2">
      {job.status === "awaiting_idea" && (
        <a
          href="#ideas"
          className="text-xs px-3 py-1 rounded border border-amber-700 text-amber-300 hover:bg-amber-900/30"
        >
          Choose idea ↓
        </a>
      )}
      {job.status === "awaiting_score" && (
        <a
          href="#score"
          className="text-xs px-3 py-1 rounded border border-indigo-700 text-indigo-300 hover:bg-indigo-900/30"
        >
          Review score ↓
        </a>
      )}
      {(isRunning || isAwaiting) && (
        <button
          disabled={busy}
          onClick={() => withBusy(() => cancelJob(job.id))}
          className="text-xs px-3 py-1 rounded border border-rose-700 text-rose-300 hover:bg-rose-900/30 disabled:opacity-50"
        >
          Cancel
        </button>
      )}
      {isDone && job.status !== "succeeded" && (
        <button
          disabled={busy}
          onClick={async () => {
            const { id } = await retryJob(job.id);
            router.push(`/jobs/${id}`);
          }}
          className="text-xs px-3 py-1 rounded border border-amber-700 text-amber-300 hover:bg-amber-900/30 disabled:opacity-50"
        >
          Retry
        </button>
      )}
      {job.status === "succeeded" && (
        <button
          disabled={busy}
          onClick={async () => {
            const { id } = await retryJob(job.id);
            router.push(`/jobs/${id}`);
          }}
          className="text-xs px-3 py-1 rounded border border-indigo-700 text-indigo-300 hover:bg-indigo-900/30 disabled:opacity-50"
        >
          Re-run
        </button>
      )}
      <button
        disabled={busy || isRunning || isAwaiting}
        onClick={() =>
          withBusy(async () => {
            await deleteJob(job.id);
            router.refresh();
          })
        }
        className="text-xs px-3 py-1 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
      >
        Delete
      </button>
    </div>
  );
}
