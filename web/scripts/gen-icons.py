#!/usr/bin/env python3
"""Иконки «Слоёв» для веба: читает docs/design/sloi/tools/icons_lib.py (ICONS: имя → (подложка, линии)) и пишет
web/src/ui/kit/icons.ts — только линии. Подложка (tint) не переносится: владелец её отклонил.

Запуск из корня репозитория или из web/: python3 web/scripts/gen-icons.py
"""
import importlib.util
import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
LIB = WEB.parent / "docs/design/sloi/tools/icons_lib.py"
OUT = WEB / "src/ui/kit/icons.ts"


def load_icons() -> dict:
    spec = importlib.util.spec_from_file_location("icons_lib", LIB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ICONS


def render(icons: dict) -> str:
    rows = [f"  {json.dumps(name)}: {json.dumps(' '.join(line.split()), ensure_ascii=False)}," for name, (_tint, line) in icons.items()]
    return "\n".join([
        "// сгенерировано scripts/gen-icons.py из docs/design/sloi/tools/icons_lib.py — не править руками",
        "export const ICONS = {",
        *rows,
        "} as const;",
        "export type IconName = keyof typeof ICONS;",
        "",
    ])


def main() -> None:
    icons = load_icons()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(icons), encoding="utf-8")
    print(f"{OUT.relative_to(WEB.parent)}: {len(icons)} иконок")


if __name__ == "__main__":
    main()
