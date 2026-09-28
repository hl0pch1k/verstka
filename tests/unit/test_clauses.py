"""Writer mode: a sentence shortened only where a clause ends, read on its own, key figures that are figures
(planning/clauses.py, gate 4 G4-1, G4-3, G4-6, G4-16). The sentences are the ones the gate found cut or orphaned."""

from __future__ import annotations

import pytest

from verstka.planning import clauses as C
from verstka.planning.grounding import figures

NORMANDY = "6 июня 1944 года союзные силы США, Великобритании и Канады после двух месяцев отвлекающих манёвров провели крупнейшую десантную операцию в истории и высадились в Нормандии."
ENGINE = "Выключение двигателя произошло только после срабатывания дублирующего механизма, но корабль уже поднялся на орбиту, высшая точка которой оказалась на 100 км выше расчётной."
TDU = "В конце полёта ТДУ конструктора Исаева проработала успешно, но отключилась на секунду раньше, в результате чего автоматика выдала запрет на штатное разделение отсеков."
UNITS = "Кроме возведения АЭС средней и большой мощности в России строят энергоблоки с реакторами малой мощности."
COLUMBUS = (
    "Полёт Юрия Гагарина часто сравнивают с такими важными событиями, ставшими историческими вехами, как плавание Христофора "
    "Колумба, приведшее к открытию Америки, или первый перелёт через Атлантический океан, совершённый Джоном Олкоком и Артуром Брауном."
)
FIRST_MET = "Первыми людьми, которые встретили космонавта после полёта, оказались жена местного лесника Анна Тахтарова и её шестилетняя внучка Рита; Гагарин их успокоил и попросил расстегнуть гермошлем."
CANDIDATES = "Для полёта в космос требовались кандидаты, соответствующие строгим требованиям: возраст около 30 лет, рост не более 170 см, вес до 68—70 кг."


# ------------------------------------------------------------------ G4-1: a cut only where a clause ends


@pytest.mark.parametrize("sentence", [NORMANDY, ENGINE, UNITS, COLUMBUS, FIRST_MET, CANDIDATES])
@pytest.mark.parametrize("limit", [10, 12, 14, 20])
def test_no_cut_leaves_a_fragment(sentence, limit):
    head = C.safe_cut(sentence, limit)
    bad = ("союзные силы США", "произошло только", "строят энергоблоки", "такими важными событиями", "после полёта", "требовались кандидаты")
    assert head is None or not any(head.endswith(b) for b in bad), head
    # fit never returns a fragment: the head or the whole sentence
    out = C.fit(sentence, limit)
    assert out == C.H.strip_end(sentence) or (head is not None and out == head)


def test_a_contrast_is_never_dropped():
    head = C.safe_cut(TDU, 14)
    assert head is None or "но отключилась на секунду раньше" in head
    assert C.safe_cut("Ракета-носитель проработала без замечаний, но на завершающем этапе не сработала система радиоуправления.", 6) is None


def test_a_head_keeps_its_own_verb_and_a_relative_clause_is_not_it():
    assert C.has_predicate("Версальский договор ограничил военную мощь Германии")
    assert C.has_predicate("В 2023 году были созданы две бизнес-группы")
    assert C.has_predicate("Экипаж корабля — Юрий Алексеевич Гагарин")
    assert not C.has_predicate("6 июня 1944 года союзные силы США")
    assert not C.has_predicate("Первыми людьми, которые встретили космонавта после полёта")
    for w in ("полёт", "перелёт", "около", "минут", "автомобили", "модели", "бюджет"):
        assert not C.is_verb(w), w
    for w in ("произошло", "растёт", "строят", "вторглась", "является", "стартовал"):
        assert C.is_verb(w), w


def test_safe_cuts_that_say_a_whole_thing():
    assert C.safe_cut("Версальский договор ограничил военную мощь Германии, что вызвало недовольство.", 8) == "Версальский договор ограничил военную мощь Германии"
    assert C.safe_cut("19 ноября 1942 года Красная армия перешла в контрнаступление под Сталинградом, окружив и разгромив немецкие войска.", 12) == "19 ноября 1942 года Красная армия перешла в контрнаступление под Сталинградом"
    assert C.safe_cut("VK владеет социальными сетями «ВКонтакте», «Одноклассники» и «Мой мир», а также мессенджерами «Max» и «VK Мессенджер».", 12) == "VK владеет социальными сетями «ВКонтакте», «Одноклассники» и «Мой мир»"
    # «сообщил, что…»: what was said is the sentence
    assert C.safe_cut("В апреле 2025 года спецпредставитель президента РФ Борис Титов сообщил, что Россия строит более 10 атомных энергоблоков за рубежом.", 12) is None


def test_a_line_that_starts_a_sentence_is_checked_where_it_was_cut():
    assert C.cut_is_safe("6 июня 1944 года союзные силы США", NORMANDY) is False
    assert C.cut_is_safe("Выключение двигателя произошло только", ENGINE) is False
    assert C.cut_is_safe("В конце полёта ТДУ конструктора Исаева проработала успешно", TDU) is False
    assert C.cut_is_safe("Полёт Юрия Гагарина часто сравнивают с такими важными событиями", COLUMBUS) is False
    assert C.cut_is_safe("Первыми людьми, которые встретили космонавта после полёта", FIRST_MET) is False
    assert C.cut_is_safe("Кроме возведения АЭС средней и большой мощности в России строят энергоблоки", UNITS) is False
    assert C.cut_is_safe("Версальский договор ограничил военную мощь Германии", "Версальский договор ограничил военную мощь Германии, что вызвало недовольство.") is True
    assert C.cut_is_safe("Совсем другая строка", NORMANDY) is None


# ------------------------------------------------------------------ G4-6: a sentence on its own

DECK = (
    "Полёт Гагарина длился 106 минут. Через несколько дней Гагарин был торжественно встречен в Москве. VK была основана в 1998 году. "
    "При петербургском дворе обычай подавать по утрам чашечку шоколада ввела, по-видимому, Екатерина II."
)


def test_a_leading_connector_goes():
    assert C.strip_connector("Также компания приобрела 45 % онлайн-школы «Тетрика».") == "Компания приобрела 45 % онлайн-школы «Тетрика»."
    assert C.strip_connector("Кроме того, Россия строит энергоблоки за рубежом.") == "Россия строит энергоблоки за рубежом."
    assert C.strip_connector("Полёт также укрепил статус Гагарина.") == "Полёт также укрепил статус Гагарина."


def test_pronouns_take_the_name_the_text_gives():
    assert C.standalone("Он стал первым человеком в космосе.", ["Полёт Гагарина длился 106 минут."], DECK) == "Гагарин стал первым человеком в космосе."
    assert C.standalone("Также она владеет поисковой системой «Поиск Mail».", ["VK владеет социальными сетями.", "Компания развивает образовательные платформы."], DECK) == "VK владеет поисковой системой «Поиск Mail»."
    assert C.standalone("В 2019 году её доход составил 87,6 млрд рублей.", ["VK была основана в 1998 году."], DECK) == "В 2019 году доход VK составил 87,6 млрд рублей."
    assert C.standalone("Большим гурманом был и её первый министр Никита Панин.", ["При петербургском дворе обычай подавать по утрам чашечку шоколада ввела, по-видимому, Екатерина II."], DECK) == "Большим гурманом был и первый министр Екатерины II Никита Панин."
    assert C.standalone("В ней участвовали 62 государства.", ["Война длилась с 1 сентября 1939 по 2 сентября 1945 года."], DECK) == "В войне участвовали 62 государства."
    assert C.standalone("14 апреля 1961 года он получил звание Героя Советского Союза.", ["Одна группа военных повезла Гагарина в расположение части."], DECK) == "14 апреля 1961 года Гагарин получил звание Героя Советского Союза."
    before = ["Первым продуктом компании стал почтовый сервис Mail.ru, разработанный Алексеем Кривенковым и Дмитрием Андриановым."]
    assert C.standalone("Вдохновлённые покупкой Hotmail Microsoft, они предложили создать публичный почтовый сервис.", before, DECK) == (
        "Вдохновлённые покупкой Hotmail Microsoft, Алексей Кривенков и Дмитрий Андрианов предложили создать публичный почтовый сервис."
    )
    # a pronoun with no name to take stays leaning (the caller keeps it next to its sentence or drops it)
    assert C.standalone("Он стал первым.", ["Погода была ясной."], DECK) is None
    assert C.standalone("Его пили только мужчины знатного происхождения.", ["Какао-бобы растирали в пасту с маисом."], DECK) is None
    # a sentence with its own name before a singular pronoun reads on its own; a plural one leans on the sentence before
    assert C.standalone("В 2019 году VK увеличила выручку, её доля выросла.", [], DECK) == "В 2019 году VK увеличила выручку, её доля выросла."
    assert C.leans("Гагарин их успокоил.")


# ------------------------------------------------------------------ G4-3, G4-16: key figures


def _kind(sentence: str, digits: str) -> str | None:
    f = next(f for f in figures(sentence) if f.date is None and sentence[f.start:f.end].replace(" ", "") == digits)
    return C.figure_kind(sentence, f.start, f.end)


def test_a_clock_time_a_project_number_a_bound_are_not_key_figures():
    assert _kind("Корабль сделал один оборот вокруг Земли, и в 10 часов 53 минуты посадка произошла в районе деревни Смеловка.", "10") == "clock"
    assert _kind("Старт состоялся в 9:07 по московскому времени.", "9") == "clock"
    assert _kind("Также развивается транспортная ядерная энергетика, включая ледоколы проекта 22220.", "22220") == "code"
    assert _kind("Решение принято в Постановлении ЦК КПСС № 22-10 от 5 января 1959 года.", "22") == "code"
    assert _kind(CANDIDATES, "170") == "bound"
    assert _kind(CANDIDATES, "30") == "requirement"
    assert _kind("Выручка выросла до 330 рублей.", "330") is None
    assert _kind("Россия потребляет около 3800 тонн природного урана в год.", "3800") is None
    uran = "Россия потребляет около 3800 тонн природного урана в год."
    assert C.hedge_of(uran, uran.find("3800")) == "около"


def test_thousands_keep_their_period():
    assert C.fix_scale("17,8 тыс") == "17,8 тыс."
    assert C.fix_scale("615 тыс.") == "615 тыс."
    assert C.fix_scale("5 млн.") == "5 млн"
    assert C.fix_scale("2 млрд. ₽") == "2 млрд ₽"
