"""Gate-4 writer defects (round 5): the storyline by what a history is the history of and the story in time order
across slides (G4-7), article sentences lifted without what they refer to and cut before their list (G4-8), a market's
part the articles do not cover and facts about somewhere else (G4-9), interpretive predicates the cited sentence does
not say (G4-10), the «Данные приблизительные» note under exact figures (G4-12). Offline: the articles are fixtures
(tests/fixtures/writer) or a few sentences written here."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from verstka.planning import writer as W
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

F = Path(__file__).resolve().parents[1] / "fixtures" / "writer"
SKILLS = SkillsRegistry.load()


@lru_cache(maxsize=None)
def ww2() -> W.Anchors:
    sup = W.ArticleSupport([(F / "ww2_full.txt").read_text(encoding="utf-8")], "Вторая мировая война")
    return W.Anchors(sup, [{"title": "Вторая мировая война", "url": "https://ru.wikipedia.org/wiki/x"}], year_now=2026, topic="Вторая мировая война")


def small(text: str, topic: str) -> W.Anchors:
    sup = W.ArticleSupport([text], topic)
    return W.Anchors(sup, [{"title": topic, "url": "https://ru.wikipedia.org/wiki/x"}], year_now=2026, topic=topic)


def idx(an: W.Anchors, pattern: str) -> int:
    return next(i for i, s in enumerate(an.support.sents) if re.search(pattern, s))


CHOC = (
    "История шоколада — история напитка и продукта из какао-бобов.\n"
    "При петербургском дворе обычай подавать по утрам чашечку шоколада ввела, по-видимому, Екатерина II. "
    "Большим гурманом и любителем шоколада был и её первый министр Никита Панин.\n"
    "В 1815 году голландский химик Конрад ван Гутен открыл фабрику в Амстердаме. "
    "Сын Гутена, в 1828 году запатентовавший изобретение отца, освоил также алкализацию какао-бобов.\n"
    "В 1847 году на английской фабрике J. Fry & Sons был произведён первый плиточный шоколад."
)


# ------------------------------------------------------------------ G4-7: the storyline by subkind


def test_a_history_is_told_by_what_it_is_the_history_of():
    assert W.history_subkind("История шоколада") == "culture"
    assert W.history_subkind("История Московского метро") == "culture"
    assert W.history_subkind("Полёт Гагарина") == "event"
    assert W.history_subkind("презентация про Крещение Руси") == "event"
    assert W.history_subkind("Вторая мировая война") == "conflict"
    assert W.history_subkind("Октябрьская революция") == "conflict"
    culture = [p.title for p in W.storyline_parts("history", 5, reference=True, subkind="culture")]
    event = [p.title for p in W.storyline_parts("history", 5, reference=True, subkind="event")]
    war = [p.title for p in W.storyline_parts("history", 5, reference=True)]
    assert culture == ["Истоки", "Распространение", "Развитие", "Новое время", "Современность"]
    assert event == ["Предыстория", "Подготовка", "Как это было", "Сразу после", "Значение"]
    assert war[0] == "Предпосылки и причины" and "Окончание" in war  # a war keeps its story
    for sub in ("event", "culture"):
        for n in list(range(1, 10)) + [12, 15]:
            parts = W.storyline_parts("history", n, reference=True, subkind=sub)
            titles = [p.title for p in parts]
            assert len(parts) == n and len(set(titles)) == n
            assert "Окончание" not in titles and "Предпосылки и причины" not in titles
            if n <= W.SHORT_DECK_CONTENT:
                assert not any("продолжение" in t for t in titles)  # a heading never repeats (gate 4 replay: «Как это было» ×2)
            if n <= W.SHORT_DECK_CONTENT:
                assert all(p.hint for p in parts)
    assert "Как это было" in W.storyline("history", 5, True, "event")


def test_an_event_topic_gets_the_events_story_whatever_kind_the_model_says():
    prompts: list[str] = []

    def fake(messages):
        system, user = messages[0].content, messages[-1].content
        if "You name encyclopedia articles" in system:
            return {"titles": [], "kind": "person"}
        if "fact-checker" in system:
            return {"issues": []}
        prompts.append(user)
        return {"status": "ok", "kind": "person", "title": "Полёт Гагарина", "subtitle": "", "slides": [
            {"title": "Начало", "text": "12 апреля 1961 года Юрий Гагарин совершил первый в мире полёт в космос. Корабль стартовал с Байконура."},
            {"title": "Окончание", "text": "Корабль совершил посадку в Саратовской области. Полёт длился 108 минут."},
        ]}

    reg = ProviderRegistry(roles={"llm": MockProvider(fake, model="Qwen/Qwen3-32B")}, limits=ProviderLimits(max_concurrency=2, time_budget_s=210))
    res = W.write_deck(Brief(text="Полёт Гагарина", slide_count=3), W.writer_mode("Полёт Гагарина"), SKILLS, reg,
                       config={"reference": {"enabled": False}})
    assert res.kind == "history" and res.subkind == "event" and res.record()["subkind"] == "event"
    assert "Как это было" in prompts[0] and "Окончание" not in prompts[0].split("working titles", 1)[1]
    # the model's war titles become the event's stages
    assert [ln.split(". ", 1)[1] for ln in res.text.splitlines() if re.match(r"^Слайд [23]\.", ln)] == ["Как это было", "Сразу после"]


def test_another_storylines_working_titles_become_this_storys():
    parts = W.storyline_parts("history", 5, reference=True, subkind="culture")
    deck = W._Deck(slides=[W._Slide(title=t, sentences=["Текст."], part=k) for k, t in enumerate(
        ["Предпосылки и причины", "Начало", "Ход событий и переломные события", "Окончание", "Потребление какао"])])
    W.retitle(deck, parts, "culture")
    assert [s.title for s in deck.slides] == ["Истоки", "Распространение", "Развитие", "Новое время", "Потребление какао"]


def test_a_slide_never_starts_before_the_slide_before_it_ends():
    # the WWII replay: «Переломные события (продолжение)» ended in August 1945, «Окончание» started at 8 May 1945
    parts = W.storyline_parts("history", 9, reference=True)
    a = W._Slide(title="Переломные события (продолжение)", part=5, sentences=[
        "6 июня 1944 года союзные войска высадились в Нормандии.",
        "В июле 1945 года США отправили Японии Потсдамскую декларацию.",
        "В августе 1945 года СССР вступил в войну против Японии."])
    b = W._Slide(title="Окончание", part=6, sentences=[
        "8 мая 1945 года Германия подписала акт о капитуляции.", "2 сентября 1945 года Япония подписала акт о капитуляции.",
        "Война официально завершилась."], src={"8 мая 1945 года Германия подписала акт о капитуляции.": [7]})
    deck = W._Deck(slides=[a, b])
    moved: list[dict] = []
    assert W.order_story(deck, parts, None, moved) == 1
    assert a.sentences[1] == "8 мая 1945 года Германия подписала акт о капитуляции." and a.src[a.sentences[1]] == [7]
    assert b.sentences[0].startswith("2 сентября 1945 года") and len(b.sentences) == 2
    assert moved[0]["from"] == 2 and moved[0]["to"] == 1
    # the chocolate: 1798 after 1847 — the fewer sentences move, both slides keep two
    parts_c = W.storyline_parts("history", 5, reference=True, subkind="culture")
    c = W._Slide(title="Развитие", part=2, sentences=["В 1606 году Карлетти опубликовал рецепт.", "В 1657 году в Лондоне открылся «шоколадный дом».",
                                                      "В 1847 году произведён первый плиточный шоколад."])
    d = W._Slide(title="Новое время", part=3, sentences=["К 1798 году в Париже было около 500 шоколадных кафе.",
                                                                    "Шоколад пили при дворе."])
    deck = W._Deck(slides=[c, d])
    W.order_story(deck, parts_c)
    keys = [[W._chrono_key(x) for x in s.sentences if W._chrono_key(x)] for s in deck.slides]
    assert max(keys[0]) <= min(keys[1]) and all(len(s.sentences) >= 2 for s in deck.slides)
    # an outcome slide is not part of the story's time order
    e = W._Slide(title="Итоги и потери", part=7, sentences=["Война длилась с 1 сентября 1939 по 2 сентября 1945 года.", "Погибло 70 млн человек."])
    deck = W._Deck(slides=[b, e])
    assert W.order_story(deck, parts) == 0


def test_an_undated_mention_of_a_dated_battle_goes_next_to_it():
    an = ww2()
    parts = W.storyline_parts("history", 9, reference=True)
    x = "В Европе Советский Союз одержал победы в Сталинградской и Курской битвах."
    a = W._Slide(title="Ход событий (продолжение)", part=3, sentences=[
        "22 июня 1941 года Германия начала вторжение в СССР.", "7 декабря 1941 года японская авиация атаковала Перл-Харбор.", x])
    b = W._Slide(title="Переломные события", part=4, sentences=[
        "В битве за Мидуэй в июне 1942 года Япония потерпела поражение.",
        "19 ноября 1942 года Красная армия перешла в контрнаступление под Сталинградом.",
        "8 ноября 1942 года англо-американский десант высадился в Марокко."])
    deck = W._Deck(slides=[a, b])
    moved: list[dict] = []
    W.order_story(deck, parts, an.support, moved)
    assert x not in a.sentences and b.sentences[b.sentences.index(x) - 1].startswith("19 ноября 1942 года")
    assert moved[-1]["why"].startswith("its key event")
    # a country is no key event: «3 сентября Великобритания и Франция…» stays where it is
    c = W._Slide(title="Начало", part=1, sentences=["1 сентября 1939 года Германия вторглась в Польшу.",
                                                    "3 сентября Великобритания и Франция объявили войну Германии.", "Началась война."])
    d = W._Slide(title="Ход событий", part=2, sentences=["С июня 1940 года Италия помогала Германии во Франции.", "Германия завоевала Данию."])
    deck = W._Deck(slides=[c, d])
    W.order_story(deck, parts, an.support)
    assert len(c.sentences) == 3


def test_a_wars_deck_tells_the_turning_points_of_its_articles_lead():
    an = ww2()
    parts = W.storyline_parts("history", 9, reference=True)
    s7 = W._Slide(title="Переломные события (продолжение)", part=5, sentences=[
        "6 июня 1944 года союзные войска высадились в Нормандии.", "В июле 1945 года США отправили Японии Потсдамскую декларацию."])
    s8 = W._Slide(title="Окончание", part=6, sentences=["2 сентября 1945 года Япония подписала акт о капитуляции.", "Война завершилась."])
    deck = W._Deck(slides=[s7, s8])
    edits: list[dict] = []
    assert W.lead_turning_points(deck, parts, an, edits) >= 1
    told = " ".join(s7.sentences + s8.sentences)
    assert "Хиросиму" in told and "Нагасаки" in told
    new = next(x for x in s7.sentences + s8.sentences if "Хиросиму" in x)
    home = s7 if new in s7.sentences else s8
    assert home.src[new] and edits[0]["why"].startswith("anchor: a turning point")
    # after July 1945, before 2 September
    all_s = s7.sentences + s8.sentences
    assert all_s.index(new) > all_s.index("В июле 1945 года США отправили Японии Потсдамскую декларацию.")


def test_a_slides_dated_blocks_go_in_time_order():
    s = W._Slide(title="Переломные события", sentences=[
        "19 ноября 1942 года Красная армия перешла в контрнаступление под Сталинградом.", "Немецкие войска были окружены.",
        "8 ноября 1942 года десант высадился в Марокко.", "В июне 1942 года Япония потерпела поражение у Мидуэя."])
    W.chrono_sentences(W._Deck(slides=[s]))
    assert s.sentences == ["В июне 1942 года Япония потерпела поражение у Мидуэя.", "8 ноября 1942 года десант высадился в Марокко.",
                           "19 ноября 1942 года Красная армия перешла в контрнаступление под Сталинградом.", "Немецкие войска были окружены."]


# ------------------------------------------------------------------ G4-8: what a lifted sentence refers to


def test_a_lifted_sentence_needs_what_it_refers_to_on_its_slide():
    topic = ["истор", "шокол"]
    panin = "Большим гурманом и любителем шоколада был и её первый министр Никита Панин."
    assert W.needs_context(panin, "", topic, ["Екатерина II"])
    assert W.needs_context(panin, "Обычай ввела Екатерина II.", topic, ["Екатерина II"]) is None
    son = "Сын Гутена, в 1828 году запатентовавший изобретение отца, освоил также алкализацию какао-бобов."
    assert "Гутена" in W.needs_context(son, "", topic)
    assert W.needs_context(son, "В 1815 году Конрад ван Гутен открыл фабрику.", topic) is None  # «отца»: Гутен, named before it
    assert W.needs_context("После посадки его встретили жители деревни — жена лесника и её внучка.", "", topic)  # «его»: whom?
    assert W.needs_context("После посадки Гагарина встретили жители деревни — жена лесника и её внучка.", "", topic) is None
    assert W.needs_context("Также на этом заводе будет производиться кроссовер.", "Выпуск идёт в Липецке.", topic)
    assert W.needs_context("Также на этом заводе будет производиться кроссовер.", "Выпуск начался на заводе «Моторинвест».", topic) is None
    assert W.needs_context("В этой войне участвовали 61 государство.", "", ["втор", "миров", "войн"]) is None  # the topic's war
    assert W.needs_context("Статистика за полугодие показывает сопоставимые результаты.", "", topic)
    # the sentence's own subject may be what the pronoun stands for; an adjective first word is not a subject
    assert W.needs_context("Гагарин вернулся на Землю, и его встретили жители деревни.", "", topic) is None
    assert W.needs_context("После посадки его встретили жители деревни.", "", topic)


def test_a_replacement_tells_what_the_statement_is_about_and_stands_alone():
    an = small(CHOC, "История шоколада")
    kate, panin, son = idx(an, r"^При петербургском"), idx(an, r"^Большим гурманом"), idx(an, r"^Сын Гутена")
    # a wrong citation: the article's sentence says something else — no replacement
    assert an.clause("В 1930-х годах на фабрике Nestlé появился первый белый шоколад.", [kate]) is None
    assert an.clause("В России шоколад ввела Екатерина II, а в XIX веке появился твёрдый шоколад.", [panin]) is None
    # «Сын Гутена … изобретение отца» on a slide that has not named Гутен — no replacement; after him, it is
    wrong = "В 1828 году сыном Конрада ван Хаутена был запатентован метод получения какао-порошка."
    assert an.clause(wrong, [son]) is None
    got = an.clause(wrong, [son], before="В 1815 году голландский химик Конрад ван Гутен открыл фабрику в Амстердаме.")
    assert got and got[0].startswith("Сын Гутена")


def test_an_article_sentence_is_cut_only_at_its_end():
    c = W.clean_article_sentence("На ноябрь 2025 года в России на 11 действующих АЭС эксплуатируется 36 энергоблоков общей "
                                 "установленной мощностью ~28,6 ГВт, из них:")
    assert c == "На ноябрь 2025 года в России на 11 действующих АЭС эксплуатируется 36 энергоблоков общей установленной мощностью около 28,6 ГВт."
    assert W.clean_article_sentence("Основные производители:") == ""
    inline = "Некоторые страны добровольно стали союзниками Германии: Венгрия, Румыния и Болгария."
    assert W.clean_article_sentence(inline) == inline  # a list inside the sentence stays
    assert W.article_clause("В ОЭС Центра — 40,96 %;") is None and W.article_clause("В ОЭС Урала — 12,3 %.") is None
    assert W.fix_grammar("Мощность составляет ~28,6 ГВт.") == "Мощность составляет около 28,6 ГВт."
    assert "около" not in W._past_verbs("Мощность составляла около 28,6 ГВт.")


def test_a_ranking_after_a_dash_takes_its_place():
    assert W.fix_grammar("Россия — четвёртое в мире по мощности атомной генерации.") == \
        "Россия занимает четвёртое место в мире по мощности атомной генерации."
    assert W.fix_grammar("Россия — четвёртая в мире по мощности атомной генерации.") == "Россия — четвёртая в мире по мощности атомной генерации."
    assert W.fix_grammar("Россия занимает второе место среди стран Европы.") == "Россия занимает второе место среди стран Европы."


def test_a_pronoun_that_would_read_as_a_thing_takes_its_own_source():
    text = ("Длительность полёта составила 106 минут.\n"
            "На приёме в Кремле 14 апреля 1961 года Юрию Гагарину вручили медаль «Золотая Звезда» Героя Советского Союза.")
    an = small(text, "Полёт Гагарина")
    hero = idx(an, r"^На приёме")
    first, second = "Полёт Гагарина длился 106 минут.", "Он получил звание Героя Советского Союза."
    s = W._Slide(title="Значение", sentences=[first, second], src={first: [0], second: [hero]}, anchors=an)
    W.fix_pronoun_subjects(W._Deck(slides=[s]))
    assert s.sentences[1].startswith("На приёме в Кремле")
    # after a person it stays
    s2 = W._Slide(title="Значение", sentences=["Гагарин вернулся на Землю.", second], src={second: [hero]}, anchors=an)
    W.fix_pronoun_subjects(W._Deck(slides=[s2]))
    assert s2.sentences[1] == second


# ------------------------------------------------------------------ G4-9: a market's parts and its place


EV = (
    "Электромобиль — автомобиль, который приводится в движение электродвигателем.\n"
    "== Шум электромобиля ==\n"
    "В ряде стран введены требования, чтобы электромобили издавали звук при низких скоростях.\n"
    "== Россия ==\n"
    "В 2020 году правительство утвердило программу поддержки производства электромобилей. "
    "Для электромобилей введена льгота по транспортному налогу. "
    "В 2024 году в России было продано 17,8 тысячи электромобилей.\n"
    "== Китай ==\n"
    "В Китае насчитывалось 5,21 млн зарядных колонок и много зарядных станций на трассах."
)


def test_a_market_part_the_articles_do_not_cover_gives_its_slide_to_a_covered_part():
    an = small(EV, "Рынок электромобилей в России")
    pages = ["Электромобиль"]
    assert not W.part_covered("Инфраструктура", an.support, pages, "росси")  # charging only in China
    assert W.part_covered("Регулирование и поддержка", an.support, pages, "росси")  # the «Россия» section
    assert W.part_covered("Основные игроки", an.support, pages, "росси")  # no words: always kept
    covered = lambda t: W.part_covered(t, an.support, pages, "росси")  # noqa: E731
    titles = [p.title for p in W.storyline_parts("market", 7, reference=True, covered=covered)]
    assert "Инфраструктура" not in titles and "Регулирование и поддержка" in titles and len(titles) == 7
    assert "Инфраструктура" in [p.title for p in W.storyline_parts("market", 7, reference=True)]


def test_a_market_slide_keeps_to_its_part_and_its_place():
    parts = W.storyline_parts("market", 7, reference=True)
    k = {p.title: i for i, p in enumerate(parts)}
    infra = W._Slide(title="Инфраструктура", part=k["Инфраструктура"], sentences=[
        "В ряде стран введены требования, чтобы электромобили издавали звук при низких скоростях."])
    trends = W._Slide(title="Тенденции", part=k["Тенденции"], sentences=[
        "По итогам 2024 года крупнейшими автопроизводителями электромобилей в мире были BYD и Tesla."])
    players = W._Slide(title="Основные игроки", part=k["Основные игроки"], sentences=[
        "В 2022 году на заводе «Моторинвест» в Липецкой области начался выпуск электромобилей Evolute.",
        "В мире продано 17 млн электромобилей, в России — 17,8 тысячи."])
    removed: list[dict] = []
    deck = W._Deck(slides=[players, infra, trends])
    W.fit_parts(deck, parts, "росси", removed)
    assert deck.slides == [players] and len(players.sentences) == 2  # a world figure next to Russia's stays
    assert {r["why"] for r in removed} == {"off its part «Инфраструктура»", "about somewhere else than the topic's place"}


def test_the_summing_up_slide_repeats_no_figure_another_slide_shows():
    deck = W._Deck(slides=[
        W._Slide(title="Объём рынка", sentences=["В 2024 году в России было продано 17,8 тысячи электромобилей."]),
        W._Slide(title="Главное", sentences=["Электромобиль — автомобиль с электродвигателем.",
                                             "В 2024 году в России продали 17,8 тысячи электромобилей."]),
    ])
    removed: list[dict] = []
    W.dedupe_figures(deck, removed)
    assert deck.slides[1].sentences == ["Электромобиль — автомобиль с электродвигателем."]
    assert removed[0]["why"].startswith("repeats the figures of slide 1")


# ------------------------------------------------------------------ G4-10: interpretive predicates


def test_an_interpretive_predicate_is_the_cited_sentences_own_word():
    text = "14 апреля 1961 года Москва встречала Гагарина как национального героя.\nПолёт укрепил престиж страны."
    an = small(text, "Полёт Гагарина")
    met = idx(an, r"^14 апреля")
    why = an.issue("Полёт также укрепил статус Гагарина как национального героя.", [met])
    assert why == "«укрепил» is not what its source tells"
    assert an.issue("Полёт укрепил престиж страны.", [idx(an, r"^Полёт укрепил")]) is None
    assert W.soft_word("Этот полёт повлиял на космонавтику.", "полет оказал влияние на космонавтику") is None
    assert W.soft_word("Сталинградская битва стала переломной.", "красная армия перешла в контрнаступление") == "переломной"
    s = W._Slide(title="Значение", sentences=["Полёт также рассматривался как триумф.", "Полёт также укрепил статус героя.", "Героя встречали."])
    W.thin_also(W._Deck(slides=[s]))
    assert s.sentences == ["Полёт также рассматривался как триумф.", "Полёт укрепил статус героя.", "Героя встречали."]


# ------------------------------------------------------------------ G4-12: the data note


def test_the_data_note_only_under_a_hedged_or_rounded_value():
    text = ("42 % совокупного дохода принесла онлайн-реклама, 32 % — игровое направление, 18,6 % — платные сервисы, 7 % — новые проекты.\n"
            "Россия потребляет около 3800 тонн природного урана в год.")
    an = small(text, "История VK")
    rev, ur = idx(an, r"^42 %"), idx(an, r"^Россия потребляет")
    assert W.row_approx(42.0, [rev], an.support) is False and W.row_approx(18.6, [rev], an.support) is False
    assert W.row_approx(3800.0, [ur], an.support) is True  # «около»
    assert W.row_approx(19.0, [rev], an.support) is True  # rounded by the writer
    assert W.row_approx(42.0, [], an.support) is True  # no source
    rows = [{"label": "Онлайн-реклама", "value": 42.0, "approx": False}, {"label": "Онлайн-игры", "value": 32.0, "approx": False},
            {"label": "Платные сервисы", "value": 18.6, "approx": False}]
    deck = W._Deck(title="История VK", slides=[W._Slide(title="Доходы", sentences=["Доход вырос."], data={"caption": "Доходы VK, 2019 год", "unit": "%", "chart": "pie", "rows": rows})])
    assert W.DATA_NOTE not in W.render_text(deck) and "Укажи, что данные приблизительные." not in W.render_text(deck, rules=True)
    rows[1]["approx"] = True
    assert W.DATA_NOTE in W.render_text(deck) and "Укажи, что данные приблизительные." in W.render_text(deck, rules=True)
    rows[1].pop("approx")  # a row the anchors never saw (no reference): approximate, as before
    assert W.DATA_NOTE in W.render_text(deck)
    # _data_ok keeps the flag (a later check rebuilds the rows)
    kept = W._data_ok({"caption": "Доходы", "unit": "%", "chart": "column", "rows": [dict(r, approx=False) for r in rows]})
    assert all(r["approx"] is False for r in kept["rows"])
