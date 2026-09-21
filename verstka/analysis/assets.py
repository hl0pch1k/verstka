"""Extract reusable media assets from the template and tag them."""

from __future__ import annotations

import hashlib
import io
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from verstka.analysis.shapes import ShapeInfo
from verstka.ingest.package import PptxPackage
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import ShapeKind
from verstka.schemas.template import Asset
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)

_SVG_SIZE_RE = re.compile(r'viewBox="[\d.\-]+\s+[\d.\-]+\s+([\d.]+)\s+([\d.]+)"')


class AssetTag(BaseModel):
    """Output of the `asset_tagger` skill."""

    kind: str = Field(description="icon|logo|mockup|illustration|photo|pattern|other")
    tags: list[str] = Field(default_factory=list)
    description: str = ""


def _image_meta(data: bytes, ext: str) -> tuple[int, int, bool]:
    if ext == "svg":
        m = _SVG_SIZE_RE.search(data[:4000].decode("utf-8", "ignore"))
        if m:
            return int(float(m.group(1))), int(float(m.group(2))), True
        return 0, 0, True
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            has_alpha = im.mode in ("RGBA", "LA", "P") and ("transparency" in im.info or im.mode in ("RGBA", "LA"))
            if im.mode == "RGBA":
                # only count real transparency
                extrema = im.getchannel("A").getextrema()
                has_alpha = extrema[0] < 255
            return im.width, im.height, bool(has_alpha)
    except Exception:  # noqa: BLE001
        return 0, 0, False


def extract_assets(
    package: PptxPackage,
    shapes_by_slide: dict[int, list[ShapeInfo]],
    assets_dir: Path,
    chrome_image_parts: Optional[set[str]] = None,
    slide_w: int = 12192000,
    slide_h: int = 6858000,
    max_assets: int = 600,
) -> tuple[list[Asset], dict[str, str]]:
    """Returns (assets, image_part → asset_id)."""
    chrome_image_parts = chrome_image_parts or set()
    assets_dir.mkdir(parents=True, exist_ok=True)
    usage: dict[str, list[tuple[int, ShapeInfo]]] = defaultdict(list)
    for idx, shapes in shapes_by_slide.items():
        for s in shapes:
            if s.image_part:
                usage[s.image_part].append((idx, s))
    assets: list[Asset] = []
    id_by_part: dict[str, str] = {}
    by_hash: dict[str, Asset] = {}
    for part, uses in list(usage.items())[:max_assets]:
        if not package.exists(part):
            continue
        data = package.read(part)
        ext = part.rsplit(".", 1)[-1].lower()
        if ext == "jpeg":
            ext = "jpg"
        digest = hashlib.sha1(data).hexdigest()[:10]
        if digest in by_hash:
            a = by_hash[digest]
            a.used_on_slides = sorted(set(a.used_on_slides) | {i for i, _ in uses})
            id_by_part[part] = a.id
            continue
        w, h, alpha = _image_meta(data, ext)
        max_used_w = max((s.bbox.w / slide_w for _, s in uses), default=0.0)
        max_used_area = max((s.bbox.area / float(slide_w * slide_h) for _, s in uses), default=0.0)
        kind = "other"
        if part in chrome_image_parts:
            kind = "logo"
        elif max_used_area >= 0.8:
            kind = "pattern"
        elif ext == "svg" or (max(w, h) <= 160) or (max_used_w <= 0.08 and alpha):
            kind = "icon"
        elif alpha:
            kind = "illustration"
        elif ext in ("jpg", "png", "webp", "gif", "bmp", "tif", "tiff"):
            kind = "photo"
        asset_id = f"a{digest}"
        out_path = assets_dir / f"{asset_id}.{ext}"
        if not out_path.exists():
            out_path.write_bytes(data)
        a = Asset(id=asset_id, path=str(out_path.relative_to(assets_dir.parent)), kind=kind, width=w, height=h, has_alpha=alpha, used_on_slides=sorted({i for i, _ in uses}), media_part=part)
        assets.append(a)
        by_hash[digest] = a
        id_by_part[part] = asset_id
    return assets, id_by_part


def tag_assets_with_vlm(assets: list[Asset], base_dir: Path, skills: SkillsRegistry, providers: ProviderRegistry, max_n: int = 30) -> list[str]:
    """Tag the largest non-icon assets with a VLM. Returns warnings."""
    warnings: list[str] = []
    if not providers.has("vlm"):
        return warnings
    from verstka.analysis.classify import image_bytes_for_vlm

    candidates = [a for a in assets if a.kind in ("illustration", "photo", "other", "pattern") and a.width * a.height >= 200 * 200 and not a.path.endswith(".svg")]
    candidates.sort(key=lambda a: -(a.width * a.height))
    for a in candidates[:max_n]:
        try:
            img = image_bytes_for_vlm(base_dir / a.path, max_w=512)
            res = skills.run("asset_tagger", providers, {"kind_hint": a.kind, "width": a.width, "height": a.height}, images=[img])
            tag: AssetTag = res.parsed
            if tag.kind in ("icon", "logo", "mockup", "illustration", "photo", "pattern", "other"):
                a.kind = tag.kind
            a.tags = [t.strip().lower() for t in tag.tags if t.strip()][:8]
            if tag.description:
                a.tags.append("desc:" + tag.description[:120])
        except (ProviderError, OSError, ValueError) as e:
            warnings.append(f"asset {a.id}: tagging failed: {str(e)[:120]}")
    return warnings
