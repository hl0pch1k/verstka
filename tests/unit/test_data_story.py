"""Колода-история из данных (описание решения §3, verstka/data/story.py): порядок истории, слайды датасетов с
`OutlineSlide.data`, число слайдов, пропуски, приложения, навык `data_storyteller` (числа — только из фактов) и
оба набора примеров. Без модели и без шаблона: только план колоды."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from verstka.data.headline import headline_ok, numbers_in
from verstka.data.readers import read_file
from verstka.data.story import (
    STORY_FILE, StoryWriting, build_data_outline, build_data_story, data_slide_labels, read_story, stamp_variants, story_plan,
)
from verstka.providers.base import ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.data import Table
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
SCIENCE = ROOT / "examples" / "data-science-2026"
SALES_BRIEF = ("Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, что даёт "
               "выручку и где узкие места. Данные — в приложенных файлах.")
SCIENCE_BRIEF = ("Итоги университета за 2026 год для учёного совета. Покажи, как подготовка влияет на баллы ЕГЭ, как устроен "
                 "приём по формам обучения, как растёт наука и на что ушёл бюджет НИОКР. Данные — в приложенных файлах.")
DATA_EXT = {".csv", ".xlsx", ".json", ".txt", ".tsv"}


def tables_of(folder: Path) -> list[Table]:
    files = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in DATA_EXT and p.is_file()]
    return [t for p in files for t in read_file(p)]


@pytest.fixture(scope="module")
def sales() -> list[Table]:
    return tables_of(SALES)


@pytest.fixture(scope="module")
def sales_story(sales):
    return build_data_story(Brief(text=SALES_BRIEF, slide_count=9), sales)


def _by_file(o) -> dict:
    return {s.data.file: s for s in o.slides if s.data is not None and s.data.part[0] == 1}


# ── the deterministic story ──────────────────────────────────────────────────────────────────────────────────────
def test_the_sample_story_follows_the_scenario(sales_story):
    o = sales_story.outline
    assert len(o.slides) == 9
    assert o.slides[0].kind.value == "title"
    assert o.title == "Итоги продаж VK Cloud за 9 месяцев 2026 года" and o.subtitle == "Для правления"
    files = [s.data.file if s.data else s.id for s in o.slides]
    # cover → key figures → the goals' datasets in the goals' order → distribution → quality (gaps) → reference → summary
    assert files == ["title", "Итоги квартала.txt", "Выручка по месяцам.csv", "Регионы.xlsx", "Каналы продаж.json",
                     "Время ответа поддержки.csv", "NPS по кварталам.csv", "Клиенты.xlsx", "summary"]
    kinds = {s.data.file: (s.kind.value, s.content.chart.type if s.content.chart else None) for s in o.slides if s.data}
    assert kinds["Итоги квартала.txt"] == ("stat_row", None)
    assert kinds["Выручка по месяцам.csv"] == ("chart", "line")
    assert kinds["Регионы.xlsx"] == ("chart", "bar")
    assert kinds["Каналы продаж.json"] == ("chart", "doughnut")
    assert kinds["Время ответа поддержки.csv"] == ("chart", "histogram")
    assert kinds["NPS по кварталам.csv"] == ("chart", "line")
    assert kinds["Клиенты.xlsx"] == ("table", None)
    assert o.planned_by == "rules" and o.purpose == "report"


def test_every_data_slide_carries_its_data_headline_source_and_reasons(sales_story):
    for s in sales_story.outline.slides:
        if s.data is None:
            continue
        d = s.data
        assert d.dataset_id and d.file and d.profile_line and d.task is not None and d.options
        assert d.headline_facts, s.headline
        assert s.footnote == f"Источник: {d.file}"
        assert s.rationale and s.alternatives
        assert all(a.kind != d.options[d.chosen].kind or a.change for a in s.alternatives)
        # the headline is a conclusion with the data's own numbers
        assert headline_ok(s.headline, d.headline_facts, data_slide_labels(s)), s.headline
        assert s.headline != d.plain_headline
    rev = _by_file(sales_story.outline)["Выручка по месяцам.csv"]
    assert rev.headline == "Выручка выросла на 23% к сентябрю"
    assert rev.content.chart.y_title and rev.content.chart.x_title and rev.content.chart.unit == "млн ₽"
    nps = _by_file(sales_story.outline)["NPS по кварталам.csv"]
    assert nps.content.chart.gaps is True and None in nps.content.chart.series[0].values


def test_the_summary_says_the_goals_conclusions(sales_story):
    summary = sales_story.outline.slides[-1]
    assert summary.id == "summary" and summary.kind.value == "cards"
    assert [it.title for it in summary.content.items] == ["Выручка по месяцам", "Выручка по регионам", "Каналы продаж"]
    heads = {s.headline for s in sales_story.outline.slides if s.data}
    assert all(it.text in heads for it in summary.content.items)


def test_the_story_logs_what_the_analyst_decided(sales, sales_story):
    log = sales_story.outline.agent_log
    assert len([x for x in log if x.startswith("Аналитик данных:")]) == len(sales)
    assert any("Цель «покажи рост выручки»" in x for x in log)
    events = []
    build_data_story(SALES_BRIEF, sales, progress=lambda m, f=None, event=None: events.append(event))
    steps = {e["step"] for e in events if e}
    assert steps == {"data", "designer"}
    assert all(e["type"] == "agent" for e in events if e)


def test_the_story_is_deterministic_and_never_reads_the_template(sales):
    a = build_data_outline(SALES_BRIEF, sales, manifest=None)
    b = build_data_outline(SALES_BRIEF, sales, manifest=object())  # (any template: the story is the same)
    assert a.model_dump_json() == b.model_dump_json()


def test_the_slide_count_drops_the_least_important_first(sales):
    st = build_data_story(Brief(text=SALES_BRIEF, slide_count=6), sales)
    o = st.outline
    assert len(o.slides) == 6
    files = [s.data.file for s in o.slides if s.data]
    # the goals' datasets and the key figures stay; the reference and the quality slides go first
    assert {"Выручка по месяцам.csv", "Регионы.xlsx", "Каналы продаж.json"} <= set(files)
    assert "Клиенты.xlsx" not in files
    assert o.slides[0].kind.value == "title" and o.slides[-1].id == "summary"
    assert st.dropped and any("слайдов просили 6" in x.lower() for x in o.agent_log)


def test_a_file_without_data_for_a_chart_gets_no_slide_and_says_why(sales):
    junk = Table(id="junk", file="Заметки.csv", kind="csv", columns=["Текст"], rows=[["просто текст"]], units=[None])
    st = build_data_story(SALES_BRIEF, list(sales) + [junk])
    assert all(s.data is None or s.data.file != "Заметки.csv" for s in st.outline.slides)
    assert st.skipped and st.skipped[0]["file"] == "Заметки.csv" and "Не для графика" in st.skipped[0]["message"]
    assert any("Заметки.csv" in x and "без слайда" in x for x in st.outline.agent_log)


def _people(n: int = 25) -> Table:
    rows = [[f"Сотрудник {i}", ["Москва", "Казань", "Пермь"][i % 3], f"Отдел {i % 5}"] for i in range(1, n + 1)]
    return Table(id="people", file="Сотрудники.csv", kind="csv", columns=["Имя", "Город", "Отдел"], rows=rows, units=[None] * 3)


def test_a_table_split_over_slides_keeps_its_parts_together():
    st = build_data_story("Справка по сотрудникам", [_people()])
    parts = [s for s in st.outline.slides if s.data is not None]
    assert [s.data.part for s in parts] == [(1, 3), (2, 3), (3, 3)]
    assert parts[1].headline.endswith("(продолжение)") and parts[1].headline.startswith(parts[0].headline)
    assert all(s.footnote == "Источник: Сотрудники.csv" for s in parts)
    assert all(s.content.table.columns == parts[0].content.table.columns for s in parts)
    assert sum(len(s.content.table.rows) for s in parts) == 25
    assert not any(s.id == "summary" for s in st.outline.slides)  # one dataset: its slides are the conclusion


def test_a_big_reference_table_goes_to_the_appendix_and_the_count_drops_it_first(sales):
    st = build_data_story(SALES_BRIEF, list(sales) + [_people()])
    ids = [s.id for s in st.outline.slides]
    people = [k for k, s in enumerate(st.outline.slides) if s.data is not None and s.data.file == "Сотрудники.csv"]
    assert people and min(people) > ids.index("summary")
    st9 = build_data_story(Brief(text=SALES_BRIEF, slide_count=9), list(sales) + [_people()])
    assert all(s.data is None or s.data.file != "Сотрудники.csv" for s in st9.outline.slides)


def test_without_text_the_deck_is_titled_by_its_data(sales):
    o = build_data_outline("", sales)
    assert o.title == "Что показывают данные" and o.subtitle
    assert not any(s.id.startswith("context") for s in o.slides)


def test_a_brief_with_context_gets_a_context_slide(sales):
    text = ("Итоги продаж VK Cloud за 9 месяцев 2026 года. Компания вышла в три новых региона и запустила маркетплейс. "
            "Команда продаж выросла вдвое, а партнёрская программа заработала с весны. Покажи рост выручки.")
    o = build_data_outline(text, sales)
    ctx = [s for s in o.slides if s.id.startswith("context")]
    assert len(ctx) == 1 and ctx[0].verbatim and len(ctx[0].content.bullets) == 2
    assert not any("Покажи" in b for b in ctx[0].content.bullets)


def test_the_second_sample_set_builds_without_a_crash():
    st = build_data_story(Brief(text=SCIENCE_BRIEF), tables_of(SCIENCE))
    o = st.outline
    data = [s for s in o.slides if s.data is not None]
    assert len(data) >= 5 and o.slides[0].kind.value == "title"
    for s in data:
        assert s.content.chart is not None or s.content.table is not None or s.content.numbers
        assert s.footnote and s.footnote.startswith("Источник:")


# ── the storyteller ──────────────────────────────────────────────────────────────────────────────────────────────
def _model(answer, model="qwen-test"):
    mp = MockProvider(answer if callable(answer) else (lambda messages: answer), model=model)
    return mp, ProviderRegistry(roles={"llm": mp})


ANSWER = {
    "title": "Продажи VK Cloud в 2026 году",
    "subtitle": "Итоги девяти месяцев для правления",
    "headlines": [
        {"id": "data-3", "headline": "Выручка за год выросла на 23%"},  # ok: 23 is a fact
        {"id": "data-7", "headline": "Москва — 41% выручки, а Казань растёт на 45% в год"},  # 45 is not a fact
        {"id": "data-5", "headline": "Почти половину выручки приносят прямые продажи"},  # ok: no number
        {"id": "data-1", "headline": "NPS вырос до 52 в 2026 году"},  # 2026 is not a fact of the dataset
    ],
    "summary_title": "Рост держится на крупных клиентах и регионах",
    "summary": ["Выручка выросла на 23% к сентябрю", "Москва даёт 41% выручки", "Прямые продажи — 46% выручки"],
    "next_steps": ["Разобрать узкие места поддержки", "Удержать 50 крупных клиентов"],
}


def test_the_storyteller_rephrases_only_with_the_facts(sales):
    mp, reg = _model(ANSWER)
    st = build_data_story(Brief(text=SALES_BRIEF, slide_count=10), sales, use_llm=True, skills=SkillsRegistry.load(), providers=reg)
    o = st.outline
    assert len(mp.calls) == 1 and mp.calls[0]["schema"] == "StoryWriting"
    by = _by_file(o)
    assert o.title == "Продажи VK Cloud в 2026 году" and o.slides[0].headline == o.title
    assert by["Выручка по месяцам.csv"].headline == "Выручка за год выросла на 23%"
    assert by["Каналы продаж.json"].headline == "Почти половину выручки приносят прямые продажи"
    # refused: a number the data does not give — the analysis's own headline stays
    assert by["Регионы.xlsx"].headline == "Москва даёт 41% выручки, Казань растёт быстрее всех"
    assert by["NPS по кварталам.csv"].headline == "NPS вырос до 52, за два квартала данных нет"
    refused = {r["to"]: r["why"] for r in st.rejected}
    assert "45" in refused["Москва — 41% выручки, а Казань растёт на 45% в год"]
    assert "Удержать 50 крупных клиентов" in refused
    # every headline of the deck still passes the check against its own facts
    for s in o.slides:
        if s.data is not None:
            assert headline_ok(s.headline, s.data.headline_facts, data_slide_labels(s)), s.headline
    summary = next(s for s in o.slides if s.id == "summary")
    assert summary.headline == "Рост держится на крупных клиентах и регионах"
    assert [it.title for it in summary.content.items] == ["Выручка по месяцам", "Выручка по регионам", "Каналы продаж"]
    steps = next(s for s in o.slides if s.id == "next-steps")
    assert steps.content.bullets == ["Разобрать узкие места поддержки"]
    assert o.planned_by == "model" and st.model == "qwen-test" and st.model_used
    assert st.usage()["calls"] == 1 and st.usage()["failed"] == 0
    assert any("не принято" in x for x in o.agent_log)


def test_the_prompt_gives_the_model_the_facts_and_the_draft(sales):
    seen = {}

    def answer(messages):
        seen["system"], seen["user"] = messages[0].content, messages[-1].content
        return {}

    _, reg = _model(answer)
    build_data_story(SALES_BRIEF, sales, use_llm=True, skills=SkillsRegistry.load(), providers=reg)
    assert messages_ok(seen)


def messages_ok(seen: dict) -> bool:
    user, system = seen["user"], seen["system"]
    assert "Never write a number that is not given to you" in system
    assert "[data-3] file «Выручка по месяцам.csv»" in user
    assert "draft headline: Выручка выросла на 23% к сентябрю" in user
    assert "+23% год к году (value 23.0 %)" in user
    return True


def test_a_failed_model_leaves_the_deterministic_story(sales):
    def boom(messages):
        raise ProviderError("the host is slow (timeout)")

    _, reg = _model(boom)
    det = build_data_outline(Brief(text=SALES_BRIEF, slide_count=9), sales)
    st = build_data_story(Brief(text=SALES_BRIEF, slide_count=9), sales, use_llm=True, skills=SkillsRegistry.load(), providers=reg)
    assert [s.headline for s in st.outline.slides] == [s.headline for s in det.slides]
    assert st.outline.planned_by == "rules" and st.model_error and not st.model_used
    assert st.usage()["failed"] == 1
    assert any("модель не ответила" in x for x in st.outline.agent_log)


def test_numbers_in_a_title_come_from_the_brief(sales):
    _, reg = _model({"title": "Продажи VK Cloud выросли на 30% в 2026 году"})
    st = build_data_story(SALES_BRIEF, sales, use_llm=True, skills=SkillsRegistry.load(), providers=reg)
    assert st.outline.title == "Итоги продаж VK Cloud за 9 месяцев 2026 года"
    assert st.rejected and st.rejected[0]["what"] == "title"


def test_the_writing_schema_is_what_the_skill_declares():
    spec = SkillsRegistry.load().get("data_storyteller")
    assert spec.output_schema == "verstka.data.story.StoryWriting" and spec.role == "llm"
    assert set(StoryWriting.model_fields) >= {"title", "headlines", "summary", "next_steps"}


# ── after the generation ─────────────────────────────────────────────────────────────────────────────────────────
class _V:
    def __init__(self, d: Path) -> None:
        self.out_dir, self.planner = d, {"supplied": True}


class _Res:
    def __init__(self, vs) -> None:
        self.variants = vs


def test_the_variants_say_who_wrote_the_plan_and_count_the_storyteller(tmp_path, sales):
    mp, reg = _model(ANSWER)
    st = build_data_story(SALES_BRIEF, sales, use_llm=True, skills=SkillsRegistry.load(), providers=reg)
    vd = tmp_path / "structured"
    vd.mkdir()
    (vd / "run_manifest.json").write_text(json.dumps({"planner": {"supplied": True}, "usage": {"calls": 2, "requests": 2, "tokens_in": 10, "tokens_out": 5, "failed": 0, "cost_rub": None, "by_skill": {"eyes": {"calls": 2}}}}), encoding="utf-8")
    v = _V(vd)
    stamp_variants(_Res([v]), st, tmp_path)
    rm = json.loads((vd / "run_manifest.json").read_text(encoding="utf-8"))
    assert rm["planner"]["planned_by"] == "model" and rm["planner"]["model"] == "qwen-test" and "supplied" not in rm["planner"]
    assert rm["usage"]["calls"] == 3 and "StoryWriting" in rm["usage"]["by_skill"] and "eyes" in rm["usage"]["by_skill"]
    assert v.planner["planned_by"] == "model"
    saved = read_story(tmp_path / STORY_FILE)
    assert saved["dataset_ids"] == st.dataset_ids and len(saved["plans"]) == len(sales)
    plan = story_plan(saved, st.dataset_ids[0])
    assert plan is not None and plan.profile.table_id == st.dataset_ids[0]
    assert numbers_in("Топ-10") == [10.0]


def test_the_context_goes_before_any_data(sales):
    text = ("Итоги продаж VK Cloud за 9 месяцев 2026 года. Компания вышла в три новых региона и запустила маркетплейс. "
            "Команда продаж выросла вдвое, а партнёрская программа заработала с весны. Покажи рост выручки.")
    full = build_data_outline(Brief(text=text), sales)
    assert len(full.slides) == 10 and any(s.id.startswith("context") for s in full.slides)
    o = build_data_outline(Brief(text=text, slide_count=9), sales)
    assert len(o.slides) == 9 and not any(s.id.startswith("context") for s in o.slides)
    assert len([s for s in o.slides if s.data is not None]) == 7
