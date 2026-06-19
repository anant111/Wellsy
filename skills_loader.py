"""skills_loader.py - Load OpenClaw-style .skill SKILL.md files as plain text.

These "skill" files are markdown knowledge documents (not executable code).
We inject their contents into Gemini system prompts to teach the model the
conventions, tables, and rules of a particular skill.
"""
import os
from functools import lru_cache

# skills/ lives next to the pipeline package
SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


@lru_cache(maxsize=8)
def load_skill(name: str) -> str:
    """Return the contents of skills/<name>/SKILL.md as a string.

    Raises FileNotFoundError if the skill is not installed.
    """
    path = os.path.join(SKILLS_DIR, name, "SKILL.md")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Skill '{name}' not found. Expected: {path}\n"
            f"Available skills: {list_skills()}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def list_skills() -> list[str]:
    """List all installed skills (names = subdirectories of skills/)."""
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(
        d for d in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, d))
    )


if __name__ == "__main__":
    print("Installed skills:", list_skills())
    for s in list_skills():
        body = load_skill(s)
        print(f"\n--- {s} ({len(body)} chars) ---")
        print(body[:200])
