"""Regenerate the check tables in AUDIT.md from the audit registry (run after adding a check)."""

from __future__ import annotations

import re
from pathlib import Path

from verstka.audit.model_checks import DECK_COHERENCE, SLIDE_CONTENT
from verstka.audit.registry import all_checks

SEV = {"error": "ошибка", "warn": "предупреждение", "info": "сведение"}
CAT = {"layout": "Вёрстка", "template": "Шаблон", "density": "Плотность", "integrity": "Целостность", "content": "Контент"}
AUTOFIX = {
    "out_of_bounds": "сдвиг внутрь слайда",
    "text_clipped": "перевыбор макета",
    "overlap": "перевыбор макета",
    "text_overflow": "уменьшение кегля по шкале / перевыбор макета",
    "margin_violation": "сдвиг в безопасную область",
    "font_not_in_template": "замена на шрифт шаблона",
    "color_not_in_palette": "ближайший цвет палитры",
    "contrast_low": "цвет текста шаблона, достигающий нужного контраста",
    "too_many_bullets": "сокращение списка",
    "bullet_too_long": "сокращение текста",
    "placeholder_text": "удаление заглушки",
    "empty_slide": "перевыбор макета",
    "content_missing": "перевыбор макета",
    "table_cell_wrap": "перевыбор макета",
}


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "AUDIT.md"
    text = path.read_text(encoding="utf-8")
    det = ["| id | Категория | Уровень | Что проверяет | Автофикс |", "|---|---|---|---|---|"]
    for spec, _ in all_checks():
        det.append(f"| `{spec.id}` | {CAT[spec.category]} | {SEV[spec.severity]} | {spec.description} | {AUTOFIX.get(spec.id, '—')} |")
    model = ["| id | Уровень | Что проверяет |", "|---|---|---|"]
    for spec in (SLIDE_CONTENT, DECK_COHERENCE):
        model.append(f"| `{spec.id}` | {SEV[spec.severity]} | {spec.description} |")
    text = re.sub(r"(## Детерминированные проверки\n\n)(\|.*?\n)+", lambda m: m.group(1) + "\n".join(det) + "\n", text, flags=re.S)
    text = re.sub(r"(## Модельные проверки\n\n)(\|.*?\n)+", lambda m: m.group(1) + "\n".join(model) + "\n", text, flags=re.S)
    path.write_text(text, encoding="utf-8")
    print(f"AUDIT.md updated: {len(det) - 2} deterministic checks")


if __name__ == "__main__":
    main()
