"""Source-anchored writing (round 4, gate 3): the writer reads the reference with a number before each sentence and
cites the sentences each of its sentences comes from; writer.Anchors checks every date, name, rank and figure against
the cited sentences, re-anchors a sentence that cites wrongly, puts the article's own clause in place of a sentence
that fails, and keeps every statement's source for writer.json and «Показать текст». Also the gate-3 writer defects
around it: the enumeration edit (W3-4), the lost antecedent (W3-3), decades, clock times and ranks (W3-5), agreement
(W3-7), the future tense for a past year (W3-8), repetition across slides (W3-9), the attribution of every page
(W3-10), hedged opinions (W3-11) and the data notes of the text the person sees (W3-12). Offline: the articles are
fixtures (tests/fixtures/writer)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

from verstka.planning import writer as W
from verstka.planning.reference import RefPage, Reference, cut_pages, number_reference, split_line
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.outline import Brief
from verstka.schemas.writer import WriterAnswer
from verstka.skills_registry.registry import SkillsRegistry

F = Path(__file__).resolve().parents[1] / "fixtures" / "writer"
SKILLS = SkillsRegistry.load()
ARTS = {
    "ww2": (["ww2_full.txt"], "Вторая мировая война", ["Вторая мировая война"]),
    "gag": (["vostok1_full.txt", "gagarin_full.txt"], "Полёт Гагарина", ["Восток-1", "Гагарин, Юрий Алексеевич"]),
    "vk": (["vk_full.txt"], "История VK", ["VK (компания)"]),
    "ev": (["ev_full.txt", "ev_ru_industry.txt"], "Рынок электромобилей в России", ["Электромобиль", "Автомобильная промышленность России"]),
}


def _text(name: str) -> str:
    return (F / name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def anchors(key: str) -> W.Anchors:
    files, topic, titles = ARTS[key]
    sup = W.ArticleSupport([_text(f) for f in files], topic)
    return W.Anchors(sup, [{"title": t, "url": f"https://ru.wikipedia.org/wiki/{t}"} for t in titles], year_now=2026, topic=topic)


def at(key: str, pattern: str) -> int:
    """The article sentence that matches."""
    sup = anchors(key).support
    return next(i for i, s in enumerate(sup.sents) if re.search(pattern, s))


# ------------------------------------------------------------------ the numbered reference


def test_the_reference_is_numbered_sentence_by_sentence_headings_as_they_are():
    cut = "# Восток-1\nПервый абзац. Второе предложение.\n\n## История\n22 мая 1959 года по инициативе Д. Устинова было принято решение. Потом ещё."
    text, sents = number_reference(cut)
    assert text.splitlines()[0] == "# Восток-1" and "## История" in text
    assert "[1] Первый абзац. [2] Второе предложение." in text
    # an initial does not end a sentence (the source line read «Устинова было принято решение…»)
    assert "[3] 22 мая 1959 года по инициативе Д. Устинова было принято решение. [4] Потом ещё." in text
    assert [s.id for s in sents] == [1, 2, 3, 4] and sents[0].page == "Восток-1"
    more, sents2 = number_reference("## Итоги\nЕщё одно предложение.", start=5)
    assert "[5] Ещё одно предложение." in more and sents2[0].id == 5
    assert split_line("Он у вас старший лейтенант. Гагарин ответил.") == ["Он у вас старший лейтенант.", "Гагарин ответил."]


def test_the_numbered_sentences_map_to_the_article_sentences():
    an = anchors("ww2")
    files, topic, titles = ARTS["ww2"]
    cut = cut_pages([RefPage(titles[0], text=_text(files[0]))], 18000, "history")
    _text_, sents = number_reference(cut)
    fresh = W.Anchors(an.support, an.pages, year_now=2026, topic=topic)
    fresh.add(sents)
    assert len(fresh.at) >= 0.95 * len(sents)
    for r in sents[:40]:
        if r.id in fresh.at:
            assert r.text.rstrip("…").strip()[:40] in fresh.support.sents[fresh.at[r.id]]


def test_citations_are_parsed_and_stripped():
    got = W.cited_sentences("Германия напала на Польшу 1 сентября 1939 года [6]. Великобритания и Франция объявили войну. [7, 8] Итоги подвели позже [9–11].")
    assert got == [("Германия напала на Польшу 1 сентября 1939 года.", [6]), ("Великобритания и Франция объявили войну.", [7, 8]),
                   ("Итоги подвели позже.", [9, 10, 11])]
    assert W.cited_sentences("Без ссылок тут. Второе предложение.") == [("Без ссылок тут.", []), ("Второе предложение.", [])]
    a = WriterAnswer.model_validate({"slides": [{"title": "Т", "text": "А [1].", "timeline": [{"when": "1939", "what": "Германия нападает [5]"}, "1941 — СССР [6]"],
                                                 "data": {"caption": "Потери", "src": [9], "rows": [{"label": "СССР", "value": 27, "src": "9"}]}}]})
    s = a.slides[0]
    assert [e.src for e in s.timeline] == [[5], [6]] and s.timeline[0].what == "Германия нападает"
    assert s.data.src == [9] and s.data.rows[0].src == [9]
    d = W._deck_of(a)
    assert d.slides[0].sentences == ["А."] and d.slides[0].cites == {"А.": [1]}


# ------------------------------------------------------------------ the anchor check (gate 3 errors)


def test_a_year_the_cited_sentence_does_not_give_fails_and_the_sentence_is_the_articles():
    an = anchors("ww2")
    g = at("ww2", r"^С августа 1942 года по февраль 1943 года японские и американские войска")
    wrong = "В 1944 году США одержали победу в битве за Гуадалканал."
    assert "1944" in an.issue(wrong, [g])
    assert an.issue("С августа 1942 года по февраль 1943 года японские и американские войска сражались за остров Гуадалканал.", [g]) is None
    new, j = an.clause(wrong, [g])
    assert j == g and new.startswith("С августа 1942 года по февраль 1943 года") and "1944" not in new
    # a neighbour's year never dates an event its cited sentence dates itself
    assert "1944" in an.issue(wrong, [g - 1, g]) if an.support.para[g - 1] == an.support.para[g] else True


def test_a_date_stays_with_the_name_its_sentence_gives_it_to():
    an = anchors("ww2")
    de = at("ww2", r"нацистскую Германию, подписавшую акт о капитуляции 8 мая")
    jp = at("ww2", r"^2 сентября 1945 года Япония подписала акт о капитуляции")
    assert "Германия" in an.issue("Германия подписала акт о капитуляции 2 сентября 1945 года.", [de, jp])
    assert an.issue("8 мая 1945 года Германия, а 2 сентября 1945 года Япония подписали акт о капитуляции.", [de, jp]) is None
    assert "Италия" in an.issue("В 1945 году Германия и Италия капитулировали.", [de])  # open item: Italy left the war in 1943


def test_decades_clock_times_verbs_and_ranks():
    an = anchors("gag")
    race = at("gag", r"^Участие СССР в космической гонке привело")
    assert "1960" in an.issue("В 1960-х годах началась космическая гонка между СССР и США.", [race])
    land = at("gag", r"совершил посадку в 10 часов 53 минуты")
    assert "отделился" in an.issue("В 10 часов 53 минуты спускаемый аппарат отделился и совершил посадку в районе деревни Смеловка.", [land])
    assert "10:55" in an.issue("В 10 часов 55 минут корабль совершил посадку в районе деревни Смеловка.", [land])
    assert an.issue("В 10:53 корабль совершил посадку в районе деревни Смеловка Саратовской области.", [land]) is None
    tdu = at("gag", r"^В 10:25:34")
    # the same time written another way is not an error (gate 3: «10 часов 25 минут» was removed as «25 минут»)
    assert an.issue("В 10 часов 25 минут была включена тормозная двигательная установка.", [tdu]) is None
    # the rank at the launch: the article tells «майор» as given during the flight
    t = W.later_titles("На борту находился лётчик-космонавт СССР майор ВВС Юрий Алексеевич Гагарин.", an.support)
    assert t == "На борту находился Юрий Алексеевич Гагарин."
    assert W.later_titles("Во время полёта Гагарину присвоили звание майора.", an.support) is None


def test_the_tense_of_the_event_and_a_plan_for_a_past_year():
    an = anchors("ev")
    bat = at("ev", r"батареи для электромобиля Москвич будут выпускаться в Москве")
    s = "В Москве с 2025 года начнётся производство батарей для электромобилей «Москвич»."
    assert "2025" in an.issue(s, [bat])
    new, _ = an.clause(s, [bat])
    assert "объявил" in new and not W._stale_future(new, 2026)
    assert W._stale_future("С 2025 года начнётся производство батарей.", 2026)
    assert not W._stale_future("В 2024 году объявили, что с 2025 года начнётся производство батарей.", 2026)
    assert not W._stale_future("К 2030 году продажи вырастут.", 2026)


def test_a_statement_without_a_citation_is_reanchored_or_goes():
    an = anchors("gag")
    got = an.reanchor("После одного оборота вокруг Земли, в 10 часов 25 минут, была включена тормозная двигательная установка.")
    assert got and "10:25:34" in an.support.sents[got[0]]
    assert an.reanchor("Полёт начался без серьёзных отклонений от плана.") is None
    assert an.reanchor("В 1960-х годах началась космическая гонка между СССР и США.") is None


def test_anchor_deck_keeps_replaces_drops_and_records_sources():
    an = anchors("ww2")
    g = at("ww2", r"^С августа 1942 года по февраль 1943 года японские и американские войска")
    de = at("ww2", r"нацистскую Германию, подписавшую акт о капитуляции 8 мая")
    ids = {1: g, 2: de}
    an.at.update(ids)  # prompt numbers 1 and 2
    deck = W._Deck(slides=[W._Slide(title="Перелом", sentences=[
        "В 1944 году США одержали победу в битве за Гуадалканал.", "8 мая 1945 года Германия подписала акт о капитуляции.",
        "Советские войска освободили Луну в 1950 году.",
    ], cites={"В 1944 году США одержали победу в битве за Гуадалканал.": [1], "8 мая 1945 года Германия подписала акт о капитуляции.": [2]})])
    removed: list[dict] = []
    edits: list[dict] = []
    stats = W.anchor_deck(deck, an, removed, edits)
    s = deck.slides[0]
    assert stats["anchored"] == 1 and stats["replaced"] == 1 and stats["dropped"] == 1
    assert s.sentences[0].startswith("С августа 1942 года") and s.sentences[1].startswith("8 мая 1945 года Германия")
    assert all(sn in s.src for sn in s.sentences)
    assert removed[0]["why"].startswith("anchor: no citation")
    out = W.final_sources(deck, an, removed)
    assert [x["text"] for x in out] == [W._sentence(x) for x in s.sentences]
    assert out[0]["page"] == "Вторая мировая война" and out[0]["sentence"].startswith("С августа 1942 года")


def test_a_pronoun_after_a_replaced_sentence_takes_its_own_source():
    an = anchors("gag")
    dur = at("gag", r"^Длительность полёта составила 106 минут")
    hero = at("gag", r"На приёме в Кремле 14 апреля 1961 года Гагарину были вручены")
    an.at.update({101: dur, 102: hero})
    first = "Полёт Гагарина длился около двух часов."
    second = "Он получил звание Героя Советского Союза."
    deck = W._Deck(slides=[W._Slide(title="Итоги", sentences=[first, second], cites={first: [101], second: [102]})])
    W.anchor_deck(deck, an, [], [])
    s = deck.slides[0].sentences
    assert s[0] == "Длительность полёта составила 106 минут." and not s[1].startswith("Он ")


# ------------------------------------------------------------------ W3-3, W3-4: antecedents and enumerations


def test_an_enumeration_cut_stays_grammatical_or_the_sentence_goes():
    t = "В этот период были запущены такие сервисы, как «Одноклассники», «Мой мир», «Почта Mail» и «ICQ»."
    cur = t
    outs = []
    for nm in ("Одноклассники", "ICQ", "Почта Mail"):
        k = cur.index(nm)
        cur = W.cut_list_item(cur, W._Ent(nm, k, k + len(nm), (nm.lower()[:6],)))
        outs.append(cur)
        if cur is None:
            break
    assert outs[0] == "В этот период были запущены такие сервисы, как «Мой мир», «Почта Mail» и «ICQ»."
    assert outs[1] == "В этот период были запущены такие сервисы, как «Мой мир» и «Почта Mail»."
    assert outs[2] is None  # never «такие сервисы и как «Мой мир»»
    # a list told «в этот период» is not repaired: its year is the sentence before's
    sup = anchors("vk").support
    p = sup.pair_issue(t)
    if p is not None and p.kind in ("verb", "item"):
        assert W._repair(t, p, sup) is None


def test_a_sentence_that_lost_its_antecedent_takes_its_cited_sentence():
    an = anchors("vk")
    dataart = at("vk", r"была разработана в 1997—1998 годах для внутренних задач американской софтверной компании DataArt")
    an.at[201] = dataart
    s = W._Slide(title="Основание", sentences=["Её создатели — российские программисты компании DataArt."], cites={"Её создатели — российские программисты компании DataArt.": [201]})
    s.anchors = an
    new = W.orphan_fix(s, s.sentences[0])
    assert new and "DataArt" in new and not W.anaphoric(new)


# ------------------------------------------------------------------ W3-7, W3-11: agreement, gender, hedges, words


def test_agreement_slips_are_fixed():
    assert W.fix_agreement("В Советском Союзе 12 апреля стал Днём космонавтики.") == "В Советском Союзе 12 апреля стало Днём космонавтики."
    assert W.fix_agreement("После 1 сентября стал известен план.") == "После 1 сентября стал известен план."
    assert W.fix_agreement("Компания стала направлением, связанном с ИИ.") == "Компания стала направлением, связанным с ИИ."
    assert W.fix_agreement("СССР показал технический превосходство.") == "СССР показал техническое превосходство."
    assert W.fix_agreement("Перед войной население выросло.") == "Перед войной население выросло."
    assert W.fix_grammar("12 апреля стал Днём космонавтики.") == "12 апреля стало Днём космонавтики."


def test_one_gender_per_name():
    art = ["В апреле 2022 года VK купила Дзен.", "VK запустила мессенджер.", "VK была основана в 1998 году."]
    assert W.entity_gender("VK", art) == "f"
    assert W.fix_gender("VK начал работу. VK изменила название. VK сменился.", {"VK": "f"}) == "VK начала работу. VK изменила название. VK сменилась."
    deck = W._Deck(slides=[W._Slide(title="Т", sentences=["VK начал работу в 1998 году."], timeline=[{"when": "2021", "what": "VK сменил название"}])])
    g = W.deck_genders(deck, ["В апреле 2022 года VK купила Дзен. VK запустила мессенджер. Затем VK объявила о продаже."])
    assert g == {"VK": "f"}
    W.apply_genders(deck, g)
    assert deck.slides[0].sentences == ["VK начала работу в 1998 году."] and deck.slides[0].timeline[0]["what"] == "VK сменила название"


def test_a_hedged_source_is_not_told_as_a_fact_and_intensifiers_go():
    an = anchors("ev")
    i = next((k for k, s in enumerate(an.support.sents) if re.search(r"рассматрива\w+\s+как", s)), None)
    if i is not None:
        assert an.issue("Электромобиль — экологичный и экономичный вид транспорта.", [i]) is not None
    assert W.plain_words("В 2000 году сервис начал активно расти.", "В 2000 году сервис рос") == "В 2000 году сервис начал расти."
    assert W.plain_words("Компания активно росла.", "компания активно развивалась") == "Компания активно росла."


# ------------------------------------------------------------------ W3-9: an event told again


def test_an_event_told_again_on_a_later_slide_goes():
    a = W._Slide(title="Развитие", sentences=["В 2021 году компания сменила название на VK."], src={"В 2021 году компания сменила название на VK.": [3]})
    b = W._Slide(title="Современный этап", sentences=["С 2021 года компания называется VK.", "В 2023 году началась реструктуризация."],
                 src={"С 2021 года компания называется VK.": [3], "В 2023 году началась реструктуризация.": [40]})
    c = W._Slide(title="Главное", sentences=["В 2021 году компания сменила название на VK."], src={"В 2021 году компания сменила название на VK.": [3]})
    deck = W._Deck(slides=[a, b, c])
    removed: list[dict] = []
    assert W.dedupe_sources(deck, removed) == 1
    assert deck.slides[1].sentences == ["В 2023 году началась реструктуризация."]
    assert deck.slides[2].sentences == ["В 2021 году компания сменила название на VK."]  # the summing-up slide restates


def test_a_mention_in_passing_of_the_next_slides_subject_is_cut():
    an = anchors("ww2")
    a = W._Slide(title="Ход событий", sentences=["В 1942 году шли тяжёлые бои.", "Немецкие войска наступали на юге, включая Сталинградскую битву.", "Третье предложение."])
    b = W._Slide(title="Переломные события", sentences=["Сталинградская битва длилась с 1942 по 1943 год.", "Под Сталинградом была окружена армия Паулюса."])
    a.anchors = b.anchors = an
    deck = W._Deck(slides=[a, b])
    W.dedupe_sources(deck, [])
    assert deck.slides[0].sentences[1] == "Немецкие войска наступали на юге."


# ------------------------------------------------------------------ W3-10, W3-12: attribution and the person's text


def test_the_attribution_names_every_page_it_used_digits_included():
    res = W.WriterResult(mode="topic", topic="Полёт Гагарина", pages_used=[{"title": "Восток-1", "url": "u1"}, {"title": "Гагарин, Юрий Алексеевич", "url": "u2"}])
    line = W.attribution(res)
    assert line.startswith(W.ATTRIBUTION_PREFIX)
    assert "по статьям «Восток-1» и «Гагарин, Юрий Алексеевич» из Википедии (лицензия CC BY-SA)" in line
    one = W.attribution(W.WriterResult(mode="topic", topic="x", source={"title": "Восток-1", "url": "u"}))
    assert "по статье «Восток-1» из Википедии" in one
    assert W.WriterResult(mode="topic", pages_used=[{"title": "A", "url": "u"}]).meta()["pages"] == [{"title": "A", "url": "u"}]


def test_the_text_the_person_sees_has_data_notes_and_the_agent_gets_its_requests():
    deck = W._Deck(title="История VK", slides=[W._Slide(title="Доходы", sentences=["В 2019 году доход составил 87,6 млрд рублей."],
                                                          data={"caption": "Доходы VK в 2019 году", "unit": "%", "chart": "pie", "rows": [
                                                              {"label": "Реклама", "value": 42}, {"label": "Игры", "value": 32}, {"label": "Прочее", "value": 26}]})])
    shown = W.render_text(deck)
    assert "Диаграмма (круговая): доходы VK в 2019 году." in shown and "Данные приблизительные." in shown
    assert "Нужна" not in shown and "Укажи" not in shown
    brief = W.render_text(deck, rules=True)
    assert "Нужна круговая диаграмма: доходы VK в 2019 году." in brief and "Укажи, что данные приблизительные." in brief
    assert W.with_rules(shown) == brief


def test_a_timeline_event_reads_lowercase_after_its_date_unless_a_name():
    sup = anchors("vk").support
    assert W._what_text("Начата редомициляция", names=sup._cap_mid) == "начата редомициляция"
    assert W._what_text("Mail.ru Group переименована в VK", names=sup._cap_mid) == "Mail.ru Group переименована в VK"
    assert W._what_text("Начата редомициляция") == "Начата редомициляция"


# ------------------------------------------------------------------ the check reads statements with their sources


def test_the_check_reads_each_statement_with_its_source_in_batches():
    an = anchors("ww2")
    g = at("ww2", r"^С августа 1942 года по февраль 1943 года японские и американские войска")
    slides = [W._Slide(title=f"С{k}", sentences=[f"Факт {k}.{j} о войне." for j in range(5)]) for k in range(5)]
    slides[0].src = {"Факт 0.0 о войне.": [g]}
    batches = W.check_batches(W._Deck(slides=slides), an)
    assert len(batches) == 3 and all(b.count("[") <= 12 for b in batches)
    assert "[1.1] Факт 0.0 о войне.\n    source: «С августа 1942 года" in batches[0]
    msgs = SKILLS.build_messages("writer_check", {"topic": "т", "reference": "", "numbered": batches[0], "sourced": True})
    assert "Under every statement stands its source" in msgs[0].content and "rank or title at that moment" in msgs[0].content
    assert "Reference:" not in msgs[1].content


# ------------------------------------------------------------------ end to end: a cited answer through write_deck


def _reference(key: str) -> Reference:
    files, _topic, titles = ARTS[key]
    pages = [RefPage(t, url=f"https://ru.wikipedia.org/wiki/{t}", text=_text(f)) for t, f in zip(titles, files)]
    return Reference(pages=pages, cut=cut_pages(pages, 18000, "history"))


def test_write_deck_anchors_a_cited_answer_and_keeps_the_sources(monkeypatch):
    import verstka.planning.reference as R

    monkeypatch.setattr(R, "fetch_reference", lambda *a, **k: _reference("ww2"))
    seen: dict = {}

    def num(prompt: str, pattern: str) -> int:
        m = re.search(r"\[(\d+)\] (?:(?!\[\d+\]).)*" + pattern, prompt)
        assert m, pattern
        return int(m.group(1))

    def fake(messages):
        system, user = messages[0].content, messages[-1].content
        if "You name encyclopedia articles" in system:
            return {"titles": ["Вторая мировая война"], "kind": "history"}
        if "fact-checker" in system:
            seen["check"] = user
            return {"issues": []}
        if "writer" in seen:
            seen["refill"] = user
            return {"status": "ok", "slides": []}
        seen["writer"] = user
        a = num(user, r"Вторая мировая война \(ВМВ")
        b = num(user, r"В этой войне участвовали 61 государство")
        c = num(user, r"1 сентября 1939 года нацистская Германия начала вторжение в Польшу")
        d = num(user, r"3 сентября вслед за этим Великобритания")
        return {"status": "ok", "kind": "history", "title": "Вторая мировая война", "subtitle": "1939—1945", "slides": [
            {"title": "Начало", "text": f"1 сентября 1939 года Германия начала вторжение в Польшу [{c}]. 3 сентября Великобритания и Франция объявили войну Германии [{d}]. "
                                        f"В 1938 году Германия напала на Францию [{c}].", "timeline": None, "data": None},
            {"title": "Масштаб", "text": f"В войне участвовали 61 государство — 80 % населения Земли [{b}]. Война длилась с 1 сентября 1939 года по 2 сентября 1945 года [{a}].",
             "timeline": None, "data": None},
        ]}

    reg = ProviderRegistry(roles={"llm": MockProvider(fake, model="Qwen/Qwen3-32B")}, limits=ProviderLimits(max_concurrency=2, time_budget_s=210))
    res = W.write_deck(Brief(text="Вторая мировая война", slide_count=3), W.writer_mode("Вторая мировая война"), SKILLS, reg,
                       config={"reference": {"enabled": True, "contact": "https://example.org"}})
    assert res.written, res.warnings
    assert re.search(r"\[\d+\] Вторая мировая война \(ВМВ", seen["writer"]) and "cite the numbers" in seen["writer"]
    assert "[" not in res.text and "1938" not in res.text  # the marks never reach the person; a wrong year is not written
    assert "source: «" in seen["check"] and "Reference:" not in seen["check"]
    assert res.anchor["anchored"] >= 3 and res.sources and all(x["page"] == "Вторая мировая война" for x in res.sources)
    rec = res.record()
    assert rec["sources"] and rec["numbered"] and rec["pages_used"][0]["title"] == "Вторая мировая война"
    assert res.meta()["sources"][0]["sentence"]
    assert "по статье «Вторая мировая война»" in W.attribution(res)


# ------------------------------------------------------------------ the older checks on top of the anchors


def test_a_clock_time_written_another_way_is_the_articles():
    d = W._Deck(slides=[W._Slide(title="Ход", sentences=["После одного оборота вокруг Земли, в 10 часов 25 минут, была включена тормозная двигательная установка.",
                                                         "В 11 часов 40 минут корабль приземлился в районе Смеловки."])])
    removed: list[dict] = []
    W.verify_against(d, [_text("vostok1_full.txt")], "Полёт Гагарина", removed)
    assert d.slides[0].sentences[0].startswith("После одного оборота") and len(d.slides[0].sentences) == 1
    assert "11 часов" in removed[0]["why"]


def test_the_pairing_checks_leave_the_date_of_an_anchored_statement_alone():
    an = anchors("ww2")
    i = at("ww2", r"В августе 1945 года СССР|8 августа 1945 года СССР|СССР.{0,40}объявил войну Японии")
    sn = "В августе 1945 года СССР вступил в войну против Японии."
    d = W._Deck(slides=[W._Slide(title="Окончание", sentences=[sn], src={sn: [i]})])
    W.fix_pairings(d, an.support, [], [])
    assert d.slides[0].sentences == [sn]


def test_two_anchored_statements_from_different_sentences_are_two_facts():
    a = W._Slide(title="Начало", sentences=["1 сентября 1939 года Германия вторглась в Польшу, что считается началом войны."],
                 src={"1 сентября 1939 года Германия вторглась в Польшу, что считается началом войны.": [10]})
    b = W._Slide(title="Итоги", sentences=["Война длилась с 1 сентября 1939 года по 2 сентября 1945 года."],
                 src={"Война длилась с 1 сентября 1939 года по 2 сентября 1945 года.": [0]})
    d = W._Deck(slides=[a, b])
    assert W.dedupe_events(d, []) == 0 and d.slides[1].sentences


def test_an_opinion_the_article_hedges_is_not_overruled():
    sup = anchors("ev").support
    sn = "Электромобили рассматриваются как экологичный транспорт."
    d = W._Deck(slides=[W._Slide(title="Что это", sentences=[sn, "Второе предложение о рынке."])])
    n = W.apply_check(d, [{"id": "1.1", "verdict": "opinion", "problem": "an evaluation the article hedges"}], support=sup, overruled=[],
                      hedged=lambda t: True)
    assert n == 1 and sn not in d.slides[0].sentences


def test_without_a_reference_a_plan_for_a_past_year_goes():
    a = WriterAnswer.model_validate({"slides": [{"title": "Планы", "text": "С 2025 года начнётся производство батарей в Москве. В 2030 году продажи вырастут."}]})
    removed: list[dict] = []
    d = W.normalise_answer(a, "Рынок", "", [], "ru", removed)
    assert [r["why"] for r in removed] == ["the future tense for a past year"]
    assert d.slides[0].sentences == ["В 2030 году продажи вырастут."]


def test_a_bound_stays_a_bound():
    an = anchors("gag")
    i = at("gag", r"возраст не больше 30 лет, рост не более 170 см")
    assert "30 лет" in an.issue("Космонавты отбирались по возрасту около 30 лет и росту не более 170 см.", [i])
    assert "30 лет" in an.issue("Космонавты отбирались по возрасту 30 лет и росту 170 см.", [i])
    assert an.issue("Космонавты отбирались по возрасту до 30 лет и росту не более 170 см.", [i]) is None


def test_the_refill_reads_a_numbered_cut_that_continues_the_numbers(monkeypatch):
    import verstka.planning.reference as R

    monkeypatch.setattr(R, "fetch_reference", lambda *a, **k: _reference("ww2"))
    prompts: list[str] = []

    def num(prompt: str, pattern: str) -> int:
        m = re.search(r"\[(\d+)\] (?:(?!\[\d+\]).)*" + pattern, prompt)
        return int(m.group(1)) if m else -1

    def fake(messages):
        system, user = messages[0].content, messages[-1].content
        if "You name encyclopedia articles" in system:
            return {"titles": ["Вторая мировая война"], "kind": "history"}
        if "fact-checker" in system:
            return {"issues": []}
        prompts.append(user)
        if len(prompts) == 1:
            c = num(user, r"1 сентября 1939 года нацистская Германия начала вторжение в Польшу")
            d = num(user, r"3 сентября вслед за этим Великобритания")
            return {"status": "ok", "kind": "history", "title": "Вторая мировая война", "subtitle": "", "slides": [
                {"title": "Начало", "text": f"1 сентября 1939 года Германия начала вторжение в Польшу [{c}]. 3 сентября Великобритания и Франция объявили войну Германии [{d}]."},
                {"title": "Ход событий", "text": "Битва длилась долго [1]."},
            ]}
        # the refill: the numbers of its own cut
        ids = [int(x) for x in re.findall(r"\[(\d+)\]", user.split("Reference text", 1)[1].split(">>>", 1)[0])]
        first = min(ids)
        sent = re.search(r"\[(\d+)\] ([^\[]{40,300}?\d{4} год[^\[]*?\.)\s", user.split("Reference text", 1)[1])
        return {"status": "ok", "slides": [{"title": "Ход событий", "text": f"{sent.group(2)} [{sent.group(1)}]." if sent else ""}], "_first": first}

    reg = ProviderRegistry(roles={"llm": MockProvider(fake, model="Qwen/Qwen3-32B")}, limits=ProviderLimits(max_concurrency=2, time_budget_s=210))
    res = W.write_deck(Brief(text="Вторая мировая война", slide_count=3), W.writer_mode("Вторая мировая война"), SKILLS, reg,
                       config={"reference": {"enabled": True, "contact": "https://example.org"}})
    assert res.written and len(prompts) == 2
    main_ids = [x[0] for x in res.numbered[0]]
    refill_ids = [x[0] for x in res.numbered[1]]
    assert min(refill_ids) == max(main_ids) + 1  # the refill's numbers continue the main cut's
    assert all(x["sentence"] for x in res.sources)


def test_a_thin_summary_gets_the_decks_first_and_last_dates():
    deck = W._Deck(slides=[
        W._Slide(title="Основание", sentences=["VK была основана в 1998 году.", "Сервис запустили в тестовом режиме."]),
        W._Slide(title="Развитие", sentences=["В 2023 году были созданы две бизнес-группы.", "Она владеет сетями."]),
        W._Slide(title="Главное", sentences=["В 2021 году компания получила новое название."]),
    ])
    assert W.fill_summary(deck) == 2
    assert deck.slides[-1].sentences == ["VK была основана в 1998 году.", "В 2021 году компания получила новое название.",
                                         "В 2023 году были созданы две бизнес-группы."]


def test_a_model_that_does_not_cite_keeps_what_the_article_supports():
    an = anchors("gag")
    kept = "12 апреля 1961 года в 9 часов 7 минут по московскому времени с космодрома Байконур стартовал корабль «Восток-1»."
    wrong = "В 1960-х годах началась космическая гонка между СССР и США."
    deck = W._Deck(slides=[W._Slide(title="Начало", sentences=[kept, wrong])])
    stats = W.anchor_deck(deck, an, [], [])
    assert kept in deck.slides[0].sentences and wrong not in deck.slides[0].sentences
    assert stats["dropped"] == 1


def test_a_century_must_be_its_sources():
    an = anchors("ww2")
    i = at("ww2", r"крупнейшим вооружённым конфликтом в истории человечества")
    assert "19" in an.issue("В XIX веке началась Вторая мировая война, крупнейший конфликт в истории человечества.", [i])
    assert W._centuries("в XX веке и в 19-м веке") == {20, 19}
