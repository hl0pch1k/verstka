"""Правки слайда по просьбе человека («Ваши правки» под замечаниями и чат — один путь, planning/slide_edit.redesign_slide):
«переделай полностью» даёт другую форму, «добавь картинку» — картинку модели изображений по описанию слайда без чисел,
«таблицей», «крупнее цифры», «короче» — и без модели текста (замечание владельца 18.10)."""

from __future__ import annotations

import json
from pathlib import Path

from verstka.planning import slide_edit as SE
from verstka.schemas.outline import DeckOutline

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"


def _outline() -> DeckOutline:
    return DeckOutline.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _bullets(o: DeckOutline, lines: list[str]):
    s = next(x for x in o.slides if x.kind.value == "bullets").model_copy(deep=True)
    s.content.bullets = lines
    s.content.items = []
    return s


DATED = ["1,7–1,8 млн лет назад — каменные орудия в Шилаке", "Около 40 000 лет назад — первые люди современного вида",
         "600 год до н. э — греки основали Массалию"]


def test_requests_are_read():
    assert SE.redo_request("переделай слайд полностью") and SE.redo_request("сделай по-другому") and SE.redo_request("с нуля")
    assert not SE.redo_request("сделай таблицей")
    assert SE.picture_request("переделай полностью и добавь картинку") and SE.picture_request("сделай с иллюстрацией")
    assert not SE.picture_request("сделай короче")
    assert SE.shorter_request("сделай короче") and SE.shorter_request("сократи текст")


def test_a_dated_list_made_anew_is_a_timeline_with_every_line():
    o = _outline()
    s = _bullets(o, DATED)
    got = SE.other_form(o, s)
    assert got is not None and got.kind.value == "timeline"
    assert [i.title for i in got.content.items] == ["1,7–1,8 млн лет назад", "Около 40 000 лет назад", "600 год до н. э"]
    assert not SE.lost_lines(s, got)


def test_rules_make_a_table_and_big_figures():
    o = _outline()
    s = _bullets(o, ["Пилот — 12 400 пользователей", "Рост — 34 % завершённых задач", "Оценка — 4,6 из 5"])
    t = SE.rules_form(o, s, "table", None)
    assert t is not None and t.kind.value == "table" and t.content.table.rows[0] == ["Пилот", "12 400 пользователей"]
    big = SE.rules_form(o, s, "stat_row", None)
    assert big is not None and big.kind.value == "stat_row" and [n.value for n in big.content.numbers][:2] == ["12 400", "34 %"]
    # a stray dash in a line keeps the line whole (one column)
    t2 = SE.rules_form(o, _bullets(o, ["В конце апреля — начале мая войска завершили разгром", "2 мая гарнизон сдался и издал приказ о капитуляции города"]), "table", None)
    assert t2.content.table.columns == ["Что известно"] and t2.content.table.rows[0] == ["В конце апреля — начале мая войска завершили разгром"]


def test_a_picture_is_described_without_figures():
    o = _outline()
    s = _bullets(o, DATED)
    s.headline = "Человек на территории Франции присутствует более 1,7 млн лет"
    hint = SE.picture_hint(s, s)
    assert "Франции" in hint and not any(ch.isdigit() for ch in hint) and "млн" not in hint and "лет" not in hint


def test_redo_with_a_picture_without_a_model_changes_the_slide():
    """No text model: the slide is made anew all the same — another form, a picture the image model draws — and the
    reply says it was done by the rules."""
    o = _outline()
    k = next(i for i, x in enumerate(o.slides, 1) if x.kind.value == "bullets")
    o.slides[k - 1] = _bullets(o, DATED).model_copy(update={"id": o.slides[k - 1].id})
    r = SE.redesign_slide(o, k, None, None, request="переделай слайд полностью и добавь картинку")
    new = r.outline.slides[k - 1]
    assert r.how == "rules" and new.kind.value != "bullets"
    assert new.content.photo_slot == SE.ASKED_PICTURE and not new.content.photo_own and new.content.photo_hint
    assert "по правилам" in r.reply and "картинка" in r.what


def test_a_picture_asked_in_the_chat_is_an_edit():
    from verstka.api.edits import looks_like_edit

    for msg in ("создай изображение на этом слайде", "создай изображение на слайде 5", "сгенерируй картинку", "нарисуй иллюстрацию на слайде 2"):
        assert SE.picture_request(msg) and looks_like_edit(msg), msg
    assert not SE.picture_request("убери место под фото")


def test_without_english_the_asked_picture_is_decorative_and_wordless():
    from verstka.images.prompt import DECORATIVE_SUBJECT, ImageAsk, build_prompt

    p, _ = build_prompt(ImageAsk(hint="Блицкриг и расширение фронта", headline="Блицкриг", deck="Война", label=SE.ASKED_PICTURE), None)
    assert DECORATIVE_SUBJECT in p and "Блицкриг" not in p and "wordless" in p.lower()
    p2, _ = build_prompt(ImageAsk(hint="Блицкриг", headline="Блицкриг", deck="Война", label=SE.ASKED_PICTURE, subject_en="Tanks crossing a field"), None)
    assert "Tanks crossing a field" in p2 and DECORATIVE_SUBJECT not in p2


def test_an_asked_picture_that_failed_keeps_its_place_and_says_why():
    from verstka.api.app import _picture_reply
    from verstka.pipeline.revise import picture_in_place, picture_why

    o = _outline()
    o.slides[2].content.photo_slot = SE.ASKED_PICTURE
    ok, why = picture_in_place([{"slide": 3, "status": "free", "error": "Polza: 401 invalid key"}], o, 3)
    assert not ok and why == "нет ключа к модели изображений"
    assert picture_why([{"slide": 3, "error": "timeout after 90 s"}]) == "модель изображений не успела за отведённое время"
    assert picture_in_place([{"slide": 3, "status": "generated"}], o, 3) == (True, None)
    reply = _picture_reply(f"Слайд 3 переделан: {SE.PICTURE_SAID}.", {3: why}, {})
    assert "нет ключа к модели изображений" in reply and "Место под неё оставил" in reply and "ещё раз" in reply and SE.PICTURE_SAID not in reply
