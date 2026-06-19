# AI Video Pipeline — Project History

This document captures everything built for the `ai_video_pipeline/` project.
Use it as the single source of truth when picking the project back up,
onboarding someone else, or planning the next iteration.

## What it is

A local-only web app that turns a one-line prompt into a finished short-form
promotional video with cinematic scriptwriting, per-scene narration, and
story continuity. Frontend is Next.js 14 + TypeScript + Tailwind; backend is
FastAPI on Python. The current pipeline is:

```
prompt + duration + orientation + style
   │
   ├─► research.py        → research.json (topic, audience, tone, key_points, hooks, CTA)
   │
   ├─► ideas.py           → ideas.json (3 distinct creative directions)
   │                              │
   │                              ▼  user picks one (or 30s auto-pick = idea-1)
   │
   ├─► scenes.py          → scenes.json (N × 6s scenes, using cinematic-script-writer skill)
   │                              • injects SKILL.md as system prompt
   │                              • each scene: narration + visual_prompt + camera_angle +
   │                                lighting + color_grading + characters + audio_prompt
   │
   ├─► for each scene:
   │       generator.generate_image()  → images/scene_NN.png  (rich prompt from skill)
   │
   ├─► for each scene:
   │       generator.generate_video()  → clips/scene_NN.mp4  (image-conditioned, 6s)
   │           (with last_frame_path extracted from previous clip — falls back
   │            to hard cut when Veo preview rejects the param)
   │
   ├─► for each scene:
   │       audio.synthesize_narration() → audio/scene_NN.wav  (Gemini TTS, Kore voice)
   │       audio.pad_to_duration(6s)     ← exactly 6s so concat is clean
   │
   └─► video_composer.compose_final_video(clips) → final.silent.mp4
       audio.mix_narrations(audio)              → audio/full.wav
       audio.mux_audio_into_video(silent, audio) → final.mp4
                                                     (H.264 + AAC, 720×1280 or 1280×720)
```

## What works

- **Standalone Python pipeline** (no web): `python pipeline.py --prompt "..." --duration 15 --orientation 9:16 --style cinematic`
  - `--idea-id idea-N` to pre-pick an idea (no pause)
  - `--interactive` to pause and prompt at the terminal
  - Default: auto-picks idea-1 with no pause
- **Web frontend** (Next.js App Router, dark theme, minimal aesthetic)
  - `/` library — all jobs, filterable by status, auto-refreshes every 5s
  - `/new` submit form — prompt, duration (15/30/60/120/240), orientation, style
  - `/jobs/[id]` detail — prompt always visible, live stage progress, **Research brief panel**, **Scene script panel**, media gallery, final video player, action buttons
  - **3-idea picker with 30s countdown** shown when job is `awaiting_idea`
- **Live updates** via Server-Sent Events (SSE) — `useJobStream` hook
  - Event types: `snapshot`, `stage`, `job`, `ideas`
- **Cancel** — sets a `threading.Event`; pipeline checks between API calls
  - Works in any state: `running`, `awaiting_idea` (wakes the wait + marks canceled)
- **Retry / re-run** — clones parameters of a finished/canceled/failed job into a new job
- **Delete** — removes the row and the on-disk media folder
- **Parallel jobs** — each job runs in its own background thread, no global lock
- **SQLite persistence** at `data/jobs.db` (jobs + job_stages tables)
- **Robust .env loading** — walks up the directory tree to find `.env`
- **Cinemаtic-script-writer skill injection** — full SKILL.md (camera angles,
  movements, shot types, lighting, color grading, character consistency rules,
  image-prompt format template) is loaded and injected into the Gemini system
  prompt for scene generation. This is the source of consistent character
  descriptions, India-specific visuals, and emotion-matched cinematography.
- **Per-scene audio narration** — Gemini TTS (`Kore` voice by default) synthesizes
  one narration clip per scene, padded to exactly 6s, concatenated and muxed
  into the final mp4 with AAC encoding.

## Constraints we hit and worked around

| Constraint | Source | Workaround |
|------------|--------|-----------|
| Veo 3.1 only generates 6-8s clips | `veo-3.1-generate-preview` API | Each scene = exactly 6s; number of scenes = `ceil(duration / 6)` |
| Veo duration API error message says "4-8" but actually 5 fails | empirical | Clamp to [6, 8] in `generator.py` |
| `nano-banana-pro-preview` returns image as `inlineData` base64 | REST API shape | Decoded and saved as PNG |
| Veo requires `prompt` to be a string (not a list) for image conditioning | `google-genai` SDK | Pass image separately as `image=types.Image(imageBytes=..., mimeType=...)` |
| `index` is a reserved word in SQLite | DB engine | Renamed column to `stage_index` in `job_stages` table |
| `dotenv_path='../.env'` breaks when started from a different cwd | `python-dotenv` | Walk-up directory tree until `.env` is found, then load it |
| Veo has no real-time cancel API | Google AI Studio | Stop polling, mark canceled; in-flight call may still complete |
| **First+last-frame interpolation rejected by preview model** | `veo-3.1-generate-preview` returns 400 INVALID_ARGUMENT | `_generate_single_clip` tries with `last_frame_path` first, on failure retries without it (hard cut). Code stays in place for when full Veo 3.1 ships the feature. |
| 1:1 aspect ratio rejected by Veo | Veo | Map to 9:16 with warning (or default to 16:9) |
| `enhance_prompt` config field rejected | Veo 3.1 | Don't pass it |
| SQLite connection needs `check_same_thread=False` for multi-thread access | stdlib `sqlite3` | Single connection guarded by a `threading.Lock` |
| `dict(r)` fails on plain sqlite3 rows | Python 3.9 | Set `conn.row_factory = sqlite3.Row` |
| `bash 3.x` on macOS doesn't have `wait -n` | shell version | Replaced with a polling loop using `kill -0` |
| `cd "$(dirname "$0")"` in nested subshells | bash | Resolved to absolute paths in `start.sh` |
| `cd` inside `next dev` breaks module imports | Next.js | Run uvicorn from `web/server/` directly |
| Gemini TTS returns raw PCM (no WAV header) | `audio/L16;codec=pcm;rate=24000` mime | Wrap with a 44-byte WAV header in `_wrap_raw_pcm_as_wav()` |
| TTS voice `Kore` not always available | API quirk | Fallback voice list: `Kore → Aoede → Leda → Orus → Puck` |
| `len(operation.response.generated_videos)` crashes when API returns `None` | `google-genai` SDK shape | `None` check before `len()` in `generator.py:201` |
| `audio_prompt` (e.g. "warm young Indian female") is ignored by TTS | TTS API only takes voice name | Field is reserved; no effect on current output. Veo-native audio would honor it. |
| `veo-3.1-generate-preview` cannot honor "voice profile" / character consistency across clips | model limitation | Image-conditioned on each scene's first frame, but Veo re-rolls the face each time. Real character consistency needs `reference_images` plumbing (already supported in `generator.py`, not yet wired into pipeline_lib). |
| Startup `sweep_orphaned_jobs` would kill `awaiting_idea` jobs | DB engine | Sweep only touches `running`/`queued`; `awaiting_idea` jobs are left paused |

## Architecture decisions

### Why FastAPI + Next.js, not Next.js API routes only
The Python pipeline does long-running blocking work (3-5 minutes per video,
plus the indefinite wait for the user's idea pick). Splitting the backend
out keeps SSE simple (one in-process broker), lets the cancel event live
in a `threading.Event` in Python memory, and means the frontend is fully
static-deployable to Vercel (when tunneled).

### Why SQLite, not Postgres
User is local-only. SQLite is one file, zero setup, no daemon. Postgres
would require a separate server process.

### Why `pipeline_lib.py` separately from `pipeline.py`
`pipeline.py` is a CLI that wraps `pipeline_lib.run_pipeline` for terminal
use. `pipeline_lib.run_pipeline` is the library form that the web backend
calls — it accepts a `job_id`, `cancel_event`, `emit` callback, **and the
optional `chosen_idea` and `ideas_already_generated` parameters** for the
2-step scenes flow. Same code, two entry points.

### Why a 2-step scenes stage with `awaiting_idea` pause
The cinematic-script-writer skill generates *3* distinct ideas per context
and recommends the user pick one before the script is written. We surface
this in the UI (3 cards with countdown) instead of just picking one
silently. The pause is implemented as a `PipelineAwaitingIdea` exception
that the runner catches, persists ideas, and waits on a `threading.Event`
that the HTTP route signals when the user picks.

### Why each scene is 6s
Veo 3.1's hard floor. 4s rejected, 5s rejected, 6-8s works. We picked 6s
as a sweet spot (long enough for one shot, short enough to keep scene
count manageable for 15-60s videos, divisible into 15/30/60/120/240s).

### Why the skill is markdown-injected, not called as a Node CLI
The `.skill` files are pure markdown (no executable code in the manifest).
The npm package `cinematic-script-writer` DOES have a CLI, but it uses an
**in-process memory store** that doesn't persist across calls — `create-context`
in one call is lost by the time `create-script` runs in another. The simpler,
more reliable approach is to load SKILL.md and inject it as system-prompt
context, the same way [image_prompts.py](image_prompts.py) embeds the
nano-banana skill as a JSON template.

### Why TTS audio instead of Veo-native audio (current state)
The current build calls Veo WITHOUT `config.generate_audio=True` (so the
clips come out silent), then synthesizes narration separately with
`gemini-2.5-flash-preview-tts`, then muxes them. Trade-off:

- **TTS pros**: deterministic voice (we can pick `Kore`), per-scene audio
  is on disk so the UI can show an `<audio>` player per scene, narration
  is decoupled from video generation timing.
- **TTS cons**: voice is robotic and emotionless, the `audio_prompt` field
  is ignored (TTS only takes voice name), the `audio_prompt` is dead code.
- **Veo-native audio pros**: cinematic voice with matching tone/breathing,
  the `audio_prompt` would actually mean something, simpler pipeline (one
  call per scene instead of two).
- **Veo-native audio cons**: voice is model-internal and varies, may
  produce silent output on preview model.

**To switch to Veo-native audio**: set `config.generate_audio = True` on
every Veo call, prepend `"She says: '<narration>'. Then <visual prompt>."`
to the prompt, and delete the `audio` stage and `audio.py`. The plumbing
in `generator.py:165-175` is already there.

## The 9 style categories (from nano-banana-prompting-skill)

`cinematic`, `realistic`, `anime`, `3d`, `watercolor`, `minimalist`, `surreal`,
`illustration`, `street`, `podcast` (the last one is an alias for `cinematic`).

**Status**: `image_prompts.py` is still in the codebase as a fallback style
mapper, but the primary prompt source is now the cinematic-script-writer
skill injected into `scenes.py`. The LLM-generated visual prompts are richer
than the structured JSON template, so we use them directly without re-mapping.

## The `awaiting_idea` flow (full state machine)

```
queued
  ↓
running [stage=research]
  ↓
running [stage=scenes, substage=ideas]     ← emit "scenes" running, generate 3 ideas
  ↓
awaiting_idea                              ← NEW. 3 ideas persisted, SSE pushes
                                            ← "ideas" event, 30s timer thread spawned
  ↓ (user picks OR 30s elapses)
running [stage=scenes, substage=script]    ← resume with chosen idea
  ↓
running [stage=image] × N
  ↓
running [stage=clip] × N                  ← each clip's last_frame = previous clip's
  ↓                                          extracted last frame (or hard cut fallback)
running [stage=audio] × N                 ← NEW. One TTS call per scene.
  ↓
running [stage=compose]                   ← ffmpeg concat clips + mux audio
  ↓
succeeded
```

The `awaiting_idea` pause is implemented in `pipeline_lib.py` by raising
`PipelineAwaitingIdea(ideas=[...], cache_dir=...)`. The runner catches it,
saves ideas to disk, updates DB to `awaiting_idea`, starts a 30s timer
thread in `idea_store.register_waiting`, and waits on the thread's event.
When the user picks (HTTP call) or the timer fires, the runner unblocks,
persists the choice, flips status back to `running`, and loops back into
`run_pipeline` with the chosen idea.

## Folder structure (current)

```
ai_video_pipeline/
├── generator.py              # text / image / video primitives (raw REST + google-genai SDK)
├── research.py               # research brief generator
├── ideas.py                  # 3-idea generation (NEW)
├── scenes.py                 # scene script generator (REWRITTEN — skill-injected)
├── audio.py                  # Gemini TTS + ffmpeg pad/concat/mux (NEW)
├── skills_loader.py          # load .skill markdown files (NEW)
├── skills/
│   └── cinematic-script-writer/
│       └── SKILL.md          # copy from /Users/anant/Downloads/cinematic-script-writer.skill
├── image_prompts.py          # nano-banana prompt builder (kept as fallback)
├── video_composer.py         # per-scene clips + ffmpeg concat (extract_last_frame added)
├── pipeline.py               # CLI entry point (--idea-id, --interactive flags added)
├── pipeline_lib.py           # library form (REWRITTEN — PipelineAwaitingIdea + audio stage)
├── start.sh                  # one-command launcher
├── README.md                 # user-facing docs
├── PROJECT_HISTORY.md        # this file
├── data/                     # SQLite + per-job media (gitignored)
│   ├── jobs.db
│   └── jobs/<job_id>/{
│       research.json, ideas.json, scenes.json,
│       images/scene_NN.png,
│       clips/scene_NN.mp4,
│       last_frames/scene_NN_last.png,    # used by last_frame interpolation
│       audio/scene_NN.wav, audio/full.wav,
│       final.silent.mp4, final.mp4
│   }
└── web/
    ├── package.json
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── app/                  # Next.js App Router
    │   ├── page.tsx          # Library
    │   ├── new/page.tsx      # Submit form
    │   ├── jobs/[id]/
    │   │   ├── page.tsx      # Job detail (uses AwaitingIdeaSection, ResearchBriefLoader, ScriptLoader)
    │   │   └── IdeaPicker.tsx # 3-idea picker with 30s countdown (NEW)
    │   └── api/              # Next.js API routes (proxy to FastAPI)
    ├── components/           # React components
    │   ├── ResearchBriefPanel.tsx  # collapsible JSON viewer (NEW)
    │   ├── ScriptPanel.tsx         # scene-by-scene viewer (NEW)
    │   ├── StageProgress.tsx       # shows audio rows too (UPDATED)
    │   ├── StatusPill.tsx          # awaiting_idea color added
    │   ├── JobActions.tsx          # "Choose idea ↓" button added
    │   ├── JobCard.tsx
    │   ├── SubmitForm.tsx
    │   ├── MediaPreview.tsx        # Audio N label added
    │   └── ...
    ├── hooks/useJobStream.ts # SSE consumer (handles "ideas" event type)
    ├── lib/
    │   ├── types.ts          # awaiting_idea status, audio StageName, Idea, ResearchBrief, ScriptScene (UPDATED)
    │   └── api.ts            # getIdeas, selectIdea, getResearchBrief, getScript (UPDATED)
    └── server/               # FastAPI backend
        ├── server.py         # /ideas, /select-idea, /research-brief, /script routes (UPDATED)
        ├── db.py             # current_substage, chosen_idea_id columns; awaiting_idea in sweep exception (UPDATED)
        ├── pipeline_runner.py # self_loop driver handles await/resume on same thread (UPDATED)
        ├── idea_store.py     # in-process wait registry with 30s auto-pick timer (NEW)
        ├── sse_broker.py
        └── requirements.txt
```

## Environment

```env
GEMINI_API_KEY=...
TEXT_MODEL=gemini-3.1-pro-preview
IMAGE_MODEL=nano-banana-pro-preview
VIDEO_MODEL=veo-3.1-generate-preview
TTS_MODEL=gemini-2.5-flash-preview-tts
TTS_VOICE=Kore
```

All model names are read at import time from `../.env` (walked-up to find
it). To swap models, edit the env file and restart.

## How to run

```bash
cd ai_video_pipeline
./start.sh
# Open http://localhost:3000
```

The launcher:
1. Starts the Python backend on :8765
2. Installs npm deps if needed, starts Next.js on :3000
3. Waits for both to be healthy
4. Catches Ctrl+C to clean up

Logs go to `/tmp/ai_video_pipeline_backend.log` and
`/tmp/ai_video_pipeline_frontend.log`.

## Key API endpoints (FastAPI on :8765)

```
GET    /api/health
GET    /api/jobs                                 list all jobs
POST   /api/jobs                                 create + start
GET    /api/jobs/{id}                            get one (includes stages)
DELETE /api/jobs/{id}                            delete
POST   /api/jobs/{id}/cancel                     cancel (running OR awaiting_idea)
POST   /api/jobs/{id}/retry                      clone params, start new
GET    /api/jobs/{id}/stream                     SSE: snapshot, stage, job, ideas events
GET    /api/jobs/{id}/ideas                      get the 3 ideas (NEW)
POST   /api/jobs/{id}/select-idea                {idea_id: "idea-2"} resumes the job (NEW)
GET    /api/jobs/{id}/research-brief             returns research.json content (NEW)
GET    /api/jobs/{id}/script                     returns scenes.json + chosen_idea (NEW)
GET    /api/media/{job_id}/{path:path}           serve images/clips/audio/final.mp4
```

## Database schema

`jobs`:
- `id` TEXT PRIMARY KEY (uuid)
- `prompt`, `duration`, `orientation`, `style`
- `status` TEXT: `queued | running | awaiting_idea | succeeded | failed | canceled`
- `current_stage` TEXT: `research | scenes | image | clip | audio | compose`
- **`current_substage` TEXT** (NEW): `NULL | 'ideas' | 'script'` — set only during scenes stage
- **`chosen_idea_id` TEXT** (NEW): `idea-1 | idea-2 | idea-3 | NULL`
- `error`, `created_at`, `started_at`, `finished_at`, `final_path`

`job_stages`:
- `id` INTEGER PRIMARY KEY
- `job_id` TEXT REFERENCES jobs(id) ON DELETE CASCADE
- `name` TEXT: same set as `current_stage`
- `stage_index` INTEGER: 0 for non-repeating stages, 1..N for image/clip/audio
- `status` TEXT: `pending | running | succeeded | failed | canceled | skipped`
- `started_at`, `finished_at`, `error`, `output_path`
- UNIQUE(job_id, name, stage_index)

`ALTER TABLE` statements in `db.py` are idempotent — they `try/except` on
column-exists errors so old databases migrate automatically.

## Per-scene output schema (scenes.json)

```json
{
  "scene_id": 1,
  "narration": "Are you finally ready to make your hard-earned money work for you?",
  "visual_prompt": "Close-up eye-level of Riya, a 20-something Indian woman in smart-casual attire sliding a steaming cup of chai toward the camera, cinematic commercial style, practical lighting, rule-of-thirds composition, teal-orange color grading, modern open-plan home interior, calm and welcoming mood, highly detailed, cinematic",
  "shot_type": "close-up",
  "camera_angle": "eye-level",
  "camera_movement": "steadicam",
  "lighting": "practical",
  "color_grading": "teal-orange",
  "characters": ["Riya"],
  "audio_prompt": "friendly and encouraging young Indian female expert, warm conversational tone, intimate pacing",
  "duration_seconds": 6
}
```

The first-appearance character template ("Riya, a 20-something Indian woman
in smart-casual attire") is reused across all scenes per the skill's
Important Rule #1. **In practice, Veo re-rolls the face each clip** because
image conditioning on a different first frame resets the character — real
character consistency would need `reference_images` plumbing, which exists
in `generator.py:151-163` but isn't wired in.

## Things to do next (not yet done)

### Deployment (Vercel + tunnel)
The user wants to deploy the frontend to Vercel at
`wellsy.vercel.app/admin/video-gen` and have the Vercel frontend reach the
local Python backend via a tunnel (ngrok, Cloudflare Tunnel, etc.).

Steps when ready:
1. Add `wellsy.vercel.app` (and Vercel preview URLs) to FastAPI CORS allowlist
2. Add a NEXT_PUBLIC_PY_BACKEND env var that defaults to `http://127.0.0.1:8765`
   and can be overridden to a tunnel URL like `https://abc123.ngrok.app`
3. Add a `vercel.json` that sets the Vercel "Root Directory" to `web/`
4. Set `NEXT_PUBLIC_PY_BACKEND` in Vercel project env vars (in dashboard)
5. Set up ngrok or `cloudflared` to expose :8765 with a stable URL
6. Document the tunnel + env-var setup in README

### GitHub push
When the user provides a fresh GitHub PAT (the previous one was leaked in chat
and should be revoked):
1. `git init` at the project root
2. Logical commits: backend → frontend → docs
3. Push to https://github.com/anant111/Wellsy

### Quality improvements (next iteration)
- **Smooth scene transitions**: Veo `last_frame_path` is wired but rejected by
  preview. Until that ships, the practical fix is **ffmpeg `xfade` filter** in
  `video_composer.compose_final_video` — 0.3-0.5s cross-dissolve at each
  scene boundary. Pure post-processing, no Veo changes needed.
- **Character consistency**: pass the first scene's character reference image
  to all subsequent scenes' Veo calls via the `reference_images` field
  (already plumbed in `generator.py`, not wired in `pipeline_lib.py`).
- **Switch to Veo-native audio**: delete the TTS stage, set
  `config.generate_audio=True`, prepend `"She says: '<narration>'. Then <visual prompt>."`
  to each Veo prompt. Result: cinematic voice matching the scene.

### Nice-to-haves
- Per-scene retry (not just whole-job)
- Edit `scenes.json` before video generation
- More styles (podcast, informational, product, etc.)
- Faster cancellation (use `client.operations.cancel()` if SDK supports it)
- Better progress feedback during 6s Veo polling (current loop sleeps 10s)
- Show audio waveform in the per-scene audio gallery

## What we'd do differently if starting over

1. **Decide on the deployment target first.** The Vercel incompatibility (no
   ffmpeg, no long-running processes) would have been visible upfront.
2. **Use a proper state machine library** for the pipeline stages. The current
   `if/raise/check_cancel` pattern works but is brittle.
3. **Persist the cancel reason in DB** so retries can decide whether to skip
   already-completed stages.
4. **Add unit tests** for `skills_loader.load_skill`, `scenes._system_prompt`,
   and `audio._wrap_raw_pcm_as_wav` (these are pure functions, easy to test).
5. **Use the `cascade` extension** in SQLite so deleting a job auto-deletes
   its stages (we have `ON DELETE CASCADE` on `job_stages.job_id` already,
   good).

## File-by-file summary

### `skills_loader.py` (NEW)
- `load_skill(name) -> str` — reads `skills/<name>/SKILL.md`, cached via `lru_cache`
- `list_skills() -> list[str]` — subdirs of `skills/`
- Raises `FileNotFoundError` with available skills list

### `skills/cinematic-script-writer/SKILL.md` (NEW)
- Copied from `/Users/anant/Downloads/cinematic-script-writer.skill`
- Contains: camera angles / movements / shot types / lighting / color grading
  tables, image-prompt format template, 6 "Important Rules" (character
  consistency, no anachronisms, match cinematography to emotion, etc.)
- ~10k characters; injected into the Gemini system prompt as-is

### `generator.py`
- `_find_and_load_dotenv()` — walks up directories to find `.env`
- `_file_to_image(path)` — converts a local image to `types.Image(imageBytes=..., mimeType=...)`
- `generate_image(prompt, reference_image_path, orientation, style, output_filename)` — REST call to `nano-banana-pro-preview`, returns bool
- `generate_video(prompt, reference_image_path, reference_audio_path, last_frame_path, reference_images_paths, orientation, style, duration, output_filename)` — SDK call to `veo-3.1-generate-preview`
  - Clamps duration to [6, 8]
  - Maps 1:1 to 9:16
  - Wires `image`, `last_frame`, `reference_images`, and `audio` into a `GenerateVideosConfig` object
  - Polls `operation.done` every 10s, downloads via `client.files.download()`
  - **`None` check before `len(operation.response.generated_videos)`** (fix for crash when API returns `None`)

### `research.py`
- `generate_research_brief(topic, save=True) -> dict`
- Returns `{topic, audience, tone, key_points[5], hook_ideas[3], call_to_action}`
- Uses `response_mime_type=application/json` to force structured output

### `ideas.py` (NEW)
- `generate_ideas(research_brief, count=3, save_path=None) -> list[dict]`
- Returns 3 distinct ideas with archetypes: safe/on-brand (idea-1), bold/emotional (idea-2), unexpected/clever (idea-3)
- Each: `{id, title, logline, tone, hook_angle, visual_seed}`
- Forces `id` field to `idea-N` regardless of model output

### `scenes.py` (REWRITTEN)
- `generate_scenes(research_brief, chosen_idea, total_duration, orientation, style, save_path=None) -> list[dict]`
- **Builds system prompt with full SKILL.md injected** so Gemini applies camera/lighting/character rules
- `num_scenes = ceil(total_duration / 6)`
- Narrative arc: scene 1 = hook (from chosen idea's hook_angle), scene N = CTA, scenes 2..N-1 = problem → solution
- Each scene has the rich schema (see above)
- Defaults for missing fields (shot_type, camera_angle, etc.) so downstream code can always rely on them

### `image_prompts.py` (kept, no longer primary)
- `build_prompt(scene, style, orientation) -> dict` — structured JSON template (nano-banana style)
- `to_text_prompt(prompt_dict) -> str`
- `_canonical_style(style)` — alias mapper
- **Status**: superseded by the LLM-generated prompts in `scenes.py`; kept for back-compat

### `audio.py` (NEW)
- `synthesize_narration(text, output_path, voice="Kore") -> bool`
  - Calls `gemini-2.5-flash-preview-tts` with `response_modalities=["AUDIO"]`
  - Response mime is `audio/L16;codec=pcm;rate=24000` (raw 16-bit PCM, no header)
  - **Wraps with WAV header in `_wrap_raw_pcm_as_wav()`** (struct-pack 44-byte header)
  - Fallback voice list: `Kore → Aoede → Leda → Orus → Puck` if API 404s on voice
- `pad_to_duration(wav_path, seconds)` — ffmpeg `apad=pad_dur=N,atrim=0:N`
- `concat_audio(audio_paths, output_path)` — ffmpeg concat-demuxer
- `mux_audio_into_video(video_path, audio_path, output_path)` — ffmpeg with `-c:v copy -c:a aac -b:a 192k -shortest`

### `video_composer.py`
- `generate_scene_clips(scenes, image_paths, orientation, style) -> list[str]`
- `compose_final_video(clip_paths, target_duration, output_path=None) -> str`
- `extract_last_frame(clip_path, output_path) -> bool` (NEW) — uses ffmpeg `-sseof -0.1` to grab the last visible frame as PNG
- `_generate_single_clip(...)` (UPDATED) — accepts `last_frame_path`; **on failure, retries without it** (Veo preview rejects first+last-frame, so this is the de-facto behavior today)

### `pipeline_lib.py` (REWRITTEN)
- `PipelineCanceled` — raised internally on cancel
- **`PipelineAwaitingIdea` (NEW)** — raised after stage 2a to pause for the user's idea pick; carries `ideas` and `cache_dir`
- `run_pipeline(job_id, prompt, duration, orientation, style, cache_dir, emit, cancel_event, chosen_idea=None, ...) -> str`
  - **Stage 2a (ideas)**: generates 3 ideas, raises `PipelineAwaitingIdea`
  - **Stage 2b (scenes)**: takes the chosen idea, generates the script
  - **Stage 3 (image)**: per-scene, uses scene's visual_prompt directly (no more `build_prompt` re-mapping)
  - **Stage 4 (clip)**: per-scene, extracts previous clip's last frame, passes as `last_frame_path` to next scene
  - **Stage 5 (audio) (NEW)**: per-scene, TTS synthesis + pad to 6s
  - **Stage 6 (compose)**: ffmpeg concat clips → silent video, then mix/concat/mux audio into final.mp4
- Each stage: `emit(stage_name, status, index, output_path, error)`

### `pipeline.py` (UPDATED)
- CLI wrapper around `pipeline_lib.run_pipeline`
- New flags: `--idea-id idea-N` (pre-pick), `--interactive` (prompt at terminal)
- Default: auto-pick idea-1, no pause
- `_driver()` loops on `PipelineAwaitingIdea` until pipeline completes

### `start.sh`
- One command, two processes
- Backend on :8765, frontend on :3000
- Catches Ctrl+C, kills both children

### `web/server/server.py` (UPDATED)
- Existing endpoints + new: `GET /api/jobs/{id}/ideas`, `POST /api/jobs/{id}/select-idea`, `GET /api/jobs/{id}/research-brief`, `GET /api/jobs/{id}/script`
- `cancel_job` handles `awaiting_idea` status (calls `request_cancel_waiting`)
- `sweep_orphaned_jobs` returns `(running_swept, awaiting_idea_left)`; on startup, logs a warning if any `awaiting_idea` jobs are left paused

### `web/server/db.py` (UPDATED)
- SQLite, single connection, threading.Lock
- `jobs` table extended: `current_substage`, `chosen_idea_id` columns
- `job_stages` table: same as before
- New helpers: `set_substage`, `set_chosen_idea`, `save_ideas`, `load_ideas`, `load_research`, `load_script`
- `sweep_orphaned_jobs()` only sweeps `running`/`queued` (not `awaiting_idea`)
- Idempotent `ALTER TABLE` for migration from old schemas

### `web/server/idea_store.py` (NEW)
- `AUTO_PICK_TIMEOUT_SEC = 30.0`
- `register_waiting(job_id, ideas) -> Event` — registers + starts timer thread
- `select_idea(job_id, idea_id) -> bool` — user pick
- `cancel_wait(job_id) -> bool` — sets cancelled flag
- `get_waiting_info`, `finish_wait`, `is_waiting`
- Lock-guarded dict `_waiting`

### `web/server/pipeline_runner.py` (REWRITTEN)
- `start_job(job_id)` — spawns daemon thread
- `self_loop(...)` — driver that runs `run_pipeline`, catches `PipelineAwaitingIdea`, waits on the event, then loops back in with the chosen idea
- `request_cancel(job_id)`, `request_cancel_waiting(job_id)` (NEW for awaiting_idea)
- `resume_job(job_id, idea_id) -> bool` (NEW) — called by the HTTP route when user picks
- `retry_job(job_id) -> new_id` (refuses to retry `running` or `awaiting_idea`)

### `web/server/sse_broker.py`
- Unchanged
- In-memory pub/sub, keyed by job_id
- `subscribe`, `unsubscribe`, `publish` (sync), `close` (sends `None` to signal end)
- Uses `asyncio.Queue` per subscriber, bridged from sync publisher via `put_nowait`

### `web/lib/types.ts` (UPDATED)
- `JobStatus`: now includes `"awaiting_idea"`
- `StageName`: now includes `"audio"`
- `Idea`, `ResearchBrief`, `ScriptScene` interfaces (NEW)
- `StreamEvent` union: `StageEvent | JobEvent | SnapshotEvent | IdeasEvent`

### `web/lib/api.ts` (UPDATED)
- `getIdeas`, `selectIdea`, `getResearchBrief`, `getScript` (NEW)
- Existing: `listJobs`, `createJob`, `getJob`, `cancelJob`, `retryJob`, `deleteJob`

### `web/app/page.tsx` (Library)
- Fetches `/api/jobs` on mount, refreshes every 5s
- Filter buttons: All / Running / Succeeded / Failed / Canceled
- `<JobCard>` per row, with action buttons (Cancel / Retry / Delete)
- Passes `onAction={refresh}` to JobCard for soft refresh after cancel/delete

### `web/app/new/page.tsx` (Submit)
- Unchanged
- `<SubmitForm>`: textarea + 3 selects (duration, orientation, style)
- On submit: POST to `/api/jobs`, redirect to `/jobs/{id}`

### `web/app/jobs/[id]/page.tsx` (Job detail, UPDATED)
- `useJobStream(id)` for live updates
- Always renders the prompt at the top, with chosen_idea_id badge
- `<AwaitingIdeaSection>` (NEW) — polls `/ideas` every 2s, renders `<IdeaPicker>`
- `<ResearchBriefLoader>` (NEW) — polls `/research-brief` every 3s
- `<ScriptLoader>` (NEW) — polls `/script` every 3s
- `<StageProgress>` (UPDATED — now has audio rows)
- Image gallery + clip gallery + **audio gallery** (per-scene `<audio>` players)
- Final video player with "🔊 Audio narration mixed in" note

### `web/app/jobs/[id]/IdeaPicker.tsx` (NEW)
- 3 cards with title, logline, tone, hook, visual_seed
- 30s countdown
- Auto-picks idea-1 (or first idea) when countdown hits 0
- Click handler calls `selectIdea(jobId, ideaId)`

### `web/hooks/useJobStream.ts`
- Subscribes to `${PY}/api/jobs/${id}/stream`
- Handles `snapshot`, `stage`, `job`, and `ideas` events
- Auto-closes the connection on `succeeded`/`failed`/`canceled`

### `web/components/*`
- `StatusPill` — colored pill per status; awaiting_idea = `bg-amber-500`, label "awaiting idea"
- `JobCard` — library row, accepts `onAction` for soft refresh
- `JobActions` — Cancel / Retry / Delete; "Choose idea ↓" anchor when awaiting_idea
- `SubmitForm` — the new-job form
- `StageProgress` — ordered list of stages with status pills; shows audio rows when scenes exist
- `MediaPreview` — auto-detects mp4 vs image vs audio
- `ResearchBriefPanel` (NEW) — collapsible JSON viewer for the research brief
- `ScriptPanel` (NEW) — collapsible scene-by-scene viewer with shot/camera/lighting/grading/characters/audio chips

---

## v2 analysis: closing-3 problem + 6 concrete improvements

After two end-to-end test runs (15s Hindi Mumbai chai + 60s English science of
fat loss), Gemini's self-score consistently gave **closing = 3/10** with the
verdict "ends abruptly mid-ride" / "Fix the abrupt ending so the final call
to action is actually delivered." The 4 other axes ranged 4-7. Diagnosing:

### Root cause: scenes prompt doesn't constrain the last scene
The old prompt distributed "HOOK / PROBLEM → SOLUTION / CTA" across N scenes
but treated the final scene identically to every other scene. The model then
produces scenes like "Hit that follow button right now for more science-backed
desi fitness tips!" — a generic social-media CTA in place of an actual story
resolution. Gemini's scorer (correctly) flags this.

### 6 concrete fixes (3 implemented in v2, 3 deferred)

**Implemented (v2, ships with this commit):**

1. **Two-part continuity token** in `scenes.py`. The old single
   `continuity_token` included the *setting* ("Mumbai street food setting at
   pre-dawn"), which forced Veo to render "pre-dawn" for every scene — even
   ones the story meant to advance to daytime. Split into:
   - `style_token` (immutable): lighting, color grade, camera style, framing
   - `setting_token` (per-scene): location, time-of-day, weather
   `visual_prompt` now uses `<style_token> <setting_token> ...`, so the
   setting can evolve while the style stays consistent.

2. **Closing-scene emphasis** in `scenes.py`. Added a `closing_directive`
   block: "Scene N MUST deliver the CTA, resolve the visual story, end on a
   settled final frame, and feel like a satisfying conclusion — NOT
   mid-action, NOT a cutaway, NOT a generic 'tag your friends' shot."

3. **Beat mapping** from the research brief. The brief's `story_arc.beats`
   are now passed to the scenes prompt and explicitly assigned 1:1 to scenes
   (or distributed if fewer beats than scenes). Previously the model had to
   invent beats on its own, which produced unmoored closings.

**Deferred to v2.x (designed, not yet built):**

4. **Character consistency via per-character `character_look` token.**
   `scenes.py` already accepts a `characters` list — we need a parallel
   `character_looks` dict that the visual_prompt of subsequent scenes
   references verbatim. Veo's preview model re-rolls faces, so this will
   only partially help; the full fix needs a per-scene `reference_images`
   plumbing (already supported in `generator.py` but not wired into
   `pipeline_lib`).

5. **Veo extension frame-handoff prompt.** Veo's extension API gives the
   model the source video + a text prompt; if the prompt names what's on
   screen ("Your source video just showed: ... Pouring chai from height
   into glass"), the cut feels less jarring. Implemented as a stop-gap
   (extension prompt now prepends previous scene's narration), but the
   better fix is to use Veo's *image conditioning on the last frame* —
   currently rejected by preview, will work when GA.

6. **Lower self-score threshold + closing-weight.** 7/10 per axis is too
   strict for Veo 3.1 preview output, which produces 4-6 range consistently.
   Either drop threshold to 6, or weight `closing` and `hook` at 1.5× for
   short-form reels (where they matter most). Decision deferred to user.

### Verifying the fix
- Submitted a follow-up same-topic job with the new prompt
  (`science-of-fat-loss 60s` again, new job_id logged in scratch).
- Compare new job's score vs the wellness baseline (27/50, closing=3).
- If new closing is ≥ 6, the closing_directive is doing the work.
- If new style_token is consistent across all scenes but setting_token
  varies by time-of-day, the split is doing the work.
