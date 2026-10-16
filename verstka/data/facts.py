"""Факты для заголовка-вывода (описание решения §2.6): числа, посчитанные из подготовленных данных.

Изменение первое → последнее и год к году (%, п.п., «в N раз»), лидер и его доля, самый быстрый рост, доля топ-N,
медиана и перцентили («80% — не дольше 2 часов»), выбросы, пропущенные периоды, связь (r). Каждый факт — `HeadlineFact`
с числом, каким его пишет заголовок, и объяснением, откуда оно («Сентябрь 2026 к сентябрю 2025: 423 млн ₽ — на 23%
больше. Посчитано по колонке «Выручка».»). Рядом — слова для шаблона (`FactSet.ctx`: лидер, период, сущность, падежи),
чтобы заголовок (`headline.compose`) только расставил их по-русски."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from verstka.data.aggregate import CatView, Data, Measure, TimeView
from verstka.data.headline import (
    PERIOD_WORDS, Phrase, count_words, fmt_num, fmt_pct, fmt_signed, fmt_value, is_counter, join_and, lower_first,
    metric_phrase, period_dative, period_text, phrase, plural, round_pct, upper_first,
)
from verstka.schemas.data import FactKind, HeadlineFact, TaskKind

__all__ = ["FactSet", "facts_for", "subject_of", "plain_headline"]


@dataclass
class FactSet:
    facts: list[HeadlineFact] = field(default_factory=list)
    ctx: dict[str, Any] = field(default_factory=dict)

    def add(self, fid: str, value: float, kind: FactKind, text: str, unit: Optional[str] = None, explain: str = "") -> None:
        self.facts.append(HeadlineFact(id=fid, text=text, value=float(value), unit=unit, kind=kind, explain=explain))

    def get(self, fid: str) -> Optional[HeadlineFact]:
        return next((f for f in self.facts if f.id == fid), None)


def _by(m: Measure) -> str:
    return f"Посчитано по колонке «{m.name}»."


_MASS_PL = {"продажи", "расходы", "доходы", "затраты", "средства", "деньги", "инвестиции", "поступления", "платежи"}


def subject_of(name: str, mtype: str = "number") -> tuple[str, str, Optional[Phrase]]:
    """Подлежащее для заголовка: «Выручка» (ж.), «NPS» (м.), «Клиентов» → «Число клиентов» (ср.)."""
    p = metric_phrase(name, mtype)
    if is_counter(name) and p is not None:
        return p.nom, p.gender, p
    return name, (p.gender if p else "m"), p


def _file_stem(d: Data) -> str:
    s = re.sub(r"\.[A-Za-z0-9]+$", "", d.profile.file or "").strip()
    if d.profile.sheet:
        s = f"{s} · {d.profile.sheet}" if s else d.profile.sheet
    return upper_first(s) if s else "Данные"


def plain_headline(task: TaskKind, d: Data) -> str:
    """Заголовок-описание (тема, не вывод): «Выручка по месяцам», «Выручка по регионам», «Список клиентов»."""
    m = d.main
    if task == "dynamics" and m is not None and d.time is not None:
        f = d.time.freq
        by = {"month": "месяцам", "quarter": "кварталам", "year": "годам", "week": "неделям", "day": "дням",
              "hour": "часам"}.get(f)
        if by:
            return f"{m.name} по {by}"
    if task == "comparison" and m is not None and d.cats is not None:
        p = phrase(d.cats.dim)
        if p is not None and p.sure:
            return f"{m.name} по {p.low.dat_pl}"
    if task == "reference" and d.entity:
        p = phrase(d.entity)
        if p is not None and p.sure:
            return f"Список {p.low.gen_pl}"
    return _file_stem(d)


def facts_for(task: TaskKind, d: Data) -> FactSet:
    fs = {
        "dynamics": _dynamics, "comparison": _comparison, "shares": _shares, "distribution": _distribution,
        "reference": _reference, "kpi": _kpi, "relationship": _relationship,
    }[task](d)
    fs.ctx.setdefault("plain", plain_headline(task, d))
    return fs


# ── динамика ──────────────────────────────────────────────────────────────────────────────────────────────────────────
_LAG = {"month": 12, "quarter": 4, "week": 52, "year": 1, "day": 365, "hour": 24}


def _dat_full(iso: str) -> str:
    """«сентябрю 2025», «III кв. 2025», «2025 году»."""
    t = period_text(iso)
    if re.match(r"^\d{4}-\d{2}$", iso):
        from verstka.data.headline import month_name

        return f"{month_name(int(iso[5:7]), 'dat')} {iso[:4]}"
    if re.match(r"^\d{4}$", iso):
        return f"{iso} году"
    return t


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


def _dynamics(d: Data) -> FactSet:
    fs = FactSet()
    tv = d.time
    m = d.main
    if tv is None:
        return fs
    vals = _series_values(tv)
    idx = [i for i, v in enumerate(vals) if v is not None]
    m = tv.measure if m is None else m
    subj, gender, ph = subject_of(m.name if tv.measure.j >= 0 else "Число строк", m.type)
    pw = PERIOD_WORDS.get(tv.freq, PERIOD_WORDS["irregular"])
    unit = m.unit_text if tv.measure.j >= 0 else None
    level = m.level or m.type == "percent"
    fs.ctx.update(subject=subj, gender=gender, metric=ph or phrase("Значение"), freq=tv.freq, unit_short=unit,
                  level=level)
    if not idx:
        return fs
    F, L = idx[0], idx[-1]
    first, last = float(vals[F]), float(vals[L])  # type: ignore[arg-type]
    pl, pf = tv.periods[L], tv.periods[F]
    fs.add("last", round(last, 2) if abs(last) < 100 else round(last), "max" if last >= max(vals[i] for i in idx) else "total",
           f"{period_text(pl)}: {fmt_value(last, unit)}", unit, f"Последнее значение — {period_text(pl)}. {_by(m)}")
    hi = max(idx, key=lambda i: (vals[i], i))
    lo = min(idx, key=lambda i: (vals[i], -i))
    fs.add("max", vals[hi], "max", f"Максимум — {fmt_value(vals[hi], unit)} ({period_text(tv.periods[hi])})", unit,
           f"Наибольшее значение ряда. {_by(m)}")
    fs.add("min", vals[lo], "min", f"Минимум — {fmt_value(vals[lo], unit)} ({period_text(tv.periods[lo])})", unit,
           f"Наименьшее значение ряда. {_by(m)}")
    # пропуски
    missing = tv.missing
    if missing:
        names = ", ".join(period_text(p) for p in missing[:4]) + (" …" if len(missing) > 4 else "")
        fs.add("gaps", len(missing), "gap", f"Нет данных: {names}", None,
               f"{count_words(len(missing), pw[0], pw[1], pw[2]).capitalize()} без значения: {names}. "
               f"На графике — разрывы, а не ноль.")
    # изменение
    lag = _LAG.get(tv.freq)
    base_i = None
    yoy = False
    if lag and L - lag >= F and vals[L - lag] is not None and tv.freq != "irregular":
        base_i, yoy = L - lag, True
    elif L > F:
        base_i = F
    caption_parts = []
    if base_i is not None:
        base = float(vals[base_i])  # type: ignore[arg-type]
        pb = tv.periods[base_i]
        if level:
            delta = last - base
            du = "п.п." if m.type == "percent" else "п."
            fs.ctx["delta"] = delta
            fs.add("change", round(abs(delta), 1), "change", f"{fmt_signed(delta, du)} к {_dat_full(pb)}", du,
                   f"{upper_first(period_text(pl))} к {_dat_full(pb)}: {fmt_value(last, unit)} против "
                   f"{fmt_value(base, unit)} — {fmt_signed(delta, du)}. {_by(m)}")
            caption_parts.append(
                f"{subj}: {period_text(pf)} — {fmt_value(first, unit)}, {period_text(pl)} — {fmt_value(last, unit)} "
                f"({fmt_signed(last - first, du)} за {count_words(L - F, pw[0], pw[1], pw[2])}).")
        elif base > 0 and last >= 0:
            pct = (last / base - 1) * 100
            fs.ctx["delta"] = pct
            more = "больше" if pct >= 0 else "меньше"
            fs.add("change", round_pct(abs(pct)), "change",
                   f"{fmt_signed(round_pct(pct), '%')} {'год к году' if yoy else 'за период'}", "%",
                   f"{upper_first(period_text(pl))} к {_dat_full(pb)}: {fmt_value(last, unit)} — на {fmt_pct(abs(pct))}% "
                   f"{more}. {_by(m)}")
            ratio = last / base
            if ratio >= 2:
                fs.add("ratio", round(ratio, 1), "change", f"в {fmt_num(round(ratio, 1), 1)} раза", "раз",
                       f"{fmt_value(last, unit)} против {fmt_value(base, unit)}. {_by(m)}")
            if yoy:
                when = period_dative(pl) or "за год"
            else:
                span = L - F
                when = f"за {count_words(span, pw[0], pw[1], pw[2])}" if tv.freq != "irregular" else "за период"
                fs.add("span", span, "count", f"{count_words(span, pw[0], pw[1], pw[2])}", None,
                       f"От {period_text(pf)} до {period_text(pl)}.")
            fs.ctx["when"] = when
            caption_parts.append(
                f"С {_gen_period(pf)} по {period_text(pl)} {lower_first(subj)} "
                f"{'вырос' if last >= first else 'снизил'}{_past_end(gender, last >= first)} "
                f"с {fmt_value(first, unit)} до {fmt_value(last, unit)}.")
    if missing:
        caption_parts.append(
            f"За {join_and([period_text(p) for p in missing[:3]])}{' и другие' if len(missing) > 3 else ''} данных нет — "
            f"на графике разрывы, а не ноль.")
    if tv.resampled and tv.note:
        caption_parts.append(upper_first(tv.note) + ".")
    fs.ctx["caption"] = " ".join(caption_parts) or None
    return fs


def _past_end(gender: str, grow: bool) -> str:
    if grow:
        return {"m": "", "f": "ла", "n": "ло", "pl": "ли"}[gender]
    return {"m": "ся", "f": "ась", "n": "ось", "pl": "ись"}[gender]


def _gen_period(iso: str) -> str:
    """«января 2025», «IV кв. 2024», «2025 года»."""
    from verstka.data.headline import month_name

    if re.match(r"^\d{4}-\d{2}$", iso):
        return f"{month_name(int(iso[5:7]), 'gen')} {iso[:4]}"
    if re.match(r"^\d{4}$", iso):
        return f"{iso} года"
    return period_text(iso)


# ── сравнение ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _growth_measure(cv: CatView) -> Optional[Measure]:
    for mm in cv.extra_measures:
        if mm.change and any(v is not None for v in cv.extra.get(mm.name, [])):
            return mm
    return None


def _comparison(d: Data) -> FactSet:
    fs = FactSet()
    cv = d.cats
    if cv is None:
        return fs
    m = cv.measure
    unit = cv.unit
    real = [k for k, lab in enumerate(cv.labels) if not (cv.others and k == cv.n - 1)]
    leader_k = real[0] if cv.ranked else max(real, key=lambda k: (cv.values[k], -k))
    leader = cv.labels[leader_k]
    lv = cv.values[leader_k]
    if m is not None:
        ph = metric_phrase(m.name, m.type)
    else:
        ent = phrase(d.entity) if d.entity else None
        ph = Phrase(ent.gen_pl, ent.gen_pl, ent.dat_pl, ent.gen_pl, ent.dat_pl, ent.nom_pl, "pl") \
            if ent is not None and ent.sure else None
    fs.ctx.update(leader=leader, metric=ph, unit_short=unit)
    name = m.name if m is not None else "Число строк"
    shares = cv.shares
    caption = []
    if shares is not None and cv.total:
        p = shares[leader_k]
        if p >= 15:
            fs.add("leader_share", round_pct(p), "share", f"{leader} — {fmt_pct(p)}%", "%",
                   f"{leader} — {fmt_value(lv, unit)} из {fmt_value(cv.total, unit)}, это {fmt_pct(p)}%. "
                   f"Посчитано по колонке «{name}».")
        caption.append(f"{leader} — {fmt_value(lv, unit)} из {fmt_value(cv.total, unit)}.")
    fs.add("leader_value", lv, "leader", f"{leader} — {fmt_value(lv, unit)}", unit,
           f"Наибольшее значение — у категории «{leader}». Посчитано по колонке «{name}».")
    last_k = real[-1] if cv.ranked else min(real, key=lambda k: (cv.values[k], k))
    if last_k != leader_k and not cv.others:
        fs.add("last_value", cv.values[last_k], "min", f"{cv.labels[last_k]} — {fmt_value(cv.values[last_k], unit)}",
               unit, f"Наименьшее значение — у категории «{cv.labels[last_k]}».")
        fs.ctx["last_label"] = cv.labels[last_k]
        lo = cv.values[last_k]
        if lo > 0 and lv / lo >= 2:
            r = round(lv / lo, 1)
            fs.add("spread", r, "max", f"Разрыв — в {fmt_num(r, 1)} раза", "раз",
                   f"{leader} — {fmt_value(lv, unit)}, {cv.labels[last_k]} — {fmt_value(lo, unit)}.")
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
                fs.add("growth_max", round_pct(gv[gk]) if gu == "%" else gv[gk], "max",
                       f"{gl}: {fmt_signed(gv[gk], gu)}", gu or None,
                       f"Самый быстрый рост — {gl}: {fmt_signed(gv[gk], gu)}. Посчитано по колонке «{g.name}».")
                caption.append(f"{gl}: {fmt_signed(gv[gk], gu)} — быстрее всех.")
    neg = cv.negatives
    if neg:
        dp = phrase(cv.dim)
        forms = (dp.low.nom, dp.low.gen, dp.low.gen_pl) if dp is not None and dp.sure and dp.gender != "pl" else \
            ("категория", "категории", "категорий")
        fs.ctx["neg_forms"] = forms
        fs.add("negatives", neg, "count", f"{count_words(neg, *forms)} в минусе", None,
               f"Отрицательные значения: {', '.join(cv.labels[k] for k in real if cv.values[k] < 0)}.")
    if cv.others:
        caption.append(f"Остальные {count_words(cv.others, 'категория', 'категории', 'категорий')} собраны в одну "
                       f"строку.")
    fs.ctx["caption"] = " ".join(caption) or None
    return fs


# ── доли ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _whole_phrase(d: Data, parts: Optional[Measure]) -> tuple[Optional[Phrase], bool]:
    """Целое, долю которого показывают: «выручки» (деньги рядом с долями), «рынка» (из «Доля рынка»)."""
    money = next((m for m in d.measures if m.additive and m is not parts and m.type == "money"), None)
    other = money or next((m for m in d.measures if m.additive and m is not parts), None)
    if other is not None:
        p = phrase(other.name)
        if p is not None:
            return p, other.type == "money"
    if parts is not None:
        rest = re.sub(r"^\s*(?:доля|доли|удельный вес|процент)\s*", "", parts.name, flags=re.I).strip()
        if rest and rest != parts.name:
            # «Доля рынка» — дополнение уже в родительном
            return Phrase(rest, rest, rest, rest, rest, rest, "f", sure=False), False
    return None, False


def _shares(d: Data) -> FactSet:
    fs = FactSet()
    parts = d.parts_measure
    cv = d.cat_view(parts) if parts is not None else d.cats
    if cv is None:
        return fs
    if parts is not None and cv.values:
        vals = cv.values
        s = sum(vals) or 1.0
        scale = 100.0 / s if 0.95 <= s <= 1.05 else 1.0
        shares = [v * scale for v in vals]
    else:
        shares = cv.shares or []
    if not shares:
        return fs
    whole, money = _whole_phrase(d, parts)
    leader = cv.labels[0]
    fs.ctx.update(leader=leader, whole=whole, money=money)
    p = shares[0]
    fs.add("leader_share", round_pct(p), "share", f"{leader} — {fmt_pct(p)}%", "%",
           f"{leader} — {fmt_pct(p)}%, больше любой другой части: "
           + ", ".join(f"{lower_first(lab) if k else lab} — {fmt_pct(v)}%" for k, (lab, v) in
                       enumerate(zip(cv.labels[1:], shares[1:]), start=1)) + ".")
    if len(shares) >= 2:
        fs.add("second_share", round_pct(shares[1]), "share", f"{cv.labels[1]} — {fmt_pct(shares[1])}%", "%",
               "Вторая по величине доля.")
        top2 = shares[0] + shares[1]
        fs.add("top2_share", round_pct(top2), "share", f"Две крупнейшие части — {fmt_pct(top2)}%", "%",
               f"{cv.labels[0]} и {lower_first(cv.labels[1])} вместе.")
    total = sum(shares)
    fs.add("total_share", round(total), "total", f"Сумма долей — {fmt_pct(total)}%", "%",
           "Части одного целого: сумма долей ≈ 100%.")
    fs.ctx["caption"] = ", ".join(f"{lab} — {fmt_pct(v)}%" for lab, v in zip(cv.labels, shares)) + "."
    return fs


# ── распределение ─────────────────────────────────────────────────────────────────────────────────────────────────────
_NICE_MIN = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 360, 480, 720, 1080, 1440, 2880, 4320, 10080]
_TO_MIN = {"мин": 1.0, "мин.": 1.0, "ч": 60.0, "ч.": 60.0, "дн.": 1440.0, "дн": 1440.0, "с": 1 / 60}


def _nice_ceil(x: float) -> float:
    if x <= 0:
        return 0.0
    e = 10 ** math.floor(math.log10(x))
    for b in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8, 10):
        if b * e >= x - 1e-9:
            return b * e
    return 10 * e


def _duration_text(minutes: float) -> tuple[str, float, str]:
    """120 → («2 часа», 2, «ч»); 45 → («45 минут», 45, «мин»); 2880 → («2 дня», 2, «дн.»)."""
    if minutes >= 1440 and minutes % 1440 == 0:
        k = minutes / 1440
        return f"{fmt_num(k)} {plural(k, 'день', 'дня', 'дней')}", k, "дн."
    if minutes >= 60 and minutes % 60 == 0:
        k = minutes / 60
        if k == 1:
            return "час", 1, "ч"
        return f"{fmt_num(k)} {plural(k, 'час', 'часа', 'часов')}", k, "ч"
    if minutes < 1:
        s = minutes * 60
        return f"{fmt_num(s)} {plural(s, 'секунду', 'секунды', 'секунд')}", s, "с"
    return f"{fmt_num(minutes)} {plural(minutes, 'минуту', 'минуты', 'минут')}", minutes, "мин"


def _duration_gen(minutes: float) -> str:
    """«600 минут», «2 часов» — после «больше»."""
    if minutes >= 60 and minutes % 60 == 0 and minutes < 1440:
        k = minutes / 60
        return f"{fmt_num(k)} {plural(k, 'часа', 'часов', 'часов')}"
    return f"{fmt_num(minutes)} {plural(minutes, 'минуты', 'минут', 'минут')}"


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


def _floor_round(threshold: float, above: float) -> float:
    """Круглая граница выбросов: наибольшее «круглое» число ≤ threshold и > above (655 при максимуме 513 → 600)."""
    mag = 10 ** math.floor(math.log10(threshold)) if threshold > 0 else 1
    for step in (mag, mag / 2, mag / 10, mag / 20, mag / 100, 1):
        t = math.floor(threshold / step) * step
        if t > above:
            return float(t)
    return float(above)


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
    fs.ctx.update(entities_gen=ent.low.gen_pl if ent_ok else None, unit_short=unit)
    med = float(np.median(x))
    fs.add("median", round(med, 1) if abs(med) < 100 else round(med), "median", f"Медиана — {fmt_value(med, unit)}", unit,
           f"Половина значений меньше {fmt_value(med, unit)}. {_by(m)}")
    p80 = float(np.percentile(x, 80))
    to_min = _TO_MIN.get((m.time_unit or "").lower()) if m.time_unit else None
    duration = to_min is not None
    if duration:
        pm = p80 * to_min  # в минутах
        t_min = next((v for v in _NICE_MIN if v >= pm - 1e-9), _nice_ceil(pm))
        t = t_min / to_min
        text, tv, tu = _duration_text(t_min)
    else:
        t = _nice_ceil(p80) if p80 > 0 else p80
        text, tv, tu = fmt_value(t, unit), t, unit
    within = int((x <= t + 1e-9).sum())
    share = math.floor(within / n * 100) if n else 0
    fs.ctx.update(duration=duration, threshold_text=text, predicate=_predicate(m.name) if duration else None)
    fs.add("share_within", share, "percentile", f"{share}% — не больше {fmt_value(t, unit)}", "%",
           f"{within} из {count_words(n, *ent_forms)} — не больше {fmt_value(t, unit)}. {_by(m)}")
    fs.add("threshold", tv, "percentile", text, tu,
           f"Граница — {fmt_value(t, unit)}: 80-й перцентиль {fmt_value(p80, unit)}, округлено вверх.")
    fs.add("p80", round(p80, 1) if abs(p80) < 100 else round(p80), "percentile",
           f"80-й перцентиль — {fmt_value(p80, unit)}", unit, f"80% значений не больше этого числа. {_by(m)}")
    fs.add("count", n, "count", count_words(n, *ent_forms), None, "Строк с числом в колонке.")
    med_txt = _duration_text(med * to_min)[0] if duration and float(med * to_min).is_integer() else fmt_value(med, unit)
    if duration and med_txt.endswith(("минуту", "секунду")):
        med_txt = med_txt[:-1] + "а"  # «медиана — 21 минута»
    caption = [f"Медиана — {med_txt}."]
    if dv.outliers:
        k = len(dv.outliers)
        thr = _floor_round(min(dv.outliers), float(dv.inliers.max()) if dv.inliers.size else 0)
        thr_txt = _duration_gen(thr * to_min) if duration else fmt_value(thr, unit)
        fs.add("outliers", k, "outliers", f"{count_words(k, 'выброс', 'выброса', 'выбросов')} больше {thr_txt}", None,
               f"Значения {', '.join(fmt_num(v) for v in dv.outliers[:5])} — далеко от остальных (правило Тьюки с отрывом).")
        fs.add("outlier_bound", thr, "outliers", f"больше {thr_txt}", unit, "Граница выбросов, округлённая вниз.")
        caption.append(f"{upper_first(count_words(k, *ent_forms))} — больше {thr_txt}: это выбросы, они отмечены "
                       f"отдельно и не вошли в интервалы.")
    fs.ctx["caption"] = " ".join(caption)
    return fs


# ── справочник ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _reference(d: Data) -> FactSet:
    fs = FactSet()
    rv = d.ref
    m = rv.measure
    ent = phrase(d.entity) if d.entity else None
    ent_ok = ent is not None and ent.sure
    fs.ctx.update(entities_gen=ent.low.gen_pl if ent_ok else None, metric=phrase(m.name) if m is not None else None,
                  entity_forms=(ent.low.nom, ent.low.gen, ent.low.gen_pl) if ent_ok else None)
    if m is not None and m.additive and rv.top_share is not None and rv.n > rv.top_n:
        top = rv.top_share
        rest_n = rv.n - rv.top_n
        rest_v = (rv.total or 0) - (rv.top_sum or 0)
        unit = m.unit_text
        fs.add("top_n", rv.top_n, "count", f"Топ-{rv.top_n}", None, f"{rv.top_n} крупнейших из {rv.n} по колонке «{m.name}».")
        fs.add("top_share", round_pct(top), "share", f"Топ-{rv.top_n} — {fmt_pct(top)}%", "%",
               f"Выручка {rv.top_n} крупнейших из {rv.n}: {fmt_value(rv.top_sum or 0, unit)} из "
               f"{fmt_value(rv.total or 0, unit)}. {_by(m)}" if m.type == "money" else
               f"{rv.top_n} крупнейших из {rv.n}: {fmt_value(rv.top_sum or 0, unit)} из {fmt_value(rv.total or 0, unit)}. "
               f"{_by(m)}")
        fs.add("rest_share", round_pct(100 - top), "share", f"Остальные {rest_n} — {fmt_pct(100 - top)}%", "%",
               f"Остальные {rest_n} дают {fmt_value(rest_v, unit)}.")
        fs.add("rest_count", rest_n, "count", f"Остальные {rest_n}", None, "Строки, собранные в итог.")
        who = f"Остальные {count_words(rest_n, *(fs.ctx['entity_forms'] or ('строка', 'строки', 'строк')))}"
        fs.ctx["caption"] = f"{who} дают {fmt_value(rest_v, unit)} — {fmt_pct(100 - top)}%."
        fs.add("count", rv.n, "count", f"Всего строк — {rv.n}", None, "Строк данных в таблице.")
        return fs
    fs.add("count", rv.n, "count", f"Всего строк — {rv.n}", None, "Строк данных в таблице.")
    grp = [j for j in d.dims if j != d.label and 1 < d.cols[j].distinct < rv.n]
    if grp:
        j = grp[0]
        gp = phrase(d.cols[j].name)
        k = d.cols[j].distinct
        if gp is not None and gp.sure and 1 < k < rv.n:
            fs.add("groups", k, "count", f"{k} значений «{d.cols[j].name}»", None, f"Разных значений в колонке «{d.cols[j].name}».")
            fs.ctx["group_forms"] = (gp.low.gen, gp.low.gen_pl)
    if rv.pages > 1:
        fs.ctx["caption"] = f"Показаны первые {min(rv.n, 10)} строк из {rv.n}."
    return fs


# ── ключевые показатели ───────────────────────────────────────────────────────────────────────────────────────────────
def _kpi(d: Data) -> FactSet:
    fs = FactSet()
    kv = d.kpi
    if kv is None or not kv.items:
        return fs
    a = kv.items[0]
    pa = phrase(a.label)
    fs.ctx.update(a_name=a.label, a_gender=pa.gender if pa else "m", a_value_text=a.value_text)
    for k, it in enumerate(kv.items):
        fs.add(f"value_{k}", it.value, "total", f"{it.label} — {it.value_text}", it.unit,
               f"{it.label}: {it.value_text}" + (f" ({kv.period})" if kv.period else "") + ".")
    fs.add("kpi_value", a.value, "total", f"{a.label} — {a.value_text}", a.unit, f"{a.label}: {a.value_text}.")
    since = f" к {kv.prev_period}" if kv.prev_period else ""
    if a.change is not None:
        fs.ctx.update(a_signed=a.change, a_unit=a.change_unit)
        fs.add("kpi_a", round_pct(abs(a.change)) if a.change_unit == "%" else abs(a.change), "change",
               f"{a.label}: {fmt_signed(a.change, a.change_unit or '')}", a.change_unit,
               f"{a.label} — {a.value_text}" + (f", было {a.prev_text}" if a.prev_text else "") +
               f": {fmt_signed(a.change, a.change_unit or '')}{since}.")
        b = next((it for it in kv.items[1:] if it.change is not None and it.change_unit == a.change_unit), None)
        if b is not None:
            pb = phrase(b.label)
            if pb is not None and pb.sure:
                if pb.gender == "pl" and b.label.lower() not in _MASS_PL:
                    b_gen = f"числа {pb.low.gen_pl}"
                else:
                    b_gen = pb.low.gen
            else:
                b_gen = b.label if pb is not None else None
            fs.ctx.update(b_name=b.label, b_gender=pb.gender if pb else "m", b_gen=b_gen, b_signed=b.change,
                          b_unit=b.change_unit)
            fs.add("kpi_b", round_pct(abs(b.change)) if b.change_unit == "%" else abs(b.change), "change",
                   f"{b.label}: {fmt_signed(b.change, b.change_unit or '')}", b.change_unit,
                   f"{b.label} — {b.value_text}" + (f", было {b.prev_text}" if b.prev_text else "") +
                   f": {fmt_signed(b.change, b.change_unit or '')}{since}.")
    parts = []
    for it in kv.items:
        s = f"{lower_first(it.label) if parts else it.label} — {it.value_text}"
        if it.change is not None:
            s += f" ({fmt_signed(it.change, it.change_unit or '')})"
        parts.append(s)
    fs.ctx["caption"] = ", ".join(parts) + "." + (f" Сравнение с {kv.prev_period}." if kv.prev_period else "")
    return fs


# ── взаимосвязь ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _relationship(d: Data) -> FactSet:
    fs = FactSet()
    xy = d.xy
    if xy is None:
        return fs
    fs.ctx.update(x=xy.x.name, y=xy.y.name, r_signed=round(xy.r, 2))
    fs.add("r", round(abs(xy.r), 2), "count", f"r = {fmt_num(xy.r, 2)}", None,
           f"Коэффициент корреляции Пирсона по {count_words(xy.n, 'паре', 'парам', 'парам')} значений «{xy.x.name}» и "
           f"«{xy.y.name}».")
    fs.add("points", xy.n, "count", count_words(xy.n, "точка", "точки", "точек"), None, "Строк с обоими значениями.")
    strength = "сильная" if abs(xy.r) >= 0.7 else "умеренная" if abs(xy.r) >= 0.3 else "слабая"
    fs.ctx["caption"] = f"{upper_first(count_words(xy.n, 'точка', 'точки', 'точек'))}; связь {strength}, r = {fmt_num(xy.r, 2)}."
    return fs
