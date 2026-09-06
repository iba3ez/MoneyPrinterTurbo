from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

from .product import ProductInput


@dataclass(frozen=True, slots=True)
class MarketplaceProductPayload:
    marketplace: str
    name: str
    price: str = ""
    description: str = ""
    specs: Mapping[str, str] | None = None
    product_url: str = ""
    image_urls: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("marketplace product name must not be empty")
        if self.product_url:
            parsed = urlparse(self.product_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("marketplace product_url must be http/https")


def _detect_marketplace(product_url: str, declared: str = "") -> str:
    if declared.strip():
        return declared.strip().lower()
    host = urlparse(product_url).netloc.lower()
    if "shopee" in host:
        return "shopee"
    if "lazada" in host:
        return "lazada"
    if "tiktok" in host:
        return "tiktok-shop"
    return "generic"


def marketplace_payload_to_product_input(payload: MarketplaceProductPayload) -> ProductInput:
    """Normalize marketplace-sourced facts into the verified ProductInput contract.

    This adapter intentionally does not scrape marketplace pages. Callers must pass
    product facts already obtained through an authorized source/export/API. That keeps
    acquisition concerns separate from content generation and avoids hidden scraping
    behavior in the video engine.
    """

    payload.validate()
    marketplace = _detect_marketplace(payload.product_url, payload.marketplace)
    return ProductInput(
        name=payload.name.strip(),
        price=payload.price.strip(),
        description=payload.description.strip(),
        specs=dict(payload.specs or {}),
        source_url=payload.product_url.strip(),
        image_urls=tuple(url.strip() for url in payload.image_urls if url.strip()),
        marketplace=marketplace,
    )
