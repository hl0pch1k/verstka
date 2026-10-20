"""The author's own text laid out as written (planning/faithful.py): parts of a dictated slide, whole sentences, the
cover and the closing slide the text itself marks, a form per variant against the template's samples."""

import json
import re
from pathlib import Path

import pytest

from verstka.planning import faithful as F
from verstka.planning.brief_structure import read_structure
from verstka.schemas.template import TemplateManifest

ROOT = Path(__file__).resolve().parents[2]
BRIEF = (ROOT / "tests" / "fixtures" / "briefs" / "smart_greenhouse.md").read_text(encoding="utf-8")
EDU = ROOT / "workspace" / "templates" / "9ef2323ed5f49f46" / "manifest.json"


def _sentences_of_brief() -> set[str]:
    out: set[str] = set()
    for sp in read_structure(BRIEF).specs:
        for p in F.read_parts(sp.text):
            out.update(F.sentences(p.text) if p.kind == "para" else [])
    return out


# ------------------------------------------------------------------ reading


def test_sentences_stay_whole_inside_quotes_and_after_abbreviations():
    text = "Пользователь получает уведомление: «Зона 2: данные датчика не обновлялись 8 минут. Полив приостановлен». Такое сообщение понятно."
    assert F.sentences(text) == [
        "Пользователь получает уведомление: «Зона 2: данные датчика не обновлялись 8 минут. Полив приостановлен».",
        "Такое сообщение понятно.",
    ]
    assert F.sentences("Сигнал при 28 °C. Разница называется гистерезисом.") == ["Сигнал при 28 °C.", "Разница называется гистерезисом."]
    assert F.sentences("Это т. е. пример. А. С. Пушкин написал.") == ["Это т. е. пример.", "А. С. Пушкин написал."]


def test_a_slide_is_read_into_its_parts():
    text = (
        "Первый абзац о данных. Второе предложение.\n\n"
        "Пример записи, которую контроллер отправляет в журнал:\n\n"
        "```json\n{\n  \"zone\": \"bed_1\",\n  \"tank_level_pct\": 72\n}\n```\n\n"
        "[Место под изображение: вид теплицы сверху. Подписи показывают датчики.]\n\n"
        "[Сравнительные столбчатые графики: расход воды — 4 800 и 3 300 литров; ручная работа — 45 и 20 минут в день.]\n\n"
        "Последовательность работы: датчики → проверка показаний → правила управления → запись результата в журнал.\n\n"
        "- первый пункт\n- второй пункт"
    )
    parts = F.read_parts(text)
    kinds = [p.kind for p in parts]
    assert kinds == ["para", "code", "image", "chart", "flow", "list"]
    code = parts[1]
    assert code.lang == "json" and code.label == "Пример записи, которую контроллер отправляет в журнал"
    assert code.text.splitlines()[1] == '  "zone": "bed_1",'  # the indent as written
    assert parts[2].text.startswith("вид теплицы сверху")
    assert parts[4].items == ["Датчики", "Проверка показаний", "Правила управления", "Запись результата в журнал"]
    assert parts[4].label == "Последовательность работы"
    assert parts[5].items == ["первый пункт", "второй пункт"]


def test_chart_notes_give_their_data():
    items = F.chart_items("расход воды — 4 800 и 3 300 литров; ручная работа — 45 и 20 минут в день; время вне диапазона — 42 и 15 часов. Для каждого показателя — отдельный график.")
    assert [(i.label, i.values, i.unit) for i in items] == [("Расход воды", [4800.0, 3300.0], "л"), ("Ручная работа", [45.0, 20.0], "мин"), ("Время вне диапазона", [42.0, 15.0], "ч")]
    pie = F.chart_items("контроллер и связь — 8 000 рублей; датчики — 14 000; резерв — 6 000.")
    assert [(i.label, i.values, i.unit) for i in pie] == [("Контроллер и связь", [8000.0], "₽"), ("Датчики", [14000.0], "₽"), ("Резерв", [6000.0], "₽")]
    assert F.chart_type_of("Круговая диаграмма распределения бюджета", pie) == "pie"
    assert F.pair_names("обслуживалась вручную, во втором — автоматически", 2) == ["Вручную", "Автоматически"]


def test_the_first_slide_with_a_tagline_is_the_cover_and_the_thanks_slide_is_the_closing():
    st = read_structure(BRIEF)
    first = F.read_slide(1, st.specs[0].title, st.specs[0].text, first=True)
    assert first.role == "cover"
    assert first.title == "Умная теплица" and first.lead == "Автоматизация полива и контроль микроклимата"
    assert first.footnote and "учебными допущениями" in first.footnote
    last = F.read_slide(14, st.specs[-1].title, st.specs[-1].text, last=True)
    assert last.role == "closing" and last.lead.startswith("Умная теплица — от наблюдений")
    # a first slide named like a part of the deck is content, even with a short line under its heading
    assert F.read_slide(1, "Проблема", "Клиенты ждут ответа два дня\n\nОператоры перегружены.", first=True).role == "content"


def test_stages_and_the_stated_result_are_read():
    st = read_structure(BRIEF)
    r = F.read_slide(13, st.specs[12].title, st.specs[12].text)
    assert [name for name, _ in r.stages()] == ["Первый этап развития", "Второй этап", "Третий этап"]
    assert r.takeaway.startswith("Главный результат проекта")


# ------------------------------------------------------------------ the deck


@pytest.fixture(scope="module")
def plan():
    manifest = TemplateManifest.model_validate(json.loads(EDU.read_text(encoding="utf-8"))) if EDU.exists() else None
    return F.plan_deck(read_structure(BRIEF).specs, manifest)


def test_the_deck_keeps_the_users_slides_with_their_own_cover_and_closing(plan):
    assert plan.title == "Умная теплица"
    for name, slides in plan.decks.items():
        assert len(slides) == 14, name  # no second cover in front of the user's own
        assert slides[0].kind.value == "title" and slides[0].headline == "Умная теплица"
        assert slides[0].subtitle == "Автоматизация полива и контроль микроклимата"
        assert slides[-1].kind.value == "thanks"
        assert all(s.verbatim for s in slides)


def test_code_charts_and_pictures_take_their_forms(plan):
    s = plan.decks["structured"]
    assert s[4].kind.value == "code" and s[4].content.code.language == "json"
    assert s[6].kind.value == "code" and "def irrigation_decision(" in s[6].content.code.text
    assert s[9].kind.value == "code"
    chart = s[8].content.chart
    assert chart.split and [x.name for x in chart.series] == ["Расход воды", "Ручная работа", "Время вне температурного диапазона"]
    assert [x.unit for x in chart.series] == ["л", "мин в день", "ч"] and chart.categories == ["Вручную", "Автоматически"]
    assert s[10].content.chart.type == "pie" and len(s[10].content.chart.categories) == 8
    assert s[3].content.photo_slot and s[3].content.photo_hint.startswith("Вид теплицы сверху")
    assert s[5].kind.value == "process" and len(s[5].content.items) == 5


def test_every_line_on_a_slide_is_made_of_the_authors_whole_sentences(plan):
    whole = _sentences_of_brief()

    def pieces(text: str) -> list[str]:
        return F.sentences(text)

    for name, slides in plan.decks.items():
        for sl in slides:
            c = sl.content
            texts = [*c.bullets, *c.paragraphs] + [it.text for it in [*c.items, *c.columns] if it.text] + [b for it in c.columns for b in it.bullets]
            for t in texts:
                for sent in pieces(t):
                    # (a stage's name taken off the front of its sentence leaves the rest, capitalised: «Первый этап — повышение …»)
                    low = sent.lower()
                    assert sent in whole or any(w.lower().endswith(low) for w in whole), (name, sl.headline, sent)


def test_the_variants_take_different_forms(plan):
    forms = {name: [s.kind.value for s in slides] for name, slides in plan.decks.items()}
    differ = lambda a, b: sum(1 for x, y in zip(forms[a], forms[b]) if x != y)  # noqa: E731
    assert differ("structured", "compact") >= 3
    assert differ("structured", "visual") >= 3


def test_notes_keep_the_whole_text(plan):
    s = plan.decks["structured"][2]
    for p in F.read_parts(read_structure(BRIEF).specs[2].text):
        assert p.text in s.notes


def test_one_sentence_less_never_cuts_a_sentence():
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import OutlineSlide, SlideContent, SlideItem

    s = OutlineSlide(id="s", kind=PatternKind.cards, headline="H", verbatim=True,
                     content=SlideContent(items=[SlideItem(title="", text="Первое предложение. Второе предложение."), SlideItem(title="", text="Короткое.")]))
    assert F.drop_one_sentence(s).startswith("one sentence less")
    assert s.content.items[0].text == "Первое предложение."
    assert F.drop_one_sentence(s) == "skip"  # two blocks of one sentence: nothing goes


def test_no_model_run_lays_the_dictated_text_out_as_written():
    from verstka.planning.agent import run_agent
    from verstka.planning.brief import parse_brief_text
    from verstka.planning.strategies import load_strategies

    sts = load_strategies()
    events: list[dict] = []
    res = run_agent(parse_brief_text(BRIEF), None, [sts[n] for n in ("structured", "visual", "compact")], progress=events.append)
    for name, o in res.outlines.items():
        assert o.title == "Умная теплица"
        assert len(o.slides) == 14 and o.slides[0].kind.value == "title"
        assert not any(re.search(r"\bСлайд\s+\d", s.headline) for s in o.slides)
        assert sum(1 for s in o.slides if s.content.code is not None) == 3
    msgs = [e["message"] for e in events if e.get("step") == "compile"]
    assert not any("добавил перед ними титульный слайд" in m for m in msgs)


# ------------------------------------------------------------------ the variants open differently (any template)


def test_each_variant_opens_on_its_own_cover_and_the_compact_one_on_a_light_cover():
    """matcher.variant_cover: from the template's covers that hold the title — one of each layout and ground — the
    structured variant takes the best, the visual one the next, the compact one a light cover; decided from the
    manifest alone (any template)."""
    from verstka.matching.matcher import match_outline
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import DeckOutline, OutlineSlide

    if not EDU.exists():
        pytest.skip("the VK Education template is not in the workspace")
    manifest = TemplateManifest.model_validate(json.loads(EDU.read_text(encoding="utf-8")))
    sts = load_strategies()
    cover = OutlineSlide(id="sl1", kind=PatternKind.title, headline="Умная теплица", subtitle="Автоматизация полива и контроль микроклимата")
    thanks = OutlineSlide(id="sl2", kind=PatternKind.thanks, headline="Спасибо за внимание!", subtitle="Вопросы и обсуждение")
    o = DeckOutline(title="Умная теплица", slides=[cover, thanks])
    picked = {}
    for name in ("structured", "visual", "compact"):
        plan = match_outline(o, manifest, sts[name])
        picked[name] = [s.pattern_id for s in plan.slides]
    by_id = {p.id: p for p in manifest.patterns}
    assert picked["structured"][0] != picked["visual"][0]
    assert by_id[picked["compact"][0]].family.value == "light"
    # the closing slide answers the cover's ground
    assert by_id[picked["compact"][1]].family.value == "light"
    assert by_id[picked["structured"][1]].family == by_id[picked["structured"][0]].family


# ------------------------------------------------------------------ what a dictated slide may hold (any brief)


def _run(text: str, manifest=None):
    from verstka.planning.agent import run_agent
    from verstka.planning.brief import parse_brief_text
    from verstka.planning.strategies import load_strategies

    sts = load_strategies()
    events: list[dict] = []
    res = run_agent(parse_brief_text(text), manifest, [sts[n] for n in ("structured", "visual", "compact")], progress=events.append)
    return res, events


_HEAD = "Слайд 1. Умная теплица\n\nАвтоматизация полива\n\n"
_TAIL = "\n\nСлайд 9. Итоги\n\nРасход воды снизился на треть. Ручной работы стало вдвое меньше. Урожай не пострадал.\n"


def _slide(res, ref: int, variant: str = "structured"):
    return next(s for s in res.outlines[variant].slides if s.spec_ref == ref)


def test_a_note_without_its_data_leaves_the_place_for_it_described():
    res, _ = _run(_HEAD + "Слайд 2. Бюджет\n\n[Здесь будет круговая диаграмма бюджета]" + _TAIL)
    s = _slide(res, 2)
    assert s.content.photo_slot == "Место под диаграмму" and s.content.photo_hint == "Круговая диаграмма бюджета"
    res, _ = _run(_HEAD + "Слайд 2. Сравнение\n\n[Таблица: вода — 4800 и 3300 литров; время — 45 и 20 минут]" + _TAIL)
    t = _slide(res, 2).content.table
    assert t is not None and t.rows == [["Вода", "4800 и 3300 литров"], ["Время", "45 и 20 минут"]]  # as written: which is which, the text does not say


def test_a_heading_over_a_line_and_a_list_or_two_sentences_is_no_divider():
    res, _ = _run(_HEAD + "Слайд 2. Что мы сделали\n\nМы прошли три шага за месяц.\n\n— купили датчики влажности;\n— собрали контроллер;\n— написали программу полива;\n— проверили систему на грядке." + _TAIL)
    s = _slide(res, 2)
    assert s.kind.value != "section" and s.subtitle == "Мы прошли три шага за месяц"
    assert len(s.content.items or s.content.bullets) == 4
    res, _ = _run(_HEAD + "Слайд 2. Решение\n\nБот отвечает за минуту. Это быстро." + _TAIL)
    assert "Это быстро." in " ".join(_slide(res, 2).content.bullets)


def test_the_closing_slide_is_a_heading_of_thanks_and_nothing_more():
    r = F.read_slide(3, "Вопросы безопасности", "Мы проверили защиту данных. Пароли меняются раз в месяц.\n\nДоступ к насосу есть у двух инженеров.", last=True)
    assert r.role == "content"
    assert F.read_slide(3, "Контактный центр после внедрения", "Операторы отвечают быстрее.", last=True).role != "closing"
    r = F.read_slide(2, "Спасибо за внимание!", "Вопросы и обсуждение.", last=True)
    assert r.role == "closing" and r.lead == "Вопросы и обсуждение"
    res, _ = _run("Слайд 1. Умная теплица\n\nАвтоматизация полива\n\nСлайд 2. Спасибо за внимание!\n\nВопросы и обсуждение.\n")
    assert [s.kind.value for s in res.outlines["structured"].slides] == ["title", "thanks"]


def test_cover_fields_given_as_a_list_make_the_cover():
    r = F.read_slide(1, "Кофейня", "— Название: Больше прибыли с каждой чашки\n— Подзаголовок: План развития на 6 месяцев", first=True)
    assert r.role == "cover" and r.title == "Больше прибыли с каждой чашки" and r.lead == "План развития на 6 месяцев"


def test_a_list_beside_a_picture_code_or_chart_stays_on_the_slide():
    r = F.read_slide(2, "Панель наблюдения", "Панель показывает оператору главное:\n— температуру воздуха в двух точках;\n— влажность грунта по трём зонам;\n— уровень воды в баке.\n\n[Место под изображение: экран панели управления]")
    for profile in ("structured", "visual", "compact"):
        s = F.forms_of(r, F.Room(), profile)[0].slide
        assert s.subtitle == "Панель показывает оператору главное" and len(s.content.bullets) == 3, profile
        assert s.content.photo_hint == "Экран панели управления"


def test_a_sequence_inside_a_paragraph_keeps_the_sentences_around_it():
    parts = F.read_parts("Мы собираем данные каждую минуту. Они идут так: датчик → контроллер → журнал. Потом инженер их анализирует. Это занимает час.")
    assert [p.kind for p in parts] == ["para", "flow", "para"]
    assert parts[1].items == ["Датчик", "Контроллер", "Журнал"] and parts[1].label == "Они идут так"
    assert parts[2].text == "Потом инженер их анализирует. Это занимает час."


def test_the_authors_sentences_are_never_taken_for_rules_to_the_designer():
    st = read_structure(BRIEF)
    r = F.read_slide(4, st.specs[3].title, st.specs[3].text)
    assert any("должны быть доступны для проверки" in x for ss in r.paras() for x in ss)
    for own in ("Цвета листьев меняются при нехватке влаги.", "Обязательно проверяйте датчики раз в неделю.", "Выводы исследования подтвердили гипотезу."):
        assert F.designer_ask(own) is None, own
    for ask in ("Используй светлый фон.", "Не перегружай слайд текстом.", "На каждом слайде должен быть вывод."):
        assert F.designer_ask(ask) == "rule", ask


def test_chart_notes_name_their_charts_and_read_their_figures_as_written():
    r = F.read_slide(2, "Бюджет", "Бюджет 22 000 рублей.\n\n[Нужна круговая диаграмма распределения бюджета: контроллер — 8 000 рублей; датчики — 14 000 рублей]")
    assert F.charts_of(r)[0].title == "Распределение бюджета"
    r = F.read_slide(2, "Results", "Water use dropped.\n\n[Column chart: water — 4,800 and 3,300 litres; manual work — 45 and 20 minutes]")
    ch = F.charts_of(r)[0]
    assert ch.title is None and [x.values for x in ch.series] == [[4800.0, 3300.0], [45.0, 20.0]] and [x.unit for x in ch.series] == ["l", "min"]
    # a range is no pair of figures: no «Было / Стало» chart, a table of the ranges as written
    r = F.read_slide(5, "Цены", "Цены доступные.\n\n[Столбчатая диаграмма цен: добавки — 40–60 рублей; сиропы — 30–50 рублей]")
    assert F.charts_of(r) == [] and F.note_table(r).rows == [["Добавки", "40–60 ₽"], ["Сиропы", "30–50 ₽"]]
    r = F.read_slide(2, "Рост", "Выручка растёт.\n\n[Линейный график выручки: 2023 — 1,2 млн рублей; 2024 — 1,8 млн рублей; 2025 — 2,5 млн рублей]")
    ch = F.charts_of(r)[0]
    assert ch.type == "line" and ch.categories == ["2023", "2024", "2025"] and ch.unit == "млн ₽" and ch.title == "Выручка"
    # litres beside minutes, one figure each: a row of key figures, never one axis
    r = F.read_slide(2, "Итоги", "Итоги.\n\n[Диаграмма: расход воды — 4 800 литров; ручная работа — 45 минут]")
    assert F.charts_of(r) == [] and [n.value for n in F.note_figures(r)] == ["4 800 л", "45 мин"]
    # two figures with nothing said of them are not «Было / Стало»
    assert F.pair_names("Вода и время.", 2) == ["1", "2"]


def test_no_variant_shows_three_slides_of_one_form_in_a_row_or_a_figure_out_of_its_sentence():
    manifest = TemplateManifest.model_validate(json.loads(EDU.read_text(encoding="utf-8"))) if EDU.exists() else None
    res, _ = _run((ROOT / "tests" / "fixtures" / "briefs" / "coffee_long.md").read_text(encoding="utf-8"), manifest)
    kinds = {}
    for name, o in res.outlines.items():
        ks = [s.kind.value for s in o.slides]
        kinds[name] = ks
        assert not any(a == b == c for a, b, c in zip(ks, ks[1:], ks[2:])), (name, ks)
        five = next(s for s in o.slides if s.spec_ref == 5)  # «Как увеличить средний чек»: a list of actions
        assert five.kind.value not in ("stat_row", "big_number"), name
    assert kinds["structured"] != kinds["visual"] != kinds["compact"]


def test_the_designer_lines_number_the_slides_of_the_deck():
    res, events = _run("Slide 1. Discovery\n\nWe interviewed forty customers in March. Most of them wait two days.\n\nSlide 2. Plan\n\nA chatbot answers routine questions. Operators handle only complex cases.\n\nSlide 3. Next steps\n\nWe hire two engineers. We launch the pilot in one region.\n")
    o = res.outlines["structured"]
    said = {e["slide"]: e["message"] for e in events if e.get("step") == "designer" and e.get("slide")}
    for i, s in enumerate(o.slides, 1):
        if s.spec_ref is not None:
            assert f"«{s.headline}»" in said[i], (i, s.headline, said.get(i))
    assert o.slides[1].kind.value != "title"  # «Discovery» is no cover


def test_slides_without_headings_take_the_texts_own_first_words():
    res, _ = _run("Слайд 1.\n\nПервый абзац про теплицу и полив растений. Второе предложение про датчики влажности.\n\n"
                  "Слайд 2.\n\nЕщё абзац про контроллер и насос. И ещё одно предложение про бак с водой.\n\n"
                  "Слайд 3.\n\nТретий абзац про результаты эксперимента. Финал этой истории про экономию воды.\n")
    for name, o in res.outlines.items():
        assert not any(re.search(r"\bСлайд\s+\d", s.headline) for s in o.slides)
        assert all(s.kind.value != "section" for s in o.slides)
        if name == "compact":
            # (without a model the compact variant puts two neighbouring slides of one line each side by side)
            assert [c.title for c in o.slides[1].content.columns] == ["Первый абзац про теплицу и полив растений", "Ещё абзац про контроллер и насос"]
        else:
            assert o.slides[2].headline == "Ещё абзац про контроллер и насос"


def test_reading_a_long_paragraph_without_a_split_point_is_fast():
    import time

    text = " ".join(["А. Б. Фамилия"] * 1500)
    t = time.time()
    F.sentences(text)
    assert time.time() - t < 0.5
