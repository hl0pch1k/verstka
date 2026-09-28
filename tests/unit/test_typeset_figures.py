"""Gate 5 (content-G5-16): ranges, signs and percents are set the Russian way on every deck, faithful or written — a
range takes an en dash bound to both numbers («5–6 тыс.» never breaks as «5 / –6 тыс.»), «5-6 тысяч» becomes «5–6»,
«-69%» takes a true minus, and one deck writes its percents one way (the style of its own words). Nothing else of a
text changes."""

from __future__ import annotations

from lxml import etree

from verstka.ru import MINUS, NBSP, WJ, deck_typography, percent_style_of, typeset, typeset_figures


def test_a_range_takes_an_en_dash_bound_to_both_numbers():
    assert typeset_figures("производство 5–6 тыс.") == f"производство 5{WJ}–{WJ}6 тыс."
    assert typeset_figures("будет произведено 5-6 тысяч") == f"будет произведено 5{WJ}–{WJ}6 тысяч"
    assert typeset_figures("в 1941-1945 годах, рост 10-15%") == f"в 1941{WJ}–{WJ}1945 годах, рост 10{WJ}–{WJ}15%"
    assert typeset_figures("в 1941—1945 годах") == f"в 1941{WJ}—{WJ}1945 годах"  # an em-dash range keeps its dash
    assert typeset_figures(f"5-{WJ}6 тысяч") == f"5{WJ}–{WJ}6 тысяч"  # a range bind_compounds already joined
    # not a range: a date, a phone, a code, a compound word, a clock time
    for text in ("2025-09-28", "8-800-555-35-35", "Ту-144 и COVID-19", "5-6-летние дети", "с 9:00-18:00", "GPU-сервера"):
        assert typeset_figures(text) == text


def test_a_sign_before_a_number_is_a_true_minus():
    assert typeset_figures("-69%") == f"{MINUS}69%"
    assert typeset_figures("снижение –5 п. п.") == f"снижение {MINUS}5 п. п."
    assert typeset_figures("(-3,5 %)") == f"({MINUS}3,5 %)"
    for text in ("от 5 -6", "Ту-144", "Рост — 5%", "2020-е годы"):
        assert typeset_figures(text) == text


def test_one_deck_writes_its_percents_one_way():
    """VK 5f8c31 s6: the heading «42 %» (the article's style) over the stat «42%» (the model's): the deck's own words
    decide — the majority, a tie goes to the first; no percent, no rule; outside a deck nothing is normalised."""
    assert percent_style_of(["Доход 42 %, игры 32 %", "42%"]) == "spaced"
    assert percent_style_of(["35% выручки", "до 33%", "26,5 %"]) == "tight"
    assert percent_style_of(["5% и 6 %"]) == "tight" and percent_style_of(["6 % и 5%"]) == "spaced"
    assert percent_style_of(["без процентов"]) is None
    with deck_typography(["Доход 42 %, игры 32 %"]):
        assert typeset_figures("42%") == f"42{NBSP}%" and typeset("−69%") == f"{MINUS}69{NBSP}%"
        with deck_typography(["35%"]):
            assert typeset_figures(f"42{NBSP}%") == "42%"
        assert typeset_figures("42%") == f"42{NBSP}%"
    assert typeset_figures("42%") == "42%" and typeset_figures("42 %") == "42 %"


def test_typesetting_is_idempotent_and_changes_only_these_characters():
    text = "В 2026 году 5-6 тыс. электромобилей, -69% к 2024 году, доля 42 %"
    with deck_typography([text]):
        once = typeset(text)
        assert typeset(once) == once
        plain = typeset_figures(text)
    assert plain.endswith("доля 42%")  # a tie («-69%» / «42 %») goes to the first percent's style
    back = plain.replace(WJ, "").replace("–", "-").replace(MINUS, "-").replace(NBSP, " ")
    assert back == text.replace(" %", "%")


def test_every_text_the_clone_writes_is_typeset():
    """textfill.fill_text (every clone text) sets the figures; the deck renderer gives the whole deck one style."""
    import inspect

    from verstka.rendering import renderer
    from verstka.rendering.textfill import ParagraphSpec, fill_text

    sp = etree.fromstring(
        '<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:txBody><a:bodyPr/><a:p><a:r><a:rPr lang=\"ru-RU\"/><a:t>x</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    with deck_typography(["42%"]):
        assert fill_text(sp, [ParagraphSpec("План: 5-6 тыс., -69 %")])
    t = sp.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t").text
    assert t == f"План: 5{WJ}–{WJ}6 тыс., {MINUS}69%"
    assert "deck_typography" in inspect.getsource(renderer.render_deck)
