"use client";

import Link from "next/link";
import type { Job } from "@/lib/types";
import { StatusPill } from "./StatusPill";
import { JobActions } from "./JobActions";

export function JobCard({ job, onAction }: { job: Job; onAction?: () => void }) {
  return (
    <div className="rounded-lg border border-border bg-panel p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <Link href={`/jobs/${job.id}`} className="flex-1 min-w-0">
          <p className="text-sm text-white line-clamp-2 leading-relaxed">{job.prompt}</p>
        </Link>
        <StatusPill status={job.status} />
      </div>
      <div className="flex items-center justify-between text-xs text-muted">
        <div className="flex items-center gap-3">
          <span>{job.duration}s</span>
          <span>·</span>
          <span>{job.orientation}</span>
          <span>·</span>
          <span className="capitalize">{job.style}</span>
          {job.current_stage && (
            <>
              <span>·</span>
              <span className="text-amber-400">running: {job.current_stage}</span>
            </>
          )}
        </div>
        <span>{new Date(job.created_at).toLocaleString()}</span>
      </div>
      <div className="flex justify-end">
        <JobActions job={job} onAction={onAction} />
      </div>
    </div>
  );
}
