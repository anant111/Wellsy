"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listJobs } from "@/lib/api";
import { JobCard } from "@/components/JobCard";
import type { Job, JobStatus } from "@/lib/types";

const FILTERS: Array<{ key: "all" | JobStatus; label: string }> = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "succeeded", label: "Succeeded" },
  { key: "failed", label: "Failed" },
  { key: "canceled", label: "Canceled" },
];

export default function LibraryPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | JobStatus>("all");

  async function refresh() {
    try {
      const data = await listJobs();
      setJobs(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // Refresh every 5s for live status
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const filtered = filter === "all" ? jobs : jobs.filter((j) => j.status === filter);

  return (
    <main className="max-w-5xl mx-auto p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Library</h1>
        <Link
          href="/new"
          className="bg-accent hover:bg-indigo-500 text-white text-sm font-medium px-4 py-2 rounded-md"
        >
          + New generation
        </Link>
      </div>

      <div className="flex items-center gap-2 mb-5">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`text-xs px-3 py-1 rounded-full border ${
              filter === f.key
                ? "border-accent bg-accent/15 text-white"
                : "border-border text-muted hover:text-white"
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted">
          {jobs.length} job{jobs.length === 1 ? "" : "s"}
        </span>
      </div>

      {loading ? (
        <p className="text-muted text-sm">Loading…</p>
      ) : filtered.length === 0 ? (
        <p className="text-muted text-sm">
          {jobs.length === 0 ? "No jobs yet. Start one →" : "No jobs match this filter."}
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {filtered.map((j) => <JobCard key={j.id} job={j} onAction={refresh} />)}
        </div>
      )}
    </main>
  );
}
