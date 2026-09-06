from __future__ import annotations

import json
from typing import Any

from .models import Scene, Storyboard


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_storyboard_json(raw: str) -> Storyboard:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("LLM storyboard response must be non-empty text")

    text = _strip_code_fences(raw)
    try:
        payload: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid storyboard JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("storyboard JSON root must be an object")

    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("storyboard JSON must contain a non-empty scenes array")

    scenes: list[Scene] = []
    for position, item in enumerate(raw_scenes, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"scene {position} must be an object")

        index = int(item.get("index", position))
        duration = float(item.get("duration_seconds", 0))
        scene = Scene(
            index=index,
            duration_seconds=duration,
            narration=str(item.get("narration", "")).strip(),
            on_screen_text=str(item.get("on_screen_text", "")).strip(),
            visual_prompt=str(item.get("visual_prompt", "")).strip(),
            camera=str(item.get("camera", "")).strip(),
            transition=str(item.get("transition", "cut")).strip() or "cut",
        )
        scene.validate()
        scenes.append(scene)

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    return Storyboard.from_scenes(
        title=str(payload.get("title", "")).strip() or "Untitled",
        hook=str(payload.get("hook", "")).strip(),
        scenes=scenes,
        cta=str(payload.get("cta", "")).strip(),
        metadata={str(k): str(v) for k, v in metadata.items()},
    )
