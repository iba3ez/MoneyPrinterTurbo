from app.services.js_content.models import Scene, Storyboard
from app.services.js_content.product import ProductInput, build_product_content_brief
from app.services.js_content.render_bridge import storyboard_to_video_params


def test_product_brief_preserves_verified_facts():
    product = ProductInput(
        name="RTX 5060",
        price="12,900 บาท",
        description="การ์ดจอสำหรับเกมและงานทั่วไป",
        specs={"VRAM": "8GB", "Warranty": "3 years"},
        marketplace="shop",
    )
    brief = build_product_content_brief(product, brand_key="jstech")

    assert brief.product_name == "RTX 5060"
    assert brief.price == "12,900 บาท"
    joined = " | ".join(brief.source_notes)
    assert "verified_price: 12,900 บาท" in joined
    assert "VRAM: 8GB" in joined


def test_storyboard_converts_to_video_params():
    storyboard = Storyboard.from_scenes(
        title="Test Product",
        hook="Hook",
        scenes=(
            Scene(1, 4, "ประโยคแรก", "ข้อความแรก", "gaming GPU product shot"),
            Scene(2, 4, "ประโยคสอง", "ข้อความสอง", "close-up cooling fans"),
        ),
        cta="ทักร้านเพื่อสอบถาม",
    )

    params = storyboard_to_video_params(storyboard, aspect_ratio="9:16")
    assert params.video_subject == "Test Product"
    assert "ประโยคแรก" in params.video_script
    assert params.match_materials_to_script is True
    assert len(params.video_terms) == 2
