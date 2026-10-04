"""A variant the planning agent did not plan (no model, no time, a failed agent) is planned by the pipeline's own
planner: its designer step still says what each slide became — the lines the agent says — so the build's storyboard
and the agent's timeline fill in without a model too."""

from verstka.pipeline.generate import _design_line, _say_designs
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent, TableData


def _slide(kind: PatternKind, headline: str, **content) -> OutlineSlide:
    return OutlineSlide(id=f"s-{headline[:4]}", kind=kind, headline=headline, content=SlideContent(**content))


def test_lines_name_the_slide_its_headline_and_its_form():
    table = _slide(PatternKind.table, "Итоги пилота", table=TableData(columns=["Метрика", "До", "После"], rows=[["Время", "47", "29"], ["Доля", "38%", "14%"]]))
    assert _design_line(3, table, "rules") == "Дизайнер: слайд 3 «Итоги пилота» собран по правилам — таблица 2×3."
    assert _design_line(3, table, "model") == "Дизайнер: слайд 3 «Итоги пилота» — таблица 2×3."
    assert _design_line(1, _slide(PatternKind.title, "Умные сводки"), "rules") == "Дизайнер: слайд 1 — обложка «Умные сводки»."
    assert _design_line(10, _slide(PatternKind.thanks, "Спасибо за внимание"), "rules") == "Дизайнер: слайд 10 — финальный слайд «Спасибо за внимание»."


def test_every_slide_of_every_variant_is_said_once_per_variant():
    said: list[dict] = []

    def progress(message, share, event=None):
        said.append({"message": message, "share": share, **(event or {})})

    deck = DeckOutline(title="Умные сводки", slides=[_slide(PatternKind.title, "Умные сводки"), _slide(PatternKind.bullets, "Проблема", bullets=["47 минут в день"])])
    _say_designs(progress, {"structured": deck, "visual": deck}, share=0.15)
    assert [(e["variant"], e["slide"], e["step"]) for e in said] == [("structured", 1, "designer"), ("structured", 2, "designer"), ("visual", 1, "designer"), ("visual", 2, "designer")]
    # the lines never move the bar past the plan's own share (the layout comes next and starts from there)
    assert all(e["share"] == 0.15 for e in said)
    # the event's words, as the agent's own: without the step and the slide (the timeline shows them)
    assert said[0]["message"] == "Обложка «Умные сводки»."
    assert said[1]["message"].startswith("«Проблема» собран по правилам — список")
