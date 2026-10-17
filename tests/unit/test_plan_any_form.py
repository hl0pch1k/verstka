"""План в любом виде и смыслы колоды (финальная доводка, направление M).

Эксперты проверяют Verstka как пользователи: примерный план (письмом, нумерованным списком, тезисами, «Слайд N: …»)
плюс данные. Пункт плана — слайд, порядок автора сохраняется; указания дизайнеру («покажи на графике», «сделай
воронку», «сравни») — форма слайда и никогда не его текст; таблица получает вывод, посчитанный по её ячейкам; колода
кончается выводом и просьбой, а не голым «Спасибо за внимание». Входы — `tests/fixtures/plans/*.md`."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from verstka.planning.directives import clean_text, directive_object, is_directive, split_directive
from verstka.planning.meaning import cell_number, close_story, conclusion_headlines, finish_deck, table_conclusion
from verstka.planning.plan_form import as_slides
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent, TableData

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "tests" / "fixtures" / "plans"


def _plan(name: str):
    return as_slides((PLANS / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the plan's forms


@pytest.mark.parametrize(
    "name, form, titles",
    [
        ("hiring_numbered.md", "numbered", ["Где мы сейчас", "Сколько людей нужно", "Сколько времени занимает найм", "Откуда кандидаты", "Бюджет", "Что просим"]),
        ("incident_bullets.md", "bullets", ["Что случилось", "Хронология", "Ущерб", "Причина", "Почему так долго", "Что меняем", "Сроки"]),
        ("warehouse_email.md", "letter", ["Сколько отгрузили", "Скорость сборки", "Ошибки комплектации", "Воронка заказов", "Ночная смена"]),
        ("q3_close_letter.md", "letter", ["Общие итоги", "По направлениям", "Расходы", "Дебиторка", "Что просим у совета"]),
        ("sales_short.md", "numbered", ["Выручка"]),
        ("budget_2027_theses.md", "bullets", ["Переезжаем из собственного дата-центра в облако"]),
        ("marketing_table.md", "letter", ["Кампания шла с 1 сентября по 15 октября", "Результаты по каналам"]),
    ],
)
def test_an_item_of_the_plan_is_a_slide_in_the_authors_order(name, form, titles):
    p = _plan(name)
    assert p is not None and p.form == form
    got = [it.title for it in p.items]
    assert got[: len(titles)] == titles


def test_the_letters_greeting_request_and_sign_off_are_not_slides():
    p = _plan("q3_close_letter.md")
    assert p.title == "Закрытие третьего квартала" and p.audience == "Совет директоров"
    text = p.text
    assert "привет" not in text.lower() and "Спасибо!" not in text
    assert len(p.items) == 5
    # the table stays with its item, as a block of its own
    assert re.search(r"Слайд 3\. По направлениям\n.*\n\n\| Направление", text)


def test_every_word_of_an_item_stays_in_the_plan():
    src = (PLANS / "warehouse_email.md").read_text(encoding="utf-8")
    text = _plan("warehouse_email.md").text
    have = set(re.findall(r"[а-яё0-9%,]+", text.lower()))
    for line in src.splitlines()[1:]:
        core = re.sub(r"^(?:Сначала|Потом)\s*[—–-]?\s*", "", line.strip())
        lost = [w for w in re.findall(r"[а-яё0-9%,]+", core.lower()) if w not in have]
        assert not lost, (core, lost)


def test_a_directive_only_item_joins_the_item_before_it():
    text = "Итоги кампании — для директора\n\n- Расходы по каналам: контекст 4 800, таргет 3 600, блогеры 2 400 тыс. ₽\n- Нужна круговая диаграмма\n- Заявки выросли на 25%\n- Предложение: перенести 1,5 млн ₽ в контекст"
    p = as_slides(text)
    assert [it.title for it in p.items] == ["Расходы по каналам", "Заявки выросли на 25%", "Предложение"]
    assert "Нужна круговая диаграмма" in " ".join(p.items[0].lines)


@pytest.mark.parametrize("name", ["cloud_initiative.md", "edu_program.md", "fitness_studio.md", "vk_workspace_feature.md", "verstka_pitch.md"])
def test_a_brief_with_its_own_slides_or_headings_is_left_as_it_is(name):
    assert as_slides((ROOT / "examples" / "briefs" / name).read_text(encoding="utf-8")) is None


def test_parts_and_blocks_are_numbered_items_too():
    text = ("Квартальный отчёт поддержки\n\nЧасть 1: Обращения — 41 200 за квартал, на 9% больше.\n"
            "Часть 2: Скорость — первый ответ за 4 минуты вместо 7.\nЧасть 3: Что дальше — чат-бот на 30% обращений.")
    p = as_slides(text)
    assert p is not None and [it.title for it in p.items] == ["Обращения", "Скорость", "Что дальше"]


def test_prose_is_not_a_plan():
    prose = ("Компания выросла за год вдвое. Мы открыли три офиса и наняли 120 человек, из них половина — инженеры.\n\n"
             "Главный риск следующего года — найм: рынок инженеров сжимается, а срок закрытия вакансии вырос до 54 дней.\n\n"
             "Поэтому мы предлагаем программу рекомендаций и обучение внутри компании, это снизит зависимость от агентств.")
    assert as_slides(prose) is None


# ------------------------------------------------------------------ asks to the designer


@pytest.mark.parametrize(
    "sentence, ask, rest",
    [
        ("Нужна воронка", True, ""),
        ("Сделай воронку.", True, ""),
        ("Покажи на графике по неделям.", True, ""),
        ("Добавь картинку с экраном приложения.", True, ""),
        ("Сравни с рынком: по данным hh.ru, у инженеров 47 дней.", True, "По данным hh.ru, у инженеров 47 дней."),
        ("Потом по направлениям — данные в таблице ниже, покажи на графике план и факт.", True, ""),
        ("Используй разные пароли для рабочих и личных сервисов.", False, None),
        ("Сохрани подозрительное письмо и перешли его в ИБ.", False, None),
        ("Выручка выросла на 18% к прошлому кварталу.", False, None),
    ],
)
def test_an_ask_is_taken_off_and_its_own_words_stay(sentence, ask, rest):
    a, r = split_directive(sentence)
    assert (a is not None) == ask
    if ask:
        assert r == rest
    else:
        assert r == " ".join(sentence.split())


def test_the_ask_names_what_to_show():
    assert directive_object("сравни скорость сборки") == "скорость сборки"
    assert directive_object("Сделай воронку заказов") == "воронка заказов"
    assert directive_object("покажи на графике план и факт") == "план и факт"
    assert is_directive("Нужен столбчатый график") and not is_directive("Не нужен график")


def test_data_of_an_ask_the_chart_shows_goes_with_it():
    line = "Нужен столбчатый график: жители района — 18 000, целевое количество клиентов — 250."
    assert clean_text(line, {18000.0, 250.0}) == ""
    assert clean_text(line, set()) == "Жители района — 18 000, целевое количество клиентов — 250."


# ------------------------------------------------------------------ the plans laid out (no model)




@pytest.fixture(scope="module")
def outlines():
    """Every fixture plan planned by the rules (the agent without a model), the structured variant."""
    os.environ["VERSTKA_NO_DOTENV"] = "1"
    from verstka.planning.agent import run_agent
    from verstka.planning.brief import parse_brief_text
    from verstka.planning.strategies import load_strategies

    st = load_strategies()["structured"]
    out = {}
    for f in sorted(PLANS.glob("*.md")):
        res = run_agent(parse_brief_text(f.read_text(encoding="utf-8")), None, [st])
        assert res is not None and "structured" in res.outlines, f.name
        out[f.name] = res.outlines["structured"]
    return out


_ASK_ON_SLIDE_RE = re.compile(r"\b(?:нуж(?:ен|на|ны)\s+\S*\s*(?:график|диаграмм|воронк)|покажи|сделай\s+воронк|сравни|добавь\s+картинк|в\s+таблице\s+ниже)", re.I)


def _visible(s: OutlineSlide) -> list[str]:
    c = s.content
    out = [s.headline, s.subtitle or "", s.takeaway or "", s.footnote or "", *c.bullets, *c.paragraphs]
    out += [x for it in [*c.items, *c.columns] for x in (it.title, it.text, *it.bullets)]
    out += [n.label for n in c.numbers] + [c.chart.title or "" if c.chart else "", (c.table.caption or "") if c.table else ""]
    return [x for x in out if x]


def test_no_ask_to_the_designer_is_on_a_slide(outlines):
    for name, o in outlines.items():
        for s in o.slides:
            for t in _visible(s):
                assert not _ASK_ON_SLIDE_RE.search(t), (name, s.id, t)


def test_the_plans_items_are_its_slides_in_order(outlines):
    for name in ("hiring_numbered.md", "incident_bullets.md", "warehouse_email.md", "q3_close_letter.md"):
        p = _plan(name)
        o = outlines[name]
        assert o.slides[0].kind == PatternKind.title
        assert len(o.slides) == len(p.items) + 1, name
        # each slide is its item: the topic stays the heading or the slide's section
        for it, s in zip(p.items, o.slides[1:]):
            assert it.title in (s.headline, s.section), (name, it.title, s.headline, s.section)


def test_asks_become_the_slides_form(outlines):
    wh = outlines["warehouse_email.md"].slides
    funnel = next(s for s in wh if (s.section or s.headline) == "Воронка заказов")
    assert funnel.content.chart is not None and funnel.content.chart.type == "bar"
    assert funnel.content.chart.series[0].values == [51000.0, 49300.0, 48200.0, 45900.0]
    speed = next(s for s in wh if (s.section or s.headline) == "Скорость сборки")
    assert speed.content.chart is not None and speed.content.chart.categories == ["В Подольске", "В Казани"]
    pl = outlines["product_launch_slides.md"].slides
    weeks = next(s for s in pl if s.content.chart is not None and s.content.chart.type == "line")
    assert weeks.content.chart.categories[0] == "1-я неделя"
    hiring = outlines["hiring_numbered.md"].slides
    need = next(s for s in hiring if (s.section or s.headline) == "Сколько людей нужно")
    assert need.content.chart is not None and need.content.chart.categories == ["Инженеры", "Аналитики", "Продавцы", "В поддержку"]


def test_plan_and_fact_are_charted_side_by_side_with_the_tables_conclusion(outlines):
    s = next(s for s in outlines["q3_close_letter.md"].slides if s.content.table is not None)
    assert s.content.chart is not None and len(s.content.chart.series) == 2
    assert s.headline.startswith("Факт выше плана: 1 840 млн ₽ против 1 750")
    assert s.section == "По направлениям"
    assert "консалтинг (193 из 220)" in (s.takeaway or "")


def test_a_short_point_of_the_authors_heads_its_slide(outlines):
    pl = outlines["product_launch_slides.md"].slides
    assert any(s.headline == "За месяц 412 000 установок при цели 300 000" and s.section == "Установки" for s in pl)


def test_the_deck_ends_on_the_ask(outlines):
    for name in ("hiring_numbered.md", "q3_close_letter.md", "warehouse_email.md", "budget_2027_theses.md"):
        last = outlines[name].slides[-1]
        assert last.kind != PatternKind.thanks, name
    # the author's own last slide stays as dictated
    assert outlines["product_launch_slides.md"].slides[-1].kind == PatternKind.thanks


# ------------------------------------------------------------------ meaning passes on outlines


def _slide(i, kind="bullets", headline="Слайд", **kw):
    return OutlineSlide(id=f"sl{i}", kind=kind, headline=headline, **kw)


def test_a_before_after_table_concludes_on_its_total_never_minus_100():
    t = TableData(columns=["Статья, млн ₽ в год", "Сейчас", "В VK Cloud"], rows=[
        ["Поддержка и амортизация", "38", "0"], ["Электричество и площадка", "9", "0"], ["Облачные ресурсы", "0", "27"],
        ["Команда эксплуатации", "14", "8"], ["Итого", "61", "35"]])
    head, detail = table_conclusion(t)
    assert head == "Итого: 61 → 35 млн ₽ в год (−26)"
    assert detail == "Сильнее всего: поддержка и амортизация — 38 → 0"
    assert "100%" not in head + detail


def test_a_plan_fact_table_says_where_it_is_above_and_below_plan():
    t = TableData(columns=["Направление", "План, млн ₽", "Факт, млн ₽"], rows=[["Облако", "820", "905"], ["Почта", "410", "398"]])
    head, detail = table_conclusion(t)
    assert head == "Факт выше плана: 1 303 млн ₽ против 1 230 (+6%)"
    assert detail == "Ниже плана: почта (398 из 410)"


def test_a_rate_column_concludes_on_its_range_not_its_sum():
    t = TableData(columns=["Канал", "Стоимость заявки, ₽"], rows=[["Контекст", "941"], ["Таргет", "923"], ["Блогеры", "2 000"]])
    assert table_conclusion(t) == ("Стоимость заявки: от 923 ₽ (таргет) до 2 000 ₽ (блогеры)", None)


def test_cells():
    assert cell_number("4 800") == 4800 and cell_number("12,5%") == 12.5 and cell_number("−5") == -5 and cell_number("н/д") is None


def test_a_bare_thanks_after_the_ask_stays_and_carries_the_ask_otherwise():
    brief = "Итоги.\n\nПросим утвердить бюджет 12 млн рублей и старт пилота с 1 ноября."
    o = DeckOutline(title="T", slides=[_slide(1, "title", "T"), _slide(2, headline="Рынок растёт", content=SlideContent(bullets=["a"])),
                                       _slide(3, headline="Что просим", content=SlideContent(bullets=["Утвердить бюджет 12 млн рублей"])),
                                       _slide(4, "thanks", "Спасибо за внимание")])
    close_story(o, brief)
    assert [s.id for s in o.slides] == ["sl1", "sl2", "sl3", "sl4"] and o.slides[-1].headline == "Спасибо за внимание"
    o2 = DeckOutline(title="T", slides=[_slide(1, "title", "T"), _slide(2, headline="Рынок растёт", content=SlideContent(bullets=["a"])),
                                        _slide(3, headline="План", content=SlideContent(bullets=["b"])), _slide(4, "thanks", "Спасибо за внимание")])
    close_story(o2, brief)
    assert o2.slides[-1].headline == "Просим утвердить бюджет 12 млн рублей и старт пилота с 1 ноября"
    assert o2.slides[-1].subtitle == "Спасибо за внимание"


def test_a_planners_ask_slide_goes_last_the_authors_order_stays():
    slides = [_slide(1, "title", "T"), _slide(2, headline="Просим утвердить бюджет", content=SlideContent(bullets=["x"])),
              _slide(3, headline="Рынок", content=SlideContent(bullets=["y"]))]
    o = DeckOutline(title="T", slides=[s.model_copy(deep=True) for s in slides])
    close_story(o, "")
    assert [s.id for s in o.slides] == ["sl1", "sl3", "sl2"]
    o2 = DeckOutline(title="T", slides=[s.model_copy(deep=True) for s in slides])
    close_story(o2, "", author_order=True)
    assert [s.id for s in o2.slides] == ["sl1", "sl2", "sl3"]


def test_a_topic_heading_takes_the_slides_stated_result_not_a_side_remark():
    s = _slide(2, headline="Удержание", content=SlideContent(bullets=["На седьмой день остаются 46% пользователей, на тридцатый — 31%. У старого приложения было 38% и 22%"]))
    o = DeckOutline(title="T", slides=[_slide(1, "title", "T"), s])
    conclusion_headlines(o)
    assert o.slides[1].headline == "На седьмой день остаются 46% пользователей, на тридцатый — 31%"
    assert o.slides[1].section == "Удержание" and o.slides[1].content.bullets == ["У старого приложения было 38% и 22%"]
    side = _slide(2, headline="Вложения", content=SlideContent(bullets=["Ещё 850 000 рублей составят оборотный резерв.", "Ремонт — 900 000 рублей."]))
    o2 = DeckOutline(title="T", slides=[_slide(1, "title", "T"), side])
    conclusion_headlines(o2)
    assert o2.slides[1].headline == "Вложения"


def test_finish_deck_is_a_copy():
    o = DeckOutline(title="T", slides=[_slide(1, "title", "T"), _slide(2, headline="Итоги", content=SlideContent(bullets=["Нужна круговая диаграмма.", "Выручка выросла на 12%."]))])
    o2, said = finish_deck(o, "")
    assert o.slides[1].content.bullets[0] == "Нужна круговая диаграмма."
    assert "Нужна круговая диаграмма." not in o2.slides[1].content.bullets and said
