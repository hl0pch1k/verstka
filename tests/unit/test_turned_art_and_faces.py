"""Owner's remarks of 18.10 (item 10, a third-party template): what lies under the letters, turned art, the faces the
headings are measured in.

* a shape turned 90° (a side bar written across the slide) covers its turned box, not the middle of the slide;
* a turned picture is read where its pixels really stand: its transparent part is no ground;
* LibreOffice draws a transparent picture under PowerPoint's «grayscale» with black where it is transparent — the
  render copy bakes the grey in and keeps the transparency;
* «Arial Black» is not Arial: measured as Arial, tracked capitals ran a fifth wider than measured;
* a heading stops before a picture placeholder that inherits its box from the layout.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.util import Emu

from verstka.schemas.common import Bbox

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
W, H = 12192000, 6858000


def _blank():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    return prs, prs.slides.add_slide(prs.slide_layouts[6])


def _rotate(shape, deg: float) -> None:
    xfrm = shape._element.find(f"{{{P}}}spPr/{{{A}}}xfrm")
    xfrm.set("rot", str(int(deg * 60000)))


def _png(w: int, h: int, transparent_left: bool = True) -> bytes:
    """A picture whose left half is transparent (black RGB under alpha 0, as the owner's building shot) and right half
    is a light opaque grey."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for x in range(w // 2, w):
        for y in range(h):
            im.putpixel((x, y), (220, 220, 220, 255))
    if not transparent_left:
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_a_bar_turned_90_degrees_covers_the_slide_edge_not_its_middle():
    from verstka.rendering.layers import drawn_layers

    prs, slide = _blank()
    # written 9 in wide across the middle, turned 90°: it stands down the right edge of the slide (the owner's template)
    bar = slide.shapes.add_shape(1, Emu(8570975), Emu(3236976), Emu(6858000), Emu(384048))
    bar.fill.solid()
    _rotate(bar, 90)
    lay = next(la for la in drawn_layers(slide) if la.el is bar._element)
    assert lay.box.y <= 0.01 * H and lay.box.y2 >= 0.99 * H, "a turned bar runs the slide's height"
    assert lay.box.x >= 0.96 * W and lay.box.w <= 0.04 * W, "and stands at its right edge"


def test_a_turned_picture_is_read_where_its_pixels_stand(tmp_path):
    from verstka.rendering.layers import drawn_layers, layer_paint_at, painted_share

    prs, slide = _blank()
    p = tmp_path / "half.png"
    p.write_bytes(_png(200, 100))
    pic = slide.shapes.add_picture(str(p), Emu(int(0.25 * W)), Emu(int(0.25 * H)), Emu(int(0.5 * W)), Emu(int(0.5 * H)))
    _rotate(pic, 180)  # turned over: the opaque half now stands on the left, the transparent half on the right
    lay = next(la for la in drawn_layers(slide) if la.el is pic._element)
    left = Bbox(x=int(0.27 * W), y=int(0.4 * H), w=int(0.2 * W), h=int(0.1 * H))
    right = Bbox(x=int(0.53 * W), y=int(0.4 * H), w=int(0.2 * W), h=int(0.1 * H))
    got_l = layer_paint_at(lay, left, slide)
    got_r = layer_paint_at(lay, right, slide)
    assert got_l is not None and got_l[1] > 0.9 and got_l[0] == "DCDCDC"
    assert got_r is None or got_r[1] < 0.1, "the transparent half is no ground for the letters over it"
    assert painted_share(lay, right) < 0.1 < 0.9 < painted_share(lay, left)
    assert 0.1 < lay.cover < 0.15, "it covers what its opaque pixels cover (an eighth of the slide), not its frame"


def test_the_render_copy_bakes_grayscale_into_a_transparent_picture(tmp_path):
    from verstka.ingest.render import render_copy

    prs, slide = _blank()
    p = tmp_path / "half.png"
    p.write_bytes(_png(40, 20))
    pic = slide.shapes.add_picture(str(p), Emu(0), Emu(0), Emu(W // 2), Emu(H // 2))
    blip = pic._element.find(f".//{{{A}}}blip")
    etree.SubElement(blip, f"{{{A}}}grayscl")
    src = tmp_path / "deck.pptx"
    prs.save(str(src))
    out = render_copy(src, tmp_path / "lo")
    with zipfile.ZipFile(out) as z:
        slide_xml = z.read("ppt/slides/slide1.xml")
        assert b"grayscl" not in slide_xml, "the effect LibreOffice draws black is dropped"
        rels = etree.fromstring(z.read("ppt/slides/_rels/slide1.xml.rels"))
        rid = etree.fromstring(slide_xml).find(f".//{{{A}}}blip").get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        im = Image.open(io.BytesIO(z.read(target.lstrip("/"))))
        assert im.mode == "LA", "grey pixels, the transparency kept"
        assert im.getpixel((0, 0))[1] == 0 and im.getpixel((39, 0))[1] == 255
    # the deck handed to the user keeps its effect
    with zipfile.ZipFile(src) as z:
        assert b"grayscl" in z.read("ppt/slides/slide1.xml")


def test_an_opaque_grey_picture_is_left_to_libreoffice(tmp_path):
    from verstka.ingest.render import render_copy

    prs, slide = _blank()
    p = tmp_path / "opaque.png"
    p.write_bytes(_png(40, 20, transparent_left=False))
    pic = slide.shapes.add_picture(str(p), Emu(0), Emu(0), Emu(W // 2), Emu(H // 2))
    etree.SubElement(pic._element.find(f".//{{{A}}}blip"), f"{{{A}}}grayscl")
    src = tmp_path / "deck.pptx"
    prs.save(str(src))
    with zipfile.ZipFile(render_copy(src, tmp_path / "lo")) as z:
        assert b"grayscl" in z.read("ppt/slides/slide1.xml")


def test_wider_and_narrower_cuts_are_not_their_family():
    from verstka.rendering.fonts import is_pinned, width_factor

    assert is_pinned("Arial") and is_pinned("Arial Bold") and is_pinned("Calibri Light")
    for fam in ("Arial Black", "Arial Narrow", "Arial Rounded MT Bold", "Roboto Condensed", "Montserrat Black", "PT Sans Narrow"):
        assert not is_pinned(fam), fam
    assert width_factor("Arial Black") != width_factor("Arial")


def test_arial_black_is_measured_with_its_own_file_when_installed():
    from verstka.rendering.fonts import _face, text_width_pt

    face = _face("Arial Black", False)
    if not face or not face[2]:
        pytest.skip("Arial Black is not installed")
    black = text_width_pt("БЛОКИРУЮЩИМИ", "Arial Black", 36, False)
    plain = text_width_pt("БЛОКИРУЮЩИМИ", "Arial", 36, True)
    assert black > 1.1 * plain, "Arial Black sets its letters wider than Arial Bold"


def test_a_heading_stops_before_an_inherited_picture_placeholder():
    from verstka.rendering.synth import _drawn_box, _free_width

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    layout = next(lo for lo in prs.slide_layouts if any("PICTURE" in str(ph.placeholder_format.type) for ph in lo.placeholders))
    lph = next(ph for ph in layout.placeholders if "PICTURE" in str(ph.placeholder_format.type))
    # the layout keeps its picture at the right, as the owner's template does (slide 13: a photo beside the text)
    lph.left, lph.top, lph.width, lph.height = Emu(int(0.645 * W)), Emu(int(0.16 * H)), Emu(int(0.285 * W)), Emu(int(0.73 * H))
    slide = prs.slides.add_slide(layout)
    pic_ph = next(ph for ph in slide.placeholders if "PICTURE" in str(ph.placeholder_format.type))
    el = pic_ph._element
    assert el.find(f"{{{P}}}spPr/{{{A}}}xfrm") is None, "the slide's placeholder writes no box of its own"
    b = _drawn_box(slide, el)
    assert b is not None and abs(b[0] - int(0.645 * W)) <= 1
    box = Bbox(x=int(0.07 * W), y=int(0.13 * H), w=int(0.47 * W), h=int(0.14 * H))
    assert box.x + _free_width(slide, box, W, H, int(0.95 * W)) <= b[0], "the heading stops before the photo"


def test_a_painted_layout_placeholder_paints_only_where_a_slide_uses_it(tmp_path):
    """LibreOffice draws a layout's painted placeholder on every slide of the layout; PowerPoint only where the slide
    has its own shape for it. The render copy follows PowerPoint: the layout stops painting it, a slide that uses it
    gets the paint on its own shape."""
    from verstka.ingest.render import _plate_fill, render_copy

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    layout = prs.slide_layouts[1]  # title and content: its body placeholder (idx 1) gets a blue fill
    body = next(ph for ph in layout.placeholders if ph.placeholder_format.idx == 1)
    body.fill.solid()
    body.fill.fore_color.rgb = __import__("pptx.dml.color", fromlist=["RGBColor"]).RGBColor(0x4A, 0x5E, 0xE6)
    used = prs.slides.add_slide(layout)  # keeps its body placeholder
    unused = prs.slides.add_slide(layout)
    for ph in list(unused.placeholders):
        if ph.placeholder_format.idx == 1:
            ph._element.getparent().remove(ph._element)  # the composed slide dropped the empty placeholder
    src = tmp_path / "deck.pptx"
    prs.save(str(src))
    with zipfile.ZipFile(render_copy(src, tmp_path / "lo")) as z:
        layouts = [n for n in z.namelist() if n.startswith("ppt/slideLayouts/slideLayout") and n.endswith(".xml")]
        assert not any(b"4A5EE6" in z.read(n) for n in layouts), "the layout's placeholder paints nowhere by itself"
        s1 = etree.fromstring(z.read("ppt/slides/slide1.xml"))
        s1_body = next(sp for sp in s1.iter(f"{{{P}}}sp") if sp.find(f".//{{{P}}}ph") is not None and sp.find(f".//{{{P}}}ph").get("idx") == "1")
        assert _plate_fill(s1_body), "the slide that uses it paints it on its own shape"
        s2 = z.read("ppt/slides/slide2.xml")
        assert b"4A5EE6" not in s2
    with zipfile.ZipFile(src) as z:  # the user's deck is untouched
        assert any(b"4A5EE6" in z.read(n) for n in z.namelist() if n.startswith("ppt/slideLayouts/") and n.endswith(".xml"))
