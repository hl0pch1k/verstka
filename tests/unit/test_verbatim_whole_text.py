"""«Модель пишет тексты» off: the author's ready text is laid out WHOLE (jury 5: VKT-A, W-B, E-A, L-B).

- every sentence of a report, a talk or a lecture is on a slide — the author's sections are the slides, a long one goes
  on over as many slides as it needs, the person's slide count is kept (what does not fit goes to the notes, said so);
- the cover is the author's title line (and the line under it that says where the talk is given), never a sentence;
- the deterministic check counts the author's sentences on the slides, in the notes only, and lost;
- a heading never cuts a formula, a bracket, a figure from its unit or a list of figures in two;
- a transcript is still condensed (planning/digest.py), not laid out sentence by sentence.
"""

from __future__ import annotations

import pytest

from verstka.planning import faithful as F
from verstka.planning import heuristics as H
from verstka.planning.agent import run_agent
from verstka.planning.brief import parse_brief_text
from verstka.planning.digest import headline_of
from verstka.planning.strategies import load_strategies
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent, SlideItem

REPORT = """Переход склада на электронные накладные: итоги полугодия

Полгода назад склад в Подольске работал только с бумажными накладными. Каждую смену кладовщики вручную сверяли до 400 документов, а ошибки в адресах доставки находили уже у клиента. Этот отчёт — для операционного комитета: что сделано, что изменилось и что предлагаем дальше.

Исходная точка. На складе работали 46 кладовщиков в три смены. Средняя сверка одной накладной занимала 4 минуты. За 2025 год случилось 312 ошибок отгрузки, из них 41 — с возвратом товара. Претензии клиентов обходились примерно в 2,4 млн рублей в год.

Что сделали. Мы подключили электронный документооборот с тремя крупнейшими поставщиками. Сканеры штрихкодов выдали всем сменам. Сверка теперь идёт автоматически, а кладовщик подтверждает только расхождения.

Результаты. Время сверки одной накладной сократилось с 4 минут до 40 секунд, то есть в 6 раз. Ошибки отгрузки снизились с 312 до 58 за полугодие. Доля накладных с расхождениями упала с 18 % до 3 %. Претензии клиентов сократились на 70 %.

Что предлагаем. Первое — подключить к электронным накладным оставшиеся 12 поставщиков до конца года. Второе — перевести на сканеры склад в Химках. Мы просим комитет утвердить бюджет на 2027 год в 9,5 млн рублей."""

TALK = """Как мы сократили время сборки мобильного приложения в 3 раза

Доклад на конференции «Мобильная разработка», секция «Инфраструктура».

Каждый день наши 80 разработчиков запускают около 1 200 сборок. В начале года одна сборка шла в среднем 27 минут. Разработчики ждали результата и переключались на другие задачи.

Главный урок: прежде чем покупать новые машины, измерьте, где на самом деле теряется время. В нашем случае медленной была не компиляция, а загрузка зависимостей."""

TRANSCRIPT = "\n".join(
    f"Спикер {1 + i % 2}: Ну вот, коллеги, я, значит, хочу сказать, что, короче, у нас тут {i} задач, и мне кажется, это ок, да."
    for i in range(1, 60)
)

STRATEGIES = list(load_strategies().values())


def _all_sentences_once(deck: F.ProseDeck, text: str) -> None:
    body = [s for p in text.split("\n\n")[1:] for s in F.sentences(p)]
    shown = [x for sl in deck.slides for x in sl.lines] + [sl.title for sl in deck.slides] + [deck.subtitle]
    for s in body:
        key = H.strip_end(s)
        assert any(key in x or H.strip_end(x) == key for x in shown + [x for sl in deck.slides for x in sl.notes]), s


# ------------------------------------------------------------------ the layout


def test_a_report_is_laid_out_whole_sections_as_slides_cover_as_written():
    d = F.prose_deck(REPORT)
    assert d is not None
    assert d.title == "Переход склада на электронные накладные: итоги полугодия"
    titles = [s.title for s in d.slides]
    for label in ("Исходная точка", "Что сделали", "Результаты", "Что предлагаем"):
        assert label in titles
    assert d.in_notes == 0
    _all_sentences_once(d, REPORT)
    # every slide holds what every variant shows whole
    assert all(sum(len(x) + 1 for x in s.lines) <= F.PROSE_MAX_CHARS for s in d.slides)
    assert len(d.sentences) == len(set(d.sentences))


def test_the_line_that_says_where_the_talk_is_given_is_the_covers_subtitle_never_its_title():
    d = F.prose_deck(TALK)
    assert d.title == "Как мы сократили время сборки мобильного приложения в 3 раза"
    assert d.subtitle.startswith("Доклад на конференции")
    assert all("Мобильная разработка" not in s.title for s in d.slides)
    # «Главный урок: …» — its label heads the slide, the sentence stays whole under it
    lesson = next(s for s in d.slides if s.title == "Главный урок")
    assert lesson.lines[0].startswith("Главный урок: прежде чем покупать")


def test_a_long_section_goes_on_over_more_slides_never_cut():
    text = "Итоги года\n\n" + "Финансы. " + " ".join(
        f"Показатель номер {i} за год изменился с {i * 10} до {i * 12} млн рублей, и это заметно повлияло на план работ отдела." for i in range(1, 13))
    d = F.prose_deck(text)
    assert d is not None and len(d.slides) >= 3
    assert d.slides[0].title == "Финансы"
    assert all(s.lines for s in d.slides)
    assert sum(len(s.lines) for s in d.slides) == 12  # the label heads the first slide; 12 sentences, each once


def test_the_persons_slide_count_is_kept_and_the_rest_goes_to_the_notes_said_so():
    d = F.prose_deck(REPORT, 4)
    assert d.size == 4
    total = sum(len([x for x in s.lines if not x.startswith("### ")]) for s in d.slides) + d.in_notes
    assert total >= len(d.sentences) - 6  # (labels of merged sections are subheadings, not sentences)
    if d.in_notes:
        assert "[Заметки докладчика:" in d.text()
    more = F.prose_deck(REPORT, 12)  # more slides than the sections: the fullest are split, each sentence whole
    assert more.size == 12 and more.in_notes == 0


def test_a_request_line_is_no_content_and_a_transcript_is_condensed():
    d = F.prose_deck("Сделай презентацию по этому тексту на 6 слайдов.\n\n" + REPORT)
    assert d is not None and d.preamble and d.title.startswith("Переход склада")
    assert all("Сделай презентацию" not in x for s in d.slides for x in s.lines)
    assert F.prose_deck(TRANSCRIPT) is None
    assert F.prose_deck("Слайд 1. Обложка\nНазвание: X\n\nСлайд 2. Y\nТекст.") is None


# ------------------------------------------------------------------ headings that never spoil the text


@pytest.mark.parametrize(
    "sentence, words, must",
    [
        ("Увольнения в первые три месяца снизились с 14 % до 9 %.", 9, "с 14 % до 9 %"),
        ("Доля брошенных поисков снизилась с 20 % до 4 %.", 8, "с 20 % до 4 %"),
        ("Время до первого доступа сократилось с 2,5 дня до 2 часов в среднем по всей компании.", 10, "до 2 часов"),
    ],
)
def test_a_shortened_heading_keeps_the_figure_with_its_unit(sentence, words, must):
    got = H.short(sentence, words)
    assert must in got
    assert H.cut_ok(sentence, got)


def test_a_heading_never_cuts_a_formula_or_a_list_of_figures():
    s = "Сравните время работы с вариантом за O(V²) на графах из 1 000, 10 000 и 100 000 вершин."
    for got in (H.short(s, 13), headline_of(s)):
        assert not got.endswith("из 1 000")
        assert got.count("(") == got.count(")")
    assert not H.cut_ok("Улучшаем d(B) до 1 + 2 = 3.", "Улучшаем d(B")
    assert not H.cut_ok("Улучшаем d(B) до 1 + 2 = 3.", "Улучшаем d(B) до 1 +")
    assert not H.cut_ok("Снизились с 14 % до 9 %.", "Снизились с 14 % до 9")
    assert not H.cut_ok("Снизились с 14 % до 9 %.", "Снизились с 14 %")
    assert H.cut_ok("Снизились с 14 % до 9 % за год.", "Снизились с 14 % до 9 %")
    assert headline_of("Увольнения в первые три месяца снизились с 14 % до 9 % за год работы новой программы адаптации сотрудников.").count("%") in (0, 2)


def test_short_heading_takes_the_authors_own_phrase():
    assert F.short_heading("Главный урок: прежде чем покупать железо, измерьте, на что уходит время.") == "Главный урок"
    assert F.short_heading("Первая волна — 64 некритичных сервиса: тестовые стенды, вики.") == "Первая волна"
    assert F.short_heading("Затраты выросли с 52 до 58 млн рублей, но в них теперь входит резервное копирование всех систем компании.") == \
        "Затраты выросли с 52 до 58 млн рублей"


# ------------------------------------------------------------------ the check


def _deck(*slides: OutlineSlide) -> DeckOutline:
    return DeckOutline(title="T", slides=list(slides))


def test_the_check_counts_sentences_on_slides_in_notes_and_lost():
    a = "Ошибки отгрузки снизились с 312 до 58 за полугодие."
    b = "Сканеры штрихкодов выдали всем сменам."
    c = "Претензии клиентов сократились на 70 %."
    s1 = OutlineSlide(id="s1", kind=K.bullets, headline="Результаты", content=SlideContent(bullets=[a]), notes=f"{a}\n\n{b}")
    cov = F.outline_coverage(_deck(s1), [a, b, c])
    assert cov.on_slides == 1 and cov.in_notes == [b] and cov.lost == [c]
    assert "70%" in cov.figures_lost
    # a sentence stated as a card of its figures under its label counts as shown; words spread over other cards never do
    d = "Доступность сервисов за квартал составила 99,95 % против 99,6 % год назад."
    card = OutlineSlide(id="s2", kind=K.big_number, headline="Надёжность",
                        content=SlideContent(numbers=[{"value": "99,6% → 99,95%", "label": "Доступность сервисов за квартал"}]))
    assert F.outline_coverage(_deck(card), [d]).on_slides == 1
    e = "Команда из 11 человек тратила 60 % времени на поддержку железа."
    spread = OutlineSlide(id="s3", kind=K.cards, headline="Люди", content=SlideContent(items=[
        SlideItem(title="", text="Из 11 человек команды семь прошли обучение."),
        SlideItem(title="", text="Доля времени на поддержку железа упала с 60 % почти до нуля.")]))
    assert F.outline_coverage(_deck(spread), [e]).on_slides == 0


def test_a_sentence_taken_off_its_slide_goes_back_and_a_lost_one_to_the_notes():
    a = "Реализуйте алгоритм на Python."
    b = "Сравните время работы на графах из 1 000, 10 000 и 100 000 вершин."
    c = "Срок сдачи — до следующей лекции."
    s = OutlineSlide(id="s1", kind=K.bullets, headline="Домашнее задание", content=SlideContent(bullets=[a, c]), notes=f"{a}\n\n{b}\n\n{c}")
    o = _deck(s)
    cov = F.outline_coverage(o, [a, b, c, "Совсем другая фраза о погоде."])
    assert F.restore_on_slides(o, cov) == 1
    assert o.slides[0].content.bullets == [a, b, c]  # in the author's order
    assert F.keep_lost(o, cov) == 1 and "Из текста автора: Совсем другая фраза" in o.slides[0].notes


# ------------------------------------------------------------------ the agent, no model


def test_without_a_model_every_variant_shows_every_sentence_of_the_report():
    events: list = []
    res = run_agent(parse_brief_text(REPORT), None, STRATEGIES, progress=events.append)
    d = F.prose_deck(REPORT)
    assert res is not None and res.outlines
    for name, o in res.outlines.items():
        cov = F.outline_coverage(o, d.sentences)
        assert cov.lost == [] and cov.in_notes == [], (name, cov.line())
        assert o.title.startswith("Переход склада на электронные накладные")
        assert any("Проверка текста автора" in x for x in o.agent_log)
    assert any("готовый текст автора" in (e.get("message") or "") for e in events)
