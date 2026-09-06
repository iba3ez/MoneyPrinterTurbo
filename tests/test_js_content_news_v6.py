import pytest
from pydantic import ValidationError

from app.controllers.v1.js_content import NewsVideoRequest
from app.services.js_content.news import NewsInput, NewsSource, build_news_content_brief


def test_news_requires_verified_source():
    with pytest.raises(ValueError):
        build_news_content_brief(NewsInput(topic="ข่าว AI", sources=()))


def test_news_source_becomes_verified_source_note():
    news = NewsInput(
        topic="ข่าว AI",
        sources=(
            NewsSource(
                title="ตัวอย่างข่าว",
                url="https://example.com/news",
                publisher="Example",
                published_at="2026-09-07",
                summary="สรุปข้อเท็จจริงจากแหล่งข่าว",
            ),
        ),
    )
    brief = build_news_content_brief(news)
    assert len(brief.source_notes) == 1
    assert "verified_news_title: ตัวอย่างข่าว" in brief.source_notes[0]
    assert "source_url: https://example.com/news" in brief.source_notes[0]
    assert "verified_summary: สรุปข้อเท็จจริงจากแหล่งข่าว" in brief.source_notes[0]


def test_news_api_rejects_empty_sources():
    with pytest.raises(ValidationError):
        NewsVideoRequest(topic="ข่าว AI", sources=[])
