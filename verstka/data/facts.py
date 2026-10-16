"""Факты для заголовка-вывода (описание решения §2.6): числа, посчитанные из подготовленных данных.

Изменение первое → последнее и год к году (%, п.п., «в N раз»), лидер и его доля, самый быстрый рост, доля топ-N,
медиана и перцентили («80% — не дольше 2 часов»), выбросы (ниже и выше обычных — каждые своими словами), пропущенные
периоды, связь (r). Каждый факт — `HeadlineFact` с числом, каким его пишет заголовок, и объяснением, откуда оно
(«Сентябрь 2026 к сентябрю 2025: 423 млн ₽ — на 23% больше. Посчитано по колонке «Выручка».»). Рядом — слова для
шаблона (`FactSet.ctx`: лидер, период, сущность, падежи, подписи категорий), чтобы заголовок (`headline.compose`) только
расставил их по-русски. Лидер — всегда по значению, а не по месту в списке (порядковые подписи «18–24», «25–34» идут как
в файле)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from verstka.data.aggregate import (
    NICE_MINUTES, TO_MINUTES, CatView, Data, KpiItem, Measure, TimeView, is_index, is_other_label,
)
from verstka.data.parse import is_total_label, quantity, split_unit
from verstka.data.units import _num as _num_cell
from verstka.data.words import (
    PERIOD_WORDS, Phrase, count_dat, count_words, duration_gen, duration_text, each_unit, file_title, fmt_num, fmt_pct,
    fmt_pct_any, fmt_signed, fmt_value, head_word, is_counter, is_event_name, is_participle, is_plural_value, join_and,
    lower_first,
    metric_phrase, period_acc, period_dat_full, period_dative, period_gen, period_in, period_text, phrase, round_pct,
    round_pct_any, times_word, upper_first,
)
from verstka.schemas.data import FactKind, HeadlineFact, TaskKind

__all__ = ["FactSet", "facts_for", "subject_of", "plain_headline"]


@dataclass
class FactSet:
    facts: list[HeadlineFact] = field(default_factory=list)
    ctx: dict[str, Any] = field(default_factory=dict)
    # откуда каждое число (колонка, сборка, отбор строк, периоды, база) — для самопроверки по сырым строкам (verify.py)
    prov: dict[str, dict] = field(default_factory=dict)

    def add(self, fid: str, value: float, kind: FactKind, text: str, unit: Optional[str] = None, explain: str = "",
            prov: Optional[dict] = None) -> None:
        # «1 840 шт..», «+0,6 п.п..» — точка сокращения и конца фразы одна
        text, explain = _one_dot(text), _one_dot(explain)
        self.facts.append(HeadlineFact(id=fid, text=text, value=float(value), unit=unit, kind=kind, explain=explain))
        if prov is not None:
            self.prov[fid] = prov

    def get(self, fid: str) -> Optional[HeadlineFact]:
        return next((f for f in self.facts if f.id == fid), None)


# ── происхождение чисел (для самопроверки, verify.py) ────────────────────────────────────────────────────────────
def _skip(d: Data) -> list[int]:
    """Строки, которых нет в данных: итог и ориентиры."""
    return sorted(set(d.totals) | set(d.benchmarks))


def _col_of(d: Data, name: Optional[str]) -> Optional[int]:
    return next((j for j, c in enumerate(d.cols) if c.name == name), None) if name else None


def _pcat(d: Data, m: Optional[Measure], dim: str, keys: list[str], rank: Optional[str] = None,
          exclude: tuple[str, ...] = (), named: Optional[str] = None) -> dict:
    """Значение категории: сумма у того, что складывается (и у остатка), среднее у уровня, число строк без метрики."""
    agg = "sum" if m is None or m.additive or m.stock else "mean"
    return {"op": "cat", "col": None if m is None else m.j, "by": _col_of(d, dim), "keys": keys, "agg": agg,
            "skip": _skip(d), "scale": m.scale if m is not None else 1.0, "rank": rank, "exclude": list(exclude),
            "named": named, "col_name": m.name if m is not None else None}


def _ptime(d: Data, tv: TimeView, mode: str, frm: Optional[str] = None, to: Optional[str] = None,
           kind: Optional[str] = None, col: Optional[Measure] = None, cat: Optional[str] = None,
           cols: Optional[list[Measure]] = None) -> dict:
    """Ряд по времени по сырым строкам: колонка времени → период частоты оси → сборка (как у графика)."""
    m = col if col is not None else tv.measure
    if tv.from_columns:
        js = list(tv.col_js)
        k = {f"{p}": i for i, p in enumerate(tv.periods)}
        out = {"op": "colseries", "cols": js, "agg": tv.how, "skip": _skip(d), "scale": tv.measure.scale,
               "mode": "at" if mode == "at" else mode, "kind": kind}
        if mode == "at":
            out["k"] = k.get(to or "", len(js) - 1)
        return out
    agg = tv.how if col is None or col is tv.measure else (col.how if not col.change else "mean")
    if tv.per_week and agg == "sum":
        agg = "mean"
    by = None
    if tv.dim and cat is None and (m.additive or m.stock):
        # длинный формат: итог по категориям — сумма (у остатка — последнее значение каждой категории, сложенное)
        agg, by = ("sum_last_by" if agg == "last" else "sum"), _col_of(d, tv.dim)
    return {"op": "series", "time": d.time_col, "freq": tv.freq, "week_src": tv.source_freq == "week",
            "col": m.j if m.j >= 0 else None, "cols": [x.j for x in cols] if cols else None, "agg": agg,
            "by": by, "cat": (_col_of(d, tv.dim), cat) if cat is not None else None, "skip": _skip(d),
            "scale": m.scale if m.j >= 0 else 1.0, "mode": mode, "from": frm, "to": to, "kind": kind}


def _one_dot(s: str) -> str:
    return re.sub(r"(?<!\.)\.\.(?!\.)", ".", s or "")


def _by(m: Measure) -> str:
    return f"Посчитано по колонке «{m.name}»."


_MASS_PL = {"продажи", "расходы", "доходы", "затраты", "средства", "деньги", "инвестиции", "поступления", "платежи"}


def subject_of(name: str, mtype: str = "number") -> tuple[str, str, Optional[Phrase]]:
    """Подлежащее для заголовка: «Выручка» (ж.), «NPS» (м.), «Клиентов» → «Число клиентов» (ср.)."""
    p = metric_phrase(name, mtype)
    if (is_counter(name) or (is_event_name(name) and mtype != "money")) and p is not None:
        return p.nom, p.gender, p
    return name, (p.gender if p else "m"), p


def _title_head(d: Data) -> Optional[Phrase]:
    """Главное слово названия датасета («Пациенты по отделениям 2025» → пациенты), без кодов и чисел в начале."""
    title = re.sub(r"^(?:[\w-]*\d[\w-]*\s+)+", "", file_title(d.profile.file, d.profile.sheet))
    head = head_word(title)
    if not head or head in ("данные", "таблица", "лист", "отчёт", "отчет", "итоги", "список", "выгрузка", "сводка",
                            "структура", "распределение", "состав", "динамика"):
        return None
    p = phrase(head)
    return p if p is not None and p.sure else None


def _subject_for(d: Data, m: Measure) -> tuple[str, str, Optional[Phrase]]:
    """Подлежащее заголовка. Безликое название колонки («Значение», «Сумма», «Всего», «Количество») — по названию
    датасета: «Урожайность», «Сумма операций», «Число пациентов»; иначе — как `subject_of`."""
    base = re.sub(r"\s*,.*$", "", m.name).strip()
    if _GENERIC.match(base) or is_total_label(base):
        tp = _title_head(d)
        if tp is not None:
            low = base.lower()
            if m.type == "money" and tp.gender != "pl" or low in ("значение", "величина", "показатель"):
                p = tp
            elif m.type == "money" or low in ("сумма", "объём", "объем"):
                p = phrase(f"Сумма {tp.low.gen_pl}") if tp.gender == "pl" else tp
            else:
                p = phrase(f"Число {tp.low.gen_pl}")
            if p is not None:
                return p.nom, p.gender, p
    return subject_of(m.name, m.type)


def _metric_title(m: Measure) -> str:
    """Название метрики для темы и объяснений: «Выручка», «Клиентов» → «Число клиентов»; без единицы («, млн ₽»)."""
    return re.sub(r"\s*,[^,]*$", "", subject_of(m.name, m.type)[0]).strip() or m.name


def plain_headline(task: TaskKind, d: Data) -> str:
    """Заголовок-описание (тема, не вывод): «Выручка по месяцам», «Выручка по регионам», «Список клиентов»."""
    m = d.main
    if task == "dynamics" and d.time is not None and len(d.time.series) >= 2 and not d.time.dim:
        return file_title(d.profile.file, d.profile.sheet)  # несколько рядов — тема по файлу, а не по первому ряду
    if task == "dynamics" and d.time is not None and d.time.from_columns:
        m = d.time.measure  # ось из колонок-периодов: ряд назван по датасету («Выручка»)
    if task == "dynamics" and m is not None and d.time is not None:
        by = {"month": "месяцам", "quarter": "кварталам", "year": "годам", "week": "неделям", "day": "дням",
              "hour": "часам"}.get(d.time.freq)
        if by:
            return f"{_metric_title(m)} по {by}"
    if task == "comparison" and m is not None and d.cats is not None:
        p = phrase(d.cats.dim)
        if p is not None and p.sure:
            return f"{_metric_title(m)} по {p.low.dat_pl}"
    if task == "reference" and d.entity:
        p = phrase(d.entity)
        if p is not None and p.sure:
            return f"Список {p.low.gen_pl}"
    return file_title(d.profile.file, d.profile.sheet)


def facts_for(task: TaskKind, d: Data) -> FactSet:
    fs = {
        "dynamics": _dynamics, "comparison": _comparison, "shares": _shares, "distribution": _distribution,
        "reference": _reference, "kpi": _kpi, "relationship": _relationship,
    }[task](d)
    fs.ctx.setdefault("plain", plain_headline(task, d))
    fs.ctx.setdefault("labels", [])
    return fs


# ── динамика ──────────────────────────────────────────────────────────────────────────────────────────────────────────
# сдвиг «год назад» по частоте; у часов его нет — сравнение «год к году» для них бессмысленно
_LAG = {"month": 12, "quarter": 4, "week": 52, "year": 1, "day": 365}


def _yoy_when(freq: str, iso: str) -> str:
    """Как назвать «год к году» в заголовке: «к сентябрю», «к III кварталу», иначе «за год»."""
    if freq in ("month", "quarter"):
        return period_dative(iso) or "за год"
    return "за год"


def _series_values(tv: TimeView) -> list[Optional[float]]:
    if not tv.dim:
        return tv.main.values
    if tv.measure.additive:
        out = []
        for i in range(tv.points):
            xs = [s.values[i] for s in tv.series if s.values[i] is not None]
            out.append(float(sum(xs)) if xs else None)
        return out
    return tv.main.values


def _past_end(gender: str, grow: bool) -> str:
    if grow:
        return {"m": "", "f": "ла", "n": "ло", "pl": "ли"}[gender]
    return {"m": "ся", "f": "ась", "n": "ось", "pl": "ись"}[gender]


def _short(parts: list[str], limit: int = 140) -> Optional[str]:
    """Подпись — 1–2 строки: предложения по порядку, пока помещаются в ~140 знаков (первое — всегда)."""
    out = ""
    for p in parts:
        if not p:
            continue
        nxt = (out + " " + p).strip()
        if out and len(nxt) > limit:
            break
        out = nxt
    out = re.sub(r"(?<!\.)\.\.(?!\.)", ".", out)  # «чел..» → «чел.»
    return out or None


def _range_text(pf: str, pl: str) -> str:
    """«С января 2025 по сентябрь 2026», «С 2005 по 2025 год»."""
    if re.fullmatch(r"\d{4}", pf) and re.fullmatch(r"\d{4}", pl):
        return f"С {pf} по {pl} год"
    return f"С {period_gen(pf)} по {period_acc(pl)}"


def _whole_period(tv: TimeView, ratio: float, span: int) -> bool:
    """Длинный ряд: вывод — изменение за весь период, а не последний шаг. Годы — всегда (их «год к году» и есть
    последний шаг); месяцы и кварталы — если за период величина выросла хотя бы втрое за 3 года и больше."""
    if tv.freq == "year" and span >= 4:
        return True
    years = {"month": span / 12, "quarter": span / 4, "week": span / 52, "day": span / 365}.get(tv.freq, 0)
    return (ratio >= 3 or (ratio > 0 and ratio <= 1 / 3)) and years >= 3


def _series_change(values: list[Optional[float]]) -> Optional[tuple[int, int, float, float]]:
    idx = [i for i, v in enumerate(values) if v is not None]
    if len(idx) < 2:
        return None
    return idx[0], idx[-1], float(values[idx[0]]), float(values[idx[-1]])  # type: ignore[arg-type]


def _dynamics(d: Data) -> FactSet:
    fs = FactSet()
    tv = d.time
    m = d.main
    if tv is None:
        return fs
    if tv.from_columns:
        m = tv.measure  # ось из колонок-периодов: ряд — сумма по строкам, названный по датасету
    if len(tv.series) >= 2 and not tv.dim and d.composition:
        # части одного целого по времени: вывод — про целое (итог или сумма частей) и самую подвижную часть
        if _dynamics_composition(d, tv, fs):
            return fs
    if len(tv.series) >= 2 and not tv.dim and not d.composition:
        multi = _dynamics_series(d, tv, fs)
        if multi:
            return fs
    if tv.dim and m is not None and not (m.additive or m.stock):
        # длинный формат и уровень (средний чек по регионам): одна категория — не вся метрика; факты по категориям
        if _dynamics_dim_level(d, tv, fs):
            return fs
    vals = _series_values(tv)
    idx = [i for i, v in enumerate(vals) if v is not None]
    m = tv.measure if m is None else m
    if tv.freq == "hour" and len(idx) >= 24 and _dynamics_hourly(d, tv, vals, idx, fs):
        return fs
    subj, gender, ph = _subject_for(d, m) if tv.measure.j != -1 else subject_of("Число строк", m.type)
    subj = re.sub(r"\s*,[^,]*$", "", subj).strip() or subj
    pw = PERIOD_WORDS.get(tv.freq, PERIOD_WORDS["irregular"])
    unit = m.unit_text if tv.measure.j != -1 else None
    # пункты — только у процентов и безразмерных индексов (NPS, балл); у денег и счёта изменение — в процентах
    level = m.type == "percent" or (not unit and is_index(m.name))
    fs.ctx.update(subject=subj, gender=gender, metric=ph or phrase("Значение"), freq=tv.freq, unit_short=unit,
                  level=level, labels=[subj])
    if not idx:
        return fs
    F, L = idx[0], idx[-1]
    first, last = float(vals[F]), float(vals[L])  # type: ignore[arg-type]
    pl, pf = tv.periods[L], tv.periods[F]
    hi = max(idx, key=lambda i: (vals[i], i))
    lo = min(idx, key=lambda i: (vals[i], -i))
    fs.add("last", round(last, 2) if abs(last) < 100 else round(last), "max" if hi == L else "total",
           f"{period_text(pl)}: {fmt_value(last, unit)}", unit, f"Последнее значение — {period_text(pl)}. {_by(m)}",
           prov=_ptime(d, tv, "at", to=pl))
    fs.add("first", round(first, 2) if abs(first) < 100 else round(first), "total",
           f"{period_text(pf)}: {fmt_value(first, unit)}", unit, f"Первое значение — {period_text(pf)}. {_by(m)}",
           prov=_ptime(d, tv, "at", to=pf))
    fs.add("max", vals[hi], "max", f"Максимум — {fmt_value(vals[hi], unit)} ({period_text(tv.periods[hi])})", unit,
           f"Наибольшее значение ряда. {_by(m)}", prov=_ptime(d, tv, "max", frm=pf, to=pl))
    fs.add("min", vals[lo], "min", f"Минимум — {fmt_value(vals[lo], unit)} ({period_text(tv.periods[lo])})", unit,
           f"Наименьшее значение ряда. {_by(m)}", prov=_ptime(d, tv, "min", frm=pf, to=pl))
    _time_structure(d, tv, fs)
    vmin, vmax = float(vals[lo]), float(vals[hi])  # type: ignore[arg-type]
    # «держится» — только если весь ряд в узкой полосе, а не потому, что первое значение равно последнему
    fs.ctx["flat"] = (vmax - vmin) <= 0.02 * max(abs(vmax), abs(vmin), 1e-9)
    if not m.additive and F < hi < L and vmax > 0 and min(first, last) > 0 and vmax >= 1.5 * max(first, last):
        # уровень (вода, температура): пик внутри ряда в полтора раза выше краёв — главное, его и называют
        # период — подписью оси графика («нед. 18, 2025»): его цифры — имя периода, а не число вывода
        fs.ctx["peak"] = ("пик", vmax, tv.labels[hi])
        fs.ctx["labels"].append(tv.labels[hi])
    elif not m.additive and F < lo < L and vmin > 0 and vmin <= min(first, last) / 1.5:
        fs.ctx["peak"] = ("минимум", vmin, tv.labels[lo])
        fs.ctx["labels"].append(tv.labels[lo])
    missing = tv.missing
    if missing:
        names = ", ".join(period_text(p) for p in missing[:4]) + (" …" if len(missing) > 4 else "")
        fs.add("gaps", len(missing), "gap", f"Нет данных: {names}", None,
               f"{upper_first(count_words(len(missing), pw[0], pw[1], pw[2]))} без значения: {names}. "
               f"На графике — разрывы, а не ноль.", prov=_ptime(d, tv, "missing", frm=tv.periods[0], to=tv.periods[-1]))
    lag = _LAG.get(tv.freq)
    base_i = None
    yoy = False
    span = L - F
    ratio_all = last / first if first > 0 and last >= 0 else 0.0
    if lag and L - lag >= F and vals[L - lag] is not None and tv.freq != "irregular" \
            and not _whole_period(tv, ratio_all, span):
        base_i, yoy = L - lag, True
    elif L > F:
        base_i = F
    caption: list[str] = []
    if base_i is not None:
        base = float(vals[base_i])  # type: ignore[arg-type]
        pb = tv.periods[base_i]
        if level:
            delta = last - base
            du = "п.п." if m.type == "percent" else "п."
            fs.ctx["delta"] = delta
            fs.add("change", round(abs(delta), 1), "change", f"{fmt_signed(delta, du)} к {period_dat_full(pb)}", du,
                   f"{upper_first(period_text(pl))} к {period_dat_full(pb)}: {fmt_value(last, unit)} против "
                   f"{fmt_value(base, unit)} — {fmt_signed(delta, du)}. {_by(m)}",
                   prov={**_ptime(d, tv, "change", frm=pb, to=pl, kind="abs"), "tol": 0.051})
            fs.add("delta_all", round(abs(last - first), 1), "change", f"{fmt_signed(last - first, du)} за период", du,
                   f"{upper_first(period_text(pf))} → {period_text(pl)}.",
                   prov={**_ptime(d, tv, "change", frm=pf, to=pl, kind="abs"), "tol": 0.051})
            fs.add("span_all", L - F, "count", count_words(L - F, pw[0], pw[1], pw[2]), None,
                   f"От {period_gen(pf)} до {period_gen(pl)}.", prov=_ptime(d, tv, "span", frm=pf, to=pl))
            caption.append(
                f"{subj}: {period_text(pf)} — {fmt_value(first, unit)}, {period_text(pl)} — {fmt_value(last, unit)} "
                f"({fmt_signed(last - first, du)} за {count_words(L - F, pw[0], pw[1], pw[2])}).")
        elif not (base > 0 and last >= 0) or _gauge(m, unit):
            # убыток, ноль в начале — проценты не считаются; уровень по шкале с произвольным нулём (вода в см,
            # температура) — тоже: изменение в единицах метрики
            delta = last - base
            fs.ctx.update(delta=delta, abs_change=True)
            fs.add("change", abs(delta) if abs(delta) >= 100 else round(abs(delta), 2), "change",
                   f"{fmt_signed(delta, unit or '')} к {period_dat_full(pb)}", unit,
                   f"{upper_first(period_text(pl))} к {period_dat_full(pb)}: {fmt_value(last, unit)} против "
                   f"{fmt_value(base, unit)}. {_by(m)}", prov=_ptime(d, tv, "change", frm=pb, to=pl, kind="abs"))
            sp = L - base_i
            fs.ctx["when"] = _yoy_when(tv.freq, pl) if yoy else (
                f"за {count_words(sp, pw[0], pw[1], pw[2])}" if tv.freq != "irregular" else "за период")
            if not yoy:
                fs.add("span", sp, "count", count_words(sp, pw[0], pw[1], pw[2]), None,
                       f"От {period_gen(pf)} до {period_gen(pl)}.", prov=_ptime(d, tv, "span", frm=pb, to=pl))
            caption.append(f"{_range_text(pf, pl)}: {fmt_value(first, unit)} → {fmt_value(last, unit)}.")
        else:
            pct = (last / base - 1) * 100
            fs.ctx["delta"] = pct
            more = "больше" if pct >= 0 else "меньше"
            fs.add("change", round_pct(abs(pct)), "change",
                   f"{fmt_signed(round_pct(pct), '%')} {'год к году' if yoy else 'за период'}", "%",
                   f"{upper_first(period_text(pl))} к {period_dat_full(pb)}: {fmt_value(last, unit)} — на "
                   f"{fmt_pct(abs(pct))}% {more}. {_by(m)}", prov=_ptime(d, tv, "change", frm=pb, to=pl, kind="pct"))
            fs.add("base", round(base, 2) if abs(base) < 100 else round(base), "total",
                   f"{period_text(pb)}: {fmt_value(base, unit)}", unit, f"База сравнения — {period_text(pb)}.",
                   prov=_ptime(d, tv, "at", to=pb))
            ratio = last / base
            if ratio >= 2:
                r = round(ratio, 1)
                fs.add("ratio", r, "change", f"в {fmt_num(r, 1)} {times_word(r)}", "раз",
                       f"{fmt_value(last, unit)} против {fmt_value(base, unit)}. {_by(m)}",
                       prov=_ptime(d, tv, "change", frm=pb, to=pl, kind="ratio"))
            if yoy:
                when = _yoy_when(tv.freq, pl)
            else:
                when = f"за {count_words(span, pw[0], pw[1], pw[2])}" if tv.freq != "irregular" else "за период"
                fs.add("span", span, "count", f"{count_words(span, pw[0], pw[1], pw[2])}", None,
                       f"От {period_gen(pf)} до {period_gen(pl)}.", prov=_ptime(d, tv, "span", frm=pf, to=pl))
            fs.ctx["when"] = when
            if yoy:
                # год к году — в подписи прямо: какие периоды сравнены
                caption.append(f"{upper_first(period_text(pl))} к {period_dat_full(pb)}: {fmt_value(last, unit)} против "
                               f"{fmt_value(base, unit)}.")
            if abs(last - first) < 1e-9:
                caption.append(f"{_range_text(pf, pl)} {lower_first(subj)} держится на уровне {fmt_value(last, unit)}.")
            else:
                caption.append(
                    f"{_range_text(pf, pl)} {lower_first(subj)} "
                    f"{'вырос' if last > first else 'снизил'}{_past_end(gender, last > first)} "
                    f"с {fmt_value(first, unit, 'gen')} до {fmt_value(last, unit, 'gen')}.")
    if missing:
        caption.append(
            f"За {join_and([period_text(p) for p in missing[:3]])}{' и другие' if len(missing) > 3 else ''} данных нет — "
            f"на графике разрывы, а не ноль.")
    if tv.resampled and tv.note:
        caption.append(upper_first(tv.note) + ".")
    if tv.per_week:
        # недели в месяцы: на графике и в выводе — среднее за неделю, и это сказано первым
        caption.insert(0, f"{PERIOD_WORDS[tv.freq][5]} — в среднем за неделю.")
    fs.ctx["caption"] = _short(caption)
    return fs


def _time_structure(d: Data, tv: TimeView, fs: FactSet) -> None:
    """Имена периодов и строки о сборке ряда («по месяцам: 365 дней → 12 месяцев», «январь 2025 — 4 из 31 дня») —
    подписи, а не числа вывода: для проверки подписи по строкам файла."""
    names: list[str] = list(tv.labels)
    for p in tv.periods:
        names += [period_text(p), period_gen(p), period_acc(p), period_dat_full(p), period_in(p)]
        dv = period_dative(p)
        if dv:
            names.append(dv)
    fs.ctx["period_labels"] = names
    fs.ctx["structure"] = [x for x in [tv.note, upper_first(tv.note or "")] + list(tv.partial_txt) if x]


def _mid(name: str) -> str:
    """Название внутри фразы: нарицательное — со строчной («план», «поступления»), аббревиатура и латиница — как есть."""
    p = phrase(name)
    return lower_first(name) if p is not None and p.sure else name


def _whole_subject(d: Data, tm: Optional[Measure], mtype: str) -> tuple[str, str, Optional[Phrase]]:
    """Подлежащее для целого: колонка-итог со своим названием — она; безликое «Всего» или итога нет — по названию
    датасета («Число пациентов», «Выручка», «Сумма расходов»); иначе «Сумма частей»."""
    if tm is not None and not (_GENERIC.match(re.sub(r"\s*,.*$", "", tm.name).strip()) or is_total_label(tm.name)):
        return subject_of(tm.name, tm.type)
    tp = _title_head(d)
    if tp is not None:
        if mtype == "money":
            p = tp if tp.gender != "pl" or tp.low.nom in ("расходы", "доходы", "продажи", "затраты", "поступления") \
                else phrase(f"Сумма {tp.low.gen_pl}")
        else:
            p = phrase(f"Число {tp.low.gen_pl}") if tp.gender == "pl" else tp
        if p is not None:
            return p.nom, p.gender, p
    return "Сумма частей", "f", phrase("Сумма частей")


def _dynamics_composition(d: Data, tv: TimeView, fs: FactSet) -> bool:
    """Части целого по времени (пациенты по отделениям, «Всего»): изменение целого — по колонке-итогу или сумме частей,
    и часть, которая изменилась сильнее всех, а не первая часть («Терапия выросла» — неверный вывод о целом)."""
    pw = PERIOD_WORDS.get(tv.freq, PERIOD_WORDS["irregular"])
    tm = d.total_metric
    tot: list[Optional[float]] = []
    tview = d.time_view(tm) if tm is not None else None
    if tview is not None and tview.periods == tv.periods:
        tot = list(tview.main.values)
    else:
        for i in range(tv.points):
            xs = [s_.values[i] for s_ in tv.series]
            tot.append(float(sum(x for x in xs if x is not None)) if all(x is not None for x in xs) else None)
    ch = _series_change(tot)
    if ch is None:
        return False
    F, L, first, last = ch
    subj, gender, ph = _whole_subject(d, tm, tv.measure.type)
    unit = tv.measure.unit_text
    span = L - F
    when = f"за {count_words(span, pw[0], pw[1], pw[2])}" if tv.freq != "irregular" else "за период"
    moves = []
    by_name = {d.series_names.get(x.name, x.name): x for x in d.parallel}
    for sv in tv.series:
        c = _series_change(sv.values)
        if c is not None and c[2] > 0:
            moves.append((sv.name, (c[3] / c[2] - 1) * 100, c[2], c[3], c[0], c[1], by_name.get(sv.name)))
    whole = dict(col=tm) if tm is not None else dict(cols=list(d.parallel))
    _time_structure(d, tv, fs)
    labels = [subj] + [x[0] for x in moves]
    fs.ctx.update(comp_time=True, subject=subj, gender=gender, metric=ph, unit_short=unit, when=when, labels=labels)
    if first > 0:
        pct = (last / first - 1) * 100
        fs.ctx["delta"] = pct
        fs.add("change", round_pct(abs(pct)), "change", f"{subj}: {fmt_signed(round_pct(pct), '%')}", "%",
               f"{subj}: {period_text(tv.periods[F])} — {fmt_value(first, unit)}, {period_text(tv.periods[L])} — "
               f"{fmt_value(last, unit)}.",
               prov=_ptime(d, tv, "change", frm=tv.periods[F], to=tv.periods[L], kind="pct", **whole))
    fs.add("last", last, "total", f"{period_text(tv.periods[L])}: {fmt_value(last, unit)}", unit,
           f"{subj} за {period_text(tv.periods[L])}.", prov=_ptime(d, tv, "at", to=tv.periods[L], **whole))
    fs.add("first", first, "total", f"{period_text(tv.periods[F])}: {fmt_value(first, unit)}", unit,
           f"{subj} за {period_text(tv.periods[F])}.", prov=_ptime(d, tv, "at", to=tv.periods[F], **whole))
    fs.add("span", span, "count", count_words(span, pw[0], pw[1], pw[2]), None,
           f"От {period_gen(tv.periods[F])} до {period_gen(tv.periods[L])}.",
           prov=_ptime(d, tv, "span", frm=tv.periods[F], to=tv.periods[L]))
    cap = [f"{_range_text(tv.periods[F], tv.periods[L])} {lower_first(subj)} — с {fmt_value(first, unit, 'gen')} до "
           f"{fmt_value(last, unit, 'gen')}."]
    if moves:
        nm, mp, a, b, mf, ml, mm = max(moves, key=lambda t: (abs(t[1]), t[0]))
        fs.ctx.update(mover=nm, mover_pct=mp)
        fs.add("mover", round_pct(abs(mp)), "change", f"{nm}: {fmt_signed(round_pct(mp), '%')}", "%",
               f"{nm}: {fmt_value(a, unit)} → {fmt_value(b, unit)} — сильнее всех частей.",
               prov=_ptime(d, tv, "change", frm=tv.periods[mf], to=tv.periods[ml], kind="pct", col=mm)
               if mm is not None else None)
        cap.append(f"{nm}: с {fmt_value(a, unit, 'gen')} до {fmt_value(b, unit, 'gen')} — сильнее всех частей.")
    fs.ctx["caption"] = _short(cap)
    return True


_GAUGE_UNITS = {"см", "мм", "м", "°c", "°с", "°f", "°", "градусов", "град."}


def _gauge(m: Measure, unit: Optional[str]) -> bool:
    """Уровень по шкале с произвольным нулём (уровень воды в см, температура): изменение — в единицах, а не в %."""
    return not m.additive and (unit or "").strip().lower() in _GAUGE_UNITS


def _dynamics_hourly(d: Data, tv: TimeView, vals: list[Optional[float]], idx: list[int], fs: FactSet) -> bool:
    """Почасовой ряд: суточный цикл, а не «первый час против последнего» — пик и среднее за час."""
    m = tv.measure
    unit = m.unit_text
    subj, gender, ph = subject_of(m.name, m.type)
    hi = max(idx, key=lambda i: (vals[i], -i))
    mean = sum(vals[i] for i in idx) / len(idx)  # type: ignore[misc]
    when = period_text(tv.periods[hi])
    fs.ctx.update(hourly=True, subject=subj, gender=gender, metric=ph, unit_short=unit, peak_when=when,
                  labels=[subj, when])
    rng = dict(frm=tv.periods[idx[0]], to=tv.periods[idx[-1]])
    _time_structure(d, tv, fs)
    fs.add("max", vals[hi], "max", f"Пик — {fmt_value(vals[hi], unit)} ({when})", unit, f"Наибольшее значение. {_by(m)}",
           prov=_ptime(d, tv, "max", **rng))
    fs.add("mean", round(mean, 1) if abs(mean) < 100 else round(mean), "median", f"В среднем — {fmt_value(mean, unit)}",
           unit, f"Среднее за час по {count_words(len(idx), 'часу', 'часам', 'часам')}. {_by(m)}",
           prov=_ptime(d, tv, "mean", **rng))
    fs.ctx["caption"] = _short([f"Пик — {when}.", f"{_range_text(tv.periods[idx[0]], tv.periods[idx[-1]])}."])
    return True


def _dynamics_dim_level(d: Data, tv: TimeView, fs: FactSet) -> bool:
    """Уровень по категориям (средний чек по регионам): сколько категорий выросло, у кого выше всех. «Остальные N» —
    среднее по ним, в счёт не идут."""
    m = tv.measure
    unit = m.unit_text
    # все категории, и те, что на графике собраны в «Остальные»
    moves = [(nm, a, b) for nm, (a, b) in tv.cat_moves.items()]
    if len(moves) < 2:
        return False
    up = sum(1 for _, a, b in moves if b > a)
    down = sum(1 for _, a, b in moves if b < a)
    lead = max(moves, key=lambda t: (t[2], t[0]))
    subj, gender, ph = _subject_for(d, m)
    subj = re.sub(r"\s*,[^,]*$", "", subj).strip() or subj
    dp = phrase(tv.dim)
    forms = (dp.low.gen, dp.low.gen_pl) if dp is not None and dp.sure else ("категории", "категорий")
    fs.ctx.update(dim_level=True, subject=subj, gender=gender, metric=ph, unit_short=unit, leader=lead[0],
                  labels=[x[0] for x in moves], dim_forms=forms, up=up >= down)
    shown = len(moves)
    mv = {"op": "moved", "time": d.time_col, "freq": tv.freq, "week_src": tv.source_freq == "week", "col": m.j,
          "by": _col_of(d, tv.dim), "agg": "mean" if m.change else tv.how, "skip": _skip(d), "scale": m.scale}
    _time_structure(d, tv, fs)
    fs.add("moved", up if up >= down else down, "count", f"{up if up >= down else down} из {shown}", None,
           f"Рост у {up}, снижение у {down} из {shown} (первое значение → последнее по каждой категории).",
           prov={**mv, "what": "moved"})
    fs.add("of", shown, "count", f"{shown} категорий", None, "Категорий с рядом на графике.", prov={**mv, "what": "of"})
    fs.add("leader_value", lead[2], "leader", f"{lead[0]} — {fmt_value(lead[2], unit)}", unit,
           f"Самое высокое последнее значение — {lead[0]}. {_by(m)}", prov={**mv, "what": "leader"})
    fs.add("up", up, "count", f"Рост — {up}", None, "Категорий, где последнее значение выше первого.",
           prov={**mv, "what": "up"})
    fs.add("down", down, "count", f"Снижение — {down}", None, "Категорий, где последнее значение ниже первого.",
           prov={**mv, "what": "down"})
    cap = [f"Первое значение против последнего: рост — {up}, снижение — {down} из {shown}."]
    if tv.others:
        fs.add("others", tv.others, "count", f"Остальные {tv.others}", None, "Категорий одной линией на графике.",
               prov={"op": "count", "what": "groups", "by": _col_of(d, tv.dim), "skip": _skip(d),
                     "minus": len(tv.series) - 1})
        cap.append(f"На графике остальные {tv.others} — одной линией, средним.")
    fs.ctx["caption"] = _short(cap)
    return True


def _dynamics_series(d: Data, tv: TimeView, fs: FactSet) -> bool:
    """Несколько рядов одного рода (Scopus и РИНЦ): у каждого — изменение за весь период; заголовок — оба ряда."""
    pw = PERIOD_WORDS.get(tv.freq, PERIOD_WORDS["irregular"])
    items = []
    for k, sv in enumerate(tv.series[:3]):
        ch = _series_change(sv.values)
        if ch is None:
            continue
        F, L, first, last = ch
        items.append((sv, F, L, first, last))
    if len(items) < 2:
        return False
    span = max(L for _, _, L, _, _ in items) - min(F for _, F, _, _, _ in items)
    unit = tv.measure.unit_text
    names = []
    for k, (sv, F, L, first, last) in enumerate(items):
        name = sv.name
        names.append(name)
        mm = next((x for x in d.parallel if d.series_names.get(x.name, x.name) == name), tv.measure)
        if mm.type == "percent":
            # проценты меняются в п.п.: «удержание выросло на 5 п.п.»
            fs.add(f"series_{k}", round(abs(last - first), 1), "change", f"{name}: {fmt_signed(last - first, 'п.п.')}",
                   "п.п.", f"{name}: {fmt_value(first, unit)} → {fmt_value(last, unit)}.",
                   prov={**_ptime(d, tv, "change", frm=tv.periods[F], to=tv.periods[L], kind="abs", col=mm),
                         "tol": 0.051})
            fs.ctx[f"s{k}"] = ("pp", last - first)
        elif first > 0 and last >= 0:
            ratio = last / first
            if ratio >= 2 or ratio <= 0.5:
                r = round(ratio if ratio >= 1 else 1 / ratio, 1)
                fs.add(f"series_{k}", r, "change", f"{name}: в {fmt_num(r, 1)} {times_word(r)}", "раз",
                       f"{name}: {fmt_value(first, unit)} → {fmt_value(last, unit)} ({period_text(tv.periods[F])} — "
                       f"{period_text(tv.periods[L])}).",
                       prov=_ptime(d, tv, "change", frm=tv.periods[F], to=tv.periods[L], kind="ratio", col=mm))
                fs.ctx[f"s{k}"] = ("ratio", ratio)
            else:
                pct = (last / first - 1) * 100
                fs.add(f"series_{k}", round_pct(abs(pct)), "change", f"{name}: {fmt_signed(round_pct(pct), '%')}", "%",
                       f"{name}: {fmt_value(first, unit)} → {fmt_value(last, unit)}.",
                       prov=_ptime(d, tv, "change", frm=tv.periods[F], to=tv.periods[L], kind="pct", col=mm))
                fs.ctx[f"s{k}"] = ("pct", pct)
        else:
            fs.add(f"series_{k}", abs(last - first), "change", f"{name}: {fmt_signed(last - first, unit or '')}", unit,
                   f"{name}: {fmt_value(first, unit)} → {fmt_value(last, unit)}.",
                   prov=_ptime(d, tv, "change", frm=tv.periods[F], to=tv.periods[L], kind="abs", col=mm))
            fs.ctx[f"s{k}"] = ("abs", last - first)
        fs.add(f"first_of_{k}", first, "total", f"{name}: {fmt_value(first, unit)}", unit, f"{name} в начале.",
               prov=_ptime(d, tv, "at", to=tv.periods[F], col=mm))
        fs.add(f"last_of_{k}", last, "total", f"{name}: {fmt_value(last, unit)}", unit, f"{name} в конце.",
               prov=_ptime(d, tv, "at", to=tv.periods[L], col=mm))
        hi = max((i for i, v in enumerate(sv.values) if v is not None), key=lambda i: sv.values[i])
        if F < hi < L and sv.values[hi] is not None and last < sv.values[hi]:  # пик внутри ряда, а не на краю
            fs.ctx.setdefault("peaks", []).append((name, sv.values[hi], tv.periods[hi]))
            fs.add(f"peak_of_{k}", sv.values[hi], "max", f"{name}: максимум {fmt_value(sv.values[hi], unit)}", unit,
                   f"Наибольшее значение ряда «{name}».",
                   prov=_ptime(d, tv, "max", frm=tv.periods[F], to=tv.periods[L], col=mm))
    f0 = min(F for _, F, _, _, _ in items)
    l0 = max(L for _, _, L, _, _ in items)
    fs.add("span", span, "count", count_words(span, pw[0], pw[1], pw[2]), None,
           f"От {period_gen(tv.periods[0])} до {period_gen(tv.periods[-1])}.",
           prov=_ptime(d, tv, "span", frm=tv.periods[f0], to=tv.periods[l0]))
    _time_structure(d, tv, fs)
    p0 = phrase(names[0])
    # даты без регулярного шага («точки») — не единица времени: «за период»
    when = f"за {count_words(span, pw[0], pw[1], pw[2])}" if tv.freq != "irregular" else "за период"
    fs.ctx.update(multi=True, names=names, labels=list(names), freq=tv.freq, unit_short=unit,
                  gender=p0.gender if p0 is not None else "m", when=when)
    caption = [f"{_range_text(tv.periods[0], tv.periods[-1])}: "
               + ", ".join(f"{_mid(sv.name)} — с {fmt_value(first, unit, 'gen')} до {fmt_value(last, unit, 'gen')}"
                           for sv, F, L, first, last in items) + "."]
    for name, v, per in fs.ctx.get("peaks", [])[:1]:
        caption.append(f"{name}: максимум {fmt_value(v, unit)} {period_in(per)}, затем ниже.")
    if tv.missing:
        caption.append(f"За {join_and([period_text(p) for p in tv.missing[:3]])} данных нет — на графике разрывы.")
    fs.ctx["caption"] = _short(caption)
    return True


# ── сравнение ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _growth_measure(cv: CatView) -> Optional[Measure]:
    """Колонка темпа («Рост, %»): «растёт быстрее всех» говорят про темп, а не про прибавку в рублях."""
    for mm in cv.extra_measures:
        if mm.change and (mm.type == "percent" or (mm.unit or "") in ("%", "п.п.")) \
                and any(v is not None for v in cv.extra.get(mm.name, [])):
            return mm
    return None


_GENERIC = re.compile(r"^(?:сумма|количество|значение|итого|всего|число|объём|объем|величина|показатель)$", re.I)
_REVENUE = re.compile(r"выручк|доход|продаж|прибыл|оборот", re.I)


def _title_whole(d: Data) -> Optional[Phrase]:
    """Целое по названию датасета для безликой метрики («Сумма»): «Структура расходов» → «расходов», «Расходы 2026» →
    «расходов»."""
    title = re.sub(r"\s*\d{4}\s*$", "", file_title(d.profile.file, d.profile.sheet)).strip()
    title = re.sub(r"^(?:[\w-]*\d[\w-]*\s+)+", "", title)  # код или число в начале имени файла — не слово
    words = title.split()
    if len(words) >= 2 and words[0].lower() in ("структура", "распределение", "состав", "доли", "доля"):
        rest = " ".join(words[1:])
        return Phrase(rest, rest, rest, rest, rest, rest, "f", sure=False)
    p = phrase(words[0]) if words else None
    return p if p is not None and p.sure else None


def _funnel(d: Data, cv: CatView) -> FactSet:
    """Воронка: конверсия от первого этапа до последнего и самый большой отсев между соседними."""
    fs = FactSet()
    labels, vals = cv.labels, cv.values
    fv, lv = vals[0], vals[-1]
    conv = lv / fv * 100 if fv else 0.0
    fs.ctx.update(funnel=True, first=labels[0], last=labels[-1], labels=list(labels))
    m = cv.measure
    r0, r1 = d.rows_idx[0], d.rows_idx[-1]
    fs.add("conversion", round_pct_any(conv), "share", f"{labels[0]} → {labels[-1]}: {fmt_pct_any(conv)}%", "%",
           f"{fmt_num(lv)} из {fmt_num(fv)}: от этапа «{labels[0]}» до «{labels[-1]}».",
           prov={"op": "conv", "col": m.j, "first": r0, "last": r1, "tol": 0.051 if conv >= 1 else 0.0006})
    fs.add("first", fv, "total", f"{labels[0]} — {fmt_num(fv)}", None, "Первый этап.",
           prov={"op": "cell", "row": r0, "col": m.j, "scale": m.scale})
    fs.add("last", lv, "total", f"{labels[-1]} — {fmt_num(lv)}", None, "Последний этап.",
           prov={"op": "cell", "row": r1, "col": m.j, "scale": m.scale})
    steps = [(labels[k], labels[k + 1], vals[k + 1] / vals[k] * 100) for k in range(len(vals) - 1) if vals[k]]
    if steps:
        k = min(range(len(steps)), key=lambda i: steps[i][2])
        a, b, p = steps[k]
        rows = d.rows_idx
        fs.add("step", round_pct_any(p), "share", f"{a} → {b}: {fmt_pct_any(p)}%", "%", "Самый большой отсев.",
               prov={"op": "conv", "col": m.j, "first": rows[k], "last": rows[k + 1],
                     "tol": 0.051 if p >= 1 else 0.0006})
        fs.ctx["caption"] = _short([f"Больше всего отсеивается между «{a}» и «{b}»: дальше проходит {fmt_pct_any(p)}%."])
    return fs


def _plan_fact(d: Data, cv: CatView) -> FactSet:
    """План и факт по категориям: исполнение в целом и у кого ниже всех."""
    fs = FactSet()
    pl, fa = d.plan_fact  # type: ignore[misc]
    unit = fa.unit_text
    pv = cv.values if cv.measure is pl else cv.extra.get(pl.name, [])
    fv = cv.values if cv.measure is fa else cv.extra.get(fa.name, [])
    pairs = [(lab, p, f) for lab, p, f in zip(cv.labels, pv, fv) if p is not None and f is not None and p > 0]
    if not pairs:
        return fs
    ptot, ftot = sum(p for _, p, _ in pairs), sum(f for _, _, f in pairs)
    ex = ftot / ptot * 100
    pw = "План"
    if re.search(r"утвержд|бюджет|смет|лимит", pl.name, re.I):
        pw = "Бюджет"
    elif re.search(r"норматив", pl.name, re.I):
        pw = "Норматив"
    fs.ctx.update(plan_fact=True, unit_short=unit, labels=[lab for lab, _, _ in pairs], plan_word=pw)
    ev = round(ex, 1) if 99 <= ex <= 101 else round_pct(ex)  # около 100% — с десятыми: 100,4% — не «ровно 100»
    ex_p = {"op": "exec", "plan": pl.j, "fact": fa.j, "skip": _skip(d), "scale": fa.scale}
    fs.add("execution", ev, "share", f"Исполнение плана — {fmt_num(ev)}%", "%",
           f"Факт {fmt_value(ftot, unit)} из плана {fmt_value(ptot, unit)}.", prov=ex_p)
    fs.add("fact_total", ftot, "total", f"Факт — {fmt_value(ftot, unit)}", unit, f"Сумма колонки «{fa.name}».",
           prov={**ex_p, "what": "fact"})
    fs.add("plan_total", ptot, "total", f"План — {fmt_value(ptot, unit)}", unit, f"Сумма колонки «{pl.name}».",
           prov={**ex_p, "what": "plan"})
    over = sum(1 for _, p, f in pairs if f > p)
    low = min(pairs, key=lambda t: (t[2] / t[1], t[0]))
    exg = {**ex_p, "by": _col_of(d, cv.dim)}
    fs.add("over", over, "count", f"Выше плана — {over}", None, "Категорий, где факт больше плана.",
           prov={**exg, "what": "over"})
    fs.add("rows", len(pairs), "count", f"{len(pairs)} категорий", None, "Категорий с планом.",
           prov={**exg, "what": "n"})
    fs.add("low_exec", round(low[2] / low[1] * 100, 1), "min", f"{low[0]}: {fmt_pct(low[2] / low[1] * 100)}% плана",
           "%", "Ниже всех по исполнению.", prov={**exg, "what": "low", "key": low[0], "tol": 0.51})
    cap = [f"Выше плана — {over} из {len(pairs)}; ниже всех — {low[0]}: {fmt_pct(low[2] / low[1] * 100)}% плана."]
    fs.ctx["caption"] = _short(cap)
    return fs


_TEMP = re.compile(r"температур|°", re.I)
_SLOW = re.compile(r"пинг|ping|отклик|latency|загрузк\w*\s+(?:страниц|сайт)|(?:^|[^a-zа-яё])p\d{2}(?:[^a-zа-яё\d]|$)", re.I)
_LONG = re.compile(r"задержк|опоздан|ожидан|время|длительн|(?:^|[^а-яё])срок", re.I)
_DELAY = re.compile(r"задержк|опоздан|ожидан", re.I)
_WORSE = re.compile(r"ошибк|отток|брак|дефект|просроч|опоздан|брошен|жалоб|возврат|авари|дтп|примес|загрязн|концентрац|выброс|"
                    r"расход\s+топлив|(?:^|[^а-яё])расход(?:[^а-яё]|$)", re.I)
_CLOCK_LAB = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")
# порядковые группы-интервалы: «0–4», «70 и старше», «до 30», «100+» (а не «5-А», «1 курс»)
_BIN_LABEL = re.compile(r"^\s*(?:до|от|свыше|более|больше|менее|меньше|<|>|≤|≥)?\s*\d+(?:[.,]\d+)?\s*"
                        r"(?:[–—-]\s*\d|\+|(?:лет\s+)?(?:и|или)\s+(?:старше|более|больше|выше|младше|меньше)|$)", re.I)
_PRICE = re.compile(r"(?:^|[^а-яё])(?:цен[аыу]?|стоимост\w*|тариф\w*|курс\w*)(?:[^а-яё]|$)", re.I)


def _ties(cv: CatView, ks: list[int], k0: int, unit: Optional[str]) -> list[int]:
    """Категории с тем же значением, что у k0 (по самим числам, а не по округлённым: 0,012 и 0,006 — не ничья):
    «ИТ и Склад — 3,2», а не одна из них."""
    v0 = cv.values[k0]
    return [k for k in ks if abs(cv.values[k] - v0) <= 1e-9 * max(1.0, abs(v0))]


def _names(cv: CatView, ks: list[int]) -> str:
    labs = [cv.labels[k] for k in ks]
    return join_and(labs) if len(labs) <= 3 else f"{labs[0]} и ещё {len(labs) - 1}"


def _wording(d: Data, cv: CatView, m: Optional[Measure]) -> str:
    """Как назвать первого и последнего: температура — «теплее всего», цена — «дороже всего», порядковые группы —
    «больше всего»; иначе «впереди»."""
    if m is None:
        return "lead"
    title = file_title(d.profile.file)
    unit = (m.unit_text or "").strip().lower()
    if _TEMP.search(m.name) or _TEMP.search(unit) or _TEMP.search(title):
        return "temp"
    # цена и тариф — «дороже/дешевле всего» (по названию, единице «₽/…» или названию файла)
    if not m.additive and (_PRICE.search(m.name) or unit.startswith(("₽/", "руб")) or _PRICE.search(title)):
        return "price"
    # меньше — лучше: задержка, время, пинг, отклик — «дольше/медленнее всего» у первого, «быстрее всего» у лучшего
    # только у длительностей (единица времени): «Доля опозданий, %» — не время
    if unit in ("мс", "ms") or (_SLOW.search(m.name) and (m.time_unit or unit in TO_MINUTES)):
        return "slow"
    if m.time_unit or unit in TO_MINUTES:
        return "delay" if _DELAY.search(m.name) else "long"
    bins = sum(1 for x in cv.labels if _BIN_LABEL.match(x) or _CLOCK_LAB.match(x)) >= 0.8 * max(1, len(cv.labels))
    if (not cv.ranked and bins) or _WORSE.search(m.name) or _WORSE.search(title):
        return "most"  # порядковые группы, а ещё ошибки, брак, отток, примеси — «больше/меньше всего», не «впереди»
    return "lead"


def _comparison(d: Data) -> FactSet:
    fs = FactSet()
    cv = d.cats
    if cv is None:
        return fs
    if d.funnel and cv.dim == (d.cols[d.label].name if d.label is not None else None):
        return _funnel(d, cv)
    if d.plan_fact is not None and cv.measure in d.plan_fact:
        return _plan_fact(d, cv)
    if d.constant_main:
        return _constant(d, cv)
    m = cv.measure
    unit = cv.unit
    shown = cv
    if cv.merged:
        # порядковых групп больше 20 и хвост на графике — одной группой: лидер и последний — по всем группам
        full = d.cat_view(m, top=10**6)
        cv = full if full is not None else cv
    # лидер и последний — среди настоящих категорий: не «Остальные N», не «Прочее»
    tail = cv.others > 0
    real = [k for k in range(cv.n) if not (tail and k == cv.n - 1) and not is_other_label(cv.labels[k])]
    real = real or [k for k in range(cv.n) if not (tail and k == cv.n - 1)]
    leader_k = max(real, key=lambda k: (cv.values[k], -k))
    lead_ks = _ties(cv, real, leader_k, unit)
    leader = _names(cv, lead_ks)
    lv = cv.values[leader_k]
    generic = m is not None and (_GENERIC.match(re.sub(r"\s*,.*$", "", m.name).strip()) is not None
                                 or is_total_label(m.name))
    if m is not None:
        ph = metric_phrase(m.name, m.type)
        if generic:
            # «Сумма», «Итого за год» — целое по названию датасета: «выручки», «расходов»
            ph = _title_whole(d) or ph
    else:
        ent = phrase(d.entity) if d.entity else None
        ph = Phrase(ent.gen_pl, ent.gen_pl, ent.dat_pl, ent.gen_pl, ent.dat_pl, ent.nom_pl, "pl") \
            if ent is not None and ent.sure else None
    labels = [cv.labels[k] for k in lead_ks]
    grouped = [x for x in d.parallel if x is not m] if m is not None and len(d.parallel) >= 2 else []
    revenue = m is not None and bool(_REVENUE.search(m.name) or (generic and _REVENUE.search(file_title(d.profile.file))))
    fs.ctx.update(leader=leader, metric=ph, unit_short=unit, labels=labels, wording=_wording(d, cv, m),
                  lead_plural=len(lead_ks) > 1 or is_plural_value(leader),
                  gives=m is not None and m.type == "money" and revenue)
    if grouped and m is not None and not cv.shares:
        # несколько величин рядом (минимум, медиана, максимум): лидер — по главной, она названа
        mp = phrase(m.name)
        fs.ctx["by_metric"] = mp.low.dat if mp is not None and mp.sure else None
    name = m.name if m is not None else "Число строк"
    shares = cv.shares
    caption = []
    if shares is not None and cv.total and len(lead_ks) == 1 and not (grouped and fs.ctx["wording"] == "most"):
        p = shares[leader_k]
        trow = _total_row(d, m) if cv.total_from_row else None
        if p >= 15:
            fs.add("leader_share", round_pct(p), "share", f"{leader} — {fmt_pct(p)}%", "%",
                   f"{leader} — {fmt_value(lv, unit)} из {fmt_value(cv.total, unit)}, это {fmt_pct(p)}%. "
                   f"Посчитано по колонке «{name}».",
                   prov={**_pcat(d, m, cv.dim, [cv.labels[k] for k in lead_ks],
                                 named=ph.low.gen if ph is not None else None), "op": "share", "total_row": trow})
        fs.add("total", round(cv.total) if abs(cv.total) >= 100 else round(cv.total, 1), "total",
               f"Всего — {fmt_value(cv.total, unit)}", unit,
               "Строка «Итого» в файле." if cv.total_from_row else f"Сумма по колонке «{name}».",
               prov={"op": "colsum", "col": m.j, "row": trow, "skip": _skip(d), "scale": m.scale}
               if m is not None else {"op": "count", "what": "rows", "skip": _skip(d)})
        caption.append(f"{leader} — {fmt_value(lv, unit)} из {fmt_value(cv.total, unit)}.")
    others_ = tuple(x for x in cv.labels if is_other_label(x))
    p_lead = _pcat(d, m, cv.dim, [cv.labels[k] for k in lead_ks], rank="max", exclude=others_)
    fs.add("leader_value", lv, "leader", f"{leader} — {fmt_value(lv, unit)}", unit,
           f"Наибольшее значение — у {'категорий' if len(lead_ks) > 1 else 'категории'} «{leader}». "
           f"Посчитано по колонке «{name}».", prov=p_lead)
    last_k = min(real, key=lambda k: (cv.values[k], k))
    last_ks = _ties(cv, real, last_k, unit)
    if cv.cut and cv.low_label is not None:
        # показаны первые по значению: последний — из всего списка, не из показанных
        lo = cv.low_value
        fs.add("last_value", lo, "min", f"{cv.low_label} — {fmt_value(lo, unit)}", unit,
               f"Наименьшее значение из всех {cv.distinct} — у категории «{cv.low_label}» (на графике — первые {cv.n}).",
               prov=_pcat(d, m, cv.dim, [cv.low_label], rank="min", exclude=others_))
        fs.ctx["last_label"] = cv.low_label
        labels.append(cv.low_label)
    elif last_k not in lead_ks and not cv.others:
        lo = cv.values[last_k]
        last_lab = _names(cv, last_ks)
        p_last = _pcat(d, m, cv.dim, [cv.labels[k] for k in last_ks], rank="min", exclude=others_)
        fs.add("last_value", lo, "min", f"{last_lab} — {fmt_value(lo, unit)}",
               unit, f"Наименьшее значение — у {'категорий' if len(last_ks) > 1 else 'категории'} «{last_lab}».",
               prov=p_last)
        fs.ctx["last_label"] = last_lab
        labels.extend(cv.labels[k] for k in last_ks)
        if lo > 0 and lv / lo >= 2:
            r = round(lv / lo, 1)
            fs.add("spread", r, "max", f"Разрыв — в {fmt_num(r, 1)} {times_word(r)}", "раз",
                   f"{leader} — {fmt_value(lv, unit)}, {last_lab} — {fmt_value(lo, unit)}.",
                   prov={"op": "ratio", "a": p_lead, "b": p_last, "tol": 0.051})
    if grouped and fs.ctx.get("wording") == "most":
        # порядковые группы и две величины рядом (мужчины и женщины по возрасту): первая у каждой своя
        x = grouped[0]
        xv = cv.extra.get(x.name, [])
        ks = [k for k in real if k < len(xv) and xv[k] is not None]
        if ks:
            xk = max(ks, key=lambda k: (xv[k], -k))
            fs.ctx.update(second_name=d.series_names.get(x.name, x.name), second_leader=cv.labels[xk],
                          first_name=d.series_names.get(m.name, m.name))
            labels.append(cv.labels[xk])
            fs.add("second_value", xv[xk], "leader", f"{cv.labels[xk]} — {fmt_value(xv[xk], unit)}", unit,
                   f"Наибольшее значение по колонке «{x.name}» — у категории «{cv.labels[xk]}».",
                   prov=_pcat(d, x, cv.dim, [cv.labels[xk]], rank="max", exclude=others_))
    g = _growth_measure(cv)
    if g is not None:
        gv = cv.extra[g.name]
        ks = [k for k in real if gv[k] is not None]
        if ks:
            gk = max(ks, key=lambda k: (gv[k], -k))
            if gv[gk] > 0:
                gl = cv.labels[gk]
                gu = g.unit or ("%" if g.type == "percent" else "")
                fs.ctx["growth_leader"] = gl
                labels.append(gl)
                fs.add("growth_max", round_pct(gv[gk]) if gu == "%" else gv[gk], "max",
                       f"{gl}: {fmt_signed(gv[gk], gu)}", gu or None,
                       f"Самый быстрый рост — {gl}: {fmt_signed(gv[gk], gu)}. Посчитано по колонке «{g.name}».",
                       prov={**_pcat(d, g, cv.dim, [gl], rank="max", exclude=others_), "agg": "mean"})
                caption.append(f"{gl}: {fmt_signed(gv[gk], gu)} — быстрее всех.")
    neg = cv.negatives
    if neg:
        dp = phrase(cv.dim)
        forms = (dp.low.nom, dp.low.gen, dp.low.gen_pl) if dp is not None and dp.sure and dp.gender != "pl" else \
            ("категория", "категории", "категорий")
        fs.ctx["neg_forms"] = forms
        fs.ctx["neg_all"] = neg == len(real)  # все в минусе — «все 5 филиалов в минусе»
        fs.add("negatives", neg, "count", f"{count_words(neg, *forms)} в минусе", None,
               f"Отрицательные значения: {', '.join(cv.labels[k] for k in real if cv.values[k] < 0)}.",
               prov={**_pcat(d, m, cv.dim, []), "op": "neg"})
    bench = _benchmark(d, cv, m)
    if bench is not None:
        blab, bv, above = bench
        brow = next(i for i, lab_ in d.benchmarks.items() if lab_ == blab)
        fs.add("benchmark", bv, "total", f"{blab} — {fmt_value(bv, unit)}", unit,
               f"Строка «{blab}» — ориентир, не категория: на графике её нет. Выше неё — {above} из {len(real)}.",
               prov={"op": "cell", "row": brow, "col": m.j, "scale": m.scale})
        fs.add("above_benchmark", above, "count", f"Выше ориентира — {above} из {len(real)}", None,
               f"Категорий со значением больше {fmt_value(bv, unit)}.",
               prov={**_pcat(d, m, cv.dim, []), "op": "above", "v": bv})
        fs.add("categories", len(real), "count", count_words(len(real), "категория", "категории", "категорий"), None,
               "Категорий в данных.", prov={"op": "count", "what": "groups", "by": _col_of(d, cv.dim), "skip": _skip(d)})
        caption.insert(0, f"{blab} — {fmt_value(bv, unit)}: выше — {above} из {len(real)}.")
        labels.append(blab)
    pg = {"op": "count", "what": "groups", "by": _col_of(d, cv.dim), "skip": _skip(d)}
    if cv.others:
        fs.add("others", cv.others, "count", f"Остальные {cv.others}", None, "Категории, собранные в одну строку.",
               prov={**pg, "minus": cv.n - 1})
        caption.append(f"Остальные {count_words(cv.others, 'категория', 'категории', 'категорий')} собраны в одну "
                       f"строку.")
    if cv.cut:
        fs.add("distinct", cv.distinct, "count", f"Всего {cv.distinct}", None, "Категорий в данных.", prov=pg)
        fs.add("shown", cv.n, "count", f"Показаны {cv.n}", None, "Категорий на графике.",
               prov={"op": "count", "what": "value", "value": cv.n})
        caption.append(f"Показаны первые {cv.n} из {cv.distinct}.")
    if shown.merged:
        fs.add("merged", shown.merged, "count", f"Одной группой — {shown.merged}", None, "Групп в хвосте графика.",
               prov={**pg, "minus": shown.n - 1})
        caption.append(f"Последние {count_words(shown.merged, 'группа', 'группы', 'групп')} — одной: «{shown.labels[-1]}».")
    fs.ctx["caption"] = _short(caption)
    return fs


def _constant(d: Data, cv: CatView) -> FactSet:
    """У всех одно значение (возвратов нет ни в одном магазине): лидера нет — это и вывод, без столбцов."""
    fs = FactSet()
    m = cv.measure
    v = cv.values[0]
    n = cv.distinct
    unit = cv.unit
    mp = metric_phrase(m.name, m.type) if m is not None else None
    dp = phrase(cv.dim)
    fs.add("constant", v, "total", f"У всех — {fmt_value(v, unit)}", unit,
           f"Все {n} значений колонки «{m.name if m else 'Число строк'}» равны {fmt_value(v, unit)}.",
           prov=_pcat(d, m, cv.dim, [cv.labels[0]], rank="max"))
    fs.add("count", n, "count", count_words(n, "категория", "категории", "категорий"), None, "Категорий в данных.",
           prov={"op": "count", "what": "groups", "by": _col_of(d, cv.dim), "skip": _skip(d)})
    fs.ctx.update(constant=True, unit_short=unit, labels=[],
                  metric_gen=(mp.low.gen_pl if mp is not None and mp.sure else None),
                  dim_gen=(dp.low.gen_pl if dp is not None and dp.sure and dp.gender != "pl" else None),
                  dim_forms=(dp.low.nom, dp.low.gen, dp.low.gen_pl) if dp is not None and dp.sure and dp.gender != "pl"
                  else ("категория", "категории", "категорий"))
    fs.ctx["caption"] = (f"Все {n} значений одинаковые: {fmt_value(v, unit)} — сравнивать нечего, поэтому таблица, а не "
                         f"столбцы.")
    return fs


def _total_row(d: Data, m: Optional[Measure]) -> Optional[int]:
    """Строка «Итого» таблицы с положительным значением в колонке (как берёт её сравнение)."""
    if m is None:
        return None
    for i in sorted(d.totals):
        tv = _num_cell(d.cell(i, m.j))
        if tv is not None and tv > 0:
            return i
    return None


def _benchmark(d: Data, cv: CatView, m: Optional[Measure]) -> Optional[tuple[str, float, int]]:
    """Строка-ориентир («Среднее по стране»): её значение и сколько категорий выше неё."""
    if m is None or m.j < 0 or not d.benchmarks:
        return None
    for i, lab in d.benchmarks.items():
        v = _num_cell(d.cell(i, m.j))
        if v is not None:
            above = sum(1 for k in range(cv.n) if not (cv.others and k == cv.n - 1) and cv.values[k] > v)
            return lab, v, above
    return None


# ── доли ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _whole_phrase(d: Data, parts: Optional[Measure], summed: Optional[Measure] = None) -> tuple[Optional[Phrase], bool]:
    """Целое, долю которого показывают. Доли посчитаны по колонке (`summed`) — целое называется ею и только ею
    («суммы выплат», если делили суммы, «числа выплат» — если число); колонка долей («Доля рынка») — «рынка» или
    деньги рядом с ней («выручки»)."""
    if parts is None and summed is not None:
        if _GENERIC.match(re.sub(r"\s*,.*$", "", summed.name).strip()):
            return _title_whole(d) or metric_phrase(summed.name, summed.type), summed.type == "money"
        p = metric_phrase(summed.name, summed.type)
        return p, summed.type == "money"
    money = next((m for m in d.measures if m.additive and m is not parts and m.type == "money"), None)
    other = money or next((m for m in d.measures if m.additive and m is not parts), None)
    if other is not None:
        p = metric_phrase(other.name, other.type)
        if p is not None:
            return p, other.type == "money"
    if parts is not None:
        base = re.sub(r"\s*[,(].*$", "", parts.name).strip()
        rest = re.sub(r"^\s*(?:доля|доли|удельный вес|процент)\s*", "", base, flags=re.I).strip()
        if rest and rest != base and re.search(r"[а-яёa-z]", rest, re.I):
            # «Доля рынка» — дополнение уже в родительном
            return Phrase(rest, rest, rest, rest, rest, rest, "f", sure=False), False
    return None, False


def _dataset_whole(d: Data) -> Optional[Phrase]:
    """Целое по названию датасета: «Приём по направлениям» → «приёма» (главное слово, если оно склоняется)."""
    head = head_word(file_title(d.profile.file, d.profile.sheet))
    if not head or head in ("данные", "таблица", "лист", "отчёт", "отчет", "итоги", "список", "выгрузка"):
        return None
    p = phrase(head)
    return p if p is not None and p.sure else None


def _composition(d: Data) -> FactSet:
    """Части одного целого по категориям: доля каждой части в общем итоге («Платное — 53% приёма, бюджет — 35%»)."""
    fs = FactSet()
    cv = d.cats
    g = d.parallel
    names = d.series_names
    totals = [(names.get(x.name, x.name), float(sum(x.present))) for x in g]
    whole = sum(v for _, v in totals)
    if whole <= 0:
        return fs
    order = sorted(range(len(totals)), key=lambda k: (-totals[k][1], k))
    unit = g[0].unit_text
    labels = [totals[k][0] for k in order]
    rows100 = _rows_of_100(d, g)
    # строки по 100 (ответы по шкале): доля части — среднее по строкам, целое — не «опроса», а сами ответы
    fs.ctx.update(composition=True, parts=labels, whole=None if rows100 else _dataset_whole(d), labels=list(labels))
    gj = [x.j for x in g]
    sk = _skip(d)
    for r, k in enumerate(order):
        nm, v = totals[k]
        fs.add(f"part_{r}", round_pct(v / whole * 100), "share", f"{nm} — {fmt_pct(v / whole * 100)}%", "%",
               f"{nm}: {fmt_value(v, unit)} из {fmt_value(whole, unit)}.",
               prov={"op": "colshare", "col": g[k].j, "cols": gj, "skip": sk, "scale": g[k].scale})
        fs.add(f"part_{r}_sum", v, "total", f"{nm} — {fmt_value(v, unit)}", unit, f"Сумма колонки «{g[k].name}».",
               prov={"op": "colsum", "col": g[k].j, "skip": sk, "scale": g[k].scale})
    fs.add("total", round(whole) if whole >= 100 else round(whole, 1), "total", f"Всего — {fmt_value(whole, unit)}",
           unit, f"Сумма частей по всем строкам ({', '.join(labels)}).",
           prov={"op": "colsum", "cols": gj, "skip": sk, "scale": g[0].scale})
    if cv is not None and rows100:
        # ответы по шкале: доля — среднее по строкам, и это сказано: «в среднем по 6 утверждениям»
        dp = phrase(cv.dim)
        nrows = len(cv.labels)
        fs.add("rows", nrows, "count", count_words(nrows, "строка", "строки", "строк"), None,
               f"Доли частей — среднее по {count_dat(nrows, 'строке', 'строкам')} колонки «{cv.dim}».",
               prov={"op": "count", "what": "groups", "by": _col_of(d, cv.dim), "skip": sk})
        fs.ctx["rows_dat"] = count_dat(nrows, dp.low.dat, dp.low.dat_pl) if dp is not None and dp.sure and \
            dp.gender != "pl" else count_dat(nrows, "строке", "строкам")
        top = g[[names.get(x.name, x.name) for x in g].index(labels[0])]
        vals = cv.values if cv.measure is top else cv.extra.get(top.name, [])
        best = max(((lab, v) for lab, v in zip(cv.labels, vals) if v is not None), key=lambda t: (t[1], t[0]),
                   default=None)
        if best is not None:
            fs.add("best_row", best[1], "max", f"{best[0]} — {fmt_pct(best[1])}%", "%", f"Наибольшая доля «{labels[0]}».",
                   prov={**_pcat(d, top, cv.dim, [best[0]], rank="max"), "tol": 0.51})
            fs.ctx["caption"] = _short([f"Чаще всего «{lower_first(labels[0])}» — {best[0]}: {fmt_pct(best[1])}%."])
            fs.ctx["labels"] = list(labels) + [best[0]]
    elif cv is not None:
        lead = cv.labels[0] if cv.ranked else None
        if lead:
            caption = [f"Больше всего — {lead}.", f"Всего {fmt_value(whole, unit)}: "
                       + ", ".join(f"{lower_first(totals[k][0]) if r else totals[k][0]} — {fmt_value(totals[k][1], unit)}"
                                   for r, k in enumerate(order)) + "."]
            fs.ctx["caption"] = _short(caption)
    return fs


def _rows_of_100(d: Data, g: list[Measure]) -> bool:
    sums = []
    for i in d.rows_idx:
        vals = [x.values[i] for x in g]
        if all(v is not None for v in vals):
            sums.append(sum(vals))  # type: ignore[arg-type]
    return bool(sums) and all(97 <= v <= 103 for v in sums)


def _shares(d: Data) -> FactSet:
    if d.composition and d.cats is not None and len(d.parallel) >= 2:
        return _composition(d)
    fs = FactSet()
    got = d.shares
    if got is None:
        return fs
    cv, shares = got
    # по значению, не по месту; «Прочее» — никогда не лидер
    order = sorted(range(len(shares)), key=lambda k: (is_other_label(cv.labels[k]), -shares[k], k))
    k1 = order[0]
    leader = cv.labels[k1]
    whole, money = _whole_phrase(d, d.parts_measure, cv.measure)
    src = cv.measure if d.parts_measure is None else \
        next((m for m in d.measures if m.additive and m is not d.parts_measure), None)
    gives = src is not None and src.type == "money" and bool(_REVENUE.search(src.name))
    fs.ctx.update(leader=leader, whole=whole, money=money, labels=[leader], gives=gives)
    p = shares[k1]
    others = [k for k in order[1:]]
    parts = d.parts_measure

    def p_share(keys: list[str]) -> dict:
        if parts is not None:
            return {"op": "pshare", "col": parts.j, "by": _col_of(d, cv.dim), "keys": keys, "skip": _skip(d),
                    "tol": 0.51}
        return {**_pcat(d, cv.measure, cv.dim, keys, named=whole.low.gen if whole is not None else None),
                "op": "share", "tol": 0.51, "total_row": _total_row(d, cv.measure) if cv.total_from_row else None}

    fs.add("leader_share", round_pct(p), "share", f"{leader} — {fmt_pct(p)}%", "%",
           f"{leader} — {fmt_pct(p)}%, больше любой другой части: "
           + ", ".join(f"{cv.labels[k]} — {fmt_pct(shares[k])}%" for k in others) + ".", prov=p_share([leader]))
    for k in order:
        fs.add(f"share_{k}", round(shares[k], 1), "share", f"{cv.labels[k]} — {fmt_pct(shares[k])}%", "%",
               f"Доля «{cv.labels[k]}».", prov={**p_share([cv.labels[k]]), "tol": 0.051})
    if len(order) >= 2:
        k2 = order[1]
        fs.add("second_share", round_pct(shares[k2]), "share", f"{cv.labels[k2]} — {fmt_pct(shares[k2])}%", "%",
               "Вторая по величине доля.", prov=p_share([cv.labels[k2]]))
        top2 = shares[k1] + shares[k2]
        fs.add("top2_share", round_pct(top2), "share", f"Две крупнейшие части — {fmt_pct(top2)}%", "%",
               f"{leader} и {cv.labels[k2]} вместе.", prov=p_share([leader, cv.labels[k2]]))
    total = sum(shares)
    fs.add("total_share", round(total), "total", f"Сумма долей — {fmt_pct(total)}%", "%",
           "Части одного целого: сумма долей ≈ 100%.", prov=p_share(list(cv.labels)))
    if len(order) > 6:
        # подпись — то, что на кольце: пять крупнейших и одни «Прочие» (с перечнем, кто в них)
        from verstka.data.plan import _doughnut_split

        top, rest, rest_label = _doughnut_split(cv.labels, shares)
        top = sorted(top, key=lambda k: (-shares[k], k))
        named = [cv.labels[k] for k in rest if not is_other_label(cv.labels[k])]
        tail = f"{rest_label}" + (f" (вместе с {join_and(named[:4])}{' и другими' if len(named) > 4 else ''})"
                                  if named and is_other_label(rest_label) else "")
        fs.add("rest_share", round(sum(shares[k] for k in rest), 1), "share", f"{tail} — "
               f"{fmt_pct(sum(shares[k] for k in rest))}%", "%", "Доля всех, кто не вошёл в пять крупнейших.",
               prov={**p_share([cv.labels[k] for k in rest]), "tol": 0.51})
        fs.ctx["caption"] = _short([", ".join(f"{cv.labels[k]} — {fmt_pct(shares[k])}%" for k in top)
                                    + f", {tail} — {fmt_pct(sum(shares[k] for k in rest))}%."])
        fs.ctx["labels"] = list(fs.ctx["labels"]) + [cv.labels[k] for k in rest]
    else:
        fs.ctx["caption"] = _short([", ".join(f"{cv.labels[k]} — {fmt_pct(shares[k])}%" for k in order[:6]) + "."])
    return fs


# ── распределение ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _nice_ceil(x: float) -> float:
    if x <= 0:
        return 0.0
    e = 10 ** math.floor(math.log10(x))
    for b in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8, 10):
        if b * e >= x - 1e-9:
            return b * e
    return 10 * e


def _predicate(name: str) -> str:
    n = name.lower()
    if "ответ" in n:
        return "получают ответ за"
    if re.search(r"закры|решени|решен", n):
        return "закрываются за"
    if "доставк" in n:
        return "доставляются за"
    if "обработ" in n:
        return "обрабатываются за"
    if re.search(r"ожидани|ждут|очеред", n):
        return "ждут не дольше"
    return "укладываются в"


def _round_down_above(threshold: float, above: float) -> float:
    """Граница выбросов сверху: наибольшее «круглое» число ≤ threshold и > above (655 при максимуме 513 → 600)."""
    mag = 10 ** math.floor(math.log10(threshold)) if threshold > 0 else 1
    for step in (mag, mag / 2, mag / 10, mag / 20, mag / 100, 1):
        t = math.floor(threshold / step) * step
        if t > above:
            return float(t)
    return float(above)


def _round_up_below(threshold: float, below: float) -> float:
    """Граница выбросов снизу: наибольшее «круглое» число ≤ below (самого малого обычного значения) и > threshold
    (самого большого низкого выброса): выбросы 1–3 мин при обычных от 76 → «меньше 70»."""
    mag = 10 ** math.floor(math.log10(below)) if below > 0 else 1
    for step in (mag, mag / 2, mag / 10, mag / 20, mag / 100, 1):
        t = math.floor(below / step) * step
        if t > threshold:
            return float(t)
    return float(below)


def _distribution(d: Data) -> FactSet:
    fs = FactSet()
    dv = d.dist
    if dv is None:
        return fs
    m = dv.measure
    unit = m.unit_text
    x = dv.values
    n = dv.n
    ent = phrase(dv.entity) if dv.entity else None
    ent_ok = ent is not None and ent.sure
    ent_forms = (ent.low.nom, ent.low.gen, ent.low.gen_pl) if ent_ok else ("значение", "значения", "значений")
    to_min = TO_MINUTES.get((m.time_unit or "").lower()) if m.time_unit else None
    duration = to_min is not None
    fs.ctx.update(entities_gen=ent.low.gen_pl if ent_ok else None, entities_nom_pl=ent.nom_pl if ent_ok else None,
                  unit_short=unit, duration=duration)
    med = float(np.median(x))
    med_txt = fmt_value(med, unit)
    if duration and float(med * to_min).is_integer():
        med_txt = duration_text(med * to_min)[0]
        if med_txt.endswith(("минуту", "секунду")):
            med_txt = med_txt[:-1] + "а"  # «медиана — 21 минута»
    fs.ctx["median_text"] = med_txt
    pd = {"op": "dist", "col": m.j, "skip": _skip(d), "scale": m.scale}
    fs.add("median", round(med, 1) if abs(med) < 100 else round(med), "median", f"Медиана — {fmt_value(med, unit)}", unit,
           f"Половина значений меньше {fmt_value(med, unit)}. {_by(m)}", prov={**pd, "stat": "median"})
    fs.add("count", n, "count", count_words(n, *ent_forms), None, "Строк с числом в колонке.",
           prov={**pd, "stat": "count"})
    fs.add("min_value", float(x.min()), "min", f"Меньше всего — {fmt_value(float(x.min()), unit)}", unit,
           "Наименьшее значение колонки.", prov={**pd, "stat": "min"})
    fs.add("max_value", float(x.max()), "max", f"Больше всего — {fmt_value(float(x.max()), unit)}", unit,
           "Наибольшее значение колонки.", prov={**pd, "stat": "max"})
    if dv.bins.n < 5:
        # почти одно и то же значение: форма распределения пустая, вывод — само значение
        fs.ctx["constant"] = "all" if float(x.min()) == float(x.max()) else "almost"
        fs.ctx["caption"] = (f"{upper_first(count_words(n, *ent_forms))}: значения от {fmt_value(float(x.min()), unit)} до "
                             f"{fmt_value(float(x.max()), unit)} — разброса почти нет.")
        return fs
    p80 = float(np.percentile(x, 80))
    if duration and to_min >= 1440:
        # дни — граница в днях («не дольше 60 дней»), а не в тысячах часов
        t = _nice_ceil(p80)
        text, tv, tu = duration_text(t * to_min)
    elif duration:
        pm = p80 * to_min  # в минутах
        t_min = next((float(v) for v in NICE_MINUTES if v >= pm - 1e-9), _nice_ceil(pm))
        step = 5.0 if pm < 60 else 10.0
        if t_min > pm * 1.15:
            # «круглая» граница далеко от 80-го перцентиля — ближайшее кратное 5/10 минут, чтобы доля осталась честной
            t_min = math.ceil(pm / step - 1e-9) * step
        t = t_min / to_min
        text, tv, tu = duration_text(t_min)
    else:
        t = _nice_ceil(p80) if p80 > 0 else p80
        text, tv, tu = fmt_value(t, unit), t, unit
    within = int((x <= t + 1e-9).sum())
    share = round_pct(within / n * 100) if n else 0
    if within < n and share >= 99.5:
        share = 99.0  # не все — значит не 100%
    fs.ctx["all_within"] = within == n
    fs.ctx.update(threshold_text=text, predicate=_predicate(m.name) if duration and ent_ok else None)
    fs.add("share_within", share, "percentile", f"{fmt_pct(share)}% — не больше {fmt_value(t, unit)}", "%",
           f"{within} из {count_words(n, *ent_forms)} — не больше {fmt_value(t, unit)}. {_by(m)}",
           prov={**pd, "stat": "within", "thr": t, "tol": 1.01})
    fs.add("within", within, "count", f"{within} из {n}", None, f"Не больше {fmt_value(t, unit)}.",
           prov={**pd, "stat": "count_to", "thr": t})
    fs.add("threshold", tv, "percentile", text, tu,
           f"Граница — {fmt_value(t, unit)}: 80-й перцентиль {fmt_value(p80, unit)}, округлено вверх.",
           prov={**pd, "stat": "upper", "q": 80, "thr": t, "factor": (tv / t) if t else 1.0})
    fs.add("p80", round(p80, 1) if abs(p80) < 100 else round(p80), "percentile",
           f"80-й перцентиль — {fmt_value(p80, unit)}", unit, f"80% значений не больше этого числа. {_by(m)}",
           prov={**pd, "stat": "p", "q": 80})
    caption = [f"Медиана — {med_txt}."]
    mean = float(np.mean(x))
    if med > 0 and float(x.min()) >= 0 and mean / med >= 1.25 and not duration:
        # длительности (время ответа, доставки) — вывод через долю «за N часов», как говорят о сроках;
        # скошенное распределение: середину честнее показывает медиана, а не среднее
        fs.add("mean", round(mean, 1) if abs(mean) < 100 else round(mean), "median", f"Среднее — {fmt_value(mean, unit)}",
               unit, f"Среднее арифметическое; медиана — {fmt_value(med, unit)}: крупные значения тянут среднее вверх.",
               prov={**pd, "stat": "mean"})
        fs.ctx.update(skewed=True, mean_text=fmt_value(mean, unit))
        caption = [f"Медиана — {med_txt}, среднее — {fmt_value(mean, unit)}."]
    sides = []
    for side, vals in (("high", dv.high_outliers), ("low", dv.low_outliers)):
        if not vals:
            continue
        k = len(vals)
        if side == "high":
            thr = _round_down_above(min(vals), float(dv.inliers.max()) if dv.inliers.size else 0)
            word = "от" if any(abs(v - thr) < 1e-9 for v in vals) else "больше"  # «больше X» — строго больше
        else:
            thr = _round_up_below(max(vals), float(dv.inliers.min()) if dv.inliers.size else 0)
            word = "до" if any(abs(v - thr) < 1e-9 for v in vals) else "меньше"
        thr_txt = duration_gen(thr * to_min) if duration else fmt_value(thr, unit)
        shown_v = duration_text(thr * to_min)[1] if duration else thr  # «10 часов» — граница в часах
        sd = {"от": "ge", "больше": "gt", "до": "le", "меньше": "lt"}[word]
        fs.add(f"outlier_bound_{side}", thr, "outliers", f"{word} {thr_txt}", unit,
               f"Граница выбросов: {count_words(k, 'значение', 'значения', 'значений')} {word} {thr_txt}.",
               prov={**pd, "stat": "bound", "thr": thr, "side": sd, "k": k, "shown": shown_v})
        fs.add(f"outliers_{side}", k, "outliers", count_words(k, "значение", "значения", "значений"), None,
               f"Значений {word} {thr_txt}.", prov={**pd, "stat": "beyond", "thr": thr, "side": sd})
        sides.append({**pd, "stat": "beyond", "thr": thr, "side": sd})
        caption.append(f"{upper_first(count_words(k, *ent_forms))} — {word} {thr_txt}: это выбросы, они отмечены "
                       f"отдельно.")
    if dv.outliers:
        fs.add("outliers", len(dv.outliers), "outliers", count_words(len(dv.outliers), "выброс", "выброса", "выбросов"),
               None, f"Значения {', '.join(fmt_num(v) for v in dv.outliers[:5])} — далеко от остальных "
                     f"(правило Тьюки с отрывом).", prov={"op": "add", "parts": sides} if sides else None)
    fs.ctx["caption"] = _short(caption)
    return fs


# ── справочник ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _biggest(d: Data, m: Measure, ent: Optional[Phrase]) -> tuple[str, float, int]:
    """Естественно большое значение (`expected_outliers` профиля: крупнейший клиент) — одной фразой, без слова
    «выброс»: «Крупнейший клиент — АО «Северный капитал»: 212,4 млн ₽»."""
    exp = [o for o in getattr(d.profile, "expected_outliers", None) or [] if o.column == m.name]
    if not exp or d.label is None:
        return "", 0.0, -1
    o = max(exp, key=lambda x: x.value)
    who = d.text(o.row, d.label) if o.row < len(d.table.rows) else ""
    if not who:
        return "", 0.0, -1
    adj = {"m": "Крупнейший", "f": "Крупнейшая", "n": "Крупнейшее"}.get(ent.gender if ent is not None else "", "")
    head = f"{adj} {ent.low.nom}" if adj and ent is not None else "Больше всех"
    return f"{head} — {who}: {fmt_value(o.value, m.unit_text)}.", float(o.value), o.row


def _reference(d: Data) -> FactSet:
    fs = FactSet()
    rv = d.ref
    m = rv.measure
    ent = phrase(d.entity) if d.entity else None
    ent_ok = ent is not None and ent.sure
    forms = (ent.low.nom, ent.low.gen, ent.low.gen_pl) if ent_ok else None
    mph = metric_phrase(m.name, m.type) if m is not None else None
    fs.ctx.update(entities_gen=ent.low.gen_pl if ent_ok else None, metric=mph, entity_forms=forms)
    sk = _skip(d)
    fs.add("count", rv.n, "count", f"Всего строк — {rv.n}", None, "Строк данных в таблице.",
           prov={"op": "count", "what": "rows", "skip": sk})
    if m is not None and rv.top_share is not None and rv.n > rv.top_n:
        # суммируемая неотрицательная метрика: доля топ-10 и итог остальных
        top = rv.top_share
        rest_n = rv.n - rv.top_n
        rest_v = (rv.total or 0) - (rv.top_sum or 0)
        unit = m.unit_text
        what = mph.nom if mph is not None else m.name
        pt = {"op": "topn", "col": m.j, "n": rv.top_n, "skip": sk, "scale": m.scale,
              "total_row": _total_row(d, m)}
        fs.add("top_n", rv.top_n, "count", f"Топ-{rv.top_n}", None, f"{rv.top_n} крупнейших из {rv.n} по колонке «{m.name}».",
               prov={"op": "count", "what": "value", "value": rv.top_n})
        fs.add("top_share", round_pct(top), "share", f"Топ-{rv.top_n} — {fmt_pct(top)}%", "%",
               f"{what} {rv.top_n} крупнейших из {rv.n}: {fmt_value(rv.top_sum or 0, unit)} из "
               f"{fmt_value(rv.total or 0, unit)}. {_by(m)}", prov={**pt, "what": "share", "tol": 0.51})
        fs.add("rest_share", round_pct(100 - top), "share", f"Остальные {rest_n} — {fmt_pct(100 - top)}%", "%",
               f"Остальные {rest_n} дают {fmt_value(rest_v, unit)}.", prov={**pt, "what": "rest", "tol": 0.51})
        fs.add("rest_value", rest_v, "total", f"Остальные {rest_n} — {fmt_value(rest_v, unit)}", unit,
               "Итог строк вне топа.", prov={**pt, "what": "rest_value"})
        fs.add("rest_count", rest_n, "count", f"Остальные {rest_n}", None, "Строки, собранные в итог.",
               prov={"op": "count", "what": "rows", "skip": sk, "minus": rv.top_n})
        who = f"Остальные {count_words(rest_n, *(forms or ('строка', 'строки', 'строк')))}"
        big, big_v, big_row = _biggest(d, m, ent if ent_ok else None)
        if big:
            fs.add("biggest", big_v, "max", big, unit, "Естественно большое значение строки (не выброс).",
                   prov={"op": "cell", "row": big_row, "col": m.j})
        fs.ctx["caption"] = _short([f"{who} — {fmt_value(rest_v, unit)}, {fmt_pct(100 - top)}%.", big])
        return fs
    if m is not None and rv.values and rv.values[0] is not None:
        # рейтинг, средний чек, прибыль с убытками: лидер по значению, без долей; строки без подписи — без имени
        leader = rv.labels[0] if rv.label is not None else ""
        lv = float(rv.values[0])
        unit = m.unit_text
        # длительность («Дней открыт», «Часов в пути») — «дольше всех», а не «первое место по числу дней открыт»
        fs.ctx.update(leader=leader, labels=[leader] if leader else [], unit_short=unit,
                      duration=bool(m.time_unit) and not m.additive)
        pd = {"op": "dist", "col": m.j, "skip": sk, "scale": m.scale}
        fs.add("leader_value", lv, "leader", f"{leader or 'Наибольшее'} — {fmt_value(lv, unit)}", unit,
               f"Наибольшее значение по колонке «{m.name}»" + (f" — у строки «{leader}»." if leader else "."),
               prov={**pd, "stat": "max"})
        if rv.negatives:
            fs.add("negatives", rv.negatives, "count", f"{rv.negatives} в минусе", None,
                   f"Отрицательных значений в колонке «{m.name}»: {rv.negatives}.", prov={**pd, "stat": "neg"})
        if rv.n > rv.top_n:
            fs.add("top_n", rv.top_n, "count", f"Первые {rv.top_n}", None, "Строк на слайде.",
                   prov={"op": "count", "what": "value", "value": rv.top_n})
        fs.ctx["caption"] = f"Строки упорядочены по колонке «{m.name}»" + (
            f"; показаны первые {rv.top_n} из {rv.n}." if rv.n > rv.top_n else ".")
        return fs
    grp = [j for j in d.dims if j != d.label and 1 < d.cols[j].distinct < rv.n]
    if grp:
        j = grp[0]
        gp = phrase(d.cols[j].name)
        k = d.cols[j].distinct
        # группа-прилагательное («Ответственный») не склоняется как существительное — без «из 4 …»
        adjective = bool(re.search(r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие)$", d.cols[j].name.strip().lower()))
        if gp is not None and gp.sure and not adjective:
            fs.add("groups", k, "count", f"«{d.cols[j].name}»: {count_words(k, 'значение', 'значения', 'значений')}",
                   None, f"Разных значений в колонке «{d.cols[j].name}».",
                   prov={"op": "count", "what": "groups", "by": j, "skip": _skip(d)})
            fs.ctx["group_forms"] = (gp.low.gen, gp.low.gen_pl)
    if rv.pages > 1:
        fs.add("top_n", min(rv.n, 10), "count", f"Первые {min(rv.n, 10)}", None, "Строк на слайде.",
               prov={"op": "count", "what": "value", "value": min(rv.n, 10)})
        fs.ctx["caption"] = f"Показаны первые {min(rv.n, 10)} строк из {rv.n}."
    return fs


# ── ключевые показатели ───────────────────────────────────────────────────────────────────────────────────────────────
def _change_value(ch: float, unit: Optional[str]) -> float:
    return round_pct(abs(ch)) if unit == "%" else round(abs(ch), 1)


def _kpi_name(it: KpiItem) -> str:
    """Название показателя без единицы: «Принято на 1 курс, чел.» → «Принято на 1 курс»."""
    return split_unit(it.label)[0] or it.label


def _kpi_kind(it: KpiItem) -> Optional[str]:
    """Род величины: единица из подписи («, чел.»), иначе из значения («млрд ₽»); множитель не важен (млн/млрд ₽)."""
    u = split_unit(it.label)[1] or it.unit
    if not u:
        return None
    return re.sub(r"^(?:тыс\.|млн|млрд|трлн)\s*", "", u.strip())


def _scaled(it: KpiItem) -> Optional[float]:
    q = quantity(it.value_text.replace("\u00a0", " "))
    return q.full if q is not None else it.value


def _related(a: KpiItem, b: KpiItem, items: list[KpiItem]) -> bool:
    """Величины разного рода сравнимы по темпу, если в той же таблице есть их отношение (средний чек = выручка /
    клиенты): тогда «выручка растёт быстрее клиентов» — содержательный вывод, а не сравнение людей с деньгами."""
    va, vb = _scaled(a), _scaled(b)
    if not va or not vb:
        return False
    for c in items:
        if c is a or c is b:
            continue
        vc = _scaled(c)
        if vc and (abs(va / vb - vc) <= 0.02 * abs(vc) or abs(vb / va - vc) <= 0.02 * abs(vc)):
            return True
    return False


def _comparable(a: KpiItem, b: KpiItem, items: list[KpiItem]) -> bool:
    if a.change_unit != b.change_unit:
        return False
    ka, kb = _kpi_kind(a), _kpi_kind(b)
    if ka is not None and ka == kb:
        return True
    return _related(a, b, items)


def _kpi_prov(it: KpiItem) -> Optional[dict]:
    """Изменение показателя: ячейка колонки изменения или пересчёт из текущей и прошлой ячейки (округлено как в факте)."""
    p = it.prov_change
    if p is None:
        return None
    return {**p, "tol": 0.51 if it.change_unit == "%" else 0.051}


def _kpi(d: Data) -> FactSet:
    fs = FactSet()
    kv = d.kpi
    if kv is None or not kv.items:
        return fs
    items = kv.items
    names = [_kpi_name(it) for it in items]
    with_ch = [k for k, it in enumerate(items) if it.change is not None]
    # пара для вывода: первый показатель с изменением и следующий того же рода; иначе — самое сильное изменение
    ia, ib = (with_ch[0] if with_ch else 0), None
    if with_ch:
        ib = next((k for k in with_ch[1:] if _comparable(items[ia], items[k], items)), None)
        if ib is None:
            pct = [k for k in with_ch if items[k].change_unit == "%"] or with_ch
            ia = max(pct, key=lambda k: (abs(items[k].change or 0), -k))
            pairs = [(x, y) for x in with_ch for y in with_ch if x < y and _comparable(items[x], items[y], items)]
            if pairs:
                ia, ib = max(pairs, key=lambda xy: (abs(items[xy[0]].change or 0) + abs(items[xy[1]].change or 0), -xy[0]))
    a = items[ia]
    pa = phrase(names[ia])
    fs.ctx.update(a_name=names[ia], a_gender=pa.gender if pa else "m", a_value_text=a.value_text,
                  a_participle=is_participle(names[ia]), labels=[it.label for it in items] + names)
    for k, it in enumerate(items):
        fs.add(f"value_{k}", it.value, "total", f"{it.label} — {it.value_text}", it.unit,
               f"{it.label}: {it.value_text}" + (f" ({kv.period})" if kv.period else "") + ".", prov=it.prov_value)
    fs.add("kpi_value", a.value, "total", f"{a.label} — {a.value_text}", a.unit, f"{a.label}: {a.value_text}.",
           prov=a.prov_value)
    since = f" к {kv.prev_period}" if kv.prev_period else ""
    if a.change is not None:
        fs.ctx.update(a_signed=a.change, a_unit=a.change_unit)
        fs.add("kpi_a", _change_value(a.change, a.change_unit), "change",
               f"{a.label}: {fmt_signed(a.change, a.change_unit or '')}", a.change_unit,
               f"{a.label} — {a.value_text}" + (f", было {a.prev_text}" if a.prev_text else "") +
               f": {fmt_signed(a.change, a.change_unit or '')}{since}.", prov=_kpi_prov(a))
        if ib is not None:
            b = items[ib]
            pb = phrase(names[ib])
            if pb is not None and pb.sure:
                b_gen = f"числа {pb.low.gen_pl}" if pb.gender == "pl" and names[ib].lower() not in _MASS_PL else pb.low.gen
            else:
                b_gen = names[ib] if pb is not None else None
            fs.ctx.update(b_name=names[ib], b_gender=pb.gender if pb else "m", b_gen=b_gen, b_signed=b.change,
                          b_unit=b.change_unit, b_participle=is_participle(names[ib]))
            fs.add("kpi_b", _change_value(b.change, b.change_unit), "change",
                   f"{b.label}: {fmt_signed(b.change, b.change_unit or '')}", b.change_unit,
                   f"{b.label} — {b.value_text}" + (f", было {b.prev_text}" if b.prev_text else "") +
                   f": {fmt_signed(b.change, b.change_unit or '')}{since}.", prov=_kpi_prov(b))
    shown = [ia] + ([ib] if ib is not None else [])
    parts = []
    for k in shown:
        it = items[k]
        s_ = f"{lower_first(names[k]) if parts else names[k]} — {it.value_text}"
        if it.change is not None:
            s_ += f" ({fmt_signed(it.change, it.change_unit or '')})"
        parts.append(s_)
    cap = [", ".join(parts) + "."]
    if kv.prev_period:
        cap.append(f"Сравнение с {kv.prev_period}.")
    fs.ctx["caption"] = _short(cap)
    return fs


# ── взаимосвязь ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _relationship(d: Data) -> FactSet:
    fs = FactSet()
    xy = d.xy
    if xy is None:
        return fs
    xp, yp = phrase(xy.x.name), metric_phrase(xy.y.name, xy.y.type)
    r_show = max(-0.99, min(0.99, round(xy.r, 2)))  # r = 1 на реальных данных не бывает: не больше 0,99
    fs.ctx.update(x=re.sub(r"\s*[,(].*$", "", xy.x.name), y=re.sub(r"\s*[,(].*$", "", xy.y.name),
                  r_signed=r_show, labels=[xy.x.name, xy.y.name], x_counter=is_counter(xy.x.name),
                  y_counter=is_counter(xy.y.name))
    causal = xy.driver and (xy.x.unit_text or "") != (xy.y.unit_text or "")
    px = {"x": xy.x.j, "y": xy.y.j, "skip": _skip(d), "sx": xy.x.scale, "sy": xy.y.scale}
    if abs(xy.r) >= 0.5 and xy.slope and causal:
        b = xy.slope
        bv = round(b, 1) if abs(b) >= 0.95 else round(b, 2)
        fs.add("slope", abs(bv), "change", f"{fmt_signed(bv)} на единицу «{xy.x.name}»", xy.y.unit_text,
               f"Наклон прямой: {xy.y.name} ≈ {fmt_num(xy.intercept, 1)} {'+' if b >= 0 else '−'} "
               f"{fmt_num(abs(bv), 2)} × {xy.x.name}.", prov={**px, "op": "slope"})
        fs.ctx.update(slope=bv, each=each_unit(xy.x.unit_text), x_gen=xp.low.gen if xp is not None and xp.sure else None,
                      y_dat=yp.low.dat if yp is not None and yp.sure else None)
    fs.add("r", abs(r_show), "count", f"r = {fmt_num(r_show, 2)}", None,
           f"Коэффициент корреляции Пирсона по {count_words(xy.n, 'паре', 'парам', 'парам')} значений «{xy.x.name}» и "
           f"«{xy.y.name}».", prov={**px, "op": "corr"})
    fs.add("points", xy.n, "count", count_words(xy.n, "точка", "точки", "точек"), None, "Строк с обоими значениями.",
           prov={**px, "op": "pairs"})
    strength = "сильная" if abs(xy.r) >= 0.7 else "умеренная" if abs(xy.r) >= 0.3 else "слабая"
    fs.ctx["caption"] = f"{upper_first(count_words(xy.n, 'точка', 'точки', 'точек'))}; связь {strength}, r = {fmt_num(r_show, 2)}."
    return fs
