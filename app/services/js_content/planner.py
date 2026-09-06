from __future__ import annotations

from app.services import llm

from .brands import get_brand_profile
from .models import ContentBrief, Storyboard
from .parser import parse_storyboard_json
from .prompts_th import build_thai_storyboard_prompt
from .storyboard import build_storyboard_scaffold


class StoryboardPlanningError(RuntimeError):
    pass


def generate_ai_storyboard(
    brief: ContentBrief,
    *,
    app_config=None,
    fallback_to_scaffold: bool = True,
) -> Storyboard:
    """Generate a structured storyboard through the existing MoneyPrinterTurbo LLM layer.

    The adapter intentionally reuses ``app.services.llm._generate_response`` so all
    configured providers, credentials, gateways and compatibility logic stay in one place.
    If the provider returns malformed JSON, callers can choose a deterministic scaffold
    fallback rather than failing the entire video task.
    """

    brief.validate()
    brand = get_brand_profile(brief.brand_key)
    prompt = build_thai_storyboard_prompt(brief, brand)

    try:
        raw = llm._generate_response(prompt, app_config=app_config)
        storyboard = parse_storyboard_json(raw)
        metadata = dict(storyboard.metadata)
        metadata.update(
            {
                "planner": "js-ai-content-brain-v2",
                "brand": brand.key,
                "platform": brief.platform,
                "aspect_ratio": brief.aspect_ratio,
            }
        )
        enriched = Storyboard(
            title=storyboard.title,
            hook=storyboard.hook,
            scenes=storyboard.scenes,
            cta=storyboard.cta or brand.cta,
            metadata=metadata,
        )
        enriched.validate()
        return enriched
    except Exception as exc:
        if fallback_to_scaffold:
            fallback = build_storyboard_scaffold(brief)
            metadata = dict(fallback.metadata)
            metadata["planner_error"] = type(exc).__name__
            return Storyboard(
                title=fallback.title,
                hook=fallback.hook,
                scenes=fallback.scenes,
                cta=fallback.cta,
                metadata=metadata,
            )
        raise StoryboardPlanningError(str(exc)) from exc
