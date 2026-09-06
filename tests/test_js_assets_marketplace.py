from app.services.js_content.assets import bind_product_assets_to_storyboard
from app.services.js_content.marketplace import MarketplaceProductPayload, marketplace_payload_to_product_input
from app.services.js_content.models import Scene, Storyboard
from app.services.js_content.product import ProductInput


def _storyboard():
    return Storyboard.from_scenes(
        title="GPU",
        hook="Hook",
        cta="CTA",
        scenes=[
            Scene(index=1, duration_seconds=3, narration="เปิด"),
            Scene(index=2, duration_seconds=4, narration="รายละเอียด"),
            Scene(index=3, duration_seconds=3, narration="ปิด"),
        ],
    )


def test_product_images_bind_to_open_middle_and_cta_scenes():
    product = ProductInput(
        name="RTX 5060",
        image_urls=("https://example.com/a.jpg", "https://example.com/b.jpg"),
    )
    manifest = bind_product_assets_to_storyboard(product, _storyboard())
    assert [item.scene_index for item in manifest.bindings] == [1, 2, 3]
    assert manifest.bindings[0].asset_uri.endswith("a.jpg")
    assert manifest.bindings[1].asset_uri.endswith("b.jpg")
    assert manifest.bindings[2].asset_uri.endswith("a.jpg")


def test_marketplace_adapter_detects_shopee_and_preserves_verified_data():
    payload = MarketplaceProductPayload(
        marketplace="",
        name="Gaming Mouse",
        price="799 บาท",
        specs={"sensor": "PAW3395"},
        product_url="https://shopee.co.th/product/123/456",
        image_urls=("https://example.com/mouse.jpg",),
    )
    product = marketplace_payload_to_product_input(payload)
    assert product.marketplace == "shopee"
    assert product.price == "799 บาท"
    assert product.specs["sensor"] == "PAW3395"
