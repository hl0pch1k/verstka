"""Жюри 5, интерфейс (UI1): правка слайда с данными по смыслу, «короче» без потери чисел, честная оценка."""

import json
from pathlib import Path
from types import SimpleNamespace

from verstka.audit.checks import request as RQ
from verstka.planning import data_edit as DE
from verstka.planning.slide_edit import redesign_slide
from verstka.schemas.outline import Brief, DeckOutline, OutlineSlide

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "j5" / "ui1_storage_slide.json"


def _slide() -> OutlineSlide:
    return OutlineSlide.model_validate(json.loads(FIX.read_text(encoding="utf-8")))


def _deck() -> DeckOutline:
    title = OutlineSlide.model_validate({"id": "title", "kind": "title", "headline": "Квартал по хранилищу"})
    return DeckOutline(title="Квартал", slides=[title, _slide()])


def test_q3_to_q2_in_percent_with_the_fall_highlighted():
    s = _slide()
    w = DE.read_wish("итог Q3 к Q2 в процентах, выдели падение", s)
    assert w.measure == "change" and w.highlight == "fall"
    e = DE.apply_wish(s, w)
    assert e is not None
    assert "+7,4% к Q2" in e.slide.headline and "8,6%" in e.slide.headline
    assert "Резервное копирование −8,6%" in e.slide.takeaway
    ch = e.slide.content.chart
    # a fall keeps both periods on the chart (a negative bar is drawn wrong by the previews), the fall highlighted
    assert ch.type == "grouped_bar" and ch.highlight_index == 2
    ids = {f.id for f in e.slide.data.headline_facts}
    assert {"edit_total_change", "edit_change_2", "edit_total_cur"} <= ids


def test_words_only_wish_names_the_category():
    s = _slide()
    w = DE.read_wish("заголовок — вывод: итог Q3 против Q2 в процентах; выдели, что резервное копирование упало", s)
    assert w.highlight == "named" and w.named == 2 and not w.show


def test_redesign_takes_the_data_rules_without_a_model_and_keeps_the_numbers_checked():
    o = _deck()
    r = redesign_slide(o, 2, Brief(text="1) общий итог Q3 против Q2"), None, request="итог Q3 к Q2 в процентах, выдели падение")
    s = r.outline.slides[1]
    assert r.how == "data" and "+7,4%" in s.headline
    from verstka.data.story import data_text_ok, slide_values

    # the audit's rule: the headline — the slide's facts; the caption — a fact or a value the slide shows
    assert data_text_ok(s.headline, s) and data_text_ok(s.takeaway, s, values=slide_values(s))


def test_shorter_drops_a_caption_the_headline_and_chart_already_say():
    o = _deck()
    r = redesign_slide(o, 2, None, None, request="сделай слайд 2 короче")
    s, old = r.outline.slides[1], o.slides[1]
    assert DE._length(s) < DE._length(old)
    assert s.headline == old.headline  # «64%» is nowhere else: the headline keeps it


def test_shorter_cuts_a_tail_whose_figure_the_chart_shows():
    s = _slide()
    s.headline = "Объектное хранилище — 64% выручки Q3"
    s.takeaway = "Резервное копирование — 32 млн ₽, наименьшая категория"
    e = DE.shorter(s)
    assert e is not None and DE._length(e.slide) < DE._length(s)


def test_author_note_is_found_and_taken_out():
    s = _slide()
    s.headline = "Итоги Q3 для правления, сделай 8 слайдов, без картинок"
    s.takeaway = "Таблица по месяцам и SLA во вложении, цели — в регламенте (база знаний)"
    assert RQ.author_notes_in(s.headline) == ["сделай 8 слайдов", "без картинок"]
    done = RQ.unsay(s)
    assert done and s.headline == "Итоги Q3 для правления" and not s.takeaway
    # words for the audience stay
    assert RQ.author_notes_in("Проверьте настройки перед запуском") == []


def _ctx(tmp_path: Path, n_slides: int, brief: str, slides=None):
    (tmp_path / "structured").mkdir()
    (tmp_path / "generation.json").write_text(json.dumps({"brief": brief, "slides": slides}), encoding="utf-8")
    ir = SimpleNamespace(slides=[SimpleNamespace(index=k + 1, outline_id=None) for k in range(n_slides)])
    issues = []
    ctx = SimpleNamespace(ir=ir, brief_text=None, pptx=tmp_path / "structured" / "deck.pptx", outline=None,
                          new_issue=lambda spec, slide, msg, **kw: issues.append((spec.id, slide, msg, kw.get("severity"))) or issues[-1])
    return ctx


def test_slide_count_unmet_reads_the_request_beside_the_deck(tmp_path):
    ctx = _ctx(tmp_path, 3, "Квартал по хранилищу\n1) общий итог Q3 против Q2\n5 слайдов")
    got = RQ.slide_count_unmet(ctx)
    assert got and got[0][3] == "error" and "5 слайдов" in got[0][2] and "3 слайда" in got[0][2]


def test_slide_count_met_or_said_by_the_stepper(tmp_path):
    assert RQ.slide_count_unmet(_ctx(tmp_path, 5, "Квартал\n5 слайдов")) == []


def test_slide_count_stepper_wins(tmp_path):
    got = RQ.slide_count_unmet(_ctx(tmp_path, 11, "Квартал по хранилищу", slides=12))
    assert got and got[0][3] == "warn"
