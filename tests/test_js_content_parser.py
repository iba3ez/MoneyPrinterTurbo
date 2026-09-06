import pytest

from app.services.js_content.models import ContentBrief
from app.services.js_content.parser import parse_storyboard_json
from app.services.js_content.storyboard import build_storyboard_scaffold


def test_parse_storyboard_json_valid():
    raw = '''{
      "title": "ทดสอบ",
      "hook": "ฮุก",
      "cta": "ทักเรา",
      "scenes": [
        {
          "index": 1,
          "duration_seconds": 4,
          "narration": "เริ่มเรื่อง",
          "on_screen_text": "เริ่ม",
          "visual_prompt": "clean studio shot",
          "camera": "close-up",
          "transition": "cut"
        }
      ],
      "metadata": {"language": "th-TH"}
    }'''

    storyboard = parse_storyboard_json(raw)
    assert storyboard.title == "ทดสอบ"
    assert storyboard.total_duration_seconds == 4.0
    assert storyboard.metadata["language"] == "th-TH"


def test_parse_storyboard_rejects_empty_scenes():
    with pytest.raises(ValueError):
        parse_storyboard_json('{"title":"x","scenes":[]}')


def test_scaffold_is_deterministic():
    brief = ContentBrief(topic="ประกอบคอมงบ 20000", objective="ให้ความรู้", duration_seconds=30)
    a = build_storyboard_scaffold(brief)
    b = build_storyboard_scaffold(brief)
    assert a == b
    assert 3 <= len(a.scenes) <= 8
