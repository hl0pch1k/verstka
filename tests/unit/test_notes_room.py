"""Regression tests (the live QA of 2026-10-07): the author's planned lines stay on the slide when a denser setting holds them."""
from __future__ import annotations

import pytest
from lxml import etree

from verstka.analysis.manifest import analyze_template
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.deck import DeckBuilder
from verstka.rendering.synth import render_synth
from verstka.schemas.common import EMU_PER_PT, PatternKind
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent, TableData
from verstka.schemas.template import TypeStep


@pytest.fixture
def env(simple_deck, tmp_path):
    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    return simple_deck, manifest, ws


def _render(env, o: OutlineSlide, comp: str, strategy: str):
    deck, manifest, ws = env
    outline = DeckOutline(title="T", strategy=strategy, slides=[o])
    return render_synth(DeckBuilder(deck), LayoutSlide(outline_id=o.id, mode="synth", composition=comp), o, manifest, ws, outline)


def _texts(slide) -> str:
    out = []
    for sh in slide.shapes:
        if sh.has_text_frame:
            out.append(sh.text_frame.text)
        if sh.has_table:
            out.extend(c.text for r in sh.table.rows for c in r.cells)
    return "\n".join(out).replace(" ", " ").replace("⁠", "")


def _table_size(slide) -> float:
    for sh in slide.shapes:
        if sh.has_table:
            szs = [int(r.get("sz")) / 100 for r in sh._element.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}rPr") if r.get("sz")]
            return min(szs)
    raise AssertionError("no table")


ROWS = [["Покупки в день", "100", "115"], ["Средний чек", "300 рублей", "330 рублей"], ["Месячная выручка", "900 000 рублей", "1 138 500 рублей"],
        ["Переменные расходы", "315 000 рублей", "375 705 рублей"], ["Постоянные операционные расходы", "465 000 рублей", "508 000 рублей"],
        ["Операционная прибыль", "120 000 рублей", "254 795 рублей"], ["Операционная рентабельность", "13,3%", "22,4%"]]
LINES = ["Рост постоянных расходов: +43 000 ₽", "Персонал: 20 000 ₽", "Маркетинг: 15 000 ₽", "Лояльность и учет: 5 000 ₽", "Коммунальные услуги: 3 000 ₽"]


def _small_under_floor(manifest, hpt: float) -> float:
    """The template's small step set at 2.1 % of the slide height: the Kit snaps «small» to it (it allows 1.9 %), the
    table must be allowed to use it too."""
    small = round(0.021 * hpt * 2) / 2
    typo = manifest.tokens.typography
    near = lambda x: small < x <= 0.022 * hpt + 0.6  # noqa: E731 — no step of the template between it and 2.2 % H
    typo.scale = [s for s in typo.scale if s.role != "small"] + [TypeStep(role="small", size_pt=small)]
    typo.sizes_used = sorted({x for x in typo.sizes_used if not near(x)} | {small})
    typo.derived_sizes = [x for x in (typo.derived_sizes or []) if not near(x)]
    return small


@pytest.mark.parametrize("strategy", ["structured", "compact", "visual"])
def test_a_table_steps_down_to_the_templates_small_size_before_its_lines_leave(env, strategy):
    deck, manifest, ws = env
    hpt = manifest.slide_size.h / EMU_PER_PT
    small = _small_under_floor(manifest, hpt)
    assert small < 0.022 * hpt
    from verstka.rendering.compose import Kit
    assert Kit(manifest, manifest.slide_size.w, manifest.slide_size.h, "FFFFFF").small == small  # the Kit takes it
    o = OutlineSlide(id="t", kind=PatternKind.table, headline="Операционная прибыль вырастет до 254 795 ₽ к шестому месяцу",
                     takeaway="Выручка увеличивается на 26,5%, а прибыль — примерно на 112%",
                     content=SlideContent(table=TableData(columns=["Показатель", "Сейчас", "Цель"], rows=ROWS), bullets=list(LINES)))
    slide, warnings = _render(env, o, "table", strategy)
    text = _texts(slide)
    missing = [t for t in LINES if t.replace("рублей", "₽") not in text and t not in text]
    assert not missing, (missing, warnings)
    assert "• " not in (o.notes or ""), o.notes
    assert "Вывод:" not in (o.notes or ""), o.notes


@pytest.mark.parametrize("strategy", ["structured", "visual"])
def test_number_tiles_beside_a_photo_place_set_denser_before_the_conclusion_leaves(env, strategy):
    nums = [NumberCallout(value="25,4 °C", label="Температура воздуха"), NumberCallout(value="67%", label="Влажность воздуха"),
            NumberCallout(value="72%", label="Заполненность бака"), NumberCallout(value="40 сек", label="Последнее обновление")]
    o = OutlineSlide(id="k", kind=PatternKind.stat_row, headline="Панель показывает текущие показания и историю за 24 часа",
                     takeaway="Данные обновляются каждые 40 секунд",
                     content=SlideContent(numbers=nums, bullets=["Графики за сутки рядом с текущими значениями", "Предупреждения объясняют причину и требуемое действие", "Отметки включения полива и вентиляции на графике"], photo_slot="Фото", photo_hint="Экран панели"))
    slide, warnings = _render(env, o, "stat_row", strategy)
    names = [sh.name for sh in slide.shapes]
    assert any(n.startswith("Conclusion") for n in names), (warnings, o.notes)
    assert "Вывод:" not in (o.notes or ""), o.notes


def test_the_audit_reads_the_typesetters_minus_and_ranges():
    """«-31,25%» is set «−31,25%» (a true minus) and «5-6 тыс.» «5⁠–⁠6 тыс.»: the planned line is on the slide."""
    from verstka.audit.checks.integrity import _norm_text, _present
    from verstka.ru import typeset

    for line in ("Эксперимент: -31,25% воды, -12,5 ч ручной работы в месяц", "Рост 5-6 тыс. гостей в месяц", "-5 °C ночью"):
        assert _present(line, _norm_text(typeset(line))), (line, typeset(line))
