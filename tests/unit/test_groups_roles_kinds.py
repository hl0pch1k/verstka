from verstka.analysis.chrome import chrome_ids, detect_chrome
from verstka.analysis.groups import detect_repeat_groups
from verstka.analysis.kinds import heuristic_kind
from verstka.analysis.roles import heuristic_roles, is_numeric_text
from verstka.analysis.shapes import ParagraphInfo, RunInfo, ShapeInfo, SlideContext, TextInfo, extract_shapes
from verstka.analysis.typography import build_type_scale
from verstka.ingest.package import PptxPackage
from verstka.schemas.common import Bbox, PatternKind, ShapeKind, SlotRole
from verstka.schemas.template import TypeStep, Typography

W, H = 12192000, 6858000


def _t(sid, text, size, x, y, w, h, bold=False):
    ti = TextInfo(paragraphs=[ParagraphInfo(text=text, runs=[RunInfo(text=text, font="Play", size_pt=size, bold=bold, color_hex="000000")])])
    return ShapeInfo(id=sid, name=sid, kind=ShapeKind.sp, bbox=Bbox(x=int(x * W), y=int(y * H), w=int(w * W), h=int(h * H)), z=0, text=ti)


def _analyze(pptx):
    pkg = PptxPackage.open(pptx)
    per_slide = {i: extract_shapes(pkg, part, SlideContext(pkg, part)) for i, part in enumerate(pkg.slide_parts, 1)}
    chrome = detect_chrome(per_slide, *pkg.slide_size)
    ids = {i: chrome_ids(per_slide[i], chrome, *pkg.slide_size) for i in per_slide}
    typo = build_type_scale(per_slide, ids)
    out = {}
    for i, shapes in per_slide.items():
        groups = detect_repeat_groups(shapes, *pkg.slide_size, chrome_ids=ids[i])
        roles = heuristic_roles(shapes, groups, ids[i], typo, *pkg.slide_size)
        kind, conf = heuristic_kind(shapes, roles, groups, i, len(per_slide), *pkg.slide_size)
        out[i] = (shapes, groups, roles, kind)
    return out


def test_simple_deck_groups_roles_kinds(simple_deck):
    res = _analyze(simple_deck)
    shapes1, groups1, roles1, kind1 = res[1]
    assert kind1 == PatternKind.title
    assert SlotRole.title in roles1.values() and SlotRole.subtitle in roles1.values()
    assert any(r == SlotRole.chrome for r in roles1.values())

    shapes2, groups2, roles2, kind2 = res[2]
    assert len(groups2) == 1 and groups2[0].axis == "row" and len(groups2[0].member_shape_ids) == 3 and groups2[0].max_n >= 3
    assert all(len(cell) == 3 for cell in groups2[0].member_shape_ids)
    assert list(roles2.values()).count(SlotRole.card_title) == 3 and list(roles2.values()).count(SlotRole.card_body) == 3
    assert kind2 == PatternKind.cards

    shapes3, groups3, roles3, kind3 = res[3]
    assert SlotRole.image in roles3.values()
    assert kind3 == PatternKind.image_text


def test_stat_row_and_numbers():
    typo = Typography(scale=[TypeStep(role="h1", size_pt=32), TypeStep(role="body", size_pt=16), TypeStep(role="caption", size_pt=10)])
    shapes = [_t("s1", "Ключевые показатели", 32, 0.05, 0.08, 0.6, 0.1)]
    for i in range(3):
        x = 0.05 + i * 0.3
        shapes.append(_t(f"n{i}", f"{40 + i}%", 54, x, 0.35, 0.2, 0.15, bold=True))
        shapes.append(_t(f"l{i}", "доля рынка", 14, x, 0.52, 0.2, 0.06))
    groups = detect_repeat_groups(shapes, W, H)
    roles = heuristic_roles(shapes, groups, set(), typo, W, H)
    assert roles["s1"] == SlotRole.title
    assert all(roles[f"n{i}"] == SlotRole.number for i in range(3))
    assert all(roles[f"l{i}"] in (SlotRole.number_label, SlotRole.card_body, SlotRole.caption) for i in range(3))
    kind, conf = heuristic_kind(shapes, roles, groups, 5, 20, W, H)
    assert kind == PatternKind.stat_row


def test_numeric_regex():
    assert is_numeric_text("91%") and is_numeric_text("1 200 млн") and is_numeric_text(">50*".replace("*", ""))
    assert not is_numeric_text("Выручка") and not is_numeric_text("2 шага к успеху")
