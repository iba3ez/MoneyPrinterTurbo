"""Image-to-Clip render pipeline for the JS Content Engine.

Turns a validated storyboard plus uploaded product images into per-scene
FFmpeg-rendered clips and feeds them into the existing MoneyPrinterTurbo
renderer through its local-material path. Upstream service files stay
untouched: the bridge only produces ``VideoParams`` with
``video_source="local"`` and ordered ``video_materials``.
"""

from __future__ import annotations

from loguru import logger

from app.models.schema import MaterialInfo, VideoParams

from .assets import SceneAssetManifest
from .brands import get_brand_profile
from .image_clip import (
    MAX_IMAGE_CLIPS_PER_REQUEST,
    ImageClipRenderError,
    render_image_clip,
    resolve_clip_storage_key,
    resolve_local_image_asset,
)
from .image_clip_models import (
    DURATION_TOLERANCE_SECONDS,
    MOTION_PAN_LEFT,
    MOTION_PAN_RIGHT,
    MOTION_PAN_UP,
    MOTION_STATIC,
    MOTION_ZOOM_IN,
    MOTION_ZOOM_OUT,
    ImageClipManifest,
    ImageClipPlan,
    ImageClipSettings,
)
from .models import Storyboard
from .scene_assets import SceneAssetResolution, resolve_scene_assets

# Deterministic motion rotation: the hook moves hardest, the CTA settles.
DEFAULT_MOTION_SEQUENCE: tuple[str, ...] = (
    MOTION_ZOOM_IN,
    MOTION_PAN_RIGHT,
    MOTION_ZOOM_OUT,
    MOTION_PAN_LEFT,
    MOTION_PAN_UP,
    MOTION_STATIC,
)


class ImageClipPipelineError(RuntimeError):
    """The image-to-clip pipeline could not produce scene clips."""


def build_image_clip_plans(
    storyboard: Storyboard,
    *,
    image_paths: tuple[str, ...],
    price_text: str = "",
    badge_text: str = "",
    settings: ImageClipSettings | None = None,
    motion_sequence: tuple[str, ...] = DEFAULT_MOTION_SEQUENCE,
) -> tuple[ImageClipPlan, ...]:
    """Assign uploaded product images to scenes and build validated clip plans.

    Image distribution mirrors the product asset binding: the first image is
    reserved for the hook scene, remaining images rotate across middle scenes,
    and the final scene reuses the primary image for CTA recall.
    """

    if not image_paths:
        return ()
    storyboard.validate()
    settings = settings or ImageClipSettings.for_aspect_ratio()
    images = tuple(path for path in image_paths if path)

    plans: list[ImageClipPlan] = []
    scene_indexes = [scene.index for scene in storyboard.scenes]
    last_position = len(scene_indexes) - 1
    for position, scene in enumerate(storyboard.scenes):
        image = images[position % len(images)]
        if position == 0:
            image = images[0]
        elif position == last_position and last_position > 0:
            image = images[0]

        motion = motion_sequence[position % len(motion_sequence)]
        zoom_start, zoom_end = 1.0, 1.3
        if motion == MOTION_ZOOM_OUT:
            zoom_start, zoom_end = 1.3, 1.0

        is_last = position == last_position
        plans.append(
            ImageClipPlan(
                scene_index=scene.index,
                source_image=image,
                duration_seconds=float(scene.duration_seconds),
                motion=motion,
                zoom_start=zoom_start,
                zoom_end=zoom_end,
                overlay_text=scene.on_screen_text.strip(),
                price_text="" if is_last else price_text.strip(),
                badge_text=badge_text.strip() if position == 0 else "",
                transition=scene.transition.strip() or "cut",
            )
        )
    return tuple(plans)


def render_storyboard_clips(
    plans: tuple[ImageClipPlan, ...],
    settings: ImageClipSettings,
    *,
    brand_key: str = "jstech",
    enable_overlay: bool = True,
    timeout_seconds: int = 120,
) -> tuple[ImageClipPlan, ...]:
    """Render every plan through FFmpeg and return plans with output paths."""

    if not plans:
        return ()
    if len(plans) > MAX_IMAGE_CLIPS_PER_REQUEST:
        raise ImageClipPipelineError(
            f"too many image clips requested ({len(plans)}); "
            f"maximum is {MAX_IMAGE_CLIPS_PER_REQUEST}"
        )

    brand = get_brand_profile(brand_key)
    rendered: list[ImageClipPlan] = []
    for plan in plans:
        try:
            rendered.append(
                render_image_clip(
                    plan,
                    settings,
                    timeout_seconds=timeout_seconds,
                    enable_overlay=enable_overlay,
                    brand_watermark=brand.watermark,
                )
            )
        except ImageClipRenderError:
            for finished in rendered:
                _discard_rendered_clip(finished.output_path)
            raise
    return tuple(rendered)


def _discard_rendered_clip(output_path: str) -> None:
    import os

    if output_path and os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            logger.warning(f"failed to clean up clip: {output_path}")


def build_image_clip_manifest(
    plans: tuple[ImageClipPlan, ...],
    settings: ImageClipSettings,
) -> ImageClipManifest:
    manifest = ImageClipManifest(
        aspect_ratio=settings.aspect_ratio,
        width=settings.width,
        height=settings.height,
        fps=settings.fps,
        duration_tolerance_seconds=DURATION_TOLERANCE_SECONDS,
        clips=tuple(plans),
    )
    manifest.validate()
    return manifest


def resolve_scene_assets_for_pipeline(
    storyboard: Storyboard,
    *,
    asset_manifest: SceneAssetManifest | None = None,
    plans: tuple[ImageClipPlan, ...] = (),
    local_video_materials: tuple[str, ...] = (),
) -> SceneAssetResolution:
    """Resolve per-scene assets; unrendered clips count as planned assets."""

    rendered = tuple(clip for clip in plans if clip.output_path)
    resolution = resolve_scene_assets(
        storyboard,
        asset_manifest=asset_manifest,
        image_clips=rendered,
        local_video_materials=local_video_materials,
    )
    if len(rendered) != len(plans):
        # Plan stage: report planned clips per scene without faking URIs.
        rendered_scenes = {clip.scene_index for clip in rendered}
        planned_only = tuple(
            clip for clip in plans if clip.scene_index not in rendered_scenes
        )
        resolution = _annotate_planned_clips(resolution, planned_only)
    return resolution


def _annotate_planned_clips(
    resolution: SceneAssetResolution,
    planned_clips: tuple[ImageClipPlan, ...],
) -> SceneAssetResolution:
    from .scene_assets import (
        PRIORITY_IMAGE_CLIP,
        _PRIORITY_LABELS,
        ResolvedSceneAsset,
    )

    planned_by_scene = {clip.scene_index: clip for clip in planned_clips}
    assets = [
        (
            ResolvedSceneAsset(
                scene_index=asset.scene_index,
                priority=PRIORITY_IMAGE_CLIP,
                priority_label=_PRIORITY_LABELS[PRIORITY_IMAGE_CLIP],
                asset_type="clip-planned",
                asset_uri="",
                source="image-to-clip",
                role=f"planned-{planned_by_scene[asset.scene_index].motion}",
            )
            if asset.scene_index in planned_by_scene
            and asset.priority > PRIORITY_IMAGE_CLIP
            else asset
        )
        for asset in resolution.assets
    ]
    return SceneAssetResolution(assets=tuple(assets))


def attach_clip_materials(
    params: VideoParams,
    plans: tuple[ImageClipPlan, ...],
    local_video_materials: tuple[str, ...] = (),
) -> VideoParams:
    """Switch params onto the local-material renderer path with scene order.

    Only scene clips that have actually been rendered can enter the timeline.
    Storage keys (never absolute server paths) are written into
    ``video_materials``; the upstream renderer re-resolves them inside the
    ``storage/local_videos`` whitelist directory.
    """

    rendered = [clip for clip in plans if clip.output_path]
    ordered_clips = sorted(rendered, key=lambda clip: clip.scene_index)
    materials = [
        MaterialInfo(
            provider="local",
            url=resolve_clip_storage_key(clip.output_path),
            duration=0,
            source_info={"provider": "image-to-clip", "scene": clip.scene_index},
        )
        for clip in ordered_clips
    ]
    materials.extend(
        MaterialInfo(provider="local", url=str(uri), duration=0)
        for uri in local_video_materials
        if str(uri or "").strip()
    )
    if not materials:
        return params

    max_scene_duration = max(
        (clip.duration_seconds for clip in rendered),
        default=params.video_clip_duration,
    )
    data = params.model_dump()
    data.update(
        {
            "video_source": "local",
            "video_materials": materials,
            "match_materials_to_script": True,
            # Each scene clip must play to its storyboard duration, so the
            # renderer's per-clip cap is raised to the longest scene.
            "video_clip_duration": max(
                1, int(round(max_scene_duration))
            ),
        }
    )
    return VideoParams(**data)


def prepare_image_clip_assets(
    storyboard: Storyboard,
    *,
    local_image_files: tuple[str, ...],
    asset_manifest: SceneAssetManifest | None = None,
    local_video_materials: tuple[str, ...] = (),
    price_text: str = "",
    badge_text: str = "",
    brand_key: str = "jstech",
    settings: ImageClipSettings | None = None,
    enable_overlay: bool = True,
    render: bool = False,
    timeout_seconds: int = 120,
) -> tuple[ImageClipManifest, SceneAssetResolution, tuple[ImageClipPlan, ...]]:
    """Plan (and optionally render) scene clips for a product video.

    ``render=False`` only validates and plans (used by the plan endpoint);
    ``render=True`` runs FFmpeg and fills output paths (generate endpoint).
    """

    settings = settings or ImageClipSettings.for_aspect_ratio()
    image_paths = tuple(
        resolve_local_image_asset(filename) for filename in local_image_files
    )
    plans = build_image_clip_plans(
        storyboard,
        image_paths=image_paths,
        price_text=price_text,
        badge_text=badge_text,
        settings=settings,
    )
    if render and plans:
        plans = render_storyboard_clips(
            plans,
            settings,
            brand_key=brand_key,
            enable_overlay=enable_overlay,
            timeout_seconds=timeout_seconds,
        )
    manifest = build_image_clip_manifest(plans, settings)
    resolution = resolve_scene_assets_for_pipeline(
        storyboard,
        asset_manifest=asset_manifest,
        plans=plans,
        local_video_materials=local_video_materials,
    )
    return manifest, resolution, plans
