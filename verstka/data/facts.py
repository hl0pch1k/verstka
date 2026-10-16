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

from verstka.data.aggregate import NICE_MINUTES, TO_MINUTES, CatView, Data, Measure, TimeView
from verstka.data.words import (
    PERIOD_WORDS, Phrase, count_words, duration_gen, duration_text, file_title, fmt_num, fmt_pct, fmt_signed,
    fmt_value, is_counter, join_and, lower_first, metric_phrase, period_dat_full, period_dative, period_gen,
    period_text, phrase, round_pct, times_word, upper_first,
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


def _metric_title(m: Measure) -> str:
    """Название метрики для темы и объяснений: «Выручка», «Клиентов» → «Число клиентов»; без единицы («, млн ₽»)."""
    return re.sub(r"\s*,[^,]*$", "", subject_of(m.name, m.type)[0]).strip() or m.name


def plain_headline(task: TaskKind, d: Data) -> str:
    """Заголовок-описание (тема, не вывод): «Выручка по месяцам», «Выручка по регионам», «Список клиентов»."""
    m = d.main
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
    hi = max(idx, key=lambda i: (vals[i], i))
    lo = min(idx, key=lambda i: (vals[i], -i))
    fs.add("last", round(last, 2) if abs(last) < 100 else round(last), "max" if hi == L else "total",
           f"{period_text(pl)}: {fmt_value(last, unit)}", unit, f"Последнее значение — {period_text(pl)}. {_by(m)}")
    fs.add("max", vals[hi], "max", f"Максимум — {fmt_value(vals[hi], unit)} ({period_text(tv.periods[hi])})", unit,
           f"Наибольшее значение ряда. {_by(m)}")
    fs.add("min", vals[lo], "min", f"Минимум — {fmt_value(vals[lo], unit)} ({period_text(tv.periods[lo])})", unit,
           f"Наименьшее значение ряда. {_by(m)}")
    missing = tv.missing
    if missing:
        names = ", ".join(period_text(p) for p in missing[:4]) + (" …" if len(missing) > 4 else "")
        fs.add("gaps", len(missing), "gap", f"Нет данных: {names}", None,
               f"{upper_first(count_words(len(missing), pw[0], pw[1], pw[2]))} без значения: {names}. "
               f"На графике — разрывы, а не ноль.")
    lag = _LAG.get(tv.freq)
    base_i = None
    yoy = False
    if lag and L - lag >= F and vals[L - lag] is not None and tv.freq != "irregular":
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
                   f"{fmt_value(base, unit)} — {fmt_signed(delta, du)}. {_by(m)}")
            caption.append(
                f"{subj}: {period_text(pf)} — {fmt_value(first, unit)}, {period_text(pl)} — {fmt_value(last, unit)} "
                f"({fmt_signed(last - first, du)} за {count_words(L - F, pw[0], pw[1], pw[2])}).")
        elif not (base > 0 and last >= 0):
            # убыток, ноль в начале: проценты не считаются — изменение в единицах метрики
            delta = last - base
            fs.ctx.update(delta=delta, abs_change=True)
            fs.add("change", abs(delta) if abs(delta) >= 100 else round(abs(delta), 2), "change",
                   f"{fmt_signed(delta, unit or '')} к {period_dat_full(pb)}", unit,
                   f"{upper_first(period_text(pl))} к {period_dat_full(pb)}: {fmt_value(last, unit)} против "
                   f"{fmt_value(base, unit)}. {_by(m)}")
            span = L - base_i
            fs.ctx["when"] = _yoy_when(tv.freq, pl) if yoy else (
                f"за {count_words(span, pw[0], pw[1], pw[2])}" if tv.freq != "irregular" else "за период")
            if not yoy:
                fs.add("span", span, "count", count_words(span, pw[0], pw[1], pw[2]), None,
                       f"От {period_gen(pf)} до {period_gen(pl)}.")
            caption.append(f"С {period_gen(pf)} по {period_text(pl)}: {fmt_value(first, unit)} → {fmt_value(last, unit)}.")
        else:
            pct = (last / base - 1) * 100
            fs.ctx["delta"] = pct
            more = "больше" if pct >= 0 else "меньше"
            fs.add("change", round_pct(abs(pct)), "change",
                   f"{fmt_signed(round_pct(pct), '%')} {'год к году' if yoy else 'за период'}", "%",
                   f"{upper_first(period_text(pl))} к {period_dat_full(pb)}: {fmt_value(last, unit)} — на "
                   f"{fmt_pct(abs(pct))}% {more}. {_by(m)}")
            ratio = last / base
            if ratio >= 2:
                r = round(ratio, 1)
                fs.add("ratio", r, "change", f"в {fmt_num(r, 1)} {times_word(r)}", "раз",
                       f"{fmt_value(last, unit)} против {fmt_value(base, unit)}. {_by(m)}")
            if yoy:
                when = _yoy_when(tv.freq, pl)
            else:
                span = L - F
                when = f"за {count_words(span, pw[0], pw[1], pw[2])}" if tv.freq != "irregular" else "за период"
                fs.add("span", span, "count", f"{count_words(span, pw[0], pw[1], pw[2])}", None,
                       f"От {period_gen(pf)} до {period_gen(pl)}.")
            fs.ctx["when"] = when
            if abs(last - first) < 1e-9:
                caption.append(f"С {period_gen(pf)} по {period_text(pl)} {lower_first(subj)} держится на уровне "
                               f"{fmt_value(last, unit)}.")
            else:
                caption.append(
                    f"С {period_gen(pf)} по {period_text(pl)} {lower_first(subj)} "
                    f"{'вырос' if last > first else 'снизил'}{_past_end(gender, last > first)} "
                    f"с {fmt_value(first, unit)} до {fmt_value(last, unit)}.")
    if missing:
        caption.append(
            f"За {join_and([period_text(p) for p in missing[:3]])}{' и другие' if len(missing) > 3 else ''} данных нет — "
            f"на графике разрывы, а не ноль.")
    if tv.resampled and tv.note:
        caption.append(upper_first(tv.note) + ".")
    fs.ctx["caption"] = " ".join(caption) or None
    return fs


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
    real = [k for k in range(cv.n) if not (cv.others and k == cv.n - 1)]
    leader_k = max(real, key=lambda k: (cv.values[k], -k))
    leader = cv.labels[leader_k]
    lv = cv.values[leader_k]
    if m is not None:
        ph = metric_phrase(m.name, m.type)
    else:
        ent = phrase(d.entity) if d.entity else None
        ph = Phrase(ent.gen_pl, ent.gen_pl, ent.dat_pl, ent.gen_pl, ent.dat_pl, ent.nom_pl, "pl") \
            if ent is not None and ent.sure else None
    labels = [leader]
    fs.ctx.update(leader=leader, metric=ph, unit_short=unit, labels=labels)
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
    last_k = min(real, key=lambda k: (cv.values[k], k))
    if last_k != leader_k and not cv.others:
        lo = cv.values[last_k]
        fs.add("last_value", lo, "min", f"{cv.labels[last_k]} — {fmt_value(lo, unit)}",
               unit, f"Наименьшее значение — у категории «{cv.labels[last_k]}».")
        fs.ctx["last_label"] = cv.labels[last_k]
        labels.append(cv.labels[last_k])
        if lo > 0 and lv / lo >= 2:
            r = round(lv / lo, 1)
            fs.add("spread", r, "max", f"Разрыв — в {fmt_num(r, 1)} {times_word(r)}", "раз",
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
                labels.append(gl)
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


def _shares(d: Data) -> FactSet:
    fs = FactSet()
    got = d.shares
    if got is None:
        return fs
    cv, shares = got
    order = sorted(range(len(shares)), key=lambda k: (-shares[k], k))  # по значению, не по месту
    k1 = order[0]
    leader = cv.labels[k1]
    whole, money = _whole_phrase(d, d.parts_measure)
    fs.ctx.update(leader=leader, whole=whole, money=money, labels=[leader])
    p = shares[k1]
    others = [k for k in order[1:]]
    fs.add("leader_share", round_pct(p), "share", f"{leader} — {fmt_pct(p)}%", "%",
           f"{leader} — {fmt_pct(p)}%, больше любой другой части: "
           + ", ".join(f"{cv.labels[k]} — {fmt_pct(shares[k])}%" for k in others) + ".")
    if len(order) >= 2:
        k2 = order[1]
        fs.add("second_share", round_pct(shares[k2]), "share", f"{cv.labels[k2]} — {fmt_pct(shares[k2])}%", "%",
               "Вторая по величине доля.")
        top2 = shares[k1] + shares[k2]
        fs.add("top2_share", round_pct(top2), "share", f"Две крупнейшие части — {fmt_pct(top2)}%", "%",
               f"{leader} и {cv.labels[k2]} вместе.")
    total = sum(shares)
    fs.add("total_share", round(total), "total", f"Сумма долей — {fmt_pct(total)}%", "%",
           "Части одного целого: сумма долей ≈ 100%.")
    fs.ctx["caption"] = ", ".join(f"{lab} — {fmt_pct(v)}%" for lab, v in zip(cv.labels, shares)) + "."
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
    fs.add("median", round(med, 1) if abs(med) < 100 else round(med), "median", f"Медиана — {fmt_value(med, unit)}", unit,
           f"Половина значений меньше {fmt_value(med, unit)}. {_by(m)}")
    fs.add("count", n, "count", count_words(n, *ent_forms), None, "Строк с числом в колонке.")
    if dv.bins.n < 5:
        # почти одно и то же значение: форма распределения пустая, вывод — само значение
        fs.ctx["constant"] = "all" if float(x.min()) == float(x.max()) else "almost"
        fs.ctx["caption"] = (f"{upper_first(count_words(n, *ent_forms))}: значения от {fmt_value(float(x.min()), unit)} до "
                             f"{fmt_value(float(x.max()), unit)} — разброса почти нет.")
        return fs
    p80 = float(np.percentile(x, 80))
    if duration:
        pm = p80 * to_min  # в минутах
        t_min = next((float(v) for v in NICE_MINUTES if v >= pm - 1e-9), _nice_ceil(pm))
        t = t_min / to_min
        text, tv, tu = duration_text(t_min)
    else:
        t = _nice_ceil(p80) if p80 > 0 else p80
        text, tv, tu = fmt_value(t, unit), t, unit
    within = int((x <= t + 1e-9).sum())
    share = math.floor(within / n * 100) if n else 0
    fs.ctx.update(threshold_text=text, predicate=_predicate(m.name) if duration and ent_ok else None)
    fs.add("share_within", share, "percentile", f"{share}% — не больше {fmt_value(t, unit)}", "%",
           f"{within} из {count_words(n, *ent_forms)} — не больше {fmt_value(t, unit)}. {_by(m)}")
    fs.add("threshold", tv, "percentile", text, tu,
           f"Граница — {fmt_value(t, unit)}: 80-й перцентиль {fmt_value(p80, unit)}, округлено вверх.")
    fs.add("p80", round(p80, 1) if abs(p80) < 100 else round(p80), "percentile",
           f"80-й перцентиль — {fmt_value(p80, unit)}", unit, f"80% значений не больше этого числа. {_by(m)}")
    caption = [f"Медиана — {med_txt}."]
    if dv.outliers:
        fs.add("outliers", len(dv.outliers), "outliers", count_words(len(dv.outliers), "выброс", "выброса", "выбросов"),
               None, f"Значения {', '.join(fmt_num(v) for v in dv.outliers[:5])} — далеко от остальных "
                     f"(правило Тьюки с отрывом).")
    for side, vals in (("high", dv.high_outliers), ("low", dv.low_outliers)):
        if not vals:
            continue
        k = len(vals)
        if side == "high":
            thr = _round_down_above(min(vals), float(dv.inliers.max()) if dv.inliers.size else 0)
            word = "больше"
        else:
            thr = _round_up_below(max(vals), float(dv.inliers.min()) if dv.inliers.size else 0)
            word = "меньше"
        thr_txt = duration_gen(thr * to_min) if duration else fmt_value(thr, unit)
        fs.add(f"outlier_bound_{side}", thr, "outliers", f"{word} {thr_txt}", unit,
               f"Граница выбросов: {count_words(k, 'значение', 'значения', 'значений')} {word} {thr_txt}.")
        caption.append(f"{upper_first(count_words(k, *ent_forms))} — {word} {thr_txt}: это выбросы, они отмечены "
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
    forms = (ent.low.nom, ent.low.gen, ent.low.gen_pl) if ent_ok else None
    mph = metric_phrase(m.name, m.type) if m is not None else None
    fs.ctx.update(entities_gen=ent.low.gen_pl if ent_ok else None, metric=mph, entity_forms=forms)
    fs.add("count", rv.n, "count", f"Всего строк — {rv.n}", None, "Строк данных в таблице.")
    if m is not None and rv.top_share is not None and rv.n > rv.top_n:
        # суммируемая неотрицательная метрика: доля топ-10 и итог остальных
        top = rv.top_share
        rest_n = rv.n - rv.top_n
        rest_v = (rv.total or 0) - (rv.top_sum or 0)
        unit = m.unit_text
        what = mph.nom if mph is not None else m.name
        fs.add("top_n", rv.top_n, "count", f"Топ-{rv.top_n}", None, f"{rv.top_n} крупнейших из {rv.n} по колонке «{m.name}».")
        fs.add("top_share", round_pct(top), "share", f"Топ-{rv.top_n} — {fmt_pct(top)}%", "%",
               f"{what} {rv.top_n} крупнейших из {rv.n}: {fmt_value(rv.top_sum or 0, unit)} из "
               f"{fmt_value(rv.total or 0, unit)}. {_by(m)}")
        fs.add("rest_share", round_pct(100 - top), "share", f"Остальные {rest_n} — {fmt_pct(100 - top)}%", "%",
               f"Остальные {rest_n} дают {fmt_value(rest_v, unit)}.")
        fs.add("rest_count", rest_n, "count", f"Остальные {rest_n}", None, "Строки, собранные в итог.")
        who = f"Остальные {count_words(rest_n, *(forms or ('строка', 'строки', 'строк')))}"
        fs.ctx["caption"] = f"{who} дают {fmt_value(rest_v, unit)} — {fmt_pct(100 - top)}%."
        return fs
    if m is not None and rv.values and rv.values[0] is not None:
        # рейтинг, средний чек, прибыль с убытками: лидер по значению, без долей; строки без подписи — без имени
        leader = rv.labels[0] if rv.label is not None else ""
        lv = float(rv.values[0])
        unit = m.unit_text
        fs.ctx.update(leader=leader, labels=[leader] if leader else [], unit_short=unit)
        fs.add("leader_value", lv, "leader", f"{leader or 'Наибольшее'} — {fmt_value(lv, unit)}", unit,
               f"Наибольшее значение по колонке «{m.name}»" + (f" — у строки «{leader}»." if leader else "."))
        if rv.negatives:
            fs.add("negatives", rv.negatives, "count", f"{rv.negatives} в минусе", None,
                   f"Отрицательных значений в колонке «{m.name}»: {rv.negatives}.")
        fs.ctx["caption"] = f"Строки упорядочены по колонке «{m.name}»" + (
            f"; показаны первые {rv.top_n} из {rv.n}." if rv.n > rv.top_n else ".")
        return fs
    grp = [j for j in d.dims if j != d.label and 1 < d.cols[j].distinct < rv.n]
    if grp:
        j = grp[0]
        gp = phrase(d.cols[j].name)
        k = d.cols[j].distinct
        if gp is not None and gp.sure:
            fs.add("groups", k, "count", f"«{d.cols[j].name}»: {count_words(k, 'значение', 'значения', 'значений')}",
                   None, f"Разных значений в колонке «{d.cols[j].name}».")
            fs.ctx["group_forms"] = (gp.low.gen, gp.low.gen_pl)
    if rv.pages > 1:
        fs.ctx["caption"] = f"Показаны первые {min(rv.n, 10)} строк из {rv.n}."
    return fs


# ── ключевые показатели ───────────────────────────────────────────────────────────────────────────────────────────────
def _change_value(ch: float, unit: Optional[str]) -> float:
    return round_pct(abs(ch)) if unit == "%" else round(abs(ch), 1)


def _kpi(d: Data) -> FactSet:
    fs = FactSet()
    kv = d.kpi
    if kv is None or not kv.items:
        return fs
    a = kv.items[0]
    pa = phrase(a.label)
    fs.ctx.update(a_name=a.label, a_gender=pa.gender if pa else "m", a_value_text=a.value_text,
                  labels=[it.label for it in kv.items])
    for k, it in enumerate(kv.items):
        fs.add(f"value_{k}", it.value, "total", f"{it.label} — {it.value_text}", it.unit,
               f"{it.label}: {it.value_text}" + (f" ({kv.period})" if kv.period else "") + ".")
    fs.add("kpi_value", a.value, "total", f"{a.label} — {a.value_text}", a.unit, f"{a.label}: {a.value_text}.")
    since = f" к {kv.prev_period}" if kv.prev_period else ""
    if a.change is not None:
        fs.ctx.update(a_signed=a.change, a_unit=a.change_unit)
        fs.add("kpi_a", _change_value(a.change, a.change_unit), "change",
               f"{a.label}: {fmt_signed(a.change, a.change_unit or '')}", a.change_unit,
               f"{a.label} — {a.value_text}" + (f", было {a.prev_text}" if a.prev_text else "") +
               f": {fmt_signed(a.change, a.change_unit or '')}{since}.")
        b = next((it for it in kv.items[1:] if it.change is not None and it.change_unit == a.change_unit), None)
        if b is not None:
            pb = phrase(b.label)
            if pb is not None and pb.sure:
                b_gen = f"числа {pb.low.gen_pl}" if pb.gender == "pl" and b.label.lower() not in _MASS_PL else pb.low.gen
            else:
                b_gen = b.label if pb is not None else None
            fs.ctx.update(b_name=b.label, b_gender=pb.gender if pb else "m", b_gen=b_gen, b_signed=b.change,
                          b_unit=b.change_unit)
            fs.add("kpi_b", _change_value(b.change, b.change_unit), "change",
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
