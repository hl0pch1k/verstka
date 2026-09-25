"""A short labelled brief without a model (the UI's own example): the rules make an honest but complete deck — one
slide per labelled line (a big number, a KPI row, the ask), never one two-column slide merging them, never a figure or
a change the brief does not state — while a longer brief is read exactly as it always was.

A change «A → B» is shown only when one clause of the brief tells it («с 47 до 29 минут», «47 → 29 минут», «было 47
минут, стало 29»); two figures of different sentences are never joined, however alike they look."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from verstka.planning import heuristics as H
from verstka.planning.brief import load_brief, parse_brief_text
from verstka.planning.facts import basic_facts
from verstka.planning.outline import _keep_priority, basic_outline, plan_outline, target_slide_count
from verstka.planning.strategies import get_strategy
from verstka.rendering.compose import distinct_label
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent

UI_EXAMPLE = (
    "Например: итоги пилота «Умные сводки» за квартал.\n\n"
    "Проблема: сотрудники тратят 47 минут в день на чтение чатов.\n"
    "Результаты: время сократилось до 29 минут, NPS 64.\n"
    "Просим: бюджет 14,5 млн ₽ на масштабирование."
)
TITLE = "Итоги пилота «Умные сводки» за квартал"
BRIEFS = Path(__file__).resolve().parents[2] / "examples" / "briefs"
STRATEGIES = ["structured", "visual", "compact"]

EXPECTED_KINDS = {
    "structured": [K.title, K.agenda, K.big_number, K.stat_row, K.bullets, K.thanks],
    "visual": [K.title, K.big_number, K.big_number, K.big_number, K.bullets, K.thanks],
    "compact": [K.title, K.big_number, K.stat_row, K.bullets, K.thanks],
}

# the review's adversarial briefs: figures of the same unit that measure different things
REVENUE_COSTS = "Итоги года по облачной платформе.\n\nВыручка: 120 млн ₽ за год.\nЗатраты: снизились до 80 млн ₽.\nПросим: утвердить план на следующий год."
MEETING_RESPONSE = "Автоматизация поддержки: итоги квартала.\n\nПроблема: ежедневная планёрка длится 60 минут.\nРезультаты: время ответа клиенту сократилось до 5 минут, NPS 70.\nПросим: бюджет 3 млн ₽ на развитие."
REPORT_DAYS = "Цифровой документооборот.\n\nПроблема: отчёт готовится 5 дней.\nРезультаты: срок согласования сократился до 2 дней.\nПросим: одобрить запуск во всех филиалах."
SHARED_WORDS = "Итоги работы службы поддержки за квартал.\n\nПроблема: 38% обращений клиентов закрываются дольше суток.\nРезультаты: доля повторных обращений клиентов снизилась до 12%.\nПросим: расширить команду на 3 человека."
OTHER_SHARE = "Итоги квартала.\n\nПроблема: 38% сообщений не читают.\nРезультаты: конверсия выросла до 52%.\nПросим: бюджет 2 млн ₽."
MONTHS_SOLUTION = "Пилот чат-бота поддержки.\n\nКонтекст: пилот шёл 3 месяца в четырёх командах поддержки клиентов.\nРезультаты: NPS вырос до 64, время сократилось до 29 минут.\nРешение: бот собирает ответ за 30 секунд."
KEY_VALUE = "План проекта внедрения.\n\nБюджет: 25 млн ₽.\nСрок: 3 месяца.\nКоманда: выросла до 40 человек."
TIME_OF_DAY = "Созвон в 10:30 занимает 45 минут. Участников 12 человек. Просим перенести созвон на пятницу."
TEAM_GREW = "Итоги найма за год.\n\nРезультаты: выручка выросла до 150 млн ₽, команда выросла до 40 человек.\nПросим: утвердить план найма."
ADVERSARIAL = [REVENUE_COSTS, MEETING_RESPONSE, REPORT_DAYS, SHARED_WORDS, OTHER_SHARE, MONTHS_SOLUTION, KEY_VALUE, TIME_OF_DAY, TEAM_GREW]

# every pair of sentences the reviews found joined into a made-up change «A → B» (and the ones an earlier round joined
# on purpose): an earlier figure and a later «до N» of the same unit, in different sentences — never one change
CROSS_SENTENCE = [
    ("Сотрудники тратят 47 минут в день на чтение чатов.", "Время сократилось до 29 минут, NPS 64."),  # the UI example
    ("Сотрудники тратят 47 минут в день на чтение чатов.", "Время на чтение чатов сократилось до 29 минут."),
    ("Доля непрочитанных сообщений — 38%.", "Доля непрочитанных снизилась до 14%."),
    ("Затраты на инфраструктуру составили 120 млн ₽ за год.", "Затраты на инфраструктуру снизились до 80 млн ₽."),
    ("Выручка: 120 млн ₽ за год.", "Затраты: снизились до 80 млн ₽."),
    ("Выручка компании составила 120 млн ₽.", "Затраты снизились до 80 млн ₽."),
    ("Ежедневная планёрка длится 60 минут.", "Время ответа клиенту сократилось до 5 минут."),
    ("Ежедневная планёрка длится 60 минут.", "Время сократилось до 30 минут."),
    ("Отчёт готовится 5 дней.", "Срок согласования сократился до 2 дней."),
    ("38% обращений клиентов закрываются дольше суток.", "Доля повторных обращений клиентов снизилась до 12%."),
    ("38% сообщений не читают.", "Конверсия выросла до 52%."),
    ("Выручка 120 млн ₽.", "Снизилась до 80 млн ₽."),
    ("Сотрудники тратят 47 минут в день.", "Время выросло до 29 минут."),
    ("Срок согласования сократился до 40 дней.", "Срок согласования сократился до 29 дней."),
    ("Команда тратит 60 минут на планёрку.", "Команда снизила время ответа клиенту до 5 минут."),
    ("Компания тратит 50 млн ₽ в год на хранение.", "Компания снизила расходы на логистику до 30 млн ₽."),
    ("Мы тратим 20 часов в неделю на согласования.", "Мы сократили время на отчёты до 5 часов."),
    ("Отдел продаж тратит 5 дней на отчёт.", "Отдел продаж сократил срок согласования до 2 дней."),
    ("Продажи за год составили 120 млн ₽.", "Продукт снизил стоимость владения до 80 млн ₽."),
    ("Отток клиентов вырос на 5% за год.", "Отток клиентов снизился до 3%."),  # a delta is not a starting level
    ("Затраты на поддержку сократились на 20 млн ₽.", "Затраты на поддержку снизились до 15 млн ₽."),
    ("Время ответа увеличилось на 40 минут.", "Время ответа сократилось до 25 минут."),
    ("Цель: сократить время ответа до 10 минут.", "Время ответа сократилось до 5 минут."),  # a goal is not a starting level
    ("Выручка конкурентов — 120 млн ₽.", "Выручка снизилась до 80 млн ₽."),  # a qualified earlier measure
    ("Время ответа конкурентов — 30 минут.", "Время ответа сократилось до 5 минут."),
    ("Время ответа в Москве — 30 минут.", "Время ответа сократилось до 5 минут."),
    ("Средний чек в регионах — 3000 ₽.", "Средний чек снизился до 2500 ₽."),
    ("Затраты: 120 млн ₽ за год.", "Затраты: снизились до 80 млн ₽."),  # one label over both figures
]


def _lower_first(t: str) -> str:
    return t[:1].lower() + t[1:]


def _cross_briefs(a: str, b: str) -> list[str]:
    """One pair of sentences typed three ways: as labelled lines, as one plain paragraph, as a markdown brief."""
    return [
        f"Итоги квартала.\n\nПроблема: {_lower_first(a)}\nРезультаты: {_lower_first(b)}\nПросим: бюджет 3 млн ₽ на развитие.",
        f"Итоги квартала. {a} {b} Просим одобрить бюджет 3 млн ₽ на развитие.",
        f"# Итоги квартала\n\n## Проблема\n{a}\n\n## Результаты\n{b}\n\n## Что просим\nПросим одобрить бюджет 3 млн ₽ на развитие.",
    ]


# a two-line paragraph whose second line asks: the ask keeps a slide of its own, its figure is never a tile
TWO_LINE = "Итоги пилота.\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\n"
TWO_LINE_ASKS = [
    ("Предлагаем: бюджет 14,5 млн ₽ на масштабирование.", "Предлагаем"),
    ("Что нужно: бюджет 14,5 млн ₽ на масштабирование.", "Что нужно"),
    ("Запрос: бюджет 14,5 млн ₽ на масштабирование.", "Запрос"),
    ("Просим: бюджет 14,5 млн ₽ на масштабирование.", "Просим"),
    ("Решение: выделить 14,5 млн ₽ на масштабирование.", "Решение"),
    ("Решение: бюджет 14,5 млн ₽ на масштабирование.", "Решение"),
    ("Решение: увеличить бюджет до 14,5 млн ₽ на масштабирование.", "Решение"),  # a level asked for, not one reached
    ("Нужен бюджет 14,5 млн ₽ на масштабирование.", "Что просим"),  # a need said with money
]

# the create screen's sample (web/src/components/NewGenerationFormParts.tsx, SAMPLE_BRIEF) — a long plain brief
WEB_SAMPLE = """Запуск функции «Умные сводки» в корпоративном мессенджере VK WorkSpace: итоги пилота за Q2 2026 и план масштабирования.

Проблема: сотрудники тратят в среднем 47 минут в день на чтение рабочих чатов, а 38% сообщений в командных каналах остаются непрочитанными. По опросу 1 240 пользователей 71% хотят получать краткое содержание пропущенных обсуждений.

Решение: «Умные сводки» — автоматическое резюме непрочитанных веток с выделением решений, задач и дедлайнов. Модель работает в контуре компании, данные не покидают периметр.

Результаты пилота (12 команд, 860 пользователей, 8 недель):

| Метрика | До пилота | После пилота | Изменение |
|---|---|---|---|
| Время на чтение чатов, мин/день | 47 | 29 | −38% |
| Доля непрочитанных сообщений | 38% | 14% | −24 п.п. |
| Пропущенные дедлайны, шт/мес | 21 | 8 | −62% |
| NPS функции | — | 64 | — |

Экономика: экономия 18 минут в день на сотрудника — это около 78 часов в год; при масштабировании на 25 000 пользователей эффект оценивается в 1,9 млн человеко-часов. Стоимость инференса — 0,4 ₽ на сводку, в среднем 6 сводок на пользователя в день.

Дорожная карта: Q3 — раскатка на 30% компании и поддержка тредов; Q4 — сводки по звонкам и интеграция с календарём; Q1 2027 — сводки по проектам в задачах.

Риски: качество резюме на смешанных языках (русский/английский), нагрузка на GPU-кластер в пиковые часы, необходимость обучения пользователей. Команда: продакт, 4 инженера, ML-инженер, дизайнер, аналитик.

Просим одобрить бюджет 14,5 млн ₽ на второе полугодие и выделить 2 дополнительные GPU-ноды."""

# a long plain brief with a key/value paragraph (the review's shape): its labelled lines stay one card slide
LONG_PLAIN = (
    "Переход отдела продаж на новую CRM: план проекта на второе полугодие.\n\n"
    "Контекст: сейчас менеджеры ведут клиентов в трёх разных таблицах, и 30% сделок теряются между этапами. Руководители тратят 6 часов в неделю на сведение отчётов вручную.\n\n"
    "Цель: единая CRM для 120 менеджеров, автоматические отчёты и прозрачная воронка продаж.\n\n"
    "Параметры: срок 6 месяцев.\nБюджет: 25 млн ₽.\nКоманда: 8 человек.\nРиски: интеграция с 1С.\n\n"
    "Ожидаемый эффект: доля потерянных сделок снизится вдвое, отчёты будут собираться автоматически каждое утро.\n\n"
    "Просим утвердить бюджет и состав команды проекта."
)


def _brief(text: str = UI_EXAMPLE, audience: str = "Генеральный директор", slides: int = 12):
    """What the API makes of the create screen: the text as typed, the audience and the slide count fields."""
    b = parse_brief_text(text)
    b.audience = audience
    b.slide_count = slides
    return b


def _outline(strategy: str, text: str = UI_EXAMPLE, audience: str = "Генеральный директор", slides: int = 12) -> DeckOutline:
    b = _brief(text, audience, slides)
    s = get_strategy(strategy)
    return basic_outline(b.model_copy(deep=True), basic_facts(b.text), s, target_slide_count(b, s))


def _texts(s: OutlineSlide) -> list[str]:
    c = s.content
    out = [s.headline, s.subtitle or ""] + c.bullets + c.paragraphs
    out += [f"{n.value} {n.label}" for n in c.numbers]
    out += [f"{i.title} {i.text} {i.number or ''} {' '.join(i.bullets)}" for i in c.items + c.columns]
    return [t for t in out if t]


def _shown(s: OutlineSlide) -> str:
    return " ".join(_texts(s))


def _has(s: OutlineSlide, figure: str) -> bool:
    return figure in _shown(s).replace(" ", " ")


def _by_section(o: DeckOutline, section: str) -> list[OutlineSlide]:
    return [s for s in o.slides if s.section == section]


def _arrows(o: DeckOutline) -> list[str]:
    return [t for s in o.slides for t in _texts(s) + [s.notes] if "→" in t]


_WORD_RE = re.compile(r"[a-zа-яё]+", re.I)
_FIGURE_RE = re.compile(r"\d+(?:[.,]\d+)?")
_FRAME_WORDS = {"о", "чём", "поговорим", "спасибо", "за", "внимание", "что", "просим"}  # the rules' own headings
_UNIT_WORDS = {"мес", "дн", "ч", "мин", "нед", "г", "с"}  # a figure's unit written short («3 месяца» → «3 мес»)


def _assert_nothing_invented(o: DeckOutline, text: str, changes: set[tuple[str, str]] = frozenset()) -> None:
    """Every figure is one the brief writes (as a whole figure, not digits put together), every change «A → B» is one
    the brief tells (`changes`), every word on a slide is a word of the brief."""
    words = {w.lower() for w in _WORD_RE.findall(f"{text} {o.audience or ''}")} | _FRAME_WORDS | _UNIT_WORDS  # the audience field too
    figures = set(_FIGURE_RE.findall(text))
    for s in o.slides:
        for n in s.content.numbers:
            if "→" in n.value:
                a, b = (x.strip() for x in n.value.split("→"))
                assert (a, b) in changes, f"a change the brief does not tell: {n.value}"
                assert H.figure_span(a, text) and H.figure_span(b, text), n.value
            else:
                assert H.figure_span(n.value.lstrip("+−"), text) is not None, f"not in the brief: {n.value}"
            assert {w.lower() for w in _WORD_RE.findall(n.label)} <= words, n.label
        for t in _texts(s) + [s.notes]:
            assert set(_FIGURE_RE.findall(t)) <= figures, (t, set(_FIGURE_RE.findall(t)) - figures)
            assert {w.lower() for w in _WORD_RE.findall(t)} <= words, (t, {w.lower() for w in _WORD_RE.findall(t)} - words)


# ---------------------------------------------------------------------------------------------- the UI example


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_labelled_line_is_a_slide_of_its_own(strategy):
    o = _outline(strategy)
    kinds = [s.kind for s in o.slides]
    assert kinds == EXPECTED_KINDS[strategy], [(s.kind.value, s.headline) for s in o.slides]
    assert K.two_column not in kinds  # «Результаты» and «Просим» are never the columns of one slide
    assert o.planned_by == "rules"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_title_is_the_example_line_without_its_marker(strategy):
    o = _outline(strategy)
    assert o.title == TITLE and o.slides[0].headline == TITLE
    assert o.slides[0].subtitle == "Генеральный директор"
    assert not any("Например" in t for s in o.slides for t in _texts(s))
    agenda = [s for s in o.slides if s.kind == K.agenda]
    if agenda:
        assert [i.title for i in agenda[0].content.items] == ["Проблема", "Результаты", "Просим"]


@pytest.mark.parametrize("strategy", ["structured", "compact"])
def test_figures_sit_on_their_own_slides(strategy):
    o = _outline(strategy)
    [problem] = _by_section(o, "Проблема")
    assert problem.kind == K.big_number and [n.value for n in problem.content.numbers] == ["47 минут"]
    assert problem.headline == "Сотрудники тратят 47 минут в день на чтение чатов"
    assert [n.label for n in problem.content.numbers] == ["в день на чтение чатов"]  # what the slide shows under it
    [results] = _by_section(o, "Результаты")
    assert results.kind == K.stat_row and results.headline == "Время сократилось до 29 минут"
    # «время сократилось до 29 минут» is said in another sentence than «тратят 47 минут»: 29 минут, not «47 → 29»
    assert [(n.value, n.label) for n in results.content.numbers] == [("29 минут", "время сократилось"), ("64", "NPS")]
    [ask] = _by_section(o, "Просим")
    assert ask.kind == K.bullets and ask.headline == "Просим"
    assert ask.content.paragraphs == ["Бюджет 14,5 млн ₽ на масштабирование"] and not ask.content.bullets and not ask.content.numbers
    # each figure is said where it belongs and nowhere else
    content = o.slides[1:-1]
    assert [s.section for s in content if _has(s, "47")] == ["Проблема"]
    assert [s.section for s in content if _has(s, "29")] == ["Результаты"]
    assert [s.section for s in content if _has(s, "64")] == ["Результаты"]
    assert [s.section for s in content if _has(s, "14,5")] == ["Просим"]


def test_visual_opens_with_the_key_result_and_says_every_figure_once():
    o = _outline("visual")
    hero = o.slides[1]
    assert hero.kind == K.big_number and [n.value for n in hero.content.numbers] == ["29 минут"]
    assert hero.headline == "Время сократилось до 29 минут"
    [problem] = _by_section(o, "Проблема")
    assert [n.value for n in problem.content.numbers] == ["47 минут"]
    [nps] = _by_section(o, "Результаты")
    assert nps.kind == K.big_number and [(n.value, n.label) for n in nps.content.numbers] == [("64", "NPS")]
    [ask] = _by_section(o, "Просим")
    assert ask.content.paragraphs == ["Бюджет 14,5 млн ₽ на масштабирование"]
    # figures first, then the ask; no figure on two slides
    assert [s.kind for s in o.slides[1:4]] == [K.big_number] * 3 and o.slides[4] is ask
    numbers = [n.value for s in o.slides for n in s.content.numbers]
    assert numbers == ["29 минут", "47 минут", "64"]
    assert not _arrows(o)
    for figure in ("47", "29", "64", "14,5"):
        assert sum(_has(s, figure) for s in o.slides) == 1, figure


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_no_invented_numbers(strategy):
    o = _outline(strategy)
    _assert_nothing_invented(o, UI_EXAMPLE)  # no change «47 → 29» either: the brief says the two in two sentences
    assert not _arrows(o)
    shown = {x for s in o.slides for t in _texts(s) for x in _FIGURE_RE.findall(t)}
    assert shown == {"47", "29", "64", "14,5"}  # …and none of the brief's figures is lost


def test_the_value_check_catches_a_change_built_from_real_digits():
    # the check is on values, not on digits: «120 → 80 млн ₽» built from a brief's 120 and 80 is an invented fact
    o = _outline("structured", REVENUE_COSTS)
    o.slides[2].content.numbers[0].value = "120 → 80 млн ₽"
    with pytest.raises(AssertionError, match="does not tell"):
        _assert_nothing_invented(o, REVENUE_COSTS)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_headings_are_unique_capitalised_and_never_x_and_y_and_z(strategy):
    for text in [UI_EXAMPLE, UI_EXAMPLE.replace("время сократилось до 29 минут, NPS 64", "NPS 64, время сократилось до 29 минут"), MONTHS_SOLUTION, TEAM_GREW]:
        o = _outline(strategy, text)
        for s in o.slides:
            assert len(re.findall(r"\sи\s", f" {s.headline} ")) < 2, s.headline  # never «X и Y и Z»
            assert not s.headline[:1].islower(), s.headline  # «время сократилось …» is a heading only with a capital
        assert len({s.headline for s in o.slides}) == len(o.slides)  # headings are unique


def test_plan_outline_without_a_model_gives_the_same_deck():
    b = _brief()
    s = get_strategy("structured")
    outline, warnings = plan_outline(b, None, s, basic_facts(b.text), None, None)  # type: ignore[arg-type]
    assert any("no LLM provider" in w for w in warnings)
    assert [x.kind for x in outline.slides] == EXPECTED_KINDS["structured"]


# ---------------------------------------------------------------------------------------------- a fixed small deck


@pytest.mark.parametrize("slides", [4, 5])
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_ask_survives_a_small_deck(strategy, slides):
    """Four or five slides for three sections: the ask («14,5 млн ₽») gives way last, the two-figure row of results
    after the one-figure problem — and no visual hero slide is added when there is no room for it."""
    o = _outline(strategy, slides=slides)
    assert len(o.slides) == slides, [(s.kind.value, s.headline) for s in o.slides]
    [ask] = _by_section(o, "Просим")
    assert ask.content.paragraphs == ["Бюджет 14,5 млн ₽ на масштабирование"]
    shown = {x for s in o.slides for t in _texts(s) for x in _FIGURE_RE.findall(t)}
    # five slides hold every figure; four hold the results and the ask, the problem slide gives way
    assert shown == ({"47", "29", "64", "14,5"} if slides == 5 else {"29", "64", "14,5"})
    _assert_nothing_invented(o, UI_EXAMPLE)
    numbers = [n.value for s in o.slides for n in s.content.numbers]
    assert len(numbers) == len(set(numbers))  # no figure said twice on tiles


@pytest.mark.parametrize("slides", [4, 5, 12])
@pytest.mark.parametrize("text", ADVERSARIAL, ids=["revenue-costs", "meeting-response", "days", "shared-words", "other-share", "months-solution", "key-value", "time-of-day", "team-grew"])
def test_adversarial_briefs_invent_nothing_and_keep_their_ask(text, slides):
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=slides)
        assert not _arrows(o), (strategy, _arrows(o))  # none of them tells a change from one figure to another
        _assert_nothing_invented(o, text)
        asks = [s for s in o.slides if s.kind == K.bullets and s.section in ("Просим", "Что просим")]
        if re.search(r"(?m)^Просим|\. Просим", text):
            assert asks, (strategy, slides, [(s.kind.value, s.headline) for s in o.slides])


@pytest.mark.parametrize("slides", [4, 5, 12])
@pytest.mark.parametrize(
    "text, ask",
    [
        ("Тема: план на год.\n\nРешение: выручка составила 80 млн ₽.\nПросим: бюджет 14 млн ₽ на масштабирование.", "Бюджет 14 млн ₽ на масштабирование"),
        ("Итоги пилота за квартал.\n\nРешение: 38% сообщений не читают, доля непрочитанных снизилась до 14%.\nСрок: согласование идёт 60 дней.\n"
         "Выручка: экономия 120 часов в неделю, конверсия 7%.\nПредлагаем утвердить план.", "Предлагаем утвердить план"),
    ],
    ids=["ask-under-solution", "proposal-under-solution"],
)
def test_an_ask_inside_a_solution_section_keeps_a_slide_of_its_own(text, ask, slides):
    """«Решение» is not an ask section by its name: a «Просим …» said inside it is taken out and kept to the last."""
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=slides)
        asks = [s for s in o.slides if s.kind == K.bullets and ask in s.content.paragraphs]
        assert len(asks) == 1, (strategy, slides, [(s.kind.value, s.headline, s.content.paragraphs) for s in o.slides])
        assert len(o.slides) <= slides
        _assert_nothing_invented(o, text)


# ---------------------------------------------------------------------------------------------- the same brief typed differently


@pytest.mark.parametrize(
    "text",
    [
        UI_EXAMPLE.replace("\n\n", "\n"),  # no blank line under the title
        UI_EXAMPLE.replace("Например: итоги", "Итоги"),  # no marker
        UI_EXAMPLE.replace("\n\n", " ").replace("\n", " "),  # everything in one line
    ],
    ids=["one-paragraph", "no-marker", "one-line"],
)
def test_labelled_lines_are_sections_however_they_are_typed(text):
    o = _outline("structured", text)
    assert o.title == TITLE
    assert [s.kind for s in o.slides] == EXPECTED_KINDS["structured"], [(s.kind.value, s.headline) for s in o.slides]
    assert [n.value for s in _by_section(o, "Результаты") for n in s.content.numbers] == ["29 минут", "64"]


def test_without_a_title_line_the_problem_keeps_its_slide():
    text = UI_EXAMPLE.split("\n\n", 1)[1]
    o = _outline("structured", text)
    assert o.title == "Сотрудники тратят 47 минут в день на чтение чатов"
    [problem] = _by_section(o, "Проблема")
    assert problem.kind == K.big_number and [n.value for n in problem.content.numbers] == ["47 минут"]
    assert len(o.slides) >= 5


def test_the_parser_keeps_paragraphs_and_the_planner_cuts_a_short_one():
    # the parser reads a paragraph as one section (as it always did); only the title marker is taken off
    title, secs = H.parse_sections(UI_EXAMPLE)
    assert title == TITLE
    assert [(s.title, s.sentences) for s in secs] == [
        ("Проблема", ["Сотрудники тратят 47 минут в день на чтение чатов.", "Результаты: время сократилось до 29 минут, NPS 64.", "Просим: бюджет 14,5 млн ₽ на масштабирование."]),
    ]
    # …and the planner cuts the labelled lines of a short brief into sections of their own
    agenda = next(s for s in _outline("structured").slides if s.kind == K.agenda)
    assert [i.title for i in agenda.content.items] == ["Проблема", "Результаты", "Просим"]
    # a lead ending with a colon keeps its labelled lines as items, not sections
    _, secs = H.parse_sections("Итоги квартала.\n\nПреимущества:\nСкорость: в 3 раза быстрее.\nЦена: на 20% дешевле.\n\nПросим одобрить запуск.")
    assert [s.title for s in secs] == ["Преимущества", "Что просим"]
    assert secs[0].sentences[-2:] == ["Скорость: в 3 раза быстрее.", "Цена: на 20% дешевле."]


# ---------------------------------------------------------------------------------------------- a change only as the brief writes it


@pytest.mark.parametrize("a, b", CROSS_SENTENCE, ids=[f"pair-{i:02d}" for i in range(len(CROSS_SENTENCE))])
def test_no_change_is_ever_made_from_two_sentences(a, b):
    """An earlier figure and a later «до N» of the same unit stay two figures, each as it is written — whatever the
    wording (one subject, a spend verb, shared words, a delta, a goal, a qualified measure, one label), in every
    variant, at every size, however the brief is typed. A made-up change is worse than none."""
    for sentence in (a, b):
        assert not any("→" in k.value for k in H.kpis_of(sentence)), sentence
    for text in _cross_briefs(a, b):
        for slides in (4, 5, 12):
            for strategy in STRATEGIES:
                o = _outline(strategy, text, slides=slides)
                assert not _arrows(o), (text, strategy, slides, _arrows(o))
                _assert_nothing_invented(o, text)
                assert len(o.slides) <= slides


def test_no_change_is_made_from_three_sentences_either():
    text = "Итоги квартала.\n\nНа чаты уходит 47 минут в день.\nНа почту уходит 15 минут в день.\nВремя сократилось до 29 минут.\n\nПросим: бюджет 3 млн ₽."
    for strategy in STRATEGIES:
        o = _outline(strategy, text)
        assert not _arrows(o)
        _assert_nothing_invented(o, text)


@pytest.mark.parametrize(
    "sentence, value, label",
    [
        ("Итоги пилота за второй квартал: время на чтение чатов сократилось с 47 до 29 минут в день.", "47 → 29 минут", "время на чтение чатов"),
        ("Время на чтение чатов 47 → 29 минут.", "47 → 29 минут", "время на чтение чатов"),
        ("Доля непрочитанных 38% → 14%.", "38% → 14%", "доля непрочитанных"),
        ("Время на чтение чатов было 47 минут, стало 29 минут.", "47 → 29 минут", "время на чтение чатов"),
        ("Время было 47 минут, а стало 29.", "47 минут → 29", "время"),  # each end as it is written
        ("Срок был 2 часа, стал 30 минут.", "2 часа → 30 минут", "срок"),
        # the start may carry words of its own before «стало»: what it counts, per what — both figures stay
        ("Время на чтение чатов было 47 минут в день, стало 29 минут.", "47 → 29 минут", "время на чтение чатов"),
        ("Было 120 заявок в день, стало 300 заявок в день.", "120 → 300", "заявок в день"),
        ("Было 12 человек в команде, стало 40.", "12 → 40", "человек в команде"),
        ("Время подготовки отчёта было 6 часов в неделю, стало 40 минут.", "6 часов → 40 минут", "время подготовки отчёта"),
        # a change without its subject has no label: never the clause that says its figures again
        ("Сроки: было 5 дней, стало 2 дня.", "5 дней → 2 дня", ""),
    ],
    ids=["from-to", "arrow", "arrow-share", "was-now", "was-now-one-unit", "was-now-two-units", "was-per-day", "was-counted-noun", "was-people", "was-two-units-per-week", "was-no-subject"],
)
def test_a_change_written_in_one_clause_is_one_figure(sentence, value, label):
    [k] = H.kpis_of(sentence)
    assert (k.value, k.label) == (value, label)


def test_was_and_now_that_do_not_read_as_one_change_keep_both_figures():
    """«было …» and «стало …» are joined into one clause only when they read as one change; otherwise each figure is
    kept as it is written (the join used to lose the second one)."""
    ks = H.kpis_of("Было 47 минут на чаты и 20 минут на почту, стало 29 минут.")
    assert not any("→" in k.value for k in ks) and "29 минут" in [k.value for k in ks]
    # a long brief shows both changes it writes, each once, with nothing made up
    text = LONG_PLAIN.replace(
        "Руководители тратят 6 часов в неделю на сведение отчётов вручную.",
        "Время подготовки отчёта было 6 часов в неделю, стало 40 минут. Было 120 заявок в день, стало 300 заявок в день.",
    )
    for strategy in STRATEGIES:
        o = _outline(strategy, text, audience="Руководитель отдела продаж")
        numbers = [(n.value, n.label) for s in o.slides for n in s.content.numbers]
        # the subject as the brief writes it: it never writes «время» in lowercase, so it may be a name (kpi_of)
        assert ("6 часов → 40 минут", "Время подготовки отчёта") in numbers and ("120 → 300", "заявок в день") in numbers, (strategy, numbers)
        _assert_nothing_invented(o, text, {("6 часов", "40 минут"), ("120", "300")})


@pytest.mark.parametrize(
    "line",
    [
        "время на чтение чатов сократилось с 47 до 29 минут, NPS 64",
        "время на чтение чатов 47 → 29 минут, NPS 64",
        "время на чтение чатов было 47 минут, стало 29 минут, NPS 64",
    ],
    ids=["from-to", "arrow", "was-now"],
)
def test_a_change_the_brief_writes_is_shown_as_one_figure(line):
    text = f"Итоги пилота.\n\nРезультаты: {line}.\nПросим: бюджет 14,5 млн ₽."
    for strategy in STRATEGIES:
        o = _outline(strategy, text)
        assert [n.value for s in o.slides for n in s.content.numbers] == ["47 → 29 минут", "64"], strategy
        _assert_nothing_invented(o, text, {("47", "29 минут")})
        assert len(_by_section(o, "Просим")) == 1


def test_a_figure_is_not_said_again_next_to_the_change_it_starts():
    text = "Пилот сводок.\n\nПроблема: сотрудники тратили 47 минут в день. Время сократилось с 47 до 29 минут.\nПросим: бюджет 3 млн ₽."
    for strategy in STRATEGIES:
        o = _outline(strategy, text)
        numbers = [n.value for s in o.slides for n in s.content.numbers]
        assert numbers == ["47 → 29 минут"], (strategy, numbers)  # not «47 минут» beside «47 → 29 минут»


def test_a_level_reached_has_no_sign():
    assert [k.value for k in H.kpis_of("Текучесть снизилась до 8%.")] == ["8%"]  # down TO 8%, not by 8%
    assert [k.value for k in H.kpis_of("Конверсия выросла до 52%.")] == ["52%"]
    assert [k.value for k in H.kpis_of("Доля завершённых в срок задач выросла на 34%.")] == ["+34%"]
    assert [k.value for k in H.kpis_of("Отток снизился на 5%.")] == ["−5%"]


# ---------------------------------------------------------------------------------------------- short briefs cut consistently


@pytest.mark.parametrize("line, label", TWO_LINE_ASKS, ids=["predlagaem", "chto-nuzhno", "zapros", "prosim", "reshenie-vydelit", "reshenie-budget", "reshenie-uvelichit-do", "nuzhen-budget"])
def test_an_ask_on_the_second_line_keeps_a_slide_of_its_own(line, label):
    """«Проблема: … / Предлагаем: бюджет 14,5 млн ₽ …»: the ask is said as a statement under its own label at every size
    — its figure is never turned into a tile next to the problem's."""
    text = TWO_LINE + line
    for slides in (4, 5, 12):
        for strategy in STRATEGIES:
            o = _outline(strategy, text, slides=slides)
            where = (strategy, slides, [(s.kind.value, s.headline) for s in o.slides])
            [ask] = [s for s in o.slides if s.kind == K.bullets and s.content.paragraphs]
            assert ask.headline == label and "14,5 млн ₽" in ask.content.paragraphs[0], where
            assert not any("14,5" in n.value for s in o.slides for n in s.content.numbers), where
            [problem] = _by_section(o, "Проблема")
            assert [n.value for n in problem.content.numbers] == ["47 минут"], where
            _assert_nothing_invented(o, text)


@pytest.mark.parametrize(
    "text, problem",
    [
        ("Итоги пилота.\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\nРезультаты: время сократилось до 29 минут, NPS 64.", "47 минут"),
        ("Цифровой документооборот.\n\nПроблема: затраты на поддержку составили 90 млн ₽ за год.\nРезультаты: время сократилось до 15 минут, NPS 64.\n"
         "Просим одобрить запуск во всех филиалах.", "90 млн ₽"),
    ],
    ids=["no-ask", "unlabelled-ask"],
)
def test_a_two_line_paragraph_is_cut_like_a_three_line_one(text, problem):
    """The paragraph's own «Проблема:» counts as a labelled line: «Проблема: … / Результаты: …» is two sections, so the
    results never sit under the problem's heading."""
    for strategy in STRATEGIES:
        o = _outline(strategy, text)
        where = (strategy, [(s.kind.value, s.headline, s.section) for s in o.slides])
        [p] = _by_section(o, "Проблема")
        assert p.kind == K.big_number and [n.value for n in p.content.numbers] == [problem], where
        assert any(n.value == "64" for s in _by_section(o, "Результаты") for n in s.content.numbers), where
        _assert_nothing_invented(o, text)


def test_a_lead_with_a_colon_keeps_its_list_together():
    text = "Итоги квартала.\n\nПреимущества:\nСкорость: в 3 раза быстрее.\nЦена: на 20% дешевле.\n\nПросим одобрить запуск."
    o = _outline("structured", text)
    [adv] = _by_section(o, "Преимущества")
    assert adv.kind == K.two_column and [c.title for c in adv.content.columns] == ["Скорость", "Цена"]


# ---------------------------------------------------------------------------------------------- what gives way in a small deck


def _slide(i: int, kind, head: str, *numbers: tuple[str, str]) -> OutlineSlide:
    return OutlineSlide(id=f"s{i}", kind=kind, headline=head, content=SlideContent(numbers=[NumberCallout(value=v, label=lab) for v, lab in numbers]))


def test_a_figure_slide_counts_as_repeated_only_by_its_values():
    keep = _keep_priority({"s9"})
    title, thanks = OutlineSlide(id="t", kind=K.title, headline="Итоги"), OutlineSlide(id="z", kind=K.thanks, headline="Спасибо")
    meeting = _slide(1, K.big_number, "Планёрка длится 30 минут", ("30 минут", "планёрка длится"))
    teams = _slide(2, K.big_number, "В пилоте 30 команд", ("30", "команд"))
    deck = [title, meeting, teams, thanks]
    assert keep(deck, meeting) is None and keep(deck, teams) is None  # «30 минут» and «30 команд» are two facts
    change = _slide(3, K.big_number, "Время сократилось", ("47 → 29 минут", "время на чтение чатов"))
    start = _slide(4, K.big_number, "Сотрудники тратят 47 минут в день", ("47 минут", "в день"))
    deck = [title, change, start, thanks]
    assert keep(deck, start) == 2.5 and keep(deck, change) is None  # the start of a change shown on another slide
    ask = OutlineSlide(id="s9", kind=K.bullets, headline="Просим", content=SlideContent(paragraphs=["Бюджет 3 млн ₽"]))
    assert keep([title, ask, thanks], ask) == 6.5  # the ask gives way last


# ---------------------------------------------------------------------------------------------- figures found as whole words


def test_a_figure_is_found_as_whole_words():
    text = "Пилот шёл 3 месяца в четырёх командах поддержки клиентов"
    s, e = H.figure_span("3 мес", text)
    assert text[s:e] == "3 месяца"  # the plan's short unit covers the word written in full, never half of it
    assert H.figure_span("3 мес", "Проект длится 13 месяцев") is None
    assert H.figure_span("5", "Ответ за 15 минут") is None and H.figure_span("5", "Стоит 0,5 ₽") is None
    s, e = H.figure_span("8–25 с", "Три варианта собираются за 8–25 секунд")
    assert e == len("Три варианта собираются за 8–25 секунд")


def test_planner_and_composer_label_a_figure_the_same_way():
    head = "Пилот шёл 3 месяца в четырёх командах поддержки клиентов"
    assert H.label_beside("3 мес", "пилот шёл в четырёх командах поддержки клиентов", head) == "в четырёх командах поддержки клиентов"
    cases = [
        ("3 мес", "пилот шёл в четырёх командах поддержки клиентов", head),
        ("6,5", "оператор тратит в среднем 6,5 минуты", "Оператор тратит в среднем 6,5 минуты на одно обращение"),
        ("64", "NPS", "NPS вырос до 64"),  # a short name stays as it is
        ("12", "участников 12 человек", "Участников 12 человек"),  # a bare number takes the word it counts
        ("40", "команда выросла до 40 человек", "Команда выросла до 40 человек"),
        ("5 минут", "время ответа клиенту сократилось", "Время ответа клиенту сократилось до 5 минут"),
        # a clause start of six words or fewer is kept whole, a longer one gives its last five words
        ("30 минут", "отдел продаж сократил время на отчёты", "Отдел продаж сократил время на отчёты до 30 минут"),
        ("30 минут", "весь отдел продаж сократил время на отчёты", "Весь отдел продаж сократил время на отчёты до 30 минут"),
    ]
    got = [distinct_label(*c) for c in cases]
    assert got == [H.label_beside(*c) for c in cases]  # one rule for the plan and the slide
    assert got[2:] == ["NPS", "человек", "человек", "время ответа клиенту сократилось", "отдел продаж сократил время на отчёты", "продаж сократил время на отчёты"]
    for strategy in STRATEGIES:
        o = _outline(strategy, MONTHS_SOLUTION)
        labels = [n.label for s in o.slides for n in s.content.numbers]
        assert not any(lab.startswith(("яца", "ца ")) for lab in labels), labels
        assert "в четырёх командах поддержки клиентов" in labels


# ---------------------------------------------------------------------------------------------- small readings


def test_a_bare_figure_is_named_by_its_section():
    # «Бюджет: 25 млн ₽»: the heading names the figure, the tile does not say «Бюджет» again
    o = _outline("structured", KEY_VALUE)
    [budget] = _by_section(o, "Бюджет")
    assert (budget.headline, [(n.value, n.label) for n in budget.content.numbers], budget.notes) == ("Бюджет", [("25 млн ₽", "")], "")
    [term] = _by_section(o, "Срок")
    assert (term.headline, [(n.value, n.label) for n in term.content.numbers], term.notes) == ("Срок", [("3 мес", "")], "")
    [team] = _by_section(o, "Команда")  # «выросла до 40 человек»: its subject is the label
    assert (team.headline, [(n.value, n.label) for n in team.content.numbers]) == ("Команда", [("40", "человек")])
    o = _outline("structured", REVENUE_COSTS)
    assert [(s.headline, [n.value for n in s.content.numbers]) for s in o.slides if s.content.numbers] == [("Выручка", ["120 млн ₽"]), ("Затраты", ["80 млн ₽"])]


def test_a_time_of_day_is_not_a_label():
    assert H.label_split("Созвон в 10:30 занимает 45 минут") is None
    # a label that ends with a number is still a label: only a colon with digits on both sides is part of a figure
    items, _ = H.labelled_items(["Вариант 1: базовый тариф.", "Вариант 2: расширенный тариф."])
    assert [i.title for i in items] == ["Вариант 1", "Вариант 2"]
    assert H.labelled_items(["Созвон в 10:30 занимает 45 минут.", "Обед в 13:00 длится 60 минут."]) == ([], ["Созвон в 10:30 занимает 45 минут.", "Обед в 13:00 длится 60 минут."])
    for strategy in STRATEGIES:
        o = _outline(strategy, TIME_OF_DAY)
        assert o.title == "Созвон в 10:30 занимает 45 минут"
        heads = [s.headline for s in o.slides] + [i.title for s in o.slides if s.kind == K.agenda for i in s.content.items]
        assert not any(h in ("Созвон в 10", "30 занимает 45 минут") for h in heads), heads


def test_a_solution_is_an_ask_only_when_it_asks():
    o = _outline("structured", MONTHS_SOLUTION)
    [solution] = _by_section(o, "Решение")
    assert solution.kind == K.big_number and [(n.value, n.label) for n in solution.content.numbers] == [("30", "секунд")]
    o = _outline("structured", MONTHS_SOLUTION.replace("бот собирает ответ за 30 секунд", "выделить 2 GPU-ноды и бюджет 3 млн ₽"))
    [solution] = _by_section(o, "Решение")
    assert solution.kind == K.bullets and solution.content.paragraphs == ["Выделить 2 GPU-ноды и бюджет 3 млн ₽"]
    # money alone does not ask: «бот экономит 2 млн ₽ в год» is a figure; money for a budget does
    o = _outline("structured", MONTHS_SOLUTION.replace("бот собирает ответ за 30 секунд", "бот экономит 2 млн ₽ в год"))
    [solution] = _by_section(o, "Решение")
    assert solution.kind == K.big_number and [n.value for n in solution.content.numbers] == ["2 млн ₽"]
    o = _outline("structured", MONTHS_SOLUTION.replace("бот собирает ответ за 30 секунд", "бюджет 3 млн ₽ на развитие бота"))
    [solution] = _by_section(o, "Решение")
    assert solution.kind == K.bullets and solution.content.paragraphs == ["Бюджет 3 млн ₽ на развитие бота"]


def test_a_figure_left_alone_is_headed_and_labelled_by_its_own_clause():
    o = _outline("visual", TEAM_GREW)
    hero = o.slides[1]
    assert (hero.headline, [n.value for n in hero.content.numbers]) == ("Выручка выросла до 150 млн ₽", ["150 млн ₽"])
    [team] = [s for s in o.slides if any(n.value == "40" for n in s.content.numbers)]
    assert team.kind == K.big_number and team.headline == "Команда выросла до 40 человек"
    assert [n.label for n in team.content.numbers] == ["человек"]  # not the heading said again
    [ask] = _by_section(o, "Просим")
    assert ask.content.paragraphs == ["Утвердить план найма"]


@pytest.mark.parametrize("strategy", ["structured", "compact"])
def test_each_tile_is_labelled_against_its_own_clause(strategy):
    o = _outline(strategy, TEAM_GREW)
    [row] = _by_section(o, "Результаты")
    assert [(n.value, n.label) for n in row.content.numbers] == [("150 млн ₽", "выручка выросла"), ("40", "человек")]  # not «команда выросла до 40 человек»


def test_every_label_in_the_plan_is_the_one_the_slide_shows():
    """A short brief's plan stores each label as the composer renders it under the slide's final heading, and no label
    repeats its own figure or the heading above it."""
    briefs = [UI_EXAMPLE, *ADVERSARIAL, *(_cross_briefs(a, b)[0] for a, b in CROSS_SENTENCE), *(TWO_LINE + line for line, _ in TWO_LINE_ASKS)]
    for text in briefs:
        for strategy in STRATEGIES:
            for slides in (4, 5, 12):
                o = _outline(strategy, text, slides=slides)
                for s in o.slides:
                    for n in s.content.numbers:
                        where = (text, strategy, slides, s.headline, n.value, n.label)
                        assert distinct_label(n.value, n.label, s.headline) == n.label, where
                        assert not n.label or H.figure_span(n.value, n.label) is None, where
                        assert n.label.strip().lower() != s.headline.strip().lower(), where


def test_no_currency_sign_opens_a_label():
    [k] = H.kpis_of("Бюджет составит 10–20 млн ₽ на команду.")
    assert k.value == "10–20 млн ₽" and "₽" not in k.label


# ---------------------------------------------------------------------------------------------- lines read in order


def _ask_slides(o: DeckOutline) -> list[OutlineSlide]:
    return [s for s in o.slides if s.kind == K.bullets and (s.content.paragraphs or s.content.bullets) and s.section and s.section in ("Просим", "Что просим", "Что нужно", "Предлагаем", "Запрос")]


def _ask_lines(s: OutlineSlide) -> list[str]:
    """The lines of an ask slide: its bullets, or the one statement two short lines are said as («A. B»)."""
    if s.content.bullets:
        return list(s.content.bullets)
    assert len(s.content.paragraphs) == 1, s.content.paragraphs
    return s.content.paragraphs[0].split(". ")


def _two_lines_are_one_statement(o: DeckOutline, ask: OutlineSlide) -> None:
    """Two short ask lines are one statement in structured and compact (two thin bullets fill a quarter of the slide);
    the visual variant keeps the lines, which its composer sets as cards."""
    if len(_ask_lines(ask)) == 2:
        assert (ask.content.bullets == []) == (o.strategy != "visual"), (o.strategy, ask.content)


@pytest.mark.parametrize("slides", [4, 5, 12])
def test_a_second_sentence_stays_with_its_own_label(slides):
    """An unlabelled sentence written on a label's own line belongs to that label: «Результаты: … . NPS вырос до 64.»
    keeps 64 on the results slide, «Просим: … . Срок запуска — 3 месяца.» keeps the term with the ask — never under
    «Проблема»."""
    two_results = UI_EXAMPLE.replace("время сократилось до 29 минут, NPS 64.", "время сократилось до 29 минут. NPS вырос до 64.")
    term_in_ask = UI_EXAMPLE.replace("на масштабирование.", "на масштабирование. Срок запуска — 3 месяца.")
    for strategy in STRATEGIES:
        o = _outline(strategy, two_results, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, s.section, [n.value for n in s.content.numbers]) for s in o.slides])
        for s in _by_section(o, "Проблема"):
            assert [n.value for n in s.content.numbers] == ["47 минут"], where
        assert {"29 минут", "64"} <= {n.value for s in o.slides for n in s.content.numbers}, where
        assert all(s.section in ("Результаты", None) for s in o.slides if any(n.value in ("29 минут", "64") for n in s.content.numbers)), where
        [ask] = _by_section(o, "Просим")
        assert ask.content.paragraphs == ["Бюджет 14,5 млн ₽ на масштабирование"], where
        _assert_nothing_invented(o, two_results)
        o = _outline(strategy, term_in_ask, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, s.section, [n.value for n in s.content.numbers]) for s in o.slides])
        assert not any("3 мес" in n.value or n.value == "3" for s in o.slides for n in s.content.numbers), where
        [ask] = _by_section(o, "Просим")
        assert ask.headline == "Просим" and _ask_lines(ask) == ["Бюджет 14,5 млн ₽ на масштабирование", "Срок запуска — 3 месяца"], where
        _two_lines_are_one_statement(o, ask)
        _assert_nothing_invented(o, term_in_ask)


LIST_ASKS = [
    UI_EXAMPLE.replace("Просим: бюджет 14,5 млн ₽ на масштабирование.", "Просим:\n- бюджет 14,5 млн ₽ на масштабирование;\n- 2 GPU-ноды;\n- 3 месяца на запуск."),
    UI_EXAMPLE.replace("Просим: бюджет 14,5 млн ₽ на масштабирование.", "Просим:\n- бюджет 14,5 млн ₽ на масштабирование;\n- 2 GPU-ноды."),
    UI_EXAMPLE.replace("Просим: бюджет 14,5 млн ₽ на масштабирование.", "Просим:\n- бюджет 14,5 млн ₽ на масштабирование;\n- 2 GPU-ноды;\n- 3 месяца на запуск;\n- доступ к данным CRM."),
    UI_EXAMPLE.replace("Просим: бюджет 14,5 млн ₽ на масштабирование.", "\nПросим:\n- бюджет 14,5 млн ₽ на масштабирование;\n- 2 GPU-ноды;\n- 3 месяца на запуск."),
    "# Итоги пилота\n\n## Проблема\nСотрудники тратят 47 минут в день на чтение чатов.\n\n## Результаты\nВремя сократилось до 29 минут, NPS 64.\n\n"
    "## Что просим\n- Бюджет 14,5 млн ₽ на масштабирование.\n- 2 GPU-ноды.\n- 3 месяца на запуск.",
    "Цифровой документооборот.\n\nРаскатка займёт 5 дней.\nЭкономия 15 минут в день на сотрудника.\nЧто нужно:\n- бюджет 14,5 млн ₽ на масштабирование;\n- 2 GPU-ноды.",
]


@pytest.mark.parametrize("slides", [4, 5, 12])
@pytest.mark.parametrize("text", LIST_ASKS, ids=["list-3", "list-2", "list-4", "own-paragraph", "markdown", "after-plain-lines"])
def test_an_ask_written_as_a_list_survives_a_small_deck(text, slides):
    """«Просим:» over two to four items is one ask slide — its label as the heading, the items as bullets (two short
    ones as one statement) — kept to the last in every variant (visual used to turn it into cards and lose it at four
    slides); its figures are never tiles."""
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, s.content.bullets) for s in o.slides])
        assert len(o.slides) <= slides, where
        [ask] = _ask_slides(o)
        assert ask.headline == ask.section and _ask_lines(ask)[0] == "Бюджет 14,5 млн ₽ на масштабирование", where
        assert "2 GPU-ноды" in _ask_lines(ask), where
        _two_lines_are_one_statement(o, ask)
        assert not any("14,5" in n.value or n.value == "3 мес" for s in o.slides for n in s.content.numbers), where
        assert not any(t in ("Просим", "Что нужно") for s in o.slides for t in s.content.bullets + s.content.paragraphs), where
        _assert_nothing_invented(o, text)


RESULTS_PLAIN = "Итоги пилота «Умные сводки».\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\nРезультаты: время сократилось до 29 минут, NPS 64.\n"
RESULTS_MD = "# Итоги пилота\n\n## Проблема\nСотрудники тратят 47 минут в день на чтение чатов.\n\n## Результаты\nВремя сократилось до 29 минут, NPS 64.\n\n"
# an ask listed as «Метка: значение» items: one ask, never figure slides named «Бюджет» and «Срок»
LABELLED_LIST_ASKS = [
    (RESULTS_PLAIN + "Просим:\n- бюджет: 14,5 млн ₽;\n- срок: 3 месяца.", "3 месяца"),
    (RESULTS_PLAIN + "Просим:\n- бюджет 14,5 млн ₽ на масштабирование;\n- срок: 3 месяца.", "3 месяца"),  # one item labelled
    (RESULTS_PLAIN + "\nПросим:\n- бюджет: 14,5 млн ₽;\n- срок: 3 месяца;\n- GPU: 2 ноды.", "2 ноды"),
    (RESULTS_MD + "## Что просим\n- Бюджет: 14,5 млн ₽.\n- Срок: 3 месяца.", "3 месяца"),
    (RESULTS_MD + "## Запрос\n- Бюджет: 14,5 млн ₽\n- GPU: 2 ноды", "2 ноды"),
    (RESULTS_MD + "## Решение\n- Бюджет: 14,5 млн ₽.\n- Срок: 3 месяца.", "3 месяца"),  # a «Решение» whose lines ask
]


@pytest.mark.parametrize("slides", [4, 5, 12])
@pytest.mark.parametrize("text, other", LABELLED_LIST_ASKS, ids=["plain", "plain-mixed", "plain-three", "markdown", "markdown-zapros", "markdown-reshenie"])
def test_an_ask_listed_as_labels_and_values_is_one_ask(text, other, slides):
    """«Просим:» / «- бюджет: 14,5 млн ₽» / «- срок: 3 месяца», or «## Что просим» / «## Запрос» over such items, is one
    ask slide under its own name, kept to the last in every variant: never cut into «Бюджет» and «Срок» sections, never
    a tile, never the visual deck's key figure, never in the agenda as «Бюджет» and «Срок»."""
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, s.section, _texts(s)) for s in o.slides])
        assert len(o.slides) <= slides, where
        [ask] = [s for s in o.slides if any("14,5 млн ₽" in t for t in s.content.bullets + s.content.paragraphs)]
        assert ask.kind == K.bullets and ask.headline == ask.section and ask.section in ("Просим", "Что просим", "Запрос", "Решение"), where
        assert any(other in line for line in _ask_lines(ask)), where
        _two_lines_are_one_statement(o, ask)
        assert not any("14,5" in n.value or n.value in ("3 мес", "2") for s in o.slides for n in s.content.numbers), where
        assert not any(s.section in ("Бюджет", "Срок", "GPU") for s in o.slides), where
        assert not any(i.title in ("Бюджет", "Срок", "GPU") for s in o.slides if s.kind == K.agenda for i in s.content.items), where
        assert {"29 минут", "64"} <= {n.value for s in o.slides for n in s.content.numbers}, where  # the results stay
        _assert_nothing_invented(o, text)


@pytest.mark.parametrize("slides", [4, 5, 12])
@pytest.mark.parametrize(
    "line, lines",
    [
        ("Решение: увеличить бюджет до 14,5 млн ₽.", ["Увеличить бюджет до 14,5 млн ₽"]),
        ("Решение:\n- выделить бюджет 14,5 млн ₽;\n- утвердить срок 3 месяца.", ["Выделить бюджет 14,5 млн ₽", "Утвердить срок 3 месяца"]),
        ("\nРешение:\n- выделить бюджет 14,5 млн ₽;\n- утвердить срок 3 месяца.", ["Выделить бюджет 14,5 млн ₽", "Утвердить срок 3 месяца"]),
    ],
    ids=["raise-to", "lead-over-asks", "lead-own-paragraph"],
)
def test_a_solution_that_asks_is_kept_as_the_ask(line, lines, slides):
    """«Решение: увеличить бюджет до 14,5 млн ₽» asks for a level («до N» after an infinitive), and a «Решение:» lead over
    lines that ask is the ask: said under «Решение» in every variant at every size, its figure never a tile nor the
    figure that opens the visual deck."""
    text = RESULTS_PLAIN + line
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, s.section, _texts(s)) for s in o.slides])
        assert len(o.slides) <= slides, where
        [ask] = _by_section(o, "Решение")
        assert ask.kind == K.bullets and ask.headline == "Решение" and _ask_lines(ask) == lines, where
        _two_lines_are_one_statement(o, ask)
        assert not any("14,5" in n.value or n.value == "3 мес" for s in o.slides for n in s.content.numbers), where
        assert {"29 минут", "64"} <= {n.value for s in o.slides for n in s.content.numbers}, where
        _assert_nothing_invented(o, text)


def test_a_level_asked_for_is_not_a_level_reached():
    from verstka.planning.outline import _asks_by_text

    for asks in ("увеличить бюджет до 14,5 млн ₽", "поднять бюджет до 20 млн ₽ на команду", "бюджет 14,5 млн ₽ на масштабирование"):
        assert _asks_by_text(asks), asks
    for reached in ("бюджет поддержки снизился до 3 млн ₽", "бюджет сократится до 8 млн ₽", "бюджет должен увеличиться до 14,5 млн ₽",
                    "бюджет вырос до 14,5 млн ₽"):
        assert not _asks_by_text(reached), reached


@pytest.mark.parametrize("slides", [4, 5, 12])
def test_a_line_of_its_own_after_label_lines_is_not_the_last_labels(slides):
    """«Бюджет: 25 млн ₽.» / «Срок: 3 месяца.» / «Команда из 8 человек начнёт работу в июле.»: the team line, typed on a
    line of its own, is not filed under «Срок» — «3 месяца» stays a figure headed «Срок». Written on the label's own line
    («Срок: 3 месяца. Команда …»), it belongs to «Срок», and the slide is still headed by the label, not by the next
    line over a bare «3 месяца»."""
    text = "План проекта внедрения.\n\nБюджет: 25 млн ₽.\nСрок: 3 месяца.\nКоманда из 8 человек начнёт работу в июле.\nПросим утвердить план."
    same_line = text.replace("3 месяца.\nКоманда", "3 месяца. Команда")
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, s.section, _texts(s)) for s in o.slides])
        assert len(o.slides) <= slides, where
        for s in o.slides:
            if any(_has(s, "3 мес") or "3 месяца" in t for t in _texts(s)):
                assert s.headline == "Срок" and not any("Команда" in t for t in _texts(s)), where
        assert not any(s.section in ("Срок", "Бюджет") and any("Команда" in t for t in _texts(s)) for s in o.slides), where
        if slides == 12:
            assert any(n.value == "3 мес" for s in o.slides for n in s.content.numbers), where
            assert any("Команда из 8 человек начнёт работу в июле" in t for s in o.slides for t in _texts(s)), where
        [ask] = [s for s in o.slides if "Просим утвердить план" in s.content.paragraphs]
        _assert_nothing_invented(o, text)
        o = _outline(strategy, same_line, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, s.section, _texts(s)) for s in o.slides])
        for s in o.slides:
            if any("3 месяца" in t or "3 мес" in t for t in _texts(s)):
                assert s.headline == "Срок" and s.section == "Срок", where
        _assert_nothing_invented(o, same_line)


def test_a_name_keeps_its_capital_in_the_label_of_a_change():
    """A change's label is its subject as written: «Сбер снизил расходы с 10 до 8 млн ₽» keeps «Сбер» — after a label's
    colon, at the start of a line, in a long brief — while a common word the brief writes in lowercase starts it in
    lowercase («время на чтение»)."""
    cases = [
        ("Итоги квартала.\n\nПроблема: ответ клиенту занимал сутки.\nРезультаты: Сбер снизил расходы с 10 до 8 млн ₽, NPS 70.\nПросим: бюджет 3 млн ₽.",
         "10 → 8 млн ₽", "Сбер снизил расходы"),
        ("Итоги квартала.\n\nСбер снизил расходы с 10 до 8 млн ₽.\nNPS вырос до 70.\nПросим: бюджет 3 млн ₽.", "10 → 8 млн ₽", "Сбер снизил расходы"),
        ("Итоги пилота.\n\nРезультаты: время на чтение сократилось с 47 до 29 минут.\nПросим: бюджет 3 млн ₽.", "47 → 29 минут", "время на чтение"),
    ]
    for text, value, label in cases:
        for strategy in STRATEGIES:
            for slides in (4, 12):
                o = _outline(strategy, text, slides=slides)
                labels = {n.label for s in o.slides for n in s.content.numbers if n.value == value}
                assert labels == {label}, (text, strategy, slides, labels)
                _assert_nothing_invented(o, text, {tuple(x.strip() for x in value.split("→"))} | {("10", "8 млн ₽"), ("47", "29 минут")})
    long = LONG_PLAIN.replace("Руководители тратят", "Сбербанк сократил расходы с 10 до 8 млн ₽ в месяц. Руководители тратят")
    o = _outline("visual", long, audience="Руководитель отдела продаж")
    labels = {n.label for s in o.slides for n in s.content.numbers if n.value == "10 → 8 млн ₽"}
    assert labels == {"Сбербанк сократил расходы"}, labels  # as the rules always wrote it (git HEAD)
    [k] = H.kpis_of("Время на чтение сократилось с 47 до 29 минут.", "Итоги: время на чтение сократилось с 47 до 29 минут.")
    assert k.label == "время на чтение"
    assert H.name_case("сбер снизил расходы", "Результаты: Сбер снизил расходы с 10 до 8 млн ₽.") == "Сбер снизил расходы"


@pytest.mark.parametrize("slides", [4, 5, 8, 12])
@pytest.mark.parametrize(
    "text",
    [
        "Итоги пилота.\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\nРезультаты: время сократилось до 29 минут, NPS 64.\n"
        "Просим: увеличить бюджет с 10 до 14,5 млн ₽.",
        "Итоги пилота. Сотрудники тратят 47 минут в день на чтение чатов. NPS вырос до 64. Просим увеличить бюджет с 10 до 14,5 млн ₽.",
    ],
    ids=["labelled", "plain"],
)
def test_the_asks_own_change_never_opens_the_deck(text, slides):
    """«Просим: увеличить бюджет с 10 до 14,5 млн ₽» is said once, on the ask slide: its change is not the visual
    deck's key figure, nor a tile anywhere."""
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=slides)
        where = (strategy, slides, [(s.kind.value, s.headline, [n.value for n in s.content.numbers]) for s in o.slides])
        assert not any("14,5" in n.value or "10" in n.value for s in o.slides for n in s.content.numbers), where
        asks = [s for s in o.slides if any("с 10 до 14,5 млн ₽" in t for t in s.content.paragraphs)]
        assert len(asks) == 1, where
        _assert_nothing_invented(o, text)


@pytest.mark.parametrize(
    "line, value",
    [
        ("Запрос пользователей: 71% хотят получать сводки.", "71%"),
        ("Предложение для клиентов: скидка 20% на годовой тариф.", "20%"),
        ("Нужна интеграция с 1С: срок 3 месяца.", "3 мес"),
    ],
    ids=["zapros-polzovateley", "predlozhenie-dlya-klientov", "nuzhna-integratsiya"],
)
def test_a_label_that_only_starts_with_an_ask_word_is_not_an_ask(line, value):
    """A label is an ask only as the ask word alone («Просим», «Запрос», «Что нужно …») or an ask verb with its object;
    «Запрос пользователей» names a topic: its figure is a figure, and at four slides the real results and the real ask
    stay."""
    from verstka.planning.outline import _ask_line

    assert not _ask_line(line, "Проблема")
    for asking in ("Просим: бюджет 3 млн ₽.", "Запрос: бюджет 3 млн ₽.", "Что нужно от комитета: утвердить план.", "Наш запрос: утвердить план.", "Просим утвердить: план найма."):
        assert _ask_line(asking, "Проблема"), asking
    text = UI_EXAMPLE.replace("Результаты:", f"{line}\nРезультаты:")
    o = _outline("structured", text)
    [topic] = [s for s in o.slides if s.section == H.strip_end(line.split(":")[0])]
    assert [n.value for n in topic.content.numbers] == [value]
    for strategy in STRATEGIES:
        o = _outline(strategy, text, slides=4)
        where = (strategy, [(s.kind.value, s.headline) for s in o.slides])
        assert [s.section for s in _ask_slides(o)] == ["Просим"], where
        assert {"29 минут", "64"} <= {n.value for s in o.slides for n in s.content.numbers}, where


@pytest.mark.parametrize(
    "line, kind, value",
    [
        ("Решение: бюджет поддержки снизился до 3 млн ₽.", K.big_number, "3 млн ₽"),  # a result said in money
        ("Решение: предлагаем бот, который экономит 2 млн ₽ в год.", K.big_number, "2 млн ₽"),  # «предлагаем» a product
        ("Решение: предлагаем утвердить бюджет 3 млн ₽.", K.bullets, None),  # «предлагаем утвердить» asks
    ],
    ids=["budget-reached", "proposes-a-product", "proposes-to-approve"],
)
def test_a_solution_that_reports_a_result_is_not_an_ask(line, kind, value):
    text = f"Итоги пилота.\n\nПроблема: 38% сообщений не читают.\n{line}\nПросим: утвердить запуск."
    o = _outline("structured", text)
    [solution] = _by_section(o, "Решение")
    assert solution.kind == kind, [(s.kind.value, s.headline) for s in o.slides]
    assert [n.value for n in solution.content.numbers] == ([value] if value else [])


def test_a_change_without_a_subject_is_headed_by_its_label():
    """«Сроки: было 5 дней, стало 2 дня» is a figure under its label, and the label under the figure is not the clause
    that says the figures again; a row with it is headed by the section, not by «Было 5 дней, стало 2 дня, NPS 64»."""
    o = _outline("structured", "Итоги пилота.\n\nСроки: было 5 дней, стало 2 дня.\nПросим: утвердить запуск.")
    [term] = _by_section(o, "Сроки")
    assert (term.kind, term.headline, [(n.value, n.label) for n in term.content.numbers]) == (K.big_number, "Сроки", [("5 дней → 2 дня", "")])
    text = "Итоги пилота.\n\nПроблема: отчёт готовится долго.\nРезультаты: было 5 дней, стало 2 дня, NPS 64.\nПросим: утвердить запуск."
    for strategy in STRATEGIES:
        o = _outline(strategy, text)
        where = (strategy, [(s.kind.value, s.headline, [(n.value, n.label) for n in s.content.numbers]) for s in o.slides])
        assert not any(s.headline.startswith("Было") for s in o.slides), where
        [row] = [s for s in o.slides if any(n.value == "5 дней → 2 дня" for n in s.content.numbers)]
        assert row.headline == "Результаты" and [(n.value, n.label) for n in row.content.numbers] == [("5 дней → 2 дня", ""), ("64", "NPS")], where
        _assert_nothing_invented(o, text, {("5 дней", "2 дня")})


LEAD_LISTS = [
    "Итоги пилота.\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\nРезультаты:\n- время сократилось до 29 минут;\n- NPS 64.\n"
    "Просим:\n- бюджет 14,5 млн ₽ на масштабирование.",
    "Итоги пилота.\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\n\nРезультаты:\n- время сократилось до 29 минут;\n- NPS 64.\n\n"
    "Просим:\n- бюджет 14,5 млн ₽ на масштабирование.",
]


@pytest.mark.parametrize("text", LEAD_LISTS, ids=["one-paragraph", "own-paragraphs"])
def test_a_lead_over_a_list_is_headed_by_its_label_and_every_heading_is_capitalised(text):
    """«Результаты:» over its list is the results slide — no line that only says «Результаты», no heading in lowercase
    («время сократилось …»); «Просим:» over its item is the ask, «Просим» not a bullet of it."""
    for slides in (4, 5, 12):
        for strategy in STRATEGIES:
            o = _outline(strategy, text, slides=slides)
            where = (strategy, slides, [(s.kind.value, s.headline, s.content.paragraphs + s.content.bullets) for s in o.slides])
            assert all(s.headline[:1].isupper() for s in o.slides), where
            assert not any(t in ("Результаты", "Просим") for s in o.slides for t in s.content.paragraphs + s.content.bullets), where
            [ask] = _by_section(o, "Просим")
            assert ask.headline == "Просим" and ask.content.paragraphs == ["Бюджет 14,5 млн ₽ на масштабирование"], where
            assert {"29 минут", "64"} <= {n.value for s in o.slides for n in s.content.numbers}, where
            _assert_nothing_invented(o, text)


def test_a_name_keeps_its_capital_in_a_label():
    """A heading's first word starts the label in lowercase only when it is a common word; a name keeps its capital —
    in the plan and on the slide (a model's label «Сбер сэкономил на поддержке» stays as it is, as before)."""
    assert distinct_label("30 млн ₽", "Сбер сэкономил на поддержке", "Сбер сэкономил на поддержке 30 млн ₽") == "Сбер сэкономил на поддержке"
    assert distinct_label("5 минут", "Москва сократила время ответа", "Москва сократила время ответа до 5 минут") == "Москва сократила время ответа"
    assert distinct_label("5 минут", "время ответа клиенту сократилось", "Время ответа клиенту сократилось до 5 минут") == "время ответа клиенту сократилось"
    cases = [
        ("Итоги квартала.\n\nПроблема: ответ клиенту в Москве занимал сутки.\nРезультаты: Москва сократила время ответа до 5 минут, NPS 70.\nПросим: бюджет 3 млн ₽.",
         "5 минут", "Москва сократила время ответа"),
        ("Итоги пилота «Умные сводки».\n\nРезультаты: Умные сводки сократили время на чтение до 29 минут, NPS 64.\nПросим: бюджет 3 млн ₽.",
         "29 минут", "Умные сводки сократили время на чтение"),
        ("Итоги квартала.\n\nРезультаты: Сбер сэкономил на поддержке 30 млн ₽, NPS 70.\nПросим: бюджет 3 млн ₽.", "30 млн ₽", "Сбер сэкономил на поддержке"),
        # a common word the brief writes in lowercase is still lowercased
        ("Итоги квартала.\n\nРезультаты: отдел продаж сократил время на отчёты до 30 минут, NPS 70.\nПросим: бюджет 3 млн ₽.", "30 минут", "отдел продаж сократил время на отчёты"),
    ]
    for text, value, label in cases:
        for strategy in STRATEGIES:
            o = _outline(strategy, text)
            labels = [n.label for s in o.slides for n in s.content.numbers if n.value == value]
            assert labels == [label], (strategy, labels)
            for s in o.slides:
                for n in s.content.numbers:
                    assert distinct_label(n.value, n.label, s.headline) == n.label  # the slide shows the plan's label
    # a name written only with a capital inside a sentence gets it back on a short label too
    assert H.name_case("москва выросла", "Офис в Москве. Москва выросла до 40 человек.") == "Москва выросла"
    assert H.name_case("время сократилось", "Время сократилось до 29 минут.") == "время сократилось"


@pytest.mark.parametrize(
    "text",
    [
        "Итоги пилота за квартал.\nЭкономия 20 минут в день на сотрудника.\nОтдел продаж сократил время на отчёты до 20 минут, NPS 64.",
        "Срок 10 дней.\nАвтоматические сводки непрочитанных веток. Запуск в 3 квартале.\n38% хотят получать сводки.\n38% сообщений не читают. "
        "Довести NPS до 40.\nЗапрос: бюджет 14 млн ₽ на развитие.",
        "Итоги пилота за квартал. Было 5 дней, стало 2 дня, NPS 70. Раскатка займёт 5 дней. Компания тратит 90 млн ₽ на аренду офисов. "
        "38% хотят получать сводки. Предлагаем: бюджет 80 млн ₽ на масштабирование.",
    ],
    ids=["same-value-hero", "text-beside-row", "was-now-in-a-list"],
)
def test_an_untitled_short_brief_never_repeats_a_heading(text):
    """A text slide headed like the KPI row of its section gives the row its line; a figure left alone without a
    statement of its own is headed by its own clause («NPS 64»); «было 5 дней, стало 2 дня, NPS 70» is a change and a
    figure, not a list of three cards — no two slides share a heading."""
    for slides in (4, 5, 12):
        for strategy in STRATEGIES:
            o = _outline(strategy, text, slides=slides)
            heads = [s.headline for s in o.slides]
            assert len(heads) == len(set(heads)), (strategy, slides, heads)
            assert not any(i.title.startswith(("Было", "Стало")) for s in o.slides for i in s.content.items), (strategy, slides)
            _assert_nothing_invented(o, text, {("5 дней", "2 дня")})


# ---------------------------------------------------------------------------------------------- long briefs are read as before

# kinds and headings of the web sample and of a long plain brief as the rules made them before short briefs were read
# line by line (git HEAD of verstka/planning), and a digest of the whole outline (every text, figure and note)
LONG_SNAPSHOTS = {
    ("web", "structured"): ("271728f9987f77f1", [
        "title | Запуск функции «Умные сводки» в корпоративном мессенджере VK WorkSpace",
        "agenda | О чём поговорим | Проблема; Решение; Результаты пилота; Экономика; Дорожная карта; Риски; Что просим",
        "stat_row | Сотрудники тратят в среднем 47 минут в день на чтение рабочих чатов | 47 минут; 38%; 71%",
        "bullets | «Умные сводки» — автоматическое резюме непрочитанных веток с выделением решений",
        "table | Результаты пилота (12 команд, 860 пользователей, 8 недель)",
        "stat_row | Экономия 18 минут в день на сотрудника | 18 минут; 78 ч; 1,9 млн; 0,4 ₽",
        "process | Дорожная карта | Q3; Q4; Q1 2027",
        "cards | Риски | Качество резюме на смешанных языках (русский/английский); Нагрузка на GPU-кластер в пиковые часы; Необходимость обучения пользователей",
        "bullets | Что просим",
        "thanks | Спасибо за внимание",
    ]),
    ("web", "visual"): ("d6bd194a7597fd2d", [
        "title | Запуск функции «Умные сводки» в корпоративном мессенджере VK WorkSpace",
        "big_number | Экономия 18 минут в день на сотрудника | 18 минут",
        "stat_row | Сотрудники тратят в среднем 47 минут в день на чтение рабочих чатов | 47 минут; 38%; 71%",
        "bullets | «Умные сводки» — автоматическое резюме непрочитанных веток с выделением решений",
        "table | Результаты пилота (12 команд, 860 пользователей, 8 недель)",
        "stat_row | Экономика | 78 ч; 1,9 млн; 0,4 ₽",
        "process | Дорожная карта | Q3; Q4; Q1 2027",
        "cards | Риски | Качество резюме на смешанных языках (русский/английский); Нагрузка на GPU-кластер в пиковые часы; Необходимость обучения пользователей",
        "bullets | Что просим",
        "thanks | Спасибо за внимание",
    ]),
    ("web", "compact"): ("68b68538173723eb", [
        "title | Запуск функции «Умные сводки» в корпоративном мессенджере VK WorkSpace",
        "stat_row | Сотрудники тратят в среднем 47 минут в день на чтение рабочих чатов | 47 минут; 38%; 71%",
        "bullets | «Умные сводки» — автоматическое резюме непрочитанных веток с выделением решений",
        "table | Результаты пилота (12 команд, 860 пользователей, 8 недель)",
        "stat_row | Экономия 18 минут в день на сотрудника | 18 минут; 78 ч; 1,9 млн; 0,4 ₽",
        "process | Дорожная карта | Q3; Q4; Q1 2027",
        "two_column | Риски и что просим | Риски; Что просим",
        "thanks | Спасибо за внимание",
    ]),
    ("long", "structured"): ("fb97df74d4a6763f", [
        "title | Переход отдела продаж на новую CRM",
        "agenda | О чём поговорим | Контекст; Цель; Параметры; Ожидаемый эффект; Что просим",
        "bullets | Сейчас менеджеры ведут клиентов в трёх разных таблицах",
        "bullets | Цель",
        "cards | Срок 6 месяцев | Бюджет; Команда; Риски",
        "bullets | Ожидаемый эффект",
        "bullets | Что просим",
        "thanks | Спасибо за внимание",
    ]),
    ("long", "visual"): ("8fcd95e71253577a", [
        "title | Переход отдела продаж на новую CRM",
        "stat_row | Сейчас менеджеры ведут клиентов в трёх разных таблицах | 30%; 6 ч",
        "bullets | Цель",
        "cards | Срок 6 месяцев | Бюджет; Команда; Риски",
        "bullets | Ожидаемый эффект",
        "bullets | Что просим",
        "thanks | Спасибо за внимание",
    ]),
    ("long", "compact"): ("8907dfee4b55ebc1", [
        "title | Переход отдела продаж на новую CRM",
        "bullets | Сейчас менеджеры ведут клиентов в трёх разных таблицах",
        "bullets | Цель",
        "cards | Срок 6 месяцев | Бюджет; Команда; Риски",
        "bullets | Ожидаемый эффект",
        "bullets | Что просим",
        "thanks | Спасибо за внимание",
    ]),
}


def _fingerprint(s: OutlineSlide) -> str:
    bits = [n.value for n in s.content.numbers] + [i.title for i in s.content.items + s.content.columns]
    return f"{s.kind.value} | {s.headline}" + (" | " + "; ".join(bits) if bits else "")


_V2_SLIDE = ("takeaway", "footnote", "rationale", "spec_ref")  # Agent v2 fields: left out while at their defaults
_V2_CONTENT = ("chart2", "formula")


def _digest(o: DeckOutline) -> str:
    dump = []
    for s in o.slides:
        d = s.model_dump(mode="json", exclude={"id"})
        for k in _V2_SLIDE:
            if d.get(k) is None:
                d.pop(k, None)
        if d.get("alternatives") == []:  # Agent v2 (UI): the designer's other forms, empty by default
            d.pop("alternatives")
        for k in _V2_CONTENT:
            if d["content"].get(k) is None:
                d["content"].pop(k, None)
        if d["content"].get("chart"):
            for k, empty in (("categories", []), ("series", [])):
                if d["content"]["chart"].get(k) == empty:
                    d["content"]["chart"].pop(k, None)
        dump.append(d)
    return hashlib.sha256(json.dumps(dump, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


@pytest.mark.parametrize("key", sorted(LONG_SNAPSHOTS))
def test_long_plain_briefs_are_read_as_before(key):
    which, strategy = key
    text, audience = (WEB_SAMPLE, "Продуктовый комитет и руководители направлений") if which == "web" else (LONG_PLAIN, "Руководитель отдела продаж")
    o = _outline(strategy, text, audience=audience)
    digest, fingerprints = LONG_SNAPSHOTS[key]
    assert [_fingerprint(s) for s in o.slides] == fingerprints
    assert _digest(o) == digest  # every text, label, figure and note as before
    assert not _arrows(o)


# kinds of the example briefs' slides before short briefs were read line by line (git HEAD of verstka/planning)
EXAMPLE_KINDS = {
    "cloud_initiative": {
        "structured": "title agenda stat_row cards stat_row table cards process bullets thanks",
        "visual": "title big_number stat_row cards stat_row chart cards process bullets thanks",
        "compact": "title stat_row cards stat_row table cards process bullets thanks",
    },
    "edu_program": {
        "structured": "title agenda bullets cards stat_row table cards cards process thanks",
        "visual": "title big_number cards cards stat_row table cards cards process thanks",
        "compact": "title two_column stat_row table cards cards process thanks",
    },
    "verstka_pitch": {
        "structured": "title agenda bullets cards cards stat_row table cards cards bullets process bullets thanks",
        "visual": "title big_number cards cards cards stat_row chart cards cards cards process cards thanks",
        "compact": "title two_column cards stat_row table two_column bullets process thanks",
    },
    "vk_workspace_feature": {
        "structured": "title agenda bullets cards stat_row chart table process bullets thanks",
        "visual": "title big_number bullets stat_row cards stat_row chart table process bullets thanks",
        "compact": "title two_column stat_row chart table process bullets thanks",
    },
}


@pytest.mark.parametrize("name", sorted(EXAMPLE_KINDS))
def test_example_briefs_keep_their_decks(name):
    b = load_brief(BRIEFS / f"{name}.md")
    for strategy, kinds in EXAMPLE_KINDS[name].items():
        s = get_strategy(strategy)
        o = basic_outline(b.model_copy(deep=True), basic_facts(b.text), s, target_slide_count(b, s))
        assert " ".join(x.kind.value for x in o.slides) == kinds, strategy
        for n in (n for x in o.slides for n in x.content.numbers if "→" in n.value):
            # a long brief shows only the changes it writes itself («снижает срывы с 31% до 12%»), never a linked pair
            start, end = (v.strip().split()[0].rstrip("%") for v in n.value.split("→"))
            assert re.search(rf"\bс\s+{re.escape(start)}\s?%?\s+до\s+{re.escape(end)}", b.text), n.value


CONTINUED_RESULTS = (
    "Итоги пилота «Умные сводки».\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\n"
    "Результаты: время сократилось до 29 минут.\nNPS вырос с 41 до 64.\nПросим: бюджет 14,5 млн ₽ на масштабирование."
)
CONTINUED_SOLUTION = (
    "Пилот чат-бота.\n\nПроблема: операторы отвечают 6 минут.\nРешение: чат-бот на базе LLM.\n"
    "Бот работает круглосуточно и знает базу знаний.\nПросим: бюджет 5 млн ₽."
)


def _figures(slide) -> list[str]:
    return [n.value for n in slide.content.numbers] + [i.number for i in slide.content.items if i.number]


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("slides", [4, 12])
def test_a_line_that_goes_on_after_a_labelled_statement_stays_with_it(strategy, slides):
    # «Результаты: время сократилось до 29 минут.» / «NPS вырос с 41 до 64.»: the second line is still the results —
    # only a «Метка: значение» line («Бюджет: 25 млн ₽») lets the next line of its own start a section
    o = _outline(strategy, CONTINUED_RESULTS, slides=slides)
    rows = [s for s in o.slides if "41 → 64" in _figures(s)]
    assert rows, [(s.kind.value, s.headline, _figures(s)) for s in o.slides]
    if slides == 4 and strategy != "visual":
        assert "29 минут" in _figures(rows[0])  # one results row at a small size
    assert any("14,5" in " ".join(s.content.paragraphs + s.content.bullets) for s in o.slides)  # and the ask stays
    o = _outline(strategy, CONTINUED_SOLUTION, slides=12)
    lone = [s for s in o.slides if s.content.paragraphs == [s.headline] or s.content.bullets == [s.headline]]
    assert not lone, [s.headline for s in lone]  # no slide whose only line repeats its heading


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("slides", [4, 12])
def test_a_solution_lead_over_key_value_items_in_its_own_paragraph_is_one_ask(strategy, slides):
    o = _outline(strategy, RESULTS_PLAIN + "\nРешение:\n- бюджет: 14,5 млн ₽;\n- срок: 3 месяца.", slides=slides)
    heads = [s.headline for s in o.slides]
    assert "Бюджет" not in heads and "Срок" not in heads, heads
    ask = [s for s in o.slides if s.headline == "Решение"]
    assert ask and "14,5" in " ".join(ask[0].content.paragraphs + ask[0].content.bullets)
