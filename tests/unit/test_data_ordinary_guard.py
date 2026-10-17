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
