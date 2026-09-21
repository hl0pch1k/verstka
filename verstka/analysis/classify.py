"""Slide classification: heuristics + LLM (structured JSON) + VLM (rendered image) ensemble."""

from __future__ import annotations

import io
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from verstka.analysis.groups import group_membership
from verstka.analysis.kinds import heuristic_kind
from verstka.analysis.roles import heuristic_roles
from verstka.analysis.shapes import ShapeInfo
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import PatternKind, ShapeKind, SlotRole
from verstka.schemas.template import ClassificationTrace, RepeatGroup, SignalVote, Typography
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)


class SlideClassification(BaseModel):
    """Output of the `slide_classifier` skill."""

    kind: PatternKind
    roles: dict[str, SlotRole] = Field(default_factory=dict)  # shape_id → role
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class SlideVisionCheck(BaseModel):
    """Output of the `slide_vision_check` skill."""

    kind: PatternKind
    purpose: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


def compact_slide_json(
    shapes: list[ShapeInfo],
    roles_hint: dict[str, SlotRole],
    groups: list[RepeatGroup],
    slide_w: int,
    slide_h: int,
    max_shapes: int = 60,
) -> list[dict]:
    membership = group_membership(groups)
    rows: list[dict] = []
    area = float(slide_w * slide_h)
    for s in sorted(shapes, key=lambda s: s.z):
        f = s.bbox.to_frac(slide_w, slide_h)
        row: dict = {
            "id": s.id,
            "kind": "pic" if s.kind == ShapeKind.pic else ("frame:" + (s.frame_kind or "other") if s.kind == ShapeKind.graphic_frame else ("line" if s.kind == ShapeKind.connector else "shape")),
            "x": int(round(f.x * 100)),
            "y": int(round(f.y * 100)),
            "w": int(round(f.w * 100)),
            "h": int(round(f.h * 100)),
        }
        if s.has_text:
            row["text"] = s.plain_text.strip().replace("\n", " / ")[:60]
            row["size"] = s.text.dominant_size_pt
            if s.text.bold_share > 0.5:
                row["bold"] = True
            n_par = len([p for p in s.text.paragraphs if p.text.strip()])
            if n_par > 1:
                row["paras"] = n_par
            if s.text.has_bullets:
                row["bullets"] = True
        elif s.kind == ShapeKind.sp and s.fill_hex:
            row["fill"] = s.fill_hex
        if s.id in membership:
            row["group"] = membership[s.id][0]
        if s.is_placeholder and s.ph_type:
            row["ph"] = s.ph_type
        if s.id in roles_hint:
            row["hint"] = roles_hint[s.id].value
        row["_area"] = s.bbox.area / area
        rows.append(row)
    if len(rows) > max_shapes:
        # keep text, pictures, frames and larger shapes; drop tiny decorations first
        rows.sort(key=lambda r: (0 if ("text" in r or r["kind"] != "shape") else 1, -r["_area"]))
        rows = rows[:max_shapes]
        rows.sort(key=lambda r: (r["y"], r["x"]))
    for r in rows:
        r.pop("_area", None)
    return rows


def image_bytes_for_vlm(path: Path, max_w: int = 1024, quality: int = 80) -> bytes:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, int(im.height * max_w / im.width)))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


def classify_slide(
    shapes: list[ShapeInfo],
    groups: list[RepeatGroup],
    chrome_ids: set[str],
    typography: Typography,
    slide_index: int,
    n_slides: int,
    slide_w: int,
    slide_h: int,
    *,
    image_path: Optional[Path] = None,
    image_kinds: Optional[dict[str, str]] = None,
    skills: Optional[SkillsRegistry] = None,
    providers: Optional[ProviderRegistry] = None,
    use_llm: bool = True,
    use_vlm: bool = True,
    template_summary: str = "",
    weights: tuple[float, float, float] = (1.0, 1.5, 1.0),
    role_override_confidence: float = 0.7,
) -> tuple[ClassificationTrace, dict[str, SlotRole], list[str]]:
    """Returns (trace, roles, warnings)."""
    warnings: list[str] = []
    w_h, w_llm, w_vlm = weights
    roles = heuristic_roles(shapes, groups, chrome_ids, typography, slide_w, slide_h, image_kinds=image_kinds)
    h_kind, h_conf = heuristic_kind(shapes, roles, groups, slide_index, n_slides, slide_w, slide_h)
    trace = ClassificationTrace(kind=h_kind, heuristic=SignalVote(kind=h_kind, confidence=h_conf))
    votes: list[tuple[PatternKind, float]] = [(h_kind, h_conf * w_h)]

    can_llm = use_llm and skills is not None and providers is not None and providers.has("llm")
    can_vlm = use_vlm and skills is not None and providers is not None and providers.has("vlm") and image_path is not None and Path(image_path).exists()

    if can_llm:
        try:
            slide_json = compact_slide_json(shapes, roles, groups, slide_w, slide_h)
            res = skills.run(
                "slide_classifier",
                providers,
                {"template_summary": template_summary, "slide_index": slide_index, "n_slides": n_slides, "slide_json": json.dumps(slide_json, ensure_ascii=False)},
            )
            sc: SlideClassification = res.parsed
            trace.llm = SignalVote(kind=sc.kind, confidence=sc.confidence, rationale=sc.rationale)
            votes.append((sc.kind, sc.confidence * w_llm))
            if sc.confidence >= role_override_confidence:
                for sid, role in sc.roles.items():
                    if sid in roles and roles[sid] != SlotRole.chrome and role != SlotRole.chrome:
                        roles[sid] = role
        except (ProviderError, KeyError, ValueError) as e:  # noqa: PERF203
            warnings.append(f"slide {slide_index}: LLM classification failed: {str(e)[:200]}")
            log.warning(warnings[-1])

    if can_vlm:
        try:
            res = skills.run(
                "slide_vision_check",
                providers,
                {"slide_index": slide_index, "n_slides": n_slides, "heuristic_kind": h_kind.value},
                images=[image_bytes_for_vlm(Path(image_path))],
            )
            vc: SlideVisionCheck = res.parsed
            trace.vlm = SignalVote(kind=vc.kind, confidence=vc.confidence, rationale=vc.purpose)
            trace.purpose = vc.purpose
            votes.append((vc.kind, vc.confidence * w_vlm))
        except (ProviderError, KeyError, ValueError) as e:
            warnings.append(f"slide {slide_index}: VLM check failed: {str(e)[:200]}")
            log.warning(warnings[-1])

    tally: dict[PatternKind, float] = defaultdict(float)
    for k, v in votes:
        tally[k] += v
    best = max(tally, key=lambda k: tally[k])
    trace.kind = best
    total = sum(tally.values()) or 1.0
    trace.agreement = round(tally[best] / total, 3)
    return trace, roles, warnings
