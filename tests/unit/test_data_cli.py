"""CLI `verstka generate --data … --brand …`: колода-история из файлов (папка или файлы через запятую) на
брендированной копии шаблона, без модели."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from verstka.cli.main import _data_files, app

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
UNSEEN = ROOT / "tests" / "fixtures" / "data_story" / "lo_forestbird.pptx"
TOKENS = ROOT / "examples" / "brandbook-vk-cloud" / "tokens.json"


def test_data_values_are_files_folders_or_comma_lists():
    files = _data_files([str(SALES)])
    assert len(files) == 7 and all(f.name != "SCENARIO.md" for f in files)
    two = _data_files([f"{SALES / 'Регионы.xlsx'},{SALES / 'Каналы продаж.json'}", str(SALES / "Регионы.xlsx")])
    assert [f.name for f in two] == ["Регионы.xlsx", "Каналы продаж.json"]


def test_generate_builds_a_data_story_on_the_branded_template(tmp_path):
    brief = tmp_path / "brief.txt"
    brief.write_text("Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы.", encoding="utf-8")
    out, ws = tmp_path / "out", tmp_path / "ws"
    r = CliRunner().invoke(app, ["generate", "-t", str(UNSEEN), "-b", str(brief), "--data", str(SALES), "--brand", str(TOKENS),
                                 "--slides", "9", "--no-llm", "--no-vlm", "-s", "structured", "-w", str(ws), "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "брендированная копия шаблона" in r.output and "История из данных: 7 наборов, 9 слайдов" in r.output
    o = json.loads((out / "structured" / "outline.json").read_text(encoding="utf-8"))
    assert len([s for s in o["slides"] if s.get("data")]) == 7
    rm = json.loads((out / "structured" / "run_manifest.json").read_text(encoding="utf-8"))
    assert rm["planner"]["planned_by"] == "rules" and rm["planner"]["data"]["datasets"] == 7
    from verstka.brand.apply import branded_info

    assert (branded_info(rm["template"]["id"], ws) or {}).get("brand_name")
    assert (out / "data_story.json").is_file()


def _said(output: str) -> str:
    """The CLI's words without the error panel's frame, colours and line breaks: rich wraps the panel at the terminal's
    width (and colours it on GitHub Actions), so a phrase may come split over two lines of the frame."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(re.sub(r"[│╭╮╰╯─]", " ", plain).split())


def test_generate_needs_a_brief_an_outline_or_data(tmp_path):
    r = CliRunner().invoke(app, ["generate", "-t", str(UNSEEN), "--no-llm", "-o", str(tmp_path)])
    assert r.exit_code != 0
    r = CliRunner().invoke(app, ["generate", "-t", str(UNSEEN), "--data", str(tmp_path / "nope.csv"), "--no-llm", "-o", str(tmp_path), "-w", str(tmp_path / "ws")])
    assert r.exit_code != 0 and "не найден" in _said(r.output)
    # said before the template's analysis and the font pick: nothing was read for a run that cannot start
    assert "Шрифты:" not in r.output and not (tmp_path / "ws").exists()
