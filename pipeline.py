"""pipeline.py - CLI entry point that runs the pipeline library.

Thin wrapper around pipeline_lib.run_pipeline. Supports:
  --idea-id idea-N  : auto-pick an idea (skips the interactive wait)
  --interactive     : pause to let the user pick from the 3 ideas
  (default)         : auto-pick idea-1 with no pause (deterministic)
"""
import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))

from scenes import ALLOWED_DURATIONS
from image_prompts import ALLOWED_STYLES
from pipeline_lib import (
    run_pipeline,
    PipelineCanceled,
    PipelineAwaitingIdea,
)


CACHE_DIR = ".cache"


def _cli_emit(stage: str, status: str, index: int, _output_path, error):
    icon = {"running": "⏳", "succeeded": "✅", "failed": "❌",
            "canceled": "🚫", "skipped": "⏭️"}.get(status, "·")
    msg = f"  {icon} [{stage}{f' #{index}' if index else ''}] {status}"
    if error:
        msg += f" — {error}"
    print(msg)


def _prompt_user_for_idea(ideas: list) -> dict:
    print("\n=== Pick a creative direction ===")
    for i, idea in enumerate(ideas, 1):
        print(f"\n[{i}] {idea['title']}")
        print(f"    {idea['logline']}")
        print(f"    tone: {idea['tone']}")
        print(f"    hook: {idea['hook_angle']}")
    while True:
        try:
            choice = input(f"\nChoose 1..{len(ideas)} (default 1): ").strip() or "1"
            idx = int(choice) - 1
            if 0 <= idx < len(ideas):
                return ideas[idx]
        except (ValueError, EOFError):
            pass
        print(f"  Please enter a number between 1 and {len(ideas)}.")


def _driver(prompt, duration, orientation, style, idea_id, interactive):
    """Run the pipeline, handling the optional 'await idea' pause."""
    cancel = threading.Event()
    chosen_idea = None

    while True:
        try:
            return run_pipeline(
                job_id="cli",
                prompt=prompt,
                duration=duration,
                orientation=orientation,
                style=style,
                cache_dir=CACHE_DIR,
                emit=_cli_emit,
                cancel_event=cancel,
                chosen_idea=chosen_idea,
            )
        except PipelineAwaitingIdea as e:
            # Pick an idea
            if idea_id:
                chosen_idea = next((i for i in e.ideas if i["id"] == idea_id), e.ideas[0])
                print(f"\n[CLI] Pre-selected idea: {chosen_idea['title']}")
            elif interactive:
                chosen_idea = _prompt_user_for_idea(e.ideas)
            else:
                # default = first
                chosen_idea = e.ideas[0]
                print(f"\n[CLI] Default idea: {chosen_idea['title']}")
            print(f"[CLI] Continuing with: {chosen_idea['title']}\n")
            # loop again — run_pipeline will skip the idea generation step


def main():
    parser = argparse.ArgumentParser(description="AI video production pipeline (CLI)")
    parser.add_argument("--prompt", "-p", required=True)
    parser.add_argument("--duration", "-d", type=int, required=True, choices=ALLOWED_DURATIONS)
    parser.add_argument("--orientation", "-o", default="16:9", choices=["16:9", "9:16"])
    parser.add_argument("--style", "-s", default="cinematic", choices=ALLOWED_STYLES)
    parser.add_argument(
        "--idea-id", default=None, choices=["idea-1", "idea-2", "idea-3"],
        help="Pre-pick a creative idea (default: auto-pick idea-1 with no pause).",
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Pause to let the user pick an idea from the 3 generated ideas.",
    )
    args = parser.parse_args()

    print(f"\n[CLI] Running pipeline: {args.duration}s, {args.orientation}, {args.style}")
    print(f"[CLI] Prompt: {args.prompt}\n")

    try:
        final = _driver(
            args.prompt, args.duration, args.orientation, args.style,
            args.idea_id, args.interactive,
        )
        print(f"\n[CLI] Done: {final}")
    except PipelineCanceled:
        print("\n[CLI] Pipeline canceled.")
        sys.exit(2)
    except Exception as e:
        print(f"\n[CLI] Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
