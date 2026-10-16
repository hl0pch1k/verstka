"""Пример брендбука VK Cloud и навык brandbook_reader после разбора замечаний ревью задачи 5: подписи осей и единицы на
диаграммах страницы 9, заполненная нижняя треть слайда «Ключевые показатели», строка про непечатный HEX в подсказке модели."""

from __future__ import annotations

from pathlib import Path

import yaml
from PIL import Image

from verstka.brand.pdf import _open, _page_texts
from verstka.brand.read import read_brandbook

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples" / "brandbook-vk-cloud"


def test_sample_page_nine_charts_follow_the_rule_the_page_states():
    page = _page_texts(_open(SAMPLE / "guideline.pdf"))[8]
    assert "Всегда подписывайте оси и единицы" in page
    assert "млн ₽" in page  # единица у оси значений линейного графика
    assert "Доля выручки, % от итога" in page and "40" in page  # шкала и заголовок оси столбцов
    assert page.count("Источник:") == 2  # источник данных — под каждой диаграммой


def test_sample_key_figures_slide_has_no_empty_lower_third():
    with Image.open(SAMPLE / "slides" / "03-pokazateli.png") as im:
        assert im.size == (1920, 1080)
        lower = im.convert("RGB").crop((0, 720, 1920, 980))
    inked = sum(1 for p in lower.getdata() if min(p) < 235)
    assert inked / (lower.width * lower.height) > 0.10  # полоса «Выручка по кварталам» занимает нижнюю треть
    # слайд по-прежнему читается как фирменный: цвета палитры на месте
    spec = read_brandbook(SAMPLE / "slides" / "03-pokazateli.png")
    assert {c.hex for c in spec.colors} >= {"#FFFFFF", "#0B1220", "#0077FF"}


def test_the_sample_still_reads_like_the_scenario():
    spec = read_brandbook(SAMPLE / "guideline.pdf")
    assert {c.hex: c.role for c in spec.colors} == {"#0077FF": "primary", "#2787F5": "secondary", "#0B1220": "text",
                                                    "#FFFFFF": "background", "#FF3985": "accent", "#00C2FF": "chart"}
    assert [(f.role, f.family, f.fallback, f.weight) for f in spec.fonts] == [("heading", "VK Sans Display", "Play", 700), ("body", "VK Sans Text", "Play", 400)]
    assert spec.pages == 12 and spec.warnings == []


def test_the_models_prompt_never_asks_to_guess_a_hex_that_is_not_printed():
    system = " ".join((ROOT / "skills" / "brandbook_reader" / "prompts" / "system.md").read_text(encoding="utf-8").split())
    assert "если HEX не напечатан — цвет не добавляйте" in system
    meta = yaml.safe_load((ROOT / "skills" / "brandbook_reader" / "skill.yaml").read_text(encoding="utf-8"))
    assert meta["version"] == "1.0.1" and meta["role"] == "vlm"
