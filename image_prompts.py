"""image_prompts.py - Build nano-banana-style structured image prompts.

Implements the structured JSON template from
minilozio/nano-banana-prompting-skill (the canonical "nano-banana" skill
on skillsmp, used in the lob ehub community).

9 style categories:
    cinematic | product | street | illustration | anime | 3d | watercolor | minimalist | surreal

Output is a JSON dict that the generator.py wraps into a text prompt for
nano-banana-pro-preview.
"""
import json

# Style categories the user can pick from. Keep this in sync with pipeline.py
ALLOWED_STYLES = [
    "cinematic", "realistic", "anime", "3d", "watercolor",
    "minimalist", "surreal", "illustration", "street", "podcast",
]

# Aliases the user might use -> canonical style
_STYLE_ALIASES = {
    "realistic": "cinematic",
    "photorealistic": "cinematic",
    "photography": "cinematic",
    "cinematic": "cinematic",
    "podcast": "cinematic",
    "informational": "cinematic",
    "anime": "anime",
    "manga": "anime",
    "3d": "3d",
    "3d_render": "3d",
    "pixar": "3d",
    "cgi": "3d",
    "watercolor": "watercolor",
    "oil_painting": "watercolor",
    "sketch": "watercolor",
    "minimalist": "minimalist",
    "flat": "minimalist",
    "vector": "minimalist",
    "surreal": "surreal",
    "abstract": "surreal",
    "dreamlike": "surreal",
    "illustration": "illustration",
    "digital_art": "illustration",
    "concept_art": "illustration",
    "street": "street",
    "documentary": "street",
    "candid": "street",
}


def _canonical_style(style: str) -> str:
    return _STYLE_ALIASES.get(style.lower(), "cinematic")


def _parse_visual_prompt(visual_prompt: str) -> dict:
    """Best-effort parse of the scene's visual_prompt into structured parts.

    The visual_prompt from scenes.py looks like:
        "Wide shot of a person in a coffee shop, holding headphones,
         warm ambient light, cinematic mood"

    We split on commas (with some basic cleanup) into subject / setting /
    lighting / mood.
    """
    parts = [p.strip() for p in visual_prompt.split(",") if p.strip()]

    subject = parts[0] if parts else visual_prompt
    setting = parts[1] if len(parts) > 1 else "natural environment"
    lighting = next((p for p in parts if any(k in p.lower() for k in
                   ["light", "shadow", "glow", "bright", "dark", "sun", "neon"])), "soft ambient lighting")
    mood = next((p for p in parts if any(k in p.lower() for k in
                ["mood", "vibe", "atmosphere", "feeling", "calm", "energetic", "mysterious", "warm", "cold"])),
                "engaging atmosphere")

    return {"subject": subject, "setting": setting, "lighting": lighting, "mood": mood}


def build_prompt(scene: dict, style: str, orientation: str = "16:9") -> dict:
    """Build a nano-banana-style structured JSON prompt for a scene.

    Returns a dict that can be (a) saved as JSON for inspection or
    (b) serialized into a single text prompt for the image model.
    """
    canonical = _canonical_style(style)
    parts = _parse_visual_prompt(scene["visual_prompt"])

    # Style-specific section
    if canonical == "cinematic":
        style_specific = {
            "photography": {
                "camera": "ARRI Alexa Mini",
                "lens": "35mm prime",
                "shot_type": scene.get("shot_type", "medium"),
                "lighting": parts["lighting"],
                "film_stock": "Kodak Vision3 500T",
            }
        }
    elif canonical == "3d":
        style_specific = {
            "render": {
                "engine": "Octane",
                "subsurface": True,
                "ray_traced_global_illumination": True,
                "subsurface_scattering": "skin",
            }
        }
    elif canonical == "anime":
        style_specific = {
            "art_style": {
                "studio": "Studio Ghibli influence",
                "line_work": "clean cel-shaded",
                "shading": "soft gradient",
            }
        }
    elif canonical == "watercolor":
        style_specific = {
            "art_style": {
                "medium": "watercolor on cold press paper",
                "brush": "wet on wet",
                "pigment": "rich saturated",
            }
        }
    elif canonical == "minimalist":
        style_specific = {
            "art_style": {
                "style": "flat vector",
                "palette": "limited 3 colors",
                "composition": "rule of thirds, lots of negative space",
            }
        }
    elif canonical == "surreal":
        style_specific = {
            "art_style": {
                "style": "Dalí-inspired surrealism",
                "elements": "floating, dreamlike, impossible geometry",
            }
        }
    elif canonical == "illustration":
        style_specific = {
            "art_style": {
                "style": "digital concept art",
                "brush": "painterly with rim lighting",
            }
        }
    elif canonical == "street":
        style_specific = {
            "photography": {
                "camera": "Leica M6",
                "lens": "28mm",
                "shot_type": "candid",
                "film_stock": "Kodak Tri-X 400",
            }
        }
    else:
        style_specific = {}

    # Build the prompt dict
    prompt = {
        "instruction": f"Generate a single {orientation} {canonical} image for a {scene['duration_seconds']}s video scene",
        "subject": parts["subject"],
        "scene": parts["setting"],
        "style": canonical,
        "style_specific": style_specific,
        "mood": parts["mood"],
        "color_palette": "complementary, balanced, professional grade",
        "aspect_ratio": orientation,
        "quality": _quality_for(canonical),
        "negative": "no text, no watermark, no deformed faces, no extra limbs, no low resolution",
    }
    return prompt


def _quality_for(canonical: str) -> str:
    if canonical == "cinematic":
        return "8K, photorealistic, cinematic color grade, shallow depth of field"
    if canonical == "3d":
        return "8K, Octane render, ray-traced, physically based"
    if canonical == "anime":
        return "high resolution, trending on Pixiv, beautiful detailed"
    if canonical == "watercolor":
        return "high resolution, master watercolor, paper texture visible"
    if canonical == "minimalist":
        return "vector clean, sharp edges, scalable"
    if canonical == "surreal":
        return "8K, hyper-detailed, dreamlike"
    if canonical == "illustration":
        return "8K, trending on ArtStation, digital painting"
    if canonical == "street":
        return "grainy film, high ISO, authentic documentary"
    return "high quality"


def to_text_prompt(prompt_dict: dict) -> str:
    """Serialize a structured prompt dict to a single text prompt for nano-banana.

    The nano-banana model accepts natural language; we fold the JSON structure
    into a clean comma-separated string.
    """
    lines = [
        f"Aspect ratio: {prompt_dict['aspect_ratio']}.",
        f"Style: {prompt_dict['style']}.",
        f"Subject: {prompt_dict['subject']}.",
        f"Scene: {prompt_dict['scene']}.",
        f"Mood: {prompt_dict['mood']}.",
        f"Color palette: {prompt_dict['color_palette']}.",
        f"Quality: {prompt_dict['quality']}.",
    ]
    ss = prompt_dict.get("style_specific", {})
    if "photography" in ss:
        p = ss["photography"]
        lines.append(f"Photography: {p.get('shot_type', '')} on {p.get('camera', '')} "
                     f"with {p.get('lens', '')} lens, {p.get('lighting', '')}, "
                     f"film: {p.get('film_stock', '')}.")
    if "render" in ss:
        r = ss["render"]
        lines.append(f"3D render: {r.get('engine', '')}, "
                     f"ray-traced global illumination, subsurface scattering.")
    if "art_style" in ss:
        lines.append(f"Art: {json.dumps(ss['art_style'])}.")
    lines.append(f"Avoid: {prompt_dict['negative']}.")
    return " ".join(lines)


if __name__ == "__main__":
    scene = {
        "scene_id": 1,
        "narration": "Imagine a quiet morning.",
        "visual_prompt": "wide shot of a person sipping coffee by a window, soft morning light, calm atmosphere",
        "shot_type": "wide",
        "duration_seconds": 6,
    }
    p = build_prompt(scene, style="cinematic", orientation="16:9")
    print(json.dumps(p, indent=2))
    print("\n--- TEXT PROMPT ---\n")
    print(to_text_prompt(p))
