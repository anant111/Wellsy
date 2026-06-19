"use client";

import { useEffect, useRef, useState } from "react";
import type { StreamEvent, Job, JobStage } from "@/lib/types";

const PY = process.env.NEXT_PUBLIC_PY_BACKEND ?? "http://127.0.0.1:8765";

interface UseJobStreamResult {
  job: Job | null;
  stages: JobStage[];
  connected: boolean;
}

/**
 * Subscribe to a job's SSE stream and return the live job + stage state.
 * Reconnects on disconnect.
 */
export function useJobStream(jobId: string | null): UseJobStreamResult {
  const [job, setJob] = useState<Job | null>(null);
  const [stages, setStages] = useState<JobStage[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!jobId) return;
    // EventSource hits the Python backend directly (CORS allows localhost:3000)
    const url = `${PY}/api/jobs/${jobId}/stream`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      try {
        const evt: StreamEvent = JSON.parse(e.data);
        if (evt.type === "snapshot") {
          setJob(evt.job);
          setStages(evt.stages);
        } else if (evt.type === "stage") {
          setStages((prev) => {
            const i = prev.findIndex(
              (s) => s.name === evt.stage && s.stage_index === evt.index
            );
            const updated: JobStage = {
              name: evt.stage,
              stage_index: evt.index,
              status: evt.status,
              output_path: evt.output_path ?? prev[i]?.output_path,
              error: evt.error ?? prev[i]?.error,
              started_at: prev[i]?.started_at,
              finished_at:
                evt.status === "succeeded" ||
                evt.status === "failed" ||
                evt.status === "canceled"
                  ? Date.now()
                  : prev[i]?.finished_at,
            };
            if (evt.status === "running" && !prev[i]?.started_at) {
              updated.started_at = Date.now();
            }
            if (i === -1) return [...prev, updated];
            const next = [...prev];
            next[i] = updated;
            return next;
          });
        } else if (evt.type === "job") {
          setJob((prev) =>
            prev
              ? { ...prev, status: evt.status, final_path: evt.final_path ?? prev.final_path, error: evt.error ?? prev.error }
              : prev
          );
          // Auto-close when the job ends
          if (
            evt.status === "succeeded" ||
            evt.status === "failed" ||
            evt.status === "canceled"
          ) {
            es.close();
            setConnected(false);
          }
        }
      } catch (err) {
        console.error("Bad SSE message", err);
      }
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [jobId]);

  return { job, stages, connected };
}
