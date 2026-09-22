"""Generalisation to templates the pipeline was never tuned on.

Two unseen inputs go through the whole offline pipeline (analysis → matching → rendering → audit → autofix):

* ``handdrawn`` — a synthetic deck drawn on the BLANK layout only (tests/fixtures/handdrawn.py): no placeholders,
  per-slide backgrounds, Georgia/Verdana, dark green ground with an orange accent, native table and chart,
  a timeline made of a connector and ovals.  Always available.
* ``lct`` — the hackathon pitch template «ЛЦТ2026 Шаблон презентации.pptx» (37 slides, Montserrat, purple/pink,
  picture backgrounds, native charts, icon sheets).  Skipped when the file is absent; the path can be overridden
  with VERSTKA_LCT_TEMPLATE.

The first block of tests is the contract every template must satisfy.  The second block pins down concrete
generalisation defects found on these two inputs (each test names the code it guards).
"""

from __future__ import annotations

import importlib.util
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from verstka.analysis.manifest import analyze_template
from verstka.analysis.shapes import looks_like_placeholder
from verstka.pipeline.generate import GenerateResult, generate_variants
from verstka.schemas.common import contrast_ratio
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest

pytestmark = pytest.mark.integration

TESTS_DIR = Path(__file__).resolve().parents[1]
OUTLINE_FIXTURE = TESTS_DIR / "fixtures" / "outline_demo.json"
HANDDRAWN_BUILDER = TESTS_DIR / "fixtures" / "handdrawn.py"
LCT_NAME = "ЛЦТ2026 Шаблон презентации.pptx"

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

TIME_BUDGET_S = 120.0
TEMPLATES = ["handdrawn", "lct", "classic43"]
CLASSIC_BUILDER = TESTS_DIR / "fixtures" / "classic43.py"


# ---------------------------------------------------------------------------- inputs


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_handdrawn_module():
    spec = importlib.util.spec_from_file_location("verstka_tests_handdrawn", HANDDRAWN_BUILDER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lct_path() -> Path | None:
    env = os.environ.get("VERSTKA_LCT_TEMPLATE")
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[3] / LCT_NAME)
    return next((c for c in candidates if c.is_file()), None)


@dataclass
class Run:
    name: str
    template: Path
    manifest: TemplateManifest
    result: GenerateResult
    seconds: float
    outline: DeckOutline


@pytest.fixture(scope="module")
def outline() -> DeckOutline:
    return DeckOutline.model_validate_json(OUTLINE_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def handdrawn_module():
    return _load_handdrawn_module()


@pytest.fixture(scope="module")
def template_paths(tmp_path_factory, handdrawn_module) -> dict[str, Path | None]:
    hd = handdrawn_module.build_handdrawn_deck(tmp_path_factory.mktemp("handdrawn") / "handdrawn.pptx")
    classic = _load_module("verstka_tests_classic43", CLASSIC_BUILDER).build_classic_deck(tmp_path_factory.mktemp("classic43") / "classic43.pptx")
    return {"handdrawn": hd, "lct": _lct_path(), "classic43": classic}


@pytest.fixture(scope="module")
def runs(template_paths, outline, tmp_path_factory) -> dict[str, Run]:
    """One offline generation per template, shared by every test of the module (the LCT run is the slow one)."""
    out: dict[str, Run] = {}
    for name, path in template_paths.items():
        if path is None:
            continue
        base = tmp_path_factory.mktemp(f"unseen_{name}")
        t0 = time.time()
        res = generate_variants(path, outline=outline, out_dir=base / "out", workspace_root=base / "ws", use_llm=False, use_vlm=False, audit=True, autofix=True, exports=[])
        out[name] = Run(name=name, template=path, manifest=res.manifest, result=res, seconds=time.time() - t0, outline=outline)
    return out


def _run(runs: dict[str, Run], name: str) -> Run:
    if name not in runs:
        pytest.skip(f"template {name!r} is not available ({LCT_NAME} absent)")
    return runs[name]


# ---------------------------------------------------------------------------- helpers


def _iter_shapes(shapes):
    for sh in shapes:
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(sh.shapes)
        else:
            yield sh


def _slide_texts(slide) -> list[str]:
    out: list[str] = []
    for sh in _iter_shapes(slide.shapes):
        if sh.has_text_frame and sh.text_frame.text.strip():
            out.append(sh.text_frame.text)
        if getattr(sh, "has_table", False) and sh.has_table:
            for row in sh.table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        out.append(cell.text)
    return out


_TYPEFACE_RE = re.compile(r'<a:(?:latin|ea|cs|sym) [^>]*?typeface="([^"]+)"')


def _typefaces_of_xml(xml: str) -> set[str]:
    return {t for t in _TYPEFACE_RE.findall(xml) if t and not t.startswith("+")}


def _template_typefaces(template: Path) -> set[str]:
    """Every explicit typeface anywhere in the template package (slides, layouts, masters, theme, charts)."""
    import zipfile

    faces: set[str] = set()
    with zipfile.ZipFile(template) as z:
        for n in z.namelist():
            if n.endswith(".xml") and n.startswith("ppt/"):
                faces |= _typefaces_of_xml(z.read(n).decode("utf-8", "ignore"))
    return faces


def _deck_typefaces(prs) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for i, s in enumerate(prs.slides, 1):
        faces = _typefaces_of_xml(etree.tostring(s._element).decode("utf-8"))
        for rel in s.part.rels.values():
            if not rel.is_external and rel.reltype.endswith("/chart"):
                faces |= _typefaces_of_xml(rel.target_part.blob.decode("utf-8", "ignore"))
        out[i] = faces
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# ---------------------------------------------------------------------------- contract: analysis


@pytest.mark.parametrize("name", TEMPLATES)
def test_analysis_finds_patterns_of_several_kinds(runs, name):
    m = _run(runs, name).manifest
    assert len(m.patterns) >= 6, [p.kind.value for p in m.patterns]
    kinds = {p.kind for p in m.patterns}
    assert len(kinds) >= 4, sorted(k.value for k in kinds)
    assert not any("extraction failed" in w for w in m.warnings), m.warnings


def test_handdrawn_tokens_come_from_the_deck(runs, handdrawn_module):
    m = _run(runs, "handdrawn").manifest
    families = [f.family for f in m.tokens.typography.families]
    assert handdrawn_module.HEADING_FONT in families and handdrawn_module.BODY_FONT in families, families
    assert set(families[:2]) == {handdrawn_module.HEADING_FONT, handdrawn_module.BODY_FONT}, families
    assert handdrawn_module.ACCENT_HEX in m.tokens.accents(), [(c.hex, c.roles) for c in m.tokens.colors]
    assert m.tokens.color_for("background.dark") == handdrawn_module.BG_HEX
    sizes = set(m.tokens.typography.sizes_used)
    assert {14.0, 16.0, 32.0, 48.0} <= sizes, sorted(sizes)


def test_lct_tokens_come_from_the_deck(runs):
    m = _run(runs, "lct").manifest
    assert m.tokens.typography.primary_family == "Montserrat", [f.family for f in m.tokens.typography.families]
    accents = set(m.tokens.accents())
    assert accents & {"FE095F", "FF0053"}, accents  # the pink brand colour
    assert "520977" in m.tokens.palette()  # the purple of headers and cards


def test_analysis_alone_is_fast(template_paths, tmp_path):
    for name, path in template_paths.items():
        if path is None:
            continue
        t0 = time.time()
        m = analyze_template(path, workspace_root=tmp_path / f"ws_{name}", use_llm=False, use_vlm=False, render=False)
        assert time.time() - t0 < 30, name
        assert m.n_slides >= 9


# ---------------------------------------------------------------------------- contract: generation


@pytest.mark.parametrize("name", TEMPLATES)
def test_three_decks_of_twelve_slides_reopen(runs, name):
    run = _run(runs, name)
    assert [v.strategy for v in run.result.variants] == ["structured", "visual", "compact"]
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        assert len(prs.slides) == 12, (v.strategy, len(prs.slides))
        failed = [w for w in v.warnings if "failed" in w]
        assert not failed, (v.strategy, failed[:5])


@pytest.mark.parametrize("name", TEMPLATES)
def test_no_placeholder_text_is_left(runs, name):
    run = _run(runs, name)
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        leftovers = [(i, t[:60]) for i, s in enumerate(prs.slides, 1) for t in _slide_texts(s) if looks_like_placeholder(t)]
        assert not leftovers, (v.strategy, leftovers[:5])


@pytest.mark.parametrize("name", TEMPLATES)
def test_audit_runs_and_reports(runs, name):
    run = _run(runs, name)
    for v in run.result.variants:
        assert v.audit is not None
        assert len(v.audit.summary.checks_run) >= 15, v.audit.summary.checks_run
        assert (v.out_dir / "audit_report.json").is_file()
        assert not [i for i in v.audit.issues if i.check_id == "file_opens"], v.strategy


@pytest.mark.parametrize("name", TEMPLATES)
def test_fonts_are_from_the_template(runs, name):
    run = _run(runs, name)
    allowed = _template_typefaces(run.template) | {f.family for f in run.manifest.tokens.typography.families}
    for v in run.result.variants:
        errors = [i for i in v.audit.issues if i.check_id == "font_not_in_template" and i.severity == "error"]
        assert not errors, (v.strategy, [(i.slide, i.message) for i in errors][:5])
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        foreign = {i: sorted(f - allowed) for i, f in _deck_typefaces(prs).items() if f - allowed}
        assert not foreign, (v.strategy, foreign)


@pytest.mark.parametrize("name", TEMPLATES)
def test_generation_fits_the_time_budget(runs, name):
    run = _run(runs, name)
    timings = {v.strategy: v.timings for v in run.result.variants}
    assert run.seconds < TIME_BUDGET_S, (round(run.seconds, 1), timings)


# ---------------------------------------------------------------------------- generalisation defects


@pytest.mark.parametrize("name", TEMPLATES)
def test_every_picture_reference_resolves_to_an_image(runs, name):
    """DeckBuilder.clone_slide must remap r:embed inside <p:bg> too, not only inside <p:spTree>."""
    run = _run(runs, name)
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        bad = []
        for i, s in enumerate(prs.slides, 1):
            for blip in s._element.iter(f"{{{NS_A}}}blip"):
                rid = blip.get(f"{{{NS_R}}}embed")
                if not rid:
                    continue
                rel = s.part.rels.get(rid)
                if rel is None:
                    bad.append((i, rid, "missing relationship"))
                elif rel.is_external or not rel.reltype.endswith("/image"):
                    bad.append((i, rid, rel.reltype.rsplit("/", 1)[-1]))
        assert not bad, (v.strategy, bad)


def test_handdrawn_slides_keep_the_template_background(runs, handdrawn_module):
    """The background of a hand-drawn deck lives on the slides; synthesised slides must get it as well."""
    run = _run(runs, "handdrawn")
    bg_hex = handdrawn_module.BG_HEX
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        area = int(prs.slide_width) * int(prs.slide_height)
        missing = []
        for i, s in enumerate(prs.slides, 1):
            bg = s._element.find(f".//{{{NS_P}}}bg")
            ok = bg is not None and any((c.get("val") or "").upper() == bg_hex for c in bg.iter(f"{{{NS_A}}}srgbClr"))
            if not ok:
                for sh in s.shapes:
                    if sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and int(sh.width) * int(sh.height) >= 0.95 * area:
                        fill = sh.fill
                        if fill.type is not None and str(fill.fore_color.rgb).upper() == bg_hex:
                            ok = True
            if not ok:
                missing.append(i)
        assert not missing, (v.strategy, "slides on a white ground:", missing)
        low = [(i.slide, i.message) for i in v.audit.issues if i.check_id == "contrast_low" and i.severity == "error"]
        assert not low, (v.strategy, low[:4])


@pytest.mark.parametrize("name", TEMPLATES)
def test_deck_title_is_written_on_the_first_slide(runs, name):
    """A title pattern without a writable title slot (text baked into the background) must not be chosen."""
    run = _run(runs, name)
    want = _norm(run.outline.title)
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        texts = " | ".join(_norm(t) for t in _slide_texts(prs.slides[0]))
        assert want in texts, (v.strategy, texts[:200])


def test_handdrawn_three_cards_become_a_three_cell_group(runs):
    """groups._satellites must not hand the texts of card N+1 to card N when cards stand close together."""
    m = _run(runs, "handdrawn").manifest
    p = next(p for p in m.patterns if p.source_slide == 3)
    cells = max((len(g.member_shape_ids) for g in p.repeat_groups), default=0)
    assert (p.kind.value, cells) == ("cards", 3), (p.kind.value, [(g.axis, len(g.member_shape_ids), round(g.cell_bbox.w, 2)) for g in p.repeat_groups])


def test_handdrawn_page_numbers_follow_the_new_order(runs):
    """Hand-typed page numbers are chrome: a cloned slide must show its own index, not the sample's."""
    run = _run(runs, "handdrawn")
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        wrong = []
        for i, s in enumerate(prs.slides, 1):
            for sh in s.shapes:
                if sh.name == "Page number" and sh.has_text_frame and sh.text_frame.text.strip() != f"{i:02d}":
                    wrong.append((i, sh.text_frame.text.strip()))
        assert not wrong, (v.strategy, wrong)


def test_handdrawn_agenda_keeps_its_ordinals(runs):
    """Number column and label column are two parallel repeat groups: the ordinals must survive the fill."""
    run = _run(runs, "handdrawn")
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        texts = [sh.text_frame.text.strip() for sh in _iter_shapes(prs.slides[1].shapes) if sh.has_text_frame and sh.name != "Page number"]
        ordinals = [t for t in texts if re.fullmatch(r"0?\d", t)]
        n_items = len(run.outline.slides[1].content.items)
        assert len(ordinals) >= min(n_items, 5), (v.strategy, [t for t in texts if t])


def test_handdrawn_primary_accent_stands_out_from_the_background(runs, handdrawn_module):
    """A card surface (contrast 1.3:1 to the ground) is not an accent: charts and KPI figures take accent.1."""
    m = _run(runs, "handdrawn").manifest
    first = m.tokens.accents()[0]
    assert contrast_ratio(first, handdrawn_module.BG_HEX) >= 2.0, (first, m.tokens.accents())
    assert m.components.chart_style.series_colors[0] == handdrawn_module.ACCENT_HEX, m.components.chart_style.series_colors


def test_lct_icon_sheets_are_not_used_as_content_layouts(runs):
    """Slides that are libraries of 100+ icons must not be matched as cards/big-number layouts."""
    run = _run(runs, "lct")
    icons = {p.id: sum(1 for s in p.slots if s.role.value == "icon") for p in run.manifest.patterns}
    for v in run.result.variants:
        used = [(s.index, s.pattern_id, icons.get(s.pattern_id, 0)) for s in v.render.slides if s.pattern_id and icons.get(s.pattern_id, 0) > 30]
        assert not used, (v.strategy, used)


def test_classic43_keeps_its_own_accent_and_geometry(runs):
    """A 4:3 placeholder template: its teal accent (drawn on the master) leads tables and charts — never a VK blue
    default — and nothing is placed outside the 4:3 slide."""
    run = _run(runs, "classic43")
    m = run.manifest
    assert m.tokens.accents()[0] == "008C8C", m.tokens.accents()
    assert m.components.table_style.header_fill_hex == "008C8C"
    for v in run.result.variants:
        prs = Presentation(str(v.out_dir / "deck.pptx"))
        W, H = int(prs.slide_width), int(prs.slide_height)
        assert (W, H) == (9144000, 6858000)
        out = [(i, sh.name) for i, s in enumerate(prs.slides, 1) for sh in s.shapes if sh.left is not None and (sh.left < -W * 0.01 or sh.left + sh.width > W * 1.01 or sh.top + sh.height > H * 1.01)]
        assert not out, (v.strategy, out)
        faces = set().union(*_deck_typefaces(prs).values())
        assert "0077FF" not in {c.upper() for c in re.findall(r'srgbClr val="([0-9A-Fa-f]{6})"', "".join(etree.tostring(s._element).decode() for s in prs.slides))}, v.strategy
