"""Content fidelity of ordinary decks and of text edits on data slides (live QA of 2026-10-17 with the VK model,
.superpowers/sdd/s2/qa2-report.md: Story S4/S5, Composer L3 on the planner's side, API E1).

- S4: a pilot's result is never told as a forecast («Пользователи пилота вырастут в 10 раз»); a plan stays a plan.
- S5: a promised count is what the slide shows; item numbers all or none; a section of the brief (its ask above all)
  reaches the storyline; a step the source labels «Далее» is never «Неделя 4».
- L3: 2–4 key figures stay a row of figures, never bare-figure cards or a two-row table in a variant.
- E1: a headline or caption edit of a data slide applies (the chart from the file stays, the number rule runs), and
  the reply never says the model is unavailable when it answered.
No network: the model is a stub (verstka/providers/mock.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from verstka.planning import agent as A
from verstka.planning.brief import parse_brief_text
from verstka.planning.brief_structure import read_structure
from verstka.planning.grounding import BriefIndex, ground_outline, uniform_numbers
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, NumberCallout, OutlineSlide, SlideContent, SlideItem

ROOT = Path(__file__).resolve().parents[2]
VKWS = (ROOT / "examples" / "briefs" / "vk_workspace_feature.md").read_text(encoding="utf-8")
EDU = (ROOT / "examples" / "briefs" / "edu_program.md").read_text(encoding="utf-8")
COFFEE = (ROOT / "tests" / "fixtures" / "briefs" / "coffee_short.md").read_text(encoding="utf-8")


def _index(text: str) -> BriefIndex:
    return BriefIndex.of(parse_brief_text(text)).use_structure(read_structure(text))


def _ctx(text: str):
    brief = parse_brief_text(text)
    structure, _ = A.analyse_brief(brief)
    facts = A._resolve_facts(None, brief, [], structure)
    return A._build_ctx(brief, structure, facts, None)


# ------------------------------------------------------------------ S4: a fact is not a forecast


@pytest.mark.parametrize("line", [
    "Пользователи пилота выросли в 10 раз",  # the brief's May → September 1 200 → 12 400: a pilot's result
    "Число активных пользователей пилота выросло в 10 раз",
    "Активные пользователи выросли до 12 400",
    "Доля завершённых в срок задач выросла на 34%",
])
def test_a_pilots_result_is_no_forecast(line):
    idx = _index(VKWS)
    assert not idx.forecast_line(line), line
    assert idx.fix_hedges(line) == line


def test_two_past_sets_are_no_forecast():
    # «Набор 2024 | Набор 2025» on 2026-10-17: the second set is a result («Набор вырастет…» was the QA's o03/o04)
    idx = _index(EDU)
    for line in ("Набор вырос с 640 до 1 100 студентов", "Трудоустройство выросло до 63%"):
        assert not idx.forecast_line(line), line


def test_a_plan_stays_a_plan():
    idx = _index(COFFEE)
    for line in ("Операционная прибыль выросла в 2,1 раза", "Выручка выросла на 26,5%", "Средний чек вырос с 300 до 330 ₽", "Рентабельность выросла до 22,4%"):
        assert idx.forecast_line(line), line


def test_a_result_the_brief_states_is_never_told_as_coming():
    # o01/e2: «Функция снижает срывы дедлайнов с 31% до 12%» → the designer's «Срывы дедлайнов снизятся с 31% до 12%»
    idx = _index(VKWS)
    assert idx.in_brief_tense("Срывы дедлайнов снизятся с 31% до 12%") == "Срывы дедлайнов снижаются с 31% до 12%"
    assert idx.in_brief_tense("Доля задач в срок вырастет на 34%") == "Доля задач в срок выросла на 34%"  # the brief's own form
    for line in ("Охват вырастет до 20% компаний", "Конверсия в «Про» вырастет"):  # a plan's figure, no figure: as it is
        assert idx.in_brief_tense(line) is None, line
    coffee = _index(COFFEE)
    for line in ("Выручка вырастет на 26,5%", "Средний чек вырастет с 300 до 330 ₽", "Прибыль составит 254 795 ₽"):
        assert coffee.in_brief_tense(line) is None, line


def test_the_compilers_tense_guard_keeps_a_pilots_result_in_the_past():
    from verstka.planning.compile import compile_outline

    brief = parse_brief_text(VKWS)
    st = read_structure(VKWS)
    o = DeckOutline(title="t", slides=[
        OutlineSlide(id="c", kind=K.title, headline="t"),
        OutlineSlide(id="s8", kind=K.chart, headline="Пользователи пилота выросли в 10 раз",
                     content=SlideContent(chart=ChartSpec(type="column", categories=["Май", "Июнь", "Июль", "Август", "Сентябрь"],
                                                          series=[InlineSeries(name="Активные пользователи", values=[1200, 3400, 6100, 9800, 12400])], unit="чел."))),
    ])
    out, warns = compile_outline(o, st, brief)
    s = next(x for x in out.slides if x.id == "s8")
    assert "выросли" in s.headline and "вырастут" not in s.headline, (s.headline, warns)


def test_the_designers_headline_keeps_its_tense():
    ctx = _ctx(VKWS)
    from verstka.schemas.agent import SlideDesignAnswer

    unit = A._Unit(key="u7", title="Динамика активных пользователей", text="Динамика активных пользователей пилота:", series_ids=list(ctx.series)[:1])
    ans = SlideDesignAnswer.model_validate({"kind": "chart", "headline": "Пользователи пилота выросли в 10 раз",
                                            "chart": {"type": "column", "categories": ["Май", "Июнь", "Июль", "Август", "Сентябрь"],
                                                      "series": [{"name": "Активные пользователи, чел.", "values": [1200, 3400, 6100, 9800, 12400]}]}})
    d = A.design_from_answer(ans, unit, ctx)
    assert d is not None and "вырастут" not in d.slide.headline, d.slide.headline
    assert not any("a plan is not a result" in x for x in d.changes), d.changes


# ------------------------------------------------------------------ S5: promised items, numbering, sections


MODULES = ["Основы SQL и Python", "Потоковая обработка", "Хранилища и витрины", "Инженерия ML-пайплайнов"]


def test_grounding_keeps_numbered_modules_the_brief_does_not_number():
    # o04: «Модуль 1/2» read as figures 1 and 2 the brief does not have: module 2 dropped, «3», «4» left as stray numbers
    items = [SlideItem(title=f"Модуль {i}", text=x, number=str(i)) for i, x in enumerate(MODULES, 1)]
    o = DeckOutline(title="t", slides=[OutlineSlide(id="c", kind=K.title, headline="t"),
                                       OutlineSlide(id="s4", kind=K.process, headline="Программа из 4 модулей ведёт от SQL к ML-пайплайнам", content=SlideContent(items=items))])
    out, warns = ground_outline(o, parse_brief_text(EDU))
    got = out.slides[1].content.items
    assert [(it.number, it.title, it.text) for it in got] == [(str(i), f"Модуль {i}", x) for i, x in enumerate(MODULES, 1)], warns
    assert not any("«1», «2»" in w for w in warns)


def test_numbering_is_all_or_nothing():
    # o03: numbers on items 3–4 only → every item numbered in order
    items = [SlideItem(title=x, number=n) for x, n in zip(MODULES, [None, None, "3", "4"])]
    assert uniform_numbers(items) and [it.number for it in items] == ["1", "2", "3", "4"]
    # one stray number of four: none
    items = [SlideItem(title=x, number=n) for x, n in zip(MODULES, [None, None, None, "4"])]
    assert uniform_numbers(items) and [it.number for it in items] == [None] * 4
    # an item dropped: the badges follow the order
    items = [SlideItem(title=x, number=n) for x, n in zip(MODULES, ["1", "3", "4"])]
    assert uniform_numbers(items) and [it.number for it in items] == ["1", "2", "3"]
    # «01», «02» keep their style; figures in the number field are no numbering
    items = [SlideItem(title="a", number="01"), SlideItem(title="b", number=None), SlideItem(title="c", number="03")]
    uniform_numbers(items)
    assert [it.number for it in items] == ["01", "02", "03"]
    figs = [SlideItem(title="Дошли до конца", number="71%"), SlideItem(title="Трудоустроены", number="58%")]
    assert not uniform_numbers(figs) and [it.number for it in figs] == ["71%", "58%"]
    # the position never stays in the item's words
    items = [SlideItem(title="1. Основы SQL"), SlideItem(title="2. Потоковая обработка")]
    uniform_numbers(items)
    assert [(it.number, it.title) for it in items] == [("1", "Основы SQL"), ("2", "Потоковая обработка")]


def test_an_items_number_is_not_said_again_in_its_words():
    # e4: badge «1» and the card's text «Модуль 1» (the brief does not number its modules; the audit flagged «1», «2»)
    items = [SlideItem(title=x, text=f"Модуль {i}", number=str(i)) for i, x in enumerate(MODULES, 1)]
    assert A.position_labels(items, SOURCE)
    assert [(it.number, it.title, it.text) for it in items] == [(str(i), x, "") for i, x in enumerate(MODULES, 1)]
    items = [SlideItem(title=f"Модуль {i}", text=x, number=str(i)) for i, x in enumerate(MODULES, 1)]
    A.position_labels(items, SOURCE)
    assert [it.title for it in items] == MODULES
    # the source's own step titles stay
    steps = [SlideItem(title=f"Неделя {i}", text="x", number=str(i)) for i in (1, 2, 3)]
    assert not A.position_labels(steps, "Неделя 1: включаем. Неделя 2: раскатываем. Неделя 3: публикуем.")
    months = [SlideItem(title=f"Месяц {i}", text="x", number=str(i)) for i in (1, 2)]
    assert not A.position_labels(months, "1-й месяц — учёт, 2-й месяц — меню.")  # a time step is a label of its own
    assert not A.position_labels([SlideItem(title=f"Модуль {i}", text="x", number=str(i)) for i in (1, 2)], "1-й модуль — SQL, 2-й модуль — потоки.")


SOURCE = "Годовая программа из 4 модулей: основы SQL и Python, потоковая обработка, хранилища и витрины, инженерия ML-пайплайнов."


def test_a_promised_count_restores_the_lost_item_from_the_source():
    s = OutlineSlide(id="x", kind=K.process, headline="Программа из 4 модулей ведёт от SQL к ML-пайплайнам", content=SlideContent(items=[
        SlideItem(title="", text=MODULES[0]), SlideItem(title="Модуль 3", text=MODULES[2], number="3"), SlideItem(title="Модуль 4", text=MODULES[3], number="4")]))
    said = A.keep_promise(s, SOURCE)
    assert said and [(it.number, it.title, it.text) for it in s.content.items] == [(str(i), f"Модуль {i}", x) for i, x in enumerate(MODULES, 1)]
    assert s.headline.startswith("Программа из 4 модулей")


def test_a_promise_the_source_cannot_keep_leaves_the_headline():
    s = OutlineSlide(id="x", kind=K.process, headline="Программа из 4 модулей ведёт от SQL к ML-пайплайнам", content=SlideContent(items=[
        SlideItem(title=f"Модуль {i}", text=x, number=str(i)) for i, x in enumerate(MODULES[:3], 1)]))
    A.keep_promise(s, "Программа учит работать с данными.")
    assert s.headline == "Программа ведёт от SQL к ML-пайплайнам"
    s = OutlineSlide(id="x", kind=K.cards, headline="Четыре функции закрывают цикл", content=SlideContent(items=[SlideItem(title="a", text="b")] * 3))
    A.keep_promise(s, "Функция делает три вещи.", fallback="Функция превращает сообщение в задачу")
    assert s.headline == "Функция превращает сообщение в задачу"
    # what the slide shows keeps its headline; counts of time, money and people are no promise
    s = OutlineSlide(id="x", kind=K.timeline, headline="Полный запуск через 3 недели", content=SlideContent(items=[SlideItem(title="Неделя 1", text="x")] * 4))
    assert not A.keep_promise(s, "") and s.headline == "Полный запуск через 3 недели"
    assert A.promised_counts("Студенты оценивают программу на 4,8 из 5") == [] and A.promised_counts("Выручка выросла в 2 раза") == []


def test_a_step_the_source_labels_keeps_its_label():
    # o01: the model's «Далее» (the brief's «Далее: интеграция с календарём и почтой») became «Неделя 4»
    text = "Неделя 1: включаем для 20% компаний. Неделя 2: раскатываем на всех. Неделя 3: публикуем дайджесты. Далее: интеграция с календарём и почтой."
    unit = A._Unit(key="u9", title="Этапы запуска", text=text)
    s = OutlineSlide(id="x", kind=K.timeline, headline="Полный запуск через 3 недели", content=SlideContent(items=[
        SlideItem(title="Неделя 1", text="20% компаний"), SlideItem(title="Неделя 2", text="Раскатка на всех"),
        SlideItem(title="Неделя 3", text="Дайджесты"), SlideItem(title="Далее", text="Интеграция с календарём и почтой")]))
    d = A._Design(unit=unit, slide=s, by="model")
    A._uniform_steps(d, text)
    assert [it.title for it in s.content.items] == ["Неделя 1", "Неделя 2", "Неделя 3", "Далее"]
    # an untitled step between titled ones still takes the title of its number
    s.content.items[1].title = ""
    A._uniform_steps(d, text)
    assert s.content.items[1].title == "Неделя 2"


def test_the_briefs_request_reaches_the_slide():
    # e2: «Просим утвердить запуск и бюджет на продвижение» only in the notes of the last slide
    src = "Функция снижает срывы дедлайнов с 31% до 12% и окупает разработку за один квартал за счёт роста конверсии в тариф «Про». Просим утвердить запуск и бюджет на продвижение."
    s = OutlineSlide(id="x", kind=K.comparison, headline="Срывы дедлайнов снижаются с 31% до 12%", takeaway="Окупаемость за квартал за счёт роста конверсии в «Про»",
                     notes="Просим утвердить запуск и бюджет на продвижение.",
                     content=SlideContent(columns=[SlideItem(title="До", text="31%"), SlideItem(title="После", text="12%")]))
    assert A.keep_ask(s, src) and s.content.bullets == ["Просим утвердить запуск и бюджет на продвижение"]
    assert not A.keep_ask(s, src)  # shown: nothing more
    s2 = OutlineSlide(id="y", kind=K.bullets, headline="h", content=SlideContent(bullets=["a"]))
    A.keep_ask(s2, src)
    assert s2.takeaway == "Просим утвердить запуск и бюджет на продвижение"


def test_the_ask_is_a_takeaway_that_states_something():
    for t in ("Просим утвердить запуск и бюджет на продвижение", "Нужны аудитории для практикумов"):
        assert A.takeaway_states(t), t
    assert not A.takeaway_states("Три ключевых направления для роста прибыли")


def test_a_section_the_architect_left_out_gets_a_slide():
    """o04's storyline (10 content slides of 12): «Как устроено обучение» and «Что нужно от партнёров» left out; two
    short slides of one part share a slide so that both get one, the count stays."""
    from verstka.planning.pictures import numbered_sentences

    ctx = _ctx(EDU)
    sentences = numbered_sentences(parse_brief_text(EDU).text)
    plan = [("Дефицит инженеров данных", "Проблема", [3]), ("Проблема университетских курсов", "Проблема", [4]),
            ("Структура программы", "Решение", [6]), ("Практика на данных VK", "Решение", [7]), ("Наставники VK Tech", "Решение", [8]),
            ("Масштаб первого набора", "Результаты", [10]), ("Успех и трудоустройство", "Результаты", [11, 12]),
            ("Оценка программы", "Результаты", [13]), ("Динамика набора", "Результаты", [14, 15, 16, 17]), ("Следующие шаги", "Планы", [24])]
    units, spans = [], {}
    for i, (title, sec, ns) in enumerate(plan, 1):
        spans[f"u{i}"] = set(ns)
        units.append(A._Unit(key=f"u{i}", title=title, section=sec, text="\n".join(sentences[n - 1] for n in ns)))
    warns: list[str] = []
    out = A.cover_sections(units, spans, sentences, ctx, 10, warns)
    assert len(out) == 10, [u.title for u in out]
    texts = "\n".join(u.text for u in out)
    assert "Зачёт модулей программы" in texts and "Онлайн-лекции по вечерам" in texts, warns
    # in the brief's order: before «Следующие шаги»
    keys = [u.key for u in out]
    ask = next(u for u in out if "Зачёт модулей" in u.text)
    assert keys.index(ask.key) < keys.index("u10")
    # every sentence of the brief's prose is on some slide
    used = {n for u in out for n in spans.get(u.key, set())}
    assert {19, 21, 22} <= used
    # with room for them, nothing is merged
    units2 = [A._Unit(key=f"u{i}", title=t, section=sec, text="\n".join(sentences[n - 1] for n in ns)) for i, (t, sec, ns) in enumerate(plan, 1)]
    spans2 = {f"u{i}": set(ns) for i, (_, _, ns) in enumerate(plan, 1)}
    out2 = A.cover_sections(units2, spans2, sentences, ctx, 12, [])
    assert len(out2) == 12


# ------------------------------------------------------------------ L3: key figures stay figures


def _kpis() -> OutlineSlide:
    return OutlineSlide(id="x", kind=K.stat_row, headline="Участники оценили удобство на 4,6 из 5",
                        content=SlideContent(numbers=[NumberCallout(value="4,6", label="Средняя оценка удобства"), NumberCallout(value="91%", label="Готовы рекомендовать")]))


def test_key_figures_never_become_bare_cards_or_a_two_row_table():
    s = _kpis()
    for kind in ("cards", "table", "bullets"):
        r = A.reshape(s, kind)
        assert r is None or A._poor_form(r, s), kind
    # a table of changes is a form of its own
    ch = OutlineSlide(id="y", kind=K.stat_row, headline="h", content=SlideContent(numbers=[NumberCallout(value="300 → 330 ₽", label="Средний чек"), NumberCallout(value="100 → 115", label="Покупок в день")]))
    t = A.reshape(ch, "table")
    assert t is not None and not A._poor_form(t, ch)
    # cards with words stay allowed
    cards = OutlineSlide(id="z", kind=K.cards, headline="h", content=SlideContent(items=[SlideItem(title="a", text="b", number="71%")]))
    assert not A._poor_form(cards, s)


def test_the_compact_variant_keeps_two_kpis_as_figures():
    from verstka.planning.strategies import load_strategies

    ctx = _ctx(VKWS)
    ctx.count = 12  # a fixed count: the compact variant may not merge, it used to take «the denser form» (a 2-row table)
    unit = A._Unit(key="u6", title="Оценка удобства", text="Средняя оценка удобства 4,6 из 5, 91% участников готовы рекомендовать функцию коллегам.")
    d = A._Design(unit=unit, slide=_kpis(), by="model", alternatives=[A.Alternative(kind="cards", why="карточки"), A.Alternative(kind="table", why="таблица")])
    placed, _ = A.assemble([d], load_strategies()["compact"], A.designer_prefs(), ctx)
    assert placed[0].slide.kind == K.stat_row, placed[0].slide.kind


# ------------------------------------------------------------------ E1: text edits on data slides


def _data_outline() -> DeckOutline:
    from verstka.schemas.data import HeadlineFact, SlideData

    data = SlideData(dataset_id="d1", file="NPS по кварталам.csv", headline_facts=[
        HeadlineFact(id="f1", text="NPS вырос до 52", value=52, kind="max"), HeadlineFact(id="f2", text="+11 п.", value=11, kind="change")])
    s = OutlineSlide(id="sl2", kind=K.chart, headline="NPS вырос до 52, за два квартала данных нет", data=data, footnote="Источник: NPS по кварталам.csv",
                     takeaway="За II кв. 2025 и II кв. 2026 данных нет — на графике разрывы, а не ноль",
                     content=SlideContent(chart=ChartSpec(type="line", categories=["IV кв. 2024", "II кв. 2025", "II кв. 2026", "III кв. 2026"],
                                                          series=[InlineSeries(name="NPS", values=[41, 45, None, 52])], gaps=True)))
    return DeckOutline(title="Итоги", strategy="structured", slides=[OutlineSlide(id="sl1", kind=K.title, headline="Итоги"), s])


def _designer(answer):
    from verstka.providers.mock import MockProvider
    from verstka.providers.registry import ProviderLimits, ProviderRegistry

    def script(messages):
        if "presentation designer" in messages[0].content:
            if isinstance(answer, Exception):
                raise answer
            return answer
        return {"facts": [], "series": [], "tables": []}

    p = MockProvider(script, model="qwen38-27b-fp8")
    return ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=2, time_budget_s=60))


BRIEF = "Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Данные — в приложенных файлах."


@pytest.mark.parametrize("answer", [
    {"kind": "chart", "headline": "NPS вырос до 52"},  # a headline only: no content block (the live failure)
    {"kind": "chart", "headline": "NPS вырос до 52", "bullets": []},
])
def test_a_headline_edit_of_a_data_slide_applies(answer):
    from verstka.planning.slide_edit import redesign_slide
    from verstka.skills_registry.registry import SkillsRegistry

    old = _data_outline()
    r = redesign_slide(old, 2, parse_brief_text(BRIEF), None, request="сделай заголовок короче", skills=SkillsRegistry.load(), providers=_designer(answer))
    s = r.outline.slides[1]
    assert r.how == "model" and s.headline == "NPS вырос до 52", (r.how, s.headline)
    assert s.data is not None and s.content.chart is not None and s.content.chart.series[0].values == [41, 45, None, 52]
    assert s.footnote == old.slides[1].footnote and s.takeaway == old.slides[1].takeaway and s.kind == K.chart
    assert "недоступна" not in r.reply


def test_a_headline_edit_takes_only_the_headline():
    # live E1 check: «сделай заголовок короче» — the model shortened the caption as well; only the headline is asked for
    from verstka.planning.slide_edit import edit_targets, redesign_slide
    from verstka.skills_registry.registry import SkillsRegistry

    assert edit_targets("сделай заголовок короче") == {"headline"} and edit_targets("добавь в подпись, почему нет данных") == {"takeaway"}
    assert edit_targets("сократи подзаголовок") == {"subtitle"} and "headline" in edit_targets("перепиши понятнее")
    old = _data_outline()
    r = redesign_slide(old, 2, parse_brief_text(BRIEF), None, request="сделай заголовок короче", skills=SkillsRegistry.load(),
                       providers=_designer({"kind": "chart", "headline": "NPS вырос до 52", "takeaway": "Короче"}))
    assert r.outline.slides[1].headline == "NPS вырос до 52" and r.outline.slides[1].takeaway == old.slides[1].takeaway


def test_a_caption_edit_of_a_data_slide_applies():
    from verstka.planning.slide_edit import redesign_slide
    from verstka.skills_registry.registry import SkillsRegistry

    tk = "За II кв. 2025 и II кв. 2026 данных нет: опрос во II кварталах не проводили — на графике разрывы, а не ноль"
    r = redesign_slide(_data_outline(), 2, parse_brief_text(BRIEF), None, request="добавь в подпись, почему нет данных",
                       skills=SkillsRegistry.load(), providers=_designer({"kind": "chart", "headline": "NPS вырос до 52, за два квартала данных нет", "takeaway": tk}))
    assert r.outline.slides[1].takeaway == tk and r.outline.slides[1].content.chart is not None


def test_an_addition_to_a_caption_keeps_what_it_said():
    # live E1 check: «добавь в подпись, почему нет данных» — the model dropped the caption's figures and added nothing
    from verstka.planning.slide_edit import redesign_slide
    from verstka.skills_registry.registry import SkillsRegistry

    old = _data_outline()
    tk = old.slides[1].takeaway
    with pytest.raises(ValueError) as e:  # nothing new: the caption stays, the reply says so
        redesign_slide(old, 2, parse_brief_text(BRIEF), None, request="добавь в подпись, почему нет данных", skills=SkillsRegistry.load(),
                       providers=_designer({"kind": "chart", "headline": old.slides[1].headline, "takeaway": "Данных нет — на графике разрывы, а не ноль"}))
    assert "нет ничего нового" in str(e.value) and "недоступна" not in str(e.value)
    r = redesign_slide(old, 2, parse_brief_text(BRIEF), None, request="добавь в подпись, почему нет данных", skills=SkillsRegistry.load(),
                       providers=_designer({"kind": "chart", "headline": old.slides[1].headline, "takeaway": "Опрос во II кварталах не проводили"}))
    got = r.outline.slides[1].takeaway
    assert got.startswith(tk.rstrip(".")) and got.endswith("Опрос во II кварталах не проводили"), got


def test_a_data_slide_edit_with_a_number_the_data_does_not_have_says_why():
    from verstka.planning.slide_edit import redesign_slide
    from verstka.skills_registry.registry import SkillsRegistry

    with pytest.raises(ValueError) as e:
        redesign_slide(_data_outline(), 2, parse_brief_text(BRIEF), None, request="перепиши заголовок",
                       skills=SkillsRegistry.load(), providers=_designer({"kind": "chart", "headline": "NPS вырос до 57"}))
    msg = str(e.value)
    assert "модель ответила" in msg and "57" in msg and "недоступна" not in msg


def test_the_reply_never_says_unavailable_when_the_model_answered():
    from verstka.planning.slide_edit import redesign_slide
    from verstka.providers.base import ProviderError
    from verstka.skills_registry.registry import SkillsRegistry

    outline = DeckOutline(title="t", strategy="structured", slides=[
        OutlineSlide(id="sl1", kind=K.title, headline="t"),
        OutlineSlide(id="sl2", kind=K.bullets, headline="Как внедряем", content=SlideContent(bullets=["Пилот на одной команде", "Запуск на всю компанию"]))])
    brief = parse_brief_text("Как внедряем: пилот на одной команде, затем запуск на всю компанию.")
    # the model answered without anything for the slide
    with pytest.raises(ValueError) as e:
        redesign_slide(outline, 2, brief, None, request="перепиши заголовок", skills=SkillsRegistry.load(), providers=_designer({"kind": "bullets", "headline": ""}))
    assert "недоступна" not in str(e.value)
    # the model did not answer at all
    with pytest.raises(ValueError) as e:
        redesign_slide(outline, 2, brief, None, request="перепиши заголовок", skills=SkillsRegistry.load(), providers=_designer(ProviderError("host down")))
    assert "не ответила" in str(e.value) and "недоступна" not in str(e.value)
    # the slide fix keeps its code for a model that did not answer, and says what happened when it did
    with pytest.raises(ValueError, match="model_unavailable"):
        redesign_slide(outline, 2, brief, None, note="- fix it", skills=SkillsRegistry.load(), providers=_designer(ProviderError("host down")))
    with pytest.raises(ValueError) as e:
        redesign_slide(outline, 2, brief, None, note="- fix it", skills=SkillsRegistry.load(), providers=_designer({"kind": "bullets", "headline": ""}))
    assert str(e.value) != "model_unavailable" and "модель ответила" in str(e.value)


# ------------------------------------------------------------------ the data file's own notes in a text edit


NOTES = ("Опрос NPS во II квартале 2025 и 2026 года не проводился: в эти месяцы команда переходила на новую систему "
         "опросов. Сравнение NPS — с последним измеренным кварталом.")


def _context_outline(context=NOTES) -> DeckOutline:
    o = _data_outline()
    o.slides[1].data = o.slides[1].data.model_copy(update={"context": context})
    return o


def test_the_designer_reads_the_files_notes_for_a_why():
    """«добавь в подпись, почему нет данных»: the file's own explanation (SlideData.context) reaches the designer, and
    its numbers («2025», «2026» — and any figure the notes give) pass the data's number rule in the caption."""
    from verstka.planning.slide_edit import redesign_slide
    from verstka.providers.mock import MockProvider
    from verstka.providers.registry import ProviderLimits, ProviderRegistry
    from verstka.skills_registry.registry import SkillsRegistry

    seen: list[str] = []
    old = _context_outline()
    tk = old.slides[1].takeaway + ". Опрос во II квартале 2025 и 2026 года не проводился: команда переходила на новую систему опросов"

    def script(messages):
        if "presentation designer" in messages[0].content:
            seen.append(messages[-1].content)
            # the stub answers only when it was given the reason, as the live model can only then
            reason = "переходила на новую систему опросов" in messages[-1].content
            return {"kind": "chart", "headline": old.slides[1].headline, "takeaway": tk if reason else old.slides[1].takeaway}
        return {"facts": [], "series": [], "tables": []}

    p = MockProvider(script, model="qwen38-27b-fp8")
    reg = ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=2, time_budget_s=60))
    r = redesign_slide(old, 2, parse_brief_text(BRIEF), None, request="добавь в подпись, почему нет данных", skills=SkillsRegistry.load(), providers=reg)
    s = r.outline.slides[1]
    assert seen and NOTES in seen[0]
    assert s.takeaway == tk.rstrip("."), s.takeaway
    assert s.content.chart is not None and s.data.context == NOTES


def test_a_number_of_the_files_notes_counts_as_the_datas():
    from verstka.planning.slide_edit import keep_data

    old = _context_outline("В III квартале опрошено 1 240 клиентов.")
    new = old.slides[1].model_copy(deep=True)
    new.takeaway = "NPS вырос до 52; опрошено 1 240 клиентов"
    assert keep_data(old.slides[1], new).takeaway == new.takeaway  # 1 240 is the file's own figure
    new.takeaway = "NPS вырос до 52; опрошено 1 500 клиентов"
    assert keep_data(old.slides[1], new).takeaway == old.slides[1].takeaway  # 1 500 is nobody's
    bare = _data_outline().slides[1]  # a deck without the notes: the old rule
    new = bare.model_copy(deep=True)
    new.takeaway = "NPS вырос до 52; опрошено 1 240 клиентов"
    assert keep_data(bare, new).takeaway == bare.takeaway
