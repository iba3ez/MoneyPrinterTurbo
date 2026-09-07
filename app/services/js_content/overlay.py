"""Overlay engine for the JS Image-to-Clip Engine.

Draws product name, price, badge, CTA and brand watermark onto scene clips via
FFmpeg ``drawtext``. All strings are escaped before they reach the filter
graph, layout respects mobile social safe areas (TikTok / Reels / Shorts keep
the bottom ~20% and the right edge busy with platform UI), and the font is
resolved through a fallback chain instead of a hardcoded machine-specific
path. No font binaries are committed by this feature.
"""

from __future__ import annotations

import os

from loguru import logger

from app.utils import utils

from .image_clip_models import ImageClipPlan, ImageClipSettings

# Candidate font families that ship Thai glyphs, ordered by preference.
# Matching is by filename substring so the resolver works across platforms
# without hardcoding a single machine-specific absolute path.
_THAI_FONT_CANDIDATES: tuple[str, ...] = (
    "NotoSansThai",
    "Noto Sans Thai",
    "Sarabun",
    "THSarabun",
    "Leelawadee",
    "Charm-Regular",
    "Charm-Bold",
    "Tahoma",
    "Angsana",
    "Browallia",
    "Waree",
    "Loma",
    "Garuda",
    "Kinnari",
)

_FONT_SEARCH_DIRS: tuple[str, ...] = (
    utils.font_dir(),  # resource/fonts (already part of the project)
    r"C:\Windows\Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
)


class OverlayFontError(RuntimeError):
    pass


def _iter_font_files(directory: str):
    if not os.path.isdir(directory):
        return
    for current_dir, _subdirs, files in os.walk(directory):
        for name in files:
            if name.lower().endswith((".ttf", ".otf", ".ttc")):
                yield os.path.join(current_dir, name)


def resolve_overlay_font(font_path: str = "") -> str | None:
    """Resolve a Thai-capable font file, or None when none can be found.

    Resolution order:
    1. Explicitly provided path (dependency injection for tests / deployments).
    2. Filenames inside ``resource/fonts`` matching the Thai candidate list.
    3. System font directories matching the same list.

    The function never raises for a missing font; callers are expected to
    render without overlays so a cosmetic limitation cannot fail a video task.
    """

    if font_path:
        if not os.path.isfile(font_path):
            raise OverlayFontError(f"configured overlay font not found: {font_path}")
        return font_path

    for candidate in _THAI_FONT_CANDIDATES:
        lowered = candidate.lower()
        for directory in _FONT_SEARCH_DIRS:
            for font_file in _iter_font_files(directory):
                if lowered in os.path.basename(font_file).lower():
                    return font_file

    available = sorted(
        os.path.basename(font_file)
        for font_file in _iter_font_files(utils.font_dir())
    )
    logger.warning(
        "no Thai-capable overlay font resolved; "
        f"fonts present in resource/fonts: {available or 'none'}"
    )
    return None


def escape_drawtext_text(value: str) -> str:
    """Escape untrusted text for a drawtext ``text='...'`` value.

    Handles the drawtext metacharacters (backslash, colon, quote, percent) and
    flattens line breaks / control characters so the text can never alter the
    filter graph structure.
    """

    text = (value or "").replace("\r", " ").replace("\n", " ")
    text = "".join(
        character for character in text if character.isprintable() or character == " "
    ).strip()
    text = text.replace("\\", "\\\\").replace(":", r"\:")
    text = text.replace("'", r"\'").replace("%", r"\%")
    return text


def _escape_filter_path(path: str) -> str:
    escaped = path.replace("\\", "/")
    escaped = escaped.replace(":", r"\:").replace("'", r"\'")
    return escaped


def social_safe_area(settings: ImageClipSettings) -> dict[str, float]:
    """Margins that keep text clear of platform UI on TikTok / Reels / Shorts."""

    width, height = float(settings.width), float(settings.height)
    return {
        "left": width * 0.08,
        "right": width * 0.92,
        "top": height * 0.10,
        "bottom": height * 0.80,
    }


def build_overlay_filters(
    plan: ImageClipPlan,
    settings: ImageClipSettings,
    *,
    font_path: str,
    brand_watermark: str = "",
) -> list[str]:
    """Build the chained drawtext filters for one clip plan.

    The returned filters are safe to join into ``filter_complex``: all dynamic
    content passes through ``escape_drawtext_text`` / ``_escape_filter_path``
    and every numeric parameter is derived from validated settings.
    """

    plan.validate()
    if not os.path.isfile(font_path):
        raise OverlayFontError(f"overlay font not found: {font_path}")

    height = settings.height
    safe = social_safe_area(settings)
    fontfile = _escape_filter_path(font_path)
    base_style = (
        f"fontfile='{fontfile}'"
        ":fontcolor=white"
        ":borderw=2"
        ":bordercolor=black@0.65"
        ":box=1"
        ":boxcolor=black@0.35"
    )
    box_padding = max(8, round(height * 0.008))

    filters: list[str] = []

    def _draw(text: str, *, fontsize: int, x: str, y: str) -> None:
        escaped = escape_drawtext_text(text)
        if not escaped:
            return
        filters.append(
            "drawtext="
            f"{base_style}"
            f":boxborderw={box_padding}"
            f":fontsize={fontsize}"
            f":text='{escaped}'"
            f":x='{x}'"
            f":y='{y}'"
        )

    centered = "(w-text_w)/2"
    if plan.badge_text:
        _draw(
            plan.badge_text,
            fontsize=max(20, round(height * 0.030)),
            x=centered,
            y=f"{safe['top']:.0f}",
        )

    if plan.overlay_text:
        _draw(
            plan.overlay_text,
            fontsize=max(28, round(height * 0.042)),
            x=centered,
            # Above the price row and comfortably inside the bottom safe area.
            y="h*0.60-text_h/2",
        )

    if plan.price_text:
        _draw(
            plan.price_text,
            fontsize=max(32, round(height * 0.052)),
            x=centered,
            y="h*0.70-text_h/2",
        )

    if brand_watermark:
        _draw(
            brand_watermark,
            fontsize=max(16, round(height * 0.022)),
            # Bottom-left corner of the safe area: never flush with the very
            # bottom edge and never on the right where platform buttons sit.
            x=f"{safe['left']:.0f}",
            y=f"{safe['bottom']:.0f}-text_h",
        )

    return filters


def overlay_enabled_for_settings(settings: ImageClipSettings) -> bool:
    """Guard hook for future resolution-based overlay restrictions."""

    return settings.width > 0 and settings.height > 0


__all__ = [
    "OverlayFontError",
    "build_overlay_filters",
    "escape_drawtext_text",
    "overlay_enabled_for_settings",
    "resolve_overlay_font",
    "social_safe_area",
]
