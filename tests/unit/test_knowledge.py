"""База знаний (verstka/knowledge): документы и архивы → фрагменты с местом в документе → локальный поиск по основам
слов → выдержка для писателя, проверка цифр и источник каждого утверждения. Ссылки — только публичные страницы."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from verstka.knowledge.reference import KbReference, sources_line
from verstka.knowledge.store import KnowledgeBase, KnowledgeError, list_bases
from verstka.knowledge.text import figures, stem_ru, tokens
from verstka.knowledge.web import FetchError, check_url, fetch

KB_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "kb"
PUBLIC = lambda host, port: ["93.184.216.34"]  # noqa: E731 - a public address for any host (no DNS in tests)


@pytest.fixture
def kb(tmp_path):
    base = KnowledgeBase.create(tmp_path, "Квартал")
    for f in sorted(KB_DIR.iterdir()):
        got = base.add_file(f.name, f.read_bytes())
        assert got.docs and not got.skipped, (f.name, got.skipped)
    return base


def test_russian_words_meet_by_their_stems():
    assert stem_ru("клиентов") == stem_ru("клиенты") == stem_ru("клиентами")
    assert stem_ru("подключения") == stem_ru("подключение")
    assert set(tokens("квартал")) == set(tokens("кварталов"))
    assert tokens("Выручка выросла до 1 240 млн ₽, на 12,5%") == ["выручк", "выросл", "1240", "млн", "12.5"]
    assert figures("412 млн ₽ — на 18%; 1 240 клиентов; 2,10") == {"412", "18", "1240", "2.1"}


def test_documents_of_every_kind_become_fragments_with_their_place(kb):
    s = kb.summary()
    assert [d["kind"] for d in s["docs"]] == ["md", "docx", "pdf", "txt"]
    assert [d["title"] for d in s["docs"]] == ["Клиенты и отзывы", "Итоги третьего квартала 2026", "Стратегия облачной платформы до 2027 года", "Команда и найм"]
    ref = KbReference(kb)
    nps = next(f for f in ref.frags if "NPS" in f.text)
    assert ref.label(nps) == "«Клиенты и отзывы», раздел «Удовлетворённость», абз. 3"
    table = next(f for f in ref.frags if f.table and "Q3 2026" in f.text)
    assert table.text.startswith("Таблица «Выручка и клиенты по кварталам»:") and "раздел «Выручка по кварталам», таблица" in ref.label(table)
    pdf = next(f for f in ref.frags if "Казахстан" in f.text and f.page)
    assert pdf.page == 1 and "раздел «Зарубежные рынки»" in ref.label(pdf)


def test_the_search_finds_the_fragment_a_question_is_about(kb):
    top = kb.search("Как изменился индекс удовлетворённости клиентов?", 3)
    assert "NPS вырос с 31" in top[0][0].text
    top = kb.search("сколько человек работает в отделе продаж", 2)
    assert "46 человек" in top[0][0].text
    top = kb.search("инвестиции в дата-центры в 2027", 2)
    assert "240" in top[0][0].text and top[0][0].table


def test_the_same_document_twice_is_taken_once_and_a_foreign_file_is_skipped(kb):
    again = kb.add_file("копия.md", (KB_DIR / "clients.md").read_bytes())
    assert not again.docs and "уже в базе" in again.skipped[0]["reason"]
    bad = kb.add_file("фото.png", b"\x89PNG....")
    assert not bad.docs and "формат не читаю" in bad.skipped[0]["reason"]


def test_a_zip_or_a_folder_brings_every_document(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("база/clients.md", (KB_DIR / "clients.md").read_bytes())
        z.writestr("база/team.txt", (KB_DIR / "team.txt").read_bytes())
        z.writestr("__MACOSX/._team.txt", b"junk")
        z.writestr("база/logo.png", b"\x89PNG")
    base = KnowledgeBase.create(tmp_path)
    got = base.add_file("база.zip", buf.getvalue())
    assert [d["name"] for d in got.docs] == ["clients.md", "team.txt"]
    assert [s["name"] for s in got.skipped] == ["logo.png"]
    assert list_bases(tmp_path)[0]["docs"] == 2
    assert base.remove(got.docs[0]["id"]) and len(base.docs) == 1 and not base.remove("nope")


def test_the_writer_reads_the_base_and_every_figure_is_checked_against_it(kb):
    ref = KbReference(kb)
    cut = ref.cut("итоги квартала для правления", 4000)
    assert cut.startswith("# ") and "412 млн ₽" in cut and len(cut) <= 4400
    assert "[«Клиенты и отзывы», раздел «Удовлетворённость», абз. 3]" in ref.relevant("NPS удовлетворённость", 2000)
    assert ref.unsupported("Выручка за квартал выросла до 412 млн ₽, на 18%.") == set()
    assert ref.unsupported("Выручка выросла до 500 млн ₽.") == {"500"}
    assert ref.unsupported("Наняли 3 инженера.") == set()  # small integers: a document writes «три»
    assert ref.unsupported("Наняли 27 инженеров.", given="план: 27 инженеров") == set()  # the person's own figure
    src = ref.source_of("Индекс NPS вырос до 44 в третьем квартале.")
    assert src is not None and src.title == "Клиенты и отзывы" and src.place == "раздел «Удовлетворённость», абз. 3"
    assert ref.source_of("Погода в Сочи была солнечной.") is None
    line = sources_line([src, ref.source_of("В отделе продаж 46 человек."), src])
    assert line == "Источники: «Клиенты и отзывы», раздел «Удовлетворённость», абз. 3; «Команда и найм», раздел «Команда и найм», абз. 1."


def test_only_public_pages_are_fetched():
    for bad, why in [("ftp://example.com/a", "http"), ("https://user:pw@example.com/", "логином"), ("https://example.com:8443/", "порты"),
                     ("http://localhost/", "сайта|внутренней"), ("http://127.0.0.1/admin", "внутренней"), ("http://169.254.169.254/latest", "внутренней"),
                     ("http://10.0.0.5/", "внутренней")]:
        with pytest.raises(FetchError, match=why):
            check_url(bad, resolve=lambda h, p: [h] if h[0].isdigit() else ["127.0.0.1"])
    with pytest.raises(FetchError, match="внутренней"):
        check_url("https://intranet.example.com/", resolve=lambda h, p: ["192.168.1.10"])
    assert check_url("example.com/page", resolve=PUBLIC) == "https://example.com/page"


def test_a_page_is_fetched_once_within_its_limits_and_a_redirect_inside_is_refused():
    page = "<html><head><title>T</title></head><body><article><h1>Отчёт</h1><p>Выручка 100 млн ₽.</p></article></body></html>"

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/moved":
            return httpx.Response(302, headers={"location": "http://192.168.0.1/secret"})
        if req.url.path == "/big":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 2_000_000)
        if req.url.path == "/login":
            return httpx.Response(401)
        if req.url.path == "/img":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")
        assert "authorization" not in req.headers and "cookie" not in req.headers
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=page.encode())

    t = httpx.MockTransport(handler)
    resolve = lambda h, p: ["192.168.0.1"] if h.startswith("192.") else ["93.184.216.34"]  # noqa: E731
    got = fetch("https://example.com/report", transport=t, resolve=resolve)
    assert got.data.decode() == page and got.content_type == "text/html"
    with pytest.raises(FetchError, match="внутренней"):
        fetch("https://example.com/moved", transport=t, resolve=resolve)
    with pytest.raises(FetchError, match="больше 1 МБ"):
        fetch("https://example.com/big", transport=t, resolve=resolve, max_bytes=1024 * 1024)
    with pytest.raises(FetchError, match="закрыта входом"):
        fetch("https://example.com/login", transport=t, resolve=resolve)
    with pytest.raises(FetchError, match="не страница"):
        fetch("https://example.com/img", transport=t, resolve=resolve)


def test_a_link_adds_its_page_to_the_base(tmp_path):
    page = "<html><body><main><h1>Рынок облаков</h1><p>Рынок облачных услуг вырос на 32% и достиг 210 млрд ₽ в 2026 году.</p></main></body></html>"
    t = httpx.MockTransport(lambda req: httpx.Response(200, headers={"content-type": "text/html"}, content=page.encode()))
    base = KnowledgeBase.create(tmp_path)
    got = base.add_url("https://example.com/market", transport=t, resolve=PUBLIC)
    d = got.docs[0]
    assert d["title"] == "Рынок облаков" and d["url"] == "https://example.com/market" and d["source"] == "link"
    with pytest.raises(KnowledgeError, match="уже в базе"):
        base.add_url("https://example.com/market", transport=t, resolve=PUBLIC)
    src = KbReference(base).source_of("Рынок облачных услуг достиг 210 млрд ₽.")
    assert src.url == "https://example.com/market"
    assert "(https://example.com/market)" in sources_line([src])
