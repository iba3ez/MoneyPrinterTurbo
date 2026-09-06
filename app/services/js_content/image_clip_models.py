"""Data contracts for the JS Image-to-Clip Engine (Phase 7).

The models stay free of FFmpeg specifics so they can be validated, serialized
into a clip manifest, and transported through the plan API without pulling the
rendering layer in. All values that later reach FFmpeg are produced by
``image_clip.py`` itself; user input only ever lands in validated fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

MOTION_STATIC = "static"
MOTION_ZOOM_IN = "zoom-in"
MOTION_ZOOM_OUT = "zoom-out"
MOTION_PAN_LEFT = "pan-left"
MOTION_PAN_RIGHT = "pan-right"
MOTION_PAN_UP = "pan-up"
MOTION_PAN_DOWN = "pan-down"
MOTION_KEN_BURNS = "ken-burns"

MOTION_MODES: tuple[str, ...] = (
    MOTION_STATIC,
    MOTION_ZOOM_IN,
    MOTION_ZOOM_OUT,
    MOTION_PAN_LEFT,
    MOTION_PAN_RIGHT,
    MOTION_PAN_UP,
    MOTION_PAN_DOWN,
    MOTION_KEN_BURNS,
)

PANNING_MOTIONS: frozenset[str] = frozenset(
    {
        MOTION_PAN_LEFT,
        MOTION_PAN_RIGHT,
        MOTION_PAN_UP,
        MOTION_PAN_DOWN,
        MOTION_KEN_BURNS,
    }
)

# Product Video defaults target mobile social platforms (TikTok / Reels / Shorts).
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
SUPPORTED_ASPECT_RATIOS: tuple[str, ...] = tuple(DEFAULT_RESOLUTIONS)

DEFAULT_FPS = 30
MIN_FPS = 12
MAX_FPS = 60

# Encoding introduces ±1 frame of rounding; the manifest exposes the tolerance
# so callers (and tests) can assert scene-duration fidelity without guessing.
DURATION_TOLERANCE_SECONDS = 0.2

MIN_CLIP_DURATION_SECONDS = 0.5
MAX_CLIP_DURATION_SECONDS = 60.0

MIN_ZOOM = 1.0
MAX_ZOOM = 2.0

# Every frame must carry motion to keep the clip alive on social feeds. A pure
# static plan is allowed, but panning motions require a crop margin that the
# camera can travel inside.
DEFAULT_PAN_MARGIN_ZOOM = 1.25


@dataclass(frozen=True, slots=True)
class ImageClipSettings:
    """Global settings applied to every clip of one render run."""

    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    fps: int = DEFAULT_FPS
    width: int = 0
    height: int = 0

    def __post_init__(self) -> None:
        if self.aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
            raise ValueError(
                f"unsupported aspect ratio: {self.aspect_ratio}. "
                f"supported: {', '.join(SUPPORTED_ASPECT_RATIOS)}"
            )
        if not MIN_FPS <= self.fps <= MAX_FPS:
            raise ValueError(f"fps must be between {MIN_FPS} and {MAX_FPS}")
        expected = DEFAULT_RESOLUTIONS[self.aspect_ratio]
        if (self.width, self.height) != expected:
            raise ValueError(
                f"resolution {self.width}x{self.height} does not match "
                f"{self.aspect_ratio} ({expected[0]}x{expected[1]})"
            )

    @classmethod
    def for_aspect_ratio(
        cls, aspect_ratio: str = DEFAULT_ASPECT_RATIO, fps: int = DEFAULT_FPS
    ) -> "ImageClipSettings":
        width, height = DEFAULT_RESOLUTIONS[aspect_ratio]
        return cls(aspect_ratio=aspect_ratio, fps=fps, width=width, height=height)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ImageClipPlan:
    """One scene's product image and how it becomes a video clip.

    ``source_image`` is a server-resolved absolute path while the plan lives in
    memory; it must never be serialized into API responses (``to_public_dict``
    strips it). ``output_path`` is filled by the renderer after FFmpeg succeeds
    and is likewise only exposed as a storage-relative key.
    """

    scene_index: int
    source_image: str
    duration_seconds: float
    motion: str = MOTION_KEN_BURNS
    zoom_start: float = 1.0
    zoom_end: float = 1.3
    pan_direction: str = ""
    overlay_text: str = ""
    price_text: str = ""
    badge_text: str = ""
    transition: str = "cut"
    output_path: str = ""

    def validate(self) -> None:
        if self.scene_index < 1:
            raise ValueError("scene index must start at 1")
        if not self.source_image.strip():
            raise ValueError("clip plan requires a source image")
        if not (
            MIN_CLIP_DURATION_SECONDS
            <= self.duration_seconds
            <= MAX_CLIP_DURATION_SECONDS
        ):
            raise ValueError(
                f"clip duration must be between {MIN_CLIP_DURATION_SECONDS} "
                f"and {MAX_CLIP_DURATION_SECONDS} seconds"
            )
        if self.motion not in MOTION_MODES:
            raise ValueError(
                f"unsupported motion '{self.motion}'. "
                f"supported: {', '.join(MOTION_MODES)}"
            )
        for name, zoom in (("zoom_start", self.zoom_start), ("zoom_end", self.zoom_end)):
            if not MIN_ZOOM <= zoom <= MAX_ZOOM:
                raise ValueError(f"{name} must be between {MIN_ZOOM} and {MAX_ZOOM}")
        if self.motion in PANNING_MOTIONS and not self.pan_direction:
            object.__setattr__(self, "pan_direction", _default_pan_direction(self.motion))
        if self.motion != MOTION_STATIC and self.zoom_end <= self.zoom_start and (
            self.motion in {MOTION_ZOOM_IN, MOTION_KEN_BURNS}
        ):
            raise ValueError(
                f"motion '{self.motion}' requires zoom_end greater than zoom_start"
            )
        if self.motion == MOTION_ZOOM_OUT and self.zoom_start <= self.zoom_end:
            raise ValueError("motion 'zoom-out' requires zoom_start greater than zoom_end")

    def with_output_path(self, output_path: str) -> "ImageClipPlan":
        return replace(self, output_path=output_path)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_public_dict(self) -> dict:
        """Serialize for API responses: no server filesystem paths are leaked.

        The absolute ``source_image`` is reduced to its basename and
        ``output_path`` becomes a storage key relative to the allowed material
        directory, so clients can reference the clip without learning where the
        server stores files.
        """

        import os

        data = asdict(self)
        data["source_image"] = os.path.basename(data.get("source_image") or "")
        data["output_path"] = to_storage_key(data.get("output_path") or "")
        return data


def _default_pan_direction(motion: str) -> str:
    if motion == MOTION_PAN_LEFT:
        return "left"
    if motion == MOTION_PAN_RIGHT:
        return "right"
    if motion == MOTION_PAN_UP:
        return "up"
    if motion == MOTION_PAN_DOWN:
        return "down"
    if motion == MOTION_KEN_BURNS:
        return "right-down"
    return ""


def to_storage_key(path: str) -> str:
    """Reduce a renderer asset path to a portable storage key.

    Relative keys already inside the material whitelist are returned unchanged
    (only normalized), absolute paths under the local material directory are
    reduced to the path after ``local_videos/``, and anything else is reduced
    to its basename. API responses therefore never carry absolute server
    paths, while the upstream renderer can still re-resolve every key inside
    its whitelist directory.
    """

    import os

    if not path:
        return ""
    normalized = os.path.normpath(path).replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if not os.path.isabs(path):
        return normalized
    marker = "local_videos/"
    position = normalized.find(marker)
    if position >= 0:
        return normalized[position + len(marker):]
    return os.path.basename(normalized)


@dataclass(frozen=True, slots=True)
class ImageClipManifest:
    """Ordered result of converting product images into scene clips."""

    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    width: int = 0
    height: int = 0
    fps: int = DEFAULT_FPS
    duration_tolerance_seconds: float = DURATION_TOLERANCE_SECONDS
    clips: tuple[ImageClipPlan, ...] = field(default_factory=tuple)

    @property
    def total_duration_seconds(self) -> float:
        return round(sum(clip.duration_seconds for clip in self.clips), 3)

    def validate(self) -> None:
        if self.aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
            raise ValueError(f"unsupported aspect ratio: {self.aspect_ratio}")
        for clip in self.clips:
            clip.validate()

    def to_dict(self) -> dict:
        return {
            "aspect_ratio": self.aspect_ratio,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_tolerance_seconds": self.duration_tolerance_seconds,
            "total_duration_seconds": self.total_duration_seconds,
            "clips": [clip.to_public_dict() for clip in self.clips],
        }
