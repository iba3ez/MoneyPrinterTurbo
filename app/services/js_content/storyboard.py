from __future__ import annotations

from math import ceil

from .brands import get_brand_profile
from .models import ContentBrief, Scene, Storyboard


def build_storyboard_scaffold(brief: ContentBrief) -> Storyboard:
    """Create a deterministic storyboard skeleton before LLM enrichment.

    This is intentionally provider-agnostic. A later AI planner can replace or
    enrich narration/visual prompts while preserving a validated scene model.
    """

    brief.validate()
    brand = get_brand_profile(brief.brand_key)

    scene_count = max(3, min(8, ceil(brief.duration_seconds / 5)))
    base_duration = brief.duration_seconds / scene_count

    scenes: list[Scene] = []
    for index in range(1, scene_count + 1):
        if index == 1:
            narration = f"Hook: {brief.topic}"
            on_screen_text = brief.topic
        elif index == scene_count:
            narration = brand.cta or f"สรุป: {brief.topic}"
            on_screen_text = brand.cta
        else:
            narration = f"Key point {index - 1}: {brief.topic}"
            on_screen_text = f"ประเด็น {index - 1}"

        visual_prompt = (
            f"Brand={brand.name}; platform={brief.platform}; "
            f"aspect_ratio={brief.aspect_ratio}; topic={brief.topic}; "
            f"scene={index}/{scene_count}; mobile-first composition"
        )
        scenes.append(
            Scene(
                index=index,
                duration_seconds=round(base_duration, 3),
                narration=narration,
                on_screen_text=on_screen_text,
                visual_prompt=visual_prompt,
                camera="dynamic social-video framing",
                transition="cut" if index == 1 else "match-cut",
            )
        )

    storyboard = Storyboard.from_scenes(
        title=brief.topic,
        hook=f"{brief.topic} — {brief.objective}",
        scenes=scenes,
        cta=brand.cta,
        metadata={
            "brand": brand.key,
            "platform": brief.platform,
            "aspect_ratio": brief.aspect_ratio,
            "objective": brief.objective,
            "planner": "js-content-scaffold-v1",
        },
    )
    return storyboard
