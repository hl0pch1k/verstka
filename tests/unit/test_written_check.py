"""Writer mode: the designer never adds a fact (planning/written_check.py, gate 3 W3-1, W3-2, W3-6, W3-7, W3-11).

The slide texts are the writer's texts of the gate-3 live runs (tq/ws/runs/20260928-0342…), the designed slides the
forms the designer and the variants gave them."""

from __future__ import annotations

import re

from verstka.planning import written_check as W
from verstka.planning.compile import _Run as CompileRun
from verstka.planning.compile import _variety
from verstka.schemas.brief_structure import BriefStructure
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, NumberCallout, OutlineSlide, SlideAlternative, SlideContent, SlideItem, TableData

WW2_S7 = (
    "В 1944 году Советский Союз начал наступление в Восточной Белоруссии и освободил большую часть оккупированной "
    "территории. В Тихом океане США одержали победу в битве за Гуадалканал. В феврале 1945 года на Ялтинской "
    "конференции были обсуждены послевоенные планы. К маю 1945 года Германия была полностью разгромлена."
)
WW2_S3 = (
    "1 сентября 1939 года нацистская Германия начала вторжение в Польшу. 3 сентября Великобритания и Франция объявили "
    "войну Германии. 17 сентября СССР начал военное вторжение в Польшу с востока. В октябре Польша была разделена между "
    "Германией и СССР по пакту Молотова—Риббентропа."
)
WW2_S5 = (
    "22 июня 1941 года Германия начала вторжение в СССР. В Азии 7 декабря 1941 года Япония атаковала Перл-Харбор, что "
    "привело к вступлению США в войну. В 1942 году Япония потерпела поражение в битве за Мидуэй, что остановило её "
    "продвижение. В Европе Советский Союз начал серию побед, включая Сталинградскую битву."
)
WW2_S8 = (
    "8 мая 1945 года Германия подписала акт о капитуляции. 2 сентября 1945 года Япония подписала акт о капитуляции после "
    "атомных бомбардировок Хиросимы и Нагасаки. Война официально закончилась. После капитуляции Германии некоторые части "
    "вермахта продолжали сопротивление."
)
WW2_S9 = (
    "Во Второй мировой войне погибло более 70 миллионов человек, большинство из которых — мирные жители. В войне "
    "участвовали 62 государства (80 % населения Земли). В вооружённые силы было мобилизовано 110 млн человек."
)
VK_S4 = (
    "В 2010 году компания была переименована в Mail.ru Group. В этот период были запущены такие сервисы, как «Мой мир». "
    "В 2010 году компания провела IPO на Лондонской фондовой бирже. В 2021 году компания сменила название на VK."
)
VK_S7 = "С 2021 года компания называется VK. В 2023 году началась реструктуризация бизнеса. В 2023 году компания начала редомициляцию в Россию."
VK_DECK = f"Слайд 2. Основание\nVK была основана в 1998 году как почтовый сервис Mail.ru.\n\nСлайд 7. Современный этап\n{VK_S7}\n\nСлайд 8. Главное\nВ 2021 году VK изменила название."
EV_S4 = (
    "В России электромобили производят «Москвич», «Автотор», «АвтоВАЗ» и завод «Моторинвест». В 2022 году началось "
    "производство «Москвич 3е» и «Эволют». Ведётся разработка новых моделей, таких как «Молния» и «Атом»."
)
EV_S5 = (
    "Электромобили в России отличаются более высокой стоимостью из-за цены на батареи, но имеют меньшие расходы на "
    "обслуживание и топливо. В 2024 году «Москвич 3е» стал одной из первых серийных моделей на российском рынке."
)
EV_S6 = (
    "Для электромобилей в России развивается сеть зарядных станций. В Москве с 2025 года начнётся производство батарей "
    "для электромобилей «Москвич». Правительство поддерживает развитие инфраструктуры, включая программы локализации "
    "производства и государственные субсидии."
)
EV_S8 = (
    "Электромобиль — экологичный и экономичный вид транспорта. В 2024 году в России зарегистрировали 59,6 тыс. "
    "электромобилей. Основные производители — «Москвич», «Автотор», «АвтоВАЗ». К 2030 году в мире может быть 240 млн "
    "электромобилей."
)
GAG_S5 = (
    "Первым, кого увидел Гагарин, была жена местного лесника Анна Тахтарова. Вскоре к месту прибыли военные и местные "
    "жители. Гагарин отрапортовал по телефону командиру дивизии ПВО. В Москве его встречали как национального героя. 14 "
    "апреля он получил медаль «Золотая Звезда» Героя Советского Союза и орден Ленина."
)
WW2_S10 = (
    "После войны были созданы новые международные организации, такие как Организация Объединённых Наций (ООН), для "
    "предотвращения будущих конфликтов. Был создан международный трибунал для осуждения бывшего руководства "
    "стран-агрессоров. Произошли территориальные изменения, и были приняты новые статьи международного права."
)


def _slide(kind, headline, **content) -> OutlineSlide:
    takeaway = content.pop("takeaway", None)
    return OutlineSlide(id="s", kind=kind, headline=headline, content=SlideContent(**content), takeaway=takeaway)


def _all_text(s: OutlineSlide) -> str:
    c = s.content
    parts = [s.headline, s.takeaway or "", *c.bullets, *c.paragraphs]
    parts += [f"{it.title} {it.text}" for it in c.items]
    parts += [f"{n.value} {n.label}" for n in c.numbers]
    if c.table:
        parts += [" ".join(r) for r in c.table.rows]
    return "\n".join(parts)


# ------------------------------------------------------------------ W3-1: a date travels only with its own event


def test_a_timeline_step_never_takes_the_year_of_the_sentence_before_it():
    s = _slide(K.timeline, "К 1945 году Советский Союз освободил большую часть оккупированной территории, а Германия была разгромлена", items=[
        SlideItem(title="1944", text="СССР начал наступление в Восточной Белоруссии и освободил большую часть оккупированной территории."),
        SlideItem(title="1944", text="США одержали победу в битве за Гуадалканал."),
        SlideItem(title="Февраль 1945", text="на Ялтинской конференции обсуждались послевоенные планы."),
        SlideItem(title="Май 1945", text="Германия была полностью разгромлена."),
    ])
    ch = W.check_slide(s, WW2_S7, title="Переломные события (продолжение)", topic="Вторая мировая война")
    text = _all_text(s)
    assert "Гуадалканал" in text
    assert not re.search(r"1944\D{0,5}США", text), text
    # a step lost its date: no time axis with a dateless step; the dated ones keep their dates, lowercase after the dash
    assert s.kind != K.timeline
    assert "США одержали победу в битве за Гуадалканал" in s.content.bullets
    assert "Февраль 1945 — на Ялтинской конференции обсуждались послевоенные планы" in s.content.bullets
    assert any("Гуадалканал" in x for x in ch)


def test_a_dated_line_without_its_date_in_the_sentence_loses_the_date():
    s = _slide(K.bullets, "К 1942 году США вступили в войну, а Советский Союз начал оборонительные бои", bullets=[
        "22 июня 1941 — Германия начала вторжение в СССР", "7 декабря 1941 — Япония атаковала Перл-Харбор",
        "1942 — Япония потерпела поражение в битве за Мидуэй", "1942 — Советский Союз начал серию побед, включая Сталинградскую битву",
    ], takeaway="К 1942 году ситуация изменилась в пользу союзников")
    W.check_slide(s, WW2_S5, title="Ход событий (продолжение)", topic="Вторая мировая война")
    assert "Советский Союз начал серию побед, включая Сталинградскую битву" in s.content.bullets
    assert "22 июня 1941 — Германия начала вторжение в СССР" in s.content.bullets
    # the headline's invented «оборонительные бои» and the takeaway not in the text are gone
    assert "оборонительные" not in s.headline
    assert s.takeaway is None


def test_a_merged_entry_is_rebuilt_from_the_sentence_of_its_date():
    s = _slide(K.timeline, "Компания сменила два названия", items=[
        SlideItem(title="2010 год", text="Переименование в Mail.ru Group и запуск «Мой мир»"),
        SlideItem(title="2010 год", text="Проведение IPO на Лондонской фондовой бирже"),
        SlideItem(title="2021 год", text="Смена названия на VK"),
    ])
    W.check_slide(s, VK_S4, deck=VK_DECK, title="Развитие", topic="История VK")
    assert s.kind == K.timeline
    first = s.content.items[0]
    assert first.title == "2010 год" and "Mail.ru Group" in first.text and "Мой мир" not in first.text
    assert [it.text for it in s.content.items[1:]] == ["Проведение IPO на Лондонской фондовой бирже", "Смена названия на VK"]


def test_a_day_without_a_year_takes_the_year_of_the_slide():
    items = [SlideItem(title="1 сентября 1939", text="Германия начала вторжение в Польшу"),
             SlideItem(title="3 сентября 1939", text="Великобритания и Франция объявили войну Германии"),
             SlideItem(title="17 сентября 1939", text="СССР начал военное вторжение в Польшу с востока"),
             SlideItem(title="Октябрь 1939", text="Польша была разделена между Германией и СССР")]
    s = _slide(K.timeline, "Вторжение в Польшу начало войны", items=[it.model_copy() for it in items])
    W.check_slide(s, WW2_S3, title="Начало", topic="Вторая мировая война")
    assert s.kind == K.timeline and [(it.title, it.text) for it in s.content.items] == [(it.title, it.text) for it in items]


def test_a_period_the_sentence_names_by_the_one_before_it_is_that_year():
    text = "К 2019 году VK стала одной из крупнейших технологических компаний в России. В этот период компания расширила портфель активов, включив в него мессенджеры и образовательные платформы."
    s = _slide(K.bullets, "Компания расширила портфель", bullets=["2019 — расширила портфель активов: мессенджеры, образовательные платформы", "Ещё одна строка про компанию"])
    W.check_slide(s, text, title="Развитие", topic="История VK")
    assert any(b.startswith("2019 — расширила портфель активов") for b in s.content.bullets), s.content.bullets
    # gate 4 G4-2: the slide's first dated sentence stays on it
    assert any(b.startswith("К 2019 году VK стала") for b in s.content.bullets), s.content.bullets


# ------------------------------------------------------------------ W3-6: no time axis without dates


def test_an_undated_timeline_becomes_cards():
    s = _slide(K.timeline, "Первой, кого увидел Гагарин, была Анна Тахтарова", items=[
        SlideItem(title="К месту прибыли военные и местные жители"), SlideItem(title="Гагарин отрапортовал по телефону командиру дивизии ПВО"),
        SlideItem(title="В Москве его встречали как национального героя"), SlideItem(title="14 апреля он получил медаль «Золотая Звезда» Героя Советского Союза и орден Ленина"),
    ])
    W.check_slide(s, GAG_S5, title="Окончание", topic="Полёт Гагарина")
    assert s.kind == K.cards and len(s.content.items) == 4


def _written_brief() -> str:
    return "Слайд 1. Титульный\nНазвание: «Полёт Гагарина».\n\nСлайд 2. Итоги\nТекст.\n\nТон нейтральный, энциклопедический. Заголовки — факты из текста, без оценок.\n"


def _bullets_slide(i: int, lines: list[str]) -> OutlineSlide:
    return OutlineSlide(id=f"s{i}", kind=K.bullets, headline=f"Слайд {i}", content=SlideContent(bullets=lines), alternatives=[SlideAlternative(kind="timeline", change="шкала")])


def test_the_compilers_variety_pass_never_picks_an_undated_timeline_in_writer_mode():
    lines = ["К месту прибыли военные — и местные жители", "Гагарин отрапортовал — командиру дивизии", "В Москве его встречали — как героя"]
    for written in (True, False):
        o = DeckOutline(title="t", slides=[_bullets_slide(i, list(lines)) for i in range(1, 4)])
        _variety(o, BriefStructure(), CompileRun(o, None), written)
        kinds = [s.kind for s in o.slides]
        if written:
            assert K.timeline not in kinds
        else:
            assert K.timeline in kinds  # a user's own brief: as before


def test_the_compilers_variety_pass_keeps_a_dated_timeline_in_writer_mode():
    lines = ["1998 — основана компания", "2010 — переименование в Mail.ru Group", "2021 — новое название VK"]
    o = DeckOutline(title="t", slides=[_bullets_slide(i, list(lines)) for i in range(1, 4)])
    _variety(o, BriefStructure(), CompileRun(o, None), True)
    assert K.timeline in [s.kind for s in o.slides]


# ------------------------------------------------------------------ W3-2: labels, hedged ranks, enumerations


def test_stat_labels_are_their_sentences_without_the_value_phrase():
    s = _slide(K.stat_row, "Электромобиль — экологичный и экономичный вид транспорта", numbers=[
        NumberCallout(value="59,6 тыс.", label="В 2024 году в России зарегистрировали 59,6 тыс."),
        NumberCallout(value="240 млн", label="К 2030 году в мире может быть 240"),
    ])
    W.check_slide(s, EV_S8, title="Главное", topic="Рынок электромобилей в России")
    labels = [n.label for n in s.content.numbers]
    assert labels == ["электромобилей зарегистрировали в России в 2024 году", "электромобилей может быть в мире к 2030 году"]
    for n in s.content.numbers:
        assert not re.search(r"\d", re.sub(r"(?:1\d{3}|20\d{2})", "", n.label)), n.label
        assert W.bad_label(n.label, n.value, None, set()) is None


def test_a_table_of_cut_labels_becomes_a_row_of_key_figures():
    s = _slide(K.table, "Электромобили в цифрах", table=TableData(columns=["Показатель", "Значение"], rows=[
        ["В 2024 году в России зарегистрировали 59,6 тыс.", "59,6 тыс."], ["К 2030 году в мире может быть 240", "240 млн"]]))
    W.check_slide(s, EV_S8, title="Главное", topic="Рынок электромобилей в России")
    assert s.kind == K.stat_row and s.content.table is None
    assert [n.value for n in s.content.numbers] == ["59,6 тыс.", "240 млн"]
    assert all("240" not in n.label and "59,6" not in n.label for n in s.content.numbers)


def test_one_word_labels_become_noun_phrases_and_the_hedge_stays():
    s = _slide(K.stat_row, "Во Второй мировой войне погибло более 70 млн человек", numbers=[
        NumberCallout(value="70 млн", label="Погибло"), NumberCallout(value="110 млн", label="Мобилизовано"),
        NumberCallout(value="62", label="Государства"), NumberCallout(value="80%", label="Населения Земли"),
    ])
    W.check_slide(s, WW2_S9, title="Итоги и потери", topic="Вторая мировая война")
    got = {n.value: n.label for n in s.content.numbers}
    # the headline is this figure's sentence: the label is the words the composer shows under it (label_beside)
    assert got["более 70 млн"] == "во Второй мировой войне погибло"
    assert got["110 млн"] == "человек мобилизовано в вооружённые силы"
    assert got["62"] == "государства участвовали в войне"
    assert all(len(x.split()) <= 7 for x in got.values())


def test_label_of_refuses_shapes_it_cannot_read():
    assert W.label_of("Война велась на территории 40 стран и вовлекала 61 государство", "40 стран") is None
    assert W.label_of("Эксперты прогнозируют рост рынка электромобилей в мире до 240 млн к 2030 году", "240 млн") is None
    assert W.label_of("В 2019 году совокупный доход компании составил 87,6 млрд рублей.", "87,6 млрд ₽") == "совокупный доход компании в 2019 году"
    assert W.label_of("В войне участвовали 62 государства (80 % населения Земли).", "80%") == "населения Земли"
    assert W.label_of("В том же году было продано 17,8 тыс. электромобилей", "17,8 тыс.", year=2024) == "электромобилей продано в 2024 году"


def test_a_headline_never_strengthens_a_hedged_rank():
    s = _slide(K.bullets, "«Москвич 3е» — первая серийная модель 2024 года", paragraphs=["Имеют меньшие расходы на топливо и обслуживание"])
    W.check_slide(s, EV_S5, title="Продукты и цены", topic="Рынок электромобилей в России")
    assert "перв" not in s.headline.split("«")[0] or "одной из" in s.headline
    # gate 4 G4-5: not the working title — the slide's own hedged sentence states it
    assert s.headline == "В 2024 году «Москвич 3е» стал одной из первых серийных моделей на российском рынке"
    # the subject-less fragment is gone: the slide shows its two sentences
    shown = _all_text(s)
    assert "Электромобили в России отличаются более высокой стоимостью" in shown
    assert not any(x.startswith("Имеют") for x in [*s.content.bullets, *s.content.paragraphs, *(it.title for it in s.content.items)])


def test_a_list_of_the_names_a_sentence_enumerates_keeps_them_all():
    s = _slide(K.bullets, "Основные производители электромобилей в России", bullets=["«Автотор»", "«АвтоВАЗ»", "Завод «Моторинвест»"])
    W.check_slide(s, EV_S4, title="Основные игроки", topic="Рынок электромобилей в России")
    assert s.content.bullets == ["«Москвич»", "«Автотор»", "«АвтоВАЗ»", "Завод «Моторинвест»"]


# ------------------------------------------------------------------ W3-7: headings — gender, the date's own event


def test_a_headline_takes_the_gender_the_text_gives_the_name():
    s = _slide(K.bullets, "VK начал работу как Mail.ru", bullets=["Компания начала свою деятельность в Санкт-Петербурге", "Сервис Mail.ru"])
    W.check_slide(s, "Компания начала свою деятельность в Санкт-Петербурге. Сервис Mail.ru был запущен.", deck=VK_DECK, title="Основание", topic="История VK")
    assert s.headline == "VK начала работу как Mail.ru"
    g = W.entity_genders(VK_DECK)
    assert g.get("vk") == "f"
    assert W.entity_genders("Слайд 8. Главное\nVK была основана в 1998 году как почтовый сервис Mail.ru.") == {"vk": "f"}  # a line's start
    assert W.agree_gender("В 2023 году чистый убыток VK составил 34,3 млрд рублей", g) == "В 2023 году чистый убыток VK составил 34,3 млрд рублей"
    assert W.agree_gender("В 2021 году VK изменил название", g) == "В 2021 году VK изменила название"


def test_a_headline_date_goes_with_its_own_event():
    s = _slide(K.bullets, "Война официально закончилась 2 сентября 1945 года", bullets=[
        "8 мая 1945 года — Германия подписала акт о капитуляции", "После капитуляции Германии — некоторые части вермахта продолжали сопротивление",
    ], takeaway="Война официально закончилась после подписания актов о капитуляции Германией и Японией")
    W.check_slide(s, WW2_S8, title="Окончание", topic="Вторая мировая война")
    assert s.headline == "2 сентября 1945 года Япония подписала акт о капитуляции"
    assert "После капитуляции Германии некоторые части вермахта продолжали сопротивление" in [*s.content.bullets, *(it.title for it in s.content.items)]
    assert s.takeaway is None


def test_a_summary_headline_with_the_slides_years_stays():
    s = _slide(K.cards, "1942–1944: Ключевые события Второй мировой войны", items=[
        SlideItem(title="19 ноября 1942", text="Красная армия начала контрнаступление под Сталинградом."),
        SlideItem(title="1943 год", text="Союзники начали стратегические бомбардировки Германии."),
        SlideItem(title="1944 год", text="Англо-американские войска высадились в Нормандии."),
    ])
    text = ("19 ноября 1942 года Красная армия начала контрнаступление под Сталинградом, что стало переломным моментом на "
            "Восточном фронте. В 1943 году союзники начали стратегические бомбардировки Германии. В 1944 году "
            "англо-американские войска высадились в Нормандии, начав освобождение Западной Европы.")
    assert W.check_slide(s, text, title="Переломные события", topic="Вторая мировая война") == []


def test_lowercase_after_a_dates_dash_but_names_keep_their_capital():
    s = _slide(K.bullets, "VK изменила название и началась реструктуризация", bullets=[
        "2021 — компания переименована в VK", "2023 — началась реструктуризация бизнеса", "2023 — Начата редомициляция в Россию",
    ])
    W.check_slide(s, VK_S7, deck=VK_DECK, title="Современный этап", topic="История VK")
    assert "2023 — начата редомициляция в Россию" in s.content.bullets
    s2 = _slide(K.bullets, "Вторжение в Польшу", bullets=["1 сентября 1939 — Германия начала вторжение в Польшу", "3 сентября 1939 — Великобритания и Франция объявили войну Германии"])
    W.check_slide(s2, WW2_S3, title="Начало", topic="Вторая мировая война")
    # two short dated lines on a slide of four dated sentences: the slide's time axis, the names with their capitals
    assert s2.kind == K.timeline
    assert [(it.title, it.text) for it in s2.content.items][:2] == [("1 сентября 1939", "Нацистская Германия начала вторжение в Польшу"), ("3 сентября 1939", "Великобритания и Франция объявили войну Германии")]
    s3 = _slide(K.bullets, "Вторжение в Польшу", bullets=["1 сентября 1939 — Германия начала вторжение в Польшу", "3 сентября 1939 — Великобритания и Франция объявили войну Германии", "17 сентября 1939 — СССР начал военное вторжение в Польшу с востока"])
    W.check_slide(s3, WW2_S3, title="Начало", topic="Вторая мировая война")
    assert s3.content.bullets[0] == "1 сентября 1939 — Германия начала вторжение в Польшу"


# ------------------------------------------------------------------ W3-11: takeaways are the text's sentences


def test_a_takeaway_is_a_sentence_of_the_slide_or_nothing():
    s = _slide(K.bullets, "Россия развивает инфраструктуру для электромобилей", bullets=[
        "В Москве с 2025 года начнётся производство батарей для электромобилей «Москвич»", "Правительство поддерживает развитие зарядных станций", "Сеть зарядных станций развивается",
    ], takeaway="Инфраструктура для электромобилей активно развивается с государственной поддержкой")
    W.check_slide(s, EV_S6, title="Инфраструктура", topic="Рынок электромобилей в России")
    # the evaluation («активно») goes: the takeaway is the slide's own sentence it meant, or nothing
    assert s.takeaway in (None, "Правительство поддерживает развитие инфраструктуры, включая программы локализации производства и государственные субсидии")
    assert "активно" not in (s.takeaway or "")
    s2 = _slide(K.bullets, "Германия начала вторжение в Польшу", bullets=["3 сентября 1939 — Великобритания и Франция объявили войну Германии", "17 сентября 1939 — СССР начал вторжение в Польшу с востока", "Октябрь 1939 — Польша была разделена"],
                takeaway="В октябре Польша была разделена между Германией и СССР")
    W.check_slide(s2, WW2_S3, title="Начало", topic="Вторая мировая война")
    # gate 4 G4-1: a sentence cut where no clause ends is the whole sentence
    assert s2.takeaway in ("В октябре Польша была разделена между Германией и СССР", "В октябре Польша была разделена между Германией и СССР по пакту Молотова—Риббентропа")


# ------------------------------------------------------------------ short slides fill the slide


def test_a_slide_of_two_short_lines_shows_its_sentences_as_cards():
    s = _slide(K.bullets, "Созданы международные организации для предотвращения конфликтов", bullets=["Произошли территориальные изменения", "Приняты новые статьи международного права"])
    W.check_slide(s, WW2_S10, title="Последствия", topic="Вторая мировая война")
    assert s.kind == K.cards
    titles = [f"{it.title} {it.text}" for it in s.content.items]
    assert any("трибунал" in t for t in titles) and len(titles) >= 2
    assert not any(t.startswith("После войны были созданы") for t in titles)  # the headline says it


def test_a_figure_line_is_its_own_sentence():
    text = "6 июня 1944 года союзные силы США, Великобритании и Канады высадились в Нормандии. Для операции было выделено 1213 кораблей и 4126 десантных судов."
    s = _slide(K.bullets, "Высадка в Нормандии", bullets=["1213 — Кораблей США", "Союзники высадились в Нормандии", "Операция началась 6 июня"])
    W.check_slide(s, text, title="Второй фронт", topic="Вторая мировая война")
    shown = [*s.content.bullets, *(f"{it.title} {it.text}".strip() for it in s.content.items)]
    assert any(x.startswith("Для операции было выделено 1213 кораблей") for x in shown), shown
    assert not any("Кораблей США" in b for b in shown)


def test_a_chart_slide_may_name_its_largest_part():
    text = "В 2019 году совокупный доход компании составил 87,6 млрд рублей. Доход от онлайн-рекламы составил 42 %, от игрового направления — 32 %."
    ch = ChartSpec(type="pie", categories=["Онлайн-реклама", "Игровое направление"], series=[InlineSeries(name="Доходы, %", values=[42.0, 32.0])])
    s = _slide(K.chart, "Онлайн-реклама принесла больше всего дохода в 2019 году", chart=ch)
    W.check_slide(s, text, title="Доходы VK в 2019 году", topic="История VK")
    assert s.headline == "Онлайн-реклама принесла больше всего дохода в 2019 году"


def test_a_slide_of_the_texts_own_sentences_is_left_alone():
    s = _slide(K.bullets, "22 июня 1941 года Германия начала вторжение в СССР", bullets=[
        "7 декабря 1941 года Япония атаковала Перл-Харбор", "В 1942 году Япония потерпела поражение в битве за Мидуэй", "В Европе Советский Союз начал серию побед, включая Сталинградскую битву",
    ])
    before = s.model_copy(deep=True)
    assert W.check_slide(s, WW2_S5, title="Ход событий (продолжение)", topic="Вторая мировая война") == []
    assert s == before


def test_an_evaluation_the_text_does_not_give_leaves_the_line():
    text = ("В России представлены различные модели электромобилей, такие как «Москвич 3е», «Атом», «UMO 5» и «Амберавто». "
            "По состоянию на 2025 год общая стоимость владения электромобилем в мире сравнима с автомобилями с двигателями "
            "внутреннего сгорания, несмотря на более высокую стоимость батарей.")
    s = _slide(K.bullets, "Электромобили представлены на рынке России", paragraphs=["«Москвич 3е», «Атом», «UMO 5» и «Амберавто» — доступные модели"])
    W.check_slide(s, text, title="Продукты и цены", topic="Рынок электромобилей в России")
    assert "доступн" not in _all_text(s)
    assert "«Амберавто»" in _all_text(s)


def test_a_slide_of_one_line_is_a_statement():
    text = "Эксперты McKinsey включили электромобили в число революционных технологий. В России растёт интерес к электромобилям, особенно в рамках государственных программ."
    s = _slide(K.bullets, "Эксперты McKinsey включили электромобили в число революционных технологий", bullets=["В России растёт интерес к электромобилям"])
    W.check_slide(s, text, title="Тенденции", topic="Рынок электромобилей в России")
    assert s.content.bullets == [] and s.content.paragraphs == ["В России растёт интерес к электромобилям, особенно в рамках государственных программ"]


def test_a_key_figure_that_lost_its_scale_gets_it_back():
    s = _slide(K.stat_row, "Итоги и потери", numbers=[NumberCallout(value="70", label="во Второй мировой войне погибло 70 миллионов человек"),
                                                     NumberCallout(value="110 млн", label="человек мобилизовано в вооружённые силы")])
    W.check_slide(s, WW2_S9, title="Итоги и потери", topic="Вторая мировая война")
    n = s.content.numbers[0]
    assert n.value == "более 70 млн" and "70" not in n.label


def test_the_composers_label_never_takes_another_figure():
    from verstka.planning.heuristics import label_beside

    head = "В 2024 году зарегистрировали 59,6 тыс. электромобилей, продано — 17,8 тыс."
    for value, label in (("59,6 тыс.", "электромобилей зарегистрировали в России в 2024 году"), ("17,8 тыс.", "продано в России в 2024 году")):
        out = label_beside(value, label, head)
        assert not re.search(r"\d+,\d", out), out
    # a figure's words after it in the heading stay the label (the old rule)
    assert label_beside("6,5 минуты", "оператор тратит в среднем 6,5 минуты", "Оператор тратит в среднем 6,5 минуты на одно обращение") == "на одно обращение"


def test_a_takeaway_that_is_not_a_sentence_becomes_the_sentence_it_meant():
    s = _slide(K.bullets, "Германия захватила Европу", bullets=["1940 — Германия завоевала Данию и Норвегию", "Апрель 1941 — Германия и Италия оккупировали Грецию"],
               takeaway="К 1941 году единственным противником Германии осталась Великобритания")
    text = "В 1940 году Германия стремительно завоевала Данию, Норвегию, Францию и страны Бенилюкса. В апреле 1941 года Германия и Италия оккупировали Грецию. К июню 1941 года единственным серьёзным противником оставалась Великобритания."
    W.check_slide(s, text, title="Ход событий", topic="Вторая мировая война")
    assert s.takeaway == "К июню 1941 года единственным серьёзным противником оставалась Великобритания"


def test_a_line_cut_after_its_subject_is_its_sentence():
    s = _slide(K.bullets, "Электромобили дороже, но дешевле в обслуживании", bullets=["Имеют меньшие расходы на топливо и обслуживание", "Цена батарей высокая", "Третья строка про рынок"])
    W.check_slide(s, EV_S5, title="Продукты и цены", topic="Рынок электромобилей в России")
    shown = [*s.content.bullets, *(f"{it.title} {it.text}".strip() for it in s.content.items), *s.content.paragraphs]
    assert not any(x.startswith("Имеют") for x in shown), shown


# ------------------------------------------------------------------ gate 4: whole sentences, lines on their own, headlines

GAG_A1_S3 = (
    "12 апреля 1961 года, в 9 часов 7 минут по московскому времени, с космодрома Байконур стартовал корабль «Восток-1» с "
    "Юрием Гагариным на борту. Выключение двигателя произошло только после срабатывания дублирующего механизма, но корабль "
    "уже поднялся на орбиту, высшая точка которой оказалась на 100 км выше расчётной."
)
GAG_A1_S4 = (
    "В конце полёта ТДУ конструктора Исаева проработала успешно, но отключилась на секунду раньше, в результате чего "
    "автоматика выдала запрет на штатное разделение отсеков. В ходе спуска произошло вращение корабля со скоростью один "
    "оборот в секунду, но спускаемый аппарат отделился."
)
WW2_S7_G4 = (
    "6 июня 1944 года союзные силы США, Великобритании и Канады после двух месяцев отвлекающих манёвров провели крупнейшую "
    "десантную операцию в истории и высадились в Нормандии. В июле 1945 года США отправили Японии Потсдамскую декларацию, "
    "которую та отклонила. В августе 1945 года СССР вступил в войну против Японии."
)
GAG_S4_G4 = (
    "Ракета-носитель «Восток» проработала без замечаний. Корабль сделал один оборот вокруг Земли, и в 10 часов 53 минуты "
    "посадка произошла в районе деревни Смеловка Саратовской области. Полёт длился 106 минут."
)
ENERGY_S5 = (
    "В России продолжается строительство новых АЭС, включая проекты в ОЭС Центра, Урала и Сибири. Также развивается "
    "транспортная ядерная энергетика, включая ледоколы проекта 22220. В апреле 2025 года Россия строила более 10 атомных "
    "энергоблоков за рубежом."
)
ENERGY_S3 = (
    "Россия потребляет около 3800 тонн природного урана в год для работы АЭС. В стране разведано около 615 тыс. тонн урана, "
    "основная добыча сосредоточена в Забайкальском крае."
)
GAG_S2_G4 = (
    "Для полёта в космос требовались кандидаты, соответствующие строгим требованиям: возраст около 30 лет, рост не более 170 "
    "см, вес до 68—70 кг. Отбор кандидатов проводила особая группа специалистов госпиталя."
)


def _shown(s: OutlineSlide) -> list[str]:
    c = s.content
    return [s.headline, s.subtitle or "", *c.bullets, *c.paragraphs, *(f"{it.title} {it.text}".strip() for it in c.items), *(f"{n.value} {n.label}" for n in c.numbers)]


def test_g4_1_a_line_cut_where_no_clause_ends_is_its_whole_sentence():
    s = _slide(K.bullets, "Переломные события", bullets=["6 июня 1944 года союзные силы США", "В июле 1945 года США отправили Японии Потсдамскую декларацию, которую та отклонила"])
    W.check_slide(s, WW2_S7_G4, title="Переломные события (продолжение)", topic="Вторая мировая война")
    text = _all_text(s)
    assert "высадились в Нормандии" in text
    assert not any(x.strip().endswith("союзные силы США") for x in _shown(s))
    s = _slide(K.bullets, "Ход событий", bullets=["В конце полёта ТДУ конструктора Исаева проработала успешно", "В ходе спуска произошло вращение корабля со скоростью один оборот в секунду"])
    W.check_slide(s, GAG_A1_S4, title="Ход событий", topic="Полёт Гагарина")
    assert "но отключилась на секунду раньше" in _all_text(s)


def test_g4_2_the_launch_sentence_stays_on_its_slide():
    s = _slide(K.bullets, "Начало", paragraphs=["Выключение двигателя произошло только"])
    W.check_slide(s, GAG_A1_S3, title="Начало", topic="Полёт Гагарина")
    text = _all_text(s)
    assert "12 апреля 1961 года" in text and "Байконур" in text and "«Восток-1»" in text
    assert not any(x.strip().endswith("произошло только") for x in _shown(s))
    assert s.headline != "Начало"


def test_g4_2_a_rejected_headline_goes_back_as_the_first_line():
    s = _slide(K.bullets, "«Москвич 3е» — первая серийная модель 2024 года", bullets=["Электромобили в России отличаются более высокой стоимостью из-за цены на батареи, но имеют меньшие расходы на обслуживание и топливо"])
    W.check_slide(s, EV_S5, title="Продукты и цены", topic="Рынок электромобилей в России")
    assert "«Москвич 3е» стал одной из первых серийных моделей" in _all_text(s)


def test_g4_3_a_clock_time_a_project_number_and_requirements_are_never_key_figures():
    s = _slide(K.stat_row, "Ход событий", numbers=[NumberCallout(value="10 ч", label="Корабль сделал один оборот вокруг Земли"), NumberCallout(value="106 минут", label="полёт длился")])
    W.check_slide(s, GAG_S4_G4, title="Ход событий и переломные события", topic="Полёт Гагарина")
    assert not any(n.value.startswith("10") for n in s.content.numbers)
    assert "10 часов 53 минуты" in _all_text(s)  # the sentence, as it is
    s = _slide(K.stat_row, "Тенденции", numbers=[NumberCallout(value="22220", label="проекта ледоколы"), NumberCallout(value="более 10", label="атомных энергоблоков строит Россия")])
    W.check_slide(s, ENERGY_S5, title="Тенденции", topic="Возобновляемая энергетика в России")
    assert not any("22220" in n.value for n in s.content.numbers)
    s = _slide(K.stat_row, "Предпосылки и причины", numbers=[NumberCallout(value="30 лет", label="Возраст"), NumberCallout(value="68–70", label="Вес кг")])
    W.check_slide(s, GAG_S2_G4, title="Предпосылки и причины", topic="Полёт Гагарина")
    assert not s.content.numbers and "не более 170 см" in _all_text(s)


def test_g4_3_hedges_and_rates_stay_with_the_figure():
    s = _slide(K.stat_row, "Уран", numbers=[NumberCallout(value="3800", label="Тонн природного урана потребляет Россия"), NumberCallout(value="615 тыс.", label="Тонн урана в стране разведано")])
    W.check_slide(s, ENERGY_S3, title="Другие факты", topic="Возобновляемая энергетика в России")
    vals = {n.value: n.label for n in s.content.numbers}
    assert "около 3800" in vals and "в год" in vals["около 3800"], vals
    assert "около 615 тыс." in vals, vals


def test_g4_5_a_relative_time_is_resolved_and_a_working_title_becomes_a_statement():
    text = "По итогам 2024 года в России было зарегистрировано 59,6 тысяч электромобилей. В том же году было продано 17,8 тысячи электромобилей."
    s = _slide(K.big_number, "В том же году было продано 17,8 тысячи электромобилей", numbers=[NumberCallout(value="17,8 тыс", label="электромобилей продано в 2024 году")])
    W.check_slide(s, text, title="Объём рынка в цифрах", topic="Рынок электромобилей в России")
    assert not s.headline.startswith("В том же году")
    assert s.content.numbers[0].value == "17,8 тыс."  # G4-16
    s = _slide(K.bullets, "Ход событий (продолжение)", bullets=["22 июня 1941 года Германия начала вторжение в СССР", "7 декабря 1941 года Япония атаковала Перл-Харбор"])
    W.check_slide(s, WW2_S5, title="Ход событий (продолжение)", topic="Вторая мировая война")
    assert "продолжение" not in s.headline and W.coverage(s.headline, WW2_S5) >= 0.8
    assert not any(W.coverage(x, s.headline) >= 0.9 and W.coverage(s.headline, x) >= 0.9 for x in s.content.bullets)  # said once


def test_g4_5_no_two_slides_under_one_headline():
    a = _slide(K.bullets, "VK была основана в 1998 году", bullets=["Первоначально компания занималась разработкой почтовой службы Mail.ru"])
    b = OutlineSlide(id="s8", kind=K.cards, headline="VK была основана в 1998 году", content=SlideContent(items=[SlideItem(title="В 2021 году компания получила новое название"), SlideItem(title="В 2023 году были созданы две бизнес-группы")]))
    t2 = "VK была основана в 1998 году. Первоначально компания занималась разработкой почтовой службы Mail.ru."
    t8 = "VK была основана в 1998 году. В 2021 году компания получила новое название. В 2023 году были созданы две бизнес-группы."
    done = W.unique_headlines([(a, t2, "Основание"), (b, t8, "Главное")], deck=f"{t2}\n{t8}", topic="История VK")
    assert done and a.headline == "VK была основана в 1998 году" and b.headline != a.headline
    assert "1998" in _all_text(b)  # the old headline's sentence stays on its slide


def test_g4_6_lines_on_their_own_name_their_subject():
    text = ("VK владеет социальными сетями «ВКонтакте», «Одноклассники» и «Мой мир». Компания развивает образовательные платформы, "
            "такие как Skillbox и Geekbrains. Также она владеет поисковой системой «Поиск Mail» и сервисом объявлений «Юла».")
    s = _slide(K.cards, "VK владеет социальными сетями", items=[SlideItem(title="Компания развивает образовательные платформы"), SlideItem(title="Также она владеет поисковой системой «Поиск Mail» и сервисом объявлений «Юла»")])
    W.check_slide(s, text, deck=f"Слайд 2. Основание\nVK была основана в 1998 году.\n\nСлайд 5. Продукты\n{text}", title="Продукты и сервисы", topic="История VK")
    titles = [it.title for it in s.content.items] + s.content.bullets
    assert any(t.startswith("VK владеет поисковой системой") for t in titles), titles
    assert not any(t.startswith("Также") for t in titles)
    s = _slide(K.stat_row, "Итоги и потери", numbers=[NumberCallout(value="62", label="государства в ней"), NumberCallout(value="более 70 млн", label="человек погибло в результате войны")])
    W.check_slide(s, "Война длилась с 1 сентября 1939 по 2 сентября 1945 года. В ней участвовали 62 государства. В результате войны погибло более 70 миллионов человек.", title="Итоги и потери", topic="Вторая мировая война")
    labels = [n.label for n in s.content.numbers]
    assert "государства участвовали в войне" in labels, labels


def test_g4_14_a_definition_is_never_a_card():
    text = ("Вторая мировая война — война двух мировых военно-политических коалиций, ставшая крупнейшим вооружённым конфликтом в истории человечества. "
            "Версальский договор ограничил военную мощь Германии, что вызвало недовольство. В Азии Япония стремилась к доминированию, начав войны в Китае.")
    s = _slide(K.cards, "Причины войны", items=[SlideItem(title="Вторая мировая война", text="война двух мировых военно-политических коалиций"),
                                                SlideItem(title="Версальский договор ограничил военную мощь Германии, что вызвало недовольство"),
                                                SlideItem(title="В Азии Япония стремилась к доминированию, начав войны в Китае")])
    W.check_slide(s, text, title="Предпосылки и причины", topic="Вторая мировая война")
    assert not any(it.title == "Вторая мировая война" for it in s.content.items)
    assert "коалиций" in (s.headline + " " + (s.subtitle or ""))


def test_g4_17_the_writers_notice_passes_the_notes_check_as_it_is():
    from verstka.planning.grounding import BriefIndex, _Log, _notes
    from verstka.schemas.outline import Brief

    notice = "Текст написан агентом Verstka по статьям «Аполлон-11» и «Армстронг, Нил» из Википедии (лицензия CC BY-SA). Проверьте факты перед выступлением."
    idx = BriefIndex.of(Brief(text="Слайд 1. Полёт на Луну\nЛюди впервые высадились на Луну в 1969 году."))
    out = _notes(idx, f"Люди впервые высадились на Луну в 1969 году.\n\n{notice}", _Log())
    assert out.endswith(notice) and "1969" in out
