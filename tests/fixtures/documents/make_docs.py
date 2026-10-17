"""Test documents: a DOCX written by hand (the WordprocessingML a Word or LibreOffice file has — heading styles, list
numbering, tables with merged cells) and, through LibreOffice, the same document as a PDF.

    python tests/fixtures/documents/make_docs.py   # rewrites report.docx, report.pdf and the knowledge base set

The tests read the committed files; `docx_bytes` is also imported by them to build variants in memory."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent

CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""
DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>"""
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W}>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="48"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/></w:style>
</w:styles>"""
NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {W}>
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum>
<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""


def _core(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{escape(title)}</dc:title></cp:coreProperties>"""


def p(text: str, style: str = "", num: int = 0, bold: bool = False) -> str:
    ppr = ""
    if style or num:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + (f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num}"/></w:numPr>' if num else "") + "</w:pPr>"
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def table(rows: list[list[str]], merge_first_col: bool = False) -> str:
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/></w:tblPr>']
    for i, r in enumerate(rows):
        out.append("<w:tr>")
        for j, c in enumerate(r):
            tcpr = ""
            if merge_first_col and j == 0 and i >= 1:
                tcpr = '<w:tcPr><w:vMerge w:val="restart"/></w:tcPr>' if i == 1 else "<w:tcPr><w:vMerge/></w:tcPr>"
                c = c if i == 1 else ""
            out.append(f"<w:tc>{tcpr}{p(c)}</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def docx_bytes(body: list[str], title: str = "") -> bytes:
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{"".join(body)}<w:sectPr/></w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/numbering.xml", NUMBERING)
        z.writestr("docProps/core.xml", _core(title))
    return buf.getvalue()


REPORT = [
    p("Итоги третьего квартала 2026", "Title"),
    p("Отдел продаж облачной платформы. Отчёт для правления."),
    p("Главное", "1"),
    p("Выручка за квартал выросла до 412 млн ₽ — на 18% больше, чем во втором квартале. Число корпоративных клиентов достигло 1 240."),
    p("Что сделали", "2"),
    p("Запустили тариф для малого бизнеса", num=1),
    p("Открыли офис в Казани", num=1),
    p("Сократили срок подключения клиента с 14 до 5 дней", num=1),
    p("Выручка по кварталам", "1"),
    p("Выручка и клиенты по кварталам:"),
    table([["Квартал", "Выручка, млн ₽", "Клиенты"], ["Q1 2026", "301", "980"], ["Q2 2026", "349", "1 105"], ["Q3 2026", "412", "1 240"]]),
    p("Сравнение тарифов", "1"),
    table([["Тариф", "Для кого", "Поддержка"], ["Старт", "малый бизнес", "чат"], ["Бизнес", "средние компании", "менеджер"], ["Корпоративный", "крупные компании", "выделенная команда"]]),
    p("Планы на четвёртый квартал", "1"),
    p("Выйти на рынок Казахстана", num=2),
    p("Довести выручку до 450 млн ₽", num=2),
    p("Ключевые риски", bold=True),
    p("Рост цен на оборудование может снизить маржу на 3 п.п."),
]


STRATEGY = [
    p("Стратегия облачной платформы до 2027 года", "Title"),
    p("Цель", "1"),
    p("К концу 2027 года платформа должна обслуживать 3 000 корпоративных клиентов и получать 2,4 млрд ₽ выручки в год."),
    p("Направления", "1"),
    p("Малый бизнес", "2"),
    p("Тариф «Старт» для компаний до 50 сотрудников: подключение за 1 день и оплата картой. Цель — 1 500 клиентов малого бизнеса к 2027 году."),
    p("Регионы", "2"),
    p("Офисы в Казани, Екатеринбурге и Новосибирске. Каждый региональный офис окупается за 18 месяцев."),
    p("Зарубежные рынки", "2"),
    p("Первый зарубежный рынок — Казахстан: запуск в первом квартале 2027 года, партнёр — местный интегратор."),
    p("Инвестиции", "1"),
    p("Инвестиции по годам, млн ₽:"),
    table([["Год", "Дата-центры", "Разработка", "Продажи"], ["2025", "120", "80", "40"], ["2026", "180", "110", "65"], ["2027", "240", "150", "90"]]),
]

CLIENTS_MD = """# Клиенты и отзывы

## Кто наши клиенты

На 30 сентября 2026 года у платформы 1 240 корпоративных клиентов. Из них 610 — малый бизнес, 470 — средние компании, 160 — крупные.

Средний чек корпоративного клиента — 110 тыс. ₽ в квартал.

## Удовлетворённость

Индекс NPS вырос с 31 в первом квартале до 44 в третьем квартале 2026 года.

Главная причина роста — срок подключения сократился с 14 до 5 дней.

## Отток

Отток клиентов за квартал — 2,1%. Чаще всего уходят компании, которым не хватило поддержки на русском языке ночью.
"""

TEAM_TXT = """Команда и найм

В отделе продаж 46 человек: 30 менеджеров, 9 инженеров предпродажи и 7 руководителей.

За третий квартал наняли 12 сотрудников, из них 5 — в новый офис в Казани.

План на четвёртый квартал: нанять ещё 8 инженеров поддержки для ночной смены, чтобы снизить отток.
"""


def main() -> None:
    (HERE / "report.docx").write_bytes(docx_bytes(REPORT, "Итоги третьего квартала 2026"))
    soffice = next((c for c in ("soffice", "/opt/homebrew/bin/soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice") if Path(c).exists() or c == "soffice"), "soffice")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/profile", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(HERE / "report.docx")],
                       check=True, capture_output=True, timeout=120)
        (HERE / "report.pdf").write_bytes((Path(tmp) / "report.pdf").read_bytes())
    kb = HERE / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "otchet-q3.docx").write_bytes(docx_bytes(REPORT, "Итоги третьего квартала 2026"))
    (kb / "clients.md").write_text(CLIENTS_MD, encoding="utf-8")
    (kb / "team.txt").write_text(TEAM_TXT, encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "strategiya-2027.docx"
        src.write_bytes(docx_bytes(STRATEGY, "Стратегия облачной платформы до 2027 года"))
        subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/profile", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
                       check=True, capture_output=True, timeout=120)
        (kb / "strategiya-2027.pdf").write_bytes((Path(tmp) / "strategiya-2027.pdf").read_bytes())
    print("ok", file=sys.stderr)


if __name__ == "__main__":
    main()
