"""«Изучаю данные» на всё время работы с данными (скринкаст, дубль 2): строки подготовки брендированной копии не читаются
экраном сборки как вёрстка («brand: rendered slides» → «Раскладываю по макетам» до разбора данных), а аналитик данных
говорит с первого шага — цели, файлы, графики."""

from __future__ import annotations

import re
from pathlib import Path

from verstka.data.readers import read_file
from verstka.data.story import build_data_story
from verstka.schemas.outline import Brief

ROOT = Path(__file__).resolve().parents[2]
# what the build screen reads as a phase of the pipeline (web/src/lib/agent.ts phaseOfMessage)
PIPELINE_LINE = re.compile(r"^[a-z_]+: ")


def test_the_branded_copys_lines_are_no_pipeline_lines():
    from verstka.api.app import _brand_line

    for stage in ("rendered slides", "loaded cached manifest", "assembled 28 patterns", "copying the package", "done"):
        line = _brand_line(stage)
        assert line.startswith("Брендбук: ") and not PIPELINE_LINE.match(line) and re.search(r"[а-яё]", line[10:]), line
    assert _brand_line("rendered slides") == "Брендбук: рисую миниатюры слайдов"
    assert _brand_line("Применяю брендбук к шаблону") == "Брендбук: применяю брендбук к шаблону"


def test_the_data_analyst_speaks_from_the_first_step():
    tables = [t for p in sorted((ROOT / "examples" / "data-sales-2026").iterdir()) if p.suffix in (".csv", ".xlsx", ".json", ".txt") for t in read_file(p)]
    seen: list[tuple[str, str]] = []

    def progress(message, share=None, event=None):
        if event is not None:
            seen.append((event["step"], event["message"]))

    build_data_story(Brief(text="Какой регион приносит больше всего? Что с NPS?"), tables, progress=progress)
    data = [m for step, m in seen if step == "data"]
    first_file = next(k for k, m in enumerate(data) if m.startswith("«"))
    assert data[:4] == ["Изучаю данные: 7 таблиц", "Понимаю цели из текста", "Читаю 7 файлов", "Выбираю графики"]
    assert first_file > 3
