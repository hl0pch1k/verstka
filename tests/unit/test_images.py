"""Pictures inside slides (verstka/images): the t2i backends read their hosts' answers, a chain skips links without a
key and links that cannot answer, the picture is graded to the template's palette and cropped to its place, the places
the author described get pictures, the author's own photo never does, and the free place comes back on request.
No live model is called: the hosts are replaced by fakes."""

from __future__ import annotations

import base64
import io
import json

import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from verstka.analysis.xmlns import q
from verstka.images import palette as P
from verstka.images import providers as IP
from verstka.images.fill import apply_pictures, plan_pictures, read_records, write_records
from verstka.images.places import CAPTION_PREFIX, places_in, take_picture_out
from verstka.images.prompt import ImageAsk, build_prompt, style_of
from verstka.images.service import ImageMaker
from verstka.schemas.outline import PHOTO_PLACE_NAME, DeckOutline, OutlineSlide, SlideContent


def _png(w=64, h=48, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


class _Resp:
    def __init__(self, status=200, obj=None, content=b"", headers=None):
        self.status_code = status
        self._obj = obj
        self.content = content or (json.dumps(obj).encode() if obj is not None else b"")
        self.text = self.content.decode("utf-8", "replace") if obj is not None else ""
        self.headers = headers or {}

    def json(self):
        return self._obj


def test_openrouter_images_reads_b64_and_sends_aspect(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, auth=headers.get("Authorization"))
        return _Resp(obj={"data": [{"b64_json": base64.b64encode(_png()).decode(), "media_type": "image/png"}], "usage": {"cost": 0.014}})

    monkeypatch.setattr(httpx, "post", fake_post)
    p = IP.OpenRouterImages("black-forest-labs/flux.2-klein-4b", "https://openrouter.ai/api/v1", "sk-test", label="FLUX.2 klein")
    r = p.generate("a greenhouse", aspect="16:9", seed=7)
    assert seen["url"] == "https://openrouter.ai/api/v1/images"
    assert seen["body"]["aspect_ratio"] == "16:9" and seen["body"]["seed"] == 7 and seen["body"]["model"] == "black-forest-labs/flux.2-klein-4b"
    assert seen["auth"] == "Bearer sk-test"
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n" and r.cost_usd == 0.014 and r.label == "FLUX.2 klein"


def test_picture_of_reads_urls_and_chat_answers():
    data = _png()
    url = "data:image/png;base64," + base64.b64encode(data).decode()
    assert IP.picture_of({"data": [{"url": url}]}) == data
    assert IP.picture_of({"choices": [{"message": {"images": [{"type": "image_url", "image_url": {"url": url}}]}}]}) == data
    assert IP.picture_of({"data": [{"url": "https://x/y.png"}]}, fetch=lambda u: data) == data
    assert IP.picture_of({"data": []}) is None


def test_a_chain_skips_links_without_a_key_and_holds_a_link_without_credits(monkeypatch):
    import httpx

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json["model"])
        if json["model"] == "paid":
            return _Resp(status=402, obj={"error": {"message": "Insufficient credits"}})
        return _Resp(obj={"data": [{"b64_json": base64.b64encode(_png()).decode()}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    chain = IP.build_image_provider({"backend": "openrouter_images", "chain": [
        {"model": "nokey", "api_key": ""}, {"model": "paid", "api_key": "k"}, {"model": "free", "api_key": "k"}]})
    assert [d["state"] for d in chain.describe()] == ["off", "ready", "ready"]
    r = chain.generate("x", aspect="1:1")
    assert r.model == "free" and calls == ["paid", "free"]
    chain.generate("y", aspect="1:1")
    assert calls == ["paid", "free", "free"]  # the link without credits is skipped for a while
    assert chain.describe()[1]["state"] == "no_credits"


def test_a_chain_without_any_key_is_off():
    chain = IP.build_image_provider({"backend": "openrouter_images", "chain": [{"model": "a", "api_key": ""}]})
    assert chain.off
    with pytest.raises(IP.ImageError):
        chain.generate("x")


def test_nearest_aspect():
    assert IP.nearest_aspect(1600, 900) == "16:9"
    assert IP.nearest_aspect(900, 1200) == "3:4"
    assert IP.nearest_aspect(1000, 1000) == "1:1"


def test_grading_brings_a_picture_to_the_palette_and_fit_keeps_proportions():
    pal = P.Palette(dark="0B1F44", light="F4F6FA", accents=["FF6A00"])
    img = Image.new("RGB", (300, 200), (40, 200, 60))  # a green the palette does not have
    before = P.palette_match(img, pal)
    after = P.palette_match(P.grade(img, pal, 0.8), pal)
    assert after > before
    assert P.grade(img, pal, 0.0).getpixel((0, 0)) == (40, 200, 60)
    out = P.fit_to(Image.new("RGB", (1600, 900)), 3, 4, max_side=800)
    assert abs(out.size[0] / out.size[1] - 0.75) < 0.01 and max(out.size) <= 800


def test_colour_names_read_as_words():
    assert P.color_name("FFFFFF") == "white"
    assert "orange" in P.color_name("FF6A00")
    assert "blue" in P.color_name("0B1F44")


def test_the_prompt_carries_subject_style_palette_and_no_text():
    pal = P.Palette(dark="0B1F44", light="F4F6FA", accents=["FF6A00"])
    prompt, style = build_prompt(ImageAsk(hint="Экран панели управления теплицей", headline="Панель наблюдения", deck="Умная теплица"), pal)
    assert style == "screen"
    assert "Экран панели управления теплицей" in prompt and "Панель наблюдения" in prompt
    assert "#FF6A00" in prompt and "No text" in prompt
    p2, _ = build_prompt(ImageAsk(hint="Вид теплицы сверху", headline="Теплица", deck="Т", wish="больше зелени, утро"), pal)
    assert p2.startswith("больше зелени, утро") and "Вид теплицы сверху" in p2
    assert style_of("схема полива", {"styles": [{"match": "схем", "style": "illustration"}], "default_style": "photo"}) == "illustration"


def _deck_with_places(tmp_path):
    """Two slides, each with a free place and its caption, as the renderer leaves them."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for i in range(2):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(6), Inches(1)).text_frame.text = f"Слайд {i + 1}"
        frame = s.shapes.add_shape(5, Inches(7), Inches(1.5), Inches(5.5), Inches(4.5))  # a rounded rectangle
        frame.name = PHOTO_PLACE_NAME
        cap = s.shapes.add_textbox(Inches(7.5), Inches(3.2), Inches(4.5), Inches(1))
        cap.text_frame.text = "Место под изображение"
        cap.name = f"{CAPTION_PREFIX} {cap.shape_id}"
        over = s.shapes.add_shape(1, Inches(6.8), Inches(1.3), Inches(0.5), Inches(0.5))  # something drawn over the place
        over.name = "Over"
    path = tmp_path / "deck.pptx"
    prs.save(str(path))
    outline = DeckOutline(title="Умная теплица", slides=[
        OutlineSlide(id="a", kind="image_text", headline="Панель наблюдения", content=SlideContent(bullets=["x"], photo_slot="Изображение", photo_hint="Экран панели управления")),
        OutlineSlide(id="b", kind="image_text", headline="Помещение", content=SlideContent(bullets=["y"], photo_slot="Фото помещения", photo_own=True)),
    ])
    return path, outline


def test_places_are_found_with_their_captions_and_owners(tmp_path):
    path, outline = _deck_with_places(tmp_path)
    places = places_in(Presentation(str(path)), outline)
    assert [(p.slide, p.own, len(p.caption_ids)) for p in places] == [(1, False, 1), (2, True, 1)]
    assert places[0].hint == "Экран панели управления" and places[0].headline == "Панель наблюдения"


def test_the_described_place_gets_a_picture_and_the_own_photo_place_stays_free(tmp_path):
    path, outline = _deck_with_places(tmp_path)
    mock = IP.MockImages()
    maker = ImageMaker(IP.ImageChain([mock]), None, tmp_path / "cache", deck_title=outline.title)
    pending = plan_pictures(path, outline, maker)
    res = apply_pictures(path, pending, wait_s=10)
    write_records(tmp_path, res.records)
    maker.close()
    assert res.changed == [1] and len(mock.calls) == 1
    assert "Экран панели управления" in mock.calls[0]["prompt"]
    prs = Presentation(str(path))
    tree1 = prs.slides[0]._element.cSld.find(q("p:spTree"))
    names = [el.find(".//" + q("p:cNvPr")).get("name") for el in tree1 if el.find(".//" + q("p:cNvPr")) is not None]
    pics = [el for el in tree1 if etree.QName(el).localname == "pic"]
    assert len(pics) == 1 and not any(n.startswith(CAPTION_PREFIX) for n in names) and PHOTO_PLACE_NAME not in names
    # the picture keeps the place's position under what was drawn over it, and the frame's geometry
    assert names.index("Over") > [n for n in names].index(pics[0].find(".//" + q("p:cNvPr")).get("name"))
    assert pics[0].find(".//" + q("a:prstGeom")).get("prst") == "roundRect"
    assert "сгенерировано" in pics[0].find(".//" + q("p:cNvPr")).get("descr")
    tree2 = prs.slides[1]._element.cSld.find(q("p:spTree"))
    assert not [el for el in tree2 if etree.QName(el).localname == "pic"]
    recs = read_records(tmp_path)
    assert [(r["slide"], r["status"]) for r in recs] == [(1, "generated"), (2, "free")]
    assert recs[1]["why"].startswith("место под ваше фото")
    # «Убрать изображение»: the free place and its caption come back
    rec = recs[0]
    assert take_picture_out(prs.slides[0], rec["shape_id"], rec["kept"])
    names = [el.find(".//" + q("p:cNvPr")).get("name") for el in tree1 if el.find(".//" + q("p:cNvPr")) is not None]
    assert PHOTO_PLACE_NAME in names and any(n.startswith(CAPTION_PREFIX) for n in names)


def test_without_a_model_the_places_stay_free(tmp_path):
    path, outline = _deck_with_places(tmp_path)
    pending = plan_pictures(path, outline, None)
    res = apply_pictures(path, pending)
    assert res.changed == [] and {r["status"] for r in res.records} == {"free"}


def test_the_variants_share_a_picture_and_a_failing_model_leaves_the_place(tmp_path):
    path, outline = _deck_with_places(tmp_path)
    mock = IP.MockImages()
    maker = ImageMaker(IP.ImageChain([mock]), None, tmp_path / "cache", deck_title=outline.title)
    f1 = maker.submit(ImageAsk(hint="h", headline="x", deck="d"), "4:3")
    f2 = maker.submit(ImageAsk(hint="h", headline="x", deck="d"), "4:3")
    assert f1 is f2
    f1.result(timeout=5)
    assert len(mock.calls) == 1
    maker.close()
    bad = ImageMaker(IP.ImageChain([IP.MockImages(fail=True)]), None, tmp_path / "cache2", deck_title=outline.title)
    res = apply_pictures(path, plan_pictures(path, outline, bad), wait_s=5)
    bad.close()
    assert res.changed == [] and res.records[0]["why"] == "модель изображений не ответила"


# ---------------------------------------------------------------------------- the whole path (no live model)

GREENHOUSE = """Тема презентации: «Умная теплица». Презентация на 3 слайда.

Слайд 1. Умная теплица

Автоматический полив и контроль климата для учебной теплицы.

Слайд 2. Панель наблюдения

Панель управления объединяет текущие показания датчиков. Пользователь быстро видит, какие зоны требуют внимания.

[Место под изображение: экран панели управления теплицей с показаниями датчиков]

Слайд 3. Помещение

Теплица площадью 40 м² стоит во дворе школы. Внутри — шесть грядок и бак для воды на 200 литров.

На этом слайде обязательно оставь свободное место под фотографию помещения. Фото я добавлю самостоятельно. Не заполняй это место текстом, диаграммой или сгенерированным изображением.
"""


def _pics_and_places(slide):
    tree = slide._element.cSld.find(q("p:spTree"))
    names = [el.find(".//" + q("p:cNvPr")).get("name") for el in tree if el.find(".//" + q("p:cNvPr")) is not None]
    return [n for n in names if n.startswith("Изображение")], [n for n in names if n == PHOTO_PLACE_NAME]


def test_a_build_puts_pictures_in_the_described_places_only(tmp_path):
    from pathlib import Path as _P

    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import load_brief

    tpl = _P(__file__).resolve().parents[1] / "fixtures" / "tpl_audit" / "templates" / "lo_focus.pptx"
    p = tmp_path / "brief.md"
    p.write_text(GREENHOUSE, encoding="utf-8")
    mock = IP.MockImages()
    g = generate_variants(tpl, brief=load_brief(p), strategies=["structured", "visual"], out_dir=tmp_path / "run", workspace_root=tmp_path / "ws",
                          use_llm=False, use_vlm=False, audit=True, exports=[], image_provider=IP.ImageChain([mock]))
    assert mock.calls and all("экран панели управления теплицей" in c["prompt"].lower() for c in mock.calls)
    assert len(mock.calls) == 1  # the variants share the place's picture
    for v in g.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        by_spec = {s.spec_ref: i for i, s in enumerate(v.outline.slides)}
        pics2, places2 = _pics_and_places(prs.slides[by_spec[2]])
        pics3, places3 = _pics_and_places(prs.slides[by_spec[3]])
        assert len(pics2) == 1 and not places2, v.strategy
        assert not pics3 and len(places3) == 1, v.strategy  # the author's own photo: the place stays free
        recs = read_records(v.out_dir)
        assert sorted(r["status"] for r in recs) == ["free", "generated"]
        assert next(r for r in recs if r["status"] == "free")["own"] is True
        rm = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
        assert rm["pictures"]["generated"] == 1 and rm["pictures"]["own"] == 1
    assert any((tmp_path / "run" / "images").glob("*.jpg"))


def test_a_build_with_pictures_off_keeps_every_place_free(tmp_path):
    from pathlib import Path as _P

    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import load_brief

    tpl = _P(__file__).resolve().parents[1] / "fixtures" / "tpl_audit" / "templates" / "lo_focus.pptx"
    p = tmp_path / "brief.md"
    p.write_text(GREENHOUSE, encoding="utf-8")
    mock = IP.MockImages()
    g = generate_variants(tpl, brief=load_brief(p), strategies=["structured"], out_dir=tmp_path / "run", workspace_root=tmp_path / "ws",
                          use_llm=False, use_vlm=False, audit=True, exports=[], image_provider=IP.ImageChain([mock]), pictures=False)
    assert not mock.calls
    recs = read_records(g.variants[0].out_dir)
    assert {r["status"] for r in recs} == {"free"} and any(r["why"] == "генерация изображений выключена" for r in recs)


def test_a_caption_hanging_out_of_its_trimmed_place_goes_with_it(tmp_path):
    """The renderer may trim a frame after captioning it (aligned to the content's foot): the caption then hangs below
    the frame — it is still the place's, and goes when the picture comes (VK Tech, slide «Панель наблюдения»)."""
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    frame = s.shapes.add_shape(1, Inches(5), Inches(1.5), Inches(3.6), Inches(1.6))
    frame.name = PHOTO_PLACE_NAME
    cap = s.shapes.add_textbox(Inches(5.3), Inches(2.85), Inches(3), Inches(0.55))  # its centre below the frame
    cap.name = f"{CAPTION_PREFIX} {cap.shape_id}"
    outline = DeckOutline(title="T", slides=[OutlineSlide(id="a", kind="image_text", headline="H", content=SlideContent(photo_slot="Изображение", photo_hint="экран"))])
    (place,) = places_in(prs, outline)
    assert place.caption_ids == [str(cap.shape_id)]
