"""FFmpeg-based Image-to-Clip rendering for the JS Content Engine.

Security contract:
- FFmpeg is always invoked through ``subprocess.run`` with an argument list
  (``shell=True`` is never used) and a hard timeout.
- Every filter expression is built server-side from validated model fields;
  user-provided text only reaches FFmpeg through ``overlay.build_overlay_filters``
  which performs drawtext escaping.
- Source images must resolve inside the ``storage/local_videos`` whitelist
  directory, reusing the existing upload validators instead of duplicating them.
- Rendered clips are written to a dedicated subdirectory of the same whitelist
  directory so the upstream renderer can re-resolve them, while API responses
  only ever carry storage keys, never absolute server paths.
"""

from __future__ import annotations

import os
import re
import subprocess
from uuid import uuid4

from loguru import logger

from app.services import material_upload
from app.services.js_content.overlay import build_overlay_filters, resolve_overlay_font
from app.utils import file_security, utils

from .image_clip_models import (
    MOTION_STATIC,
    ImageClipPlan,
    ImageClipSettings,
)

CLIP_OUTPUT_SUBDIR = "js-image-clips"
CLIP_RENDER_TIMEOUT_SECONDS = 120
MAX_IMAGE_CLIPS_PER_REQUEST = 10
_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)")


class ImageClipRenderError(RuntimeError):
    """Rendering a scene clip failed or timed out."""


def clip_output_dir(create: bool = True) -> str:
    """Directory for generated clips, inside the allowed local material storage."""

    base_dir = utils.storage_dir("local_videos", create=create)
    output_dir = os.path.join(base_dir, CLIP_OUTPUT_SUBDIR)
    if create and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    return output_dir


def resolve_local_image_asset(filename: str) -> str:
    """Resolve an uploaded product image inside the local material whitelist.

    Reuses ``material_upload.sanitize_material_filename`` and the shared
    path-traversal resolver. Absolute paths, ``..`` segments, and symlink
    escapes are all rejected; callers receive the resolved absolute path or a
    ``ValueError``.
    """

    safe_name = material_upload.sanitize_material_filename(filename)
    suffix = os.path.splitext(safe_name)[1].lower()
    if suffix not in material_upload.SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(
            "product image must be one of: "
            f"{', '.join(material_upload.SUPPORTED_IMAGE_EXTENSIONS)}"
        )
    base_dir = utils.storage_dir("local_videos", create=True)
    try:
        return file_security.resolve_path_within_directory(base_dir, safe_name)
    except ValueError as exc:
        raise ValueError(f"uploaded product image not found: {safe_name}") from exc


def _escape_drawtext_path(path: str) -> str:
    escaped = path.replace("\\", "/")
    escaped = escaped.replace(":", r"\:").replace("'", r"\'")
    return escaped


def build_normalization_filters(settings: ImageClipSettings) -> list[str]:
    """Aspect-preserving cover normalization: scale then crop, never distort."""

    width, height = settings.width, settings.height
    # zoompan operates on the pre-scaled frame so animated zoom keeps quality;
    # the margin covers the maximum allowed zoom factor.
    canvas_width, canvas_height = width * 2, height * 2
    return [
        (
            f"scale={canvas_width}:{canvas_height}"
            ":force_original_aspect_ratio=increase"
        ),
        f"crop={canvas_width}:{canvas_height}",
        "setsar=1",
    ]


def build_zoompan_filter(
    plan: ImageClipPlan,
    settings: ImageClipSettings,
    frames: int,
) -> str:
    """Build the zoompan filter for a validated motion plan.

    The zoompan input is a single frame; ``d=frames`` duplicates it into the
    output timeline and ``on`` counts output frames 0..frames-1, which keeps
    motion expressions deterministic.
    """

    last_frame = max(frames - 1, 1)
    progress = f"*on/{last_frame}"

    if plan.motion == "zoom-in":
        z_expr = f"{plan.zoom_start}+({plan.zoom_end - plan.zoom_start}){progress}"
        x_expr, y_expr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif plan.motion == "zoom-out":
        z_expr = f"{plan.zoom_start}-({plan.zoom_start - plan.zoom_end}){progress}"
        x_expr, y_expr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif plan.motion == "pan-left":
        z_expr = f"{max(plan.zoom_end, plan.zoom_start)}"
        x_expr, y_expr = f"(iw-iw/zoom)*(1-on/{last_frame})", "ih/2-(ih/zoom/2)"
    elif plan.motion == "pan-right":
        z_expr = f"{max(plan.zoom_end, plan.zoom_start)}"
        x_expr, y_expr = f"(iw-iw/zoom)*on/{last_frame}", "ih/2-(ih/zoom/2)"
    elif plan.motion == "pan-up":
        z_expr = f"{max(plan.zoom_end, plan.zoom_start)}"
        x_expr, y_expr = "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{last_frame})"
    elif plan.motion == "pan-down":
        z_expr = f"{max(plan.zoom_end, plan.zoom_start)}"
        x_expr, y_expr = "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*on/{last_frame}"
    elif plan.motion == "ken-burns":
        z_expr = f"{plan.zoom_start}+({plan.zoom_end - plan.zoom_start}){progress}"
        x_expr, y_expr = f"(iw-iw/zoom)*on/{last_frame}", f"(ih-ih/zoom)*on/{last_frame}"
    else:
        raise ValueError(f"unsupported motion for zoompan: {plan.motion}")

    return (
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={settings.width}x{settings.height}:fps={settings.fps}"
    )


def build_image_clip_command(
    plan: ImageClipPlan,
    settings: ImageClipSettings,
    output_path: str,
    *,
    overlay_filters: list[str] | None = None,
) -> list[str]:
    """Return the complete FFmpeg argument list for one clip."""

    plan.validate()
    frames = max(1, round(plan.duration_seconds * settings.fps))
    ffmpeg = utils.get_ffmpeg_binary()

    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if plan.motion == MOTION_STATIC:
        command += ["-loop", "1", "-i", plan.source_image]
    else:
        # A single input frame is enough: zoompan duplicates it into `frames`.
        command += ["-i", plan.source_image]

    filters = build_normalization_filters(settings)
    if plan.motion != MOTION_STATIC:
        filters.append(build_zoompan_filter(plan, settings, frames))
    filters.extend(overlay_filters or [])
    filters.append("format=yuv420p")

    command += ["-filter_complex", f"[0:v]{','.join(filters)}[v]"]
    command += ["-map", "[v]"]
    if plan.motion != MOTION_STATIC:
        command += ["-frames:v", str(frames)]
    command += ["-t", f"{plan.duration_seconds:.3f}"]
    command += [
        "-r", str(settings.fps),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-movflags", "+faststart",
        output_path,
    ]
    return command


def render_image_clip(
    plan: ImageClipPlan,
    settings: ImageClipSettings,
    *,
    timeout_seconds: int = CLIP_RENDER_TIMEOUT_SECONDS,
    enable_overlay: bool = True,
    brand_watermark: str = "",
) -> ImageClipPlan:
    """Render one scene clip and return the plan with ``output_path`` filled."""

    plan.validate()
    output_dir = clip_output_dir(create=True)
    output_path = os.path.join(output_dir, f"js-clip-{uuid4().hex}.mp4")

    overlay_filters: list[str] = []
    if enable_overlay and (
        plan.overlay_text or plan.price_text or plan.badge_text or brand_watermark
    ):
        font_path = resolve_overlay_font()
        if font_path is None:
            logger.warning(
                "no suitable overlay font found; rendering scene "
                f"{plan.scene_index} without text overlays"
            )
        else:
            overlay_filters = build_overlay_filters(
                plan,
                settings,
                font_path=font_path,
                brand_watermark=brand_watermark,
            )

    command = build_image_clip_command(
        plan,
        settings,
        output_path,
        overlay_filters=overlay_filters,
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _discard_partial_output(output_path)
        raise ImageClipRenderError(
            f"image clip rendering timed out after {timeout_seconds}s "
            f"for scene {plan.scene_index}"
        ) from exc
    except OSError as exc:
        raise ImageClipRenderError(
            f"failed to launch FFmpeg for scene {plan.scene_index}: {exc}"
        ) from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        _discard_partial_output(output_path)
        raise ImageClipRenderError(
            f"FFmpeg failed for scene {plan.scene_index} "
            f"with return code {completed.returncode}: {stderr[:500]}"
        )
    if not os.path.isfile(output_path):
        raise ImageClipRenderError(
            f"FFmpeg reported success but scene {plan.scene_index} clip is missing"
        )

    logger.info(
        f"image clip rendered: scene={plan.scene_index}, motion={plan.motion}, "
        f"duration={plan.duration_seconds}s"
    )
    return plan.with_output_path(output_path)


def _discard_partial_output(output_path: str) -> None:
    if output_path and os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError as exc:
            logger.warning(f"failed to remove partial clip: {str(exc)}")


def probe_clip_duration(
    video_path: str, timeout_seconds: int = 30
) -> float | None:
    """Probe a rendered clip's duration, or return None when it cannot be read."""

    command = [
        utils.get_ffmpeg_binary(),
        "-nostdin",
        "-hide_banner",
        "-i",
        video_path,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout_seconds, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    # ffmpeg -i writes stream info to stderr and exits non-zero without an
    # output file; the Duration line in stderr is the reliable source here.
    match = _DURATION_PATTERN.search(completed.stderr.decode("utf-8", errors="replace"))
    if not match:
        return None
    hours, minutes, seconds, centiseconds = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + centiseconds / 100


def resolve_clip_storage_key(output_path: str) -> str:
    """Map a rendered clip path to the storage key exposed through the API."""

    from .image_clip_models import to_storage_key

    return to_storage_key(output_path)
