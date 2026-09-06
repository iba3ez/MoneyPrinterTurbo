"""Phase 7 tests: Image-to-Clip plan validation, durations, and motion modes."""

import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.services.js_content.image_clip import (
    build_image_clip_command,
    build_zoompan_filter,
    probe_clip_duration,
    render_image_clip,
    resolve_local_image_asset,
)
from app.services.js_content.image_clip_models import (
    DURATION_TOLERANCE_SECONDS,
    ImageClipManifest,
    ImageClipPlan,
    ImageClipSettings,
    MOTION_MODES,
)
from app.services.js_content.models import Scene, Storyboard
from app.services.js_content.render_pipeline import (
    attach_clip_materials,
    build_image_clip_manifest,
    build_image_clip_plans,
    prepare_image_clip_assets,
)
from app.models.schema import VideoParams
from app.utils import utils

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None or bool(
    os.environ.get("IMAGEIO_FFMPEG_EXE")
)

_ROOT = Path(utils.root_dir())
_RESOURCES = _ROOT / "test" / "resources"


def _make_settings(**kwargs) -> ImageClipSettings:
    return ImageClipSettings.for_aspect_ratio("9:16", fps=24)


def _sample_storyboard() -> Storyboard:
    return Storyboard.from_scenes(
        title="RTX 5060",
        hook="Hook",
        scenes=(
            Scene(index=1, duration_seconds=5, narration="hook", on_screen_text="RTX 5060"),
            Scene(index=2, duration_seconds=4, narration="point", on_screen_text="สเปกเด่น"),
            Scene(index=3, duration_seconds=3, narration="cta", on_screen_text="ทักแชท"),
        ),
    )


def test_image_clip_plan_validation():
    storyboard = _sample_storyboard()
    with pytest.raises(ValueError):
        ImageClipPlan(
            scene_index=1,
            source_image="a.png",
            duration_seconds=0.2,
        ).validate()
    with pytest.raises(ValueError):
        ImageClipPlan(
            scene_index=1, source_image="a.png", duration_seconds=5, motion="fly-away"
        ).validate()
    with pytest.raises(ValueError):
        ImageClipPlan(
            scene_index=1,
            source_image="a.png",
            duration_seconds=5,
            zoom_start=0.5,
        ).validate()
    with pytest.raises(ValueError):
        ImageClipPlan(
            scene_index=0, source_image="a.png", duration_seconds=5
        ).validate()
    # ken-burns requires an increasing zoom range.
    with pytest.raises(ValueError):
        ImageClipPlan(
            scene_index=1,
            source_image="a.png",
            duration_seconds=5,
            motion="ken-burns",
            zoom_start=1.3,
            zoom_end=1.0,
        ).validate()
    # Valid plans accept every supported motion.
    for motion in MOTION_MODES:
        if motion == "zoom-out":
            continue
        ImageClipPlan(
            scene_index=1,
            source_image="a.png",
            duration_seconds=5,
            motion=motion,
        ).validate()
    _ = storyboard


def test_image_clip_duration():
    storyboard = _sample_storyboard()
    plans = build_image_clip_plans(
        storyboard,
        image_paths=("a.png", "b.png"),
        settings=_make_settings(),
    )
    assert [plan.duration_seconds for plan in plans] == [5.0, 4.0, 3.0]

    manifest = build_image_clip_manifest(plans, _make_settings())
    assert isinstance(manifest, ImageClipManifest)
    assert manifest.total_duration_seconds == pytest.approx(12.0)
    assert manifest.duration_tolerance_seconds == DURATION_TOLERANCE_SECONDS
    # Public manifest must never leak server paths.
    public = manifest.to_dict()
    for clip in public["clips"]:
        assert not str(clip["source_image"]).startswith(str(_ROOT))
        assert clip["output_path"] == ""

    if FFMPEG_AVAILABLE:
        image = _RESOURCES / "1.png"
        plan = ImageClipPlan(
            scene_index=1,
            source_image=str(image),
            duration_seconds=2.0,
            motion="ken-burns",
        )
        rendered = render_image_clip(plan, _make_settings(), enable_overlay=False)
        try:
            probed = probe_clip_duration(rendered.output_path)
            assert probed is not None
            assert abs(probed - 2.0) <= DURATION_TOLERANCE_SECONDS
        finally:
            if os.path.exists(rendered.output_path):
                os.remove(rendered.output_path)


def test_image_motion_modes():
    storyboard = _sample_storyboard()
    settings = _make_settings()
    plans = build_image_clip_plans(storyboard, image_paths=("a.png",), settings=settings)
    # Deterministic rotation: hook zooms in, middle pans, last scene zooms out.
    assert [plan.motion for plan in plans] == ["zoom-in", "pan-right", "zoom-out"]

    commands = {
        plan.motion: build_image_clip_command(plan, settings, "out.mp4")
        for plan in plans
    }

    # Commands are argument lists (never shell strings) starting with ffmpeg.
    for command in commands.values():
        assert isinstance(command, list)
        assert "&&" not in command and "|" not in command
        assert command[0] == utils.get_ffmpeg_binary()

    for plan in plans:
        joined = " ".join(build_image_clip_command(plan, settings, "o.mp4"))
        assert "zoompan=" in joined

    static_plan = ImageClipPlan(
        scene_index=9, source_image="a.png", duration_seconds=2, motion="static"
    )
    static_command = build_image_clip_command(static_plan, settings, "out.mp4")
    joined = " ".join(static_command)
    assert "-loop" in static_command
    assert "zoompan" not in joined

    # Pan directions move the camera inside the frame.
    left = build_zoompan_filter(
        ImageClipPlan(
            scene_index=1,
            source_image="a.png",
            duration_seconds=2,
            motion="pan-left",
            zoom_end=1.25,
        ),
        settings,
        frames=48,
    )
    right = build_zoompan_filter(
        ImageClipPlan(
            scene_index=1,
            source_image="a.png",
            duration_seconds=2,
            motion="pan-right",
            zoom_end=1.25,
        ),
        settings,
        frames=48,
    )
    assert "(1-on/47)" in left
    assert "on/47" in right and "(1-on/47)" not in right


def test_product_image_to_clip_manifest(tmp_path, monkeypatch):
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

    source = _RESOURCES / "1.png"
    stored_name = f"{uuid.uuid4().hex}.png"
    shutil.copy(source, local_videos / stored_name)

    resolved = resolve_local_image_asset(stored_name)
    assert os.path.isfile(resolved)

    if not FFMPEG_AVAILABLE:
        pytest.skip("ffmpeg is not available")

    storyboard = _sample_storyboard()
    manifest, _resolution, plans = prepare_image_clip_assets(
        storyboard,
        local_image_files=(stored_name,),
        price_text="12,900 บาท",
        badge_text="แนะนำ",
        settings=_make_settings(),
        render=True,
        timeout_seconds=120,
    )
    try:
        assert len(manifest.clips) == 3
        assert manifest.total_duration_seconds == pytest.approx(12.0)
        for clip in manifest.clips:
            assert clip.output_path, "rendered clip must have an output path"
            assert "js-image-clips" in clip.output_path
            probed = probe_clip_duration(clip.output_path)
            assert probed is not None
            assert abs(probed - clip.duration_seconds) <= DURATION_TOLERANCE_SECONDS
        # Params must carry storage keys only, never absolute paths.
        params = attach_clip_materials(VideoParams(video_subject="t"), plans)
        assert params.video_source == "local"
        for material in params.video_materials:
            assert not os.path.isabs(material.url)
            assert material.url.replace("\\", "/").startswith("js-image-clips/")
        assert params.video_clip_duration == 5
    finally:
        for plan in plans:
            if plan.output_path and os.path.exists(plan.output_path):
                os.remove(plan.output_path)
