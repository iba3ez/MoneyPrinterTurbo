from __future__ import annotations

from .models import BrandProfile


BRANDS: dict[str, BrandProfile] = {
    "jstech": BrandProfile(
        key="jstech",
        name="JSTech",
        tone="clear, practical, trustworthy, energetic Thai IT shop",
        audience="Thai PC buyers, gamers, office users, and repair customers",
        cta="ทัก JSTech เพื่อสอบถามสเปก ราคา งานซ่อม หรืออัปเกรด",
        watermark="JSTech",
        visual_notes=(
            "clean studio product presentation",
            "high readability for Thai text",
            "mobile-first social video framing",
        ),
    ),
    "jsflix": BrandProfile(
        key="jsflix",
        name="JSFLIX",
        tone="fast, entertaining, curiosity-driven Thai streaming content",
        audience="Thai mobile streaming and short-drama viewers",
        cta="ดูรายละเอียดเพิ่มเติมกับ JSFLIX",
        watermark="JSFLIX",
        visual_notes=(
            "cinematic vertical composition",
            "strong first-frame hook",
            "platform-friendly on-screen captions",
        ),
    ),
    "jsplus": BrandProfile(
        key="jsplus",
        name="JSPLUS+",
        tone="clear, modern, conversion-focused Thai digital service",
        audience="Thai users looking for digital and premium services",
        cta="สอบถามบริการและแพ็กเกจ JSPLUS+",
        watermark="JSPLUS+",
        visual_notes=(
            "clean digital-service visual language",
            "clear offer hierarchy",
            "mobile-first call to action",
        ),
    ),
}


def get_brand_profile(key: str) -> BrandProfile:
    normalized = key.strip().lower()
    try:
        profile = BRANDS[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(BRANDS))
        raise ValueError(f"unknown brand '{key}'. supported brands: {supported}") from exc
    profile.validate()
    return profile
