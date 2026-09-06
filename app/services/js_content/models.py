from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class BrandProfile:
    key: str
    name: str
    language: str = "th-TH"
    tone: str = "clear, trustworthy, energetic"
    audience: str = "general"
    cta: str = ""
    watermark: str = ""
    visual_notes: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.key.strip():
            raise ValueError("brand key must not be empty")
        if not self.name.strip():
            raise ValueError("brand name must not be empty")


@dataclass(frozen=True, slots=True)
class ContentBrief:
    topic: str
    objective: str
    platform: str = "tiktok"
    aspect_ratio: str = "9:16"
    duration_seconds: int = 30
    brand_key: str = "jstech"
    product_name: str = ""
    price: str = ""
    source_notes: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.topic.strip():
            raise ValueError("topic must not be empty")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class Scene:
    index: int
    duration_seconds: float
    narration: str
    on_screen_text: str = ""
    visual_prompt: str = ""
    camera: str = ""
    transition: str = "cut"

    def validate(self) -> None:
        if self.index < 1:
            raise ValueError("scene index must start at 1")
        if self.duration_seconds <= 0:
            raise ValueError("scene duration must be greater than zero")
        if not self.narration.strip() and not self.on_screen_text.strip():
            raise ValueError("scene needs narration or on-screen text")


@dataclass(frozen=True, slots=True)
class Storyboard:
    title: str
    hook: str
    scenes: tuple[Scene, ...]
    cta: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def total_duration_seconds(self) -> float:
        return round(sum(scene.duration_seconds for scene in self.scenes), 3)

    def validate(self) -> None:
        if not self.scenes:
            raise ValueError("storyboard must contain at least one scene")
        expected = list(range(1, len(self.scenes) + 1))
        actual = [scene.index for scene in self.scenes]
        if actual != expected:
            raise ValueError(f"scene indexes must be sequential: expected {expected}, got {actual}")
        for scene in self.scenes:
            scene.validate()

    @classmethod
    def from_scenes(
        cls,
        *,
        title: str,
        hook: str,
        scenes: Iterable[Scene],
        cta: str = "",
        metadata: dict[str, str] | None = None,
    ) -> "Storyboard":
        storyboard = cls(
            title=title,
            hook=hook,
            scenes=tuple(scenes),
            cta=cta,
            metadata=metadata or {},
        )
        storyboard.validate()
        return storyboard
