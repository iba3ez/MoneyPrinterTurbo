from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List

from fastapi import Depends, Request
from pydantic import BaseModel, Field, HttpUrl

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.video import create_task
from app.models.exception import HttpException
from app.models.schema import TaskResponse, TaskVideoRequest
from app.services.js_content.assets import bind_product_assets_to_storyboard
from app.services.js_content.image_clip import MAX_IMAGE_CLIPS_PER_REQUEST
from app.services.js_content.image_clip_models import (
    ImageClipSettings,
    to_storage_key,
)
from app.services.js_content.local_media import (
    attach_local_video_materials,
    resolve_local_video_materials,
)
from app.services.js_content.news import NewsInput, NewsSource, generate_news_storyboard
from app.services.js_content.product import ProductInput, generate_product_storyboard
from app.services.js_content.render_bridge import storyboard_to_video_params
from app.services.js_content.render_pipeline import (
    attach_resolved_scene_materials,
    prepare_image_clip_assets,
)
from app.services.js_content.scene_render import build_scene_render_manifest


router = new_router(dependencies=[Depends(base.verify_token)])


class ProductVideoRequest(BaseModel):
    product: str = Field(min_length=1, max_length=500)
    price: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    specs: Dict[str, str] = Field(default_factory=dict)
    source_url: HttpUrl | None = None
    image_urls: List[HttpUrl] = Field(default_factory=list)
    marketplace: str = Field(default="", max_length=100)
    local_video_materials: List[str] = Field(default_factory=list)

    brand: str = Field(default="jstech", max_length=100)
    objective: str = Field(
        default="สร้างวิดีโอขายสินค้าที่กระชับ น่าเชื่อถือ และกระตุ้นการตัดสินใจ",
        max_length=1000,
    )
    platform: str = Field(default="tiktok", max_length=64)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")
    duration_seconds: int = Field(default=30, ge=5, le=180)
    video_source: str = Field(default="pexels", max_length=100)
    voice_name: str = Field(default="", max_length=200)
    bgm_type: str = Field(default="random", max_length=100)
    fallback_to_scaffold: bool = True


class ProductVideoPlanResponse(BaseModel):
    storyboard: dict
    render_manifest: dict
    asset_manifest: dict
    video_params: dict


class NewsSourceRequest(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    url: HttpUrl
    publisher: str = Field(default="", max_length=300)
    published_at: str = Field(default="", max_length=100)
    summary: str = Field(default="", max_length=5000)


class NewsVideoRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=1000)
    sources: List[NewsSourceRequest] = Field(min_length=1, max_length=20)
    brand: str = Field(default="jstech", max_length=100)
    objective: str = Field(
        default="สรุปข่าวให้เข้าใจง่าย กระชับ และอ้างอิงเฉพาะข้อมูลที่มีแหล่งที่มา",
        max_length=1000,
    )
    platform: str = Field(default="tiktok", max_length=64)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")
    duration_seconds: int = Field(default=45, ge=10, le=180)
    video_source: str = Field(default="pexels", max_length=100)
    voice_name: str = Field(default="", max_length=200)
    bgm_type: str = Field(default="random", max_length=100)
    fallback_to_scaffold: bool = True


class NewsVideoPlanResponse(BaseModel):
    storyboard: dict
    render_manifest: dict
    video_params: dict
    sources: List[dict]


class ProductImageClipOptions(BaseModel):
    """Image-to-Clip tuning; keep it small so FFmpeg stays fully server-side."""

    enable_overlay: bool = True
    badge_text: str = Field(default="", max_length=100)
    fps: int = Field(default=30, ge=12, le=60)


class ProductImageVideoRequest(ProductVideoRequest):
    """Product video request with local product images converted to clips."""

    local_image_files: List[str] = Field(
        default_factory=list,
        max_length=MAX_IMAGE_CLIPS_PER_REQUEST,
        description="Filenames returned by the local material upload endpoint",
    )
    clip_options: ProductImageClipOptions = Field(
        default_factory=ProductImageClipOptions
    )


class ProductImageVideoPlanResponse(BaseModel):
    storyboard: dict
    asset_manifest: dict
    clip_manifest: dict
    video_params: dict


def _build_product(body: ProductVideoRequest) -> ProductInput:
    return ProductInput(
        name=body.product,
        price=body.price,
        description=body.description,
        specs=body.specs,
        source_url=str(body.source_url or ""),
        image_urls=tuple(str(url) for url in body.image_urls),
        marketplace=body.marketplace,
    )


def _build_product_storyboard(body: ProductVideoRequest):
    return generate_product_storyboard(
        _build_product(body),
        fallback_to_scaffold=body.fallback_to_scaffold,
        objective=body.objective,
        platform=body.platform,
        aspect_ratio=body.aspect_ratio,
        duration_seconds=body.duration_seconds,
        brand_key=body.brand,
    )


def _build_news(body: NewsVideoRequest) -> NewsInput:
    return NewsInput(
        topic=body.topic,
        sources=tuple(
            NewsSource(
                title=source.title,
                url=str(source.url),
                publisher=source.publisher,
                published_at=source.published_at,
                summary=source.summary,
            )
            for source in body.sources
        ),
    )


def _build_news_storyboard(body: NewsVideoRequest):
    return generate_news_storyboard(
        _build_news(body),
        fallback_to_scaffold=body.fallback_to_scaffold,
        objective=body.objective,
        platform=body.platform,
        aspect_ratio=body.aspect_ratio,
        duration_seconds=body.duration_seconds,
        brand_key=body.brand,
    )


def _storyboard_payload(storyboard) -> dict:
    return {
        "title": storyboard.title,
        "hook": storyboard.hook,
        "cta": storyboard.cta,
        "metadata": storyboard.metadata,
        "scenes": [asdict(scene) for scene in storyboard.scenes],
    }


def _render_manifest_payload(storyboard) -> dict:
    manifest = build_scene_render_manifest(storyboard)
    return {
        "title": manifest.title,
        "hook": manifest.hook,
        "cta": manifest.cta,
        "total_duration_seconds": manifest.total_duration_seconds,
        "scenes": [asdict(scene) for scene in manifest.scenes],
    }


@router.post(
    "/js/product-video/plan",
    response_model=ProductVideoPlanResponse,
    summary="Plan a product video using JS Content Brain",
)
def plan_product_video(body: ProductVideoRequest):
    product = _build_product(body)
    storyboard = _build_product_storyboard(body)
    assets = bind_product_assets_to_storyboard(product, storyboard)
    params = storyboard_to_video_params(
        storyboard,
        subject=body.product,
        aspect_ratio=body.aspect_ratio,
        video_source=body.video_source,
        voice_name=body.voice_name,
        bgm_type=body.bgm_type,
    )
    if body.local_video_materials:
        params = attach_local_video_materials(params, body.local_video_materials)
    return ProductVideoPlanResponse(
        storyboard=_storyboard_payload(storyboard),
        render_manifest=_render_manifest_payload(storyboard),
        asset_manifest={"bindings": [asdict(binding) for binding in assets.bindings]},
        video_params=params.model_dump(),
    )


@router.post(
    "/js/product-video",
    response_model=TaskResponse,
    summary="Generate a product video using JS Content Brain",
)
def create_product_video(request: Request, body: ProductVideoRequest):
    storyboard = _build_product_storyboard(body)
    params = storyboard_to_video_params(
        storyboard,
        subject=body.product,
        aspect_ratio=body.aspect_ratio,
        video_source=body.video_source,
        voice_name=body.voice_name,
        bgm_type=body.bgm_type,
    )
    if body.local_video_materials:
        params = attach_local_video_materials(params, body.local_video_materials)
    task_body = TaskVideoRequest(**params.model_dump())
    return create_task(request, task_body, stop_at="video")


def _resolve_local_video_keys(filenames: List[str]) -> tuple[str, ...]:
    """Validate uploaded video filenames and reduce them to storage keys.

    Validation is delegated to the existing local material resolver (same
    whitelist directory, same traversal protection). Only portable storage
    keys are kept so no absolute server path ever enters task params.
    """

    if not filenames:
        return ()
    try:
        materials = resolve_local_video_materials(filenames)
    except ValueError as exc:
        raise HttpException(
            task_id="product-image-video",
            status_code=400,
            message=str(exc),
        )
    return tuple(to_storage_key(material.url) for material in materials)


def _prepare_product_image_clip_assets(
    body: ProductImageVideoRequest,
    storyboard,
    assets,
    *,
    render: bool,
    local_video_materials: tuple[str, ...] = (),
):
    settings = ImageClipSettings.for_aspect_ratio(
        body.aspect_ratio, fps=body.clip_options.fps
    )
    try:
        return prepare_image_clip_assets(
            storyboard,
            local_image_files=tuple(body.local_image_files),
            asset_manifest=assets,
            local_video_materials=local_video_materials,
            price_text=body.price,
            badge_text=body.clip_options.badge_text,
            brand_key=body.brand,
            settings=settings,
            enable_overlay=body.clip_options.enable_overlay,
            render=render,
        )
    except ValueError as exc:
        raise HttpException(
            task_id="product-image-video",
            status_code=400,
            message=str(exc),
        )


@router.post(
    "/js/product-image-video/plan",
    response_model=ProductImageVideoPlanResponse,
    summary="Plan a product video with product images converted to scene clips",
)
def plan_product_image_video(request: Request, body: ProductImageVideoRequest):
    product = _build_product(body)
    storyboard = _build_product_storyboard(body)
    assets = bind_product_assets_to_storyboard(product, storyboard)
    # Validation happens here (400 on invalid names); the resulting storage
    # keys flow into the scene resolver, which owns all priority decisions.
    local_video_keys = _resolve_local_video_keys(body.local_video_materials)
    clip_manifest, resolution, plans = _prepare_product_image_clip_assets(
        body, storyboard, assets, render=False,
        local_video_materials=local_video_keys,
    )
    params = storyboard_to_video_params(
        storyboard,
        subject=body.product,
        aspect_ratio=body.aspect_ratio,
        video_source=body.video_source,
        voice_name=body.voice_name,
        bgm_type=body.bgm_type,
    )
    # Plan stage: planned clips carry no output yet, so the resolution keeps
    # the stock workflow params unless uploaded local videos already cover
    # every scene. planning_notes explains any mixed-local fallback.
    params = attach_resolved_scene_materials(params, resolution)
    return ProductImageVideoPlanResponse(
        storyboard=_storyboard_payload(storyboard),
        asset_manifest={
            "bindings": [asdict(binding) for binding in assets.bindings],
            "resolution": resolution.to_dict(),
        },
        clip_manifest=clip_manifest.to_dict(),
        video_params=params.model_dump(),
    )


@router.post(
    "/js/product-image-video",
    response_model=TaskResponse,
    summary="Generate a product video from product images via the Image-to-Clip engine",
)
def create_product_image_video(request: Request, body: ProductImageVideoRequest):
    params = build_product_image_video_params(body)
    task_body = TaskVideoRequest(**params.model_dump())
    return create_task(request, task_body, stop_at="video")


def build_product_image_video_params(body: ProductImageVideoRequest):
    """Render image clips and return renderer params for a product video.

    Shared by the HTTP endpoint and the JS Content Studio WebUI so both entry
    points run the identical Image-to-Clip pipeline (backend is the single
    source of truth for storyboard and clip planning).
    """

    product = _build_product(body)
    storyboard = _build_product_storyboard(body)
    assets = bind_product_assets_to_storyboard(product, storyboard)
    # Validation happens here (400 on invalid names); the resulting storage
    # keys flow into the scene resolver, which owns all priority decisions.
    local_video_keys = _resolve_local_video_keys(body.local_video_materials)
    _clip_manifest, resolution, plans = _prepare_product_image_clip_assets(
        body, storyboard, assets, render=True,
        local_video_materials=local_video_keys,
    )
    params = storyboard_to_video_params(
        storyboard,
        subject=body.product,
        aspect_ratio=body.aspect_ratio,
        video_source=body.video_source,
        voice_name=body.voice_name,
        bgm_type=body.bgm_type,
    )
    rendered_plans = [clip for clip in plans if clip.output_path]
    max_scene_duration = (
        max(clip.duration_seconds for clip in rendered_plans)
        if rendered_plans
        else None
    )
    # The scene resolver decides which assets enter the local timeline and in
    # which order; mixed local/stock timelines fall back to the stock workflow.
    return attach_resolved_scene_materials(
        params,
        resolution,
        max_scene_duration_seconds=max_scene_duration,
    )


def build_news_video_params(body: NewsVideoRequest):
    """Return renderer params for a sourced news video (shared with the WebUI)."""

    storyboard = _build_news_storyboard(body)
    return storyboard_to_video_params(
        storyboard,
        subject=body.topic,
        aspect_ratio=body.aspect_ratio,
        video_source=body.video_source,
        voice_name=body.voice_name,
        bgm_type=body.bgm_type,
    )


@router.post(
    "/js/news-video/plan",
    response_model=NewsVideoPlanResponse,
    summary="Plan a sourced news video using JS Content Brain",
)
def plan_news_video(body: NewsVideoRequest):
    news = _build_news(body)
    storyboard = _build_news_storyboard(body)
    params = storyboard_to_video_params(
        storyboard,
        subject=body.topic,
        aspect_ratio=body.aspect_ratio,
        video_source=body.video_source,
        voice_name=body.voice_name,
        bgm_type=body.bgm_type,
    )
    return NewsVideoPlanResponse(
        storyboard=_storyboard_payload(storyboard),
        render_manifest=_render_manifest_payload(storyboard),
        video_params=params.model_dump(),
        sources=[asdict(source) for source in news.sources],
    )


@router.post(
    "/js/news-video",
    response_model=TaskResponse,
    summary="Generate a sourced news video using JS Content Brain",
)
def create_news_video(request: Request, body: NewsVideoRequest):
    storyboard = _build_news_storyboard(body)
    params = storyboard_to_video_params(
        storyboard,
        subject=body.topic,
        aspect_ratio=body.aspect_ratio,
        video_source=body.video_source,
        voice_name=body.voice_name,
        bgm_type=body.bgm_type,
    )
    task_body = TaskVideoRequest(**params.model_dump())
    return create_task(request, task_body, stop_at="video")
