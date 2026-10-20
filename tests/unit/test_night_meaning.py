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
        assert len(s.title.split()) <= DG.HEAD_WORDS + 4 and s.points


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
        assert 3 <= len(o.slides) <= 15, (name, len(o.slides))
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


# ------------------------------------------------------------------ round 2: without any model


ARTICLE = """Байка́л (бур. Байгал далай) — озеро тектонического происхождения в южной части Восточной Сибири площадью 31 722 км². Самое глубокое озеро на планете, крупнейший природный резервуар пресной воды.

== Название ==
Название озера объясняется обычно через тюркское baiköl «богатое озеро», и это слово встречается в разных языках региона.

== География ==
Максимальная глубина Байкала — 1642 м, средняя — 744,4 м. В озеро впадают 336 рек, вытекает одна — Ангара. Байкал замерзает целиком с января по май, толщина льда достигает 1 м. Площадь водосборного бассейна составляет 571 тысячу км², и он лежит на территории двух стран.

== Растительный и животный мир ==
В Байкале обитают 2600 видов животных, больше половины из них эндемики. Самый известный эндемик — байкальская нерпа, единственный пресноводный тюлень. Здесь живут голомянки и омуль, которых нет больше нигде на Земле в таком числе.

== Экология ==
В 1996 году Байкал включён в список Всемирного наследия ЮНЕСКО. В 2013 году закрыт Байкальский целлюлозно-бумажный комбинат, главный источник загрязнения. Закон об охране озера Байкал принят 1 мая 1999 года и действует до сих пор.

== Примечания ==
1. Ссылка на источник один и ещё много слов, которые не нужны на слайдах никогда вообще.
"""


def test_a_topic_article_is_digested_by_its_sections_with_the_topic_on_the_cover():
    page = SimpleNamespace(title="Байкал", url="https://ru.wikipedia.org/wiki/Байкал", text=ARTICLE)
    d = DG.page_digest(page, 6, "Озеро Байкал")
    assert d is not None and d.title == "Озеро Байкал" and d.source["title"] == "Байкал"
    text = d.text()
    assert "Подзаголовок: По статье «Байкал» из Википедии" in text
    assert "1642 м" in text and "2600 видов" in text and "Примечани" not in text and "Ссылка на источник" not in text
    assert "бур." not in text and "Байкал — озеро тектонического происхождения" in text
    assert 4 <= d.size <= 6


def test_a_topic_without_a_model_and_without_an_article_says_so_and_never_shows_the_request():
    st = load_strategies()
    res = run_agent(parse_brief_text("Сделай презентацию про озеро Байкал"), None, [st["structured"]])  # (tests have no network)
    o = res.outlines["structured"]
    text = _all_text(o)
    assert "Сделай презентацию" not in text
    assert o.slides[0].headline == "Озеро Байкал"
    assert "модель недоступна" in text.lower() and all(s.kind != K.section for s in o.slides)


def test_a_page_long_document_without_a_model_is_a_deck_of_all_its_parts():
    parts = [f"{k}. {h}: {t}" for k, (h, t) in enumerate([
        ("Профилирование данных", "типы колонок, временная ось, количество измерений и метрик, пропуски и выбросы."),
        ("Аналитическая задача", "динамика, сравнение категорий, структура долей, распределение, взаимосвязь величин."),
        ("Выбор визуализации", "ранжированный список из 2–3 вариантов с объяснением, основанным на свойствах данных."),
        ("Дизайн-система", "палитра, шрифты, сетка, стиль осей и легенды берутся из разобранного шаблона."),
        ("Вёрстка слайда", "заголовок-вывод, подписи осей, единицы измерения и источник данных на каждом слайде."),
        ("Сложные случаи", "при избыточном объёме данных — разбиение на несколько слайдов или агрегация данных."),
        ("Брендбук", "при конфликте шаблона и брендбука приоритет у брендбука, если пользователь не указал иное."),
        ("Ограничения", "жёсткое соответствие формата файла и типа графика не допускается в решении."),
        ("Результат", "презентация в PPTX, PDF или HTML, которая открывается без ручных правок."),
        ("Скринкаст", "до 5 минут: загрузка шаблона, запуск генерации, пояснение по двум-трём слайдам."),
    ], 1)]
    text = "Вторая ступень хакатона: интерпретация данных\n\n" + "\n\n".join(p + " Это требование обязательно для сервиса и проверяется экспертами на защите решения." for p in parts)
    assert DG.is_document(text) and not DG.is_long_document(text)
    st = load_strategies()
    res = run_agent(Brief(text=text), None, [st["structured"]])
    o = res.outlines["structured"]
    assert 8 <= len(o.slides) <= 15, len(o.slides)
    shown = _all_text(o)
    for word in ("Профилирование", "Брендбук", "Скринкаст"):
        assert word.lower() in shown.lower(), word


def test_a_slide_count_is_never_a_line_or_a_figure():
    from verstka.planning.directives import clean_text
    from verstka.planning.writer import writer_mode

    assert clean_text("Коротко для команды. 6–8 слайдов.") == "Коротко для команды."
    assert writer_mode("Коротко для руководителей: что такое облачные вычисления. 7 слайдов.").kind == "topic"
    o = DeckOutline(title="Т", slides=[OutlineSlide(id="a", kind=K.big_number, headline="Коротко для команды",
                                                    content=SlideContent(numbers=[NumberCallout(value="6–8", label="слайдов")], bullets=["Требования второй ступени."]))])
    from verstka.planning.meaning import sensible_labels

    sensible_labels(o, "Коротко для команды. 6–8 слайдов.")
    assert o.slides[0].content.numbers == []


def test_the_request_s_subject_without_what_it_says_to_the_planner():
    from verstka.knowledge.compose import request_subject

    assert request_subject("Коротко для команды: что организаторы требуют на второй ступени хакатона. 6–8 слайдов.") == "что организаторы требуют на второй ступени хакатона"


def test_key_figures_say_what_they_are():
    from verstka.planning.meaning import sensible_labels

    o = DeckOutline(title="t", slides=[
        OutlineSlide(id="a", kind=K.stat_row, headline="48 200 заказов, на 12% больше, чем в августе",
                     content=SlideContent(numbers=[NumberCallout(value="48 200", label="Заказов"), NumberCallout(value="12%", label="Больше")])),
        OutlineSlide(id="b", kind=K.stat_row, headline="0,8% заказов, цель — не больше 0,5%", section="Ошибки комплектации",
                     content=SlideContent(numbers=[NumberCallout(value="0,8%", label="Заказов"), NumberCallout(value="0,5%", label="Цель")])),
        OutlineSlide(id="c", kind=K.stat_row, headline="Кампания шла с 1 сентября по 15 октября",
                     content=SlideContent(numbers=[NumberCallout(value="15", label="Кампания"), NumberCallout(value="12 млн ₽", label="Бюджет")])),
        OutlineSlide(id="d", kind=K.stat_row, headline="Что нужно сделать",
                     content=SlideContent(numbers=[NumberCallout(value="5–7", label="Датасетов"), NumberCallout(value="200", label="Строк")])),
    ])
    sensible_labels(o, "")
    got = [[(n.value, n.label) for n in s.content.numbers] for s in o.slides]
    assert got[0][1] == ("12%", "Больше, чем в августе")
    assert got[1][0] == ("0,8%", "Ошибки комплектации")
    assert got[2] == [("12 млн ₽", "Бюджет")]
    assert ("200", "Строк") not in got[3]


def test_the_author_s_points_come_back_when_a_form_left_them_out():
    from verstka.planning.meaning import keep_author_points

    brief = ("Слайд 1: Деньги. Выручка от подписок за месяц — 18,6 млн рублей.\n\n"
             "Слайд 2: Что дальше. В ноябре — ускорить синхронизацию в 2 раза и выпустить тёмную тему, в декабре — семейная подписка.")
    o = DeckOutline(title="t", slides=[OutlineSlide(id="a", kind=K.big_number, headline="Что дальше", spec_ref=2,
                                                    content=SlideContent(numbers=[NumberCallout(value="×2", label="В ноябре ускорить синхронизацию")]))])
    keep_author_points(o, brief)
    assert any("тёмную тему" in b and "семейная подписка" in b for b in o.slides[0].content.bullets)


# ------------------------------------------------------------------ a digest's titles are finished thoughts


def test_a_digest_title_is_a_finished_thought_never_a_sentence_cut_off():
    cases = {
        "В 1959—1962 годах уровень озера вырос на 1,2 м в связи с подпором уровня воды плотиной Иркутской ГЭС.":
            "В 1959—1962 годах уровень озера вырос на 1,2 м",
        "Обязательное дополнение — скринкаст работы сервиса (до 5 минут), где показано:": "Обязательное дополнение — скринкаст работы сервиса",
        "2021 год объявлен Годом Байкала в Иркутской области в соответствии с Указом Губернатора Иркутской области № 256-уг от 9 сентября 2020 года.":
            "2021 год объявлен Годом Байкала",
        "Вёрстка слайда: заголовок-вывод («Продажи выросли на 23% к декабрю», а не «Продажи по месяцам»), подписи осей, единицы измерения, источник данных.":
            "Вёрстка слайда: заголовок-вывод, подписи осей, единицы измерения, источник данных",
        "Байкал (бур. Байгал далай) — озеро тектонического происхождения в южной части Восточной Сибири площадью 31 722 км².":
            "Байкал — озеро тектонического происхождения в южной части Восточной Сибири площадью 31 722 км²",
    }
    for sentence, title in cases.items():
        assert DG.headline_of(sentence) == title, sentence
    for sentence in ["Тайминг на хокатоне, потому что есть целый блок вопросов, связанных с тем, когда дедлайн, когда происходит экспертиза данных работ.",
                     "С 2010 года ведётся строительство нейтринного телескопа НТ1000 с эффективным объёмом 1 км3, строительство которого предполагалось завершить не ранее 2017 года."]:
        t = DG.headline_of(sentence)
        last = t.split()[-1].lower().strip(",.;:")
        assert last not in DG._TAIL_BAD and DG._balanced(t) and len(t.split()) <= DG.HEAD_WORDS + 4, t
    assert DG.headline_of("Сложные случаи при избыточном объёме данных и при нетипизируемых данных, когда график нечитаем и нужен совсем другой вид.",
                          fallback="Сложные случаи") == "Сложные случаи"


# ------------------------------------------------------------------ round 3


def test_a_pitch_is_named_after_its_product_never_presentation():
    from verstka.planning.plan_form import as_slides

    text = ("Привет! Нужен питч нашего стартапа для инвесторов на демо-дне, 8–10 слайдов.\n\n"
            "1. Проблема: малый бизнес теряет до 30% заявок ночью.\n"
            "2. Решение: «Ответ24» — ИИ-ассистент, который отвечает клиентам за 5 секунд.\n"
            "3. Просим: 120 млн рублей на 18 месяцев.\n")
    p = as_slides(text)
    assert p.title == "Ответ24" and p.subtitle.startswith("Питч стартапа")
    assert "Привет" not in p.text
    from verstka.planning.meaning import name_cover

    o = DeckOutline(title="Презентация", slides=[OutlineSlide(id="c", kind=K.title, headline="Презентация")])
    name_cover(o, text)
    assert o.slides[0].headline == "Ответ24"


def test_series_of_different_units_never_share_an_axis():
    from verstka.planning.meaning import split_mixed_units
    from verstka.schemas.outline import ChartSpec, InlineSeries

    o = DeckOutline(title="t", slides=[OutlineSlide(id="a", kind=K.chart, headline="h", content=SlideContent(chart=ChartSpec(
        type="column", categories=["Q1", "Q2", "Q3"], series=[InlineSeries(name="Выручка, млн ₽", values=[301, 349, 412]), InlineSeries(name="Клиенты", values=[980, 1105, 1240])])))])
    split_mixed_units(o)
    assert o.slides[0].content.chart.split
    o2 = DeckOutline(title="t", slides=[OutlineSlide(id="a", kind=K.chart, headline="h", content=SlideContent(chart=ChartSpec(
        type="column", categories=["Q1", "Q2"], series=[InlineSeries(name="План", values=[1, 2]), InlineSeries(name="Факт", values=[1, 3])])))])
    split_mixed_units(o2)
    assert not o2.slides[0].content.chart.split


def test_a_table_of_periods_says_how_the_total_moved():
    from verstka.planning.meaning import table_conclusions
    from verstka.schemas.outline import TableData

    t = TableData(columns=["Год", "Дата-центры", "Разработка", "Продажи"], rows=[["2025", "120", "80", "40"], ["2026", "180", "110", "65"], ["2027", "240", "150", "90"]])
    o = DeckOutline(title="t", slides=[OutlineSlide(id="a", kind=K.table, headline="Инвестиции по годам", content=SlideContent(table=t))])
    table_conclusions(o)
    assert o.slides[0].headline == "Инвестиции: 240 → 480 за 2025–2027 (×2)"


def test_a_heading_never_promises_more_than_the_slide_shows():
    from verstka.planning.meaning import promised_counts_kept
    from verstka.schemas.outline import SlideItem

    o = DeckOutline(title="t", slides=[
        OutlineSlide(id="a", kind=K.cards, headline="Успех оценивается по трём показателям", content=SlideContent(items=[SlideItem(title="a"), SlideItem(title="b")])),
        OutlineSlide(id="b", kind=K.bullets, headline="Выручка выросла в 2 раза за год", content=SlideContent(bullets=["a", "b", "c"]))])
    promised_counts_kept(o)
    assert [s.headline for s in o.slides] == ["Успех оценивается по показателям", "Выручка выросла в 2 раза за год"]


def test_a_topic_without_any_source_keeps_no_made_up_figure():
    from verstka.planning.topic_writer import unsourced_figures

    slides = [TopicSlide(title="Первая неделя", lead="Первая неделя — знакомство с командой и продуктом.",
                         points=["Ежедневная планёрка длится 30–40 минут.", "Наставник отвечает на вопросы новичка.", "Цель — 10 звонков в день."])]
    gone = unsourced_figures(slides, "онбординг отдела продаж: первая неделя")
    assert len(gone) == 2 and slides[0].points == ["Наставник отвечает на вопросы новичка."]


def test_a_lecture_request_is_about_its_subject_and_a_bare_count_is_the_deck_s_size():
    from verstka.planning.topic_writer import topic_subject

    assert topic_subject("Сделай лекцию для студентов первого курса про производную функции: определение, геометрический смысл") == "производную функции"
    assert parse_brief_text("Коротко: что такое облачные вычисления. 7 слайдов.").slide_count == 7


def test_a_wiki_page_loses_its_footnote_marks_and_back_matter():
    from verstka.ingest.documents import read_html

    d = read_html("x.html", "<html><body><article><h2>Модели<span class='mw-editsection'>[править | править код]</span></h2>"
                            "<p>Облачные вычисления<sup class='reference'>[4]</sup> — модель[5] (PaaS, англ. Platform as a Service).</p>"
                            "<h2>Примечания</h2><p>1. Сноска</p></article></body></html>")
    assert [(b.kind, b.text) for b in d.blocks] == [("heading", "Модели"), ("para", "Облачные вычисления — модель (PaaS, англ. Platform as a Service).")]


# ------------------------------------------------------------------ without a model: speech, two measures


def test_a_talk_s_sentence_becomes_a_statement():
    assert DG.unspeak("Мы предлагаем использовать модель класса Text Image до 20 млрд параметров.") == "Предлагаем использовать модель класса Text Image до 20 млрд параметров."
    assert DG.unspeak("В качестве решения нужно прикрепить ссылку на ваше хранилище, значит, заранее.") == "В качестве решения нужно прикрепить ссылку на хранилище, заранее."
    assert DG.unspeak("Если говорить о формальностях, то итогом решения будет сервис.") == "Итогом решения будет сервис."
    assert DG.score_sentence("Давайте, если вы хотите, посмотрим на интересный вопрос.") < 0


def test_a_table_of_two_measures_by_periods_never_adds_them_up():
    from verstka.planning.meaning import table_conclusion
    from verstka.schemas.outline import TableData

    got = table_conclusion(TableData(columns=["Квартал", "Выручка, млн ₽", "Клиенты"], rows=[["Q1 2026", "301", "980"], ["Q3 2026", "412", "1240"]]), None)
    assert got == ("Выручка: 301 → 412 млн ₽ за Q1 2026–Q3 2026 (+37%)", "Клиенты: 980 → 1 240 (+27%)")


# ------------------------------------------------------------------ round 4


def test_a_statement_that_gives_a_year_to_another_person_or_another_share_goes():
    from verstka.planning.topic_writer import source_mismatches

    paras = ["В 1684 году Лейбниц опубликовал первую работу по дифференциальному исчислению. Метод флюксий Ньютона издан в 1736 году.",
             "Байкал — крупнейший пресноводный биогеоценоз, две трети видов животных и растений эндемичны."]
    sl = [TopicSlide.model_validate({"title": "Трети видов Байкала — эндемики", "points": ["Трети видов Байкала не встречаются нигде больше.", "Две трети видов Байкала — эндемики."],
                                     "timeline": [{"when": "1684", "what": "Ньютон опубликовал трактат о методе флюксий"},
                                                  {"when": "1684", "what": "Лейбниц опубликовал работу о дифференциальном исчислении"}]})]
    gone = source_mismatches(sl, paras)
    assert {g["id"] for g in gone} == {"s2.p1", "s2.t1", "s2.title"}
    assert sl[0].title == "Две трети видов Байкала — эндемики"
    assert sl[0].points == ["Две трети видов Байкала — эндемики."] and [e.what for e in sl[0].timeline] == ["Лейбниц опубликовал работу о дифференциальном исчислении"]


def test_the_large_figure_is_the_heading_s_and_no_line_twice():
    from verstka.planning.meaning import dedupe_lines, hero_of_headline

    o = DeckOutline(title="t", slides=[OutlineSlide(id="a", kind=K.big_number, headline="Байкал вытянут на 636 км в форме полумесяца", content=SlideContent(
        numbers=[NumberCallout(value="30 км³/год", label="объём стока которой")],
        bullets=["Байкал вытянут на 636 км в форме полумесяца", "Байкал вытянут на 636 км в форме полумесяца, а его ширина от 24 до 79 км"]))])
    hero_of_headline(o)
    dedupe_lines(o)
    s = o.slides[0]
    assert not s.content.numbers and s.kind == K.bullets and s.content.bullets == ["Байкал вытянут на 636 км в форме полумесяца, а его ширина от 24 до 79 км"]


# ------------------------------------------------------------------ scenarios: what the author says to the deck


def test_what_the_author_says_to_the_deck_is_never_its_title():
    from verstka.planning.meaning import deck_title_said, title_of_request

    assert title_of_request("Нужно рассказать совету директоров про переход компании на облачную инфраструктуру. Сейчас серверы стареют.") == "Переход компании на облачную инфраструктуру"
    assert title_of_request("Слайд 1: Обложка — Итоги хакатона 2025\nСлайд 2: 412 участников") == "Итоги хакатона 2025"
    assert title_of_request("Сделай 8 слайдов, без картинок. Тема: онбординг новых сотрудников в отделе продаж.") == "Онбординг новых сотрудников в отделе продаж"
    assert title_of_request("Лекция для 10 класса: производная функции") == "Производная функции"
    o = DeckOutline(title="Сделай, без картинок", slides=[OutlineSlide(id="c", kind=K.title, headline="Сделай, без картинок")])
    deck_title_said(o, "Сделай 8 слайдов, без картинок. Тема: онбординг новых сотрудников в отделе продаж.")
    assert o.title == o.slides[0].headline == "Онбординг новых сотрудников в отделе продаж"


def test_the_author_s_count_holds_without_a_model():
    st = load_strategies()
    text = ("Сделай 8 слайдов, без картинок. Тема: онбординг новых сотрудников в отделе продаж. Первая неделя — знакомство с продуктом, "
            "вторая — работа с CRM, третья — первые звонки под присмотром наставника. Наставник закреплён на 3 месяца. Цель — выход на план за 90 дней вместо 150.")
    res = run_agent(parse_brief_text(text), None, [st["structured"]])
    o = res.outlines["structured"]
    assert len(o.slides) == 8
    assert o.slides[0].headline == "Онбординг новых сотрудников в отделе продаж"
    assert "Вторая неделя" in _all_text(o) and "без картинок" not in _all_text(o).lower()


def test_the_author_s_point_heads_the_slide_of_its_data():
    st = load_strategies()
    text = ("# Итоги найма за полугодие\n\nПокажи, что найм в разработку вырос сильнее всего.\n\n| Отдел | I полугодие 2025 | II полугодие 2025 |\n|---|---|---|\n"
            "| Разработка | 14 | 31 |\n| Продажи | 9 | 12 |\n| Поддержка | 7 | 8 |\n| Маркетинг | 3 | 4 |\n\nИсточник: HR-отчёт.\n")
    from verstka.planning.facts import basic_facts
    from verstka.planning.outline import plan_outline

    b = parse_brief_text(text)
    res = run_agent(b, None, [st["structured"]])
    o = res.outlines.get("structured") if res is not None else None
    if o is None:  # (no slides dictated, no model: the planner lays the brief out, as the pipeline does)
        o, _ = plan_outline(b, None, st["structured"], basic_facts(b.text), None, None)
    assert not any(s.kind != K.table and "Покажи" in s.headline for s in o.slides)
    tab = next(s for s in o.slides if s.content.table is not None)
    assert tab.headline == "Найм в разработку вырос сильнее всего"
    assert "14" in (tab.takeaway or "") and "31" in (tab.takeaway or "")


def test_a_heading_never_says_what_the_slide_holds():
    from verstka.planning.meaning import no_meta_lines
    from verstka.schemas.outline import TableData

    o = DeckOutline(title="t", slides=[OutlineSlide(id="a", kind=K.table, headline="Вывод: Таблица содержит производные шести основных элементарных функций",
                                                    takeaway="На слайде показаны основные производные", content=SlideContent(table=TableData(columns=["f", "f'"], rows=[["x^n", "n·x^(n-1)"]])))])
    no_meta_lines(o)
    assert o.slides[0].headline == "Производные шести основных элементарных функций" and o.slides[0].takeaway is None
    assert DG.headline_of("Правила: (u+v)' = u' + v'; (uv)' = u'v + uv'.") == "Правила: (u+v)' = u' + v'; (uv)' = u'v + uv'"


def test_a_one_line_point_of_the_author_s_plan_is_content_not_a_divider():
    st = load_strategies()
    text = "Слайд 1: Обложка — Итоги хакатона 2025\nСлайд 2: 412 участников из 37 городов\nСлайд 3: Лучшие команды и их решения\nСлайд 4: Что дальше — акселератор весной\n"
    res = run_agent(parse_brief_text(text), None, [st["structured"]])
    o = res.outlines["structured"]
    assert o.slides[0].headline == "Итоги хакатона 2025"
    assert not any(s.kind == K.section for s in o.slides)
    big = next(s for s in o.slides if s.kind == K.big_number)
    assert big.content.numbers[0].value == "412" and big.headline == "Участники" and not big.content.bullets
    best = next(s for s in o.slides if s.content.quote)
    assert best.kind == K.quote and best.content.quote == "Лучшие команды и их решения" and not best.headline
    nxt = o.slides[-1]
    assert nxt.headline == "Что дальше" and nxt.content.paragraphs == ["Акселератор весной."]
    from verstka.planning import faithful as F

    r = F.read_slide(4, "Часть 2. Решение", "")
    assert r.role == "section"
