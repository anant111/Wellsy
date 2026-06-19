"""scenes.py - Generate a scene-by-scene cinematic script for a video.

Uses the `cinematic-script-writer` skill (loaded from SKILL.md) to teach Gemini
the cinematography tables, character-consistency rules, and image-prompt
format template. The skill is injected as system-prompt context; no Node CLI.

Output schema (one dict per scene):
    {
      "scene_id": int,
      "narration": str,            # voiceover text (~8-15 words)
      "visual_prompt": str,        # image-gen prompt using skill's format
      "shot_type": str,            # establishing | wide | medium | close-up | extreme close-up | detail
      "camera_angle": str,         # from the skill's camera angles table
      "camera_movement": str,      # from the skill's camera movements table
      "lighting": str,             # from the skill's lighting techniques table
      "color_grading": str,        # from the skill's color grading table
      "characters": [str],         # character names present in the scene
      "audio_prompt": str,         # voice/tone descriptor for the TTS stage
      "duration_seconds": int      # 4-8, variable per scene, sum ≈ target
    }

PER-SCENE DURATION: the model owns each scene's duration. We trim the
final continuous clip to the user's requested total. This avoids the
robotic "every scene is exactly 6s" feel.

KNOWN ISSUE: prompts that frame a person as "explaining to the viewer"
or "speaking directly to camera" get rejected by the image model
(finishReason=IMAGE_OTHER) — the cinematic language protects against
this. Visual prompts should always describe a cinematic frame, not a
"presenter" pose.
"""
import os
import json
import requests
from typing import List, Optional
from dotenv import load_dotenv

from skills_loader import load_skill

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
SKILL_NAME = "cinematic-script-writer"

# Veo 3.1 reliably generates 4, 6, 7, or 8 second clips. Per-scene duration
# is decided by the model (4-8s) and clamped to this set by the composer.
VEO_ALLOWED_DURATIONS = (4, 6, 7, 8)
ALLOWED_DURATIONS = [15, 30, 60, 120, 240]
PER_SCENE_DURATION_MIN = 4
PER_SCENE_DURATION_MAX = 8


def _system_prompt() -> str:
    """Build the Gemini system prompt: skill markdown + behaviour rules."""
    skill_md = load_skill(SKILL_NAME)
    return f"""You are a cinematic scriptwriter producing production-ready
scene-by-scene scripts for AI video generation. You write rich visual
prompts, structured voiceover, and consistent character descriptions.

You follow the conventions, tables, and rules of the skill below.

=== BEGIN SKILL: {SKILL_NAME} ===
{skill_md}
=== END SKILL ===

When you generate image prompts, USE THE SKILL'S IMAGE PROMPT FORMAT:
    [Shot type] [camera angle] of [subject doing action], [visual style] style,
    [lighting technique], [composition rule], [color grading],
    [era-appropriate details], [mood keywords], highly detailed, cinematic

When you design cinematography, MATCH IT TO EMOTION (skill rule #3):
- Power / dominance / heroism → low-angle
- Vulnerability / weakness → high-angle
- Isolation / scale → bird-eye
- Intimacy / connection → eye-level, close-up
- Tension / disorientation → dutch angle

When you introduce a character, USE THE SKILL'S FIRST-APPEARANCE TEMPLATE
and REUSE that exact description whenever the character reappears (rule #1).

ALWAYS RETURN VALID JSON. No markdown fences. No commentary."""


def generate_scenes(
    research_brief: dict,
    chosen_idea: dict,
    total_duration: int,
    orientation: str = "16:9",
    style: str = "cinematic",
    save_path: Optional[str] = None,
    language: str = "en",
) -> List[dict]:
    """Generate one scene per (total_duration / SCENE_DURATION) chunk.

    Args:
        research_brief: output of research.generate_research_brief
        chosen_idea: one of the dicts from ideas.generate_ideas
        total_duration: total seconds (15/30/60/120/240)
        orientation: "16:9" or "9:16"
        style: one of image_prompts.ALLOWED_STYLES
        save_path: where to write scenes.json (None = don't write)
        language: 'en' or 'hi' — narration text is written in this language
    """
    if total_duration not in ALLOWED_DURATIONS:
        raise ValueError(f"total_duration must be one of {ALLOWED_DURATIONS}, got {total_duration}")

    # Estimate scene count as a soft guideline, not a hard constraint. The
    # model can deviate ±2 to honor pacing. Final total is trimmed to
    # target_duration at the compose stage.
    avg_scene_duration = 6
    guideline_scenes = max(3, round(total_duration / avg_scene_duration))
    print(f"[scenes] Asking model for ~{guideline_scenes} scenes summing to "
          f"~{total_duration}s ({orientation}, {style}, {language})")
    print(f"[scenes] Chosen idea: {chosen_idea['title']} — {chosen_idea['logline'][:60]}...")

    language_directive = {
        "en": "Write all narration in fluent, conversational English.",
        "hi": "Write all narration in natural, conversational Hindi (Devanagari script). "
              "Use short sentences, present-tense verbs, and a warm voice.",
    }.get(language, "Write all narration in English.")

    # Pass the research story_arc to the scene writer so beats are assigned
    # to scenes 1:1 instead of "distribute across N scenes" (which historically
    # produced weak closings).
    beats = []
    story_arc = research_brief.get("story_arc") or {}
    if isinstance(story_arc, dict):
        beats = story_arc.get("beats") or []
        setup = (story_arc.get("setup") or "").strip()
        tension = (story_arc.get("tension") or "").strip()
        resolution = (story_arc.get("resolution") or "").strip()
    else:
        setup = tension = resolution = ""

    beat_directive = ""
    if beats:
        beat_directive = (
            "BEAT MAPPING — distribute these beats across the scenes in order:\n"
            + "\n".join(f"  beat {i+1}: {b}" for i, b in enumerate(beats))
            + f"\n(If you decide on N scenes, map beats 1..{len(beats)} to scenes 1..N; "
            "if N < number of beats, drop trailing beats; if N > number of beats, "
            "split the last beat across the extra scenes.)"
        )

    duration_directive = (
        "PER-SCENE DURATION (CRITICAL — vary the timing, do NOT make every scene the same length):\n"
        f"  - Each scene's `duration_seconds` is an integer in [{PER_SCENE_DURATION_MIN}, {PER_SCENE_DURATION_MAX}].\n"
        f"  - The sum across all scenes should be ~{total_duration}s (you may go ±10%).\n"
        "  - SHORTER (4-5s) for: quick cuts, transitional moments, action beats, time-passes.\n"
        "  - LONGER (7-8s) for: emotional beats, big reveals, the closing shot, slow pans.\n"
        "  - The CLOSING scene MUST be 7-8s and feel settled (a deliberate hold, not a quick tag).\n"
        "  - DO NOT make every scene 6s — that produces a robotic metronome feel. "
        "Mix it up based on pacing."
    )

    closing_directive = (
        "CLOSING SCENE — the most important scene. It MUST:\n"
        "  - be 7-8 seconds long (longer hold),\n"
        "  - have a SPOKEN narration of ≤10 words — short, deliberate, held. "
        "Do NOT pack the full CTA into the voiceover; the voice line is a\n"
        "    closing thought or one-word affirmation (e.g. 'Try it tonight.' or\n"
        "    'आज ही आज़माइए।'), delivered slowly with a settled pace.\n"
        "  - deliver the CALL TO ACTION as a VISUAL ELEMENT on screen — printed\n"
        "    text overlay, a brand logo, a 'Link in bio' graphic, or a final\n"
        "    branded frame. This visual CTA stays on screen for the final 2-3s,\n"
        "    lingering after the voice line lands. Describe it explicitly in the\n"
        "    visual_prompt (e.g. 'bold on-screen text reading \"TRY FREE\" lower\n"
        "    third, brand mark in corner, settled hold for final beat').\n"
        "  - resolve the visual story that was set up in scene 1 (payoff),\n"
        "  - end on a settled final frame (NOT mid-action, NOT a movement, NOT a\n"
        "    cutaway, NOT a generic 'tag your friends' shot),\n"
        "  - feel like a satisfying conclusion to the viewer, not a stop.\n"
        "\n"
        "RATIONALE: 22 words in 8 seconds feels rushed and the CTA gets lost. "
        "A held 6-10 word voiceover + a visual CTA gives the viewer time to "
        "absorb the message and is what high-performing Reels actually do."
    )

    visual_prompt_directive = (
        "VISUAL PROMPT FORMAT — every scene's `visual_prompt` MUST be a CINEMATIC FILM STILL.\n"
        "  - Describe the frame as if it were a shot from a movie, NOT a presenter or teacher.\n"
        "  - AVOID phrases like 'explaining to the viewer', 'speaking directly to camera',\n"
        "    'addressing the audience', 'looking at the camera' — these get rejected by the image model.\n"
        "  - INSTEAD: 'over-the-shoulder shot of a person pouring tea', 'close-up of hands\n"
        "    holding a steaming glass', 'medium shot of a person walking through a market'.\n"
        "  - The VOICEOVER narration can be second-person ('you', 'your') but the IMAGE\n"
        "    is always a third-person cinematic frame."
    )

    user_prompt = f"""Write a cinematic script for a ~{total_duration}s promotional video.
Target N scenes: ~{guideline_scenes} (you may choose N from {max(3, guideline_scenes - 2)} to {guideline_scenes + 2}).
Aspect ratio: {orientation}. Visual style: {style}.

LANGUAGE: {language_directive}

RESEARCH BRIEF:
Topic: {research_brief['topic']}
Audience: {research_brief['audience']}
Tone: {research_brief['tone']}
Key points: {json.dumps(research_brief['key_points'])}
Call to action: {research_brief['call_to_action']}

STORY ARC (from research):
- Setup: {setup or '(not provided)'}
- Tension: {tension or '(not provided)'}
- Resolution: {resolution or '(not provided)'}
{beat_directive}

CHOSEN CREATIVE DIRECTION:
- Title: {chosen_idea['title']}
- Logline: {chosen_idea['logline']}
- Tone: {chosen_idea['tone']}
- Hook angle: {chosen_idea['hook_angle']}
- Visual seed: {chosen_idea['visual_seed']}

NARRATIVE ARC:
- Scene 1: HOOK (use the chosen idea's hook_angle as the opening)
- Middle scenes: PROBLEM → SOLUTION (use key points, vary pacing)
- Final scene: CALL TO ACTION (use the CTA as the closing line)

{duration_directive}

{closing_directive}

{visual_prompt_directive}

CRITICAL — TWO-PART CONTINUITY TOKEN: Generate TWO strings, both of which
must be repeated verbatim across every scene.

A) `style_token` (~15-25 words — keep it short to avoid overwhelming the image model):
   the IMMUTABLE visual style. Include lighting family, color grading, visual style
   (Pixar 3D / documentary handheld / etc.), camera language. Short and punchy.

B) `setting_token` (~10-20 words): the EVOLVABLE setting. May change between
   scenes (time-of-day, location, weather). Each scene's setting_token describes
   THIS scene's setting.

Example style_token (paste in every scene):
  "Pixar 3D style, warm golden-hour key light, teal-orange grading,
   shallow depth of field, slow dolly moves"

Example setting_token scene 1:
  "Mumbai street food setting at pre-dawn, single steaming kettle"
Example setting_token scene 3:
  "Same Mumbai tapri, golden morning light now flooding the frame"

PER-SCENE REQUIREMENTS:
  scene_id: integer 1..N
  continuity_token: the SINGLE shared style_token (same in every scene)
  setting_token: this scene's setting_token
  style_token: same as continuity_token (kept for backward-compat)
  narration: 1 short sentence in {language}, 8-15 words, suitable for voiceover
  visual_prompt: BEGIN with "<style_token> <setting_token> " then the cinematic shot.
    NEVER include 'speaking to camera', 'explaining to viewer', or 'addressing the
    audience' — describe a cinematic film still instead.
  shot_type: one of (establishing, wide, medium, close-up, extreme close-up, detail)
  camera_angle: one of the skill's angles
  camera_movement: one of the skill's movements — keep it SHORT and Veo-friendly
  lighting: one of the skill's lighting techniques
  color_grading: one of the skill's color grading styles
  characters: list of character names introduced in this scene (with brief
    visual description in the visual_prompt — the FIRST time a character
    appears, give a 5-8 word visual; subsequent scenes just reference the name)
  audio_prompt: 1-sentence voice description — informational only
  duration_seconds: integer 4-8, chosen by pacing as described above

Return ONLY valid JSON — an array of N scene objects, in order, with NO
markdown fences and NO commentary. Every scene's `continuity_token` field MUST
be identical (the style_token). The `setting_token` may differ per scene.
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL}:generateContent?key={API_KEY}"
    body = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": _system_prompt()}]},
        "generationConfig": {"response_mime_type": "application/json"},
    }

    resp = requests.post(url, json=body, timeout=240)
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()

    scenes = json.loads(raw)

    # Validate + normalize
    if not isinstance(scenes, list):
        raise ValueError(f"Expected JSON array, got {type(scenes).__name__}")
    if not scenes:
        raise ValueError(f"Model returned 0 scenes")
    # The model decides N; we accept any reasonable count (≥3).
    if len(scenes) < 3:
        raise ValueError(f"Expected at least 3 scenes, got {len(scenes)}")
    if len(scenes) > 30:
        raise ValueError(f"Too many scenes ({len(scenes)}); clamping to 30")
        scenes = scenes[:30]

    total_intended = 0
    for i, s in enumerate(scenes):
        for required in ("narration", "visual_prompt"):
            if required not in s:
                raise ValueError(f"Scene {i + 1} missing required field: {required}")
        s["scene_id"] = i + 1
        s.setdefault("shot_type", "medium")
        s.setdefault("camera_angle", "eye-level")
        s.setdefault("camera_movement", "static")
        s.setdefault("lighting", "three-point")
        s.setdefault("color_grading", "teal-orange")
        s.setdefault("characters", [])
        s.setdefault("audio_prompt", "neutral narrator, calm pace")

        # Per-scene duration: model decides, we clamp to [4, 8] and snap to
        # the nearest allowed Veo length (4, 6, 7, 8 — preview rejects 5).
        raw_dur = s.get("duration_seconds")
        try:
            dur = int(raw_dur)
        except (TypeError, ValueError):
            dur = 6  # safe default
        if dur < PER_SCENE_DURATION_MIN:
            dur = PER_SCENE_DURATION_MIN
        if dur > PER_SCENE_DURATION_MAX:
            dur = PER_SCENE_DURATION_MAX
        # Snap to nearest of {4, 6, 7, 8}
        dur = min(VEO_ALLOWED_DURATIONS, key=lambda x: abs(x - dur))
        s["duration_seconds"] = dur
        total_intended += dur

    # Backfill a continuity_token (the IMMUTABLE style token) if the model
    # didn't provide one: derive a stable one from scene 1's cinematography.
    # Also support the new two-part style_token + setting_token split.
    style = ""
    for s in scenes:
        if s.get("style_token"):
            style = s["style_token"]
            break
    if not style:
        for s in scenes:
            if s.get("continuity_token"):
                style = s["continuity_token"]
                break
    if not style:
        s0 = scenes[0]
        style = (
            f"{s0.get('lighting', 'three-point')} lighting, "
            f"{s0.get('color_grading', 'teal-orange')} color grade, "
            f"{style} visual style, {orientation} framing, "
            f"{s0.get('camera_movement', 'static')} camera"
        )
    for s in scenes:
        s["style_token"] = style
        s["continuity_token"] = style  # back-compat alias
        if not s.get("setting_token"):
            s["setting_token"] = s.get("continuity_token", style)

    # Per-scene duration breakdown — the model owns each scene's timing.
    durations = [s["duration_seconds"] for s in scenes]
    breakdown = " + ".join(f"{d}s" for d in durations)
    # Closing-scene guardrail: the final scene's narration should be ≤10 words
    # so it can be delivered deliberately in the 7-8s hold. Flag violations so
    # we can iterate on the prompt if the model keeps packing too much in.
    closing = scenes[-1]
    closing_words = len((closing.get("narration") or "").split())
    closing_flag = ""
    if closing_words > 10:
        closing_flag = (
            f"  ⚠️  Closing narration is {closing_words} words (>10). "
            f"Will feel rushed in 7-8s. Consider tightening the prompt."
        )
    print(f"[scenes] ✅ Generated {len(scenes)} scenes; style token "
          f"({len(style.split())} words); per-scene durations: [{breakdown}] "
          f"= {total_intended}s (target {total_duration}s, will trim)")
    for s in scenes:
        setting = s.get('setting_token', s.get('continuity_token', ''))[:60]
        print(f"  {s['scene_id']:>2}. [{s['shot_type']}/{s['camera_angle']}/{s['lighting']}, "
              f"{s['duration_seconds']}s] {s['narration'][:50]}...  (setting: {setting}...)")
    if closing_flag:
        print(closing_flag)

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(scenes, f, indent=2)
        print(f"[scenes] Saved to {save_path}")

    return scenes


if __name__ == "__main__":
    import sys

    # Minimal smoke test: requires a research brief and an idea
    brief = {
        "topic": "Promote a noise-cancelling headphone for remote workers",
        "audience": "Knowledge workers in open-plan homes who struggle to focus",
        "tone": "calm, premium, slightly playful",
        "key_points": [
            "Best-in-class noise cancellation",
            "All-day comfort",
            "Crystal-clear call quality",
            "Seamless multi-device pairing",
            "30-hour battery life",
        ],
        "hook_ideas": [
            "The loudest sound in a remote worker's day is silence itself.",
            "Focus is a luxury. We make it affordable.",
            "What does productivity sound like?",
        ],
        "call_to_action": "Hear the difference. Try them risk-free for 30 days.",
    }
    from ideas import generate_ideas
    ideas = generate_ideas(brief, count=3)
    chosen = ideas[0]
    scenes = generate_scenes(brief, chosen, total_duration=15)
    print(json.dumps(scenes, indent=2))
