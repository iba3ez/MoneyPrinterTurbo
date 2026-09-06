from dataclasses import asdict

from app.controllers.v1.js_content import ProductVideoRequest
from app.services.js_content.models import Scene, Storyboard
from app.services.js_content.scene_render import build_scene_render_manifest


def test_product_video_request_accepts_verified_product_data():
    body = ProductVideoRequest(
        product="RTX 5060",
        price="12,900 บาท",
        specs={"VRAM": "8GB"},
        brand="jstech",
    )
    assert body.product == "RTX 5060"
    assert body.price == "12,900 บาท"
    assert body.specs["VRAM"] == "8GB"
    assert body.aspect_ratio == "9:16"


def test_scene_render_manifest_preserves_scene_order_and_duration():
    storyboard = Storyboard.from_scenes(
        title="Demo",
        hook="Hook",
        cta="CTA",
        scenes=(
            Scene(index=1, duration_seconds=3, narration="A", visual_prompt="visual A"),
            Scene(index=2, duration_seconds=4, narration="B", visual_prompt="visual B"),
        ),
    )
    manifest = build_scene_render_manifest(storyboard)
    assert [scene.scene_index for scene in manifest.scenes] == [1, 2]
    assert manifest.total_duration_seconds == 7
    assert asdict(manifest.scenes[0])["visual_prompt"] == "visual A"
