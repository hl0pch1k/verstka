"""Брендбук → брендированная копия шаблона (verstka/brand/apply.py) и расхождения (verstka/brand/conflicts.py).

Без модели и сети: синтетический шаблон python-pptx, настоящий шаблон из фикстур LibreOffice, разбор VK Tech из фикстур
и пример брендбука `examples/brandbook-vk-cloud`."""

from __future__ import annotations

import gzip
import json
import random
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

import verstka.brand.apply as ap
from verstka.analysis.manifest import analyze_template
from verstka.brand.apply import ColorPlan, apply_brand, brand_fingerprint, branded_info, branded_template, plan_colors, theme_info, tone
from verstka.brand.conflicts import brand_conflicts
from verstka.ingest.workspace import TemplateWorkspace
from verstka.schemas.brand import BrandColor, BrandFont, BrandLogo, BrandSpec
from verstka.schemas.template import TemplateManifest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "tpl_audit"
BRAND_EXAMPLE = ROOT / "examples" / "brandbook-vk-cloud"
W, H = 12192000, 6858000

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


# ---------------------------------------------------------------------------------------------- материалы


def _logo_png(path: Path, badge, ink, size=(400, 100)) -> Path:
    """Логотип: знак-плашка и «надпись» полосой на прозрачном фоне."""
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size[1]
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s // 5, fill=badge)
    d.rectangle([int(s * 1.25), s // 3, size[0] - 8, 2 * s // 3], fill=ink)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def _photo(path: Path) -> Path:
    rnd = random.Random(7)
    im = Image.new("RGB", (320, 240))
    im.putdata([(rnd.randrange(256), rnd.randrange(80), rnd.randrange(80)) for _ in range(320 * 240)])
    im.save(path, quality=90)
    return path


def _brand_dir(tmp: Path) -> Path:
    d = tmp / "brandbook"
    _logo_png(d / "logos" / "primary.png", (0, 119, 255, 255), (11, 18, 32, 255))
    _logo_png(d / "logos" / "white.png", (255, 255, 255, 255), (255, 255, 255, 255))
    im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, 127, 127], radius=24, fill=(0, 119, 255, 255))
    im.save(d / "logos" / "mark.png")
    return d


def _brand(**kw) -> BrandSpec:
    data = dict(
        name="Облако",
        source="tokens",
        colors=[
            BrandColor(hex="#0077FF", role="primary", name="Синий"),
            BrandColor(hex="#2787F5", role="secondary"),
            BrandColor(hex="#0B1220", role="text"),
            BrandColor(hex="#FFFFFF", role="background"),
            BrandColor(hex="#FF3985", role="accent"),
            BrandColor(hex="#00C2FF", role="chart"),
        ],
        fonts=[
            BrandFont(role="heading", family="Brand Display", fallback="Play", weight=700),
            BrandFont(role="body", family="Brand Text", fallback="Play", weight=400),
        ],
        logos=[
            BrandLogo(name="Основной", file="logos/primary.png", variant="primary", ground="light"),
            BrandLogo(name="Белый", file="logos/white.png", variant="white", ground="dark"),
            BrandLogo(name="Знак", file="logos/mark.png", variant="mark", ground="any"),
        ],
        logo_place="bottom_right",
        margins_px=48,
    )
    data.update(kw)
    return BrandSpec(**data)


def _text(slide, text, x, y, w, h, font, size, color, bold=False):
    tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    tb.text_frame.text = text
    r = tb.text_frame.paragraphs[0].runs[0]
    r.font.name, r.font.size, r.font.bold = font, Pt(size), bold
    r.font.color.rgb = RGBColor.from_string(color)
    return tb


def _card(slide, x, color):
    sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(x), Emu(int(H * 0.35)), Emu(int(W * 0.25)), Emu(int(H * 0.3)))
    sp.fill.solid()
    sp.fill.fore_color.rgb = RGBColor.from_string(color)
    sp.line.fill.background()
    return sp


def build_template(tmp: Path, *, logo: bool = True) -> Path:
    """Шаблон: светлый фон F7F7F7, текст 1F2937, акценты 1F6FEB и E8590C, светлая плашка DCE8FD, заголовки Georgia,
    текст Verdana, фото на втором слайде, диаграмма на третьем, логотип «знак + надпись» внизу слева."""
    logo_path = _logo_png(tmp / "src" / "acme-logo.png", (31, 111, 235, 255), (31, 41, 55, 255))
    photo = _photo(tmp / "src" / "photo.jpg")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    for i in range(4):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = RGBColor.from_string("F7F7F7")
        _text(s, f"Итоги квартала {i + 1}", int(W * 0.05), int(H * 0.06), int(W * 0.8), int(H * 0.14), "Georgia", 36, "1F2937")
        _text(s, "Выручка выросла, клиентов стало больше", int(W * 0.05), int(H * 0.22), int(W * 0.8), int(H * 0.08), "Verdana", 14, "1F2937")
        bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(W * 0.05)), Emu(int(H * 0.2)), Emu(int(W * 0.3)), Emu(int(H * 0.01)))
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string("1F6FEB")  # фирменная полоса шаблона: главный акцент
        bar.line.fill.background()
        if i == 1:
            s.shapes.add_picture(str(photo), Emu(int(W * 0.05)), Emu(int(H * 0.33)), Emu(int(W * 0.5)), Emu(int(H * 0.5))).name = "Фото"
        elif i == 2:
            cd = CategoryChartData()
            cd.categories = ["янв", "фев", "мар"]
            cd.add_series("Выручка", (1, 2, 3))
            gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Emu(int(W * 0.05)), Emu(int(H * 0.33)), Emu(int(W * 0.6)), Emu(int(H * 0.5)), cd)
            ser = gf.chart.plots[0].series[0]
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = RGBColor.from_string("1F6FEB")
            gf.chart.font.name = "Verdana"
        else:
            _card(s, int(W * 0.05), "1F6FEB")
            _card(s, int(W * 0.36), "E8590C" if i == 0 else "1F6FEB")
            _card(s, int(W * 0.67), "DCE8FD")
            _text(s, "+23%", int(W * 0.06), int(H * 0.4), int(W * 0.2), int(H * 0.12), "Georgia", 40, "FFFFFF")
        if logo:
            pic = s.shapes.add_picture(str(logo_path), Emu(int(W * 0.04)), Emu(int(H * 0.9)), height=Emu(int(H * 0.05)))
            pic.name = "Логотип ACME"
    out = tmp / "src" / "acme.pptx"
    prs.save(out)
    return out


@pytest.fixture
def fonts_here(monkeypatch):
    """На «машине» есть шрифты бренда — в копию пишутся они, а не замена."""
    monkeypatch.setattr(ap, "font_available", lambda f: f in {"Brand Display", "Brand Text", "Play"})


@pytest.fixture
def fonts_missing(monkeypatch):
    """Шрифтов бренда нет — пишется замена из брендбука (Play)."""
    monkeypatch.setattr(ap, "font_available", lambda f: f == "Play")


def _analyze(path: Path, ws: Path) -> TemplateManifest:
    return analyze_template(path, workspace_root=ws, use_llm=False, use_vlm=False, render=False)


def _parts(pptx: Path, pattern: str) -> dict[str, str]:
    with zipfile.ZipFile(pptx) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist() if re.match(pattern, n)}


def _all(pptx: Path, pattern: str) -> str:
    return "\n".join(_parts(pptx, pattern).values())


def _hexes(xml: str) -> set[str]:
    return set(re.findall(r'srgbClr val="([0-9A-Fa-f]{6})"', xml))


@pytest.fixture
def synthetic(tmp_path):
    src = build_template(tmp_path)
    m = _analyze(src, tmp_path / "ws")
    return src, m, _brand_dir(tmp_path)


# ---------------------------------------------------------------------------------------------- цвета


def test_color_math_tones():
    assert tone("0077FF") == "chromatic"
    assert tone("D6ECFF") == "tint"
    assert tone("000000") == tone("0B1220") == "dark"
    assert tone("FAFCFF") == "light"
    assert tone("8F8F8F") == "grey"


def test_synthetic_roles_as_expected(synthetic):
    """Предпосылка остальных тестов: разбор видит роли так, как задумано в шаблоне."""
    _, m, _ = synthetic
    roles = {t.hex: t.roles for t in m.tokens.colors}
    assert "background.light" in roles["F7F7F7"]
    assert "text.primary" in roles["1F2937"]
    assert any(r.startswith("accent.") for r in roles["1F6FEB"])
    assert any(r.startswith("accent.") for r in roles["E8590C"])


def test_explicit_colors_mapped_by_role(synthetic, fonts_here, tmp_path):
    src, m, bdir = synthetic
    out = tmp_path / "branded.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, brand_dir=bdir)
    slides = _all(out, r"ppt/slides/slide\d+\.xml$")
    hx = _hexes(slides)
    # главный акцент → основной цвет бренда, текст → текст бренда, фон → фон бренда
    assert {"0077FF", "0B1220", "FFFFFF"} <= hx
    assert not {"1F6FEB", "1F2937", "F7F7F7", "E8590C"} & hx
    assert res.colors["#1F6FEB"] == "#0077FF"
    assert res.colors["#1F2937"] == "#0B1220"
    assert res.colors["#F7F7F7"] == "#FFFFFF"
    # второй акцент (тёплый оранжевый) — к ближайшему по тону цвету бренда: тёплому розовому, не к синим
    assert res.colors["#E8590C"] == "#FF3985"
    # светлая плашка — тот же светлый оттенок, только в тоне бренда
    tint = res.colors.get("#DCE8FD", "#DCE8FD").lstrip("#")
    assert tone(tint) in ("tint", "light") and ap._hls(tint)[1] > 0.85
    # белые цифры на синей плашке остаются белыми: контраст не ломается
    assert "FFFFFF" in hx
    # диаграмма: заливка серии тоже в цветах бренда
    charts = _all(out, r"ppt/charts/chart\d+\.xml$")
    assert "0077FF" in _hexes(charts) and "1F6FEB" not in _hexes(charts)


def test_theme_colors_and_fonts_rewritten(synthetic, fonts_here, tmp_path):
    src, m, bdir = synthetic
    out = tmp_path / "branded.pptx"
    apply_brand(src, out, _brand(), manifest=m, brand_dir=bdir)
    before = theme_info(ap.etree.fromstring(_parts(src, r"ppt/theme/theme1\.xml$")["ppt/theme/theme1.xml"].encode()))
    after = theme_info(ap.etree.fromstring(_parts(out, r"ppt/theme/theme1\.xml$")["ppt/theme/theme1.xml"].encode()))
    assert before.stock  # стандартная тема python-pptx: её акценты занимает бренд по порядку
    assert after.slots["accent1"] == "0077FF"
    assert after.slots["accent2"] == "2787F5"
    assert after.slots["dk1"] == "0B1220"
    assert after.major == "Brand Display" and after.minor == "Brand Text"


def test_fonts_rewritten_by_role(synthetic, fonts_here, tmp_path):
    src, m, bdir = synthetic
    out = tmp_path / "branded.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, brand_dir=bdir)
    slides = _all(out, r"ppt/slides/slide\d+\.xml$")
    assert "Georgia" not in slides and "Verdana" not in slides
    # заголовок (36 пт) — шрифтом заголовков и полужирным (вес бренда 700), текст 14 пт — шрифтом текста
    title = re.search(r'<a:rPr[^>]*sz="3600"[^>]*>.*?</a:rPr>', slides, re.S).group(0)
    assert 'typeface="Brand Display"' in title and 'b="1"' in title
    body = re.search(r'<a:rPr[^>]*sz="1400"[^>]*>.*?</a:rPr>', slides, re.S).group(0)
    assert 'typeface="Brand Text"' in body and 'b="1"' not in body
    # мастера, макеты и диаграммы
    masters = _all(out, r"ppt/(slideMasters|slideLayouts)/.*\.xml$")
    assert re.search(r'typeface="Brand (Display|Text)"', masters) or "+mj-lt" in masters
    assert 'typeface="Brand Text"' in _all(out, r"ppt/charts/chart\d+\.xml$")
    assert res.fonts == {"heading": "Brand Display", "body": "Brand Text"}


def test_missing_brand_font_falls_back(synthetic, fonts_missing, tmp_path):
    """Шрифта бренда нет на машине — в копию пишется его замена из брендбука, как велит брендбук."""
    src, m, bdir = synthetic
    out = tmp_path / "branded.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, brand_dir=bdir)
    slides = _all(out, r"ppt/slides/slide\d+\.xml$")
    assert 'typeface="Play"' in slides and "Brand Display" not in slides
    assert res.fonts == {"heading": "Play", "body": "Play"}


def test_pictures_untouched(synthetic, fonts_here, tmp_path):
    src, m, bdir = synthetic
    out = tmp_path / "branded.pptx"
    apply_brand(src, out, _brand(), manifest=m, brand_dir=bdir)
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        photos = [n for n in a.namelist() if n.startswith("ppt/media/") and n.endswith((".jpg", ".jpeg"))]
        assert photos
        for n in photos:
            assert a.read(n) == b.read(n)  # пиксели фото те же
        s2a, s2b = a.read("ppt/slides/slide2.xml").decode(), b.read("ppt/slides/slide2.xml").decode()
    photo_pic = lambda x: re.search(r'<p:pic>(?:(?!</p:pic>).)*name="Фото".*?</p:pic>', x, re.S).group(0)  # noqa: E731
    pa, pb = photo_pic(s2a), photo_pic(s2b)
    assert re.search(r"<a:blip [^>]*>", pa).group(0) == re.search(r"<a:blip [^>]*>", pb).group(0)
    assert re.search(r"<a:xfrm>.*?</a:xfrm>", pa, re.S).group(0) == re.search(r"<a:xfrm>.*?</a:xfrm>", pb, re.S).group(0)


def test_blip_recolor_kept():
    """Цвета внутри картинки (перекраска, дуотон) — часть картинки: не трогаются."""
    xml = (
        f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{A[1:-1]}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree>'
        '<p:pic><p:blipFill><a:blip r:embed="rId2"><a:duotone><a:srgbClr val="1F6FEB"/><a:srgbClr val="FFFFFF"/></a:duotone></a:blip></p:blipFill>'
        '<p:spPr><a:ln><a:solidFill><a:srgbClr val="1F6FEB"/></a:solidFill></a:ln></p:spPr></p:pic></p:spTree></p:cSld></p:sld>'
    )
    root = ap.etree.fromstring(xml.encode())
    plan = ColorPlan(table={"1F6FEB": "0077FF"})
    from collections import Counter

    assert ap._recolor(root, plan, Counter())
    vals = [e.get("val") for e in root.iter(f"{A}srgbClr")]
    assert vals == ["1F6FEB", "FFFFFF", "0077FF"]


# ---------------------------------------------------------------------------------------------- логотипы


def test_logos_replaced_with_brand_logo(synthetic, fonts_here, tmp_path):
    src, m, bdir = synthetic
    out = tmp_path / "branded.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, brand_dir=bdir)
    assert res.logos_replaced == 4 and res.logos_added == 0
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        brand_media = [n for n in names if n.startswith("ppt/media/brand-logo-")]
        assert brand_media and all("primary" in n for n in brand_media)  # светлый фон → основной логотип
        assert z.read(brand_media[0]) == (bdir / "logos" / "primary.png").read_bytes()
        for i in range(1, 5):
            xml = z.read(f"ppt/slides/slide{i}.xml").decode()
            rels = z.read(f"ppt/slides/_rels/slide{i}.xml.rels").decode()
            logo = re.search(r'<p:pic>(?:(?!</p:pic>).)*name="Логотип Облако".*?</p:pic>', xml, re.S)
            assert logo, f"slide {i}: логотип бренда"
            rid = re.search(r'r:embed="([^"]+)"', logo.group(0)).group(1)
            assert re.search(rf'Id="{rid}"[^>]*Target="\.\./media/brand-logo-primary', rels) or re.search(
                rf'Target="\.\./media/brand-logo-primary[^"]*"[^>]*Id="{rid}"', rels
            )
            assert "Логотип ACME" not in xml
            # пропорции логотипа бренда и та же высота рамки
            ext = re.search(r'<a:ext cx="(\d+)" cy="(\d+)"', logo.group(0))
            cx, cy = int(ext.group(1)), int(ext.group(2))
            assert abs(cx / cy - 392 / 100) < 0.15
            assert abs(cy - H * 0.05) < H * 0.01
    # фото и диаграмма не задеты
    assert "Фото" in _parts(out, r"ppt/slides/slide2\.xml$")["ppt/slides/slide2.xml"]


def test_dark_ground_gets_white_logo(tmp_path, fonts_here):
    """Белая надпись логотипа шаблона — тёмный фон: ставится белый логотип бренда."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    white = _logo_png(tmp_path / "src" / "logo-white.png", (255, 255, 255, 255), (255, 255, 255, 255))
    for i in range(3):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = RGBColor.from_string("101828")
        _text(s, "Итоги", int(W * 0.05), int(H * 0.06), int(W * 0.8), int(H * 0.14), "Georgia", 36, "FFFFFF")
        s.shapes.add_picture(str(white), Emu(int(W * 0.8)), Emu(int(H * 0.05)), height=Emu(int(H * 0.06))).name = "Logo"
    src = tmp_path / "src" / "dark.pptx"
    prs.save(src)
    m = _analyze(src, tmp_path / "ws")
    out = tmp_path / "dark-branded.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, brand_dir=_brand_dir(tmp_path))
    assert res.logos_replaced == 3
    media = [n for n in zipfile.ZipFile(out).namelist() if n.startswith("ppt/media/brand-logo-")]
    assert media and all("white" in n for n in media)
    # тёмный фон шаблона брендбук со светлым фоном не переворачивает
    assert "101828" in _hexes(_all(out, r"ppt/slides/slide\d+\.xml$"))


def test_no_template_logo_brand_rule_adds_logo(tmp_path, fonts_here):
    """Логотипа в шаблоне нет, в брендбуке есть правило места — логотип бренда встаёт на макеты содержательных слайдов
    в правый нижний угол с полями брендбука; без правила — ничего не добавляется."""
    src = build_template(tmp_path, logo=False)
    m = _analyze(src, tmp_path / "ws")
    bdir = _brand_dir(tmp_path)
    out = tmp_path / "with-logo.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, brand_dir=bdir)
    assert res.logos_added >= 1
    layouts = _parts(out, r"ppt/slideLayouts/slideLayout\d+\.xml$")
    hit = [x for x in layouts.values() if "Логотип Облако" in x]
    assert hit
    off = re.search(r'name="Логотип Облако".*?<a:off x="(\d+)" y="(\d+)"/><a:ext cx="(\d+)" cy="(\d+)"', hit[0], re.S)
    x, y, cx, cy = (int(v) for v in off.groups())
    margin = 48 / 1920 * W
    assert abs(W - (x + cx) - margin) < W * 0.002 and abs(H - (y + cy) - margin) < H * 0.01
    out2 = tmp_path / "no-rule.pptx"
    res2 = apply_brand(src, out2, _brand(logo_place=None), manifest=m, brand_dir=bdir)
    assert res2.logos_added == 0
    assert "Логотип Облако" not in _all(out2, r"ppt/slideLayouts/.*\.xml$")


def test_added_logo_skips_covered_corner(tmp_path, fonts_here):
    """Угол занят содержимым образцов шаблона (логотип макета лёг бы под него) — логотип не ставится, с объяснением."""
    src = build_template(tmp_path, logo=False)
    prs = Presentation(str(src))
    for s in prs.slides:
        _card(s, int(W * 0.7), "1F6FEB").top = Emu(int(H * 0.7))
    prs.save(src)
    m = _analyze(src, tmp_path / "ws")
    res = apply_brand(src, tmp_path / "out.pptx", _brand(), manifest=m, brand_dir=_brand_dir(tmp_path))
    assert res.logos_added == 0
    assert any("угол занят" in w for w in res.warnings)
    assert "Логотип Облако" not in _all(tmp_path / "out.pptx", r"ppt/(slides|slideLayouts)/.*\.xml$")


def test_added_logo_goes_over_background_pictures(tmp_path, fonts_here):
    """Образцы шаблона закрывают угол фоновой картинкой во весь слайд (логотип макета скрылся бы под ней) — логотип
    встаёт на сами образцы поверх фона."""
    src = build_template(tmp_path, logo=False)
    bg = tmp_path / "src" / "bg.png"
    Image.new("RGB", (160, 90), (240, 240, 240)).save(bg)
    prs = Presentation(str(src))
    for s in prs.slides:
        pic = s.shapes.add_picture(str(bg), 0, 0, Emu(W), Emu(H))
        s.shapes._spTree.remove(pic._element)
        s.shapes._spTree.insert(2, pic._element)  # фон — под всем
    prs.save(src)
    m = _analyze(src, tmp_path / "ws")
    out = tmp_path / "out.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, brand_dir=_brand_dir(tmp_path))
    assert res.logos_added >= 1
    slides = _parts(out, r"ppt/slides/slide\d+\.xml$")
    assert any("Логотип Облако" in x for x in slides.values())
    assert "Логотип Облако" not in _all(out, r"ppt/slideLayouts/.*\.xml$")


# ---------------------------------------------------------------------------------------------- приоритет


def test_priority_template_only_fills_gaps(synthetic, fonts_here, tmp_path):
    """«Шаблон важнее»: свои цвета, шрифты и логотип шаблона остаются; бренд занимает только пустые места —
    стандартную тему офисного пакета и шрифты по умолчанию."""
    src, m, bdir = synthetic
    out = tmp_path / "tpl.pptx"
    res = apply_brand(src, out, _brand(), manifest=m, priority="template", brand_dir=bdir)
    slides = _all(out, r"ppt/slides/slide\d+\.xml$")
    hx = _hexes(slides)
    assert {"1F6FEB", "E8590C", "1F2937", "F7F7F7"} <= hx
    assert "Georgia" in slides and "Verdana" in slides
    assert 'b="1"' not in re.search(r'<a:rPr[^>]*sz="3600"[^>]*>', slides).group(0)
    assert res.logos_replaced == 0 and "Логотип ACME" in slides
    theme = theme_info(ap.etree.fromstring(_parts(out, r"ppt/theme/theme1\.xml$")["ppt/theme/theme1.xml"].encode()))
    assert theme.slots["accent1"] == "0077FF"  # стандартная тема — пустое место
    assert theme.major == "Brand Display"  # Calibri темы — шрифт по умолчанию, не свой у шаблона
    assert theme.slots["dk1"] == "000000"


def test_priority_brand_vs_template_on_real_template(tmp_path, fonts_here):
    """Настоящий шаблон LibreOffice (lo_vivid): брендбук перекрашивает акценты и текст, меняет шрифт; при приоритете
    шаблона свои цвета и Noto Sans остаются."""
    src = FIX / "templates" / "lo_vivid.pptx"
    ws = tmp_path / "ws"
    m = _analyze(src, ws)
    bdir = _brand_dir(tmp_path)
    brand = _brand()
    chrom = {"#0077FF", "#2787F5", "#00C2FF", "#FF3985"}
    out = tmp_path / "vivid-brand.pptx"
    res = apply_brand(src, out, brand, manifest=m, brand_dir=bdir)
    # текст (тёмный бирюзовый) → текст бренда, голубой акцент → цвет бренда того же тона
    assert res.colors["#04617B"] == "#0B1220"
    assert res.colors["#009EDA"] in chrom
    vis = _all(out, r"ppt/(slides|slideLayouts|slideMasters)/.*\.xml$")
    assert not {"04617B", "009EDA"} & _hexes(vis)
    assert 'typeface="Noto Sans"' not in vis and re.search(r'typeface="Brand (Display|Text)"', vis)
    theme = theme_info(ap.etree.fromstring(_parts(out, r"ppt/theme/theme1\.xml$")["ppt/theme/theme1.xml"].encode()))
    assert theme.slots["accent1"] == "0077FF" and theme.major == "Brand Display"
    # разбор копии: акценты — цвета бренда или их оттенки (заливки шаблона с модификаторами яркости)
    bid = branded_template(m.template_id, brand, "brand", workspace_root=ws, brand_dir=bdir, render=False)
    copy = TemplateManifest.model_validate_json((ws / "templates" / bid / "manifest.json").read_text(encoding="utf-8"))
    acc = [t.hex for t in copy.tokens.colors if (t.role or "").startswith("accent.")]
    assert acc and {"0077FF", "2787F5"} <= set(acc)
    assert all(min(ap._hue_dist(ap._hue(a), ap._hue(b[1:])) for b in chrom) <= 25 for a in acc)
    assert not {"1A82BF", "009EDA", "04617B"} & {t.hex for t in copy.tokens.colors}
    assert {f.family for f in copy.tokens.typography.families} & {"Brand Display", "Brand Text"}
    # шаблон важнее: свои цвета и Noto Sans остаются
    out2 = tmp_path / "vivid-template.pptx"
    apply_brand(src, out2, brand, manifest=m, priority="template", brand_dir=bdir)
    vis2 = _all(out2, r"ppt/(slides|slideLayouts|slideMasters)/.*\.xml$")
    assert {"04617B", "009EDA"} <= _hexes(vis2) and 'typeface="Noto Sans"' in vis2


def test_contrast_kept_light_on_dark(tmp_path, fonts_here):
    """Брендбук со светлым фоном и тёмным текстом на тёмном шаблоне: светлый текст и тёмный фон шаблона остаются."""
    src = FIX / "templates" / "lo_vivid.pptx"
    m = _analyze(src, tmp_path / "ws")
    plan = plan_colors(m, _brand(colors=[BrandColor(hex="#0077FF", role="primary"), BrandColor(hex="#FFFFFF", role="text"), BrandColor(hex="#0B1220", role="background")]), "brand")
    # текст шаблона тёмный, текст бренда светлый — не меняется; фон шаблона светлый, фон бренда тёмный — не меняется
    text = next(t.hex for t in m.tokens.colors if "text.primary" in t.roles)
    bg = next(t.hex for t in m.tokens.colors if "background.light" in t.roles)
    assert plan.map(text) == text and plan.map(bg) == bg
    assert len(plan.warnings) == 2


# ---------------------------------------------------------------------------------------------- копия в хранилище и кэш


def test_branded_template_stored_analyzed_and_cached(synthetic, fonts_here, tmp_path, monkeypatch):
    src, _, bdir = synthetic
    ws = tmp_path / "ws"
    base = TemplateWorkspace.create(src, ws)
    (base.dir / "title.txt").write_text("ACME\n", encoding="utf-8")
    brand = _brand()
    bid = branded_template(base.template_id, brand, "brand", workspace_root=ws, brand_dir=bdir, render=False)
    assert bid != base.template_id
    d = ws / "templates" / bid
    assert (d / "source.pptx").exists() and (d / "manifest.json").exists()
    assert (d / "title.txt").read_text(encoding="utf-8").strip() == "ACME · брендбук Облако"
    m = TemplateManifest.model_validate_json((d / "manifest.json").read_text(encoding="utf-8"))
    assert m.template_id == bid
    # разбор копии видит бренд: палитра и шрифты — бренда, весь конвейер дальше работает с ними
    hexes = {t.hex for t in m.tokens.colors}
    assert "0077FF" in hexes and "1F6FEB" not in hexes
    fams = {f.family for f in m.tokens.typography.families}
    assert {"Brand Display", "Brand Text"} & fams and not {"Georgia", "Verdana"} & fams
    info = branded_info(bid, ws)
    assert info["base_template_id"] == base.template_id and info["priority"] == "brand" and info["brand_name"] == "Облако"
    assert info["result"]["logos_replaced"] == 4

    # кэш: тот же брендбук и приоритет — без нового применения и разбора
    calls = []
    monkeypatch.setattr(ap, "apply_brand", lambda *a, **k: calls.append(1))
    import verstka.analysis.manifest as man

    monkeypatch.setattr(man, "analyze_template", lambda *a, **k: calls.append(2))
    assert branded_template(base.template_id, brand.model_copy(update={"id": "другой-id", "warnings": ["x"]}), "brand", workspace_root=ws, brand_dir=bdir) == bid
    assert calls == []
    # другой приоритет и другой брендбук — другие копии
    assert ap.branded_id(base.template_id, brand_fingerprint(brand, bdir), "template") != bid
    other = brand.model_copy(update={"colors": [BrandColor(hex="#00AA55", role="primary")]})
    assert brand_fingerprint(other, bdir) != brand_fingerprint(brand, bdir)
    # логотип поменялся в файле — другой отпечаток
    fp = brand_fingerprint(brand, bdir)
    _logo_png(bdir / "logos" / "primary.png", (255, 0, 0, 255), (0, 0, 0, 255))
    assert brand_fingerprint(brand, bdir) != fp


def test_branded_template_unchanged_copy_reuses_analysis(tmp_path, fonts_here, monkeypatch):
    """Брендбук ничего не меняет (шаблон важнее, своё всё) — копия получает разбор шаблона без нового разбора."""
    src = FIX / "templates" / "lo_vivid.pptx"
    ws = tmp_path / "ws"
    m = _analyze(src, ws)
    import verstka.analysis.manifest as man

    called = []
    monkeypatch.setattr(man, "analyze_template", lambda *a, **k: called.append(1))
    # шрифты шаблона свои (Noto Sans), тема — стандартная, но у бренда нет хроматических цветов и логотипов
    brand = _brand(colors=[BrandColor(hex="#222222", role="text")], fonts=[], logos=[], logo_place=None)
    monkeypatch.setattr(ap, "_retheme", lambda *a, **k: False)
    bid = branded_template(m.template_id, brand, "template", workspace_root=ws, render=False)
    assert called == []
    m2 = TemplateManifest.model_validate_json((ws / "templates" / bid / "manifest.json").read_text(encoding="utf-8"))
    assert m2.template_id == bid and len(m2.patterns) == len(m.patterns)
    assert (ws / "templates" / bid / "source.pptx").read_bytes() == TemplateWorkspace.open(m.template_id, ws).source.read_bytes()


def test_unknown_template_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        branded_template("0123456789abcdef", _brand(), workspace_root=tmp_path)


# ---------------------------------------------------------------------------------------------- расхождения


def _vk_manifest() -> TemplateManifest:
    data = json.loads(gzip.open(FIX / "manifest_cbbe3aa6a21d23ce.json.gz").read())
    return TemplateManifest.model_validate(data)


def test_conflicts_vk_tech_and_vk_cloud_as_in_scenario(monkeypatch):
    """SCENARIO.md: шрифт заголовков Play → VK Sans Display (замена — Play), второй акцент #FF3885 → #FF3985."""
    from verstka.brand.read import read_brandbook

    monkeypatch.setattr(ap, "font_available", lambda f: f == "Play")
    brand = read_brandbook(BRAND_EXAMPLE)
    m = _vk_manifest()
    src = FIX / "vktech_short.pptx"  # колода на шаблоне VK Tech: его тема и макеты
    got = brand_conflicts(m, brand, source=src, brand_dir=BRAND_EXAMPLE)
    by = {c.what: c for c in got}
    head = by["Шрифт заголовков"]
    assert (head.template, head.brand, head.result, head.kind) == ("Play", "VK Sans Display", "VK Sans Display, замена — Play", "font")
    acc = by["Второй акцент"]
    assert (acc.template, acc.brand, acc.result, acc.kind) == ("#FF3885", "#FF3985", "#FF3985", "color")
    # основной акцент совпадает (#0077FF), чёрный и #0B1220, #FAFCFF и белый — для человека одно и то же
    assert "Основной акцент" not in by and "Цвет текста" not in by and "Фон" not in by
    assert by["Логотип"].result == "логотип VK Cloud"
    # шаблон важнее — в презентации остаётся шаблон
    tpl = {c.what: c for c in brand_conflicts(m, brand, priority="template", source=src, brand_dir=BRAND_EXAMPLE)}
    assert tpl["Шрифт заголовков"].result == "Play, как в шаблоне"
    assert tpl["Второй акцент"].result == "#FF3885, как в шаблоне"


def test_conflicts_brand_font_installed(monkeypatch):
    from verstka.brand.read import read_brandbook

    monkeypatch.setattr(ap, "font_available", lambda f: True)
    got = {c.what: c for c in brand_conflicts(_vk_manifest(), read_brandbook(BRAND_EXAMPLE / "tokens.json"), source=FIX / "vktech_short.pptx")}
    assert got["Шрифт заголовков"].result == "VK Sans Display"
    assert "Логотип" not in got  # у токенов нет файлов логотипов


def test_conflicts_without_template_file():
    """Файла шаблона нет — расхождения по разбору (тема неизвестна: акценты — из разбора)."""
    got = brand_conflicts(_vk_manifest(), _brand(), workspace_root="/nonexistent")
    assert any(c.what == "Шрифт заголовков" for c in got)
    assert all(c.what and c.template and c.brand and c.result for c in got)
