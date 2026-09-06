"""JS Content Studio — Streamlit page for the JS AI Content Production OS.

Runs as a Streamlit multipage entry next to ``webui/Main.py`` so the upstream
general video workflow stays untouched. Product / News / General modes share
the backend planning pipeline through ``app.controllers.v1.js_content``; the
page never re-implements storyboard logic — the backend is the single source
of truth and this page only renders its plan output.
"""

import json
import os
import sys
import time
from uuid import uuid4

# WebUI multipage entries run as standalone scripts: the project root must be
# importable before any ``app`` import, mirroring webui/Main.py.
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

import streamlit as st
from loguru import logger

from app.controllers.v1 import js_content as js_api
from app.models import const
from app.models.schema import VideoParams
from app.services import material_upload, webui_task
from app.services import state as sm

_IMAGE_EXTENSIONS = material_upload.SUPPORTED_IMAGE_EXTENSIONS
_VIDEO_EXTENSIONS = material_upload.SUPPORTED_VIDEO_EXTENSIONS
_BRANDS = ("jstech", "jsflix", "jsplus")
_BGM_OPTIONS = [("", "No BGM"), ("random", "Random BGM")]


def tr(key: str) -> str:
    """Minimal i18n with the same English fallback rule as webui/Main.py."""

    language = st.session_state.get("ui_language", "en")
    try:
        path = os.path.join(
            root_dir, "webui", "i18n", f"{language}.json"
        )
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream).get("Translation", {}).get(key)
        if value:
            return value
    except (OSError, ValueError):
        pass
    return key


def _persist_upload(uploaded_file, allowed_extensions) -> str:
    extension = os.path.splitext(uploaded_file.name)[1].lower()
    if extension not in allowed_extensions:
        raise ValueError(f"unsupported file type: {extension}")
    return material_upload.save_material_upload(uploaded_file.name, uploaded_file)


def _persist_uploads(uploaded_files, allowed_extensions) -> list[str]:
    stored_names = []
    for uploaded_file in uploaded_files or []:
        try:
            stored_names.append(_persist_upload(uploaded_file, allowed_extensions))
        except ValueError:
            st.error(tr("Unsupported Upload File Type") + f": {uploaded_file.name}")
            st.stop()
        except Exception as exc:  # service/storage failures
            logger.error(f"material upload failed: {exc}")
            st.error(tr("Background Music Validation Failed"))
            st.stop()
    return stored_names


def _scene_rows(plan_payload: dict) -> list[dict]:
    """Join storyboard scenes with clip manifest + asset resolution (read-only).

    All inputs come from the backend plan response; nothing is re-planned here.
    """

    storyboard = plan_payload.get("storyboard") or {}
    clips = {
        clip.get("scene_index"): clip
        for clip in (plan_payload.get("clip_manifest") or {}).get("clips", [])
    }
    assets = {
        asset.get("scene_index"): asset
        for asset in ((plan_payload.get("asset_manifest") or {}).get("resolution") or {}).get(
            "assets", []
        )
    }
    rows = []
    for scene in storyboard.get("scenes", []):
        index = scene.get("index")
        clip = clips.get(index, {})
        asset = assets.get(index, {})
        rows.append(
            {
                "scene": index,
                "duration": scene.get("duration_seconds"),
                "narration": scene.get("narration", ""),
                "on_screen_text": scene.get("on_screen_text", ""),
                "visual_prompt": scene.get("visual_prompt", ""),
                "asset": asset.get("priority_label", ""),
                "motion": clip.get("motion", "—"),
                "transition": scene.get("transition", ""),
            }
        )
    return rows


def _render_storyboard_preview(plan_payload: dict) -> None:
    storyboard = plan_payload.get("storyboard") or {}
    st.markdown(f"### {storyboard.get('title', '')}")
    st.caption(storyboard.get("hook", ""))
    if storyboard.get("cta"):
        st.caption(f"CTA: {storyboard.get('cta')}")
    for row in _scene_rows(plan_payload):
        with st.container(border=True):
            cols = st.columns([1, 3, 3])
            cols[0].markdown(f"**Scene {row['scene']}**\n\n{row['duration']}s")
            cols[1].markdown(
                f"**{tr('Narration')}**\n\n{row['narration'] or '—'}\n\n"
                f"**{tr('On-screen Text')}**\n\n{row['on_screen_text'] or '—'}"
            )
            cols[2].markdown(
                f"**{tr('Visual Prompt')}**\n\n{row['visual_prompt'] or '—'}\n\n"
                f"**{tr('Asset')}**: {row['asset'] or '—'} · "
                f"**{tr('Motion')}**: {row['motion']} · "
                f"**{tr('Transition')}**: {row['transition']}"
            )
    clip_manifest = plan_payload.get("clip_manifest") or {}
    if clip_manifest.get("clips"):
        st.info(
            f"{tr('Clip Manifest')}: {len(clip_manifest['clips'])} clips, "
            f"{clip_manifest.get('total_duration_seconds', 0)}s total, "
            f"{clip_manifest.get('width')}x{clip_manifest.get('height')}@{clip_manifest.get('fps')}fps"
        )


def _poll_task(task_id: str, progress_bar) -> dict | None:
    while True:
        task = sm.state.get_task(task_id)
        if not task:
            return None
        progress_bar.progress(min(100, int(task.get("progress") or 0)))
        state = task.get("state")
        if state in (const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED):
            return task
        time.sleep(1.5)


def _submit_generation(params: VideoParams):
    task_id = str(uuid4())
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=0,
        video_subject=params.video_subject or params.video_script or task_id,
    )
    webui_task.submit_generation(task_id=task_id, params=params)
    progress_bar = st.progress(0)
    task = _poll_task(task_id, progress_bar)
    if not task:
        st.error(tr("Video Generation Failed"))
        return
    if task.get("state") == -1:
        st.error(f"{tr('Video Generation Failed')}: {task.get('error', '')}")
        return
    st.success(tr("Video Generation Completed"))
    for video_path in task.get("videos") or []:
        if os.path.isfile(video_path):
            st.video(video_path)


def _product_request_from_form(**fields) -> js_api.ProductImageVideoRequest:
    specs = {}
    for line in (fields.get("specs_text") or "").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() and value.strip():
                specs[key.strip()[:100]] = value.strip()[:300]
    return js_api.ProductImageVideoRequest(
        product=fields["product"],
        price=fields.get("price", ""),
        description=fields.get("description", ""),
        specs=specs,
        source_url=fields.get("source_url") or None,
        image_urls=fields.get("image_urls"),
        brand=fields.get("brand", "jstech"),
        platform=fields.get("platform", "tiktok"),
        aspect_ratio=fields.get("aspect_ratio", "9:16"),
        duration_seconds=fields.get("duration_seconds", 30),
        video_source=fields.get("video_source", "pexels"),
        voice_name=fields.get("voice_name", ""),
        bgm_type=fields.get("bgm_type", ""),
        local_image_files=fields.get("local_image_files", []),
        local_video_materials=fields.get("local_video_materials", []),
        clip_options=js_api.ProductImageClipOptions(
            enable_overlay=fields.get("enable_overlay", True),
            badge_text=fields.get("badge_text", ""),
            fps=fields.get("fps", 30),
        ),
    )


def _render_product_tab() -> None:
    st.subheader("🎬 " + tr("Product Video"))

    uploaded_images = st.file_uploader(
        tr("Product Images"),
        type=[ext.removeprefix(".") for ext in _IMAGE_EXTENSIONS],
        accept_multiple_files=True,
    )
    uploaded_videos = st.file_uploader(
        tr("Local Videos"),
        type=[ext.removeprefix(".") for ext in _VIDEO_EXTENSIONS],
        accept_multiple_files=True,
    )

    left, right = st.columns(2)
    with left:
        brand = st.selectbox(tr("Brand"), _BRANDS)
        product = st.text_input(tr("Product Name"), max_chars=500)
        price = st.text_input(tr("Price"), max_chars=200)
        source_url = st.text_input(tr("Source URL (optional)"))
        platform = st.selectbox(tr("Platform"), ("tiktok", "youtube", "instagram"))
    with right:
        aspect_ratio = st.selectbox(tr("Aspect Ratio"), ("9:16", "16:9", "1:1"))
        duration_seconds = st.slider(tr("Duration (seconds)"), 10, 180, 30)
        voice_name = st.text_input(tr("Voice Name"), value="th-TH-PremwadeeNeural-Female")
        bgm_label_to_value = {label: value for value, label in _BGM_OPTIONS}
        bgm_type = st.selectbox(
            tr("Background Music"), options=list(bgm_label_to_value.keys()),
            format_func=lambda v: v,
        )

    description = st.text_area(tr("Description"), max_chars=4000)
    specs_text = st.text_area(
        tr("Specs (one per line, e.g. VRAM: 8GB)"), height=80
    )

    with st.expander(tr("Advanced Settings")):
        enable_overlay = st.checkbox(tr("Enable Text Overlays"), value=True)
        badge_text = st.text_input(tr("Badge Text"), max_chars=100)
        fps = st.selectbox(tr("Clip FPS"), (24, 30), index=1)

    stored_images = _persist_uploads(uploaded_images, _IMAGE_EXTENSIONS)
    stored_videos = _persist_uploads(uploaded_videos, _VIDEO_EXTENSIONS)

    form = dict(
        product=product,
        price=price,
        description=description,
        specs_text=specs_text,
        source_url=source_url.strip() or None,
        brand=brand,
        platform=platform,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        video_source="pexels",
        voice_name=voice_name.strip(),
        bgm_type=bgm_label_to_value[bgm_type],
        local_image_files=stored_images,
        local_video_materials=stored_videos,
        enable_overlay=enable_overlay,
        badge_text=badge_text,
        fps=int(fps),
    )

    action_left, action_right = st.columns(2)
    if action_left.button("🧠 " + tr("Generate Storyboard"), type="primary"):
        if not product.strip():
            st.error(tr("Please Enter Product Name"))
            st.stop()
        body = _product_request_from_form(**form)
        try:
            with st.spinner(tr("Planning Storyboard")):
                plan = js_api.plan_product_image_video(None, body)
            st.session_state["js_studio_product_plan"] = plan.model_dump()
        except Exception as exc:  # validation / planning errors surface to UI
            st.error(str(exc))

    if action_right.button("✨ " + tr("Analyze")):
        if not product.strip():
            st.error(tr("Please Enter Product Name"))
            st.stop()
        body = _product_request_from_form(**form)
        product_input = js_api._build_product(body)
        st.info(
            "**" + tr("Analyzed Product Facts") + "**\n\n"
            + "\n".join(f"- {note}" for note in product_input.source_notes())
            + f"\n\n- uploaded images: {len(stored_images)}"
            + f"\n- uploaded videos: {len(stored_videos)}"
        )

    plan_payload = st.session_state.get("js_studio_product_plan")
    if plan_payload:
        st.divider()
        _render_storyboard_preview(plan_payload)
        if st.button("🎥 " + tr("Generate Video"), type="primary"):
            body = _product_request_from_form(**form)
            try:
                with st.status(tr("Rendering Scene Clips")):
                    params = js_api.build_product_image_video_params(body)
            except Exception as exc:
                st.error(str(exc))
                st.stop()
            _submit_generation(params)


def _render_news_tab() -> None:
    st.subheader("📰 " + tr("News Video"))
    st.caption(tr("News Video Requires Source"))

    topic = st.text_input(tr("News Topic"), max_chars=1000)
    sources = []
    for i in range(2):
        cols = st.columns([2, 3])
        title = cols[0].text_input(tr("Source Title") + f" {i + 1}", key=f"news_title_{i}")
        url = cols[1].text_input(tr("Source URL") + f" {i + 1}", key=f"news_url_{i}")
        if title.strip() and url.strip():
            sources.append({"title": title.strip(), "url": url.strip()})

    left, right = st.columns(2)
    with left:
        brand = st.selectbox(tr("Brand"), _BRANDS, key="news_brand")
        duration_seconds = st.slider(tr("Duration (seconds)"), 10, 180, 45, key="news_duration")
    with right:
        aspect_ratio = st.selectbox(tr("Aspect Ratio"), ("9:16", "16:9", "1:1"), key="news_aspect")
        voice_name = st.text_input(
            tr("Voice Name"), value="th-TH-PremwadeeNeural-Female", key="news_voice"
        )

    if st.button("🧠 " + tr("Generate Storyboard"), type="primary"):
        if not topic.strip() or not sources:
            st.error(tr("News Video Requires Source"))
            st.stop()
        try:
            body = js_api.NewsVideoRequest(
                topic=topic.strip(),
                sources=sources,
                brand=brand,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                voice_name=voice_name.strip(),
                bgm_type="",
            )
            with st.spinner(tr("Planning Storyboard")):
                plan = js_api.plan_news_video(body)
            st.session_state["js_studio_news_plan"] = plan.model_dump()
            st.session_state["js_studio_news_body"] = body.model_dump()
        except Exception as exc:
            st.error(str(exc))

    plan_payload = st.session_state.get("js_studio_news_plan")
    if plan_payload:
        _render_storyboard_preview(plan_payload)
        if st.button("🎥 " + tr("Generate Video"), type="primary"):
            try:
                body = js_api.NewsVideoRequest(**st.session_state["js_studio_news_body"])
                with st.spinner(tr("Preparing News Video")):
                    params = js_api.build_news_video_params(body)
            except Exception as exc:
                st.error(str(exc))
                st.stop()
            _submit_generation(params)


def _render_general_tab() -> None:
    st.subheader("🎞️ " + tr("General Video"))
    st.caption(tr("General Video Uses Upstream Workflow"))

    subject = st.text_input(tr("Video Subject"), max_chars=500)
    script = st.text_area(tr("Video Script (optional)"), height=120)

    left, right = st.columns(2)
    with left:
        aspect_ratio = st.selectbox(tr("Aspect Ratio"), ("9:16", "16:9", "1:1"), key="gen_aspect")
        voice_name = st.text_input(
            tr("Voice Name"), value="th-TH-PremwadeeNeural-Female", key="gen_voice"
        )
    with right:
        video_source = st.selectbox(tr("Video Source"), ("pexels", "pixabay"), key="gen_source")
        clip_duration = st.slider(tr("Clip Duration (seconds)"), 1, 20, 5, key="gen_clip")

    if st.button("🎥 " + tr("Generate Video"), type="primary"):
        if not subject.strip():
            st.error(tr("Please Enter Video Subject"))
            st.stop()
        params = VideoParams(
            video_subject=subject.strip(),
            video_script=script.strip(),
            video_aspect=aspect_ratio,
            video_source=video_source,
            voice_name=voice_name.strip(),
            video_clip_duration=clip_duration,
            bgm_type="random",
        )
        _submit_generation(params)


def main() -> None:
    st.set_page_config(page_title="JS Content Studio", page_icon="🎬", layout="wide")
    st.title("🎬 JS Content Studio")
    st.caption(tr("JS Content Studio Subtitle"))

    product_tab, news_tab, general_tab = st.tabs(
        ["🎬 " + tr("Product Video"), "📰 " + tr("News Video"), "🎞️ " + tr("General Video")]
    )
    with product_tab:
        _render_product_tab()
    with news_tab:
        _render_news_tab()
    with general_tab:
        _render_general_tab()


main()
