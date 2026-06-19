// API client used by client components. The Next.js API routes proxy to the
// Python backend on :8765 (because the browser can't reach cross-origin SSE
// without cookies, and EventSource is a GET-only API).

import type { Idea, Language, AspectMode, AudioMode, ResearchBrief, ScriptScene, Job, SelfScore } from "./types";

const PY = process.env.NEXT_PUBLIC_PY_BACKEND ?? "http://127.0.0.1:8765";

export async function listJobs(): Promise<Job[]> {
  const r = await fetch(`${PY}/api/jobs`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listJobs failed: ${r.status}`);
  return r.json();
}

export async function createJob(input: {
  prompt: string;
  duration: number;
  orientation: string;
  style: string;
  language?: Language;
  aspect_mode?: AspectMode;
  audio_mode?: AudioMode;
}): Promise<{ id: string }> {
  const r = await fetch(`${PY}/api/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      language: "en",
      aspect_mode: "single",
      audio_mode: "veo_native",
      ...input,
    }),
  });
  if (!r.ok) {
    const txt = await r.text();
    throw new Error(`createJob failed (${r.status}): ${txt}`);
  }
  return r.json();
}

export async function getJob(id: string): Promise<Job> {
  const r = await fetch(`${PY}/api/jobs/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getJob failed: ${r.status}`);
  return r.json();
}

export async function cancelJob(id: string): Promise<void> {
  const r = await fetch(`${PY}/api/jobs/${id}/cancel`, { method: "POST" });
  if (!r.ok) throw new Error(`cancelJob failed: ${r.status}`);
}

export async function retryJob(id: string): Promise<{ id: string }> {
  const r = await fetch(`${PY}/api/jobs/${id}/retry`, { method: "POST" });
  if (!r.ok) throw new Error(`retryJob failed: ${r.status}`);
  return r.json();
}

export async function deleteJob(id: string): Promise<void> {
  const r = await fetch(`${PY}/api/jobs/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`deleteJob failed: ${r.status}`);
}

export interface IdeasResponse {
  ideas: Idea[];
  chosen_idea_id: string | null;
  auto_pick_timeout_sec: number;
}

export async function getIdeas(id: string): Promise<IdeasResponse> {
  const r = await fetch(`${PY}/api/jobs/${id}/ideas`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getIdeas failed: ${r.status}`);
  return r.json();
}

export async function selectIdea(id: string, ideaId: string): Promise<void> {
  const r = await fetch(`${PY}/api/jobs/${id}/select-idea`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idea_id: ideaId }),
  });
  if (!r.ok) throw new Error(`selectIdea failed: ${r.status}`);
}

export async function getResearchBrief(id: string): Promise<ResearchBrief> {
  const r = await fetch(`${PY}/api/jobs/${id}/research-brief`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getResearchBrief failed: ${r.status}`);
  return r.json();
}

export interface ScriptResponse {
  scenes: ScriptScene[];
  chosen_idea: Idea | null;
}

export async function getScript(id: string): Promise<ScriptResponse> {
  const r = await fetch(`${PY}/api/jobs/${id}/script`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getScript failed: ${r.status}`);
  return r.json();
}

export interface ScoreResponse {
  score: SelfScore;
  threshold: number;
  auto_accept_seconds: number;
}

export async function getScore(id: string): Promise<ScoreResponse> {
  const r = await fetch(`${PY}/api/jobs/${id}/score`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getScore failed: ${r.status}`);
  return r.json();
}

export async function resolveScore(id: string, action: "accept" | "retry"): Promise<void> {
  const r = await fetch(`${PY}/api/jobs/${id}/resolve-score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!r.ok) throw new Error(`resolveScore failed: ${r.status}`);
}

export const MEDIA_BASE = `${PY}/api/media`;
