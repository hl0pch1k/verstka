"""Slides made from data files (описание решения §7): what the data layer planned (`OutlineSlide.data`, the chart,
the table, the key figures) against what the deck shows.

The figures are checked against the dataset, not against the brief: a data slide's headline may only name the facts
the analysis counted from the file (`headline_ok`), the chart on the slide draws the values the data layer prepared from
the file, the slide names its source, the axes are named, the chart is not overloaded, a table is never the file
dumped whole, a file not fit for a chart never becomes one, and a table split over slides keeps its parts together.
Slides without `data` are not this module's business."""

from __future__ import annotations

import math
import re
from typing import Optional

from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.deck_ir import IRChart, IRElement, IRSlide
from verstka.schemas.outline import ChartSpec, OutlineSlide

HEADLINE_NO_CONCLUSION = CheckSpec(
    id="headline_no_conclusion",
    title="Заголовок слайда с данными называет тему, а не вывод",
    severity="warn",
    category="content",
    description="У слайда с графиком или таблицей из файла заголовок говорит, что видно в данных («Выручка выросла на 23% "
                "к сентябрю»), а не только тему («Выручка по месяцам») и не перечень чисел («Платное — 53%, бюджет — 35%»).",
)
HEADLINE_FIGURE_NOT_IN_DATA = CheckSpec(
    id="headline_figure_not_in_data",
    title="Число в заголовке не следует из данных",
    severity="error",
    category="content",
    description="Каждое число в заголовке слайда с данными — таком, каким его показывает файл презентации, — должно быть "
                "среди фактов, посчитанных по файлу с данными (изменение, доля, медиана, лидер…). Цифры внутри названий из "
                "данных («Филиал 1», «III кв. 2026») числами не считаются.",
)
TEXT_FIGURE_NOT_IN_DATA = CheckSpec(
    id="data_text_figure_not_in_data",
    title="Число в тексте слайда с данными не из файла",
    severity="error",
    category="content",
    description="На слайде с данными каждое число в подзаголовке, пунктах, карточках, выводе и подписях — это факт, "
                "посчитанный по файлу, значение диаграммы или таблицы этого слайда, слова слоя данных (подпись, подписи "
                "карточек), цифра внутри названия из данных («1 курс») или год, который называют сами данные. Заголовок "
                "проверяет своя проверка, строку «Источник» — своя.",
)
CHART_VALUES_MISMATCH = CheckSpec(
    id="chart_values_mismatch",
    title="Значения на слайде не совпадают с данными файла",
    severity="error",
    category="content",
    description="Диаграмма, таблица и карточки слайда показывают те же значения, что слой данных подготовил из файла при "
                "сборке (они хранятся в данных слайда и не меняются правками плана): те же категории и числа, пропуски — "
                "на своих местах, лишних строк нет.",
)
CHART_NO_UNITS = CheckSpec(
    id="chart_no_units",
    title="У диаграммы нет подписей осей и единиц",
    severity="warn",
    category="content",
    description="У графика, столбцов, полос и гистограммы подписаны обе оси: категорий («Месяц») и значений с единицей "
                "(«Выручка, млн ₽») — единица на самой оси, а не только в заголовке слайда; у рассеяния — обе оси. У "
                "круговой и кольцевой осей нет — хватает подписей долей.",
)
CHART_AXIS_TITLE_WRONG = CheckSpec(
    id="chart_axis_title_wrong",
    title="Ось значений подписана не тем, что на ней отложено",
    severity="error",
    category="content",
    description="Ось значений называет величину («Принято, чел.», «Выручка, млн ₽»), а не то, чем различаются категории или "
                "ряды: колонку-измерение файла («Регион», «Месяц») или вид группы («Форма обучения», «Тип клиента») — это "
                "подпись легенды или оси категорий.",
)
CHART_NO_SOURCE = CheckSpec(
    id="chart_no_source",
    title="Не указан источник данных",
    severity="warn",
    category="content",
    description="На слайде с данными из файла есть строка «Источник: <имя файла>» — в сноске или под диаграммой.",
)
CHART_OVERLOADED = CheckSpec(
    id="chart_overloaded",
    title="Диаграмма перегружена",
    severity="warn",
    category="content",
    description="Круговая и кольцевая — не больше 6 долей, столбцы и полосы — не больше 12 категорий, линия — не больше 60 "
                "точек: больше не прочитать с экрана.",
)
TABLE_RAW_DUMP = CheckSpec(
    id="table_raw_dump",
    title="Таблица из файла длиннее 10 строк",
    severity="warn",
    category="content",
    description="Таблица на слайде с данными длиннее 10 строк — и сырая выгрузка файла, и уже сгруппированная: такую "
                "не прочитать с экрана, нужны топ-N и «Остальные» или разбиение по слайдам.",
)
CHART_FROM_UNTYPABLE = CheckSpec(
    id="chart_from_untypable",
    title="График из данных, которые не годятся для графика",
    severity="error",
    category="content",
    description="Файл без чисел для графика (одни тексты, одна строка) показывается таблицей или не показывается вовсе — "
                "диаграммы из него быть не должно.",
)
DATA_SPLIT_INCONSISTENT = CheckSpec(
    id="data_split_inconsistent",
    title="Части таблицы на нескольких слайдах разошлись",
    severity="warn",
    category="content",
    description="Таблица, разбитая на 2–3 слайда, идёт подряд, все её части на месте, у них одни колонки и один заголовок.",
)

_CONT_RE = re.compile(r"\s*\((?:продолжение|continued)\)\s*$", re.I)
_SPACE_RE = re.compile(r"[\s   ⁠​]+")
_CATEGORY_TYPES = ("line", "area", "column", "bar", "histogram", "stacked_column", "stacked_bar", "grouped_column", "grouped_bar")
_SLICES_MAX, _BARS_MAX, _POINTS_MAX, _ROWS_MAX = 6, 12, 60, 10


def numbers_in(text: str, labels=()) -> list[float]:
    # (the data layer is imported when a deck has data slides: a deck without them never loads it)
    from verstka.data.headline import numbers_in as f

    return f(text, labels)


def headline_ok(text: str, facts, labels=()) -> bool:
    from verstka.data.headline import headline_ok as f

    return f(text, facts, labels)


def file_title(file: Optional[str], sheet: Optional[str] = None) -> str:
    from verstka.data.words import file_title as f

    return f(file, sheet)


def _norm(text: Optional[str]) -> str:
    return _SPACE_RE.sub(" ", str(text or "")).replace("ё", "е").replace("Ё", "Е").strip()


def _data_slides(ctx: AuditContext) -> list[tuple[IRSlide, OutlineSlide]]:
    if ctx.outline is None:
        return []
    by_id = {s.id: s for s in ctx.outline.slides}
    out = []
    for s in ctx.ir.slides:
        osl = by_id.get(s.outline_id or "")
        if osl is not None and osl.data is not None:
            out.append((s, osl))
    return out


def _elements(s: IRSlide) -> list[IRElement]:
    return list(s.elements)


def _charts(s: IRSlide) -> list[IRElement]:
    return [e for e in _elements(s) if e.chart is not None]


def _tables(s: IRSlide) -> list[IRElement]:
    return [e for e in _elements(s) if e.table is not None]


def _slide_text(s: IRSlide) -> str:
    return _norm(" ".join(e.text for e in _elements(s) if e.has_text and e.table is None))


def _bboxes(els: list[IRElement]) -> dict:
    return {"bboxes": [e.bbox_frac for e in els], "element_ids": [e.id for e in els]}


# ── the headline ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _headline(osl: OutlineSlide) -> str:
    return _CONT_RE.sub("", osl.headline or "").strip()


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zа-яё0-9]+", _norm(text).lower()) if len(w) > 1}


def _title_element(s: IRSlide, osl: OutlineSlide) -> Optional[IRElement]:
    """The slide's heading element: the title placeholder, else the text near the top that says most of the planned
    headline (the person may have edited it in the file); None when none reads as it."""
    want = _words(_headline(osl))
    best, score = None, 0.0
    for e in s.elements:
        if e.type != "text" or not e.has_text or e.table is not None:
            continue
        if (e.ph_type or "") in ("title", "ctrTitle"):
            return e
        if e.bbox_frac.y > 0.45:
            continue
        got = _words(" ".join(p.text for p in e.paragraphs))
        if not got or not want:
            continue
        j = len(got & want) / len(got | want)
        if j > score:
            best, score = e, j
    return best if best is not None and score >= 0.4 else None


def _shown_headline(s: IRSlide, osl: OutlineSlide) -> str:
    """The slide's heading as the deck shows it; the plan's headline when no text of the slide reads as it."""
    e = _title_element(s, osl)
    if e is None:
        return _headline(osl)
    return _CONT_RE.sub("", " ".join(_norm(p.text) for p in e.paragraphs if p.text.strip())).strip()


@check(HEADLINE_NO_CONCLUSION)
def headline_no_conclusion(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        head = _norm(_shown_headline(s, osl)).lower().rstrip(".")
        d = osl.data
        topics = {_norm(x).lower() for x in (d.plain_headline, file_title(d.file), d.file) if x}
        if not head or head in topics:
            out.append(ctx.new_issue(
                HEADLINE_NO_CONCLUSION, s.index,
                f"Заголовок «{_shown_headline(s, osl) or '—'}» называет тему, а не вывод из данных «{d.file}»",
                suggestion="Скажите в заголовке, что видно в данных, с числом из них: «Выручка выросла на 23% к сентябрю».",
            ))
            continue
        from verstka.data.story import is_description

        if not osl.content.numbers and is_description(_shown_headline(s, osl)):  # (a key figures' slide lists them)
            # «Платное — 53% приёма, бюджет — 35%»: values against names, no claim — a description, not a conclusion
            out.append(ctx.new_issue(
                HEADLINE_NO_CONCLUSION, s.index,
                f"Заголовок «{_shown_headline(s, osl)}» перечисляет числа, а не говорит, что из них следует",
                suggestion="Скажите вывод: «Больше половины приёма — платное: 53%».",
            ))
    return out


@check(HEADLINE_FIGURE_NOT_IN_DATA)
def headline_figure_not_in_data(ctx: AuditContext) -> list[Issue]:
    from verstka.data.story import bad_numbers

    out = []
    for s, osl in _data_slides(ctx):
        head = _shown_headline(s, osl)
        bad = bad_numbers(head, osl)  # (the story checks its own headlines by the same rule)
        if not bad:
            continue
        shown = ", ".join(f"«{_num(n)}»" for n in dict.fromkeys(bad))
        out.append(ctx.new_issue(
            HEADLINE_FIGURE_NOT_IN_DATA, s.index,
            f"В заголовке {shown} — такого числа нет среди фактов, посчитанных по файлу «{osl.data.file}»",
            suggestion="Оставьте в заголовке только числа из данных или верните заголовок-вывод, который предложил анализ.",
        ))
    return out


def _num(n: float) -> str:
    if float(n).is_integer():
        return str(int(n))
    return f"{n:.2f}".rstrip("0").rstrip(".").replace(".", ",")


# ── the values ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _same(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b)) or round(a, 2) == round(b, 2)


def _same_labels(want: list[str], have: list[str]) -> bool:
    """The chart's category labels are the data's: a label the renderer left out to thin a long axis (every other
    month) or shortened («янв 2025» under «янв», «янв ’25») still stands for its category."""
    if len(want) != len(have):
        return False

    def norm(x: str) -> str:
        # «’25» / «'25» — the year said short: the same year as «2025» of the data
        return re.sub(r"[’'‘`]\s?(\d{2})\b", r"20\1", _norm(x)).lower()

    pairs = [(norm(w), norm(h)) for w, h in zip(want, have)]
    return all(not h or h == w or h in w or w in h for w, h in pairs)


def _series_found(name: str, values: list[Optional[float]], cats: list[str], charts: list[IRChart]) -> Optional[str]:
    """None when one of the slide's charts draws this series (its values, gaps in their places; in the categories'
    order or reversed, as horizontal bars write it); else what differs, in words."""
    want_cats = [_norm(c) for c in cats]
    best: Optional[str] = None
    for c in charts:
        have_cats = [_norm(x) for x in c.categories]
        for sr in c.series:
            got = list(sr.values)
            if len(got) != len(values):
                best = best or f"на слайде {len(got)} значений вместо {len(values)}"
                continue
            for cats_order, vals in ((have_cats, got), (list(reversed(have_cats)), list(reversed(got)))):
                if want_cats and cats_order and not _same_labels(want_cats, cats_order):
                    continue
                if all(_same(a, b) for a, b in zip(values, vals)):
                    return None
            k = next((i for i, (a, b) in enumerate(zip(values, got)) if not _same(a, b)), None)
            if k is not None:
                lab = cats[k] if k < len(cats) else str(k + 1)
                best = f"«{lab}»: в данных {_val(values[k])}, на слайде {_val(got[k])}"
            else:
                best = best or "категории идут в другом порядке"
    return best or "на слайде нет такого ряда"


def _val(v: Optional[float]) -> str:
    return "пропуск" if v is None else _num(round(v, 2))


def _prepared(osl: OutlineSlide):
    """What the data layer prepared from the file for the slide (`SlideData.prepared`); a deck built before it was kept
    — its plan's content."""
    from verstka.schemas.data import PreparedValues

    p = osl.data.prepared
    if p is not None:
        return p
    c = osl.content
    if c.chart is not None:
        return PreparedValues(categories=[str(x) for x in c.chart.categories], series=[(x.name, list(x.values)) for x in c.chart.series],
                              points=[(x.name, list(zip(x.x, x.y))) for x in c.chart.xy])
    if c.table is not None:
        return PreparedValues(columns=list(c.table.columns), rows=[list(r) for r in c.table.rows])
    return PreparedValues(numbers=[n.value for n in c.numbers])


def _chart_problem(prep, s: IRSlide) -> Optional[str]:
    charts = [e.chart for e in _charts(s)]
    if not charts and _tables(s) and prep.categories and not prep.points:
        return _series_table_problem(prep, s)  # the chart's data as a table (its rows did not fit a chart, qa3)
    if not charts:
        return "диаграммы на слайде нет"
    if prep.points:
        for name, pairs in prep.points:
            pts = sorted((round(x, 6), round(y, 6)) for x, y in pairs if x is not None and y is not None)
            found = False
            for c in charts:
                for sr in c.series:
                    got = sorted((round(x, 6), round(y, 6)) for x, y in zip(sr.x_values, sr.values) if x is not None and y is not None)
                    if got == pts:
                        found = True
            if not found:
                return f"точки «{name}» на слайде другие"
        return None
    cats = list(prep.categories)
    for name, values in prep.series:
        vals = [None if v is None else float(v) for v in values][: len(cats)]
        vals += [None] * (len(cats) - len(vals))
        if not any(v is not None for v in vals):
            continue
        why = _series_found(name, vals, cats, charts)
        if why is not None:
            return (f"ряд «{name}»: " if name and len(prep.series) > 1 else "") + why
    return None


_ROWS_RE = re.compile(r"(\d[\d\s\u00a0\u202f]*)\s+строк")


def _bins_problem(osl: OutlineSlide, prep) -> Optional[str]:
    """A histogram counts every value of its column: its bins add up to the file's values (an open bin «больше 180»
    holds the outliers too) — unless the slide says some are not drawn."""
    spec = osl.content.chart
    if spec is None or spec.type != "histogram" or not prep.series:
        return None
    m = _ROWS_RE.search(osl.data.profile_line or "")
    if not m:
        return None
    rows = int(re.sub(r"\D", "", m.group(1)))
    metrics = [c for c in osl.data.columns if str(getattr(c.role, "value", c.role)) == "metric"]
    col = next((c for c in metrics if spec.x_title and _norm(spec.x_title).lower().startswith(_norm(c.name).lower())), metrics[0] if len(metrics) == 1 else None)
    n = rows - (col.missing if col is not None else 0)
    shown = sum(v for v in prep.series[0][1] if v is not None)
    if n <= 0 or abs(shown - n) < 0.5:
        return None
    said = " ".join(x for x in (osl.takeaway or "", *prep.texts) if x).lower()
    if re.search(r"не\s+показан|не\s+вошл|не\s+отображ", said):
        return None
    return f"в столбцах гистограммы {_num(shown)} значений из {_num(n)}: {_num(n - shown)} не попали ни в один столбец"


_OTHERS_RE = re.compile(r"^(?:прочие|остальные)\b", re.I)


def _series_table_problem(prep, s: IRSlide) -> Optional[str]:
    """The prepared series shown as a table: a row a category (its name first), its values in the row. A table of at
    most ten rows (the composer's chart-as-table, qa4 NEW-H1) may show the largest categories and sum the rest in a
    row «Прочие (n)» / «Остальные …»: that row holds, series by series, the sums of the categories it stands for."""
    rows = [[_norm(c) for c in r] for e in _tables(s) for r in e.table.rows]
    missing = []
    for k, cat in enumerate(prep.categories):
        row = next((r for r in rows if r and _norm(r[0]).lower() == _norm(cat).lower()), None)
        if row is None:
            missing.append(k)
            continue
        want = [v[k] for _, v in prep.series if k < len(v) and v[k] is not None]
        have = [n for c in row[1:] for n in _cell_numbers(c)]
        if any(not any(_same(w, h) for h in have) for w in want):
            return f"в строке «{cat}» другие числа"
    if missing:
        other = next((r for r in rows if r and _OTHERS_RE.match(_norm(r[0]))), None)
        if other is None:
            return f"нет строки «{prep.categories[missing[0]]}»"
        want = [sum(v[k] for k in missing if k < len(v) and v[k] is not None) for _, v in prep.series]
        have = [n for c in other[1:] for n in _cell_numbers(c)]
        if any(not any(_same(w, h) for h in have) for w in want):
            return f"в строке «{other[0]}» не сумма остальных {len(missing)} строк"
    return None


def _cell_numbers(text: str) -> list[float]:
    return numbers_in(_norm(text).replace("⁠", ""))


def _table_problem(prep, s: IRSlide) -> Optional[str]:
    tables = _tables(s)
    if not tables:
        return "таблицы на слайде нет"
    have = [[_norm(c) for c in r] for e in tables for r in e.table.rows]
    if len([r for r in have if any(r)]) - len(tables) > len(prep.rows):
        return f"на слайде строк больше, чем подготовлено из файла ({len(prep.rows)})"
    for row in prep.rows:
        want = [_norm(c) for c in row]
        if not want:
            continue
        match = next((r for r in have if r and r[0] == want[0]), None)
        if match is None:
            return f"нет строки «{row[0]}»"
        if [n for c in want for n in _cell_numbers(c)] != [n for c in match for n in _cell_numbers(c)]:
            return f"в строке «{row[0]}» другие числа"
    return None


def _numbers_problem(prep, s: IRSlide) -> Optional[str]:
    text = _slide_text(s)
    have = _cell_numbers(text)
    for value in prep.numbers:
        want = _cell_numbers(value)
        if want and not all(any(abs(a - b) < 1e-9 for b in have) for a in want):
            return f"нет карточки «{_norm(value)}»"
    return None


_SKIP_PH = {"sldNum", "dt", "ftr"}


@check(TEXT_FIGURE_NOT_IN_DATA)
def data_text_figure_not_in_data(ctx: AuditContext) -> list[Issue]:
    from verstka.audit.checks.common import is_chrome_like
    from verstka.data.story import bad_numbers, slide_values

    out = []
    for s, osl in _data_slides(ctx):
        title = _title_element(s, osl)
        allowed = slide_values(osl)
        if osl.data.prepared is None:  # a deck built before the prepared values: its plan's own words
            allowed += [v for t in (osl.takeaway or "", *(n.label for n in osl.content.numbers)) for v in numbers_in(t)]
        found: list[tuple[IRElement, list[float]]] = []
        for e in s.elements:
            if e.type != "text" or not e.has_text or e is title or (e.ph_type or "") in _SKIP_PH:
                continue
            try:
                if is_chrome_like(e, ctx.ir, ctx.manifest):
                    continue  # the template's own footer, page number, date
            except Exception:  # noqa: BLE001 - a manifest without its chrome: every text counts
                pass
            for para in e.paragraphs:
                t = _norm(para.text)
                if not t or "источник" in t.lower():
                    continue
                bad = bad_numbers(t, osl, values=allowed)
                if bad:
                    found.append((e, bad))
        if found:
            shown = ", ".join(dict.fromkeys(f"«{_num(n)}»" for _, bad in found for n in bad))
            out.append(ctx.new_issue(
                TEXT_FIGURE_NOT_IN_DATA, s.index,
                f"В тексте слайда {shown} — таких чисел нет ни среди фактов файла «{osl.data.file}», ни на его диаграмме",
                suggestion="Уберите строку с этим числом или пересоберите слайд по файлу.", **_bboxes([e for e, _ in found]),
            ))
    return out


@check(CHART_VALUES_MISMATCH)
def chart_values_mismatch(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        prep = _prepared(osl)
        why = None
        els: list[IRElement] = []
        if prep.series or prep.points:
            why, els = _chart_problem(prep, s) or _bins_problem(osl, prep), _charts(s)
        elif prep.rows:
            why, els = _table_problem(prep, s), _tables(s)
        elif prep.numbers:
            why = _numbers_problem(prep, s)
        if why:
            out.append(ctx.new_issue(
                CHART_VALUES_MISMATCH, s.index, f"Данные «{osl.data.file}» на слайде показаны не так, как в файле: {why}",
                suggestion="Пересоберите слайд: значения берутся из файла заново.", **_bboxes(els),
            ))
    return out


# ── axes, source, load ───────────────────────────────────────────────────────────────────────────────────────────────
@check(CHART_NO_UNITS)
def chart_no_units(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        spec = osl.content.chart
        if spec is None:
            continue
        for e in _charts(s):
            c = e.chart
            if spec.type == "scatter" or c.type == "scatter":
                if not (c.x_title and c.y_title):
                    out.append(ctx.new_issue(CHART_NO_UNITS, s.index, "У диаграммы рассеяния не подписаны оси", **_bboxes([e])))
                continue
            if spec.type not in _CATEGORY_TYPES or c.type in ("pie", "doughnut"):
                continue
            missing = [w for w, ok in (("оси категорий", bool(c.x_title)), ("оси значений", bool(c.y_title))) if not ok]
            if missing:
                out.append(ctx.new_issue(
                    CHART_NO_UNITS, s.index, f"У диаграммы «{osl.data.file}» нет подписи {' и '.join(missing)}",
                    suggestion="Подпишите ось значений с единицей («Выручка, млн ₽») и ось категорий.", **_bboxes([e]),
                ))
            elif spec.unit and not _unit_in(spec.unit, c.y_title) and not _unit_in(spec.unit, c.title):
                # the unit on the axis itself (or the chart's own unit caption above it) — a headline that says «423 млн ₽»
                # does not name the axis
                out.append(ctx.new_issue(
                    CHART_NO_UNITS, s.index, f"На оси значений диаграммы «{osl.data.file}» нет единицы: «{_norm(c.y_title)}» без «{spec.unit}»",
                    suggestion=f"Подпишите ось значений с единицей: «{_norm(c.y_title)}, {spec.unit}».", **_bboxes([e]),
                ))
    return out


def _unit_in(unit: str, title: Optional[str]) -> bool:
    """The unit is named in the title («Выручка, млн ₽» — «млн ₽»; «Принято, человек» — «чел.»)."""
    t, u = _norm(title).lower(), _norm(unit).lower()
    if not t or not u:
        return False
    if u in t:
        return True
    stem = re.sub(r"[.\s]+$", "", u)
    return len(stem) >= 2 and re.search(r"(?<![а-яёa-z])" + re.escape(stem), t) is not None


# a kind of a category, not a quantity: what the legend or the category axis names («Форма обучения», «Тип клиента»)
_KIND_WORD_RE = re.compile(r"^(?:форм[аы]|тип|вид|категори|групп|сегмент|класс|статус|способ|направлени|канал|регион|город|"
                           r"филиал|отрасл|профил|институт|кафедр|подразделени|отдел|продукт|тариф)\w*\b", re.I)


@check(CHART_AXIS_TITLE_WRONG)
def chart_axis_title_wrong(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        spec = osl.content.chart
        if spec is None or spec.type in ("pie", "doughnut", "scatter"):
            continue
        not_measures = {_norm(c.name).lower() for c in osl.data.columns if str(getattr(c.role, "value", c.role)) != "metric"}
        for e in _charts(s):
            c = e.chart
            if c.type in ("pie", "doughnut", "scatter") or not c.y_title:
                continue
            name = _norm(c.y_title.split(",")[0]).lower()
            if name in not_measures or _KIND_WORD_RE.match(name):
                out.append(ctx.new_issue(
                    CHART_AXIS_TITLE_WRONG, s.index,
                    f"Ось значений диаграммы «{osl.data.file}» подписана «{_norm(c.y_title)}» — так называются категории или "
                    f"ряды, а на оси — величина",
                    suggestion="Подпишите ось тем, что отложено: «Принято, чел.», «Выручка, млн ₽».", **_bboxes([e]),
                ))
    return out


@check(CHART_NO_SOURCE)
def chart_no_source(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        name = _norm(osl.data.file).lower()
        lines = [_norm(e.text).lower() for e in _elements(s) if e.has_text and e.table is None]
        if any("источник" in t and name in t for t in lines):
            continue
        out.append(ctx.new_issue(
            CHART_NO_SOURCE, s.index, f"На слайде не указан источник данных: «{osl.data.file}»",
            suggestion=f"Добавьте сноску «Источник: {osl.data.file}».",
        ))
    return out


@check(CHART_OVERLOADED)
def chart_overloaded(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        for e in _charts(s):
            c = e.chart
            n = len(c.categories)
            why = None
            if c.type in ("pie", "doughnut") and n > _SLICES_MAX:
                why = f"{n} долей — больше {_SLICES_MAX} на круговой не прочитать"
            elif c.type in ("column", "bar") and n > _BARS_MAX:
                why = f"{n} категорий — больше {_BARS_MAX} столбцов не прочитать"
            elif c.type in ("line", "area") and n > _POINTS_MAX:
                why = f"{n} точек — больше {_POINTS_MAX} на линии не различить"
            if why:
                out.append(ctx.new_issue(
                    CHART_OVERLOADED, s.index, f"Диаграмма «{osl.data.file}» перегружена: {why}",
                    suggestion="Сгруппируйте данные: топ-N и «Остальные», месяцы вместо дней.", **_bboxes([e]),
                ))
    return out


@check(TABLE_RAW_DUMP)
def table_raw_dump(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        t = osl.content.table
        if t is None or len(t.rows) <= _ROWS_MAX:
            continue
        how = "даже после агрегации" if osl.data.aggregation else "без агрегации"
        out.append(ctx.new_issue(
            TABLE_RAW_DUMP, s.index, f"Таблица «{osl.data.file}» — {len(t.rows)} строк {how}",
            suggestion="Покажите топ-10 и строку «Остальные» или разбейте таблицу на слайды по 10 строк.", **_bboxes(_tables(s)),
        ))
    return out


@check(CHART_FROM_UNTYPABLE)
def chart_from_untypable(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        if osl.data.nature != "untypable":
            continue
        if osl.content.chart is not None or _charts(s):
            out.append(ctx.new_issue(
                CHART_FROM_UNTYPABLE, s.index, f"Из «{osl.data.file}» построен график, хотя в файле нет данных для графика",
                suggestion="Покажите такие данные таблицей.", **_bboxes(_charts(s)),
            ))
    return out


@check(DATA_SPLIT_INCONSISTENT)
def data_split_inconsistent(ctx: AuditContext) -> list[Issue]:
    groups: dict[str, list[tuple[int, IRSlide, OutlineSlide]]] = {}
    for pos, (s, osl) in enumerate(_data_slides(ctx)):
        groups.setdefault(osl.data.dataset_id, []).append((pos, s, osl))
    out = []
    for parts in groups.values():
        totals = {osl.data.part[1] for _, _, osl in parts}
        if max(totals) <= 1 and len(parts) <= 1:
            continue
        first = parts[0][2]
        why = None
        numbers = [osl.data.part[0] for _, _, osl in parts]
        if len(totals) > 1:
            why = "у частей разное число слайдов"
        elif sorted(numbers) != list(range(1, max(totals) + 1)):
            why = f"частей {len(parts)} из {max(totals)}" if len(parts) != max(totals) else "части повторяются"
        elif numbers != sorted(numbers) or [p[1].index for p in parts] != list(range(parts[0][1].index, parts[0][1].index + len(parts))):
            why = "части идут не подряд"
        elif any((osl.content.table is None) != (first.content.table is None) or (osl.content.table is not None and first.content.table is not None and osl.content.table.columns != first.content.table.columns) for _, _, osl in parts):
            why = "у частей разные колонки"
        elif len({_norm(_headline(osl)).lower() for _, _, osl in parts}) > 1:
            why = "у частей разные заголовки"
        if why:
            s = parts[0][1]
            out.append(ctx.new_issue(
                DATA_SPLIT_INCONSISTENT, s.index, f"Таблица «{first.data.file}» на нескольких слайдах: {why}",
                suggestion="Пересоберите слайд: части таблицы строятся заново по файлу.",
            ))
    return out


# ── qa3 (N-U1): a chart in the heading's band, a hero figure the heading does not say, nameless categories ──────────
CHART_IN_HEADING_BAND = CheckSpec(
    id="chart_in_heading_band",
    title="Диаграмма заходит в полосу заголовка",
    severity="error",
    category="layout",
    description="Рамка диаграммы слайда с данными начинается выше первой строки заголовка или заходит на его рамку: "
                "диаграмма лезет к краю слайда над заголовком.",
)
HERO_NOT_IN_HEADING = CheckSpec(
    id="hero_not_in_heading",
    title="Крупная цифра рядом с диаграммой — не из заголовка",
    severity="warn",
    category="content",
    description="Крупная цифра, вынесенная рядом с диаграммой (визуальный вариант), — это главная цифра заголовка "
                "слайда; граница столбца («больше 180»), число точек или «остальные 230 клиентов» под «Топ-10 дают 38%» — "
                "не она.",
)
CHART_LABELS_MISSING = CheckSpec(
    id="chart_labels_missing",
    title="У категорий диаграммы нет подписей",
    severity="error",
    category="content",
    description="Названия категорий (направления, регионы, каналы) подписаны все: пропускать через одну можно только "
                "подписи оси времени (месяцы, кварталы, годы), где пропущенное читается по соседям.",
)
_HERO_NAMES = ("Figure", "Conclusion figure")


@check(CHART_IN_HEADING_BAND)
def chart_in_heading_band(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        title = _title_element(s, osl)
        if title is None:
            continue
        from verstka.audit.checks.density import _ink

        tb = _ink(title)  # (the heading's lines, not its box: a tall title box over the chart is the template's)
        if tb.w <= 0 or tb.h <= 0:
            continue
        for e in _charts(s):
            b = e.bbox
            # (a chart beside the heading may start a little higher — the template's own side-by-side; far above its
            # first line, at the slide's edge, it climbs)
            if b.y < tb.y - int(0.06 * ctx.ir.slide_h) or b.intersection(tb) > 0.05 * min(tb.area, b.area):
                out.append(ctx.new_issue(
                    CHART_IN_HEADING_BAND, s.index, f"Диаграмма «{osl.data.file}» поднимается к краю слайда над заголовком или заходит на него",
                    suggestion="Диаграмма начинается под заголовком.", **_bboxes([e, title]),
                ))
                break
    return out


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


@check(HERO_NOT_IN_HEADING)
def hero_not_in_heading(ctx: AuditContext) -> list[Issue]:
    out = []
    for s, osl in _data_slides(ctx):
        if not _charts(s):
            continue
        # (the heading as shown and as planned: a template's label chip «СТРУКТУРА» may be the title placeholder)
        heads = {_digits(m) for m in re.findall(r"[+\-−–]?\d[\d\s  ]*(?:[.,]\d+)?", _shown_headline(s, osl) + " " + (osl.headline or "")) if _digits(m)}
        for e in s.elements:
            if e.type != "text" or not e.has_text or not (e.name or "").startswith(_HERO_NAMES):
                continue
            fig = " ".join(e.text.split())
            d = _digits(fig)
            if d and d not in heads:
                out.append(ctx.new_issue(
                    HERO_NOT_IN_HEADING, s.index, f"Крупная цифра «{fig}» рядом с диаграммой — не та, что в заголовке «{_shown_headline(s, osl)}»",
                    suggestion="Вынесите цифру из заголовка или уберите крупную цифру.", **_bboxes([e]),
                ))
    return out


@check(CHART_LABELS_MISSING)
def chart_labels_missing(ctx: AuditContext) -> list[Issue]:
    from verstka.rendering.charts import is_time_axis

    out = []
    for s, osl in _data_slides(ctx):
        prep = _prepared(osl)
        cats = [str(c) for c in prep.categories]
        if len(cats) < 2 or is_time_axis(cats):
            continue
        for e in _charts(s):
            c = e.chart
            if c.type in ("pie", "doughnut", "scatter") or len(c.categories) != len(cats):
                continue
            blank = sum(1 for x in c.categories if not str(x).strip())
            if blank:
                out.append(ctx.new_issue(
                    CHART_LABELS_MISSING, s.index, f"У {blank} из {len(cats)} категорий диаграммы «{osl.data.file}» нет подписи",
                    suggestion="Подпишите все категории: дайте диаграмме больше высоты, оставьте топ и «Прочие» или покажите таблицей.", **_bboxes([e]),
                ))
    return out


CHART_ROWS_DONT_FIT = CheckSpec(
    id="chart_rows_dont_fit",
    title="Строки диаграммы не помещаются",
    severity="error",
    category="content",
    description="У горизонтальных столбцов на каждую категорию нужна строка в 1,3 кегля подписи: в рамке ниже этого имена "
                "категорий наезжают друг на друга или пропадают. Такую диаграмму дают в рамке выше или таблицей.",
)


@check(CHART_ROWS_DONT_FIT)
def chart_rows_dont_fit(ctx: AuditContext) -> list[Issue]:
    from verstka.rendering.charts import min_frame_height

    out = []
    hpt = ctx.ir.slide_h / 12700.0
    fs = max(8.0, 0.02 * hpt)  # (the least size a chart sets its labels at: 2 % of the slide's height)
    for s, osl in _data_slides(ctx):
        for e in _charts(s):
            c = e.chart
            if c.type != "bar" or len(c.categories) < 2:
                continue
            need = min_frame_height("bar", len(c.categories), fs, legend_rows=1 if len(c.series) > 1 else 0)
            have = e.bbox.h / 12700.0
            if have < 0.9 * need:
                out.append(ctx.new_issue(
                    CHART_ROWS_DONT_FIT, s.index, f"Строки диаграммы «{osl.data.file}» не помещаются: {len(c.categories)} категорий в рамке {have:.0f} pt, нужно от {need:.0f}",
                    suggestion="Дайте диаграмме рамку выше или покажите данные таблицей.", **_bboxes([e]),
                ))
    return out
