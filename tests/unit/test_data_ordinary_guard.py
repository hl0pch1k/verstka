"""Обычные колоды (без файлов с данными) свёрстаны так же, как до правил слайдов данных (ревью Task 10, Important 2):
на VK WorkSpace и VK Education одна и та же раскладка — вид, режим, образец шаблона или композиция каждого слайда во
всех трёх вариантах — что и при прогоне ревьюера на коде до 09946b7 (`tests/fixtures/data_story/ordinary_guard.json`).
Правила «декор не под диаграммой» и «объект во весь пустой ряд» действуют только на слайдах с `OutlineSlide.data`.

Разбор шаблонов берётся из рабочей папки владельца, если он там свежий; иначе тест пропускается (разбор шаблонов VK
занимает минуты)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from verstka.pipeline.generate import generate_variants
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
GUARD = json.loads((FIX / "data_story" / "ordinary_guard.json").read_text(encoding="utf-8"))["decks"]
OUTLINES = {"charts": FIX / "data_story" / "ordinary_charts_outline.json", "demo": FIX / "outline_demo.json"}


def _cached(tid: str, root: Path) -> bool:
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


@pytest.mark.parametrize("key", sorted(GUARD))
def test_an_ordinary_deck_is_laid_out_as_before(key, tmp_path):
    tid = GUARD[key]["template_id"]
    if not _cached(tid, tmp_path):
        pytest.skip(f"the analysis of {tid} is not in the owner's workspace")
    d = json.loads(OUTLINES[key.split("/")[1]].read_text(encoding="utf-8"))
    d.pop("_source", None)
    res = generate_variants(tmp_path / "templates" / tid / "source.pptx", outline=DeckOutline.model_validate(d), out_dir=tmp_path / "out",
                            workspace_root=tmp_path, use_llm=False, use_vlm=False, render_images=False, audit=True, autofix=True,
                            exports=[], pictures=False, eyes=False)
    for v in res.variants:
        got = []
        for s in v.render.slides:
            osl = next((o for o in v.outline.slides if o.id == s.outline_id), None)
            got.append([osl.kind.value if osl else None, s.mode, s.pattern_id, s.composition])
        assert got == GUARD[key]["variants"][v.strategy], (key, v.strategy)
        assert not any(osl.data is not None for osl in v.outline.slides)
