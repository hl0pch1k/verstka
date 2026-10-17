"""Живой прогон второй ступени (live QA): итог не теряет выводов, «Что дальше» — не из одной строки, шаги не просят
выяснить то, что объясняют сами файлы, переформулировка-описание — не вывод, годы — не числа; чат узнаёт правки;
шаг брендбука и история данных входят во время прогона."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from verstka.api.app import _intent, _is_edit
from verstka.api.edits import parse_edit
from verstka.data.readers import read_file
from verstka.data.story import build_data_outline, build_data_story, is_description, stamp_steps, tidy_text
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
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


def _story(tables, brief: str, answer: dict, seen: dict | None = None):
    def reply(messages):
        if seen is not None:
            seen["user"] = messages[-1].content
        return answer

    mp = MockProvider(reply, model="qwen-test")
    return build_data_story(Brief(text=brief, slide_count=10), tables, use_llm=True, skills=SkillsRegistry.load(), providers=ProviderRegistry(roles={"llm": mp}))


def _summary(o):
    return next(s for s in o.slides if s.id == "summary")


def _by_file(o, file):
    return next(s for s in o.slides if s.data is not None and s.data.file == file)


# ── S1: the summary keeps every conclusion; «Что дальше» only with two steps or more ────────────────────────────────
def test_a_refused_summary_line_keeps_its_own_conclusion(sales):
    det = _summary(build_data_outline(Brief(text=SALES_BRIEF, slide_count=10), sales))
    st = _story(sales, SALES_BRIEF, {"summary": ["Выручка растёт быстрее числа клиентов: +23% против +18%", "Москва даёт 45% выручки",
                                                 "Прямые продажи приносят почти половину выручки — 46%"]})
    got = {i.title: i.text for i in _summary(st.outline).content.items}
    assert len(got) == len(det.content.items) == 4
    assert got["Каналы продаж"] == "Прямые продажи приносят почти половину выручки — 46%"  # the model's line, for its own slide
    assert got["Выручка по регионам"] == next(i.text for i in det.content.items if i.title == "Выручка по регионам")  # kept
    assert any(r["to"] == "Москва даёт 45% выручки" for r in st.rejected)


def test_the_summary_headline_says_only_what_its_cards_back(sales):
    # the key figures' card says it (live QA, N-S1: refused in every run while the cards were the first three slides)
    st = _story(sales, SALES_BRIEF, {"summary_title": "Рост выручки опережает рост клиентской базы"})
    assert _summary(st.outline).headline == "Рост выручки опережает рост клиентской базы"
    st = _story(sales, SALES_BRIEF, {"summary_title": "Пик выручки пришёлся на декабрь"})  # no card speaks of the months
    assert _summary(st.outline).headline == "Выручка растёт быстрее числа клиентов; Москва даёт 41% выручки"
    assert any(r["what"] == "summary_title" and "карточках" in r["why"] for r in st.rejected)
    ok = _story(sales, SALES_BRIEF, {"summary_title": "Рост держится на Москве и прямых продажах"})
    assert _summary(ok.outline).headline == "Рост держится на Москве и прямых продажах"


def test_one_step_makes_no_next_steps_slide(sales):
    st = _story(sales, SALES_BRIEF, {"next_steps": ["Сократить хвост обращений дольше двух часов"]})
    assert not any(s.id == "next-steps" for s in st.outline.slides)


# ── S2 / S3: next steps never ask what the files explain; the files' text reaches the model ───────────────────────
def test_a_step_about_what_the_files_explain_is_refused(sales):
    seen: dict = {}
    st = _story(sales, SALES_BRIEF, {"next_steps": ["Разобрать причины отсутствия данных по NPS во II квартале",
                                                    "Сократить хвост обращений дольше двух часов", "Развивать партнёрский канал в Казани"]}, seen)
    # (the tail step is the model's, not the input's — qa6: one step left makes no slide)
    assert not any(s.id == "next-steps" for s in st.outline.slides)
    why = next(r["why"] for r in st.rejected if r["what"] == "next_step")
    assert "объясняют сами файлы" in why and "не проводился" in why
    # the model is told what the files say, and asked for the brief's own asks (узкие места)
    assert "Итоги квартала.txt" in seen["user"] and "не проводился" in seen["user"]
    assert "узкие места" in (ROOT / "skills" / "data_storyteller" / "prompts" / "system.md").read_text(encoding="utf-8")


# ── A2: a rewording that only lists values is no conclusion ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("Медиана стипендии — 3 590 ₽, среднее — 5 740 ₽", True),
    ("Москва — 1 433 млн ₽, Казань — 274 млн ₽", True),
    ("Половина студентов — до 3 590 ₽, а крупные значения поднимают среднее до 5 740 ₽", False),
    ("Москва даёт 41% выручки", False),
    ("Выручка выросла на 23% к сентябрю", False),
])
def test_a_description_is_told_from_a_conclusion(text, expected):
    assert is_description(text) is expected


def test_a_description_does_not_replace_a_conclusion(science):
    det = build_data_outline(Brief(text=SCIENCE_BRIEF, slide_count=10), science)
    sid = _by_file(det, "Стипендии.csv").id
    st = _story(science, SCIENCE_BRIEF, {"headlines": [{"id": sid, "headline": "Медиана стипендии — 3 590 ₽, среднее — 5 740 ₽"}]})
    assert _by_file(st.outline, "Стипендии.csv").headline == _by_file(det, "Стипендии.csv").headline
    assert any(r["why"] == "это описание чисел, а не вывод" for r in st.rejected)


# ── A3: the years the data or the brief name are no figures ────────────────────────────────────────────────────────
def test_a_year_is_not_a_figure(sales):
    det = build_data_outline(Brief(text=SALES_BRIEF, slide_count=10), sales)
    sid = _by_file(det, "Выручка по месяцам.csv").id
    st = _story(sales, SALES_BRIEF, {"headlines": [{"id": sid, "headline": "Выручка в сентябре 2026 достигла 423 млн ₽"}]})
    assert _by_file(st.outline, "Выручка по месяцам.csv").headline == "Выручка в сентябре 2026 достигла 423 млн ₽"
    # a number the data does not give is still refused
    st = _story(sales, SALES_BRIEF, {"headlines": [{"id": sid, "headline": "Выручка в сентябре 2026 достигла 425 млн ₽"}]})
    assert _by_file(st.outline, "Выручка по месяцам.csv").headline != "Выручка в сентябре 2026 достигла 425 млн ₽"


# ── L6: the data layer's words are set for a slide ─────────────────────────────────────────────────────────────────
def test_periods_and_figures_never_split_and_a_series_name_is_lower_case_mid_sentence():
    nb = " "
    assert tidy_text("III кв. 2026 к III кв. 2025") == f"III{nb}кв.{nb}2026 к III{nb}кв.{nb}2025"
    assert tidy_text("принято 1 290 чел.") == f"принято 1 290{nb}чел."
    assert tidy_text("Больше всех: Платное — 1 290 чел.", ["Платное", "Бюджет"]) == f"Больше всех: платное — 1 290{nb}чел."
    assert tidy_text("Платное — 53% приёма", ["Платное"]) == "Платное — 53% приёма"  # the start of a sentence stays
    # a name, Latin or an acronym keeps its capital (qa3 N-A1: «…год: scopus — с 42 статей»)
    assert tidy_text("С 2005 по 2025 год: Scopus — с 42 статей, РИНЦ — с 255", ["Scopus", "РИНЦ"]) == "С 2005 по 2025 год: Scopus — с 42 статей, РИНЦ — с 255"


def test_a_data_deck_sets_its_periods_together(sales):
    o = build_data_outline(Brief(text=SALES_BRIEF, slide_count=10), sales)
    texts = [x for s in o.slides if s.data is not None for x in (s.headline, s.takeaway or "")]
    assert not any("III кв." in t or "II кв." in t for t in texts)


# ── E2: the chat reads these as edits of the slide ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("message, slide", [
    ("на слайде 3 оставь в подписи только сравнение с сентябрём 2025 года", 3),
    ("на слайде 7 добавь в заголовок, почему нет данных за II квартал", 7),
    ("на слайде 4 выдели Казань цветом", 4),
    ("на слайде 5 напиши в подписи источник", 5),
])
def test_edit_requests_reach_the_edit(message, slide):
    intent, _ = _intent(message)
    assert _is_edit(message, intent)
    req = parse_edit(message, 2, 10)
    assert req is not None and req.kind == "slide" and req.slides == [slide]


@pytest.mark.parametrize("message", ["почему слайд 7 такой?", "объясни слайд 3", "почему на слайде 3 нет данных, добавь объяснение"])
def test_a_question_about_a_slide_stays_a_question(message):
    intent, _ = _intent(message)
    assert intent == "explain_slide" and not _is_edit(message, intent)


# ── E4: the brandbook and the data story are part of the run's time ───────────────────────────────────────────────
def test_the_steps_before_the_pipeline_are_in_the_run_manifest(tmp_path):
    variants = []
    for name in ("structured", "visual"):
        d = tmp_path / name
        d.mkdir()
        (d / "run_manifest.json").write_text(json.dumps({"timings_s": {"plan": 3.0, "total": 30.0}}), encoding="utf-8")
        variants.append(SimpleNamespace(out_dir=d, timings={"plan": 3.0, "total": 30.0}))
    res = SimpleNamespace(variants=variants, seconds=40.0)
    stamp_steps(res, {"brand": 12.345, "data": 2.0})
    for v in variants:
        rm = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
        assert rm["timings_s"] == {"plan": 3.0, "total": 44.35, "brand": 12.35, "data": 2.0}
        assert v.timings["brand"] == 12.35 and v.timings["total"] == 44.35
    assert res.seconds == 54.35
    stamp_steps(res, {})  # nothing before the pipeline: nothing changes
    assert res.seconds == 54.35


# ── R1: a template first met through --brand is analysed with the models when they are on ─────────────────────────
@pytest.mark.parametrize("use_models", [True, False])
def test_the_brand_path_analyses_with_the_models_when_they_are_on(tmp_path, monkeypatch, use_models):
    import verstka.analysis.manifest as manifest_mod
    import verstka.brand.apply as apply_mod
    import verstka.brand.read as read_mod
    import verstka.ingest.workspace as ws_mod
    from verstka.cli import main as cli

    calls = {}

    def analyse(template, **kw):
        calls.update(kw)
        return SimpleNamespace(template_id="tpl")

    monkeypatch.setattr(manifest_mod, "analyze_template", analyse)
    monkeypatch.setattr(read_mod, "read_brandbook", lambda *a, **k: SimpleNamespace(id="", name="Бренд"))
    monkeypatch.setattr(apply_mod, "branded_template", lambda *a, **k: "tpl-brand")
    monkeypatch.setattr(ws_mod.TemplateWorkspace, "open", classmethod(lambda cls, tid, root: SimpleNamespace(source=tmp_path / f"{tid}.pptx")))
    status = SimpleNamespace(update=lambda *_: None)
    providers, skills = object(), object()
    out = cli._branded(tmp_path / "t.pptx", "brand.pdf", "brand", tmp_path, providers, skills, use_vlm=use_models, use_llm=use_models, status=status)
    assert out == tmp_path / "tpl-brand.pptx"
    assert calls["use_llm"] is use_models and calls["use_vlm"] is use_models
    assert (calls["providers"] is providers) is use_models


# ── qa3: summary figures, next steps, the chat on data slides, the run manifest's inputs and usage ─────────────────
def test_the_summary_cards_lead_with_their_key_figure_and_the_steps_are_numbered(sales):
    from verstka.data.story import key_figure

    assert key_figure("Выручка растёт быстрее числа клиентов: +23% против +18%") == "+23%"
    assert key_figure("80% обращений получают ответ за 2 часа") == "80%"
    assert key_figure("Каждый час подготовки в неделю — около +1,9 к среднему баллу ЕГЭ") == "+1,9"
    assert key_figure("NPS вырос в 2026 году") is None
    o = build_data_outline(Brief(text=SALES_BRIEF, slide_count=10), sales)
    assert [i.number for i in _summary(o).content.items] == ["+23%", "41%", "46%", "20%"]  # (the weak spot: its tail, qa4 S3)
    st = _story(sales, SALES_BRIEF, {"next_steps": ["Удержать темп роста в IV квартале за счёт партнёрского канала", "Развивать партнёрский канал в Казани"]})
    steps = next(s for s in st.outline.slides if s.id == "next-steps")
    assert steps.kind.value == "process" and [i.title for i in steps.content.items] == ["Удержать темп роста в IV квартале за счёт партнёрского канала", "Развивать партнёрский канал в Казани"]


def test_an_edit_of_a_data_slide_takes_its_figures_from_the_files():
    from verstka.api.app import _edit_ack

    req = parse_edit("на слайде 3 оставь в подписи только сравнение с сентябрём 2025 года", 2, 10)
    assert "только из файлов с данными" in _edit_ack(req, data_slide=True)
    assert "из вашего текста" in _edit_ack(req)


def test_the_run_manifest_names_the_brief_the_data_and_the_brandbooks_calls(sales, tmp_path):
    from verstka.data.story import stamp_usage, stamp_variants

    st = build_data_story(Brief(text=SALES_BRIEF, slide_count=10), sales)
    vdir = tmp_path / "structured"
    vdir.mkdir()
    (vdir / "run_manifest.json").write_text(json.dumps({"inputs": {"brief_sha256": None, "outline_sha256": "x"}, "usage": {"scope": "generation", "calls": 2, "requests": 2, "tokens_in": 10, "tokens_out": 5, "failed": 0, "cost_rub": None, "by_skill": {"DesignReview": {"calls": 2, "requests": 2, "tokens_in": 10, "tokens_out": 5, "failed": 0, "seconds": 1.0, "cost_rub": None}}}}), encoding="utf-8")
    res = SimpleNamespace(variants=[SimpleNamespace(out_dir=vdir, timings={})], seconds=1.0)
    stamp_variants(res, st, tmp_path)
    stamp_usage(res, [{"skill": "BrandbookRead", "ok": True, "requests": 1, "tokens_in": 100, "tokens_out": 20, "seconds": 3.0}], "brand")
    rm = json.loads((vdir / "run_manifest.json").read_text(encoding="utf-8"))
    assert rm["inputs"]["brief_sha256"] and len(rm["inputs"]["data"]) == len(sales)
    assert all(d["sha256"] and d["file"] for d in rm["inputs"]["data"])
    assert rm["usage"]["calls"] == 3 and "BrandbookRead" in rm["usage"]["by_skill"] and "DesignReview" in rm["usage"]["by_skill"]
