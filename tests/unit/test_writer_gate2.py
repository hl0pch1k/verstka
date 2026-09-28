"""Writer mode after gate 2 (planning/writer.py, reference.py, agent.py): the fact check never does more harm than
good, the pairing checks (a year next to a name, done vs planned, the direction of a transfer), the refill that keeps
the asked slide count, the chronology in time order, the short history's storyline, one figure and one total per deck,
the grammar lint, and the rules line kept out of the text the person sees. Offline: the answers are the ones Qwen3-32B
gave in the gate-2 live runs (tests/fixtures/writer/gate2_answers.json) and the articles they were written from."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from verstka.planning import agent as A
from verstka.planning import writer as W
from verstka.planning.reference import RefPage, cut_pages, fresh_cut
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
F = ROOT / "tests" / "fixtures" / "writer"
G2 = json.loads((F / "gate2_answers.json").read_text(encoding="utf-8"))
SKILLS = SkillsRegistry.load()
OFFLINE = {"reference": {"enabled": False}}


def _text(name: str) -> str:
    return (F / name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _support(key: str) -> W.ArticleSupport:
    arts = {"vk": ["vk_full.txt"], "ww2": ["ww2_full.txt"], "ev": ["ev_full.txt", "ev_ru_industry.txt"], "vostok": ["vostok1_full.txt"]}[key]
    return W.ArticleSupport([_text(a) for a in arts], G2[key]["topic"] if key in G2 else "Полёт Гагарина")


def _gate2_deck(key: str) -> W._Deck:
    a, _ = W.parse_answer(G2[key]["writer"])
    assert a is not None
    return W._deck_of(a)


def _check_issues(key: str) -> list[dict]:
    m = re.search(r"\{.*\}", G2[key]["check"], re.S)
    return json.loads(m.group(0))["issues"] if m else []


def _registry(fn) -> ProviderRegistry:
    return ProviderRegistry(roles={"llm": MockProvider(fn, model="Qwen/Qwen3-32B")}, limits=ProviderLimits(max_concurrency=2, time_budget_s=210))


def _slide(title: str, *sentences: str) -> dict:
    return {"title": title, "text": " ".join(sentences), "timeline": None, "data": None}


# ------------------------------------------------------------------ W1: the check never does more harm than good


def test_a_verdict_without_a_reason_or_with_an_acceptance_is_ignored():
    deck = W._Deck(slides=[W._Slide(title="Итоги", sentences=[
        "Война закончилась 2 сентября 1945 года.", "Погибло около 60—65 миллионов человек.", "Италия вела войну в Африке.",
        "Германия капитулировала 8 мая 1945 года.", "Япония капитулировала 2 сентября 1945 года.", "СССР понёс большие потери.",
    ])])
    stats: dict = {}
    n = W.apply_check(deck, [
        {"id": "1.1", "verdict": "unsupported", "problem": "the text says '2 сентября 1945 года', which is correct, so this is not an issue"},
        {"id": "1.2", "verdict": "unsupported", "problem": ""},
        {"id": "1.3", "verdict": "unsupported", "problem": "the reference does not say Italy fought in Africa at that time"},
    ], stats=stats)
    assert n == 1 and stats["ignored"] == 2 and not stats.get("degenerate")
    assert deck.slides[0].sentences[:2] == ["Война закончилась 2 сентября 1945 года.", "Погибло около 60—65 миллионов человек."]
    assert "Италия вела войну в Африке." not in deck.slides[0].sentences


def test_a_check_that_flags_most_statements_is_degenerate_and_the_article_decides():
    # gate 2 (История VK): 17 of 27 statements «unsupported» with empty reasons; ten true ones were removed
    deck = _gate2_deck("vk")
    stats: dict = {}
    removed: list[dict] = []
    W.apply_check(deck, _check_issues("vk"), removed, support=_support("vk"), overruled=[], stats=stats)
    assert stats["degenerate"] and stats["flagged"] > 0.35 * stats["statements"]
    kept = " ".join(sn for s in deck.slides for sn in s.sentences)
    assert "В 2010 году компания была переименована в Mail.ru Group, а в 2021 году — в VK." in kept
    assert "Дмитрий Андрианов добавил функцию просмотра почты" in kept and "Вдохновлённые успехом Hotmail" in kept
    # without the article a degenerate answer removes nothing
    deck2 = _gate2_deck("vk")
    before = [sn for s in deck2.slides for sn in s.sentences]
    stats2: dict = {}
    assert W.apply_check(deck2, _check_issues("vk"), [], stats=stats2) == 0 and stats2["degenerate"]
    assert [sn for s in deck2.slides for sn in s.sentences] == before


def test_the_article_supports_the_war_dates_the_losses_and_the_renames():
    ww2, vk = _support("ww2"), _support("vk")
    assert ww2.supported("Вторая мировая война началась 1 сентября 1939 года и закончилась 2 сентября 1945 года.")
    assert ww2.supported("Во время Второй мировой войны погибло около 60—65 миллионов человек.")
    assert vk.supported("В 2010 году компания была переименована в Mail.ru Group, а в 2021 году — в VK.")
    assert vk.supported("В 1998 году Дмитрий Андрианов добавил функцию просмотра почты.")  # no figure but its own: words
    assert vk.supported("Вдохновлённые успехом Hotmail, команда предложила создать публичный сервис.")
    assert not vk.supported("В 2006 году компания была переименована в Mail.ru Group.")
    assert vk.rename_fixed("В 2006 году компания была переименована в Mail.ru Group.") == "В 2010 году компания была переименована в Mail.ru Group."
    assert vk.pair_issue("В 2021 году компания Mail.ru Group была переименована в VK.") is None


def test_the_check_puts_the_articles_own_words_in_when_it_quotes_them():
    deck = W._Deck(slides=[W._Slide(title="Причины", sentences=[
        "Договор ограничил военную мощь Германии и передал ей колонии.", "Германия считала условия договора несправедливыми.",
    ] + [f"Факт номер {k} о войне." for k in range(3, 9)])])
    edits: list[dict] = []
    W.apply_check(deck, [{"id": "1.1", "verdict": "unsupported", "problem": "the treaty took territories from Germany",
                          "evidence": "Версальский договор крайне ограничил военную мощь Германии, а также передал из её состава ряд территорий другим странам"}],
                  support=_support("ww2"), edits=edits)
    assert deck.slides[0].sentences[0].startswith("Версальский договор крайне ограничил военную мощь Германии")
    assert edits and edits[0]["where"] == "1.1"


# ------------------------------------------------------------------ W4: the pairing checks


@pytest.mark.parametrize("key,text,kind,fixed", [
    ("vk", "VK была основана в 1998 году как компания Digital Sky Technologies.", "former", "VK была основана в 1998 году."),
    ("ev", "В 2026 году на заводе «Москвич» начнётся выпуск электрического кроссовера UMO 5.", "tense", "20 февраля 2026 года"),
    ("ev", "В 2024 году АвтоВАЗ начал производство электромобиля e-Largus.", "year", "В феврале 2025 года компания АвтоВАЗ сообщила о первой продаже электромобиля e-Largus"),
    ("ww2", "В марте 1941 года Германия начала военное вторжение в Югославию.", "month", "6 апреля 1941 года Германия начала военное вторжение в Югославию."),
    ("ww2", "В июле 1944 года Красная армия начала наступление в Восточной Белоруссии.", "month", "Летом 1944 года Красная армия"),
    ("ww2", "В марте 1943 года началась Курская битва, которая стала крупнейшей танковой битвой в истории.", "month", "В июле 1943 года началась Курская битва"),
    ("vostok", "В мае 1961 года Совет Министров утвердил программу первого пилотируемого полёта.", "event", "В мае 1959 года Совет Министров"),
    ("ev", "В 2024 году началось производство «Москвич 3е» на Московском автомобильном заводе.", "event",
     "В 2022 году началось производство «Москвич 3е» на Московском автомобильном заводе."),
    ("vk", "Компания активно расширялась, запуская новые продукты: «Одноклассники», «Мой мир», мессенджеры и сервис объявлений «Юла».", "verb",
     "запуская новые продукты: «Мой мир», мессенджеры и сервис объявлений «Юла»."),
    ("vk", "Основателем компании стал Евгений Голанд, а ключевую роль в создании почтового сервиса сыграли Алексей Кривенков и Дмитрий Андрианов.",
     "founder", "американской софтверной компании DataArt, основанной российским эмигрантом Евгением Голандом"),
    ("ev", "На заводе «Москвич» производятся модели «Москвич 3е» и «Атом», а также планируется выпуск электрического кроссовера UMO 5.", "tense",
     "20 февраля 2026 года на автозаводе «Москвич» началось производство"),
    ("ev", "В 2025 году общая стоимость владения электромобилем сравнялась с автомобилями с ДВС.", "place",
     "По состоянию на 2025 год общая стоимость владения электромобилями в мире была сопоставима"),
    ("ww2", "Договор ограничил военную мощь страны, передал ей территории и колонии.", "direction", "передал из её состава"),
    ("vk", "В 2006 году компания была переименована в Mail.ru Group.", "rename", "В 2010 году компания была переименована в Mail.ru Group."),
])
def test_a_wrong_pairing_is_repaired_in_the_articles_words(key, text, kind, fixed):
    sup = _support(key)
    p = sup.pair_issue(text)
    assert p is not None and p.kind == kind, p
    new = W._repair(text, p, sup)
    assert new is not None and fixed in new and sup.pair_issue(new) is None


@pytest.mark.parametrize("key,text", [
    ("ww2", "22 июня 1941 года Германия начала военную операцию против СССР под кодовым названием «Операция Барбаросса»."),
    ("ww2", "7 декабря 1941 года Япония атаковала Перл-Харбор, что привело к вступлению США в войну."),
    ("ww2", "В Азии Япония атаковала Китай с 1931 года и в июле 1937 года начала полномасштабную войну."),
    ("ww2", "Сталинградская битва 1942—1943 годов стала переломом на Восточном фронте."),
    ("ww2", "6 августа 1945 года США сбросили атомную бомбу на Хиросиму, а 9 августа — на Нагасаки."),
    ("vk", "В 2010 году компания была переименована в Mail.ru Group, а в 2021 году — в VK."),
    ("vk", "Первый прототип почтового сервиса Mail.ru был разработан Алексеем Кривенковым в 1997 году."),
    ("ev", "В 2026 году планируется выпуск 5–6 тыс. электромобилей «Атом» на заводе «Москвич»."),
    ("ev", "По итогам 2024 года в России было зарегистрировано 59,6 тыс. электромобилей."),
    ("ww2", "6 июня 1944 года союзники высадились в Нормандии."),
    ("ww2", "В августе 1945 года США атаковали Японию атомными бомбами в Хиросиме и Нагасаки."),
    ("ww2", "В феврале 1945 года на Ялтинской конференции были обсуждены послевоенные планы."),
    ("vk", "Почтовый сервис Mail.ru был запущен в тестовом режиме в конце 1990-х годов."),  # a decade is not the year 1990
    ("vk", "Идея создания публичного почтового сервиса возникла после успешной сделки Microsoft с Hotmail."),
    ("vk", "В 2023 году были созданы две бизнес-группы: «Социальные платформы и медиаконтент» и «Экосистемные и комплексные сервисы»."),
    ("vostok", "12 апреля 1961 года в 9 часов 7 минут по московскому времени с космодрома Байконур стартовал космический корабль «Восток-1»."),
    ("vostok", "В 1960 году были сформированы первые группы кандидатов в космонавты, включая Юрия Гагарина и Германа Титова."),
    # a day or a month the article writes without its year takes the sentence's year («…, а в октябре страна … была поделена»)
    ("ww2", "В октябре 1939 года Польша была поделена между Германией и СССР согласно пакту Молотова — Риббентропа."),
    ("ww2", "22 июля 1940 года ОКХ начало разработку плана «Операция Барбаросса»."),
    ("ev", "Эксперты McKinsey в 2024–2025 годах назвали электромобили одной из революционных технологий, вносящих вклад в экономический рост."),
    ("ev", "В 2024 году в России было продано 17,8 тыс. электромобилей."),
    ("vk", "Павел Дуров основал «ВКонтакте»."),
    ("ww2", "В июле 1943 года началась Курская битва."),
])
def test_a_right_pairing_is_left_alone(key, text):
    assert _support(key).pair_issue(text) is None


def test_the_pairings_are_fixed_across_the_deck_and_the_timeline():
    deck = W._Deck(slides=[
        W._Slide(title="Основание", sentences=["VK была основана в 1998 году как компания Digital Sky Technologies.", "Mail.ru работал в тестовом режиме."]),
        W._Slide(title="Хронология", sentences=["Ключевые даты компании."], timeline=[
            {"when": "1998 год", "what": "Основание компании Digital Sky Technologies"}, {"when": "2010 год", "what": "Переименование в Mail.ru Group"},
            {"when": "2021 год", "what": "Новое название VK"}, {"when": "2023 год", "what": "Реструктуризация"}]),
    ])
    removed: list[dict] = []
    edits: list[dict] = []
    W.fix_pairings(deck, _support("vk"), removed, edits)
    assert deck.slides[0].sentences[0] == "VK была основана в 1998 году."
    assert edits[0]["why"].startswith("former")
    assert [e["when"] for e in deck.slides[1].timeline] == ["2010 год", "2021 год", "2023 год"]
    assert any("Digital Sky" in r["text"] for r in removed)


# ------------------------------------------------------------------ W3: time order


@pytest.mark.parametrize("text,start", [
    ("22 июня 1941", (1941, 6, 22)), ("Июль 1937", (1937, 7, 0)), ("1931–1937", (1931, 0, 0)), ("20.02.2026", (2026, 2, 20)),
    ("Весна 1945", (1945, 3, 0)), ("Апрель — июнь 1940", (1940, 4, 0)), ("1 сентября 1939 года", (1939, 9, 1)), ("Май 1945", (1945, 5, 0)),
    ("Операция «Барбаросса»", None),
])
def test_a_date_title_parses_to_its_start(text, start):
    assert W.date_start(text) == start


def test_dated_items_are_sorted_stably_only_when_most_parse():
    ww2 = ["22 июня 1941", "1931–1937", "Июль 1937", "7 декабря 1941"]
    assert W.chrono_sort(ww2, str) == ["1931–1937", "Июль 1937", "22 июня 1941", "7 декабря 1941"]
    assert W.chrono_sort(["2024", "2026", "2025"], str) == ["2024", "2025", "2026"]
    assert W.chrono_sort(["Июнь 1940", "Апрель 1941", "Апрель 1940"], str) == ["Апрель 1940", "Июнь 1940", "Апрель 1941"]
    mixed = ["Начало", "Середина", "1941", "Конец"]
    assert W.chrono_sort(mixed, str) == mixed  # fewer than 80 % dated: the narrative's order
    a = W.WriterAnswer.model_validate({"slides": [{"title": "Хронология", "text": "Даты.", "timeline": [
        {"when": "2024", "what": "первые продажи"}, {"when": "2026", "what": "запуск завода"}, {"when": "2025", "what": "новая модель"}]}]})
    deck = W.normalise_answer(a, "электромобили", "")
    assert [e["when"] for e in deck.slides[0].timeline] == ["2024", "2025", "2026"]


def _design(kind, headline, text="", title="Ход событий", **content):
    from verstka.schemas.outline import OutlineSlide, SlideContent

    unit = A._Unit(key="u5", title=title, text=text)
    return A._Design(unit=unit, slide=OutlineSlide(id="s5", kind=kind, headline=headline, content=SlideContent(**content)), by="model")


def test_the_designers_timeline_cards_and_dated_list_are_in_time_order():
    from verstka.schemas.outline import SlideItem

    items = [SlideItem(title="22 июня 1941", text="Германия напала на СССР"), SlideItem(title="1931–1937", text="Япония атаковала Китай"),
             SlideItem(title="Июль 1937", text="Япония начала полномасштабную войну"), SlideItem(title="7 декабря 1941", text="Атака на Перл-Харбор")]
    d = _design(K.timeline, "Война охватила Европу и Азию", items=items)
    A._chrono_order(d)
    assert [it.title for it in d.slide.content.items] == ["1931–1937", "Июль 1937", "22 июня 1941", "7 декабря 1941"]
    cards = _design(K.cards, "Ход войны", items=[SlideItem(title="Апрель 1941", text="Югославия"), SlideItem(title="Июнь 1940", text="Франция"),
                                                 SlideItem(title="Сентябрь 1939", text="Польша")])
    A._chrono_order(cards)
    assert [it.title for it in cards.slide.content.items] == ["Сентябрь 1939", "Июнь 1940", "Апрель 1941"]
    bl = _design(K.bullets, "Производство", bullets=["2024 — прототип «Молния»", "2026 — выпуск UMO 5", "2022 — «Москвич 3е»"])
    A._chrono_order(bl)
    assert bl.slide.content.bullets == ["2022 — «Москвич 3е»", "2024 — прототип «Молния»", "2026 — выпуск UMO 5"]


# ------------------------------------------------------------------ W5: the short history, one figure and one total


def test_a_short_history_is_a_story_without_a_separate_chronology():
    parts = W.storyline_parts("history", 9, reference=True)
    assert [p.title for p in parts] == ["Предпосылки и причины", "Начало", "Ход событий", "Ход событий (продолжение)", "Переломные события",
                                         "Переломные события (продолжение)", "Окончание", "Итоги и потери", "Последствия"]
    assert not any(p.timeline for p in parts) and [p.data for p in parts].count(True) == 1
    assert "turning points" in W.storyline("history", 9, reference=True)
    assert any(p.timeline for p in W.storyline_parts("history", 14, reference=True))  # a long deck keeps its chronology


def test_a_short_decks_chronology_goes_when_the_narrative_carries_the_dates():
    tl = [{"when": "1 сентября 1939 года", "what": "нападение на Польшу"}, {"when": "22 июня 1941 года", "what": "нападение на СССР"},
          {"when": "8 мая 1945 года", "what": "капитуляция Германии"}, {"when": "2 сентября 1945 года", "what": "капитуляция Японии"}]
    slides = [W._Slide(title="Начало", sentences=["1 сентября 1939 года Германия напала на Польшу."]),
              W._Slide(title="Ход", sentences=["22 июня 1941 года Германия напала на СССР."]),
              W._Slide(title="Окончание", sentences=["8 мая 1945 года Германия капитулировала."]),
              W._Slide(title="Хронология", sentences=["Главные даты войны."], timeline=list(tl))]
    deck = W._Deck(slides=slides)
    W.dedupe_chronology(deck, [], short=True)
    assert [s.title for s in deck.slides] == ["Начало", "Ход", "Окончание"]
    # fewer dated slides: the timeline keeps the events no other slide dates (here too few: it goes)
    deck = W._Deck(slides=[W._Slide(title="Начало", sentences=["1 сентября 1939 года Германия напала на Польшу."]),
                           W._Slide(title="Итоги", sentences=["Война изменила карту мира.", "Появилась ООН."], timeline=list(tl))])
    W.dedupe_chronology(deck, [], short=True)
    assert [e["when"] for e in deck.slides[1].timeline] == ["22 июня 1941 года", "8 мая 1945 года", "2 сентября 1945 года"]


def test_a_figure_is_told_once_and_a_total_once():
    deck = W._Deck(slides=[
        W._Slide(title="Итоги и потери", sentences=["Во время войны погибло более 70 миллионов человек.", "В войне участвовали 62 государства, 80 % населения Земли."]),
        W._Slide(title="В цифрах", sentences=["Общие людские потери достигли 60—65 миллионов человек.", "В войне участвовали 62 государства и 80 % населения Земли.", "Мобилизовано 110 миллионов человек."]),
        W._Slide(title="Главное", sentences=["В войне участвовали 62 государства, 80 % населения Земли.", "Погибло более 70 миллионов человек."]),
    ])
    removed: list[dict] = []
    W.dedupe_totals(deck, removed)
    W.dedupe_figures(deck, removed)
    assert deck.slides[1].sentences == ["Мобилизовано 110 миллионов человек."]
    # gate 4 G4-9: the summing-up slide restates no figure another slide shows (it was one); left empty, it goes (the
    # writer's fill_summary gives it the deck's first and last dated statements)
    assert len(deck.slides) == 2 and deck.slides[-1].title == "В цифрах"
    whys = {r["why"].split(" slide")[0] for r in removed}
    assert "another total than" in whys and "repeats the figures of" in whys


# ------------------------------------------------------------------ W7: grammar, opinions, the hero figure, labels


def test_the_grammar_lint_fixes_the_governance_errors():
    assert W.fix_grammar("Войну участвовали 62 страны.") == "В войне участвовали 62 страны."
    assert W.fix_grammar("В битве участвовали две армии.") == "В битве участвовали две армии."
    assert W.fix_grammar("Битву участвовали две армии.") == "В битве участвовали две армии."
    a = W.WriterAnswer.model_validate({"slides": [{"title": "Итоги", "text": "Войну участвовали 62 страны. Погибло более 70 млн человек."}]})
    assert W.normalise_answer(a, "война", "")
    deck = W.normalise_answer(W.WriterAnswer.model_validate({"slides": [{"title": "Итоги", "text": "Войну участвовали 62 страны. Погибло более 70 млн человек."}]}), "война", "")
    assert deck.slides[0].sentences[0] == "В войне участвовали 62 страны."


def test_an_evaluation_goes_unless_the_reference_says_it():
    assert W.opinion_sentence("Электромобили в России — быстро развивающийся рынок.") == "быстро развивающийся"
    assert W.opinion_sentence("Электромобили в России — быстро развивающийся рынок.", "рынок быстро развивается") is None
    assert W.opinion_sentence("В 2024 году продажи выросли значительно.") is None  # a dated statement of fact stays
    d = _design(K.bullets, "Прогноз", "К 2030 году в мире будет 240 млн электромобилей.", bullets=["240 млн к 2030 году"])
    d.slide.takeaway = "Прогнозируется значительный рост рынка."
    A._plain_takeaway(d)
    assert d.slide.takeaway is None


def test_a_big_number_stands_only_under_a_headline_that_names_it():
    from verstka.schemas.outline import NumberCallout

    text = "По состоянию на 2023 год VK охватывает миллионы пользователей. Образовательные проекты VK ежегодно охватывают около 2800 студентов."
    d = _design(K.big_number, "VK охватывает миллионы пользователей по всему миру", text, title="Аудитория",
                numbers=[NumberCallout(value="2800", label="студентов в вузах ежегодно")])
    A._hero_supports_headline(d)
    assert d.slide.kind == K.bullets and not d.slide.content.numbers and "2800 студентов" in d.slide.content.bullets[0]
    ok = _design(K.big_number, "Проекты VK охватывают 2800 студентов в год", text, numbers=[NumberCallout(value="2800", label="студентов в год")])
    A._hero_supports_headline(ok)
    assert ok.slide.kind == K.big_number


def test_a_label_headline_becomes_a_statement():
    text = "В России началось строительство зарядной инфраструктуры. В 2022 году началось производство «Москвич 3е»."
    d = _design(K.bullets, "Инфраструктура", text, title="Инфраструктура", bullets=["Строятся зарядные станции"])
    A._sentence_headline(d)
    assert d.slide.headline == "В России началось строительство зарядной инфраструктуры"


# ------------------------------------------------------------------ W2: the asked slide count is a promise


def _writer_fake(first: dict, refill: dict | None, check: dict | None = None, seen: list | None = None):
    def fake(messages):
        system, user = messages[0].content, messages[-1].content
        if seen is not None:
            seen.append(user)
        if "You name encyclopedia articles" in system:
            return {"titles": [], "kind": "company"}
        if "fact-checker" in system:
            return check or {"issues": []}
        if "The deck already has these slides" in user:
            return refill or {"status": "ok", "slides": []}
        return first
    return fake


FIRST = {"status": "ok", "kind": "company", "title": "История VK", "subtitle": "От почты к экосистеме", "slides": [
    _slide("Основание", "Mail.ru запущен в 1998 году.", "Сервис начинался как бесплатная почта.", "Его разработала команда DataArt."),
    _slide("Первые годы", "В 2000-х годах компания росла.", "Появились новые сервисы.", "Компания привлекла инвесторов."),
    _slide("Развитие", "В 2010 году компания провела IPO на Лондонской бирже.", "Компания купила долю во «ВКонтакте».", "Позже она купила «Одноклассники»."),
    _slide("Продукты", "Компании принадлежат «ВКонтакте» и «Одноклассники».", "Она развивает почту и поиск.", "У неё есть облачные сервисы."),
    _slide("Современный этап", "В 2021 году компания получила название VK."),
    _slide("Главное", "VK — одна из крупнейших интернет-компаний России.", "Она объединяет соцсети и сервисы."),
]}


def test_a_slide_the_checks_empty_is_written_again_and_a_thin_one_is_topped_up():
    refill = {"status": "ok", "slides": [
        _slide("Структура и управление", "В 2023 году сервисы объединили в две бизнес-группы.", "Компанией управляет совет директоров.", "Штаб-квартира находится в Москве."),
        _slide("Современный этап", "В 2022 году компания продала долю в Delivery Club.", "В 2024 году выручка выросла."),
    ]}
    check = {"issues": [{"id": "2.1", "verdict": "unsupported", "problem": "not in the reference"}, {"id": "2.2", "verdict": "unsupported", "problem": "not in the reference"},
                        {"id": "2.3", "verdict": "unsupported", "problem": "not in the reference"}]}
    seen: list[str] = []
    res = W.write_deck(Brief(text="История VK", slide_count=7), W.writer_mode("История VK"), SKILLS, _registry(_writer_fake(FIRST, refill, check, seen)), config=OFFLINE)
    assert res.written and res.slides == 6 and res.short_by == 0, (res.slides, res.log_lines)
    titles = [line for line in res.text.splitlines() if line.startswith("Слайд ")]
    assert titles[-1].endswith("Главное") and any("Структура и управление" in t for t in titles)
    # the refilled slide goes to its place in the story, before the summing-up slide
    assert titles.index(next(t for t in titles if "Структура и управление" in t)) < len(titles) - 1
    assert "В 2022 году компания продала долю в Delivery Club." in res.text and res.refill["topped"] == 1 and res.refill["added"] == 1
    refill_prompt = next(x for x in seen if "The deck already has these slides" in x)
    assert "do not repeat any of them" in refill_prompt and "Mail.ru запущен в 1998 году." in refill_prompt
    assert any("дописал 1 слайд" in x for x in res.log_lines)
    assert res.record()["refill"]["asked"] == 2 and res.meta()["short_by"] == 0


def test_a_shortfall_is_said_whatever_its_size():
    check = {"issues": [{"id": "2.1", "verdict": "unsupported", "problem": "not in the reference"}, {"id": "2.2", "verdict": "unsupported", "problem": "not in the reference"},
                        {"id": "2.3", "verdict": "unsupported", "problem": "not in the reference"}]}
    res = W.write_deck(Brief(text="История VK", slide_count=7), W.writer_mode("История VK"), SKILLS, _registry(_writer_fake(FIRST, None, check)), config=OFFLINE)
    assert res.written and res.slides == 5 and res.short_by == 1
    assert any("вышло 6 слайдов вместо 7" in x for x in res.log_lines)
    notice = (ROOT / "web/src/lib/modelText.ts").read_text(encoding="utf-8")
    assert "want > total" in notice  # the result screen says «Вышло N слайдов вместо M» for any shortfall


# ------------------------------------------------------------------ W6: the rules line is the agent's


def test_the_person_never_sees_the_rules_line():
    res = W.write_deck(Brief(text="История VK", slide_count=7), W.writer_mode("История VK"), SKILLS, _registry(_writer_fake(FIRST, None)), config=OFFLINE)
    assert W.RULES_LINE not in res.text and W.RULES_LINE not in res.meta()["text"]
    assert res.brief.text.rstrip().endswith(W.RULES_LINE)


# ------------------------------------------------------------------ the reference: turning points and the refill's sections


def test_a_historys_cut_reaches_its_turning_points():
    pages = [RefPage("Вторая мировая война", text=_text("ww2_full.txt"))]
    plain = cut_pages(pages, 12000, "person")
    deep = cut_pages(pages, W._ref_limit({}, "history"), "history")
    assert "Сталинград" in deep and "Нормандии" in deep and "### Перелом на Восточном фронте" in deep
    assert len(deep) <= 18000 and "### " not in plain


def test_the_refill_reads_the_sections_the_deck_does_not_use_yet():
    used = "Версальский договор крайне ограничил военную мощь Германии. 1 сентября 1939 года Германия напала на Польшу."
    cut = fresh_cut([_text("ww2_full.txt")], used, limit=6000, want="Переломные события битвы сражения")
    assert 0 < len(cut) <= 6000 and "Предпосылки войны в Европе" not in cut
    assert not re.search(r"^## (?:Примечания|Литература|Ссылки)", cut, re.M)


def test_a_wrong_year_is_never_cut_into_another_wrong_statement():
    # «В 2006 году компания запустила «ВКонтакте»» — it did not (DST bought into it in 2007): without the year the
    # statement is still false, so it goes
    sup = _support("vk")
    text = "В 2006 году компания запустила социальную сеть «ВКонтакте», которая стала одним из ключевых продуктов."
    p = sup.pair_issue(text)
    assert p is not None and W._repair(text, p, sup) is None
    assert sup.pair_issue("Компания запустила социальную сеть «ВКонтакте».").kind == "verb"
    assert sup.pair_issue("Павел Дуров основал «ВКонтакте».") is None  # a name before the verb may be the founder


def test_a_timeline_entry_gets_the_articles_month():
    deck = W._Deck(slides=[W._Slide(title="Ход войны", sentences=["Германия наступала на Балканах."], timeline=[
        {"when": "Апрель 1940", "what": "вторжение в Данию и Норвегию"}, {"when": "Март 1941", "what": "вторжение Германии в Югославию"},
        {"when": "22 июня 1941", "what": "нападение на СССР"}])])
    edits: list[dict] = []
    W.fix_pairings(deck, _support("ww2"), [], edits)
    assert [e["when"] for e in deck.slides[0].timeline] == ["Апрель 1940", "6 апреля 1941", "22 июня 1941"]
    assert edits and edits[0]["why"].startswith("month")


def test_a_written_decks_key_figures_timeline_tense_and_notes():
    from verstka.schemas.outline import NumberCallout, SlideItem

    text = "В 2024 году в России зарегистрировали 59,6 тыс. электромобилей. Основные производители — «Москвич», «Автотор».\nПотери, тыс.:\n— A — 1;\n— B — 2.\nНужна столбчатая диаграмма: потери."
    d = _design(K.stat_row, "В 2024 году зарегистрировали 59,6 тыс. электромобилей", text, title="Главное",
                numbers=[NumberCallout(value="59,6 тыс.", label="Электромобилей"), NumberCallout(value="Москвич", label="Основной производитель"),
                         NumberCallout(value="2021 г", label="— ребрендинг")])
    A._written_kpis(d)
    assert [n.value for n in d.slide.content.numbers] == ["59,6 тыс."] and "Москвич — основной производитель" in d.slide.content.bullets
    assert "2021 г — ребрендинг" in d.slide.content.bullets
    assert A._written_notes(text) == "В 2024 году в России зарегистрировали 59,6 тыс. электромобилей. Основные производители — «Москвич», «Автотор»."
    assert A._written_notes("Годы.\nХронология:\n— 1998 год — запуск Mail.ru;\n— 2021 год — название VK.") == "Годы. 1998 год — запуск Mail.ru. 2021 год — название VK."
    tl = _design(K.timeline, "Почта Mail.ru", "Почта создана в 1998 году, скрипт написал Алексей Кривенков.", items=[SlideItem(title="1997—1998", text="Почта для DataArt"),
                                                                               SlideItem(title="Нью-Йорк", text="Кривенков создал скрипт")])
    A._undated_timeline(tl)
    assert tl.slide.kind == K.bullets and tl.slide.content.bullets == ["1997—1998 — почта для DataArt", "Нью-Йорк — Кривенков создал скрипт"]
    fut = _design(K.bullets, "Полёт получил признание", "Гагарин стал самым известным человеком планеты. Полёт длился 106 минут.",
                  bullets=["Гагарин станет самым известным человеком планеты", "Полёт длился 106 минут"])
    fut.slide.takeaway = "Полёт станет важным историческим событием"
    A._no_new_future(fut)
    assert fut.slide.takeaway is None and fut.slide.content.bullets == ["Полёт длился 106 минут", "Гагарин стал самым известным человеком планеты"] or \
        fut.slide.content.bullets == ["Гагарин стал самым известным человеком планеты", "Полёт длился 106 минут"]


def test_an_event_told_twice_goes_from_the_later_slide():
    deck = W._Deck(slides=[
        W._Slide(title="Переломные события", sentences=["19 ноября 1942 года Красная армия начала контрнаступление под Сталинградом.",
                                                         "В ходе операции были окружены и разгромлены две немецкие, две румынские и одна итальянская армии."]),
        W._Slide(title="Перелом на Востоке", sentences=["19 ноября 1942 года Красная армия перешла в контрнаступление под Сталинградом.",
                                                         "В ходе операции были окружены и разгромлены две немецкие, две румынские и одна итальянская армии.",
                                                         "Около 92 тысяч солдат было взято в плен."]),
        W._Slide(title="Главное", sentences=["19 ноября 1942 года Красная армия начала контрнаступление под Сталинградом."]),
    ])
    removed: list[dict] = []
    assert W.dedupe_events(deck, removed) == 2
    assert deck.slides[1].sentences == ["Около 92 тысяч солдат было взято в плен."] and len(deck.slides[2].sentences) == 1


def test_a_possessive_pronoun_without_its_antecedent_goes():
    assert W.anaphoric("Первоначально её основной задачей было развитие почтового сервиса Mail.ru.")
    assert not W.anaphoric("В их числе «ВКонтакте» и «Одноклассники».")
    deck = W._Deck(slides=[W._Slide(title="Основание", sentences=["Первоначально её основной задачей было развитие почты.", "Сервис создан в 1998 году."])])
    W.drop_orphans(deck, [])
    assert deck.slides[0].sentences == ["Сервис создан в 1998 году."]


def test_a_chart_row_is_never_a_ranges_bound():
    # «Общие потери — 65» of «Общие людские потери достигли 60—65 млн человек»
    sup = _support("ww2")
    assert sup.range_bound_only(65, "Общие потери") and not sup.range_bound_only(27, "Убитые на фронтах")
    deck = W._Deck(slides=[W._Slide(title="Итоги", sentences=["Общие людские потери достигли 60—65 млн человек."], data={
        "caption": "Людские потери", "unit": "млн человек", "chart": "column",
        "rows": [{"label": "Мобилизованные", "value": 110.0}, {"label": "Общие потери", "value": 65.0}, {"label": "Убитые на фронтах", "value": 27.0}]})])
    removed: list[dict] = []
    W.verify_against(deck, [_text("ww2_full.txt")], "Вторая мировая война", removed, support=sup)
    assert any(r["why"] == "the article gives a range, not this value" for r in removed) and deck.slides[0].data is None


def test_a_figure_line_says_what_its_sentence_counts_and_a_count_is_not_a_year():
    from verstka.schemas.outline import NumberCallout

    text = "6 июня 1944 года союзные силы высадились в Нормандии. Для операции было выделено 1213 кораблей и 4126 десантных судов."
    d = _design(K.bullets, "Высадка в Нормандии", text, title="Высадка", bullets=["1213 — Кораблей США", "4126 — десантных судов"])
    A._true_bullet_labels(d)
    assert d.slide.content.bullets == ["Для операции было выделено 1213 кораблей и 4126 десантных судов", "4126 — десантных судов"]
    assert A._date_callout(NumberCallout(value="6 июня 1944", label="Дата высадки"), source=text)
    assert not A._date_callout(NumberCallout(value="1213", label="Кораблей"), source=text)
    assert A._date_callout(NumberCallout(value="1998", label="запуск"), source="В 1998 году запущен Mail.ru.")


def test_a_sentence_tied_to_a_removed_one_loses_its_conjunction():
    assert W.unlinked("Однако в других странах введены требования к шуму.") == "В других странах введены требования к шуму."
    assert W.unlinked("Кроме того, компания купила долю.") == "Компания купила долю."
    s = W._Slide(title="Инфраструктура", sentences=["В России нет значительных данных о зарядке.", "Однако в других странах введены требования к шуму."])
    W._prune(s, lambda sn: "opinion" if "значительных" in sn else None, [], "1")
    assert s.sentences == ["В других странах введены требования к шуму."]


def test_every_bought_item_leaves_the_list_and_a_noun_is_not_a_past_tense():
    sup = _support("vk")
    s = "Компания начала активно расширять портфель продуктов: запустила социальные сети «ВКонтакте», «Одноклассники», «Мой мир», а также сервис объявлений «Юла»."
    p = sup.pair_issue(s)
    fixed = W._repair(s, p, sup)
    assert fixed is not None and "ВКонтакте" not in fixed and "Одноклассники" not in fixed and "«Мой мир»" in fixed
    # gate 3 W3-4: a list told «в этот период» dates its items by the sentence before it — nothing checks that year, so
    # the sentence goes instead of keeping «запущены в этот период … «Мой мир»» (2010, false)
    then = "В этот период " + s[0].lower() + s[1:]
    p2 = sup.pair_issue(then)
    assert p2 is not None and W._repair(then, p2, sup) is None
    ev = _support("ev")
    t = "В 2026 году ожидается начало производства новой модели электрического кроссовера UMO 5."
    p = ev.pair_issue(t)
    assert p is not None and p.kind == "tense" and W._repair(t, p, ev).startswith("20 февраля 2026 года")


def test_a_written_decks_time_axis_has_dates():
    from verstka.schemas.outline import OutlineSlide, SlideContent, SlideItem

    s = OutlineSlide(id="s", kind=K.cards, headline="Основание", content=SlideContent(items=[
        SlideItem(title="Компания DataArt основана Евгением Голандом"), SlideItem(title="Кривенков создал скрипт"), SlideItem(title="Проект стал основой")]))
    written = "Слайд 1. Титульный\nНазвание: «История VK».\n\n" + W.RULES_LINE
    assert A.reshape(s, "timeline", case_text=written) is None
    assert A.reshape(s, "timeline", case_text="Кофейня: план на 6 месяцев.") is not None  # a faithful deck as before
    assert W.is_written_text(W.with_rules("Слайд 1. Титульный\nНазвание: «X».\n"))


def test_a_part_larger_than_its_whole_is_cut():
    assert W.fix_including("В войне участвовали 62 государства, включая 110 млн мобилизованных солдат.") == "В войне участвовали 62 государства."
    assert W.fix_including("В войне участвовали 62 государства, включая 80 % населения Земли.") == "В войне участвовали 62 государства (80 % населения Земли)."
    same = "Погибло более 70 миллионов человек, включая 27 миллионов граждан СССР."
    assert W.fix_including(same) == same


def test_the_refill_of_a_place_topic_reads_that_places_sections_only():
    full = [_text("ev_full.txt"), _text("ev_ru_industry.txt")]
    cut = fresh_cut(full, "В 2024 году в России было продано 17,8 тыс. электромобилей.", limit=9000, want="Инфраструктура", focus="росси")
    assert cut and "## В России" in cut and "Вермонт" not in cut


def test_layoffs_and_loss_rankings_stay_out_of_a_company_history():
    deck = W._Deck(slides=[W._Slide(title="Современный этап", sentences=[
        "В 2023 году компания провела редомициляцию в Россию.",
        "В сентябре и начале октября 2024 года VK покинули несколько сотен человек, а всего компания собирается уволить до пары тысяч сотрудников.",
        "В 2023 году компания заняла пятое место в рейтинге самых убыточных российских компаний."])])
    W.guard_company(deck, [])
    assert deck.slides[0].sentences == ["В 2023 году компания провела редомициляцию в Россию."]
    assert [e.text for e in _support("ev").entities("Началось производство «Москвич 3е» и «Эволют».")][:1] == ["Москвич 3е"]
