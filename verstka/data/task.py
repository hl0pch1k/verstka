"""Аналитическая задача датасета (описание решения §2.3): динамика, сравнение категорий, структура долей,
распределение, взаимосвязь, справочные значения, ключевые значения.

Каждая задача получает балл по свойствам профиля (ось времени и метрика → динамика; категории и метрика → сравнение;
доли с суммой ≈ 100 → структура; одна числовая колонка ≥ 30 значений → распределение; две метрики без времени и ≥ 8
строк → взаимосвязь; больше 30 строк и ≥ 4 колонок или id-колонка → справочник; до 6 показателей с изменениями или в разных единицах →
ключевые значения). Задача с нулевым баллом неосуществима: цель из текста её не поднимет. Цель («покажи рост выручки»),
если она о датасете и её задача осуществима, прибавляет +0,5 — так «покажи структуру» превращает сравнение регионов в
структуру долей. Причины — короткие русские фразы для «Почему так»."""

from __future__ import annotations

import re
from typing import Optional

from verstka.data.aggregate import Data
from verstka.data.goals import Goal
from verstka.data.words import (
    PERIOD_WORDS, count_words, file_title, lower_first, metric_phrase, number_word, parts_words, phrase, plural,
    same_stem, stems_of, upper_first,
)
from verstka.schemas.data import TASK_TITLES, TaskDecision, TaskKind

__all__ = ["task_scores", "decide_task", "covers", "ask_feasible", "GOAL_BONUS", "FEASIBLE"]

GOAL_BONUS = 0.5
FEASIBLE = 0.25  # ниже — задача для этих данных не годится (цель её не поднимет)
_ORDER: list[TaskKind] = ["kpi", "dynamics", "shares", "distribution", "comparison", "relationship", "reference"]


def task_scores(d: Data) -> dict[TaskKind, float]:
    """Баллы задач по свойствам данных, 0…1 (0 — неосуществима)."""
    p = d.profile
    n = d.n
    ms = d.measures
    has_time = p.time_axis is not None and d.time_col is not None
    cats = d.cat_dim()
    cat_count = d.cols[cats].distinct if cats is not None else 0
    s: dict[TaskKind, float] = {k: 0.0 for k in _ORDER}
    if (not p.typable or d.not_numbers) and not ms:
        # нетипизируемое или номера вместо величин (расписание): осмысленная таблица — справочник, иначе ничего
        s["reference"] = 0.6 if n >= 2 and len(d.cols) >= 2 else 0.0
        return s

    # ключевые значения
    if d.kpi_like:
        s["kpi"] = 0.95
    elif n == 1 and ms:
        s["kpi"] = 0.9

    # динамика
    if has_time:
        pts = d.time.points if d.time is not None else 0
        if ms:
            s["dynamics"] = 0.9 if pts >= 4 else 0.5 if pts >= 2 else 0.0
        elif p.time_axis is not None and d.time is not None and pts >= 2 and d.label is None:
            # одни даты с повторами — число событий по периодам; у каждой строки своя подпись (вехи, события) — это
            # перечень, а не ряд: его показывают таблицей
            s["dynamics"] = 0.6
        if d.kpi_like:
            s["dynamics"] = min(s["dynamics"], 0.3)
    elif d.columns_time is not None and ms:
        s["dynamics"] = 0.45  # колонки-периоды («I кв. · II кв. · …»): ось времени, если о ней просит цель

    m = d.main
    scores = bool(d.part_group) and all(re.search(r"балл|очк|оценк", x.name, re.I) for x in d.part_group)
    # структура долей
    if d.funnel:
        pass  # этапы воронки — не части одного целого
    elif d.parts_measure is not None:
        s["shares"] = 0.92
    elif d.composition and cats is not None and not has_time:
        # несколько частей одного целого по категориям (формы обучения по направлениям); доли у всех строк одни и
        # те же (НДС 18% цены у каждого тарифа) — структура не главное, но осуществима
        # баллы жюри и зрителей — части итога команды, но их сумма по всем командам («всего 508 баллов») смысла не
        # имеет: главное — кто впереди по итогу
        s["shares"] = 0.5 if d.composition_constant or scores else 0.88
    elif p.parts_of_whole and m is not None and m.additive and m.nonneg and cats is not None and cat_count <= 12:
        s["shares"] = 0.9  # части целого: строка «Итого» равна сумме
    elif m is not None and m.additive and m.nonneg and cats is not None and 2 <= cat_count <= 60 and not has_time \
            and not d.mixed_units:
        s["shares"] = 0.35 if cat_count <= 12 else 0.3  # больше 12 частей — крупнейшие и «Остальные»

    # сравнение категорий
    if cats is not None and not d.mixed_units:
        if ms or any(d.cols[j].distinct < n for j in d.dims):
            base = 0.75 if cat_count <= 12 else 0.6
            if n > 30 and len(d.cols) >= 4 and d.label is not None:
                base = 0.45  # список строк с подписью — скорее справочник
            elif not ms and d.label is not None:
                base = 0.3  # список без чисел (вехи, контакты): счёт строк по группам — запасной путь, первым — таблица
            if has_time:
                base = min(base, 0.4)
            if (d.parts_measure is not None or p.parts_of_whole) and not scores:
                base = min(base, 0.55)
            if d.kpi_like:
                base = min(base, 0.4)
            s["comparison"] = base
    elif not ms and d.dims and any(d.cols[j].distinct < n for j in d.dims):
        s["comparison"] = 0.6 if d.label is None else 0.55  # список с подписью строк — скорее справочник

    # план и факт по категориям — исполнение, а не доли плана; срезы одной величины («на 30.06 · на 30.09», «Q2 · Q3») —
    # изменение по категориям, а не структура одного среза
    if cats is not None and not d.mixed_units and ms:
        from verstka.data.units import period_siblings

        if d.plan_fact is not None:
            s["comparison"] = max(s["comparison"], 0.93)
            s["shares"] = min(s["shares"], 0.5)
        elif d.total_metric is None and period_siblings([x.name for x in ms if not x.change and not x.mixed]):
            s["comparison"] = max(s["comparison"], 0.9 if not has_time else s["comparison"])
            s["shares"] = min(s["shares"], 0.5)

    # распределение
    if d.freq_table is not None:
        s["distribution"] = 0.88  # готовая частотная таблица («Оценка | Число учеников») — это и есть распределение
    elif m is not None and len(m.present) >= 30 and not has_time:
        only = len([x for x in ms if not x.mixed]) == 1 and not d.dims and d.label is None
        s["distribution"] = 0.88 if only else 0.35

    # взаимосвязь
    strong = False
    # колонки-«близнецы» («Показатель А · Показатель Б») мешают связи, только если есть категории или время — без них
    # пара величин и есть вопрос о связи
    if d.xy is not None and not has_time and d.xy.n >= 8 and not (d.parallel and cats is not None):
        r = min(1.0, abs(d.xy.r))
        strong = r >= 0.5
        if d.label is not None and n <= 60:
            # именованные строки (регионы, менеджеры, статьи бюджета): их сравнивают; связь — только по цели
            s["relationship"] = round(min(0.5, 0.4 + 0.3 * r), 3)
        else:
            # много безымянных наблюдений (коды, опыты): сильная связь — главное в данных
            s["relationship"] = round(0.4 + (0.5 if strong else 0.3) * r, 3)
    elif d.xy is not None and has_time and d.xy.n >= 8 and not d.parallel_time_only:
        # по дням две величины (посетители и выручка): ряд по времени главнее, но связь осуществима — цель её поднимет;
        # сильная связь на 30+ парах — вторым вариантом и без цели
        r = min(1.0, abs(d.xy.r))
        s["relationship"] = 0.5 if d.xy.n >= 30 and r >= 0.7 else FEASIBLE

    # справочник
    if n > 30 and len(d.cols) >= 4:
        # строки с кодом вместо имени и сильная связь двух величин — это взаимосвязь, а не список
        s["reference"] = 0.6 if strong and d.label is None else 0.8
    elif d.id_col is not None and n > 1:
        s["reference"] = 0.7  # §2.3: id-колонка — справочник (список строк с кодами)
    elif d.label is not None and n > 12:
        s["reference"] = 0.65 if not ms else 0.5
    elif d.label is not None and not ms and n > 1:
        s["reference"] = 0.6  # у каждой строки своя подпись и чисел нет — перечень (вехи, контакты): таблица
    else:
        s["reference"] = 0.15
    return {k: round(v, 3) for k, v in s.items()}


def _best(scores: dict[TaskKind, float], prefer: Optional[TaskKind] = None) -> TaskKind:
    """Лучшая задача; при равенстве — задача цели («сравни склады по доле опозданий» при равных баллах — сравнение)."""
    return max(_ORDER, key=lambda k: (round(scores[k], 6), k == prefer, -_ORDER.index(k)))


def covers(g: Goal, d: Data) -> bool:
    """Каждое слово предмета цели есть в данных: в названии файла, колонках или значениях подписей."""
    if not g.subject:
        return True
    words = stems_of(" ".join([file_title(d.profile.file, d.profile.sheet)] + [c.name for c in d.cols]))
    vals: list[str] = []
    for j in d.dims + ([d.label] if d.label is not None else []):
        for i in d.rows_idx[:300]:
            vals.append(d.text(i, j))
    words += stems_of(" ".join(vals))
    return all(any(same_stem(s_, w) for w in words) for s_ in g.subject)


def _infeasible_reason(task: TaskKind, d: Data) -> str:
    return {
        "dynamics": "в данных нет оси времени",
        "comparison": "нет категорий, которые можно сравнить" if not d.mixed_units else "у чисел разные единицы",
        "shares": "значения не складываются в целое (доли не дают 100%, есть отрицательные или это не сумма)",
        "distribution": "нужна числовая колонка хотя бы из 30 значений",
        "relationship": "нужны две числовые колонки без оси времени и хотя бы 8 строк",
        "reference": "таблица слишком мала для справочника",
        "kpi": "показателей больше шести или у них нет подписи",
    }[task]


def _why(task: TaskKind, d: Data) -> str:
    """Главная причина — одной фразой, как в «Почему так»."""
    m = d.main
    mp = metric_phrase(m.name, m.type) if m is not None else None
    mlow = lower_first(mp.nom if mp is not None else m.name) if m is not None else "значения"
    if task == "dynamics" and d.time is not None:
        tv = d.time
        if tv.from_columns:  # колонки-периоды: ряд — по всем строкам, назван по датасету
            mp = metric_phrase(tv.measure.name, tv.measure.type)
            mlow = lower_first(mp.nom if mp is not None else tv.measure.name)
        pw = PERIOD_WORDS.get(tv.freq, PERIOD_WORDS["irregular"])
        k = len(tv.series)
        metrics = "одна главная метрика" if k <= 1 or tv.dim else f"{count_words(k, 'ряд', 'ряда', 'рядов')}"
        miss = tv.missing
        if d.forecasts or d.forecast_rows:
            # после последнего факта — прогноз, а не пустые периоды
            vals_ = tv.main.values if not tv.dim else [1.0 if any(s_.values[i] is not None for s_ in tv.series) else None
                                                        for i in range(tv.points)]
            last_ = max((tv.periods[i] for i, v in enumerate(vals_) if v is not None), default=None)
            miss = [p_ for p_ in miss if last_ is None or p_ < last_]
        if miss:
            gap = len(miss)
            gp = (f"{number_word(gap, pw[3])} {plural(gap, 'пустой', 'пустых', 'пустых')} "
                  f"{plural(gap, pw[0], pw[1], pw[2])}") if gap <= 4 else count_words(gap, "пустой период",
                                                                                      "пустых периода",
                                                                                      "пустых периодов")
            return f"Ось времени, {metrics} и {gp} — их нельзя показать нулём или падением."
        if k >= 2 and not tv.dim:  # несколько рядов: «как средние менялись» про ряд «Средние (P3)» — не то
            return f"Есть ось времени ({count_words(tv.points, pw[0], pw[1], pw[2])}) и {metrics} — важно, как они " \
                   f"менялись {pw[4]}."
        gend = mp.gender if mp is not None else "f"
        changed = {"m": "менялся", "f": "менялась", "n": "менялось", "pl": "менялись"}[gend]
        return (f"Есть ось времени ({count_words(tv.points, pw[0], pw[1], pw[2])}) и {metrics} — важно, как {mlow} "
                f"{changed} {pw[4]}.")
    if task == "comparison" and d.cats is not None:
        cv = d.cats
        dp = phrase(cv.dim)
        what = count_words(cv.distinct, dp.low.nom, dp.low.gen, dp.low.gen_pl) if dp is not None and dp.sure else \
            count_words(cv.distinct, "категория", "категории", "категорий")
        grow = any(x.change and (x.type == "percent" or (x.unit or "") in ("%", "п.п.")) for x in cv.extra_measures)
        tail = "важно, кто больше и кто растёт быстрее" if grow else "важно, кто больше и насколько"
        metric = "одна главная метрика" if m is not None else "число строк в каждой"
        s = f"{upper_first(what)} и {metric} — {tail}."
        if cv.others:
            s += f" Крупнейшие {cv.n - 1} — отдельно, остальные {cv.others} — одной строкой."
        return s
    if task == "shares" and d.composition and d.cats is not None and len(d.parallel) >= 2:
        cv = d.cats
        dp = phrase(cv.dim)
        what = count_words(cv.n, dp.low.nom, dp.low.gen, dp.low.gen_pl) if dp is not None and dp.sure else \
            count_words(cv.n, "категория", "категории", "категорий")
        parts = [d.series_names.get(x.name, x.name) for x in d.parallel]
        return (f"{upper_first(what)} и {parts_words(len(parts), d.group_name)} "
                f"({', '.join(parts)}) — важно, из чего складывается каждое и целое.")
    if task == "shares":
        cv = d.cat_view(d.parts_measure) if d.parts_measure is not None else d.cats
        if cv is not None:
            dp = phrase(cv.dim)
            each = "каждая часть"
            if dp is not None and dp.sure and dp.gender != "pl":
                each = {"m": "каждый", "f": "каждая", "n": "каждое"}[dp.gender] + " " + dp.low.nom
            if d.parts_measure is not None:
                return (f"{upper_first(count_words(cv.n, 'доля', 'доли', 'долей'))} в сумме дают 100% — важно, какую "
                        f"часть целого даёт {each}.")
            return f"{upper_first(mlow)} складывается из {count_words(cv.n, 'части', 'частей', 'частей')} — важно, какую часть целого даёт {each}."
    if task == "distribution" and d.dist is not None:
        typical = "типичное время" if m is not None and m.time_unit else "типичное значение"
        return (f"Одна числовая колонка из {count_words(d.dist.n, 'значения', 'значений', 'значений')} — важны форма "
                f"распределения и {typical}.")
    if task == "reference":
        ent = phrase(d.entity) if d.entity else None
        who = f"конкретные {ent.low.nom_pl}" if ent is not None and ent.sure else "конкретные строки"
        if d.n > 10 and m is not None and m.additive:
            rest = d.n - 10
            return (f"Нужны {who} и их цифры, а не форма. {count_words(d.n, 'строка', 'строки', 'строк').capitalize()} "
                    f"целиком не поместятся — агрегирую: топ-10 и итог «остальные {rest}».")
        if d.n > 10:
            return f"Нужны {who} и их значения, а не форма; {count_words(d.n, 'строка', 'строки', 'строк')} — по 10 на слайд."
        return f"Нужны {who} и их значения, а не форма."
    if task == "kpi" and d.kpi is not None:
        kv = d.kpi
        k = len(kv.items)
        nums = count_words(k, "итоговое число", "итоговых числа", "итоговых чисел")
        if kv.with_change:
            since = f" к {kv.prev_period}" if kv.prev_period else ""
            return f"{upper_first(nums)} с изменением{since} — важны сами значения и их рост."
        if kv.mixed_units:
            return f"{upper_first(nums)} в разных единицах — важны сами значения, сравнивать их столбцами нельзя."
        return f"{upper_first(nums)} — важны сами значения."
    if task == "relationship" and d.xy is not None:
        xy = d.xy
        xp, yp = metric_phrase(xy.x.name, xy.x.type), metric_phrase(xy.y.name, xy.y.type)
        xn = lower_first(xp.nom if xp is not None else xy.x.name)
        yn = lower_first(yp.nom if yp is not None else xy.y.name)
        return (f"Две метрики без оси времени, {count_words(xy.n, 'точка', 'точки', 'точек')} — важно, связаны ли "
                f"{xn} и {yn}.")
    return f"Задача — {TASK_TITLES[task].lower()}."


_FORM_ASKED = re.compile(r"(?i)график|столб|диаграм|кругов|кольцев|полос|гистограм")


def _directory_answers(d: Data, g: Goal, data_task: TaskKind) -> bool:
    """Цель сравнения над справочником — «кто главные клиенты», «крупнейшие поставщики»: список длиннее графика
    (больше 30 строк, своя подпись у каждой), цель не называет ни разреза, ни строк, ни формы. Ответ на неё — таблица
    крупнейших строк справочника, а не полосы «топ-11 и Остальные 229»: один набор данных — один вид в любом режиме."""
    if data_task != "reference" or g.task != "comparison" or d.n <= 30 or d.entity is None:
        return False
    if g.categories or (g.ask not in (None, "max", "total")) or _FORM_ASKED.search(g.phrase or ""):
        return False
    if g.dimension:
        return g.dimension == d.entity
    # без разреза — только когда цель называет сами строки справочника («кто главные клиенты» — «Клиент»)
    from verstka.data.words import same_stem, stems_of

    ent = stems_of(d.entity)
    return bool(ent) and any(same_stem(a, b) for a in stems_of(g.phrase or "") for b in ent)


# вопросы, у которых свой ответ (темп, худший, итог, порог, план): они точнее общей цели той же задачи
_SPECIFIC_ASKS = ("fastest", "fastest_down", "worst", "min", "meet", "miss", "total", "mean", "margin")


def _goal_weight(g: Goal, d: Data) -> float:
    """Насколько цель говорит именно об этом датасете и спрашивает своё: «клиенты по отраслям — госсектор выстрелил»
    (предмет — файл и колонки, вопрос — темп) весомее общей «сравни Q3 с Q2» той же задачи."""
    from verstka.data.goals import goal_ask, goal_match

    ask = g.ask if g.given else goal_ask(g.phrase)
    return (1.0 if ask in _SPECIFIC_ASKS or (ask or "").startswith(("above:", "below:")) else 0.0) + \
        min(goal_match(g, d.profile), 2.0)


def ask_feasible(g: Goal, d: Data) -> bool:
    """Вопрос цели осуществим на этих данных: темп («кто растёт быстрее всех») — только там, где есть ось времени или
    колонки-срезы одной величины («на 30.06 · на 30.09», «Q2 · Q3»); иначе цель — не об этом датасете."""
    from verstka.data.goals import goal_ask
    from verstka.data.units import period_siblings, _period_name

    ask = g.ask if g.given else goal_ask(g.phrase)
    if ask not in ("fastest", "fastest_down"):
        return True
    if d.profile.time_axis is not None:
        return True
    names = [m.name for m in d.measures]
    return bool(period_siblings(names)) or sum(1 for n in names if _period_name(n)) >= 2


def decide_task(d: Data, goals: Optional[list[Goal]] = None) -> TaskDecision:
    """Задача: лучший балл по данным, цель из текста (о датасете, осуществимая) — +0,5."""
    base = task_scores(d)
    scores = dict(base)
    goals = goals or []
    used: Optional[Goal] = None
    notes: list[str] = []
    feasible_phrases = {g.phrase for g in goals if not g.unmet and not g.free and base.get(g.task, 0.0) >= FEASIBLE}
    for g in goals:
        if g.free:
            continue
        if g.unmet:
            notes.append(f"Цель «{g.phrase}» здесь не подходит: {g.unmet}.")
        elif base.get(g.task, 0.0) >= FEASIBLE:
            if used is None or (base[g.task] > base[used.task] and not (g.given and used.given)) or (
                    not g.given and not used.given and base[g.task] == base[used.task]
                    and _goal_weight(g, d) > _goal_weight(used, d)):
                # цели, понятые моделью, — по порядку брифа (порог — первым): главная — первая осуществимая, а не та,
                # чья задача сильнее по данным
                used = g
        elif g.phrase not in feasible_phrases:
            # одна фраза — несколько прочтений («какой регион растёт быстрее»: динамика и сравнение): пометка — только
            # если не подошло ни одно
            notes.append(f"Цель «{g.phrase}» здесь не подходит: {_infeasible_reason(g.task, d)}.")
    data_task = _best(base)
    directory = used is not None and _directory_answers(d, used, data_task)
    if used is not None and not directory:
        scores[used.task] = round(scores[used.task] + GOAL_BONUS, 3)
    task = _best(scores, used.task if used is not None else None)
    reasons = [_why(task, d)]
    goal_phrase = None
    if directory:
        # «кто главные клиенты» над списком из 240 клиентов: ответ — таблица крупнейших с их колонками, тот же вид,
        # что без модели и на любом шаблоне (жюри 20.10: с моделью — полосы с «Остальные 229», без — таблица)
        goal_phrase = used.phrase
        reasons.append(f"Цель «{used.phrase}» — ответ таблицей крупнейших строк: у каждой свои колонки, остальные — "
                       "итогом в подписи.")
    elif used is not None and used.task == task:
        goal_phrase = used.phrase
        if data_task != task:
            reasons.append(f"Цель «{used.phrase}» подняла эту задачу: без неё по данным задача была бы "
                           f"«{TASK_TITLES[data_task].lower()}».")
        elif covers(used, d):
            reasons.append(f"Цель «{used.phrase}» совпала с тем, что видно по данным.")
        else:
            reasons.append(f"Цель «{used.phrase}» ведёт к той же задаче.")
    elif used is not None:
        # цель не потерялась: её задача слабее того, что видно по данным, — сказано
        reasons.append(f"Цель «{used.phrase}» ведёт к задаче «{TASK_TITLES[used.task].lower()}», но по данным сильнее "
                       f"«{TASK_TITLES[task].lower()}».")
    for g in goals:
        if g is not used and not g.unmet and not g.free and base.get(g.task, 0.0) >= FEASIBLE \
                and (used is None or g.phrase != used.phrase):
            notes.append(f"Цель «{g.phrase}» здесь не главная: слайд один, и он отвечает на «{used.phrase}».")
        if g.free:
            # вопрос понят как вопрос, но не как задача: ответ — главный вывод по данным, и это сказано
            notes.append(f"Вопрос «{g.phrase}» не распознан как задача — показан главный вывод по данным "
                         f"({TASK_TITLES[task].lower()}).")
    reasons.extend(notes)
    return TaskDecision(task=task, reasons=reasons, goal=goal_phrase, scores=scores)
