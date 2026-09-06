from __future__ import annotations

from dataclasses import dataclass, field

from .models import ContentBrief
from .planner import generate_ai_storyboard


@dataclass(frozen=True, slots=True)
class NewsSource:
    title: str
    url: str
    publisher: str = ""
    published_at: str = ""
    summary: str = ""

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("news source title must not be empty")
        if not self.url.strip().startswith(("http://", "https://")):
            raise ValueError("news source URL must be http(s)")

    def to_source_note(self) -> str:
        self.validate()
        parts = [
            f"verified_news_title: {self.title.strip()}",
            f"source_url: {self.url.strip()}",
        ]
        if self.publisher.strip():
            parts.append(f"publisher: {self.publisher.strip()}")
        if self.published_at.strip():
            parts.append(f"published_at: {self.published_at.strip()}")
        if self.summary.strip():
            parts.append(f"verified_summary: {self.summary.strip()}")
        return " | ".join(parts)


@dataclass(frozen=True, slots=True)
class NewsInput:
    topic: str
    sources: tuple[NewsSource, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.topic.strip():
            raise ValueError("news topic must not be empty")
        if not self.sources:
            raise ValueError("news-to-video requires at least one verified source")
        for source in self.sources:
            source.validate()


def build_news_content_brief(
    news: NewsInput,
    *,
    objective: str = "สรุปข่าวให้เข้าใจง่าย กระชับ และอ้างอิงเฉพาะข้อมูลที่มีแหล่งที่มา",
    platform: str = "tiktok",
    aspect_ratio: str = "9:16",
    duration_seconds: int = 45,
    brand_key: str = "jstech",
) -> ContentBrief:
    news.validate()
    source_notes = tuple(source.to_source_note() for source in news.sources)
    brief = ContentBrief(
        topic=news.topic.strip(),
        objective=objective,
        platform=platform,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        brand_key=brand_key,
        source_notes=source_notes,
    )
    brief.validate()
    return brief


def generate_news_storyboard(
    news: NewsInput,
    *,
    app_config=None,
    fallback_to_scaffold: bool = True,
    **brief_options,
):
    brief = build_news_content_brief(news, **brief_options)
    return generate_ai_storyboard(
        brief,
        app_config=app_config,
        fallback_to_scaffold=fallback_to_scaffold,
    )
