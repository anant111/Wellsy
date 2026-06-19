"use client";

export function StatusPill({ status }: { status: string }) {
  const color = {
    queued: "bg-slate-700",
    running: "bg-amber-600 animate-pulse",
    awaiting_idea: "bg-amber-500",
    awaiting_score: "bg-indigo-600 animate-pulse",
    succeeded: "bg-emerald-700",
    failed: "bg-rose-700",
    canceled: "bg-slate-600",
    pending: "bg-slate-700",
    skipped: "bg-slate-700",
  }[status] ?? "bg-slate-700";
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${color} text-white capitalize`}>
      {status === "awaiting_idea" ? "awaiting idea"
        : status === "awaiting_score" ? "awaiting review"
        : status.replace(/_/g, " ")}
    </span>
  );
}
