"""Расхождения брендбука с шаблоном — для слоя «Брендбук» (описание решения §5).

Каждое расхождение — по-человечески: что расходится («Шрифт заголовков», «Второй акцент», «Логотип»), значение в
шаблоне и в брендбуке и что в итоге будет в презентации при выбранном приоритете. Считается теми же правилами, что и
брендированная копия (`verstka.brand.apply`), поэтому слой показывает ровно то, что попадёт в слайды.

Что считается расхождением:
- шрифты заголовков и текста — разные семейства (у бренда без шрифта на машине итог — «VK Sans Display, замена — Play»);
- акценты палитры шаблона (цвета темы по порядку, у стандартной темы — акценты из разбора) — любой другой цвет бренда,
  даже очень близкий (#FF3885 и #FF3985 — разные фирменные цвета);
- цвет текста и фон — только заметная разница (ΔE > 15) или разная светлота: чёрный и «ночной» #0B1220, белый и
  #FAFCFF — один и тот же цвет для человека, бренд просто уточняет его;
- логотип — когда в шаблоне есть свой логотип, а в брендбуке — логотипы.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from verstka.brand.apply import (
    _ORDINALS,
    ThemeInfo,
    _base,
    _de,
    _lstar,
    _Pkg,
    _pkg_theme,
    find_template_logos,
    font_result,
    plan_colors,
    plan_fonts,
    resolve_brand_dir,
)
from verstka.ingest.workspace import TemplateWorkspace
from verstka.schemas.brand import BrandConflict, BrandPriority, BrandSpec
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

# заметная разница нейтральных цветов (текст, фон)
NEUTRAL_DE = 15.0


def _source_of(manifest: TemplateManifest, source: Optional[Path | str], workspace_root: Optional[Path | str]) -> Optional[Path]:
    if source:
        return Path(source)
    try:
        ws = TemplateWorkspace.open(manifest.template_id, workspace_root)
    except FileNotFoundError:
        return None
    return ws.source if ws.source.exists() else None


def _template_title(manifest: TemplateManifest, workspace_root: Optional[Path | str]) -> Optional[str]:
    try:
        ws = TemplateWorkspace.open(manifest.template_id, workspace_root)
    except FileNotFoundError:
        return None
    try:
        t = (ws.dir / "title.txt").read_text(encoding="utf-8").strip()
    except OSError:
        t = ""
    return t or None


def _hx(h: str) -> str:
    return "#" + h.upper()


def brand_conflicts(
    manifest: TemplateManifest,
    brand: BrandSpec,
    *,
    priority: BrandPriority = "brand",
    source: Optional[Path | str] = None,
    workspace_root: Optional[Path | str] = None,
    brand_dir: Optional[Path | str] = None,
) -> list[BrandConflict]:
    """Расхождения брендбука `brand` с шаблоном `manifest`. Тема и логотипы читаются из файла шаблона (`source` или копия
    шаблона в рабочей папке); без файла — по разбору."""
    path = _source_of(manifest, source, workspace_root)
    pkg = None
    theme = ThemeInfo()
    if path is not None:
        try:
            pkg = _Pkg(path)
            theme = _pkg_theme(pkg)
        except Exception as e:  # noqa: BLE001 - без файла расхождения считаются по разбору
            log.warning("template package unreadable for brand conflicts: %s", e)
            pkg = None
    cp = plan_colors(manifest, brand, "brand", theme)
    fp = plan_fonts(manifest, brand, "brand")
    out: list[BrandConflict] = []

    def add(what: str, tpl: str, brd: str, result_brand: str, kind: str, lacking: bool = False) -> None:
        # при приоритете шаблона бренд только дополняет: расхождение остаётся как в шаблоне
        result = result_brand if priority == "brand" or lacking else f"{tpl}, как в шаблоне"
        out.append(BrandConflict(what=what, template=tpl, brand=brd, result=result, kind=kind))  # type: ignore[arg-type]

    # --- шрифты
    same_tpl = fp.heading_from and fp.body_from and _base(fp.heading_from) == _base(fp.body_from)
    same_brand = fp.heading and fp.body and _base(fp.heading.family) == _base(fp.body.family)
    rows = []
    if fp.heading and fp.heading_from and _base(fp.heading_from) != _base(fp.heading.family):
        rows.append(("Шрифт заголовков", fp.heading_from, fp.heading, fp.heading_to, fp.heading_fallback))
    if fp.body and fp.body_from and _base(fp.body_from) != _base(fp.body.family):
        rows.append(("Шрифт текста", fp.body_from, fp.body, fp.body_to, fp.body_fallback))
    if len(rows) == 2 and same_tpl and same_brand:
        rows = [("Шрифт", rows[0][1], rows[0][2], rows[0][3], rows[0][4])]
    for what, tpl, bf, written, fb in rows:
        add(what, tpl, bf.family, font_result(bf, written or bf.family, fb), "font", lacking=fp.lacking(tpl))

    # --- акценты палитры
    for i, a in enumerate(cp.main[: len(_ORDINALS)]):
        res = cp.anchors.get(a) or cp.table.get(a)
        b = cp.brand_of.get(a) or res
        if b and b != a:
            # светлый акцент шаблона получает оттенок цвета бренда той же светлоты
            result = _hx(res) if res == b else f"{_hx(res)} — оттенок {_hx(b)}"
            add(_ORDINALS[i], _hx(a), _hx(b), result, "color", lacking=theme.stock and a in theme.slots.values())

    # --- текст и фон: только заметная разница
    for what, pair in (("Цвет текста", cp.text_pair), ("Фон", cp.background_pair)):
        if not pair:
            continue
        t, b = pair
        bc = brand.color("text" if what == "Цвет текста" else "background")
        if bc is None:
            continue
        bh = bc.hex.lstrip("#").upper()
        if t == b and bh != t:
            # разная светлота: брендбук не может перевернуть шаблон — остаётся шаблон
            out.append(BrandConflict(what=what, template=_hx(t), brand=_hx(bh), result=f"{_hx(t)}, как в шаблоне: у бренда другая светлота", kind="color"))
        elif t != b and (_de(t, b) > NEUTRAL_DE or (_lstar(t) > 50) != (_lstar(b) > 50)):
            add(what, _hx(t), _hx(b), _hx(b), "color")

    # --- логотип
    if brand.logos:
        has_logo = False
        if pkg is not None:
            try:
                has_logo = bool([lk for lk in find_template_logos(pkg, manifest, theme.slots) if not lk.duplicate])
            except Exception as e:  # noqa: BLE001
                log.warning("template logos not found: %s", e)
        else:
            has_logo = any(a.kind == "logo" for a in manifest.assets)
        if has_logo:
            title = _template_title(manifest, workspace_root)
            tpl = f"логотип {title}" if title else "логотип шаблона"
            brd = f"логотип {brand.name}" if brand.name else "логотип брендбука"
            bdir = resolve_brand_dir(brand, brand_dir, workspace_root)
            found = any((Path(bdir) / lg.file if bdir and not Path(lg.file).is_absolute() else Path(lg.file)).exists() for lg in brand.logos)
            add("Логотип", tpl, brd, brd if found else f"{tpl}: файлов логотипа бренда нет", "logo")
    return out
