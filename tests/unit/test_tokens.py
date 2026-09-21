from verstka.analysis.chrome import chrome_ids, detect_chrome
from verstka.analysis.colors import ColorSample, assign_color_roles, cluster_colors, collect_color_samples
from verstka.analysis.shapes import ParagraphInfo, RunInfo, ShapeInfo, SlideContext, TextInfo, extract_shapes
from verstka.analysis.spacing import compute_spacing
from verstka.analysis.typography import build_type_scale
from verstka.ingest.package import PptxPackage
from verstka.schemas.common import Bbox, Family, ShapeKind

W, H = 12192000, 6858000


def _text_shape(sid: str, text: str, size: float, x=0.1, y=0.1, w=0.3, h=0.1, bold=False, color="000000", font="Play", align=None, paragraphs=None):
    paras = paragraphs or [text]
    ti = TextInfo(paragraphs=[ParagraphInfo(text=t, align=align, runs=[RunInfo(text=t, font=font, size_pt=size, bold=bold, color_hex=color)]) for t in paras])
    return ShapeInfo(id=sid, name=sid, kind=ShapeKind.sp, bbox=Bbox(x=int(x * W), y=int(y * H), w=int(w * W), h=int(h * H)), z=int(sid[1:]) if sid[1:].isdigit() else 0, text=ti)


def test_cluster_merges_near_colors_and_keeps_brand_hex():
    samples = [ColorSample("0077FF", "fill", 5), ColorSample("0078FE", "fill", 1), ColorSample("0079FF", "text", 1), ColorSample("FF3885", "fill", 2)]
    tokens = cluster_colors(samples)
    assert [t.hex for t in tokens] == ["0077FF", "FF3885"]
    assert tokens[0].weight == 7 and tokens[0].contexts == {"fill": 2, "text": 1}


def test_role_assignment_light_template():
    samples = [
        ColorSample("FFFFFF", "background", 100),
        ColorSample("000000", "text", 40),
        ColorSample("8F8F8F", "text", 10),
        ColorSample("0077FF", "fill", 12),
        ColorSample("0077FF", "text", 5),
        ColorSample("F5F8FC", "fill", 6),
        ColorSample("FF3885", "fill", 2),
    ]
    tokens = assign_color_roles(cluster_colors(samples), Family.light)
    roles = {t.role.split("|")[0]: t.hex for t in tokens if t.role}
    assert roles["background.light"] == "FFFFFF"
    assert roles["text.primary"] == "000000"
    assert roles["text.secondary"] == "8F8F8F"
    assert roles["accent.1"] == "0077FF"
    assert roles["surface"] == "F5F8FC"
    assert roles["accent.2"] == "FF3885"


def test_type_scale_roles():
    shapes = {
        1: [_text_shape("s1", "Заголовок слайда", 32), _text_shape("s2", "x" * 200, 18), _text_shape("s3", "note", 12)],
        2: [_text_shape("s4", "Другой заголовок", 32), _text_shape("s5", "y" * 300, 18), _text_shape("s6", "sub", 24), _text_shape("s7", "97%", 60)],
        3: [_text_shape("s8", "Третий", 32), _text_shape("s9", "z" * 250, 18), _text_shape("s10", "cap", 12)],
    }
    typo = build_type_scale(shapes)
    roles = {s.role: s.size_pt for s in typo.scale}
    assert roles["h1"] == 32 and roles["body"] == 18 and roles["h2"] == 24 and roles["display"] == 60
    assert roles["small"] == 12
    assert typo.families[0].family == "Play"
    assert typo.left_align_share == 1.0


def test_chrome_and_spacing_on_simple_deck(simple_deck):
    pkg = PptxPackage.open(simple_deck)
    per_slide = {}
    for i, part in enumerate(pkg.slide_parts, 1):
        per_slide[i] = extract_shapes(pkg, part, SlideContext(pkg, part))
    chrome = detect_chrome(per_slide, *pkg.slide_size)
    assert any(c.text == "ACME" for c in chrome)
    assert not any(c.text and c.text.startswith("Quarterly") for c in chrome)
    ids = {i: chrome_ids(per_slide[i], chrome, *pkg.slide_size) for i in per_slide}
    assert all(len(v) >= 1 for v in ids.values())
    spacing = compute_spacing(per_slide, ids, *pkg.slide_size)
    assert 0.02 <= spacing.safe_area.x <= 0.15 and spacing.safe_area.w >= 0.7
    samples = collect_color_samples(per_slide[2], *pkg.slide_size, bg_hex="FFFFFF", chrome_ids=ids[2])
    hexes = {s.hex for s in samples}
    assert "EDF3FC" in hexes and "0077FF" in hexes
