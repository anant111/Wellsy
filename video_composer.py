"""video_composer.py - Generate per-scene clips and stitch into a final video.

Two modes:

A) Extension mode (default, new): scene 1 produces a base ~7s clip via
   Veo image-to-video. Scenes 2..N each call `extend_video()` on the
   previous output. The final mp4 is ONE continuous clip that contains
   all scenes concatenated by Veo itself — no hard cuts.

B) Hard-cut fallback (legacy): each scene is an independent 6s clip;
   ffmpeg stitches them. Used when the extension mode fails (e.g. the
   preview model rejects `video=`).

The composer is a no-op for case A: Veo has already given us the final
mp4. Case B still uses the original `compose_final_video()` concat path.
"""
import os
import subprocess
import sys
import time
from typing import List, Optional

sys.path.insert(0, os.path.dirname(__file__))
from generator import generate_video, extend_video, VIDEO_MODEL
from google import genai

CACHE_DIR = ".cache"
IMAGES_DIR = os.path.join(CACHE_DIR, "images")
CLIPS_DIR = os.path.join(CACHE_DIR, "clips")
FINAL_PATH = os.path.join(CACHE_DIR, "final.mp4")
EXTENSION_DIR = os.path.join(CACHE_DIR, "extensions")


def _ensure_dirs():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(CLIPS_DIR, exist_ok=True)
    os.makedirs(EXTENSION_DIR, exist_ok=True)


def _make_video_client():
    """Reuse the SDK client from generator.py (which loads .env for us)."""
    from generator import client
    return client


def generate_extended_clip(
    scenes: list,
    image_paths: List[str],
    orientation: str,
    style: str,
    audio_mode: str = "veo_native",
    language: str = "en",
    output_path: Optional[str] = None,
) -> Optional[str]:
    """Build ONE continuous mp4 by chaining Veo extensions.

    Scene 1: image-conditioned base clip (image-to-video). Audio via
             "Voiceover (in <language>): ..." in the prompt.
    Scenes 2..N: extend_video() on the running source. Each extension
             appends ~7s. The final mp4 is written to `output_path`
             (defaults to CLIPS_DIR/final.mp4) and is ready to play
             (no ffmpeg concat needed).

    Returns:
        Absolute path to the final continuous clip, or None on failure.
    """
    if not scenes:
        raise ValueError("No scenes to render")
    if len(scenes) != len(image_paths):
        raise ValueError(f"scenes ({len(scenes)}) and image_paths ({len(image_paths)}) mismatch")

    _ensure_dirs()
    if output_path is None:
        output_path = os.path.join(CLIPS_DIR, "final.mp4")
    final_out = output_path
    final_dir = os.path.dirname(final_out) or "."
    os.makedirs(final_dir, exist_ok=True)
    if os.path.exists(final_out) and os.path.getsize(final_out) > 0:
        print(f"[composer] Extended final already exists: {final_out}")
        return final_out

    client = _make_video_client()

    # ── Scene 1: image-conditioned base clip ──
    # The base clip is at least 6s (Veo minimum for extensions). If the
    # model wanted 4s, we generate 6s and trim later.
    base_clip = os.path.join(EXTENSION_DIR, "scene_01_base.mp4")
    s1 = scenes[0]
    img1 = image_paths[0]
    narration1 = (s1.get("narration") or "").strip()
    style_token = s1.get("style_token") or s1.get("continuity_token") or ""
    setting_token1 = s1.get("setting_token") or s1.get("continuity_token") or ""
    voice_intro = (
        f"Voiceover (in {language}): {narration1}. " if narration1
        else f"Voiceover in {language}, "
    )
    base_prompt = (
        f"{voice_intro}"
        f"{style_token} {setting_token1}. "
        f"Cinematic motion, smooth camera drift, no cuts."
    )
    audio_on = audio_mode != "gemini_tts"  # gemini_tts = silent video, audio added later

    # Base duration: snap to {6,7,8} (Veo can't do 4s base reliably).
    base_intended = int(s1.get("duration_seconds") or 6)
    base_dur = min((6, 7, 8), key=lambda x: abs(x - base_intended))
    print(f"[composer] Step 1/{len(scenes)}: base clip "
          f"(image-to-video, {base_dur}s, audio={audio_on}; model wanted {base_intended}s)")
    # Single call: generate the base clip AND keep the operation handle so we
    # can chain extend_video() on top of it without a redundant second call.
    op_base = generate_video(
        prompt=base_prompt,
        reference_image_path=img1,
        orientation=orientation,
        style=style,
        duration=base_dur,
        output_filename=base_clip,
        generate_audio=audio_on,
        return_operation=True,
    )
    if op_base is None:
        print("[composer] ❌ base clip failed")
        return None

    current_video = op_base.response.generated_videos[0].video

    # ── Scenes 2..N: chain extensions ──
    for i, (scene, img_path) in enumerate(zip(scenes[1:], image_paths[1:]), start=2):
        ext_out = os.path.join(EXTENSION_DIR, f"scene_{i:02d}_ext.mp4")
        narration = (scene.get("narration") or "").strip()
        voice_line = (
            f"Voiceover (in {language}): {narration}. " if narration
            else f"Voiceover in {language}, "
        )
        setting_token = scene.get("setting_token") or scene.get("continuity_token") or ""
        ext_prompt = (
            f"{voice_line}"
            f"{style_token} {setting_token}. "
            f"Cinematic motion, smooth camera drift, no cuts."
        )

        # Each extension's duration is the model's choice, snapped to {4,6,7,8}.
        ext_intended = int(scene.get("duration_seconds") or 7)
        ext_dur = min((4, 6, 7, 8), key=lambda x: abs(x - ext_intended))

        print(f"[composer] Step {i}/{len(scenes)}: extending with scene {i} "
              f"({ext_dur}s; model wanted {ext_intended}s)")
        new_video = _extend_keep_video(
            client, current_video, ext_prompt, orientation, audio_on, duration=ext_dur,
        )
        if new_video is None:
            print(f"[composer] ❌ extension {i} failed; bailing")
            return None
        current_video = new_video

        # Save each extension to disk for debugging / fallback
        try:
            content = client.files.download(file=current_video)
            with open(ext_out, "wb") as f:
                f.write(content)
        except Exception as e:
            print(f"[composer] (could not save ext {i} to disk: {e})")

    # ── Save the final continuous clip ──
    print(f"[composer] Downloading final continuous clip to {final_out}")
    try:
        content = client.files.download(file=current_video)
        with open(final_out, "wb") as f:
            f.write(content)
    except Exception as e:
        print(f"[composer] ❌ final download failed: {e}")
        return None

    size_mb = os.path.getsize(final_out) / (1024 * 1024)
    print(f"[composer] ✅ Continuous clip saved: {final_out} ({size_mb:.1f} MB)")

    # Probe duration
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", final_out],
        capture_output=True, text=True,
    )
    if probe.returncode == 0:
        dur = probe.stdout.strip()
        print(f"[composer]    Final duration: {dur}s")
    return final_out


def _extend_keep_video(
    client, source_video, prompt: str, orientation: str,
    generate_audio: bool, duration: int = 7, timeout_attempts: int = 30,
):
    """Same as generator.extend_video but returns the new Video object
    so we can chain the next extension on top of it.

    NOTE: veo-3.1-generate-preview does NOT honor `duration_seconds` on
    extensions — it always produces a ~7s extension. So the `duration`
    arg is currently ignored; the real timing variation is achieved by
    trimming the final continuous clip in pipeline_lib.
    """
    from google.genai import types

    veo_aspect = orientation if orientation in ("16:9", "9:16") else "16:9"
    # Snap to nearest valid value to be safe, but don't pass duration_seconds
    # for extensions — the preview model rejects it with 400.
    if duration not in (4, 6, 7, 8):
        duration = min((4, 6, 7, 8), key=lambda x: abs(x - duration))
    config = types.GenerateVideosConfig(
        number_of_videos=1,
        resolution="720p",
        aspect_ratio=veo_aspect,
        # NOTE: do NOT set generate_audio — veo-3.1-generate-preview rejects
        # this field with 400. Audio is synthesized from the prompt.
        # NOTE: do NOT set duration_seconds — the extension API ignores it
        # and on preview it can return 400. Extensions are always ~7s.
    )
    op = client.models.generate_videos(
        model=VIDEO_MODEL,
        video=source_video,
        prompt=prompt,
        config=config,
    )
    attempts = 0
    while not op.done:
        print("  [ext] waiting 10s...")
        time.sleep(10)
        op = client.operations.get(op)
        attempts += 1
        if attempts > timeout_attempts:
            print("  [ext] ❌ timed out")
            return None
    if (op.response and op.response.generated_videos
            and len(op.response.generated_videos) > 0):
        return op.response.generated_videos[0].video
    return None


# ── LEGACY: hard-cut composer (kept as fallback) ───────────────────

def generate_scene_clips(scenes: list, image_paths: List[str], orientation: str, style: str) -> List[str]:
    """Legacy: generate one independent 6-second clip per scene.

    Used as a fallback when extension mode is rejected by the preview model.
    """
    _ensure_dirs()
    clip_paths = []

    for scene, img_path in zip(scenes, image_paths):
        clip_filename = f"scene_{scene['scene_id']:02d}.mp4"
        clip_path = os.path.join(CLIPS_DIR, clip_filename)

        if os.path.exists(clip_path):
            print(f"[composer] Scene {scene['scene_id']} clip already exists, skipping")
            clip_paths.append(clip_path)
            continue

        veo_prompt = f"{scene['visual_prompt']}. Cinematic motion, smooth camera drift, no cuts."

        print(f"[composer] Scene {scene['scene_id']}/{len(scenes)}: generating clip (legacy)...")
        success = generate_video(
            prompt=veo_prompt,
            reference_image_path=img_path,
            orientation=orientation,
            style=style,
            duration=6,
            output_filename=clip_path,
            generate_audio=False,  # audio is muxed separately
        )
        if not success:
            raise RuntimeError(f"Failed to generate clip for scene {scene['scene_id']}")
        clip_paths.append(clip_path)

    return clip_paths


def compose_final_video(clip_paths: List[str], target_duration: int, output_path: str = None) -> str:
    """Concatenate scene clips with ffmpeg (legacy fallback path)."""
    if not clip_paths:
        raise ValueError("No clips to compose")

    if output_path is None:
        output_path = FINAL_PATH

    _ensure_dirs()
    list_dir = os.path.dirname(output_path) or "."
    list_path = os.path.join(list_dir, "concat_list.txt")
    with open(list_path, "w") as f:
        for clip in clip_paths:
            abs_path = os.path.abspath(clip).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    print(f"[composer] (legacy) Concatenating {len(clip_paths)} clips -> {output_path}")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_path, "-t", str(target_duration),
        "-c", "copy", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[composer] ffmpeg failed:\n{result.stderr}")
        raise RuntimeError(f"ffmpeg concat failed (exit {result.returncode})")
    return output_path


def extract_last_frame(clip_path: str, output_path: str) -> bool:
    """Extract the final non-black frame of an mp4 as a PNG.

    Kept for the last-frame fallback path.
    """
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.1",
        "-i", clip_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[composer] ❌ extract_last_frame failed: {r.stderr[-200:]}")
        return False
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def _generate_single_clip(
    prompt: str,
    reference_image_path: str,
    orientation: str,
    style: str,
    duration: int,
    output_path: str,
    last_frame_path: str = None,
) -> bool:
    """Legacy wrapper for a single-scene clip with optional last-frame."""
    if last_frame_path and os.path.exists(last_frame_path):
        ok = generate_video(
            prompt=prompt,
            reference_image_path=reference_image_path,
            orientation=orientation,
            style=style,
            duration=duration,
            output_filename=output_path,
            last_frame_path=last_frame_path,
            generate_audio=False,
        )
        if ok:
            return True
        print("[composer] ⚠️  last-frame interpolation rejected; falling back to hard cut")
    return generate_video(
        prompt=prompt,
        reference_image_path=reference_image_path,
        orientation=orientation,
        style=style,
        duration=duration,
        output_filename=output_path,
        generate_audio=False,
    )


if __name__ == "__main__":
    import json
    if not os.path.exists(os.path.join(CACHE_DIR, "scenes.json")):
        print("Run scenes.py first to generate scenes.json")
        sys.exit(1)

    with open(os.path.join(CACHE_DIR, "scenes.json")) as f:
        scenes = json.load(f)

    # Find the existing image files
    image_paths = sorted([
        os.path.join(IMAGES_DIR, f) for f in os.listdir(IMAGES_DIR)
        if f.endswith(".png")
    ])

    if len(image_paths) != len(scenes):
        print(f"Warning: found {len(image_paths)} images but {len(scenes)} scenes")

    orientation = os.environ.get("ORIENTATION", "16:9")
    style = os.environ.get("STYLE", "cinematic")

    clips = generate_scene_clips(scenes, image_paths, orientation, style)
    final = compose_final_video(clips, target_duration=len(scenes) * 6)
    print(f"Done: {final}")
