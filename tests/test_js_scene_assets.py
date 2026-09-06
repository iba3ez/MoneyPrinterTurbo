"""Phase 7 tests: scene asset priority resolution and local asset security."""

import uuid

import pytest

from app.services.js_content.assets import SceneAssetBinding, SceneAssetManifest
from app.services.js_content.image_clip_models import ImageClipPlan
from app.services.js_content.models import Scene, Storyboard
from app.services.js_content.render_pipeline import attach_resolved_scene_materials
from app.services.js_content.scene_assets import (
    PRIORITY_AI_MEDIA,
    PRIORITY_IMAGE_CLIP,
    PRIORITY_IMAGE_URL,
    PRIORITY_LOCAL_VIDEO,
    PRIORITY_STOCK_MEDIA,
    PRIORITY_VISUAL_PROMPT,
    resolve_scene_assets,
)
from app.services.js_content.image_clip import resolve_local_image_asset
from app.models.schema import VideoParams
from app.utils import utils


def _storyboard() -> Storyboard:
    return Storyboard.from_scenes(
        title="Demo",
        hook="Hook",
        scenes=(
            Scene(index=1, duration_seconds=4, narration="a", visual_prompt="prompt a"),
            Scene(index=2, duration_seconds=4, narration="b", visual_prompt="prompt b"),
            Scene(index=3, duration_seconds=4, narration="c", visual_prompt="prompt c"),
            Scene(index=4, duration_seconds=4, narration="d", visual_prompt="prompt d"),
            Scene(index=5, duration_seconds=4, narration="e", visual_prompt="prompt e"),
            Scene(index=6, duration_seconds=4, narration="f", visual_prompt="prompt f"),
        ),
    )


def test_scene_asset_priority():
    storyboard = _storyboard()
    manifest = SceneAssetManifest(
        bindings=(
            SceneAssetBinding(
                scene_index=2,
                asset_type="image",
                asset_uri="https://example.com/product.jpg",
                source="product",
                role="product-detail",
            ),
        )
    )
    rendered_clips = (
        ImageClipPlan(
            scene_index=3,
            source_image="a.png",
            duration_seconds=4,
            output_path="js-image-clips/rendered.mp4",
        ),
        # A plan without output_path is not yet usable and must not win.
        ImageClipPlan(
            scene_index=4,
            source_image="b.png",
            duration_seconds=4,
            output_path="",
        ),
    )
    resolution = resolve_scene_assets(
        storyboard,
        asset_manifest=manifest,
        image_clips=rendered_clips,
        local_video_materials=("clip-one.mp4",),
        ai_media={5: "ai://scene-5"},
        stock_media={6: "stock://beach"},
    )

    by_scene = {asset.scene_index: asset for asset in resolution.assets}
    # 1. explicit local uploaded video wins first.
    assert by_scene[1].priority == PRIORITY_LOCAL_VIDEO
    assert by_scene[1].asset_uri == "clip-one.mp4"
    # 2. rendered image clip beats the image URL binding.
    assert by_scene[3].priority == PRIORITY_IMAGE_CLIP
    assert by_scene[3].asset_uri == "js-image-clips/rendered.mp4"
    # 3. product image URL is used when no clip/local video exists.
    assert by_scene[2].priority == PRIORITY_IMAGE_URL
    assert by_scene[2].asset_uri == "https://example.com/product.jpg"
    # 4. AI media, 5. stock media, 6. visual prompt fallback.
    assert by_scene[5].priority == PRIORITY_AI_MEDIA
    assert by_scene[6].priority == PRIORITY_STOCK_MEDIA
    assert by_scene[4].priority == PRIORITY_VISUAL_PROMPT
    assert by_scene[4].asset_uri == "prompt d"

    # The local pipeline is only chosen when every scene carries local media.
    assert resolution.all_scenes_local is False
    assert resolution.local_material_uris == (
        "clip-one.mp4",
        "js-image-clips/rendered.mp4",
    )


def test_invalid_local_filename_rejected(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(
        utils,
        "storage_dir",
        lambda sub_dir="", create=False: str(
            (storage_root / sub_dir) if sub_dir else storage_root
        ),
    )
    for filename in (
        "",
        "photo.gif",
        "photo.svg",
        "internal/.material-upload-x.png",
        "clip.mp4",  # videos are not product images
    ):
        with pytest.raises(ValueError):
            resolve_local_image_asset(filename)


def test_path_traversal_rejected(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    local_videos = storage_root / "local_videos"
    local_videos.mkdir(parents=True)
    monkeypatch.setattr(
        utils,
        "storage_dir",
        lambda sub_dir="", create=False: str(
            (storage_root / sub_dir) if sub_dir else storage_root
        ),
    )
    (local_videos / "safe.png").write_bytes(b"not-a-real-image")

    escapes = (
        # Traversal segments are neutralized to a basename by the shared
        # sanitizer, so "../safe.png" cannot escape: it would simply resolve
        # to local_videos/safe.png. Real escapes below must all be rejected.
        "..\\..\\secret.png",
        "js-image-clips/../../secrets.png",
        "C:\\Windows\\system32\\config.png",
        "/etc/passwd",
        str(local_videos.parent / "outside.png"),
    )
    for candidate in escapes:
        with pytest.raises(ValueError):
            resolve_local_image_asset(candidate)

    # Traversal segments are neutralized to the basename and stay inside the
    # whitelist directory — never at the requested relative location.
    neutralized = resolve_local_image_asset("../safe.png")
    assert neutralized.startswith(str(local_videos))

    # A symlink escape is also rejected by the shared resolver.
    link = local_videos / f"link-{uuid.uuid4().hex}.png"
    try:
        link.symlink_to(storage_root / "outside-scope.png")
        with pytest.raises(ValueError):
            resolve_local_image_asset(link.name)
    except (OSError, NotImplementedError):
        # Windows may deny symlink creation without privileges.
        pass


def _three_scene_storyboard() -> Storyboard:
    return Storyboard.from_scenes(
        title="Order",
        hook="Hook",
        scenes=(
            Scene(index=1, duration_seconds=4, narration="a", visual_prompt="prompt a"),
            Scene(index=2, duration_seconds=5, narration="b", visual_prompt="prompt b"),
            Scene(index=3, duration_seconds=4, narration="c", visual_prompt="prompt c"),
        ),
    )


def _rendered_clip(scene_index: int, duration: float = 4.0) -> ImageClipPlan:
    return ImageClipPlan(
        scene_index=scene_index,
        source_image="a.png",
        duration_seconds=duration,
        output_path=f"js-image-clips/clip-{scene_index}.mp4",
    )


def test_renderer_material_order_matches_scene_resolution():
    storyboard = _three_scene_storyboard()
    resolution = resolve_scene_assets(
        storyboard,
        image_clips=(_rendered_clip(2), _rendered_clip(3)),
        local_video_materials=("uploaded-video.mp4",),
    )
    params = attach_resolved_scene_materials(
        VideoParams(video_subject="t"),
        resolution,
        max_scene_duration_seconds=5.0,
    )

    # Payload order must follow scene_index: scene 1 local video, then clips.
    urls = [material.url.replace("\\", "/") for material in params.video_materials]
    assert urls == [
        "uploaded-video.mp4",
        "js-image-clips/clip-2.mp4",
        "js-image-clips/clip-3.mp4",
    ]
    scenes = [material.source_info["scene"] for material in params.video_materials]
    assert scenes == [1, 2, 3]
    assert params.video_source == "local"
    assert params.match_materials_to_script is True
    assert params.video_clip_duration == 5
    assert resolution.to_dict()["local_timeline_supported"] is True


def test_local_video_overrides_image_clip_for_same_scene():
    storyboard = _three_scene_storyboard()
    clips = (_rendered_clip(1), _rendered_clip(2), _rendered_clip(3))
    resolution = resolve_scene_assets(
        storyboard,
        image_clips=clips,
        # Local videos occupy the first scene slots, overriding the clips.
        local_video_materials=("video-a.mp4",),
    )
    by_scene = {asset.scene_index: asset for asset in resolution.assets}
    assert by_scene[1].priority == PRIORITY_LOCAL_VIDEO
    assert by_scene[1].asset_uri == "video-a.mp4"
    assert by_scene[2].priority == PRIORITY_IMAGE_CLIP

    params = attach_resolved_scene_materials(VideoParams(video_subject="t"), resolution)
    urls = [material.url.replace("\\", "/") for material in params.video_materials]
    assert urls == [
        "video-a.mp4",
        "js-image-clips/clip-2.mp4",
        "js-image-clips/clip-3.mp4",
    ]


def test_mixed_local_stock_does_not_drop_scenes():
    storyboard = _three_scene_storyboard()
    resolution = resolve_scene_assets(
        storyboard,
        # Only scene 1 carries local media; scenes 2-3 fall to visual prompts.
        local_video_materials=("only-video.mp4",),
    )
    assert resolution.all_scenes_local is False
    notes = resolution.planning_notes()
    assert notes and "mixed-local" in notes[0]
    assert resolution.to_dict()["local_timeline_supported"] is False

    params_before = VideoParams(video_subject="t", video_source="pexels")
    params_after = attach_resolved_scene_materials(params_before, resolution)

    # No partial local timeline: params untouched, every scene stays covered
    # by the existing stock workflow instead of silently dropping scenes.
    assert params_after.video_source == "pexels"
    assert params_after.video_materials is None
    assert params_after.model_dump() == params_before.model_dump()
    assert len(resolution.assets) == len(storyboard.scenes)


def test_all_local_scenes_switch_video_source_to_local():
    storyboard = _three_scene_storyboard()
    resolution = resolve_scene_assets(
        storyboard,
        image_clips=(_rendered_clip(1, 4.0), _rendered_clip(2, 5.0), _rendered_clip(3, 4.0)),
    )
    assert resolution.all_scenes_local is True

    params_before = VideoParams(video_subject="t", video_source="pexels")
    params_after = attach_resolved_scene_materials(
        params_before,
        resolution,
        max_scene_duration_seconds=5.0,
    )
    assert params_before.video_source == "pexels"
    assert params_after.video_source == "local"
    assert len(params_after.video_materials) == 3
    assert params_after.video_clip_duration == 5
