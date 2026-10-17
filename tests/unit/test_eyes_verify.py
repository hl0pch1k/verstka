"""«Взгляд дизайнера» checks its remarks against the slide's own data (qa4 U2/U3): a chart remark the chart's IR
contradicts is dropped («ось Y разорвана» with no gap in the data, «точка 52 над II кв.» on a chart drawn from checked
data, «Институт обрезан» for a category the chart holds whole inside the slide); only a verified major remark lays the
slide out again, and a new layout on which the verified problem is gone is taken without the side-by-side vote."""

from __future__ import annotations

from verstka.audit import eyes as E
from verstka.schemas.audit import Issue
from verstka.schemas.common import Bbox, BboxFrac
from verstka.schemas.deck_ir import IRChart, IRChartSeries, IRElement, IRSlide
from verstka.schemas.common import PatternKind as K
from verstka.schemas.data import SlideData
from verstka.schemas.outline import OutlineSlide

W, H = 12192000, 6858000


def _chart_slide(categories, values, kind="column", frac=(0.05, 0.25, 0.9, 0.6)) -> IRSlide:
    x, y, w, h = frac
    e = IRElement(id="7", type="chart", bbox=Bbox(x=int(x * W), y=int(y * H), w=int(w * W), h=int(h * H)), bbox_frac=BboxFrac(x=x, y=y, w=w, h=h),
                  chart=IRChart(type=kind, categories=categories, series=[IRChartSeries(name="Значение", values=values)]))
    return IRSlide(index=3, elements=[e], outline_id="s3")


def _p(code, where, evidence, severity="major") -> E.ReviewProblem:
    return E.ReviewProblem(code=code, severity=severity, where=where, evidence=evidence)


DATA = OutlineSlide(id="s3", kind=K.chart, headline="NPS вырос до 52", data=SlideData(dataset_id="d", file="NPS.csv"))
PLAIN = OutlineSlide(id="s3", kind=K.chart, headline="Выручка растёт")


def test_a_broken_axis_with_no_gap_in_the_data_is_dropped():
    sl = _chart_slide(["Янв", "Фев", "Мар", "Апр"], [10, 12, 15, 18])
    verdict, why = E.check_problem(_p("chart_unreadable", "ось Y", "ось Y разорвана, значения не читаются"), sl, PLAIN, [])
    assert verdict == "contradicted" and "пропусков" in why
    gap = _chart_slide(["I", "II", "III"], [41, None, 52])
    assert E.check_problem(_p("chart_unreadable", "линия", "линия прерывается"), gap, DATA, [])[0] == "contradicted"  # intended gap
    assert E.check_problem(_p("chart_unreadable", "линия", "линия прерывается"), gap, PLAIN, [])[0] == "verified"


def test_a_point_over_the_wrong_label_on_checked_data_is_dropped():
    sl = _chart_slide(["II кв. 2026", "III кв. 2026"], [None, 52], kind="line")
    assert E.check_problem(_p("chart_unreadable", "график", "точка 52 над II кв. 2026"), sl, DATA, [])[0] == "contradicted"
    # a chart of the brief: the value is the data's, at its own category
    assert E.check_problem(_p("chart_unreadable", "график", "точка 52 стоит над II кв."), sl, PLAIN, [])[0] == "contradicted"


def test_a_cut_label_the_chart_holds_whole_is_dropped_and_a_frame_past_the_slide_is_verified():
    cats = ["Институт экономики", "Институт права", "Медицинский институт"]
    sl = _chart_slide(cats, [120, 90, 60], kind="bar")
    assert E.check_problem(_p("text_cut", "подписи диаграммы", "«Институт» обрезан"), sl, PLAIN, [])[0] == "contradicted"
    out = _chart_slide(cats, [120, 90, 60], kind="bar", frac=(0.3, 0.2, 0.8, 0.6))
    assert E.check_problem(_p("text_cut", "подписи диаграммы", "«Инстит…» обрезан краем слайда"), out, PLAIN, [])[0] == "verified"


def test_crowded_labels_are_checked_against_the_room_they_have():
    roomy = _chart_slide(["Москва", "Казань", "Сочи"], [3, 2, 1])
    assert E.check_problem(_p("chart_unreadable", "подписи оси X", "подписи слиплись"), roomy, PLAIN, [])[0] == "contradicted"
    many = _chart_slide([f"Подразделение{k}" for k in range(24)], list(range(24)), frac=(0.05, 0.25, 0.4, 0.5))
    assert E.check_problem(_p("chart_unreadable", "подписи оси X", "подписи слиплись"), many, PLAIN, [])[0] == "verified"


def test_text_remarks_are_verified_by_the_xml_checks_only():
    sl = IRSlide(index=4, elements=[], outline_id="s4")
    remark = _p("text_cut", "правая карточка", "текст выходит за карточку")
    assert E.check_problem(remark, sl, PLAIN, [])[0] == "unverified"
    clipped = Issue(id="text_clipped-4-0", slide=4, check_id="text_clipped", severity="error", kind="deterministic", message="обрезан")
    assert E.check_problem(remark, sl, PLAIN, [clipped])[0] == "verified"


def test_only_verified_major_remarks_lay_a_slide_out_again():
    sl = _chart_slide(["Янв", "Фев", "Мар"], [1, 2, 3])
    problems = [_p("chart_unreadable", "ось Y", "ось Y разорвана"), _p("unbalanced", "правая половина", "пусто"),
                _p("chart_unreadable", "подписи", "подписи слиплись", severity="minor")]
    fill = Issue(id="fill_ratio-3-0", slide=3, check_id="fill_ratio", severity="warn", kind="deterministic", message="слайд заполнен на 9%")
    keep, verified, dropped = E.sort_problems(problems, sl, PLAIN, [fill])
    assert [p.code for p in verified] == ["unbalanced"]
    assert len(dropped) == 2 and all(d["why"] for d in dropped)
    assert [p.code for p in keep] == ["unbalanced"]


def test_a_strip_over_the_chart_is_verified_by_its_geometry():
    """u1 live (qa4 round): «голубая плашка с текстом перекрывает нижнюю часть графика» was real — the conclusion strip
    stood on the line's lower half — and must never be dropped as «labels have room»."""
    sl = _chart_slide([f"м{k}" for k in range(21)], list(range(21)), kind="line", frac=(0.066, 0.307, 0.871, 0.585))
    strip = IRElement(id="9", type="shape", name="Conclusion strip", bbox=Bbox(x=int(0.056 * W), y=int(0.678 * H), w=int(0.89 * W), h=int(0.147 * H)),
                      bbox_frac=BboxFrac(x=0.056, y=0.678, w=0.89, h=0.147))
    foot = IRElement(id="10", type="text", name="Footnote", bbox=Bbox(x=int(0.056 * W), y=int(0.849 * H), w=int(0.89 * W), h=int(0.033 * H)),
                     bbox_frac=BboxFrac(x=0.056, y=0.849, w=0.89, h=0.033))
    remark = _p("overlap", "нижняя часть графика", "голубая плашка с текстом перекрывает нижнюю часть графика: линия и точки скрыты")
    sl.elements += [foot]
    assert E.check_problem(remark, sl, DATA, [])[0] == "contradicted"  # the footnote under the axis is no overlap
    sl.elements += [strip]
    verdict, why = E.check_problem(remark, sl, DATA, [])
    assert verdict == "verified" and "Conclusion strip" in why


def test_a_tall_headline_box_above_the_chart_is_not_on_it():
    # the relayout that cured u2's overlap: the headline's text box runs down past the chart's top, its text does not
    sl = _chart_slide(["a", "b"], [1, 2], kind="line", frac=(0.069, 0.275, 0.859, 0.322))
    head = IRElement(id="2", type="text", name="Headline", bbox=Bbox(x=int(0.056 * W), y=int(0.101 * H), w=int(0.89 * W), h=int(0.508 * H)),
                     bbox_frac=BboxFrac(x=0.056, y=0.101, w=0.89, h=0.508))
    sl.elements.append(head)
    assert E._on_chart(sl, sl.elements[0]) == []
