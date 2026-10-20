"""Обычные колоды (без файлов с данными) свёрстаны так же, как до правил слайдов данных (ревью Task 10, Important 2):
на VK WorkSpace и VK Education одна и та же раскладка — вид, режим, образец шаблона или композиция каждого слайда во
всех трёх вариантах — что и при прогоне ревьюера на коде до 09946b7 (`tests/fixtures/data_story/ordinary_guard.json`).
Правила «декор не под диаграммой» и «объект во весь пустой ряд» действуют только на слайдах с `OutlineSlide.data`.

Шаблоны VK — из папки «Датасет» (VERSTKA_FIXTURES_DIR или рядом с репозиторием); их разбор делается заново во
временной рабочей папке теста, без модели (≈ 12 с на шаблон) — рабочая папка владельца не нужна."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from verstka.pipeline.generate import generate_variants
from verstka.schemas.outline import DeckOutline

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
GUARD = json.loads((FIX / "data_story" / "ordinary_guard.json").read_text(encoding="utf-8"))["decks"]
OUTLINES = {"charts": FIX / "data_story" / "ordinary_charts_outline.json", "demo": FIX / "outline_demo.json"}
NAMES = {"workspace": "workspace", "education": "education"}


def _template(name: str):
    env = os.environ.get("VERSTKA_FIXTURES_DIR")
    for d in ([Path(env)] if env else []) + [p / "Датасет" for p in ROOT.parents]:
        if d.is_dir():
            hit = next((p for p in d.glob("*.pptx") if name in p.name.lower()), None)
            if hit is not None:
                return hit
    return None


@pytest.fixture(scope="module")
def analysed(tmp_path_factory):
    from verstka.analysis.manifest import analyze_template

    root = tmp_path_factory.mktemp("ws")
    out = {}
    for key, name in NAMES.items():
        src = _template(name)
        if src is not None:
            out[key] = analyze_template(src, workspace_root=root, use_llm=False, use_vlm=False).template_id
    return root, out


@pytest.mark.parametrize("key", sorted(GUARD))
def test_an_ordinary_deck_is_laid_out_as_before(key, analysed, tmp_path):
    root, tids = analysed
    tname, oname = key.split("/")
    if tname not in tids:
        pytest.skip(f"the VK {tname} template is not available (VERSTKA_FIXTURES_DIR)")
    tid = tids[tname]
    assert tid == GUARD[key]["template_id"]
    d = json.loads(OUTLINES[oname].read_text(encoding="utf-8"))
    d.pop("_source", None)
    res = generate_variants(root / "templates" / tid / "source.pptx", outline=DeckOutline.model_validate(d), out_dir=tmp_path / "out",
                            workspace_root=root, use_llm=False, use_vlm=False, render_images=False, audit=True, autofix=True,
                            exports=[], pictures=False, eyes=False)
    for v in res.variants:
        got = []
        for s in v.render.slides:
            osl = next((o for o in v.outline.slides if o.id == s.outline_id), None)
            got.append([osl.kind.value if osl else None, s.mode, s.pattern_id, s.composition])
        assert got == GUARD[key]["variants"][v.strategy], (key, v.strategy)
        assert not any(osl.data is not None for osl in v.outline.slides)


def test_a_big_figure_stays_under_its_heading(analysed, tmp_path):
    """Live QA (VK Education, «Студенты оценивают программу на 4,8 из 5»): the large figure's box ran up over the
    heading — the audit's overlap error. Its box starts under the heading now."""
    root, tids = analysed
    if "education" not in tids:
        pytest.skip("the VK Education template is not available (VERSTKA_FIXTURES_DIR)")
    o = DeckOutline.model_validate({"title": "Программа", "slides": [
        {"id": "t", "kind": "title", "headline": "Программа data-инженеров"},
        {"id": "b", "kind": "big_number", "headline": "Студенты оценивают программу на 4,8 из 5",
         "content": {"numbers": [{"value": "4,8 из 5", "label": "Оценка программы студентами"}]}},
    ]})
    res = generate_variants(root / "templates" / tids["education"] / "source.pptx", outline=o, out_dir=tmp_path / "out", workspace_root=root,
                            use_llm=False, use_vlm=False, render_images=False, audit=True, autofix=False, exports=[], pictures=False, eyes=False)
    for v in res.variants:
        assert not [i for i in v.audit.issues if i.slide == 2 and i.check_id == "overlap"], v.strategy


def test_every_card_of_an_icon_row_has_its_icon(analysed):
    """VK Education p26/p27: three icons in the sample, four scenarios on the slide — the fourth card took no icon. The
    card the row gained gets an icon of the sample's own set, not the one beside it."""
    from lxml import etree

    from verstka.analysis.xmlns import q
    from verstka.ingest.workspace import TemplateWorkspace
    from verstka.rendering.clone import render_clone
    from verstka.rendering.deck import DeckBuilder, element_bbox
    from verstka.schemas.common import PatternKind
    from verstka.schemas.layout import LayoutSlide
    from verstka.schemas.outline import OutlineSlide, SlideContent, SlideItem
    from verstka.schemas.template import TemplateManifest

    root, tids = analysed
    if "education" not in tids:
        pytest.skip("the VK Education template is not available (VERSTKA_FIXTURES_DIR)")
    ws = TemplateWorkspace.open(tids["education"], root)
    m = TemplateManifest.model_validate_json((root / "templates" / tids["education"] / "manifest.json").read_text(encoding="utf-8"))
    items = [SlideItem(title=t, text=x) for t, x in [("Напоминание из чата", "Одно касание превращает сообщение в задачу"), ("Умный срок", "Модель предлагает дату"),
                                                     ("Эскалация", "Просроченная задача уходит руководителю"), ("Дайджест", "Утренняя сводка по задачам")]]
    for pid in ("p26", "p27"):
        p = next(x for x in m.patterns if x.id == pid)
        o = OutlineSlide(id="s", kind=PatternKind.cards, headline="Четыре сценария", content=SlideContent(items=items))
        slide, _ = render_clone(DeckBuilder(root / "templates" / tids["education"] / "source.pptx"), LayoutSlide(outline_id="s", mode="clone", pattern_id=pid), o, p, m, ws, DeckOutline(title="T", slides=[o]))
        H = slide.part.package.presentation_part.presentation.slide_height
        # (a tile is a picture or a plain shape — p26 draws its first one as a shape)
        shapes = [e for e in slide.shapes._spTree if etree.QName(e).localname in ("pic", "sp") and not "".join(e.itertext()).strip()]
        boxes = [element_bbox(e) for e in shapes]
        tiles = {round(b[0] / 1e5) for b in boxes if b and 0.3 * H < b[1] < 0.55 * H and 0.1 * H < b[3] < 0.2 * H}
        assert len(tiles) == 4, (pid, sorted(tiles))
