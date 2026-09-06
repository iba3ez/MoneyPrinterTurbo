from __future__ import annotations

from dataclasses import dataclass

from .models import Storyboard


@dataclass(frozen=True, slots=True)
class SceneRenderItem:
    scene_index: int
    duration_seconds: float
    narration: str
    on_screen_text: str
    visual_prompt: str
    camera: str
    transition: str


@dataclass(frozen=True, slots=True)
class SceneRenderManifest:
    title: str
    hook: str
    cta: str
    scenes: tuple[SceneRenderItem, ...]

    @property
    def total_duration_seconds(self) -> float:
        return round(sum(scene.duration_seconds for scene in self.scenes), 3)


def build_scene_render_manifest(storyboard: Storyboard) -> SceneRenderManifest:
    """Create a stable, ordered render manifest from a validated storyboard.

    The manifest preserves scene boundaries explicitly so downstream material
    search/generation can bind one asset set per scene instead of treating all
    visual prompts as a flat keyword list.
    """

    storyboard.validate()
    scenes = tuple(
        SceneRenderItem(
            scene_index=scene.index,
            duration_seconds=scene.duration_seconds,
            narration=scene.narration.strip(),
            on_screen_text=scene.on_screen_text.strip(),
            visual_prompt=scene.visual_prompt.strip(),
            camera=scene.camera.strip(),
            transition=scene.transition.strip(),
        )
        for scene in storyboard.scenes
    )
    return SceneRenderManifest(
        title=storyboard.title,
        hook=storyboard.hook,
        cta=storyboard.cta,
        scenes=scenes,
    )
