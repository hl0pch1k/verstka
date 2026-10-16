"""Ось времени: номера периодов, частоты, ресэмплинг и полнота периодов; ряд по времени `TimeView` из таблицы."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Optional

from verstka.data.parse import period_iso, period_parts
from verstka.data.views import MAX_POINTS, MAX_SERIES, Measure, SeriesV, TimeView
from verstka.data.words import count_gen, period_label, period_text

if TYPE_CHECKING:
    from verstka.data.aggregate import Data

# ── время ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
_FREQ_ORDER = ["hour", "day", "week", "month", "quarter", "year"]


def _to_freq(gran: str, ordinal: int, freq: str) -> Optional[int]:
    """Номер периода `gran` → номер периода частоты `freq` (не мельче исходного)."""
    if gran == freq:
        return ordinal
    if gran == "hour":
        return _to_freq("day", ordinal // 24, freq) if freq != "day" else ordinal // 24
    if gran == "day":
        d = date.fromordinal(ordinal)
        if freq == "week":
            return (ordinal - 1) // 7
        if freq == "month":
            return d.year * 12 + d.month - 1
        if freq == "quarter":
            return d.year * 4 + (d.month - 1) // 3
        if freq == "year":
            return d.year
    if gran == "week":
        # неделя относится к периоду, где большая часть её дней, — по её четвергу (неделя — с понедельника)
        return _to_freq("day", ordinal * 7 + 4, freq) if freq != "week" else ordinal
    if gran == "month":
        if freq == "quarter":
            return (ordinal // 12) * 4 + (ordinal % 12) // 3
        if freq == "year":
            return ordinal // 12
    if gran == "quarter" and freq == "year":
        return ordinal // 4
    return None


def _period_days(target: str, k: int) -> list[int]:
    """Дни (порядковые номера) периода `target` с номером `k`."""
    if target == "day":
        return [k]
    if target == "week":
        return [k * 7 + 1 + d for d in range(7)]
    if target == "month":
        y, mth = divmod(k, 12)
        first = date(y, mth + 1, 1)
        nxt = date(y + (mth + 1) // 12, (mth + 1) % 12 + 1, 1)
        return list(range(first.toordinal(), nxt.toordinal()))
    if target == "quarter":
        y, q = divmod(k, 4)
        return [d for mm in range(3) for d in _period_days("month", y * 12 + q * 3 + mm)]
    if target == "year":
        return list(range(date(k, 1, 1).toordinal(), date(k + 1, 1, 1).toordinal()))
    return []


def _calendar_count(gran: str, target: str, k: int) -> int:
    """Сколько исходных точек `gran` в полном периоде `target`: 28–31 день месяца, 7 дней недели, 24 часа суток,
    понедельники недель месяца, 3 месяца квартала, 12 месяцев года, 4 квартала года. 0 — неизвестно."""
    if gran == "month":
        return {"quarter": 3, "year": 12}.get(target, 0)
    if gran == "quarter":
        return 4 if target == "year" else 0
    days = _period_days(target, k)
    if not days:
        return 0
    if gran == "day":
        return len(days)
    if gran == "hour":
        return 24 * len(days)
    if gran == "week":
        return sum(1 for d in days if date.fromordinal(d).weekday() == 0)
    return 0


MAX_WEEKS = 60  # недельный ряд до 60 точек остаётся неделями


def _cadence(gran: str, ordinals: list[int]) -> set[int]:
    """Обычный ритм дневного ряда — дни недели, которые есть хотя бы в половине недель: будни у рабочих дней, все семь
    у ежедневного ряда. Не дни — пусто."""
    if gran != "day" or not ordinals:
        return set()
    weeks = max(1.0, (max(ordinals) - min(ordinals) + 1) / 7)
    cnt: dict[int, int] = {}
    for o in set(ordinals):
        wd = date.fromordinal(o).weekday()
        cnt[wd] = cnt.get(wd, 0) + 1
    return {wd for wd, c in cnt.items() if c >= 0.5 * weeks} or set(range(7))


def _need(gran: str, target: str, k: int, cadence: set[int]) -> int:
    """Сколько точек в полном периоде по ритму ряда: рабочих дней месяца у ряда по будням, всех дней — у ежедневного."""
    if gran == "day" and cadence and len(cadence) < 7:
        return sum(1 for o in _period_days(target, k) if date.fromordinal(o).weekday() in cadence)
    return _calendar_count(gran, target, k)


def _of_words(gran: str, need: int, cadence: set[int]) -> str:
    """«31 дня», «23 рабочих дней», «24 часов» — после «из»."""
    if gran == "day" and cadence and len(cadence) < 7:
        return count_gen(need, "рабочего дня", "рабочих дней")
    forms = {"day": ("дня", "дней"), "hour": ("часа", "часов"), "week": ("недели", "недель"),
             "month": ("месяца", "месяцев"), "quarter": ("квартала", "кварталов")}.get(gran, ("точки", "точек"))
    return count_gen(need, *forms)


def resample_freq(freq: str, points: int, span: dict[str, int]) -> str:
    """Самая мелкая частота не мельче исходной, при которой точек ≤ 36."""
    if points <= MAX_POINTS:
        return freq
    start = _FREQ_ORDER.index(freq) if freq in _FREQ_ORDER else 1
    for f in _FREQ_ORDER[start + 1:]:
        if span.get(f, 10**9) <= MAX_POINTS:
            return f
    return "year"


def _cell_time(cell: Any) -> Optional[tuple[str, int]]:
    if isinstance(cell, bool):
        return None
    if isinstance(cell, int) and 1900 <= cell <= 2100:
        return "year", cell
    if isinstance(cell, float) and cell.is_integer() and 1900 <= cell <= 2100:
        return "year", int(cell)
    if isinstance(cell, str):
        s = " ".join(cell.split())
        return period_parts(s, with_time=True) if s else None
    return None


def _iso(freq: str, o: int) -> str:
    return period_iso("day" if freq == "irregular" else freq, o)



def time_view(d: "Data", m: Optional[Measure], max_points: int = MAX_POINTS) -> Optional[TimeView]:
    ax = d.profile.time_axis
    if ax is None or d.time_col is None:
        return None
    tj = d.time_col
    cells = [(i, _cell_time(d.cell(i, tj))) for i in d.rows_idx]
    cells = [(i, t) for i, t in cells if t is not None]
    if not cells:
        return None
    grans = {t[0] for _, t in cells}
    if "hour" in grans:
        # почасовой ряд: полночь чтение отдаёт днём («2026-01-02») — это час 00:00 того же ряда
        cells = [(i, ("hour", t[1] * 24) if t[0] == "day" else t) for i, t in cells]
        grans = {t[0] for _, t in cells}
    gran = "day" if "day" in grans else sorted(grans, key=lambda g: _FREQ_ORDER.index(g) if g in _FREQ_ORDER else 0)[0]
    if "hour" in grans:
        gran = "hour"
    cells = [(i, t) for i, t in cells if t[0] == gran]
    freq = ax.freq if ax.freq in _FREQ_ORDER else gran
    if _FREQ_ORDER.index(freq) < _FREQ_ORDER.index(gran):
        freq = gran
    irregular = ax.freq == "irregular"
    keyed = []
    for i, (g, o) in cells:
        k = o if irregular else _to_freq(g, o, freq)
        if k is not None:
            keyed.append((i, k))
    if not keyed:
        return None
    src_freq = "day" if irregular else freq
    uniq = sorted({k for _, k in keyed})
    if irregular:
        src_points = len(uniq)
    else:
        src_points = uniq[-1] - uniq[0] + 1
    partial = 0

    def how_of(mm: Optional[Measure]) -> str:
        return "sum" if mm is None else ("mean" if mm.change else mm.how)

    def key_to(t: tuple[str, int], f: str) -> Optional[int]:
        """Номер периода `f` для точки: недельный ряд — по четвергу недели (неделя на стыке месяцев — там, где
        большая часть её дней), остальное — по самой дате."""
        if src_freq == "week" and gran == "day":
            wk = _to_freq("day", t[1], "week")
            return _to_freq("week", wk, f) if wk is not None else None
        return _to_freq(gran, t[1], f)

    # ресэмплинг; почасовой ряд до недели (168 точек) остаётся часами — суточный цикл виден только так; недели — до
    # 60 точек остаются неделями (сумма недель в месяцы врёт: в одном месяце 4 понедельника, в другом — 5)
    target = src_freq
    limit = 168 if src_freq == "hour" else MAX_WEEKS if src_freq == "week" and max_points == MAX_POINTS else max_points
    per_week = False
    if src_points > limit:
        spans = {}
        for f in _FREQ_ORDER[_FREQ_ORDER.index(src_freq) + 1:]:
            ks = [key_to(t, f) for _, t in cells]
            ks = [k for k in ks if k is not None]
            if ks:
                spans[f] = max(ks) - min(ks) + 1
        target = resample_freq(src_freq, src_points, spans)
        keyed = [(i, key_to(t, target)) for i, t in cells]
        keyed = [(i, k) for i, k in keyed if k is not None]
        uniq = sorted({k for _, k in keyed})
        irregular = False
        # недели в месяцы и кварталы — в среднем за неделю, а не суммой (число недель в периоде разное)
        per_week = src_freq == "week" and how_of(m) == "sum"
    partial_txt: list[str] = []
    if target != src_freq and how_of(m) == "sum" and not per_week:
        # полнота периода — по обычному ритму ряда: рабочие дни (будни есть, выходных нет) — полный месяц из 22–23
        # дней; хватает 90% дней (магазин закрыт 1 января); сумма за неполный крайний период занижена — он не
        # показывается и не участвует в выводе
        per: dict[int, set] = {}
        for _, t in cells:
            k = key_to(t, target)
            if k is not None:
                per.setdefault(k, set()).add(t[1])
        cadence = _cadence(gran, [t[1] for _, t in cells])
        drop = set()
        for k in {uniq[0], uniq[-1]}:
            need = _need(gran, target, k, cadence)
            have = len(per.get(k, ()))
            full = have >= need or (gran in ("day", "hour") and have >= 0.9 * need)
            if need and not full and len(uniq) > 2:
                drop.add(k)
                partial_txt.append(f"{period_text(_iso(target, k))} — {have} из {_of_words(gran, need, cadence)}")
        if drop:
            keyed = [(i, k) for i, k in keyed if k not in drop]
            uniq = [k for k in uniq if k not in drop]
            partial = len(drop)
    if irregular or len(uniq) == 2:
        order = uniq
    else:
        order = list(range(uniq[0], uniq[-1] + 1))
    pos = {k: p for p, k in enumerate(order)}
    out_freq = target if not (ax.freq == "irregular" and target == src_freq) else "irregular"
    iso_freq = "day" if out_freq == "irregular" else out_freq
    periods = [_iso(iso_freq, k) for k in order]
    labels = [period_label(p, out_freq) for p in periods]

    # ряды: длинный формат — по категориям, иначе метрика (и метрики в тех же единицах)
    dupes = len(keyed) > len({k for _, k in keyed})
    cat_moves: dict[str, tuple[float, float]] = {}
    series: list[SeriesV] = []
    dim_name = None
    others = 0
    measures = [m] if m is not None else []
    how = m.how if m is not None else "sum"
    if (m is not None and m.change) or per_week:
        how = "mean"

    def agg(vals: list[float], how_: str) -> Optional[float]:
        if not vals:
            return None
        if how_ == "sum":
            return float(sum(vals))
        if how_ == "last":
            return float(vals[-1])
        return float(sum(vals) / len(vals))

    if dupes and d.dims and m is not None:
        dj = next((j for j in d.dims if 2 <= d.cols[j].distinct <= 12), None)
        if dj is not None:
            dim_name = d.cols[dj].name
            groups: dict[str, dict[int, list[float]]] = {}
            g_units: dict[str, list[str]] = {}
            for i, k in keyed:
                v = m.raw[i] if m.mixed else m.values[i]
                lab = d.text(i, dj)
                if v is None or not lab:
                    continue
                groups.setdefault(lab, {}).setdefault(pos[k], []).append(v)
                if m.mixed:
                    g_units.setdefault(lab, []).append(m.row_units[i] or "")
            tot = {g: sum(sum(x) for x in d.values()) for g, d in groups.items()}
            for g, dd in groups.items():
                seq = [agg(dd[p_], how) for p_ in sorted(dd)]
                seq = [v for v in seq if v is not None]
                if len(seq) >= 2:
                    cat_moves[g] = (seq[0], seq[-1])
            # порядок рядов — по величине: у сумм — по итогу, у уровней — по среднему значению
            cnt = {g: sum(len(x) for x in dd.values()) for g, dd in groups.items()}
            names = sorted(groups, key=lambda g: (-(tot[g] if m.additive else tot[g] / max(1, cnt[g])), g))
            keep = names
            if len(names) > MAX_SERIES:
                keep = names[: MAX_SERIES - 1]
                others = len(names) - len(keep)
            for g in keep:
                vals = [agg(groups[g].get(p, []), how) for p in range(len(order))]
                gu = m.unit_text
                if m.mixed and g_units.get(g):
                    gu = max(set(g_units[g]), key=g_units[g].count) or None
                series.append(SeriesV(g, gu, vals))
            if others:
                # «Остальные N»: сначала значение каждой категории за период (сумма, последнее, среднее),
                # потом сумма по категориям (уровень — среднее по ним, это и сказано в подписи)
                rest_vals = []
                for p_ in range(len(order)):
                    per_cat = [agg(groups[g].get(p_, []), how) for g in names[len(keep):]]
                    per_cat = [v for v in per_cat if v is not None]
                    if not per_cat:
                        rest_vals.append(None)
                    elif m.additive or m.stock:
                        rest_vals.append(float(sum(per_cat)))
                    else:
                        rest_vals.append(float(sum(per_cat) / len(per_cat)))
                label = f"Остальные {others}" if (m.additive or m.stock) else f"Остальные {others} (среднее)"
                series.append(SeriesV(label, m.unit_text, rest_vals))
    if not series:
        if m is None:
            counts = [0] * len(order)
            for _, k in keyed:
                counts[pos[k]] += 1
            series = [SeriesV("Число строк", None, [float(c) for c in counts])]
            how = "sum"
        else:
            # метрики одного рода (Scopus и РИНЦ, план и факт) — каждая своим рядом
            if m in d.parallel:
                measures = list(d.parallel)
            for mm in measures:
                buckets: dict[int, list[float]] = {}
                for i, k in keyed:
                    v = mm.values[i]
                    if v is not None:
                        buckets.setdefault(pos[k], []).append(v)
                h = how if mm is m else mm.how
                nm = d.series_names.get(mm.name, mm.name) if len(measures) > 1 else mm.name
                series.append(SeriesV(nm, mm.unit_text, [agg(buckets.get(p, []), h) for p in range(len(order))]))
    if len(series) > 1 and not dim_name:
        # главный ряд — первым (тот, что назван целью или первый по порядку)
        series.sort(key=lambda sv: sv.name != d.series_names.get(m.name, m.name))
    meas = m if m is not None else Measure(j=-1, name="Число строк", unit=None, type="number",
                                           values=[1.0] * len(d.table.rows))
    return TimeView(
        column=d.cols[tj].name, freq=out_freq, periods=periods, labels=labels, series=series, measure=meas,
        source_freq="irregular" if ax.freq == "irregular" else src_freq, source_points=src_points, how=how,
        dim=dim_name, others=others, column_type=d.cols[tj].type, partial=partial, partial_txt=partial_txt,
        cat_moves=cat_moves, per_week=per_week,
    )



def columns_time_view(d: "Data") -> Optional[TimeView]:
    """Ось времени из колонок-периодов («I кв. · II кв. · III кв. · IV кв.» по регионам), когда своей оси нет: значение
    периода — сумма по строкам (поток) или среднее (уровень), один ряд. Год — из названий колонок или файла; без года
    оси нет. Колонка-итог («Итого за год») — не период."""
    import re

    from verstka.data.parse import is_total_label
    from verstka.data.words import file_title, head_word, phrase

    title = file_title(d.profile.file, d.profile.sheet)
    ty = re.search(r"(?:^|\D)((?:19|20)\d\d)(?:\D|$)", title)
    cols = []
    for m in d.measures:
        if m.change or m.mixed or is_total_label(m.name):
            continue
        nm = " ".join(m.name.split())
        pp = period_parts(nm)
        if pp is None and ty is not None:
            pp = period_parts(f"{nm} {ty.group(1)}")
        if pp is not None and pp[0] in ("month", "quarter", "year"):
            cols.append((pp, m))
    if len(cols) < 3 or len({pp[0] for pp, _ in cols}) != 1 or len({pp for pp, _ in cols}) != len(cols):
        return None
    if len({(m.unit or "") for _, m in cols}) != 1 or len({m.additive for _, m in cols}) != 1:
        return None
    cols.sort(key=lambda t: t[0][1])
    freq = cols[0][0][0]
    add = cols[0][1].additive
    vals: list[Optional[float]] = []
    for _, m in cols:
        xs = [m.values[i] for i in d.rows_idx if m.values[i] is not None]
        vals.append((float(sum(xs)) if add else float(sum(xs) / len(xs))) if xs else None)
    periods = [_iso(freq, pp[1]) for pp, _ in cols]
    # имя ряда — по названию датасета («Выручка по кварталам 2025» → «Выручка»)
    head = head_word(re.sub(r"^(?:[\w-]*\d[\w-]*\s+)+", "", title))
    hp = phrase(head) if head else None
    name = hp.nom[:1].upper() + hp.nom[1:] if hp is not None and hp.sure else "Сумма"
    m0 = cols[0][1]
    meas = Measure(j=-2, name=name, unit=m0.unit, type=m0.type, values=[], level=m0.level, time_unit=m0.time_unit,
                   basis=m0.basis)
    return TimeView(column={"quarter": "Квартал", "month": "Месяц", "year": "Год"}[freq], freq=freq, periods=periods,
                    labels=[period_label(p_, freq) for p_ in periods], series=[SeriesV(name, m0.unit_text, vals)],
                    measure=meas, source_freq=freq, source_points=len(periods), how="sum" if add else "mean",
                    column_type="period", from_columns=True)
