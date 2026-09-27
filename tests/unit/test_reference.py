"""The writer's reference (planning/reference.py, WRITER_SPEC §4, §12.1 T8–T9): the MediaWiki client — only titles leave
the machine, a contact in the User-Agent, redirects and the fallback search, the cache (a stale entry when the network
fails), every failure a missing reference — and the cut the writer reads. No network: httpx.MockTransport."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from verstka.planning import reference as R
from verstka.planning import writer as W
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

F = Path(__file__).resolve().parents[1] / "fixtures" / "writer"
CONTACT = "https://example.org/verstka"
VK_TEXT = (
    "«ВКонта́кте» — российская социальная сеть. Запущена в 2006 году Павлом Дуровым.\n\n"
    "== История ==\nСайт был запущен 10 октября 2006 года как сеть для студентов и выпускников вузов. "
    "В 2014 году Павел Дуров покинул компанию.\n\n== Примечания ==\nСсылки на источники."
)


class Wiki:
    """A scripted MediaWiki API: pages by title (with redirects), search hits, and a log of every request."""

    def __init__(self, pages: dict[str, str], redirects: dict[str, str] | None = None, search: dict[str, list[tuple[str, int]]] | None = None,
                 disambiguation: tuple[str, ...] = (), status: int = 200) -> None:
        self.pages, self.redirects, self.hits, self.disamb, self.status = pages, redirects or {}, search or {}, set(disambiguation), status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, text="Please respect our robot policy")
        q = dict(request.url.params)
        if q.get("list") == "search":
            hits = self.hits.get(q["srsearch"], [])
            return httpx.Response(200, json={"query": {"search": [{"title": t, "wordcount": w} for t, w in hits]}})
        titles = q.get("titles", "").split("|")
        redirects, out = [], []
        for t in titles:
            to = self.redirects.get(t)
            if to:
                redirects.append({"from": t, "to": to})
            name = to or t
            if name in self.pages or name in self.disamb:
                pg = {"title": name, "pageid": 1}
                if "extracts" in q.get("prop", ""):
                    pg.update({"extract": self.pages.get(name, ""), "fullurl": f"https://ru.wikipedia.org/wiki/{name}", "revisions": [{"revid": 42, "timestamp": "2026-09-27T10:00:00Z"}]})
                if name in self.disamb:
                    pg["pageprops"] = {"disambiguation": ""}
                out.append(pg)
            else:
                out.append({"title": name, "missing": True})
        return httpx.Response(200, json={"query": {"pages": out, "redirects": redirects}})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _fetch(wiki: Wiki, titles, topic="История VK", tmp_path: Path | None = None, contact=CONTACT, **kw):
    return R.fetch_reference(titles, topic, contact=contact, transport=wiki.transport, cache_dir=tmp_path, **kw)


def test_the_proposed_title_is_fetched_with_the_contact_in_the_user_agent(tmp_path):
    wiki = Wiki({"ВКонтакте": VK_TEXT}, redirects={"VK": "ВКонтакте"})
    ref = _fetch(wiki, ["VK"], tmp_path=tmp_path)
    assert [p.title for p in ref.pages] == ["ВКонтакте"] and ref.pages[0].revid == 42
    assert "Запущена в 2006 году" in ref.cut and "Примечания" not in ref.cut
    ua = wiki.requests[0].headers["User-Agent"]
    assert ua.startswith("Verstka/") and CONTACT in ua
    # only titles left the machine, never the user's text
    assert all("История" not in str(r.url.params) for r in wiki.requests if r.url.params.get("titles"))


def test_a_missing_title_is_searched_and_the_largest_matching_article_wins(tmp_path):
    wiki = Wiki(
        {"VK (компания)": VK_TEXT, "VK Видео": "Видеосервис."},
        search={"История VK": [("VK Видео", 659), ("История (значения)", 90000)], "VK": [("VK Видео", 659), ("VK (компания)", 12000), ("VK (значения)", 50000)]},
    )
    ref = _fetch(wiki, ["История VK"], tmp_path=tmp_path)
    assert ref.main is not None and ref.main.title == "VK (компания)"  # the main article, not the «VK Видео» stub
    searched = [r.url.params.get("srsearch") for r in wiki.requests if r.url.params.get("list") == "search"]
    assert sorted(searched) == ["VK", "История VK"]


def test_a_narrow_topic_takes_the_most_relevant_general_article(tmp_path):
    wiki = Wiki({"Электромобиль": "Электромобиль — автомобиль на электродвигателях.", "Россия": "Страна."},
                search={"Рынок электромобилей в России": [("Электромобиль", 9000), ("Россия", 200000)]})
    ref = _fetch(wiki, ["Рынок электромобилей в России"], topic="Рынок электромобилей в России", tmp_path=tmp_path)
    assert ref.main is not None and ref.main.title == "Электромобиль"  # the search's order, not the largest article


def test_a_disambiguation_page_is_skipped(tmp_path):
    wiki = Wiki({"ВКонтакте": VK_TEXT}, disambiguation=("VK",), search={"VK": [("ВКонтакте", 12000)]})
    ref = _fetch(wiki, ["VK", "ВКонтакте"], tmp_path=tmp_path)
    assert [p.title for p in ref.pages] == ["ВКонтакте"]


def test_no_contact_no_request():
    wiki = Wiki({"ВКонтакте": VK_TEXT})
    ref = _fetch(wiki, ["ВКонтакте"], contact="")
    assert not ref.pages and not wiki.requests and ref.warnings == ["reference: no contact configured"]
    assert not R.contact_ok("команда верстки") and R.contact_ok("team@example.org")


@pytest.mark.parametrize("status", [403, 503])
def test_a_refusal_or_a_server_error_is_no_reference(status, tmp_path):
    ref = _fetch(Wiki({"ВКонтакте": VK_TEXT}, status=status), ["ВКонтакте"], tmp_path=tmp_path)
    assert not ref.pages and not ref.cut and ref.warnings and ref.warnings[0].startswith("reference:")


def test_a_timeout_is_no_reference(tmp_path):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    ref = R.fetch_reference(["ВКонтакте"], "VK", contact=CONTACT, transport=httpx.MockTransport(slow), cache_dir=tmp_path)
    assert not ref.pages and "timeout" in ref.warnings[0].lower()


def test_the_cache_saves_the_requests_and_a_stale_entry_saves_a_failure(tmp_path):
    wiki = Wiki({"ВКонтакте": VK_TEXT})
    first = _fetch(wiki, ["ВКонтакте"], tmp_path=tmp_path)
    n = len(wiki.requests)
    again = _fetch(wiki, ["ВКонтакте"], tmp_path=tmp_path)
    assert len(wiki.requests) == n and again.pages[0].cached and again.cut == first.cut
    # a week later the network is down: the stale entry is used
    for f in (tmp_path / "ru").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        d["fetched_at"] = time.time() - 30 * 86400
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    down = _fetch(Wiki({}, status=503), ["ВКонтакте"], tmp_path=tmp_path)
    assert down.pages and down.pages[0].title == "ВКонтакте" and down.cut == first.cut


def test_lead_words_are_not_searched():
    assert R.lead_free("Сделай презентацию на 10 слайдов про историю космонавтики") == "космонавтики"
    assert R.lead_free("История VK") == "VK"
    assert R.tokens("VK") == {"vk"} and "ии" in R.tokens("ИИ в медицине")


# ------------------------------------------------------------------ the writer never asks Wikipedia about the user's own subject


def _registry(fn):
    model = MockProvider(fn, model="Qwen/Qwen3-32B")
    return ProviderRegistry(roles={"llm": model}, limits=ProviderLimits(max_concurrency=2, time_budget_s=210))


def _writer(messages):
    system = messages[0].content
    if "You name encyclopedia articles" in system:
        return {"titles": ["ВКонтакте"], "kind": "company"}
    if "fact-checker" in system:
        return {"issues": []}
    return {"status": "ok", "kind": "company", "title": "История VK", "subtitle": "Социальная сеть с 2006 года", "slides": [
        {"title": "Основание", "text": "«ВКонтакте» запущена в 2006 году Павлом Дуровым. Сайт открылся 10 октября 2006 года для студентов."},
        {"title": "Развитие", "text": "В 2014 году Павел Дуров покинул компанию. Сеть работает из Санкт-Петербурга."},
        {"title": "Главное", "text": "«ВКонтакте» — российская социальная сеть, запущенная в 2006 году."},
    ]}


def test_the_private_hint_never_reaches_wikipedia(tmp_path):
    wiki = Wiki({"ВКонтакте": VK_TEXT})
    topic = "итоги работы нашего отдела продаж"
    res = W.write_deck(Brief(text=topic, slide_count=5), W.writer_mode(topic), SkillsRegistry.load(), _registry(lambda m: {"status": "private"}),
                       config={"reference": {"enabled": True, "contact": CONTACT}}, cache_dir=tmp_path, transport=wiki.transport)
    assert res.status == "private" and not wiki.requests


def test_the_writer_writes_from_the_article_and_names_it(tmp_path):
    wiki = Wiki({"ВКонтакте": VK_TEXT})
    events: list[dict] = []
    res = W.write_deck(Brief(text="История VK", slide_count=4), W.writer_mode("История VK"), SkillsRegistry.load(), _registry(_writer),
                       config={"reference": {"enabled": True, "contact": CONTACT}}, cache_dir=tmp_path, transport=wiki.transport, progress=events.append)
    assert res.written and res.source == {"title": "ВКонтакте", "url": "https://ru.wikipedia.org/wiki/ВКонтакте"} and res.checked == "reference"
    assert res.pages[0]["revid"] == 42 and res.kind == "company"
    assert "по статье «ВКонтакте» из Википедии (лицензия CC BY-SA)" in W.attribution(res)
    assert [e["step"] for e in events] == ["writer"] * len(events) and "Нашёл статью «ВКонтакте»" in events[1]["message"]
    assert "Сверил текст со статьёй" in " ".join(e["message"] for e in events)


def test_offline_the_writer_writes_from_knowledge(tmp_path, monkeypatch):
    monkeypatch.setenv("VERSTKA_WIKI", "0")
    wiki = Wiki({"ВКонтакте": VK_TEXT})
    res = W.write_deck(Brief(text="История VK", slide_count=4), W.writer_mode("История VK"), SkillsRegistry.load(), _registry(_writer),
                       cache_dir=tmp_path, transport=wiki.transport)
    assert res.written and res.source is None and res.checked == "model" and not wiki.requests
    assert "по теме «История VK»" in W.attribution(res)


# ------------------------------------------------------------------ T9: the cut the writer reads


@pytest.fixture(scope="module")
def ww2_full() -> str:
    return (F / "ww2_full.txt").read_text(encoding="utf-8")


def test_the_cut_covers_every_section(ww2_full):
    lead, secs = R.sections(ww2_full)
    kept = [h for h, b in secs if not R._SKIP_RE.match(h) and b.strip()]
    cut = R.cut_reference(ww2_full, 12000)
    assert len(cut) <= 12000 and len(kept) >= 10
    for h in kept:
        assert f"## {h}" in cut, h
    assert "## Примечания" not in cut and "## Литература" not in cut
    assert cut.startswith(lead[:200])


def test_the_politician_cut_keeps_the_biography_only():
    bio = (F / "putin_bio.txt").read_text(encoding="utf-8")
    text = bio + "\n\n== Внешняя политика ==\nПолитика в отношении соседних стран.\n\n== Оценки и критика ==\nОценки деятельности."
    cut = R.cut_reference(text, 12000, kind="politician")
    assert "## Ранние годы и образование" in cut and "Внешняя политика" not in cut and "Оценки и критика" not in cut
    assert len(cut) <= 12000


def test_two_pages_share_the_limit():
    pages = [R.RefPage("Главная", text="Лид. " * 2000), R.RefPage("Вторая", text="Текст. " * 2000)]
    cut = R.cut_pages(pages, 9000)
    assert cut.startswith("# Главная") and "# Вторая" in cut and len(cut) <= 9000 + 10
    assert cut.index("# Вторая") > 5000
