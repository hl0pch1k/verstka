"""Ключевые показатели (`KpiView`): значение, единица и изменение каждой строки («1,24 млрд ₽», «+23%», «+6 п.»)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Optional

from verstka.data.parse import parse_quantity, split_unit
from verstka.data.timeaxis import _cell_time, _iso, cell_period
from verstka.data.units import kpi_change
from verstka.data.views import KpiItem, KpiView
from verstka.data.words import fmt_value, is_counter, metric_phrase, period_text

if TYPE_CHECKING:
    from verstka.data.aggregate import Data

# ── ключевые показатели ───────────────────────────────────────────────────────────────────────────────────────────────
def _norm_text(v: Any) -> str:
    return " ".join(str(v).replace(" ", " ").split())


def _value_text(v: Any, unit: Optional[str]) -> Optional[tuple[float, str, Optional[str]]]:
    """Ячейка → (число, текст «1,24 млрд ₽», единица)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return float(v), fmt_value(float(v), unit), unit
    q = parse_quantity(v)
    if q is None:
        return None
    num, u = q
    u = u or unit
    text = fmt_value(num, u)
    return num, text, u


def _kpi_view(d: Data) -> Optional[KpiView]:
    if d.n == 0 or not d.measures:
        return None
    # одна строка: показатели — колонки
    if d.n == 1:
        i = d.rows_idx[0]
        items = []
        for m in d.measures:
            vt = _value_text(d.cell(i, m.j), m.unit_text)
            if vt is not None:
                # счётчик-заголовок («Заказов») на карточке — «Число заказов»
                lab = metric_phrase(m.name, m.type).nom if is_counter(m.name) and metric_phrase(m.name, m.type) else m.name
                items.append(KpiItem(label=lab, value=vt[0], value_text=vt[1], unit=vt[2],
                                     prov_value={"op": "cell", "row": i, "col": m.j, "shown": True}))
        return KpiView(items=items, mixed_units=len({it.unit for it in items}) > 1) if items else None
    lab_j = d.label
    if lab_j is None:
        # длинный формат: «Показатель × Период → Значение» (широкую таблицу чтение разворачивает так)
        return _kpi_long(d)
    if d.n > 6:
        return None
    changes = [m for m in d.measures if m.change]
    values = [m for m in d.measures if not m.change]
    if not values:
        return None
    # колонки-периоды («III кв. 2026», «III кв. 2025»): текущая — поздняя
    timed = [(m, _cell_time(m.name)) for m in values]
    cur, prev = values[0], None
    if all(t is not None for _, t in timed) and len(timed) >= 2:
        timed.sort(key=lambda mt: (mt[1][0], mt[1][1]))  # type: ignore[index]
        cur, prev = timed[-1][0], timed[-2][0]
    elif len(values) >= 2:
        prev = None
    items: list[KpiItem] = []
    units = set()
    for i in d.rows_idx:
        label = d.text(i, lab_j)
        # единица строки («чел.», «%», «млн ₽»): из чтения, иначе из подписи («Выручка, млн ₽»), иначе колонки
        lab_unit = split_unit(label)[1] if label and not d.row_unit(i) else None
        ru = d.row_unit(i) or lab_unit or cur.unit_text
        vt = _value_text(d.cell(i, cur.j), ru)
        if not label or vt is None:
            continue
        units.add(vt[2] or "")
        it = KpiItem(label=(split_unit(label)[0] or label) if lab_unit else label, value=vt[0], value_text=vt[1],
                     unit=vt[2], prov_value={"op": "cell", "row": i, "col": cur.j, "shown": True})
        if prev is not None:
            pv = _value_text(d.cell(i, prev.j), d.row_unit(i) or lab_unit or prev.unit_text)
            if pv is not None:
                it.prev_text = pv[1]
        if changes:
            cq = d.cell(i, changes[0].j)
            q = parse_quantity(cq) if isinstance(cq, str) else (None if cq is None else (float(cq), changes[0].unit))
            if q is not None:
                it.change, it.change_unit = q[0], (q[1] or changes[0].unit)
                it.prov_change = {"op": "cell", "row": i, "col": changes[0].j, "shown": True}
        elif prev is not None:
            pv = _value_text(d.cell(i, prev.j), d.row_unit(i) or lab_unit or prev.unit_text)
            if pv is not None and (pv[2] or "") == (vt[2] or ""):
                ch = kpi_change(label, vt[0], pv[0], vt[2])
                if ch is not None:
                    it.change, it.change_unit = ch
                    it.prov_change = {"op": "cellchange", "row": i, "prev": prev.j, "cur": cur.j,
                                      "kind": "pct" if ch[1] == "%" else "abs", "shown": True}
        items.append(it)
    if not items:
        return None
    return KpiView(items=items, period=cur.name if prev is not None else None,
                   prev_period=prev.name if prev is not None else None, mixed_units=len(units) > 1)


def _kpi_long(d: Data) -> Optional[KpiView]:
    if d.time_col is None or not d.dims:
        return None
    lab_j = d.dims[0]
    m = next((x for x in d.measures if not x.change), None)
    if m is None:
        return None
    ch = next((x for x in d.measures if x.change), None)
    rows_by: dict[str, list[tuple[tuple[str, int], int]]] = {}
    for i in d.rows_idx:
        lab = d.text(i, lab_j)
        t = cell_period(d.cell(i, d.time_col), d.profile.time_axis)
        if lab and t is not None:
            rows_by.setdefault(lab, []).append((t, i))
    if not rows_by or len(rows_by) > 6 or any(len(v) > 4 for v in rows_by.values()):
        return None
    items = []
    units = set()
    periods = sorted({t for v in rows_by.values() for t, _ in v})
    for lab, rs in rows_by.items():
        rs.sort()
        i_cur = rs[-1][1]
        lab_unit = split_unit(lab)[1] if not d.row_unit(i_cur) else None
        vt = _value_text(d.cell(i_cur, m.j), d.row_unit(i_cur) or lab_unit or m.unit_text)
        if vt is None:
            continue
        units.add(vt[2] or "")
        it = KpiItem(label=(split_unit(lab)[0] or lab) if lab_unit else lab, value=vt[0], value_text=vt[1], unit=vt[2],
                     prov_value={"op": "cell", "row": i_cur, "col": m.j, "shown": True})
        if len(rs) >= 2 and rs[-2][0] != rs[-1][0]:
            pv = _value_text(d.cell(rs[-2][1], m.j), d.row_unit(rs[-2][1]) or lab_unit or m.unit_text)
            if pv is not None:
                it.prev_text = pv[1]
                if (pv[2] or "") == (vt[2] or ""):
                    ch2 = kpi_change(lab, vt[0], pv[0], vt[2])
                    if ch2 is not None:
                        it.change, it.change_unit = ch2
                        it.prov_change = {"op": "cellchange", "row": i_cur, "prev_row": rs[-2][1], "prev": m.j,
                                          "cur": m.j, "kind": "pct" if ch2[1] == "%" else "abs",
                                          "shown": True}
        if ch is not None:
            for _, i in reversed(rs):
                cq = d.cell(i, ch.j)
                q = parse_quantity(cq) if isinstance(cq, str) else (None if cq is None else (float(cq), ch.unit))
                if q is not None:
                    it.change, it.change_unit = q[0], (q[1] or ch.unit)
                    it.prov_change = {"op": "cell", "row": i, "col": ch.j, "shown": True}
                    break
        items.append(it)
    if not items:
        return None
    per = [period_text(_iso(g, o)) for g, o in periods[-2:]] if periods else []
    return KpiView(items=items, period=per[-1] if per else None, prev_period=per[0] if len(per) == 2 else None,
                   mixed_units=len(units) > 1)

