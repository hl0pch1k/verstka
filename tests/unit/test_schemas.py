from verstka.schemas.common import Bbox, BboxFrac, Color, contrast_ratio
from verstka.schemas.template import ShapeStyleStats, SlideSize, Spacing, TemplateManifest, Tokens, Typography


def test_bbox_to_frac_and_iou():
    a = Bbox(x=0, y=0, w=100, h=100)
    b = Bbox(x=50, y=50, w=100, h=100)
    assert abs(a.iou(b) - 2500 / 17500) < 1e-9
    f = a.to_frac(200, 400)
    assert (f.x, f.y, f.w, f.h) == (0.0, 0.0, 0.5, 0.25)


def test_bbox_frac_close_to():
    assert BboxFrac(x=0.1, y=0.1, w=0.2, h=0.2).close_to(BboxFrac(x=0.105, y=0.1, w=0.2, h=0.2))
    assert not BboxFrac(x=0.1, y=0.1, w=0.2, h=0.2).close_to(BboxFrac(x=0.2, y=0.1, w=0.2, h=0.2))


def test_color_normalization_and_delta_e():
    c = Color(hex="#0077ff")
    assert c.hex == "0077FF"
    assert Color.delta_e(Color(hex="0077FF"), Color(hex="0077FF")) == 0
    assert Color.delta_e(Color(hex="0077FF"), Color(hex="FF3885")) > 30
    assert Color.delta_e(Color(hex="0077FF"), Color(hex="0079FF")) < 3


def test_contrast_ratio():
    assert abs(contrast_ratio("000000", "FFFFFF") - 21.0) < 0.01
    assert contrast_ratio("FFFFFF", "FFFFFF") == 1.0


def test_manifest_roundtrip(tmp_path):
    m = TemplateManifest(
        template_id="abc",
        source_file="x.pptx",
        slide_size=SlideSize(w=9144000, h=5143500),
        tokens=Tokens(typography=Typography(), spacing=Spacing(), shapes=ShapeStyleStats()),
    )
    p = tmp_path / "m.json"
    p.write_text(m.model_dump_json())
    back = TemplateManifest.model_validate_json(p.read_text())
    assert back.template_id == "abc" and back.slide_size.w == 9144000
