"""A model plan is made to read like a designed deck after grounding (outline.polish_plan)."""

from __future__ import annotations

from verstka.planning.outline import _agree, polish_plan
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent


def _deck(slides: list[OutlineSlide], planned_by: str = "model") -> DeckOutline:
    return DeckOutline(title="Итоги пилота", planned_by=planned_by, slides=[OutlineSlide(id="t", kind=K.title, headline="Итоги пилота"), *slides, OutlineSlide(id="z", kind=K.thanks, headline="Спасибо за внимание")])


def _live_structured() -> list[OutlineSlide]:
    return [
        OutlineSlide(id="s1", kind=K.section, headline="Контекст и проблема"),
        OutlineSlide(id="a", kind=K.bullets, headline="Проблема: избыточное время на обработку чатов", content=SlideContent(bullets=["Сотрудники тратят 47 минут в день на чтение чатов."])),
        OutlineSlide(id="s2", kind=K.section, headline="Результаты пилота"),
        OutlineSlide(id="b", kind=K.stat_row, headline="Улучшение показателей", content=SlideContent(numbers=[NumberCallout(value="29 минут", label="время на чтение чатов"), NumberCallout(value="64", label="NPS")])),
        OutlineSlide(id="s3", kind=K.section, headline="Просьба на масштабирование"),
        OutlineSlide(id="c", kind=K.bullets, headline="Просим бюджет на масштабирование", content=SlideContent(paragraphs=["Бюджет: 14,5 млн ₽"])),
    ]


def test_a_short_model_deck_has_no_divider_per_slide_and_one_line_slides_become_figures():
    o = polish_plan(_deck(_live_structured()))
    assert [s.kind for s in o.slides] == [K.title, K.big_number, K.stat_row, K.big_number, K.thanks]
    problem, ask = o.slides[1], o.slides[3]
    assert problem.content.numbers[0].value == "47 минут" and not problem.content.bullets
    assert ask.content.numbers[0].value == "14,5 млн ₽" and ask.content.numbers[0].label == "бюджет" and not ask.content.paragraphs


def test_a_line_without_one_figure_is_a_statement_and_a_label_never_repeats_its_figure():
    o = polish_plan(_deck([
        OutlineSlide(id="a", kind=K.bullets, headline="Главное", content=SlideContent(bullets=["Команда запускает раскатку на все отделы"])),
        OutlineSlide(id="b", kind=K.bullets, headline="Обратная связь пользователей", content=SlideContent(paragraphs=["NPS: 64 баллов"])),
    ]))
    st, nps = o.slides[1], o.slides[2]
    assert st.kind == K.bullets and st.content.paragraphs == ["Команда запускает раскатку на все отделы"] and not st.content.bullets
    assert nps.kind == K.big_number and nps.content.numbers[0].value == "64" and nps.content.numbers[0].label == "NPS"


def test_count_nouns_agree_with_their_number():
    assert _agree("NPS: 64 баллов") == "NPS: 64 балла"
    assert _agree("1 баллов") == "1 балл" and _agree("4,5 баллов") == "4,5 балла" and _agree("12 пунктов") == "12 пунктов"


def test_a_long_model_deck_keeps_its_dividers_and_rules_plans_are_untouched():
    many = [OutlineSlide(id=f"x{i}", kind=K.bullets, headline=f"Тезис {i}", content=SlideContent(bullets=["первый пункт", "второй пункт"])) for i in range(6)]
    long = _deck([OutlineSlide(id="s", kind=K.section, headline="Раздел"), *many])
    assert any(s.kind == K.section for s in polish_plan(long).slides)
    rules = _deck(_live_structured(), planned_by="rules")
    assert polish_plan(rules).model_dump() == rules.model_dump()
