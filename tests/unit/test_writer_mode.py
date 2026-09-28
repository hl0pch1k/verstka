"""Writer mode (planning/writer.py, WRITER_SPEC §12.1): which texts are topics, the written text as the analyst reads it,
the deterministic clean-up, salvage and continuation, the checks against the reference (deletion only), the living
politician's biography, the storylines, the writer's statuses, and the rules fallback on a written text. Offline: the
answers are the ones Qwen3-32B gave in the probes (tests/fixtures/writer)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from verstka.planning import agent as A
from verstka.planning import writer as W
from verstka.planning.brief import parse_brief_text
from verstka.planning.brief_structure import read_structure
from verstka.providers.base import ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.agent import SlideDesignAnswer
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import Brief
from verstka.schemas.writer import WriterAnswer
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
F = ROOT / "tests" / "fixtures" / "writer"
REF = json.loads((F / "answers_ref.json").read_text(encoding="utf-8"))
MODEL = json.loads((F / "answers_model.json").read_text(encoding="utf-8"))
SKILLS = SkillsRegistry.load()
OFFLINE = {"reference": {"enabled": False}}  # no Wikipedia request in these tests


def _answer(raw: str) -> WriterAnswer:
    a, _ = W.parse_answer(raw)
    assert a is not None
    return a


def _deck(key: str, src: dict = REF, reference: bool = True):
    d = src[key]
    return W.normalise_answer(_answer(d["raw"]), d["topic"], d.get("reference", "") if reference else "")


# ------------------------------------------------------------------ T1: when writer mode starts


TOPICS = [
    "презентация про вторую мировую войну",
    "История VK",
    "Рынок электромобилей в России",
    "Квантовые компьютеры: как они работают и зачем нужны бизнесу",
    "Сделай презентацию на 10 слайдов про историю космонавтики",
    "Как работает фотосинтез — для школьников 7 класса",
    "презентация про президента российской федерации владимира путина",
    "итоги пилота умные сводки за второй квартал",
]
OLD_PLACEHOLDER = (
    "Например: итоги пилота «Умные сводки» за квартал.\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\n"
    "Результаты: время сократилось до 29 минут, NPS 64. Просим: бюджет 14,5 млн ₽ на масштабирование."
)


@pytest.mark.parametrize("text", TOPICS)
def test_a_topic_goes_to_the_writer(text):
    m = W.writer_mode(Brief(text=text, slide_count=10))
    assert m.kind == "topic", (text, m.reason)
    assert not m.private_hint and m.topic == " ".join(text.split())


def test_our_own_subject_is_a_topic_with_the_private_hint():
    m = W.writer_mode("итоги работы нашего отдела продаж за третий квартал")
    assert m.kind == "topic" and m.private_hint


def test_a_topic_with_statements_keeps_them_word_for_word():
    m = W.writer_mode("Презентация про наш сервис Verstka. Он собирает презентацию за 5 минут. Даёт 3 варианта на выбор.")
    assert m.kind == "expand" and m.private_hint
    assert m.theses == ["Он собирает презентацию за 5 минут.", "Даёт 3 варианта на выбор."]


def _sample_brief() -> str:
    src = (ROOT / "web/src/components/NewGenerationFormParts.tsx").read_text(encoding="utf-8")
    return re.search(r"export const SAMPLE_BRIEF = `(.*?)`", src, re.S).group(1)


@pytest.mark.parametrize("path", sorted((ROOT / "tests/fixtures/briefs").glob("*.md")) + sorted((ROOT / "examples/briefs").glob("*.md")), ids=lambda p: p.stem)
def test_every_brief_with_material_stays_faithful(path):
    m = W.writer_mode(parse_brief_text(path.read_text(encoding="utf-8")))
    assert m.kind == "off", (path.name, m.reason)


@pytest.mark.parametrize("text", [OLD_PLACEHOLDER, "SAMPLE"])
def test_the_create_screens_examples_stay_faithful(text):
    text = _sample_brief() if text == "SAMPLE" else text
    assert W.writer_mode(text).kind == "off"


def test_only_my_text_switches_the_writer_off():
    m = W.writer_mode("Расскажи о Python только по моему тексту: это язык программирования.")
    assert m.kind == "off" and m.reason == "no_write"
    assert W.writer_mode("Про Python, ничего не придумывай").kind == "off"


def test_years_and_the_slide_count_are_not_figures():
    assert W.writer_mode("История космонавтики 1957–1969 годов на 10 слайдов").kind == "topic"
    assert W.writer_mode("Итоги: выручка 900 тысяч, 120 клиентов, 35 сотрудников").reason.startswith("figures:")


def test_the_web_mirror_names_the_server_rules():
    ts = (ROOT / "web/src/lib/writerMode.ts").read_text(encoding="utf-8")
    assert "planning/writer.py" in ts
    assert "MAX_FIGURES = 2" in ts and "MAX_SENTENCES = 5" in ts and f"MAX_WORDS = {W.MAX_WORDS}" in ts
    assert "writerMode.ts" in (ROOT / "verstka/planning/writer.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------ T2: the written text reads back


def test_render_reads_back_as_a_brief():
    deck = _deck("ww2s")
    text = W.render_text(deck, rules=True)
    st = read_structure(text)
    # gate 2 W6: the rules line is the agent's, never in the text the person sees («Показать текст», writer.md)
    # (round 4: the person's text writes the chart request and the caveat as data notes; with_rules gives the brief back)
    assert W.RULES_LINE not in W.render_text(deck) and W.with_rules(W.render_text(deck)) == W.render_text(deck, rules=True)
    assert W.with_rules(W.render_text(deck)) == text and W.with_rules(text) == text and W.with_rules("Кофейня: выручка 900 000 рублей.") == "Кофейня: выручка 900 000 рублей."
    assert len(st.specs) == len(deck.slides) + 1
    assert st.specs[0].title == "Титульный" and st.title == deck.title and st.subtitle
    assert st.rules == ["Тон нейтральный, энциклопедический.", "Заголовки — факты из текста, без оценок."]
    tl = next(s for s in st.specs if s.items)
    assert len(tl.items) == 6 and tl.items[0].title == "1 сентября 1939 года" and tl.items[0].text == "Германия вторгается в Польшу"
    assert all(it.text[:1].isupper() for it in tl.items)  # «Германия», never «германия»
    assert len(st.series) == 1 and st.series[0].values[:1] == [27.0]
    data_spec = next(s for s in st.specs if s.series_ids)
    assert data_spec.charts and data_spec.charts[0].type == "column" and data_spec.series_ids == [st.series[0].id]
    assert data_spec.footnote == "Данные приблизительные"
    assert "— США — 0,4." in text  # a decimal with a comma, the last row with a full stop


def test_the_chart_words_follow_the_chart_type():
    deck = W._Deck(title="Рынок", subtitle="", slides=[W._Slide(title="Продажи", sentences=["Продажи росли."], data={"caption": "Продажи", "unit": "тыс. штук", "chart": "line", "rows": [{"label": "2021", "value": 1.0}, {"label": "2022", "value": 2.5}, {"label": "2023", "value": 4.0}]})])
    text = W.render_text(deck, rules=True)
    assert "Нужна линейная диаграмма: продажи." in text and "— 2022 — 2,5;" in text and "— 2023 — 4." in text
    assert "Диаграмма (линейная): продажи." in W.render_text(deck)  # the person's text: a data note (gate 3 W3-12)


# ------------------------------------------------------------------ T3: the deterministic clean-up


def test_normalise_drops_junk_filler_and_bad_structures():
    a = WriterAnswer.model_validate({
        "status": "ok", "kind": "history", "title": "Тема", "subtitle": "",
        "slides": [
            {"title": "Слайд 2. Начало (timeline)", "text": "Германия напала на Польшу 1 сентября 1939 года. Это событие играет важную роль в истории. Он служил в elementGuidId.",
             "timeline": [{"when": "1939", "what": "Начало .ll войны"}, {"when": "1940", "what": "Франция капитулирует"}, {"when": "1941", "what": "Нападение на СССР"}, {"when": "1945", "what": "Капитуляция Германии"}, {"when": "без даты", "what": "что-то"}],
             "data": {"caption": "Смешанные", "rows": [{"label": "2020", "value": 1}, {"label": "СССР", "value": 2}, {"label": "2022", "value": 3}]}},
            {"title": "Рост", "text": "Продажи росли.", "data": {"caption": "Продажи", "chart": "line", "rows": [{"label": "Январь", "value": 1}, {"label": "Февраль", "value": 2}, {"label": "Март", "value": 3}]}},
            {"title": "Доли", "text": "Доли рынка.", "data": {"caption": "Доли", "unit": "%", "chart": "pie", "rows": ["Ромашка — 20", "Лютик — 30", "Василёк — 10"]}},
            {"title": "Ещё", "text": "", "timeline": ["1950 — Событие один", "1951 — Событие два", "1952 — Событие три"]},
            {"title": "И ещё", "text": "", "timeline": ["1960 — Событие один", "1961 — Событие два", "1962 — Событие три", "1963 — Событие четыре"]},
            {"title": "Пусто", "text": ""},
        ],
    })
    removed: list[dict] = []
    d = W.normalise_answer(a, "тема", "", removed=removed)
    s1 = d.slides[0]
    assert s1.title == "Начало"
    assert s1.sentences == ["Германия напала на Польшу 1 сентября 1939 года."]
    assert [e["what"] for e in s1.timeline] == ["Франция капитулирует", "Нападение на СССР", "Капитуляция Германии"]
    assert s1.data is None  # years mixed with countries
    assert d.slides[1].data["chart"] == "column"  # a line needs years in order
    assert d.slides[2].data["chart"] == "column" and len(d.slides[2].data["rows"]) == 3  # rows as strings parsed; 60 ≠ 100
    assert sum(1 for s in d.slides if s.timeline) == 2  # the two longest timelines stay
    assert all(s.title != "Пусто" for s in d.slides)
    whys = " ".join(r["why"] for r in removed)
    assert "filler" in whys and "latin" in whys and "junk timeline" in whys


def test_normalise_keeps_every_thesis_of_the_user():
    a = _answer(REF["vk"]["raw"])
    thesis = "Сервис придумали студенты из Петербурга."
    d = W.normalise_answer(a, "История VK", REF["vk"]["reference"], theses=[thesis])
    assert any(thesis in s.sentences and thesis in s.theses for s in d.slides)


def test_a_working_title_gives_way_to_the_charts_caption():
    a = WriterAnswer.model_validate({"slides": [{"title": "В цифрах (data)", "text": "Потери велики.", "data": {"caption": "Потери по странам", "unit": "млн человек", "rows": [{"label": "СССР", "value": 27}, {"label": "Китай", "value": 20}, {"label": "Германия", "value": 7}]}}]})
    d = W.normalise_answer(a, "война", "")
    assert d.slides[0].title == "Потери по странам"


def test_a_column_chart_is_ordered_by_value():
    rows = [{"label": "Германия", "value": 5}, {"label": "СССР", "value": 27}, {"label": "Китай", "value": 20}]
    assert [r["label"] for r in W._data_ok({"caption": "x", "rows": rows})["rows"]] == ["СССР", "Китай", "Германия"]
    years = [{"label": "2023", "value": 5}, {"label": "2021", "value": 27}, {"label": "2022", "value": 20}]
    assert [r["label"] for r in W._data_ok({"caption": "x", "rows": years})["rows"]] == ["2023", "2021", "2022"]


def test_every_recorded_answer_parses():
    for key, d in {**REF, **MODEL}.items():
        a, _ = W.parse_answer(d["raw"])
        assert a is not None, key
        if key == "priv":
            assert a.status == "private"
        else:
            assert a.status == "ok" and len(a.slides) >= 5, key


# ------------------------------------------------------------------ T4: salvage and the continuation


def _registry(fn) -> ProviderRegistry:
    model = MockProvider(fn, model="Qwen/Qwen3-32B")
    return ProviderRegistry(roles={"llm": model}, limits=ProviderLimits(max_concurrency=2, time_budget_s=210))


def test_a_cut_answer_keeps_its_complete_slides():
    a, salvaged = W.parse_answer((F / "raw_cut.txt").read_text(encoding="utf-8"))
    assert salvaged and a is not None and len(a.slides) >= 4
    assert a.title == "Президент Российской Федерации Владимир Путин"
    assert all("elementGuidId" not in s.text for s in a.slides)


def _slide(title: str, *sentences: str) -> dict:
    return {"title": title, "text": " ".join(sentences), "timeline": None, "data": None}


def test_a_short_answer_is_continued(monkeypatch):
    first = {"status": "ok", "kind": "science", "title": "Фотосинтез", "subtitle": "Как растения получают энергию", "slides": [
        _slide("Что такое фотосинтез", "Фотосинтез — процесс образования органических веществ на свету.", "Он идёт в хлоропластах."),
        _slide("Как устроен лист", "В листе есть хлоропласты с хлорофиллом.", "Хлорофилл поглощает свет."),
    ]}
    more = {"status": "ok", "title": "", "subtitle": "", "slides": [
        _slide("Световая фаза", "На свету вода расщепляется и выделяется кислород."),
        _slide("Темновая фаза", "Углекислый газ превращается в глюкозу."),
        _slide("Главное", "Фотосинтез даёт кислород и органические вещества."),
    ]}
    seen: list[str] = []

    def fake(messages):
        user = messages[-1].content
        seen.append(user)
        return more if "The deck is already written up to slide" in user else first

    res = W.write_deck(Brief(text="Как работает фотосинтез", slide_count=6), W.writer_mode("Как работает фотосинтез"), SKILLS, _registry(fake), config={**OFFLINE, "check": {"enabled": False}})
    assert res.status == "written" and res.continuation
    assert res.slides == 5 and res.brief.slide_count == 6
    cont = next(x for x in seen if "The deck is already written up to slide" in x)
    assert "The deck is already written up to slide 2" in cont and "1. Что такое фотосинтез; 2. Как устроен лист" in cont
    assert "Write exactly 3 content slides" in cont
    assert any("дописал ещё 3 слайда" in x for x in res.log_lines)


def test_without_time_there_is_no_continuation():
    first = {"status": "ok", "title": "Фотосинтез", "subtitle": "", "slides": [_slide("Что такое фотосинтез", "Фотосинтез — процесс на свету."), _slide("Хлоропласты", "Процесс идёт в хлоропластах.")]}
    res = W.write_deck(Brief(text="Как работает фотосинтез", slide_count=8), W.writer_mode("Как работает фотосинтез"), SKILLS, _registry(lambda m: first),
                       config={**OFFLINE, "check": {"enabled": False}, "limits": {"writer_max_s": 34}})
    assert res.status == "written" and not res.continuation and res.slides == 2


# ------------------------------------------------------------------ T5: the figures and names against the article


@pytest.fixture(scope="module")
def ww2_full() -> str:
    return (F / "ww2_full.txt").read_text(encoding="utf-8")


def test_verify_keeps_the_articles_facts_and_drops_the_rest(ww2_full):
    deck = W._Deck(title="Вторая мировая война", slides=[W._Slide(title="Потери", sentences=[
        "Всего погибло около 27 миллионов граждан СССР.",
        "В ней погибло более 70 миллионов человек, включая 27 миллионов — граждан СССР.",
        "Война продолжалась 6 лет и 1 месяц.",
        "В войне участвовало 312 государств.",
        "Операцию возглавили генералы Зюйдвестов и Эльфенгард.",
    ])])
    removed: list[dict] = []
    W.verify_against(deck, [ww2_full], "вторая мировая война", removed)
    kept = deck.slides[0].sentences
    assert kept[:2] == ["Всего погибло около 27 миллионов граждан СССР.", "В ней погибло более 70 миллионов человек, включая 27 миллионов — граждан СССР."]
    assert "Война продолжалась 6 лет и 1 месяц." not in kept and "В войне участвовало 312 государств." not in kept
    assert not any("Зюйдвестов" in s for s in kept)
    assert {r["why"].split(":")[0] for r in removed} == {"not in the article", "names not in the article"}


def test_verify_drops_a_wrong_date_of_the_biography():
    bio = (F / "putin_bio.txt").read_text(encoding="utf-8")
    deck = W._Deck(title="Путин", slides=[W._Slide(title="Приход к власти", sentences=[
        "8 августа того же года он был назначен председателем правительства.",
        "Владимир Путин родился 7 октября 1952 года в Ленинграде.",
    ], theses={"Тезис пользователя про 1234 год."})])
    deck.slides[0].sentences.append("Тезис пользователя про 1234 год.")
    W.verify_against(deck, [bio], "Путин")
    assert deck.slides[0].sentences == ["Владимир Путин родился 7 октября 1952 года в Ленинграде.", "Тезис пользователя про 1234 год."]


def test_verify_checks_the_timeline_and_the_rows(ww2_full):
    deck = _deck("ww2s")
    removed: list[dict] = []
    W.verify_against(deck, [ww2_full], REF["ww2s"]["topic"], removed)
    assert any(s.timeline for s in deck.slides)
    # the chart's rows: the article gives the USSR's 27 млн, not «Китай — 20», «Япония — 3», «США — 0,4» (their values
    # stand in the article next to other things) — 2 rows left, no chart
    unlabelled = {r["text"].split(": ", 1)[1].split(" — ")[0] for r in removed if r["why"] == "not in the article next to its label"}
    assert unlabelled == {"Китай", "Япония", "США"} and not any(s.data for s in deck.slides)
    assert len(removed) <= 4


# ------------------------------------------------------------------ T5b: the storylines


@pytest.mark.parametrize("kind", sorted(W.STORYLINES))
@pytest.mark.parametrize("n", [5, 6, 8, 10, 12, 20])
def test_storyline(kind, n):
    parts = W.storyline_parts(kind, n - 1, reference=True)
    want = min(n - 1, W.POLITICIAN_MAX_CONTENT) if kind == "politician" else n - 1
    assert len(parts) == want
    short = want <= W.SHORT_DECK_CONTENT
    if kind == "history" and short:
        # gate 2 W5: a short history is a story — causes → start → course → turning points → end → outcome → after
        assert parts[-1].title in ("Последствия", "Итоги и последствия") and parts[0].title == "Предпосылки и причины"
        assert all(p.hint for p in parts)
    else:
        assert parts[-1].title == "Главное"
    if kind in ("history", "person", "politician", "company") and n - 1 >= 5:
        # a deck of ≤ 10 slides has no separate chronology: its narrative slides carry the dates
        assert any(p.timeline for p in parts) == (not short)
    titles = [p.title for p in parts]
    assert len(set(titles)) == len(titles)
    assert not any("сторона темы" in t.lower() for t in titles)
    text = W.storyline(kind, n - 1, reference=True)
    assert text.startswith("1. ") and "(timeline)" in text or not any(p.timeline for p in parts)


def test_the_data_part_needs_a_reference_or_a_market():
    assert not any(p.data for p in W.storyline_parts("history", 9, reference=False))
    assert any(p.data for p in W.storyline_parts("history", 9, reference=True))
    assert any(p.data for p in W.storyline_parts("market", 7, reference=False))


def test_the_kind_is_guessed_without_a_model():
    assert W.guess_kind("презентация про вторую мировую войну") == "history"
    assert W.guess_kind("Рынок электромобилей в России") == "market"
    assert W.guess_kind("Как работает фотосинтез") == "science"
    assert W.guess_kind("Юрий Гагарин") == "person"


# ------------------------------------------------------------------ T6: the check deletes, never rewrites


def test_apply_check_removes_exactly_the_reported_ids():
    d = MODEL["pres3"]
    deck = W.normalise_answer(_answer(d["raw"]), d["topic"], "")
    before = {(i, j): sn for i, s in enumerate(deck.slides, 1) for j, sn in enumerate(s.sentences, 1)}
    all_text = [sn for s in deck.slides for sn in s.sentences]
    issues = d["check"] + [{"id": "99.1", "verdict": "wrong"}, {"id": "мусор", "verdict": "wrong"}]
    removed: list[dict] = []
    n = W.apply_check(deck, issues, removed)
    gone = {r["text"] for r in removed}
    for it in d["check"]:
        m = re.match(r"^(\d+)\.(\d+)$", it["id"])
        if m and (int(m.group(1)), int(m.group(2))) in before:
            assert before[(int(m.group(1)), int(m.group(2)))] in gone
    after = [sn for s in deck.slides for sn in s.sentences]
    assert set(after) <= set(all_text)  # no sentence was rewritten
    assert n == len(removed) and len(after) == len(all_text) - sum(1 for r in removed if "." in r["where"] and "t" not in r["where"] and "d" not in r["where"])


def test_apply_check_ignores_the_users_theses():
    deck = W._Deck(slides=[W._Slide(title="A", sentences=["Мой тезис.", "Факт."], theses={"Мой тезис."})])
    W.apply_check(deck, [{"id": "1.1", "verdict": "doubtful", "problem": "not in the reference"}, {"id": "1.2", "verdict": "wrong", "problem": "another year"}])
    assert deck.slides[0].sentences == ["Мой тезис."]


# ------------------------------------------------------------------ T7: a living politician — the biography only


def test_the_politician_guard_keeps_the_biography():
    deck = _deck("pres")
    titles = [s.title for s in deck.slides]
    bio = {t: list(s.sentences) for t, s in zip(titles, deck.slides)}
    removed: list[dict] = []
    n = W.guard_politician(deck, removed)
    left = [s.title for s in deck.slides]
    assert n >= 5
    assert not any(re.search("политик", t, re.I) for t in left)
    for t in titles[:6]:
        assert t in left and next(s for s in deck.slides if s.title == t).sentences == bio[t]
    text = " ".join(sn for s in deck.slides for sn in s.sentences)
    assert not re.search(r"ПАСЕ|Парламентская ассамблея|Крым|ордер|агресси|вторжени", text)


def test_the_guard_leaves_history_alone():
    d = REF["ww2s"]
    res = W.write_deck(Brief(text=d["topic"], slide_count=10), W.writer_mode(d["topic"]), SKILLS, _reg_answers(json.loads(d["raw"])), config=OFFLINE)
    assert res.written and res.kind == "history"
    assert "вторглась в СССР" in res.text  # the politician lexicon is not applied
    # a 10-slide history has no separate chronology: its narrative slides carry the dates (gate 2 W5)
    assert "Хронология" not in res.text and any("short deck" in r["why"] for r in res.removed)
    assert not any("politician" in r["why"] for r in res.removed)


# ------------------------------------------------------------------ T10: the writer's statuses


def _reg_answers(writer, check=None, reference=None):
    def fake(messages):
        system = messages[0].content
        if "You name encyclopedia articles" in system:
            if isinstance(reference, Exception):
                raise reference
            return reference or {"titles": [], "kind": "other"}
        if "fact-checker" in system:
            return check or {"issues": []}
        if isinstance(writer, Exception):
            raise writer
        return writer

    return _registry(fake)


def test_private_topic():
    res = W.write_deck(Brief(text="итоги работы нашего отдела продаж за третий квартал", slide_count=8), W.writer_mode("итоги работы нашего отдела продаж за третий квартал"), SKILLS, _reg_answers({"status": "private"}), config=OFFLINE)
    assert res.status == "private" and not res.written and res.brief is None
    assert any("private" in w for w in res.warnings)


def test_refused_topic():
    res = W.write_deck(Brief(text="тема", slide_count=8), W.writer_mode("Текущий вооружённый конфликт"), SKILLS, _reg_answers({"status": "refuse"}), config=OFFLINE)
    assert res.status == "refused" and not res.written


def test_a_conflict_named_by_the_reference_step_is_refused_before_writing():
    reg = _reg_answers({"status": "ok", "slides": []}, reference={"titles": ["Конфликт"], "kind": "conflict"})
    res = W.write_deck(Brief(text="тема", slide_count=8), W.writer_mode("Вооружённый конфликт"), SKILLS, reg, config={"reference": {"enabled": True, "contact": "https://example.org"}})
    assert res.status == "refused" and "answers" in res.record() and not res.answers.get("writer")


def test_a_model_error_is_a_failure_with_the_providers_reason():
    res = W.write_deck(Brief(text="История VK", slide_count=8), W.writer_mode("История VK"), SKILLS, _reg_answers(ProviderError("rate limit (429)")), config=OFFLINE)
    assert res.status == "failed" and any(w.startswith("deck_writer failed: rate limit") for w in res.warnings)
    from verstka.api.model_status import _PLANNER_STEP

    assert any(_PLANNER_STEP.search(w) for w in res.warnings)


def test_no_time_no_writer():
    import time

    res = W.write_deck(Brief(text="История VK", slide_count=8), W.writer_mode("История VK"), SKILLS, _reg_answers({"status": "ok"}), config=OFFLINE, budget_end=time.monotonic() + 100)
    assert res.status == "skipped" and res.reason == "no_time"


def test_a_written_deck_is_a_brief_with_the_cover_and_the_attribution():
    d = MODEL["photo"]
    res = W.write_deck(Brief(text=d["topic"], slide_count=6, audience="школьники", purpose="product"), W.writer_mode(d["topic"]), SKILLS, _reg_answers(json.loads(d["raw"])), config=OFFLINE)
    assert res.written and res.brief.text.startswith("Слайд 1. Титульный") and res.brief.slide_count == res.slides + 1
    assert res.brief.purpose == "other" and res.brief.audience == "школьники"
    assert res.checked == "model" and res.log_lines[0].startswith("Автор: пишу текст по теме")
    line = W.attribution(res)
    assert "по теме «Как работает фотосинтез»" in line and not re.search(r"\d", line)
    meta = res.meta()
    assert meta["status"] == "written" and meta["text"] == res.text and meta["slides"] == res.slides + 1 and meta["source"] is None
    rec = res.record()
    assert rec["skills"]["deck_writer"]["version"] == "2.0.0" and rec["answers"]["writer"]


def test_the_config_switches(monkeypatch):
    monkeypatch.setenv("VERSTKA_WIKI", "0")
    monkeypatch.setenv("VERSTKA_WRITER", "0")
    cfg = W.load_config()
    assert cfg["reference"]["enabled"] is False and cfg["enabled"] is False
    monkeypatch.delenv("VERSTKA_WIKI")
    monkeypatch.delenv("VERSTKA_WRITER")
    cfg = W.load_config()
    assert cfg["enabled"] is True and cfg["reference"]["contact"]


# ------------------------------------------------------------------ T12 / T13: the written text without a designer


def _written_ctx():
    text = W.render_text(_deck("ww2s"))
    brief = parse_brief_text(text)
    st = read_structure(text)
    ctx = A._build_ctx(brief, st, A._resolve_facts(None, brief, [], st), None)
    ctx.written = True
    return ctx


def test_rules_make_the_dated_list_a_timeline_and_never_a_year_a_key_figure():
    ctx = _written_ctx()
    units = A._units_from_specs(ctx)
    kinds = {}
    for u in units:
        d = A.rules_design(u, ctx)
        kinds[u.title] = d.slide.kind
        for n in d.slide.content.numbers or []:
            assert not re.fullmatch(r"\d{4}(?:\s*[–—-]\s*\d{4})?(?:\s*г\.?)?", (n.value or "").strip()), (u.title, n)
        if u.title == "Хронология":
            assert d.slide.kind == K.timeline and len(d.slide.content.items) == 6
            assert d.slide.content.items[0].title == "1 сентября 1939 года"


def test_a_timeline_answer_without_items_takes_the_slides_list():
    ctx = _written_ctx()
    unit = next(u for u in A._units_from_specs(ctx) if u.title == "Хронология")
    ans = SlideDesignAnswer.model_validate({"kind": "timeline", "headline": "Главные даты войны", "items": []})
    d = A.design_from_answer(ans, unit, ctx)
    assert d is not None and d.slide.kind == K.timeline and len(d.slide.content.items) == 6
    assert d.slide.content.items[0].text == "Германия вторгается в Польшу"


def test_words_given_as_key_figures_become_lines():
    ctx = _written_ctx()
    unit = next(u for u in A._units_from_specs(ctx) if u.title == "Хронология")
    ans = SlideDesignAnswer.model_validate({"kind": "stat_row", "headline": "Рынок остаётся небольшим", "numbers": [
        {"value": "1939", "label": "начало войны"}, {"value": "Высокая стоимость", "label": "Электромобили"}, {"value": "Низкие эксплуатационные расходы", "label": ""}]})
    d = A.design_from_answer(ans, unit, ctx)
    assert d is not None
    assert all(re.search(r"\d", n.value) for n in d.slide.content.numbers)
    assert "Электромобили: высокая стоимость" in d.slide.content.bullets and "Низкие эксплуатационные расходы" in d.slide.content.bullets


def test_a_slide_never_opens_with_a_pronoun_left_without_its_subject():
    deck = W._Deck(slides=[
        W._Slide(title="Главное", sentences=["Он происходит в хлоропластах листьев.", "В ходе фотосинтеза выделяется кислород."]),
        W._Slide(title="Этапы", sentences=["Фотосинтез идёт в две стадии.", "Она начинается на свету."]),
        W._Slide(title="Тезис", sentences=["Он мой тезис."], theses={"Он мой тезис."}),
    ])
    removed: list[dict] = []
    assert W.drop_orphans(deck, removed) == 1
    assert deck.slides[0].sentences == ["В ходе фотосинтеза выделяется кислород."]
    assert deck.slides[1].sentences == ["Фотосинтез идёт в две стадии.", "Она начинается на свету."]  # mid-slide: its subject is right before it
    assert deck.slides[2].sentences == ["Он мой тезис."]
    assert removed[0]["why"].startswith("no subject")


def test_an_abbreviation_does_not_end_a_sentence():
    text = "В 1979 году прошёл курсы при Высшей школе КГБ СССР им. Дзержинского. В 1990 году вернулся в Ленинград."
    assert W.sentences_of(text) == ["В 1979 году прошёл курсы при Высшей школе КГБ СССР им. Дзержинского.", "В 1990 году вернулся в Ленинград."]


def test_the_summing_up_slide_may_restate_the_facts():
    a = WriterAnswer.model_validate({"slides": [
        {"title": "Начало войны", "text": "1 сентября 1939 года Германия напала на Польшу. 3 сентября Великобритания объявила войну Германии."},
        {"title": "Итоги", "text": "1 сентября 1939 года Германия напала на Польшу. Война закончилась 2 сентября 1945 года."},
        {"title": "Главное", "text": "1 сентября 1939 года Германия напала на Польшу. Война закончилась 2 сентября 1945 года. Война закончилась 2 сентября 1945 года."},
    ]})
    d = W.normalise_answer(a, "война", "")
    assert d.slides[1].sentences == ["Война закончилась 2 сентября 1945 года."]  # «Итоги» is a content slide: its repeats go
    assert d.slides[2].sentences == ["1 сентября 1939 года Германия напала на Польшу.", "Война закончилась 2 сентября 1945 года."]


def test_a_year_is_never_a_key_figure_of_a_written_deck():
    ctx = _written_ctx()
    unit = next(u for u in A._units_from_specs(ctx) if u.title == "Хронология")
    ans = SlideDesignAnswer.model_validate({"kind": "big_number", "headline": "Путин вступил в пятый срок", "numbers": [{"value": "1999 г", "label": "последовательно занимает должности главы правительства"}]})
    d = A.design_from_answer(ans, unit, ctx)
    assert d is not None and not d.slide.content.numbers
    assert d.slide.content.bullets == ["1999 г — последовательно занимает должности главы правительства"]


# ------------------------------------------------------------------ gate 1 (27.09): the writer's own defects


def test_billions_are_not_junk():
    # G1-06: «млрд» has no vowel and is a word of every financial sentence («История VK» lost four of them)
    for sn in ["В 2019 году VK получила 87,6 млрд рублей дохода.", "Выручка составила 2 трлн рублей.", "Станция выдаёт 5 кВтч за час."]:
        assert W.junk_sentence(sn, "История VK", "ru", strict=False) is None, sn
    assert W.junk_sentence("Компания работает в elementGuidId.", "История VK", "ru", strict=False)


def test_a_one_word_piece_stays_with_its_sentence():
    # G1-07: the article writes «купила Дзен. Новости, которые…»; «Новости.» alone was left over after a removal
    assert W.sentences_of("В 2022 году компания приобрела Дзен. Новости. VK владеет «Юлой».") == [
        "В 2022 году компания приобрела Дзен. Новости.", "VK владеет «Юлой».",
    ]


def test_a_year_that_dates_a_named_thing_is_cut_and_the_sentence_stays(ww2_full):
    # G1-03 (b), (c): «договора 1919 года» — the article never writes the year: the year goes, not the sentence, and
    # the next sentence («Согласно договору, страна…») keeps its antecedent
    deck = W._Deck(slides=[W._Slide(title="Причины", sentences=[
        "Одной из причин стало недовольство Германии условиями Версальского договора 1919 года.",
        "Согласно договору, страна теряла территории и колонии.",
        "В 1919 году Германия начала войну против Японии.",
        "Это создало напряжённость.",
    ])])
    removed: list[dict] = []
    edits: list[dict] = []
    W.verify_against(deck, [ww2_full], "вторая мировая война", removed, edits=edits)
    assert deck.slides[0].sentences == [
        "Одной из причин стало недовольство Германии условиями Версальского договора.",
        "Согласно договору, страна теряла территории и колонии.",
    ]
    assert edits and edits[0]["now"].endswith("Версальского договора.")
    # an event's own date is never cut: «В 1919 году…» goes whole, and «Это…» after it goes with it
    assert [r["why"].split(":")[0] for r in removed] == ["not in the article", "no antecedent"]


def test_a_sentence_that_leans_on_a_removed_one_goes_with_it():
    deck = W._Deck(slides=[W._Slide(title="Ход", sentences=[
        "Германия завоевала Данию.", "Италия вступила в войну.", "В 1941 году она вторглась в Грецию.", "Война шла в Африке.",
    ])])
    removed: list[dict] = []
    W.apply_check(deck, [{"id": "1.2", "verdict": "wrong", "problem": "Italy entered the war in June 1940, not as told"}], removed)
    assert deck.slides[0].sentences == ["Германия завоевала Данию.", "Война шла в Африке."]
    assert removed[1]["why"].startswith("no antecedent") and removed[1]["where"] == "1.3"
    assert W.anaphoric("Согласно договору, страна теряла территории.") and W.anaphoric("Это событие считается началом войны.")
    assert not W.anaphoric("Италия присоединилась к Германии в июне 1940 года.")


# the fact check of the live WWII run 20260927-223710-b7581a (it read the 12 000-character cut only)
WW2_TEXT = {
    3: ["Германия стремительно завоевала Данию и Норвегию (апрель—июнь 1940).", "В 1941 году она вторглась в Югославию и Грецию."],
    5: ["6 июня 1944 года союзные войска высадились в Нормандии.", "8 мая 1945 года Германия капитулировала.",
        "В августе 1945 года США атаковали Японию атомными бомбами, что привело к её капитуляции 2 сентября 1945 года."],
    6: ["Во Второй мировой войне погибло более 70 миллионов человек, включая мирных жителей.", "Война затронула 61 страну и около 80 % населения Земли."],
    9: ["Вторая мировая война длилась с 1 сентября 1939 по 2 сентября 1945 года.", "Погибло более 70 миллионов человек."],
}
WW2_CHECK = [
    {"id": "3.2", "verdict": "unsupported", "problem": "does not state that Germany invaded Yugoslavia and Greece in 1941"},
    {"id": "5.3", "verdict": "unsupported", "problem": "does not mention the atomic bombings"},
    {"id": "6.1", "verdict": "unsupported", "problem": "does not explicitly include civilians"},
    {"id": "6.2", "verdict": "unsupported", "problem": "does not explicitly state 61 countries"},
    {"id": "8.d1", "verdict": "unsupported", "problem": "no figure of 20 million Chinese deaths"},
    {"id": "9.2", "verdict": "unsupported", "problem": "states 60–65 million, not more than 70 million"},
    {"id": "9.9", "verdict": "wrong"},
]


def _ww2_deck() -> "W._Deck":
    slides = []
    for i in range(1, 10):
        # the other slides: three sentences each, as a live deck has (the check reports 6 of ~24 statements)
        slides.append(W._Slide(title=f"Слайд {i}", sentences=list(WW2_TEXT.get(i, [f"Текст слайда номер {i} о войне.", f"Второе предложение слайда {i}.", f"Третье предложение слайда {i}."]))))
    slides[7].sentences = []
    slides[7].data = {"caption": "Потери по странам", "unit": "млн человек", "chart": "column", "rows": [
        {"label": "Китай", "value": 20.0}, {"label": "СССР", "value": 27.0}, {"label": "Германия", "value": 7.0}]}
    return W._Deck(title="Вторая мировая война", slides=slides)


def test_the_check_never_removes_what_the_full_article_states(ww2_full):
    # G1-03 (a): the death toll, 61 государство / 80 %, the atomic bombings, Yugoslavia 1941 are in the full article
    deck = _ww2_deck()
    removed: list[dict] = []
    overruled: list[dict] = []
    W.apply_check(deck, WW2_CHECK, removed, support=W.ArticleSupport([ww2_full], "Вторая мировая война"), overruled=overruled)
    kept = {sn for s in deck.slides for sn in s.sentences}
    for i in (3, 5, 6, 9):
        assert set(WW2_TEXT[i]) <= kept, i
    assert {o["where"] for o in overruled} == {"3.2", "5.3", "6.1", "6.2", "9.2"}
    # a data row the article does not give («Китай — 20 млн») stays removed
    assert [r["where"] for r in removed] == ["8.d1"]
    # without the article, the check's word is final (and the model-only self-check is unchanged)
    deck2 = _ww2_deck()
    W.apply_check(deck2, WW2_CHECK, [])
    assert "Погибло более 70 миллионов человек." not in {sn for s in deck2.slides for sn in s.sentences}


def test_support_needs_the_figure_next_to_the_statements_words(ww2_full):
    sup = W.ArticleSupport([ww2_full], "Вторая мировая война")
    assert sup.supported("Война затронула 61 страну и около 80 % населения Земли.")
    assert not sup.supported("Германия капитулировала 61 раз.")  # 61 is the article's, but not about capitulations
    assert not sup.supported("Операцию возглавил генерал Зюйдвестов в 1941 году.")  # a name the article never writes
    assert not sup.supported("Япония стремилась доминировать в Тихоокеанском регионе.")  # no figure: the check decides


def test_long_quotations_are_not_given_to_the_writer(ww2_full):
    # G1-12: Hitler's quoted aim («…устранение угрозы с Востока…») became «Целью было устранить угрозу со стороны СССР»
    from verstka.planning.reference import cut_reference, drop_quotations

    assert "устранение угрозы с Востока" in ww2_full
    assert "устранение угрозы с Востока" not in drop_quotations(ww2_full)
    assert "устранение угрозы с Востока" not in cut_reference(ww2_full, 60000)
    assert drop_quotations("VK владеет «Юлой» и «Дзеном». Всё.") == "VK владеет «Юлой» и «Дзеном». Всё."
    text = "Он сказал: «Мы будем расширять жизненное пространство на Восток и устраним угрозу, которая исходит от соседей». Затем началась война."
    assert drop_quotations(text).strip() == "Затем началась война."
    sk = SKILLS.build_messages("writer_check", {"topic": "т", "reference": "r", "numbered": "[1.1] x"})[0].content
    assert "paraphrase" in sk and "quotes from a participant" in sk


def test_the_chronology_tells_each_earlier_slide_once_and_the_summary_does_not_repeat_it():
    # G1-11: «Начало» (1, 3, 17 сентября 1939) was the first half of «Хронология»; «Главное» restated it
    deck = W._Deck(slides=[
        W._Slide(title="Начало", sentences=["1 сентября 1939 года Германия начала вторжение в Польшу.", "3 сентября Великобритания и Франция объявили войну Германии.", "17 сентября СССР вторгся в Польшу."]),
        W._Slide(title="Ход событий", sentences=["22 июня 1941 года Германия напала на СССР.", "7 декабря 1941 года Япония атаковала Перл-Харбор."]),
        W._Slide(title="Хронология", sentences=["Главные даты войны."], timeline=[
            {"when": "1 сентября 1939 года", "what": "Германия вторгается в Польшу"},
            {"when": "3 сентября 1939 года", "what": "Великобритания и Франция объявляют войну"},
            {"when": "17 сентября 1939 года", "what": "СССР вторгается в Польшу"},
            {"when": "22 июня 1941 года", "what": "Германия нападает на СССР"},
            {"when": "7 декабря 1941 года", "what": "Япония атакует Перл-Харбор"},
            {"when": "2 сентября 1945 года", "what": "Япония капитулирует"},
        ]),
        W._Slide(title="Главное", sentences=["Война длилась с 1 сентября 1939 по 2 сентября 1945 года.", "22 июня 1941 года Германия напала на СССР.", "Погибло более 70 миллионов человек."]),
    ])
    removed: list[dict] = []
    W.dedupe_chronology(deck, removed)
    when = [e["when"] for e in deck.slides[2].timeline]
    assert when == ["1 сентября 1939 года", "22 июня 1941 года", "7 декабря 1941 года", "2 сентября 1945 года"]
    assert deck.slides[3].sentences == ["Война длилась с 1 сентября 1939 по 2 сентября 1945 года.", "Погибло более 70 миллионов человек."]
    assert any("repeats slide 1" in r["why"] for r in removed) and any(r["why"] == "restates the chronology" for r in removed)


def test_a_company_deck_has_no_slide_about_sanctions():
    # G1-13: «VK попала под санкции ЕС» was a headline and in «Главное»; one chronology line keeps the fact
    deck = W._Deck(slides=[
        W._Slide(title="Современный этап", sentences=["В 2023 году были созданы две бизнес-группы.", "В 2026 году VK попала под санкции ЕС, а её приложения были удалены из App Store и Google Play."]),
        W._Slide(title="Хронология", sentences=[], timeline=[
            {"when": "1998 год", "what": "Основание компании"}, {"when": "2021 год", "what": "Ребрендинг в VK"},
            {"when": "2026 год", "what": "Санкции ЕС"}, {"when": "2026 год", "what": "Удаление приложений из App Store"},
        ]),
        W._Slide(title="Главное", sentences=["VK основана в 1998 году.", "В 2026 году VK попала под санкции ЕС."]),
    ])
    removed: list[dict] = []
    assert W.guard_company(deck, removed) == 3
    assert deck.slides[0].sentences == ["В 2023 году были созданы две бизнес-группы."]
    assert [e["what"] for e in deck.slides[1].timeline] == ["Основание компании", "Ребрендинг в VK", "Санкции ЕС"]
    assert deck.slides[2].sentences == ["VK основана в 1998 году."]


def test_a_topic_about_a_place_reads_that_places_sections_first():
    # G1-22: «Рынок электромобилей в России» was written from the world figures of «Электромобиль»
    from verstka.planning.reference import cut_reference, place_of

    assert place_of("Рынок электромобилей в России") == ("России", "росси")
    assert place_of("российский рынок кофе")[1] == "росси"
    assert place_of("История VK") is None and place_of("презентация про вторую мировую войну") is None
    world = "\n".join(f"Мировой факт номер {k}: в мире продано {k} млн машин, это длинное предложение о мировом рынке." for k in range(1, 60))
    art = (
        "Электромобиль — автомобиль на электродвигателе.\n\n== Рынок ==\n" + world
        + "\n\n== История ==\n" + " ".join(f"В {1830 + k} году изобретатель номер {k} построил опытный экипаж на батареях." for k in range(1, 30)) + "\n"
        + "=== В России ===\nВ начале 2000-х годов в России существовали проекты электромобилей, но они не получили развития.\n"
        + "В 2024 году в России было продано 17,8 тысячи электромобилей, по данным статистики продаж.\n"
    )
    plain = cut_reference(art, 2000, "market")
    focused = cut_reference(art, 2000, "market", "росси")
    assert "17,8 тысячи" not in plain and "17,8 тысячи" in focused and len(focused) <= 2000
    msgs = SKILLS.build_messages("deck_writer", {
        "topic": "Рынок электромобилей в России", "theses": "", "private_hint": False, "reference": "", "audience": "все", "language": "ru",
        "n_content": 7, "sentences": "4–5", "max_data": 2, "written_titles": "", "first_number": 2, "storyline": "1. Что это", "place": "России",
    })
    assert "take the facts and figures about России first" in msgs[0].content


# ------------------------------------------------------------------ gate 1: the designer's side of a written deck


def test_a_name_keeps_its_capital_after_a_date():
    # G1-05: «1937 год — япония начала войну против Китая», «1 сентября 1939 — германия начала вторжение»
    from verstka.schemas.outline import SlideItem

    text = "В Азии Япония вела войну против Китая с 1937 года. 1 сентября 1939 года Германия начала вторжение в Польшу. Германские войска наступали."
    assert A._title_text(SlideItem(title="1937 год", text="Япония начала войну против Китая"), text) == "1937 год — Япония начала войну против Китая"
    assert A._title_text(SlideItem(title="1 сентября 1939", text="Германия начала вторжение в Польшу"), text) == "1 сентября 1939 — Германия начала вторжение в Польшу"
    # a chronology's list: the name stands only after a dash inside a line
    chron = "Хронология:\n— 7 декабря 1941 года — Япония атакует Перл-Харбор;\n— 8 мая 1945 года — Германия капитулирует."
    assert A._title_text(SlideItem(title="8 мая 1945 года", text="Германия капитулирует"), chron) == "8 мая 1945 года — Германия капитулирует"
    # common words and function words still start in lowercase
    assert A._title_text(SlideItem(title="Партнёрства", text="С пятью ближайшими офисами"), "Партнёрства с пятью ближайшими офисами.") == "Партнёрства — с пятью ближайшими офисами"
    assert A._title_text(SlideItem(title="Итог", text="Высокая выручка"), "Выручка высокая.") == "Итог — высокая выручка"
    assert A._title_text(SlideItem(title="Партнёр", text="VK Tech"), "") == "Партнёр — VK Tech"


def test_polish_restores_a_names_capital_after_a_dash():
    from verstka.schemas.outline import OutlineSlide, SlideContent

    s = OutlineSlide(id="s", kind=K.bullets, headline="Ход войны", content=SlideContent(bullets=["1937 год — япония начала войну против Китая", "Май 1940 — союзники отступили"]))
    A.polish_case(s, "В Азии Япония вела войну против Китая с 1937 года. В мае 1940 года союзники отступили.")
    assert s.content.bullets == ["1937 год — Япония начала войну против Китая", "Май 1940 — союзники отступили"]


def _design(kind, headline, text="", title="Продукты и сервисы", by="model", **content):
    from verstka.schemas.outline import OutlineSlide, SlideContent

    unit = A._Unit(key="u4", title=title, text=text)
    return A._Design(unit=unit, slide=OutlineSlide(id="s4", kind=kind, headline=headline, content=SlideContent(**content)), by=by)


def test_a_headline_never_invents_a_count():
    # G1-08: «VK владеет шестью социальными сетями и пятью мессенджерами» — the text and the slide list 3 and 3
    from verstka.schemas.outline import SlideItem

    text = "VK владеет социальными сетями «ВКонтакте», «Одноклассники», «Мой мир», мессенджерами «VK Мессенджер», «ТамТам», «Max»."
    items = [SlideItem(title="Социальные сети", text="«ВКонтакте», «Одноклассники», «Мой мир»"), SlideItem(title="Мессенджеры", text="«VK Мессенджер», «ТамТам», «Max»")]
    ctx = _written_ctx()
    d = _design(K.cards, "VK владеет шестью социальными сетями и пятью мессенджерами", text, items=items)
    A.tidy_design(d, ctx)
    assert d.slide.headline == "Продукты и сервисы" and any("count the source does not" in c for c in d.changes)
    d = _design(K.cards, "VK владеет тремя социальными сетями и тремя мессенджерами", text, items=items)
    A.tidy_design(d, ctx)
    assert d.slide.headline == "VK владеет тремя социальными сетями и тремя мессенджерами"
    assert A.invented_counts("Две трети гостей берут кофе с собой", "", d.slide) == []


def test_years_are_never_a_row_of_key_figures():
    # G1-09: «1998 г / 2021 г / 2023 г / 2026 г» with labels «— основана как почтовый сервис Mail.ru»
    from verstka.schemas.outline import NumberCallout

    nums = [NumberCallout(value="1998 г", label="— основана как почтовый сервис Mail.ru"), NumberCallout(value="2021 г", label="— получено новое название"),
            NumberCallout(value="2023 г", label="— созданы две бизнес-группы")]
    # (round 4: the written check drops entries the slide's text does not tell — the text now tells all three)
    d = _design(K.stat_row, "VK получила новое название", "VK основана в 1998 году как почтовый сервис Mail.ru. В 2021 году компания "
                "получила новое название. В 2023 году были созданы две бизнес-группы.", numbers=nums)
    A.tidy_design(d, _written_ctx())
    assert d.slide.kind == K.timeline and not d.slide.content.numbers
    assert [(it.title, it.text) for it in d.slide.content.items][0] == ("1998", "Основана как почтовый сервис Mail.ru")
    from verstka.schemas.outline import OutlineSlide, SlideContent

    s = OutlineSlide(id="s", kind=K.bullets, headline="Главное", content=SlideContent(bullets=["1998 — основана как почтовый сервис", "2021 — получено новое название", "2023 — созданы две бизнес-группы"]))
    assert A.reshape(s, "stat_row") is None and A.reshape(s, "big_number") is None


def test_a_key_figures_label_says_what_its_sentence_counts():
    # G1-10: «240 млн · Прогноз продаж к 2030 году» — the text: 240 млн electric cars in the world
    from verstka.schemas.outline import NumberCallout

    text = ("Электромобили — это перспективное направление. В России в первом квартале 2025 года было продано 1854 электромобиля. "
            "Прогнозируется, что к 2030 году в мире будет около 240 млн электромобилей.")
    d = _design(K.big_number, "Продажи электромобилей в России: 1854 шт. в I квартале 2025 года", text, title="Главное",
                numbers=[NumberCallout(value="240 млн", label="Прогноз продаж к 2030 году")])
    A.tidy_design(d, _written_ctx())
    n = d.slide.content.numbers[0]
    assert n.value == "240 млн" and "продаж" not in n.label.lower() and "электромобилей" in n.label and "в мире" in n.label
    assert "240 млн" in d.slide.headline
    # a label that paraphrases its own measure stays
    d = _design(K.stat_row, "В I квартале 2025 года продано 1854 электромобиля", text, title="Объём рынка",
                numbers=[NumberCallout(value="1 854", label="Проданных электромобилей"), NumberCallout(value="240 млн", label="Электромобилей в мире к 2030 году")])
    A.tidy_design(d, _written_ctx())
    assert [x.label for x in d.slide.content.numbers] == ["Проданных электромобилей", "Электромобилей в мире к 2030 году"]


def test_a_revision_never_takes_a_headline_of_two_sentences():
    # live EV run: the critic's «neutral» headline joined two sentences of the text (22 words over a row of figures)
    from verstka.schemas.outline import NumberCallout

    text = "В России доля электромобилей в общем числе продаж новых автомобилей составляет менее 1 %. Рынок растёт."
    nums = [NumberCallout(value="< 1%", label="доля электромобилей в продажах")]
    first = _design(K.big_number, "Доля электромобилей в продажах — менее 1 %", text, title="Тенденции", numbers=nums)
    long = ("В 2025 году мировые продажи электромобилей составили 1,26 млн шт., в России доля электромобилей в общем числе "
            "продаж новых автомобилей составляет менее 1 %")
    revised = _design(K.big_number, long, text, title="Тенденции", numbers=[n.model_copy() for n in nums])
    merged, why = A.merge_revision(first, revised, _written_ctx())
    assert merged is None or merged.slide.headline == "Доля электромобилей в продажах — менее 1 %"


def test_a_slide_titled_after_its_chart_takes_its_title_back_when_the_chart_goes(ww2_full):
    a = WriterAnswer.model_validate({"slides": [{"title": "В цифрах", "text": "Общие людские потери достигли 60—65 млн человек.", "data": {
        "caption": "Потери по странам", "unit": "млн человек", "chart": "column",
        "rows": [{"label": "СССР", "value": 27}, {"label": "Китай", "value": 20}, {"label": "Япония", "value": 3}]}}]})
    deck = W.normalise_answer(a, "Вторая мировая война", "ref")
    assert deck.slides[0].title == "Потери по странам"
    W.verify_against(deck, [ww2_full], "Вторая мировая война")
    assert deck.slides[0].data is None and deck.slides[0].title == "В цифрах"


def test_a_headline_never_gives_a_date_to_another_actor():
    # live WWII run: «Германия капитулировала 2 сентября 1945 года» over the chronology (Japan did; Germany on 8 May)
    from verstka.schemas.outline import SlideItem

    chron = "Хронология:\n— 1 сентября 1939 года — Германия нападает на Польшу;\n— 8 мая 1945 года — Германия капитулирует;\n— 2 сентября 1945 года — Япония капитулирует."
    items = [SlideItem(title="8 мая 1945 года", text="Германия капитулирует"), SlideItem(title="2 сентября 1945 года", text="Япония капитулирует"),
             SlideItem(title="1 сентября 1939 года", text="Германия нападает на Польшу")]
    d = _design(K.timeline, "Германия капитулировала 2 сентября 1945 года", chron, title="Хронология", items=items)
    A.tidy_design(d, _written_ctx())
    assert d.slide.headline == "Хронология" and any("another" in c for c in d.changes)
    d = _design(K.timeline, "Япония капитулировала 2 сентября 1945 года", chron, title="Хронология", items=items)
    A.tidy_design(d, _written_ctx())
    assert d.slide.headline == "Япония капитулировала 2 сентября 1945 года"
    assert A.misdated("Война завершилась 2 сентября 1945 года", chron) == []


def test_a_wrapped_timeline_is_read():
    # live «История VK»: {"timeline": {"text": "…", "entries": [...]}, "text": ""} lost the chronology slide
    a = WriterAnswer.model_validate({"slides": [{"title": "Хронология", "text": "", "data": None, "timeline": {
        "text": "VK прошла путь от почтового сервиса к корпорации.", "entries": [
            {"when": "1998 год", "what": "Основание"}, {"when": "2010 год", "what": "Mail.ru Group"}, {"when": "2021 год", "what": "Ребрендинг в VK"}]}}]})
    s = a.slides[0]
    assert s.text.startswith("VK прошла путь") and [e.when for e in s.timeline] == ["1998 год", "2010 год", "2021 год"]
