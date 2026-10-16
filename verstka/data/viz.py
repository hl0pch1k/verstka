"""Варианты визуализации (описание решения §2.4): 2–3 варианта, лучший по данным — первым.

Кандидаты строятся из задачи и профиля и ранжируются баллами с жёсткими ограничениями: кольцо и круговая — не больше 6
долей и только части целого; линия — ось времени и ≥ 4 точек; гистограмма — числовая колонка ≥ 30 значений; рассеяние —
две метрики; горизонтальные полосы — длинные подписи или больше 7 категорий; таблица — до 10 строк на слайд (больше —
топ-10 и итог или разбиение, не больше 3 слайдов). Неосуществимый вариант может остаться в списке как отвергнутый — с
причиной «почему не он» («8 долей — мелкие сектора нечитаемы») и низким баллом, но выбран не будет.

У каждого варианта — причины, основанные на свойствах данных («Дата и одна метрика, 21 точка — тренд виден сразу»),
у невыбранных — «почему не он», у выбранного — слово цели, если она подтвердила выбор или подняла вариант на первое
место. Выбор не зависит ни от шаблона, ни от формата файла: на вход идут только данные и цели."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from verstka.data.aggregate import MAX_CATS, MAX_SLIDES, TABLE_ROWS, Data, describe_dropped
from verstka.data.goals import Goal
from verstka.data.words import (
    PERIOD_WORDS, count_words, fmt_num, fmt_pct, metric_phrase, phrase, upper_first, verb_agree,
)
from verstka.schemas.data import TaskKind, VizKind, VizOption

__all__ = ["rank_options", "candidates", "find_candidate", "GOAL_VIZ_BONUS"]

GOAL_VIZ_BONUS = 0.15
_MIN_OPTIONS, _MAX_OPTIONS = 2, 3


@dataclass
class _Cand:
    kind: VizKind
    score: float
    title: str = ""
    reasons: list[str] = field(default_factory=list)
    why_not: str = ""
    aggregation: Optional[str] = None
    feasible: bool = True
    key: str = ""  # различает два варианта одного вида (таблица топ-10 и таблица по слайдам)
    dim: Optional[int] = None  # колонка категорий варианта (уровень иерархии: институты или кафедры)

    def option(self) -> VizOption:
        return VizOption(kind=self.kind, score=round(self.score, 3), title=self.title, reasons=list(self.reasons),
                         why_not=self.why_not or None, aggregation=self.aggregation)


def _points(n: int) -> str:
    return count_words(n, "точка", "точки", "точек")


def _rows(n: int) -> str:
    return count_words(n, "строка", "строки", "строк")


# ── динамика ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _dynamics(d: Data) -> list[_Cand]:
    tv = d.time
    if tv is None:
        return []
    P = tv.points
    S = len(tv.series)
    Pv = sum(1 for v in tv.main.values if v is not None)  # точки со значением (пропуск — не точка)
    gaps = bool(tv.missing) or tv.gaps
    pw = PERIOD_WORDS.get(tv.freq, PERIOD_WORDS["irregular"])
    axis = "Дата" if tv.column_type == "date" else (tv.column if 0 < len(tv.column) <= 16 else "Период")
    metrics = "одна метрика" if S == 1 else count_words(S, "ряд", "ряда", "рядов")
    agg = tv.note
    out: list[_Cand] = []
    # линия
    line = _Cand("line", 0.9 if S <= 5 else 0.6, title="Линейный график с разрывами" if gaps else "Линейный график",
                 aggregation=agg)
    if P < 4:
        line.score, line.feasible = 0.2, False
        line.why_not = f"{upper_first(_points(P))} — для линии мало, тренда ещё нет."
    else:
        line.reasons.append(f"{axis} и {metrics}, {_points(Pv)} — тренд виден сразу.")
        if gaps:
            line.reasons.append("Пропуски — разрывы линии, а не падение до нуля.")
        line.why_not = "Тоже читается, но отдельные периоды сравнивать труднее." if P < 8 else \
            "Подходит, но тренд здесь не главное."
    out.append(line)
    # столбцы
    col = _Cand("column", 0.0, title="Столбцы с пустыми местами" if gaps else "Столбцы", aggregation=agg)
    if S > 1:
        parts = (tv.measure.additive and tv.dim) or d.composition
        col.kind = "stacked_column" if parts else "grouped_column"
        col.title = "Накопительные столбцы" if col.kind == "stacked_column" else "Сгруппированные столбцы"
    if P > 36:
        col.score, col.feasible = 0.05, False
        col.why_not = f"{upper_first(count_words(P, 'столбец', 'столбца', 'столбцов'))} не поместятся."
    else:
        col.score = 0.85 if P < 4 else 0.7 if P <= 8 else 0.55 if P <= 24 else 0.35
        if S > 1 and col.kind == "stacked_column":
            col.score += 0.15 if P <= 12 else 0.0
            col.reasons.append(f"Видно и итог каждого периода, и вклад каждой части ({count_words(S, 'ряд', 'ряда', 'рядов')}).")
            col.why_not = "Видно итог и вклад частей, но тренд каждой части читается хуже."
        elif S > 1:
            col.score -= 0.1 if P > 8 else 0.0
            col.reasons.append(f"{count_words(S, 'ряд', 'ряда', 'рядов').capitalize()} рядом в каждом периоде.")
            col.why_not = f"За {count_words(P * S, 'столбцом', 'столбцами', 'столбцами')} тренд теряется."
        elif P < 4:
            col.reasons.append(f"{upper_first(count_words(P, pw[0], pw[1], pw[2]))} — столбцы сравнивают периоды напрямую.")
        else:
            col.reasons.append(f"{pw[5]} дискретны — каждый период отдельным столбцом.")
            if gaps:
                col.why_not = "Пропуски видны, но рост читается хуже."
            else:
                col.why_not = (f"{pw[5]} дискретны, но за {count_words(P, 'столбцом', 'столбцами', 'столбцами')} тренд "
                               f"виден хуже.")
    out.append(col)
    # карточки «было — стало» на 2–3 точках
    if P <= 3 and S == 1:
        out.append(_Cand("kpi_cards", 0.5, title="Карточки: было и стало",
                         reasons=[f"{upper_first(count_words(P, pw[0], pw[1], pw[2]))} — главное в числах изменения."],
                         why_not="Числа крупно, но динамика не видна."))
    # таблица
    tab = _Cand("table", 0.2, title="Таблица с прочерками" if gaps else "Таблица", key="table")
    if P <= TABLE_ROWS:
        tab.score = 0.25
        tab.reasons.append(f"{upper_first(_rows(P))} — помещаются на слайд.")
        tab.why_not = f"{upper_first(_rows(P))} читаются, но динамика не видна."
    else:
        tab.reasons.append("Точные значения каждого периода.")
        tab.why_not = f"{upper_first(_rows(P))} — тренд не читается."
        tab.feasible = P <= TABLE_ROWS * MAX_SLIDES
        tab.score = 0.2 if tab.feasible else 0.05
        tab.aggregation = f"по {TABLE_ROWS} строк на слайд" if tab.feasible else None
    out.append(tab)
    return out


# ── сравнение ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _comparison(d: Data) -> list[_Cand]:
    cv = d.cats
    if cv is None:
        return []
    C = cv.n
    long_ = cv.long_labels
    dp = phrase(cv.dim)
    names_of = f"Названия {dp.low.gen_pl}" if dp is not None and dp.sure else "Названия категорий"
    m = cv.measure
    mph = metric_phrase(m.name, m.type) if m is not None else None
    by = f"по {mph.low.dat}" if mph is not None else "по значению"
    cats = count_words(C, "категория", "категории", "категорий")
    out: list[_Cand] = []
    agg = cv.note
    same = [x for x in d.parallel if x is not m]
    grouped = bool(same)
    # ранжированные полосы
    bar = _Cand("bar", 0.7 + (0.15 if long_ else 0.0) + (0.1 if C > 7 else 0.0),
                title="Ранжированные горизонтальные столбцы" if cv.ranked else "Горизонтальные столбцы", aggregation=agg)
    if long_:
        bar.reasons.append(f"{upper_first(cats)} с длинными названиями: подписи слева, порядок — {by}.")
    else:
        bar.reasons.append(f"{upper_first(cats)}: подписи слева, порядок — {by}.")
    bar.why_not = "Тоже подойдёт, но при коротких подписях вертикальные столбцы привычнее."
    out.append(bar)
    # вертикальные столбцы
    col = _Cand("column", 0.8, title="Вертикальные столбцы", aggregation=agg)
    if long_ and (C >= 6 or max(len(x) for x in cv.labels) > 20):
        col.score -= 0.35
        col.why_not = f"{names_of} не помещаются под столбцами."
    elif C > 7:
        col.score -= 0.15
        col.why_not = f"{upper_first(count_words(C, 'столбец', 'столбца', 'столбцов'))} — подписи придётся наклонять."
    else:
        col.why_not = "Тоже подойдёт, но длинные подписи под столбцами читать труднее."
    col.reasons.append(f"{upper_first(cats)} — каждая отдельным столбцом, сравнение по высоте.")
    if not cv.ranked:
        col.score += 0.1
        col.reasons.append("Подписи по порядку (интервалы, ступени) — столбцы сохраняют этот порядок.")
    out.append(col)
    if grouped:
        k = len(same) + 1
        gk: VizKind = "grouped_bar" if long_ or C > 7 else "grouped_column"
        out.append(_Cand(gk, 0.9, title="Сгруппированные полосы" if gk == "grouped_bar" else "Сгруппированные столбцы",
                         reasons=[f"{upper_first(count_words(k, 'метрика', 'метрики', 'метрик'))} в одних единицах для "
                                  f"{count_words(C, 'категории', 'категорий', 'категорий')} — сравнение рядом."],
                         why_not="Метрики рядом, но столбцов вдвое больше."))
    # уровень иерархии: сравнение по родителю (сумма по детям) и детали — отдельным вариантом
    child = d.label
    if child is not None and cv.dim != d.cols[child].name and d.parent_of(child) is not None:
        cp, pp = phrase(d.cols[child].name), phrase(cv.dim)
        by_child = f"по {cp.low.dat_pl}" if cp is not None and cp.sure else "по строкам"
        by_parent = f"по {pp.low.dat_pl}" if pp is not None and pp.sure else "по группам"
        bar.title = f"Ранжированные горизонтальные столбцы {by_parent}"
        bar.reasons.insert(0, f"Иерархия «{d.cols[child].name} → {cv.dim}»: {by_parent} — сумма {by_child}.")
        kc = d.cat_view(m, dim=child)
        nchild = kc.distinct if kc is not None else d.n
        out.append(_Cand("bar", 0.6, title=f"Столбцы {by_child}" + (", топ-11" if nchild > 12 else ""), dim=child,
                         key="child", aggregation=kc.note if kc is not None else None,
                         reasons=[f"Детальнее: {count_words(nchild, 'строка', 'строки', 'строк')} {by_child}."],
                         why_not=f"Детальнее, но {count_words(nchild, 'длинное название', 'длинных названия', 'длинных названий')}"
                                 f" — вклад {pp.low.gen_pl if pp is not None and pp.sure else 'групп'} не виден."))
        pages = -(-d.n // TABLE_ROWS)
        out.append(_Cand("table", 0.5, title=f"Таблица «{cv.dim} → {d.cols[child].name}»", key="table_tree",
                         feasible=pages <= MAX_SLIDES,
                         aggregation=f"{count_words(pages, 'слайд', 'слайда', 'слайдов')} по {TABLE_ROWS} строк, итог внизу",
                         reasons=["Все строки с группой и итогом."],
                         why_not=f"{upper_first(_rows(d.n))} — на слайд не помещаются, нужно "
                                 f"{count_words(pages, 'слайд', 'слайда', 'слайдов')}."))
    # круговая — только для сумм (части целого)
    shares = cv.shares
    if m is None or m.additive:
        pie = _Cand("pie", 0.0, title="Круговая диаграмма")
        if shares is None:
            pie.score, pie.feasible = 0.05, False
            pie.reasons.append("Показывает части целого.")
            pie.why_not = "Есть отрицательные значения — это не доли целого."
        elif cv.distinct > 6:
            pie.score, pie.feasible = 0.12, False
            pie.reasons.append("Показывает, какую часть целого даёт лидер.")
            pie.why_not = f"{upper_first(count_words(cv.distinct, 'доля', 'доли', 'долей'))} — мелкие сектора нечитаемы."
        else:
            pie.score = 0.45
            pie.reasons.append(f"{upper_first(count_words(C, 'доля', 'доли', 'долей'))} одного целого.")
            pie.why_not = "Показывает долю, но сравнивать сектора по величине труднее, чем столбцы."
        out.append(pie)
    # таблица
    tab = _Cand("table", 0.1, title="Таблица", key="table")
    tab.reasons.append("Точные значения каждой категории.")
    tab.why_not = "Числа читаются, но сравнения не видно."
    if C > TABLE_ROWS:
        tab.score, tab.feasible = 0.05, C <= TABLE_ROWS * MAX_SLIDES
    out.append(tab)
    return out


# ── доли ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _composition(d: Data) -> list[_Cand]:
    """Части одного целого по категориям (формы обучения по направлениям): накопительные столбцы, сгруппированные,
    кольцо по частям в целом."""
    cv = d.cats
    g = d.parallel
    if cv is None or len(g) < 2:
        return []
    C, k = cv.n, len(g)
    dp = phrase(cv.dim)
    cats_word = count_words(C, dp.low.nom, dp.low.gen, dp.low.gen_pl) if dp is not None and dp.sure else \
        count_words(C, "категория", "категории", "категорий")
    long_ = cv.long_labels or C > 7
    out = [
        _Cand("stacked_bar" if long_ else "stacked_column", 0.9,
              title="Накопительные горизонтальные столбцы" if long_ else "Накопительные столбцы",
              reasons=[f"{upper_first(cats_word)} и {count_words(k, 'часть', 'части', 'частей')}: видны и размер, и "
                       f"состав" + (", подписи слева." if long_ else ".")],
              why_not="Видны размер и состав, но части разных категорий сравнивать труднее."),
        _Cand("grouped_bar" if long_ else "grouped_column", 0.55,
              title="Сгруппированные горизонтальные столбцы" if long_ else "Сгруппированные столбцы",
              reasons=["Части рядом — сравнивать их внутри категории легко."],
              why_not=f"{upper_first(count_words(C * k, 'столбец', 'столбца', 'столбцов'))}: состав сравнить легко, а "
                      f"общий размер — нет."),
        _Cand("doughnut", 0.5, title="Кольцевая диаграмма по частям в целом", key="parts_total",
              reasons=[f"{upper_first(count_words(k, 'часть', 'части', 'частей'))} целого — сразу видно, какая больше."],
              why_not=f"Читается, но {dp.low.nom_pl if dp is not None and dp.sure else 'категории'} потеряны."),
    ]
    return out


def _shares(d: Data) -> list[_Cand]:
    if d.composition and d.cats is not None and len(d.parallel) >= 2:
        return _composition(d)
    got = d.shares
    if got is None:
        return []
    cv, shares = got
    C = cv.n
    total = sum(shares)
    sum_txt = "100%" if 95 <= total <= 105 else f"{fmt_pct(total)}%"
    out: list[_Cand] = []
    dn = _Cand("doughnut", 0.9, title="Кольцевая диаграмма")
    if C <= 6:
        dn.reasons.append(f"{upper_first(count_words(C, 'доля', 'доли', 'долей'))} в сумме дают {sum_txt} — целое видно "
                          f"сразу, подписи помещаются.")
        dn.why_not = "Целое видно, но доли сравнивать труднее, чем столбцы."
    else:
        dn.score = 0.55
        dn.aggregation = "5 крупнейших и «Остальные»"
        dn.reasons.append(f"{upper_first(count_words(C, 'доля', 'доли', 'долей'))} — крупнейшие пять отдельно, остальные одним "
                          f"сектором.")
        dn.why_not = f"{upper_first(count_words(C, 'доля', 'доли', 'долей'))} — даже с «Остальными» мелкие части теряются."
    out.append(dn)
    st = _Cand("stacked_column", 0.5, title="Накопительный столбец",
               reasons=["Те же доли одним столбцом высотой 100%."],
               why_not="Те же доли, но отрезки сравнивать труднее.")
    out.append(st)
    long_ = cv.long_labels and C >= 6
    col = _Cand("bar" if long_ else "column", 0.45 if C <= 6 else 0.6,
                title="Ранжированные горизонтальные столбцы" if long_ else "Столбцы",
                reasons=["Доли рядом — сравнение по длине."],
                why_not="Не видно, что вместе это 100%." if C <= 6 else "Не видно, что вместе это 100%, зато видны все части.")
    out.append(col)
    return out


# ── распределение ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _distribution(d: Data) -> list[_Cand]:
    dv = d.dist
    if dv is None:
        return []
    n = dv.n
    vals = count_words(n, "значение", "значения", "значений")
    out: list[_Cand] = []
    flat = dv.bins.n < 5  # почти одно значение: интервалов нет
    h = _Cand("histogram", 0.9, title="Гистограмма", aggregation=dv.note)
    if n < 30:
        h.score, h.feasible = 0.1, False
        h.why_not = f"{upper_first(vals)} — для гистограммы мало."
    elif flat:
        h.score, h.feasible = 0.1, False
        h.why_not = (f"Значения почти не различаются: {count_words(dv.bins.n, 'интервал', 'интервала', 'интервалов')} — "
                     f"гистограмма ничего не покажет.")
    else:
        h.reasons.append(f"Одна числовая колонка, {vals} — видно, где большинство и насколько длинный хвост.")
        if dv.outliers:
            h.reasons.append(f"{upper_first(count_words(len(dv.outliers), 'выброс', 'выброса', 'выбросов'))} — отдельно.")
        h.why_not = "Видна форма, но не точные числа."
    out.append(h)
    k = _Cand("kpi_cards", 0.6 if flat else 0.45, title="Карточки ключевых показателей",
              reasons=["Значения почти одинаковые — главное в самом значении." if flat else
                       "Медиана и 80-й перцентиль — коротко."],
              why_not="Медиана и 80-й перцентиль — коротко, но без формы распределения.")
    out.append(k)
    tab = _Cand("table", 0.15, title="Таблица", key="table", feasible=n <= TABLE_ROWS * MAX_SLIDES,
                reasons=["Точные значения."])
    if n > TABLE_ROWS * MAX_SLIDES:
        tab.score = 0.05
        tab.why_not = f"{upper_first(_rows(n))} не показать."
    else:
        tab.why_not = f"{upper_first(_rows(n))} — форма распределения не видна."
    out.append(tab)
    return out


# ── справочник ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _groups_cand(d: Data, score: float) -> Optional[_Cand]:
    """Столбцы «число строк по группам» — есть колонка-группа с повторами."""
    j = next((j for j in d.dims if j != d.label and 1 < d.cols[j].distinct < d.n), None)
    if j is None:
        return None
    name = d.cols[j].name
    return _Cand("bar", score, title=f"Столбцы: число строк по группам «{name}»", key="groups",
                 aggregation=f"число строк по группам «{name}»",
                 reasons=[f"Видно, каких строк больше по колонке «{name}»."],
                 why_not="Видны группы, но не сами строки.")


def _reference(d: Data) -> list[_Cand]:
    rv = d.ref
    n = rv.n
    m = rv.measure
    out: list[_Cand] = []
    pages = rv.pages
    unit = m.unit_text if m is not None else None
    mph = metric_phrase(m.name, m.type) if m is not None else None
    by = f"по {mph.low.dat}" if mph is not None else "по значению"
    if n <= TABLE_ROWS:
        out.append(_Cand("table", 0.9, title="Таблица", key="table",
                         reasons=[f"{upper_first(_rows(n))} — помещаются на слайд целиком."],
                         why_not="Все значения, но без наглядного сравнения."))
        if m is not None and rv.label is not None:
            out.append(_Cand("bar", 0.5, title="Ранжированные горизонтальные столбцы", key="ref_bar",
                             reasons=[f"Строки по порядку {by} — видно, кто больше."],
                             why_not="Видно, кто больше, но теряются остальные колонки."))
    elif m is not None:
        rest_n = n - rv.top_n
        if rv.top_share is not None and rv.rest is not None:
            rest_v = (rv.total or 0) - (rv.top_sum or 0)
            share = 100 - (rv.top_share or 0)
            t = _Cand("table", 0.85, title=f"Таблица топ-{rv.top_n} и итог «остальные {rest_n}»", key="table_top",
                      aggregation=f"топ-{rv.top_n} и строка «Остальные {rest_n}»")
            t.reasons.append(f"{upper_first(_rows(n))} не помещаются: {rv.top_n} крупнейших — строками, остальные — одной "
                             f"строкой, {fmt_num(rest_v)}{' ' + unit if unit else ''} и {fmt_pct(share)}%.")
        else:
            # рейтинг, средний чек, прибыль с убытками: порядок есть, суммы и доли — нет
            t = _Cand("table", 0.8, title=f"Таблица топ-{rv.top_n} {by}", key="table_top",
                      aggregation=f"топ-{rv.top_n} {by}")
            t.reasons.append(f"{upper_first(_rows(n))} не помещаются: первые {rv.top_n} {by}; сумма и доли здесь смысла "
                             f"не имеют.")
        if rv.dropped:
            t.reasons.append(f"На слайде {count_words(len(rv.columns), 'колонка', 'колонки', 'колонок')}: "
                             f"{describe_dropped(rv.dropped)} "
                             f"{verb_agree(rv.dropped, ('не вошёл', 'не вошла', 'не вошло', 'не вошли'))}"
                             + (", доля посчитана." if rv.share_added else "."))
        t.why_not = "Цифры и подписи есть, но первых видно хуже, чем на столбцах."
        out.append(t)
        lost_names = [c.split(",")[0] for c in rv.columns[1:] if not c.startswith(("Доля", m.name))]
        lost = describe_dropped(lost_names)
        verb_lost = "теряется" if len(lost_names) == 1 else "теряются"
        out.append(_Cand("bar", 0.5, title=f"Столбцы топ-{rv.top_n}", key="ref_bar", aggregation=f"топ-{rv.top_n}",
                         reasons=["Видно лидеров и разрыв между ними."],
                         why_not=f"Видно лидеров, но {verb_lost} {lost}." if lost else
                         "Видно лидеров, но теряются остальные колонки."))
    else:
        feasible = pages <= MAX_SLIDES
        out.append(_Cand("table", 0.8 if feasible else 0.5, title="Таблица по слайдам" if feasible else
                         f"Первые {TABLE_ROWS} строк", key="table_pages" if feasible else "table_head",
                         aggregation=f"{count_words(pages, 'слайд', 'слайда', 'слайдов')} по {TABLE_ROWS} строк"
                         if feasible else f"первые {TABLE_ROWS} из {n}",
                         reasons=[f"{upper_first(_rows(n))} — по {TABLE_ROWS} на слайд, ничего не теряется."] if feasible
                         else [f"{upper_first(_rows(n))} — на слайде первые {TABLE_ROWS}, остальное в файле."],
                         why_not="Все строки, но слайдов несколько."))
    g = _groups_cand(d, 0.4) if m is None else None  # без метрики — сколько строк в каждой группе
    if g is not None:
        out.append(g)
    if pages > 1 and not any(c.key == "table_pages" for c in out):
        sp = _Cand("table", 0.1 if pages > MAX_SLIDES else 0.6,
                   title=f"Разбиение на {count_words(pages, 'слайд', 'слайда', 'слайдов')}", key="table_pages",
                   aggregation=f"по {TABLE_ROWS} строк на слайд", feasible=pages <= MAX_SLIDES)
        sp.reasons.append("Все строки, ничего не теряется.")
        sp.why_not = f"По {TABLE_ROWS} строк на слайд — слишком много." if pages > MAX_SLIDES else \
            "Все строки, но главное теряется среди них."
        out.append(sp)
    return out


def _fallbacks(d: Data, have: list[_Cand]) -> list[_Cand]:
    """Честные альтернативы, когда у задачи меньше двух вариантов: таблица, карточки, столбцы — осуществимые или с
    причиной, почему нет."""
    kinds = {c.kind for c in have}
    keys = {c.key for c in have}
    out: list[_Cand] = []
    m = d.main
    if "table" not in kinds:
        ok = d.n <= TABLE_ROWS * MAX_SLIDES
        out.append(_Cand("table", 0.3 if ok else 0.05, title="Таблица", key="fb_table", feasible=ok,
                         reasons=["Все значения как в файле."],
                         why_not="Значения видны, но вывод не читается." if ok else f"{upper_first(_rows(d.n))} не показать."))
    if "kpi_cards" not in kinds:
        if m is not None:
            out.append(_Cand("kpi_cards", 0.25, title="Карточки: итог и среднее", key="fb_cards",
                             reasons=[f"Главные числа колонки «{m.name}» крупно."],
                             why_not="Итог и среднее крупно, но строки не видны."))
        else:
            out.append(_Cand("kpi_cards", 0.05, title="Карточки ключевых показателей", key="fb_cards", feasible=False,
                             why_not="Чисел нет — карточкам нечего показать."))
    if not kinds & {"bar", "column"} and "groups" not in keys:
        g = _groups_cand(d, 0.2)
        if g is not None:
            out.append(g)
        elif m is not None and (d.label is not None or d.id_col is not None) and d.n >= 2:
            out.append(_Cand("bar", 0.2, title="Ранжированные горизонтальные столбцы", key="ref_bar",
                             reasons=["Строки по величине — видно, кто больше."],
                             why_not="Видно, кто больше, но теряются остальные колонки."))
        else:
            out.append(_Cand("bar", 0.05, title="Столбцы", key="fb_bar", feasible=False,
                             why_not="Чисел нет — сравнивать нечего." if m is None else
                             "Строки не подписаны — столбцы не назвать."))
    return out


# ── ключевые показатели ───────────────────────────────────────────────────────────────────────────────────────────────
def _kpi(d: Data) -> list[_Cand]:
    kv = d.kpi
    if kv is None:
        return []
    k = len(kv.items)
    nums = count_words(k, "число", "числа", "чисел")
    out: list[_Cand] = []
    c = _Cand("kpi_cards", 0.95 if k <= 6 else 0.3, title="Карточки ключевых показателей", feasible=k <= 6)
    if kv.with_change:
        c.reasons.append(f"{upper_first(nums)} с изменением — каждое крупно, со своим ростом.")
    else:
        c.reasons.append(f"{upper_first(nums)} — каждое крупно, со своей подписью.")
    c.why_not = "Числа крупно, но без сравнения."
    out.append(c)
    out.append(_Cand("table", 0.5, title="Таблица", key="table", reasons=["Все значения и изменения в одном месте."],
                     why_not="Читается, но главные числа теряются в строках."))
    col = _Cand("column", 0.4, title="Столбцы", reasons=["Сравнение по высоте."],
                why_not="Сравнение по высоте, но карточки показывают сами числа крупнее.")
    vals = [abs(it.value) for it in kv.items if it.value]
    spread = (max(vals) / min(vals)) if vals and min(vals) > 0 else 1.0
    if kv.mixed_units:
        col.score, col.feasible = 0.05, False
        col.why_not = "Разные единицы — сравнивать нельзя."
    elif spread > 10:
        col.score, col.feasible = 0.05, False
        col.why_not = (f"Масштабы разные (от {fmt_num(min(vals))} до {fmt_num(max(vals))}) — на одной оси мелкие "
                       f"значения пропадут.")
    elif k < 2:
        col.score, col.feasible = 0.05, False
        col.why_not = "Одно число — сравнивать не с чем."
    out.append(col)
    return out


# ── взаимосвязь ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _relationship(d: Data) -> list[_Cand]:
    xy = d.xy
    if xy is None:
        return []
    sc = _Cand("scatter", 0.9 if xy.n >= 8 else 0.2, title="Диаграмма рассеяния", feasible=xy.n >= 8,
               reasons=[f"Две метрики, {_points(xy.n)} — видно, есть ли связь (r = {fmt_num(xy.r, 2)})."],
               why_not="Связь видна, но значения каждой строки — нет.")
    if xy.group:
        sc.reasons.append(f"Точки окрашены по колонке «{xy.group}».")
    out = [sc]
    if xy.n >= 30:
        yp = metric_phrase(xy.y.name, xy.y.type)
        out.append(_Cand("column", 0.4, title=f"Столбцы: {yp.low.nom if yp else xy.y.name} по группам «{xy.x.name}»",
                         key="xy_bins", aggregation=f"среднее по трём группам «{xy.x.name}»",
                         reasons=["Читается быстрее: три группы и среднее в каждой."],
                         why_not="Читается быстрее, но прячет разброс и теряет связь как линию."))
    if d.label is not None and xy.n <= MAX_CATS:
        out.append(_Cand("grouped_bar", 0.4, title="Сгруппированные полосы",
                         reasons=["Обе метрики по каждой строке."],
                         why_not="Каждая метрика видна, но связь между ними — нет."))
    out.append(_Cand("table", 0.2 if xy.n <= TABLE_ROWS else 0.05, title="Таблица", key="table",
                     reasons=["Точные пары значений."], why_not="Пары чисел читаются, но связь не видна.",
                     feasible=xy.n <= TABLE_ROWS * MAX_SLIDES))
    return out


_BUILDERS = {
    "dynamics": _dynamics, "comparison": _comparison, "shares": _shares, "distribution": _distribution,
    "reference": _reference, "kpi": _kpi, "relationship": _relationship,
}


def candidates(task: TaskKind, d: Data) -> list[_Cand]:
    """Все варианты задачи (с отвергнутыми); меньше двух — добавляются честные альтернативы."""
    out = _BUILDERS[task](d)
    if not out:
        # задача без вида (данных не хватило) — справочная таблица
        out = _reference(d)
    if len(out) < _MIN_OPTIONS:
        out = out + _fallbacks(d, out)
    return out


def find_candidate(task: TaskKind, d: Data, kind: str, title: str) -> Optional[_Cand]:
    """Вариант по виду и названию — чтобы знать, осуществим ли он и почему нет («Пересобрать слайд так»)."""
    return next((c for c in candidates(task, d) if c.kind == kind and c.title == title), None)


def _order(cands: list[_Cand], bonus: dict[VizKind, float]) -> list[_Cand]:
    """По баллу (отвергнутые варианты остаются в списке по своему низкому баллу — с «почему не он»); первым — всегда
    осуществимый."""
    def key(c: _Cand) -> tuple:
        s = c.score + (bonus.get(c.kind, 0.0) if c.feasible else 0.0)
        return (-round(s, 6), _KIND_ORDER.index(c.kind) if c.kind in _KIND_ORDER else 99, c.key)
    out = sorted(cands, key=key)
    first = next((k for k, c in enumerate(out) if c.feasible), 0)
    if first:
        out.insert(0, out.pop(first))
    return out


_KIND_ORDER: list[VizKind] = ["line", "bar", "column", "doughnut", "histogram", "kpi_cards", "table", "scatter",
                              "grouped_column", "grouped_bar", "stacked_column", "stacked_bar", "pie", "area"]


def rank_options(task: TaskKind, d: Data, goals: Optional[list[Goal]] = None,
                 goal_raised_task: bool = False) -> list[VizOption]:
    """2–3 варианта по убыванию балла. Цель о датасете прибавляет вид, к которому ведёт (+0,15); у выбранного
    варианта причина называет цель: «подняла его на первое место», если без неё первым был бы другой, или
    «подтвердила выбор»."""
    goals = goals or []
    cands = candidates(task, d)
    bonus: dict[VizKind, float] = {}
    goal_for: dict[VizKind, Goal] = {}
    family = {"doughnut": ("doughnut", "pie", "stacked_bar", "stacked_column"), "bar": ("bar", "column")}
    for g in goals:
        # цель поднимает лучший вариант своего рода: «как устроен …» — накопительные столбцы, если данные — состав
        kinds = family.get(g.viz, (g.viz,))
        own = [c for c in cands if c.kind in kinds and c.feasible]
        kind = max(own, key=lambda c: c.score).kind if own else g.viz
        if kind not in bonus:
            bonus[kind] = GOAL_VIZ_BONUS
            goal_for[kind] = g
    plain = _order(cands, {})
    ranked = _order(cands, bonus)
    for c in ranked:
        if c.feasible:
            c.score = round(min(1.0, c.score + bonus.get(c.kind, 0.0)), 3)
    top = ranked[0]
    g = goal_for.get(top.kind) or next((x for x in goals if x.task == task), None)
    if g is not None:
        if plain[0] is not top or goal_raised_task:
            top.reasons.append(f"Цель «{g.phrase}» подняла его на первое место.")
        else:
            top.reasons.append(f"Цель «{g.phrase}» подтвердила выбор.")
    picked = ranked[:_MAX_OPTIONS]
    for i, c in enumerate(picked):
        if i == 0:
            c.why_not = ""
        elif not c.why_not:
            c.why_not = "Подходит хуже первого варианта."
    return [c.option() for c in picked]
