"""Regression tests for the audit/autofix review findings (FIX-1..3, F4, F5, AUD-1, AUD-2, empty deck)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

from verstka.analysis.xmlns import q
from verstka.audit import autofix as af
from verstka.audit.checks.common import composite_hex, enclosing_fill
from verstka.audit.checks.integrity import content_missing, empty_slide
from verstka.audit.checks.layout import table_cell_wrap, text_overflow
from verstka.audit.checks.template import contrast_low
from verstka.audit.registry import AuditContext, all_checks
from verstka.audit.runner import run_audit
from verstka.rendering.renderer import RenderResult
from verstka.schemas.audit import AuditReport, FixAction, Issue
from verstka.schemas.common import Bbox, contrast_ratio
from verstka.schemas.deck_ir import DeckIR, IRElement, IRParagraph, IRRun, IRSlide, IRTable
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent, SlideItem, TableData
from verstka.schemas.template import ColorToken, FontUsage, SlideSize, TemplateManifest, Tokens, Typography

W, H = 12192000, 6858000


# ---------------------------------------------------------------- helpers


def _manifest(dark: bool = False) -> TemplateManifest:
    colors = [
        ColorToken(hex="000000", roles=["background.dark"]),
        ColorToken(hex="FFFFFF", roles=["background.light"] + (["text.primary"] if dark else [])),
        ColorToken(hex="1A1A1A", roles=["text.primary"] if not dark else []),
        ColorToken(hex="0077FF", roles=["accent.1"]),
        ColorToken(hex="151515", roles=["surface"]),
        ColorToken(hex="8F8F8F", roles=["text.secondary"]),
    ]
    typo = Typography(families=[FontUsage(family="Play", weight=1.0)], sizes_used=[12.0, 14.0, 18.0, 24.0, 32.0, 40.0])
    return TemplateManifest(template_id="t", source_file="t.pptx", slide_size=SlideSize(w=W, h=H), tokens=Tokens(colors=colors, typography=typo))


def _el(eid: str, text: str, x: float, y: float, w: float, h: float, *, size: float = 18.0, color: str | None = None, etype: str = "text", fill: str | None = None, autofit: str | None = None, alpha: float | None = None, table: IRTable | None = None) -> IRElement:
    paras = [IRParagraph(text=p, runs=[IRRun(text=p, size_pt=size, color_hex=color, font="Play")]) for p in text.split("\n")] if text else []
    bbox = Bbox(x=int(W * x), y=int(H * y), w=int(W * w), h=int(H * h))
    el = IRElement(id=eid, type=etype, bbox=bbox, bbox_frac=bbox.to_frac(W, H), paragraphs=paras, fill_hex=fill, autofit=autofit, table=table)
    if alpha is not None:  # `fill_alpha` is being added to IRElement by another engineer; work with or without it
        if "fill_alpha" in IRElement.model_fields:
            el.fill_alpha = alpha
        else:
            object.__setattr__(el, "fill_alpha", alpha)
    return el


def _ir(*slides: IRSlide) -> DeckIR:
    return DeckIR(source="x.pptx", slide_w=W, slide_h=H, slides=list(slides))


def _report(pptx: Path, issues: list[Issue]) -> AuditReport:
    return AuditReport(deck=str(pptx), template_id="t", issues=issues).recompute()


def _issue(iid: str, slide: int, check: str, sev: str, oid: str | None, autofix: FixAction | None = None, **details) -> Issue:
    return Issue(id=iid, slide=slide, check_id=check, severity=sev, kind="deterministic", message=iid, outline_id=oid, autofix=autofix, details=details)


def _card_deck(path: Path) -> tuple[Path, str]:
    """One slide: a dark card (#151515) whose text box has blue (#0077FF) runs. Returns (path, card shape id)."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    card = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(int(W * 0.1)), Emu(int(H * 0.3)), Emu(int(W * 0.3)), Emu(int(H * 0.3)))
    card.fill.solid()
    card.fill.fore_color.rgb = RGBColor(0x15, 0x15, 0x15)
    card.line.fill.solid()
    card.line.fill.fore_color.rgb = RGBColor(0x00, 0x77, 0xFF)
    card.text_frame.text = "Каждый третий дедлайн срывается"
    r = card.text_frame.paragraphs[0].runs[0]
    r.font.size = Pt(18)
    r.font.color.rgb = RGBColor(0x00, 0x77, 0xFF)
    prs.save(str(path))
    return path, str(card.shape_id)


def _colors(path: Path, sid: str) -> tuple[str | None, list[str], str | None]:
    """(spPr fill hex, run colours, line hex) of shape sid on slide 1."""
    prs = Presentation(str(path))
    sp = next(sh for sh in prs.slides[0].shapes if str(sh.shape_id) == sid)._element
    fill = sp.find(q("p:spPr") + "/" + q("a:solidFill") + "/" + q("a:srgbClr"))
    line = sp.find(q("p:spPr") + "/" + q("a:ln") + "/" + q("a:solidFill") + "/" + q("a:srgbClr"))
    runs = [c.get("val") for rPr in sp.iter(q("a:rPr")) for c in rPr.iter(q("a:srgbClr"))]
    return (fill.get("val") if fill is not None else None), runs, (line.get("val") if line is not None else None)


# ---------------------------------------------------------------- FIX-1: info issues, recolor scope, contrast target


def test_plan_fixes_skips_info_unless_requested():
    plan = LayoutPlan(strategy="visual", template_id="t")
    info = _issue("contrast_low-3-1", 3, "contrast_low", "info", "sl3", FixAction(action="recolor", params={"element_ids": ["442"], "to": "FFFFFF", "scope": "text"}))
    warn = _issue("contrast_low-4-2", 4, "contrast_low", "warn", "sl4", FixAction(action="recolor", params={"element_ids": ["9"], "to": "FFFFFF", "scope": "text"}))
    report = _report(Path("x.pptx"), [info, warn])
    fixes = af.plan_fixes(report, plan)
    assert "sl3" not in fixes and "sl4" in fixes
    fixes = af.plan_fixes(report, plan, only_ids={"contrast_low-3-1"})
    assert list(fixes) == ["sl3"]


def test_recolor_text_scope_leaves_card_fill_alone(tmp_path):
    path, sid = _card_deck(tmp_path / "card.pptx")
    manifest = _manifest(dark=True)
    act = FixAction(action="recolor", params={"element_ids": [sid], "to": "FFFFFF", "scope": "text"})
    lines = af._xml_fixes(path, [(1, act)], manifest, W, H)
    fill, runs, line = _colors(path, sid)
    assert fill == "151515" and line == "0077FF", "card fill and outline must not be recoloured"
    assert runs and all(c == "FFFFFF" for c in runs)
    assert len(lines) == 1 and lines[0]["kind"] == "recolor" and lines[0]["slide"] == 1
    assert lines[0]["result"] == "Цвет текста заменён на #FFFFFF"
    # nothing left to change → nothing recorded
    assert af._xml_fixes(path, [(1, act)], manifest, W, H) == []


def test_recolor_all_scope_with_hex_filter_touches_only_that_colour(tmp_path):
    path, sid = _card_deck(tmp_path / "card.pptx")
    manifest = _manifest(dark=True)
    manifest.tokens.colors = [c for c in manifest.tokens.colors if c.hex != "151515"] + [ColorToken(hex="121212", roles=["surface"])]
    act = FixAction(action="recolor", params={"element_ids": [sid], "hex": "151515", "scope": "all"})
    lines = af._xml_fixes(path, [(1, act)], manifest, W, H)
    fill, runs, line = _colors(path, sid)
    assert fill == "121212" and line == "0077FF" and all(c == "0077FF" for c in runs)
    assert len(lines) == 1


def test_contrast_low_targets_real_background_and_composites_alpha():
    manifest = _manifest(dark=True)
    # WorkSpace compact slide 5: a 0077FF card at alpha 0.298 over a black slide → #00234C; blue text on it → 3.78:1 → info (accent ≥ 3.0)
    card = _el("10", "", 0.1, 0.2, 0.3, 0.5, etype="shape", fill="0077FF", alpha=0.298)
    txt = _el("11", "Дайджест", 0.12, 0.25, 0.25, 0.1, color="0077FF", size=14)  # regular text: 4.5:1 applies
    slide = IRSlide(index=1, family="dark", background_hex="000000", elements=[card, txt], outline_id="sl5")
    assert composite_hex("0077FF", 0.298, "000000") == "00234C"
    assert enclosing_fill(slide, txt) == "00234C"
    issues = contrast_low(AuditContext(ir=_ir(slide), manifest=manifest))
    assert len(issues) == 1 and issues[0].severity == "info", [i.message for i in issues]
    assert abs(issues[0].details["contrast"] - contrast_ratio("0077FF", "00234C")) < 0.01
    fx = issues[0].autofix
    assert fx is not None and fx.action == "recolor" and fx.params["to"] == "FFFFFF" and fx.params["scope"] == "text"
    # opaque dark card, blue text: the candidate is text.primary (FFFFFF) and it reaches 4.5:1
    card2 = _el("20", "", 0.1, 0.2, 0.3, 0.5, etype="shape", fill="151515")
    txt2 = _el("21", "Каждый третий", 0.12, 0.25, 0.25, 0.1, color="0077FF", size=14)
    slide2 = IRSlide(index=2, family="dark", background_hex="000000", elements=[card2, txt2], outline_id="sl3")
    issues = contrast_low(AuditContext(ir=_ir(slide2), manifest=manifest))
    assert len(issues) == 1 and issues[0].autofix.params["to"] == "FFFFFF"
    assert contrast_ratio("FFFFFF", "151515") >= 4.5


def test_contrast_low_prefers_template_text_colour_that_reaches_ratio():
    manifest = _manifest(dark=False)  # text.primary = 1A1A1A
    txt = _el("5", "серый на белом", 0.1, 0.2, 0.5, 0.1, color="BBBBBB", size=14)
    slide = IRSlide(index=1, family="light", background_hex="FFFFFF", elements=[txt], outline_id="sl2")
    issues = contrast_low(AuditContext(ir=_ir(slide), manifest=manifest))
    assert len(issues) == 1 and issues[0].autofix is not None
    assert issues[0].autofix.params["to"] == "1A1A1A"


# ---------------------------------------------------------------- FIX-2: rollback of a regressing iteration


def _rematch_setup(tmp_path: Path):
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"ORIGINAL")
    outline = DeckOutline(title="t", slides=[OutlineSlide(id="s1", kind="bullets", headline="h", content=SlideContent(bullets=["a"])), OutlineSlide(id="s2", kind="bullets", headline="h2", content=SlideContent(bullets=["b"]))])
    plan = LayoutPlan(strategy="visual", template_id="t", slides=[LayoutSlide(outline_id="s1", mode="clone", pattern_id="p1", alternatives=[("p2", 0.9)]), LayoutSlide(outline_id="s2", mode="clone", pattern_id="p3")])
    overlap = _issue("overlap-1-1", 1, "overlap", "error", "s1", FixAction(action="rematch", params={"outline_id": "s1"}))
    return pptx, outline, plan, overlap


def test_autofix_rolls_back_a_regressing_iteration(tmp_path, monkeypatch):
    pptx, outline, plan, overlap = _rematch_setup(tmp_path)
    report0 = _report(pptx, [overlap])
    audits: list[str] = []

    def fake_render(outline, plan, manifest, ws, out, **kw):
        Path(out).write_bytes(b"WORSE")
        return RenderResult(pptx_path=Path(out))

    def fake_audit(path, manifest, outline=None, ws=None, **kw):
        audits.append(Path(path).read_bytes().decode())
        if Path(path).read_bytes() == b"WORSE":
            return _report(path, [_issue("empty_slide-1-1", 1, "empty_slide", "error", "s1"), _issue("content_missing-1-2", 1, "content_missing", "error", "s1")])
        return _report(path, [overlap.model_copy()])

    monkeypatch.setattr(af, "render_deck", fake_render)
    monkeypatch.setattr(af, "run_audit", fake_audit)
    final, plan2, outline2, rr = af.autofix_loop(pptx, report0, outline, plan, _manifest(), None, max_iterations=2)
    assert pptx.read_bytes() == b"ORIGINAL", "the regressing deck must not ship"
    assert final.summary.errors == 1 and final.iterations == 1
    assert plan2.for_outline("s1").pattern_id == "p1" and plan2.for_outline("s1").mode == "clone", "plan restored with the deck"
    rollbacks = [f for f in final.applied_fixes if f.get("action") == "rollback"]
    assert len(rollbacks) == 1 and rollbacks[0]["iteration"] == 1 and "возвращена предыдущая версия" in rollbacks[0]["result"]
    assert audits[-1] == "ORIGINAL", "the restored deck is audited again so slide images match"
    assert not [p for p in tmp_path.iterdir() if p.name != "deck.pptx"], "snapshots are deleted"


def test_autofix_keeps_an_improving_iteration(tmp_path, monkeypatch):
    pptx, outline, plan, overlap = _rematch_setup(tmp_path)
    report0 = _report(pptx, [overlap])
    monkeypatch.setattr(af, "render_deck", lambda outline, plan, manifest, ws, out, **kw: (Path(out).write_bytes(b"BETTER"), RenderResult(pptx_path=Path(out)))[1])
    monkeypatch.setattr(af, "run_audit", lambda path, manifest, outline=None, ws=None, **kw: _report(path, []))
    final, plan2, _, _ = af.autofix_loop(pptx, report0, outline, plan, _manifest(), None, max_iterations=2)
    assert pptx.read_bytes() == b"BETTER" and final.summary.errors == 0
    assert plan2.for_outline("s1").pattern_id == "p2"
    assert not any(f.get("action") == "rollback" for f in final.applied_fixes)
    assert not [p for p in tmp_path.iterdir() if p.name != "deck.pptx"]


# ---------------------------------------------------------------- FIX-3: no blanket rematch override, norm autofit, scale snapping


def test_plan_fixes_keeps_the_checks_decision_for_overflow():
    plan = LayoutPlan(strategy="visual", template_id="t")
    shrink = FixAction(action="shrink_text", params={"outline_id": "sl1", "element_id": "7", "ratio": 1.9})
    report = _report(Path("x.pptx"), [_issue("text_overflow-1-1", 1, "text_overflow", "warn", "sl1", shrink, ratio=1.9, autofit="norm")])
    fixes = af.plan_fixes(report, plan)
    assert [a.action for a in fixes["sl1"]] == ["shrink_text"]
    assert not hasattr(af, "REMATCH_CHECKS")


def test_text_overflow_with_norm_autofit_is_info_without_autofix():
    manifest = _manifest()
    long = "Умные напоминания в VK WorkSpace: итоги пилота и план запуска для продуктового комитета"
    norm = _el("1", long, 0.1, 0.1, 0.5, 0.1, size=24, autofit="norm")
    none = _el("2", long, 0.1, 0.5, 0.5, 0.1, size=24)
    slide = IRSlide(index=1, elements=[norm, none], outline_id="sl1")
    issues = {i.element_ids[0]: i for i in text_overflow(AuditContext(ir=_ir(slide), manifest=manifest))}
    assert 1.08 < issues["1"].details["ratio"] <= 2.5, issues["1"].details
    assert issues["1"].severity == "info" and issues["1"].autofix is None
    assert issues["2"].severity in ("warn", "error") and issues["2"].autofix is not None


def test_shrink_text_snaps_to_template_scale(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = s.shapes.add_textbox(Emu(int(W * 0.1)), Emu(int(H * 0.1)), Emu(int(W * 0.5)), Emu(int(H * 0.1)))
    tb.text_frame.text = "Заголовок"
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(40)
    prs.save(str(tmp_path / "d.pptx"))
    sid = str(tb.shape_id)
    manifest = _manifest()  # sizes 12 14 18 24 32 40
    af._xml_fixes(tmp_path / "d.pptx", [(1, FixAction(action="shrink_text", params={"element_id": sid, "ratio": 1.3}))], manifest, W, H)
    prs = Presentation(str(tmp_path / "d.pptx"))
    sz = prs.slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt
    assert sz == 24.0, sz  # 40/1.3 = 30.8 → largest scale step that fits
    af._xml_fixes(tmp_path / "d.pptx", [(1, FixAction(action="shrink_text", params={"element_id": sid, "ratio": 1.1}))], manifest, W, H)
    prs = Presentation(str(tmp_path / "d.pptx"))
    assert prs.slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt == 18.0
    # below the scale: never an out-of-scale 6 pt run (Education's scale starts at 12 pt)
    assert af._snap_size(12.0, 0.6, [12.0, 14.0, 18.0]) == 12.0  # target 7.2 is far from any step → unchanged
    assert af._snap_size(12.0, 0.87, [12.0, 14.0, 18.0]) == 10.5  # within 2 pt of 12 → tolerated (audit: info)
    assert af._snap_size(20.0, 0.6, [18.0, 24.0]) == 18.0  # nothing ≤ 12 in scale: smallest step below 20
    af._xml_fixes(tmp_path / "d.pptx", [(1, FixAction(action="shrink_text", params={"element_id": sid, "ratio": 6.5}))], manifest, W, H)
    prs = Presentation(str(tmp_path / "d.pptx"))
    assert prs.slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt == 12.0  # 18 → smallest step, never 6 pt


# ---------------------------------------------------------------- F4: XML fixes after a re-render, move_inside


def test_xml_fixes_are_rederived_after_a_rerender(tmp_path, monkeypatch):
    pptx, outline, plan, overlap = _rematch_setup(tmp_path)
    font_issue = _issue("font_not_in_template-2-2", 2, "font_not_in_template", "error", "s2", FixAction(action="refont", params={"element_ids": ["30"]}))
    report0 = _report(pptx, [overlap, font_issue])
    fresh_refont = FixAction(action="refont", params={"element_ids": ["77"]})
    calls: list[list[tuple[int, FixAction]]] = []

    audits: list[bool] = []

    def fake_audit(path, manifest, outline=None, ws=None, render=True, **kw):
        audits.append(render)
        if len(audits) == 1:  # the audit right after the re-render: element ids changed
            return _report(path, [_issue("font_not_in_template-2-9", 2, "font_not_in_template", "error", "s2", fresh_refont)])
        return _report(path, [])

    monkeypatch.setattr(af, "render_deck", lambda outline, plan, manifest, ws, out, **kw: (Path(out).write_bytes(b"NEW"), RenderResult(pptx_path=Path(out)))[1])
    monkeypatch.setattr(af, "run_audit", fake_audit)
    monkeypatch.setattr(af, "_ir_slides", lambda report: [SimpleNamespace(outline_id="s1", index=1), SimpleNamespace(outline_id="s2", index=2)])
    monkeypatch.setattr(af, "_xml_fixes", lambda p, actions, manifest, w, h: calls.append(list(actions)) or [{"slide": i, "kind": a.action, "element_id": a.params["element_ids"][0], "result": "Шрифт заменён"} for i, a in actions])
    final, *_ = af.autofix_loop(pptx, report0, outline, plan, _manifest(), None, max_iterations=2)
    assert calls == [[(2, fresh_refont)]], calls
    assert audits == [False, False]  # without models no audit of the loop starts LibreOffice
    xml = [f for f in final.applied_fixes if f.get("action") == "xml"]
    assert xml and xml[0]["iteration"] == 1 and xml[0]["element_id"] == "77" and xml[0]["slide"] == 2
    assert final.summary.errors == 0


def test_move_inside_handles_oversized_elements_and_safe_area(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    wide = s.shapes.add_textbox(Emu(int(-0.015 * W)), Emu(int(H * 0.2)), Emu(int(W * 1.039)), Emu(int(H * 0.5)))
    wide.text_frame.text = "chart-like"
    edge = s.shapes.add_textbox(Emu(int(W * 0.01)), Emu(int(H * 0.3)), Emu(int(W * 0.3)), Emu(int(H * 0.1)))
    edge.text_frame.text = "12 400"
    prs.save(str(tmp_path / "d.pptx"))
    manifest = _manifest()
    safe = manifest.tokens.spacing.safe_area  # x=0.05 y=0.08 w=0.90 h=0.84
    actions = [(1, FixAction(action="move_inside", params={"element_id": str(wide.shape_id)})), (1, FixAction(action="move_inside", params={"element_id": str(edge.shape_id), "safe": True}))]
    lines = af._xml_fixes(tmp_path / "d.pptx", actions, manifest, W, H)
    assert len(lines) == 2
    prs = Presentation(str(tmp_path / "d.pptx"))
    shapes = {str(sh.shape_id): sh for sh in prs.slides[0].shapes}
    w2 = shapes[str(wide.shape_id)]
    margin = round(safe.x * W)
    assert w2.left == margin and w2.width == W - 2 * margin, (w2.left, w2.width)
    e2 = shapes[str(edge.shape_id)]
    assert e2.left == margin and e2.width == int(W * 0.3)


# ---------------------------------------------------------------- AUD-1: content that disappeared from a slide


def _outline_process() -> DeckOutline:
    items = [SlideItem(title="Неделя 1", text="Включаем"), SlideItem(title="Неделя 2", text="Раскатываем"), SlideItem(title="Неделя 3", text="Публикуем"), SlideItem(title="Далее", text="Интеграция")]
    numbers = [NumberCallout(value="12 400", label="участников пилота"), NumberCallout(value="+34%", label="задач завершены в срок"), NumberCallout(value="2,1 ч", label="экономии в неделю")]
    return DeckOutline(
        title="t",
        slides=[
            OutlineSlide(id="sl9", kind="process", headline="Запуск за три недели", content=SlideContent(items=items)),
            OutlineSlide(id="sl4", kind="stat_row", headline="Пилот подтвердил эффект", content=SlideContent(numbers=numbers)),
            OutlineSlide(id="sl7", kind="table", headline="Функциональность по тарифам", content=SlideContent(table=TableData(columns=["Сценарий", "Базовый", "Про"], rows=[["Дайджест", "нет", "да"]]))),
        ],
    )


def test_content_missing_flags_only_real_losses():
    outline = _outline_process()
    manifest = _manifest()
    lost = IRSlide(index=1, outline_id="sl9", elements=[_el("1", "ЗАПУСК ЗА ТРИ НЕДЕЛИ", 0.1, 0.1, 0.8, 0.1, size=32), _el("2", "01 Неделя 1\nВключаем", 0.1, 0.3, 0.3, 0.2), _el("3", "02 Неделя 2\nРаскатываем", 0.45, 0.3, 0.3, 0.2)])
    kpi = IRSlide(index=2, outline_id="sl4", elements=[_el("4", "Пилот подтвердил эффект", 0.1, 0.1, 0.8, 0.1, size=32), _el("5", "12 400", 0.1, 0.3, 0.2, 0.2, size=54), _el("6", "участников пилота", 0.1, 0.5, 0.2, 0.1), _el("7", "+34 %", 0.4, 0.3, 0.2, 0.2, size=54), _el("8", "задач завершены в срок", 0.4, 0.5, 0.2, 0.1)])
    table = IRSlide(index=3, outline_id="sl7", elements=[_el("9", "Функциональность по тарифам", 0.1, 0.1, 0.8, 0.1, size=32), _el("10", "", 0.1, 0.3, 0.8, 0.5, etype="table", table=IRTable(rows=[["Сценарий", "Базовый", "Про"], ["Дайджест", "нет", "да"]]))])
    issues = content_missing(AuditContext(ir=_ir(lost, kpi, table), manifest=manifest, outline=outline))
    by_slide = {i.slide: i for i in issues}
    assert set(by_slide) == {1, 2}, [(i.slide, i.message) for i in issues]
    i9 = by_slide[1]
    assert i9.severity == "error" and i9.check_id == "content_missing" and i9.details["missing"] == ["Неделя 3", "Далее"]
    assert i9.message.startswith("2 из 5 текстов плана нет на слайде") and "Неделя 3" in i9.message
    assert i9.autofix is not None and i9.autofix.action == "rematch" and i9.autofix.params["outline_id"] == "sl9"
    i4 = by_slide[2]  # the third KPI («2,1 ч», «экономии в неделю») is lost (2 of 7 < 1/3 → warn), «12 400» with NBSP is not
    assert i4.severity == "warn" and i4.details["missing"] == ["2,1 ч", "экономии в неделю"]
    # one small loss out of many strings is a warning
    warn_slide = IRSlide(index=4, outline_id="sl9", elements=[_el("1", "Запуск за три недели", 0.1, 0.1, 0.8, 0.1), _el("2", "Неделя 1", 0.1, 0.3, 0.2, 0.1), _el("3", "Неделя 2", 0.3, 0.3, 0.2, 0.1), _el("4", "Неделя 3", 0.5, 0.3, 0.2, 0.1)])
    issues = content_missing(AuditContext(ir=_ir(warn_slide), manifest=manifest, outline=outline))
    assert len(issues) == 1 and issues[0].severity == "warn" and issues[0].details["missing"] == ["Далее"]
    # no outline → silent
    assert content_missing(AuditContext(ir=_ir(lost), manifest=manifest)) == []


def test_empty_slide_counts_a_picture_only_with_an_image_hint():
    manifest = _manifest()
    outline = DeckOutline(title="t", slides=[OutlineSlide(id="c", kind="cards", headline="h", content=SlideContent(items=[SlideItem(title="a")])), OutlineSlide(id="i", kind="image_text", headline="h", content=SlideContent(paragraphs=["p"])), OutlineSlide(id="p", kind="bullets", headline="h", content=SlideContent(bullets=["b"], image_hint="office"))])

    def slide(idx: int, oid: str) -> IRSlide:
        return IRSlide(index=idx, outline_id=oid, elements=[_el(f"{idx}t", "Заголовок слайда", 0.1, 0.1, 0.8, 0.1, size=32), _el(f"{idx}p", "", 0.1, 0.3, 0.5, 0.5, etype="picture")])

    ir = _ir(IRSlide(index=1, elements=[_el("0", "Титул", 0.1, 0.3, 0.8, 0.2, size=40)]), slide(2, "c"), slide(3, "i"), slide(4, "p"), IRSlide(index=5, elements=[_el("9", "Спасибо", 0.1, 0.3, 0.8, 0.2, size=40)]))
    issues = empty_slide(AuditContext(ir=ir, manifest=manifest, outline=outline))
    assert [i.slide for i in issues] == [2], [(i.slide, i.message) for i in issues]


# ---------------------------------------------------------------- F5: tables are not text boxes; header words wrapping mid-word


def _table_deck(path: Path, width_frac: float) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    cols = ["Сценарий", "Базовый", "Про", "Корпоративный"]
    rows = [["Напоминание из чата", "да", "да", "да"], ["Умный срок", "нет", "да", "да"], ["Эскалация", "нет", "нет", "да"], ["Дайджест", "нет", "да", "да"]]
    gf = s.shapes.add_table(len(rows) + 1, len(cols), Emu(int(W * 0.05)), Emu(int(H * 0.25)), Emu(int(W * width_frac)), Emu(int(H * 0.5)))
    for j, c in enumerate(cols):
        gf.table.cell(0, j).text = c
    for i, r in enumerate(rows, 1):
        for j, v in enumerate(r):
            gf.table.cell(i, j).text = v
    prs.save(str(path))
    return path


def test_tables_are_not_audited_as_text_boxes(tmp_path):
    from verstka.audit.ir import build_deck_ir

    deck = _table_deck(tmp_path / "t.pptx", 0.9)
    ctx = AuditContext(ir=build_deck_ir(deck), manifest=_manifest())
    assert any(e.type == "table" for e in ctx.ir.slides[0].elements)
    assert text_overflow(ctx) == []
    assert not [i for i in run_audit(deck, _manifest(), render=False).issues if i.check_id in ("text_overflow", "margin_violation", "grid_alignment", "contrast_low", "font_not_in_template", "size_not_in_scale", "bullet_too_long", "too_many_bullets") and "10" not in i.element_ids or i.check_id == "text_overflow"]


def test_table_cell_wrap_flags_narrow_tables(tmp_path):
    from verstka.audit.ir import build_deck_ir

    manifest = _manifest()
    narrow = _table_deck(tmp_path / "narrow.pptx", 0.25)
    issues = table_cell_wrap(AuditContext(ir=build_deck_ir(narrow), manifest=manifest))
    assert len(issues) == 1 and issues[0].check_id == "table_cell_wrap" and issues[0].severity == "warn"
    assert "Корпоративный" in issues[0].message and issues[0].autofix is not None and issues[0].autofix.action == "rematch"
    wide = _table_deck(tmp_path / "wide.pptx", 0.9)
    assert table_cell_wrap(AuditContext(ir=build_deck_ir(wide), manifest=manifest)) == []
    assert {"table_cell_wrap", "content_missing", "empty_deck"} <= {spec.id for spec, _ in all_checks()}


# ---------------------------------------------------------------- minor: fill_ratio wording, empty deck


def test_fill_ratio_description_matches_code():
    from verstka.audit.checks.density import FILL_RATIO

    assert "80" in FILL_RATIO.description and "75" not in FILL_RATIO.description
    assert "три четверти" not in FILL_RATIO.title


def test_empty_deck_is_an_error(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    prs.save(str(tmp_path / "empty.pptx"))
    report = run_audit(tmp_path / "empty.pptx", _manifest(), render=False)
    assert report.summary.errors >= 1 and report.summary.score < 100
    assert any(i.check_id == "empty_deck" and i.slide == 0 and i.severity == "error" for i in report.issues)


def test_a_grid_of_roomy_cards_is_not_too_dense_but_a_wall_of_text_is():
    """«Слишком плотно» is about ink, not boxes: four big cards with a line of text each fill the grid of the template
    (86% of the safe area by their boxes) and read as airy; the same boxes full of lines are a wall of text."""
    from verstka.audit.checks.density import fill_ratio

    def slide(text: str) -> IRSlide:
        els = [_el(f"c{i}", text, 0.06 + (i % 2) * 0.45, 0.1 + (i // 2) * 0.42, 0.43, 0.4, size=16.0) for i in range(4)]
        return IRSlide(index=2, elements=els)

    airy = fill_ratio(AuditContext(ir=_ir(IRSlide(index=1, elements=[]), slide("Экономия 2,1 часа в неделю"), IRSlide(index=3, elements=[])), manifest=_manifest()))
    assert not [i for i in airy if i.slide == 2 and i.severity == "warn"], [i.message for i in airy]
    wall = "\n".join(["Длинный абзац текста, который занимает всю ширину карточки и много строк подряд"] * 9)
    dense = fill_ratio(AuditContext(ir=_ir(IRSlide(index=1, elements=[]), slide(wall), IRSlide(index=3, elements=[])), manifest=_manifest()))
    assert any(i.slide == 2 and i.severity == "warn" and "заполнен на" in i.message for i in dense), [i.message for i in dense]
