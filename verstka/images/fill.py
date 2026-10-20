"""The pictures of one variant: its free places found after the render (`plan_pictures`: each place described by its
author is asked of the generation's ImageMaker at once, so the pictures are made while the other variants render), then
put in (`apply_pictures`: each picture cropped to its place's proportions, the caption gone) — and the record of every
place in images.json: what it is for, what was asked, by which model, why a place stayed free."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from verstka.images import palette as P
from verstka.images.places import Place, places_in, put_picture
from verstka.images.prompt import ImageAsk, load_config
from verstka.images.providers import nearest_aspect
from verstka.ingest.deck_text import is_source_hint

log = logging.getLogger(__name__)

RECORD_FILE = "images.json"
# what the person reads about a place left free
WHY_OWN = "место под ваше фото — вставьте его в PowerPoint"
WHY_OFF = "генерация изображений выключена"
WHY_REMOVED = "изображение убрано — место оставлено под ваше фото"
WHY_SOURCE = "изображения из исходной презентации нет — место оставлено под ваше фото"


@dataclass
class Pending:
    place: Place
    ask: Optional[ImageAsk]
    aspect: str
    future: Optional[Future]
    why: Optional[str] = None  # why the place is left free (own photo, generation off)
    wish: Optional[str] = None  # the person's wish the picture was made for (kept over a new render)
    frame: Any = None  # the picture's frame on the slide (rendering/picture_layouts.py), None: the place as drawn


@dataclass
class Applied:
    changed: list[int] = field(default_factory=list)  # slides that got a picture
    records: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ask_of(place: Place, deck_title: str, wish: Optional[str] = None, frame: str = "") -> ImageAsk:
    return ImageAsk(hint=place.hint or "", headline=place.headline, deck=deck_title, label=place.label, wish=wish, frame=frame)


def frames_for(prs, places: list[Place], cfg: Optional[dict] = None) -> dict:
    """The frame of each place's picture ({(slide, shape id): Frame}): a bleed, a circle, a background…
    (rendering/picture_layouts.py); none — the place as drawn — when configs/images.yaml `layouts` is off."""
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("layouts", True) or not places:
        return {}
    from verstka.rendering.picture_layouts import frames_of

    try:
        return frames_of(prs, places)
    except Exception:  # noqa: BLE001 - the pictures stand in their places as drawn
        log.warning("picture frames not planned", exc_info=True)
        return {}


# a tall frame's picture is asked one step squarer and cropped to the frame around what it shows: asked at 3:4 for a
# strip, the image model drew a small scene at the bottom under an empty sky or a blank panel (live runs of 20.10);
# asked square, its subject stands large in the middle (configs/images.yaml `squarer_tall`)
_SQUARER = {"3:4": "1:1", "9:16": "3:4"}


def _aspect_of(place: Place, frame, cfg: Optional[dict] = None) -> str:
    box = frame.box if frame is not None else place.box
    aspect = nearest_aspect(box[2], box[3])
    cfg = cfg if cfg is not None else load_config()
    if cfg.get("squarer_tall", True) and frame is not None and frame.composition == "tall":
        return _SQUARER.get(aspect, aspect)
    return aspect


def descr_of(record: dict) -> str:
    """The picture's alternative text: what it shows and that a model made it."""
    what = record.get("wish") or record.get("hint") or record.get("label") or record.get("headline") or "иллюстрация"
    if record.get("model") == "original":
        # (the hint of a place read back from the deck already says where it comes from)
        return what if "исходной презентации" in what else f"{what} — изображение из исходной презентации"
    return f"{what} — изображение сгенерировано моделью {record.get('model_label') or record.get('model') or 'text-to-image'}"


def made_from_record(rec: dict, folder: Optional[Path]):
    """The picture a record names, as made (its file in the generation's images folder), or None when it is gone."""
    from verstka.images.service import Made

    if folder is None or rec.get("status") != "generated" or not rec.get("file"):
        return None
    path = Path(folder) / str(rec["file"])
    if not path.is_file():
        return None
    return Made(
        key=str(rec.get("key") or ""), aspect=str(rec.get("aspect") or "4:3"), path=str(path), prompt=str(rec.get("prompt") or ""),
        style=str(rec.get("style") or ""), subject_by=str(rec.get("subject_by") or "author"), model=str(rec.get("model") or ""),
        model_label=str(rec.get("model_label") or rec.get("model") or ""), seed=int(rec.get("seed") or 0),
        palette_match=float(rec.get("palette_match") or 0.0), seconds=0.0,
        cost_rub=float(rec["cost_rub"]) if rec.get("cost_rub") is not None else None,  # paid once, kept through edits
        fits=int(rec["fits"]) if isinstance(rec.get("fits"), (int, float)) else None,
    )


def _done(value) -> Future:
    f: Future = Future()
    f.set_result(value)
    return f


def _match(place: Place, records: list[dict]) -> Optional[dict]:
    """The record of the same place before a new render: the same slide of the plan (its id), else the same
    description, else the same slide number."""
    for test in (
        lambda r: place.outline_id and r.get("outline_id") == place.outline_id and (r.get("hint") or "") == (place.hint or ""),
        lambda r: place.outline_id and r.get("outline_id") == place.outline_id,
        lambda r: (place.hint or "") and (r.get("hint") or "") == place.hint,
    ):
        hit = next((r for r in records if test(r)), None)
        if hit is not None:
            return hit
    return None


def plan_pictures(deck: Path, outline, maker, *, enabled: bool = True, reuse: Optional[list[dict]] = None, folder: Optional[Path] = None,
                  slides: Optional[set[int]] = None) -> list[Pending]:
    """Every free place of the deck (of `slides` only, when given): a picture asked for each place its author described
    (when `enabled` and there is a maker), the others left free with the reason. `reuse` — the variant's records before
    a new render (an edit, a slide fix): a place keeps the picture it had (no new call) or stays empty when the person
    took its picture out."""
    from pptx import Presentation

    prs = Presentation(str(deck))
    out: list[Pending] = []
    title = getattr(outline, "title", "") or ""
    places = [pl for pl in places_in(prs, outline) if slides is None or pl.slide in slides]
    frames = frames_for(prs, places, getattr(maker, "cfg", None))
    for place in places:
        # the picture is asked in its frame's proportions and composition (a bleed half of the slide: a tall picture)
        frame = frames.get((place.slide, place.shape_id))
        aspect = _aspect_of(place, frame, getattr(maker, "cfg", None))
        comp = frame.composition if frame is not None else ""
        old = _match(place, reuse or [])
        if old is not None and old.get("status") == "removed":
            out.append(Pending(place, None, aspect, None, why=old.get("why") or WHY_REMOVED, wish=old.get("wish"), frame=frame))
            continue
        made = made_from_record(old, folder) if old is not None else None
        if made is not None:
            out.append(Pending(place, ask_of(place, title, old.get("wish"), comp), made.aspect, _done(made), wish=old.get("wish"), frame=frame))
            continue
        if is_source_hint(place.hint):
            # the place of a picture of an improved deck: its own picture or none — a model never draws «Изображение со
            # слайда 3 исходной презентации» (the deck's pictures are not here: another deck, the improve lost on reload)
            out.append(Pending(place, None, aspect, None, why=WHY_SOURCE, frame=frame))
            continue
        if place.own:
            out.append(Pending(place, None, aspect, None, why=WHY_OWN, frame=frame))
            continue
        if not enabled or maker is None:
            out.append(Pending(place, None, aspect, None, why=WHY_OFF, frame=frame))
            continue
        ask = ask_of(place, title, frame=comp)
        out.append(Pending(place, ask, aspect, maker.submit(ask, aspect), frame=frame))
    return out


def _base_record(p: Pending) -> dict:
    pl = p.place
    return {
        "id": f"s{pl.slide}-{pl.shape_id}", "slide": pl.slide, "shape_id": pl.shape_id, "outline_id": pl.outline_id,
        "headline": pl.headline, "label": pl.label, "hint": pl.hint, "own": pl.own, "box": list(pl.box), "aspect": p.aspect,
        "status": "removed" if p.why == WHY_REMOVED else "free", "why": p.why, "wish": p.wish, "key": p.ask.key() if p.ask is not None else None,
        "at": time.time(),
    }


def made_fields(made) -> dict:
    return {
        "key": made.key, "prompt": made.prompt, "style": made.style, "subject_by": made.subject_by, "model": made.model, "model_label": made.model_label,
        "seed": made.seed, "palette_match": made.palette_match, "seconds": made.seconds, "cost_rub": made.cost_rub, "file": Path(made.path).name,
        "fits": getattr(made, "fits", None), "attempts": getattr(made, "attempts", 1),
    }


def fitted(made_path: str, box, cfg: Optional[dict] = None, *, trim: bool = False) -> bytes:
    """The made picture cropped to `box`'s proportions around what it shows (past an empty sky or wall at its top or
    bottom when `trim`), scaled down, as JPEG."""
    cfg = cfg or {}
    img = P.open_image(Path(made_path).read_bytes())
    return P.encode(P.fit_to(img, box[2], box[3], int(cfg.get("max_side_px", 1600)), trim=trim), int(cfg.get("jpeg_quality", 88)))


def apply_pictures(deck: Path, pending: list[Pending], *, wait_s: float = 75.0, cfg: Optional[dict] = None) -> Applied:
    """The made pictures put in their places (waiting at most `wait_s` in all for those still being made); a record for
    every place (the caller writes them: write_records), the deck saved when a picture went in."""
    from pptx import Presentation

    out = Applied()
    if not pending:
        return out
    prs = Presentation(str(deck))
    slides = list(prs.slides)
    # the frames read again on the deck the pictures go into (the same deck as planned: the same frames)
    frames = frames_for(prs, [p.place for p in pending], cfg if cfg and "layouts" in cfg else None)
    end = time.monotonic() + max(0.0, wait_s)
    for p in pending:
        frame = frames.get((p.place.slide, p.place.shape_id), p.frame) if frames else p.frame
        rec = _base_record(p)
        if p.future is not None:
            try:
                made = p.future.result(timeout=max(0.0, end - time.monotonic()))
            except FutureTimeout:
                rec["why"] = "изображение не успело сгенерироваться"
                out.warnings.append(f"slide {p.place.slide}: the picture was not ready in time, the place stays free")
                made = None
            except Exception as e:  # noqa: BLE001 - the place stays free, the reason is kept
                rec["why"] = getattr(e, "why", None) or "модель изображений не ответила"
                rec["error"] = str(e)[:300]
                out.warnings.append(f"slide {p.place.slide}: no picture ({str(e)[:160]})")
                made = None
            if made is not None:
                rec.update(made_fields(made))
                try:
                    # (a background keeps its calm areas: the text stands on them)
                    trim = bool((cfg or load_config()).get("trim_empty", True)) and (frame is None or frame.kind != "background")
                    data = fitted(made.path, frame.box if frame is not None else p.place.box, cfg, trim=trim)
                    kept = put_picture(slides[p.place.slide - 1], p.place, data, descr=descr_of(rec), frame=frame)
                except Exception as e:  # noqa: BLE001
                    kept = None
                    rec["error"] = str(e)[:300]
                if kept is not None:
                    rec.update({"status": "generated", "why": None, "kept": kept})
                    if frame is not None:
                        # the picture's box is its frame's (a new picture on «Заменить» is cropped to it)
                        rec.update({"box": list(frame.box), "place_box": list(p.place.box), "frame": frame.public(), "composition": frame.composition})
                    out.changed.append(p.place.slide)
                else:
                    rec["why"] = rec.get("why") or "изображение не встало на место"
        out.records.append(rec)
    if out.changed:
        prs.save(str(deck))
    return out


def merged(old: list[dict], new: list[dict], slides: set[int]) -> list[dict]:
    """The records of `slides` replaced by `new`, the others kept, in slide order."""
    return sorted([r for r in old if r.get("slide") not in slides] + list(new), key=lambda r: (int(r.get("slide") or 0), str(r.get("shape_id") or "")))


def write_records(vdir: Path, records: list[dict]) -> None:
    path = Path(vdir) / RECORD_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"pictures": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_records(vdir: Path) -> list[dict]:
    try:
        data = json.loads((Path(vdir) / RECORD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pics = data.get("pictures") if isinstance(data, dict) else None
    return [r for r in pics if isinstance(r, dict)] if isinstance(pics, list) else []


def public_records(records: list[dict]) -> list[dict]:
    """The records for the interface: no kept XML, no paths."""
    keep = ("id", "slide", "shape_id", "headline", "label", "hint", "own", "status", "why", "wish", "prompt", "style", "subject_by",
            "model", "model_label", "palette_match", "fits", "aspect", "frame", "at")
    return [{k: r.get(k) for k in keep if k in r} for r in records]


def _paid(made: list[dict]) -> Optional[float]:
    """What the pictures cost in rubles, each file once (the variants share them); None when no picture said."""
    costs = [float(r["cost_rub"]) for r in {r.get("file"): r for r in made}.values() if r.get("cost_rub") is not None]
    return round(sum(costs), 2) if costs else None


def summary(records: list[dict]) -> dict[str, Any]:
    made = [r for r in records if r.get("status") == "generated"]
    return {
        "places": len(records), "generated": len(made), "own": sum(1 for r in records if r.get("own")),
        "models": sorted({r.get("model_label") or r.get("model") for r in made if r.get("model")}),
        "palette_match": round(sum(float(r.get("palette_match") or 0) for r in made) / len(made), 3) if made else None,
        # the pictures of this variant (the variants share them: the same place, the same picture, paid once)
        "cost_rub": _paid(made),
    }
