"""The audit compares every figure of the finished deck with the source text (checks/facts.py)."""

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches, Pt

from verstka.audit.checks.facts import figure_not_in_brief, figure_summary
from verstka.audit.ir import build_deck_ir
from verstka.audit.registry import AuditContext

BRIEF = (
    "Ежемесячные расходы кофейни составляют 780 000 рублей: продукты — 315 000 рублей, зарплаты — 270 000 рублей, "
    "аренда — 195 000 рублей. Выручка вырастет с 900 000 до 1 138 500 рублей."
)


def _deck(tmp_path, texts, pie=None):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for t in texts:
        s = prs.slides.add_slide(prs.slide_layouts[6])
        for i, line in enumerate(t):
            tb = s.shapes.add_textbox(Inches(1), Inches(1 + i), Inches(8), Inches(0.8))
            tb.text_frame.text = line
            tb.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
        if pie is not None:
            data = CategoryChartData()
            data.categories = list(pie)
            data.add_series("Расходы", list(pie.values()))
            s.shapes.add_chart(XL_CHART_TYPE.PIE, Inches(8), Inches(2), Inches(4), Inches(4), data)
    path = tmp_path / "deck.pptx"
    prs.save(path)
    return build_deck_ir(path)


def _ctx(ir, brief=BRIEF):
    return AuditContext(ir=ir, manifest=None, outline=None, brief_text=brief)


def test_brief_figures_and_derived_ones_pass(tmp_path):
    ir = _deck(tmp_path, [["Расходы — 780 000 ₽ в месяц", "Выручка вырастет на 26,5%", "01"]])
    ctx = _ctx(ir)
    assert figure_not_in_brief(ctx) == []
    assert ctx.figure_stats["unverified"] == 0
    assert ctx.figure_stats["derived"] >= 1  # 26,5% of 900 000 → 1 138 500


def test_an_invented_figure_is_reported(tmp_path):
    ir = _deck(tmp_path, [["Расходы — 780 000 ₽ в месяц", "Нас выбрали 12 400 клиентов"]])
    ctx = _ctx(ir)
    issues = figure_not_in_brief(ctx)
    assert len(issues) == 1 and "12 400" in issues[0].message.replace(" ", " ")
    assert ctx.figure_stats["unverified"] == 1
    assert "в нём нет" in figure_summary(ctx.figure_stats)


def test_pie_legend_shares_are_the_charts_own(tmp_path):
    pie = {"Продукты": 315000, "Зарплаты": 270000, "Аренда": 195000}
    ir = _deck(tmp_path, [["Продукты  315 000 ₽ · 40%", "Зарплаты  270 000 ₽ · 35%", "Аренда  195 000 ₽ · 25%"]], pie=pie)
    ctx = _ctx(ir)
    assert figure_not_in_brief(ctx) == []
    assert ctx.figure_stats["derived"] == 3


def test_no_brief_no_check(tmp_path):
    ir = _deck(tmp_path, [["Нас выбрали 12 400 клиентов"]])
    ctx = _ctx(ir, brief=None)
    assert figure_not_in_brief(ctx) == [] and ctx.figure_stats is None


def test_step_numbers_are_not_figures(tmp_path):
    ir = _deck(tmp_path, [["Месяц 2 — запуск комбо", "Этап 1", "3‑й мес.", "Шаг 4: обучение"]])
    ctx = _ctx(ir)
    assert figure_not_in_brief(ctx) == []
