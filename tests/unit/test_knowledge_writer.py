"""Режим писателя по базе знаний: короткий запрос (или план без своих цифр) + документы человека → текст колоды по
фактам из базы. Цифры, которых нет в документах, уходят; у каждого утверждения — документ и место; заметки слайдов и
«Почему так» называют источник. Модель — заглушка (ответы навыков заданы), сеть закрыта."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from verstka.knowledge.reference import KbReference
from verstka.knowledge.store import KnowledgeBase
from verstka.planning import topic_writer as T
from verstka.planning.writer import WriterMode, attribution, writer_mode
from verstka.schemas.outline import Brief

KB_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "kb"


class _Skills:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def get(self, name):
        return SimpleNamespace(version="1.2.0", sha256="0" * 64)

    def run(self, name, providers, variables, images=None):
        self.calls.append((name, variables))
        from verstka.planning.topic_writer import FactIssues, TopicPlan, TopicSlide
        from verstka.schemas.writer import ReferenceAnswer

        model = {"topic_reference": ReferenceAnswer, "topic_planner": TopicPlan, "topic_slide_writer": TopicSlide, "topic_fact_check": FactIssues}[name]
        ans = self.answers[name](variables) if callable(self.answers[name]) else self.answers[name]
        return SimpleNamespace(parsed=model.model_validate(ans), text=json.dumps(ans, ensure_ascii=False), usage=None, model="fake", label="fake")


class _Providers:
    def has(self, role):
        return role == "llm"

    def with_deadline(self, d):
        return self


@pytest.fixture
def ref(tmp_path):
    kb = KnowledgeBase.create(tmp_path, "Квартал отдела продаж")
    for f in sorted(KB_DIR.iterdir()):
        kb.add_file(f.name, f.read_bytes())
    return KbReference(kb)


PLAN = {"title": "Итоги третьего квартала", "subtitle": "Выручка, клиенты и планы", "kind": "company",
        "facts": ["Выручка за квартал — 412 млн ₽, на 18% больше второго квартала", "NPS вырос с 31 до 44"],
        "slides": [{"title": "Выручка выросла на 18%", "form": "numbers", "must": [1]}, {"title": "Клиенты довольны больше", "form": "text", "must": [2]},
                   {"title": "Команда растёт", "form": "list"}, {"title": "Что просим у правления", "form": "list"}]}
SLIDES = {
    "Выручка выросла на 18%": {"title": "Выручка выросла на 18%", "lead": "Выручка за квартал выросла до 412 млн ₽ — на 18% больше, чем во втором квартале.",
                               "numbers": [{"value": "412 млн ₽", "label": "выручка за квартал"}, {"value": "1 240", "label": "корпоративных клиентов"}]},
    "Клиенты довольны больше": {"title": "Клиенты довольны больше", "lead": "Индекс NPS вырос с 31 до 44 за три квартала.",
                                "points": ["Срок подключения сократился с 14 до 5 дней.", "Отток клиентов за квартал составил 7,5%."]},
    "Команда растёт": {"title": "Команда растёт", "lead": "В отделе продаж 46 человек.", "points": ["За квартал наняли 12 сотрудников, из них 5 — в Казани."]},
    "Что просим у правления": {"title": "Что просим у правления", "lead": "Нанять 8 инженеров поддержки для ночной смены, чтобы снизить отток.",
                               "points": ["Довести выручку до 450 млн ₽ в четвёртом квартале."]},
}


def _run(ref, brief_text: str, mode=None, **kw):
    skills = _Skills({"topic_reference": {"kind": "other", "titles": ["X"]}, "topic_planner": PLAN,
                      "topic_slide_writer": lambda v: SLIDES[v["title"]], "topic_fact_check": {"issues": []}})
    events: list = []
    mode = mode or writer_mode(Brief(text=brief_text))
    res = T.write_topic_deck(Brief(text=brief_text, slide_count=5), mode, skills, _Providers(), progress=events.append,
                             config={"reference": {"enabled": True, "contact": "test@example.com"}}, knowledge=ref, **kw)
    return res, skills, [e["message"] for e in events]


def test_a_short_request_is_written_from_the_knowledge_base_with_a_source_for_every_fact(ref):
    res, skills, msgs = _run(ref, "Итоги квартала нашего отдела продаж для правления")
    assert res.status == "written", (res.reason, res.warnings)
    names = [c[0] for c in skills.calls]
    assert "topic_reference" not in names  # no Wikipedia: the base is the source (and «нашего» is no longer private)
    plan_vars = next(v for n, v in skills.calls if n == "topic_planner")
    assert plan_vars["source"] == "kb" and "412 млн ₽" in plan_vars["reference"] and plan_vars["reference_title"] == "Квартал отдела продаж"
    slide_vars = next(v for n, v in skills.calls if n == "topic_slide_writer" and v["title"] == "Клиенты довольны больше")
    assert slide_vars["source"] == "kb" and "[«Клиенты и отзывы», раздел «Удовлетворённость»" in slide_vars["reference"]
    check_vars = next(v for n, v in skills.calls if n == "topic_fact_check")
    assert check_vars["source"] == "kb"
    # a figure no document states («отток 7,5%»: the base says 2,1%) leaves the deck
    assert "7,5%" not in res.text and any("7.5" in x.get("why", "") for x in res.removed)
    assert "412 млн ₽" in res.text and "NPS вырос с 31 до 44" in res.text
    by = {x["text"]: x for x in res.sources}
    nps = next(x for t, x in by.items() if "NPS" in t)
    assert nps["page"] == "Клиенты и отзывы" and nps["place"] == "раздел «Удовлетворённость», абз. 3"
    team = next(x for t, x in by.items() if "46 человек" in t)
    assert team["page"] == "Команда и найм"
    assert res.basis == "kb" and res.checked == "knowledge" and res.kb["name"] == "Квартал отдела продаж"
    assert {p["title"] for p in res.pages_used} >= {"Клиенты и отзывы", "Команда и найм", "Итоги третьего квартала 2026"}
    line = attribution(res)
    assert line.startswith("Текст написан агентом Verstka по базе знаний «Квартал отдела продаж» по документам") and "в заметках слайда" in line
    assert any(m.startswith("Беру факты из базы знаний «Квартал отдела продаж»: 4 документа") for m in msgs), msgs
    assert any("убрал 1 утверждение, цифр которых в документах нет" in m for m in msgs), msgs
    rec = res.record()
    assert rec["knowledge"]["name"] == "Квартал отдела продаж" and rec["basis"] == "kb"


def test_a_base_that_does_not_know_the_topic_leaves_it_to_the_open_sources(ref):
    skills = _Skills({"topic_reference": {"kind": "science", "titles": []}, "topic_planner": PLAN,
                      "topic_slide_writer": lambda v: SLIDES[v["title"]], "topic_fact_check": {"issues": []}})
    events: list = []
    res = T.write_topic_deck(Brief(text="Расскажи про фотосинтез", slide_count=5), writer_mode(Brief(text="Расскажи про фотосинтез")), skills, _Providers(),
                             progress=events.append, config={"reference": {"enabled": False}}, knowledge=ref)
    assert res.basis == "wikipedia" and res.kb is None
    assert any("нет ничего о теме" in e["message"] for e in events)
    assert "topic_reference" in [n for n, _ in skills.calls]


def test_a_plan_without_figures_is_written_from_the_base_item_by_item(ref):
    text = "Итоги квартала для правления\n\n1. Как выросла выручка — покажи на графике\n2. Что думают клиенты\n3. Команда и найм\n4. Что просим у правления\n"
    off = writer_mode(Brief(text=text))
    assert off.kind == "off"
    mode = T.kb_plan_mode(Brief(text=text), off)
    assert mode.kind == "topic" and mode.reason == "kb_plan" and len(mode.plan) == 4
    assert mode.plan[0].startswith("Как выросла выручка")
    res, skills, _ = _run(ref, text, mode=mode)
    plan_vars = next(v for n, v in skills.calls if n == "topic_planner")
    assert plan_vars["plan_items"] == mode.plan and plan_vars["slides"] == 4
    # a plan full of the person's own figures is material: it stays as written
    material = "Итоги\n\n1. Выручка 412 млн ₽ (+18%)\n2. Клиенты 1 240, NPS 44\n3. Отток 2,1%, найм 12 человек\n"
    assert T.kb_plan_mode(Brief(text=material), writer_mode(Brief(text=material))).kind == "off"


def test_each_slide_notes_name_the_sources_of_its_facts(ref):
    from verstka.pipeline.generate import _mark_written
    from verstka.schemas.outline import DeckOutline

    res, _, _ = _run(ref, "Итоги квартала нашего отдела продаж для правления")
    o = DeckOutline.model_validate({"title": "Итоги", "slides": [
        {"id": "s1", "kind": "title", "headline": "Итоги третьего квартала"},
        {"id": "s2", "kind": "bullets", "headline": "Клиенты довольны больше", "content": {"bullets": ["Индекс NPS вырос с 31 до 44 за три квартала", "Срок подключения сократился с 14 до 5 дней"]}},
        {"id": "s3", "kind": "bullets", "headline": "Команда растёт", "content": {"bullets": ["В отделе продаж 46 человек"]}},
    ]})
    got = _mark_written(o, res)
    assert "по базе знаний «Квартал отдела продаж»" in got.slides[0].notes
    assert "Источник" in got.slides[1].notes and "«Клиенты и отзывы», раздел «Удовлетворённость», абз. 3" in got.slides[1].notes
    assert "«Команда и найм»" in got.slides[2].notes
    from verstka.api.app import _notes_sources

    assert _notes_sources(got, 3).startswith("Источник: «Команда и найм»")
