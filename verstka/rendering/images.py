"""Picture replacement and insertion with aspect-preserving crop."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lxml import etree
from PIL import Image
from pptx.slide import Slide
from pptx.util import Emu

from verstka.analysis.xmlns import q
from verstka.rendering.deck import element_bbox
from verstka.schemas.common import Bbox


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:  # noqa: BLE001
        return 0, 0


def _crop_rect(frame_w: int, frame_h: int, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """srcRect (l, t, r, b) in 1/100000 that crops the image to the frame's aspect (cover)."""
    if not (frame_w and frame_h and img_w and img_h):
        return 0, 0, 0, 0
    frame_ar = frame_w / frame_h
    img_ar = img_w / img_h
    if img_ar > frame_ar:  # image wider → crop sides
        keep = frame_ar / img_ar
        cut = (1 - keep) / 2
        return int(cut * 100000), 0, int(cut * 100000), 0
    keep = img_ar / frame_ar
    cut = (1 - keep) / 2
    return 0, int(cut * 100000), 0, int(cut * 100000)


def replace_picture(slide: Slide, pic_el: etree._Element, image_path: Path) -> bool:
    blip = pic_el.find(".//" + q("a:blip"))
    if blip is None:
        return False
    image_part, rid = slide.part.get_or_add_image_part(str(image_path))
    blip.set(q("r:embed"), rid)
    ext_lst = blip.find(q("a:extLst"))
    if ext_lst is not None:
        blip.remove(ext_lst)  # drop SVG extension: the new image is raster
    box = element_bbox(pic_el)
    blip_fill = blip.getparent()
    for old in blip_fill.findall(q("a:srcRect")):
        blip_fill.remove(old)
    if box:
        iw, ih = _image_size(image_path)
        l, t, r, b = _crop_rect(box[2], box[3], iw, ih)
        if any((l, t, r, b)):
            src = etree.Element(q("a:srcRect"))
            for k, v in (("l", l), ("t", t), ("r", r), ("b", b)):
                if v:
                    src.set(k, str(v))
            blip_fill.insert(list(blip_fill).index(blip) + 1, src)
    return True


def insert_picture(slide: Slide, bbox: Bbox, image_path: Path, name: Optional[str] = None):
    iw, ih = _image_size(image_path)
    pic = slide.shapes.add_picture(str(image_path), Emu(bbox.x), Emu(bbox.y), Emu(bbox.w), Emu(bbox.h))
    l, t, r, b = _crop_rect(bbox.w, bbox.h, iw, ih)
    pic.crop_left = l / 100000
    pic.crop_right = r / 100000
    pic.crop_top = t / 100000
    pic.crop_bottom = b / 100000
    if name:
        pic.name = name
    return pic
