"""Жюри 20.10 (финальная ночь): данные «меньше — лучше», обложка без служебных слов, хвост «Остальные N» и один вид
справочника в любом режиме, числа без смысла крупно.

Фикстура — набор «поддержка/SLA» жюри (`tests/fixtures/support_sla`): время решения по линиям против цели SLA (у
времени меньше — лучше: уложилась только Первая линия), каналы с «%» в шапке, отрезанным запятой, обращения по месяцам."""

from __future__ import annotations

from pathlib import Path

import pytest

from verstka.data.intent import GoalReading, read_goals
from verstka.data.plan import plan_datasets
from verstka.data.polarity import lower_better, name_direction, target_direction, text_direction
from verstka.data.readers import read_file
from verstka.data.story import build_data_story, clean_deck_title, met_claim_problem
from verstka.data.verify import verify
from verstka.schemas.data import HeadlineFact, Table

ROOT = Path(__file__).resolve().parents[2]
SLA = ROOT / "tests" / "fixtures" / "support_sla"
SALES = ROOT / "examples" / "data-sales-2026"
SCIENCE = ROOT / "examples" / "data-science-2026"


def _lines() -> list[Table]:
    return read_file(SLA / "Линии поддержки.csv")


def _met_plan(q: str):
    t = _lines()
    r = read_goals(q, t, reading=GoalReading.model_validate(
        {"goals": [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Среднее время решения", "ask": "meet"}],
         "unanswerable": []}))
    assert r.understood and r.understood[0].ask == "met"
    return plan_datasets(t, q, goals=r.goals)[0], t[0]


# ── направление «лучше» ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,unit,lower", [
    ("Среднее время решения", "ч", True), ("Время ответа", "мин", True), ("Срок поставки", "дн.", True),
    ("Затраты на привлечение", "млн ₽", True), ("Ошибки 5xx", None, True), ("Отток", "%", True),
    ("Жалобы", None, True), ("Расход топлива", "л/100 км", True), ("Отчислено студентов", "чел.", True),
    ("Выручка", "млн ₽", False), ("NPS", None, False), ("Доставлено вовремя", "%", False),
    ("Решено в первый день", "%", False), ("Доступность", "%", False),
])
def test_the_meaning_of_a_measure_says_which_way_is_better(name, unit, lower):
    assert name_direction(name, unit) is lower


def test_the_authors_words_and_the_target_column_come_first():
    assert text_direction("цель SLA — не более 6 часов") is True
    assert text_direction("цель SLA — максимум часов, меньше — лучше") is True
    assert text_direction("уложились ли линии в SLA") is None  # «уложиться» — в цель, в какую сторону ни было бы
    assert text_direction("целевое ≤ 6 ч") is True
    assert text_direction("план — не менее 80%") is False
    assert text_direction("сравни линии с целью SLA") is None
    assert target_direction("Максимум, ч") is True and target_direction("Не менее, %") is False
    assert target_direction("Цель SLA, мин") is None  # «мин» — минуты, не «минимум»
    # слова автора сильнее смысла колонки
    assert lower_better("Выручка", "млн ₽", text="не более 100 млн ₽") == (True, "brief")
    assert lower_better("Среднее время решения", "ч", target_name="Цель SLA") == (True, "name")
    assert lower_better("Продажи", None) == (False, "name")


# ── «кто выполнил цель» у времени ─────────────────────────────────────────────────────────────────────────────────
def test_lines_against_sla_time_met_only_by_the_first_line():
    p, t = _met_plan("где проседаем: сравни линии с целью SLA")
    h = p.headline.replace(" ", " ")
    assert h.startswith("В пределах цели SLA — 1 из 4: Первая линия"), h
    assert "План выполнили 3" not in h and "Вторая" not in h
    cap = (p.caption or "").replace(" ", " ")
    assert cap.startswith("Выше цели SLA — Вторая линия") and "9,6 ч (цель — 6 ч)" in cap and "Первая" not in cap


def test_the_authors_saying_rules_the_direction():
    p, _ = _met_plan("какие линии уложились в цель — не более заданных часов")
    assert p.headline.startswith("В пределах цели SLA — 1 из 4")
    p, _ = _met_plan("какие линии уложились в SLA")
    assert p.headline.startswith("В пределах цели SLA — 1 из 4")


def test_revenue_plan_still_met_when_fact_is_not_below_plan():
    t = Table(id="st", file="Станции.csv", kind="csv", columns=["Станция", "Выработка", "План"], units=[None, "МВт·ч", "МВт·ч"],
              raw_header=["Станция", "Выработка, МВт·ч", "План, МВт·ч"],
              rows=[["Нива", 80, 100], ["Заря", 120, 100], ["Луч", 105, 100], ["Степь", 90, 100]])
    q = "какие станции выполнили план по выработке"
    r = read_goals(q, [t], reading=GoalReading.model_validate(
        {"goals": [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Выработка", "ask": "meet"}], "unanswerable": []}))
    p = plan_datasets([t], q, goals=r.goals)[0]
    assert p.headline.startswith("План выполнили 2 из 4: Заря и Луч"), p.headline
    assert "Нива" in (p.caption or "")


def test_verify_catches_a_target_counted_the_wrong_way():
    t = _lines()[0]
    jf, jt = t.columns.index("Среднее время решения"), t.columns.index("Цель SLA")
    # «факт не ниже цели» у времени — перевёрнуто: 3 «выполнили»
    wrong = {"op": "rows_gt", "a": jf, "b": jt, "ge": True, "skip": [],
             "met": {"fact": jf, "target": jt, "lower": False, "src": "default"}}
    f = HeadlineFact(id="rows_hit", text="3 из 4", value=3, kind="count")
    v = verify(t, [f], {"rows_hit": wrong}, "План выполнили 3 из 4", None)
    assert "rows_hit" in v.failed and "направление" in v.failed["rows_hit"] and not v.headline_ok
    # верное направление — подтверждается
    right = {**wrong, "a": jt, "b": jf, "met": {**wrong["met"], "lower": True, "src": "name"}}
    of = HeadlineFact(id="rows_of", text="из 4", value=4, kind="count")
    v = verify(t, [HeadlineFact(id="rows_hit", text="1 из 4", value=1, kind="count"), of],
               {"rows_hit": right, "rows_of": {"op": "count", "what": "value", "value": 4}}, "В пределах цели SLA — 1 из 4", None)
    assert v.ok == {"rows_hit", "rows_of"} and v.headline_ok
    # «больше — лучше» по слову автора — его право
    said = {**wrong, "met": {**wrong["met"], "src": "brief"}}
    assert "rows_hit" in verify(t, [f], {"rows_hit": said}, "3 из 4", None).ok


def test_an_edit_cannot_bring_the_wrong_conclusion_back():
    """«Этот слайд переделай полностью» (жюри 20.10): ни прежний ложный вывод, ни ложь модели «Первая линия не
    выполнила план» не проходят правило текста слайда с данными."""
    from verstka.data.story import data_text_ok, slide_for

    p, t = _met_plan("где проседаем: сравни линии с целью SLA")
    s = slide_for(p, t, slide_id="d1")
    assert data_text_ok(p.headline, s)
    assert met_claim_problem("План выполнили 3 из 4: Вторая линия, Третья линия (инженеры) и Биллинг", s)
    assert met_claim_problem("Первая линия не выполнила план", s)
    assert not data_text_ok("Не выполнили — Первая линия", s)
    assert met_claim_problem("Не уложились в SLA Вторая линия и Биллинг", s) is None


def test_rules_without_a_model_say_the_same():
    p = plan_datasets(_lines(), "где проседаем: сравни линии с целью SLA")[0]
    assert p.headline.startswith("Выше цели SLA — 3 из 4: Вторая линия"), p.headline


# ── обложка ───────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,title,aud", [
    ("Закрытие 3 квартала по службе поддержки — , слайдов 8–10", "Закрытие 3 квартала по службе поддержки", None),
    ("Закрытие 3 квартала по службе поддержки — для операционного директора, слайдов 8–10",
     "Закрытие 3 квартала по службе поддержки", "операционного директора"),
    ("Итоги 2026 года — университет, для учёного совета", "Итоги 2026 года — университет", "учёного совета"),
    ("Нужна презентация про итоги года, 10 слайдов", "Итоги года", None),
    ("Итоги продаж — 8 слайдов, в стиле VK", "Итоги продаж", None),
])
def test_deck_title_keeps_the_topic_only(raw, title, aud):
    assert clean_deck_title(raw) == (title, aud)


def _files(folder: Path) -> list[Table]:
    out: list[Table] = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in (".csv", ".xlsx", ".json", ".txt") and not f.name.startswith("SCENARIO"):
            out += read_file(f)
    return out


def test_plan_cover_is_the_topic_with_whom_it_is_for():
    st = build_data_story((ROOT / "tests" / "fixtures" / "support_sla_plan.md").read_text(encoding="utf-8"), _files(SLA))
    o = st.outline
    cover = o.slides[0]
    assert (o.title, cover.headline) == ("Закрытие 3 квартала по службе поддержки",) * 2
    assert cover.subtitle == "Для операционного директора" == o.subtitle
    assert "слайд" not in o.title and ".csv" not in (cover.subtitle or "") and "Доля обращений" not in (cover.subtitle or "")


def test_data_without_text_is_titled_by_what_it_is_about():
    st = build_data_story(None, _files(SCIENCE))
    o = st.outline
    assert o.slides[0].headline == "Итоги 2026 года — университет" and o.slides[0].subtitle == "Для учёного совета"
    assert "ещё" not in o.title
    st = build_data_story(None, _files(SALES))
    assert st.outline.slides[0].headline.startswith("Итоги III квартала 2026 года")


# ── хвост и один вид ──────────────────────────────────────────────────────────────────────────────────────────────
def test_clients_are_one_table_with_and_without_the_model():
    t = read_file(SALES / "Клиенты.xlsx")
    q = "Кто главные клиенты"
    r = read_goals(q, t, reading=GoalReading.model_validate(
        {"goals": [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Выручка", "dimension": "Клиент", "ask": "max"}],
         "unanswerable": []}))
    with_model = plan_datasets(t, q, goals=r.goals)[0]
    rules = plan_datasets(t, q)[0]
    for p in (with_model, rules):
        assert p.task.task == "reference" and p.options[p.chosen].kind == "table"
        assert p.headline.startswith("Топ-10 клиентов дают 38%")
    assert with_model.task.goal == "кто главные клиенты"


def test_an_incommensurable_tail_is_a_caption_not_a_bar():
    rows = [[f"Магазин {k:02d}", v] for k, v in enumerate([300, 250, 220] + [40] * 27, start=1)]
    t = Table(id="sh", file="Магазины.csv", kind="csv", columns=["Магазин", "Выручка"], units=[None, "млн ₽"],
              raw_header=["Магазин", "Выручка, млн ₽"], rows=rows)
    p = plan_datasets([t], "сравни магазины по выручке на графике")[0]
    assert p.options[p.chosen].kind in ("bar", "column")
    from verstka.data.story import slide_for

    s = slide_for(p, t, slide_id="d1")
    ch = s.content.chart
    assert ch is not None and not any(str(c).startswith("Остальные") for c in ch.categories), ch.categories
    cap = (p.caption or "").replace(" ", " ")
    assert "Остальные 19" in cap and "760 млн ₽" in cap and "на графике их нет" in cap, cap


# ── единица в шапке и числа без смысла ────────────────────────────────────────────────────────────────────────────
def test_a_unit_cut_off_by_a_comma_in_the_header_is_glued_back():
    t = read_file(SLA / "Каналы.csv")[0]
    assert t.columns == ["Канал", "Доля обращений Q3 2026"] and t.units == [None, "%"]


def test_no_bare_count_as_a_key_figure():
    st = build_data_story((ROOT / "tests" / "fixtures" / "support_sla_plan.md").read_text(encoding="utf-8"), _files(SLA))
    for s in st.outline.slides:
        for n in s.content.numbers:
            assert n.value.strip() not in ("3", "4", "1"), (s.id, n.value, n.label)


def test_why_says_the_target_is_on_the_chart():
    """«Почему так» (жюри, раунд 2): цель строки — второй ряд графика, а не «одна величина; «Цель SLA» — в таблице»."""
    p = plan_datasets(_lines(), "")[0]
    why = " ".join(p.options[p.chosen].reasons)
    assert "Цель SLA" in why and "одна величина" not in why


# ── жюри, раунд 3 (R25, исследование рынка) ───────────────────────────────────────────────────────────────────────
MARKET = ROOT / "tests" / "fixtures" / "market"


def test_market_research_answers_where_to_grow_with_checked_figures():
    st = build_data_story((ROOT / "tests" / "fixtures" / "market_plan.md").read_text(encoding="utf-8"), _files(MARKET))
    o = st.outline
    texts = " ‖ ".join([s.headline or "" for s in o.slides] + [f"{n.value} · {n.label}" for s in o.slides for n in s.content.numbers])
    assert "в раз" not in texts and "+5" not in texts, texts  # кратность — «в 5 раз», не «+5» под обрубком
    kf = next((s for s in o.slides if s.id == "key-figures"), None)
    if kf is not None:
        assert any(n.value == "в 5 раз" for n in kf.content.numbers)
        assert all(n.label != "Сегменты" for n in kf.content.numbers)  # «+41%» назван тем, что растёт: PaaS
        assert "paaS" not in kf.headline
    end = next(s for s in o.slides if s.id == "summary")
    assert end.headline == "Где расти: PaaS — +41%, быстрее всех" and end.section == "Выводы"
    assert not any((s.headline or "") == "Выводы" for s in o.slides)  # строка плана без ответа — не слайд
    assert o.slides[0].subtitle == "Для стратегической сессии"


def test_fastest_over_two_period_columns_shows_the_segments():
    """Модель поняла «какие сегменты растут быстрее всего» как динамику: над двумя колонками-периодами это ряд итога из
    двух точек без сегментов — вид сравнения: сегменты рядом по годам (жюри R25, раунд 3)."""
    from verstka.data.story import slide_for

    t = read_file(MARKET / "Сегменты.csv")
    q = "Какие сегменты растут быстрее всего"
    r = read_goals(q, t, reading=GoalReading.model_validate({"goals": [
        {"span": q, "dataset": "d1", "task": "dynamics", "metric": "2025", "dimension": "Сегмент", "ask": "fastest"}],
        "unanswerable": []}))
    p = plan_datasets(t, q, goals=r.goals)[0]
    ch = slide_for(p, t[0], slide_id="d").content.chart
    assert p.task.task == "comparison" and ch.categories == ["IaaS", "SaaS", "PaaS"] and len(ch.series) == 2
    assert p.headline.startswith("PaaS растёт быстрее всех: +41%")


def test_a_firm_ok_noun_keeps_its_vowel():
    from verstka.data.words import phrase

    assert phrase("Игрок").low.dat_pl == "игрокам" and phrase("Звонок").low.dat_pl == "звонкам"
