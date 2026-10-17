"""Заголовок-вывод (описание решения §2.6): шаблоны по задаче и проверка чисел.

Заголовок — вывод с настоящим числом из данных («Выручка выросла на 23% к сентябрю», «Москва даёт 41% выручки,
Казань растёт быстрее всех», «80% обращений получают ответ за 2 часа», «Топ-10 клиентов дают 38% выручки»), а не тема
(«Выручка по месяцам»). Числа берутся только из фактов (`verstka/data/facts.py`), слова — из `verstka/data/words.py`.
`headline_ok` проверяет, что каждое число заголовка есть среди фактов; числа внутри известных подписей («Филиал 1»,
«25–34») можно исключить параметром `labels`. Модель (навык `data_storyteller`) может переформулировать заголовок, но
проверка её текста строгая: если в нём число не из фактов, остаётся детерминированный."""

from __future__ import annotations

import re
from typing import Optional, Sequence

from verstka.data.facts import FactSet
from verstka.data.words import (
    PERIOD_WORDS, WORD_NUMS, Gender, Phrase, count_words, fmt_num, fmt_pct, fmt_pct_any, fmt_signed, fmt_value,
    fraction_words, is_event_name, is_period_name, is_plural_value, lower_first, number_word, phrase, plural, round_pct, times_word,
    upper_first, verb,
)
from verstka.schemas.data import HeadlineFact, TaskKind

__all__ = ["numbers_in", "headline_ok", "compose"]


# ── проверка чисел заголовка ──────────────────────────────────────────────────────────────────────────────────────────
_NUM_IN_TEXT = re.compile(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[   ]\d{3})+(?:,\d+)?(?![\d])"
                          r"|(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])")
_WORD_RE = re.compile(r"[а-яё]+", re.I)


def _without(text: str, labels: Sequence[str]) -> str:
    """Текст без известных подписей («Филиал 1», «25–34»): цифры внутри названий — не числа заголовка."""
    for lab in sorted({x for x in labels if x}, key=len, reverse=True):
        # подпись — целым словом, не кусок десятичной дроби («67» не вырезается из «0,67»)
        text = re.sub(r"(?<![\w,.])" + re.escape(lab) + r"(?![\w]|[,.]\d)", " ", text)
    return text


def numbers_in(text: str, labels: Sequence[str] = ()) -> list[float]:
    """Числа в тексте: «1 433», «4,2», «+23%», «топ-10» (10), «два квартала» (2). Римские («III кв.») — не числа.
    `labels` — подписи категорий из данных: их цифры («Филиал 1», «18–24») не считаются."""
    out: list[float] = []
    text = _without(text or "", labels)
    text = re.sub(r"\b(?:две|три)\s+(?:трети|четверти)\b", " ", text, flags=re.I)  # доли словами — не числа
    for m in _NUM_IN_TEXT.finditer(text):
        tok = m.group(0)
        tok = re.sub(r"[   ]", "", tok).replace(",", ".").lstrip("+−–-")
        try:
            out.append(abs(float(tok)))
        except ValueError:
            continue
    for w in _WORD_RE.findall(text):
        n = WORD_NUMS.get(w.lower())
        if n is not None:
            out.append(float(n))
    return out


def _matches(n: float, v: float) -> bool:
    v = abs(v)
    if abs(n - v) < 1e-9:
        return True
    for d in (0, 1, 2):
        if abs(round(v, d) - n) < 1e-9:
            return True
    return False


def headline_ok(text: str, facts: Sequence[HeadlineFact], labels: Sequence[str] = ()) -> bool:
    """Каждое число заголовка есть среди фактов (значение, как его пишет заголовок: целое или с одним-двумя знаками).
    По умолчанию проверка строгая — так проверяется перефразировка модели. `labels` — подписи категорий, которые
    шаблон сам поставил в заголовок («Филиал 1 даёт 50% выручки»): их цифры — часть названия, а не вывод."""
    values = [f.value for f in facts]
    return all(any(_matches(n, v) for v in values) for n in numbers_in(text, labels))


def _labels(fs: FactSet) -> list[str]:
    """Подписи и названия, которые шаблон сам ставит в заголовок: их цифры («Филиал 1», «Бюджет 2026») — не вывод."""
    c = fs.ctx
    out = list(c.get("labels") or [])
    for k in ("leader", "last_label", "growth_leader", "a_name", "b_name", "subject", "x", "y", "unit_short",
              "second_leader", "first_name", "second_name", "matrix_note", "years_range"):
        if c.get(k):
            out.append(c[k])
    out += list(c.get("names") or []) + list(c.get("parts") or []) + list(c.get("period_labels") or [])
    out += [lower_first(x) for x in out if isinstance(x, str)]
    for k in ("metric", "whole"):
        p = c.get(k)
        if isinstance(p, Phrase):
            for form in (p.nom, p.gen, p.dat, p.gen_pl, p.dat_pl, p.nom_pl):
                out += [form, lower_first(form)]
    return out


def _strongest(fs: FactSet) -> Optional[str]:
    """Запасной вывод, если шаблон не сложился: текст самого содержательного факта (доля, изменение, лидер)."""
    for kind in ("share", "change", "leader", "percentile", "median", "max"):
        f = next((x for x in fs.facts if x.kind == kind and x.text), None)
        if f is not None:
            return f.text
    return None


# ── шаблоны заголовка ─────────────────────────────────────────────────────────────────────────────────────────────────
def compose(task: TaskKind, fs: FactSet) -> tuple[str, Optional[str]]:
    """Заголовок-вывод и подпись-пояснение из фактов задачи. Факты задают и слова (ctx: лидер, период, сущность) —
    шаблон только расставляет их по-русски."""
    fn = {
        "dynamics": _dynamics, "comparison": _comparison, "shares": _shares, "distribution": _distribution,
        "reference": _reference, "kpi": _kpi, "relationship": _relationship,
    }[task]
    head, caption = fn(fs)
    head = head.strip()
    if head.endswith(".") and not re.search(r"(?:^|\s)(?:п|п\.п|чел|шт|тыс|руб|дн|мин|кв|млн|млрд|ч|г)\.$", head):
        head = head[:-1]  # точку после сокращения («+6 п.») не трогаем
    head = upper_first(head)
    labels = _labels(fs)
    if not headline_ok(head, fs.facts, labels) or head == fs.ctx.get("plain"):
        # страховка: число не из фактов или вышла тема — вывод из самого сильного факта, и только потом тема
        alt = _strongest(fs)
        if alt and headline_ok(alt, fs.facts, labels):
            head = upper_first(alt)
        elif not headline_ok(head, fs.facts, labels):
            head = fs.ctx.get("plain") or head
    if caption:
        caption = re.sub(r"(?<!\.)\.\.(?!\.)", ".", caption)  # «чел..» → «чел.»: точка сокращения и конца — одна
    return _lower_months(head), _lower_months(caption) if caption else caption


_MONTH_CAP = re.compile(r"(?<=[^\s.!?«]\s)(?:Январ|Феврал|Март|Апрел|Ма[йяе]|Июн|Июл|Август|Сентябр|Октябр|Ноябр|"
                        r"Декабр)[а-яё]*\b")


def _lower_months(text: str) -> str:
    """Месяц внутри фразы — со строчной («теплее всего — июль»), в начале предложения — как был."""
    return _MONTH_CAP.sub(lambda m_: m_.group(0).lower(), text)


def _f(fs: FactSet, fid: str) -> Optional[HeadlineFact]:
    return next((f for f in fs.facts if f.id == fid), None)


def _dynamics(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    if c.get("years"):
        return _dynamics_years(fs)
    if c.get("target_pair"):
        bt, n, tg, last = _f(fs, "below_target"), _f(fs, "periods"), _f(fs, "target"), _f(fs, "last")
        if bt is None or n is None or tg is None or last is None:
            return c.get("plain", ""), c.get("caption")
        u = c.get("unit_short")
        prep, gen = _PERIOD_PREP.get(c["target_words"][0], ("периодах", "периодов"))
        k, nn = int(bt.value), int(n.value)
        if k == 0:
            how = f"выше цели {fmt_value(tg.value, u)} во всех {nn} {prep}"
        elif k == nn:
            how = f"ниже цели {fmt_value(tg.value, u)} во всех {nn} {prep}"
        else:
            how = f"ниже цели {fmt_value(tg.value, u)} в {k} из {nn} {gen}"
        return f"{c['subject']}: {how}, в конце — {fmt_value(last.value, u)}", c.get("caption")
    if c.get("multi"):
        return _dynamics_multi(fs)
    if c.get("hourly"):
        mx, mean = _f(fs, "max"), _f(fs, "mean")
        u = c.get("unit_short")
        return (f"{c['subject']}: пик {fmt_value(mx.value, u)}, в среднем {fmt_value(mean.value, u)} в час",
                c.get("caption"))
    if c.get("comp_time"):
        return _dynamics_parts(fs)
    if c.get("dim_level"):
        moved, of, lv = _f(fs, "moved"), _f(fs, "of"), _f(fs, "leader_value")
        gen1, genp = c["dim_forms"]
        n = int(of.value)
        word = gen1 if plural(n, 1, 2, 2) == 1 else genp
        v = verb("grow" if c["up"] else "fall", c["gender"])
        head = f"{c['subject']} {v} в {int(moved.value)} из {n} {word}"
        if lv is not None:
            head += f", выше всех — {c['leader']}: {fmt_value(lv.value, c.get('unit_short'))}"
        return head, c.get("caption")
    m: Phrase = c["metric"]
    subj = c["subject"]  # «Выручка», «NPS», «Число клиентов»
    g: Gender = c["gender"]
    gap = _f(fs, "gaps")
    gap_txt = ""
    if gap is not None and int(gap.value) >= 2:  # один пропуск — в подписи, не в заголовке
        k = int(gap.value)
        pw = PERIOD_WORDS.get(c["freq"], PERIOD_WORDS["irregular"])
        if k <= 4:
            gap_txt = f", за {number_word(k, pw[3])} {plural(k, pw[0], pw[1], pw[2])} данных нет"
        else:
            gap_txt = f", за {count_words(k, pw[0], pw[1], pw[2])} данных нет"
    last = _f(fs, "last")
    change = _f(fs, "change")
    ratio = _f(fs, "ratio")
    u = c.get("unit_short")

    def hold() -> str:
        """«держится на уровне» — только у ряда в узкой полосе; иначе — размах и конец («от 0 до 1, в конце — 1»)."""
        if c.get("flat", True):
            return f"{subj} {verb('hold', g, past=False)} на уровне {fmt_value(last.value, u)}"
        mn, mx = _f(fs, "min"), _f(fs, "max")
        return f"{subj}: от {fmt_value(mn.value, u)} до {fmt_value(mx.value, u)}, в конце — {fmt_value(last.value, u)}"

    if c.get("seasonal"):
        # месяцы без года: максимум и минимум года, у температуры — сколько месяцев ниже нуля
        hi_p, lo_p = c["seasonal"]
        mn, mx = _f(fs, "min"), _f(fs, "max")
        head = f"{subj}: от {fmt_value(mn.value, u)} ({lo_p}) до {fmt_value(mx.value, u)} ({hi_p})"
        if c.get("below_zero"):
            head += f", {c['below_zero']} " + ("ниже нуля" if (u or "").startswith("°") else "в минусе")
        return head, c.get("caption")
    if c.get("peak") and last is not None:
        # уровень с пиком внутри ряда: пик — главное
        what, v, per = c["peak"]
        return f"{subj}: {what} {fmt_value(v, u)} ({per}), к концу — {fmt_value(last.value, u)}" + gap_txt, \
            c.get("caption")
    if c.get("noisy"):
        kind, v, k, du = c["noisy"]
        mn, mx = _f(fs, "min"), _f(fs, "max")
        change = _f(fs, "mean_change")
        if kind == "flat" or change is None:
            return (f"{subj}: без выраженного тренда, от {fmt_value(mn.value, u)} до {fmt_value(mx.value, u)}"
                    + gap_txt), c.get("caption")
        how = f"на {fmt_pct(change.value)}%" if kind == "pct" else f"на {fmt_value(change.value, du or None)}"
        vv = verb("grow" if v > 0 else "fall", g)
        return (f"{subj} в среднем {vv} {how}: последние {c['k_words']} к первым {k}" + gap_txt), c.get("caption")
    if c.get("level") and last is not None:
        delta = c.get("delta", 0.0)
        if abs(delta) < 1e-9 or change is None:
            head = hold()
        else:
            v = verb("grow" if delta > 0 else "fall", g)
            head = f"{subj} {v} до {fmt_value(last.value, c.get('unit_short'))}"
        return head + gap_txt, c.get("caption")
    if change is None and last is not None:
        return f"{subj} — {fmt_value(last.value, c.get('unit_short'))}" + gap_txt, c.get("caption")
    if change is None:
        return c.get("plain", subj), c.get("caption")
    when = c.get("when", "")
    if ratio is not None:
        r = ratio.value
        head = f"{subj} {verb('grow', g)} в {fmt_num(r, 1)} {times_word(r)} {when}"
    elif c.get("abs_change") and last is not None:
        if abs(c["delta"]) < 1e-9:
            head = hold()
        else:
            v = verb("grow" if c["delta"] > 0 else "fall", g)
            head = (f"{subj} {v} на {fmt_value(change.value, c.get('unit_short'))} {when}, до "
                    f"{fmt_value(last.value, c.get('unit_short'))}")
    elif abs(change.value) < 1 and last is not None:
        head = hold()
    elif re.search(r"[a-z]{3,}", subj):
        # латиница («Active users»): род неизвестен — без глагола
        head = f"{subj}: {fmt_signed(change.value if c['delta'] > 0 else -change.value, '%')} {when}"
    else:
        v = verb("grow" if c["delta"] > 0 else "fall", g)
        head = f"{subj} {v} на {fmt_pct(change.value)}% {when}"
    return " ".join(head.split()) + gap_txt, c.get("caption")


_PERIOD_PREP = {"месяц": ("месяцах", "месяцев"), "квартал": ("кварталах", "кварталов"), "неделя": ("неделях", "недель"),
                "день": ("днях", "дней")}


def _dynamics_years(fs: FactSet) -> tuple[str, Optional[str]]:
    """«2025 к 2024: +6% за январь–сентябрь, выше во всех 9 месяцах»."""
    c = fs.ctx
    y0, y1 = c["years"]
    kind, v = c["years_change"]
    ch = _f(fs, "change")
    if ch is None:
        return c.get("plain", ""), c.get("caption")
    move = fmt_signed(ch.value if v >= 0 else -ch.value, "п.п." if kind == "pp" else "%")
    head = f"{y1} к {y0}: {move}" + (f" за {c['years_range']}" if c.get("years_range") else "")
    up, n = c["years_n"]
    prep, gen = _PERIOD_PREP.get(c["years_word"][0], ("периодах", "периодов"))
    if up == n:
        head += f", выше во всех {n} {prep}"
    elif up == 0:
        head += f", ниже во всех {n} {prep}"
    else:
        head += f", выше в {up} из {n} {gen}"
    return head, c.get("caption")


def _move(kind: str, v: float, unit: Optional[str]) -> tuple[bool, str]:
    """(рост ли, «в 9,1 раза» / «на 16%» / «на 33 млн ₽»)."""
    if kind == "ratio":
        r = v if v >= 1 else 1 / v
        return v >= 1, f"в {fmt_num(round(r, 1), 1)} {times_word(round(r, 1))}"
    if kind == "pct":
        return v >= 0, f"на {fmt_pct(abs(v))}%"
    if kind == "pp":
        return v >= 0, f"на {fmt_num(round(abs(v), 1))}\u00a0п.п."
    return v >= 0, f"на {fmt_value(abs(v), unit)}"


def _signed_move(kind: str, v: float, unit: Optional[str]) -> str:
    """«+5 п.п.», «−8%», «рост в 2,1 раза», «+33 млн ₽» — изменение со знаком для формы через двоеточие."""
    if kind == "ratio":
        r = v if v >= 1 else 1 / v
        return f"{'рост' if v >= 1 else 'снижение'} в {fmt_num(round(r, 1), 1)} {times_word(round(r, 1))}"
    if kind == "pct":
        return fmt_signed(round_pct(v), "%")
    if kind == "pp":
        return fmt_signed(round(v, 1), "п.п.")
    return fmt_signed(v, unit or "")


def _dynamics_parts(fs: FactSet) -> tuple[str, Optional[str]]:
    """Части целого по времени: «Число пациентов выросло на 0,5% за 11 месяцев, а педиатрия снизилась на 15%»."""
    c = fs.ctx
    subj, g = c["subject"], c["gender"]
    u = c.get("unit_short")
    ch, last = _f(fs, "change"), _f(fs, "last")
    delta = c.get("delta", 0.0)
    if ch is None or abs(delta) < 1:
        head = f"{subj} {verb('hold', g, past=False)} на уровне {fmt_value(last.value, u)}" if last is not None else subj
    else:
        head = f"{subj} {verb('grow' if delta > 0 else 'fall', g)} на {fmt_pct(ch.value)}% {c.get('when', '')}".strip()
    mv = _f(fs, "mover")
    if mv is not None and c.get("mover"):
        nm, mp = c["mover"], c["mover_pct"]
        p = phrase(nm)
        if ch is not None and abs(delta) >= 1 and (mp > 0) == (delta > 0):
            head += f", сильнее всех — {_mid(nm)}: {fmt_signed(round_pct(mp), '%')}"
        elif p is not None and p.sure:
            head += f", а {_mid(nm)} {verb('grow' if mp > 0 else 'fall', p.gender)} на {fmt_pct(abs(mp))}%"
        else:
            head += f", {nm}: {fmt_signed(round_pct(mp), '%')}"
    return head, c.get("caption")


def _mid(name: str) -> str:
    """Название ряда внутри фразы: нарицательное — со строчной («факт», «брак»), аббревиатура и латиница — как есть."""
    p = phrase(name)
    return lower_first(name) if p is not None and p.sure else name


def _dynamics_multi(fs: FactSet) -> tuple[str, Optional[str]]:
    """«Scopus вырос в 9,1 раза за 20 лет, РИНЦ — в 3,4 раза»."""
    c = fs.ctx
    names = c["names"]
    unit = c.get("unit_short")
    parts = []
    up0 = None
    if any(is_period_name(nm) or is_event_name(nm) or (phrase(nm) is not None and not phrase(nm).sure
                                                       and re.search(r"[а-яё]", nm, re.I)) for nm in names[:2]):
        # ряды-номера («Неделя 1», «Неделя 2»): подлежащим их не делают — через двоеточие
        for k, name in enumerate(names[:2]):
            kind, v = c[f"s{k}"]
            parts.append(f"{name if k == 0 else _mid(name)}: {_signed_move(kind, v, unit)}"
                         + (f" {c.get('when', '')}" if k == 0 else ""))
        return ", ".join(p_.strip() for p_ in parts), c.get("caption")
    for k, name in enumerate(names[:2]):
        kind, v = c[f"s{k}"]
        up, how = _move(kind, v, unit)
        p = phrase(name)
        g: Gender = p.gender if p is not None else "m"
        if k == 0:
            up0 = up
            parts.append(f"{name} {verb('grow' if up else 'fall', g)} {how} {c.get('when', '')}".strip())
        elif up == up0:
            parts.append(f"{_mid(name)} — {how}")
        else:
            parts.append(f"а {_mid(name)} {verb('grow' if up else 'fall', g)} {how}")
    return ", ".join(parts), c.get("caption")


def _comparison(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    if c.get("funnel"):
        conv, first, last = _f(fs, "conversion"), _f(fs, "first"), _f(fs, "last")
        if conv is None or first is None or last is None:
            return c.get("plain", ""), c.get("caption")
        return (f"До этапа «{c['last']}» доходит {fmt_pct_any(conv.value)}% от этапа «{c['first']}»: "
                f"{fmt_num(last.value)} из {fmt_num(first.value)}"), c.get("caption")
    if c.get("plan_fact"):
        ex, fa, pl = _f(fs, "execution"), _f(fs, "fact_total"), _f(fs, "plan_total")
        if ex is None or fa is None or pl is None:
            return c.get("plain", ""), c.get("caption")
        word = c.get("plan_word", "План")
        done = "выполнен" if word == "Норматив" else "исполнен"
        return (f"{word} {done} на {fmt_num(ex.value, 0 if float(ex.value).is_integer() else 1)}%: {fmt_num(fa.value)} "
                f"из {fmt_value(pl.value, c.get('unit_short'))}"), c.get("caption")
    if c.get("constant"):
        v, n = _f(fs, "constant"), _f(fs, "count")
        k = int(n.value)
        if abs(v.value) < 1e-12 and c.get("metric_gen") and c.get("dim_gen"):
            return f"{upper_first(c['metric_gen'])} нет ни в одном из {fmt_num(k)} {c['dim_gen']}", c.get("caption")
        return (f"У всех {count_words(k, *c['dim_forms'])} одно значение: {fmt_value(v.value, c.get('unit_short'))}",
                c.get("caption"))
    leader = c["leader"]
    pl = "pl" if c.get("lead_plural") or is_plural_value(leader) else "m"
    share = _f(fs, "leader_share")
    grow_leader = c.get("growth_leader")
    m: Optional[Phrase] = c.get("metric")
    if share is not None and m is not None:
        # «даёт» — про выручку и доход; расходы, люди, штуки — просто доля: «Продажи — 38% сотрудников»
        if c.get("gives"):
            head = f"{leader} {verb('give', pl, past=False)} {fmt_pct(share.value)}% {m.low.gen}"
        else:
            head = f"{leader} — {fmt_pct(share.value)}% {m.low.gen}"
        lv, total = _f(fs, "leader_value"), _f(fs, "total")
        if not grow_leader and lv is not None and total is not None:
            head += f": {fmt_num(lv.value)} из {fmt_value(total.value, c.get('unit_short'))}"
    elif _f(fs, "leader_value") is not None:
        lv = _f(fs, "leader_value")
        u = c.get("unit_short")
        last = _f(fs, "last_value")
        w = c.get("wording", "lead")
        top_w, low_w = {"temp": ("Теплее всего", "холоднее всего"), "price": ("Дороже всего", "дешевле всего"),
                        "most": ("Больше всего", "меньше всего"), "slow": ("Медленнее всего", "быстрее всего"),
                        "long": ("Дольше всего", "быстрее всего"), "delay": ("Дольше всего", "меньше всего"),
                        "rate": ("Выше всего", "ниже всего")}.get(w, (None, None))
        second = _f(fs, "second_value")
        if w == "most" and second is not None and c.get("second_leader"):
            # две величины рядом по порядковым группам: у каждой своя самая большая группа
            head = (f"{c['first_name']}: больше всего — {leader} ({fmt_value(lv.value, u)}), "
                    f"{_mid(c['second_name'])}: {c['second_leader']} ({fmt_value(second.value, u)})")
        elif top_w:
            head = f"{top_w} — {leader}: {fmt_value(lv.value, u)}" + (f" ({c['matrix_note']})" if c.get("matrix_note")
                                                                       else "")
            if last is not None and c.get("last_label"):
                head += f", {low_w} — {c['last_label']}: {fmt_value(last.value, u)}"
        else:
            by = f" по {c['by_metric']}" if c.get("by_metric") else ""
            # «растёт быстрее всех» — рядом с тем, кто растёт, а не после последнего в списке
            fast = f" и {verb('grow', pl, past=False)} быстрее всех" if grow_leader and grow_leader == leader else ""
            # изменение («Δ к 2024, %») — со знаком: «+12,6%», «−3,4%»
            val = (lambda v_: ("+" if v_ > 0 else "−" if v_ < 0 else "") + fmt_value(abs(v_), u)) if c.get("signed") \
                else (lambda v_: fmt_value(v_, u))
            head = f"{leader} впереди{fast}{by}: {val(lv.value)}" + (
                f" ({c['matrix_note']})" if c.get("matrix_note") else "")
            if fast:
                grow_leader = None
            if last is not None and c.get("last_label"):
                head += f", {c['last_label']} — {val(last.value)}"
    else:
        head = c.get("plain", leader)
    if grow_leader:
        gpl = "pl" if is_plural_value(grow_leader) else "m"
        if grow_leader == leader and share is not None and m is not None:
            head += f" и {verb('grow', pl, past=False)} быстрее всех"  # «Арбат даёт 25% выручки и растёт быстрее всех»
        elif grow_leader == leader:
            # лидер растёт быстрее всех, а в конце фразы — последний: имя повторено («…, быстрее всех растёт Арбат»)
            head += f", быстрее всех {verb('grow', gpl, past=False)} {grow_leader}"
        else:
            head += f", {grow_leader} {verb('grow', gpl, past=False)} быстрее всех"
    neg = _f(fs, "negatives")
    if neg is not None and not grow_leader:
        forms = c.get("neg_forms") or ("категория", "категории", "категорий")
        head += (", все " if c.get("neg_all") and int(neg.value) > 1 else ", ") + \
            f"{count_words(int(neg.value), *forms)} в минусе"
    return head, c.get("caption")


def _shares(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    if c.get("composition"):
        p0, p1 = _f(fs, "part_0"), _f(fs, "part_1")
        parts = c.get("parts") or []
        whole: Optional[Phrase] = c.get("whole")
        if p0 is None or len(parts) < 2 or p1 is None:
            return c.get("plain", ""), c.get("caption")
        w = f" {whole.low.gen}" if whole is not None else ""
        if c.get("rows_dat"):
            # ответы по шкале: доли — средние по строкам, и это сказано
            return (f"В среднем по {c['rows_dat']}: {lower_first(parts[0])} — {fmt_pct(p0.value)}%, "
                    f"{lower_first(parts[1])} — {fmt_pct(p1.value)}%"), c.get("caption")
        return f"{parts[0]} — {fmt_pct(p0.value)}%{w}, {lower_first(parts[1])} — {fmt_pct(p1.value)}%", c.get("caption")
    leader = c["leader"]
    pl = "pl" if is_plural_value(leader) else "m"
    share = _f(fs, "leader_share")
    whole: Optional[Phrase] = c.get("whole")
    if share is None:
        return c.get("plain", leader), c.get("caption")
    p = share.value
    words = fraction_words(p)
    v = verb("bring" if c.get("money") else "give", pl, past=False)
    if whole is not None and not c.get("gives"):
        # расходы, люди, штуки — доля без «приносит»: «Фонд оплаты труда — две трети расходов: 66%»
        wn = fraction_words(p, "nom")
        return (f"{leader} — {wn} {whole.low.gen}: {fmt_pct(p)}%" if wn else
                f"{leader} — {fmt_pct(p)}% {whole.low.gen}"), c.get("caption")
    if whole is not None:
        if words:
            head = f"{leader} {v} {words} {whole.low.gen} — {fmt_pct(p)}%"
        else:
            head = f"{leader} {v} {fmt_pct(p)}% {whole.low.gen}"
    else:
        head = f"{leader} — крупнейшая доля: {fmt_pct(p)}%"
    return head, c.get("caption")


def _distribution(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    if c.get("freq"):
        mc, tot, sh = _f(fs, "mode_count"), _f(fs, "total"), _f(fs, "mode_share")
        if mc is None or tot is None or sh is None:
            return c.get("plain", ""), c.get("caption")
        each = "по " if "и" in c["modes"].split() else ""
        return (f"Чаще всего — {c['vname']} {c['modes']}: {each}{fmt_num(mc.value)} {c['who']} из {fmt_num(tot.value)}, "
                f"{fmt_pct(sh.value)}%"), c.get("caption")
    ent = c.get("entities_gen")  # «обращений»
    if c.get("constant"):
        nom = c.get("entities_nom_pl")
        who = f"{'Все' if c['constant'] == 'all' else 'Почти все'} {lower_first(nom) if nom else 'значения'}"
        return f"{who} — {c['median_text']}", c.get("caption")
    share = _f(fs, "share_within")
    if c.get("skewed") and c.get("median_text"):
        # скошенные данные: вывод — медиана, среднее завышают крупные значения
        who = f"Половина {ent}" if ent else "Половина значений"
        return f"{who} — до {c['median_text']}, а крупные значения поднимают среднее до {c['mean_text']}", \
            c.get("caption")
    if share is None:
        return (f"Медиана — {c['median_text']}" if c.get("median_text") else c.get("plain", "")), c.get("caption")
    p = share.value
    who = f"{fmt_pct(p)}% {ent or 'значений'}"
    if c.get("duration") and ent and c.get("predicate"):
        head = f"{who} {c['predicate']} {c['threshold_text']}"
    elif c.get("duration"):
        head = f"{who} — не дольше {c['threshold_text']}"
    else:
        head = f"{who} — не больше {c['threshold_text']}"
    return head, c.get("caption")


def _reference(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    top = _f(fs, "top_share")
    n_top = _f(fs, "top_n")
    m: Optional[Phrase] = c.get("metric")
    if top is not None and n_top is not None and m is not None:
        ent = c.get("entities_gen")
        who = f"Топ-{int(n_top.value)} {ent}" if ent else f"{int(n_top.value)} крупнейших"
        return f"{who} {verb('give', 'pl', past=False)} {fmt_pct(top.value)}% {m.low.gen}", c.get("caption")
    lv = _f(fs, "leader_value")
    ties = _f(fs, "ties")
    if lv is not None and ties is not None:
        # ничья наверху: «8 клиентов — по 75», а не «первое место» строки, которая оказалась первой
        forms = c.get("entity_forms") or ("строка", "строки", "строк")
        who = upper_first(count_words(int(ties.value), *forms))
        v = fmt_value(lv.value, c.get("unit_short"))
        if c.get("duration"):
            return f"{who} — дольше всех: по {v}", c.get("caption")
        col = f" «{c['column']}»" if c.get("column") else ""
        return f"{who} — по {v}: наибольшее значение{col}", c.get("caption")
    if lv is not None and not c.get("leader") and m is not None:
        return f"{m.nom}: наибольшее значение — {fmt_value(lv.value, c.get('unit_short'))}", c.get("caption")
    if lv is not None and c.get("leader"):
        by = f"по {m.low.dat}" if m is not None else "по значению"
        head = f"{c['leader']} — первое место {by}: {fmt_value(lv.value, c.get('unit_short'))}"
        if c.get("duration"):
            head = f"{c['leader']} — дольше всех: {fmt_value(lv.value, c.get('unit_short'))}"
        neg = _f(fs, "negatives")
        if neg is not None:
            forms = c.get("entity_forms") or ("строка", "строки", "строк")
            head += f", {count_words(int(neg.value), *forms)} в минусе"
        return head, c.get("caption")
    count = _f(fs, "count")
    if count is not None:
        forms = c.get("entity_forms") or ("строка", "строки", "строк")
        head = count_words(int(count.value), *forms)
        groups = _f(fs, "groups")
        if groups is not None and c.get("group_forms"):
            gn = int(groups.value)
            gf = c["group_forms"]
            head += f" из {fmt_num(gn)} {gf[0] if plural(gn, 1, 2, 3) == 1 else gf[1]}"
        return head, c.get("caption")
    return c.get("plain", ""), c.get("caption")


def _kpi(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    a, b = _f(fs, "kpi_a"), _f(fs, "kpi_b")
    a_name: str = c.get("a_name", "")
    if a is not None and b is not None:
        ga: Gender = c.get("a_gender", "m")
        b_gen = c.get("b_gen")
        sa = fmt_signed(c["a_signed"], c.get("a_unit") or "")
        sb = fmt_signed(c["b_signed"], c.get("b_unit") or "")
        if c.get("a_participle") or c.get("b_participle"):
            # «Принято на 1 курс: +6%, отчислено студентов: −8%» — с причастием не говорят «принято выросло»
            return f"{a_name}: {sa}, {lower_first(c.get('b_name', ''))}: {sb}", c.get("caption")
        if c["a_signed"] > 0 and c["b_signed"] > 0 and b_gen:
            cmp_word = "быстрее" if c["a_signed"] > c["b_signed"] else "медленнее" if c["a_signed"] < c["b_signed"] else None
            if cmp_word:
                return f"{a_name} {verb('grow', ga, past=False)} {cmp_word} {b_gen}: {sa} против {sb}", c.get("caption")
        if c["a_signed"] > 0 > c["b_signed"]:
            gb: Gender = c.get("b_gender", "m")
            return (f"{a_name} {verb('grow', ga, past=False)}, а {lower_first(c.get('b_name', ''))} "
                    f"{verb('fall', gb, past=False)}: {sa} и {sb}"), c.get("caption")
        return f"{a_name}: {sa}, {lower_first(c.get('b_name', ''))}: {sb}", c.get("caption")
    if a is not None and c.get("a_participle"):
        return f"{a_name}: {fmt_signed(c['a_signed'], c.get('a_unit') or '')}", c.get("caption")
    if a is not None:
        ga = c.get("a_gender", "m")
        v = verb("grow" if c["a_signed"] > 0 else "fall", ga)
        return f"{a_name} {v} на {fmt_pct(abs(c['a_signed']))}%" if c.get("a_unit") == "%" else \
            f"{a_name}: {fmt_signed(c['a_signed'], c.get('a_unit') or '')}", c.get("caption")
    val = _f(fs, "kpi_value")
    if val is not None:
        return f"{a_name} — {c.get('a_value_text')}", c.get("caption")
    return c.get("plain", ""), c.get("caption")


def _relationship(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    r = _f(fs, "r")
    if r is None:
        return c.get("plain", ""), c.get("caption")
    x, y = c["x"], c["y"]
    rv = c["r_signed"]
    rt = fmt_num(rv, 2)
    xn = f"число {lower_first(x)}" if c.get("x_counter") else lower_first(x)
    yn = f"число {lower_first(y)}" if c.get("y_counter") else lower_first(y)
    if abs(rv) < 0.3:
        return f"{upper_first(xn)} и {yn} почти не связаны: r = {rt}", c.get("caption")
    # счётчик — «чем больше сделок», величина — «чем выше цена»
    more = f"больше {lower_first(x)}" if c.get("x_counter") else f"выше {lower_first(x)}"
    if c.get("y_counter"):
        other = f"{'больше' if rv > 0 else 'меньше'} {lower_first(y)}"
    else:
        other = f"{'выше' if rv > 0 else 'ниже'} {lower_first(y)}"
    slope = c.get("slope")
    if slope is not None and _f(fs, "slope") is not None:
        yu = _f(fs, "slope").unit
        b = fmt_signed(slope) + (f"\u00a0{yu}" if yu and yu != "%" else "%" if yu == "%" else "")
        if c.get("each") and c.get("x_gen") and c.get("y_dat"):
            # «Каждый час подготовки в неделю — около +1,9 к среднему баллу ЕГЭ»
            each, per = c["each"]
            return f"{upper_first(each)} {c['x_gen']}{' ' + per if per else ''} — около {b} к {c['y_dat']}", \
                c.get("caption")
        return f"Чем {more}, тем {other}: около {b} на единицу, r = {rt}", c.get("caption")
    strength = "" if abs(rv) >= 0.7 else ", но связь умеренная"
    if _f(fs, "slope") is None:
        # без естественной причины — не «каждый X даёт Y», а только связь
        return f"{upper_first(xn)} и {yn} связаны{strength}: r = {rt}", c.get("caption")
    return f"Чем {more}, тем {other}{strength}: r = {rt}", c.get("caption")
