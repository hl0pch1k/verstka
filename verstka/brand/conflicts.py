"""Расхождения брендбука с шаблоном — для слоя «Брендбук» (описание решения §5).

Каждое расхождение — по-человечески: что расходится («Шрифт заголовков», «Второй акцент», «Логотип»), значение в
шаблоне и в брендбуке и что в итоге будет в презентации при выбранном приоритете. Считается тем же планом, что и
брендированная копия (`verstka.brand.apply.brand_plan`), поэтому слой показывает ровно то, что попадёт в слайды.

Что считается расхождением:
- шрифты заголовков и текста — разные семейства (у бренда без шрифта на машине итог — «VK Sans Display, замена — Play»);
- акценты главной палитры шаблона (цвета темы по порядку, у стандартной темы — акценты разбора) — любой другой цвет
  бренда, даже очень близкий (#FF3885 и #FF3985 — разные фирменные цвета); акцент, оставшийся как в шаблоне, — тоже,
  с причиной;
- цвет текста и фон — только заметная разница (ΔE > 15): чёрный и «ночной» #0B1220, белый и #FAFCFF — один и тот же
  цвет для человека, бренд просто уточняет его; оставшийся текст или фон — с настоящей причиной;
- логотип — когда в шаблоне есть свой логотип-картинка, а в брендбуке — логотипы.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from verstka.brand.apply import brand_plan, font_base, font_result, resolve_brand_dir
from verstka.brand.logos import has_template_logo, logo_path
from verstka.brand.palette import ACCENT_ORDINALS, NEUTRAL_DE, delta_e, kept_reason_text
from verstka.ingest.workspace import TemplateWorkspace
from verstka.schemas.brand import BrandConflict, BrandPriority, BrandSpec
from verstka.schemas.template import TemplateManifest


def _workspace(manifest: TemplateManifest, workspace_root: Optional[Path | str]) -> Optional[TemplateWorkspace]:
    try:
        return TemplateWorkspace.open(manifest.template_id, workspace_root)
    except FileNotFoundError:
        return None


def _template_title(ws: Optional[TemplateWorkspace]) -> Optional[str]:
    if ws is None:
        return None
    try:
        t = (ws.dir / "title.txt").read_text(encoding="utf-8").strip()
    except OSError:
        t = ""
    return t or None


def _hx(h: str) -> str:
    return "#" + h.upper().lstrip("#")


def brand_conflicts(
    manifest: TemplateManifest,
    brand: BrandSpec,
    *,
    priority: BrandPriority = "brand",
    source: Optional[Path | str] = None,
    workspace_root: Optional[Path | str] = None,
    brand_dir: Optional[Path | str] = None,
) -> list[BrandConflict]:
    """Расхождения брендбука `brand` с шаблоном `manifest`. Тема, тексты и логотипы читаются из файла шаблона
    (`source` или копия шаблона в рабочей папке); без файла — по разбору."""
    ws = _workspace(manifest, workspace_root)
    path = Path(source) if source else (ws.source if ws is not None and ws.source.exists() else None)
    plan = brand_plan(path, manifest, brand, "brand")
    cp, fp = plan.colors, plan.fonts
    out: list[BrandConflict] = []

    def add(what: str, tpl: str, brd: str, result_brand: str, kind: str, lacking: bool = False) -> None:
        # при приоритете шаблона бренд только дополняет: расхождение остаётся как в шаблоне
        result = result_brand if priority == "brand" or lacking else f"{tpl}, как в шаблоне"
        out.append(BrandConflict(what=what, template=tpl, brand=brd, result=result, kind=kind))  # type: ignore[arg-type]

    # --- шрифты
    rows = []
    if fp.heading and fp.heading_from and font_base(fp.heading_from) != font_base(fp.heading.family):
        rows.append(("Шрифт заголовков", fp.heading_from, fp.heading, fp.heading_to, fp.heading_fallback))
    if fp.body and fp.body_from and font_base(fp.body_from) != font_base(fp.body.family):
        rows.append(("Шрифт текста", fp.body_from, fp.body, fp.body_to, fp.body_fallback))
    same_tpl = fp.heading_from and fp.body_from and font_base(fp.heading_from) == font_base(fp.body_from)
    same_brand = fp.heading and fp.body and font_base(fp.heading.family) == font_base(fp.body.family)
    if len(rows) == 2 and same_tpl and same_brand:
        rows = [("Шрифт", rows[0][1], rows[0][2], rows[0][3], rows[0][4])]
    for what, tpl, bf, written, fb in rows:
        add(what, tpl, bf.family, font_result(bf, written or bf.family, fb), "font", lacking=fp.lacking(tpl))

    # --- акценты главной палитры
    for i, a in enumerate(cp.main[: len(ACCENT_ORDINALS)]):
        res = cp.table.get(a, cp.anchors.get(a, a))
        b = cp.brand_of.get(a) or cp.kept_target.get(a) or res
        lacking = plan.theme.stock and a in plan.theme.slots.values()
        if a in cp.keep:
            why = kept_reason_text(cp, a) or "цвет шаблона"
            out.append(BrandConflict(what=ACCENT_ORDINALS[i], template=_hx(a), brand=_hx(b) if b != a else "нет пары", result=f"{_hx(a)}, как в шаблоне: {why}", kind="color"))
        elif b != a:
            # тон бренда при светлоте шаблона — светлое осталось светлым, текст на нём — читаемым
            result = _hx(res) if res == b else f"{_hx(res)} — оттенок {_hx(b)}"
            add(ACCENT_ORDINALS[i], _hx(a), _hx(b), result, "color", lacking=lacking)

    # --- текст и фон: только заметная разница
    for what, pair, role in (("Цвет текста", cp.text_pair, "text"), ("Фон", cp.background_pair, "background")):
        bc = brand.color(role)  # type: ignore[arg-type]
        if not pair or bc is None:
            continue
        t, b = pair
        bh = bc.hex.lstrip("#").upper()
        if delta_e(t, bh) <= NEUTRAL_DE:
            continue  # для человека один цвет: бренд его просто уточняет
        why = kept_reason_text(cp, t)
        if t in cp.keep:
            out.append(BrandConflict(what=what, template=_hx(t), brand=_hx(bh), result=f"{_hx(t)}, как в шаблоне: {why or 'цвет шаблона'}", kind="color"))
        elif b != bh and why:
            # точный цвет бренда нельзя (занят другим цветом шаблона) — своя светлота, оттенок бренда
            add(what, _hx(t), _hx(bh), f"{_hx(b)}, светлота шаблона: {why}", "color")
        elif t != b:
            add(what, _hx(t), _hx(bh), _hx(b), "color")

    # --- логотип
    if brand.logos and (has_template_logo(path, manifest) if path else any(a.kind == "logo" for a in manifest.assets)):
        title = _template_title(ws)
        tpl = f"логотип {title}" if title else "логотип шаблона"
        brd = f"логотип {brand.name}" if brand.name else "логотип брендбука"
        bdir = resolve_brand_dir(brand, brand_dir, workspace_root)
        found = any((p := logo_path(lg, bdir)) is not None and p.exists() for lg in brand.logos)
        add("Логотип", tpl, brd, brd if found else f"{tpl}: файлов логотипа бренда нет", "logo")
    return out
