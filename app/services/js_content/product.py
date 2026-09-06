from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .models import ContentBrief
from .planner import generate_ai_storyboard


@dataclass(frozen=True, slots=True)
class ProductInput:
    name: str
    price: str = ""
    description: str = ""
    specs: Mapping[str, str] = field(default_factory=dict)
    source_url: str = ""
    image_urls: tuple[str, ...] = ()
    marketplace: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("product name must not be empty")

    def source_notes(self) -> tuple[str, ...]:
        notes: list[str] = []
        if self.description.strip():
            notes.append(f"description: {self.description.strip()}")
        if self.specs:
            spec_text = "; ".join(
                f"{str(key).strip()}: {str(value).strip()}"
                for key, value in self.specs.items()
                if str(key).strip() and str(value).strip()
            )
            if spec_text:
                notes.append(f"verified_specs: {spec_text}")
        if self.price.strip():
            notes.append(f"verified_price: {self.price.strip()}")
        if self.marketplace.strip():
            notes.append(f"marketplace: {self.marketplace.strip()}")
        if self.source_url.strip():
            notes.append(f"source_url: {self.source_url.strip()}")
        return tuple(notes)


def build_product_content_brief(
    product: ProductInput,
    *,
    objective: str = "สร้างวิดีโอขายสินค้าที่กระชับ น่าเชื่อถือ และกระตุ้นการตัดสินใจ",
    platform: str = "tiktok",
    aspect_ratio: str = "9:16",
    duration_seconds: int = 30,
    brand_key: str = "jstech",
) -> ContentBrief:
    """Convert verified product data into the shared JS Content Brain contract.

    Product facts are copied into ``source_notes`` so the planner can distinguish
    provided data from claims it must not invent.
    """

    product.validate()
    brief = ContentBrief(
        topic=f"รีวิวและแนะนำ {product.name.strip()}",
        objective=objective,
        platform=platform,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        brand_key=brand_key,
        product_name=product.name.strip(),
        price=product.price.strip(),
        source_notes=product.source_notes(),
    )
    brief.validate()
    return brief


def generate_product_storyboard(
    product: ProductInput,
    *,
    app_config=None,
    fallback_to_scaffold: bool = True,
    **brief_options,
):
    brief = build_product_content_brief(product, **brief_options)
    return generate_ai_storyboard(
        brief,
        app_config=app_config,
        fallback_to_scaffold=fallback_to_scaffold,
    )
