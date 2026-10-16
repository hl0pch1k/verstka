"""Колода из семи файлов примера на трёх шаблонах VK и на незнакомом (LibreOffice «Forestbird», при разработке не
использовался), без модели: история строится, вариант визуализации датасета один во всех трёх вариантах и на всех
шаблонах (и в плане, и в самих файлах .pptx), `OutlineSlide.data` заполнено, аудит без замечаний к данным, а вся
работа — история, вёрстка трёх вариантов и аудит на четырёх шаблонах — укладывается в 60 секунд.

Шаблоны VK — из папки «Датасет» (VERSTKA_FIXTURES_DIR или рядом с репозиторием); их разбор берётся из рабочей папки
владельца, если он там свежий (иначе шаблон разбирается заново — это время в 60 секунд не входит). Второй набор данных
(`examples/data-science-2026/`) проходит тот же путь на незнакомом шаблоне без падений."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from verstka.audit.ir import build_deck_ir
from verstka.audit.runner import run_audit
from verstka.data.readers import read_file
from verstka.data.story import build_data_story
from verstka.ingest.workspace import TemplateWorkspace, file_sha256
from verstka.pipeline.generate import generate_variants
from verstka.schemas.outline import Brief
from verstka.schemas.template import TemplateManifest

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
SCIENCE = ROOT / "examples" / "data-science-2026"
UNSEEN = ROOT / "tests" / "fixtures" / "data_story" / "lo_forestbird.pptx"
BRIEF = ("Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, что даёт "
         "выручку и где узкие места. Данные — в приложенных файлах.")
SCIENCE_BRIEF = ("Итоги университета за 2026 год для учёного совета. Покажи, как подготовка влияет на баллы ЕГЭ, как устроен "
                 "приём по формам обучения, как растёт наука и на что ушёл бюджет НИОКР. Данные — в приложенных файлах.")
VK_NAMES = ("vk tech", "workspace", "education")
DATA_CHECKS = {"headline_no_conclusion", "headline_figure_not_in_data", "chart_values_mismatch", "chart_no_units",
               "chart_no_source", "chart_overloaded", "table_raw_dump", "chart_from_untypable", "data_split_inconsistent"}
DATA_EXT = {".csv", ".xlsx", ".json", ".txt"}


def _vk_templates() -> list[Path]:
    env = os.environ.get("VERSTKA_FIXTURES_DIR")
    dirs = ([Path(env)] if env else []) + [p / "Датасет" for p in ROOT.parents]
    for d in dirs:
        if d.is_dir():
            found = [next((p for p in d.glob("*.pptx") if n in p.name.lower()), None) for n in VK_NAMES]
            if all(found):
                return found  # type: ignore[return-value]
    return []


def _cached(template: Path, root: Path) -> bool:
    """The owner's analysis of the template, when it is current: copied into the test's workspace."""
    tid = file_sha256(template)[:16]
    for ws in [p / "workspace" / "templates" / tid for p in ROOT.parents]:
        m = ws / "manifest.json"
        if m.is_file():
            try:
                version = json.loads(m.read_text(encoding="utf-8")).get("analysis_version")
            except (OSError, ValueError):
                continue
            if version == TemplateManifest.model_fields["analysis_version"].default:
                shutil.copytree(ws, root / "templates" / tid, dirs_exist_ok=True)
                return True
    return False


def _tables(folder: Path):
    return [t for p in sorted(folder.iterdir()) if p.suffix.lower() in DATA_EXT and p.is_file() for t in read_file(p)]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from verstka.analysis.manifest import analyze_template

    root = tmp_path_factory.mktemp("ws")
    templates = _vk_templates() + [UNSEEN]
    for t in templates:
        if not _cached(t, root):
            analyze_template(t, workspace_root=root, use_llm=False, use_vlm=False)  # (not timed: a template is analysed once)
    tables = _tables(SALES)
    t0 = time.monotonic()
    out = {}
    for t in templates:
        story = build_data_story(Brief(text=BRIEF, slide_count=9), tables)
        res = generate_variants(t, outline=story.outline, out_dir=tmp_path_factory.mktemp("out"), workspace_root=root,
                                use_llm=False, use_vlm=False, audit=False, autofix=False, exports=[], render_images=False, pictures=False)
        ws = TemplateWorkspace.open(res.template_id, root)
        audits = {v.strategy: run_audit(v.out_dir / "deck.pptx", res.manifest, v.outline, ws, render=False, use_vlm=False, use_llm=False, strategy=v.strategy) for v in res.variants}
        out[t.name] = (story, res, audits)
    seconds = time.monotonic() - t0
    return out, seconds, len(templates)


def test_the_sample_deck_builds_on_every_template_in_a_minute(built):
    out, seconds, n = built
    if n < 4:
        pytest.skip("the VK templates are not available (VERSTKA_FIXTURES_DIR): only the unseen one was built")
    assert seconds <= 60, f"{seconds:.1f} s for 4 templates × 3 variants"


def test_a_dataset_keeps_its_chart_in_every_variant_and_template(built):
    out, _, _ = built
    planned: dict[str, set] = {}
    drawn: dict[str, set] = {}
    for name, (story, res, audits) in out.items():
        assert len(res.variants) == 3
        for v in res.variants:
            data = [s for s in v.outline.slides if s.data is not None]
            assert len(data) == 7, (name, v.strategy)
            ir = build_deck_ir(v.out_dir / "deck.pptx")
            by_id = {s.outline_id: s for s in ir.slides}
            for k, s in enumerate(v.outline.slides):
                if s.data is None:
                    continue
                c = s.content
                planned.setdefault(s.data.file, set()).add(c.chart.type if c.chart else "table" if c.table else "cards")
                ir_slide = by_id.get(s.id) or ir.slides[k]
                charts = [(e.chart.type, e.chart.grouping, e.chart.gap_width == 0) for e in ir_slide.elements if e.chart]
                tables = [e for e in ir_slide.elements if e.table]
                drawn.setdefault(s.data.file, set()).add(tuple(charts) if charts else ("table",) if tables else ("cards",))
    assert all(len(v) == 1 for v in planned.values()), planned
    assert all(len(v) == 1 for v in drawn.values()), drawn
    assert planned["Выручка по месяцам.csv"] == {"line"} and planned["Регионы.xlsx"] == {"bar"}
    assert planned["Каналы продаж.json"] == {"doughnut"} and planned["Время ответа поддержки.csv"] == {"histogram"}
    assert planned["Клиенты.xlsx"] == {"table"} and planned["Итоги квартала.txt"] == {"cards"}


def test_the_variants_differ_in_layout_not_in_the_chart(built):
    out, _, _ = built
    from verstka.pipeline.revise import slide_fingerprints

    for name, (story, res, audits) in out.items():
        prints = {v.strategy: tuple(slide_fingerprints(v.out_dir / "deck.pptx")) for v in res.variants}
        assert len(set(prints.values())) == 3, name  # three different decks of one story


def test_the_slides_carry_their_data_for_why_this(built):
    out, _, _ = built
    for story, res, _ in out.values():
        for v in res.variants:
            for s in v.outline.slides:
                if s.data is None:
                    continue
                assert s.data.options and s.data.task is not None and s.data.headline_facts and s.data.profile_line
                assert s.footnote and s.footnote.startswith("Источник:")


def test_the_audit_finds_nothing_wrong_with_the_data(built):
    out, _, _ = built
    for name, (_, _, audits) in out.items():
        for strategy, rep in audits.items():
            bad = [(i.slide, i.check_id, i.message) for i in rep.issues if i.check_id in DATA_CHECKS and i.severity in ("error", "warn")]
            assert bad == [], (name, strategy, bad)


def test_the_second_data_set_builds_on_the_unseen_template(tmp_path):
    story = build_data_story(Brief(text=SCIENCE_BRIEF), _tables(SCIENCE))
    res = generate_variants(UNSEEN, outline=story.outline, out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", strategies=["structured"],
                            use_llm=False, use_vlm=False, audit=False, autofix=False, exports=[], render_images=False, pictures=False)
    v = res.variants[0]
    assert (v.out_dir / "deck.pptx").is_file()
    assert len([s for s in v.outline.slides if s.data is not None]) >= 5
