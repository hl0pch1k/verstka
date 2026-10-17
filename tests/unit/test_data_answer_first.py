"""Ответ на вопрос брифа первым (qa4, NEW-S1…S5, S3, E3): обложка отвечает на главный вопрос, слайды ответов — в
начале, у каждого вопроса — карточка итога; заголовок итога — вывод, а не «Четыре главных вывода»; верные числа файла
принимаются и становятся фактами; узкое место — узким местом; шаги — из текста файлов или узкого места данных."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from verstka.data.answer import step_grounded, summary_headline, topic_only
from verstka.data.readers import read_file
from verstka.data.story import build_data_story
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
Q1 = "Какой регион приносит больше всего и где мы растём быстрее? Что с NPS?"
Q2 = "Хватает ли нам прямых продаж или пора развивать партнёров?"
SALES_BRIEF = ("Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, что даёт "
               "выручку и где узкие места. Данные — в приложенных файлах.")
SCIENCE_BRIEF = ("Итоги университета за 2026 год для учёного совета. Покажи, как подготовка влияет на баллы ЕГЭ, как устроен "
                 "приём по формам обучения, как растёт наука и на что ушёл бюджет НИОКР. Данные — в приложенных файлах.")


def _tables(folder: str):
    return [t for p in sorted((ROOT / "examples" / folder).iterdir()) if p.suffix in (".csv", ".xlsx", ".json", ".txt") for t in read_file(p)]


@pytest.fixture(scope="module")
def sales():
    return _tables("data-sales-2026")


@pytest.fixture(scope="module")
def science():
    return _tables("data-science-2026")


def _told(tables, brief: str, answer: dict):
    """The story with a model that answers every call with `answer` (the storyteller's JSON)."""
    mp = MockProvider(lambda messages: answer, model="qwen-test")
    return build_data_story(Brief(text=brief), tables, use_llm=True, skills=SkillsRegistry.load(), providers=ProviderRegistry(roles={"llm": mp}))


def _summary(o):
    return next(s for s in o.slides if s.id == "summary")


def _data(o):
    return [s for s in o.slides if s.data is not None]


def _by_file(o, file):
    return next(s for s in o.slides if s.data is not None and s.data.file == file)


def _plain(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace(" ", " "))


def _figures(s) -> set:
    return {round(f.value, 2) for f in s.data.headline_facts}


# ── NEW-S2: the question brief is answered first ─────────────────────────────────────────────────────────────────────
def test_a_question_brief_is_answered_on_the_cover_first_and_in_the_summary(sales):
    st = build_data_story(Brief(text=Q1), sales)
    o = st.outline
    assert o.title == "Москва даёт 41% выручки, Казань растёт быстрее всех" and o.slides[0].headline == o.title
    assert "Что с NPS?" in (o.subtitle or "") and o.title != "Что показывают данные"
    assert [s.data.file for s in _data(o)][:2] == ["Регионы.xlsx", "NPS по кварталам.csv"]
    cards = _summary(o).content.items
    assert "Москва" in cards[0].text and "NPS" in cards[1].text
    assert [q["file"] for q in st.questions] == ["Регионы.xlsx", "NPS по кварталам.csv"]


def test_a_question_about_two_channels_gets_their_shares_sums_and_deals(sales):
    st = build_data_story(Brief(text=Q2), sales)
    o = st.outline
    assert _data(o)[0].data.file == "Каналы продаж.json"
    assert _plain(o.title) == "Прямые продажи — 46% выручки, партнёры — 28%" and Q2 in (o.subtitle or "")
    card = _summary(o).content.items[0]
    text = _plain(card.text)
    assert "партнёры — 28% (978 млн ₽)" in text and "сделок: 391" in text and "сделок: 214" in text
    assert card.title == "Прямые продажи и партнёры" and card.number == "46%"
    # every figure said is a fact of the channels' slide: the audit's figure checks read them
    assert {28.0, 978.0, 391.0, 214.0} <= _figures(_by_file(o, "Каналы продаж.json"))


def test_a_brief_without_questions_keeps_its_own_cover_and_order(sales):
    o = build_data_story(Brief(text=SALES_BRIEF), sales).outline
    assert o.title.startswith("Итоги продаж VK Cloud") and _data(o)[0].data.file == "Итоги квартала.txt"


# ── NEW-S1: the summary's headline is a conclusion ───────────────────────────────────────────────────────────────────
def test_the_summary_headline_says_the_two_strongest_conclusions(sales, science):
    o = build_data_story(Brief(text=SALES_BRIEF), sales).outline
    head = _plain(_summary(o).headline)
    assert head == "Выручка растёт быстрее числа клиентов; Москва даёт 41% выручки"
    assert not topic_only(head) and "главных вывода" not in head
    q1 = build_data_story(Brief(text=Q1), sales).outline
    assert _plain(_summary(q1).headline) == "Москва даёт 41% выручки; NPS вырос до 52"
    sci = build_data_story(Brief(text=SCIENCE_BRIEF), science).outline
    assert not topic_only(_summary(sci).headline)
    assert summary_headline(["Прямые продажи дают 46% выручки: 1 608 из 3 495 млн ₽", "Партнёры растут"]) == "Прямые продажи дают 46% выручки; партнёры растут"


@pytest.mark.parametrize("text, topic", [
    ("Ключевые итоги 2026 года", True), ("КЛЮЧЕВЫЕ ИТОГИ ГОДА", True), ("Четыре главных вывода", True),
    ("Итоги III квартала 2026: рост выручки и NPS", True), ("Рост выручки опережает рост клиентской базы", False),
    ("NPS вырос до 52", False), ("Прямые продажи — 46% выручки, партнёры — 28%", False),
])
def test_a_topic_is_told_from_a_conclusion(text, topic):
    assert topic_only(text) is topic


def test_the_models_label_for_the_summary_is_refused_and_a_conclusion_taken(sales):
    for label in ("КЛЮЧЕВЫЕ ИТОГИ ГОДА", "Ключевые итоги 2026 года", "Четыре главных вывода"):
        st = _told(sales, SALES_BRIEF, {"summary_title": label})
        assert _summary(st.outline).headline != label
        assert any(r["what"] == "summary_title" and not r["accepted"] for r in st.rephrased)
    st = _told(sales, SALES_BRIEF, {"summary_title": "Выручка растёт быстрее числа клиентов, Москва даёт 41% выручки"})
    assert _summary(st.outline).headline == "Выручка растёт быстрее числа клиентов, Москва даёт 41% выручки"


def test_the_models_topic_title_does_not_replace_the_answer(sales):
    st = _told(sales, Q1, {"title": "Итоги III квартала 2026: рост выручки и NPS", "subtitle": "Для правления"})
    assert st.outline.title == "Москва даёт 41% выручки, Казань растёт быстрее всех"
    refused = {r["what"]: r["why"] for r in st.rephrased if not r["accepted"]}
    assert "тема" in refused["title"] and "вопрос" in refused["subtitle"]


# ── NEW-S3: a true figure of the file a line names is accepted and becomes a fact ────────────────────────────────────
def test_a_true_figure_of_the_named_file_is_accepted(sales):
    st = _told(sales, Q2, {
        "headlines": [{"id": _by_file(build_data_story(Brief(text=Q2), sales).outline, "Каналы продаж.json").id,
                       "headline": "Прямые продажи дают 46% выручки, онлайн — лишь 9%"}],
        "summary": ["Прямые продажи дают 46% выручки, партнёры — 28% и 391 сделка против 214"],
        "next_steps": ["Развивать партнёрский канал за счёт регионов, где выручка растёт быстрее", "Удержать темп роста в IV квартале"],
    })
    o = st.outline
    ch = _by_file(o, "Каналы продаж.json")
    assert ch.headline == "Прямые продажи дают 46% выручки, онлайн — лишь 9%" and 9.0 in _figures(ch)
    assert _summary(o).content.items[0].text.startswith("Прямые продажи дают 46% выручки, партнёры — 28%")
    # a cell said of another row is refused: 9% is Онлайн's, not the partners'
    st2 = _told(sales, Q2, {"headlines": [{"id": ch.id, "headline": "Партнёры дают лишь 9% выручки"}]})
    assert _by_file(st2.outline, "Каналы продаж.json").headline != "Партнёры дают лишь 9% выручки"


def test_a_step_about_the_tail_in_hours_is_accepted(sales):
    st = _told(sales, SALES_BRIEF, {"next_steps": [
        "Удержать темп роста в IV квартале за счёт партнёрского канала", "Сократить хвост обращений дольше 10 часов"]})
    steps = next(s for s in st.outline.slides if s.id == "next-steps")
    assert [i.title for i in steps.content.items][1] == "Сократить хвост обращений дольше 10 часов"
    assert 10.0 in _figures(_by_file(st.outline, "Время ответа поддержки.csv"))


# ── NEW-S5: next steps stand on the files' proposal or on a weak spot ────────────────────────────────────────────────
def test_invented_next_steps_are_refused(science):
    st = _told(science, SCIENCE_BRIEF, {"next_steps": [
        "Сохранить рост приёма на бюджетные места ИТ-направлений",
        "Перераспределить бюджет НИОКР в пользу кафедр с падающим объёмом",
        "Усилить работу с абитуриентами по подготовке к ЕГЭ",
        "Усилить поддержку студентов с низкой стипендиальной нагрузкой",
    ]})
    verdict = {r["to"]: r["accepted"] for r in st.rephrased if r["what"] == "next_step"}
    assert verdict["Сохранить рост приёма на бюджетные места ИТ-направлений"]
    assert verdict["Перераспределить бюджет НИОКР в пользу кафедр с падающим объёмом"]
    assert not verdict["Усилить работу с абитуриентами по подготовке к ЕГЭ"]
    assert step_grounded("Усилить поддержку студентов с низкой стипендиальной нагрузкой", "сохранить рост приёма", set(), set())[0] is False


# ── S3 and NEW-S4: a weak spot said as one; topics and signs on the cards ────────────────────────────────────────────
def test_a_bottleneck_the_brief_asks_about_is_a_weak_spot_card(sales):
    cards = _summary(build_data_story(Brief(text=SALES_BRIEF), sales).outline).content.items
    weak = next(c for c in cards if c.title.startswith("Узкое место"))
    assert _plain(weak.text).startswith("20% обращений — больше 120 мин") and weak.number == "20%"
    st = _told(sales, SALES_BRIEF, {"summary": ["Выручка растёт быстрее числа клиентов: +23% против +18%", "Москва даёт 41% выручки, Казань растёт быстрее всех",
                                                 "Прямые продажи приносят почти половину выручки — 46%", "80% обращений получают ответ за 2 часа"]})
    assert any(c.title.startswith("Узкое место") and "20%" in c.text for c in _summary(st.outline).content.items)


def test_card_labels_are_topics_and_changes_keep_their_sign(sales, science):
    cards = _summary(build_data_story(Brief(text=SALES_BRIEF), sales).outline).content.items
    assert cards[0].title == "Выручка и клиенты"
    sci = _summary(build_data_story(Brief(text=SCIENCE_BRIEF), science).outline).content.items
    assert sci[0].number == "+6%" and not any(c.title in ("Итоги года", "Итоги квартала") for c in sci)


# ── E3: one period after a refusal ───────────────────────────────────────────────────────────────────────────────────
def test_a_refusal_reply_ends_with_one_period():
    from verstka.api.app import _refused_reply

    assert _refused_reply("«Таблица» не подходит: 512 строк не показать.") == "Не получилось: «Таблица» не подходит: 512 строк не показать."
    assert _refused_reply("Слайда 12 нет").endswith("нет.")


# ── short conclusions beside the chart: the main facts, never every category ─────────────────────────────────────────
def test_a_caption_says_its_main_facts_and_keeps_what_the_gaps_mean():
    from verstka.data.story import short_caption

    assert short_caption("Прямые продажи — 46%, Партнёры — 28%, Маркетплейс — 17%, Онлайн — 9%") == "Прямые продажи — 46%, Партнёры — 28%."
    long_ = ("С 2005 по 2025 год: Scopus — с 42 до 381 статьи, РИНЦ — с 255 до 867 статей. РИНЦ: максимум 985 статей в 2019 году, "
             "затем ниже. За 2016 год данных нет.")
    got = short_caption(long_)
    assert len(got) <= 140 and got.endswith("За 2016 год данных нет.") and "максимум 985" not in got
    nps = "NPS: IV кв. 2024 — 41, III кв. 2026 — 52 (+11 п. за 7 кварталов). За II кв. 2025 и II кв. 2026 данных нет — на графике разрывы, а не ноль."
    assert short_caption(nps) == nps  # («IV кв. 2024» is no end of a sentence)


def test_data_slides_carry_short_captions_and_the_full_one_in_the_notes(sales, science):
    for tables, brief in ((sales, SALES_BRIEF), (science, SCIENCE_BRIEF)):
        for s in _data(build_data_story(Brief(text=brief), tables).outline):
            assert s.takeaway is None or len(s.takeaway) <= 160, s.takeaway
    o = build_data_story(Brief(text=Q1), sales).outline
    ch = _by_file(o, "Каналы продаж.json")
    if ch.takeaway and "Онлайн" not in ch.takeaway:
        assert "Онлайн — 9%" in ch.notes and "полностью" in ch.rationale


def test_a_rewording_that_lists_every_category_is_refused(sales):
    reg = _by_file(build_data_story(Brief(text=SALES_BRIEF), sales).outline, "Регионы.xlsx")
    listed = "Москва — 1 433 млн ₽, Санкт-Петербург — 612 млн ₽, Екатеринбург — 318 млн ₽"
    st = _told(sales, SALES_BRIEF, {"headlines": [{"id": reg.id, "headline": listed}]})
    assert _by_file(st.outline, "Регионы.xlsx").headline != listed
    assert any(r["to"] == listed and "перечень" in (r["why"] or "") for r in st.rephrased)


def test_a_list_after_an_intro_keeps_its_first_two_with_one_period():
    from verstka.data.story import short_caption

    got = short_caption("Больше всего — Прикладная информатика. Всего 2 425 чел.: платное — 1 290 чел., бюджет — 840 чел., целевое — 295 чел.")
    assert got == "Больше всего — Прикладная информатика. Всего 2 425 чел.: платное — 1 290 чел., бюджет — 840 чел."
