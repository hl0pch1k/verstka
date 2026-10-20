"""Решение по датасету (описание решения §2.3–2.6): профиль и таблица → `DatasetPlan`.

`plan_dataset(profile, table, goals)` — задача, 2–3 ранжированных варианта, заголовок-вывод с фактами, подпись,
источник, число слайдов и сообщение для нетипизируемых данных. `plan_datasets(tables, brief_text)` — то же для всех
файлов: цели из текста сопоставляются с датасетами (цель достаётся тому, о котором она говорит и где её задача
осуществима). `chart_spec_of(plan, table, option, part)` — данные слайда для выбранного (или другого — «Пересобрать
слайд так») варианта: `ChartSpec`, `TableData` или карточки `NumberCallout`; отвергнутый вариант не строится — вместо
данных `NotBuilt` с причиной. `slide_data_of(plan, part)` — `SlideData` для «Почему так».

Шаблон не входит ни в один вход: один датасет при любом шаблоне и любом формате файла даёт один и тот же вид."""

from __future__ import annotations

import math
from dataclasses import replace
import re
from typing import Optional, Sequence, Union

import numpy as np
from pydantic import BaseModel

from verstka.data.aggregate import MAX_SLIDES, RATE_GOAL, TABLE_ROWS, CatView, Data, KpiItem
from verstka.data.facts import FactSet, facts_for, plain_headline
from verstka.data.goals import Goal, goal_ask, goal_focus, goal_match, goals_of, stems_of
from verstka.data.words import same_stem, stem_in
from verstka.data.headline import _labels as headline_labels
from verstka.data.headline import compose
from verstka.data.parse import split_unit
from verstka.data.profile import profile_table
from verstka.data.derive import metric_goals
from verstka.data.task import FEASIBLE, _infeasible_reason, ask_feasible, decide_task, task_scores
from verstka.data.verify import numbers_ok, verify
from verstka.data.viz import find_candidate, rank_options
from verstka.data.words import count_words, file_title, fmt_exact, fmt_num, fmt_signed, fmt_value, phrase, upper_first
from verstka.schemas.data import NATURE_LABELS, DatasetPlan, DatasetProfile, SlideData, Table, TaskDecision, VizOption
from verstka.schemas.outline import ChartSpec, InlineSeries, NumberCallout, TableData, XYSeries

__all__ = ["plan_dataset", "plan_datasets", "assign_goals", "goal_notes", "file_context", "chart_spec_of", "slides_of", "slide_data_of", "data_of",
           "SlideBody", "NotBuilt"]


class NotBuilt(BaseModel):
    """Вариант не строится (отвергнут по данным): причина — для «Пересобрать слайд так» и ленты агента."""

    reason: str


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


def _honest_goal(decision: TaskDecision, d: Data, goal: Optional[Goal] = None) -> TaskDecision:
    """«Цель совпала» — только если показана та величина, о которой цель: колонка, выбранная по главному слову цели
    (буквально или по смыслу: «дольше ждут» — срок, «денег» — рубли). Показана другая колонка — так и сказано
    («показано «Заявлений», а не «Срок рассмотрения, дн.»: …»); главного слова нет ни в одной колонке — тоже
    («величины «удержание» в колонках нет»). Слово-уточнение цели («по заявлению») в показанной колонке — не довод:
    оно о предмете, а не о величине."""
    if not decision.goal:
        return decision
    if goal is not None and goal.given:
        if not goal.column or d.main is None or d.main.name == goal.column or \
                f"{d.main.name}, {d.main.unit or ''}" == goal.column:
            return decision  # колонку назвала цель — она и показана
        reasons = [r for r in decision.reasons if not (r.startswith(f"Цель «{decision.goal}»") and (
            "совпала" in r or "той же задаче" in r))]
        return decision.model_copy(update={"reasons": reasons + [
            f"Цель «{decision.goal}»: показано «{d.main.name}», а не «{goal.column}»: эта колонка не отвечает на цель."]})
    metric, head, _ = goal_focus(decision.goal)
    if not head:
        return decision
    word = next((w for w in re.findall(r"[а-яёa-z0-9]+", decision.goal.lower()) if w.replace("ё", "е").startswith(head)),
                head)
    m = d.main
    hm = d.head_measure if d.head == head else None
    literal = m is not None and any(stem_in(head, w) for w in stems_of(m.name))
    by_goal = m is not None and (literal or (hm is not None and hm.j == m.j) or d.head_syn(m))
    quals = m is not None and hm is None and not d.head_in_columns and any(
        stem_in(x, w) for x in metric if len(x) >= 3 and x != head for w in stems_of(m.name))
    title = any(stem_in(head, w) for w in stems_of(file_title(d.profile.file, d.profile.sheet)))
    focus = d.time.focus if decision.task == "dynamics" and d.time is not None else None
    if focus and any(stem_in(x, w) for x in [head] + [y for y in metric if len(y) >= 4] for w in stems_of(focus)):
        return decision  # цель назвала строку («облачной платформы»): ряд — по ней
    if decision.task == "comparison" and d.matrix_focus_rows and d.matrix_axis == "col":
        return decision  # перекрёстная таблица: колонки сравнены по строке, которую назвала цель (она в заголовке)
    if by_goal or quals or (title and not d.head_in_columns):
        return decision
    shown = m.name if m is not None else "—"
    if hm is not None:
        note = f"Цель «{decision.goal}»: показано «{shown}», а не «{hm.name}»: эта колонка не отвечает на цель."
    elif d.head_in_columns:
        note = f"Цель «{decision.goal}»: показано «{shown}», а не «{word}»: величина цели — в другой колонке."
    else:
        note = f"Цель «{decision.goal}»: величины «{word}» в колонках нет — показан главный вывод по данным."
    reasons = [r for r in decision.reasons if not (r.startswith(f"Цель «{decision.goal}»") and ("совпала" in r or
                                                                                               "той же задаче" in r))]
    return decision.model_copy(update={"reasons": reasons + [note]})


_SPEC_FIELDS = ("head", "metric", "negate", "ask", "column", "dimension", "categories", "weight", "period", "n", "versus",
                "derive")


def goal_spec(g: Optional[Goal]) -> Optional[dict]:
    """Поля цели, понятой снаружи (модель), — для `TaskDecision.spec`: данные слайда и пересборка видят ту же
    величину без разбора фразы. Цель из текста — None (её разбирает фраза)."""
    if g is None or not g.given:
        return None
    return g.model_dump(include=set(_SPEC_FIELDS), mode="json")


def _given_of(spec: Optional[dict], phrase: Optional[str]) -> Optional[Goal]:
    if not spec:
        return None
    return Goal(phrase=phrase or "", task="comparison", viz="bar", to="", given=True, **spec)


def goal_data(table: Table, profile: DatasetProfile, phrase: Optional[str], compare: bool = False,
              goal: Optional[Goal] = None) -> Data:
    """`Data` глазами цели: предмет — основы её слов, величина — главное слово, уточнения и отрицания
    («по цене с НДС» → «цен», уточнение «ндс»; «без НДС» — отрицание). Цель, понятая снаружи (`goal.given`: модель),
    задаёт всё сама — колонку, разрез, категории, вес, период и вопрос (и «max» — тоже ответ: фразу не разбирают);
    разбор фразы — для целей из текста. Состояние — только в аргументах: ничего не помнится между вызовами."""
    if goal is not None and goal.given:
        from verstka.data.asks import ASKS

        phrase = phrase or goal.phrase
        ask = None if goal.ask in (None, "max", "null") or goal.ask in ASKS else goal.ask
        if ask == "meet" and goal_ask(phrase or "") == "miss":
            ask = "miss"  # «какие магазины не выполнили план» — кто ниже плана, а не исполнение в целом
        metric = list(goal.metric)
        head = goal.head
        negate = list(goal.negate)
        if not goal.column and not head and not metric and phrase:
            # колонку модель не назвала (или её нет в данных) — величину ищет фраза, как у цели из текста
            metric, head, negate = goal_focus(phrase)
        period = goal.period.model_dump() if goal.period is not None else None
        th = re.search(r"(\d+(?:[.,]\d+)?)", ask or "") if (ask or "").startswith(("above:", "below:")) else None
        unit = None
        if th is not None and goal.column:
            # порог — к своей колонке: единица порога — её единица
            cu = next((c.unit for c in profile.columns if c.name == goal.column or
                       f"{c.name}, {c.unit}" == goal.column), None)
            unit = "%" if (cu or "").strip() == "%" else None
        months = tuple(_MONTH_STEMS.index(mm.group(1)) + 1 for mm in _MONTH_RX.finditer((phrase or "").lower()))
        p_ = goal.period
        one_month = p_ is not None and p_.kind == "range" and bool(p_.start) and bool(p_.end) and \
            (p_.start or "")[:7] == (p_.end or "")[:7] and re.fullmatch(r"\d{4}-\d{2}.*", p_.start or "") is not None
        if one_month and not months:
            months = (int((p_.start or "")[5:7]),)  # «за ноябрь»: диапазон в один месяц
        if ask == "spike" or (ask == "total" and one_month):
            # всплеск ищут на всём ряду (неделя всплеска — в названном месяце); итог месяца считают по дням месяца,
            # а сравнение с другим месяцем — по всему файлу
            period = None
        if goal.ask == "period_min":
            ask = None
        cats = () if goal.ask in ("share_of", "top_n", "position") else tuple(goal.categories)  # доля названных — от всех строк
        return Data(table, profile, subject=tuple(stems_of(phrase or "")), compare=compare, head=head,
                    negate=tuple(negate), qualifiers=tuple(x for x in metric if x != head), ask=ask,
                    ask_unit=unit, ask_periods=tuple(dict.fromkeys(months)), column=goal.column,
                    dimension=goal.dimension, categories=cats, weight=goal.weight, period=period, goal_text=phrase)
    if not phrase:
        return Data(table, profile, compare=compare)
    metric, head, negate = goal_focus(phrase)
    ask = goal_ask(phrase)
    if (ask or "").startswith(("above:", "below:")) and _threshold_is_a_name(phrase, profile):
        ask = None  # «просрочка свыше 90 дней» — колонка «Свыше 90 дней», а не порог
    pct = re.search(r"(?:выше|больше|ниже|меньше|свыше|более|менее)\s+\d+(?:[.,]\d+)?\s*(?:%|процент)", phrase.lower())
    pre = tuple(x for x in metric[:metric.index(head)]) if head in metric else None
    months = tuple(_MONTH_STEMS.index(mm.group(1)) + 1 for mm in _MONTH_RX.finditer(phrase.lower()))
    return Data(table, profile, subject=tuple(stems_of(phrase)), compare=compare, head=head, negate=tuple(negate),
                qualifiers=tuple(x for x in metric if x != head), ask=ask, ask_unit="%" if pct else None,
                pre_qualifiers=pre, ask_periods=tuple(dict.fromkeys(months)), goal_text=phrase)


def _other_mean(rel: Sequence[Goal], goal_phrase: Optional[str], table: Table, profile: DatasetProfile, d: Data,
                fs: FactSet) -> Optional[str]:
    """Другая цель того же датасета спрашивает среднее той же величины («какой средний балл по району в целом и какие
    школы ниже 60»): слайд один и отвечает на порог, среднее — в подписи, с весом, если он есть."""
    for g in rel:
        if g.phrase == goal_phrase or (g.ask if g.given else goal_ask(g.phrase)) != "mean":
            continue
        d2 = goal_data(table, profile, g.phrase, compare=True, goal=g)
        if d2.main is None or d.main is None or d2.main.name != d.main.name:
            continue
        d2.ask = "mean"
        fs2 = facts_for("comparison", d2)
        f = fs2.get("overall_mean")
        if f is None or "overall_mean" not in fs2.prov:
            continue
        fs.add("other_mean", f.value, f.kind, f.text, f.unit, f.explain, prov=fs2.prov["overall_mean"])
        w = d2.weight_of(d2.main)
        return f"В целом — {fmt_value(f.value, f.unit)}" + (f" (с весом по «{w.name}»)." if w is not None else ".")
    return None


def _other_extreme(rel: Sequence[Goal], goal_phrase: Optional[str], table: Table, profile: DatasetProfile, d: Data,
                   fs: FactSet, said: str = "") -> Optional[str]:
    """Другая цель того же датасета спрашивает, кто первый (последний) по другой колонке («какие категории решаются
    дольше всего и где SLA ниже 90%»): слайд один — о первой цели, ответ на вторую — в подписи."""
    from verstka.data.aggregate import is_other_label
    from verstka.data.facts import _pcat

    for g in rel:
        if g.phrase == goal_phrase or not g.given or g.task != "comparison":
            continue
        ask = g.ask if g.ask in ("max", "min", None) else "skip"
        if ask == "skip":
            continue
        d2 = goal_data(table, profile, g.phrase, compare=True, goal=g)
        m2, cv = d2.main, d2.cats
        if m2 is None or cv is None or d.main is None or m2.name == d.main.name or m2.j < 0:
            continue
        real = [k for k in range(cv.n) if not is_other_label(cv.labels[k]) and not cv.labels[k].startswith("Остальные")]
        if len(real) < 2:
            continue
        low = ask == "min"
        k = (min if low else max)(real, key=lambda k_: (cv.values[k_], -k_ if not low else k_))
        lab, v = cv.labels[k], cv.values[k]
        if lab in said:
            return None  # уже сказано («больше всех — Фасад: +19,6%»)
        fs.add("other_extreme", v, "min" if low else "leader", f"{lab} — {fmt_value(v, cv.unit)}", cv.unit,
               f"{'Меньше' if low else 'Больше'} всех по колонке «{m2.name}».",
               prov=_pcat(d2, m2, cv.dim, [lab], rank="min" if low else "max",
                          exclude=tuple(x for x in cv.labels if is_other_label(x))))
        fs.ctx.setdefault("labels", []).append(lab)
        return f"«{m2.name}»: {'меньше' if low else 'больше'} всех — {lab}, {fmt_value(v, cv.unit)}."
    return None


def _threshold_is_a_name(phrase: str, profile: DatasetProfile) -> bool:
    """Число цели — часть имени колонки («свыше 90 дней» — колонка «Свыше 90 дней»), а не порог."""
    m = re.search(r"(?:выше|больше|ниже|меньше|свыше|более|менее)\s+(\d+(?:[.,]\d+)?)", (phrase or "").lower())
    if not m:
        return False
    return any(re.search(r"(?:выше|больше|ниже|меньше|свыше|более|менее|от|до)\s+" + re.escape(m.group(1)) + r"\b",
                         c.name.lower()) for c in profile.columns)


_MONTH_STEMS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр",
                "декабр"]
# месяц в любой форме: «за ноябрь», «с октябрём», «в мае»
_MONTH_RX = re.compile(r"\b(январ|феврал|март|апрел|ма(?=[йяеюё]\b)|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", re.I)


def data_of(plan: DatasetPlan, table: Table) -> Data:
    """Тот же `Data`, что видел план (главная метрика — по цели, которая решила задачу; у сравнения — колонка-итог;
    цель, понятая моделью, — по её полям из `TaskDecision.spec`, без разбора фразы). Колонка-отношение цели
    («выручка на одного посетителя») добавляется к таблице файла снова (`derive.apply`), если её там нет."""
    from verstka.data.derive import apply as derive_apply

    spec = plan.task.spec or {}
    if spec.get("derive"):
        table = derive_apply(table, spec["derive"])
    return goal_data(table, plan.profile, plan.task.goal, compare=plan.task.task == "comparison",
                     goal=_given_of(plan.task.spec, plan.task.goal))


def _source(p: DatasetProfile) -> str:
    return f"Источник: {p.file}" + (f", лист «{p.sheet}»" if p.sheet and p.kind == "xlsx" else "")


def plan_dataset(profile: DatasetProfile, table: Table, goals: Optional[Sequence[Goal]] = None,
                 assigned: bool = False) -> DatasetPlan:
    """Задача, варианты, заголовок-вывод и факты одного датасета. `goals` — цели (из текста брифа или понятые моделью,
    `verstka/data/intent.py`); к датасету относятся только те, что о нём (предмет совпал с файлом, колонками или
    значениями) или без предмета. `assigned=True` — цели уже распределены по датасетам (`plan_datasets`), повторно их
    не фильтруем."""
    d0 = Data(table, profile)
    rel = list(goals or []) if assigned else _relevant(goals or [], d0)
    first = decide_task(Data(table, profile, subject=tuple(s for g in rel for s in g.subject)), rel)
    g_first = next((g for g in rel if g.phrase == first.goal), None)
    subject = tuple(stems_of(first.goal)) if first.goal else ()
    d = goal_data(table, profile, first.goal, goal=g_first) if subject or (g_first is not None and g_first.given) \
        else d0
    decision = decide_task(d, rel)
    g_dec = next((g for g in rel if g.phrase == decision.goal), None)
    if decision.goal and decision.goal != first.goal:
        # задачу решила другая цель — данные глазами её (как их увидит `data_of`)
        d = goal_data(table, profile, decision.goal, goal=g_dec)
    decision = decision.model_copy(update={"spec": goal_spec(g_dec)}) if g_dec is not None else decision
    decision = _honest_goal(decision, d, g_dec)
    source = _source(profile)
    title = file_title(profile.file, profile.sheet)

    base = task_scores(d)
    if not profile.typable and base.get("reference", 0.0) <= 0.0 and not d.measures:
        reason = profile.untypable_reason or "данные не складываются в график"
        msg = f"Не для графика: {reason}"
        return DatasetPlan(profile=profile, task=TaskDecision(task="reference", reasons=[msg + "."], scores=base),
                           options=[], chosen=0, headline="", plain_headline=title, source=source, slides=0,
                           message=msg)

    task = decision.task
    if task == "comparison":
        # сравнение категорий — по колонке-итогу («Итого за год»), если она есть, а не по первой части
        d = goal_data(table, profile, decision.goal or first.goal, compare=True,
                      goal=g_dec if decision.goal else g_first)
    data_task = max(base, key=lambda k: base[k])
    raised = decision.goal is not None and base[data_task] > base[task]
    options = rank_options(task, d, [g for g in rel if base.get(g.task, 0) >= FEASIBLE or g.task == task], raised)
    th_goal = None
    if d.ask is None and not (g_dec is not None and g_dec.given and (g_dec.ask or "").startswith(("above", "below"))):
        # порог цели («какие серверы загружены выше 80%») — ответ и тогда, когда сравнивать категории нечем; порог —
        # к своей колонке: цель о другой величине свой порог показанной колонке не передаёт
        th_goal = next((g for g in rel if ((g.ask if g.given else goal_ask(g.phrase)) or "").startswith(
            ("above:", "below:"))), None)
        if th_goal is not None and th_goal.given:
            gd_ = goal_data(table, profile, th_goal.phrase, goal=th_goal)
            if gd_.main is None or d.main is None or gd_.main.name != d.main.name:
                th_goal = None
        if th_goal is not None and not th_goal.given and _threshold_is_a_name(th_goal.phrase, profile):
            th_goal = None
        if th_goal is not None:
            d.ask = th_goal.ask if th_goal.given else goal_ask(th_goal.phrase)
            if re.search(r"\d\s*(?:%|процент)", th_goal.phrase):
                d.ask_unit = "%"
    if d.ask == "total" and len(d.ask_periods) == 1:
        # итог месяца, а другая цель того же предложения сравнивает его с другим месяцем («… как это соотносится с
        # октябрём»): база сравнения — её месяц
        for g in rel:
            p_ = g.period if g.given else None
            if p_ is not None and p_.kind == "compare" and p_.base and re.fullmatch(r"\d{4}-\d{2}.*", p_.base):
                mb = int(p_.base[5:7])
                if mb != d.ask_periods[0]:
                    d.ask_periods = (d.ask_periods[0], mb)
                    break
    fs = facts_for(task, d)
    headline, caption = compose(task, fs)
    # вопрос, на который обычный вывод не отвечает (N крупнейших, доля названных, колонка против колонки, самый низкий
    # период): ответ — свои факты, проверенные тем же `verify` (F2)
    from verstka.data.asks import answer_ask

    asked = answer_ask(g_dec, d, task, fs) if g_dec is not None and g_dec.given else None
    if asked is not None:
        headline, caption, fs = asked
    extra = _other_mean(rel, decision.goal, table, profile, d, fs) if task == "comparison" and asked is None else None
    if task == "comparison" and not extra and asked is None:
        extra = _other_extreme(rel, decision.goal, table, profile, d, fs, f"{headline} {caption or ''}")
    if extra:
        caption = f"{extra} {caption}" if caption else extra
    plain = fs.ctx.get("plain") or title
    if th_goal is not None and fs.ctx.get("threshold"):
        side, thr = fs.ctx["threshold"][:2]
        rs = [r for r in decision.reasons if not (r.startswith(f"Цель «{th_goal.phrase}»") and "не подходит" in r)]
        rs.append(f"Цель «{th_goal.phrase}»: показано, кто {'выше' if side == 'above' else 'ниже'} {thr}.")
        decision = decision.model_copy(update={"reasons": rs})
    message = None
    if not profile.typable and options and options[0].kind == "table":
        message = f"Не для графика: {profile.untypable_reason or 'данные не складываются в график'} — показываю таблицей"
    elif d.not_numbers and not d.measures and options and options[0].kind == "table":
        message = (f"Не для графика: в колонке «{d.not_numbers[0]}» — номера, а не величины (повторяются, без единицы) "
                   f"— показываю таблицей")
    if message and task == "reference":
        # перечень (расписание, список) — заголовок называет его, а не «12 аудиторий из 5 дней»; без чисел из имени
        # файла («10Б»): в заголовке каждое число — факт
        words = [w for w in title.split() if not re.search(r"\d", w)]
        name = " ".join(words[:3]) if words else "Перечень"
        headline = f"{upper_first(name)}: {count_words(d.n, 'строка', 'строки', 'строк')}"
    headline = headline or plain
    freq_note = _freq_note(decision.goal, d, task)
    if freq_note:
        decision = decision.model_copy(update={"reasons": list(decision.reasons) + [freq_note]})
    facts = list(fs.facts)
    # самопроверка: каждое число заголовка и подписи пересчитано по сырым строкам файла; не подтвердилось — тема
    # вместо вывода и подпись только из подтверждённого, причина — в «Почему так»
    labels = _check_labels(fs, d, title)
    # «Остальные 3» — подпись группы на графике, её цифра — имя, а не число вывода (раунд 9, V2)
    labels += re.findall(r"[Оо]стальны[ех]\s+\d+(?:\s+[а-яё]+)?", f"{headline} {caption or ''}")
    verdict = verify(table, fs.facts, fs.prov, "" if headline == plain else headline, caption, labels, title,
                     bins=_bins_claim(d, task))
    if not verdict.headline_ok:
        headline = plain
        if any("— не колонка «" in r for r in verdict.reasons):
            # отвергнут пересказ имени колонки («покупок мест» при «Куплено мест») — тема её же именем
            headline = plain = plain_headline(task, d, own=True)
        facts = [f for f in fs.facts if f.id in verdict.ok]
    if not verdict.caption_ok:
        caption = _factual_caption(fs, verdict, labels)
    if verdict.reasons:
        decision = decision.model_copy(update={"reasons": list(decision.reasons) + verdict.reasons})
    plan = DatasetPlan(
        profile=profile, task=decision, options=options, chosen=0, headline=headline, headline_facts=facts,
        plain_headline=plain, caption=caption, source=source, slides=1, message=message,
    )
    plan.slides = slides_of(plan, table, 0, d)
    return plan


_FREQ_ASK = {"дням": "day", "неделям": "week", "месяцам": "month", "кварталам": "quarter", "годам": "year"}
_FREQ_SHOWN = {"day": "по дням", "week": "по неделям", "month": "по месяцам", "quarter": "по кварталам", "year": "по годам",
               "hour": "по часам", "irregular": "по датам"}


def _freq_note(goal: Optional[str], d: Data, task: str) -> Optional[str]:
    """Цель просит «по месяцам», а ряд показан по неделям: это сказано и почему (не молча)."""
    m = re.search(r"по\s+(дням|неделям|месяцам|кварталам|годам)", goal or "")
    tv = d.time if task == "dynamics" else None
    if m is None or tv is None or tv.freq == _FREQ_ASK[m.group(1)]:
        return None
    why = ""
    if tv.partial_txt:
        why = f": крайние периоды неполные ({tv.partial_txt[0]})"
    elif tv.freq == "week" and _FREQ_ASK[m.group(1)] == "month":
        why = ": месяцы в ряду неполные или их мало — по неделям ряд честнее и подробнее"
    return f"Цель просит «по {m.group(1)}», ряд показан {_FREQ_SHOWN.get(tv.freq, tv.freq)}{why}."


def _bins_claim(d: Data, task: str) -> Optional[dict]:
    """Столбцы гистограммы слайда — для проверки по сырым значениям (открытые «больше X» и «меньше X» — все значения
    за X, выбросы тоже)."""
    if task != "distribution" or d.dist is None:
        return None
    dv, b = d.dist, d.dist.bins
    return {"col": dv.measure.j, "counts": list(b.counts), "labels": list(b.labels), "open_from": b.open_from,
            "open_to": b.open_to, "skip": sorted(set(d.totals) | set(d.benchmarks)), "scale": dv.measure.scale,
            "weighted": d.freq_table is not None}


def _check_labels(fs: FactSet, d: Data, title: str) -> list[str]:
    """Подписи, цифры которых — часть названия, а не вывод: категории и имена из фактов, периоды, файл, колонки."""
    out = headline_labels(fs) + list(fs.ctx.get("period_labels") or []) + list(fs.ctx.get("structure") or [])
    out += [title] + [c.name for c in d.cols] + [c.unit for c in d.cols if c.unit]
    out += [m.unit_text for m in d.measures if m.unit_text] + _values_for_match(d)
    out = [x for x in out if isinstance(x, str) and x]
    return out + [upper_first(x) for x in out] + [x[:1].lower() + x[1:] for x in out]


_FACT_ORDER = ("total", "max", "leader", "median", "share", "change", "min", "count")


def _factual_caption(fs: FactSet, verdict, labels: list[str]) -> Optional[str]:
    """Подпись только из подтверждённых фактов (одна-две фразы); подтверждённых нет — без подписи."""
    ok = [f for f in fs.facts if f.id in verdict.ok and f.text and not numbers_ok(f.text, verdict.pool, labels)]
    ok.sort(key=lambda f: _FACT_ORDER.index(f.kind) if f.kind in _FACT_ORDER else len(_FACT_ORDER))
    parts = [upper_first(f.text.rstrip(".")) + "." for f in ok[:2]]
    return " ".join(parts) or None


def _file_match(g: Goal, d: Data) -> bool:
    """Цель называет датасет целиком: каждое слово предмета есть в имени файла или в колонках, и хотя бы одно — в имени
    файла («на что ушёл бюджет НИОКР» → «Бюджет НИОКР.csv»; «сравни классы по среднему баллу» — не «Средний чек»)."""
    if not g.subject:
        return False
    if goal_match(g, d.profile.model_copy(update={"columns": []})) < 1.0:
        return False
    words = stems_of(file_title(d.profile.file, d.profile.sheet) + " " + " ".join(c.name for c in d.profile.columns))
    return all(any(stem_in(s, w) for w in words) for s in g.subject)


# слова величины цели, которые колонку не называют, а описывают: статистика («средней»), темп («изменению»), величина
# на душу («обеспеченности», «уровню») — им отвечают колонка-изменение, колонка «на 1 000 жителей» или среднее
_STAT_METRIC = re.compile(r"^(?:средн|медиан|общ|суммарн|итогов|совокупн)")
_CHANGE_METRIC = re.compile(r"^(?:изменен|рост|прирост|динамик|снижен|паден|отклонен)")


def _near(a: str, b: str) -> bool:
    """Одно слово: основы совпадают, одна — часть сложного слова, или общее начало от 6 букв («преступн» и
    «преступлен»)."""
    if stem_in(a, b):
        return True
    k = 0
    for x, y in zip(a, b):
        if x != y:
            break
        k += 1
    return k >= 6


def _metric_ok(g: Goal, d: Data) -> bool:
    """Величина цели («по прибыли») есть в колонках или в названии файла; цель без величины — да. Слова-описания
    величины понимаются по смыслу: «по обеспеченности врачами», «по уровню преступности» — колонка на душу населения;
    «по изменению продаж» — колонка изменения; «по средней оценке» — среднее оценок."""
    if g.given and g.column:
        # цель называет колонку точно (модель): она есть — величина есть; слова её имени не сверяются
        return any(m.name == g.column or f"{m.name}, {m.unit or ''}" == g.column for m in d.measures) or any(
            c.name == g.column for c in d.profile.columns)
    if not g.metric:
        return True
    words = stems_of(file_title(d.profile.file, d.profile.sheet) + " " + " ".join(
        f"{c.name} {c.unit or ''}" for c in d.profile.columns))
    # и шапка файла как была («Мячи» над «Забито» и «Пропущено»)
    words += stems_of(" ".join(x for x in (getattr(d.table, "raw_header", None) or []) if x))
    # и слова, которые цели считают служебными («Выполнение» — колонка, хотя «выполнение плана» — слово задачи)
    words += [x for x in (re.sub(r"(?:ием|ием|ией|ию|ия|ие|ий|ем|ом|ам|ой|ы|и|а|е|у|ю|я)$", "", w)
                          for c in d.profile.columns for w in re.findall(r"[а-яё]{5,}", c.name.lower())) if len(x) >= 4]
    metric = list(g.metric)
    if g.head and d.head == g.head and any(d.head_syn(x) for x in d.measures):
        # главное слово найдено по смыслу («дольше ждут» — срок, «денег» — рубли, «загруженная» — посещения):
        # остальные слова величины проверяем как обычно
        metric = [s_ for s_ in metric if s_ != g.head]
        if not metric:
            return True
    if any(RATE_GOAL.match(s_) for s_ in metric):
        if d.rate_measure is None:
            return False
        metric = [s_ for s_ in metric if not RATE_GOAL.match(s_)]
    if any(_CHANGE_METRIC.match(s_) for s_ in metric) and any(m.change for m in d.measures):
        metric = [s_ for s_ in metric if not _CHANGE_METRIC.match(s_)]
    metric = [s_ for s_ in metric if not _STAT_METRIC.match(s_)] or metric[:0]
    # части сложных слов тоже: «воды» — в «Водопотребление», «на человека» — в единице «л/сут на человека»
    if all(any(_near(s_, w) for w in words) for s_ in metric):
        return True
    rj = d._matrix_rows() if d.matrix else None
    if rj is not None:
        # перекрёстная таблица: величина цели — строка («удовлетворённость зарплатой» — «Моя зарплата справедлива»)
        rows_w = stems_of(" ".join(d.text(i, rj) for i in d.rows_idx))
        if any(len(s_) >= 5 and any(_near(s_, w) for w in rows_w) for s_ in metric):
            return True
    # цель называет колонку своими словами: «просрочка свыше 90 дней» — колонка «Свыше 90 дней» (два слова цели в
    # одном имени колонки)
    subj = [x for x in stems_of(g.phrase) if len(x) >= 3] + re.findall(r"\d+", g.phrase)
    return any(sum(1 for x in subj if any(x == w or _near(x, w) for w in stems_of(c.name) + re.findall(r"\d+", c.name)))
               >= 2 for c in d.profile.columns if c.role == "metric")


def _unmet_reason(g: Goal, d: Data) -> str:
    """Почему цель не выполнима на датасете — для «Почему так»."""
    if not _metric_ok(g, d):
        what = " ".join(g.metric) if g.metric else ""
        return f"в данных нет величины, о которой она говорит{f' («{what}…»)' if what else ''}"
    return _infeasible_reason(g.task, d)


def assign_goals(goals: Sequence[Goal], datas: Sequence[Data]) -> list[list[Goal]]:
    """Цель — каждому датасету, который она называет по имени файла и где её задача осуществима; если по имени не
    назван ни один — тем, о которых она больше всего говорит (совпадение предмета с файлом, колонками и значениями плюс
    половина балла задачи по данным). Цель без предмета — лучшему по задаче."""
    out: list[list[Goal]] = [[] for _ in datas]
    values = [_values_for_match(d) for d in datas]
    for g in goals:
        # данные глазами цели: главная метрика — по её предмету («структура выручки» — выручка, а не цена)
        gd = [goal_data(d.table, d.profile, g.phrase, goal=g) if g.subject or g.given else d for d in datas]
        scores = [task_scores(x) for x in gd]
        # величина цели («по прибыли», «по среднему баллу») должна быть в данных — иначе цель не об этом датасете
        ok = [_metric_ok(g, x) and ask_feasible(g, x) for x in gd]
        named = [k for k, d in enumerate(datas)
                 if ok[k] and scores[k].get(g.task, 0.0) >= FEASIBLE and _file_match(g, d)]
        if named:
            for k in named:
                out[k].append(g)
            continue
        best, who = 0.0, []
        for k, d in enumerate(datas):
            s = scores[k].get(g.task, 0.0)
            if s < FEASIBLE or not ok[k]:
                continue
            mt = goal_match(g, d.profile, values[k])
            if mt <= 0:
                continue
            c = round(mt + 0.5 * s, 6)
            if c > best + 1e-9:
                best, who = c, [k]
            elif abs(c - best) <= 1e-9:
                who.append(k)
        if not who and g.subject:
            # предмет не назван так, чтобы датасет мог ответить («как растёт наука»: «наук» есть лишь в названиях
            # институтов бюджета, где нет ряда по годам) — цель достаётся единственному датасету, где её задача
            # осуществима лучше всего; при равенстве — никому
            feas = [(scores[k].get(g.task, 0.0), k) for k in range(len(datas))
                    if scores[k].get(g.task, 0.0) >= FEASIBLE and ok[k]]
            if feas:
                best_s = max(s_ for s_, _ in feas)
                top = [k for s_, k in feas if abs(s_ - best_s) < 1e-9]
                if len(top) == 1:
                    who = top
        if not who:
            # цель не выполнима ни на одном датасете — не теряется: достаётся самому похожему по предмету (или
            # единственному) с причиной, почему не выполнена; совсем ни о чём — в контекст колоды (`goal_notes`)
            near = sorted(((goal_match(g, d.profile, values[k]) + (1.0 if _file_match(g, d) else 0.0), -k)
                           for k, d in enumerate(datas)), reverse=True)
            if near and (near[0][0] > 0 or len(datas) == 1):
                k = -near[0][1]
                out[k].append(g.model_copy(update={"unmet": _unmet_reason(g, gd[k])}))
            continue
        for k in who:
            out[k].append(g)
    return out


def goal_notes(brief_text: str, plans: Sequence[DatasetPlan]) -> list[str]:
    """Цели текста, которые не достались ни одному датасету (ни о чём в файлах), — строки для контекста колоды."""
    used = " ".join(" ".join(p.task.reasons) + " " + (p.task.goal or "") for p in plans)
    out = []
    for g in goals_of(brief_text):
        if g.phrase not in used:
            out.append(f"Цель «{g.phrase}» данными не подтверждается: ни в одном файле нет того, о чём она.")
    return out


def plan_datasets(tables: Sequence[Table], brief_text: str = "",
                  profiles: Optional[Sequence[DatasetProfile]] = None,
                  goals: Optional[Sequence[Goal]] = None) -> list[DatasetPlan]:
    """Планы всех датасетов; цели из текста — каждая своему датасету. `goals` — цели, понятые снаружи (модель,
    `verstka/data/intent.py`): тогда текст брифа не разбирается, а цели распределяются по датасетам так же; у целей,
    понятых моделью (`given`), колонка, разрез, категории, вес, период и вопрос задают данные вместо разбора фразы
    и сохраняются в плане (`TaskDecision.spec`)."""
    profs = list(profiles) if profiles is not None else [profile_table(t) for t in tables]
    if goals is not None:
        # цель снаружи с величиной (`head`, `metric`, `negate`) — явная: её поля выбирают колонку, фразу не разбирают
        goals = [g if g.given or not (g.head or g.metric or g.negate) else g.model_copy(update={"given": True})
                 for g in goals]
    else:
        goals = goals_of(brief_text)
    datas = [Data(t, p) for t, p in zip(tables, profs)]
    per = assign_goals(goals, datas)
    out = []
    for t, p, g in zip(tables, profs, per):
        # вопрос плана, которому отвечает производная мера (конверсия этапов воронки, затраты на клиента): колонка-
        # отношение добавляется к таблице, цель — к ней (`derive.metric_goals`); `data_of` добавит её снова по `spec`
        t2, g2, mq = metric_goals(t, list(g))
        p2 = profile_table(t2) if mq is not None else p
        out.append(_two_period_fastest(plan_dataset(p2, t2, g2, assigned=True), p2, t2, g2))
    return out


def _two_period_fastest(plan: DatasetPlan, profile: DatasetProfile, table: Table, goals: Sequence[Goal]) -> DatasetPlan:
    """«Какие сегменты растут быстрее всего» над двумя колонками-периодами («2024 · 2025»), понятое как динамика: ряд
    итога из двух точек, где сегментов не видно, а заголовок — о PaaS (жюри R25, раунд 3). Тот же вопрос как сравнение
    сегментов по периодам — сегменты рядом; он берётся, когда его проверенный вывод отвечает «быстрее всех»."""
    g = next((x for x in goals or [] if x.task == "dynamics" and x.ask == "fastest" and x.phrase == plan.task.goal), None)
    if g is None or plan.task.task != "dynamics":
        return plan
    d = Data(table, profile)
    tv = d.time
    if tv is None or tv.points > 2 or d.cats is None:
        return plan
    try:
        alt = plan_dataset(profile, table, [g.model_copy(update={"task": "comparison", "viz": "grouped_column"})],
                           assigned=True)
    except Exception:  # noqa: BLE001 - the dynamics stays
        return plan
    if alt.task.task == "comparison" and "быстрее всех" in (alt.headline or ""):
        return alt
    return plan


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
    if t == "comparison" and d.cats is not None:
        return d.cats.n
    if t == "shares" and d.shares is not None:
        return len(d.shares[0].labels)
    if t == "kpi" and d.kpi is not None:
        return len(d.kpi.items)
    return d.n


def _part(rows: list[list[str]], part: int) -> list[list[str]]:
    a = (max(1, part) - 1) * TABLE_ROWS
    return rows[a:a + TABLE_ROWS] or rows[:TABLE_ROWS]


def _col_title(name: str, unit: Optional[str]) -> str:
    return f"{name}, {unit}" if unit else name


def _cell(v: Optional[float]) -> str:
    """Значение в таблице — как в файле (142,6, а не 143)."""
    return fmt_exact(v)


def _pages_ok(rows: list[list[str]], part: int) -> Optional[NotBuilt]:
    pages = max(1, -(-len(rows) // TABLE_ROWS))
    if part > pages:
        return NotBuilt(reason=f"Слайда {part} нет: таблица занимает {count_words(pages, 'слайд', 'слайда', 'слайдов')}.")
    return None


def chart_spec_of(plan: DatasetPlan, table: Table, option: Optional[int] = None,
                  part: int = 1) -> Union[SlideBody, NotBuilt, None]:
    """Данные слайда для варианта `option` (по умолчанию — выбранного): `ChartSpec` для графиков, `TableData` для
    таблиц (`part` — номер слайда при разбиении, с 1), список `NumberCallout` для карточек. Отвергнутый по данным
    вариант (круговая на 8 долях, гистограмма из одного интервала) — `NotBuilt` с причиной. None — датасет пропущен."""
    opt = _option(plan, option)
    if opt is None:
        return None
    d = data_of(plan, table)
    task = plan.task.task
    cand = find_candidate(task, d, opt.kind, opt.title)
    if cand is not None and not cand.feasible:
        return NotBuilt(reason=cand.why_not or "Этот вариант не подходит к данным.")
    src = plan.source or _source(plan.profile)
    key = cand.key if cand is not None else ""
    if key == "child" and cand is not None and cand.dim is not None:
        cv = d.cat_view(d.main, dim=cand.dim)
        return _cats_spec(cv, "bar", src, unit=cv.unit) if cv is not None else None
    if key == "table_tree":
        return _tree_table(d, part)
    if key == "parts_total":
        return _parts_doughnut(d, src)
    if key == "xy_bins":
        return _xy_bins(d, src)
    if opt.title == "Карточки: итог и среднее":
        return _summary_cards(d)
    if opt.title.startswith("Столбцы: число строк по группам"):
        return _groups_spec(d, src)
    fn = {
        "dynamics": _spec_dynamics, "comparison": _spec_comparison, "shares": _spec_shares,
        "distribution": _spec_distribution, "reference": _spec_reference, "kpi": _spec_kpi,
        "relationship": _spec_relationship,
    }[task]
    return fn(d, opt, src, part, plan)


def _summary_cards(d: Data) -> Union[list[NumberCallout], NotBuilt]:
    m = d.main
    if m is None:
        return NotBuilt(reason="Чисел нет — карточкам нечего показать.")
    vals = m.present
    unit = m.unit_text
    out = []
    if m.additive and m.nonneg:
        out.append(NumberCallout(value=fmt_value(sum(vals), unit), label=f"{m.name}: итог"))
    out.append(NumberCallout(value=fmt_value(sum(vals) / len(vals), unit), label=f"{m.name}: среднее"))
    out.append(NumberCallout(value=fmt_num(len(vals)), label="Строк"))
    return out


def _groups_spec(d: Data, src: str) -> Union[ChartSpec, NotBuilt]:
    j = next((j for j in d.dims if j != d.label and 1 < d.cols[j].distinct < d.n), None)
    cv = d.cat_view(None, dim=j) if j is not None else None
    if cv is None:
        return NotBuilt(reason="Нет колонки с группами — считать нечего.")
    return _cats_spec(cv, "bar", src)


def _spec_dynamics(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    tv = d.time
    if tv is None:
        return _spec_reference(d, opt, src, part, plan)
    unit = tv.measure.unit_text if tv.measure.j != -1 else None
    yname = tv.measure.name if tv.measure.j != -1 else "Число строк"
    if opt.kind == "table":
        cols = [tv.axis_title] + [_col_title(s.name, s.unit) for s in tv.series]
        rows = [[lab] + [_cell(s.values[i]) for s in tv.series] for i, lab in enumerate(tv.labels)]
        bad = _pages_ok(rows, part)
        return bad if bad is not None else TableData(columns=cols, rows=_part(rows, part), unit=unit)
    if opt.kind == "kpi_cards":
        vals = [(lab, v) for lab, v in zip(tv.labels, tv.main.values) if v is not None]
        return [NumberCallout(value=fmt_value(v, unit), label=lab) for lab, v in vals[-3:]]
    series = [InlineSeries(name=s.name, values=list(s.values), unit=s.unit) for s in tv.series]
    cats = list(tv.labels)
    if (d.forecasts or d.forecast_rows) and not tv.split and opt.kind not in ("table", "kpi_cards"):
        cats, series = _with_forecast(d, tv, cats, series, joined=opt.kind in ("line", "area"))
    typo = [m for m in d.measures if d.typo_rows.get(m.name)]
    if typo and len(series) == 1:
        # опечатка убрана из ряда — это сказано в легенде: «Продажи (без выброса: июль 2025)»
        from verstka.data.facts import facts_for

        note = facts_for("dynamics", d).ctx.get("typo_note")
        if note:
            series[0] = series[0].model_copy(update={"name": f"{series[0].name} ({note})"})
    kind = opt.kind if opt.kind in ("line", "column", "area", "grouped_column", "stacked_column", "bar") else "line"
    last = max((i for i, v in enumerate(tv.main.values) if v is not None), default=None)
    if tv.split:
        kind = "line" if kind in ("stacked_column", "grouped_column") else kind
    # подпись оси значений есть всегда (единицу дописывает движок): один ряд — его имя; ряды одной единицы — общее
    # имя по датасету («Публикации», «Денежный поток»); ряды в разных единицах — у каждой части своя единица
    if tv.split:
        y_title = "Значение"
    elif len(series) == 1 or tv.dim:
        y_title = yname
    else:
        y_title = _series_title(d)  # ось — по величине; группа рядов из шапки — заголовок легенды
    return ChartSpec(type=kind, categories=cats, series=series, unit=None if tv.split else unit,
                     highlight_index=last if kind in ("line", "column", "area") and len(series) == 1 else None,
                     x_title=tv.axis_title, y_title=y_title, gaps=tv.gaps, source=src, split=tv.split,
                     legend_title=d.group_name if len(series) > 1 and not tv.dim else None)


def _with_forecast(d: Data, tv, cats: list[str], series: list[InlineSeries],
                   joined: bool = True) -> tuple[list[str], list[InlineSeries]]:
    """Прогноз — отдельным рядом «… (прогноз)»: колонки-прогнозы — на той же оси, строки-прогнозы («2026П») — ось
    продолжается их периодами, ряд факта там пустой; у линии прогноз начинается с последнего факта (продолжение
    линии), у столбцов — нет (второй столбец того же года — повтор факта)."""
    from verstka.data.parse import forecast_period, period_iso, period_parts
    from verstka.data.timeaxis import time_view
    from verstka.data.units import _num as _num_cell
    from verstka.data.words import period_label

    periods = list(tv.periods)
    out = list(series)
    if tv.from_columns and series:
        # колонки-годы и колонка «2026 (прогноз)»: ось продолжается периодом прогноза, ряд — «… (прогноз)» от
        # последнего факта (строка, названная целью, — её прогноз)
        rows = tv.only_rows or d.rows_idx
        pts = []
        for fm in d.forecasts:
            pp = period_parts(forecast_period(fm.name.strip()) or "")
            xs = [float(fm.values[i]) for i in rows if fm.values[i] is not None]  # type: ignore[arg-type]
            if pp is not None and xs and pp[0] == tv.freq:
                pts.append((period_iso(pp[0], pp[1]), sum(xs) if tv.how == "sum" else sum(xs) / len(xs)))
        pts = [x for x in sorted(pts) if x[0] not in periods]
        if pts:
            last = max((k for k, v in enumerate(series[0].values) if v is not None), default=None)
            n0 = len(periods)
            cats = cats + [period_label(p_, tv.freq) for p_, _ in pts]
            out = [x.model_copy(update={"values": list(x.values) + [None] * len(pts)}) for x in out]
            vals: list[Optional[float]] = [None] * n0 + [v for _, v in pts]
            if last is not None and joined:
                vals[last] = series[0].values[last]
            out.append(InlineSeries(name=f"{series[0].name} (прогноз)", values=vals, unit=series[0].unit))
        return cats, out
    for fm in d.forecasts:
        tvf = time_view(d, fm)
        if tvf is None:
            continue
        by = dict(zip(tvf.periods, tvf.main.values))
        name = fm.name if "прогноз" in fm.name.lower() else f"{fm.name} (прогноз)"
        out.append(InlineSeries(name=name, values=[by.get(p_) for p_ in periods], unit=series[0].unit if series else None))
    if d.forecast_rows and d.time_col is not None and series:
        m = tv.measure
        pts = []
        for i in sorted(d.forecast_rows):
            pp = period_parts(forecast_period(d.cell(i, d.time_col)) or str(d.cell(i, d.time_col) or ""))
            v = _num_cell(d.cell(i, m.j)) if m.j >= 0 else None
            if pp is not None and v is not None:
                pts.append((period_iso(pp[0], pp[1]), v / (m.scale or 1.0)))
        pts = [x for x in sorted(pts) if x[0] not in periods]
        if pts:
            last = max((k for k, v in enumerate(series[0].values) if v is not None), default=None)
            n0 = len(periods)
            cats = cats + [period_label(p_, tv.freq) for p_, _ in pts]
            out = [x.model_copy(update={"values": list(x.values) + [None] * len(pts)}) for x in out]
            fvals: list[Optional[float]] = [None] * n0 + [v for _, v in pts]
            if last is not None and joined:
                fvals[last] = series[0].values[last]
            out.append(InlineSeries(name=f"{series[0].name} (прогноз)", values=fvals, unit=series[0].unit))
    return cats, out


def _series_title(d: Data) -> str:
    """Общее имя нескольких рядов одной единицы — по названию датасета без периода и чисел: «Публикации по годам» →
    «Публикации», «Денежный поток 2025» → «Денежный поток»."""
    title = re.split(r"\s+(?:по|за|в|на|с)\s+", file_title(d.profile.file, d.profile.sheet), maxsplit=1)[0]
    words = [w for w in title.split() if not re.search(r"\d", w)]
    return upper_first(" ".join(words)) if words else "Значение"


def _argmax(values: Sequence[Optional[float]], labels: Optional[Sequence[str]] = None) -> Optional[int]:
    """Выделенный столбец — лидер по значению; «Прочее» файла и «Остальные N» — никогда (как и в фактах)."""
    from verstka.data.aggregate import is_other_label

    ks = [k for k, v in enumerate(values) if v is not None
          and not (labels is not None and k < len(labels) and (is_other_label(labels[k])
                                                               or str(labels[k]).startswith("Остальные ")))]
    return max(ks, key=lambda k: (values[k], -k)) if ks else None


def _cats_spec(cv: CatView, kind: str, src: str, values: Optional[list[float]] = None, unit: Optional[str] = None,
               y_title: Optional[str] = None, extra: Optional[list[tuple[str, list[Optional[float]]]]] = None) -> ChartSpec:
    """Столбцы по категориям; выделен лидер — по значению (у порядковых подписей он не обязательно первый)."""
    vals = values if values is not None else cv.values
    name = y_title or (cv.measure.name if cv.measure else "Число строк")
    series = [InlineSeries(name=name, values=list(vals), unit=unit)]
    for nm, vs in extra or []:
        series.append(InlineSeries(name=nm, values=list(vs), unit=unit))
    real = list(vals[:-1]) + [None] if cv.others else list(vals)
    return ChartSpec(type=kind, categories=list(cv.labels), series=series, unit=unit,
                     highlight_index=_argmax(real, cv.labels) if len(series) == 1 else None,
                     x_title=cv.dim, y_title=name, source=src)


def _spec_comparison(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Union[SlideBody, NotBuilt, None]:
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
        if cv.total is not None and cv.measure is not None and cv.measure.additive and not d.funnel \
                and len(rows) % TABLE_ROWS:
            # «Итого» — только если помещается на последнем слайде таблицы (≤ 10 строк), иначе итог — в подписи
            rows.append(["Итого", _cell(cv.total)] + [""] * (len(ms) - 1))
        bad = _pages_ok(rows, part)
        return bad if bad is not None else TableData(columns=cols, rows=_part(rows, part))
    if opt.kind in ("pie", "doughnut"):
        if cv.shares is None:
            return NotBuilt(reason="Значения не складываются в целое — круговая здесь неверна.")
        return _cats_spec(cv, opt.kind, src, values=[round(s, 1) for s in cv.shares], unit="%", y_title="Доля")
    if opt.kind in ("grouped_bar", "grouped_column", "stacked_bar", "stacked_column"):
        if d.parallel:
            return _parts_spec(d, opt.kind, src)
        same = [x for x in cv.extra_measures if not x.change][:1]  # взаимосвязь по строкам — обе метрики
        return _cats_spec(cv, opt.kind, src, unit=unit, extra=[(x.name, cv.extra[x.name]) for x in same])
    kind = opt.kind if opt.kind in ("bar", "column") else "bar"
    from verstka.data.facts import tail_apart

    if tail_apart(cv):
        # «Остальные N» больше лидера: не полоса той же шкалы — их сумма и доля в подписи (facts.tail_apart)
        cv = replace(cv, labels=list(cv.labels[:-1]), values=list(cv.values[:-1]),
                     extra={k: list(v[:-1]) for k, v in cv.extra.items()}, others=0)
    rt = d.row_target
    if rt is not None and rt[0] is cv.measure and rt[1].name in cv.extra and not cv.others:
        # своя цель у каждой строки («Цель SLA»): цель — рядом с фактом, вторым рядом, иначе «выше цели» не видно
        # на графике (жюри 20.10)
        spec = _cats_spec(cv, "grouped_bar" if kind == "bar" else "grouped_column", src, unit=unit,
                          extra=[(rt[1].name, cv.extra[rt[1].name])])
        miss = _worst_miss(d, cv, plan)
        if miss is not None and miss in cv.labels:
            spec.highlight_index = cv.labels.index(miss)  # самый далёкий от своей цели — акцент
        return spec
    spec = _cats_spec(cv, kind, src, unit=unit)
    focus = _headline_focus(plan) or _worst_miss(d, cv, plan)
    if focus is not None and focus in cv.labels and spec.highlight_index is not None:
        # заголовок называет того, кто растёт быстрее всех: акцент — у него (лидер по величине виден и так — он
        # самый длинный столбец), а не у другого столбца
        spec.highlight_index = cv.labels.index(focus)
    return spec


def _worst_miss(d: Data, cv: CatView, plan: DatasetPlan) -> Optional[str]:
    """Заголовок о промахах мимо цели строки («Ниже цели SLA — 2 из 7: CDN и Почта для бизнеса»): акцент — у
    самого далёкого от своей цели, а не у лидера."""
    f = next((x for x in plan.headline_facts if x.id == "miss_0"), None)
    if f is None or d.row_target is None or not re.match(r"^(?:Ниже|Выше) ", plan.headline or ""):
        return None
    nm = f.text.rsplit(" — ", 1)[0].strip()
    return nm if nm in plan.headline else None


def _headline_focus(plan: DatasetPlan) -> Optional[str]:
    """Категория, о которой заголовок говорит сверх лидера: «Москва даёт 41% выручки, Казань растёт быстрее всех» →
    «Казань» (по подтверждённому факту «growth_max», а не по разбору фразы)."""
    if "быстрее всех" not in (plan.headline or ""):
        return None
    f = next((x for x in plan.headline_facts if x.id == "growth_max"), None)
    if f is None:
        return None
    nm = f.text.rsplit(":", 1)[0].strip()
    return nm if nm and nm in plan.headline else None


def _parts_spec(d: Data, kind: str, src: str) -> Union[ChartSpec, NotBuilt]:
    """Части по категориям: ряд на каждую часть (короткие имена), категории — по сумме частей."""
    cv = d.cats
    g = d.parallel
    if cv is None or len(g) < 2:
        return NotBuilt(reason="Частей меньше двух.")
    names = d.series_names
    m = cv.measure
    unit = g[0].unit_text
    series = []
    for x in g:
        vals = cv.values if x is m else cv.extra.get(x.name, [])
        # пропуск — пустое место, а не ноль (месяцы, которых ещё не было)
        series.append(InlineSeries(name=names.get(x.name, x.name), values=list(vals), unit=unit))
    # ось значений — по величине («Приём», единицу «чел.» дописывает движок); группа частей из шапки («Форма
    # обучения») — заголовок легенды, а не оси
    title = _series_title(d)
    from verstka.data.units import period_tag

    tags = [period_tag(x.name) for x in g]
    if all(t is not None and t[2] for t in tags) and len({t[2].lower() for t in tags}) == 1:  # type: ignore[union-attr]
        # срезы одной величины («Учеников на 30.06 · на 30.09»): ось — сама величина, а не файл
        title = upper_first(tags[0][2])  # type: ignore[index]
    elif title == "Значение" or any(same_stem(a, b) for a in stems_of(title) for b in stems_of(cv.dim or "")):
        # «Сегменты.csv» с колонками-годами: «Сегменты» — это категории, а не величина на оси (жюри R25: ошибка
        # аудита «ось названа как категории») — ось называет единица
        title = unit or "Значение"
    return ChartSpec(type=kind, categories=list(cv.labels), series=series, unit=unit, x_title=cv.dim,
                     y_title=title, legend_title=d.group_name, source=src)


def _parts_doughnut(d: Data, src: str) -> Union[ChartSpec, NotBuilt]:
    g = d.parallel
    if len(g) < 2:
        return NotBuilt(reason="Частей меньше двух.")
    names = d.series_names
    tot = [float(sum(x.present)) for x in g]
    whole = sum(tot) or 1.0
    vals = [round(v / whole * 100, 1) for v in tot]
    lead = max(range(len(vals)), key=lambda k: (vals[k], -k))
    return ChartSpec(type="doughnut", categories=[names.get(x.name, x.name) for x in g],
                     series=[InlineSeries(name="Доля", values=vals, unit="%")], unit="%", highlight_index=lead,
                     y_title="Доля", source=src)


def _tree_table(d: Data, part: int) -> Union[TableData, NotBuilt]:
    """Таблица «родитель → строка → значение»: группы по сумме, строки внутри по значению, итог внизу."""
    m, child = d.main, d.label
    parent = d.parent_of(child) if child is not None else None
    if m is None or child is None or parent is None:
        return NotBuilt(reason="Иерархии нет.")
    groups: dict[str, list[int]] = {}
    for i in d.rows_idx:
        groups.setdefault(d.text(i, parent), []).append(i)
    tot = {g: sum(m.values[i] or 0.0 for i in idx) for g, idx in groups.items()}
    rows = []
    for g in sorted(groups, key=lambda x: (-tot[x], x)):
        for i in sorted(groups[g], key=lambda i: (-(m.values[i] or 0.0), i)):
            rows.append([g, d.text(i, child), _cell(m.values[i])])
    if len(rows) % TABLE_ROWS:  # «Итого» — на последнем слайде, если там есть место
        rows.append(["Итого", "", _cell(sum(tot.values()))])
    bad = _pages_ok(rows, part)
    if bad is not None:
        return bad
    return TableData(columns=[d.cols[parent].name, d.cols[child].name, _col_title(m.name, m.unit_text)],
                     rows=_part(rows, part), unit=m.unit_text)


def _xy_bins(d: Data, src: str) -> Union[ChartSpec, NotBuilt]:
    """Среднее y в трёх группах x (по терцилям, границы округлены): «до 8», «8–16», «от 16»."""
    xy = d.xy
    if xy is None or xy.n < 30:
        return NotBuilt(reason="Точек мало для групп.")
    xs, ys = np.array(xy.xs), np.array(xy.ys)
    a, b = (float(v) for v in np.percentile(xs, [100 / 3, 200 / 3]))
    a, b = round(a), round(b)
    if b <= a:
        return NotBuilt(reason="Значения почти не различаются — групп не получится.")
    masks = [xs < a, (xs >= a) & (xs < b), xs >= b]
    labels = [f"до {fmt_num(a)}", f"{fmt_num(a)}–{fmt_num(b)}", f"от {fmt_num(b)}"]
    vals = [round(float(ys[mk].mean()), 1) if mk.any() else None for mk in masks]
    return ChartSpec(type="column", categories=labels, series=[InlineSeries(name=xy.y.name, values=vals,
                                                                            unit=xy.y.unit_text)],
                     unit=xy.y.unit_text, x_title=_col_title(xy.x.name, xy.x.unit_text), y_title=xy.y.name, source=src)


def _spec_shares(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Union[SlideBody, NotBuilt, None]:
    if d.composition and d.parallel and d.cats is not None:
        if opt.kind in ("stacked_bar", "stacked_column", "grouped_bar", "grouped_column"):
            return _parts_spec(d, opt.kind, src)
        if opt.kind == "table":
            return _spec_comparison(d, opt, src, part, plan)
    got = d.shares
    if got is None:
        return NotBuilt(reason="Значения не складываются в целое.")
    cv, shares = got
    labels = list(cv.labels)
    if opt.kind in ("doughnut", "pie") and len(labels) > 6:
        top, rest, rest_label = _doughnut_split(cv.labels, shares)
        labels = [cv.labels[k] for k in top] + [rest_label]
        shares = [shares[k] for k in top] + [sum(shares[k] for k in rest)]
    vals = [round(x, 1) for x in shares]
    lead = _argmax(vals, labels)
    if opt.kind == "table":
        rows = [[a, fmt_num(b, 1)] for a, b in zip(labels, vals)]
        return _pages_ok(rows, part) or TableData(columns=[cv.dim, "Доля, %"], rows=_part(rows, part))
    if opt.kind in ("stacked_column", "stacked_bar"):
        return ChartSpec(type=opt.kind, categories=[plan.plain_headline or "Доли"],
                         series=[InlineSeries(name=a, values=[b], unit="%") for a, b in zip(labels, vals)], unit="%",
                         x_title=cv.dim, y_title="Доля", source=src)
    kind = opt.kind if opt.kind in ("doughnut", "pie", "column", "bar") else "doughnut"
    return ChartSpec(type=kind, categories=labels, series=[InlineSeries(name="Доля", values=vals, unit="%")], unit="%",
                     highlight_index=lead, x_title=cv.dim, y_title="Доля", source=src)


def _doughnut_split(labels: list[str], shares: list[float]) -> tuple[list[int], list[int], str]:
    """Кольцо больше 6 долей: пять крупнейших названных — отдельно, остальное одним сектором. «Прочие» в файле — не
    отдельный сектор рядом с «Остальными»: всё, что не вошло, — одни «Прочие» (бренды названы в подписи)."""
    from verstka.data.aggregate import is_other_label

    order = sorted(range(len(shares)), key=lambda k: (is_other_label(labels[k]), -shares[k], k))
    top = sorted(k for k in order[:5] if not is_other_label(labels[k]))
    rest = [k for k in range(len(shares)) if k not in top]
    other = next((labels[k] for k in rest if is_other_label(labels[k])), None)
    return top, rest, other or f"Остальные {len(rest)}"


def _spec_distribution(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    dv = d.dist
    if dv is None:
        return None
    m = dv.measure
    unit = m.unit_text
    ent = phrase(dv.entity) if dv.entity else None
    count_name = f"Число {ent.low.gen_pl}" if ent is not None and ent.sure else "Число значений"
    if d.freq_table is not None:
        count_name = d.freq_table[1].name  # частотная таблица: счёт — своя колонка («Число учеников»)
    if opt.kind == "kpi_cards":
        out = [NumberCallout(value=fmt_value(dv.median, unit), label="Медиана"),
               NumberCallout(value=fmt_value(dv.percentile(80), unit), label="80-й перцентиль"),
               NumberCallout(value=fmt_num(dv.n), label=count_name)]
        if dv.outliers:
            out.append(NumberCallout(value=fmt_num(len(dv.outliers)), label="Выбросы"))
        return out
    b = dv.bins
    if opt.kind == "table":
        rows = [[lab, fmt_num(c)] for lab, c in zip(b.labels, b.counts)]
        return _pages_ok(rows, part) or TableData(columns=[_col_title(m.name, m.unit), count_name], rows=_part(rows, part))
    return ChartSpec(type="histogram", categories=list(b.labels),
                     series=[InlineSeries(name=count_name, values=[float(c) for c in b.counts])], unit=None,
                     x_title=_col_title(m.name, m.unit), y_title=count_name, source=src)


def _spec_reference(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Union[SlideBody, NotBuilt]:
    rv = d.ref
    if opt.kind == "bar":
        if rv.measure is None:
            return _groups_spec(d, src)
        m = rv.measure
        # одно упорядочение: подписи и значения — из одних и тех же строк
        k = min(rv.top_n, len(rv.labels))
        labs = rv.labels[:k]
        vals = [float(v) if v is not None else None for v in rv.values[:k]]
        return ChartSpec(type="bar", categories=labs, series=[InlineSeries(name=m.name, values=vals, unit=m.unit_text)],
                         unit=m.unit_text, highlight_index=0 if vals and vals[0] is not None else None,
                         x_title=rv.label or "Строка", y_title=m.name, source=src)
    if opt.kind == "kpi_cards":
        return _summary_cards(d)
    mode = _table_mode(opt) if opt.kind == "table" else "top"
    if mode == "top":
        # на слайде — ровно 10 строк данных (правило ≤ 10 строк); остальные — в подписи, а не 11-й строкой
        return TableData(columns=list(rv.columns), rows=list(rv.rows)[:TABLE_ROWS],
                         unit=rv.measure.unit_text if rv.measure else None)
    if mode == "head":
        return TableData(columns=list(rv.full_columns), rows=rv.all_rows[:TABLE_ROWS])
    bad = _pages_ok(rv.all_rows, part)
    return bad if bad is not None else TableData(columns=list(rv.full_columns), rows=_part(rv.all_rows, part))


def _kpi_label(it: KpiItem, prev: Optional[str]) -> str:
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
                     unit=unit, x_title="Показатель", y_title=kv.period or "Значение", source=src)


def _spec_relationship(d: Data, opt: VizOption, src: str, part: int, plan: DatasetPlan) -> Optional[SlideBody]:
    xy = d.xy
    if xy is None:
        return None
    if opt.kind == "scatter":
        if xy.group and xy.groups:
            # точки — по группе (≤ 5 значений): цвет показывает, у кого связь сильнее
            series = []
            for g in sorted(set(xy.groups), key=lambda g: (-xy.groups.count(g), g)):
                idx = [k for k, gg in enumerate(xy.groups) if gg == g]
                series.append(XYSeries(name=g, x=[xy.xs[k] for k in idx], y=[xy.ys[k] for k in idx]))
        else:
            series = [XYSeries(name=xy.y.name, x=list(xy.xs), y=list(xy.ys))]
        return ChartSpec(type="scatter", xy=series, x_title=_col_title(xy.x.name, xy.x.unit_text), y_title=xy.y.name,
                         unit=xy.y.unit_text, source=src)
    if opt.kind == "table":
        rows = [[lab or str(k + 1), _cell(a), _cell(b)] for k, (lab, a, b) in enumerate(zip(xy.labels, xy.xs, xy.ys))]
        return _pages_ok(rows, part) or TableData(columns=[xy.label_name or "№", _col_title(xy.x.name, xy.x.unit_text),
                                                           _col_title(xy.y.name, xy.y.unit_text)], rows=_part(rows, part))
    cv = d.cat_view(xy.y, rank=True)
    if cv is None:
        return None
    return _cats_spec(cv, "grouped_bar", src, extra=[(xy.x.name, cv.extra.get(xy.x.name, []))])


# ── «Почему так» ──────────────────────────────────────────────────────────────────────────────────────────────────────
_CONTEXT_MAX = 600
_FOOTNOTE = re.compile(r"^(?:источник|примечани|сноска|\*|составлено|подготовлено|данные\s+(?:на|по\s+состоянию))", re.I)
_EXPLAINS = re.compile(r"не\s+проводил|не\s+измеря|нет\s+данных|без\s+данных|не\s+собира|пропуск|не\s+учитыв|"
                       r"переход|изменил[аи]?сь\s+методик|по\s+новой\s+методик|сравнени[ея]|потому\s+что|из-за", re.I)


_PERIOD_WORD = re.compile(r"^(?:месяц|квартал|год|недел|ден|дн[яеи]|час|период|дат|значени|данн|итог|показател|"
                          r"изменени|доля|дол|(?:i{1,3}|iv|v)$|по$|за$|в$)", re.I)


def _subject_stems(table: Optional[Table], plan: Optional[DatasetPlan]) -> list[str]:
    """Основы предмета датасета: главное слово названия файла и величин («NPS», «выручк»), без слов периода."""
    if plan is None:
        return []
    from verstka.data.words import head_word

    names = [file_title(plan.profile.file, plan.profile.sheet)] + list(plan.profile.metrics)
    out: list[str] = []
    for n in names:
        h = head_word(split_unit(n)[0] or n) or ""
        for w in [h] + ([n] if re.fullmatch(r"[A-Za-z]{2,6}", n.strip()) else []):
            w = w.strip().lower()
            if len(w) >= 2 and not _PERIOD_WORD.match(w):
                out.append(w if re.fullmatch(r"[a-z]{2,6}", w) else (stems_of(w) or [w])[0])
    return list(dict.fromkeys(out))


def _cross_context(table: Optional[Table], plan: Optional[DatasetPlan], others: Sequence[Table]) -> list[str]:
    """Предложения из текста других файлов, которые называют предмет этого датасета («Опрос NPS во II квартале не
    проводился» — для «NPS по кварталам.csv»), с названием файла; объяснения пропусков — первыми."""
    stems = _subject_stems(table, plan)
    if not stems:
        return []
    out: list[tuple[int, int, str]] = []
    for k, o in enumerate(others):
        if o is table or not (getattr(o, "notes", "") or "").strip() or getattr(o, "file", None) == getattr(table, "file",
                                                                                                          None):
            continue
        text = " ".join(o.notes.split())
        for i, sent in enumerate(re.split(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«])", text)):
            low = sent.lower()
            words = re.findall(r"[а-яёa-z]{2,}", low)
            hit = any((re.fullmatch(r"[a-z]{2,6}", st) and re.search(rf"(?<![a-z]){st}(?![a-z])", low))
                      or (not re.fullmatch(r"[a-z]{2,6}", st) and any(w.startswith(st) for w in words)) for st in stems)
            if hit and not _FOOTNOTE.match(sent) and not sent.startswith("|"):
                out.append((0 if _EXPLAINS.search(sent) else 1, k * 1000 + i, f"«{o.file}»: {sent}"))
    return [x for _, _, x in sorted(out)]


def file_context(table: Optional[Table], plan: Optional[DatasetPlan] = None,
                 others: Sequence[Table] = ()) -> Optional[str]:
    """Что файл говорит о своих данных: абзацы текста вокруг таблицы (`Table.notes`) без строки-заголовка и сносок
    («Источник:», «Подготовлено…»), до ~600 знаков. Первыми — объяснения пропусков и сравнений («Опрос NPS во II
    квартале не проводился…»), потом абзацы о величинах таблицы; порядок — как в файле. `others` — другие файлы
    колоды: их предложения о предмете этого датасета идут следом, с названием файла («Итоги квартала.txt»: …)."""
    own = _own_context(table, plan)
    cross = _cross_context(table, plan, others) if others else []
    if not cross:
        return own
    parts = [own] if own else []
    size = len(own or "")
    for c in cross:
        if size + len(c) + 1 > _CONTEXT_MAX:
            continue
        parts.append(c)
        size += len(c) + 1
    return " ".join(parts) or None


def _own_context(table: Optional[Table], plan: Optional[DatasetPlan] = None) -> Optional[str]:
    notes = (getattr(table, "notes", "") or "").strip()
    if not notes:
        return None
    paras = [" ".join(x.split()) for x in re.split(r"\n\s*\n", notes) if x.strip()]
    if paras and "\n" not in notes.split("\n\n", 1)[0].strip() and not re.search(r"[.!?…]$", paras[0]):
        paras = paras[1:]  # строка-заголовок («Итоги III квартала 2026 года — VK Cloud»)
    paras = [x for x in paras if not _FOOTNOTE.match(x) and not x.startswith("|")]
    if not paras:
        return None
    words = []
    if plan is not None:
        words = [c.name.lower() for c in plan.profile.columns] + [c.lower() for c in getattr(table, "columns", [])]
        for r in getattr(table, "rows", [])[:30]:
            if r and isinstance(r[0], str):
                words.append(r[0].lower())
    words = [w for w in words if len(w) >= 3]

    def score(x: str) -> int:
        low = x.lower()
        return (2 if _EXPLAINS.search(x) else 0) + (1 if any(w in low for w in words) else 0)

    order = sorted(range(len(paras)), key=lambda k: (-score(paras[k]), k))
    keep: list[int] = []
    size = 0
    for k in order:
        if size + len(paras[k]) + 1 > _CONTEXT_MAX:
            continue
        keep.append(k)
        size += len(paras[k]) + 1
    if not keep:
        first = paras[order[0]]
        cut = first[:_CONTEXT_MAX]
        dot = cut.rfind(". ")
        return (cut[: dot + 1] if dot > 100 else cut.rstrip() + "…") or None
    return " ".join(paras[k] for k in sorted(keep))


def slide_data_of(plan: DatasetPlan, part: int = 1, table: Optional[Table] = None) -> SlideData:
    """Данные слайда для «Почему так» (`part` — номер слайда датасета, с 1, как у `chart_spec_of`): профиль кратко,
    задача, варианты, факты заголовка. У справочника и карточек выбросы не показываются: крупнейшие клиенты в списке —
    это данные, а не проблема."""
    p = plan.profile
    line = " · ".join([
        _KIND_LABEL.get(p.kind, p.kind.upper()),
        f"{count_words(p.rows, 'строка', 'строки', 'строк')} × {count_words(p.cols, 'колонка', 'колонки', 'колонок')}",
        NATURE_LABELS[p.nature].lower(),
    ])
    opt = plan.chosen_option
    outliers = [] if plan.task.task in ("reference", "kpi") else list(p.outliers)
    total = max(1, plan.slides)
    return SlideData(
        dataset_id=p.table_id, file=p.file, profile_line=line, nature=p.nature, columns=list(p.columns),
        time_axis=p.time_axis, metrics=list(p.metrics), dimensions=list(p.dimensions), missing_total=p.missing_total,
        outliers=outliers, task=plan.task, options=list(plan.options), chosen=plan.chosen,
        headline_facts=list(plan.headline_facts), plain_headline=plan.plain_headline,
        aggregation=opt.aggregation if opt else None, part=(min(max(1, part), total), total),
        context=file_context(table, plan),
    )
