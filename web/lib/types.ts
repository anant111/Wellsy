export type JobStatus =
  | "queued"
  | "running"
  | "awaiting_idea"   // paused for user to pick a creative direction
  | "awaiting_score"  // paused for user to accept/retry the self-score
  | "succeeded"
  | "failed"
  | "canceled";

export type StageStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | "skipped";

export type StageName =
  | "research"
  | "scenes"
  | "image"
  | "clip"
  | "audio"      // legacy: narration synthesis per scene (only when audio_mode=gemini_tts)
  | "compose"
  | "score";     // self-score stage (Gemini watches the final mp4)

export type StageSubstage = "ideas" | "script" | "awaiting_user" | null;

export type Language = "en" | "hi";
export type AspectMode = "single" | "both";
export type AudioMode = "veo_native" | "gemini_tts";

export interface JobStage {
  name: StageName;
  stage_index: number;
  status: StageStatus;
  started_at?: number;
  finished_at?: number;
  error?: string;
  output_path?: string;
}

export interface Idea {
  id: string;            // "idea-1" | "idea-2" | "idea-3"
  title: string;
  logline: string;       // 1-2 sentences
  tone: string;          // 2-4 adjectives
  hook_angle: string;    // how the video opens
  visual_seed: string;   // 1-sentence style hint
}

export interface ResearchBrief {
  topic: string;
  audience: string;
  tone: string;
  key_points: string[];
  hook_ideas: string[];
  call_to_action: string;
  // New in v2 — optional for backward-compat with old cached jobs
  target_audience?: string;
  cultural_anchors?: string[];
  hook_options?: string[];
  story_arc?: {
    setup: string;
    tension: string;
    resolution: string;
    beats: string[];
  };
  emotional_target?: string;
}

export interface ScriptScene {
  scene_id: number;
  narration: string;
  visual_prompt: string;
  shot_type: string;
  camera_angle: string;
  camera_movement: string;
  lighting: string;
  color_grading: string;
  characters: string[];
  audio_prompt: string;
  duration_seconds: number;
  continuity_token?: string;  // shared across all scenes in v2
}

export interface SelfScore {
  hook: number;
  story: number;
  momentum: number;
  emotional_linkage: number;
  closing: number;
  total: number;
  one_line_verdict: string;
  one_line_strength: string;
}

export interface Job {
  id: string;
  prompt: string;
  duration: number;
  orientation: "16:9" | "9:16";
  style: string;
  language: Language;
  aspect_mode: AspectMode;
  audio_mode: AudioMode;
  status: JobStatus;
  current_stage: StageName | null;
  current_substage?: StageSubstage;
  chosen_idea_id?: string | null;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  final_path: string | null;
  stages?: JobStage[];
}

export interface StageEvent {
  type: "stage";
  stage: StageName;
  index: number;
  status: StageStatus;
  output_path?: string;
  error?: string;
}

export interface JobEvent {
  type: "job";
  status: JobStatus;
  final_path?: string;
  error?: string;
  chosen_idea_id?: string;
  score_action?: "accept" | "retry";
}

export interface SnapshotEvent {
  type: "snapshot";
  job: Job;
  stages: JobStage[];
}

export interface IdeasEvent {
  type: "ideas";
  ideas: Idea[];
  auto_pick_seconds: number;
}

export interface ScoreEvent {
  type: "score";
  score: SelfScore;
  threshold: number;
  auto_accept_seconds: number;
}

export type StreamEvent = StageEvent | JobEvent | SnapshotEvent | IdeasEvent | ScoreEvent;

export const DURATIONS = [15, 30, 60, 120, 240] as const;
export const ORIENTATIONS = ["16:9", "9:16"] as const;
export const LANGUAGES = ["en", "hi"] as const;
export const ASPECT_MODES = [
  { value: "single", label: "Selected only" },
  { value: "both",   label: "Both (9:16 + 16:9, v2)" },
] as const;
export const STYLES = [
  "cinematic",
  "realistic",
  "anime",
  "3d",
  "watercolor",
  "minimalist",
  "surreal",
  "illustration",
  "street",
  "podcast",
] as const;
