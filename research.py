"""research.py - Generate a research brief for the video topic.

Adapted from the content-research-writer skill pattern (outline + key points +
hook ideas), but tailored for short-form video production.
"""
import os
import json
import requests
from dotenv import load_dotenv

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
CACHE_DIR = ".cache"


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def generate_research_brief(topic: str, save: bool = True, language: str = "en") -> dict:
    """Use Gemini to produce a research brief as structured JSON.

    Returns a dict with: topic, audience, tone, key_points, hook_options,
    story_arc, emotional_target, target_audience, cultural_anchors, cta.

    Default bias is Indian audience context unless the topic clearly is not
    India-relevant. The `language` param steers cultural anchors and example
    phrasing toward Hindi- or English-speaking audiences.
    """
    print(f"[research] Generating brief for: {topic}")

    language_block = {
        "en": "Use natural English phrasing for hooks and narrations.",
        "hi": "Use natural Hindi (Devanagari) phrasing for hooks and narrations. "
              "Anchor examples in Indian context (Mumbai, Delhi, Bengaluru, local "
              "festivals, cricket, Bollywood, street food, etc.).",
    }.get(language, "Use natural English.")

    prompt = f"""You are a video marketing strategist. Analyze the topic below and produce a concise research brief for a short-form promotional video.

TOPIC: {topic}

LANGUAGE: {language_block}

DEFAULT AUDIENCE: India (urban, 22-40, mobile-first, watches Reels + Shorts in {'Hindi' if language == 'hi' else 'English'}). If the topic is clearly location-agnostic and not India-specific, keep the default; if it is explicitly US/EU/global, set target_audience accordingly.

Return ONLY valid JSON (no markdown fences, no commentary) in this exact shape:
{{
  "topic": "<the topic restated clearly>",
  "audience": "<who this video is for, 1 sentence>",
  "target_audience": "<India (default) | <other country/region if topic demands it>>",
  "cultural_anchors": ["<India-flavored reference 1>", "<reference 2>", "<reference 3>"],
  "tone": "<3-5 adjectives describing the desired feel>",
  "key_points": ["<point 1>", "<point 2>", "<point 3>", "<point 4>", "<point 5>"],
  "hook_options": [
    "<opening line 1 — question>",
    "<opening line 2 — surprising statement>",
    "<opening line 3 — emotional / bold>"
  ],
  "story_arc": {{
    "setup": "<1 sentence: the world before the solution>",
    "tension": "<1 sentence: the friction or desire>",
    "resolution": "<1 sentence: how the product/topic resolves it>",
    "beats": ["<beat 1>", "<beat 2>", "<beat 3>"]
  }},
  "emotional_target": "<1-2 adjectives: what should the viewer FEEL after watching>",
  "call_to_action": "<compelling CTA, <= 8 words>"
}}

Constraints:
- key_points: exactly 5 short phrases, each <= 12 words
- hook_options: 3 punchy opening lines (question, statement, or surprising fact), each <= 15 words
- story_arc.beats: 3 short beats, each <= 10 words
- call_to_action: imperative, action-oriented
- cultural_anchors: when target_audience is India, include references like 'local train', 'chai', 'IPL', 'auto-rickshaw', 'monsoon', 'Diwali', 'Mumbai local', etc.
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL}:generateContent?key={API_KEY}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    resp = requests.post(url, json=body, timeout=120)
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    # Some Gemini models return JSON in a code fence; strip defensively
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()

    brief = json.loads(raw)
    # Backfill renamed fields so downstream code (which expects hook_options)
    # and log lines (which referenced hook_ideas) both work.
    if "hook_options" in brief and "hook_ideas" not in brief:
        brief["hook_ideas"] = brief["hook_options"]

    print(f"[research] ✅ Got brief: {brief['topic']}")
    print(f"[research]    {len(brief['key_points'])} key points, "
          f"{len(brief.get('hook_options', brief.get('hook_ideas', [])))} hook options")

    if save:
        _ensure_cache_dir()
        with open(os.path.join(CACHE_DIR, "research.json"), "w") as f:
            json.dump(brief, f, indent=2)
        print(f"[research] Saved to {CACHE_DIR}/research.json")

    return brief


if __name__ == "__main__":
    import sys
    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Promote a noise-cancelling headphone for remote workers"
    brief = generate_research_brief(topic)
    print(json.dumps(brief, indent=2))
