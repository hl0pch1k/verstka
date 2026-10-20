"""Колода данных (план + таблицы ± база знаний): указания автора выполняются, а не печатаются; база знаний сверяется с
таблицами — цель против факта, а не пересказ цели и не вердикт, которому факт противоречит (жюри 5, 20.10). Модели нет."""

from __future__ import annotations

import re

from verstka.knowledge.against_data import goals_of, match, reconcile, table_facts, verdict
from verstka.planning.directives import drop_author_notes, is_author_note, plan_text, scrub_author_notes
from verstka.schemas.common import PatternKind
from verstka.schemas.data import Table
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent, SlideItem

_NOTE_WORDS = re.compile(r"(?i)слайд|картин|выдумыв|придумыв|приложил|вложени|наметк|черновик|проверь|посчитай|по-моему|база знаний")


# ------------------------------------------------------------------ the author's notes


def test_rules_of_the_deck_guesses_and_pointers_are_notes_the_audience_never_reads():
    for note in ("сделай 6 слайдов", "10 слайдов", "без картинок", "картинки не нужны", "не выдумывай цифру", "ничего не придумывай",
                 "проверь", "посчитай по таблице продаж", "по-моему розница быстрее всех", "мне кажется, дело в сезоне",
                 "таблицы приложил", "отчёт во вложении", "цели — в регламенте", "данные в таблице", "наметки", "черновик",
                 "О чём хочу рассказать"):
        assert is_author_note(note), note
    for line in ("выручка выросла на 12 %", "без учёта НДС", "данных за май нет", "Цели — рост в регионах", "в Москве 30 тыс. врачей",
                 "проверка показала 3 ошибки", "с фотографиями товаров продажи выше на 8 %", "2 инженера в команду"):
        assert not is_author_note(line), line


def test_a_line_keeps_its_content_and_loses_the_notes_in_it():
    assert drop_author_notes("Итоги года — для совета (черновик, таблицы приложил)") == "Итоги года — для совета"
    assert drop_author_notes("Склад: в мае данных нет (сбой выгрузки), не выдумывай цифру") == "Склад: в мае данных нет (сбой выгрузки)"
    assert drop_author_notes("Отгрузки — пик в марте (причину не знаю, не придумывай)") == "Отгрузки — пик в марте"
    assert drop_author_notes("Регионы — Сибирь выросла сильнее всех, проверь") == "Регионы"
    assert drop_author_notes("Какие каналы растут — по-моему розница быстрее всех") == "Какие каналы растут"
    assert drop_author_notes("Бюджет (12 млн ₽ на найм)") == "Бюджет (12 млн ₽ на найм)"
    assert drop_author_notes("Таблица продаж во вложении, цели — в положении (база знаний).") == ""
    # a cover cut through its bracket keeps its words, not the notes
    assert drop_author_notes("Для совета (наметки") == "Для совета"
    assert drop_author_notes("Склад, таблицы приложил)") == "Склад"
    # nothing to take off: the text as it is (the same object)
    t = "Выручка выросла на 12 % за квартал."
    assert drop_author_notes(t) is t


def test_the_plan_is_read_without_the_rules_but_with_what_names_its_items():
    brief = ("Итоги квартала по складу — для директора (наметки, файлы приложил)\n\n"
             "- главное: рекорд? посчитай по таблице отгрузок, сравни с прошлым кварталом\n"
             "- регионы — Сибирь выросла, проверь\n"
             "- в конце — что просим: 3 кладовщика\n"
             "сделай 6 слайдов, без картинок\n")
    got = plan_text(brief)
    assert "наметки" not in got and "приложил" not in got and "слайдов" not in got and "картинок" not in got
    # the analyst's ask and the designer's ask stay for the plan: they name the file and the slide's form
    assert "посчитай по таблице отгрузок" in got and "сравни с прошлым кварталом" in got
    assert "- в конце — что просим: 3 кладовщика" in got.splitlines()
    assert got.splitlines()[0] == "Итоги квартала по складу — для директора"


def _deck() -> DeckOutline:
    return DeckOutline(title="Итоги (наметки, таблицы приложил)", slides=[
        OutlineSlide(id="title", kind=PatternKind.title, headline="Итоги квартала, файлы приложил)", subtitle="Для совета (наметки"),
        OutlineSlide(id="context-1", kind=PatternKind.bullets, headline="Контекст", content=SlideContent(bullets=[
            "Таблица продаж во вложении, цели — в положении (база знаний)."])),
        OutlineSlide(id="data-plan-2", kind=PatternKind.bullets, headline="Склад", content=SlideContent(bullets=[
            "В мае данных нет (сбой выгрузки), не выдумывай цифру"])),
        OutlineSlide(id="data-plan-3", kind=PatternKind.bullets, headline="Воронка", content=SlideContent(bullets=["Где теряем? по-моему опт"])),
        OutlineSlide(id="data-plan-4", kind=PatternKind.bullets, headline="Что просим: 3 кладовщика сделай 6 слайдов, без картинок",
                     content=SlideContent(bullets=["3 кладовщика", "3 кладовщика сделай 6 слайдов."])),
    ])


def test_the_last_check_of_a_data_deck_leaves_no_note_on_cover_and_slides():
    o = _deck()
    said = scrub_author_notes(o)
    assert said
    ids = [s.id for s in o.slides]
    # the context of pointers only and the slide of the author's bare question go
    assert ids == ["title", "data-plan-2", "data-plan-4"]
    cover = o.slides[0]
    assert (cover.headline, cover.subtitle, o.title) == ("Итоги квартала", "Для совета", "Итоги")
    assert o.slides[1].content.bullets == ["В мае данных нет (сбой выгрузки)"]
    ask = o.slides[2]
    assert ask.headline == "Что просим: 3 кладовщика" and ask.content.bullets == ["3 кладовщика"]
    text = " ".join([o.title or "", *(" ".join([s.headline or "", s.subtitle or "", *s.content.bullets]) for s in o.slides)])
    assert not _NOTE_WORDS.search(text), text


def test_a_plan_with_data_prints_none_of_its_directives():
    from verstka.data.story import build_data_story
    from verstka.planning.brief import parse_brief_text

    months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь"]
    sales = Table(id="s", file="otgruzki.csv", kind="csv", columns=["Месяц", "Отгрузки"], units=[None, "т"],
                  rows=[[m, v] for m, v in zip(months, [120, 130, 125, 150, None, 170])])
    regions = Table(id="r", file="regiony.csv", kind="csv", columns=["Регион", "Отгрузки Q1", "Отгрузки Q2"], units=[None, "т", "т"],
                    rows=[["Сибирь", 90, 140], ["Урал", 120, 130], ["Центр", 165, 175]])
    brief = ("Итоги полугодия по складу — для директора (наметки, файлы приложил)\n\n"
             "- отгрузки по месяцам — покажи рост, а не просто график\n"
             "- май: данных нет (сбой выгрузки), не выдумывай цифру\n"
             "- регионы — Сибирь выросла, проверь\n"
             "- в конце — что просим: 3 кладовщика и 2 погрузчика (12 млн ₽)\n"
             "сделай 6 слайдов, без картинок\n")
    story = build_data_story(parse_brief_text(brief), [sales, regions])
    o = story.outline
    for s in o.slides:
        words = [s.headline or "", s.subtitle or "", s.takeaway or "", *s.content.bullets,
                 *(f"{it.title} {it.text}" for it in s.content.items)]
        for w in words:
            assert not re.search(r"(?i)слайд|картин|выдумыв|наметк|приложил|проверь|покажи", w), (s.id, w)
    assert o.slides[0].headline.startswith("Итоги полугодия по складу") and "(" not in o.slides[0].headline


# ------------------------------------------------------------------ the knowledge base against the tables


def _tables() -> list[Table]:
    months = ["Июль", "Август", "Сентябрь"]
    calls = Table(id="c", file="servis.xlsx", sheet="Звонки", kind="xlsx", columns=["Месяц", "Звонков", "Решено с первого звонка", "CSI"],
                  units=[None, "шт.", "%", None], rows=[["Июль", 5000, 60, 40], ["Август", 5200, 64, 42], ["Сентябрь", 5600, 66, 47]])
    sla = Table(id="l", file="servis.xlsx", sheet="Скорость", kind="xlsx", columns=["Смена", "Ожидание Q2", "Ожидание Q3", "Цель"],
                units=[None, None, None, None], rows=[["1-я смена", "9 мин", "7 мин", "8 мин"], ["2-я смена", "2,5 ч", "3,5 ч", "3 ч"]])
    money = Table(id="m", file="fin.xlsx", sheet="Выручка", kind="xlsx", columns=["Месяц", "Выручка", "Подписчиков", "Отписались"],
                  units=[None, "тыс. ₽", None, None], rows=[[m, v, n, k] for m, v, n, k in zip(months, [700, 760, 840], [100, 110, 120], [3, 5, 6])])
    budget = Table(id="b", file="fin.xlsx", sheet="Смета Q3", kind="xlsx", columns=["Статья", "План", "Факт"], units=[None, "млн ₽", "тыс. ₽"],
                   rows=[["Люди", 10, 10400], ["Техника", 5, 5300], ["Итого", 15, 15700]], totals=[2])
    ads = Table(id="a", file="fin.xlsx", sheet="Каналы Q3", kind="xlsx", columns=["Канал", "Новых подписчиков", "Затраты"],
                units=[None, None, "тыс. ₽"], rows=[["Блогеры", 10, 500], ["Поиск", 20, 400], ["Итого", 30, 900]], totals=[2])
    return [calls, sla, money, budget, ads]


DOC = """Цели на 2026 год

• Ожидание ответа в 1-й смене — не более 8 минут.
• Ожидание ответа во 2-й смене — не более 3 часов.
• Доля вопросов, решённых с первого звонка, — не менее 65 % к концу года.
• CSI клиентов — не ниже 45 к концу года.
• Выручка 1,2 млн рублей в месяц к декабрю 2026 года.
• Ежемесячный отток подписчиков — не выше 3 %.
• Стоимость привлечения подписчика — не выше 25 тысяч рублей.

Бюджет: перераспределение между статьями утверждает директор, превышение квартальной сметы более чем на 10 % — правление."""


def test_goals_meet_the_facts_of_their_tables():
    facts = table_facts(_tables())
    got = {g.subject: verdict(g, f).text for g in goals_of(DOC) if (f := match(g, facts)) is not None}
    assert got["Доля вопросов, решённых с первого звонка"].startswith("Доля вопросов, решённых с первого звонка: 66 % в сентябре при цели не ниже 65 %")
    assert got["Доля вопросов, решённых с первого звонка"].endswith("цель достигнута")
    assert got["CSI клиентов"].startswith("CSI клиентов: 47 в сентябре") and got["CSI клиентов"].endswith("цель достигнута")
    # the current column of a «Q2 / Q3» pair, the row the goal names, never the target column
    assert got["Ожидание ответа в 1-й смене"] == "Ожидание ответа в 1-й смене: 7 мин в Q3 при норме не более 8 мин — в пределах нормы"
    assert got["Ожидание ответа во 2-й смене"] == "Ожидание ответа во 2-й смене: 3,5 ч в Q3 при норме не более 3 ч — дольше нормы"
    # scales brought together: 840 тыс. ₽ against 1,2 млн рублей
    assert got["Выручка в месяц"].startswith("Выручка в месяц: 0,84 млн ₽ в сентябре при цели 1,2 млн ₽") and got["Выручка в месяц"].endswith("70 % цели")
    # a rate and a cost per unit of two columns
    assert got["Ежемесячный отток подписчиков"].startswith("Ежемесячный отток подписчиков: 5 % в сентябре при цели не выше 3 %")
    assert "30 тыс. ₽" in got["Стоимость привлечения подписчика"] and "выше цели" in got["Стоимость привлечения подписчика"]
    assert "Блогеры — 50 тыс. ₽" in got["Стоимость привлечения подписчика"] and "Поиск — 20 тыс. ₽" in got["Стоимость привлечения подписчика"]


def test_a_verdict_the_facts_contradict_goes_and_the_heading_says_the_facts():
    s = OutlineSlide(id="kb-1", kind=PatternKind.bullets, headline="Цели года по качеству не достигнуты",
                     takeaway="Отставание от плана по обоим показателям требует мер",
                     content=SlideContent(bullets=["Решение с первого звонка и CSI не достигли целевых значений."]))
    said = reconcile([s], _tables(), [DOC])
    assert said
    assert "не достиг" not in (s.headline + " ".join(s.content.bullets)).lower() and s.takeaway is None
    assert s.headline.endswith("цели достигнуты")
    assert any(b.startswith("CSI клиентов: 47") for b in s.content.bullets)
    assert "servis.xlsx" in s.notes


def test_a_slide_that_retells_goals_states_them_against_the_facts():
    s = OutlineSlide(id="kb-2", kind=PatternKind.bullets, headline="Выручка и подписчики",
                     content=SlideContent(bullets=["Выручка 1,2 млн рублей в месяц к декабрю 2026 года.", "Ежемесячный отток подписчиков — не выше 3 %.",
                                                   "Компания работает в трёх городах."]))
    reconcile([s], _tables(), [DOC])
    b = s.content.bullets
    assert b[0].startswith("Выручка в месяц: 0,84 млн ₽ в сентябре") and b[1].endswith("выше цели") and b[2] == "Компания работает в трёх городах."
    assert re.search(r"\d", s.headline) and "70 % цели" in s.headline
    n = OutlineSlide(id="kb-3", kind=PatternKind.stat_row, headline="Цели",
                     content=SlideContent(numbers=[NumberCallout(value="1,2 млн ₽", label="выручка в месяц к декабрю 2026 года")]))
    reconcile([n], _tables(), [DOC])
    assert n.content.numbers[0].value == "0,84 млн ₽" and "70 % цели" in n.content.numbers[0].label


def test_an_approval_a_threshold_needs_is_not_asked_when_the_overrun_stays_under_it():
    s = OutlineSlide(id="kb-4", kind=PatternKind.process, headline="План на 4 квартал",
                     takeaway="Корректировка бюджета делает одобрение правления необходимым",
                     content=SlideContent(items=[SlideItem(title="Шаг 1", text="Открыть второй склад."),
                                                 SlideItem(title="Шаг 2", text="Получить одобрение правления на превышение квартальной сметы более чем на 10 %.")]))
    reconcile([s], _tables(), [DOC])
    step = s.content.items[1].text
    assert "одобрение" not in step and "порог превышения — 10 %" in step and "перерасход по таблице — 4,7 %" in step and "в пределах порога" in step
    assert s.takeaway is None
    # the rule itself stays, with the comparison beside it
    r = OutlineSlide(id="kb-5", kind=PatternKind.bullets, headline="Бюджет", content=SlideContent(bullets=[
        "Превышение квартальной сметы более чем на 10 % утверждает правление."]))
    reconcile([r], _tables(), [DOC])
    assert r.content.bullets[0].startswith("Превышение квартальной сметы более чем на 10 % утверждает правление.") and "в пределах порога" in r.content.bullets[0]


def test_a_goal_the_tables_do_not_measure_stays_as_the_document_says():
    s = OutlineSlide(id="kb-6", kind=PatternKind.bullets, headline="Цели", content=SlideContent(bullets=[
        "Не менее 60 % учеников завершают курс.", "Открыть 5 новых офисов к концу года."]))
    reconcile([s], _tables(), [DOC])
    assert s.content.bullets == ["Не менее 60 % учеников завершают курс.", "Открыть 5 новых офисов к концу года."] and s.headline == "Цели"


def test_a_table_of_norms_gets_the_facts_of_the_tables_not_the_writers():
    from verstka.schemas.outline import TableData

    s = OutlineSlide(id="kb-7", kind=PatternKind.table, headline="Скорость против нормы", content=SlideContent(table=TableData(
        columns=["Смена", "Факт", "Норматив ожидания ответа"], rows=[["1-я смена", "5 мин", "не более 8 минут"], ["2-я смена", "2 ч", "не более 3 часов"]])))
    reconcile([s], _tables(), [DOC])
    t = s.content.table
    assert t.columns == ["Смена", "Норматив ожидания ответа", "Факт, Q3", "Итог"]
    assert t.rows == [["1-я смена", "не более 8 минут", "7 мин", "в пределах нормы"], ["2-я смена", "не более 3 часов", "3,5 ч", "дольше нормы"]]
    assert "2-я смена 3,5 ч — дольше нормы 3 ч" in s.headline
    g = goals_of("Целевая стоимость привлечения подписчика не должна превышать 25 тысяч рублей.")
    assert len(g) == 1 and g[0].op == "<=" and g[0].qty.value == 25000
