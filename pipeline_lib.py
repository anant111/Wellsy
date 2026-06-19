"""pipeline_lib.py - Library form of the pipeline for the web backend.

The "scenes" stage is split into two sub-steps:
  2a. generate_ideas(brief) -> 3 ideas
  2b. generate_scenes(brief, chosen_idea) -> scenes.json

Between 2a and 2b, the pipeline raises PipelineAwaitingIdea(ideas=...) and
the runner pauses the job thread until the user (or a 30s auto-pick) selects
an idea. When resumed, the chosen idea is passed to generate_scenes.

Clip generation uses the Veo 3.1 video-extension feature to produce ONE
continuous clip from the N scenes (1 base + (N-1) extensions). When this
mode is rejected by the preview model, we fall back to the legacy
per-scene clip + ffmpeg concat path.

A new "score" stage runs after "compose": Gemini watches the final mp4
and scores hook / story / momentum / emotional-linkage / closing 1-10.
A self-score below threshold raises PipelineAwaitingScore so the user
can accept or retry.

Audio: by default the video is generated with Veo-native audio (which
honors the "Voiceover (in <language>): ..." prompt and supports Hindi).
The Gemini TTS stage is skipped unless `audio_mode="gemini_tts"`.
"""
import json
import os
import sys
import threading
from typing import Callable, List, Optional

sys.path.insert(0, os.path.dirname(__file__))

from research import generate_research_brief
from ideas import generate_ideas
from scenes import generate_scenes
from generator import generate_image
import video_composer
import audio as audio_mod
import scorer


class PipelineCanceled(Exception):
    """Raised internally to abort a stage on cancel."""
    pass


class PipelineAwaitingIdea(Exception):
    """Raised after stage 2a to pause the pipeline for the user's idea choice.

    The runner catches this, persists the ideas, and blocks until the user
    (or the 30s auto-pick) makes a selection. The chosen idea id is then
    passed back into the second invocation of run_pipeline.
    """
    def __init__(self, ideas: list, cache_dir: str):
        self.ideas = ideas
        self.cache_dir = cache_dir


class PipelineAwaitingScore(Exception):
    """Raised after the score stage when the self-score is below threshold.

    The runner catches this, persists the score JSON, flips the job to
    `awaiting_score`, and waits for the user to either accept (resume with
    skip) or retry (resume by regenerating).
    """
    def __init__(self, score: dict, cache_dir: str, threshold: int):
        self.score = score
        self.cache_dir = cache_dir
        self.threshold = threshold


# Type for the emit callback
EmitFn = Callable[[str, str, int, Optional[str], Optional[str]], None]
# signature: emit(stage_name, status, index, output_path_or_None, error_or_None)


def run_pipeline(
    job_id: str,
    prompt: str,
    duration: int,
    orientation: str,
    style: str,
    cache_dir: str,
    emit: EmitFn,
    cancel_event: threading.Event,
    chosen_idea: Optional[dict] = None,
    wait_for_idea: Optional["threading.Event"] = None,
    ideas_already_generated: Optional[list] = None,
    language: str = "en",
    aspect_mode: str = "single",       # v2 deferred; today: always 'single'
    audio_mode: str = "veo_native",    # 'veo_native' | 'gemini_tts'
    score_threshold: int = 7,          # 1-10 per axis; below = await user
    skip_score: bool = False,          # True when re-entering after user accept
) -> str:
    """Run the full pipeline for a job. Returns path to final.mp4.

    Modes:
      1. First call (no chosen_idea): does stage 2a (ideas), then raises
         PipelineAwaitingIdea. The runner unblocks the thread by setting
         `wait_for_idea`, then calls run_pipeline(...) again with the chosen idea.
      2. Resume call (with chosen_idea): skips 2a, goes straight to 2b onwards.
    """
    images_dir = os.path.join(cache_dir, "images")
    clips_dir = os.path.join(cache_dir, "clips")
    audio_dir = os.path.join(cache_dir, "audio")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)

    def check():
        if cancel_event.is_set():
            raise PipelineCanceled()

    # ── STAGE 1: Research ────────────────────────────────────────────
    brief_path = os.path.join(cache_dir, "research.json")
    if os.path.exists(brief_path):
        with open(brief_path) as f:
            brief = json.load(f)
        emit("research", "succeeded", 0, brief_path, None)
    else:
        emit("research", "running", 0, None, None)
        try:
            check()
            brief = generate_research_brief(
                prompt, save=False, language=language,
            )
            with open(brief_path, "w") as f:
                json.dump(brief, f, indent=2)
            emit("research", "succeeded", 0, brief_path, None)
        except PipelineCanceled:
            emit("research", "canceled", 0, None, None)
            raise
        except Exception as e:
            emit("research", "failed", 0, None, str(e))
            raise

    # ── STAGE 2: Scenes (split into 2a ideas → wait → 2b script) ─────
    scenes_path = os.path.join(cache_dir, "scenes.json")
    if os.path.exists(scenes_path) and not chosen_idea:
        with open(scenes_path) as f:
            scenes = json.load(f)
        emit("scenes", "succeeded", 0, scenes_path, None)
    else:
        # 2a: generate ideas (unless we're resuming with one already chosen)
        if not chosen_idea:
            ideas_path = os.path.join(cache_dir, "ideas.json")
            if ideas_already_generated is not None:
                ideas = ideas_already_generated
            elif os.path.exists(ideas_path):
                with open(ideas_path) as f:
                    ideas = json.load(f).get("ideas", [])
            else:
                emit("scenes", "running", 0, None, None)
                try:
                    check()
                    ideas = generate_ideas(brief, count=3)
                    with open(ideas_path, "w") as f:
                        json.dump({"ideas": ideas}, f, indent=2)
                except PipelineCanceled:
                    emit("scenes", "canceled", 0, None, None)
                    raise
                except Exception as e:
                    emit("scenes", "failed", 0, None, str(e))
                    raise

            raise PipelineAwaitingIdea(ideas=ideas, cache_dir=cache_dir)

        # 2b: generate scenes with the chosen idea
        emit("scenes", "running", 0, None, None)
        try:
            check()
            scenes = generate_scenes(
                brief, chosen_idea, duration, orientation, style,
                save_path=None, language=language,
            )
            with open(scenes_path, "w") as f:
                json.dump(scenes, f, indent=2)
            emit("scenes", "succeeded", 0, scenes_path, None)
        except PipelineCanceled:
            emit("scenes", "canceled", 0, None, None)
            raise
        except Exception as e:
            emit("scenes", "failed", 0, None, str(e))
            raise

    # ── STAGE 3: Images (one per scene) ──────────────────────────────
    image_paths: List[str] = []
    for scene in scenes:
        idx = scene["scene_id"]
        image_path = os.path.join(images_dir, f"scene_{idx:02d}.png")

        if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
            image_paths.append(image_path)
            emit("image", "succeeded", idx, image_path, None)
            continue

        emit("image", "running", idx, None, None)
        try:
            check()
            text_prompt = scene["visual_prompt"]
            success = generate_image(
                prompt=text_prompt,
                orientation=orientation,
                style=style,
                output_filename=image_path,
            )
            if not success:
                raise RuntimeError("generate_image returned False")
            image_paths.append(image_path)
            emit("image", "succeeded", idx, image_path, None)
        except PipelineCanceled:
            emit("image", "canceled", idx, None, None)
            raise
        except Exception as e:
            emit("image", "failed", idx, None, str(e))
            raise

    # ── STAGE 4: Clips (ONE continuous clip via Veo extension) ──────
    # Scene 1: image-to-video base clip. Scenes 2..N: each extends the
    # previous output by ~7s. The result is a single mp4 that plays as
    # one continuous video with no hard cuts.
    final_continuous_clip = os.path.join(clips_dir, "final.mp4")
    if os.path.exists(final_continuous_clip) and os.path.getsize(final_continuous_clip) > 0:
        # Cached: skip regeneration
        emit("clip", "succeeded", 0, final_continuous_clip, None)
        clip_paths = [final_continuous_clip]
    else:
        emit("clip", "running", 0, None, None)
        try:
            check()
            extended_path = video_composer.generate_extended_clip(
                scenes=scenes,
                image_paths=image_paths,
                orientation=orientation,
                style=style,
                audio_mode=audio_mode,
                language=language,
                output_path=final_continuous_clip,  # write to the JOB's clips_dir, not CWD-relative
            )
            if extended_path is None:
                # Fall back to legacy hard-cut composer
                print("[clips] extension mode failed; falling back to legacy hard-cut composer")
                legacy_clips = video_composer.generate_scene_clips(
                    scenes, image_paths, orientation, style,
                )
                video_composer.compose_final_video(
                    legacy_clips, target_duration=duration,
                    output_path=final_continuous_clip,
                )
                clip_paths = [final_continuous_clip]
            else:
                # extended_path is the absolute path the composer wrote to.
                # Use it directly so we don't rely on a relative path lookup.
                clip_paths = [extended_path]
            emit("clip", "succeeded", 0, final_continuous_clip, None)
        except PipelineCanceled:
            emit("clip", "canceled", 0, None, None)
            raise
        except Exception as e:
            emit("clip", "failed", 0, None, str(e))
            raise

    # ── STAGE 5 (legacy): Audio narration via Gemini TTS ───────────
    # Skipped when audio_mode='veo_native' (Veo already generated the
    # voiceover as part of clip gen). Only runs when audio_mode='gemini_tts'.
    audio_paths: List[str] = []
    if audio_mode == "gemini_tts":
        for scene in scenes:
            idx = scene["scene_id"]
            audio_path = os.path.join(audio_dir, f"scene_{idx:02d}.wav")

            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                audio_paths.append(audio_path)
                emit("audio", "succeeded", idx, audio_path, None)
                continue

            emit("audio", "running", idx, None, None)
            try:
                check()
                narration = scene.get("narration", "").strip()
                if not narration:
                    raise RuntimeError("Empty narration for scene")
                ok = audio_mod.synthesize_narration(narration, audio_path)
                if not ok:
                    raise RuntimeError("TTS returned no audio")
                audio_mod.pad_to_duration(audio_path, scene.get("duration_seconds", 7))
                audio_paths.append(audio_path)
                emit("audio", "succeeded", idx, audio_path, None)
            except PipelineCanceled:
                emit("audio", "canceled", idx, None, None)
                raise
            except Exception as e:
                emit("audio", "failed", idx, None, str(e))
                raise

    # ── STAGE 6: Compose ────────────────────────────────────────────
    # In extension mode the clip is already a single continuous mp4 with
    # Veo-native audio baked in. We CUT it at per-scene boundaries to
    # honor the model's pacing, then trim the total to target_duration.
    final_path = os.path.join(cache_dir, "final.mp4")
    emit("compose", "running", 0, None, None)
    try:
        check()
        src = clip_paths[0] if clip_paths else None
        if not src or not os.path.exists(src):
            raise RuntimeError("No continuous clip available to compose")

        # Per-scene duration breakdown from the model. Falls back to 6s
        # per scene if the script didn't provide durations.
        scene_durations = [int(s.get("duration_seconds") or 6) for s in scenes]
        if not scene_durations:
            scene_durations = [6] * len(scenes)

        per_scene_cut = _cut_into_scenes(src, final_path, scene_durations, target_duration=duration)
        if audio_mode == "gemini_tts" and audio_paths:
            full_audio_path = os.path.join(audio_dir, "full.wav")
            audio_mod.concat_audio(audio_paths, full_audio_path)
            audio_mod.mux_audio_into_video(per_scene_cut, full_audio_path, final_path)
        else:
            # Veo-native audio: the cut is already in final_path
            pass
        emit("compose", "succeeded", 0, final_path, None)
    except PipelineCanceled:
        emit("compose", "canceled", 0, None, None)
        raise
    except Exception as e:
        emit("compose", "failed", 0, None, str(e))
        raise

    # ── STAGE 7: Self-score (Gemini watches the final mp4) ──────────
    score_path = os.path.join(cache_dir, "score.json")
    if skip_score:
        # Re-entry after user accepted a low score; reuse prior score.json
        if os.path.exists(score_path):
            with open(score_path) as f:
                existing = json.load(f)
            emit("score", "succeeded", 0, score_path, None)
            return final_path
        # else fall through to fresh score

    emit("score", "running", 0, None, None)
    try:
        check()
        score = scorer.score_video(
            final_path=final_path,
            brief=brief,
            chosen_idea=chosen_idea,
            scenes=scenes,
            language=language,
        )
        with open(score_path, "w") as f:
            json.dump(score, f, indent=2)

        all_axes = ["hook", "story", "momentum", "emotional_linkage", "closing"]
        below = [a for a in all_axes if score.get(a, 0) < score_threshold]
        if below:
            print(f"[score] below threshold on {below}: {score}")
            emit("score", "succeeded", 0, score_path, None)
            raise PipelineAwaitingScore(
                score=score, cache_dir=cache_dir, threshold=score_threshold,
            )

        emit("score", "succeeded", 0, score_path, None)
    except PipelineCanceled:
        emit("score", "canceled", 0, None, None)
        raise
    except PipelineAwaitingScore:
        # already emitted "succeeded" for the stage above; re-raise to pause
        raise
    except Exception as e:
        emit("score", "failed", 0, None, str(e))
        raise

    return final_path


def _trim_to_duration(src: str, dst: str, seconds: int) -> None:
    """Stream-copy `src` mp4 to `dst`, trimmed to `seconds`."""
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-i", src, "-t", str(seconds),
        "-c", "copy", "-movflags", "+faststart", dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[compose] ffmpeg trim failed: {r.stderr[-300:]}")
        # Fallback: just copy
        import shutil
        shutil.copyfile(src, dst)


def _cut_into_scenes(src: str, dst: str, scene_durations: list, target_duration: int) -> str:
    """Cut a continuous Veo-extension mp4 into N segments of `scene_durations[i]`
    seconds each, then concatenate and trim to `target_duration`.

    The Veo continuous clip is the natural sum of base + extensions, so each
    cut point lands near a Veo transition (visually smooth). The result honors
    the per-scene pacing the model chose while keeping the "single continuous
    video" feel — the seams are barely visible because they sit at extension
    boundaries Veo itself made.

    Uses ffmpeg with stream-copy for video (no re-encode, fast). Audio is
    re-encoded to AAC because the cuts are at arbitrary timestamps and
    stream-copy may produce glitches at the joins.
    """
    import subprocess
    tmp_dir = os.path.dirname(dst) or "."
    segment_paths = []
    cursor = 0.0
    for i, dur in enumerate(scene_durations):
        seg = os.path.join(tmp_dir, f"_seg_{i:02d}.mp4")
        cmd = [
            "ffmpeg", "-y", "-ss", f"{cursor:.3f}", "-i", src,
            "-t", str(dur),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            seg,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[compose] ffmpeg cut for scene {i} failed: {r.stderr[-200:]}")
            # Fall back to trim-to-target
            return _trim_to_duration_fallback(src, dst, target_duration)
        segment_paths.append(seg)
        cursor += dur

    # Concat segments
    list_path = os.path.join(tmp_dir, "_seg_list.txt")
    with open(list_path, "w") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",  # segments are already encoded; stream-copy
        "-movflags", "+faststart",
        dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[compose] ffmpeg concat failed: {r.stderr[-200:]}")
        return _trim_to_duration_fallback(src, dst, target_duration)

    # Final trim to target_duration
    if os.path.exists(dst):
        tmp = dst + ".trim.mp4"
        cmd = [
            "ffmpeg", "-y", "-i", dst, "-t", str(target_duration),
            "-c", "copy", "-movflags", "+faststart", tmp,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            os.replace(tmp, dst)
        else:
            # Last resort
            import shutil
            shutil.copyfile(dst, tmp)

    # Cleanup segments
    for p in segment_paths + [list_path]:
        try: os.remove(p)
        except Exception: pass

    return dst


def _trim_to_duration_fallback(src: str, dst: str, seconds: int) -> str:
    """Last-resort fallback: just trim the source to target_duration."""
    _trim_to_duration(src, dst, seconds)
    return dst
