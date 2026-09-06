from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .models import Storyboard
from .product import ProductInput


@dataclass(frozen=True, slots=True)
class SceneAssetBinding:
    scene_index: int
    asset_type: str
    asset_uri: str
    source: str
    role: str


@dataclass(frozen=True, slots=True)
class SceneAssetManifest:
    bindings: tuple[SceneAssetBinding, ...]

    def for_scene(self, scene_index: int) -> tuple[SceneAssetBinding, ...]:
        return tuple(binding for binding in self.bindings if binding.scene_index == scene_index)


def _validate_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"unsupported asset URL: {value}")
    return value


def bind_product_assets_to_storyboard(
    product: ProductInput,
    storyboard: Storyboard,
) -> SceneAssetManifest:
    """Bind verified product images to storyboard scenes deterministically.

    Product images are treated as first-class assets. The first image is reserved
    for the hook/opening scene, remaining images are distributed across middle
    scenes, and the final scene reuses the primary image for CTA/product recall.
    Scenes without a product image remain available for downstream stock/AI media.
    """

    product.validate()
    storyboard.validate()
    images = tuple(_validate_http_url(url.strip()) for url in product.image_urls if url.strip())
    if not images:
        return SceneAssetManifest(bindings=())

    bindings: list[SceneAssetBinding] = []
    scene_indexes = [scene.index for scene in storyboard.scenes]
    first_scene = scene_indexes[0]
    last_scene = scene_indexes[-1]

    bindings.append(
        SceneAssetBinding(
            scene_index=first_scene,
            asset_type="image",
            asset_uri=images[0],
            source="product",
            role="primary-hook",
        )
    )

    middle_scenes = scene_indexes[1:-1]
    secondary_images = images[1:] or images[:1]
    for offset, scene_index in enumerate(middle_scenes):
        asset_uri = secondary_images[offset % len(secondary_images)]
        bindings.append(
            SceneAssetBinding(
                scene_index=scene_index,
                asset_type="image",
                asset_uri=asset_uri,
                source="product",
                role="product-detail",
            )
        )

    if last_scene != first_scene:
        bindings.append(
            SceneAssetBinding(
                scene_index=last_scene,
                asset_type="image",
                asset_uri=images[0],
                source="product",
                role="cta-recall",
            )
        )

    return SceneAssetManifest(bindings=tuple(bindings))
