"""Самопроверка выводов (самоконтроль качества): каждое число заголовка и подписи пересчитывается по СЫРЫМ строкам
таблицы — по происхождению, которое объявил факт (колонка, сборка, отбор строк, периоды, база), — до того, как вывод
покажут.

Происхождение (`FactSet.prov[id]`) — словарь «op» и параметров: категория и её сборка (`cat`), доля (`share`, `pshare`,
`colshare`, `topn`), итог колонки (`colsum`), ряд по времени (`series`: значение периода, изменение %, п.п., в единицах,
«в N раз», максимум, среднее, число периодов), ряд по колонкам-периодам (`colseries`), «выросла в N из M» (`moved`),
распределение (`dist`), связь (`corr`, `slope`), ячейка и её изменение (`cell`, `cellchange`), исполнение плана
(`exec`), конверсия воронки (`conv`), счёт (`count`, `neg`, `above`), отношение двух величин (`ratio`). Пересчёт не
использует ни `Data`, ни виды анализа: только ячейки таблицы и разбор чисел и дат (`parse.py`).

Если хоть одно число заголовка не подтвердилось (или его нечем проверить) — заголовок заменяется заголовком-описанием,
подпись без подтверждённых чисел — фактической подписью, а причина идёт в «Почему так» («Вывод не подтвердился
проверкой: …»). Название величины в выводе проверяется тоже: доля «суммы выплат» должна быть посчитана по сумме, а не
по числу выплат."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, Sequence

from verstka.data.parse import iso_ord, period_parts, quantity, season_name, season_ord
from verstka.data.words import fmt_num, stem, stems_of
from verstka.schemas.data import HeadlineFact, Table

__all__ = ["Verdict", "verify", "numbers_ok", "claims_problem"]


@dataclass
class Verdict:
    """Итог самопроверки: какие факты подтвердились, что не так, и годятся ли заголовок и подпись."""

    ok: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)  # id → почему
    pool: list[float] = field(default_factory=list)  # подтверждённые значения (и промежуточные: база, итог, группы)
    headline_ok: bool = True
    caption_ok: bool = True
    reasons: list[str] = field(default_factory=list)


# строка-остаток («Прочее», «Другие»): в сравнении её нет — ни лидер, ни последний
_OTHER = re.compile(r"^(?:прочее|прочие|другое|другие|остальное|остальные|иное|иные|прочее\s+\S+|другие\s+\S+)$", re.I)


def is_other_label(label: str) -> bool:
    return bool(_OTHER.match(" ".join(str(label).split())))


# ── сырые ячейки ──────────────────────────────────────────────────────────────────────────────────────────────────
def _num(cell: Any, shown: bool = False) -> Optional[float]:
    """Число ячейки; shown — как написано, без множителя («1,24 млрд ₽» → 1,24: так его показывает карточка)."""
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(cell) else None
    q = quantity(" ".join(str(cell).split()))
    return None if q is None else q.value if shown else q.full


def _text(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, bool):
        return "да" if cell else "нет"
    if isinstance(cell, (int, float)):
        return fmt_num(float(cell))
    return " ".join(str(cell).split())


class _Raw:
    def __init__(self, t: Table, skip: Sequence[int] = ()):
        self.t = t
        sk = set(skip)
        self.rows = [i for i in range(len(t.rows)) if i not in sk]

    def cell(self, i: int, j: int) -> Any:
        r = self.t.rows[i]
        return r[j] if 0 <= j < len(r) else None

    def num(self, i: int, j: int, scale: float = 1.0, shown: bool = False) -> Optional[float]:
        v = _num(self.cell(i, j), shown)
        return None if v is None else v / scale

    def text(self, i: int, j: int) -> str:
        return _text(self.cell(i, j))

    def groups(self, by: int, j: Optional[int], scale: float = 1.0, rowcols: Sequence[int] = (),
               rowagg: str = "sum") -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for i in self.rows:
            lab = self.text(i, by)
            if rowcols:  # перекрёстная таблица: значение строки — сумма или среднее её колонок
                xs = [x for x in (self.num(i, c, scale) for c in rowcols) if x is not None]
                v = None if not xs else (sum(xs) if rowagg == "sum" else sum(xs) / len(xs))
            else:
                v = 1.0 if j is None else self.num(i, j, scale)
            if lab and v is not None:
                out.setdefault(lab, []).append(v)
        return out


def _agg(xs: list[float], how: str) -> float:
    if how == "sum":
        return float(sum(xs))
    if how == "count":
        return float(len(xs))
    if how == "last":
        return float(xs[-1])
    return float(sum(xs) / len(xs))


# ── время ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _time(cell: Any) -> Optional[tuple[str, int]]:
    if isinstance(cell, bool) or cell is None:
        return None
    if isinstance(cell, (int, float)) and float(cell).is_integer() and 1900 <= cell <= 2100:
        return "year", int(cell)
    s = " ".join(str(cell).split())
    return period_parts(s, with_time=True) if s else None


def _key(gran: str, o: int, f: str, week_src: bool) -> Optional[int]:
    """Номер периода `f` для точки (`gran`, `o`); недельный ряд — по четвергу недели."""
    if f == "irregular":
        return o
    if week_src and gran == "day" and f != "week":
        o = ((o - 1) // 7) * 7 + 4
    if gran == f:
        return o
    if gran == "hour":
        if f == "day":
            return o // 24
        o, gran = o // 24, "day"
    if gran == "day":
        d = date.fromordinal(o)
        return {"week": (o - 1) // 7, "month": d.year * 12 + d.month - 1, "quarter": d.year * 4 + (d.month - 1) // 3,
                "year": d.year}.get(f)
    if gran == "week":
        return _key("day", o * 7 + 4, f, False)
    if gran == "month":
        return {"quarter": (o // 12) * 4 + (o % 12) // 3, "year": o // 12}.get(f)
    if gran == "quarter" and f == "year":
        return o // 4
    return None


def _iso_key(iso: str, f: str) -> Optional[int]:
    io = iso_ord(iso, with_time=True)
    if io is None:
        return None
    if f == "hour" and io[0] == "day":
        return io[1] * 24  # полночь («2026-01-12T00:00») читается как день
    return io[1] if f in (io[0], "irregular") else _key(io[0], io[1], f, False)


def _series(raw: _Raw, p: dict) -> dict[int, float]:
    """Значения периодов по сырым строкам: строки → номер периода частоты `freq` → сборка (`agg`)."""
    tj, f = p["time"], p["freq"]
    scale = p.get("scale", 1.0)
    week_src = bool(p.get("week_src"))
    cat = p.get("cat")
    cols = p.get("cols") or ([p["col"]] if p.get("col") is not None else [])
    pts: list[tuple[int, int, float]] = []  # (номер периода, строка, значение)
    hourly = any((_time(raw.cell(i, tj)) or ("", 0))[0] == "hour" for i in raw.rows)
    st = iso_ord(p["ax_start"]) if p.get("ax_start") else None
    for i in raw.rows:
        if cat is not None and raw.text(i, cat[0]) != cat[1]:
            continue
        tt = _time(raw.cell(i, tj))
        if tt is None and st is not None and st[0] in ("month", "quarter"):
            # месяц или квартал без года — по началу оси (год из колонки, файла или условный)
            sn = season_name(raw.cell(i, tj))
            if sn is not None and sn[0] == st[0]:
                per = 12 if st[0] == "month" else 4
                tt = (sn[0], season_ord(sn[0], sn[1], st[1] // per, st[1] % per + 1))
        if tt is None:
            continue
        g, o = tt
        if hourly and g == "day":
            g, o = "hour", o * 24
        k = _key(g, o, f, week_src)
        if k is None:
            continue
        if cols:
            vs = [raw.num(i, j, scale) for j in cols]
            if any(v is None for v in vs):
                continue
            v = float(sum(vs))  # type: ignore[arg-type]
        else:
            v = 1.0
        pts.append((k, i, v))
    how = p.get("agg", "sum")
    out: dict[int, float] = {}
    by: dict[int, list[tuple[int, float]]] = {}
    for k, i, v in pts:
        by.setdefault(k, []).append((i, v))
    for k, xs in by.items():
        xs.sort()
        if how == "sum_last_by":
            last: dict[str, float] = {}
            for i, v in xs:
                last[raw.text(i, p["by"])] = v
            out[k] = float(sum(last.values()))
        else:
            out[k] = _agg([v for _, v in xs], how)
    return out


def _colseries(raw: _Raw, p: dict) -> list[float]:
    scale = p.get("scale", 1.0)
    out = []
    for j in p["cols"]:
        xs = [v for v in (raw.num(i, j, scale) for i in raw.rows) if v is not None]
        out.append(_agg(xs, p.get("agg", "sum")) if xs else float("nan"))
    return out


def _change(a: float, b: float, kind: str) -> float:
    """Изменение от a к b: «pct» — %, «pp» — пункты, «abs» — в единицах, «ratio» — во сколько раз."""
    if kind == "pct":
        return (b / a - 1) * 100
    if kind == "ratio":
        return b / a if b >= a else a / b
    return b - a


# ── пересчёт одного факта ─────────────────────────────────────────────────────────────────────────────────────────
class _Fail(Exception):
    pass


def _compute(t: Table, p: dict) -> tuple[float, list[float]]:
    """(значение по сырым строкам, промежуточные значения для проверки подписи)."""
    op = p["op"]
    raw = _Raw(t, list(p.get("skip", ())) + list(p.get("exclude", ())))
    if p.get("only") is not None:
        only = set(p["only"])
        raw.rows = [i for i in raw.rows if i in only]
    scale = p.get("scale", 1.0)
    if op == "add":
        got = [_compute(t, q) for q in p["parts"]]
        return float(sum(g[0] for g in got)), [x for g in got for x in g[1]]
    if op == "change2":
        # изменение между двумя пересчитанными величинами (средние первых и последних периодов)
        a, ea = _compute(t, p["base"])
        b, eb = _compute(t, p["cur"])
        if p["kind"] == "pct" and a <= 0:
            raise _Fail("база не положительная")
        return _change(a, b, p["kind"]), ea + eb + [a, b]
    if op == "ratio":
        a, ea = _compute(t, p["a"])
        b, eb = _compute(t, p["b"])
        if not b:
            raise _Fail("делитель — ноль")
        return a / b, ea + eb + [a, b]
    if op == "colrank":
        # перекрёстная таблица: колонки сравниваются по сумме или среднему по строкам
        agg = {}
        for name, j in p["cols"].items():
            xs = [v for v in (raw.num(i, j, scale) for i in raw.rows) if v is not None]
            if xs:
                agg[name] = _agg(xs, p.get("agg", "sum"))
        keys = p["keys"]
        if any(k not in agg for k in keys):
            raise _Fail(f"нет колонки «{keys[0]}»")
        vals = [agg[k] for k in keys]
        rank = p.get("rank")
        if rank == "max" and any(v < max(agg.values()) - 1e-9 * max(1.0, abs(v)) for v in vals):
            raise _Fail(f"«{keys[0]}» — не наибольшее значение")
        if rank == "min" and any(v > min(agg.values()) + 1e-9 * max(1.0, abs(v)) for v in vals):
            raise _Fail(f"«{keys[0]}» — не наименьшее значение")
        if p.get("share"):
            return sum(vals) / sum(agg.values()) * 100, list(agg.values())
        return vals[0], list(agg.values())
    if op in ("cat", "share", "neg", "above"):
        g = raw.groups(p["by"], p.get("col"), scale, p.get("rowcols") or (), p.get("rowagg", "sum"))
        agg = {k: _agg(v, p.get("agg", "sum")) for k, v in g.items()}
        ex = list(agg.values())
        if op == "neg":
            return float(sum(1 for v in agg.values() if v < 0)), ex
        if op == "above":
            return float(sum(1 for k, v in agg.items() if v > p["v"] and k not in p.get("exclude", ()))), ex
        keys = p["keys"]
        missing = [k for k in keys if k not in agg]
        if missing:
            raise _Fail(f"нет категории «{missing[0]}» в колонке")
        if op == "cat":
            vals = [agg[k] for k in keys]
            rank = p.get("rank")
            # «Прочее», «Другие» — никогда не лидер и не последний: их нет в сравнении
            pool = {k: v for k, v in agg.items() if k not in set(p.get("exclude", ())) and not is_other_label(k)}
            if rank == "max" and pool and any(v < max(pool.values()) - 1e-9 * max(1.0, abs(v)) for v in vals):
                raise _Fail(f"«{keys[0]}» — не наибольшее значение")
            if rank == "min" and pool and any(v > min(pool.values()) + 1e-9 * max(1.0, abs(v)) for v in vals):
                raise _Fail(f"«{keys[0]}» — не наименьшее значение")
            if rank in ("max", "min") and pool:
                # ничья: с тем же значением есть ещё категории, а названы не все
                tied = [k for k, v in pool.items() if k not in keys and abs(v - vals[0]) <= 1e-9 * max(1.0, abs(v))]
                if tied:
                    raise _Fail(f"ничья: у «{keys[0]}» и «{tied[0]}» одно значение, а названа одна")
            return vals[0], ex
        num = sum(agg[k] for k in keys)
        if p.get("total_row") is not None:
            den = raw.num(p["total_row"], p["col"], scale)
        else:
            den = sum(agg.values())
        if not den:
            raise _Fail("целое — ноль")
        return num / den * 100, ex + [num, den]
    if op == "pshare":
        g = raw.groups(p["by"], p["col"])
        agg = {k: sum(v) for k, v in g.items()}
        tot = sum(agg.values())
        f = 100.0 / tot if 0.95 <= tot <= 1.05 else 1.0
        return sum(agg[k] for k in p["keys"] if k in agg) * f, [v * f for v in agg.values()]
    if op == "colshare":
        sums = [sum(v for v in (raw.num(i, j, scale) for i in raw.rows) if v is not None) for j in p["cols"]]
        part = sum(v for v in (raw.num(i, p["col"], scale) for i in raw.rows) if v is not None)
        if not sum(sums):
            raise _Fail("целое — ноль")
        return part / sum(sums) * 100, sums + [part, sum(sums)]
    if op == "freq":
        # частотная таблица: значение и сколько раз оно встретилось
        pairs = [(raw.num(i, p["value"]), raw.num(i, p["count"])) for i in raw.rows]
        pairs = [(a, int(b)) for a, b in pairs if a is not None and b is not None]
        tot = sum(n for _, n in pairs)
        if not tot:
            raise _Fail("счёт — ноль")
        st = p["stat"]
        top = max(n for _, n in pairs)
        if st in ("mode_count", "mode_share"):
            modes = sorted(a for a, n in pairs if n == top)
            if sorted(p.get("modes", modes)) != modes:
                raise _Fail("самое частое значение — другое")
            return (float(top) if st == "mode_count" else top / tot * 100), [float(tot)]
        if st == "total":
            return float(tot), []
        if st == "count_at":
            got = [n for a, n in pairs if abs(a - p["at"]) < 1e-9]
            if not got:
                raise _Fail("нет такого значения")
            return float(got[0]), [float(tot)]
        xs = sorted(a for a, n in pairs for _ in range(n))
        return (sum(xs) / len(xs) if st == "mean" else _pct(xs, 50)), [float(tot)]
    if op == "rows_gt":
        pairs = [(raw.num(i, p["a"]), raw.num(i, p["b"])) for i in raw.rows]
        return float(sum(1 for a, b in pairs if a is not None and b is not None and a > b)), []
    if op == "colsum":
        if p.get("cols"):
            xs = [v for j in p["cols"] for v in (raw.num(i, j, scale) for i in raw.rows) if v is not None]
            if p.get("agg") == "mean":
                if not xs:
                    raise _Fail("нет значений")
                return float(sum(xs) / len(xs)), []
            return float(sum(xs)), []
        if p.get("row") is not None:
            v = raw.num(p["row"], p["col"], scale)
            if v is None:
                raise _Fail("пустая ячейка итога")
            return v, []
        xs = [v for v in (raw.num(i, p["col"], scale) for i in raw.rows) if v is not None]
        return float(sum(xs)), xs
    if op == "topn":
        xs = sorted((v for v in (raw.num(i, p["col"], scale) for i in raw.rows) if v is not None), reverse=True)
        top, tot = sum(xs[:p["n"]]), sum(xs)
        if p.get("total_row") is not None:
            tot = raw.num(p["total_row"], p["col"], scale) or 0.0
        if not tot:
            raise _Fail("итог — ноль")
        share = top / tot * 100
        what = p.get("what", "share")
        val = share if what == "share" else 100 - share if what == "rest" else tot - top
        return val, [top, tot, tot - top, share, 100 - share]
    if op == "series":
        s = _series(raw, p)
        ks = sorted(s)
        mode = p["mode"]
        fk = _iso_key(p["from"], p["freq"]) if p.get("from") else (ks[0] if ks else None)
        tk = _iso_key(p["to"], p["freq"]) if p.get("to") else (ks[-1] if ks else None)
        if mode == "span":
            if fk is None or tk is None:
                raise _Fail("нет периодов")
            if p["freq"] == "irregular":  # даты без шага: число шагов между точками
                return float(sum(1 for k in ks if fk <= k <= tk) - 1), []
            return float(tk - fk), []
        if mode == "missing":
            if fk is None or tk is None:
                raise _Fail("нет периодов")
            return float((tk - fk + 1) - sum(1 for k in ks if fk <= k <= tk)), []
        if mode == "at":
            if tk not in s:
                raise _Fail("нет значения за период")
            return s[tk], [s[tk]]
        if mode == "year":
            if tk not in s:
                raise _Fail("такого периода в файле нет")
            return float(int(str(p["to"])[:4])), []
        rng = [s[k] for k in ks if fk is not None and tk is not None and fk <= k <= tk]
        if mode in ("max", "min", "mean", "count", "neg"):
            if not rng:
                raise _Fail("нет значений за периоды")
            v = max(rng) if mode == "max" else min(rng) if mode == "min" else len(rng) if mode == "count" else \
                sum(1 for x in rng if x < 0) if mode == "neg" else sum(rng) / len(rng)
            return float(v), rng
        if fk not in s or tk not in s:
            raise _Fail("нет значения в начале или в конце")
        return _change(s[fk], s[tk], p["kind"]), [s[fk], s[tk], s[tk] - s[fk]]
    if op == "colseries":
        vals = _colseries(raw, p)
        mode = p["mode"]
        if mode == "at":
            return vals[p["k"]], vals
        if mode in ("max", "min"):
            return (max(vals) if mode == "max" else min(vals)), vals
        if mode == "mean":
            return sum(vals) / len(vals), vals
        if mode == "neg":
            return float(sum(1 for v in vals if v < 0)), vals
        if mode == "span":
            return float(len(vals) - 1), vals
        return _change(vals[0], vals[-1], p["kind"]), vals + [vals[0], vals[-1]]
    if op == "moved":
        cats = sorted({raw.text(i, p["by"]) for i in raw.rows} - {""})
        up = down = n = 0
        ends = []
        for c in cats:
            s = _series(raw, {**p, "cat": (p["by"], c)})
            if len(s) >= 2:
                ks = sorted(s)
                n += 1
                up += s[ks[-1]] > s[ks[0]]
                down += s[ks[-1]] < s[ks[0]]
                ends.append(s[ks[-1]])
        if p.get("what") == "of":
            return float(n), ends
        if p.get("what") in ("up", "down"):
            return float(up if p["what"] == "up" else down), ends
        if p.get("what") == "leader":
            return max(ends), ends
        return float(max(up, down)), ends
    if op == "dist":
        xs = sorted(v for v in (raw.num(i, p["col"], scale) for i in raw.rows) if v is not None)
        if not xs:
            raise _Fail("нет значений")
        st = p["stat"]
        if st == "median":
            return _pct(xs, 50), xs[:1] + xs[-1:]
        if st == "p":
            return _pct(xs, p["q"]), []
        if st == "mean":
            return sum(xs) / len(xs), []
        if st == "count":
            return float(len(xs)), []
        if st == "within":
            k = sum(1 for v in xs if v <= p["thr"] + 1e-9)
            return k / len(xs) * 100, [float(k), float(len(xs))]
        if st == "count_from":
            return float(sum(1 for v in xs if v >= p["thr"] - 1e-9)), []
        if st == "count_to":
            return float(sum(1 for v in xs if v <= p["thr"] + 1e-9)), []
        if st in ("min", "max"):
            return (xs[0] if st == "min" else xs[-1]), []
        if st == "neg":
            return float(sum(1 for v in xs if v < 0)), []
        if st == "count_eq":
            return float(sum(1 for v in xs if abs(v - p["thr"]) <= 1e-9 * max(1.0, abs(v)))), []
        if st == "upper":
            # граница «не больше X» — перцентиль, округлённый вверх: не ниже него
            if p["thr"] < _pct(xs, p["q"]) - 1e-9 * max(1.0, abs(p["thr"])):
                raise _Fail(f"граница {fmt_num(p['thr'])} ниже {p['q']}-го перцентиля")
            return p["thr"] * p.get("factor", 1.0), [p["thr"]]
        if st in ("bound", "beyond"):
            side, thr = p["side"], p["thr"]
            hit = {"ge": lambda v: v >= thr - 1e-9, "gt": lambda v: v > thr + 1e-9,
                   "le": lambda v: v <= thr + 1e-9, "lt": lambda v: v < thr - 1e-9}[side]
            k = sum(1 for v in xs if hit(v))
            if st == "beyond":
                return float(k), []
            if k != p["k"]:
                raise _Fail(f"за границей {fmt_num(thr)} — {k} значений, а не {p['k']}")
            return thr, [p.get("shown", thr)]
        raise _Fail(f"нет статистики «{st}»")
    if op in ("corr", "slope", "pairs"):
        pairs = [(raw.num(i, p["x"], p.get("sx", 1.0)), raw.num(i, p["y"], p.get("sy", 1.0))) for i in raw.rows]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        if op == "pairs":
            return float(len(pairs)), []
        if len(pairs) < 3:
            raise _Fail("мало пар")
        n = len(pairs)
        mx = sum(a for a, _ in pairs) / n
        my = sum(b for _, b in pairs) / n
        sxy = sum((a - mx) * (b - my) for a, b in pairs)
        sxx = sum((a - mx) ** 2 for a, _ in pairs)
        syy = sum((b - my) ** 2 for _, b in pairs)
        if op == "slope":
            return sxy / sxx if sxx else 0.0, [float(n)]
        r = sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0
        return max(-0.99, min(0.99, r)), [float(n)]
    if op == "cell":
        v = raw.num(p["row"], p["col"], scale, bool(p.get("shown")))
        if v is None:
            raise _Fail("пустая ячейка")
        return v, [v]
    if op == "cellchange":
        sh = bool(p.get("shown"))
        a, b = raw.num(p.get("prev_row", p["row"]), p["prev"], 1.0, sh), raw.num(p["row"], p["cur"], 1.0, sh)
        if a is None or b is None:
            raise _Fail("пустая ячейка")
        if p["kind"] == "pct" and a <= 0:
            raise _Fail("база не положительная")
        return _change(a, b, p["kind"]), [a, b]
    if op == "exec":
        rows = [(raw.text(i, p["by"]) if p.get("by") is not None else str(i), raw.num(i, p["plan"], scale),
                 raw.num(i, p["fact"], scale)) for i in raw.rows]
        grp: dict[str, list[float]] = {}
        for k, a, b in rows:
            if a is not None and b is not None and k:
                g = grp.setdefault(k, [0.0, 0.0])
                g[0] += a
                g[1] += b
        pairs = {k: (a, b) for k, (a, b) in grp.items() if a > 0}
        ps, fs_ = sum(a for a, _ in pairs.values()), sum(b for _, b in pairs.values())
        if not ps:
            raise _Fail("план — ноль")
        what = p.get("what", "exec")
        if what == "over":
            return float(sum(1 for a, b in pairs.values() if b > a)), [ps, fs_]
        if what == "n":
            return float(len(pairs)), [ps, fs_]
        if what == "low":
            ex = {k: b / a * 100 for k, (a, b) in pairs.items()}
            if p.get("key") not in ex or ex[p["key"]] > min(ex.values()) + 1e-9:
                raise _Fail(f"«{p.get('key')}» — не самое низкое исполнение")
            return ex[p["key"]], [ps, fs_]
        return (fs_ / ps * 100 if what == "exec" else ps if what == "plan" else fs_), [ps, fs_]
    if op == "conv":
        a, b = raw.num(p["first"], p["col"]), raw.num(p["last"], p["col"])
        if not a or b is None:
            raise _Fail("нет этапов")
        return b / a * 100, [a, b]
    if op == "count":
        what = p["what"]
        if what == "rows":
            if p.get("col") is None:
                return float(len(raw.rows) - p.get("minus", 0)), []
            return float(sum(1 for i in raw.rows if raw.num(i, p["col"]) is not None)), []
        if what == "groups":
            return float(len({raw.text(i, p["by"]) for i in raw.rows} - {""}) - p.get("minus", 0)), []
        if what == "rows_list":
            return float(len([i for i in p["rows"] if i < len(t.rows)])), []
        return float(p["value"]), []
    raise _Fail(f"неизвестное происхождение «{op}»")


def _pct(xs: list[float], q: float) -> float:
    """Перцентиль с линейной интерполяцией (как у numpy по умолчанию)."""
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q / 100
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


# ── сравнение ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _decimals(v: float) -> int:
    for k in range(0, 7):
        if abs(round(v, k) - v) < 1e-9 * max(1.0, abs(v)):
            return k
    return 7


def _agrees(fact: float, true: float, kind: str = "", tol: Optional[float] = None) -> bool:
    """Значение факта — пересчёт, округлённый так, как его хранит факт (целое, десятые, сотые…)."""
    a, b = abs(fact), abs(true)
    if tol is not None:
        return abs(a - b) <= tol
    k = _decimals(fact)
    return abs(a - b) <= 0.5 * 10 ** (-k) + 1e-9 * max(1.0, b) or abs(a - b) <= 1e-6 * max(1.0, b)


_NUM_IN_TEXT = re.compile(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[   ]\d{3})+(?:,\d+)?(?![\d])"
                          r"|(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])")


def numbers_ok(text: str, values: Sequence[float], labels: Sequence[str] = ()) -> list[float]:
    """Числа текста, которых нет среди значений (как их пишет текст: целое, десятые, сотые); пусто — все на месте."""
    from verstka.data.headline import numbers_in

    bad = []
    for n in numbers_in(text or "", labels):
        if not any(_shown_as(n, v) for v in values):
            bad.append(n)
    return bad


def _shown_as(n: float, v: float) -> bool:
    v = abs(v)
    if abs(n - v) < 1e-9 * max(1.0, v):
        return True
    for d in range(0, 5):
        if abs(round(v, d) - n) < 1e-9:
            return True
    # проценты от 10 — целыми, огромные значения — с множителем (7 345 000 000 000 → «7,3 трлн»)
    for f in (1e3, 1e6, 1e9, 1e12):
        if v >= f and any(abs(round(v / f, d) - n) < 1e-9 for d in (0, 1, 2)):
            return True
    return False


def _named_ok(named: str, col_name: str, title: str) -> bool:
    """Величина в тексте («суммы выплат») — это колонка происхождения: каждое её значимое слово есть в названии колонки
    (или в названии файла, если колонка безликая: «Сумма», «Итого за год»)."""
    want = [s for s in stems_of(named) if len(s) >= 3 and s not in ("числ", "количеств", "доля", "дол")]
    have = stems_of(col_name)
    generic = bool(re.match(r"^(?:сумма|итого|всего|значение|количество|число|объ[её]м|показатель|общий итог)\b",
                            col_name.strip(), re.I))
    if generic or not have:
        have = have + stems_of(title)
    return all(any(_stem_eq(w, h) for h in have) for w in want)


def _stem_eq(a: str, b: str) -> bool:
    """Одно слово в разных формах: «выплат» = «выплаты», «добавивших» = «добавили» (общее начало от 5 букв)."""
    a, b = stem(a), stem(b)
    short, long_ = sorted((a, b), key=len)
    common = len(next((a[:k] for k in range(min(len(a), len(b)), 0, -1) if a[:k] == b[:k]), ""))
    return a == b or (len(short) >= 4 and long_.startswith(short)) or (len(short) >= 5 and short in long_) \
        or common >= 5


# ── проверка плана ────────────────────────────────────────────────────────────────────────────────────────────────
def verify(table: Table, facts: Sequence[HeadlineFact], prov: dict[str, dict], headline: str,
           caption: Optional[str], labels: Sequence[str] = (), title: str = "",
           bins: Optional[dict] = None) -> Verdict:
    """Пересчитывает каждый факт по сырым строкам и проверяет, что числа заголовка и подписи — подтверждённые, а
    утверждения (кто впереди, кто растёт быстрее всех, «во всех N», «в K из N», ничьи, «лучше», цель, столбцы
    гистограммы) — правда по тем же строкам. `bins` — столбцы гистограммы слайда (подписи, счёт, открытые края)."""
    v = Verdict()
    for f in facts:
        p = prov.get(f.id)
        if p is None:
            v.failed[f.id] = "нечем проверить: не объявлено, откуда число"
            continue
        try:
            true, extra = _compute(table, p)
        except _Fail as e:
            v.failed[f.id] = str(e)
            continue
        except (ValueError, IndexError, KeyError, ZeroDivisionError, TypeError) as e:
            v.failed[f.id] = f"не пересчитать: {type(e).__name__}"
            continue
        if not _agrees(f.value, true, tol=p.get("tol")):
            v.failed[f.id] = f"{f.text}: по строкам файла — {fmt_num(true)}"
            continue
        if p.get("named") and p.get("col_name") and not _named_ok(p["named"], p["col_name"], title):
            v.failed[f.id] = f"«{p['named']}» — не колонка «{p['col_name']}», по которой посчитано"
            continue
        v.ok.add(f.id)
        v.pool += [f.value, true] + list(extra)
    ok_vals = [f.value for f in facts if f.id in v.ok]
    bad_head = numbers_ok(headline, ok_vals, labels)
    if bad_head:
        # число заголовка не подтверждено ни одним проверенным фактом: причина — проверка факта с этим числом
        v.headline_ok = False
        why = next((v.failed[f.id] for f in facts if f.id in v.failed and _shown_as(bad_head[0], f.value)),
                   f"число {fmt_num(bad_head[0])} не подтверждено строками файла")
        v.reasons.append(f"Вывод не подтвердился проверкой: {why}")
    if caption:
        bad_cap = numbers_ok(caption, list(v.pool), labels)
        if bad_cap:
            v.caption_ok = False
            why = next((v.failed[f.id] for f in facts if f.id in v.failed and _shown_as(bad_cap[0], f.value)),
                       f"число {fmt_num(bad_cap[0])} не подтверждено строками файла")
            v.reasons.append(f"Подпись не подтвердилась проверкой: {why}")
    # утверждения, не только числа
    ok = {f.id: f for f in facts if f.id in v.ok}
    if v.headline_ok:
        why_h = claims_problem(headline, ok, prov, table, title)
        if why_h:
            v.headline_ok = False
            v.reasons.append(f"Вывод не подтвердился проверкой: {why_h}")
    if caption and v.caption_ok:
        why_c = claims_problem(caption, ok, prov, table, title, caption=True) or \
            (_bins_problem(table, bins) if bins else None)
        if why_c:
            v.caption_ok = False
            v.reasons.append(f"Подпись не подтвердилась проверкой: {why_c}")
    elif bins:
        why_b = _bins_problem(table, bins)
        if why_b:
            v.caption_ok = False
            v.reasons.append(f"Подпись не подтвердилась проверкой: {why_b}")
    return v


# ── утверждения ───────────────────────────────────────────────────────────────────────────────────────────────────
_LEAD_HEAD = re.compile(
    r"^(?:(?:Больше|Выше|Дольше|Медленнее|Дороже|Теплее)\s+всего\s+—\s+(?P<a>.+?):\s"
    r"|(?P<b>.+?)\s+(?:впереди|лидирует|лидируют|—\s+первое\s+место|даёт|дают|приносит|приносят)\b"
    r"|(?P<c>[^—:]+?)\s+—\s+(?:\d|почти|больше|половин|треть|четверть|две\s+трети))")
_GROW = re.compile(r"раст(?:ёт|ет|ут)\s+быстрее\s+всех|быстрее\s+всех\s+раст(?:ёт|ет|ут)")
_ALL_N = re.compile(r"во\s+всех\s+(\d+)")
_K_OF_N = re.compile(r"(?:^|\s)в\s+(\d+)\s+из\s+(\d+)")
_BETTER = re.compile(r"лучше\s+всех|лучш(?:ий|ая|ее|ие)\b|лидиру|впереди", re.I)
# меньше — лучше: ошибки, брак, отток, задержки, время, ставки и цены, преступность, расход
_LOWER_BETTER = re.compile(r"ошиб|брак|дефект|отток|жалоб|задерж|опозда|просроч|врем[яе]|длительн|минут|пинг|"
                           r"ставк|цен[аы]|тариф|стоимост|преступн|дтп|авари|расход|потер|убыт|выброс|примес", re.I)


def _names(text: str) -> list[str]:
    """«Лицей № 2 и Гимназия № 1» → два имени; «Москва» → одно."""
    return [x.strip(" «»\"") for x in re.split(r"\s+и\s+|,\s*", text.strip()) if x.strip(" «»\"")]


def _keys_of(p: Optional[dict]) -> list[str]:
    return [str(k) for k in (p or {}).get("keys", [])]


def _same_name(a: str, b: str) -> bool:
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    return a == b


def claims_problem(text: str, ok: dict[str, HeadlineFact], prov: dict[str, dict], table: Table,
                   title: str = "", caption: bool = False) -> Optional[str]:
    """Что в утверждениях текста неправда по подтверждённым фактам (их происхождению): None — всё сходится. Кто
    впереди — по заголовку (подпись начинается с ориентиров и итогов, а не с лидера)."""
    t = " ".join((text or "").replace("\u00a0", " ").split())
    if not t:
        return None
    # кто впереди: названный первым — ключ подтверждённого лидера (наибольшее значение по строкам файла)
    lead = next((ok[k] for k in ("leader_share", "leader_value") if k in ok and _keys_of(prov.get(k))), None)
    m = None if caption else _LEAD_HEAD.match(t)
    if m is not None and m.group("c") is not None and "leader_share" not in ok:
        m = None  # «X — 31%…» — лидер доли; без доли «X — 5» — не утверждение о первенстве
    if lead is not None and m is not None:
        said = m.group("a") or m.group("b") or m.group("c") or ""
        keys = _keys_of(prov.get(lead.id))
        names = _names(said)
        if names and not any(_same_name(n, k) for n in names for k in keys) and not \
                any(_same_name(said, k) for k in keys):
            return f"впереди назван «{said}», а по строкам файла — «{keys[0]}»"
        if len(keys) > 1 and len(names) < len(keys):
            return f"ничья: у «{' и '.join(keys)}» одно значение, а назван один"
    # кто растёт быстрее всех: фраза стоит при том, кто растёт (не после последнего в списке)
    g = _GROW.search(t)
    if g is not None:
        gm = ok.get("growth_max")
        keys = _keys_of(prov.get("growth_max")) if gm is not None else []
        if not keys:
            return "«растёт быстрее всех» — нечем подтвердить: нет проверенного роста"
        subj = _grow_subject(t, g)
        if subj is None or not any(_same_name(subj, k) for k in keys):
            return f"«быстрее всех» стоит при «{subj or '?'}», а быстрее всех растёт «{keys[0]}»"
    # «во всех N» и «в K из N» — счёт, а не только числа
    counts = [f for f in ok.values() if f.kind == "count"]
    for m_ in _ALL_N.finditer(t):
        n = float(m_.group(1))
        pre = t[:m_.start()].lower()
        part = next((f for f in ok.values() if f.id in ("up", "moved", "below_target") ), None)
        tot = next((f for f in ok.values() if f.id in ("periods", "of")), None)
        if part is None or tot is None or abs(tot.value - n) > 1e-9:
            return f"«во всех {int(n)}» — нечем подтвердить"
        want = 0 if ("выше цели" in pre and part.id == "below_target") else n
        if part.id == "below_target" and "ниже цели" in pre:
            want = n
        if abs(part.value - want) > 1e-9:
            return f"«во всех {int(n)}» — по строкам файла {fmt_num(part.value)} из {fmt_num(n)}"
    for m_ in _K_OF_N.finditer(t):
        k, n = float(m_.group(1)), float(m_.group(2))
        if not any(abs(f.value - k) < 1e-9 for f in counts) or not any(abs(f.value - n) < 1e-9 for f in counts):
            return f"«в {int(k)} из {int(n)}» — нечем подтвердить"
    # «лучше», «впереди» — не у величины, где меньше — лучше
    if _BETTER.search(t):
        cols = [str(prov.get(f.id, {}).get("col_name") or "") for f in ok.values() if f.id in ("leader_value",
                                                                                             "leader_share")]
        if any(_LOWER_BETTER.search(c) for c in cols if c) or (not any(cols) and _LOWER_BETTER.search(title or "")):
            return "«впереди» или «лучше» у величины, где меньше — лучше"
    return None


def _grow_subject(t: str, g: "re.Match[str]") -> Optional[str]:
    """Кто «растёт быстрее всех» по строению фразы: «X впереди и растёт…» → X; «…, X растёт быстрее всех» → X;
    «…, быстрее всех растёт X» → X; «…, Y — 980 ₽ и растёт быстрее всех» → Y (ближайший перед)."""
    after = t[g.end():]
    if g.group(0).startswith("быстрее"):
        m = re.match(r"\s+([^,.;:]+)", after)
        return m.group(1).strip() if m else None
    before = t[:g.start()].rstrip()
    chunk = re.split(r",\s+(?=[^,]*$)", before)[-1] if "," in before else before
    chunk = re.sub(r"\s+и$", "", chunk).strip()
    m = re.match(r"^(.+?)(?:\s+впереди\b.*|\s+—\s+.*|\s+(?:даёт|дают|приносит|приносят)\b.*|:.*)?$", chunk)
    return m.group(1).strip() if m else chunk


def _bins_problem(table: Table, b: dict) -> Optional[str]:
    """Столбцы гистограммы — по сырым значениям: открытый «больше X» считает все значения больше X (и выбросы),
    «меньше X» — все меньше X, сумма столбцов — все значения."""
    raw = _Raw(table, b.get("skip", ()))
    xs = [v for v in (raw.num(i, b["col"], b.get("scale", 1.0)) for i in raw.rows) if v is not None]
    counts, labels = list(b["counts"]), list(b["labels"])
    if b.get("weighted"):
        return None  # частотная таблица: столбцы — сами строки файла
    if abs(sum(counts) - len(xs)) > 0:
        return f"на гистограмме {fmt_num(sum(counts))} значений, а в файле — {fmt_num(len(xs))}"
    if b.get("open_from") is not None:
        n = sum(1 for v in xs if v > b["open_from"] + 1e-9)
        if counts[-1] != n:
            return f"столбец «{labels[-1]}» — {fmt_num(counts[-1])}, а значений больше {fmt_num(b['open_from'])} — {n}"
    if b.get("open_to") is not None:
        n = sum(1 for v in xs if v < b["open_to"] - 1e-9)
        if counts[0] != n:
            return f"столбец «{labels[0]}» — {fmt_num(counts[0])}, а значений меньше {fmt_num(b['open_to'])} — {n}"
    return None
