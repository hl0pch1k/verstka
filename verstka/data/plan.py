"""Решение по датасету (описание решения §2.3–2.6): профиль и таблица → `DatasetPlan`.

`plan_dataset(profile, table, goals)` — задача, 2–3 ранжированных варианта, заголовок-вывод с фактами, подпись,
источник, число слайдов и сообщение для нетипизируемых данных. `plan_datasets(tables, brief_text)` — то же для всех
файлов: цели из текста сопоставляются с датасетами (цель достаётся тому, о котором она говорит и где её задача
осуществима). `chart_spec_of(plan, table, option)` — данные слайда для выбранного (или другого — «Пересобрать слайд
так») варианта: `ChartSpec`, `TableData` или карточки `NumberCallout`. `slide_data_of(plan)` — `SlideData` для
«Почему так».

Шаблон не входит ни в один вход: один датасет при любом шаблоне и любом формате файла даёт один и тот же вид."""

from __future__ import annotations

import math
import re
from typing import Optional, Sequence, Union

from verstka.data.aggregate import MAX_SLIDES, TABLE_ROWS, CatView, Data
from verstka.data.facts import facts_for
from verstka.data.goals import Goal, goal_match, goals_of, stems_of
from verstka.data.headline import compose, fmt_num, fmt_signed, fmt_value, phrase
from verstka.data.profile import count_ru, profile_table
from verstka.data.task import FEASIBLE, decide_task, task_scores
from verstka.data.viz import rank_options
from verstka.schemas.data import (
    NATURE_LABELS, DatasetPlan, DatasetProfile, SlideData, Table, TaskDecision, VizOption,
)
from verstka.schemas.outline import ChartSpec, InlineSeries, NumberCallout, TableData, XYSeries

__all__ = ["plan_dataset", "plan_datasets", "assign_goals", "chart_spec_of", "slide_data_of", "data_of", "SlideBody"]

SlideBody = Union[ChartSpec, TableData, list[NumberCallout]]
_KIND_LABEL = {"csv": "CSV", "tsv": "TSV", "xlsx": "XLSX", "json": "JSON", "text": "TXT"}


def _values_for_match(d: Data, limit: int = 300) -> list[str]:
    out: list[str] = []
    for j in d.dims + ([d.label] if d.label is not None else []):
        for i in d.rows_idx:
            t = d.text(i, j)
            if t and t not in out:
                out.append(t)
                if len(out) >= limit:
                    return out
    return out


def _relevant(goals: Sequence[Goal], d: Data) -> list[Goal]:
    vals = _values_for_match(d)
    return [g for g in goals if goal_match(g, d.profile, vals) > 0]


def data_of(plan: DatasetPlan, table: Table) -> Data:
    """Тот же `Data`, что видел план (главная метрика — по цели, которая решила задачу)."""
    subject = tuple(stems_of(plan.task.goal)) if plan.task.goal else ()
    return Data(table, plan.profile, subject=subject)


def _source(p: DatasetProfile) -> str:
    return f"Источник: {p.file}" + (f", лист «{p.sheet}»" if p.sheet and p.kind == "xlsx" else "")


def plan_dataset(profile: DatasetProfile, table: Table, goals: Optional[Sequence[Goal]] = None) -> DatasetPlan:
    """Задача, варианты, заголовок-вывод и факты одного датасета. `goals` — цели из текста; к датасету относятся только
    те, что о нём (предмет совпал с файлом, колонками или значениями) или без предмета."""
    d0 = Data(table, profile)
    rel = _relevant(goals or [], d0)
    first = decide_task(Data(table, profile, subject=tuple(s for g in rel for s in g.subject)), rel)
    subject = tuple(stems_of(first.goal)) if first.goal else ()
    d = Data(table, profile, subject=subject) if subject else d0
    decision = decide_task(d, rel)
    source = _source(profile)

    base = task_scores(d)
    if not profile.typable and base.get("reference", 0.0) <= 0.0 and not d.measures:
        reason = profile.untypable_reason or "данные не складываются в график"
        msg = f"Не для графика: {reason}"
        return DatasetPlan(profile=profile, task=TaskDecision(task="reference", reasons=[msg + "."], scores=base),
                           options=[], chosen=0, headline="", plain_headline=_stem(profile), source=source, slides=0,
                           message=msg)

    task = decision.task
    data_task = max(base, key=lambda k: base[k])
    raised = decision.goal is not None and base[data_task] > base[task]
    options = rank_options(task, d, [g for g in rel if base.get(g.task, 0) >= FEASIBLE or g.task == task], raised)
    fs = facts_for(task, d)
    headline, caption = compose(task, fs)
    plain = fs.ctx.get("plain") or _stem(profile)
    message = None
    if not profile.typable and options and options[0].kind == "table":
        message = f"Не для графика: {profile.untypable_reason or 'данные не складываются в график'} — показываю таблицей"
    plan = DatasetPlan(
        profile=profile, task=decision, options=options, chosen=0, headline=headline or plain, headline_facts=fs.facts,
        plain_headline=plain, caption=caption, source=source, slides=1, message=message,
    )
    plan.slides = slides_of(plan, table, 0, d)
    return plan


def _stem(p: DatasetProfile) -> str:
    s = re.sub(r"\.[A-Za-z0-9]+$", "", p.file or "").strip() or "Данные"
    return s[:1].upper() + s[1:]


def assign_goals(goals: Sequence[Goal], datas: Sequence[Data]) -> list[list[Goal]]:
    """Цель — тем датасетам, о которых она больше всего говорит и где её задача осуществима: совпадение предмета
    (файл, колонки, значения) плюс половина балла задачи по данным. Цель без предмета — лучшему по задаче."""
    out: list[list[Goal]] = [[] for _ in datas]
    scores = [task_scores(d) for d in datas]
    values = [_values_for_match(d) for d in datas]
    for g in goals:
        best, who = 0.0, []
        for k, d in enumerate(datas):
            s = scores[k].get(g.task, 0.0)
            if s < FEASIBLE:
                continue
            mt = goal_match(g, d.profile, values[k])
            if mt <= 0:
                continue
            c = round(mt + 0.5 * s, 6)
            if c > best + 1e-9:
                best, who = c, [k]
            elif abs(c - best) <= 1e-9:
                who.append(k)
        for k in who:
            out[k].append(g)
    return out


def plan_datasets(tables: Sequence[Table], brief_text: str = "",
                  profiles: Optional[Sequence[DatasetProfile]] = None) -> list[DatasetPlan]:
    """Планы всех датасетов; цели из текста — каждая своему датасету."""
    profs = list(profiles) if profiles is not None else [profile_table(t) for t in tables]
    goals = goals_of(brief_text)
    datas = [Data(t, p) for t, p in zip(tables, profs)]
    per = assign_goals(goals, datas)
    return [plan_dataset(p, t, g) for t, p, g in zip(tables, profs, per)]


# ── данные слайда ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _option(plan: DatasetPlan, option: Optional[int]) -> Optional[VizOption]:
    k = plan.chosen if option is None else option
    return plan.options[k] if 0 <= k < len(plan.options) else None


def _table_mode(opt: VizOption) -> str:
    a = (opt.aggregation or "").lower()
    t = opt.title.lower()
    if a.startswith("топ-") or "топ-" in t:
        return "top"
    if "слайд" in a or "разбиение" in t or "по слайдам" in t:
        return "pages"
    if a.startswith("первые"):
        return "head"
    return "all"


def slides_of(plan: DatasetPlan, table: Table, option: Optional[int] = None, d: Optional[Data] = None) -> int:
    """Сколько слайдов займёт вариант: таблица по слайдам — до 3, остальное — 1; пропущенный датасет — 0."""
    opt = _option(plan, option)
    if opt is None:
        return 0
    if opt.kind != "table" or _table_mode(opt) not in ("pages", "all"):
        return 1
    d = d or data_of(plan, table)
    rows = _table_rows_count(plan, d)
    return max(1, min(MAX_SLIDES, math.ceil(rows / TABLE_ROWS)))


def _table_rows_count(plan: DatasetPlan, d: Data) -> int:
    t = plan.task.task
    if t == "dynamics" and d.time is not None:
        return d.time.points
    if t in ("comparison", "shares") and d.cats is not None:
        return d.cats.n
    if t == "kpi" and d.kpi is not None:
        return len(d.kpi.items)
    return d.n


def _part(rows: list[list[str]], part: int) -> list[list[str]]:
    a = (max(1, part) - 1) * TABLE_ROWS
    return rows[a:a + TABLE_ROWS] or rows[:TABLE_ROWS]


def _col_title(name: str, unit: Optional[str]) -> str:
    return f"{name}, {unit}" if unit else name


def _cell(v: Optional[float]) -> str:
    return "—" if v is None else fmt_num(v)


def chart_spec_of(plan: DatasetPlan, table: Table, option: Optional[int] = None, part: int = 1) -> Optional[SlideBody]:
    """Данные слайда для варианта `option` (по умолчанию — выбранного): `ChartSpec` для графиков, `TableData` для
    таблиц (`part` — номер слайда при разбиении), список `NumberCallout` для карточек. None — датасет пропущен."""
    opt = _option(plan, option)
    if opt is None:
        return None
    d = data_of(plan, table)
    task = plan.task.task
    src = plan.source or _source(plan.profile)
    fn = {
        "dynamics": _spec_dynamics, "comparison": _spec_comparison, "shares": _spec_shares,
        "distribution": _spec_distribution, "reference": _spec_reference, "kpi": _spec_kpi,
        "relationship": _spec_relationship,
    }[task]
    return fn(d, opt, src, part, plan)


def _spec_dynamics(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    tv = d.time
    if tv is None:
        return _spec_reference(d, opt, src, part, plan)
    unit = tv.measure.unit_text if tv.measure.j >= 0 else None
    yname = tv.measure.name if tv.measure.j >= 0 else "Число строк"
    if opt.kind == "table":
        cols = [tv.column] + [_col_title(s.name, s.unit) for s in tv.series]
        rows = [[lab] + [_cell(s.values[i]) for s in tv.series] for i, lab in enumerate(tv.labels)]
        return TableData(columns=cols, rows=_part(rows, part), unit=unit)
    if opt.kind == "kpi_cards":
        vals = [(lab, v) for lab, v in zip(tv.labels, tv.main.values) if v is not None]
        return [NumberCallout(value=fmt_value(v, unit), label=lab) for lab, v in vals[-3:]]
    series = [InlineSeries(name=s.name, values=list(s.values), unit=s.unit) for s in tv.series]
    kind = opt.kind if opt.kind in ("line", "column", "area", "grouped_column", "stacked_column", "bar") else "line"
    last = max((i for i, v in enumerate(tv.main.values) if v is not None), default=None)
    if tv.split:
        kind = "line" if kind in ("stacked_column", "grouped_column") else kind
    return ChartSpec(type=kind, categories=list(tv.labels), series=series, unit=None if tv.split else unit,
                     highlight_index=last if kind in ("line", "column", "area") and len(series) == 1 else None,
                     x_title=tv.column, y_title=yname if (len(series) == 1 or tv.dim) and not tv.split else None,
                     gaps=tv.gaps, source=src, split=tv.split)


def _cats_spec(cv: CatView, kind: str, src: str, values: Optional[list[float]] = None, unit: Optional[str] = None,
               y_title: Optional[str] = None, extra: Optional[list[tuple[str, list[Optional[float]]]]] = None,
               highlight: Optional[int] = 0) -> ChartSpec:
    vals = values if values is not None else cv.values
    name = y_title or (cv.measure.name if cv.measure else "Число строк")
    series = [InlineSeries(name=name, values=list(vals), unit=unit)]
    for nm, vs in extra or []:
        series.append(InlineSeries(name=nm, values=list(vs), unit=unit))
    return ChartSpec(type=kind, categories=list(cv.labels), series=series, unit=unit,
                     highlight_index=highlight if cv.ranked and len(series) == 1 else None,
                     x_title=cv.dim, y_title=name, source=src)


def _spec_comparison(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    cv = d.cats
    if cv is None:
        return _spec_reference(d, opt, src, part, plan)
    unit = cv.unit
    if opt.kind == "table":
        ms = [(cv.measure.name if cv.measure else "Число строк", cv.values, unit)]
        for mm in cv.extra_measures:
            ms.append((mm.name, cv.extra.get(mm.name, []), mm.unit_text))
        cols = [cv.dim] + [_col_title(n, u) for n, _, u in ms]
        rows = [[lab] + [_cell(v[i] if i < len(v) else None) for _, v, _ in ms] for i, lab in enumerate(cv.labels)]
        return TableData(columns=cols, rows=_part(rows, part))
    if opt.kind in ("pie", "doughnut"):
        shares = cv.shares or cv.values
        return _cats_spec(cv, opt.kind, src, values=[round(s, 1) for s in shares], unit="%")
    if opt.kind in ("grouped_bar", "grouped_column"):
        m = cv.measure
        same = [x for x in cv.extra_measures if m is not None and not x.change and (x.unit or "") == (m.unit or "")
                and x.type == m.type]
        if not same:  # взаимосвязь по строкам — обе метрики
            same = [x for x in cv.extra_measures if not x.change][:1]
        return _cats_spec(cv, opt.kind, src, unit=unit, extra=[(x.name, cv.extra[x.name]) for x in same[:3]])
    kind = opt.kind if opt.kind in ("bar", "column") else "bar"
    return _cats_spec(cv, kind, src, unit=unit)


def _spec_shares(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    parts = d.parts_measure
    cv = d.cat_view(parts) if parts is not None else d.cats
    if cv is None:
        return None
    if parts is not None:
        s = sum(cv.values) or 1.0
        scale = 100.0 / s if 0.95 <= s <= 1.05 else 1.0
        shares = [v * scale for v in cv.values]
    else:
        shares = cv.shares or cv.values
    labels = list(cv.labels)
    if opt.kind in ("doughnut", "pie") and len(labels) > 6:
        rest = sum(shares[5:])
        labels, shares = labels[:5] + [f"Остальные {len(labels) - 5}"], shares[:5] + [rest]
    vals = [round(x, 1) for x in shares]
    name = plan.plain_headline or "Доля"
    if opt.kind == "table":
        return TableData(columns=[cv.dim, "Доля, %"], rows=_part([[a, fmt_num(b, 1)] for a, b in zip(labels, vals)], part))
    if opt.kind in ("stacked_column", "stacked_bar"):
        return ChartSpec(type=opt.kind, categories=[name],
                         series=[InlineSeries(name=a, values=[b], unit="%") for a, b in zip(labels, vals)], unit="%",
                         y_title="Доля", source=src)
    kind = opt.kind if opt.kind in ("doughnut", "pie", "column", "bar") else "doughnut"
    return ChartSpec(type=kind, categories=labels, series=[InlineSeries(name="Доля", values=vals, unit="%")], unit="%",
                     highlight_index=0, x_title=cv.dim, y_title="Доля", source=src)


def _spec_distribution(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    dv = d.dist
    if dv is None:
        return None
    m = dv.measure
    unit = m.unit_text
    ent = phrase(dv.entity) if dv.entity else None
    count_name = f"Число {ent.low.gen_pl}" if ent is not None and ent.sure else "Число значений"
    if opt.kind == "kpi_cards":
        out = [NumberCallout(value=fmt_value(dv.median, unit), label="Медиана"),
               NumberCallout(value=fmt_value(dv.percentile(80), unit), label="80-й перцентиль"),
               NumberCallout(value=fmt_num(dv.n), label=count_name)]
        if dv.outliers:
            out.append(NumberCallout(value=fmt_num(len(dv.outliers)), label="Выбросы"))
        return out
    if opt.kind == "table":
        b = dv.bins
        return TableData(columns=[_col_title(m.name, m.unit), count_name],
                         rows=_part([[lab, fmt_num(c)] for lab, c in zip(b.labels, b.counts)], part))
    b = dv.bins
    return ChartSpec(type="histogram", categories=list(b.labels),
                     series=[InlineSeries(name=count_name, values=[float(c) for c in b.counts])], unit=None,
                     x_title=_col_title(m.name, m.unit), y_title=count_name, source=src)


def _spec_reference(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    rv = d.ref
    if opt.kind == "bar" and rv.measure is not None:
        m = rv.measure
        labs = [r[0] for r in rv.rows]
        order = sorted(d.rows_idx, key=lambda i: (-(m.values[i] if m.values[i] is not None else -math.inf), i))
        vals = [float(m.values[i] or 0) for i in order[:rv.top_n]]
        return ChartSpec(type="bar", categories=labs, series=[InlineSeries(name=m.name, values=vals, unit=m.unit_text)],
                         unit=m.unit_text, highlight_index=0, x_title=rv.label, y_title=m.name, source=src)
    if opt.kind == "bar":
        cv = d.cat_view(None)
        if cv is not None:
            return _cats_spec(cv, "bar", src)
    mode = _table_mode(opt) if opt.kind == "table" else "top"
    if mode == "top":
        rows = list(rv.rows) + ([rv.rest] if rv.rest else [])
        return TableData(columns=list(rv.columns), rows=rows, unit=rv.measure.unit_text if rv.measure else None)
    if mode == "head":
        return TableData(columns=list(rv.full_columns), rows=rv.all_rows[:TABLE_ROWS])
    return TableData(columns=list(rv.full_columns), rows=_part(rv.all_rows, part))


def _kpi_label(it, prev: Optional[str]) -> str:
    if it.change is None:
        return it.label
    s = f"{it.label}, {fmt_signed(it.change, it.change_unit or '')}"
    return s + (f" к {prev}" if prev else "")


def _spec_kpi(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    kv = d.kpi
    if kv is None:
        return None
    if opt.kind == "kpi_cards":
        return [NumberCallout(value=it.value_text, label=_kpi_label(it, kv.prev_period)) for it in kv.items[:6]]
    if opt.kind == "table":
        cols = ["Показатель", kv.period or "Значение"]
        has_prev = any(it.prev_text for it in kv.items)
        has_ch = any(it.change is not None for it in kv.items)
        if has_prev:
            cols.append(kv.prev_period or "Было")
        if has_ch:
            cols.append("Изменение")
        rows = []
        for it in kv.items:
            r = [it.label, it.value_text]
            if has_prev:
                r.append(it.prev_text or "—")
            if has_ch:
                r.append(fmt_signed(it.change, it.change_unit or "") if it.change is not None else "—")
            rows.append(r)
        return TableData(columns=cols, rows=rows)
    unit = kv.items[0].unit if kv.items else None
    return ChartSpec(type="column", categories=[it.label for it in kv.items],
                     series=[InlineSeries(name=kv.period or "Значение", values=[it.value for it in kv.items], unit=unit)],
                     unit=unit, source=src)


def _spec_relationship(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    xy = d.xy
    if xy is None:
        return None
    if opt.kind == "scatter":
        return ChartSpec(type="scatter", xy=[XYSeries(name=xy.y.name, x=list(xy.xs), y=list(xy.ys))],
                         x_title=_col_title(xy.x.name, xy.x.unit_text), y_title=xy.y.name, unit=xy.y.unit_text, source=src)
    if opt.kind == "table":
        rows = [[lab or str(k + 1), fmt_num(a), fmt_num(b)] for k, (lab, a, b) in enumerate(zip(xy.labels, xy.xs, xy.ys))]
        return TableData(columns=[d.entity or "№", _col_title(xy.x.name, xy.x.unit_text),
                                  _col_title(xy.y.name, xy.y.unit_text)], rows=_part(rows, part))
    cv = d.cat_view(xy.y, rank=True)
    if cv is None:
        return None
    return _cats_spec(cv, "grouped_bar", src, extra=[(xy.x.name, cv.extra.get(xy.x.name, []))])


# ── «Почему так» ──────────────────────────────────────────────────────────────────────────────────────────────────────
def slide_data_of(plan: DatasetPlan, part: tuple[int, int] = (1, 1)) -> SlideData:
    """Данные слайда для «Почему так»: профиль кратко, задача, варианты, факты заголовка. У справочника выбросы не
    показываются: крупнейшие клиенты в списке — это данные, а не проблема."""
    p = plan.profile
    line = " · ".join([
        _KIND_LABEL.get(p.kind, p.kind.upper()),
        f"{count_ru(p.rows, 'строка', 'строки', 'строк')} × {count_ru(p.cols, 'колонка', 'колонки', 'колонок')}",
        NATURE_LABELS[p.nature].lower(),
    ])
    opt = plan.chosen_option
    outliers = [] if plan.task.task in ("reference", "kpi") else list(p.outliers)
    return SlideData(
        dataset_id=p.table_id, file=p.file, profile_line=line, nature=p.nature, columns=list(p.columns),
        time_axis=p.time_axis, metrics=list(p.metrics), dimensions=list(p.dimensions), missing_total=p.missing_total,
        outliers=outliers, task=plan.task, options=list(plan.options), chosen=plan.chosen,
        headline_facts=list(plan.headline_facts), plain_headline=plan.plain_headline,
        aggregation=opt.aggregation if opt else None, part=part,
    )
