"""scorer.py - Self-score stage: Gemini watches the final mp4 and grades it.

Uses the Files API to upload the rendered video, then asks
`gemini-3.1-pro-preview` to score it on 5 axes (1-10 each):
  - hook              (does the first ~2s grab attention?)
  - story             (is there a clear narrative arc across the video?)
  - momentum          (does the pacing keep you watching?)
  - emotional_linkage (does the emotional thread connect scene to scene?)
  - closing           (does the ending deliver the CTA and feel resolved?)

The model is told to be strict. We then check against `threshold` (default 7)
per axis and surface a structured JSON result to pipeline_lib.
"""
import json
import os
import time
from typing import Optional

from dotenv import load_dotenv

# env loading (same pattern as other modules)
def _find_and_load_dotenv():
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        candidate = os.path.join(here, ".env")
        if os.path.exists(candidate):
            load_dotenv(dotenv_path=candidate)
            return
        here = os.path.dirname(here)
    load_dotenv()


_find_and_load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
TEXT_MODEL = os.getenv("TEXT_MODEL", "gemini-3.1-pro-preview")
GEMINI_FILES_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"


SCORE_RUBRIC = """You are a senior short-form video critic (Instagram Reels / YouTube Shorts).

Watch the uploaded video and score it on these 5 axes, each 1-10.
Be strict. Most videos deserve 5-7; reserve 8+ for genuinely excellent work.

Axes:
- hook (1-10): do the first ~2 seconds grab the viewer's attention and make them keep watching?
- story (1-10): is there a clear narrative arc (setup → tension → resolution / call to action)?
- momentum (1-10): does the pacing carry the viewer through without dead air or repetition?
- emotional_linkage (1-10): does the emotional thread connect from scene to scene (visual + audio + voiceover)?
- closing (1-10): does the ending deliver the call to action and feel like a satisfying conclusion (not a hard stop)?

Also provide:
- total: integer sum of the 5 axes (range 5-50)
- one_line_verdict: a single sentence, plain English, telling the creator what to fix FIRST
- one_line_strength: a single sentence naming the strongest aspect of the video

Return ONLY valid JSON (no markdown fences, no commentary), in this exact shape:
{
  "hook": <int 1-10>,
  "story": <int 1-10>,
  "momentum": <int 1-10>,
  "emotional_linkage": <int 1-10>,
  "closing": <int 1-10>,
  "total": <int>,
  "one_line_verdict": "<...>",
  "one_line_strength": "<...>"
}
"""


def _upload_video(path: str) -> Optional[str]:
    """Upload a local mp4 to the Gemini Files API. Returns the file URI or None."""
    import requests
    if not os.path.exists(path):
        print(f"[scorer] ❌ video not found: {path}")
        return None
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > 2048:  # Files API practical limit ~2GB
        print(f"[scorer] ❌ video too large: {size_mb:.0f} MB")
        return None
    # Step 1: initiate resumable upload
    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(os.path.getsize(path)),
        "X-Goog-Upload-Header-Content-Type": "video/mp4",
        "Content-Type": "application/json",
    }
    body = {"file": {"display_name": os.path.basename(path)}}
    r = requests.post(
        f"{GEMINI_FILES_URL}?key={API_KEY}",
        headers=headers, json=body, timeout=60,
    )
    if r.status_code != 200:
        print(f"[scorer] ❌ upload init failed: {r.status_code} {r.text[:200]}")
        return None
    upload_url = r.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        print(f"[scorer] ❌ no upload URL in response")
        return None
    # Step 2: send bytes
    with open(path, "rb") as f:
        r2 = requests.post(
            upload_url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
                "Content-Type": "video/mp4",
            },
            data=f.read(), timeout=300,
        )
    if r2.status_code != 200:
        print(f"[scorer] ❌ upload finalize failed: {r2.status_code} {r2.text[:200]}")
        return None
    file_info = r2.json().get("file", {})
    name = file_info.get("name")  # e.g. "files/abc123"
    uri = file_info.get("uri") or name
    state = file_info.get("state", "UNKNOWN")
    print(f"[scorer] uploaded {path} ({size_mb:.1f} MB) -> {uri} (state={state})")

    # Step 3: poll until state == ACTIVE. The Files API requires the file
    # to be ACTIVE before generateContent can reference it. For video
    # this can take 5-30s.
    if state != "ACTIVE":
        print(f"[scorer] waiting for file to become ACTIVE...")
        for attempt in range(30):  # up to ~5 min
            time.sleep(5)
            try:
                r3 = requests.get(
                    f"https://generativelanguage.googleapis.com/v1beta/{name}?key={API_KEY}",
                    timeout=30,
                )
                if r3.status_code == 200:
                    cur_state = r3.json().get("state", "UNKNOWN")
                    if cur_state == "ACTIVE":
                        print(f"[scorer] file is ACTIVE after {(attempt+1)*5}s")
                        return uri
                    if cur_state == "FAILED":
                        print(f"[scorer] ❌ file FAILED to process: {r3.text[:200]}")
                        return None
            except Exception as e:
                print(f"[scorer] poll error: {e}")
        print(f"[scorer] ❌ file did not become ACTIVE in time")
        return None

    return uri


def _call_gemini_with_video(file_uri: str, brief: dict, chosen_idea,
                            scenes: list, language: str) -> Optional[dict]:
    """Send the video + context to Gemini, parse the JSON score response."""
    import requests
    ctx_lines = [
        f"Topic: {brief.get('topic', '')}",
        f"Audience: {brief.get('audience', '')}",
        f"Tone: {brief.get('tone', '')}",
        f"Language: {language}",
    ]
    if chosen_idea:
        ctx_lines.append(f"Chosen idea: {chosen_idea.get('title','')} — {chosen_idea.get('logline','')}")
    if scenes:
        ctx_lines.append("Scene narrations:")
        for s in scenes:
            ctx_lines.append(f"  {s.get('scene_id')}. {s.get('narration','')}")

    user_prompt = (
        "Score the attached video using the rubric.\n\n"
        "CONTEXT (from the research brief and chosen idea):\n"
        + "\n".join(ctx_lines)
    )

    body = {
        "contents": [{
            "parts": [
                {"text": user_prompt},
                {"fileData": {"mimeType": "video/mp4", "fileUri": file_uri}},
            ],
        }],
        "systemInstruction": {"parts": [{"text": SCORE_RUBRIC}]},
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{TEXT_MODEL}:generateContent?key={API_KEY}"
    )
    r = requests.post(url, json=body, timeout=300)
    if r.status_code != 200:
        print(f"[scorer] ❌ Gemini call failed: {r.status_code} {r.text[:200]}")
        return None
    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[scorer] ❌ could not parse score JSON: {e}\nRaw: {raw[:300]}")
        return None


def _delete_file(file_uri: str) -> None:
    """Best-effort cleanup of the uploaded file."""
    import requests
    try:
        # file_uri looks like 'files/abc123'
        name = file_uri.split("/")[-1] if "/" in file_uri else file_uri
        requests.delete(
            f"https://generativelanguage.googleapis.com/v1beta/{file_uri}?key={API_KEY}",
            timeout=30,
        )
    except Exception:
        pass


def score_video(final_path: str, brief: dict, chosen_idea,
                scenes: list, language: str) -> dict:
    """Score the final mp4. Returns a dict of axes (1-10) plus verdict."""
    print(f"[scorer] scoring {final_path}...")
    file_uri = _upload_video(final_path)
    if not file_uri:
        return {
            "hook": 5, "story": 5, "momentum": 5,
            "emotional_linkage": 5, "closing": 5, "total": 25,
            "one_line_verdict": "scoring failed (upload error); defaulting to neutral",
            "one_line_strength": "n/a",
        }
    try:
        score = _call_gemini_with_video(file_uri, brief, chosen_idea, scenes, language)
    finally:
        _delete_file(file_uri)
    if not score:
        return {
            "hook": 5, "story": 5, "momentum": 5,
            "emotional_linkage": 5, "closing": 5, "total": 25,
            "one_line_verdict": "scoring failed (parse error); defaulting to neutral",
            "one_line_strength": "n/a",
        }
    # Sanity-check the axes
    for axis in ("hook", "story", "momentum", "emotional_linkage", "closing"):
        v = int(score.get(axis, 5))
        score[axis] = max(1, min(10, v))
    score["total"] = sum(score[a] for a in ("hook", "story", "momentum", "emotional_linkage", "closing"))
    print(f"[scorer] ✅ score={score['total']}/50 "
          f"hook={score['hook']} story={score['story']} momentum={score['momentum']} "
          f"emo={score['emotional_linkage']} close={score['closing']}")
    return score


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else ".cache/final.mp4"
    brief = {"topic": "demo", "audience": "demo", "tone": "demo"}
    print(json.dumps(score_video(path, brief, None, [], "en"), indent=2))
