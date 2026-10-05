"""The author's text laid out as written — the swarm review of 2026-10-05 (planning): no sentence of the author is cut
at an abbreviation, taken for a designer's instruction because it is an imperative, or lost because the slides are
numbered with a typo, headed by markdown or carry a long title."""

from __future__ import annotations

import pytest

from verstka.planning import faithful as F
from verstka.planning.brief_structure import read_structure


# ---------------------------------------------------------------------------- P10: abbreviations


@pytest.mark.parametrize("text,expected", [
    ("Офис находится в г. Москва, на ул. Тверская, д. 7. Приходите.", ["Офис находится в г. Москва, на ул. Тверская, д. 7.", "Приходите."]),
    ("Проект поддержал проф. Иванов из МГУ. Он консультирует команду.", ["Проект поддержал проф. Иванов из МГУ.", "Он консультирует команду."]),
    ("Мы работаем в трёх городах, т. е. Москву, Казань и Самару. Дальше — Пермь.", ["Мы работаем в трёх городах, т. е. Москву, Казань и Самару.", "Дальше — Пермь."]),
    ("Первую акцию провели на берегу у ул. Баумана: 14 волонтёров. Потом вторую.", ["Первую акцию провели на берегу у ул. Баумана: 14 волонтёров.", "Потом вторую."]),
    ("Dr. Smith met Mr. Brown at the U.S. Embassy. They talked.", ["Dr. Smith met Mr. Brown at the U.S. Embassy.", "They talked."]),
    ("Брендов много, e.g. Walmart and Target. Next.", ["Брендов много, e.g. Walmart and Target.", "Next."]),
])
def test_an_abbreviation_before_a_name_never_ends_the_sentence(text, expected):
    assert F.sentences(text) == expected


def test_a_sentence_may_still_end_at_an_abbreviation_that_ends_it():
    # «…в 2024 г.», «…и т. д.», «…5 млн руб.» end their sentences: the next one starts with a capital
    assert F.sentences("Компания основана в 2024 г. Сейчас в ней 40 человек.") == ["Компания основана в 2024 г.", "Сейчас в ней 40 человек."]
    assert F.sentences("Мы делаем отчёты, сводки и т. д. Всё по шаблону.") == ["Мы делаем отчёты, сводки и т. д.", "Всё по шаблону."]
    assert F.sentences("Выручка — 5 млн руб. Прибыль — 1 млн руб.") == ["Выручка — 5 млн руб.", "Прибыль — 1 млн руб."]


# ---------------------------------------------------------------------------- P5: imperatives are the author's text


SECURITY = """Слайд 1. Цифровая гигиена для сотрудников

Памятка службы информационной безопасности

Слайд 2. Пароли и доступы

Используй разные пароли для рабочих и личных сервисов. Включи двухфакторную аутентификацию в почте и мессенджерах. Не сохраняй пароли в браузере на общих компьютерах.

Слайд 3. Что делать при подозрении на взлом

Сразу отключи компьютер от сети. Сохрани подозрительное письмо и не удаляй его. Позвони на горячую линию 1234.
"""


def test_an_imperative_of_the_authors_text_stays_on_the_slide():
    r = F.read_slide(2, "Пароли и доступы", "Используй разные пароли для рабочих и личных сервисов. Включи двухфакторную аутентификацию в почте и мессенджерах. Не сохраняй пароли в браузере на общих компьютерах.")
    assert not r.asks and not r.used
    assert sum(len(p.sentences) for p in r.of("para")) == 3


def test_an_instruction_about_the_deck_is_still_one():
    for s in ("Используй крупный шрифт на этом слайде.", "Выдели главное число крупно.", "Покажи расходы круговой диаграммой.", "Не перегружай слайд текстом."):
        assert F.designer_ask(s) is not None, s


def test_the_last_slide_of_imperatives_keeps_its_text():
    st = read_structure(SECURITY)
    assert [sp.number for sp in st.specs] == [1, 2, 3]
    last = st.specs[-1]
    assert "Сохрани подозрительное письмо" in last.text and "Позвони на горячую линию 1234" in last.text
    assert not any("Сохрани" in r for r in st.rules)


def test_requirements_on_the_last_slide_are_the_slides_text():
    text = SECURITY + "\nСлайд 4. Требования к надёжности\n\nСистема должна быть доступна 24 часа в сутки. Резервная копия должна делаться каждый час.\n"
    st = read_structure(text)
    assert "доступна 24 часа в сутки" in st.specs[-1].text and not st.rules


# ---------------------------------------------------------------------------- P2: numbering typos, long titles


def test_a_repeated_slide_number_keeps_the_authors_slides():
    text = """Слайд 1. Мобильное приложение «Шаг»

Трекер привычек для студентов

Слайд 2. Проблема

Студенты бросают новые привычки в первые две недели.

Слайд 3. Решение

Приложение напоминает о привычке в удобное время.

Слайд 3. Результаты бета-теста

За месяц приложение установили 2 400 студентов.

Слайд 5. Спасибо!
"""
    st = read_structure(text)
    assert [sp.title for sp in st.specs] == ["Мобильное приложение «Шаг»", "Проблема", "Решение", "Результаты бета-теста", "Спасибо!"]
    assert [sp.number for sp in st.specs] == [1, 2, 3, 4, 5]  # renumbered in the author's order: no two slides share a number


def test_slides_out_of_order_keep_the_authors_order():
    text = "Слайд 1. Обложка\n\nТекст.\n\nСлайд 2. Два\n\nВторой слайд.\n\nСлайд 4. Четыре\n\nЧетвёртый.\n\nСлайд 3. Три\n\nТретий.\n"
    st = read_structure(text)
    assert [sp.title for sp in st.specs] == ["Обложка", "Два", "Четыре", "Три"]


def test_a_long_slide_title_is_still_a_heading():
    long_title = "Почему студенты бросают новые привычки уже в первые две недели после начала занятий и что с этим делать"
    text = f"Слайд 1. Приложение\n\nТрекер.\n\nСлайд 2. Проблема\n\nТекст проблемы.\n\nСлайд 3. {long_title}\n\nОпрос показал причины.\n"
    st = read_structure(text)
    assert len(st.specs) == 3 and st.specs[2].title == long_title
    assert "Слайд 3" not in st.specs[1].text


def test_a_slide_sentence_in_a_paragraph_is_no_heading():
    # a line of a paragraph that starts with «Слайд 3 …» inside the text is not a new slide
    text = "Слайд 1. Обложка\n\nТекст.\n\nСлайд 2. Итоги\n\nМы показали рост.\nСлайд 3 показывает детали расчёта, если нужно.\n"
    st = read_structure(text)
    assert len(st.specs) == 2


# ---------------------------------------------------------------------------- P1: markdown headings are slides


MD = """# Городской велопрокат «Педаль»

Сервис коротких поездок для спальных районов

## Проблема

Жителям спальных районов сложно добраться до метро. Автобусы ходят раз в 20 минут, а пробки в час пик удлиняют поездку вдвое.

## Решение

Мы ставим 40 станций у остановок и станций метро. Оплата поминутная, первые 10 минут бесплатно.

## Команда

Анна Смирнова — основатель. Игорь Петров — технический директор.

## Спасибо!
"""


def test_markdown_headings_are_the_slides_of_a_text_without_slide_heads():
    st = read_structure(MD, md_slides=True)
    assert [sp.title for sp in st.specs] == ["Городской велопрокат «Педаль»", "Проблема", "Решение", "Команда", "Спасибо!"]
    assert "Мы ставим 40 станций" in st.specs[2].text
    assert read_structure(MD).specs == []  # the model plans such a text freely: only the laid-out-as-written path reads it so


def test_a_markdown_text_is_laid_out_as_written_without_a_model():
    from verstka.planning.agent import run_agent
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.outline import Brief

    res = run_agent(Brief(text=MD), None, [load_strategies()["structured"]])
    o = res.outlines["structured"]
    shown = " ".join([s.headline for s in o.slides] + [b for s in o.slides for b in s.content.bullets + s.content.paragraphs] + [s.notes or "" for s in o.slides]
                     + [it.title + " " + it.text for s in o.slides for it in s.content.items])
    for sentence in ("Мы ставим 40 станций у остановок и станций метро", "Автобусы ходят раз в 20 минут", "Игорь Петров — технический директор"):
        assert sentence in shown, sentence
    assert [s.headline for s in o.slides][:2] == ["Городской велопрокат «Педаль»", "Проблема"]


def test_a_rule_of_the_decks_voice_is_still_a_rule_and_a_statement_is_text():
    from verstka.planning.brief_structure import speaks_of_the_deck

    for s in ("Тон нейтральный, энциклопедический.", "Заголовки — факты из текста, без оценок.", "Выводы — отдельной строкой."):
        assert speaks_of_the_deck(s), s
    for s in ("Выводы исследования показывают рост продаж.", "Цвета листьев меняются осенью.", "Используй разные пароли для рабочих сервисов."):
        assert not speaks_of_the_deck(s), s


# ---------------------------------------------------------------------------- P12: markdown is read, never shown


def test_markdown_emphasis_links_and_quotes_are_read_as_text():
    parts = F.read_parts("Наши клиенты — **интернет-магазины** и *службы доставки*.\n\nСайт: [kod-school.ru](https://kod-school.ru). Запись — [на сайте школы](https://kod-school.ru/join).")
    text = " ".join(p.text for p in parts)
    assert "**" not in text and "*службы" not in text and "интернет-магазины" in text
    assert "Сайт: kod-school.ru." in text  # a link whose text is its address is written once
    assert "на сайте школы (https://kod-school.ru/join)" in text
    r = F.read_slide(3, "Отзывы", "> Курс помог мне поступить в университет и найти первую работу программистом.\n> — Артём, 16 лет")
    q = r.quote()
    assert q is not None and q[0].startswith("Курс помог мне поступить") and ">" not in q[0]
    assert "Артём, 16 лет" in r.text


def test_markdown_subheads_are_card_titles():
    r = F.read_slide(4, "Как мы учим", "### Практика\nКаждое занятие — 80% практики. Ученики пишут код с первого урока.\n\n### Наставники\nУ каждой группы есть наставник из индустрии.")
    assert not any("#" in p.text for p in r.parts)
    forms = F.forms_of(r, F.Room(), "structured")
    cards = next((f for f in forms if f.kind == "cards"), None)
    assert cards is not None
    assert [it.title for it in cards.slide.content.items] == ["Практика", "Наставники"]
    assert cards.slide.content.items[0].text.startswith("Каждое занятие — 80% практики")


def test_a_table_without_outer_pipes_is_a_table():
    parts = F.read_parts("Курс | Длительность | Стоимость\n--- | --- | ---\nPython Start | 3 месяца | 24 000 ₽\nWeb Pro | 6 месяцев | 48 000 ₽")
    assert [p.kind for p in parts] == ["table"]
    assert "Python Start" in parts[0].text and parts[0].text.splitlines()[0].startswith("|")


def test_the_slide_marker_never_reaches_the_decks_title():
    st = read_structure("# Слайд 1. Городской велопрокат «Педаль»\n\nСервис коротких поездок\n\n# Слайд 2. Проблема\n\nДо метро далеко.\n")
    assert st.title == "Городской велопрокат «Педаль»"


# ---------------------------------------------------------------------------- P7: a long table goes on, never cut


MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
LONG_TABLE = ("Слайд 1. Отчёт\n\nПродажи за год.\n\nСлайд 2. Продажи по месяцам\n\n| Месяц | Заказы |\n| --- | --- |\n"
              + "".join(f"| {m} | {200 + k * 10} |\n" for k, m in enumerate(MONTHS)) + "| Итого | 3 060 |\n| Среднее | 255 |\n"
              + "\nВывод: продажи росли весь год.\n\nСлайд 3. Спасибо!\n")


def test_a_table_longer_than_a_slide_goes_on_over_a_second_one():
    from verstka.planning.agent import run_agent
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.outline import Brief

    res = run_agent(Brief(text=LONG_TABLE), None, [load_strategies()["structured"]])
    o = res.outlines["structured"]
    parts = [s for s in o.slides if s.content.table is not None]
    assert len(parts) == 2, [s.headline for s in o.slides]
    rows = [r[0] for s in parts for r in s.content.table.rows]
    assert rows == MONTHS + ["Итого", "Среднее"]  # every row, in order, the totals at the end
    assert all(len(s.content.table.rows) <= 10 for s in parts)
    assert parts[1].headline.endswith("(продолжение)") and parts[1].content.table.columns == parts[0].content.table.columns
    assert parts[1].content.table.rows[-1][0] == "Среднее"


def test_split_keeps_short_tables_and_the_conclusion_with_the_last_part():
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import OutlineSlide, SlideContent, TableData

    short = OutlineSlide(id="a", kind=PatternKind.table, headline="Т", content=SlideContent(table=TableData(columns=["a", "b"], rows=[["1", "2"]] * 4)))
    long_ = OutlineSlide(id="b", kind=PatternKind.table, headline="Длинная", takeaway="Вывод.", content=SlideContent(table=TableData(columns=["a", "b"], rows=[[str(k), "x"] for k in range(23)]), bullets=["строка рядом"]))
    got = F.split_long_tables([short, long_])
    assert [(i, j) for _, i, j in got] == [(0, 0), (1, 0), (1, 1), (1, 2)]
    assert [len(s.content.table.rows) for s, _, _ in got[1:]] == [8, 8, 7]
    assert got[1][0].content.bullets == ["строка рядом"] and not got[2][0].content.bullets
    assert got[-1][0].takeaway == "Вывод." and got[1][0].takeaway is None


# ---------------------------------------------------------------------------- P8: the slides' roles


def test_a_first_slide_of_one_short_sentence_is_the_cover_not_a_twin_of_it():
    from verstka.planning.agent import run_agent
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.outline import Brief

    for text in ("Слайд 1. Итоги 2025 года.\n\nОтчёт отдела продаж.\n\nСлайд 2. Выручка\n\nВыручка выросла на 12% и достигла 48 млн ₽.\n",
                 "Тема презентации: «Отчёт». \n\nСлайд 1. Отчёт\n\nПродажи за год.\n\nСлайд 2. Выручка\n\nВыручка выросла на 12% и достигла 48 млн ₽.\n"):
        o = run_agent(Brief(text=text), None, [load_strategies()["structured"]]).outlines["structured"]
        heads = [s.headline for s in o.slides]
        assert len(heads) == len(set(heads)), heads
        assert o.slides[0].kind.value == "title"


def test_a_first_slide_named_as_a_part_stays_content_under_the_decks_own_cover():
    r = F.read_slide(1, "Проблема", "Клиенты ждут ответа два дня.", first=True, deck="Умная поддержка")
    assert r.role == "content"


def test_a_one_line_slide_with_a_figure_is_content_not_a_divider():
    r = F.read_slide(4, "Сколько мусора мы собрали", "За год волонтёры фонда собрали 48 тонн мусора.")
    assert r.role == "content"
    r2 = F.read_slide(4, "Часть 2. Решение", "Как мы это сделаем")
    assert r2.role == "section"


def test_a_closing_with_its_contacts_is_a_closing_whatever_their_number():
    text = "- Почта: hello@shag.app\n- Телефон: +7 900 123-45-67\n- Сайт: https://shag.app\n- Telegram: t.me/shag\n- VK: vk.com/shag"
    r = F.read_slide(9, "Спасибо за внимание! Контакты команды", text, last=True)
    assert r.role == "closing" and "hello@shag.app" in (r.lead or "") and "vk.com/shag" in (r.lead or "")
    assert F.read_slide(9, "Вопросы безопасности", "Пароли меняются раз в квартал.", last=True).role != "closing"


# ---------------------------------------------------------------------------- P14, P15: footnote once, quote's author, English labels


def test_a_quote_keeps_its_author():
    r = F.read_slide(10, "Отзыв клиента", "«Северный путь доставляет наши заказы точно в срок уже третий год подряд.» — Ольга Смирнова, директор по логистике сети «Дом и сад»")
    f = F._quote(r, r.paras())
    assert f is not None and f.slide.content.quote.startswith("Северный путь доставляет")
    assert f.slide.content.quote_author.startswith("Ольга Смирнова, директор по логистике")
    r2 = F.read_slide(3, "Testimonial", '"The new routing cut our delivery time in half within two months." — Anna Lee, COO')
    assert r2.quote() is not None


def test_an_english_text_gets_english_heads():
    r = F.read_slide(4, "Market", "[Pie chart: market share by segment]")
    label, _ = F._place_of(r.of("chart")[0], F.latin(r.text))
    assert label == "Place for a chart"
    r2 = F.read_slide(5, "", "```python\nprint('hi')\n```")
    assert F._slide(r2, "code").headline in ("Code example", "Slide 5")
    from verstka.rendering.synth import place_head

    assert place_head("Place for a chart") == "Place for a chart" and place_head("Image") == "Place for an image"
    assert place_head("Изображение") == "Место под изображение"


# ---------------------------------------------------------------------------- P9: line breaks


def test_short_lines_without_marks_are_a_list_not_one_sentence():
    parts = F.read_parts("Прозрачность\nСкорость\nОтветственность перед клиентом")
    assert [p.kind for p in parts] == ["list"] and parts[0].items == ["Прозрачность", "Скорость", "Ответственность перед клиентом"]


def test_a_short_line_over_a_paragraph_is_its_label():
    r = F.read_slide(3, "Этапы проекта", "Подготовка\nМы описали процессы продаж и выбрали CRM.\nПилот\nПять менеджеров работали в системе месяц.")
    assert [(p.label, p.text[:10]) for p in r.of("para")] == [("Подготовка", "Мы описали"), ("Пилот", "Пять менед")]


def test_a_sentence_broken_by_a_line_still_joins():
    parts = F.read_parts("Мы открыли офис в\nМоскве в 2024 году и наняли\n12 человек.")
    assert [p.kind for p in parts] == ["para"] and parts[0].text == "Мы открыли офис в Москве в 2024 году и наняли 12 человек."


def test_a_wrapped_list_item_goes_on():
    parts = F.read_parts("- Звонки записываются автоматически.\n- Все сделки и звонки хранятся в одной системе, и история клиента\n  доступна любому менеджеру отдела.\n- Отчёты собираются за минуту.")
    assert [p.kind for p in parts] == ["list"]
    assert parts[0].items[1] == "Все сделки и звонки хранятся в одной системе, и история клиента доступна любому менеджеру отдела"


def test_a_bare_slide_head_takes_the_next_short_line_as_its_title():
    st = read_structure("Слайд 1\nШаг\nТрекер привычек для студентов\n\nСлайд 2\nПроблема\nСтуденты бросают новые привычки в первые две недели.\n")
    assert [sp.title for sp in st.specs] == ["Шаг", "Проблема"]
    assert st.specs[1].text.startswith("Студенты бросают")


# ---------------------------------------------------------------------------- P4: the author's key figures, whole


KPI = """Слайд 1. Компания «Северный путь»

Логистика для розничных сетей

Слайд 2. Ключевые показатели

- Выручка — 4,8 млрд ₽.
- Рост к 2024 году — 27%.
- Площадь складов — 96 000 м².
- Клиентов — 1,3 млн.
- Средняя температура в холодильных камерах — минус 18 °C.
- Складов — 12.

Слайд 3. Спасибо!
"""


def test_every_key_figure_keeps_its_sign_and_unit():
    from verstka.planning.agent import verbatim_kpis

    got = verbatim_kpis(["Выручка — 4,8 млрд ₽.", "Средняя температура в холодильных камерах — минус 18 °C.", "Площадь складов — 96 000 м²."])
    assert [(n.label, n.value) for n in got] == [("Выручка", "4,8 млрд ₽"), ("Средняя температура в холодильных камерах", "минус 18 °C"), ("Площадь складов", "96 000 м²")]


def test_a_figure_list_shows_all_its_lines_in_every_variant():
    from verstka.planning.agent import run_agent
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.outline import Brief

    res = run_agent(Brief(text=KPI), None, list(load_strategies().values()))
    for name, o in res.outlines.items():
        s = next(x for x in o.slides if x.headline == "Ключевые показатели")
        c = s.content
        shown = " ".join([n.value + " " + n.label for n in c.numbers] + [" ".join(r) for r in (c.table.rows if c.table else [])]
                         + [it.title + " " + it.text for it in c.items] + c.bullets)
        for v in ("4,8 млрд ₽", "27%", "96 000 м²", "1,3 млн", "минус 18 °C", "12"):
            assert v in shown, (name, v, shown)


# ---------------------------------------------------------------------------- P3, P13, P6: the data of a note, whole and named


def _chart_of(text):
    r = F.read_slide(3, "Данные", text)
    return F.charts_of(r), F.note_table(r), r


def test_a_note_with_its_subject_before_a_dash_reads_every_item():
    charts, _, _ = _chart_of("[Bar chart: fuel per day before and after — Driver A: 42 and 29 litres; Driver B: 38 and 30 litres; Driver C: 45 and 31 litres]")
    assert charts and charts[0].categories == ["Driver A", "Driver B", "Driver C"]
    assert [s.name for s in charts[0].series] == ["Before", "After"]


def test_a_unit_after_the_subject_is_every_items_unit_and_years_are_labels():
    charts, _, _ = _chart_of("[Столбчатая диаграмма: выручка, млн ₽ — 2022: 1,2; 2023: 2,5; 2024: 4,1]")
    assert charts and charts[0].categories == ["2022", "2023", "2024"]
    assert charts[0].series[0].values == [1.2, 2.5, 4.1] and charts[0].unit == "млн ₽"


def test_comma_separated_periods_and_bare_items_are_items():
    charts, _, _ = _chart_of("[Линейный график: 2021 — 10%, 2022 — 15%, 2023 — 22%]")
    assert charts and charts[0].categories == ["2021", "2022", "2023"] and charts[0].series[0].values == [10.0, 15.0, 22.0]
    charts, _, _ = _chart_of("[Круговая диаграмма: доля каналов — онлайн 60%, офлайн 40%]")
    assert charts and charts[0].categories == ["Онлайн", "Офлайн"] and charts[0].series[0].values == [60.0, 40.0]


def test_a_note_read_in_part_is_never_a_partial_chart():
    items = F.chart_items("Москва — 120 тыс. ₽; Казань — около восьмидесяти, точнее 80 и 95 тыс. ₽")
    assert not F.note_covered("Москва — 120 тыс. ₽; Казань — около восьмидесяти, точнее 80 и 95 тыс. ₽", items)


def test_legends_come_from_the_note_and_its_figures_never_from_a_preposition():
    charts, table, _ = _chart_of("[Столбчатая диаграмма: Москва — 120 и 150 тыс. ₽; Казань — 80 и 95 тыс. ₽]\n\nДанные за 2024 и 2025 годы. После открытия второго офиса выручка выросла до 150 тыс. ₽.")
    assert charts and [s.name for s in charts[0].series] == ["2024", "2025"]
    charts, table, _ = _chart_of("[Столбчатая диаграмма: базовый — 300 и 450 ₽; премиум — 900 и 1200 ₽]\n\nЦены в Москве и в регионах. Цены были пересмотрены в марте.")
    assert not charts  # nothing names the two prices: no chart with an invented «Было/Стало» legend
    assert table is not None and [r[0] for r in table.rows] == ["Базовый", "Премиум"]


def test_every_data_block_of_a_slide_is_shown():
    from verstka.planning.agent import run_agent
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.outline import Brief

    text = ("Слайд 1. Отчёт\n\nИтоги квартала.\n\nСлайд 2. Каналы и цены\n\n"
            "[Круговая диаграмма: доля каналов — онлайн 60%, офлайн 40%]\n\n"
            "| Тариф | Цена |\n| --- | --- |\n| Базовый | 199 ₽ |\n| Премиум | 499 ₽ |\n\nСлайд 3. Спасибо!\n")
    o = run_agent(Brief(text=text), None, [load_strategies()["structured"]]).outlines["structured"]
    pie = [s for s in o.slides if s.content.chart is not None and s.content.chart.type in ("pie", "doughnut", "column")]
    tables = [s for s in o.slides if s.content.table is not None]
    assert pie and tables, [s.headline for s in o.slides]
    assert any("Премиум" in r[0] for s in tables for r in s.content.table.rows)


# ---------------------------------------------------------------------------- P11: the grounding leaves the author's own lines


def test_the_grounding_keeps_the_authors_lines_and_notes_as_written():
    from verstka.planning.agent import run_agent
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.outline import Brief

    text = ("Слайд 1. Склад «Север»\n\nЛогистика для розничных сетей\n\n"
            "Слайд 2. Как нас найти\n\nАдрес: Москва, ул. Складская, д. 1.\n\nРаботаем с 8 до 20 часов.\n\n"
            "Слайд 3. Итоги года\n\nВыручка — 4,8 млрд ₽.\n\nРост к 2024 году — 27%.\n")
    res = run_agent(Brief(text=text), None, [load_strategies()["structured"]])
    o = res.outlines["structured"]
    s2 = next(s for s in o.slides if s.headline == "Как нас найти")
    shown = " ".join(s2.content.bullets + s2.content.paragraphs + [it.title + " " + it.text for it in s2.content.items] + [s2.subtitle or ""])
    assert "ул. Складская, д. 1" in shown, shown
    assert "\n\n" in (s2.notes or "")  # the author's paragraphs stay paragraphs in the speaker's notes
    assert not any("given another subject" in w for w in res.warnings.get("structured", []))


def test_opening_hours_are_no_change_but_a_change_in_hours_is():
    from verstka.planning.brief_structure import _pairs_of

    assert _pairs_of("Работаем с 8 до 20 часов.") == []
    assert _pairs_of("Приём с 9 до 18.") == []
    got = _pairs_of("Время ответа сократилось с 8 до 2 часов.")
    assert got and got[0].values == [8.0, 2.0]
