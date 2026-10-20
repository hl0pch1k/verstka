"""Брендбук главнее шаблона (жюри, раунд 2, R20): подложка шаблона почти во весь слайд («Sunset»: оранжевый градиент на
82 % слайда) — цветом фона бренда, и логотип встаёт на неё, а не «у краёв нет свободного места»."""

from __future__ import annotations

from lxml import etree

from verstka.brand.apply import _reground, ground_shape
from verstka.brand.package import A, P
from verstka.brand.palette import ColorPlan

SW, SH = 10080625, 5670550


def _tree(shapes: str) -> etree._Element:
    return etree.fromstring(
        f'<p:sldMaster xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sldMaster>')


def _sp(cx: int, cy: int, fill: str, text: str = "", ph: bool = False) -> str:
    nv = '<p:nvSpPr><p:cNvPr id="2" name=""/><p:cNvSpPr/><p:nvPr>' + ('<p:ph type="body"/>' if ph else "") + '</p:nvPr></p:nvSpPr>'
    body = f'<p:txBody><a:bodyPr/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody>' if text else ""
    return (f'<p:sp>{nv}<p:spPr><a:xfrm><a:off x="540000" y="360000"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{fill}<a:ln w="108000"><a:solidFill><a:srgbClr val="FFFFFF"/>'
            f'</a:solidFill></a:ln></p:spPr>{body}</p:sp>')


GRAD = ('<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="FFFF00"/></a:gs><a:gs pos="100000"><a:srgbClr val="FF8000"/>'
        '</a:gs></a:gsLst></a:gradFill>')


def test_the_template_ground_takes_the_brand_background():
    root = _tree(_sp(9000000, 5220000, GRAD) + _sp(2000000, 900000, GRAD) + _sp(9000000, 5220000, GRAD, text="Заголовок"))
    plan = ColorPlan(background_pair=("FFC000", "FFFFFF"))
    from collections import Counter

    assert _reground(root, plan, (SW, SH), Counter())
    sps = root.findall(f".//{{{P}}}sp")
    grad = lambda sp: [c.get("val") for c in sp.find(f"{{{P}}}spPr/{{{A}}}gradFill").iter(f"{{{A}}}srgbClr")]  # noqa: E731
    assert grad(sps[0]) == ["FFFFFF", "FFFFFF"]  # the ground — the brand's
    assert grad(sps[1]) == ["FFFF00", "FF8000"]  # a small shape is the template's drawing
    assert grad(sps[2]) == ["FFFF00", "FF8000"]  # a shape with text is no ground
    ln = sps[0].find(f"{{{P}}}spPr/{{{A}}}ln/{{{A}}}solidFill/{{{A}}}srgbClr").get("val")
    assert ln == "FFFFFF"


def test_no_ground_change_when_the_brand_background_was_not_taken():
    root = _tree(_sp(9000000, 5220000, GRAD))
    from collections import Counter

    assert not _reground(root, ColorPlan(background_pair=("FFC000", "FFC000")), (SW, SH), Counter())
    assert ground_shape(root.find(f".//{{{P}}}sp"), SW, SH)
