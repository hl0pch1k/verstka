"""Смысл колоды данных (сценарий S10: выручка по месяцам, по регионам, по каналам): обложка — тема и итог, сводный
заголовок — один вывод, подписи карточек словами человека, период словами календаря, финал — что значат цифры, а не
повтор карточек начала."""

from __future__ import annotations

from pathlib import Path

from verstka.data.readers import read_file
from verstka.data.story import build_data_story
from verstka.schemas.data import Table
from verstka.schemas.outline import Brief

ROOT = Path(__file__).resolve().parents[2]
S10 = ROOT / "tests" / "fixtures" / "s10_sales"
BRIEF = ("Итоги 2025 года для правления. Покажи, что выручка растёт, сравни регионы, из чего складываются каналы продаж "
         "и есть ли связь между часами подготовки и баллом.")


def _story(n=7):
    tables: list[Table] = []
    for f in sorted(S10.iterdir()):
        tables += read_file(f)
    return build_data_story(Brief(text=BRIEF), tables, slide_count=n).outline


def test_cover_names_the_topic_and_no_heading_repeats():
    """Обложка — тема («Итоги 2025 года»); ни один заголовок не повторяет другой — ни текстом, ни главным числом о том
    же предмете (владелец 21.10: «Выручка выросла на 66%» на сводке и на графике)."""
    from verstka.data.story import same_headline

    for n in (5, 6, 7):
        o = _story(n)
        assert o.slides[0].headline == "Итоги 2025 года" and o.slides[0].subtitle == "Для правления"
        heads = [s.headline for s in o.slides]
        assert not any(same_headline(a, b) for i, a in enumerate(heads) for b in heads[i + 1:]), heads


def test_period_in_calendar_words_and_one_conclusion_over_the_cards():
    o = _story()
    heads = [s.headline for s in o.slides]
    assert "Выручка выросла на 66% за 2025 год" in heads and not any("за 11 месяцев" in h for h in heads)
    kf = next(s for s in o.slides if s.id == "key-figures")
    assert ";" not in kf.headline and kf.headline.startswith("2025 год в трёх цифрах: рост выручки, главный регион — Москва")
    labels = [n.label for n in kf.content.numbers]
    assert labels == ["рост выручки за 2025 год", "Москва — доля выручки", "Прямые продажи — крупнейшая доля"], labels


def test_the_end_says_what_the_figures_mean_not_the_cards_again():
    o = _story(6)
    end = next(s for s in o.slides if s.id == "summary")
    assert not end.content.items and end.content.bullets  # no second row of the opening's cards
    assert end.headline == "Итог зависит от одного региона: это риск и резерв роста"
    assert any("Москва — 46% выручки" in b for b in end.content.bullets)
    assert any(b.startswith("Резерв роста") for b in end.content.bullets)
    kf = next(s for s in o.slides if s.id == "key-figures")
    assert end.headline != kf.headline


def test_an_exact_count_is_met_with_slides_of_their_own_or_said_plainly():
    """«7 слайдов» → 7: финал делится на «что значат цифры» и «что дальше» (действия из следствий), без пустых и
    повторов; 8 — данных хватает на 7, и это сказано; 5 — не больше 5, итог — один вывод."""
    o = _story(7)
    assert len(o.slides) == 7
    nxt = next(s for s in o.slides if s.id == "data-next")
    assert nxt.headline == "Расти за пределами лидера и удержать темп" and len(nxt.content.bullets) == 2
    heads = [s.headline for s in o.slides]
    assert len(set(heads)) == len(heads)
    tables = []
    for f in sorted(S10.iterdir()):
        tables += read_file(f)
    st = build_data_story(Brief(text=BRIEF), tables, slide_count=9)
    assert len(st.outline.slides) == 7 and st.short_of == (7, 9)
    assert any("Данных хватило на 7 осмысленных слайдов из 9 запрошенных" in x for x in st.outline.agent_log)
    small = _story(5)
    assert len(small.slides) <= 5 and all(";" not in s.headline for s in small.slides)
