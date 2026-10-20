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
from verstka.brand.logos import CORNER_RU, DEFAULT_LOGO_PLACE, has_template_logo, logo_outcome, logo_path
from verstka.brand.palette import ACCENT_ORDINALS, NEUTRAL_DE, delta_e, kept_reason_text
from verstka.ingest.workspace import TemplateWorkspace
from verstka.schemas.brand import BrandConflict, BrandPriority, BrandSpec
from verstka.schemas.template import TemplateManifest


def _workspace(manifest: TemplateManifest, workspace_root: Optional[Path | str]) -> Optional[TemplateWorkspace]:
    """Рабочая папка шаблона — только названная явно (API и копия передают свою): без неё расхождения считаются по
    файлу и разбору, а не по чужой рабочей папке по умолчанию (её «title.txt» менял итог от машины к машине)."""
    if workspace_root is None:
        return None
    try:
        return TemplateWorkspace.open(manifest.template_id, workspace_root)
    except FileNotFoundError:
        return None


_INSETS: dict = {}


def _inset_of(path: Path) -> Optional[float]:
    """Поле шаблона (px на 1920) — один раз на файл: расхождения зовутся на каждый запрос брендбука."""
    from verstka.brand.palette import file_key

    key = file_key(path)
    if key is not None and key in _INSETS:
        return _INSETS[key]
    try:
        from verstka.brand.apply import template_inset_px
        from verstka.brand.package import Package

        inset = template_inset_px(Package(path))
    except Exception:  # noqa: BLE001 - a template that does not read: no line
        inset = None
    if key is not None:
        if len(_INSETS) > 64:
            _INSETS.clear()
        _INSETS[key] = inset
    return inset


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
    # при приоритете шаблона итог каждой строки — то, что сделает копия с этим приоритетом: бренд только занимает
    # места, которые автор шаблона не заполнял (стандартный шрифт, слоты стандартной темы), остальное — как в шаблоне
    tplan = brand_plan(path, manifest, brand, "template") if priority == "template" else None
    out: list[BrandConflict] = []

    def add(what: str, tpl: str, brd: str, result_brand: str, kind: str, result_template: Optional[str] = None) -> None:
        result = result_brand if priority == "brand" else (result_template or f"{tpl}, как в шаблоне")
        out.append(BrandConflict(what=what, template=tpl, brand=brd, result=result, kind=kind))  # type: ignore[arg-type]

    def tpl_color(h: str) -> Optional[str]:
        """Что станет с цветом шаблона при приоритете шаблона: цвет бренда (слот стандартной темы) или None — как был."""
        if tplan is None:
            return None
        got = tplan.colors.map(h)
        return _hx(got) if got != h else None

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
        role = "body" if what == "Шрифт текста" else "heading"
        t_written = tplan.fonts.target(tpl, role) if tplan is not None else None
        add(what, tpl, bf.family, font_result(bf, written or bf.family, fb), "font", font_result(bf, t_written, fb) if t_written else None)

    # --- акценты главной палитры
    for i, a in enumerate(cp.main[: len(ACCENT_ORDINALS)]):
        res = cp.table.get(a, cp.anchors.get(a, a))
        b = cp.brand_of.get(a) or cp.kept_target.get(a) or res
        if a in cp.keep:
            why = kept_reason_text(cp, a) or "цвет шаблона"
            out.append(BrandConflict(what=ACCENT_ORDINALS[i], template=_hx(a), brand=_hx(b) if b != a else "нет пары", result=f"{_hx(a)}, как в шаблоне: {why}", kind="color"))
        elif b != a:
            # тон бренда при светлоте шаблона — светлое осталось светлым, текст на нём — читаемым
            result = _hx(res) if res == b else f"{_hx(res)} — оттенок {_hx(b)}"
            add(ACCENT_ORDINALS[i], _hx(a), _hx(b), result, "color", tpl_color(a))

    if cp.mono and cp.main:
        add("Акценты", ", ".join(_hx(a) for a in cp.main[:3]), f"только основной {_hx(cp.mono)}",
            f"Акценты шаблона заменены цветами бренда: тона {_hx(cp.mono)}", "color")

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
            add(what, _hx(t), _hx(bh), f"{_hx(b)}, светлота шаблона: {why}", "color", tpl_color(t))
        elif t != b:
            add(what, _hx(t), _hx(bh), _hx(b), "color", tpl_color(t))

    # --- поля: брендбук шире шаблона — текст отодвигается от краёв (`apply._apply_margins`)
    if brand.margins_px and 0 < brand.margins_px <= 200 and path is not None and path.exists():
        inset = _inset_of(path)
        if inset is not None and inset < brand.margins_px - 4:
            add("Поля", f"{inset:g} px", f"{brand.margins_px:g} px", f"{brand.margins_px:g} px: текст отодвинут от краёв", "margins")

    # --- логотип: чей и где
    bdir = resolve_brand_dir(brand, brand_dir, workspace_root)
    found = any((p := logo_path(lg, bdir)) is not None and p.exists() for lg in brand.logos)
    title = _template_title(ws)
    tpl = f"логотип {title}" if title else "логотип шаблона"
    brd = f"логотип {brand.name}" if brand.name else "логотип брендбука"
    outcome = logo_outcome(path, manifest, brand, bdir) if path and found and priority == "brand" else None
    own = outcome.template_logo if outcome is not None else (has_template_logo(path, manifest) if path else any(a.kind == "logo" for a in manifest.assets))
    if own and brand.logos:
        result = brd if found else f"{tpl}: файлов логотипа бренда нет"
        if outcome is not None and outcome.note:
            result = f"{brd}: {outcome.note}"
        add("Логотип", tpl, brd, result, "logo")
    elif brand.logos and found and outcome is not None and not own:
        # у шаблона логотипа нет: логотип бренда добавлен (место — из брендбука или правый верхний угол)
        where = CORNER_RU.get(outcome.add.corner or brand.logo_place or DEFAULT_LOGO_PLACE, "")
        placed = outcome.add.box is not None or outcome.covered > 0
        how = (f"{brd} {where}" + (" (брендбук место не называет)" if outcome.default_place else "")) if placed else "без логотипа: места на слайдах нет"
        add("Логотип", "у шаблона нет", brd, how, "logo")
    if not brand.logos:
        # в брендбуке нет файлов логотипа — видно и в слое «Брендбук», а не только в отчёте копии; итог при любом
        # приоритете один: логотип шаблона, а где его нет — без логотипа
        kept = f"{tpl} оставлен" if own else "без логотипа"
        add("Логотип", tpl if own else "у шаблона нет", "в брендбуке нет файлов логотипа", kept, "logo", kept)
    return out
