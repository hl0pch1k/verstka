"""Справочник (`RefView`): одно упорядочение строк по главной метрике, топ-10 и строка «Остальные 230 …»."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from verstka.data.units import _num
from verstka.data.views import TOP_N, RefView
from verstka.data.words import fmt_exact, fmt_num, join_and, lower_first, period_label, phrase, plural

if TYPE_CHECKING:
    from verstka.data.aggregate import Data

# ── справочник ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _ref_view(d: Data) -> RefView:
    """Справочник: одно упорядочение строк по главной метрике (любой числовой — по убыванию, пустые в конце), из него —
    и строки таблицы, и подписи, и значения столбцов. Доля и итог «Остальные … дают X» — только у суммируемой
    неотрицательной метрики (у рейтинга или прибыли с убытками доля смысла не имеет)."""
    m = d.main
    lab = d.label if d.label is not None else d.id_col
    order = list(d.rows_idx)
    if m is not None:
        order.sort(key=lambda i: (m.values[i] is None, -(m.values[i] or 0.0), i))
    summable = m is not None and m.additive and m.nonneg
    # колонки: подпись, измерения (до 2), метрика, доля
    cols: list[int] = []
    if lab is not None:
        cols.append(lab)
    budget = 5 - len(cols) - (2 if summable else 1 if m is not None else 0)
    for j in d.dims:
        if j != lab and budget > 0 and d.cols[j].distinct < d.n:
            cols.append(j)
            budget -= 1
    if m is not None:
        cols.append(m.j)
        # остальные числа строки не теряются («Оценка | Число учеников»): таблица держит каждую числовую колонку
        for x in d.measures:
            if x.j not in cols and len(cols) < 6:
                cols.append(x.j)
    else:
        for j, c in enumerate(d.cols):
            if j not in cols and len(cols) < 5 and c.role != "id":
                cols.append(j)
    cols_sorted = sorted(set(cols), key=lambda j: (j != lab, j))
    total = None
    if summable:
        total = float(sum(m.present))  # type: ignore[union-attr]
        for i in sorted(d.totals):
            tv = _num(d.cell(i, m.j))  # type: ignore[union-attr]
            if tv is not None and tv > 0:
                total = tv
                break
    names = [d.cols[j].name + (f", {d.cols[j].unit}" if d.cols[j].unit else "") for j in cols_sorted]
    if summable:
        names.append("Доля, %")

    def row(i: int) -> list[str]:
        r = [_fmt_cell(d, i, j) for j in cols_sorted]
        if summable:
            v = m.values[i]  # type: ignore[union-attr]
            r.append(fmt_num(v / total * 100, 1) if v is not None and total else "")
        return r

    all_rows = [row(i) for i in order]
    top_n = min(TOP_N, d.n)
    top_sum = float(sum(m.values[i] or 0 for i in order[:top_n])) if summable else None  # type: ignore[union-attr]
    rest = None
    if d.n > top_n:
        k = d.n - top_n
        ent = phrase(d.entity) if d.entity else None
        word = plural(k, ent.low.nom, ent.low.gen, ent.low.gen_pl) if ent is not None and ent.sure else \
            plural(k, "строка", "строки", "строк")
        rest = [""] * len(names)
        rest[0] = f"Остальные {k} {word}"
        if summable and total:
            rv = total - (top_sum or 0)
            rest[cols_sorted.index(m.j)] = fmt_num(rv)  # type: ignore[union-attr]
            rest[-1] = fmt_num(rv / total * 100, 1)
    dropped = [c.name for j, c in enumerate(d.cols) if j not in cols_sorted and c.role != "id"]
    labels = [d.text(i, lab) if lab is not None else str(i + 1) for i in order]
    values = [m.values[i] for i in order] if m is not None else []
    return RefView(
        label=d.cols[lab].name if lab is not None else None, columns=names, rows=all_rows[:top_n], rest=rest, measure=m,
        n=d.n, top_n=top_n, total=total, top_sum=top_sum, dropped=dropped, share_added=summable, all_rows=all_rows,
        full_columns=names, order=order, labels=labels, values=values,
        negatives=sum(1 for v in values if v is not None and v < 0),
    )


def _fmt_cell(d: Data, i: int, j: int) -> str:
    v = d.cell(i, j)
    c = d.cols[j]
    if v is None:
        return "—"
    if c.type == "date" and isinstance(v, str):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
        if m:
            return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    if c.type == "period" and isinstance(v, str):
        return period_label(v, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return fmt_exact(float(v))  # как в файле: 212,4, а не 212
    return d.text(i, j)


def describe_dropped(names: list[str]) -> str:
    return join_and([lower_first(n) for n in names])

