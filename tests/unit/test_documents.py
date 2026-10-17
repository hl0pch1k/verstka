"""«Из файла»: DOCX и PDF → структура документа (заголовки, абзацы, списки, таблицы) → Markdown для поля и таблицы с
цифрами для данных (verstka/ingest/documents.py). Документы — tests/fixtures/documents (make_docs.py)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from verstka.ingest.documents import DocumentError, read_document, read_html, read_markdown

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
sys.path.insert(0, str(FIX))
from make_docs import docx_bytes, p, table  # noqa: E402


def _doc(name: str):
    return read_document(name, (FIX / name).read_bytes())


@pytest.mark.parametrize("name", ["report.docx", "report.pdf"])
def test_a_report_reads_with_its_headings_lists_and_tables(name):
    d = _doc(name)
    assert d.title == "Итоги третьего квартала 2026"
    heads = [b.text for b in d.blocks if b.kind == "heading"]
    assert heads[:4] == ["Итоги третьего квартала 2026", "Главное", "Что сделали", "Выручка по кварталам"]
    assert "Ключевые риски" in heads  # a bold short paragraph is the author's own heading
    items = [b.text for b in d.blocks if b.kind == "item"]
    assert "Открыли офис в Казани" in items and "Довести выручку до 450 млн ₽" in items
    assert len(d.tables) == 2 and len(d.data_tables) == 1
    data = d.data_tables[0]
    assert data.caption == "Выручка и клиенты по кварталам"
    assert data.rows[0] == ["Квартал", "Выручка, млн ₽", "Клиенты"] and data.rows[-1] == ["Q3 2026", "412", "1 240"]
    md = d.markdown()
    assert "# Итоги третьего квартала 2026" in md and "## Главное" in md
    assert "412 млн ₽ — на 18% больше" in md  # the ruble sign drawn apart in the PDF goes back into its gap
    assert "| Q3 2026 | 412 | 1 240 |" in md and "| Старт | малый бизнес | чат |" in md
    assert "1. Выйти на рынок Казахстана" in md and "- Открыли офис в Казани" in md


@pytest.mark.parametrize("name", ["report.docx", "report.pdf"])
def test_the_text_for_the_field_keeps_word_tables_and_leaves_figure_tables_to_the_data(name):
    md = _doc(name).markdown(data_tables=False)
    assert "| Q3 2026 |" not in md and "| Старт | малый бизнес | чат |" in md
    assert "Выручка за квартал выросла до 412 млн ₽" in md


def test_the_pdf_reads_like_the_docx_it_was_saved_from():
    a, b = _doc("report.docx").markdown(), _doc("report.pdf").markdown()
    assert a == b


def test_a_currency_sign_drawn_after_its_stop_goes_back_before_it():
    doc = read_document("strategiya-2027.pdf", (FIX / "kb" / "strategiya-2027.pdf").read_bytes())
    texts = [b.text for b in doc.blocks]
    assert "Инвестиции по годам, млн ₽:" in texts and not any(":₽" in t for t in texts)


def test_merged_cells_are_filled_and_a_one_cell_frame_is_a_paragraph():
    body = [p("Отчёт", "1"), table([["Регион", "Месяц", "Продажи"], ["Москва", "Янв", "10"], ["", "Фев", "12"], ["", "Мар", "15"]], merge_first_col=True),
            table([["Важно: данные предварительные"]])]
    d = read_document("x.docx", docx_bytes(body))
    t = d.tables[0]
    assert [r[0] for r in t.rows[1:]] == ["Москва", "Москва", "Москва"]
    assert len(d.tables) == 1
    assert any(b.kind == "para" and "предварительные" in b.text for b in d.blocks)


def test_a_broken_or_foreign_file_is_said_in_words():
    with pytest.raises(DocumentError, match="не документ Word"):
        read_document("x.docx", b"PK\x03\x04garbage")
    with pytest.raises(DocumentError, match="не читается как PDF|повреждён"):
        read_document("x.pdf", b"%PDF-1.4\n garbage")
    with pytest.raises(DocumentError, match="пустой"):
        read_document("x.docx", b"")


def test_a_scan_without_a_text_layer_is_said_honestly():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

    w = PdfWriter()
    page = w.add_blank_page(width=595, height=842)
    img = DecodedStreamObject()
    img.set_data(b"\x00" * 16)
    img.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"), NameObject("/Width"): NumberObject(4),
                NameObject("/Height"): NumberObject(4), NameObject("/ColorSpace"): NameObject("/DeviceGray"), NameObject("/BitsPerComponent"): NumberObject(8)})
    ref = w._add_object(img)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): ref})})
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(DocumentError, match="скан без текстового слоя"):
        read_document("scan.pdf", buf.getvalue())


def test_markdown_and_plain_text_read_into_the_same_structure():
    d = read_markdown("a.md", "# План\n\nВступление.\n\n## Цифры\n\nВыручка по годам:\n\n| Год | Выручка |\n|---|---|\n| 2025 | 10 |\n| 2026 | 14 |\n\n- пункт один\n- пункт два\n")
    assert [b.kind for b in d.blocks] == ["heading", "para", "heading", "para", "table", "item", "item"]
    assert d.tables[0].caption == "Выручка по годам" and d.tables[0].is_data
    t = read_document("team.txt", "Команда и найм\n\nВ отделе продаж 46 человек.\n".encode())
    assert t.title == "Команда и найм" and t.blocks[0].kind == "heading"


def test_a_web_page_reads_its_article_without_menus_and_scripts():
    html = """<html><head><title>Блог — компания</title><script>var x=1</script></head><body>
    <nav><a href="/">Главная</a><a href="/about">О нас</a></nav>
    <article><h1>Рынок облаков в 2026 году</h1><p>Рынок вырос на 32% и достиг 210 млрд ₽.</p>
    <h2>Игроки</h2><ul><li>Первый игрок — 28%</li><li>Второй игрок — 19%</li></ul>
    <table><caption>Доли рынка</caption><tr><th>Игрок</th><th>Доля, %</th></tr><tr><td>А</td><td>28</td></tr><tr><td>Б</td><td>19</td></tr></table></article>
    <footer>© 2026</footer></body></html>"""
    d = read_html("page.html", html)
    assert d.title == "Рынок облаков в 2026 году"
    text = d.markdown()
    assert "Главная" not in text and "var x" not in text and "©" not in text
    assert "Рынок вырос на 32% и достиг 210 млрд ₽." in text and "- Первый игрок — 28%" in text
    assert d.tables[0].caption == "Доли рынка" and d.tables[0].is_data
