"""Scene asset priority resolver for the JS Content Engine.

Chooses, per storyboard scene, the best available asset following the fixed
priority chain:

1. explicit local uploaded video
2. product image converted to a clip (Image-to-Clip engine output)
3. product image URL
4. AI-generated media
5. stock media
6. visual prompt fallback

The resolver is pure: it never touches the filesystem and never calls the
upstream stock material search. Scenes that resolve to URL/AI/stock/prompt
assets keep the existing MoneyPrinterTurbo workflow — the render pipeline only
switches to the local-material renderer when every scene carries a local asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .assets import SceneAssetManifest
from .image_clip_models import ImageClipPlan
from .models import Storyboard

PRIORITY_LOCAL_VIDEO = 1
PRIORITY_IMAGE_CLIP = 2
PRIORITY_IMAGE_URL = 3
PRIORITY_AI_MEDIA = 4
PRIORITY_STOCK_MEDIA = 5
PRIORITY_VISUAL_PROMPT = 6

_PRIORITY_LABELS: dict[int, str] = {
    PRIORITY_LOCAL_VIDEO: "local-uploaded-video",
    PRIORITY_IMAGE_CLIP: "product-image-clip",
    PRIORITY_IMAGE_URL: "product-image-url",
    PRIORITY_AI_MEDIA: "ai-generated-media",
    PRIORITY_STOCK_MEDIA: "stock-media",
    PRIORITY_VISUAL_PROMPT: "visual-prompt-fallback",
}


@dataclass(frozen=True, slots=True)
class ResolvedSceneAsset:
    scene_index: int
    priority: int
    priority_label: str
    asset_type: str
    asset_uri: str
    source: str
    role: str

    @property
    def is_local_media(self) -> bool:
        """True when the asset can be fed to the local-material renderer."""

        return self.priority in {PRIORITY_LOCAL_VIDEO, PRIORITY_IMAGE_CLIP}

    def to_dict(self) -> dict:
        return {
            "scene_index": self.scene_index,
            "priority": self.priority,
            "priority_label": self.priority_label,
            "asset_type": self.asset_type,
            "asset_uri": self.asset_uri,
            "source": self.source,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class SceneAssetResolution:
    assets: tuple[ResolvedSceneAsset, ...]

    @property
    def all_scenes_local(self) -> bool:
        return bool(self.assets) and all(asset.is_local_media for asset in self.assets)

    @property
    def local_material_uris(self) -> tuple[str, ...]:
        """Local storage keys ordered by scene, ready for video_materials."""

        ordered = sorted(self.assets, key=lambda asset: asset.scene_index)
        return tuple(
            asset.asset_uri for asset in ordered if asset.is_local_media and asset.asset_uri
        )

    def to_dict(self) -> dict:
        return {
            "assets": [asset.to_dict() for asset in self.assets],
            "all_scenes_local": self.all_scenes_local,
            "local_timeline_supported": self.all_scenes_local,
            "planning_notes": self.planning_notes(),
        }

    def planning_notes(self) -> tuple[str, ...]:
        """Explicit planner metadata for mixed local/stock timelines.

        The upstream renderer consumes either a full local timeline or the
        stock workflow — it has no per-scene mixed mode. When only some scenes
        resolve to local media, the local assets must NOT be assembled into a
        partial timeline (that would silently drop the remaining scenes); the
        whole task falls back to the stock workflow instead.
        """

        if not self.assets or self.all_scenes_local:
            return ()
        local_count = sum(1 for asset in self.assets if asset.is_local_media)
        if not local_count:
            return ()
        return (
            (
                "mixed-local timeline is not supported yet: "
                f"{local_count} of {len(self.assets)} scenes resolved to local "
                "media, remaining scenes fall back to the stock workflow"
            ),
        )


def resolve_scene_assets(
    storyboard: Storyboard,
    *,
    asset_manifest: SceneAssetManifest | None = None,
    image_clips: tuple[ImageClipPlan, ...] | tuple = (),
    local_video_materials: tuple[str, ...] | tuple = (),
    ai_media: Mapping[int, str] | None = None,
    stock_media: Mapping[int, str] | None = None,
) -> SceneAssetResolution:
    """Resolve the best asset for every scene according to the priority chain.

    ``image_clips`` maps scenes to Image-to-Clip plans; clips without a rendered
    ``output_path`` are skipped because they cannot enter the renderer yet.
    ``local_video_materials`` are storage keys of previously uploaded videos and
    are distributed over scenes in order. ``ai_media`` / ``stock_media`` map
    scene indexes to URIs for future engines.
    """

    storyboard.validate()
    local_videos = tuple(
        str(uri).strip() for uri in local_video_materials if str(uri or "").strip()
    )
    clip_by_scene = {
        clip.scene_index: clip
        for clip in image_clips
        if getattr(clip, "output_path", "")
    }
    binding_by_scene = {}
    if asset_manifest is not None:
        for binding in asset_manifest.bindings:
            binding_by_scene.setdefault(binding.scene_index, binding)

    assets: list[ResolvedSceneAsset] = []
    local_video_cursor = 0
    for scene in storyboard.scenes:
        resolved: ResolvedSceneAsset | None = None

        if local_video_cursor < len(local_videos):
            resolved = ResolvedSceneAsset(
                scene_index=scene.index,
                priority=PRIORITY_LOCAL_VIDEO,
                priority_label=_PRIORITY_LABELS[PRIORITY_LOCAL_VIDEO],
                asset_type="video",
                asset_uri=local_videos[local_video_cursor],
                source="local-upload",
                role="explicit-local-video",
            )
            local_video_cursor += 1

        if resolved is None and scene.index in clip_by_scene:
            clip = clip_by_scene[scene.index]
            resolved = ResolvedSceneAsset(
                scene_index=scene.index,
                priority=PRIORITY_IMAGE_CLIP,
                priority_label=_PRIORITY_LABELS[PRIORITY_IMAGE_CLIP],
                asset_type="video",
                asset_uri=clip.output_path,
                source="image-to-clip",
                role=f"product-image-{clip.motion}",
            )

        if resolved is None and scene.index in binding_by_scene:
            binding = binding_by_scene[scene.index]
            resolved = ResolvedSceneAsset(
                scene_index=scene.index,
                priority=PRIORITY_IMAGE_URL,
                priority_label=_PRIORITY_LABELS[PRIORITY_IMAGE_URL],
                asset_type="image",
                asset_uri=binding.asset_uri,
                source=binding.source,
                role=binding.role,
            )

        if resolved is None and ai_media and scene.index in ai_media:
            resolved = ResolvedSceneAsset(
                scene_index=scene.index,
                priority=PRIORITY_AI_MEDIA,
                priority_label=_PRIORITY_LABELS[PRIORITY_AI_MEDIA],
                asset_type="media",
                asset_uri=str(ai_media[scene.index]),
                source="ai-generated",
                role="ai-scene-media",
            )

        if resolved is None and stock_media and scene.index in stock_media:
            resolved = ResolvedSceneAsset(
                scene_index=scene.index,
                priority=PRIORITY_STOCK_MEDIA,
                priority_label=_PRIORITY_LABELS[PRIORITY_STOCK_MEDIA],
                asset_type="media",
                asset_uri=str(stock_media[scene.index]),
                source="stock",
                role="stock-scene-media",
            )

        if resolved is None:
            resolved = ResolvedSceneAsset(
                scene_index=scene.index,
                priority=PRIORITY_VISUAL_PROMPT,
                priority_label=_PRIORITY_LABELS[PRIORITY_VISUAL_PROMPT],
                asset_type="visual_prompt",
                asset_uri=scene.visual_prompt.strip(),
                source="storyboard",
                role="visual-prompt-fallback",
            )

        assets.append(resolved)

    return SceneAssetResolution(assets=tuple(assets))


def summarize_resolution(resolution: SceneAssetResolution) -> dict[int, str]:
    """Compact scene -> priority label map for manifests and logs."""

    return {
        asset.scene_index: asset.priority_label for asset in resolution.assets
    }
