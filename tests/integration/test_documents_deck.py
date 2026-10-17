"""DOCX и PDF с заголовками и таблицами → бриф и данные → колода (без модели, шаблон VK Tech; пропускается без датасета).

Текст документа (заголовки, абзацы, списки, таблица слов) — бриф; таблица с цифрами — файл данных второй ступени;
колода — история данных по брифу, как у CSV."""

from pathlib import Path

import pytest
from pptx import Presentation

from verstka.data.story import build_data_story
from verstka.ingest.documents import document_tables, read_document
from verstka.pipeline.generate import generate_variants
from verstka.planning.brief import parse_brief_text

pytestmark = pytest.mark.integration
DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@pytest.mark.parametrize("name", ["report.docx", "report.pdf"])
def test_a_document_becomes_a_brief_and_data_and_a_deck(fixtures_dir, tmp_path, name):
    if fixtures_dir is None:
        pytest.skip("VK templates not available")
    pptx = next((p for p in fixtures_dir.glob("*.pptx") if "vk tech" in p.name.lower()), None)
    if pptx is None:
        pytest.skip("VK Tech")
    data = (DOCS / name).read_bytes()
    doc = read_document(name, data)
    brief = parse_brief_text(doc.markdown(data_tables=False))
    tables = document_tables(name, data)
    assert len(tables) == 1 and tables[0].file == name and len(tables[0].rows) == 3
    story = build_data_story(brief, tables, use_llm=False)
    res = generate_variants(pptx, outline=story.outline, strategies=["structured"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws",
                            use_llm=False, use_vlm=False)
    v = res.variants[0]
    prs = Presentation(str(v.out_dir / "deck.pptx"))
    text = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    assert any(sh.has_chart for s in prs.slides for sh in s.shapes), "the table of figures is a chart"
    assert "Итоги третьего квартала 2026" in text.replace("\xa0", " ")
    assert v.audit is None or v.audit.summary.errors == 0
