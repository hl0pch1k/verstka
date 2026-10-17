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


def test_a_table_is_a_block_of_its_own_and_never_a_headline():
    """qa5 06 s4/s12: таблица сразу под списком читалась строками списка — «| Малый бизнес | 610 | 49,2 % |» стал
    заголовком слайда. Таблица — отдельный блок, анализатор видит её таблицей."""
    from verstka.planning.brief_structure import read_structure

    plan = T.TopicPlan(title="Итоги", slides=[{"title": "Клиенты по сегментам", "form": "table"}])
    s = T.TopicSlide(title="Клиенты по сегментам", lead="Малый бизнес — крупнейший сегмент.", points=["Всего 1 240 клиентов."],
                     table={"header": ["Сегмент", "Клиенты"], "rows": [["Малый бизнес", "610"], ["Средние | крупные", "630"]]})
    text = T.render_text(plan, [s])
    assert "- Всего 1 240 клиентов.\n\n| Сегмент | Клиенты |" in text and "Средние / крупные" in text and "\n\n\n" not in text
    spec = read_structure(text).specs[-1]
    assert not spec.title.startswith("|")
    assert "|" not in " ".join(spec.title.split())


def test_the_deck_from_documents_ends_with_its_conclusion_and_says_each_fact_once():
    plan = T.TopicPlan(title="Итоги", facts=["x"], slides=[{"title": "Выручка"}, {"title": "Инвестиции и команда"}])
    assert T.kb_final(plan) and plan.slides[-1].title == "Выводы и что предлагаем"
    assert not T.kb_final(plan)  # (a closing slide already)
    mixed = T.TopicPlan(title="Итоги", facts=["x"], slides=[{"title": "Выручка"}, {"title": "Инвестиции и выводы", "must": [1]}])
    assert T.kb_final(mixed) and [s.title for s in mixed.slides] == ["Выручка", "Инвестиции", "Выводы и что предлагаем"]
    assert mixed.slides[1].must == [1]  # the topic keeps its facts
    slides = [
        T.TopicSlide(title="Клиенты", lead="На 30 сентября у платформы 1 240 корпоративных клиентов.", points=["Средний чек — 110 тыс. ₽ в квартал."]),
        T.TopicSlide(title="Цели", lead="К 2027 году — 3 000 клиентов.", points=["На 30 сентября у платформы 1 240 корпоративных клиентов.", "Офисы окупаются за 18 месяцев."],
                     timeline=[{"when": "2026", "what": "Открыт офис в Казани"}, {"when": "2026", "what": "Планируются офисы в Екатеринбурге"},
                               {"when": "1 квартал 2027", "what": "Запуск в Казахстане"}]),
    ]
    done = T.kb_tidy(slides)
    assert slides[1].timeline == [] and "2026 — Открыт офис в Казани." in slides[1].points  # one bare year twice: a list
    assert "На 30 сентября у платформы 1 240 корпоративных клиентов." not in slides[1].points  # said on the slide before
    assert {d["kind"] for d in done} == {"timeline_to_points", "repeat"}
    risk = [T.TopicSlide(title="Риски", lead="Главный риск — цены.")]
    put = T.cover_facts(T.TopicPlan(facts=["Рост цен на оборудование может снизить маржу на 3 п.п."], slides=[{"title": "Риски", "must": [1]}]), risk)
    assert put and risk[0].points == ["Рост цен на оборудование может снизить маржу на 3 п.п."]  # one stop, never «п.п..»


def test_a_fact_lives_where_it_is_the_lead_and_the_closing_slide_concludes():
    slides = [
        T.TopicSlide(title="Выручка", lead="Выручка за третий квартал 2026 года — 412 млн ₽, на 18% больше, чем во втором.",
                     takeaway="Рост на 18% подтверждает устойчивую динамику в 2026 году."),
        T.TopicSlide(title="Планы на четвёртый квартал", lead="В четвёртом квартале — выйти на рынок Казахстана и довести выручку до 450 млн ₽.",
                     points=["Первый зарубежный рынок — Казахстан: запуск в первом квартале 2027 года, партнёр — местный интегратор."],
                     takeaway="План создаёт базу для целевых 3 000 клиентов и 2,4 млрд ₽ выручки к концу 2027 года."),
        T.TopicSlide(title="Цели на 2027 год", lead="К концу 2027 года — 3 000 корпоративных клиентов и 2,4 млрд ₽ выручки в год.",
                     takeaway="Цели требуют роста клиентской базы в 2,4 раза."),
        T.TopicSlide(title="Зарубежные рынки", lead="Первый зарубежный рынок — Казахстан: запуск в первом квартале 2027 года с местным интегратором.",
                     takeaway="Партнёрство с местным интегратором обеспечивает запуск в Казахстане в первом квартале 2027 года."),
        T.TopicSlide(title="Выводы и что просим", lead="Просим утвердить найм 8 инженеров поддержки.",
                     points=["В отделе продаж работают 30 менеджеров, 9 инженеров предпродажи и 7 руководителей.",
                             "Ключевой риск: рост цен на оборудование может снизить маржу на 3 п.п."]),
    ]
    done = T.kb_tidy(slides)
    kinds = [d["kind"] for d in done]
    assert slides[1].points == []  # Kazakhstan is the lead of «Зарубежные рынки»
    assert slides[1].takeaway == ""  # 3 000 and 2,4 млрд are the figures of «Цели», not of this slide
    assert slides[3].takeaway == ""  # the takeaway repeats the lead
    assert slides[0].takeaway  # its own figures (and a year) stay
    shares = [T.TopicSlide(title="Инвестиции", lead="В 2027 году — 240 млн ₽ в дата-центры, 150 млн ₽ в разработку, 90 млн ₽ в продажи.",
                           takeaway="Половина бюджета (50 %) идёт в дата-центры."),
              T.TopicSlide(title="Тариф «Старт»", lead="Тариф «Старт» — для компаний до 50 сотрудников.")]
    T.kb_tidy(shares)
    assert shares[0].takeaway  # a derived share, not the «50 сотрудников» of another slide
    goals = [T.TopicSlide(title="Цели", lead="К концу 2027 года — 3 000 корпоративных клиентов и 2,4 млрд ₽ выручки в год.",
                          points=["Целевой показатель по выручке — 2,4 млрд ₽ в год.", "Каждый офис окупается за 18 месяцев."])]
    T.kb_tidy(goals)
    assert goals[0].points == ["Каждый офис окупается за 18 месяцев."]  # the lead's figure again in fewer words goes
    close = slides[-1].points
    assert not any("30 менеджеров" in p for p in close)  # a new fact on the closing slide: no conclusion, no ask
    assert any("риск" in p for p in close) and any("18%" in p for p in close)  # the asks stay, the conclusions come
    assert {"repeat", "repeat_takeaway", "closing_new_fact", "closing_conclusions"} <= set(kinds)


def test_a_table_fragment_reaches_the_writer_as_a_table(ref):
    got = ref.relevant("выручка и клиенты по кварталам", 3000)
    assert "| Квартал | Выручка, млн ₽ | Клиенты |" in got and "|---|---|---|" in got


def test_a_fact_check_correction_the_documents_do_not_back_is_not_applied(ref):
    slides = [
        T.TopicSlide(title="Тариф «Старт»", lead="Тариф «Старт» для компаний до 50 сотрудников: подключение за 1 день с оплатой картой."),
        T.TopicSlide(title="Планы", lead="В четвёртом квартале 2026 года — выйти на рынок Казахстана и довести выручку до 450 млн ₽."),
        T.TopicSlide(title="Выручка", lead="Выручка за третий квартал выросла до 500 млн ₽."),
    ]
    issues = [
        T.FactIssue(id="s2.lead", problem="wrong time", fix="Тариф «Старт» для компаний до 50 сотрудников: подключение за 5 дней с оплатой картой."),
        T.FactIssue(id="s3.lead", problem="wrong quarter", fix="В первом квартале 2027 года — выйти на рынок Казахстана и довести выручку до 450 млн ₽."),
        T.FactIssue(id="s4.lead", problem="wrong figure", fix="Выручка за третий квартал выросла до 412 млн ₽."),
    ]
    kept = T.kb_weigh_fixes(slides, issues, ref)
    assert [it.id for it in kept] == ["s4.lead"]  # the right correction stays, the two that break a true statement go
    T.apply_fixes(slides, kept)
    assert "1 день" in slides[0].lead and "четвёртом квартале 2026" in slides[1].lead and "412 млн ₽" in slides[2].lead


def test_the_authors_words_of_a_list_line_come_without_its_marker():
    from verstka.planning.proportions import authors_words

    text = "Слайд 4. Структура\nНа 30 сентября у платформы 1 240 клиентов.\n- Малый бизнес формирует крупнейший сегмент клиентской базы, насчитывая 610 компаний.\n"
    got = authors_words("Малый бизнес — крупнейший сегмент клиентской базы: 610 из 1 240", text)
    assert got == "Малый бизнес формирует крупнейший сегмент клиентской базы, насчитывая 610 компаний"  # never «- Малый…» as a headline
    assert authors_words("Иван продал 30% акций", "Иван продал 30% акций компании.") == "Иван продал 30% акций компании"


def test_documents_that_ask_nothing_close_without_an_invented_request(ref):
    assert not T.kb_asks("Презентация для совета директоров: итоги 3 квартала и планы на 2027 год.", ref)
    assert T.kb_asks("Итоги квартала. Просим утвердить бюджет.", ref)
    plan = T.TopicPlan(title="Итоги", facts=["x"], slides=[{"title": "Выручка"}, {"title": "Выводы и что просим"}])
    assert not T.kb_final(plan, asks=False) and plan.slides[-1].title == T.KB_ASKLESS_TITLE
    slides = [
        T.TopicSlide(title="NPS", lead="Индекс NPS вырос с 31 до 44 за счёт сокращения срока подключения.", takeaway="Клиенты довольны быстрым подключением."),
        T.TopicSlide(title="Достижения", lead="Запущен тариф «Старт».",
                     points=["Сокращение срока подключения стало главной причиной роста индекса NPS с 31 в первом квартале до 44 в третьем."]),
        T.TopicSlide(title="Выводы и что просим", lead="Рост квартала устойчив. Совету директоров предлагается утвердить найм 8 инженеров поддержки.",
                     points=["В четвёртом квартале планируется нанять 8 инженеров поддержки для ночной смены.", "Просим одобрить бюджет 2027 года."],
                     takeaway="Утверждение найма снизит отток."),
    ]
    done = T.kb_tidy(slides, asks=False)
    assert slides[1].points == []  # «NPS 31 → 44» is the lead of the slide before (qa6 10 s5/s6)
    close = slides[-1]
    assert close.title == T.KB_ASKLESS_TITLE and close.lead == "Рост квартала устойчив." and close.takeaway == ""
    assert "В четвёртом квартале планируется нанять 8 инженеров поддержки для ночной смены." in close.points  # the documents' plan stays
    assert not any("одобрить" in p for p in close.points)
    assert sum(d["kind"] == "closing_invented_ask" for d in done) == 3
    # the closing states conclusions: no table of its own, no advice the documents do not give (live qa6 10)
    tail = [T.TopicSlide(title="Риски", lead="Рост цен на оборудование может снизить маржу на 3 п.п.",
                         takeaway="Снижение маржи потребует пересмотра ценовой политики."),
            T.TopicSlide(title="Выводы и планы", points=["Выход в Казахстан запланирован на первый квартал 2027 года."],
                         table={"header": ["Направление", "Сумма"], "rows": [["Дата-центры", "240"]]})]
    T.kb_tidy(tail, asks=False)
    assert tail[-1].table is None and not any("ценовой" in p for p in tail[-1].points)
