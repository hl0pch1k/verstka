"""План + файлы с данными + база знаний в одной колоде: история данных (её графики и выводы — как есть) и слайды по базе
для пунктов плана, которых в данных нет, с источниками и той же проверкой цифр. Модель — заглушка или её нет."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from verstka.knowledge.reference import KbReference
from verstka.knowledge.store import KnowledgeBase
from verstka.knowledge.with_data import add_knowledge, item_covered, outline_slide
from verstka.schemas.outline import Brief, DeckOutline

KB_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "kb"
PLAN = "Итоги квартала\n\n1. Как выросла выручка — покажи на графике\n2. Что думают клиенты\n3. Команда и найм\n4. Что просим у правления\n"


@pytest.fixture
def ref(tmp_path):
    kb = KnowledgeBase.create(tmp_path, "Квартал")
    for f in sorted(KB_DIR.iterdir()):
        kb.add_file(f.name, f.read_bytes())
    return KbReference(kb)


def _story() -> DeckOutline:
    return DeckOutline.model_validate({"title": "Выручка выросла на 37%", "slides": [
        {"id": "title", "kind": "title", "headline": "Выручка выросла на 37%"},
        {"id": "context-1", "kind": "bullets", "headline": "Контекст", "content": {"bullets": [
            "Цель «что думают клиенты» данными не подтверждается: ни в одном файле нет того, о чём она.", "Отчёт для правления по итогам квартала."]}},
        {"id": "data-1", "kind": "chart", "headline": "Выручка выросла на 37%: с 301 до 412 млн ₽", "takeaway": "Рост выручки каждый квартал."},
        {"id": "summary", "kind": "cards", "headline": "Главные выводы", "content": {"items": [{"title": "Выручка", "text": "+37 %"}]}},
    ]})


def test_the_plan_items_the_data_shows_stay_the_data_s():
    data = [s for s in _story().slides if s.id == "data-1"]
    assert item_covered("Как выросла выручка — покажи на графике", data)
    assert not item_covered("Что думают клиенты", data)
    assert not item_covered("Команда и найм", data)


def test_a_written_slide_becomes_an_outline_slide_of_its_form():
    s = outline_slide({"title": "NPS вырос", "lead": "Индекс вырос с 31 до 44", "numbers": [{"value": "44", "label": "NPS"}, {"value": "2,1 %", "label": "отток"}]}, "kb-1")
    assert s.kind.value == "stat_row" and s.subtitle == "Индекс вырос с 31 до 44." and len(s.content.numbers) == 2
    t = outline_slide({"title": "Тарифы", "table": {"header": ["Тариф", "Для кого"], "rows": [["Старт", "малый бизнес"], ["Бизнес", "средние"]]}}, "kb-2")
    assert t.kind.value == "table" and t.content.table.rows[0] == ["Старт", "малый бизнес"]
    b = outline_slide({"title": "Команда", "lead": "В отделе 46 человек", "points": ["Наняли 12"]}, "kb-3")
    assert b.kind.value == "bullets" and b.content.bullets == ["В отделе 46 человек.", "Наняли 12."]
    assert outline_slide({"title": ""}, "x") is None


def test_without_a_model_the_base_fills_the_items_the_data_does_not_show(ref):
    part = add_knowledge(_story(), Brief(text=PLAN), ref)
    ids = [s.id for s in part.outline.slides]
    assert part.covered == ["Как выросла выручка — покажи на графике"]
    assert part.items == ["Что думают клиенты", "Команда и найм", "Что просим у правления"]
    # the data's chart and summary stay as they were; the base's slides go before the summary, the closing item after it
    assert ids[0] == "title" and "data-1" in ids and ids.index("data-1") < ids.index("summary")
    kb_ids = [i for i in ids if i.startswith("kb-")]
    assert len(kb_ids) == 3 and ids.index(kb_ids[0]) < ids.index("summary") < ids.index(kb_ids[-1])
    by = {s.id: s for s in part.outline.slides}
    assert by["data-1"].headline == "Выручка выросла на 37%: с 301 до 412 млн ₽"
    clients = next(s for s in part.outline.slides if s.id.startswith("kb-") and "клиент" in s.headline.lower())
    assert "Источник" in clients.notes and "«Клиенты и отзывы»" in clients.notes
    # the context line «что думают клиенты — not in the data» is gone: the base answers it
    ctx = by["context-1"].content.bullets
    assert ctx == ["Отчёт для правления по итогам квартала."]
    assert "по базе знаний «Квартал»" in part.outline.slides[0].notes


class _Skills:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get(self, name):
        return SimpleNamespace(version="1.2.0", sha256="0" * 64)

    def run(self, name, providers, variables, images=None):
        self.calls.append((name, variables))
        from verstka.planning.topic_writer import FactIssues, TopicPlan, TopicSlide

        model = {"topic_planner": TopicPlan, "topic_slide_writer": TopicSlide, "topic_fact_check": FactIssues}[name]
        ans = self.answers[name](variables) if callable(self.answers[name]) else self.answers[name]
        return SimpleNamespace(parsed=model.model_validate(ans), text=json.dumps(ans, ensure_ascii=False), usage=None, model="fake", label="fake")


class _Providers:
    def has(self, role):
        return role == "llm"

    def with_deadline(self, d):
        return self


def test_with_a_model_the_writer_writes_only_the_items_the_data_does_not_show(ref):
    plan = {"title": "Итоги", "facts": ["NPS вырос с 31 до 44", "В отделе продаж 46 человек"], "slides": [
        {"title": "Клиенты довольны больше", "form": "numbers", "must": [1]}, {"title": "Команда растёт", "form": "list", "must": [2]},
        {"title": "Просим нанять 8 инженеров", "form": "list"}]}
    slides = {
        "Клиенты довольны больше": {"title": "Клиенты довольны больше", "lead": "Что думают клиенты: индекс NPS вырос с 31 до 44.",
                                    "numbers": [{"value": "44", "label": "NPS"}, {"value": "2,1 %", "label": "отток за квартал"}, {"value": "9,9 %", "label": "доля жалоб"}]},
        "Команда растёт": {"title": "Команда растёт", "lead": "Команда и найм: в отделе продаж 46 человек.", "points": ["За квартал наняли 12 сотрудников."]},
        "Просим нанять 8 инженеров": {"title": "Что просим у правления", "lead": "Просим у правления нанять 8 инженеров поддержки для ночной смены."},
    }
    skills = _Skills({"topic_planner": plan, "topic_slide_writer": lambda v: slides[v["title"]], "topic_fact_check": {"issues": []}})
    part = add_knowledge(_story(), Brief(text=PLAN), ref, skills=skills, providers=_Providers())
    planner = next(v for n, v in skills.calls if n == "topic_planner")
    assert planner["plan_items"] == ["Что думают клиенты", "Команда и найм", "Что просим у правления"] and planner["source"] == "kb"
    assert part.writer.basis == "kb" and part.writer.written
    kb = [s for s in part.outline.slides if s.id.startswith("kb-")]
    assert [s.kind.value for s in kb] == ["stat_row", "bullets", "bullets"]
    # «9,9 % жалоб» is in no document: it left the slide (the same figure check as the writer's)
    assert [n.value for n in kb[0].content.numbers] == ["44", "2,1 %"]
    assert all("Источник" in s.notes for s in kb)
    assert [s.id for s in part.outline.slides][-1] == kb[-1].id  # the request closes the deck


def test_no_plan_and_a_base_that_knows_nothing_leave_the_data_deck_as_it_is(ref):
    part = add_knowledge(_story(), Brief(text="Фотосинтез у растений"), ref)
    assert [s.id for s in part.outline.slides] == [s.id for s in _story().slides]
    part = add_knowledge(_story(), Brief(text="Итоги квартала отдела продаж для правления"), ref)
    assert any(s.id.startswith("kb-") for s in part.outline.slides)


def test_a_written_slide_in_other_words_still_takes_its_plan_item(ref):
    from verstka.knowledge import with_data as W

    d = {"title": "Запрос на финансирование", "lead": "Утвердить инвестиции в дата-центры."}
    assert W._item_of(d, ["Команда и найм", "Что просим у правления"], ["Выручка", "Команда и найм", "Что просим у правления"]) == -1


def test_the_writer_s_slides_take_the_plan_items_by_place_and_the_request_closes_the_deck(ref, monkeypatch):
    """Живой прогон 17.10: «Запрос на поддержку ночной смены» (про найм) по словам ушёл к «Команда и найм» и встал
    перед итогом; слайды писателя идут по плану — по одному на пункт, по порядку."""
    from types import SimpleNamespace

    from verstka.knowledge import with_data as W

    sl = [{"n": 2, "title": "Малый бизнес — драйвер роста", "lead": "Сегмент малого бизнеса крупнейший."},
          {"n": 3, "title": "Рост NPS и причины оттока", "lead": "Удовлетворённость клиентов выросла."},
          {"n": 4, "title": "Расширение команды и найм", "lead": "В отделе продаж 46 человек."},
          {"n": 5, "title": "Запрос на поддержку ночной смены", "lead": "Правлению предлагается утвердить найм 8 инженеров."}]
    monkeypatch.setattr(W, "_write", lambda *a, **k: (SimpleNamespace(sources=[], written=True), sl))
    plan = ("Закрытие квартала\n\n1. Как росла выручка по месяцам — покажи на графике\n2. Какие сегменты клиентов растут быстрее\n"
            "3. Что думают клиенты\n4. Команда и найм\n5. Что просим у правления\n")
    story = _story()
    story.slides[2].headline = "Выручка по месяцам росла: с 96 до 144 млн ₽"
    ids = [s.id for s in W.add_knowledge(story, Brief(text=plan), ref).outline.slides]
    assert ids[-1] == "kb-4" and ids.index("summary") == len(ids) - 2
