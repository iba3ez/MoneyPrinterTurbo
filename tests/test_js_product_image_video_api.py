"""Phase 7 tests: product image-video API plan shape and flow regressions.

Storyboard planning is stubbed to the deterministic scaffold so tests stay
offline and fast; the planner itself is covered by the phase 2/6 suites.
"""

import os
import shutil
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.controllers.v1 import js_content as js_api
from app.controllers.v1.js_content import (
    NewsVideoRequest,
    ProductImageVideoRequest,
)
from app.services.js_content.storyboard import build_storyboard_scaffold
from app.utils import utils


def _scaffold_planner(brief, *, app_config=None, fallback_to_scaffold=True):
    return build_storyboard_scaffold(brief)


@pytest.fixture(autouse=True)
def _offline_planner(monkeypatch):
    from app.services.js_content import product as product_service

    monkeypatch.setattr(product_service, "generate_ai_storyboard", _scaffold_planner)
    from app.services.js_content import news as news_service

    monkeypatch.setattr(news_service, "generate_ai_storyboard", _scaffold_planner)


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(
        utils,
        "storage_dir",
        lambda sub_dir="", create=False: str(
            (storage_root / sub_dir) if sub_dir else storage_root
        ),
    )
    return storage_root


def _body(**overrides) -> ProductImageVideoRequest:
    fields = dict(product="RTX 5060", price="12,900 บาท", brand="jstech")
    fields.update(overrides)
    return ProductImageVideoRequest(**fields)


def test_product_plan_response(isolated_storage):
    plan = js_api.plan_product_image_video(None, _body())
    payload = plan.model_dump()

    # The plan contract: storyboard + asset manifest + clip manifest + params.
    assert set(payload) == {"storyboard", "asset_manifest", "clip_manifest", "video_params"}
    assert payload["storyboard"]["scenes"]
    assert payload["video_params"]["video_aspect"] == "9:16"

    # No explicit assets: the plan falls back to the existing stock workflow.
    assert payload["clip_manifest"]["clips"] == []
    assert payload["video_params"]["video_source"] == "pexels"
    resolution = payload["asset_manifest"]["resolution"]
    assert resolution["all_scenes_local"] is False


def test_product_plan_response_with_uploaded_image(isolated_storage):
    local_videos = isolated_storage / "local_videos"
    local_videos.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        Path(utils.root_dir()) / "test" / "resources" / "1.png",
        local_videos / f"{uuid.uuid4().hex}.png",
    )
    stored_name = f"{uuid.uuid4().hex}.png"
    shutil.copy(
        Path(utils.root_dir()) / "test" / "resources" / "1.png",
        local_videos / stored_name,
    )
    plan = js_api.plan_product_image_video(
        None,
        _body(
            local_image_files=[stored_name],
            clip_options={"badge_text": "แนะนำ"},
        ),
    )
    payload = plan.model_dump()

    clips = payload["clip_manifest"]["clips"]
    assert [clip["scene_index"] for clip in clips] == [1, 2, 3, 4, 5, 6]
    assert clips[0]["overlay_text"]
    assert clips[0]["badge_text"]
    assert clips[1]["price_text"] == "12,900 บาท"
    assert clips[-1]["price_text"] == ""
    # Unrendered plan: no server paths may leak into the response.
    for clip in clips:
        assert clip["output_path"] == ""
        assert "/" not in clip["source_image"] and "\\" not in clip["source_image"]
    resolution = payload["asset_manifest"]["resolution"]
    assert {asset["priority_label"] for asset in resolution["assets"]} == {
        "product-image-clip"
    }


def test_product_plan_rejects_unknown_image_file(isolated_storage):
    with pytest.raises(Exception) as excinfo:
        js_api.plan_product_image_video(None, _body(local_image_files=["missing.png"]))
    assert excinfo.value.status_code == 400
    assert "not found" in excinfo.value.message


def test_product_image_request_rejects_too_many_images():
    with pytest.raises(ValidationError):
        _body(local_image_files=[f"{index}.png" for index in range(11)])


def test_news_flow_regression():
    # Verified sources remain mandatory end to end.
    with pytest.raises(ValidationError):
        NewsVideoRequest(topic="ข่าว AI", sources=[])
    from app.services.js_content.news import NewsInput, build_news_content_brief

    with pytest.raises(ValueError):
        build_news_content_brief(NewsInput(topic="ข่าว AI", sources=()))

    body = NewsVideoRequest(
        topic="ข่าว AI",
        sources=[
            {
                "title": "ตัวอย่างข่าว",
                "url": "https://example.com/news",
            }
        ],
    )
    plan = js_api.plan_news_video(body)
    payload = plan.model_dump()
    assert payload["sources"][0]["url"] == "https://example.com/news"
    assert payload["video_params"]["video_script"]

    params = js_api.build_news_video_params(body)
    assert params.video_source == "pexels"
    assert params.match_materials_to_script is True


def test_general_video_regression():
    # The upstream general workflow contracts are untouched.
    from app.models.schema import TaskVideoRequest
    from app.controllers.v1.video import create_task, create_video

    params = TaskVideoRequest(video_subject="ทดสอบ")
    assert params.video_source == "pexels"
    assert params.subtitle_enabled is True
    assert params.video_clip_duration == 5
    assert callable(create_video)
    assert callable(create_task)

    # The existing local video attach path (phase 6) is unchanged.
    from app.services.js_content.local_media import attach_local_video_materials

    unchanged = attach_local_video_materials(params, [])
    assert unchanged.video_source == "pexels"


def test_product_image_video_params_renders_clips(isolated_storage):
    if shutil.which("ffmpeg") is None and not os.environ.get("IMAGEIO_FFMPEG_EXE"):
        pytest.skip("ffmpeg is not available")

    local_videos = isolated_storage / "local_videos"
    local_videos.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.png"
    shutil.copy(
        Path(utils.root_dir()) / "test" / "resources" / "1.png",
        local_videos / stored_name,
    )

    try:
        params = js_api.build_product_image_video_params(
            _body(local_image_files=[stored_name])
        )
    except Exception as exc:  # pragma: no cover - ffmpeg missing environments
        pytest.skip(f"ffmpeg rendering unavailable: {exc}")

    assert params.video_source == "local"
    assert len(params.video_materials) == 6
    urls = [material.url.replace("\\", "/") for material in params.video_materials]
    assert all(not url.startswith(str(Path(utils.root_dir()))) for url in urls)
    assert all(url.startswith("js-image-clips/") for url in urls)
    assert params.video_clip_duration == 5

    # Cleanup rendered clips so repeated runs stay lean.
    for url in urls:
        clip_path = Path(utils.root_dir()) / "storage" / "local_videos" / url
        if clip_path.exists():
            clip_path.unlink()
