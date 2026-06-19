"""ideas.py - Generate 3 distinct creative directions for a video.

This is the first sub-step of the "scenes" stage. The user (or a 30s
auto-pick) chooses one direction, which is then passed to scenes.py to
generate the actual scene-by-scene script.
"""
import os
import json
import requests
from typing import List, Optional
from dotenv import load_dotenv

from skills_loader import load_skill

# Same env-loading pattern as generator.py / research.py
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


def generate_ideas(
    research_brief: dict,
    count: int = 3,
    save_path: Optional[str] = None,
) -> List[dict]:
    """Return `count` distinct creative ideas for a short promotional video.

    Each idea is a dict:
        {
          "id": "idea-1" | "idea-2" | "idea-3",
          "title": str,
          "logline": str,        # 1-2 sentences
          "tone": str,           # 2-4 adjectives
          "hook_angle": str,     # how the video opens
          "visual_seed": str,    # 1-sentence style hint for scene writer
        }

    The three ideas are intentionally diverse: one safe, one bold, one unexpected.
    """
    prompt = f"""You are a creative director proposing three distinct directions for a short
promotional video. They must be genuinely DIFFERENT approaches, not rewordings.

RESEARCH BRIEF:
Topic: {research_brief['topic']}
Audience: {research_brief['audience']}
Tone: {research_brief['tone']}
Key points: {json.dumps(research_brief['key_points'])}
Call to action: {research_brief['call_to_action']}

Generate exactly {count} ideas with these archetypes:
- idea-1: the SAFE, on-brand concept that any marketer would approve
- idea-2: the BOLD / EMOTIONAL concept that takes a real creative risk
- idea-3: the UNEXPECTED / CLEVER concept (a surprising angle, metaphor, or POV)

For each, return:
  id: "idea-1" | "idea-2" | "idea-3"
  title: short, evocative (3-6 words)
  logline: 1-2 sentences capturing the whole video
  tone: 2-4 adjectives describing the feel
  hook_angle: how the opening scene hooks the viewer (1 sentence)
  visual_seed: a 1-sentence visual style hint for the scene-by-scene writer
    (e.g. "Use warm golden-hour photography, hand-held camera, intimate close-ups")

Constraints:
- Make each idea's title/logline/hook_angle visually distinct
- Each idea should be producible as a {research_brief.get('target_duration', 30)}s video
- Stay on-brand for the topic; do not invent products/features not in the brief

Return ONLY valid JSON (no markdown fences, no commentary):
{{"ideas": [...]}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL}:generateContent?key={API_KEY}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    resp = requests.post(url, json=body, timeout=120)
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()

    payload = json.loads(raw)
    ideas = payload.get("ideas", [])
    if len(ideas) != count:
        raise ValueError(f"Expected {count} ideas, got {len(ideas)}")

    # Force the id field to be stable, in case the model rewords it
    for i, idea in enumerate(ideas):
        idea["id"] = f"idea-{i + 1}"

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "w") as f:
            json.dump({"ideas": ideas}, f, indent=2)

    return ideas


if __name__ == "__main__":
    import sys
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
        "target_duration": 30,
    }
    if len(sys.argv) > 1:
        brief["topic"] = " ".join(sys.argv[1:])
    ideas = generate_ideas(brief)
    print(json.dumps({"ideas": ideas}, indent=2))
