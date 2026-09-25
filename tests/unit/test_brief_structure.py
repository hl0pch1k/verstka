"""Analyst (Agent v2, step 1): the brief read by rules — slide specs, requested charts / tables / formulas, global
rules and the data of every chart — and completed by the data_extractor per block. The two coffee briefs of the user
(tests/fixtures/briefs) are the reference: the deterministic part alone must give every requested chart its data.
Hermetic: the model is a mock."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from verstka.planning.brief import load_brief, parse_brief_text
from verstka.planning.brief_structure import BlockExtraction, describe, enrich_with_model, numbers_of, read_structure
from verstka.planning.facts import basic_facts, extract_facts
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.brief_structure import BriefStructure
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
BRIEFS = ROOT / "tests" / "fixtures" / "briefs"
LONG = (BRIEFS / "coffee_long.md").read_text(encoding="utf-8")
SHORT = (BRIEFS / "coffee_short.md").read_text(encoding="utf-8")
EXAMPLES = sorted((ROOT / "examples" / "briefs").glob("*.md"))


@pytest.fixture(scope="module")
def long_st() -> BriefStructure:
    return read_structure(LONG)


@pytest.fixture(scope="module")
def short_st() -> BriefStructure:
    return read_structure(SHORT)


def series_of(st: BriefStructure, sid: str):
    return next(s for s in st.series if s.id == sid)


def chart_data(st: BriefStructure, spec_no: int) -> list[tuple]:
    spec = st.specs[spec_no - 1]
    out = []
    for r in spec.charts:
        assert r.series_ids, f"slide {spec_no}: request «{r.what}» has no data"
        s = series_of(st, r.series_ids[0])
        out.append((r.type, s.values, s.categories))
    return out


# ------------------------------------------------------------------ the long brief


def test_long_brief_deck_level(long_st):
    st = long_st
    assert st.title == "Больше прибыли с каждой чашки"
    assert st.subtitle == "План развития кофейни “Точка кофе” на 6 месяцев"
    assert st.slide_count == 10
    assert st.disclaimer == "Все исходные данные и прогнозы условные"
    assert st.notes_rule is True
    assert st.rounding and "округлять до тысяч рублей" in st.rounding
    assert "Не перегружай слайды текстом." in st.rules
    assert any(r.startswith("На каждом слайде должен быть") for r in st.rules)
    assert not any(r.startswith("Создай презентацию") for r in st.rules)  # the task itself is not a rule


def test_long_brief_specs(long_st):
    st = long_st
    assert [s.number for s in st.specs] == list(range(1, 11))
    assert [s.title for s in st.specs][:3] == ["Титульный", "Как работает кофейня сейчас", "Куда уходят деньги"]
    assert st.specs[9].title == "Что контролировать каждую неделю"
    # the text under each heading, verbatim; the closing rules after slide 10 are global, not slide 10's
    assert "— аренда — 120 000 рублей;" in st.specs[2].text
    assert "Финальный вывод" in st.specs[9].text and "Не перегружай" not in st.specs[9].text
    assert st.specs[1].formula == "100 × 300 × 30 = 900 000 рублей"
    s3 = st.specs[2]
    assert s3.footnote == "Налоги, проценты по кредитам и амортизация в упрощенной модели не учитываются"
    [(ctype, values, cats)] = chart_data(st, 3)
    assert ctype in ("pie", None) and values == [315000, 270000, 120000, 25000, 20000, 30000]
    assert cats[0] == "Продукты, упаковка и списания" and cats[2] == "Аренда"
    assert st.specs[8].takeaway == "Выручка увеличивается на 26,5%, а ежемесячная операционная прибыль — примерно на 112%"
    assert st.specs[9].takeaway == "Рост прибыли зависит от трех измеримых изменений: больше покупок, выше средний чек и меньше потерь"


def test_long_brief_table_and_plan(long_st):
    st = long_st
    s9 = st.specs[8]
    assert s9.table is True and len(s9.table_ids) == 1
    t = st.tables[s9.table_ids[0]]
    assert t.columns == ["Показатель", "Сейчас", "Цель"] and len(t.rows) == 7
    assert t.rows[0] == ["Покупки в день", "100", "115"]
    assert t.rows[2] == ["Месячная выручка", "900 000 рублей", "1 138 500 рублей"]
    assert t.rows[6] == ["Операционная рентабельность", "13,3%", "22,4%"]
    s8 = st.specs[7]
    assert [i.title for i in s8.items] == [f"{k}-й месяц" for k in range(1, 7)]
    assert s8.items[0].text == "Учет показателей и обновление меню"
    budget = [series_of(st, sid) for sid in s8.series_ids]
    assert any(s.values == [70000, 35000, 25000, 20000, 30000] and s.name == "Общий бюджет запуска" for s in budget)
    # before/after figures said in a sentence become two-point series of their slide
    pairs = {series_of(st, sid).name: series_of(st, sid).values for sid in st.specs[4].series_ids}
    assert pairs["Средний чек"] == [300, 330] and pairs["Доля чеков с едой"] == [20, 30]
    assert [i.title for i in st.specs[9].items][:2] == ["Количество покупок в день", "Средний чек"]


# ------------------------------------------------------------------ the short brief


def test_short_brief_charts_get_their_data(short_st):
    st = short_st
    assert [s.number for s in st.specs] == [1, 2, 3, 4, 5]
    assert st.title == "Кофейня «Точка кофе»: план увеличения прибыли за 6 месяцев"
    assert st.disclaimer == "Все цифры условные"
    assert chart_data(st, 1) == [("pie", [60, 25, 15], ["Кофе", "Десерты и выпечка", "Чай и другие напитки"])]
    [(t2, v2, c2)] = chart_data(st, 2)
    assert t2 == "pie" and v2 == [315000, 270000, 120000, 25000, 20000, 30000] and len(c2) == 6
    assert [(t, v) for t, v, _ in chart_data(st, 3)] == [("column", [100, 115]), ("column", [300, 330])]
    (t4a, v4a, c4a), (t4b, v4b, _) = chart_data(st, 4)
    assert t4a == "line" and v4a == [900000, 930000, 970000, 1015000, 1060000, 1100000, 1138500]
    assert c4a[0] == "Сейчас" and c4a[1] == "1-й месяц" and c4a[-1] == "6-й месяц"
    assert t4b == "pie" and v4b == [70000, 35000, 25000, 20000, 30000]
    assert [(t, v) for t, v, _ in chart_data(st, 5)] == [("column", [120000, 254795])]
    assert st.specs[1].footnote and "не включены" in st.specs[1].footnote
    assert describe(st) == "Нашёл в брифе 5 слайдов, 11 рядов данных и 7 заказанных диаграмм"


@pytest.mark.parametrize("text", [LONG, SHORT] + [p.read_text(encoding="utf-8") for p in EXAMPLES])
def test_every_series_value_is_a_number_of_the_brief(text):
    st = read_structure(text)
    pool = numbers_of(text)
    for s in st.series:
        assert len(s.values) == len(s.categories) >= 2, s
        for v in s.values:
            assert any(abs(v - p) < 1e-6 for p in pool), (s.name, v)
    ids = {s.id for s in st.series}
    assert len(ids) == len(st.series)
    for spec in st.specs:
        assert set(spec.series_ids) <= ids and all(0 <= i < len(st.tables) for i in spec.table_ids)
        assert all(set(r.series_ids) <= set(spec.series_ids) for r in spec.charts)


# ------------------------------------------------------------------ briefs without slide specs, other forms


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_generic_briefs_do_not_break(path):
    text = path.read_text(encoding="utf-8")
    st = read_structure(text)
    assert st.specs == []
    body = parse_brief_text(text).text
    assert read_structure(body).series == st.series  # the pipeline passes the text without front matter
    if path.stem == "vk_workspace_feature":
        users = next(s for s in st.series if s.categories[:2] == ["Май", "Июнь"])
        assert users.values == [1200, 3400, 6100, 9800, 12400]
        assert st.slide_count == 12 and len(st.tables) == 2
    if path.stem == "cloud_initiative":
        assert {s.name for s in st.series} >= {"Сейчас", "В VK Cloud"}


def test_generic_registry_keeps_its_table_series_first():
    """The rules' registry of a brief without slides is unchanged where it was: the tables' series keep their ids."""
    b = load_brief(ROOT / "examples" / "briefs" / "vk_workspace_feature.md")
    f = basic_facts(b.text)
    assert f.series[0].id == "s1" and f.series[0].values == [1200, 3400, 6100, 9800, 12400]


def test_other_heading_forms():
    text = "Презентация на 3 слайда.\n\n1. Проблема\nКлиенты ждут ответа 47 минут.\n\n2. Решение\nБот отвечает за 2 минуты.\n\n3. Итог\nВывод: время ответа сократилось с 47 до 2 минут.\n"
    st = read_structure(text)
    assert [s.number for s in st.specs] == [1, 2, 3] and st.slide_count == 3
    assert st.specs[2].takeaway == "Время ответа сократилось с 47 до 2 минут"
    # a numbered list is not a slide plan: no lines of its own under each number
    assert read_structure("Сделай 5 слайдов о нас.\n1. Команда\n2. Продукт\n3. Клиенты\n").specs == []
    colon = read_structure("## Слайд 1: Итоги\nКлиентов стало больше.\n## Слайд 2: План\nНужна круговая диаграмма каналов: сайт — 50%, магазин — 30%, партнеры — 20%.\n")
    assert [s.title for s in colon.specs] == ["Итоги", "План"]
    assert chart_data(colon, 2) == [("pie", [50, 30, 20], ["Сайт", "Магазин", "Партнеры"])]


def test_words_that_are_not_chart_requests():
    st = read_structure("Слайд 1. Риски\nПредложи меры: корректировать графики смен и сравнивать поставщиков.\nСлайд 2. Итог\nВсё.\n")
    assert st.specs[0].charts == []
    assert read_structure("").specs == [] and read_structure("").series == []


# ------------------------------------------------------------------ the facts registry


class _NoModel:
    name = "none"
    model = "none"

    def complete(self, *a, **k):  # pragma: no cover - the test fails if called
        raise AssertionError("no model call expected")


def test_registry_takes_the_structure_and_calls_no_model(short_st):
    brief = parse_brief_text(SHORT)
    providers = ProviderRegistry(roles={"llm": _NoModel()})
    st = short_st.model_copy(deep=True)
    from verstka.schemas.outline import Fact

    st.facts = [Fact(id="m1", value="45", unit="м²", label="площадь кофейни")]
    out, warnings = extract_facts(brief, SkillsRegistry.load(), providers, structure=st)
    # the ids the slide specs name are the registry's ids
    for spec in st.specs:
        for sid in spec.series_ids:
            assert next(s for s in out.series if s.id == sid).values == series_of(st, sid).values
    assert any(f.value == "45" and f.unit == "м²" for f in out.facts)
    assert [f.id for f in out.facts] == [f"f{i}" for i in range(1, len(out.facts) + 1)]
    # without a structure the rules' registry reads it itself
    assert [s.id for s in basic_facts(brief.text).series] == [s.id for s in short_st.series]


# ------------------------------------------------------------------ the model per block

MODEL_BRIEF = """Слайд 1. Итоги пилота
В пилоте участвовали 12 400 сотрудников из 37 компаний. Доля задач, закрытых в срок, выросла на 34%, экономия — 2,1 часа в неделю.
Нужна диаграмма результатов пилота.
Слайд 2. Бюджет
Бюджет по статьям:
— разработка — 40 000 рублей;
— реклама — 25 000 рублей;
— поддержка — 15 000 рублей.
"""


def test_enrich_runs_the_model_only_where_rules_fell_short():
    st = read_structure(MODEL_BRIEF)
    assert st.specs[0].charts[0].series_ids == [] and st.specs[1].series_ids  # slide 2 is covered by the list
    seen: list[str] = []
    lock = threading.Lock()

    def respond(messages):
        text = messages[-1].content
        with lock:
            seen.append(text)
        return {
            "facts": [{"id": "f1", "value": "12 400", "unit": "чел.", "label": "участники пилота"}, {"id": "f2", "value": "99", "label": "выдумка"}],
            "series": [
                {"id": "a", "name": "Результаты пилота", "categories": ["Сотрудники", "Компании"], "values": [12400, 37]},
                {"id": "b", "name": "Выдумка", "categories": ["x", "y"], "values": [999, 1000]},  # not in the text
            ],
            "tables": [],
            "charts": [{"series": "a", "type": "column"}],
        }

    providers = ProviderRegistry.mock({"*": respond})
    events: list[dict] = []
    warnings: list[str] = []
    out = enrich_with_model(st, MODEL_BRIEF, SkillsRegistry.load(), providers, deadline=None, progress=events.append, warnings=warnings)
    assert len(seen) == 1 and "12 400" in seen[0] and "разработка" not in seen[0]  # one call, slide 1 only
    req = out.specs[0].charts[0]
    new = series_of(out, req.series_ids[0])
    assert new.values == [12400, 37] and req.type == "column"  # the hint gives the kind the user did not name
    assert not any(s.values == [999, 1000] for s in out.series)  # a figure the text does not have is dropped
    assert [f.value for f in out.facts] == ["12 400"]
    assert st.specs[0].charts[0].series_ids == []  # the input structure is not changed
    assert all(e["type"] == "agent" and e["step"] == "analyst" and e["message"] for e in events) and len(events) == 2
    assert "слайдов 1" in events[0]["message"] and not warnings


def test_enrich_keeps_the_rules_when_the_model_fails():
    st = read_structure(MODEL_BRIEF)

    def boom(messages):
        raise ProviderError("host down")

    warnings: list[str] = []
    out = enrich_with_model(st, MODEL_BRIEF, SkillsRegistry.load(), ProviderRegistry.mock(boom), warnings=warnings)
    assert out.series == st.series and warnings
    # no model at all: the structure as it is
    assert enrich_with_model(st, MODEL_BRIEF, None, None) is st


def test_data_extractor_v2_is_compact():
    skills = SkillsRegistry.load()
    spec = skills.get("data_extractor")
    assert spec.version == "0.2.0" and spec.output_schema.endswith("BlockExtraction")
    assert int(spec.params["max_tokens"]) <= 2000
    prompt = skills.render("data_extractor", {"brief": "Выручка 900 000 рублей.", "language": "ru"})
    assert "source_span" not in prompt["system"] and "charts" in prompt["system"]
    # the answer schema still reads as the old one for the whole-brief path
    parsed = BlockExtraction.model_validate(json.loads('{"facts": [{"id": "f1", "value": "3", "label": "x"}], "series": [], "tables": []}'))
    assert parsed.charts == [] and parsed.facts[0].source_span is None


def test_negated_requests_are_not_requests():
    st = read_structure("Слайд 1. А\nНе используй здесь диаграммы, только текст.\nСлайд 2. Б\nНужна таблица цен.\n")
    assert st.specs[0].charts == [] and st.specs[1].table is True


def test_whole_brief_path_keeps_the_model_ids():
    """Without a structure the data_extractor reads the whole brief as before: its series keep their ids (the model
    plan names them), the structure's other series follow with ids of their own."""
    brief = parse_brief_text(SHORT)
    answer = {"facts": [], "series": [{"id": "s1", "name": "Выручка", "categories": ["Сейчас", "Цель"], "values": [900000, 1138500]}], "tables": []}
    out, _ = extract_facts(brief, SkillsRegistry.load(), ProviderRegistry.mock({"*": answer}))
    assert out.series[0].id == "s1" and out.series[0].values == [900000, 1138500]
    ids = [s.id for s in out.series]
    assert len(ids) == len(set(ids)) and any(s.values == [60, 25, 15] for s in out.series)
