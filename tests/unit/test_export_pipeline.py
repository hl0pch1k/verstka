from pathlib import Path

import pytest
from typer.testing import CliRunner

from verstka.analysis.manifest import analyze_template
from verstka.cli.main import app
from verstka.export.html import export_html
from verstka.export.svg_charts import chart_svg
from verstka.ingest.render import find_pdftoppm, find_soffice
from verstka.ingest.workspace import TemplateWorkspace
from verstka.matching.matcher import match_outline
from verstka.pipeline.generate import generate_variants
from verstka.pipeline.run_manifest import diff_manifests
from verstka.planning.strategies import get_strategy
from verstka.rendering.renderer import render_deck
from verstka.schemas.deck_ir import IRChart, IRChartSeries
from verstka.schemas.outline import DeckOutline

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"
needs_office = pytest.mark.skipif(find_soffice() is None or find_pdftoppm() is None, reason="LibreOffice/poppler not installed")


def test_svg_chart_types():
    c = IRChart(type="column", categories=["Май", "Июнь"], series=[IRChartSeries(name="Users", values=[1200, 3400])], has_data_labels=True, number_format='#,##0" чел."')
    svg = chart_svg(c, 600, 300, ["0077FF"])
    assert svg.startswith("<svg") and "<rect" in svg and "3 400 чел." in svg
    pie = chart_svg(IRChart(type="doughnut", categories=["a", "b"], series=[IRChartSeries(name="s", values=[30, 70])], has_data_labels=True), 400, 300, ["0077FF", "FF3885"])
    assert pie.count("<path") == 2


def test_html_export_has_markup(simple_deck, tmp_path):
    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    outline = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    plan = match_outline(outline, manifest, get_strategy("structured"))
    render_deck(outline, plan, manifest, ws, tmp_path / "deck.pptx")
    html_path = export_html(tmp_path / "deck.pptx", manifest, tmp_path / "deck.html", title="Демо")
    text = html_path.read_text(encoding="utf-8")
    assert text.count('<section class="slide"') == 12
    assert "<table" in text and "<svg" in text and "@font-face" in text
    assert "Умные напоминания" in text and "Спасибо" in text
    assert "data:font/ttf;base64" in text  # fonts are embedded
    assert "<img" not in text.split('<section class="slide"')[2]  # a text slide has no screenshot image
    assert 'src="data:image' in text or "<img" not in text  # any picture is embedded, never linked


@needs_office
def test_generate_with_audit_autofix_and_exports(simple_deck, tmp_path):
    outline = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    res = generate_variants(simple_deck, outline=outline, strategies=["structured"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, audit=True, autofix=True, exports=["pdf", "html"])
    v = res.variants[0]
    assert v.audit is not None and (v.out_dir / "audit_report.json").exists()
    assert (v.out_dir / "run_manifest.json").exists() and (v.out_dir / "deck.pdf").exists() and (v.out_dir / "deck.html").exists()
    import json

    rm = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert rm["strategy"] == "structured" and "timings_s" in rm and "audit" in rm
    assert diff_manifests(rm, {**rm, "strategy": "visual"})["strategy"]["to"] == "visual"


def test_cli_generate_offline(simple_deck, tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["generate", "--template", str(simple_deck), "--outline", str(FIXTURE), "--strategy", "compact", "--out", str(tmp_path / "cli_out"), "--workspace", str(tmp_path / "ws"), "--no-llm", "--no-vlm", "--no-audit"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "cli_out" / "compact" / "deck.pptx").exists()
    result2 = runner.invoke(app, ["checks"])
    assert result2.exit_code == 0 and "text_overflow" in result2.output


def test_html_keeps_the_line_breaks_inside_a_paragraph():
    # a cover title set in three lines with <a:br/> («Verstka —» / «цифровой дизайнер» / «презентаций»): the web version
    # must not glue the words together («дизайнерпрезентаций»)
    from verstka.export.html import _text_html
    from verstka.schemas.common import Bbox, BboxFrac
    from verstka.schemas.deck_ir import IRElement, IRParagraph, IRRun

    runs = [IRRun(text="Verstka —", size_pt=40), IRRun(text="цифровой дизайнер", size_pt=40), IRRun(text="презентаций", size_pt=40)]
    p = IRParagraph(text="Verstka —\nцифровой дизайнер\nпрезентаций", runs=runs)
    e = IRElement(id="1", type="text", bbox=Bbox(x=0, y=0, w=100, h=100), bbox_frac=BboxFrac(x=0, y=0, w=0.5, h=0.5), paragraphs=[p])
    out = _text_html(e, 12192000, "000000", "Play")
    assert out.count("<br>") == 2
    assert "Verstka —</span><br><span" in out and "цифровой дизайнер</span><br><span" in out


def test_html_keeps_the_paragraphs_line_spacing():
    # a cover title set at 90 % line spacing: at the page's default 1.2 its third line fell out of the frame
    from verstka.export.html import _text_html
    from verstka.schemas.common import Bbox, BboxFrac
    from verstka.schemas.deck_ir import IRElement, IRParagraph, IRRun

    p = IRParagraph(text="Verstka —\nцифровой дизайнер\nпрезентаций", runs=[IRRun(text="Verstka —"), IRRun(text="цифровой дизайнер"), IRRun(text="презентаций")], line_spacing=0.9)
    e = IRElement(id="1", type="text", bbox=Bbox(x=0, y=0, w=100, h=100), bbox_frac=BboxFrac(x=0, y=0, w=0.5, h=0.5), paragraphs=[p])
    assert "line-height:1.08" in _text_html(e, 12192000, "000000", "Play")
