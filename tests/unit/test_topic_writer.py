"""Writer mode v2 (verstka/planning/topic_writer.py) — a short request («Сделай презентацию про интегралы») becomes a
full deck text: the topic's subject, the plan's must-know facts, slides in their forms, formulas typeset as LaTeX
with their explanations in words, the fact check's corrections — and the text reads back as a deck whose formula
slides are formulas, their explanation and the line they follow (planning/compile.py `_math_slide`)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from verstka.planning import topic_writer as T
from verstka.planning.writer import WriterMode
from verstka.schemas.outline import Brief


def test_the_subject_of_a_short_request():
    assert T.topic_subject("Сделай презентацию про вторую мировую войну") == "вторую мировую войну"
    assert T.topic_subject("сделай презентаицю про интегралы") == "интегралы"
    assert T.topic_subject("Подготовь презентацию на тему «Фотосинтез»") == "Фотосинтез"


def test_latex_the_model_wrote_with_single_backslashes_is_repaired():
    # a JSON escape the model wrote single: «\frac» read as a form feed, «\neq» as a new line, «\times» as a tab
    s = T.TopicSlide.model_validate({"title": "x", "formula": "$\x0crac{a}{b} \neq \times c$", "formulas": [
        {"name": "Аддитивность", "latex": "\\\\int_a^b f\\,dx", "note": "интеграл; по частям"}, "Линейность: \\int (f + g)\\,dx = \\int f\\,dx + \\int g\\,dx"]})
    assert s.formula == "\\frac{a}{b} \\neq \\times c"
    assert s.formulas[0].latex == "\\int_a^b f\\,dx" and s.formulas[0].note == "интеграл, по частям"
    assert s.formulas[1].name == "Линейность" and s.formulas[1].latex.startswith("\\int (f + g)")


def test_formulas_that_cannot_be_typeset_are_read_again_or_leave():
    s = T.TopicSlide.model_validate({"title": "x", "formula": "∫[a,b] f(x)dx = F(b) − F(a)", "formulas": [{"name": "Плохая", "latex": "\\badcmd{x}"}, {"name": "Хорошая", "latex": "E = mc^2"}]})
    dropped = T.check_formulas([s])
    assert s.formula == "\\int _{a}^{b} f(x)\\,dx = F(b) - F(a)"
    assert [f.name for f in s.formulas] == ["Хорошая"] and dropped == [{"slide": 2, "formula": "Плохая: \\badcmd{x}"}]


def test_a_slide_of_formulas_is_written_with_their_explanations():
    s = T.TopicSlide.model_validate({"title": "Таблица интегралов", "lead": "Их читают по таблице производных.", "formulas": [
        {"name": "Степенная функция", "latex": "\\int x^n\\,dx = \\frac{x^{n+1}}{n+1} + C", "note": "показатель растёт на единицу"},
        {"name": "Экспонента", "latex": "\\int e^x\\,dx = e^x + C", "note": "экспонента равна своей первообразной"}], "points": ["dx показывает переменную интегрирования"]})
    lines = T.render_slide(3, s, "Таблица")
    assert lines[1] == "Слайд 3. Таблица интегралов"
    assert "- dx показывает переменную интегрирования." in lines  # a symbol keeps its case
    f = next(x for x in lines if x.startswith("Формулы: "))
    assert f == ("Формулы: Степенная функция: $\\int x^n\\,dx = \\frac{x^{n+1}}{n+1} + C$ — показатель растёт на единицу; "
                 "Экспонента: $\\int e^x\\,dx = e^x + C$ — экспонента равна своей первообразной")
    from verstka.rendering.equation import formulas_of

    got = formulas_of(f.split(": ", 1)[1])
    assert [(x.label, x.note) for x in got] == [("Степенная функция", "Показатель растёт на единицу"), ("Экспонента", "Экспонента равна своей первообразной")]
    one = T.TopicSlide.model_validate({"title": "Ньютон — Лейбниц", "formula": "\\int_a^b f(x)\\,dx = F(b) - F(a)", "formula_note": "интеграл равен приращению первообразной"})
    assert "Формула: $\\int_a^b f(x)\\,dx = F(b) - F(a)$ — интеграл равен приращению первообразной" in T.render_slide(4, one, "x")


def test_the_fact_check_corrects_a_formula_and_keeps_its_explanation():
    s = T.TopicSlide.model_validate({"title": "x", "formulas": [{"name": "Ньютон — Лейбниц", "latex": "\\int_a^b f\\,dx = F(a) - F(b)", "note": "приращение первообразной"}],
                                     "formula": "", "points": ["Лейбниц опубликовал работу в 1686 году"]})
    st = {x["id"]: x["text"] for x in T.statements([s])}
    assert st["s2.m1"] == "Ньютон — Лейбниц: \\int_a^b f\\,dx = F(a) - F(b) — приращение первообразной"
    done = T.apply_fixes([s], [T.FactIssue(id="s2.m1", problem="знак", fix="Ньютон — Лейбниц: \\int_a^b f\\,dx = F(b) - F(a) — приращение первообразной"),
                               T.FactIssue(id="s2.p1", problem="год", fix="")])
    assert s.formulas[0].latex == "\\int_a^b f\\,dx = F(b) - F(a)" and s.formulas[0].note == "приращение первообразной"
    assert s.points == [] and len(done) == 2


def test_a_formula_fact_on_a_slide_of_formulas_is_never_put_back_as_a_line():
    plan = T.TopicPlan.model_validate({"title": "Интеграл", "facts": ["Формула Ньютона — Лейбница: ∫ₐᵇ f(x) dx = F(b) − F(a)"], "slides": [{"title": "Формула", "form": "formula", "must": [1]}]})
    s = T.TopicSlide.model_validate({"title": "Формула", "formula": "\\int_a^b f(x)\\,dx = F(b) - F(a)"})
    assert T.cover_facts(plan, [s]) == [] and s.points == []


# ------------------------------------------------------------------ the phase end to end, with scripted answers


class _Skills:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[str] = []

    def get(self, name):
        return SimpleNamespace(version="1.1.0", sha256="0" * 64)

    def run(self, name, providers, variables, images=None):
        self.calls.append(name)
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


def test_a_math_topic_becomes_a_deck_of_formulas_with_their_explanations():
    plan = {"title": "Интеграл", "subtitle": "Определение, свойства, примеры", "kind": "math",
            "facts": ["Знак ∫ ввёл Лейбниц в 1686 году", "Неопределённый интеграл — множество первообразных"],
            "slides": [{"title": "История", "form": "timeline", "must": [1]}, {"title": "Неопределённый интеграл", "form": "formula", "must": [2]},
                       {"title": "Свойства", "form": "formulas"}, {"title": "Пример", "form": "example"}]}
    slides = {
        "История": {"title": "История", "lead": "Интеграл создали Ньютон и Лейбниц.", "timeline": [{"when": "1686", "what": "Знак ∫ ввёл Лейбниц"}, {"when": "1823", "what": "Коши даёт строгое определение"}]},
        "Неопределённый интеграл": {"title": "Неопределённый интеграл", "lead": "Неопределённый интеграл — множество первообразных функции.",
                                    "formula": "\\int f(x)\\,dx = F(x) + C", "formula_note": "интегрирование восстанавливает функцию по производной", "points": ["C — произвольная постоянная"]},
        "Свойства": {"title": "Свойства", "lead": "Интеграл линеен.", "formulas": [{"name": "Линейность", "latex": "\\int (f + g)\\,dx = \\int f\\,dx + \\int g\\,dx", "note": "интеграл суммы равен сумме интегралов"}]},
        "Пример": {"title": "Пример", "lead": "Найдём площадь под параболой y = x² на отрезке [0; 2].", "formulas": [
            {"name": "Первообразная", "latex": "F(x) = \\frac{x^3}{3}", "note": "по таблице интегралов"}, {"name": "Ответ", "latex": "F(2) - F(0) = \\frac{8}{3}", "note": "разность значений на концах"}],
                   "takeaway": "Площадь равна 8/3."},
    }
    skills = _Skills({
        "topic_reference": {"kind": "math", "titles": []},
        "topic_planner": plan,
        "topic_slide_writer": lambda v: slides[v["title"]],
        "topic_fact_check": {"issues": []},
    })
    events: list = []
    res = T.write_topic_deck(Brief(text="сделай презентаицю про интегралы", slide_count=5), WriterMode(kind="topic", topic="сделай презентаицю про интегралы"),
                             skills, _Providers(), progress=events.append, config={"reference": {"enabled": False}})
    assert res.status == "written", (res.status, res.reason, res.warnings)
    text = res.text
    assert "Формула: $\\int f(x)\\,dx = F(x) + C$ — интегрирование восстанавливает функцию по производной" in text
    assert "Формулы: Первообразная: $F(x) = \\frac{x^3}{3}$ — по таблице интегралов; Ответ: $F(2) - F(0) = \\frac{8}{3}$ — разность значений на концах" in text
    assert skills.calls.count("topic_slide_writer") == 4 and "topic_fact_check" in skills.calls
    msgs = [e["message"] for e in events]
    assert any(m.startswith("Составил план: 4 слайда, 2 ключевых факта, формы — хронология, формулы, разборы примеров") for m in msgs), msgs

    # the text read back: the formula slides are their formulas, the line they follow and their explanation
    from verstka.planning.agent import run_agent
    from verstka.planning.compile import compile_outline  # noqa: F401 - the compiler that shapes them must import

    st = __import__("verstka.planning.brief_structure", fromlist=["read_structure"]).read_structure(res.brief.text)
    ex = next(sp for sp in st.specs if sp.title == "Пример")
    from verstka.rendering.equation import formulas_of

    assert [f.label for f in formulas_of(ex.formula)] == ["Первообразная", "Ответ"]


def test_the_compiler_shapes_a_slide_of_formulas(tmp_path):
    from verstka.planning.compile import _math_slide
    from verstka.schemas.brief_structure import SlideSpec
    from verstka.schemas.common import PatternKind as K
    from verstka.schemas.outline import OutlineSlide, SlideContent, SlideItem

    spec = SlideSpec(number=4, title="Пример", text="Найдём площадь под параболой y = x² на отрезке [0; 2].\nФормулы: Первообразная: $F(x) = \\frac{x^3}{3}$ — по таблице интегралов\nВывод: Площадь равна 8/3.",
                     formula="Первообразная: $F(x) = \\frac{x^3}{3}$ — по таблице интегралов")
    s = OutlineSlide(id="s4", kind=K.cards, headline="Пример", subtitle="Найдём площадь под параболой y = x² на отрезке [0; 2]",
                     content=SlideContent(formula="F(x) = x³/3", items=[SlideItem(title="Шаг", text="x")],
                                          bullets=["Формулы: Первообразная: $F(x) = \\frac{x^3}{3}$", "Найдём площадь под параболой y = x² на отрезке [0; 2]", "По таблице интегралов"]))
    said: list = []
    _math_slide(s, spec, SimpleNamespace(say=lambda m, sl=None: said.append(m)))
    c = s.content
    assert c.formula == spec.formula and not c.items and s.kind == K.bullets
    assert c.paragraphs == ["Найдём площадь под параболой y = x² на отрезке [0; 2]."] and s.subtitle is None
    assert c.bullets == []  # the formula once more, the lead once more and the formula's own explanation: never a line
    assert said and "набрана как математическ" in said[0]


def test_a_slide_of_formulas_keeps_its_form_and_no_slide_shows_raw_latex():
    from verstka.planning.compile import _no_raw_latex, _pinned
    from verstka.schemas.brief_structure import SlideSpec
    from verstka.schemas.common import PatternKind as K
    from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent, SlideItem

    assert _pinned(SlideSpec(number=3, formula="$E = mc^2$"))  # the variety pass never turns it into cards
    assert not _pinned(SlideSpec(number=3, formula="100 × 300 × 30 = 900 000 рублей"))
    s = OutlineSlide(id="s", kind=K.cards, headline="Кратные интегралы", subtitle="Формула: $\\iint_D f(x, y)\\,dx\\,dy$ — объём",
                     content=SlideContent(formula="$\\iint_D f\\,dx\\,dy$", bullets=["Выручка $5 млн и $3 млн"], items=[SlideItem(title="$\\int_a^b f\\,dx$", text="площадь")]))
    o = DeckOutline(title="t", slides=[s])
    _no_raw_latex(o)
    assert s.subtitle == "Формула: ∬_Df(x, y) dx dy — объём" and s.content.items[0].title == "∫ₐᵇf dx"
    assert s.content.formula == "$\\iint_D f\\,dx\\,dy$" and s.content.bullets == ["Выручка $5 млн и $3 млн"]


def test_a_timeline_reads_in_time_order():
    s = T.TopicSlide.model_validate({"title": "История", "timeline": [{"when": "1638", "what": "Галилей"}, {"when": "1687", "what": "«Начала»"}, {"when": "1680-е", "what": "Ньютон и Лейбниц"}, {"when": "1744", "what": "Эйлер"}]})
    T.order_timelines([s])
    assert [e.when for e in s.timeline] == ["1638", "1680-е", "1687", "1744"]


def test_a_correction_about_another_statement_is_not_applied():
    # live 2026-10-08: the checker mixed up the numbers and «corrected» a line on Pearl Harbor with an event of the
    # timeline («9 декабря 1941 — Китай объявил войну Японии»)
    s = T.TopicSlide.model_validate({"title": "Тихий океан", "points": ["В нападении на Перл-Харбор участвовало 353 самолёта с шести авианосцев."],
                                     "timeline": [{"when": "1675", "what": "Ньютон и Лейбниц опубликовали первые работы"}]})
    skipped: list = []
    done = T.apply_fixes([s], [T.FactIssue(id="s2.p1", problem="?", fix="9 декабря 1941 — Китай объявил войну Японии"),
                               T.FactIssue(id="s2.t1", problem="год", fix="1684 — Лейбниц опубликовал первую работу")], skipped)
    assert s.points == ["В нападении на Перл-Харбор участвовало 353 самолёта с шести авианосцев."]
    assert s.timeline[0].when == "1684" and len(done) == 1 and [x["id"] for x in skipped] == ["s2.p1"]


def test_the_graph_of_a_function_is_no_chart_request():
    from verstka.planning.brief_structure import _chart_requests

    assert not _chart_requests("Определённый интеграл равен площади криволинейной трапеции, ограниченной графиком функции f(x), осью абсцисс.")
    assert _chart_requests("Нужен линейный график выручки по месяцам.")
