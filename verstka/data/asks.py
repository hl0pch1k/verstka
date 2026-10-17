"""Вопросы брифа, на которые обычный вывод слайда не отвечает (F2, conv5): доля N крупнейших («какую долю перевозят пять
крупнейших маршрутов»), доля названных категорий («доля выработки астраханских станций»), колонка против колонки по
строкам («где платных заявлений меньше, чем платных мест», «у каких клубов новых больше, чем ушедших», «какие станции
выполнили план»), самый низкий или высокий период («в каком месяце загрузка сети была самой низкой»).

Каждый ответ — факты с происхождением (`prov`): `verify` пересчитывает их по сырым строкам, как любой другой вывод.
Слайд остаётся тем же (график сравнения или ряда) — меняются заголовок-вывод, подпись и факты: они о заданном вопросе.
None — данные на такой вопрос не отвечают (колонок нет, величина не складывается): тогда остаётся обычный вывод, а
цель получает видимую пометку (`verstka/data/intent.py`)."""

from __future__ import annotations

import re
from typing import Any, Optional

from verstka.data.aggregate import Data, is_other_label
from verstka.data.facts import FactSet, _as_share, _col_of, _pcat, _ptime, _skip
from verstka.data.words import count_words, fmt_pct, fmt_value, join_and, period_text, round_pct, upper_first

__all__ = ["ASKS", "answer_ask"]

ASKS = ("top_n", "share_of", "versus_lt", "versus_gt", "met", "period_min", "period_max", "position", "row_ratio")
_PLAN = re.compile(r"(?i)(?:^|[^а-яё])(?:план\w*|норматив\w*|цел[ьи]|target|plan)(?:[^а-яё]|$)")


def answer_ask(goal: Any, d: Data, task: str, fs: FactSet) -> Optional[tuple[str, Optional[str], FactSet]]:
    """(заголовок, подпись, факты) — ответ на вопрос цели `goal` (её `ask` — из `ASKS`), или None."""
    ask = getattr(goal, "ask", None) if goal is not None else None
    if ask not in ASKS:
        return None
    try:
        if ask == "top_n":
            return _top_n(goal, d, fs)
        if ask == "share_of":
            return _share_of(goal, d, fs)
        if ask in ("versus_lt", "versus_gt", "met"):
            return _versus(goal, d, fs, ask)
        if ask in ("period_min", "period_max"):
            return _period_extreme(d, fs, ask == "period_min")
        if ask == "position":
            return _position(goal, d, fs)
        if ask == "row_ratio":
            return _row_ratio(goal, d, fs)
    except Exception:  # noqa: BLE001 - a question the engine cannot answer keeps the slide's own conclusion
        return None
    return None


def _new(fs: FactSet) -> FactSet:
    out = FactSet()
    out.ctx = {k: v for k, v in fs.ctx.items() if k in ("plain", "labels", "unit_short")}
    out.ctx.setdefault("labels", [])
    return out


def _metric_name(m: Any) -> str:
    return re.sub(r"\s*,.*$", "", m.name).strip()


def _top_n(goal: Any, d: Data, fs: FactSet) -> Optional[tuple[str, Optional[str], FactSet]]:
    """«Какую долю дают пять крупнейших»: сумма N первых категорий от суммы всех."""
    m, cv = d.main, d.cats
    n = int(getattr(goal, "n", None) or 0)
    if m is None or cv is None or not (m.additive or m.stock) or n < 1:
        return None
    pairs = [(lab, v) for lab, v in zip(cv.labels, cv.values) if not is_other_label(lab) and not lab.startswith("Остальные")]
    total_n = cv.distinct or len(pairs)
    if n >= total_n or n > len(pairs):
        return None
    top = sorted(pairs, key=lambda x: -x[1])[:n]
    keys = [lab for lab, _ in top]
    out = _new(fs)
    prov = {**_as_share(_pcat(d, m, cv.dim, keys)), "tol": 0.51}
    tot = sum(float(m.values[i]) for i in d.rows_idx if m.values[i] is not None)
    part = sum(v for _, v in top)
    if not tot:
        return None
    share = part / tot * 100
    out.add("top_share", round_pct(share), "share", f"{n} крупнейших — {fmt_pct(share)}%", "%",
            f"Сумма «{m.name}» у {n} первых категорий от суммы всех.", prov=prov)
    out.add("top_n", n, "count", f"{n} крупнейших", None, "Сколько категорий спросил бриф.",
            prov={"op": "count", "what": "value", "value": n})
    out.add("top_of", total_n, "count", f"из {total_n}", None, "Сколько всего категорий.",
            prov={"op": "count", "what": "value", "value": total_n})
    names = (", ".join(keys[:3]) + " и другие") if n > 3 else join_and(keys)
    head = f"{n} крупнейших из {total_n} — {fmt_pct(share)}% суммы «{_metric_name(m)}»: {names}"
    cap = f"{upper_first(join_and(keys))}: всего {fmt_pct(share)}%."
    out.ctx["labels"] = list(out.ctx.get("labels", [])) + keys
    return head, cap, out


def _dim_of(d: Data, cats: list[str]) -> Optional[int]:
    """Колонка, в которой названные категории — значения (регион у станций, а не сама станция)."""
    want = {c.strip().lower() for c in cats}
    best = None
    for j in list(d.dims) + ([d.label] if d.label is not None else []):
        vals = {d.text(i, j).strip().lower() for i in d.rows_idx}
        if want <= vals and (best is None or len(vals) < len(best[1])):
            best = (j, vals)
    return best[0] if best else None


def _share_of(goal: Any, d: Data, fs: FactSet) -> Optional[tuple[str, Optional[str], FactSet]]:
    """«Какая доля выработки приходится на астраханские станции»: сумма строк названных категорий от суммы всех."""
    m = d.main
    cats = list(getattr(goal, "categories", None) or [])
    if m is None or not cats or not (m.additive or m.stock) or fs.get("named_share") is not None:
        return None  # (доля названной части — уже вывод слайда: «СБП — 23% оборота»)
    j = _dim_of(d, cats)
    if j is None:
        return None
    dim = d.cols[j].name
    out = _new(fs)
    prov = {**_as_share(_pcat(d, m, dim, cats)), "tol": 0.51}
    vals = {}
    for i in d.rows_idx:
        v = m.values[i]
        if v is None:
            continue
        k = d.text(i, j).strip()
        vals[k] = vals.get(k, 0.0) + float(v)
    tot = sum(vals.values())
    part = sum(v for k, v in vals.items() if k.lower() in {c.lower() for c in cats})
    if not tot:
        return None
    share = part / tot * 100
    out.add("named_share", round_pct(share), "share", f"{join_and(cats)} — {fmt_pct(share)}%", "%",
            f"Сумма «{m.name}» строк, где «{dim}» — {join_and(cats)}, от суммы всех строк.", prov=prov)
    out.add("named_part", round(part, 1) if abs(part) < 100 else round(part), "total",
            f"{join_and(cats)} — {fmt_value(part, m.unit_text)}", m.unit_text, "Их сумма.",
            prov={"op": "add", "parts": [{**_pcat(d, m, dim, [c]), "op": "cat"} for c in cats],
                  "tol": 0.051 if abs(part) < 100 else 0.51})
    out.add("named_total", round(tot, 1) if abs(tot) < 100 else round(tot), "total", f"Всего — {fmt_value(tot, m.unit_text)}",
            m.unit_text, "Сумма всех строк.", prov={"op": "colsum", "col": m.j, "skip": _skip(d), "scale": m.scale,
                                                    "tol": 0.051 if abs(tot) < 100 else 0.51})
    out.ctx["labels"] = list(out.ctx.get("labels", [])) + cats
    head = f"{join_and(cats)} — {fmt_pct(share)}% суммы «{_metric_name(m)}»"
    cap = f"{upper_first(join_and(cats))} — {fmt_value(part, m.unit_text)} из {fmt_value(tot, m.unit_text)}."
    return head, cap, out


def _position(goal: Any, d: Data, fs: FactSet) -> Optional[tuple[str, Optional[str], FactSet]]:
    """«Правда ли, что «Ночная» хуже остальных», «правда ли Новосибирск отстаёт от остальных городов»: где названная
    категория среди всех — кто выше и кто ниже её (значения — по тем же правилам, что у графика: сумма, среднее, с
    весом)."""
    m = d.main
    cats = list(getattr(goal, "categories", None) or [])
    if m is None or len(cats) != 1:
        return None
    j = _dim_of(d, cats)
    if j is None:
        return None
    cv = d.cat_view(m, top=1000, dim=j)
    if cv is None:
        return None
    pairs = [(lab, v) for lab, v in zip(cv.labels, cv.values) if not is_other_label(lab) and not lab.startswith("Остальные")]
    me = next(((lab, v) for lab, v in pairs if lab.strip().lower() == cats[0].strip().lower()), None)
    if me is None or len(pairs) < 3:
        return None
    lab0, v0 = me
    hi = [(a, b) for a, b in pairs if b > v0 + 1e-12 and a != lab0]
    lo = [(a, b) for a, b in pairs if b < v0 - 1e-12 and a != lab0]
    u = m.unit_text
    out = _new(fs)
    dim = cv.dim

    def fact(lab: str, v: float) -> None:
        out.add(f"pos_{len(out.facts)}", round(v, 2) if abs(v) < 100 else round(v), "total", f"{lab} — {fmt_value(v, u)}", u,
                f"«{m.name}» у «{lab}».", prov={**_pcat(d, m, dim, [lab]), "tol": 0.006 if abs(v) < 100 else 0.51})

    fact(lab0, v0)
    said = lambda xs: join_and([f"«{a}» ({fmt_value(b, u)})" for a, b in xs])  # noqa: E731
    if not hi:
        tail = "выше всех"
    elif not lo:
        tail = "ниже всех"
    elif len(lo) <= 2:
        tail = f"ниже — только {said(lo)}"
        for a, b in lo:
            fact(a, b)
    elif len(hi) <= 2:
        tail = f"выше — только {said(hi)}"
        for a, b in hi:
            fact(a, b)
    else:
        tail = f"выше — {len(hi)} из {len(pairs) - 1}, ниже — {len(lo)}"
        for fid, v in (("pos_hi", len(hi)), ("pos_of", len(pairs) - 1), ("pos_lo", len(lo))):
            out.add(fid, v, "count", str(v), None, "Счёт категорий.", prov={"op": "count", "what": "value", "value": v})
    out.ctx["labels"] = list(out.ctx.get("labels", [])) + [a for a, _ in pairs]
    head = f"{lab0} — {fmt_value(v0, u)}: {tail}"
    return head, None, out


def _row_ratio(goal: Any, d: Data, fs: FactSet) -> Optional[tuple[str, Optional[str], FactSet]]:
    """«Конверсия от отклика до оффера в IT и в продажах», «сколько дошли до выхода на работу из откликнувшихся»: строка
    B от строки A в каждой колонке-счёте (воронка по колонкам), а не сумма строк."""
    cats = list(getattr(goal, "categories", None) or [])
    lab = d.label
    if len(cats) != 2 or lab is None:
        return None
    rows = {d.text(i, lab).strip().lower(): i for i in d.rows_idx}
    ia, ib = rows.get(cats[0].strip().lower()), rows.get(cats[1].strip().lower())
    if ia is None or ib is None:
        return None
    col = getattr(goal, "column", None)
    ms = [m for m in d.measures if m.type != "percent" and (m.unit or "") != "%" and not m.change
          and (not col or m.name == col) and m.values[ia] is not None and m.values[ib] is not None]
    if not ms:
        return None
    va0, vb0 = ms[0].values[ia], ms[0].values[ib]
    if va0 < vb0:  # «из откликнувшихся дошли до выхода»: доля — меньшего от большего (база — первый этап)
        ia, ib = ib, ia
    a_lab, b_lab = d.text(ia, lab).strip(), d.text(ib, lab).strip()
    out = _new(fs)
    parts = []
    dim = d.cols[lab].name
    for m in ms[:3]:
        a, b = float(m.values[ia]), float(m.values[ib])
        if a <= 0:
            continue
        r = b / a * 100
        pa = {**_pcat(d, m, dim, [a_lab]), "op": "cat", "rank": None}
        pb = {**_pcat(d, m, dim, [b_lab]), "op": "cat", "rank": None}
        k = len(out.facts)
        # доля строки от строки той же колонки: `conv` пересчитывает «последний этап / первый × 100» по сырым ячейкам
        out.add(f"rr_{k}", round_pct(r), "share", f"{_metric_name(m)}: {fmt_pct(r)}%", "%",
                f"«{b_lab}» от «{a_lab}» в колонке «{m.name}».",
                prov={"op": "conv", "col": m.j, "first": ia, "last": ib, "tol": 0.051 if r < 9.95 else 0.51})
        out.add(f"rr_a_{k}", a, "total", f"{a_lab} — {fmt_value(a, m.unit_text)}", m.unit_text, "Первый этап.", prov=pa)
        out.add(f"rr_b_{k}", b, "total", f"{b_lab} — {fmt_value(b, m.unit_text)}", m.unit_text, "Последний этап.", prov=pb)
        parts.append((m, r, a, b))
    if not parts:
        return None
    out.ctx["labels"] = list(out.ctx.get("labels", [])) + [a_lab, b_lab]
    if len(parts) == 1:
        m, r, a, b = parts[0]
        head = f"До «{b_lab}» доходит {fmt_pct(r)}% от «{a_lab}»: {fmt_value(b, m.unit_text)} из {fmt_value(a, m.unit_text)}"
    else:
        head = f"От «{a_lab}» до «{b_lab}»: " + ", ".join(f"{_metric_name(m)} — {fmt_pct(r)}%" for m, r, _, _ in parts)
    cap = "; ".join(f"{_metric_name(m)}: {fmt_value(b, m.unit_text)} из {fmt_value(a, m.unit_text)}" for m, _, a, b in parts) + "."
    return head, cap, out


def _versus(goal: Any, d: Data, fs: FactSet, ask: str) -> Optional[tuple[str, Optional[str], FactSet]]:
    """Колонка против колонки по строкам: «где платных заявлений меньше, чем платных мест» (versus_lt), «у каких
    клубов новых больше, чем ушедших» (versus_gt), «какие станции выполнили план» (met: факт не ниже плана)."""
    a_name = getattr(goal, "column", None)
    b_name = getattr(goal, "versus", None)
    ma = d.measure(a_name) if a_name else d.main
    if ask == "met" and not b_name and ma is not None:
        b = next((x for x in d.measures if x is not ma and _PLAN.search(x.name)), None)
        b_name = b.name if b is not None else None
        if b is None:
            pf = d.plan_fact
            if pf is not None:
                b_name, ma = pf[0].name, pf[1]
    mb = d.measure(b_name) if b_name else None
    lab = d.label if d.label is not None else (d.dims[0] if d.dims else None)
    if ma is None or mb is None or ma is mb or lab is None:
        return None
    rows = [i for i in d.rows_idx if ma.values[i] is not None and mb.values[i] is not None]
    names = [d.text(i, lab).strip() for i in rows]
    if len(rows) < 2 or len(set(names)) != len(names):
        return None  # одна категория — несколько строк: сравнение по строкам — не о категориях
    if ask == "versus_lt":
        hit = [i for i in rows if ma.values[i] < mb.values[i]]
        prov = {"op": "rows_gt", "a": mb.j, "b": ma.j, "skip": _skip(d)}
    elif ask == "versus_gt":
        hit = [i for i in rows if ma.values[i] > mb.values[i]]
        prov = {"op": "rows_gt", "a": ma.j, "b": mb.j, "skip": _skip(d)}
    else:
        hit = [i for i in rows if ma.values[i] >= mb.values[i]]
        prov = {"op": "rows_gt", "a": ma.j, "b": mb.j, "skip": _skip(d), "ge": True}
    out = _new(fs)
    k, n = len(hit), len(rows)
    out.add("rows_hit", k, "count", f"{k} из {n}", None, f"Строк, где «{ma.name}» и «{mb.name}» — так, как спросил бриф.",
            prov=prov)
    out.add("rows_of", n, "count", f"из {n}", None, "Строк с обеими колонками.",
            prov={"op": "count", "what": "value", "value": n})
    who = [d.text(i, lab).strip() for i in hit]
    rest = [d.text(i, lab).strip() for i in rows if i not in hit]
    out.ctx["labels"] = list(out.ctx.get("labels", [])) + who + rest
    a_n, b_n = _metric_name(ma), _metric_name(mb)
    listed = (", ".join(who[:4]) + " и другие") if k > 4 else join_and(who)
    if ask == "met":
        plan_word = "План выполнили" if _PLAN.search(mb.name) else f"«{a_n}» не ниже «{b_n}» —"
        if not k:
            head = f"{plan_word} ни одна строка из {n}" if not _PLAN.search(mb.name) else f"План не выполнил никто из {n}"
        else:
            head = f"{plan_word} {k} из {n}: {listed}"
        cap = (f"Не выполнили — {join_and(rest[:4])}{' и другие' if len(rest) > 4 else ''}." if rest and _PLAN.search(mb.name)
               else (f"Ниже — {join_and(rest[:4])}." if rest else None))
        return head, cap, out
    word = "меньше" if ask == "versus_lt" else "больше"
    if not k:
        head = f"«{a_n}» {word}, чем «{b_n}», — ни у одной строки из {n}"
    else:
        head = f"«{a_n}» {word}, чем «{b_n}», — у {k} из {n}: {listed}"
    return head, None, out


def _period_extreme(d: Data, fs: FactSet, low: bool) -> Optional[tuple[str, Optional[str], FactSet]]:
    """«В каком месяце загрузка сети была самой низкой»: период ряда по всем строкам (сумма у потока, среднее — с весом
    — у уровня) с наименьшим (наибольшим) значением."""
    from verstka.data.verify import recompute

    tv = d.time
    m = d.main
    if tv is None or m is None or tv.points < 3:
        return None
    vals = []
    for p in tv.periods:
        pr = _ptime(d, tv, "at", to=p)
        v = recompute(d.table, pr)
        if v is not None:
            vals.append((p, float(v), pr))
    if len(vals) < 3:
        return None
    pick = min(vals, key=lambda x: x[1]) if low else max(vals, key=lambda x: x[1])
    other = max(vals, key=lambda x: x[1]) if low else min(vals, key=lambda x: x[1])
    ties = [x for x in vals if abs(x[1] - pick[1]) < 1e-9 and x[0] != pick[0]]
    if ties:
        return None
    u = m.unit_text
    out = _new(fs)
    for fid, (p, v, pr) in (("period_pick", pick), ("period_other", other)):
        r = round(v, 1) if abs(v) < 100 else round(v)
        out.add(fid, r, "min" if (fid == "period_pick") == low else "max", f"{period_text(p)} — {fmt_value(v, u)}", u,
                f"«{m.name}» за {period_text(p)} по всем строкам.", prov={**pr, "tol": 0.051 if abs(v) < 100 else 0.51})
    out.ctx["labels"] = list(out.ctx.get("labels", [])) + [period_text(p) for p, _, _ in vals]
    name = _metric_name(m)
    head = f"{name}: {'ниже' if low else 'выше'} всего — {period_text(pick[0])}, {fmt_value(pick[1], u)}"
    cap = f"{'Выше' if low else 'Ниже'} всего — {period_text(other[0])}: {fmt_value(other[1], u)}."
    return head, cap, out


def asks_words(ask: Optional[str], n: Optional[int] = None) -> str:
    return {"top_n": f"доля {count_words(int(n or 0), 'крупнейшей', 'крупнейших', 'крупнейших')}" if n else "доля крупнейших",
            "share_of": "доля названных категорий", "versus_lt": "колонка меньше другой", "versus_gt": "колонка больше другой",
            "met": "кто выполнил план", "period_min": "самый низкий период", "period_max": "самый высокий период"}.get(ask or "", "")
