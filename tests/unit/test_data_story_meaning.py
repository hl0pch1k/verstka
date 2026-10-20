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


def test_cover_names_the_topic_and_its_result():
    o = _story()
    assert o.slides[0].headline == "Итоги 2025 года: выручка +66%" and o.slides[0].subtitle == "Для правления"
    assert o.slides[0].headline not in [s.headline for s in o.slides[1:]]


def test_period_in_calendar_words_and_one_conclusion_over_the_cards():
    o = _story()
    heads = [s.headline for s in o.slides]
    assert "Выручка выросла на 66% за 2025 год" in heads and not any("за 11 месяцев" in h for h in heads)
    kf = next(s for s in o.slides if s.id == "key-figures")
    assert ";" not in kf.headline
    labels = [n.label for n in kf.content.numbers]
    assert labels == ["рост выручки за 2025 год", "Москва — доля выручки", "Прямые продажи — крупнейшая доля"], labels


def test_the_end_says_what_the_figures_mean_not_the_cards_again():
    o = _story()
    end = next(s for s in o.slides if s.id == "summary")
    assert not end.content.items and end.content.bullets  # no second row of the opening's cards
    assert end.headline.startswith("Москва — 46% выручки") and "одного региона" in end.headline
    assert any(b.startswith("Резерв роста") for b in end.content.bullets)
    kf = next(s for s in o.slides if s.id == "key-figures")
    assert end.headline != kf.headline
