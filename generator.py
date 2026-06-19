import os
import time
import base64
import mimetypes
import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Robust env loading: walk up the directory tree to find .env
def _find_and_load_dotenv():
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        candidate = os.path.join(here, ".env")
        if os.path.exists(candidate):
            load_dotenv(dotenv_path=candidate)
            return candidate
        here = os.path.dirname(here)
    # Fallback: default location
    load_dotenv()
    return None

_find_and_load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

TEXT_MODEL = os.getenv("TEXT_MODEL", "gemini-3.1-pro-preview")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "nano-banana-pro-preview")
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "veo-3.1-generate-preview")

client = genai.Client(api_key=API_KEY)
OUTPUT_DIR = "."

# Exhaustive list of video/image styles for the prompt construction
STYLES = [
    "realistic", "cinematic", "informational", "anime", "watercolor",
    "3d_render", "sketch", "neon_punk", "vintage", "documentary",
    "drone_footage", "macro", "surrealism"
]


def _file_to_image(path):
    """Load a local image file and convert it into a google.genai types.Image.

    The Veo schema expects `imageBytes` (base64-encoded) + `mimeType` directly
    on the Image object.
    """
    mime_type, _ = mimetypes.guess_type(path)
    mime_type = mime_type or "image/png"
    with open(path, "rb") as f:
        raw = f.read()
    return types.Image(imageBytes=base64.b64encode(raw).decode("utf-8"),
                       mimeType=mime_type)


def extend_video(source_video, prompt, aspect_ratio="16:9",
                 generate_audio=True, output_filename="extended.mp4",
                 timeout_attempts: int = 30) -> bool:
    """Extend a previously-generated Veo clip by ~7s.

    The Veo 3.1 video-extension feature works by passing the source clip's
    SDK Video object to a new generate_videos() call. The output is a single
    mp4 that contains the original clip + the new ~7s appended.

    Args:
        source_video: the SDK Video object from a prior generate_videos op
            (i.e. `operation.response.generated_videos[0].video`). NOT a path.
        prompt: text prompt for the continuation segment. Should include
            "Voiceover (in <language>): <narration>." for native audio.
        aspect_ratio: 16:9 or 9:16 (must match the source clip's ratio).
        generate_audio: True to let Veo synthesize voice/SFX for the
            extension. Should match the source clip's setting.
        output_filename: local path to write the new (extended) mp4.
        timeout_attempts: poll attempts at 10s each (default 5 min).

    Returns:
        True on success (file written); False on failure.

    Reference: https://ai.google.dev/gemini-api/docs/video#extensions
    """
    if aspect_ratio not in ("16:9", "9:16"):
        print(f"  (mapping requested orientation {aspect_ratio} -> 16:9)")
        aspect_ratio = "16:9"

    print(f"[extend] Appending ~7s to source video via {VIDEO_MODEL} (audio={generate_audio})...")

    try:
        config = types.GenerateVideosConfig(
            number_of_videos=1,
            resolution="720p",
            aspect_ratio=aspect_ratio,
            generate_audio=bool(generate_audio),
        )
        operation = client.models.generate_videos(
            model=VIDEO_MODEL,
            video=source_video,
            prompt=prompt,
            config=config,
        )
        attempts = 0
        while not operation.done:
            print("  [extend] waiting 10s...")
            time.sleep(10)
            operation = client.operations.get(operation)
            attempts += 1
            if attempts > timeout_attempts:
                print("  [extend] ❌ timed out")
                return False

        if (operation.response
                and hasattr(operation.response, "generated_videos")
                and operation.response.generated_videos
                and len(operation.response.generated_videos) > 0):
            video_obj = operation.response.generated_videos[0]
            content = client.files.download(file=video_obj.video)
            with open(output_filename, "wb") as f:
                f.write(content)
            size_kb = os.path.getsize(output_filename) / 1024
            print(f"  [extend] ✅ extended to {output_filename} ({size_kb:.0f} KB)")
            return True
        print("  [extend] ❌ operation complete, no video returned")
        return False
    except Exception as e:
        print(f"  [extend] ❌ failed: {e}")
        return False


def generate_image(prompt, reference_image_path=None, orientation="16:9",
                   style="cinematic", output_filename="workshop_ad.png",
                   max_retries: int = 3):
    """Generates an image via REST using nano-banana/imagen with optional conditioning.

    Retries on transient errors (5xx, network, empty inlineData) with
    exponential backoff. The nano-banana-pro-preview model occasionally
    returns a 200 with no image data; we treat that as a retryable failure
    rather than killing the whole job.
    """
    print(f"Generating Image ({orientation}, {style}) via {IMAGE_MODEL}...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_MODEL}:generateContent?key={API_KEY}"
    headers = {"Content-Type": "application/json"}

    enhanced_prompt = f"Aspect Ratio: {orientation}. Style: {style}. {prompt}"
    parts = [{"text": enhanced_prompt}]

    if reference_image_path and os.path.exists(reference_image_path):
        with open(reference_image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        parts.append({
            "inlineData": {
                "mimeType": "image/png",
                "data": encoded_string
            }
        })

    data = {"contents": [{"parts": parts}]}

    import time as _t
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=120)
            response.raise_for_status()
            result = response.json()

            ret_parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for part in ret_parts:
                if "inlineData" in part:
                    b64_img = part["inlineData"]["data"]
                    filepath = os.path.join(OUTPUT_DIR, output_filename)
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(b64_img))
                    print(f"✅ Image saved to {output_filename} (attempt {attempt})")
                    return True
            # 200 OK but no image: log the response shape for debugging
            finish_reason = (
                result.get("candidates", [{}])[0].get("finishReason")
                if result.get("candidates") else None
            )
            safety_ratings = (
                result.get("candidates", [{}])[0].get("safetyRatings")
                if result.get("candidates") else None
            )
            print(f"❌ Image attempt {attempt}/{max_retries}: 200 OK but no inlineData "
                  f"(finishReason={finish_reason}, safetyRatings={safety_ratings})")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            print(f"❌ Image attempt {attempt}/{max_retries}: HTTP {status} {str(e)[:120]}")
            if status == 400 or status == 403:
                # Bad request or auth — retrying won't help
                return False
        except Exception as e:
            print(f"❌ Image attempt {attempt}/{max_retries}: {e}")

        if attempt < max_retries:
            backoff = 5 * (2 ** (attempt - 1))  # 5, 10, 20s
            print(f"   retrying in {backoff}s...")
            _t.sleep(backoff)

    print(f"❌ Image generation failed after {max_retries} attempts")
    return False


def generate_video(prompt, reference_image_path=None, reference_audio_path=None,
                   last_frame_path=None, reference_images_paths=None,
                   orientation="16:9", style="cinematic", duration=9,
                   output_filename="workshop_ad.mp4", generate_audio=True,
                   return_operation=False):
    """Generates video via Veo using the official google-genai SDK.

    Supports:
      - text-to-video             (just provide prompt)
      - image-to-video            (reference_image_path)
      - first→last frame interp   (reference_image_path + last_frame_path)
      - reference images          (reference_images_paths list, up to 3)
      - audio/voiceover           (reference_audio_path OR generate_audio=True
                                   with a "Voiceover: ..." prompt for Veo-native
                                   audio generation, including Hindi)

    Reference: https://ai.google.dev/gemini-api/docs/video

    All rich options (duration, aspect_ratio, last_frame, reference_images,
    generate_audio, etc.) live inside `config=types.GenerateVideosConfig(...)`.

    If `return_operation=True`, the function returns the live operation object
    instead of a bool. The caller's caller can then pass
    `op.response.generated_videos[0].video` into `extend_video()` for chaining,
    avoiding a redundant second generate_videos call. Returns None on failure.
    """
    print(f"Generating Video ({duration}s, {orientation}, {style}) via {VIDEO_MODEL}...")

    uploaded_files = []
    try:
        enhanced_prompt = f"{prompt}"

        # Build config with all the rich Veo options
        # Note: not all models support every config field. We only set the
        # ones that the current model (veo-3.1-generate-preview) supports.
        # Valid aspect ratios for Veo: 16:9, 9:16 (NOT 1:1).
        # Map "1:1" -> "9:16" to gracefully fail.
        veo_aspect = orientation if orientation in ("16:9", "9:16") else "16:9"
        if veo_aspect != orientation:
            print(f"  (mapping requested orientation {orientation} -> {veo_aspect})")

        # Veo 3.1-generate-preview supports durations 6-8 seconds inclusive
        # (despite the API error message claiming 4-8, empirical testing shows
        # 5 is rejected — actual valid range is 6-8).
        if duration < 6:
            print(f"  (clamping duration {duration}s -> 6s minimum)")
            duration = 6
        if duration > 8:
            print(f"  (clamping duration {duration}s -> 8s maximum)")
            duration = 8

        config = types.GenerateVideosConfig(
            duration_seconds=duration,
            aspect_ratio=veo_aspect,
        )
        # NOTE: do NOT set config.generate_audio — the veo-3.1-generate-preview
        # model returns 400 INVALID_ARGUMENT for that field. Audio is
        # synthesized automatically from the prompt (e.g. "Voiceover (in
        # Hindi): ...").

        # First/last frame interpolation (must be set on config)
        if last_frame_path and os.path.exists(last_frame_path):
            print(f"Attaching last frame {last_frame_path}...")
            config.last_frame = _file_to_image(last_frame_path)

        # Up to 3 reference images for style/character guidance
        if reference_images_paths:
            ref_imgs = []
            for p in reference_images_paths[:3]:
                if os.path.exists(p):
                    print(f"Attaching reference image {p}...")
                    ref_imgs.append(_file_to_image(p))
            if ref_imgs:
                # Each reference image can be tagged with a reference_type
                config.reference_images = [
                    types.VideoGenerationReferenceImage(image=img)
                    for img in ref_imgs
                ]

        # Audio (voiceover / soundtrack) — must be uploaded via Files API
        if reference_audio_path and os.path.exists(reference_audio_path):
            print(f"Uploading audio {reference_audio_path}...")
            aud = client.files.upload(file=reference_audio_path)
            uploaded_files.append(aud)
            # Some SDK builds accept audio in config; if not, we can pass via
            # the prompt side as a last resort. Config is the documented path.
            try:
                config.generate_audio = True
            except Exception:
                pass

        # Build kwargs — only include image if we have a real local file
        kwargs = {
            "model": VIDEO_MODEL,
            "prompt": enhanced_prompt,
            "config": config,
        }
        if reference_image_path and os.path.exists(reference_image_path):
            print(f"Attaching initial image {reference_image_path}...")
            kwargs["image"] = _file_to_image(reference_image_path)

        operation = client.models.generate_videos(**kwargs)

        if return_operation:
            # Caller wants the live operation handle so they can chain
            # extend_video() without re-running generate_videos. We still
            # block here until completion, but we return the operation
            # (after saving the file as a side effect so disk state is
            # the same as the non-return path).
            attempts = 0
            while not operation.done:
                print("Generating video... waiting 10 seconds.")
                time.sleep(10)
                operation = client.operations.get(operation)
                attempts += 1
                if attempts > 30:
                    print("❌ Video generation timed out.")
                    return None
            if (operation.response
                    and hasattr(operation.response, "generated_videos")
                    and operation.response.generated_videos
                    and len(operation.response.generated_videos) > 0):
                video_obj = operation.response.generated_videos[0]
                content = client.files.download(file=video_obj.video)
                filepath = os.path.join(OUTPUT_DIR, output_filename)
                with open(filepath, "wb") as f:
                    f.write(content)
                print(f"✅ Video saved as {output_filename} (return_operation=True)")
                return operation
            print("❌ Operation complete, but no video was returned.")
            return None

        attempts = 0
        while not operation.done:
            print("Generating video... waiting 10 seconds.")
            time.sleep(10)
            operation = client.operations.get(operation)
            attempts += 1
            if attempts > 30:  # 5 minutes max
                print("❌ Video generation timed out.")
                return False

        if (operation.response
                and hasattr(operation.response, "generated_videos")
                and operation.response.generated_videos
                and len(operation.response.generated_videos) > 0):
            video_obj = operation.response.generated_videos[0]
            content = client.files.download(file=video_obj.video)

            filepath = os.path.join(OUTPUT_DIR, output_filename)
            with open(filepath, "wb") as f:
                f.write(content)
            print(f"✅ Video saved as {output_filename}")
            return True
        else:
            print("❌ Operation complete, but no video was returned.")
            return False

    except Exception as e:
        print(f"❌ Failed to generate video: {str(e)}")
        return False
    finally:
        for f in uploaded_files:
            try:
                client.files.delete(name=f.name)
                print(f"Cleaned up remote file {f.name}")
            except Exception:
                pass
