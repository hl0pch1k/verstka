"""Финальная ночь 20.10 — корни из отчёта жюри (смысл колоды):

- длинный документ (стенограмма в DOCX) — материал, а не план: колода 10–15 слайдов его смысла, без разговорной речи
  (R13: 159 слайдов «Денис, Господи, я, блин, формат PTX»), с моделью и без неё;
- число слайдов, заданное человеком диапазоном («6–8 слайдов», «слайдов 8–10»), соблюдается; колода планировщика —
  не больше 15 слайдов;
- исправление факта принимается только с подтверждением источником; сравнение «в несколько раз» — только если источник
  говорит так же; «1 мая» — дата, а не подпись счёта;
- без модели три варианта различаются формой; финал — вывод или просьба, не «Спасибо за внимание»; пункт плана с
  содержанием — содержательный слайд, а не пустой «Раздел»; придуманная цифра «2 · Этап» — не ключевая.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from verstka.planning import digest as DG
from verstka.planning.agent import run_agent
from verstka.planning.brief import parse_brief_text, slide_range
from verstka.planning.directives import strip_count_phrase
from verstka.planning.meaning import _counted, cap_slides, close_story, diversify_variants, label_figures
from verstka.planning.strategies import load_strategies
from verstka.planning.topic_writer import FactIssue, TopicSlide, ref_weigh_fixes, unbacked_comparisons
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import Brief, DeckOutline, NumberCallout, OutlineSlide, SlideContent

SPEECH = ("Итак, добрый день, уважаемые участники. Ну вот, блин, слышно меня? Господи, я, короче, сейчас расскажу. "
          "Всё, я могу. Спасибо, коллеги, поднимите руку в телемосте и включите микрофон.")
FACTS = [
    "Решения сдают до 30 сентября, техническая экспертиза идёт с 30 сентября до 14 октября.",
    "С 15 по 20 октября команды дорабатывают решения по замечаниям экспертов.",
    "Сервис должен генерировать презентацию в шаблоне заказчика по текстовому описанию.",
    "Разрешены только модели с открытыми весами до 35 млрд параметров.",
    "Для изображений можно взять отдельную модель до 20 млрд параметров.",
    "Экспорт нужен в PPTX, а также в PDF и HTML.",
    "Колода обычно содержит от 10 до 15 слайдов.",
    "Главный критерий оценки — соответствие решения постановке задачи.",
    "Аудит и прослеживаемость результата обязательны для каждого слайда.",
    "Итог: команды показывают работающий сервис и скринкаст до 5 минут.",
]


def _transcript() -> str:
    out = ["Бизнес 4. VK Tech_1.mp4", "", "Сессия вопросов и ответов в рамках проекта «Лидеры цифровой трансформации 2026»."]
    for fact in FACTS:
        for _ in range(3):
            out += ["", f"{SPEECH} Ну, это самое, понимаете, вопрос хороший?"]
        out += ["", f"{SPEECH} {fact}"]
    return "\n".join(out)


def _all_text(o: DeckOutline) -> str:
    bits = []
    for s in o.slides:
        c = s.content
        bits += [s.headline, s.subtitle or "", *c.bullets, *c.paragraphs]
        bits += [x for it in [*c.items, *c.columns] for x in (it.title, it.text, *it.bullets)]
        bits += [f"{n.value} {n.label}" for n in c.numbers]
    return " ".join(bits)


# ------------------------------------------------------------------ a long document is material


def test_a_transcript_is_a_long_document_and_a_plan_is_not():
    assert DG.is_long_document(_transcript())
    assert not DG.is_long_document("Слайд 1. Итоги\n" + _transcript())  # the author dictates the slides
    assert not DG.is_long_document("Нужна презентация про склад.\n\n- отгрузки\n- ошибки\n- просьба")


def test_the_rules_digest_keeps_the_facts_and_never_the_speech():
    d = DG.digest_by_rules(_transcript())
    assert d is not None and DG.MIN_SLIDES <= d.size <= DG.DEFAULT_SLIDES
    text = d.text()
    assert text.startswith("Слайд 1. Обложка\nНазвание: Лидеры цифровой трансформации 2026")
    for bad in ("блин", "Господи", "Всё, я могу", "слышно", "микрофон", "добрый день", "?"):
        assert bad not in text, bad
    assert "30 сентября" in text and "35 млрд" in text
    for s in d.slides:
        assert len(s.title.split()) <= DG.HEAD_WORDS + 1 and s.points


def test_the_person_s_count_sizes_the_digest():
    d = DG.digest_by_rules(_transcript(), 6)
    assert d is not None and d.size <= 6


def test_the_model_digest_loses_a_figure_the_document_does_not_state_and_spoken_lines():
    ans = DG.DigestAnswer(title="Хакатон: требования и сроки", slides=[
        DG.DigestSlideAnswer(title="Решения сдают до 30 сентября", points=["Экспертиза — с 30 сентября до 14 октября", "Призовой фонд — 5 млн ₽"]),
        DG.DigestSlideAnswer(title="Ну вот, блин, модели", points=["Только открытые веса до 35 млрд параметров"]),
        DG.DigestSlideAnswer(title="Экспорт в PPTX, PDF и HTML", points=["Колода — от 10 до 15 слайдов"]),
        DG.DigestSlideAnswer(title="Главное — соответствие постановке", points=["Скринкаст до 5 минут"]),
    ])
    d = DG.check_answer(ans, _transcript(), 12)
    assert d is not None and d.by == "model"
    text = d.text()
    assert "5 млн ₽" not in text and "блин" not in text
    assert "Только открытые веса до 35 млрд параметров" in text  # the spoken title gave way to its point


def test_the_model_digest_is_used_when_the_model_answers():
    ans = DG.DigestAnswer(title="Хакатон", slides=[DG.DigestSlideAnswer(title=t, points=[FACTS[k]]) for k, t in enumerate(
        ["Сроки сдачи жёсткие", "Доработка идёт после экспертизы", "Сервис работает по описанию", "Модели только открытые",
         "Картинки рисует отдельная модель", "Экспорт в три формата"])])
    skills = SimpleNamespace(run=lambda name, providers, variables: SimpleNamespace(parsed=ans))
    providers = SimpleNamespace(has=lambda role: role == "llm")
    d = DG.digest(_transcript(), None, skills=skills, providers=providers)
    assert d is not None and d.by == "model" and d.size == 7


def test_a_long_transcript_without_a_model_is_a_deck_of_its_meaning_in_every_variant():
    st = load_strategies()
    res = run_agent(Brief(text=_transcript()), None, [st[n] for n in ("structured", "visual", "compact")])
    assert res is not None and res.outlines
    for name, o in res.outlines.items():
        assert 4 <= len(o.slides) <= 15, (name, len(o.slides))
        text = _all_text(o)
        for bad in ("блин", "Господи", "Всё, я могу"):
            assert bad not in text, (name, bad)
        assert any("длинный документ" in x for x in o.agent_log), name


def test_a_letter_of_more_parts_than_a_deck_has_slides_is_no_plan():
    body = "\n\n".join(f"Потом {FACTS[k % len(FACTS)][0].lower()}{FACTS[k % len(FACTS)][1:]}" for k in range(24))
    st = load_strategies()
    res = run_agent(Brief(text="Подготовь, пожалуйста, слайды к встрече.\n\n" + body), None, [st["structured"]])
    o = res.outlines["structured"]
    assert len(o.slides) <= 15


# ------------------------------------------------------------------ the deck's size


def test_a_range_of_slides_is_read_as_its_upper_bound():
    assert parse_brief_text("Коротко для команды. 6–8 слайдов.").slide_count == 8
    assert parse_brief_text("Для операционного директора, слайдов 8–10.").slide_count == 10
    assert parse_brief_text("---\nslides: 6-8\n---\nТекст").slide_count == 8
    assert slide_range("В 2023–2024 годах выручка росла") is None
    assert parse_brief_text("Слайды 3-5 про рынок, остальное как обычно").slide_count is None
    assert parse_brief_text("Пояснение по 2–3 слайдам: какие данные были на входе.").slide_count is None  # (jury R04 PDF)


def _long_deck(n: int, sections: int = 0) -> DeckOutline:
    slides = [OutlineSlide(id="c", kind=K.title, headline="Итоги")]
    for k in range(n):
        if k < sections:
            slides.append(OutlineSlide(id=f"s{k}", kind=K.section, headline=f"Раздел {k}"))
        else:
            slides.append(OutlineSlide(id=f"b{k}", kind=K.bullets, headline=f"Вывод {k}", content=SlideContent(bullets=["слово " * (k + 1)])))
    slides.append(OutlineSlide(id="z", kind=K.bullets, headline="Просим утвердить бюджет", content=SlideContent(bullets=["Бюджет 5 млн ₽"])))
    return DeckOutline(title="Итоги", slides=slides)


def test_a_deck_over_its_size_loses_dividers_first_then_the_thinnest_never_the_cover_or_the_ask():
    o = _long_deck(16, sections=3)
    said = cap_slides(o, 14)
    assert len(o.slides) == 14 and said
    assert o.slides[0].id == "c" and o.slides[-1].id == "z"
    assert not any(s.kind == K.section for s in o.slides)
    assert "b3" not in {s.id for s in o.slides}  # the thinnest content slide went


def test_the_author_s_dictated_slides_are_never_dropped():
    o = _long_deck(10)
    for s in o.slides[1:]:
        s.spec_ref = 1
    cap_slides(o, 5)
    assert len(o.slides) == 12


def test_the_slide_count_never_stays_on_the_cover():
    assert strip_count_phrase(", слайдов 8–10 · Доля обращений Q3 2026 по каналам") == "Доля обращений Q3 2026 по каналам"
    assert strip_count_phrase("Закрытие 3 квартала по службе поддержки — , слайдов 8–10") == "Закрытие 3 квартала по службе поддержки"
    assert strip_count_phrase("Слайд 3 о рынке") == "Слайд 3 о рынке"


# ------------------------------------------------------------------ the deck ends on its point


def _with_farewell(last_headline: str) -> DeckOutline:
    return DeckOutline(title="Итоги", slides=[
        OutlineSlide(id="c", kind=K.title, headline="Итоги"),
        OutlineSlide(id="a", kind=K.bullets, headline="Выручка выросла на 12%", content=SlideContent(bullets=["Выручка 120 млн ₽"])),
        OutlineSlide(id="b", kind=K.bullets, headline=last_headline, content=SlideContent(bullets=["Бюджет 5 млн ₽ на найм"])),
        OutlineSlide(id="z", kind=K.thanks, headline="Спасибо за внимание"),
    ])


def test_a_farewell_after_the_ask_is_no_slide():
    o = _with_farewell("Просим утвердить бюджет")
    close_story(o, "Итоги квартала. Просим утвердить бюджет.")
    assert [s.id for s in o.slides] == ["c", "a", "b"]


def test_a_farewell_carries_the_ask_and_never_says_thanks():
    o = _with_farewell("Найм идёт по плану")
    close_story(o, "Итоги квартала. Просим утвердить бюджет 5 млн ₽ на найм.")
    last = o.slides[-1]
    assert "Спасибо" not in (last.headline + (last.subtitle or ""))


def test_the_author_s_own_farewell_stays():
    o = _with_farewell("Найм идёт по плану")
    close_story(o, "Слайд 3: Спасибо за внимание!")
    assert o.slides[-1].headline == "Спасибо за внимание"


# ------------------------------------------------------------------ facts


def _slides() -> list[TopicSlide]:
    return [TopicSlide(title="Глубина", points=[
        "На Земле только два водоёма глубже 1000 м: озеро Танганьика (1470 м) и Каспийское море (1025 м).",
        "Объём воды Байкала превышает объём пяти Великих озёр в несколько раз.",
        "Байкал — самое глубокое озеро на планете.",
    ])]


REF = ["Байкал — самое глубокое озеро на планете, его глубина 1642 м. Второе по глубине — Танганьика (1470 м), "
       "затем Каспийское море (1025 м). Объём воды больше, чем во всех пяти Великих озёрах вместе взятых."]


def test_a_correction_the_reference_does_not_back_is_not_applied():
    issues = [FactIssue(id="s2.p1", problem="Caspian is saline",
                        fix="На Земле только два пресных водоёма глубже 1000 м: озеро Танганьика (1470 м) и озеро Малави (706 м).")]
    assert ref_weigh_fixes(_slides(), issues, REF) == []  # the reference states the original: it stays


def test_a_correction_without_any_reference_drops_the_disputed_statement():
    issues = [FactIssue(id="s2.p1", problem="x", fix="Глубже 1000 м — только Танганьика и Малави (706 м).")]
    got = ref_weigh_fixes(_slides(), issues, [])
    assert len(got) == 1 and got[0].fix == ""


def test_a_backed_correction_stays():
    issues = [FactIssue(id="s2.p1", problem="x", fix="Глубже 1000 м — Танганьика (1470 м) и Каспийское море (1025 м).")]
    assert ref_weigh_fixes(_slides(), issues, REF) == issues


def test_a_comparison_the_reference_does_not_make_goes_and_a_backed_one_stays():
    slides = _slides()
    gone = unbacked_comparisons(slides, REF)
    assert [g["id"] for g in gone] == ["s2.p2"]
    assert any("самое глубокое" in p for p in slides[0].points)
    assert not any("несколько раз" in p for p in slides[0].points)


def test_a_date_is_no_count():
    assert _counted("1", "Река вытекает из озера", "Закон принят 1 мая 1999 года.") is None


def test_a_small_figure_the_brief_never_writes_is_no_key_figure():
    o = DeckOutline(title="Т", slides=[OutlineSlide(id="a", kind=K.big_number, headline="Второй этап — интерпретация данных",
                                                    content=SlideContent(numbers=[NumberCallout(value="2", label="Этап хакатона")], bullets=["Особое внимание — интерпретации данных."]))])
    label_figures(o, "1. Что сделать\n\nНа втором этапе будем обращать особое внимание на интерпретацию данных.\n\n2. Требования, 2–3 варианта")
    assert o.slides[0].content.numbers == []
    lone = DeckOutline(title="Т", slides=[OutlineSlide(id="a", kind=K.big_number, headline="Второй этап — интерпретация данных", takeaway="Особое внимание — интерпретации данных",
                                                       content=SlideContent(numbers=[NumberCallout(value="2", label="Этап хакатона")]))])
    label_figures(lone, "На втором этапе будем обращать особое внимание на интерпретацию данных.")
    assert lone.slides[0].content.numbers == [] and lone.slides[0].kind == K.bullets and lone.slides[0].content.paragraphs


# ------------------------------------------------------------------ three variants without a model


WAREHOUSE = """Подготовь, пожалуйста, слайды к планёрке по складу в Подольске за сентябрь.
Сначала — сколько отгрузили: 48 200 заказов, на 12% больше, чем в августе.
Потом сравни скорость сборки: в Подольске 3,1 часа на заказ, в Казани 2,4 часа.
Ошибки комплектации: 0,8% заказов, цель — не больше 0,5%.
Сделай воронку заказов: поступило 51 000, собрано 49 300, отгружено 48 200, доставлено вовремя 45 900.
Главная проблема — ночная смена: на неё приходится 61% ошибок при 35% объёма.
Предлагаю перевести ночную смену на сканеры с проверкой и добавить 6 кладовщиков, это 2,9 млн рублей в год.
"""


def test_without_a_model_the_three_variants_differ_in_form():
    st = load_strategies()
    res = run_agent(parse_brief_text(WAREHOUSE), None, [st[n] for n in ("structured", "visual", "compact")])
    s, v, c = (res.outlines[n] for n in ("structured", "visual", "compact"))

    def sig(o):
        return [(x.kind.value, x.headline) for x in o.slides]

    assert sig(s) != sig(v) and sig(s) != sig(c) and sig(v) != sig(c)
    assert any(x.kind == K.big_number and re.search(r"\d", x.headline) for x in v.slides)  # a conclusion heads the figure
    assert len(c.slides) < len(s.slides)


def test_diversify_leaves_variants_that_already_differ():
    a = _long_deck(3)
    b = _long_deck(3)
    b.slides[1].kind = K.cards
    b.slides[2].kind = K.cards
    b.slides[3].kind = K.cards
    assert diversify_variants({"structured": a, "visual": b}) == {}


def test_a_point_of_the_plan_with_its_content_is_no_section():
    st = load_strategies()
    plan = ("Нужна презентация для операционного директора.\n\n- как менялось число обращений за год\n- откуда приходят обращения\n"
            "- главное узкое место — вторая линия, нагрузка растёт, а людей столько же\n- что просим: 6 человек на вторую линию")
    res = run_agent(parse_brief_text(plan), None, [st["structured"]])
    o = res.outlines["structured"]
    hit = [x for x in o.slides if "узкое место" in x.headline.lower() or "вторая линия" in _all_text(DeckOutline(title="", slides=[x])).lower()]
    assert hit and all(x.kind != K.section for x in hit)
