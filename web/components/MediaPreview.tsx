"use client";

import { MEDIA_BASE } from "@/lib/api";
import type { StageName } from "@/lib/types";

interface Props {
  jobId: string;
  path: string;
  className?: string;
}

/** Renders an image or video preview based on file extension. */
export function MediaPreview({ jobId, path, className = "" }: Props) {
  const url = `${MEDIA_BASE}/${jobId}/${path}`;
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "mp4") {
    return (
      <video
        src={url}
        controls
        playsInline
        className={`rounded-lg w-full ${className}`}
      />
    );
  }
  // Default: image
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={path} className={`rounded-lg w-full ${className}`} loading="lazy" />
  );
}

export function MediaPath({ jobId, path }: { jobId: string; path: string }) {
  return `${MEDIA_BASE}/${jobId}/${path}`;
}

export function stageLabel(name: StageName, index: number): string {
  if (name === "research") return "Research brief";
  if (name === "scenes") return "Scene script";
  if (name === "image") return `Image ${index}`;
  if (name === "clip") return "Continuous clip (Veo extension chain)";
  if (name === "audio") return `Audio ${index}`;
  if (name === "compose") return "Final composition";
  if (name === "score") return "Self-score";
  return name;
}
