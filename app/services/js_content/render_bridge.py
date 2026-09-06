from __future__ import annotations

from app.models.schema import VideoAspect, VideoParams

from .models import Storyboard


_ASPECT_MAP = {
    "9:16": VideoAspect.portrait,
    "16:9": VideoAspect.landscape,
    "1:1": VideoAspect.square,
}


def storyboard_to_video_params(
    storyboard: Storyboard,
    *,
    subject: str | None = None,
    aspect_ratio: str = "9:16",
    video_source: str = "pexels",
    voice_name: str = "",
    bgm_type: str = "random",
) -> VideoParams:
    """Translate a validated JS storyboard into MoneyPrinterTurbo VideoParams.

    This bridge deliberately stays conservative: narration becomes the existing
    script contract, visual prompts become search terms, and rendering remains in
    the upstream task pipeline. Scene-accurate material binding can be layered on
    later without replacing the renderer.
    """

    storyboard.validate()
    if aspect_ratio not in _ASPECT_MAP:
        raise ValueError(f"unsupported aspect ratio: {aspect_ratio}")

    narration_parts = [scene.narration.strip() for scene in storyboard.scenes if scene.narration.strip()]
    script = "\n\n".join(narration_parts)
    terms = [scene.visual_prompt.strip() for scene in storyboard.scenes if scene.visual_prompt.strip()]

    params = VideoParams(
        video_subject=subject or storyboard.title,
        video_script=script,
        video_terms=terms or None,
        video_aspect=_ASPECT_MAP[aspect_ratio],
        video_source=video_source,
        voice_name=voice_name,
        bgm_type=bgm_type,
        match_materials_to_script=True,
        paragraph_number=max(1, min(10, len(storyboard.scenes))),
    )
    return params
