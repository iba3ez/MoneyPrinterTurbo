from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from app.models.schema import MaterialInfo, VideoParams
from app.services import material_upload
from app.utils import file_security, utils


def _resolve_uploaded_filename(filename: str) -> str:
    safe_name = material_upload.sanitize_material_filename(filename)
    base_dir = utils.storage_dir("local_videos", create=True)
    try:
        return file_security.resolve_path_within_directory(base_dir, safe_name)
    except ValueError as exc:
        raise ValueError(f"uploaded material not found: {safe_name}") from exc


def resolve_local_video_materials(filenames: Iterable[str]) -> list[MaterialInfo]:
    """Resolve previously uploaded local *video* material into renderer inputs.

    Images are intentionally excluded here. The upstream renderer's local material
    pipeline is video-oriented; product images stay in the scene asset manifest until
    an explicit image-to-clip conversion step is selected.
    """

    materials: list[MaterialInfo] = []
    for raw_name in filenames:
        name = str(raw_name or "").strip()
        if not name:
            continue
        path = _resolve_uploaded_filename(name)
        suffix = Path(path).suffix.lower()
        if suffix not in material_upload.SUPPORTED_VIDEO_EXTENSIONS:
            raise ValueError(
                f"local renderer material must be a video ({', '.join(material_upload.SUPPORTED_VIDEO_EXTENSIONS)}): {name}"
            )
        materials.append(
            MaterialInfo(
                provider="local",
                url=path,
                duration=0,
                source_info={"provider": "local", "asset_id": os.path.basename(path)},
            )
        )
    return materials


def attach_local_video_materials(
    params: VideoParams,
    filenames: Iterable[str],
) -> VideoParams:
    materials = resolve_local_video_materials(filenames)
    if not materials:
        return params

    data = params.model_dump()
    data.update(
        {
            "video_source": "local",
            "video_materials": materials,
            "match_materials_to_script": True,
        }
    )
    return VideoParams(**data)
