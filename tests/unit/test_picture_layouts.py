"""A generated picture takes a form of the slide, not a box in it (the owner, 18.10, п. 9: «картинки всегда
прямоугольник, не подходят ни по месту, ни по форме»): a side column bleeds to the slide's edge, a deck of circles gets
a round picture, a deck of rounded cards a rounded one, a place over most of the slide is its background with an
underlay under the text; the picture is cropped to its frame by what it shows; it is asked in its frame's composition
and only where the slide has room for it."""

from __future__ import annotations

import io

import numpy as np
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from verstka.analysis.xmlns import q
from verstka.images import palette as P
from verstka.images.places import CAPTION_PREFIX, places_in, put_picture, take_picture_out
from verstka.images.prompt import ImageAsk, build_prompt, template_style
from verstka.rendering import picture_layouts as PL
from verstka.schemas.outline import PHOTO_PLACE_NAME, DeckOutline, OutlineSlide, SlideContent

W, H = Inches(13.333), Inches(7.5)


def _deck(place=(7.2, 1.6, 5.4, 5.0), title_w=6.0, extra=None, circles=0, rounded=0, geom=MSO_SHAPE.RECTANGLE, number=False):
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    s = prs.slides.add_slide(prs.slide_layouts[6])
    t = s.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(title_w), Inches(1))
    t.text_frame.text = "Головной офис"
    s.shapes.add_textbox(Inches(0.6), Inches(1.8), Inches(5.8), Inches(3)).text_frame.text = "Короткий текст рядом с картинкой."
    if number:
        n = s.shapes.add_textbox(Inches(12.6), Inches(7.0), Inches(0.5), Inches(0.4))
        n.text_frame.text = "6"
    x, y, w, h = place
    frame = s.shapes.add_shape(geom, Inches(x), Inches(y), Inches(w), Inches(h))
    frame.name = PHOTO_PLACE_NAME
    cap = s.shapes.add_textbox(Inches(x + 0.3), Inches(y + 1), Inches(w - 0.6), Inches(1))
    cap.text_frame.text = "Место под изображение"
    cap.name = f"{CAPTION_PREFIX} {cap.shape_id}"
    for k in range(circles):
        s2 = prs.slides.add_slide(prs.slide_layouts[6])
        s2.shapes.add_shape(MSO_SHAPE.OVAL, Inches(1 + k), Inches(1), Inches(3), Inches(3))
    for k in range(rounded):
        s2 = prs.slides.add_slide(prs.slide_layouts[6])
        s2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1), Inches(1 + k * 0.1), Inches(4), Inches(2))
    if extra:
        extra(s)
    return prs, s


def _frame(prs, s):
    pl = places_in(prs, None)[0]
    return pl, PL.frames_of(prs, [pl])[(1, pl.shape_id)]


def _jpeg(w=1200, h=900) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (90, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_a_side_column_bleeds_to_the_edge_and_bottom_but_never_over_the_title():
    prs, s = _deck(title_w=12.0)  # a title spanning the slide: the picture starts under it
    pl, fr = _frame(prs, s)
    assert fr.kind == "bleed" and fr.edges == ("right", "bottom")
    assert fr.box[0] == pl.box[0] and fr.box[0] + fr.box[2] == W and fr.box[1] == pl.box[1] and fr.box[1] + fr.box[3] == H
    # a short title leaves the column free up to the top: the picture is the right half of the slide
    prs, s = _deck(title_w=5.0)
    pl, fr = _frame(prs, s)
    assert fr.kind == "bleed" and set(fr.edges) == {"right", "top", "bottom"} and fr.box[1] == 0 and fr.composition == "tall"


def test_the_title_box_counts_by_its_words_not_its_width():
    def sized(s):
        t = s.shapes[0]
        t.width = Inches(12.4)
        for r in t.text_frame.paragraphs[0].runs:
            r.font.size = Pt(28)
    prs, s = _deck(title_w=6.0, extra=sized)
    _, fr = _frame(prs, s)
    assert "top" in fr.edges  # «Головной офис» at 28 pt ends far left of the picture's column


def test_no_bleed_over_text_or_a_logo_between_the_place_and_the_edge():
    def logo(s):
        s.shapes.add_picture(io.BytesIO(_jpeg(200, 200)), Inches(12.85), Inches(3), Inches(0.4), Inches(0.4))
    prs, s = _deck(place=(6.6, 1.6, 5.4, 5.0), extra=logo)
    _, fr = _frame(prs, s)
    assert fr.kind == "plain" and fr.box == places_in(prs, None)[0].box


def test_a_page_number_the_bleed_covers_is_put_over_the_picture():
    prs, s = _deck(number=True)
    pl, fr = _frame(prs, s)
    assert fr.kind == "bleed" and fr.raise_ids
    put_picture(s, pl, _jpeg(), descr="x", frame=fr)
    tree = s._element.cSld.find(q("p:spTree"))
    ids = [PL._id(e) for e in tree]
    assert ids.index(fr.raise_ids[0]) > ids.index(pl.shape_id)


def test_a_deck_of_circles_gets_a_round_picture_and_rounded_cards_a_rounded_one():
    prs, s = _deck(place=(4, 1.5, 5, 4.5), circles=3)  # a place in the middle of the slide: no bleed
    pl, fr = _frame(prs, s)
    assert fr.kind == "circle" and fr.geom == "ellipse" and fr.box[2] == fr.box[3] == min(pl.box[2], pl.box[3])
    assert fr.composition == "circle"
    prs, s = _deck(place=(4, 1.5, 5, 4.5), rounded=4)
    _, fr = _frame(prs, s)
    assert fr.kind == "rounded" and fr.geom == "roundRect" and 0 < fr.adj <= 50000
    put_picture(s, places_in(prs, None)[0], _jpeg(), descr="x", frame=fr)
    pic = next(e for e in s._element.cSld.find(q("p:spTree")) if etree.QName(e).localname == "pic")
    g = pic.find(".//" + q("a:prstGeom"))
    assert g.get("prst") == "roundRect" and g.find(q("a:avLst") + "/" + q("a:gd")) is not None


def test_a_form_the_template_drew_stays():
    prs, s = _deck(place=(4, 1.5, 5, 4.5), geom=MSO_SHAPE.HEXAGON, circles=3)
    _, fr = _frame(prs, s)
    assert fr.kind == "template" and fr.geom is None


def test_a_place_over_most_of_the_slide_is_its_background_with_an_underlay_under_the_text():
    prs, s = _deck(place=(0.3, 0.3, 12.7, 6.9))
    pl, fr = _frame(prs, s)
    assert fr.kind == "background" and fr.box == (0, 0, W, H) and fr.to_back and fr.scrim is not None
    assert fr.scrim_color == "FFFFFF"  # the slide's ground, not the free place's fill
    kept = put_picture(s, pl, _jpeg(), descr="x", frame=fr)
    tree = s._element.cSld.find(q("p:spTree"))
    kids = [e for e in tree if etree.QName(e).localname in ("sp", "pic")]
    assert etree.QName(kids[0]).localname == "pic" and PL._name(kids[1]) == "Подложка под текст"
    alpha = kids[1].find(".//" + q("a:alpha"))
    assert alpha is not None and 50000 <= int(alpha.get("val")) < 100000
    # «Убрать изображение»: the place comes back, the underlay goes
    assert take_picture_out(s, pl.shape_id, kept)
    assert not any(PL._name(e) == "Подложка под текст" for e in tree)
    assert any(PL._name(e) == PHOTO_PLACE_NAME for e in tree)


def test_a_sample_photo_the_place_already_covers_does_not_stop_the_bleed():
    def under(s):
        pic = s.shapes.add_picture(io.BytesIO(_jpeg()), Inches(7.2), Inches(1.6), Inches(5.4), Inches(5.0))
        tree = s._element.cSld.find(q("p:spTree"))
        tree.remove(pic._element)
        tree.insert(2, pic._element)  # under the place
    prs, s = _deck(extra=under)
    _, fr = _frame(prs, s)
    assert fr.kind == "bleed"


def test_the_crop_keeps_the_subject_not_the_middle():
    img = Image.new("RGB", (1600, 800), (200, 205, 210))
    px = np.asarray(img).copy()
    px[300:600, 100:400] = (20, 40, 160)  # the subject at the left
    img = Image.fromarray(px)
    l, t, r, b = P.focus_crop(img, 1.0)
    assert (r - l) == 800 and l <= 100 and r >= 400
    out = P.fit_to(img, 1, 1, focus=True)
    a = np.asarray(out)
    assert (a[..., 2] > 140).mean() > 0.05  # the blue subject is in the crop
    assert P.fit_to(img, 1, 1, focus=False).size == (800, 800)


def test_the_picture_is_asked_in_its_frames_composition_and_the_templates_style():
    pal = P.Palette(dark="0B1F44", light="F4F6FA", accents=["FF6A00"])
    tall, _ = build_prompt(ImageAsk(hint="Стеклянный фасад офиса", frame="tall"), pal)
    assert "Vertical portrait composition" in tall
    circle, _ = build_prompt(ImageAsk(hint="Стеклянный фасад офиса", frame="circle"), pal)
    assert "circular crop" in circle
    plain, _ = build_prompt(ImageAsk(hint="Стеклянный фасад офиса"), pal)
    assert "composition" not in plain.lower() or "uncluttered composition" in plain
    # the author's words leave the style open: the template's own pictures set it
    _, style = build_prompt(ImageAsk(hint="Процесс обучения", template_style="illustration"), pal)
    assert style == "illustration"
    _, style = build_prompt(ImageAsk(hint="Фото команды", template_style="illustration"), pal)
    assert style == "photo"

    class A:
        def __init__(self, kind):
            self.kind, self.width, self.height = kind, 1000, 800

    class M:
        assets = [A("illustration")] * 10 + [A("photo")]

    assert template_style(M()) == "illustration"
    M.assets = [A("photo")] * 3 + [A("illustration")] * 4
    assert template_style(M()) == "photo"
    M.assets = []
    assert template_style(M()) == ""


def test_a_picture_only_beside_a_short_text():
    from verstka.planning.pictures import room_for_picture

    assert room_for_picture("Короткий лид.", ["раз", "два", "три"])
    assert not room_for_picture("Лид.", ["1", "2", "3", "4", "5"])
    assert not room_for_picture("Лид.", ["пункт"], ["1 — a", "2 — b", "3 — c"])
    assert not room_for_picture("Лид.", other=True)
    assert not room_for_picture("x" * 500)


def test_the_writers_note_keeps_its_description():
    """The writer's note glued to a list was read as the list's line: the place «Фото» lost what it shows and the
    picture was drawn from the headline (the owner's run of 17.10: a glass trophy)."""
    from verstka.planning.brief_structure import read_structure
    from verstka.planning.faithful import read_parts
    from verstka.planning.topic_writer import TopicSlide, render_slide

    lines = render_slide(6, TopicSlide(title="Бренд", lead="Самый узнаваемый бренд.", points=["Первое место."], picture="Стеклянный фасад офиса банка"), "Бренд")
    text = "Слайд 1. Титульный\nНазвание: «Банк».\n" + "\n".join(lines) + "\n"
    spec = next(sp for sp in read_structure(text).specs if sp.photo)
    img = [p for p in read_parts(spec.text) if p.kind == "image"]
    assert img and img[0].text.startswith("Стеклянный фасад")


def test_a_rendered_place_gets_its_frame_through_plan_and_apply(tmp_path):
    from verstka.images import providers as IP
    from verstka.images.fill import apply_pictures, plan_pictures
    from verstka.images.service import ImageMaker

    prs, s = _deck(title_w=5.0)
    path = tmp_path / "deck.pptx"
    prs.save(str(path))
    outline = DeckOutline(title="Банк", slides=[OutlineSlide(id="a", kind="image_text", headline="Головной офис",
                                                             content=SlideContent(bullets=["x"], photo_slot="Изображение", photo_hint="Стеклянный фасад офиса"))])
    mock = IP.MockImages()
    maker = ImageMaker(IP.ImageChain([mock]), None, tmp_path / "cache", deck_title="Банк")
    pend = plan_pictures(path, outline, maker)
    assert pend[0].frame.kind == "bleed" and pend[0].aspect == "3:4" and "Vertical portrait" in mock_prompt(pend)
    res = apply_pictures(path, pend, wait_s=10)
    maker.close()
    rec = res.records[0]
    assert rec["status"] == "generated" and rec["frame"]["kind"] == "bleed" and rec["box"] == list(pend[0].frame.box)


def mock_prompt(pend) -> str:
    return pend[0].future.result(timeout=10).prompt


def test_a_note_the_designer_copied_into_the_slide_leaves_its_text():
    from verstka.planning.pictures import strip_picture_notes

    o = DeckOutline(title="Банк", slides=[OutlineSlide(id="s8", kind="bullets", headline="Головной офис", content=SlideContent(
        bullets=["Офис на улице Вавилова", "[Место под изображение: стеклянный фасад офиса]"], photo_slot="Фото", photo_hint="Стеклянный фасад офиса"))])
    warns: list = []
    strip_picture_notes(o, warns)
    assert o.slides[0].content.bullets == ["Офис на улице Вавилова"] and o.slides[0].content.photo_hint and warns


def test_a_content_slides_picture_is_a_full_height_strip_away_from_the_layouts_logo():
    """The owner (18.10, after 88ef1e9): «картинка — от самого верха до самого низа, а с другой стороны текст». The
    strip takes ~44 % of the slide at the right edge — the left one for the compact variant — unless the layout draws
    a logo there; the text's columns stay beside it."""
    prs, s = _deck()
    sw = int(PL.STRIP_SHARE * W)
    assert PL.picture_strip(s, W, H) == (W - sw, 0, sw, H)
    assert PL.picture_strip(s, W, H, left=True) == (0, 0, sw, H)
    # a logo the layout draws at the bottom left: the compact variant's strip goes right
    tmp = s.shapes.add_picture(io.BytesIO(_jpeg(200, 200)), Inches(0.4), Inches(6.8), Inches(1), Inches(0.4))
    el = tmp._element
    el.getparent().remove(el)
    s.slide_layout._element.cSld.find(q("p:spTree")).append(el)
    assert PL.picture_strip(s, W, H, left=True) == (W - sw, 0, sw, H)
    x, w = PL.beside_strip((W - sw, 0, sw, H), Inches(0.5), W - Inches(1), W)
    assert x == Inches(0.5) and x + w <= W - sw - int(0.03 * W)
    x, w = PL.beside_strip((0, 0, sw, H), Inches(0.5), W - Inches(1), W)
    assert x >= sw + int(0.03 * W) and x + w == W - Inches(0.5)
