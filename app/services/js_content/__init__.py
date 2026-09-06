"""JS Content Video Engine extension layer.

This package intentionally stays isolated from the upstream MoneyPrinterTurbo
services so JS-specific development can evolve without making upstream merges
unnecessarily difficult.
"""

from .models import BrandProfile, ContentBrief, Scene, Storyboard

__all__ = ["BrandProfile", "ContentBrief", "Scene", "Storyboard"]
